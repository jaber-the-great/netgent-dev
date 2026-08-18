"""Minimal Playwright session: launch, dispatch actions, evaluate state conditions.

This is the v0 of the browser layer — locator chains replay via whitelist reflection,
triggers are evaluated on a polling loop. Capture (HAR/tracing) hooks in at context
creation here when the capture subsystem lands (docs/browser-layer-design.md §4).
"""

import asyncio
import re
import time
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright, async_playwright

from netgent.browser.dom.snapshot import DOM_SNAPSHOT_JS, DomElement, DomSnapshot, TextBlock
from netgent.browser.dom.stealth import StealthProfile
from netgent.core.errors import ActionDispatchError, LocatorResolutionError, TriggerTimeoutError
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
    SetCheckedAction,
)
from netgent.schema.actions import Locator as LocatorChain
from netgent.schema.triggers import SelectorHidden, SelectorVisible, TitleContains, Trigger, UrlMatches
from netgent.schema.workflow import State

POLL_INTERVAL_S = 0.1


class BrowserSession:
    def __init__(self, headless: bool = True, stealth: bool | StealthProfile = True):
        self._headless = headless
        # stealth=True → default profile; a StealthProfile → that profile; False → vanilla.
        self._stealth: StealthProfile | None = (
            (stealth if isinstance(stealth, StealthProfile) else StealthProfile()) if stealth else None
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserSession":
        self._playwright = await async_playwright().start()
        profile = self._stealth
        launch_kwargs = profile.launch_kwargs(self._headless) if profile else {"headless": self._headless}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(**(profile.context_kwargs() if profile else {}))
        if profile:
            await self._context.add_init_script(profile.init_script)
        self._page = await self._context.new_page()
        return self

    async def snapshot(self) -> DomSnapshot:
        """Observe the page's interactive elements + salient visible text."""
        raw = await self.page.evaluate(DOM_SNAPSHOT_JS)
        return DomSnapshot(
            url=self.page.url,
            title=await self.page.title(),
            elements=[DomElement.model_validate(e) for e in raw["elements"]],
            texts=[TextBlock.model_validate(t) for t in raw["texts"]],
        )

    async def __aexit__(self, *exc_info: object) -> None:
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
        target: Page | Locator = self.page
        for step in chain:
            fn = getattr(target, step.fn, None)
            if fn is None:
                raise LocatorResolutionError(f"{type(target).__name__} has no locator fn {step.fn!r}")
            try:
                target = fn(*step.args, **step.kwargs)
            except Exception as exc:
                raise LocatorResolutionError(f"step {step.fn!r} failed: {exc}") from exc
        if isinstance(target, Page):
            raise LocatorResolutionError("empty locator chain")
        return target

    async def dispatch(self, action: Action) -> None:
        try:
            match action:
                case GotoAction():
                    await self.page.goto(action.url, timeout=action.timeout_ms)
                case ClickAction():
                    await self._resolve(action.locator).click(timeout=action.timeout_ms)
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
                    await self.page.mouse.wheel(0, action.delta_y)
                case SetCheckedAction():
                    await self._resolve(action.locator).set_checked(action.checked, timeout=action.timeout_ms)
                case GoBackAction():
                    await self.page.go_back(timeout=action.timeout_ms)
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

    async def _holds(self, trigger: Trigger) -> bool:
        match trigger:
            case UrlMatches():
                return re.search(trigger.pattern, self.page.url) is not None
            case TitleContains():
                return trigger.text in await self.page.title()
            case SelectorVisible():
                return await self.page.locator(trigger.selector).first.is_visible()
            case SelectorHidden():
                return not await self.page.locator(trigger.selector).first.is_visible()
        return False

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
