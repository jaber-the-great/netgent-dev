"""Minimal Playwright session: launch, dispatch actions, evaluate state conditions.

This is the v0 of the browser layer — locator chains replay via whitelist reflection,
triggers are evaluated on a polling loop. Capture (HAR/tracing) hooks in at context
creation here when the capture subsystem lands (docs/browser-layer-design.md §4).
"""

import asyncio
import re
import time
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Frame, Locator, Page, Playwright, async_playwright

from netgent.browser.dom.snapshot import DOM_SNAPSHOT_JS, FRAME_SELECTOR_JS, DomElement, DomSnapshot, TextBlock
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
    UploadFileAction,
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

    async def _frame_info(self, frame: Frame) -> tuple[list[str], float]:
        """(iframe CSS-selector chain, top-viewport Y offset) for a frame.

        Both are computed in each parent frame's context, so they work for cross-origin
        frames too (Playwright reaches them via CDP). The Y offset is the sum of each
        iframe's getBoundingClientRect().top up the chain, i.e. the frame's top edge in
        the TOP viewport's coordinates — used to place in-frame elements for scroll paging.
        """
        path: list[str] = []
        offset = 0.0
        current = frame
        while current.parent_frame is not None:
            handle = await current.frame_element()
            selector = await current.parent_frame.evaluate(FRAME_SELECTOR_JS, handle)
            top = await current.parent_frame.evaluate("(el) => el.getBoundingClientRect().top", handle)
            path.insert(0, selector)
            offset += top
            current = current.parent_frame
        return path, offset

    async def snapshot(self) -> DomSnapshot:
        """Observe interactive elements + text across ALL frames (same- and cross-origin).

        The DOM walk runs inside each frame's own context (Playwright evaluates it there
        via CDP, bypassing the same-origin policy that limits in-page contentDocument access).
        Element bbox.y is normalized to TOP-viewport coordinates so the observation can be
        paged by scroll position.
        """
        elements: list[DomElement] = []
        texts: list[TextBlock] = []
        viewport_height = await self.page.evaluate("() => window.innerHeight")
        for frame in self.page.frames:
            try:
                frame_path, offset_y = await self._frame_info(frame)
                raw = await frame.evaluate(DOM_SNAPSHOT_JS)
            except Exception:  # a detached/unreachable frame is skipped, not fatal
                continue
            for element in raw["elements"]:
                element["framePath"] = frame_path
                element["bbox"]["y"] += round(offset_y)  # normalize to top-viewport coordinates
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

    async def _click(self, locator: Locator, timeout_ms: int) -> None:
        """Click, with checkbox/radio handling folded in (keyed on the live element).

        A checkbox toggles; a radio selects. First try Playwright's set_checked/check
        (label-aware, verified). If the state still didn't change — the tell of a custom
        control whose real <input> is hidden behind a styled label — fall back to clicking
        the associated label in JS, which fires the framework's own handler.
        """
        kind = (await locator.get_attribute("type")) or (await locator.get_attribute("role"))
        if kind not in ("checkbox", "radio"):
            await locator.click(timeout=timeout_ms)
            return

        target = True if kind == "radio" else not await locator.is_checked()
        try:
            await locator.set_checked(target, timeout=timeout_ms)
        except Exception:  # noqa: BLE001 — custom controls make set_checked time out; try the fallback
            pass
        if await locator.is_checked() != target:
            # Custom radio/checkbox: click the label (or the input) in the element's own
            # context — this fires framework listeners a synthetic input click misses.
            await locator.evaluate("el => (el.labels && el.labels[0] ? el.labels[0] : el).click()")

    async def dispatch(self, action: Action) -> None:
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
                    viewport = await self.page.evaluate("() => window.innerHeight")
                    pixels = int(action.pages * viewport) * (1 if action.down else -1)
                    await self.page.mouse.wheel(0, pixels)
                case UploadFileAction():
                    await self._resolve(action.locator).set_input_files(action.paths, timeout=action.timeout_ms)
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
