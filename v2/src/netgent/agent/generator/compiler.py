"""Compile an agent trajectory into a workflow (NFA): Discovery -> artifact.

Each successful action step becomes one transition; the state after each step is
recognized by the (query-stripped) URL it landed on. Sample values the caller names
become ${name} parameters, so the compiled workflow replays for other values:

    traj = await ExplorerAgent(...).run(session, task)
    wf = compile_trajectory(traj, name="twitch-live", params={"channel": "monstercat"})
    # netgent run wf.yaml --param channel=bobross
"""

import re
from urllib.parse import quote_plus

from netgent.agent.explorer.models import AgentTrajectory
from netgent.browser.locators import is_volatile_selector
from netgent.schema.actions import (
    Action,
    ClickAction,
    FillAction,
    GotoAction,
    HoverAction,
    Locator,
    SelectAction,
    UploadFileAction,
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

# Media gating: a state whose capture-time reading showed the CONTENT playing gets a
# media_playing(min_duration_s=…) condition, so a replay cannot spend its dwells/seeks on an
# ad playing in the same element (measured: three +10s seeks no-op'd into a 90 s ad while
# every selector condition held). The threshold is a heuristic ad/content separator:
# half the content's duration, capped — most ads are <= 90 s; a parameterized replay may
# play different content, so the gate must not demand the captured duration exactly.
MEDIA_GATE_MIN_CONTENT_S = 30.0  # content shorter than this can't be told from an ad — no gate
MEDIA_GATE_CAP_S = 120.0
MEDIA_GATE_TIMEOUT_MS = 130_000  # a gated state may legitimately wait out an unskippable ad

_MEDIA_READING_RE = re.compile(r"\b(video|audio) (PLAYING|PAUSED|ENDED) at (\d+):(\d{2})(?: / (\d+):(\d{2}))?")


def _base_url(url: str) -> str:
    """URL without query/fragment — the stable part worth recognizing a state by."""
    return url.split("#", 1)[0].split("?", 1)[0]


def _anchor(action: Action) -> dict | None:
    """A selector_visible condition on the very locator chain `action` resolves — the anchor a
    state carries for the edge that acts next.

    The chain itself is the condition (schema/triggers.py `_ElementTrigger.locator`): the
    trigger engine resolves it through the same `LocatorResolver` the action uses, so the
    anchor holds exactly when the edge's element is there — role/name matching, `exact`,
    frame steps and `nth` included. Rendering the chain to a selector string cannot promise
    that: Playwright's public `role=` engine matches `[name="…" i]` exactly, `get_by_role`
    by substring, and Playwright's own selector generator shortens names to a ≤30-character
    word prefix that only substring matching satisfies (archive.org replay failed on its
    first edge this way; docs/research/media-platforms-eval.md).

    Uploads are not anchored: `set_input_files` works on hidden file inputs, and custom upload
    widgets hide the real input on purpose — "its element is visible" is not a sound guard.
    """
    locator = getattr(action, "locator", None)
    if not locator or isinstance(action, UploadFileAction):
        return None
    return {"type": "selector_visible", "locator": [step.model_dump(mode="json") for step in locator]}


def _hidden(action: Action) -> dict:
    """selector_hidden on the same chain — an interrupt's resolution state (the overlay is gone)."""
    return {"type": "selector_hidden", "locator": [step.model_dump(mode="json") for step in action.locator]}


def _locator_selector(locator: Locator) -> str | None:
    """A readable selector-string rendering of a single-step chain, or None — for CLASSIFYING
    and REPORTING a target (interrupt detection, volatile-id warnings, merge keys), never for
    evaluating one: the `role=` form is only a label (its name match is exact where
    get_by_role's is substring), which is why anchors carry the chain itself (`_anchor`).
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
        return f'role={role}[name="{escaped}" i]'
    return None


def _target_selector(action: Action) -> str | None:
    """The selector label of the element the action acts on, when it has one (see `_locator_selector`)."""
    locator = getattr(action, "locator", None)
    return _locator_selector(locator) if locator else None


def _media_readings(step) -> list[tuple[str, int | None]]:
    """(state, duration_s) per media reading recorded on the step ("video PLAYING at 0:21 / 8:35")."""
    if not getattr(step, "media", None):
        return []
    return [
        (m.group(2), int(m.group(5)) * 60 + int(m.group(6)) if m.group(5) else None)
        for m in _MEDIA_READING_RE.finditer(step.media)
    ]


def _gate_media_states(states: list[State], steps: list) -> None:
    """Add media_playing gates to main-path states whose capture-time reading showed the
    content playing.

    A step's `media` is the reading taken just BEFORE it ran, i.e. it describes the step's
    SOURCE state — states[i-1] for step i (states[0] is init, never gated). The content's
    duration is the longest duration observed on the main path (ads playing in the same
    element are shorter); states observed with the content PLAYING are gated on
    "media at least min_duration_s long is playing", which an ad cannot satisfy. States
    observed PAUSED (a pause phase) or during an ad are left ungated on purpose.
    """
    from netgent.schema.triggers import MediaPlaying

    durations = [d for step in steps for _, d in _media_readings(step) if d is not None]
    if not durations:
        return
    content_s = max(durations)
    if content_s < MEDIA_GATE_MIN_CONTENT_S:
        return  # content indistinguishable from an ad by length — an exact gate would overfit
    threshold = min(round(content_s / 2), MEDIA_GATE_CAP_S)
    for i, step in enumerate(steps, 1):
        if i == 1:  # states[0] is init: pre-goto, nothing to gate
            continue
        if any(s == "PLAYING" and d is not None and d >= threshold for s, d in _media_readings(step)):
            state = states[i - 1]
            state.conditions = [*state.conditions, MediaPlaying(min_duration_s=float(threshold))]
            # Recognition may legitimately have to wait out an unskippable ad.
            state.timeout_ms = max(state.timeout_ms, MEDIA_GATE_TIMEOUT_MS)


def is_interruption_step(step) -> bool:
    """A click that dismisses an overlay (ad-skip, cookie wall, pop-up): the step's reasoning
    AND its click target must both look like interruption handling — reasoning alone flagged a
    seek-slider click (v3 run, 2026-08-27). Shared with the multi-run merge, where cross-run
    presence is the primary interrupt signal and this stays the single-run/tie-break rule."""
    if step.action is None or step.action.type != "click" or not _INTERRUPTION_RE.search(step.reasoning or ""):
        return False
    sel = _target_selector(step.action)
    return sel is not None and bool(_INTERRUPTION_TARGET_RE.search(sel))


def compile_trajectory(
    traj: AgentTrajectory,
    name: str,
    params: dict[str, str] | None = None,
    version: str = "1",
    warnings: list[str] | None = None,
) -> Workflow:
    """Compile the trajectory's successful action steps into a replayable Workflow.

    `params` maps a param name to the sample value used during exploration. Binding is a
    case-insensitive literal sweep over value fields and state conditions — never inside
    locators, where substring matches over-abstracted names. Anything the compiler could not
    bind is reported in `warnings` (appended in place) instead of failing silently.
    """
    all_steps = [s for s in traj.steps if s.action is not None and s.error is None]
    if not all_steps:
        raise ValueError("trajectory has no successful action steps to compile")

    # Interruption-handling clicks (ad-skip, cookie-dismiss, …) leave the main word and
    # become scoped ε-interrupts: the executor fires them whenever their anchor holds,
    # so a replay that gets no ad (or an ad at a different moment) still walks the word.
    interruption_steps = [s for s in all_steps if is_interruption_step(s)]
    steps = [s for s in all_steps if not is_interruption_step(s)]
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
        # Anchor the state on the NEXT edge's target element (its very locator chain, frame
        # steps included — an embedded document being ready is not expressible by the URL):
        # recognition (up to the state's timeout) then gates that edge on the page being ready
        # for it, replacing blind sleeps and races. docs/browser-layer-design.md §3: every
        # fixed sleep is a trigger that couldn't be expressed — this expresses it.
        if i < len(steps) and (anchor := _anchor(steps[i].action)) is not None:
            conditions.append(anchor)
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

    _gate_media_states(states, steps)

    interrupts: list[Interrupt] = []
    for k, intr in enumerate(interruption_steps, 1):
        sel = _target_selector(intr.action)  # non-None by is_interruption_step
        if is_volatile_selector(sel) and warnings is not None:
            # An interrupt exists to fire on a FUTURE instance of its overlay; a per-mount
            # id (`#skip-button\:2`) can never match one. The capture ladder avoids these,
            # so reaching here means no semantic candidate existed — say so loudly.
            warnings.append(
                f"interrupt int{k} is anchored on {sel!r}, which looks machine-generated "
                "(per-session id) — it will likely never fire on replay"
            )
        anchor_state = f"i{k}"
        done_state = f"i{k}_done"
        states.append(State(id=anchor_state, conditions=[_anchor(intr.action)]))
        states.append(State(id=done_state, conditions=[_hidden(intr.action)]))
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

    # The literal sweep over value fields and state conditions (never locators): the sample value
    # the caller named, wherever the explorer typed or reached it, becomes the placeholder.
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
                f"parameter {pname!r} was never bound: the sample {params[pname]!r} appears in no action value "
                "or state condition — replay will not vary it"
            )
    data["params"] = [
        Param(name=n, default=v, description=f"exploration used {v!r}").model_dump(mode="json")
        for n, v in params.items()
    ]
    return Workflow.model_validate(data)
