"""Minimal Playwright session: launch, dispatch actions, evaluate state conditions.

This is the v0 of the browser layer — locator chains replay via whitelist reflection,
triggers are evaluated on a polling loop. Capture (HAR/tracing) hooks in at context
creation here when the capture subsystem lands (docs/browser-layer-design.md §4).
"""

import asyncio
import re
import time
from pathlib import Path

try:  # Patchright: a patched Playwright that closes the CDP-level leaks (Runtime.enable,
    # Console.enable, automation flags). Same API, so it is a drop-in when installed.
    from patchright.async_api import (
        Browser,
        BrowserContext,
        Frame,
        FrameLocator,
        Locator,
        Page,
        Playwright,
        async_playwright,
    )

    PATCHED_BROWSER = True
except ImportError:  # pragma: no cover — plain Playwright fallback
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Frame,
        FrameLocator,
        Locator,
        Page,
        Playwright,
        async_playwright,
    )

    PATCHED_BROWSER = False

from netgent.browser.closed_shadow import ClosedShadowObserver
from netgent.browser.dom.snapshot import (
    DOM_SNAPSHOT_JS,
    FRAME_CONTENT_ORIGIN_JS,
    FRAME_SELECTOR_JS,
    DomElement,
    DomSnapshot,
    TextBlock,
)
from netgent.browser.profile import BrowserProfile, user_agent_metadata
from netgent.core.errors import ActionDispatchError, LocatorResolutionError, TriggerTimeoutError
from netgent.core.logger import get_logger
from netgent.schema.actions import (
    Action,
    ClickAction,
    FillAction,
    GoBackAction,
    GotoAction,
    HoverAction,
    NoopAction,
    PressAction,
    ScrollAction,
    SelectAction,
    UploadFileAction,
    WaitAction,
)
from netgent.schema.actions import Locator as LocatorChain
from netgent.schema.control import ParamSource
from netgent.schema.triggers import SelectorHidden, SelectorVisible, TitleContains, Trigger, UrlMatches
from netgent.schema.workflow import State

POLL_INTERVAL_S = 0.1
logger = get_logger(__name__)


# browser.version per channel, so the headless UA flag needs only one extra launch per process.
_VERSION_CACHE: dict[str | None, str] = {}


class BrowserSession:
    def __init__(self, headless: bool = True, profile: BrowserProfile | None = None):
        self._headless = headless
        self._profile = profile or BrowserProfile.default()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._cdp = None  # CDP session: closed-shadow observation (Patchright) + headless client-hints repair
        self._closed_shadow: ClosedShadowObserver | None = None

    async def _browser_version(self) -> str:
        """The channel's real version, via a throwaway launch (memoized per process)."""
        channel = self._profile.channel
        if channel not in _VERSION_CACHE:
            kwargs = self._profile.launch_kwargs(headless=True)
            try:
                browser = await self._playwright.chromium.launch(**kwargs)
            except Exception:  # noqa: BLE001 — channel not installed: fall back to bundled Chromium
                if "channel" not in kwargs:
                    raise
                kwargs.pop("channel")
                browser = await self._playwright.chromium.launch(**kwargs)
            _VERSION_CACHE[channel] = browser.version
            await browser.close()
        return _VERSION_CACHE[channel]

    async def __aenter__(self) -> "BrowserSession":
        self._playwright = await async_playwright().start()
        profile = self._profile
        # Headless Chrome stamps "HeadlessChrome/<ver>" into its UA. Only the LAUNCH flag
        # reaches ServiceWorkers/SharedWorkers (the context option leaves them leaking); the
        # real version keeps the UA in step with the binary.
        user_agent = profile.headless_user_agent(await self._browser_version()) if self._headless else None
        launch_kwargs = profile.launch_kwargs(self._headless, user_agent)
        try:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        except Exception:  # noqa: BLE001 — e.g. channel="chrome" but Chrome isn't installed
            if "channel" not in launch_kwargs:
                raise
            launch_kwargs.pop("channel")
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(**profile.context_kwargs(self._headless))
        self._page = await self._context.new_page()
        try:
            self._cdp = await self._context.new_cdp_session(self._page)
        except Exception as exc:  # noqa: BLE001 — everything below is best-effort
            logger.warning("CDP session unavailable: %s", exc)
            self._cdp = None
        # Closed-shadow observation (R8) is read from OUTSIDE the page over CDP — no init
        # script, no prototype patch, no global: page JS cannot tell (browser/closed_shadow.py).
        # Patchright only — closed roots can only be ACTED on through Patchright's CDP pierce,
        # so observing them under plain Playwright would surface elements the replayer could
        # never drive. Cross-origin frames work because every frame is read through its own
        # target's session (an init script via add_init_script would break them — measured).
        if PATCHED_BROWSER and self._cdp is not None:
            self._closed_shadow = ClosedShadowObserver(self._page, self._cdp, DOM_SNAPSHOT_JS, FRAME_SELECTOR_JS)
        if user_agent and self._cdp is not None:
            await self._repair_client_hints(user_agent)
        return self

    async def _repair_client_hints(self, user_agent: str) -> None:
        """The --user-agent flag empties the high-entropy client hints (architecture,
        platformVersion, fullVersionList) on the page. Re-issue the UA over CDP with a complete
        userAgentMetadata: the browser's own brands/platform (read from a routed https page —
        userAgentData needs a secure context) plus the host's real architecture and OS version.
        Measured byte-identical to real headed Chrome on headers, page and both worker types."""
        probe_url = "https://netgent.invalid/client-hints"
        try:
            await self._page.route(
                probe_url, lambda route: route.fulfill(status=200, body="", content_type="text/html")
            )
            await self._page.goto(probe_url)
            hints = await self._page.evaluate(
                "() => navigator.userAgentData ? {brands: navigator.userAgentData.brands, "
                "platform: navigator.userAgentData.platform} : null"
            )
            await self._page.unroute(probe_url)
            await self._page.goto("about:blank")
            if not hints:
                return
            metadata = user_agent_metadata(self._browser.version, hints["brands"], hints["platform"])
            await self._cdp.send(
                "Emulation.setUserAgentOverride", {"userAgent": user_agent, "userAgentMetadata": metadata}
            )
        except Exception as exc:  # noqa: BLE001 — a headless UA with empty hints beats a crash
            logger.warning("client-hints repair skipped: %s", exc)

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
        closed roots as handles) and joined here by their frame path (browser/closed_shadow.py).
        Element bboxes are normalized to TOP-viewport coordinates (both axes) so the
        observation can be paged by scroll position and matched against bounding_box().
        """
        elements: list[DomElement] = []
        texts: list[TextBlock] = []
        skipped: list[str] = []
        viewport_height = await self.page.evaluate("() => window.innerHeight")
        closed: dict[tuple[str, ...], dict] = {}
        if self._closed_shadow is not None:
            closed = await self._closed_shadow.observe()
        frame_cache: dict[Frame, tuple[list[str], float, float]] = {}
        for frame in self.page.frames:
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
            url=self.page.url,
            title=await self.page.title(),
            elements=elements,
            texts=texts,
            viewport_height=int(viewport_height),
            frames_skipped=len(skipped),
            skipped_frames=skipped,
        )

    async def __aexit__(self, *exc_info: object) -> None:
        if self._cdp is not None:
            try:
                await self._cdp.detach()
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("session not started — use `async with BrowserSession(...)`")
        return self._page

    def _resolve(self, chain: LocatorChain) -> Locator:
        """Replay a stored chain by whitelist reflection; the result is always a Locator.

        The schema already type-checks the receiver sequence (`validate_locator_chain`);
        this is the runtime backstop, so a chain ending on a FrameLocator (no fill/click)
        or on the Page is a LocatorResolutionError, never an AttributeError from dispatch.
        """
        target: Page | Locator | FrameLocator = self.page
        for i, step in enumerate(chain):
            fn = getattr(target, step.fn, None)
            if fn is None:
                raise LocatorResolutionError(
                    f"step {i} ({step.fn!r}) is not available on a {type(target).__name__}"
                )
            try:
                target = fn(*step.args, **step.kwargs)
            except Exception as exc:
                raise LocatorResolutionError(f"step {i} ({step.fn!r}) failed: {exc}") from exc
        if not isinstance(target, Locator):
            raise LocatorResolutionError(
                "empty locator chain" if isinstance(target, Page)
                else f"locator chain ends on a {type(target).__name__}, not an element locator"
            )
        return target

    async def count(self, chain: LocatorChain) -> int:
        """How many elements a chain resolves to right now (0 = nothing, >1 = ambiguous).

        A compile-time hook: the explore agent verifies every captured chain resolves to
        exactly one element before storing it (Skyvern's `count() == 1` discipline,
        `skyvern/webeye/utils/dom.py`), so replay never sees a strict-mode violation.
        """
        return await self._resolve(chain).count()

    async def match_index(self, chain: LocatorChain, x: float, y: float, limit: int = 50) -> int:
        """Index (for an `nth` step) of the chain's match whose box is nearest (x, y).

        (x, y) are top-viewport coordinates, the same space Playwright's bounding_box()
        reports in — so this works for in-frame elements too.
        """
        locator = self._resolve(chain)
        n = min(await locator.count(), limit)
        best, best_d = 0, float("inf")
        for i in range(n):
            try:
                box = await locator.nth(i).bounding_box(timeout=1000)
            except Exception:  # noqa: BLE001 — a detached match is simply not the one
                box = None
            if box is None:
                continue
            d = (box["x"] - x) ** 2 + (box["y"] - y) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    async def normalize(self, chain: LocatorChain) -> str:
        """Playwright's own selector for the element `chain` resolves to (Locator.normalize()).

        Server side this is Frame.resolveSelector (playwright-core server/frames.ts:1312-1339):
        resolve, generate a selector for the element, then one per ancestor <iframe>, joined
        by `>> internal:control=enter-frame >>`. The string is in Playwright's private
        `internal:` syntax and is only ever parsed back into our whitelist at compile time
        (agent/explore_agent/normalized.py); it never reaches an artifact.
        """
        normalized = await self._resolve(chain).normalize()
        return normalized._impl_obj._selector

    async def same_element(self, a: LocatorChain, b: LocatorChain) -> bool:
        """Do two chains resolve to the very same element node right now?"""
        try:
            ha = await self._resolve(a).element_handle(timeout=2000)
            hb = await self._resolve(b).element_handle(timeout=2000)
            return bool(await ha.evaluate("(x, y) => x === y", hb))
        except Exception:  # noqa: BLE001 — different frames / unresolvable → not the same
            return False

    async def _click(self, locator: Locator, timeout_ms: int) -> None:
        """Click, with checkbox/radio handling folded in (keyed on the live element).

        A checkbox toggles; a radio selects. First try Playwright's set_checked/check
        (label-aware, verified). If the state still didn't change — the tell of a custom
        control whose real <input> is hidden behind a styled label — fall back to clicking
        the associated label in JS, which fires the framework's own handler.
        """
        # Target the first match — real sites often resolve a locator to several elements,
        # and get_attribute/click are strict (they throw on multi-match).
        first = locator.first
        try:
            kind = (await first.get_attribute("type")) or (await first.get_attribute("role"))
        except Exception:  # noqa: BLE001 — attribute probe must never break the click
            kind = None
        if kind not in ("checkbox", "radio"):
            await first.click(timeout=timeout_ms)
            return

        target = True if kind == "radio" else not await first.is_checked()
        try:
            await first.set_checked(target, timeout=timeout_ms)
        except Exception:  # noqa: BLE001 — custom controls make set_checked time out; try the fallback
            pass
        if await first.is_checked() != target:
            # Custom radio/checkbox: click the label (or the input) in the element's own
            # context — this fires framework listeners a synthetic input click misses.
            await first.evaluate("el => (el.labels && el.labels[0] ? el.labels[0] : el).click()")

    async def _scroll(self, action: ScrollAction) -> None:
        """Wheel-scroll whatever is under the cursor: the top frame by default, or the frame /
        inner scroller holding `action.locator` (mouse moved to its box centre first — the
        mechanic lumen and magnitude rely on). The page-to-pixel conversion uses that
        element's own window height, so 'one page' means one page of the frame it lives in.
        """
        viewport = await self.page.evaluate("() => window.innerHeight")
        if action.locator is not None:
            locator = self._resolve(action.locator)
            box = await locator.bounding_box(timeout=action.timeout_ms)
            if box is None:
                raise ActionDispatchError("scroll target has no bounding box (hidden or detached)")
            await self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            viewport = await locator.evaluate("el => el.ownerDocument.defaultView.innerHeight")
        else:
            # Park the cursor at the origin so an earlier anchored scroll cannot leave it over
            # an iframe / inner scroller: an unanchored scroll always means the top frame.
            await self.page.mouse.move(0, 0)
        pixels = int(action.pages * viewport) * (1 if action.down else -1)
        await self.page.mouse.wheel(0, pixels)

    async def dispatch(self, action: Action) -> None:
        if getattr(action, "requires_closed_shadow", False) and not PATCHED_BROWSER:
            # The capability flag a plain-Playwright replayer refuses on (R8): the target is
            # inside a closed shadow root, which only Patchright's CDP pierce can resolve.
            raise ActionDispatchError(
                "action requires a closed-shadow-piercing engine (Patchright); this replayer cannot resolve it"
            )
        try:
            match action:
                case GotoAction():
                    await self.page.goto(action.url, timeout=action.timeout_ms)
                case ClickAction():
                    await self._click(self._resolve(action.locator), action.timeout_ms)
                case FillAction():
                    await self._resolve(action.locator).fill(action.text, timeout=action.timeout_ms)
                case PressAction():
                    if action.locator is not None:
                        await self._resolve(action.locator).press(action.keys, timeout=action.timeout_ms)
                    else:
                        await self.page.keyboard.press(action.keys)
                case SelectAction():
                    await self._resolve(action.locator).select_option(action.value, timeout=action.timeout_ms)
                case ScrollAction():
                    await self._scroll(action)
                case UploadFileAction():
                    await self._resolve(action.locator).set_input_files(action.paths, timeout=action.timeout_ms)
                case GoBackAction():
                    await self.page.go_back(timeout=action.timeout_ms)
                case WaitAction():
                    await self.page.wait_for_timeout(action.seconds * 1000)
                case HoverAction():
                    await self._resolve(action.locator).hover(timeout=action.timeout_ms)
                case NoopAction():
                    pass
                case _:
                    raise ActionDispatchError(f"unhandled action type {type(action).__name__}")
        except (ActionDispatchError, LocatorResolutionError):
            raise
        except Exception as exc:
            raise ActionDispatchError(f"{action.type} failed: {exc}") from exc

    def _frame_scope(self, frame_path: list[str]) -> Page | FrameLocator:
        """The receiver a CSS selector is queried on: the page, or the frame_locator chain
        for `frame_path` — the same chain `_resolve` builds from a locator's frame steps,
        so triggers and parameter sources see exactly the frames actions do."""
        scope: Page | FrameLocator = self.page
        for selector in frame_path:
            scope = scope.frame_locator(selector)
        return scope

    async def _holds(self, trigger: Trigger) -> bool:
        match trigger:
            case UrlMatches():
                return re.search(trigger.pattern, self.page.url) is not None
            case TitleContains():
                return trigger.text in await self.page.title()
            case SelectorVisible():
                locator = self._frame_scope(trigger.frame_path).locator(trigger.selector)
                return await locator.first.is_visible()
            case SelectorHidden():
                # Resolved-and-hidden only: a selector matching nothing must not hold, or a
                # typo'd selector would "recognize" every state (research doc, R2).
                locator = self._frame_scope(trigger.frame_path).locator(trigger.selector)
                if await locator.count() == 0:
                    return False
                return not await locator.first.is_visible()
        return False

    async def extract_value(self, source: "ParamSource", timeout_ms: int = 5000) -> str | None:
        """Read a dynamic parameter's value from the live page (returns None if unavailable)."""
        try:
            if source.kind == "url_group":
                if not source.pattern:
                    return None
                match = re.search(source.pattern, self.page.url)
                return match.group(source.group) if match else None
            locator = self._frame_scope(source.frame_path).locator(source.selector).first
            if source.kind == "text":
                return (await locator.inner_text(timeout=timeout_ms)).strip()
            if source.kind == "input_value":
                return await locator.input_value(timeout=timeout_ms)
            if source.kind == "attribute":
                return await locator.get_attribute(source.attribute, timeout=timeout_ms)
        except Exception:  # noqa: BLE001 — a missing value is None (a healable signal), not a crash
            return None
        return None

    async def condition_report(self, state: State) -> list[tuple[str, bool]]:
        """Evaluate each of a state's conditions once; return [(type, met), ...]."""
        return [(t.type, await self._holds(t)) for t in state.conditions]

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path))

    async def wait_for_state(self, state: State) -> float:
        """Poll until every condition of `state` holds; return recognition latency in ms.

        Raises TriggerTimeoutError naming the unmet conditions — never a silent timeout.
        """
        start = time.monotonic()
        deadline = start + state.timeout_ms / 1000
        while True:
            unmet = [t.type for t in state.conditions if not await self._holds(t)]
            if not unmet:
                return (time.monotonic() - start) * 1000
            if time.monotonic() >= deadline:
                raise TriggerTimeoutError(state.id, unmet, state.timeout_ms)
            await asyncio.sleep(POLL_INTERVAL_S)
