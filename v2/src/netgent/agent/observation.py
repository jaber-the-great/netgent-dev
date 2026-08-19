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


def format_observation(snapshot: DomSnapshot, limit: int = 60, text_limit: int = 25) -> str:
    """Render the near-viewport slice of the page. Elements keep their original snapshot
    index (what the agent references); scrolling shifts which slice is shown."""
    lines = [f"URL: {snapshot.url}", f"TITLE: {snapshot.title}"]

    # Page the elements by top-viewport position so scroll reveals the next batch.
    vh = snapshot.viewport_height or 0
    indexed = list(enumerate(snapshot.interactive()))
    if vh:
        above = sum(1 for _, el in indexed if el.bbox.y < -60)
        visible = sorted((ie for ie in indexed if ie[1].bbox.y >= -60), key=lambda ie: ie[1].bbox.y)
    else:  # viewport unknown → show in document order, no paging
        above, visible = 0, indexed
    shown = visible[:limit]
    below = len(visible) - len(shown)
    if vh:
        if not above and below:
            lines.append("POSITION: top of page. The elements below are the first ones — act on them.")
        elif above and not below:
            lines.append("POSITION: bottom of page. Nothing more below; do not scroll down further.")
        elif above and below:
            lines.append("POSITION: middle of page.")
    if above:
        lines.append(f"(↑ {above} elements above — already handled; scroll up only to revisit)")
    lines.append("INTERACTIVE ELEMENTS (near viewport):")

    for i, el in shown:
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
        if el.required:
            state += " [required]"
        if el.invalid:
            state += " [invalid: still needs a valid value]"
        lines.append(f"  [{i}] {kind}{name}{val}{state}")
    if below:
        lines.append(f"(↓ {below} more elements below — scroll down to reveal and reach them)")
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
            el = element()
            # Clicking a checkbox/radio routes to the robust set_checked path (label-aware,
            # verified, idempotent) — so the agent only needs one verb, "click".
            if el.tag == "input" and el.type == "checkbox":
                return SetCheckedAction(locator=_locator_for(el), checked=not bool(el.checked))
            if el.tag == "input" and el.type == "radio":
                return SetCheckedAction(locator=_locator_for(el), checked=True)
            return ClickAction(locator=_locator_for(el))
        case "upload":
            if not upload_path:
                raise ValueError("no upload file configured for this agent")
            return UploadFileAction(locator=_locator_for(element()), paths=[upload_path])
        case "fill":
            el = element()
            if el.tag == "select":
                raise ValueError(f"element {decision.index} is a dropdown — use 'select' with one of its options")
            return FillAction(locator=_locator_for(el), text=decision.text or "")
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
            return SelectAction(locator=_locator_for(el), value=decision.value or "")
        case "hover":
            return HoverAction(locator=_locator_for(element()))
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
            return ScrollAction(down=down, pages=decision.pages if decision.pages is not None else 1.0)
        case "go_back":
            return GoBackAction()
    raise ValueError(f"{decision.kind} is not a dispatchable action")
