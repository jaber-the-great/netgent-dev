"""Action dispatch: one handler per atomic action type, driven through resolved locators."""

from netgent.browser.dialogs import DialogLog
from netgent.browser.pw import PATCHED_BROWSER, Locator, Page
from netgent.browser.resolution import LocatorResolver
from netgent.core.errors import ActionDispatchError, LocatorResolutionError
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

logger = get_logger(__name__)


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
            try:
                await first.click(timeout=timeout_ms)
                return
            except Exception as exc:  # noqa: BLE001 — occluded/unstable element: try the JS ladder
                reason = str(exc).splitlines()[0]
            # The ladder every mature agent lands on (Skyvern chain_click steps 3+7, browser-use
            # _click_element_node_impl occluded→JS): a sticky header/toast/overlay intercepts the
            # pointer, but the element itself is live — click its bound label if it has one
            # (custom widgets bind behaviour there), else dispatch el.click() directly. Untrusted
            # events, so only after the trusted path failed, and only on a visible element.
            try:
                await first.evaluate(
                    "el => { if (!el.isConnected) throw new Error('detached');"
                    " const t = (el.labels && el.labels[0]) || el; t.click(); }"
                )
                logger.info("click fell back to JS dispatch (%s)", reason)
            except Exception as js_exc:
                raise ActionDispatchError(
                    f"click failed via mouse ({reason}) and via JS dispatch: {js_exc}"
                ) from js_exc
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

    # The value a fill can be verified against, or None when the element has no readable
    # value (then we trust the fill). Contenteditable reads textContent.
    _READBACK_JS = (
        "el => el.isContentEditable ? el.textContent"
        " : ('value' in el ? String(el.value) : null)"
    )

    async def _fill(self, locator: Locator, text: str, timeout_ms: int) -> None:
        """fill, verified by reading the value back, with two escalations.

        Playwright's fill sets the value and dispatches synthetic (untrusted) events; most
        frameworks accept that, but keystroke-driven widgets (rich editors, maskers,
        listeners gating on isTrusted) drop it — measured across browser-use
        (_input_text_element_node_impl readback+retry), Skyvern (input_sequentially) and
        Stagehand (CDP Input.insertText). Ladder: fill → trusted per-key typing
        (press_sequentially) → native-prototype setter + input/change/blur (the React
        _valueTracker path). Each rung is verified; all rungs are deterministic, so one
        artifact action stays one action at replay.
        """
        first = locator.first
        try:
            before = await first.evaluate(self._READBACK_JS)
        except Exception:  # noqa: BLE001
            before = None

        async def verify() -> tuple[bool, str | None]:
            """Did the write LAND? Exact match is success; so is any non-empty NEW value —
            maskers/datepickers reformat what was typed ("1990-05-15" → "05/15/1990"), and
            escalating on a reformatted value fights the widget (measured: the typed-input
            rung opened a datepicker popup and garbled the field). Escalate only when the
            field ended empty or provably unchanged."""
            try:
                current = await first.evaluate(self._READBACK_JS)
            except Exception:  # noqa: BLE001 — unreadable: trust the write
                return True, None
            if current is None or current == text:
                return True, current
            return bool(current) and current != before, current

        try:
            await first.fill(text, timeout=timeout_ms)
            ok, _ = await verify()
            if ok:
                return
        except Exception as exc:  # noqa: BLE001 — fall through to typed input
            logger.info("fill escalating to typed input: %s", str(exc).splitlines()[0])
        try:
            await first.click(timeout=timeout_ms)
            await first.press("ControlOrMeta+a", timeout=timeout_ms)
            await first.press_sequentially(text, timeout=timeout_ms)
            ok, _ = await verify()
            if ok:
                return
        except Exception as exc:  # noqa: BLE001 — fall through to the native setter
            logger.info("typed input escalating to native setter: %s", str(exc).splitlines()[0])
        await first.evaluate(
            """(el, value) => {
                 const proto = el instanceof HTMLTextAreaElement
                   ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                 const setter = Object.getOwnPropertyDescriptor(proto, 'value');
                 if (setter && setter.set && 'value' in el) setter.set.call(el, value);
                 else if (el.isContentEditable) el.textContent = value;
                 if (el._valueTracker) el._valueTracker.setValue('');
                 el.dispatchEvent(new Event('input', {bubbles: true}));
                 el.dispatchEvent(new Event('change', {bubbles: true}));
                 el.dispatchEvent(new Event('blur', {bubbles: true}));
               }""",
            text,
        )
        ok, current = await verify()
        if not ok:
            raise ActionDispatchError(
                f"fill did not stick: field still holds {current!r} after fill, typing and native set"
            )

    async def _select(self, action: SelectAction, locator: Locator) -> None:
        """select_option, with a surrogate ladder for non-native dropdowns.

        A styled dropdown (Material UI div[role=button], Select2 span[combobox], headless-UI
        listboxes) is not a <select>: select_option can never work on it. Ladder (Skyvern's
        hidden-select surrogate flow, Stagehand's click-to-expand evals): if the target is a
        real <select>, select_option by value then by label; otherwise click it open and
        click the option whose text is the recorded value — deterministic, since the option
        text is stored in the artifact.
        """
        value, timeout_ms = action.value, action.timeout_ms
        first = locator.first
        is_select = False
        try:
            is_select = await first.evaluate("el => el.tagName === 'SELECT'")
        except Exception:  # noqa: BLE001 — unreachable element: let select_option surface it
            is_select = True
        if is_select:
            try:
                await first.select_option(value, timeout=timeout_ms)
                return
            except Exception:  # noqa: BLE001 — value didn't match: try the visible label
                await first.select_option(label=value, timeout=timeout_ms)
                return
        await first.click(timeout=timeout_ms)
        # Options portal to the DOCUMENT the widget lives in, not into its subtree — search
        # the same frame the action's locator chain targets (frame-blindness would miss every
        # in-iframe dropdown).
        scope = self._resolver.frame_scope(
            [str(step.args[0]) for step in action.locator if step.fn == "frame_locator"]
        )
        option = scope.get_by_role("option", name=value, exact=True)
        if await option.count() == 0:
            option = scope.get_by_role("option", name=value)
        if await option.count() == 0:
            option = scope.get_by_text(value, exact=True)
        try:
            await option.first.click(timeout=timeout_ms)
        except Exception as exc:
            raise ActionDispatchError(
                f"select {value!r}: target is not a <select> and no matching option appeared after opening"
            ) from exc

    async def _upload(self, locator: Locator, action: UploadFileAction) -> None:
        """set_input_files, with a file-chooser fallback for styled upload widgets.

        Custom widgets can leave the real input un-settable, or the captured locator lands on
        the styled label/button ("Node is not an HTMLInputElement"). Fall back to clicking the
        control with a chooser interceptor armed and feeding the intercepted chooser —
        Playwright suppresses the native dialog; Skyvern arms page.on("filechooser") around
        the click the same way (webeye handler.py).
        """
        first = locator.first
        try:
            await first.set_input_files(action.paths, timeout=min(action.timeout_ms, 3000))
            return
        except Exception as exc:  # noqa: BLE001 — try the chooser route before giving up
            reason = str(exc).splitlines()[0]
        try:
            async with self._page.expect_file_chooser(timeout=action.timeout_ms) as chooser:
                # The label the input belongs to (or the element itself) is what opens the
                # chooser on widgets that hide the real input.
                await first.evaluate("el => (el.labels && el.labels[0] ? el.labels[0] : el).click()")
            await (await chooser.value).set_files(action.paths)
        except Exception as exc:
            raise ActionDispatchError(f"upload failed directly ({reason}) and via file chooser: {exc}") from exc

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
                    await self._fill(resolve(action.locator), action.text, action.timeout_ms)
                case PressAction():
                    if action.locator is not None:
                        await resolve(action.locator).press(action.keys, timeout=action.timeout_ms)
                    else:
                        await page.keyboard.press(action.keys)
                case SelectAction():
                    await self._select(action, resolve(action.locator))
                case ScrollAction():
                    await self._scroll(action)
                case UploadFileAction():
                    await self._upload(resolve(action.locator), action)
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
