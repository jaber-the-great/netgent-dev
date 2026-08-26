"""Playwright session facade: lifecycle plus the public surface the executor and agents drive.

`factory.launch` builds the browser/context/page/CDP handle; `DomObserver` observes,
`LocatorResolver` replays locator chains, `ActionDispatcher` dispatches actions and
`TriggerEngine` evaluates state conditions. This class composes them and only delegates
(docs/browser-layer-design.md §"Package structure").
"""

from pathlib import Path
from typing import Any

from netgent.browser.actions import ActionDispatcher
from netgent.browser.dialogs import DialogLog
from netgent.browser.dom.closed_shadow import ClosedShadowObserver
from netgent.browser.dom.models import DomSnapshot
from netgent.browser.dom.observer import DomObserver
from netgent.browser.dom.scripts import DOM_SNAPSHOT_JS, FRAME_SELECTOR_JS
from netgent.browser.factory import BrowserHandle, close, launch
from netgent.browser.profile import BrowserProfile
from netgent.browser.pw import PATCHED_BROWSER, Browser, BrowserContext, Locator, Page, Playwright
from netgent.browser.resolution import LocatorResolver
from netgent.browser.triggers import TriggerEngine
from netgent.schema.actions import Action
from netgent.schema.actions import Locator as LocatorChain
from netgent.schema.control import ParamSource
from netgent.schema.workflow import State

__all__ = ["PATCHED_BROWSER", "BrowserSession"]


class BrowserSession:
    def __init__(self, headless: bool = True, profile: BrowserProfile | None = None):
        self._headless = headless
        self._profile = profile or BrowserProfile.default()
        self._handle: BrowserHandle | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._cdp: Any | None = None  # CDP session: closed-shadow observation (Patchright) + client-hints repair
        self._dom: DomObserver | None = None
        self._resolver: LocatorResolver | None = None
        self._actions: ActionDispatcher | None = None
        self._triggers: TriggerEngine | None = None

    async def __aenter__(self) -> "BrowserSession":
        handle = await launch(self._profile, self._headless)
        self._handle = handle
        self._playwright = handle.playwright
        self._browser = handle.browser
        self._context = handle.context
        self._page = handle.page
        self._cdp = handle.cdp
        # Closed-shadow observation (R8) is read from OUTSIDE the page over CDP — no init
        # script, no prototype patch, no global: page JS cannot tell (dom/closed_shadow.py).
        # Patchright only — closed roots can only be ACTED on through Patchright's CDP pierce,
        # so observing them under plain Playwright would surface elements the replayer could
        # never drive. Cross-origin frames work because every frame is read through its own
        # target's session (an init script via add_init_script would break them — measured).
        closed_shadow: ClosedShadowObserver | None = None
        if PATCHED_BROWSER and self._cdp is not None:
            closed_shadow = ClosedShadowObserver(self._page, self._cdp, DOM_SNAPSHOT_JS, FRAME_SELECTOR_JS)
        dialogs = DialogLog(self._page)
        self._dom = DomObserver(self._page, closed_shadow, dialogs)
        self._resolver = LocatorResolver(self._page)
        self._actions = ActionDispatcher(self._page, self._resolver, dialogs)
        self._triggers = TriggerEngine(self._page, self._resolver, dialogs)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._handle is not None:
            await close(self._handle)

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("session not started — use `async with BrowserSession(...)`")
        return self._page

    # ── observation ──────────────────────────────────────────────────────────────

    async def snapshot(self) -> DomSnapshot:
        return await self._dom.snapshot()

    def dialogs_since_last_action(self) -> list[str]:
        """Dialogs raised by the most recently dispatched action (browser/dialogs.py)."""
        dialogs = self._dom._dialogs if self._dom is not None else None
        return dialogs.since_last_action() if dialogs is not None else []

    def dialogs_seen(self) -> list[str]:
        """Every JS dialog (alert/confirm/prompt) accepted this session, in order. Cumulative —
        unlike `snapshot().dialogs`, which drains. Used to verify a success alert after the
        fact (browser/dialogs.py)."""
        return self._dom.dialogs_seen() if self._dom is not None else []

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path))

    # ── locator resolution ───────────────────────────────────────────────────────

    def resolve(self, chain: LocatorChain) -> Locator:
        return self._resolver.resolve(chain)

    async def count(self, chain: LocatorChain) -> int:
        return await self._resolver.count(chain)

    async def match_index(self, chain: LocatorChain, x: float, y: float, limit: int = 50) -> int:
        return await self._resolver.match_index(chain, x, y, limit)

    async def normalize(self, chain: LocatorChain) -> str:
        return await self._resolver.normalize(chain)

    async def same_element(self, a: LocatorChain, b: LocatorChain) -> bool:
        return await self._resolver.same_element(a, b)

    # ── actions ──────────────────────────────────────────────────────────────────

    async def dispatch(self, action: Action) -> None:
        await self._actions.dispatch(action)

    # ── triggers / state ─────────────────────────────────────────────────────────

    async def extract_value(self, source: "ParamSource", timeout_ms: int = 5000) -> str | None:
        return await self._triggers.extract_value(source, timeout_ms)

    async def condition_report(self, state: State) -> list[tuple[str, bool]]:
        return await self._triggers.condition_report(state)

    async def wait_for_state(self, state: State) -> float:
        return await self._triggers.wait_for_state(state)
