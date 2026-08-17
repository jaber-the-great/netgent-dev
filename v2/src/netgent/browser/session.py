"""Minimal Playwright session: launch, dispatch actions, evaluate state conditions.

This is the v0 of the browser layer — locator chains replay via whitelist reflection,
triggers are evaluated on a polling loop. Capture (HAR/tracing) hooks in at context
creation here when the capture subsystem lands (docs/browser-layer-design.md §4).
"""

import asyncio
import re
import time

from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright, async_playwright

from netgent.browser.errors import ActionDispatchError, LocatorResolutionError, TriggerTimeoutError
from netgent.core.actions import (
    Action,
    ClickAction,
    FillAction,
    GotoAction,
    NoopAction,
    PressAction,
    ScrollAction,
    SelectAction,
)
from netgent.core.actions import Locator as LocatorChain
from netgent.core.triggers import SelectorHidden, SelectorVisible, TitleContains, Trigger, UrlMatches
from netgent.core.workflow import State

POLL_INTERVAL_S = 0.1


class BrowserSession:
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserSession":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        return self

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
