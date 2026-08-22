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
    from patchright.async_api import Browser, BrowserContext, Frame, Locator, Page, Playwright, async_playwright

    PATCHED_BROWSER = True
except ImportError:  # pragma: no cover — plain Playwright fallback
    from playwright.async_api import Browser, BrowserContext, Frame, Locator, Page, Playwright, async_playwright

    PATCHED_BROWSER = False

from netgent.browser.dom import ax_snapshot as ax
from netgent.browser.dom.snapshot import DOM_SNAPSHOT_JS, FRAME_SELECTOR_JS, DomElement, DomSnapshot, TextBlock
from netgent.browser.dom.stealth import StealthProfile
from netgent.core.errors import ActionDispatchError, LocatorResolutionError, TriggerTimeoutError
from netgent.core.logger import get_logger
from netgent.core.settings import get_settings
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
SNAPSHOT_RETRIES = 3  # re-observe after a navigation destroyed the context mid-snapshot
NAVIGATION_SETTLE_MS = 5000


def _is_navigation_error(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "Execution context was destroyed",
            "Frame was detached",
            "frame was detached",
            "Target closed",
            "Cannot find context",
            "Navigation interrupted",
        )
    )
HOVER_SETTLE_MS = 1200

# Key names models commonly emit that Playwright does not accept verbatim.
KEY_ALIASES = {
    "return": "Enter", "esc": "Escape", "del": "Delete", "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight", "spacebar": "Space", "pgup": "PageUp", "pgdn": "PageDown",
}


def normalize_keys(keys: str) -> str:
    """'Return' → 'Enter', 'ctrl+a' → 'Control+a': each chord part through the alias table."""
    modifiers = {"ctrl": "Control", "cmd": "Meta", "option": "Alt"}
    parts = []
    for part in keys.split("+"):
        low = part.strip().lower()
        parts.append(KEY_ALIASES.get(low) or modifiers.get(low) or part.strip())
    return "+".join(parts)

# Evaluated through CDP with includeCommandLineAPI so `getEventListeners` exists. Lists the
# document-order index of every element with a direct mouse/keyboard listener.
LISTENER_PROBE_JS = """(() => {
  const want = new Set(['click','dblclick','mousedown','mouseup','pointerdown','pointerup',
    'mouseenter','mouseover','keydown','keyup','keypress','touchstart']);
  const out = {};
  const all = document.querySelectorAll('*');
  for (let i = 0; i < all.length; i++) {
    try {
      const types = Object.keys(getEventListeners(all[i])).filter(t => want.has(t));
      if (types.length) out[i] = types.join(',');
    } catch (e) {}
  }
  return {n: all.length, m: out};
})()"""

logger = get_logger(__name__)


class BrowserSession:
    def __init__(
        self,
        headless: bool = True,
        stealth: bool | StealthProfile = True,
        observation: str | None = None,
    ):
        self._headless = headless
        # Observation backend: "dom" (injected DOM walk) or "ax" (accessibility tree, hybrid).
        # None → NETGENT_OBSERVATION (default "dom"). Both produce the same DomSnapshot.
        self.observation = observation or get_settings().observation
        # stealth=True → default profile; a StealthProfile → that profile; False → vanilla.
        # With a patched binary the best stealth is to spoof NOTHING in JS (spoofs are
        # themselves detectable) and run real Chrome with its native UA/headers.
        default_profile = StealthProfile.native() if PATCHED_BROWSER else StealthProfile()
        self._stealth: StealthProfile | None = (
            (stealth if isinstance(stealth, StealthProfile) else default_profile) if stealth else None
        )
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "BrowserSession":
        self._playwright = await async_playwright().start()
        profile = self._stealth
        launch_kwargs = profile.launch_kwargs(self._headless) if profile else {"headless": self._headless}
        try:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        except Exception:  # noqa: BLE001 — e.g. channel="chrome" but Chrome isn't installed
            if "channel" not in launch_kwargs:
                raise
            launch_kwargs.pop("channel")
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        context_kwargs = profile.context_kwargs() if profile else {}
        if profile and profile.user_agent is None and self._headless:
            # Headless Chrome stamps "HeadlessChrome/<ver>" into its own UA — the one native
            # tell worth overriding. Use the REAL version so the UA never drifts from the binary.
            context_kwargs["user_agent"] = profile.headless_user_agent(self._browser.version)
        self._context = await self._browser.new_context(**context_kwargs)
        if profile and profile.init_script:
            await self._context.add_init_script(profile.init_script)
        self._page = await self._context.new_page()
        return self

    async def _frame_info(self, frame: Frame) -> tuple[list[str], float, float]:
        """(iframe CSS-selector chain, top-viewport Y offset, X offset) for a frame.

        Both are computed in each parent frame's context, so they work for cross-origin
        frames too (Playwright reaches them via CDP). The Y offset is the sum of each
        iframe's getBoundingClientRect().top up the chain, i.e. the frame's top edge in
        the TOP viewport's coordinates — used to place in-frame elements for scroll paging.
        """
        path: list[str] = []
        offset_y = offset_x = 0.0
        current = frame
        while current.parent_frame is not None:
            handle = await current.frame_element()
            selector = await current.parent_frame.evaluate(FRAME_SELECTOR_JS, handle)
            rect = await current.parent_frame.evaluate("(el) => el.getBoundingClientRect().toJSON()", handle)
            path.insert(0, selector)
            offset_y += rect["top"]
            offset_x += rect["left"]
            current = current.parent_frame
        return path, offset_y, offset_x

    async def snapshot(self) -> DomSnapshot:
        """Observe interactive elements + text across ALL frames (same- and cross-origin).

        Dispatches to the configured backend. Both normalize element bbox.y to TOP-viewport
        coordinates so the observation can be paged by scroll position. If the accessibility
        backend fails on a page it falls back to the DOM walk (logged) — observation must
        never abort an exploration step.
        """
        backend = self._snapshot_ax if self.observation in ("ax", "hybrid", "hybrid_on_stuck") else self._snapshot_dom
        last: Exception | None = None
        for attempt in range(SNAPSHOT_RETRIES + 1):
            try:
                return await backend()
            except Exception as exc:  # noqa: BLE001
                last = exc
                if not _is_navigation_error(exc):
                    break
                # The page navigated under us (a click that submitted, a redirect): wait for
                # the new document, then observe again. Bounded, so a thrashing page cannot
                # hang a step.
                logger.info("snapshot attempt %d hit a navigation (%s); retrying", attempt + 1, str(exc)[:80])
                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=NAVIGATION_SETTLE_MS)
                except Exception:  # noqa: BLE001 — still loading; retry anyway
                    pass
        if backend is self._snapshot_ax:
            logger.warning("ax snapshot failed (%s); falling back to the DOM walk", last)
            return await self._snapshot_dom()
        raise last  # type: ignore[misc]

    async def _listener_probe(self, frame: Frame) -> dict | None:
        """Elements with DIRECT mouse/keyboard listeners (addEventListener), via DevTools'
        command-line `getEventListeners` — the only way to see a plain <div> that reacts to
        hover/click without a role, onclick attribute, tabindex or pointer cursor
        (browser-use does the same). Needs a CDP session: available for the main frame and
        out-of-process (cross-origin) iframes; same-process child frames return None.
        Returns {n: element count, m: {index: "click,mouseenter"}} or None.
        """
        target = self.page if frame is self.page.main_frame else frame
        try:
            cdp = await self.page.context.new_cdp_session(target)
        except Exception:  # noqa: BLE001 — same-process child frame: no session of its own
            return None
        try:
            result = await cdp.send(
                "Runtime.evaluate",
                {"expression": LISTENER_PROBE_JS, "includeCommandLineAPI": True, "returnByValue": True},
            )
            value = result.get("result", {}).get("value")
            return value if isinstance(value, dict) else None
        except Exception:  # noqa: BLE001
            return None
        finally:
            try:
                await cdp.detach()
            except Exception:  # noqa: BLE001
                pass

    async def _walk_frames(self, extras_only: bool = False) -> tuple[list[DomElement], list[TextBlock]]:
        """Run the DOM walk in every frame's own context (Playwright evaluates it there via
        CDP, bypassing the same-origin policy that limits in-page contentDocument access)."""
        elements: list[DomElement] = []
        texts: list[TextBlock] = []
        for frame in self.page.frames:
            try:
                frame_path, offset_y, offset_x = await self._frame_info(frame)
                listeners = await self._listener_probe(frame)
                raw = await frame.evaluate(DOM_SNAPSHOT_JS, {"extrasOnly": extras_only, "listeners": listeners})
            except Exception:  # a detached/unreachable frame is skipped, not fatal
                continue
            for element in raw["elements"]:
                element["framePath"] = frame_path
                element["bbox"]["y"] += round(offset_y)  # normalize to top-viewport coordinates
                element["bbox"]["x"] += round(offset_x)
                elements.append(DomElement.model_validate(element))
            for t in raw["texts"]:
                t["frame_path"] = frame_path
                if t.get("y") is not None:
                    t["y"] += round(offset_y)
                texts.append(TextBlock.model_validate(t))
        return elements, texts

    async def _snapshot_dom(self) -> DomSnapshot:
        viewport_height = await self.page.evaluate("() => window.innerHeight")
        elements, texts = await self._walk_frames()
        return DomSnapshot(
            url=self.page.url,
            title=await self.page.title(),
            elements=elements,
            texts=texts,
            viewport_height=int(viewport_height),
        )

    async def _snapshot_ax(self) -> DomSnapshot:
        """Accessibility-tree backend (see browser/dom/ax_snapshot.py).

        1. One `aria_snapshot(mode="ai", boxes=True)` for the whole page (all frames).
        2. Per interactive node, DOM facts via its `aria-ref` (gathered concurrently);
           per iframe node, its CSS selector for the frame_locator chain.
        3. DOM-structural extras (tabindex/onclick/contenteditable/summary/scrollable) from
           the DOM walk in extrasOnly mode, merged by frame + bbox.
        """
        viewport_height = await self.page.evaluate("() => window.innerHeight")
        text = await self.page.locator("body").aria_snapshot(mode="ai", boxes=True)
        nodes = ax.parse_aria_snapshot(text)
        interactives, texts_with_frames, iframe_refs = ax.collect(nodes)

        async def facts(ref: str) -> dict | None:
            try:
                return await self.page.locator(f"aria-ref={ref}").evaluate(ax.ELEMENT_FACTS_JS)
            except Exception:  # noqa: BLE001 — a vanished node just loses its DOM facts
                return None

        async def frame_selector(ref: str) -> str | None:
            try:
                return await self.page.locator(f"aria-ref={ref}").evaluate(FRAME_SELECTOR_JS)
            except Exception:  # noqa: BLE001
                return None

        refs = [it.node.ref for it in interactives if it.node.ref]
        fact_list, selector_list = await asyncio.gather(
            asyncio.gather(*(facts(r) for r in refs)),
            asyncio.gather(*(frame_selector(r) for r in iframe_refs)),
        )
        frame_selectors = {r: sel for r, sel in zip(iframe_refs, selector_list, strict=True) if sel}
        elements = ax.build_elements(interactives, dict(zip(refs, fact_list, strict=True)), frame_selectors)
        texts = []
        for chain, block in texts_with_frames:
            if all(r in frame_selectors for r in chain):
                block.frame_path = [frame_selectors[r] for r in chain]
                texts.append(block)
        extras, _ = await self._walk_frames(extras_only=True)
        return DomSnapshot(
            url=self.page.url,
            title=await self.page.title(),
            elements=ax.merge_extras(elements, extras),
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

    async def _upload(self, locator: Locator, paths: list[str], timeout_ms: int) -> None:
        """set_input_files on the element — or on the file input it stands for.

        Frameworks (MUI, Bootstrap custom-file) render the visible "Upload" control as a
        <label role=button> or <button> with the real <input type=file> hidden beside it; the
        agent picks the visible control. Retarget to the label's control, a descendant file
        input, or the nearest one in the same fieldset/form.
        """
        first = locator.first
        try:
            await first.set_input_files(paths, timeout=timeout_ms)
            return
        except Exception as exc:  # noqa: BLE001 — retarget below
            err = exc
        handle = await first.element_handle(timeout=timeout_ms)
        found = await handle.evaluate_handle(
            """el => {
              if (el.matches('input[type=file]')) return el;
              if (el.control && el.control.type === 'file') return el.control;
              const inside = el.querySelector('input[type=file]');
              if (inside) return inside;
              const scope = el.closest('form, fieldset, .form-group, div') || document;
              return scope.querySelector('input[type=file]') || document.querySelector('input[type=file]');
            }"""
        )
        target = found.as_element()
        if target is None:
            raise err
        await target.set_input_files(paths, timeout=timeout_ms)

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
                    # "ArrowRight ArrowRight ArrowRight" is a sequence of presses; each item
                    # may be a chord ("Control+a"). Aliases like Return/Esc are normalized.
                    for keys in (normalize_keys(k) for k in action.keys.split()):
                        if action.locator is not None:
                            await self._resolve(action.locator).press(keys, timeout=action.timeout_ms)
                        else:
                            await self.page.keyboard.press(keys)
                case SelectAction():
                    await self._resolve(action.locator).select_option(action.value, timeout=action.timeout_ms)
                case ScrollAction():
                    if action.locator is not None:
                        # Scroll INSIDE a scrollable box: hover it, then wheel — exactly the
                        # events a human's wheel delivers, so nested containers and their
                        # scroll listeners behave.
                        target = self._resolve(action.locator).first
                        await target.hover(timeout=action.timeout_ms)
                        viewport = await target.evaluate("el => el.clientHeight || window.innerHeight")
                    else:
                        viewport = await self.page.evaluate("() => window.innerHeight")
                    pixels = int(action.pages * viewport) * (1 if action.down else -1)
                    await self.page.mouse.wheel(0, pixels)
                case UploadFileAction():
                    await self._upload(self._resolve(action.locator), action.paths, action.timeout_ms)
                case GoBackAction():
                    await self.page.go_back(timeout=action.timeout_ms)
                case WaitAction():
                    await self.page.wait_for_timeout(action.seconds * 1000)
                case HoverAction():
                    await self._resolve(action.locator).hover(timeout=action.timeout_ms)
                    # Let the page react to the pointer: hover menus/tooltips open on a delay
                    # and "hover for a second" handlers cancel on mouseleave.
                    await self.page.wait_for_timeout(HOVER_SETTLE_MS)
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

    async def extract_value(self, source: "ParamSource", timeout_ms: int = 5000) -> str | None:
        """Read a dynamic parameter's value from the live page (returns None if unavailable)."""
        try:
            if source.kind == "url_group":
                if not source.pattern:
                    return None
                match = re.search(source.pattern, self.page.url)
                return match.group(source.group) if match else None
            locator = self.page.locator(source.selector).first
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

    async def capture_viewport_png(self) -> bytes:
        """Clean viewport screenshot (no full-page) as PNG bytes — the base for Set-of-Marks."""
        return await self.page.screenshot(full_page=False)

    async def viewport_size(self) -> tuple[int, int]:
        size = await self.page.evaluate("() => [window.innerWidth, window.innerHeight]")
        return int(size[0]), int(size[1])

    async def mark_hits(self, shown: list[tuple[int, "DomElement"]]) -> dict[int, bool]:
        """For each shown element, does document.elementFromPoint at its box CENTER (in the
        element's own frame) land on that element (or its label/child/ancestor)? True = the drawn
        mark sits on the intended, un-occluded element; False = covered by an overlay/modal or
        mis-placed. Used by evals/som_check.py and (optionally) to drop covered marks at runtime.

        The element is located by its durable locator, so nothing is stamped on the page.
        """
        from netgent.agent.explore_agent.observation import _locator_for

        hits: dict[int, bool] = {}
        for idx, el in shown:
            try:
                handle = await self._resolve(_locator_for(el)).first.element_handle(timeout=1000)
                if handle is None:
                    hits[idx] = False
                    continue
                hits[idx] = bool(
                    await handle.evaluate(
                        """el => {
                          const r = el.getBoundingClientRect();
                          const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
                          if (r.width === 0 && r.height === 0) return false;
                          const hit = el.ownerDocument.elementFromPoint(cx, cy);
                          if (!hit) return false;
                          if (hit === el || el.contains(hit) || hit.contains(el)) return true;
                          // a <label> for the control, or the control's label, counts as landing on it
                          const lbl = el.labels && el.labels[0];
                          return !!(lbl && (hit === lbl || lbl.contains(hit)));
                        }"""
                    )
                )
            except Exception:  # noqa: BLE001 — an element that vanished is simply not a hit
                hits[idx] = False
        return hits

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
