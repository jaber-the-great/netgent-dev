"""Format a DOM snapshot for the LLM, and resolve a chosen element to a real action.

The observation is a numbered list of interactive elements. The LLM answers with an element
`index`; `to_action` turns (decision, snapshot) into a schema Action whose locator is built
from the element's most durable candidate selector (role → test-id → label → css).
"""

from netgent.agent.decision import AgentDecision
from netgent.browser.dom.snapshot import DomElement, DomSnapshot
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
    SetCheckedAction,
)


def format_observation(snapshot: DomSnapshot, limit: int = 80, text_limit: int = 30) -> str:
    lines = [f"URL: {snapshot.url}", f"TITLE: {snapshot.title}", "INTERACTIVE ELEMENTS:"]
    for i, el in enumerate(snapshot.interactive()[:limit]):
        kind = el.tag
        if el.type:  # input[date], input[file], input[email] — the agent needs the type
            kind += f"[{el.type}]"
        elif el.role and el.role != el.tag:
            kind += f" ({el.role})"
        val = f' value="{el.value}"' if el.value else ""
        name = f' "{el.name}"' if el.name else ""
        state = ""
        if el.checked is not None:
            state += " [checked]" if el.checked else " [unchecked]"
        if el.disabled:
            state += " [disabled]"
        lines.append(f"  [{i}] {kind}{name}{val}{state}")
    if snapshot.texts:
        lines.append("VISIBLE TEXT:")
        for t in snapshot.texts[:text_limit]:
            prefix = "  !ALERT " if t.alert else "  "
            lines.append(f"{prefix}{t.text}")
    return "\n".join(lines)


def _locator_for(el: DomElement) -> list[LocatorStep]:
    """Build a durable locator chain from an element's best candidate selector."""
    candidates = el.candidates
    # <select> accessible names are unreliable (option dumps); prefer a stable selector.
    if el.tag == "select":
        candidates = [c for c in candidates if c.kind != "role"] or candidates
    for cand in candidates:
        if cand.kind == "role" and cand.role:
            kwargs = {"name": cand.name} if cand.name else {}
            return [LocatorStep(fn="get_by_role", args=[cand.role], kwargs=kwargs)]
        if cand.kind == "test_id" and cand.value:
            return [LocatorStep(fn="get_by_test_id", args=[cand.value])]
        if cand.kind == "label" and cand.value:
            return [LocatorStep(fn="get_by_label", args=[cand.value])]
        if cand.kind == "css" and cand.value:
            return [LocatorStep(fn="locator", args=[cand.value])]
    raise ValueError(f"element {el.name!r} has no usable candidate selector")


def to_action(decision: AgentDecision, snapshot: DomSnapshot) -> Action:
    """Map an element-indexed decision to a concrete schema Action."""
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
            return ClickAction(locator=_locator_for(element()))
        case "fill":
            return FillAction(locator=_locator_for(element()), text=decision.text or "")
        case "select":
            return SelectAction(locator=_locator_for(element()), value=decision.value or "")
        case "check":
            return SetCheckedAction(locator=_locator_for(element()), checked=True)
        case "uncheck":
            return SetCheckedAction(locator=_locator_for(element()), checked=False)
        case "hover":
            return HoverAction(locator=_locator_for(element()))
        case "press":
            return PressAction(keys=decision.keys or "Enter")
        case "scroll":
            return ScrollAction(delta_y=decision.delta_y or 400)
        case "go_back":
            return GoBackAction()
    raise ValueError(f"{decision.kind} is not a dispatchable action")
