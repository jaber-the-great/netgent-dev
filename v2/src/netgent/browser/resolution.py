"""Locator-chain resolution: replay a stored chain against the live page by whitelist reflection."""

from netgent.browser.pw import FrameLocator, Locator, Page
from netgent.core.errors import LocatorResolutionError
from netgent.schema.actions import Locator as LocatorChain


class LocatorResolver:
    """Turns artifact locator chains into Playwright Locators (and answers questions about them)."""

    def __init__(self, page: Page):
        self._page = page

    def resolve(self, chain: LocatorChain) -> Locator:
        """Replay a stored chain by whitelist reflection; the result is always a Locator.

        The schema already type-checks the receiver sequence (`validate_locator_chain`);
        this is the runtime backstop, so a chain ending on a FrameLocator (no fill/click)
        or on the Page is a LocatorResolutionError, never an AttributeError from dispatch.
        """
        target: Page | Locator | FrameLocator = self._page
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
        return await self.resolve(chain).count()

    async def match_index(self, chain: LocatorChain, x: float, y: float, limit: int = 50) -> int:
        """Index (for an `nth` step) of the chain's match whose box is nearest (x, y).

        (x, y) are top-viewport coordinates, the same space Playwright's bounding_box()
        reports in — so this works for in-frame elements too.
        """
        locator = self.resolve(chain)
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
        (agent/explorer/normalized.py); it never reaches an artifact.
        """
        normalized = await self.resolve(chain).normalize()
        return normalized._impl_obj._selector

    async def same_element(self, a: LocatorChain, b: LocatorChain) -> bool:
        """Do two chains resolve to the very same element node right now?"""
        try:
            ha = await self.resolve(a).element_handle(timeout=2000)
            hb = await self.resolve(b).element_handle(timeout=2000)
            return bool(await ha.evaluate("(x, y) => x === y", hb))
        except Exception:  # noqa: BLE001 — different frames / unresolvable → not the same
            return False

    def frame_scope(self, frame_path: list[str]) -> Page | FrameLocator:
        """The receiver a CSS selector is queried on: the page, or the frame_locator chain
        for `frame_path` — the same chain `resolve` builds from a locator's frame steps,
        so triggers and parameter sources see exactly the frames actions do."""
        scope: Page | FrameLocator = self._page
        for selector in frame_path:
            scope = scope.frame_locator(selector)
        return scope
