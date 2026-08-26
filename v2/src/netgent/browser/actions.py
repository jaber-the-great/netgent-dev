"""Action dispatch: one handler per atomic action type, driven through resolved locators."""

from netgent.browser.dialogs import DialogLog
from netgent.browser.pw import PATCHED_BROWSER, Locator, Page
from netgent.browser.resolution import LocatorResolver
from netgent.core.errors import ActionDispatchError, LocatorResolutionError
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


class ActionDispatcher:
    """Executes artifact actions against the live page. Zero LLM, by construction."""

    def __init__(self, page: Page, resolver: LocatorResolver, dialogs: DialogLog | None = None):
        self._page = page
        self._resolver = resolver
        self._dialogs = dialogs

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
        page = self._page
        viewport = await page.evaluate("() => window.innerHeight")
        if action.locator is not None:
            locator = self._resolver.resolve(action.locator)
            box = await locator.bounding_box(timeout=action.timeout_ms)
            if box is None:
                raise ActionDispatchError("scroll target has no bounding box (hidden or detached)")
            await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            viewport = await locator.evaluate("el => el.ownerDocument.defaultView.innerHeight")
        else:
            # Park the cursor at the origin so an earlier anchored scroll cannot leave it over
            # an iframe / inner scroller: an unanchored scroll always means the top frame.
            await page.mouse.move(0, 0)
        pixels = int(action.pages * viewport) * (1 if action.down else -1)
        await page.mouse.wheel(0, pixels)

    async def dispatch(self, action: Action) -> None:
        if self._dialogs is not None:
            self._dialogs.mark_action()  # dialogs from here on belong to this edge (dialog_matches)
        if getattr(action, "requires_closed_shadow", False) and not PATCHED_BROWSER:
            # The capability flag a plain-Playwright replayer refuses on (R8): the target is
            # inside a closed shadow root, which only Patchright's CDP pierce can resolve.
            raise ActionDispatchError(
                "action requires a closed-shadow-piercing engine (Patchright); this replayer cannot resolve it"
            )
        page = self._page
        resolve = self._resolver.resolve
        try:
            match action:
                case GotoAction():
                    await page.goto(action.url, timeout=action.timeout_ms)
                case ClickAction():
                    await self._click(resolve(action.locator), action.timeout_ms)
                case FillAction():
                    await resolve(action.locator).fill(action.text, timeout=action.timeout_ms)
                case PressAction():
                    if action.locator is not None:
                        await resolve(action.locator).press(action.keys, timeout=action.timeout_ms)
                    else:
                        await page.keyboard.press(action.keys)
                case SelectAction():
                    await resolve(action.locator).select_option(action.value, timeout=action.timeout_ms)
                case ScrollAction():
                    await self._scroll(action)
                case UploadFileAction():
                    await resolve(action.locator).set_input_files(action.paths, timeout=action.timeout_ms)
                case GoBackAction():
                    await page.go_back(timeout=action.timeout_ms)
                case WaitAction():
                    await page.wait_for_timeout(action.seconds * 1000)
                case HoverAction():
                    await resolve(action.locator).hover(timeout=action.timeout_ms)
                case NoopAction():
                    pass
                case _:
                    raise ActionDispatchError(f"unhandled action type {type(action).__name__}")
        except (ActionDispatchError, LocatorResolutionError):
            raise
        except Exception as exc:
            raise ActionDispatchError(f"{action.type} failed: {exc}") from exc
