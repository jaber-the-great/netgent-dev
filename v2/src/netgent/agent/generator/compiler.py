"""Compile an agent trajectory into a workflow (NFA): Discovery -> artifact.

Each successful action step becomes one transition; the state after each step is
recognized by the (query-stripped) URL it landed on. Sample values the caller names
become ${name} parameters, so the compiled workflow replays for other values:

    traj = await BrowserAgent(...).run(session, task)
    wf = compile_trajectory(traj, name="twitch-live", params={"channel": "monstercat"})
    # netgent run wf.yaml --param channel=bobross
"""

import re
from urllib.parse import quote_plus

from netgent.agent.explorer.browser_agent import AgentTrajectory
from netgent.schema.actions import (
    Action,
    ClickAction,
    FillAction,
    GotoAction,
    HoverAction,
    Locator,
    SelectAction,
    WaitAction,
)
from netgent.schema.control import ControlNode, EdgeStep, Interrupt, Repeat
from netgent.schema.workflow import Param, State, Transition, Workflow

NAVIGATION_TIMEOUT_MS = 30_000  # a page load needs a navigation-scale budget, not an element-action one

# Actions whose element must be VISIBLE for Playwright to act on it — so "its element is
# visible" is a sound guard for the state the action fires from. (upload_file and press
# are excluded: set_input_files works on hidden file inputs, press only needs focus.)
_VISIBILITY_GATED = (ClickAction, FillAction, SelectAction, HoverAction)

# Steps whose reasoning marks them as interruption-handling (ads, cookie walls, pop-ups).
# Deliberately excludes bare "skip": fast-forward reasoning says "skip ahead 10 seconds".
_INTERRUPTION_RE = re.compile(
    r"\b(ads?|advert\w+|pop-?ups?|cookies?|consent|banners?|dismiss\w*|no thanks)\b",
    re.IGNORECASE,
)

# ...and whose click TARGET also looks like a dismissal control. Reasoning alone is too
# loose — "maybe it restarted after the ad" flagged a seek-slider click as an interrupt
# (v3 run, 2026-08-27). Both signals must agree.
_INTERRUPTION_TARGET_RE = re.compile(
    r"skip|dismiss|consent|cookie|no.?thanks|close|reject|accept|got.?it",
    re.IGNORECASE,
)

DWELL_SLICE_S = 1.0  # dwells compile to Repeat(wait 1s) so interrupt sweeps run between slices
DWELL_MIN_SLICED_S = 3.0  # shorter waits stay a single atomic action


def _base_url(url: str) -> str:
    """URL without query/fragment — the stable part worth recognizing a state by."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _element_condition(action: Action) -> dict | None:
    """A selector_visible condition for the IN-IFRAME element `action` targets, with its frame path.

    A URL recognizes the top document only; an embedded document (payment, login, consent
    widgets) loads on its own schedule, so a state whose next action lives in an iframe is
    anchored on that element being visible *inside the frame* — the frame_locator steps become
    the trigger's `frame_path` (the frame-blind trigger bug, research doc "Where NetGent stands"
    #1). Top-frame elements get no such guard on purpose: a missing top-frame element should
    surface as the action's error (UI drift), not as a state never recognized (flow drift).
    Only a chain of the shape [frame_locator+, locator(css)] is expressible as a CSS trigger;
    role/label chains and nth-disambiguated chains (where `.first` would be a different
    element) yield nothing.
    """
    if not isinstance(action, _VISIBILITY_GATED):
        return None
    chain = action.locator
    if len(chain) < 2 or chain[-1].fn != "locator" or chain[-1].kwargs:
        return None
    frame_path: list[str] = []
    for step in chain[:-1]:
        if step.fn == "frame_locator" and len(step.args) == 1:
            frame_path.append(str(step.args[0]))
        elif step.fn == "nth" and frame_path and len(step.args) == 1:
            # a disambiguated frame step: the same thing as a selector string (Playwright's
            # `>> nth=N` chaining), which is what frame_path carries
            frame_path[-1] = f"{frame_path[-1]} >> nth={int(step.args[0])}"
        else:
            return None
    selector = chain[-1].args[0] if len(chain[-1].args) == 1 else None
    if not isinstance(selector, str):
        return None
    return {"type": "selector_visible", "selector": selector, "frame_path": frame_path}


def _locator_selector(locator: Locator) -> str | None:
    """A Playwright selector string equivalent to a locator chain, or None if inexpressible.

    Conservative by design: only the two single-step shapes the explore agent emits today.
    A chain we can't translate yields no guard (an open gate), never a wrong guard.
    """
    if len(locator) != 1:
        return None
    step = locator[0]
    if step.fn == "locator" and step.args and not step.kwargs:
        return str(step.args[0])  # raw CSS/Playwright selector, verbatim
    if step.fn == "get_by_role" and step.args:
        role = step.args[0]
        name = step.kwargs.get("name")
        if name is None:
            return f"role={role}"
        escaped = str(name).replace('"', '\\"')
        return f'role={role}[name="{escaped}" i]'  # `i`: get_by_role's name match is case-insensitive
    return None


def _target_selector(action: Action) -> str | None:
    """The selector the action is about to act on, when it has one (click/fill/press-on-element/…)."""
    locator = getattr(action, "locator", None)
    return _locator_selector(locator) if locator else None


def compile_trajectory(
    traj: AgentTrajectory,
    name: str,
    params: dict[str, str] | None = None,
    version: str = "1",
    warnings: list[str] | None = None,
) -> Workflow:
    """Compile the trajectory's successful action steps into a replayable Workflow.

    `params` maps a param name to the sample value used during exploration. Binding is
    structural first: a step whose `param` names one of them gets `${name}` in its action's
    value field (and in a locator name that IS the sample value). The old case-insensitive
    literal sweep remains as a fallback for value fields and state conditions — never inside
    locators, where substring matches over-abstracted names. Anything the compiler could not
    bind is reported in `warnings` (appended in place) instead of failing silently.
    """
    all_steps = [s for s in traj.steps if s.action is not None and s.error is None]
    if not all_steps:
        raise ValueError("trajectory has no successful action steps to compile")

    # Interruption-handling clicks (ad-skip, cookie-dismiss, …) leave the main word and
    # become scoped ε-interrupts: the executor fires them whenever their anchor holds,
    # so a replay that gets no ad (or an ad at a different moment) still walks the word.
    def _is_interruption(step) -> bool:
        if step.action.type != "click" or not _INTERRUPTION_RE.search(step.reasoning or ""):
            return False
        sel = _target_selector(step.action)
        return sel is not None and bool(_INTERRUPTION_TARGET_RE.search(sel))

    interruption_steps = [s for s in all_steps if _is_interruption(s)]
    steps = [s for s in all_steps if not _is_interruption(s)]
    if not steps:
        raise ValueError("trajectory has no main-path steps to compile (all were interruptions)")

    states = [State(id="init")]
    transitions: list[Transition] = []
    control: list[ControlNode] = []
    state_base: dict[str, str] = {}  # state id -> base URL it lives on (for interrupt scoping)
    prev_base: str | None = None
    for i, step in enumerate(steps, 1):
        base = _base_url(step.url)
        # Recognize the state by its URL only when the action moved somewhere new;
        # same-page steps (fills, same-page clicks) get an unconditioned state.
        conditions = [{"type": "url_matches", "pattern": re.escape(base)}] if base != prev_base else []
        # Anchor the state on the in-iframe element the NEXT step acts on (when it has a
        # CSS chain): the embedded document being ready is not expressible by the URL.
        if i < len(steps):
            element_condition = _element_condition(steps[i].action)
            if element_condition is not None:
                conditions.append(element_condition)
            # Anchor the state on the NEXT edge's target element: recognition (up to the
            # state's timeout) then gates that edge on the page being ready for it, replacing
            # blind sleeps and races. docs/browser-layer-design.md §3: every fixed sleep is a
            # trigger that couldn't be expressed — this expresses it.
            elif (sel := _target_selector(steps[i].action)) is not None:
                conditions.append({"type": "selector_visible", "selector": sel})
        # A dialog raised by THIS step's action is the page's own confirmation — often the
        # ONLY one (alert-only forms leave URL and DOM unchanged). Anchor the state the
        # action lands in on it; replay evaluates it against dialogs raised since the last
        # dispatched action, so it cannot match a dialog from an earlier edge. If the
        # message is dynamic, zero-LLM validation replay fails the workflow honestly.
        if step.dialogs:
            conditions.append({"type": "dialog_matches", "pattern": re.escape(step.dialogs[-1])})
        prev_base = base
        state_id = f"s{i}"
        states.append(State(id=state_id, conditions=conditions))
        state_base[state_id] = base
        action = step.action
        if isinstance(action, GotoAction) and action.timeout_ms < NAVIGATION_TIMEOUT_MS:
            # Exploration navigated with Playwright's 30 s default; the artifact must too,
            # or a slow real site fails replay on its very first edge.
            action = action.model_copy(update={"timeout_ms": NAVIGATION_TIMEOUT_MS})
        if isinstance(action, WaitAction) and action.seconds >= DWELL_MIN_SLICED_S:
            # Dwell as bounded Repeat of 1 s slices: the interrupt sweep runs between slices,
            # so an ad striking mid-dwell is handled without splitting an atomic action.
            slices = max(1, round(action.seconds / DWELL_SLICE_S))
            slice_action = action.model_copy(update={"seconds": DWELL_SLICE_S})
            transitions.append(Transition(id=f"t{i}", source=states[-2].id, target=state_id, action=slice_action))
            control.append(EdgeStep(edge=f"t{i}"))
            if slices > 1:
                transitions.append(
                    Transition(id=f"t{i}_dwell", source=state_id, target=state_id, action=slice_action)
                )
                control.append(Repeat(body=[EdgeStep(edge=f"t{i}_dwell")], max_iterations=slices - 1))
        else:
            transitions.append(Transition(id=f"t{i}", source=states[-2].id, target=state_id, action=action))
            control.append(EdgeStep(edge=f"t{i}"))

    interrupts: list[Interrupt] = []
    for k, intr in enumerate(interruption_steps, 1):
        sel = _target_selector(intr.action)  # non-None by _is_interruption
        anchor_state = f"i{k}"
        done_state = f"i{k}_done"
        states.append(State(id=anchor_state, conditions=[{"type": "selector_visible", "selector": sel}]))
        states.append(State(id=done_state, conditions=[{"type": "selector_hidden", "selector": sel}]))
        transitions.append(Transition(id=f"ti{k}", source=anchor_state, target=done_state, action=intr.action))
        base = _base_url(intr.url)
        scope = [sid for sid, b in state_base.items() if b == base]
        if not scope:  # interruption on a page no main state lives on — arm it where it happened
            prior = [j for j, s in enumerate(steps, 1) if s.n < intr.n]
            scope = [f"s{prior[-1]}" if prior else "init"]
        interrupts.append(
            Interrupt(id=f"int{k}", state=anchor_state, resolve=[f"ti{k}"], scope=scope, max_fires=3)
        )

    uses_program = interrupts or any(isinstance(n, Repeat) for n in control)
    wf = Workflow(
        name=name,
        version=version,
        description=traj.task,
        start_state="init",
        states=states,
        transitions=transitions,
        # A plain linear run keeps the legacy control_sequence shape; repeats/interrupts
        # need the richer control program.
        control=control if uses_program else None,
        control_sequence=None if uses_program else [n.edge for n in control],
        interrupts=interrupts,
    )

    if params:
        wf = _bind_params(wf, steps, params, warnings if warnings is not None else [])
    return wf


_VALUE_FIELD = {"fill": "text", "select": "value", "goto": "url"}  # the action field a param lands in


def _bind_params(wf: Workflow, steps: list, params: dict[str, str], warnings: list[str]) -> Workflow:
    data = wf.model_dump(mode="json")
    bound: dict[str, int] = dict.fromkeys(params, 0)

    def sub_literal(text: str, pname: str, value: str, escaped: bool = False) -> tuple[str, int]:
        """Replace the sample (literal + URL-encoded forms) by ${pname}; `escaped` matches the
        re.escape'd forms, which is how a state's url_matches pattern carries them."""
        n_total = 0
        for form in (value, quote_plus(value)):
            needle = re.escape(re.escape(form) if escaped else form)
            text, n = re.subn(needle, "${" + pname + "}", text, flags=re.IGNORECASE)
            n_total += n
        return text, n_total

    # 1. Structural: the explorer declared which step carried which parameter.
    # Steps pair with the word's primary edges t1..tN only — dwell twins (t{i}_dwell)
    # and interrupt resolutions (ti{k}) are compiler-synthesized and carry no step.
    word_edges = [tr for tr in data["transitions"] if re.fullmatch(r"t\d+", tr["id"])]
    for step, tr in zip(steps, word_edges, strict=True):
        pname = getattr(step, "param", None)
        if not pname:
            continue
        if pname not in params:
            warnings.append(f"step {step.n}: declared param {pname!r} is not a known parameter {sorted(params)}")
            continue
        value, placeholder, action = params[pname], "${" + pname + "}", tr["action"]
        field = _VALUE_FIELD.get(action["type"])
        if field == "url":
            new, n = sub_literal(action["url"], pname, value)
            if n:
                action["url"], bound[pname] = new, bound[pname] + 1
            else:
                warnings.append(
                    f"step {step.n}: tagged goto as {placeholder} but the sample {value!r} is not in {action['url']!r}"
                )
        elif field is not None:
            typed = action[field]
            if typed.strip().lower() != value.strip().lower():
                warnings.append(
                    f"step {step.n}: explorer tagged this {action['type']} as {placeholder} but typed {typed!r}, "
                    f"not the sample {value!r} — bound to the placeholder anyway"
                )
            action[field], bound[pname] = placeholder, bound[pname] + 1
        # A locator whose name IS the sample value (a link named after the channel) — whole
        # value only, never a substring, and only on the step that declared the param.
        for ls in action.get("locator") or []:
            for k, v in list(ls.get("kwargs", {}).items()):
                if isinstance(v, str) and v.strip().lower() == value.strip().lower():
                    ls["kwargs"][k], bound[pname] = placeholder, bound[pname] + 1
            ls["args"] = [
                placeholder if isinstance(a, str) and a.strip().lower() == value.strip().lower() else a
                for a in ls.get("args", [])
            ]
        if field is None and not any(placeholder in str(ls) for ls in action.get("locator") or []):
            warnings.append(
                f"step {step.n}: param {placeholder} declared on a {action['type']} action carrying no value — ignored"
            )

    # 2. Fallback: the literal sweep over value fields and state conditions (not locators).
    # Longest sample values first, so overlapping values substitute correctly; case-insensitive
    # because sites re-case what was typed and Playwright's role-name matching is too.
    ordered = sorted(params.items(), key=lambda kv: -len(kv[1]))
    for tr in data["transitions"]:
        action = tr["action"]
        for field in ("text", "value", "url"):
            if isinstance(action.get(field), str):
                for pname, value in ordered:
                    action[field], n = sub_literal(action[field], pname, value)
                    bound[pname] += n
    for st in data["states"]:
        for cond in st.get("conditions", []):
            if isinstance(cond.get("pattern"), str):
                for pname, value in ordered:
                    cond["pattern"], n = sub_literal(cond["pattern"], pname, value, escaped=True)
                    bound[pname] += n

    for pname, n in bound.items():
        if n == 0:
            warnings.append(
                f"parameter {pname!r} was never bound: no step declared param={pname!r} and the sample "
                f"{params[pname]!r} appears in no action value or state condition — replay will not vary it"
            )
    data["params"] = [
        Param(name=n, default=v, description=f"exploration used {v!r}").model_dump(mode="json")
        for n, v in params.items()
    ]
    return Workflow.model_validate(data)
