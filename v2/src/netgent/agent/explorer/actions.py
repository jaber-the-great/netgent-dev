"""Decision → Action: resolve the LLM's element-indexed decision to a schema Action.

The observation is a numbered list of interactive elements (rendered by
browser/dom/serializer.py). The LLM answers with an element `index`; `to_action` turns
(decision, snapshot) into an Action whose locator comes from `locator_for` — the agent loop
passes a builder verified against the live page (browser/locators.py); the default is the
pure most-durable candidate.
"""

from collections.abc import Callable

from netgent.agent.explorer.decision import AgentDecision
from netgent.browser.dom import DomElement, DomSnapshot
from netgent.browser.locators import durable_locator
from netgent.schema.actions import (
    Action,
    ClickAction,
    FillAction,
    GoBackAction,
    GotoAction,
    HoverAction,
    LocatorStep,
    PressAction,
    ScrollAction,
    SelectAction,
    UploadFileAction,
    WaitAction,
)

LocatorBuilder = Callable[[DomElement], list[LocatorStep]]


def to_action(
    decision: AgentDecision,
    snapshot: DomSnapshot,
    upload_path: str | None = None,
    locator_for: LocatorBuilder = durable_locator,
) -> Action:
    """Map an element-indexed decision to a concrete schema Action.

    `locator_for` builds the chain for the chosen element; the agent loop passes one that
    was verified unique against the live page (browser/locators.py), the default is pure.
    """
    def element() -> DomElement:
        elems = snapshot.interactive()
        if decision.index is None or not (0 <= decision.index < len(elems)):
            raise ValueError(f"{decision.kind} needs a valid element index, got {decision.index}")
        return elems[decision.index]

    match decision.kind:
        case "goto":
            if not decision.url:
                raise ValueError("goto needs a url")
            return GotoAction(url=decision.url)
        case "click":
            # One click verb for everything. Checkbox/radio handling (toggle/select via
            # a verified, label-aware path) lives in the click dispatch, keyed on the live
            # element — so both the agent and the schema stay simple.
            return ClickAction(locator=locator_for(element()))
        case "upload":
            if not upload_path:
                raise ValueError("no upload file configured for this agent")
            return UploadFileAction(locator=locator_for(element()), paths=[upload_path])
        case "fill":
            el = element()
            if el.tag == "select":
                raise ValueError(f"element {decision.index} is a dropdown — use 'select' with one of its options")
            return FillAction(locator=locator_for(el), text=decision.text or "")
        case "select":
            el = element()
            if el.tag != "select":
                kind = f"{el.tag}[{el.type}]" if el.type else el.tag
                raise ValueError(
                    f"element {decision.index} is <{kind}>, not a dropdown — use 'fill'"
                    " (dates as YYYY-MM-DD), or 'click' for a radio/checkbox"
                )
            if el.options and decision.value and decision.value not in el.options:
                raise ValueError(f"'{decision.value}' is not an option; choose one of {el.options}")
            return SelectAction(locator=locator_for(el), value=decision.value or "")
        case "hover":
            return HoverAction(locator=locator_for(element()))
        case "press":
            return PressAction(keys=decision.keys or "Enter")
        case "scroll":
            down = decision.down if decision.down is not None else True
            # Guard against survey-scrolling: don't scroll past required fields still in view.
            if down and snapshot.viewport_height:
                vh = snapshot.viewport_height
                pending = [i for i, e in enumerate(snapshot.interactive()) if e.invalid and 0 <= e.bbox.y <= vh]
                if pending:
                    raise ValueError(
                        f"do not scroll yet — fill the [required]/[invalid] fields in view first: {pending[:8]}"
                    )
            pages = decision.pages if decision.pages is not None else 1.0
            # Frame-aware scroll: anchor on the named element, or — when the observation is
            # scoped to one iframe (a sweep) — on any element of that frame, so the wheel
            # moves that frame instead of the top document (research doc, R5).
            elems = snapshot.interactive()
            anchor: DomElement | None = None
            if decision.index is not None and 0 <= decision.index < len(elems):
                anchor = elems[decision.index]
            elif elems and elems[0].frame_path and all(e.frame_path == elems[0].frame_path for e in elems):
                anchor = elems[0]
            if anchor is not None:
                return ScrollAction(down=down, pages=pages, locator=locator_for(anchor))
            return ScrollAction(down=down, pages=pages)
        case "go_back":
            return GoBackAction()
        case "wait":
            # cap the agent's dwell so a runaway decision can't stall exploration
            return WaitAction(seconds=min(decision.seconds or 3.0, 60.0))
    raise ValueError(f"{decision.kind} is not a dispatchable action")
