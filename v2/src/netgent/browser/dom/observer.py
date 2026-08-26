"""DOM observation: walk every frame of the page (same- and cross-origin) into a `DomSnapshot`.

Compile-time only — the observation feeds the explore agent; replay never calls it.
"""

from netgent.browser.dom.closed_shadow import ClosedShadowObserver
from netgent.browser.dom.models import DomElement, DomSnapshot, TextBlock
from netgent.browser.dom.scripts import DOM_SNAPSHOT_JS, FRAME_CONTENT_ORIGIN_JS, FRAME_SELECTOR_JS
from netgent.browser.pw import Frame, Page
from netgent.core.logger import get_logger

logger = get_logger(__name__)


class DomObserver:
    """Snapshots interactive elements + text across all frames, joining closed shadow roots
    observed over CDP (`closed_shadow` is None under plain Playwright or without a CDP session)."""

    def __init__(self, page: Page, closed_shadow: ClosedShadowObserver | None = None):
        self._page = page
        self._closed_shadow = closed_shadow

    async def _frame_info(
        self, frame: Frame, cache: dict[Frame, tuple[list[str], float, float]] | None = None
    ) -> tuple[list[str], float, float]:
        """(iframe CSS-selector chain, top-viewport X offset, top-viewport Y offset) for a frame.

        Computed in each parent frame's context, so it works for cross-origin frames too
        (Playwright reaches them via CDP). The offsets place the frame's CONTENT origin in
        the top viewport: per hop, the iframe's border-box left/top plus its border and
        padding — Puppeteer's #getTopLeftCornerOfFrame (puppeteer-core
        api/ElementHandle.ts:1380-1415), which is what Playwright's bounding_box() reports
        against. `cache` memoizes ancestors within one snapshot (O(frames) round trips
        instead of O(depth²)).
        """
        if cache is None:
            cache = {}
        if frame in cache:
            return cache[frame]
        parent = frame.parent_frame
        if parent is None:
            cache[frame] = ([], 0.0, 0.0)
            return cache[frame]
        parent_path, px, py = await self._frame_info(parent, cache)
        handle = await frame.frame_element()
        selector = await parent.evaluate(FRAME_SELECTOR_JS, handle)
        left, top = await parent.evaluate(FRAME_CONTENT_ORIGIN_JS, handle)
        cache[frame] = (parent_path + [selector], px + left, py + top)
        return cache[frame]

    async def snapshot(self) -> DomSnapshot:
        """Observe interactive elements + text across ALL frames (same- and cross-origin).

        The DOM walk runs inside each frame's own context (Playwright evaluates it there
        via CDP, bypassing the same-origin policy that limits in-page contentDocument access),
        in an ISOLATED world — the page's own JavaScript never sees it. Frames containing a
        closed shadow root are walked over CDP instead (same walker, same world kind, plus the
        closed roots as handles) and joined here by their frame path (dom/closed_shadow.py).
        Element bboxes are normalized to TOP-viewport coordinates (both axes) so the
        observation can be paged by scroll position and matched against bounding_box().
        """
        page = self._page
        elements: list[DomElement] = []
        texts: list[TextBlock] = []
        skipped: list[str] = []
        viewport_height = await page.evaluate("() => window.innerHeight")
        closed: dict[tuple[str, ...], dict] = {}
        if self._closed_shadow is not None:
            closed = await self._closed_shadow.observe()
        frame_cache: dict[Frame, tuple[list[str], float, float]] = {}
        for frame in page.frames:
            try:
                frame_path, offset_x, offset_y = await self._frame_info(frame, frame_cache)
                if tuple(frame_path) in closed:
                    raw = closed[tuple(frame_path)]
                else:
                    raw = await frame.evaluate(DOM_SNAPSHOT_JS)
            except Exception as exc:  # noqa: BLE001 — a detached/unreachable frame is skipped, not fatal
                # Ad/analytics iframes attach and detach constantly; the top frame must never
                # be lost to one. Skip it, but say so (browser-use #4778 lost whole observations
                # to this until they logged and kept going; dom/service.py:376-398).
                reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                logger.warning("snapshot: skipping frame %s: %s", frame.url, reason)
                skipped.append(f"{frame.url}: {reason}")
                continue
            for element in raw["elements"]:
                element["framePath"] = frame_path
                # normalize to top-viewport coordinates (both axes — R6)
                element["bbox"]["x"] += round(offset_x)
                element["bbox"]["y"] += round(offset_y)
                elements.append(DomElement.model_validate(element))
            for t in raw["texts"]:
                t["frame_path"] = frame_path
                texts.append(TextBlock.model_validate(t))
        return DomSnapshot(
            url=page.url,
            title=await page.title(),
            elements=elements,
            texts=texts,
            viewport_height=int(viewport_height),
            frames_skipped=len(skipped),
            skipped_frames=skipped,
        )
