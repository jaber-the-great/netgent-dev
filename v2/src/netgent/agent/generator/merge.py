"""Merge N same-task trajectories into ONE generalized workflow — pure code, zero LLM.

The typed-key merge of docs/research/trajectory-memory.md §C.1: align the achieved runs'
steps on (action type, durable target key) with a small sequence alignment, then:

- **conditions by version-space intersection** — a trigger is emitted only if it held in
  EVERY achieved run at that column (URL bases equal, anchors identical, dialogs equal
  after value masking), with a support count recorded per column;
- **divergence has four dispositions**:
  1. value varies at an aligned column and matches a planner-proposed value in every run
     → a ``Param`` under the planner's name (``${video_query}``, ``Repeat.count="${watch_time}"``);
  2. a step present in k < N runs whose target looks like a dismissal control
     → an ``Interrupt`` candidate (cross-run presence is the primary signal; the single-run
     text heuristics are the tie-break);
  3. runs genuinely diverge downstream and each continuation's first target distinguishes
     them → a ``Branch`` with one arm per continuation, guarded by those targets;
  4. anything else → **reject**, with a warning naming the column: a full-support column
     keeps run 1's version (every run did it — required, just value-dependent), while a
     minority-run step is dropped (the other runs achieved the task without it — the
     structural intersection). Another run may overrule either call.

Failed runs contribute NOTHING structural. Failures may one day mine *conditions*; they must
never mine transitions — trajectory-shaped memory is poisoned by failures (AWM 44.4→42.2 with
failures) while condition-shaped memory is helped (trajectory-memory.md §B.5). Do not
"improve" this by copying fallback actions out of failed runs.
"""

import json
import re
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import (
    _INTERRUPTION_RE,
    _INTERRUPTION_TARGET_RE,
    DWELL_MIN_SLICED_S,
    DWELL_SLICE_S,
    NAVIGATION_TIMEOUT_MS,
    _anchor,
    _base_url,
    _hidden,
    _target_selector,
    compile_trajectory,
    is_interruption_step,
)
from netgent.schema.actions import Action, GotoAction, LocatorStep, NoopAction, WaitAction
from netgent.schema.control import Branch, BranchArm, ControlNode, EdgeStep, Interrupt, Param, Repeat
from netgent.schema.workflow import State, Transition, Workflow

# Action types where a same-type / different-target column is a meaningful substitution
# (the same intent aimed at a different element) rather than an accident of alignment.
_SUBSTITUTABLE = frozenset({"click", "fill", "select", "hover", "press", "goto", "upload_file"})
# Value-carrying action fields the param inference inspects (never locators, never keys).
_VALUE_FIELDS = ("text", "value", "url", "seconds")
_MIN_VALUE_LEN = 2  # a 1-char value substitutes everywhere; refuse to infer from it


# ── inputs / outputs ─────────────────────────────────────────────────────────


class RunInput(BaseModel):
    """One exploration run, as the merge consumes it."""

    run: int  # 1-based; run 1 is the spine (its values become the params' defaults)
    trajectory: AgentTrajectory
    values: dict[str, str] = Field(default_factory=dict)  # planner-proposed name -> this run's value
    achieved: bool = True  # the verifier's call; only achieved runs form the merge spine


class ColumnReport(BaseModel):
    """One aligned column's disposition — the merge's evidence trail."""

    index: int
    # aligned | param | param-target | interrupt | branch | dropped | value-diverges | target-varies
    disposition: str
    support: int
    runs: list[int]
    action_type: str
    target: str | None = None
    param: str | None = None
    note: str = ""


class ParamReport(BaseModel):
    name: str
    default: str  # the spine run's value
    values_by_run: dict[int, str] = Field(default_factory=dict)


class GeneralizedTrajectory(BaseModel):
    """The induced cross-run memory, written to <name>.trajectories/generalized.json."""

    task: str
    runs: int
    achieved_runs: list[int]
    params: list[ParamReport] = Field(default_factory=list)
    columns: list[ColumnReport] = Field(default_factory=list)
    interrupts: list[dict] = Field(default_factory=list)  # {selector, support, runs}
    branches: list[dict] = Field(default_factory=list)  # {guards, runs_by_arm}
    warnings: list[str] = Field(default_factory=list)


class MergeOutcome(BaseModel):
    workflow: Workflow
    generalized: GeneralizedTrajectory


# ── the alignment ────────────────────────────────────────────────────────────


class _Column:
    def __init__(self, steps: dict[int, AgentStep]):
        self.steps = steps  # run id -> that run's step at this column

    def sigs(self) -> set[tuple]:
        return {_sig(s) for s in self.steps.values()}

    def types(self) -> set[str]:
        return {s.action.type for s in self.steps.values()}


def _canonical_locator(action: Action) -> str:
    """A stable key for a locator chain, even when it is not expressible as one selector."""
    sel = _target_selector(action)
    if sel is not None:
        return sel
    locator = getattr(action, "locator", None)
    if not locator:
        return ""
    return json.dumps([step.model_dump() for step in locator], sort_keys=True)


def _sig(step: AgentStep) -> tuple:
    """The typed alignment key: (action type, durable target key) — value fields excluded,
    so the same step with a different query/duration still aligns (AWM's abstract-trajectory
    signature with a durable locator instead of a volatile a11y id)."""
    action = step.action
    if isinstance(action, GotoAction):
        return ("goto", _base_url(action.url))
    if action.type == "press":
        return ("press", action.keys, _canonical_locator(action))
    if action.type == "scroll":
        return ("scroll", action.down)
    if action.type in ("wait", "noop", "go_back"):
        return (action.type,)
    return (action.type, _canonical_locator(action))


def _target_shape(action: Action) -> tuple:
    """How the target is addressed: (last locator fn, role) — nth disambiguation ignored."""
    locator = getattr(action, "locator", None)
    if not locator:
        return (action.type,)
    last = locator[-1]
    if last.fn == "nth" and len(locator) >= 2:
        last = locator[-2]
    role = str(last.args[0]) if last.fn == "get_by_role" and last.args else None
    return (last.fn, role)


Effect = tuple[bool, str]  # (did the step change the page's base URL, the base it landed on)


def _step_effects(seqs: dict[int, list[AgentStep]]) -> dict[int, Effect]:
    """Per step (by identity): what it DID to the page — the discriminator locator shape
    can't provide. Measured on YouTube: run A clicks a video as a role link, run B as
    `a >> filter(has_text)` — shapes differ, but both navigate results → watch, while run
    A's play-button click (same type, same page) must not absorb either."""
    eff: dict[int, Effect] = {}
    for steps in seqs.values():
        prev: str | None = None
        for s in steps:
            post = _base_url(s.url)
            eff[id(s)] = (prev is None or post != prev, post)
            prev = post
    return eff


def _match_score(col: _Column, step: AgentStep, eff: dict[int, Effect]) -> int:
    if _sig(step) in col.sigs():
        return 3
    if step.action.type in col.types() and step.action.type in _SUBSTITUTABLE:
        # Same intent aimed at a different element — a substitution column. Rank the pairing
        # by evidence: locator shape (both role=link, both css, …) and URL effect each count;
        # a pairing with neither is worth nothing and loses to any real partner.
        best = 0
        for s in col.steps.values():
            if s.action.type != step.action.type:
                continue
            same_shape = _target_shape(s.action) == _target_shape(step.action)
            same_effect = eff.get(id(s)) == eff.get(id(step))
            best = max(best, 2 if (same_shape and same_effect) else (1 if (same_shape or same_effect) else 0))
        return best
    return -10  # never align across action types


def _align_one(cols: list[_Column], rid: int, steps: list[AgentStep], eff: dict[int, Effect]) -> list[_Column]:
    """Needleman-Wunsch of one run against the running column list (gap = -1)."""
    gap = -1
    n, m = len(cols), len(steps)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * gap
    for j in range(1, m + 1):
        dp[0][j] = j * gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = max(
                dp[i - 1][j - 1] + _match_score(cols[i - 1], steps[j - 1], eff),
                dp[i - 1][j] + gap,
                dp[i][j - 1] + gap,
            )
    out: list[_Column] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + _match_score(cols[i - 1], steps[j - 1], eff):
            col = cols[i - 1]
            col.steps[rid] = steps[j - 1]
            out.append(col)
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + gap:
            out.append(cols[i - 1])
            i -= 1
        else:
            out.append(_Column({rid: steps[j - 1]}))
            j -= 1
    out.reverse()
    return out


def _align(seqs: dict[int, list[AgentStep]]) -> list[_Column]:
    run_ids = sorted(seqs)
    eff = _step_effects(seqs)
    cols = [_Column({run_ids[0]: s}) for s in seqs[run_ids[0]]]
    for rid in run_ids[1:]:
        cols = _align_one(cols, rid, seqs[rid], eff)
    return cols


# ── param inference ──────────────────────────────────────────────────────────


def _run_value_forms(value: str) -> tuple[str, ...]:
    return (value, quote_plus(value))


def _number_in(value: str) -> float | None:
    """The number a natural-language value carries ("5 seconds" → 5.0), or None."""
    m = re.search(r"\d+(?:\.\d+)?", value)
    return float(m.group()) if m else None


def _field_matches_value(field_value: object, value: str, field: str) -> bool:
    if field == "seconds":
        n = _number_in(value)
        try:
            return n is not None and n == float(field_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if not isinstance(field_value, str):
        return False
    if field == "url":
        return any(form.lower() in field_value.lower() for form in _run_value_forms(value))
    return any(field_value.lower() == form.lower() for form in _run_value_forms(value))


def _confirm_param(col: _Column, field: str, values_by_run: dict[int, dict[str, str]]) -> str | None:
    """The planner-proposed name whose per-run values explain this column's differing field
    values — confirmed only if every run matches AND the observed values actually vary."""
    per_run = {rid: getattr(s.action, field, None) for rid, s in col.steps.items()}
    for name in sorted(values_by_run[min(values_by_run)]):
        declared = {rid: values_by_run[rid].get(name, "") for rid in col.steps}
        # Too-short values substitute everywhere in a string; numeric fields compare, not
        # substitute, so "5" is a fine watch_time.
        if field != "seconds" and any(len(v) < _MIN_VALUE_LEN for v in declared.values()):
            continue
        if any(not v for v in declared.values()):
            continue
        if len({v.lower() for v in declared.values()}) < 2:
            continue  # constant across runs: not a parameter, just a value
        if all(_field_matches_value(per_run[rid], declared[rid], field) for rid in col.steps):
            return name
    return None


def _sub_value(text: str, value: str, name: str) -> str:
    for form in _run_value_forms(value):
        text = re.sub(re.escape(form), "${" + name + "}", text, flags=re.IGNORECASE)
    return text


def _generalize_target(col: _Column, values_by_run: dict[int, dict[str, str]]) -> tuple[Action, str] | None:
    """A same-type column whose per-run targets are role locators with names that each
    CONTAIN that run's value of one varying param → get_by_role(role, name="${param}") + nth(0)
    ("the first <role> naming the value" — Playwright's role-name match is a case-insensitive
    substring). Returns (canonical action, param name), or None when the evidence is thinner."""
    roles: set[str] = set()
    names: dict[int, str] = {}
    frames: dict[int, list[LocatorStep]] = {}
    for rid, s in col.steps.items():
        locator = getattr(s.action, "locator", None)
        if not locator:
            return None
        last = locator[-1]
        if last.fn != "get_by_role" or not last.args or "name" not in last.kwargs:
            return None
        roles.add(str(last.args[0]))
        names[rid] = str(last.kwargs["name"])
        frames[rid] = [st for st in locator[:-1]]
        if any(st.fn == "nth" for st in locator):  # already disambiguated: too specific to rewrite
            return None
    if len(roles) != 1:
        return None
    for name in sorted(values_by_run[min(values_by_run)]):
        declared = {rid: values_by_run[rid].get(name, "") for rid in col.steps}
        if any(len(v) < 3 for v in declared.values()):
            continue
        if len({v.lower() for v in declared.values()}) < 2:
            continue
        if all(declared[rid].lower() in names[rid].lower() for rid in col.steps):
            spine_rid = min(col.steps)
            chain = [
                *frames[spine_rid],
                LocatorStep(fn="get_by_role", args=[roles.pop()], kwargs={"name": "${" + name + "}"}),
                LocatorStep(fn="nth", args=[0]),
            ]
            action = col.steps[spine_rid].action.model_copy(update={"locator": chain})
            return action, name
    return None


# ── emit plan (columns/regions → an ordered program) ─────────────────────────


class _EmitStep:
    def __init__(self, action: Action, col: _Column, *, anchor_ok: bool, param: str | None = None,
                 dwell_param: str | None = None, dwell_bound: int = 0):
        self.action = action
        self.col = col
        self.anchor_ok = anchor_ok  # may the PREVIOUS state anchor on this step's target?
        self.param = param
        self.dwell_param = dwell_param  # a parameterized dwell: Repeat(count="${param}")
        self.dwell_bound = dwell_bound


class _EmitBranch:
    def __init__(self, arms: list[tuple[dict, list[AgentStep]]], runs_by_arm: list[list[int]]):
        self.arms = arms  # (guard condition — selector_visible on the arm's first target, that continuation's steps)
        self.runs_by_arm = runs_by_arm


def _dismissal_step(step: AgentStep) -> bool:
    """The merge's relaxed interrupt test: target OR reasoning looks like dismissal — the
    cross-run presence gap is the other half of the signal (single runs need both)."""
    if step.action is None or step.action.type != "click":
        return False
    sel = _target_selector(step.action)
    if sel is None:
        return False
    return bool(_INTERRUPTION_TARGET_RE.search(sel)) or bool(_INTERRUPTION_RE.search(step.reasoning or ""))


def _solid(col: _Column, n_runs: int) -> bool:
    return len(col.steps) == n_runs and len(col.sigs()) == 1


def merge_trajectories(
    runs: list[RunInput],
    name: str,
    version: str = "1",
    warnings: list[str] | None = None,
) -> MergeOutcome:
    """The merge: achieved runs in, one generalized Workflow + its evidence trail out.

    With one achieved run this degrades to `compile_trajectory` with the planner's values as
    the literal-sweep params (today's single-run behaviour); with none it raises.
    """
    warnings = warnings if warnings is not None else []
    achieved = [r for r in runs if r.achieved]
    if not achieved:
        raise ValueError("no achieved runs to merge — nothing forms the spine")
    task = achieved[0].trajectory.task
    if len(achieved) == 1:
        warnings.append("only one achieved run: single-run compile; params bound by literal sweep, unconfirmed")
        wf = compile_trajectory(
            achieved[0].trajectory, name, params=achieved[0].values or None, version=version, warnings=warnings
        )
        generalized = GeneralizedTrajectory(
            task=task, runs=len(runs), achieved_runs=[achieved[0].run],
            params=[ParamReport(name=p.name, default=p.default or "", values_by_run={achieved[0].run: p.default or ""})
                    for p in wf.params],
            warnings=list(warnings),
        )
        return MergeOutcome(workflow=wf, generalized=generalized)

    values_by_run = {r.run: dict(r.values) for r in achieved}
    spine_rid = achieved[0].run
    n_runs = len(achieved)

    mains: dict[int, list[AgentStep]] = {}
    interrupt_cands: list[tuple[int, AgentStep]] = []  # (support hint, step) — support filled later
    for r in achieved:
        steps = [s for s in r.trajectory.steps if s.action is not None and s.error is None]
        for s in steps:
            if is_interruption_step(s):
                interrupt_cands.append((r.run, s))
        mains[r.run] = [s for s in steps if not is_interruption_step(s)]

    columns = _align(mains)
    reports: list[ColumnReport] = []
    confirmed: dict[str, ParamReport] = {}
    branches_report: list[dict] = []

    def report(i: int, col: _Column, disposition: str, param: str | None = None, note: str = "") -> None:
        spine_step = col.steps.get(spine_rid) or col.steps[min(col.steps)]
        reports.append(ColumnReport(
            index=i, disposition=disposition, support=len(col.steps), runs=sorted(col.steps),
            action_type=spine_step.action.type, target=_target_selector(spine_step.action),
            param=param, note=note,
        ))

    def confirm(name: str, col: _Column) -> None:
        if name not in confirmed:
            confirmed[name] = ParamReport(
                name=name, default=values_by_run[spine_rid].get(name, ""),
                values_by_run={rid: values_by_run[rid].get(name, "") for rid in values_by_run},
            )

    # Pass 1: columns → emit plan. Regions of non-solid columns are examined together so a
    # genuine fork becomes ONE Branch instead of a pile of per-column warnings.
    emits: list[_EmitStep | _EmitBranch] = []
    i = 0
    while i < len(columns):
        col = columns[i]
        if _solid(col, n_runs):
            emits.append(_make_emit(col, spine_rid, values_by_run, confirmed, confirm, report, warnings, i))
            i += 1
            continue
        # a non-solid region: [i, j)
        j = i
        while j < len(columns) and not _solid(columns[j], n_runs):
            j += 1
        region = columns[i:j]
        # A single full-support column is a substitution (param-target / target-varies),
        # never a fork — a Branch with one arm per run's target would freeze the values.
        branch = None
        if len(region) > 1 or len(region[0].steps) < n_runs:
            branch = _try_branch(region, n_runs, sorted(values_by_run))
        if branch is not None:
            emits.append(branch)
            for k, c in enumerate(region):
                report(i + k, c, "branch", note="one arm per observed continuation")
            branches_report.append({
                "guards": [g for g, _ in branch.arms],
                "runs_by_arm": branch.runs_by_arm,
                "columns": list(range(i, j)),
            })
            i = j
            continue
        # no branch: handle the region column by column
        for k, c in enumerate(region):
            idx = i + k
            if len(c.steps) == n_runs:  # full support, targets differ (substitution column)
                emits.append(_make_emit(c, spine_rid, values_by_run, confirmed, confirm, report, warnings, idx))
                continue
            # a gap column: present in k < N runs
            some = c.steps[min(c.steps)]
            if _dismissal_step(some):
                for rid in c.steps:
                    interrupt_cands.append((rid, c.steps[rid]))
                report(idx, c, "interrupt", note=f"present in {len(c.steps)}/{n_runs} runs, dismissal-shaped")
                continue
            # Structural intersection: the runs WITHOUT this step still achieved the task,
            # so it is not required — drop it, whether or not the spine had it. (Measured on
            # YouTube: keeping run-1-only steps put a suggestion click and a play click in
            # the word, and both timed out at replay; the majority path replays.)
            report(idx, c, "dropped", note=f"present in {len(c.steps)}/{n_runs} runs, removable")
            if some.action.type not in ("scroll", "wait"):
                warnings.append(
                    f"column {idx}: {some.action.type} present in {len(c.steps)}/{n_runs} runs — the other "
                    "runs achieved the task without it; dropped (another run can overrule this)"
                )
        i = j

    if not any(isinstance(e, _EmitStep) for e in emits):
        raise ValueError("merge produced no main-path steps")

    # Pass 2: emit plan → workflow.
    wf = _compile_emits(
        emits, interrupt_cands, name=name, version=version, task=task,
        n_runs=n_runs, run_values=values_by_run, confirmed=confirmed,
    )
    generalized = GeneralizedTrajectory(
        task=task, runs=len(runs), achieved_runs=[r.run for r in achieved],
        params=sorted(confirmed.values(), key=lambda p: p.name),
        columns=reports,
        interrupts=[
            {"selector": intr_sel, "support": support, "runs": sorted(rids)}
            for intr_sel, (support, rids) in _interrupt_summary(interrupt_cands).items()
        ],
        branches=branches_report,
        warnings=list(warnings),
    )
    return MergeOutcome(workflow=wf, generalized=generalized)


def _make_emit(col, spine_rid, values_by_run, confirmed, confirm, report, warnings, idx) -> _EmitStep:
    """Classify one full-support column: aligned / param / param-target / value-diverges /
    target-varies — and build its canonical action (spine's, with ${param} substituted)."""
    spine_step = col.steps.get(spine_rid) or col.steps[min(col.steps)]
    action = spine_step.action
    if len(col.sigs()) > 1:
        generalized = _generalize_target(col, values_by_run)
        if generalized is not None:
            action, pname = generalized
            confirm(pname, col)
            report(idx, col, "param-target", param=pname,
                   note="role-name targets each contain that run's value; rewrote to name=${%s} + nth(0)" % pname)
            return _EmitStep(action, col, anchor_ok=True, param=pname)
        report(idx, col, "target-varies", note="same action, different targets; kept run 1's")
        warnings.append(
            f"column {idx}: {action.type} targets differ across runs and match no planned value — "
            "kept run 1's selector; replay with other values may not find it"
        )
        return _EmitStep(action, col, anchor_ok=False)
    # one sig: targets agree; do the value fields?
    for field in _VALUE_FIELDS:
        per_run = {rid: getattr(s.action, field, None) for rid, s in col.steps.items()}
        if any(v is None for v in per_run.values()) or len({str(v).lower() for v in per_run.values()}) < 2:
            continue
        pname = _confirm_param(col, field, values_by_run)
        if pname is None:
            report(idx, col, "value-diverges",
                   note=f"{field} differs across runs and matches no planned value; kept run 1's")
            warnings.append(
                f"column {idx}: {action.type}.{field} differs across runs ({sorted(set(map(str, per_run.values())))}) "
                "and matches no planned value — kept run 1's"
            )
            return _EmitStep(action, col, anchor_ok=True)
        confirm(pname, col)
        if field == "seconds":
            # The param feeds Repeat.count, so its stored values must be bare numbers even
            # when the planner wrote "10 seconds" — the count is 1 s slices.
            rep = confirmed[pname]

            def _num_str(v: str) -> str:
                n = _number_in(v)
                return v if n is None else (str(int(n)) if n == int(n) else str(n))

            rep.default = _num_str(rep.default)
            rep.values_by_run = {rid: _num_str(v) for rid, v in rep.values_by_run.items()}
            observed = max(int(float(v)) for v in per_run.values())  # type: ignore[arg-type]
            report(idx, col, "param", param=pname, note=f'dwell parameterized: Repeat(count="${{{pname}}}")')
            return _EmitStep(action, col, anchor_ok=True, param=pname,
                            dwell_param=pname, dwell_bound=max(60, 3 * observed))
        value = values_by_run[spine_rid].get(pname, "")
        action = action.model_copy(update={field: _sub_value(getattr(action, field), value, pname)})
        report(idx, col, "param", param=pname, note=f"{field} varies with {pname}")
        return _EmitStep(action, col, anchor_ok=True, param=pname)
    report(idx, col, "aligned")
    return _EmitStep(action, col, anchor_ok=True)


def _try_branch(region: list[_Column], n_runs: int, run_ids: list[int]) -> _EmitBranch | None:
    """A Branch from a divergence region: every run covered, ≥2 distinct continuations, and
    each continuation's FIRST target selector is expressible and distinct (it becomes the
    guard — the state whose conditions distinguish the runs).

    Presence-based ONLY: every region column must be a gap (each run walks its own steps —
    the login-wall shape, where run 1 fills credentials the wall never showed run 2). A
    full-support substitution column in the region is value variance, not a fork — a Branch
    guarded on per-run targets would freeze the observed values into the artifact."""
    if any(len(col.steps) == n_runs for col in region):
        return None
    per_run: dict[int, list[AgentStep]] = {rid: [] for rid in run_ids}
    for col in region:
        for rid, step in col.steps.items():
            per_run[rid].append(step)
    if any(not steps for steps in per_run.values()):
        return None  # a run skips the region entirely: optional segment, not a fork
    groups: dict[tuple, list[int]] = {}
    for rid, steps in sorted(per_run.items()):
        groups.setdefault(tuple(_sig(s) for s in steps), []).append(rid)
    if len(groups) < 2:
        return None
    arms: list[tuple[dict, list[AgentStep]]] = []
    runs_by_arm: list[list[int]] = []
    guards: set[str] = set()
    for _sig_seq, rids in sorted(groups.items(), key=lambda kv: kv[1][0]):
        steps = per_run[rids[0]]
        guard = _anchor(steps[0].action)
        key = _canonical_locator(steps[0].action)
        if guard is None or key in guards:
            return None
        guards.add(key)
        arms.append((guard, steps))
        runs_by_arm.append(rids)
    return _EmitBranch(arms, runs_by_arm)


# ── pass 2: emit plan → Workflow ─────────────────────────────────────────────


def _shared_base(col: _Column) -> str | None:
    bases = {_base_url(s.url) for s in col.steps.values()}
    return bases.pop() if len(bases) == 1 else None


def _masked_dialog(col: _Column, values_by_run: dict[int, dict[str, str]]) -> str | None:
    """A dialog condition that held in EVERY run: equal verbatim, or equal once each run's
    values are masked — then the value part becomes `.*` (value-agnostic, never invented)."""
    per_run: dict[int, str] = {}
    for rid, s in col.steps.items():
        if not s.dialogs:
            return None
        per_run[rid] = s.dialogs[-1]
    if len(set(per_run.values())) == 1:
        return re.escape(per_run[min(per_run)])
    masked: dict[int, str] = {}
    for rid, dialog in per_run.items():
        m = dialog
        for value in values_by_run.get(rid, {}).values():
            if len(value) >= _MIN_VALUE_LEN:
                m = re.sub(re.escape(value), "\x00", m, flags=re.IGNORECASE)
        masked[rid] = m
    if len(set(masked.values())) != 1:
        return None
    return re.escape(masked[min(masked)]).replace("\x00", ".*")


def _next_anchor(emits: list, pos: int) -> dict | None:
    """The anchor the state at `pos` may carry: the NEXT emitted step's target — only when
    that step's target held in every run (anchor_ok), the intersection rule."""
    for nxt in emits[pos + 1:]:
        if isinstance(nxt, _EmitBranch):
            return None  # the branch guards do the distinguishing
        if not isinstance(nxt, _EmitStep):
            continue
        return _anchor(nxt.action) if nxt.anchor_ok else None
    return None


def _compile_emits(
    emits: list,
    interrupt_cands: list[tuple[int, AgentStep]],
    *,
    name: str,
    version: str,
    task: str,
    n_runs: int,
    run_values: dict[int, dict[str, str]],
    confirmed: dict[str, ParamReport],
) -> Workflow:
    states = [State(id="init")]
    transitions: list[Transition] = []
    control: list[ControlNode] = []
    state_base: dict[str, str] = {}
    prev_base: str | None = None
    ti = 0  # transition counter
    bi = 0  # branch counter

    for pos, emit in enumerate(emits):
        if isinstance(emit, _EmitBranch):
            bi += 1
            pre_state = states[-1].id
            conv_id = f"m{bi}"
            arms: list[BranchArm] = []
            for aj, (guard, steps) in enumerate(emit.arms, 1):
                guard_id = f"g{bi}a{aj}"
                states.append(State(id=guard_id, conditions=[guard]))
                then: list[ControlNode] = []
                at = pre_state
                for q, step in enumerate(steps, 1):
                    target = conv_id if q == len(steps) else f"b{bi}a{aj}s{q}"
                    if target != conv_id:
                        anchor = _anchor(steps[q].action) if q < len(steps) else None
                        states.append(State(id=target, conditions=[anchor] if anchor else []))
                    edge_id = f"b{bi}a{aj}t{q}"
                    transitions.append(Transition(id=edge_id, source=at, target=target, action=step.action))
                    then.append(EdgeStep(edge=edge_id))
                    at = target
                arms.append(BranchArm(when=guard_id, then=then))
            conv_anchor = _next_anchor(emits, pos)
            states.append(State(id=conv_id, conditions=[conv_anchor] if conv_anchor else []))
            control.append(Branch(arms=arms))
            prev_base = None  # arms may have moved; the next shared base re-anchors
            continue

        emit_step: _EmitStep = emit
        ti += 1
        base = _shared_base(emit_step.col)
        conditions: list = []
        if base is not None and base != prev_base:
            conditions.append({"type": "url_matches", "pattern": re.escape(base)})
        anchor = _next_anchor(emits, pos)
        if anchor is not None:
            conditions.append(anchor)
        dialog = _masked_dialog(emit_step.col, run_values)
        if dialog is not None:
            conditions.append({"type": "dialog_matches", "pattern": dialog})
        prev_base = base if base is not None else None
        state_id = f"s{ti}"
        states.append(State(id=state_id, conditions=conditions))
        if base is not None:
            state_base[state_id] = base

        action = emit_step.action
        if isinstance(action, GotoAction) and action.timeout_ms < NAVIGATION_TIMEOUT_MS:
            action = action.model_copy(update={"timeout_ms": NAVIGATION_TIMEOUT_MS})
        if emit_step.dwell_param is not None:
            # Parameterized dwell: a noop edge enters the state, then Repeat 1 s wait slices
            # count="${param}" times (interrupt sweeps run between slices). max_iterations is
            # the static red-line bound; a larger runtime value is truncated to it.
            transitions.append(Transition(id=f"t{ti}", source=states[-2].id, target=state_id, action=NoopAction()))
            control.append(EdgeStep(edge=f"t{ti}"))
            slice_action = WaitAction(seconds=DWELL_SLICE_S)
            transitions.append(Transition(id=f"t{ti}_dwell", source=state_id, target=state_id, action=slice_action))
            control.append(Repeat(
                body=[EdgeStep(edge=f"t{ti}_dwell")],
                count="${" + emit_step.dwell_param + "}",
                max_iterations=emit_step.dwell_bound,
            ))
        elif isinstance(action, WaitAction) and action.seconds >= DWELL_MIN_SLICED_S:
            slices = max(1, round(action.seconds / DWELL_SLICE_S))
            slice_action = action.model_copy(update={"seconds": DWELL_SLICE_S})
            transitions.append(Transition(id=f"t{ti}", source=states[-2].id, target=state_id, action=slice_action))
            control.append(EdgeStep(edge=f"t{ti}"))
            if slices > 1:
                transitions.append(
                    Transition(id=f"t{ti}_dwell", source=state_id, target=state_id, action=slice_action)
                )
                control.append(Repeat(body=[EdgeStep(edge=f"t{ti}_dwell")], max_iterations=slices - 1))
        else:
            transitions.append(Transition(id=f"t{ti}", source=states[-2].id, target=state_id, action=action))
            control.append(EdgeStep(edge=f"t{ti}"))

    # Interrupts: deduped by anchor target; scoped to the states on the page they fired on.
    interrupts: list[Interrupt] = []
    seen_sel: dict[str, Interrupt] = {}
    k = 0
    for _rid, intr in interrupt_cands:
        sel = _canonical_locator(intr.action)
        if not sel or sel in seen_sel:
            continue
        k += 1
        anchor_state = f"i{k}"
        done_state = f"i{k}_done"
        states.append(State(id=anchor_state, conditions=[_anchor(intr.action)]))
        states.append(State(id=done_state, conditions=[_hidden(intr.action)]))
        transitions.append(Transition(id=f"ti{k}", source=anchor_state, target=done_state, action=intr.action))
        base = _base_url(intr.url)
        scope = [sid for sid, b in state_base.items() if b == base]
        if not scope:
            scope = [states[1].id if len(states) > 1 else "init"]
        interrupt = Interrupt(id=f"int{k}", state=anchor_state, resolve=[f"ti{k}"], scope=scope, max_fires=3)
        interrupts.append(interrupt)
        seen_sel[sel] = interrupt

    # Accept: what held at the end of every achieved run — the final state's intersected
    # conditions. Intersection only, never invented; empty = legacy success (every edge ok).
    main_states = [s for s in states if s.id.startswith("s") or s.id == "init"]
    final = main_states[-1] if main_states else states[-1]
    accept = [final.id] if final.conditions else []

    uses_program = bool(interrupts) or any(isinstance(n, (Repeat, Branch)) for n in control)
    params = [
        Param(name=p.name, default=p.default,
              description=f"inferred from {n_runs} runs; observed: "
              + ", ".join(f"run {rid}: {v!r}" for rid, v in sorted(p.values_by_run.items())))
        for p in sorted(confirmed.values(), key=lambda p: p.name)
    ]
    return Workflow(
        name=name,
        version=version,
        description=task,
        start_state="init",
        states=states,
        transitions=transitions,
        control=control if uses_program else None,
        control_sequence=None if uses_program else [n.edge for n in control],
        interrupts=interrupts,
        params=params,
        accept_states=accept,
    )


def _interrupt_summary(cands: list[tuple[int, AgentStep]]) -> dict[str, tuple[int, set[int]]]:
    out: dict[str, tuple[int, set[int]]] = {}
    for rid, step in cands:
        sel = _canonical_locator(step.action)
        if not sel:
            continue
        support, rids = out.get(sel, (0, set()))
        rids.add(rid)
        out[sel] = (len(rids), rids)
    return out
