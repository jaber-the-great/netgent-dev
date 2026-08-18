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
    UploadFileAction,
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
        if el.options:
            val += f" options=[{', '.join(el.options)}]"
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
    """Build a durable locator chain: frame_locator steps for any iframe path, then the element.

    Preference order: a simple #id (precise and pierces open shadow DOM) → role WITH a real
    accessible name → test-id → label → any css path. A role locator with no name is skipped:
    it comes from a placeholder-only field, which Playwright's role-name matching won't match.
    """
    chain = [LocatorStep(fn="frame_locator", args=[sel]) for sel in el.frame_path]
    cands = el.candidates

    def css(value: str) -> list[LocatorStep]:
        return chain + [LocatorStep(fn="locator", args=[value])]

    # 1. simple #id — most precise, and Playwright's css engine pierces open shadow roots
    for c in cands:
        if c.kind == "css" and c.value and c.value.startswith("#") and " " not in c.value:
            return css(c.value)
    # 2. role with a genuine accessible name (skip <select>: its name is an option dump)
    if el.tag != "select":
        for c in cands:
            if c.kind == "role" and c.role and c.name:
                return chain + [LocatorStep(fn="get_by_role", args=[c.role], kwargs={"name": c.name})]
    # 3. test-id, 4. label
    for c in cands:
        if c.kind == "test_id" and c.value:
            return chain + [LocatorStep(fn="get_by_test_id", args=[c.value])]
        if c.kind == "label" and c.value:
            return chain + [LocatorStep(fn="get_by_label", args=[c.value])]
    # 5. any css path
    for c in cands:
        if c.kind == "css" and c.value:
            return css(c.value)
    raise ValueError(f"element {el.name!r} has no usable candidate selector")


def to_action(decision: AgentDecision, snapshot: DomSnapshot, upload_path: str | None = None) -> Action:
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
        case "upload":
            if not upload_path:
                raise ValueError("no upload file configured for this agent")
            return UploadFileAction(locator=_locator_for(element()), paths=[upload_path])
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
