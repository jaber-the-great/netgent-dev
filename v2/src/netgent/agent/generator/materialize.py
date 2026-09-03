"""`materialize`: a WorkflowDraft + the recordings → a Workflow, with per-item outcomes. Pure code,
zero LLM, zero browser (docs/research/generator-agent-v2.md §B.3–B.4, §D.3, §F.2).

Every pointer in the draft is resolved against the stored AgentSteps and checked by the
invariants M1–M14 (params, targets, folds, accept) and I1–I6 (interrupts). A choice that cannot
be re-derived is REJECTED with a reason and that region falls back to the recorded step; if
fewer than half of `main` materializes, the merge's own artifact (`ctx.fallback`) is returned
wholesale. So the worst case is today's output plus a list of reasons — C.0's asymmetry, kept.

The artifact is built by the merge's `_compile_emits`, so states anchor on the next edge's
target, dwells slice into 1 s repeats, folded gestures become a self-loop Repeat and interrupts
scope by base URL exactly as they do today; what changes is who decides the emit plan.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field

from netgent.agent.explorer.models import AgentStep
from netgent.agent.generator.compiler import (
    _INTERRUPTION_RE,
    MEDIA_GATE_CAP_S,
    MEDIA_GATE_MIN_CONTENT_S,
    MEDIA_GATE_TIMEOUT_MS,
    _anchor,
    _base_url,
    _locator_selector,
)
from netgent.agent.generator.context import GeneratorContext
from netgent.agent.generator.draft import (
    DraftBranch,
    DraftCondition,
    DraftEdge,
    DraftInterrupt,
    DraftRepeat,
    LocatorRef,
    ParamWitness,
    WorkflowDraft,
    parse_ref,
    ref_of,
)
from netgent.agent.generator.evidence import media_reading, run_steps, seek_between
from netgent.agent.generator.merge import (
    SECONDS_TOLERANCE,
    ParamReport,
    RunInput,
    _canonical_locator,
    _Column,
    _compile_emits,
    _dismissal_step,
    _EmitBranch,
    _EmitStep,
    _field_matches_value,
    _number_in,
    _sig,
    _sub_value,
    _target_shape,
)
from netgent.agent.generator.models import DraftOutcome, GenerateOutcome
from netgent.browser.locators import is_volatile_selector
from netgent.schema.actions import Action, LocatorStep
from netgent.schema.control import Param, ParamDerivation
from netgent.schema.triggers import MediaPlaying
from netgent.schema.units import UNIT_NOTE
from netgent.schema.workflow import State, Workflow

MIN_VALUE_LEN = 3  # a shorter literal substitutes everywhere (§B.3 M8)
STOP_WORDS = frozenset(
    {"submit", "search", "next", "ok", "yes", "no", "go", "play", "skip", "close", "login", "sign in"})
MAX_INTERRUPTS = 4  # I6
MAX_NTH = 4  # a small ordinal relative to a named container (§K.6, UiPath UI-REL-001)
SEEK_TOLERANCE = 0.40  # M10: the median measured seek must be within ±40 % of the claimed divide_by
MIN_SEEK_PAIRS = 3
MIN_SEEK_RUNS = 2
FALLBACK_FLOOR = 0.5  # < 50 % of main materialized → the merge's artifact (§B.4 step 6)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_RESERVED = frozenset({"name", "version", "params", "control", "states", "transitions"})


@dataclass
class _Resolved:
    """A DraftParam that passed M8–M10, as the compile consumes it."""

    report: ParamReport
    kind: str
    derive: ParamDerivation | None = None
    witnesses: list[tuple[int, AgentStep, ParamWitness]] = field(default_factory=list)


class _Recorder:
    def __init__(self) -> None:
        self.outcomes: list[DraftOutcome] = []
        self.warnings: list[str] = []

    def ok(self, item: str, ref: str | None, reason: str = "") -> None:
        self.outcomes.append(DraftOutcome(item=item, ref=ref, status="applied", reason=reason))

    def no(self, item: str, ref: str | None, reason: str) -> None:
        self.outcomes.append(DraftOutcome(item=item, ref=ref, status="rejected", reason=reason))

    def degraded(self, item: str, ref: str | None, reason: str) -> None:
        self.outcomes.append(DraftOutcome(item=item, ref=ref, status="degraded", reason=reason))


class _Recordings:
    """The immutable recordings, indexed for the resolver: run → ordered steps, ref → step."""

    def __init__(self, runs: list[RunInput]):
        self.by_run: dict[int, RunInput] = {r.run: r for r in runs}
        self.steps: dict[int, list[AgentStep]] = {r.run: run_steps(r) for r in runs}
        self.position: dict[str, int] = {}
        self.by_ref: dict[str, tuple[int, AgentStep]] = {}
        for rid, steps in self.steps.items():
            for i, s in enumerate(steps):
                ref = ref_of(rid, s)
                self.by_ref[ref] = (rid, s)
                self.position[ref] = i

    def resolve(self, ref: str, kept: set[int]) -> tuple[int, AgentStep] | str:
        """M1: (run, step) for a ref in a kept run with a successful action, or the reason not."""
        if parse_ref(ref) is None:
            return f"{ref!r} is not a step reference (r<run>.s<n>.<item>)"
        got = self.by_ref.get(ref)
        if got is None:
            rid = parse_ref(ref)[0]
            if rid not in self.by_run:
                return f"{ref}: run {rid} is not an achieved run"
            return f"{ref}: no such recorded step with a successful action"
        if got[0] not in kept:
            return f"{ref}: run {got[0]} is not a kept run"
        return got

    def next_step(self, rid: int, step: AgentStep) -> AgentStep | None:
        i = self.position[ref_of(rid, step)]
        steps = self.steps[rid]
        return steps[i + 1] if i + 1 < len(steps) else None

    def prev_step(self, rid: int, step: AgentStep) -> AgentStep | None:
        i = self.position[ref_of(rid, step)]
        return self.steps[rid][i - 1] if i > 0 else None

    def changed_base_url(self, rid: int, step: AgentStep) -> bool:
        """I3: did this step change the page's base URL in its own run (merge._step_effects' rule)?"""
        prev = self.prev_step(rid, step)
        return prev is not None and _base_url(prev.url) != _base_url(step.url)

    def block_of(self, rid: int, step: AgentStep) -> list[AgentStep]:
        """The maximal contiguous run of same-signature steps around `step` (scroll gaps allowed)."""
        steps = self.steps[rid]
        i = self.position[ref_of(rid, step)]
        sig = _sig(step)

        def same(s: AgentStep) -> bool:
            return _sig(s) == sig

        def skippable(s: AgentStep) -> bool:
            return s.action.type == "scroll"

        a = i
        while a > 0 and (same(steps[a - 1]) or (skippable(steps[a - 1]) and a > 1 and same(steps[a - 2]))):
            a -= 1
        b = i
        while b + 1 < len(steps) and (same(steps[b + 1]) or (skippable(steps[b + 1]) and b + 2 < len(steps)
                                                              and same(steps[b + 2]))):
            b += 1
        return [s for s in steps[a:b + 1] if same(s)]


# ── params (M8–M10) ──────────────────────────────────────────────────────────


def _literal_in_field(step: AgentStep, witness: ParamWitness, rec: _Recordings, rid: int) -> str | None:
    """M8: is the witness literal recoverable from the named field of the step? Returns the reason
    it is not, or None when it is."""
    lit = witness.literal.strip()
    a = step.action
    if witness.field in ("text", "value", "url"):
        recorded = getattr(a, witness.field, None)
        if not isinstance(recorded, str):
            return f"{a.type} has no {witness.field} field"
        if len(lit) < MIN_VALUE_LEN:
            return f"literal {lit!r} is shorter than {MIN_VALUE_LEN} characters"
        if lit.lower() in STOP_WORDS:
            return f"literal {lit!r} is page furniture, not a value"
        if not _field_matches_value(recorded, lit, witness.field) and lit.lower() not in recorded.lower():
            return f"literal {lit!r} does not appear in the recorded {witness.field} {recorded[:60]!r}"
        return None
    if witness.field == "seconds":
        if a.type != "wait":
            return f"{a.type} has no seconds field"
        n = _number_in(lit)
        if n is None or abs(n - float(a.seconds)) > 1e-6:
            return f"literal {lit!r} is not the recorded {a.seconds:g}s"
        return None
    if witness.field == "press_count":
        if a.type != "press":
            return f"{a.type} is not a press"
        n = _number_in(lit)
        count = len(rec.block_of(rid, step))
        if n is None or int(n) != count:
            return f"literal {lit!r} is not the recorded press count {count}"
        return None
    if witness.field == "media_jump":
        nxt = rec.next_step(rid, step)
        seek = seek_between(step, nxt) if nxt is not None else None
        n = _number_in(lit)
        if seek is None or n is None:
            return "no media reading pair around this step to measure a jump"
        if abs(seek - n) > SEEK_TOLERANCE * max(n, 1.0):
            return f"literal {lit!r} is not the measured jump {seek:+.0f}s"
        return None
    return f"unknown witness field {witness.field!r}"


def _provenance(literal: str, rid: int, ctx: GeneratorContext, run: RunInput) -> str:
    """M9: 'user' when the literal is in the task text or the run's declared values, 'page' when it
    was seen on a page but not in the task, else ''."""
    lit = literal.lower()
    declared = [v.lower() for v in ctx.values_by_run.get(rid, {}).values()]
    if lit in ctx.task.lower() or lit in run.trajectory.task.lower() or any(lit in v or v in lit for v in declared):
        return "user"
    if any(lit in t.lower() for t in run.trajectory.texts_seen):
        return "page"
    return ""


def _resolve_params(draft: WorkflowDraft, rec: _Recordings, kept: set[int], spine: int, ctx: GeneratorContext,
                    out: _Recorder) -> dict[str, _Resolved]:
    resolved: dict[str, _Resolved] = {}
    for i, p in enumerate(draft.params):
        item = f"params[{i}]"
        if not _NAME_RE.match(p.name) or p.name in _RESERVED:
            out.no(item, None, f"param name {p.name!r} is not a legal, unreserved name")
            continue
        if p.name in resolved:
            out.no(item, None, f"param {p.name!r} declared twice")
            continue
        if p.kind == "derived":
            if p.derived_from is None or p.divide_by is None:
                out.no(item, None, f"derived param {p.name!r} needs derived_from and divide_by")
                continue
            resolved[p.name] = _Resolved(report=ParamReport(name=p.name, default=""), kind="derived",
                                         derive=ParamDerivation(from_param=p.derived_from, divide_by=p.divide_by,
                                                                rounding=p.rounding, min=1))
            continue  # M10 is checked where a Repeat uses it
        if p.kind == "page":
            out.no(item, None, "page-extracted params are not materialized yet (generator-agent-v2.md §L.3)")
            continue
        if not p.witnesses:
            out.no(item, None, f"param {p.name!r} has no witness — no witness, no param")
            continue
        good: list[tuple[int, AgentStep, ParamWitness]] = []
        reasons: list[str] = []
        for w in p.witnesses:
            got = rec.resolve(w.step, kept)
            if isinstance(got, str):
                reasons.append(got)
                continue
            rid, step = got
            why = _literal_in_field(step, w, rec, rid)
            if why is not None:
                reasons.append(f"{w.step}: {why}")
                continue
            if w.field in ("text", "value", "url"):
                prov = _provenance(w.literal, rid, ctx, rec.by_run[rid])
                if prov != "user":
                    page = " (seen on the page: a page param, not supported yet)" if prov == "page" else ""
                    reasons.append(f"{w.step}: literal {w.literal!r} is not in the task text or the run's declared "
                                   f"values{page}")
                    continue
            good.append((rid, step, w))
        if not good:
            out.no(item, None, f"param {p.name!r}: no witness verified — " + "; ".join(reasons)[:300])
            continue
        declared = {rid: ctx.values_by_run.get(rid, {}).get(p.name, "") for rid in kept}
        default = declared.get(spine) or next((w.literal for rid, _s, w in good if rid == spine), good[0][2].literal)
        values_by_run = {rid: (declared[rid] or next((w.literal for r2, _s, w in good if r2 == rid), ""))
                         for rid in sorted(kept)}
        resolved[p.name] = _Resolved(
            report=ParamReport(name=p.name, default=default, values_by_run=values_by_run), kind="user", witnesses=good)
        out.ok(item, good[0][2].step, f"param {p.name!r}: {len(good)}/{len(p.witnesses)} witness(es) verified"
               + (f"; dropped: {'; '.join(reasons)[:200]}" if reasons else ""))
    return resolved


# ── targets (M5–M7) ──────────────────────────────────────────────────────────


def _rung(step: AgentStep, rung: int | None) -> list[LocatorStep] | str:
    """M5: the rung's chain, verbatim — or the recorded chain for None — or the reason not."""
    if rung is None:
        locator = getattr(step.action, "locator", None)
        return list(locator) if locator else "the step has no locator"
    if rung >= len(step.locator_candidates):
        return f"rung {rung} was not recorded (the ladder has {len(step.locator_candidates)} rung(s))"
    return list(step.locator_candidates[rung])


def _rung_of_kind(step: AgentStep, chain: list[LocatorStep], kind: str) -> int | None:
    """The index of the rung with this chain (else of this kind) in `step`'s ladder."""
    dumped = [st.model_dump() for st in chain]
    for i, c in enumerate(step.locator_candidates):
        if [st.model_dump() for st in c] == dumped:
            return i
    for i, k in enumerate(step.candidate_kinds):
        if k == kind:
            return i
    return None


def _apply_target(action: Action, ref: LocatorRef, spine_step: AgentStep, column: dict[int, AgentStep],
                  spine: int, params: dict[str, _Resolved], ctx: GeneratorContext) -> tuple[Action, str] | str:
    """M5–M7 on a DraftEdge.target: the rewritten action and what was applied, or the reason not."""
    chain = _rung(spine_step, ref.rung)
    if isinstance(chain, str):
        return chain
    kind = spine_step.candidate_kinds[ref.rung] if ref.rung < len(spine_step.candidate_kinds) else "recorded"
    if ref.nth is not None and ref.name_param is not None:
        return "set nth OR name_param, not both"
    if ref.nth is not None:
        if kind != "structural":
            return f"nth needs a structural (container-relative) rung; rung {ref.rung} is {kind}"
        if ref.nth > MAX_NTH:
            return f"nth={ref.nth} is not a small ordinal (max {MAX_NTH})"
        for rid, st in sorted(column.items()):
            k = ref.rung if rid == spine else _rung_of_kind(st, chain, kind)
            if k is None:
                return f"run {rid}: recorded no {kind} rung for this step"
            if [s.model_dump() for s in st.locator_candidates[k]] != [s.model_dump() for s in chain]:
                other = _locator_selector(st.locator_candidates[k])
                return f"run {rid}: its {kind} rung is a different chain ({other!r})"
            count = st.match_counts[k] if k < len(st.match_counts) else -1
            index = st.match_indices[k] if k < len(st.match_indices) else None
            if index is None:
                return f"run {rid}: the acted element's position in that rung was not recorded"
            if count <= ref.nth:
                return f"run {rid}: the rung resolved to {count} element(s), not more than {ref.nth}"
            if index != ref.nth:
                return f"run {rid}: the acted element sat at index {index}, not {ref.nth}"
        return action.model_copy(update={"locator": [*chain, LocatorStep(fn="nth", args=[ref.nth])]}), (
            f"structural rung {_locator_selector(chain)!r} + nth({ref.nth}), the same position in "
            f"{len(column)} run(s)")
    if ref.name_param is not None:
        pname = ref.name_param
        if pname not in params or params[pname].kind != "user":
            return f"name_param {pname!r} is not an accepted user param"
        last = chain[-1]
        if last.fn != "get_by_role" or not last.args or "name" not in last.kwargs:
            return f"name_param needs a get_by_role rung with a name; rung {ref.rung} is {last.fn}"
        for rid, st in sorted(column.items()):
            k = ref.rung if rid == spine else _rung_of_kind(st, chain, "role")
            c = st.locator_candidates[k] if k is not None and k < len(st.locator_candidates) else None
            if c is None or c[-1].fn != "get_by_role" or "name" not in c[-1].kwargs:
                return f"run {rid}: no role rung with a name recorded for this step"
            value = ctx.values_by_run.get(rid, {}).get(pname, "")
            if len(value) < MIN_VALUE_LEN or value.lower() not in str(c[-1].kwargs["name"]).lower():
                recorded = str(c[-1].kwargs["name"])[:50]
                return f"run {rid}: its {pname} value {value!r} is not in the recorded name {recorded!r}"
        new_last = LocatorStep(fn="get_by_role", args=list(last.args),
                               kwargs={**last.kwargs, "name": "${" + pname + "}"})
        return action.model_copy(update={"locator": [*chain[:-1], new_last, LocatorStep(fn="nth", args=[0])]}), (
            f"get_by_role(name=${{{pname}}}) + nth(0): every run's recorded name contains its value")
    return action.model_copy(update={"locator": chain}), f"rung {ref.rung} ({kind}) {_locator_selector(chain)!r}"


# ── value binding (M8, per edge) ─────────────────────────────────────────────


def _bind_value(action: Action, pname: str, column: dict[int, AgentStep], spine: int, params: dict[str, _Resolved],
                ctx: GeneratorContext, edge_refs: set[str]) -> tuple[Action, str | None, str] | str:
    """Bind an edge's value field to ${pname}: (action, dwell field or None, what) or the reason not."""
    p = params.get(pname)
    if p is None or p.kind != "user":
        return f"value_param {pname!r} is not an accepted user param"
    on_edge = [w for _rid, _s, w in p.witnesses if w.step in edge_refs]
    if not on_edge:
        return f"param {pname!r} has no verified witness on this step or its corroborating steps"
    fld = on_edge[0].field
    if fld not in ("text", "value", "url", "seconds"):
        return f"a {fld} witness does not bind an action field"
    for rid, st in sorted(column.items()):
        declared = ctx.values_by_run.get(rid, {}).get(pname)
        if not declared:
            continue
        recorded = getattr(st.action, fld, None)
        if recorded is None:
            return f"run {rid}: its step has no {fld} field"
        if fld == "seconds":
            planned = _number_in(declared)
            if planned is None or abs(float(recorded) - planned) > max(2.0, SECONDS_TOLERANCE * planned):
                return f"run {rid}: recorded {recorded:g}s, declared {pname}={declared!r}"
        elif not _field_matches_value(recorded, declared, fld) and declared.lower() not in str(recorded).lower():
            return f"run {rid}: recorded {fld} {str(recorded)[:50]!r} does not carry its {pname}={declared!r}"
    if fld == "seconds":
        return action, "seconds", f"dwell bound to ${{{pname}}} (1 s slices)"
    spine_value = ctx.values_by_run.get(spine, {}).get(pname) or on_edge[0].literal
    new = _sub_value(getattr(action, fld), spine_value, pname)
    if new == getattr(action, fld):
        return f"the spine's {fld} does not contain {spine_value!r}"
    return action.model_copy(update={fld: new}), None, f"{fld} bound to ${{{pname}}}"


# ── folds (M10–M11) ──────────────────────────────────────────────────────────


def _check_fold(node: DraftRepeat, rec: _Recordings, kept: set[int], spine: int, params: dict[str, _Resolved],
                ctx: GeneratorContext) -> tuple[_EmitStep, dict[int, list[AgentStep]], str] | str:
    if len(node.body) != 1 or not isinstance(node.body[0], DraftEdge):
        return "only a Repeat whose body is ONE edge is supported"
    body: DraftEdge = node.body[0]
    per_run: dict[int, list[AgentStep]] = {}
    for ref in node.covers:
        got = rec.resolve(ref, kept)
        if isinstance(got, str):
            return f"covers: {got}"
        per_run.setdefault(got[0], []).append(got[1])
    missing = sorted(kept - set(per_run))
    if missing:
        return f"covers has no step in kept run(s) {missing}"
    if body.step not in node.covers:
        return f"the body edge {body.step} is not in covers"
    if parse_ref(body.step)[0] != spine:
        return f"the body edge {body.step} is not a spine step"
    sigs = {_sig(s) for steps in per_run.values() for s in steps}
    if len(sigs) != 1:
        return f"covers span {len(sigs)} action signatures; a gesture has one"
    sig = next(iter(sigs))
    if sig[0] == "wait":
        return "a dwell is bound with value_param on its wait edge, not folded"
    for rid, steps in per_run.items():
        steps.sort(key=lambda s: rec.position[ref_of(rid, s)])
        block = rec.block_of(rid, steps[0])
        block_refs = [ref_of(rid, s) for s in block]
        if any(ref_of(rid, s) not in block_refs for s in steps):
            return f"run {rid}: covers are not contiguous in the recording (scroll gaps aside)"
    counts = {rid: len(steps) for rid, steps in per_run.items()}
    spine_step = per_run[spine][0]
    emit = _EmitStep(spine_step.action, _Column({rid: steps[0] for rid, steps in per_run.items()}), anchor_ok=True)
    emit.repeat_bound = max(10, 3 * max(counts.values()))
    if node.count.param is None:
        if node.count.constant is None:
            return "count needs a constant or a param"
        if node.count.constant != counts[spine]:
            return f"count.constant {node.count.constant} is not the spine's {counts[spine]}"
        if len(set(counts.values())) != 1:
            return f"per-run counts differ ({counts}) — a constant does not explain them"
        emit.repeat_count = counts[spine]
        return emit, per_run, f"Repeat ×{counts[spine]} over {sum(counts.values())} recorded steps"
    pname = node.count.param
    p = params.get(pname)
    if p is None:
        return f"count.param {pname!r} is not an accepted param"
    if p.kind == "derived":
        why = _check_derived(p, per_run, rec, ctx, params)
        if why is not None:
            return why
        emit.repeat_param = pname
        p.report.default = str(counts[spine])
        p.report.values_by_run = {rid: str(n) for rid, n in sorted(counts.items())}
        return emit, per_run, (f"Repeat(count=${{{pname}}}) = {p.derive.from_param} / {p.derive.divide_by:g}"
                               f" ({p.derive.rounding}); counts {counts}")
    planned = {rid: _number_in(ctx.values_by_run.get(rid, {}).get(pname, "")) for rid in per_run}
    if any(v is None for v in planned.values()):
        return f"{pname} has no numeric value in every kept run"
    if any(planned[rid] != counts[rid] for rid in per_run):
        return f"per-run counts {counts} are not the planned {pname} values {planned}; declare a derived param"
    emit.repeat_param = pname
    return emit, per_run, f"Repeat(count=${{{pname}}}); counts {counts}"


def _check_derived(p: _Resolved, per_run: dict[int, list[AgentStep]], rec: _Recordings, ctx: GeneratorContext,
                   params: dict[str, _Resolved]) -> str | None:
    """M10: the claimed per-iteration unit must be what the media readings measured."""
    d = p.derive
    src_param = params.get(d.from_param)
    if src_param is None or src_param.kind != "user":
        return f"derived {p.report.name}: derived_from {d.from_param!r} is not an accepted user param"
    seeks: list[float] = []
    runs_with: set[int] = set()
    for rid, steps in per_run.items():
        for s in steps:
            nxt = rec.next_step(rid, s)
            seek = seek_between(s, nxt) if nxt is not None else None
            if seek is not None:
                seeks.append(seek)
                runs_with.add(rid)
    if len(seeks) < MIN_SEEK_PAIRS or len(runs_with) < MIN_SEEK_RUNS:
        return (f"derived {p.report.name}: only {len(seeks)} media-reading pair(s) in {len(runs_with)} run(s); "
                f"need {MIN_SEEK_PAIRS} in {MIN_SEEK_RUNS}")
    med = statistics.median(seeks)
    if abs(med - d.divide_by) > SEEK_TOLERANCE * d.divide_by:
        return (f"derived {p.report.name}: the median measured jump is {med:+.1f}s per iteration, not "
                f"{d.divide_by:g} (±{int(SEEK_TOLERANCE * 100)}%)")
    for rid, steps in per_run.items():
        src = _number_in(ctx.values_by_run.get(rid, {}).get(d.from_param, ""))
        if src is None:
            return f"derived {p.report.name}: run {rid} declares no numeric {d.from_param}"
        expected = -(-src // d.divide_by)  # ceil
        if not 1 <= len(steps) <= expected + 2:
            return (f"derived {p.report.name}: run {rid} recorded {len(steps)} iteration(s) for {d.from_param}="
                    f"{src:g}, outside 1..{int(expected) + 2}")
    return None


# ── interrupts (I1–I6) ───────────────────────────────────────────────────────


def _check_interrupt(i: int, intr: DraftInterrupt, rec: _Recordings, kept: set[int], main_refs: set[str],
                     main_targets: set[str], ctx: GeneratorContext, out: _Recorder,
                     ) -> tuple[int, AgentStep, int] | None:
    item = f"interrupts[{i}]"
    got = rec.resolve(intr.step, kept)
    if isinstance(got, str):
        out.no(item, intr.step, got)
        return None
    rid, step = got
    if step.action.type != "click":  # I1
        out.no(item, intr.step, f"a {step.action.type} is not a dismissal click")
        return None
    chain = _rung(step, intr.rung)
    if isinstance(chain, str):
        out.no(item, intr.step, chain)
        return None
    sel = _locator_selector(chain)  # I2
    if sel is None:
        out.no(item, intr.step, "the chosen rung is not expressible as a selector")
        return None
    if is_volatile_selector(sel.split()[0]) or is_volatile_selector(sel) and " " not in sel:
        # the leading id token (a css PATH legitimately carries ':nth-of-type'), or a fragile-framework id anywhere
        out.no(item, intr.step,
               f"anchor {sel!r} looks machine-generated (per-session id) — it would never fire again")
        return None
    if rec.changed_base_url(rid, step):  # I3
        out.no(item, intr.step, f"the click changed the page's base URL ({_base_url(rec.prev_step(rid, step).url)} -> "
                                f"{_base_url(step.url)}): a navigation, not a dismissal")
        return None
    if intr.step in main_refs or _canonical_locator(step.action) in main_targets:  # I4
        out.no(item, intr.step, "the step (or its target) is on the main path — not an interrupt")
        return None
    seen = {rid}
    for ref in intr.also_seen:
        g = rec.resolve(ref, kept)
        if isinstance(g, str):
            continue
        r2, s2 = g
        if s2.action.type == "click" and (_canonical_locator(s2.action) == _canonical_locator(step.action)
                                          or _target_shape(s2.action) == _target_shape(step.action)):
            seen.add(r2)
    support = len(seen)
    if support < 2:  # I5
        named = bool(_INTERRUPTION_RE.search(ctx.task)) and bool(intr.why.strip()) and _dismissal_step(step)
        if not named:
            out.no(item, intr.step, "seen in one run only, and neither the task text nor the click's own target/"
                                    "reasoning names it as a dismissal")
            return None
    action = step.action.model_copy(update={"locator": chain})
    return rid, step.model_copy(update={"action": action}), support


# ── accept (M13) ─────────────────────────────────────────────────────────────


def _check_condition(i: int, cond: DraftCondition, rec: _Recordings, kept: set[int], out: _Recorder,
                     ) -> dict | MediaPlaying | None:
    item = f"accept[{i}]"
    got = rec.resolve(cond.witness, kept)
    if isinstance(got, str):
        out.no(item, cond.witness, got)
        return None
    rid, step = got
    if cond.type == "url_matches":
        base = _base_url(step.url)
        out.ok(item, cond.witness, f"url_matches ^{base}")
        return {"type": "url_matches", "pattern": "^" + re.escape(base)}
    if cond.type in ("selector_visible", "selector_hidden"):
        chain = _rung(step, cond.rung)
        if isinstance(chain, str):
            out.no(item, cond.witness, chain)
            return None
        if cond.rung is not None and (cond.rung >= len(step.match_counts) or step.match_counts[cond.rung] < 1):
            out.no(item, cond.witness, f"rung {cond.rung} resolved to no element at capture time")
            return None
        out.ok(item, cond.witness, f"{cond.type} on {_locator_selector(chain) or 'the recorded chain'}")
        return {"type": cond.type, "locator": [st.model_dump(mode="json") for st in chain]}
    reading = media_reading(step)
    if reading is None or reading[0] != "PLAYING":
        out.no(item, cond.witness, "the witness step recorded no PLAYING media reading")
        return None
    durations = [r[2] for s in rec.steps[rid] if (r := media_reading(s)) is not None and r[2] is not None]
    content = max(durations) if durations else None
    if content is None or content < MEDIA_GATE_MIN_CONTENT_S:
        out.no(item, cond.witness, f"content of {content}s cannot be told from an ad by length")
        return None
    threshold = min(round(content / 2), MEDIA_GATE_CAP_S)
    out.ok(item, cond.witness, f"media_playing(min_duration_s={threshold:g}) — half the observed content, capped")
    return MediaPlaying(playing=cond.playing, min_duration_s=float(threshold))


# ── the materialization ──────────────────────────────────────────────────────


def _fallback(ctx: GeneratorContext, draft: WorkflowDraft | None, out: _Recorder, reason: str) -> GenerateOutcome:
    out.warnings.append(f"fallback to the merge's artifact: {reason}")
    return GenerateOutcome(workflow=ctx.fallback, draft=draft, outcomes=out.outcomes, warnings=out.warnings,
                           used_fallback=True, validated=bool(ctx.fallback.accept_states))


def materialize(draft: WorkflowDraft, ctx: GeneratorContext) -> GenerateOutcome:
    """draft + recordings → Workflow. Never raises on a bad draft; records what it refused."""
    out = _Recorder()
    achieved = ctx.achieved()
    if not achieved:
        return _fallback(ctx, draft, out, "no achieved runs")
    rec = _Recordings(achieved)
    n = len(achieved)

    # 1. the run policy (M2, M3)
    kept = {r for r in draft.kept_runs if r in rec.by_run}
    spine = draft.spine
    excluded_ids = {e.run for e in draft.excluded}
    omitted = set(rec.by_run) - kept
    policy_ok = spine in kept
    reasons = []
    if not policy_ok:
        reasons.append(f"spine run {spine} is not among the kept runs {sorted(kept)}")
    if len(omitted) > n // 3:
        policy_ok = False
        reasons.append(f"{len(omitted)} of {n} achieved runs left out (excluded or not kept); at most {n // 3} may be")
    for e in draft.excluded:
        got = rec.by_ref.get(e.evidence)
        if e.run not in rec.by_run or got is None or got[0] != e.run:
            policy_ok = False
            reasons.append(f"excluded run {e.run}: evidence {e.evidence} is not a step of that run")
    if policy_ok:
        excl = f", excluded {sorted(excluded_ids)}" if excluded_ids else ""
        out.ok("runs", None, f"spine {spine}, kept {sorted(kept)}{excl}")
    else:
        out.no("runs", None, "; ".join(reasons) + " — kept every achieved run instead")
        kept = set(rec.by_run)
        spine = draft.spine if draft.spine in kept else min(kept)

    # 2. params (M8–M10)
    params = _resolve_params(draft, rec, kept, spine, ctx, out)

    # 3. main
    emits: list = []
    item_of_emit: dict[int, str] = {}
    main_refs: set[str] = set()
    main_targets: set[str] = set()
    referenced: set[str] = set()
    promoted: list[tuple[str, list[str]]] = []  # main-path dismissals moved to the interrupt candidates
    last_pos = -1
    applied_nodes = 0
    if not draft.main:
        return _fallback(ctx, draft, out, "the draft has no main path")

    def _edge_emit(idx: int, node: DraftEdge, item: str) -> _EmitStep | None:
        nonlocal last_pos
        got = rec.resolve(node.step, kept)
        if isinstance(got, str):
            out.no(item, node.step, got)
            return None
        rid, step = got
        if rid != spine:
            out.no(item, node.step, f"main-path edges come from the spine (run {spine}), this is run {rid}'s")
            return None
        pos = rec.position[node.step]
        if pos <= last_pos:
            out.no(item, node.step, "out of the spine's step order (main-path edges must be strictly increasing)")
            return None
        last_pos = pos
        column: dict[int, AgentStep] = {spine: step}
        for ref in node.corroborated_by:
            g = rec.resolve(ref, kept)
            if isinstance(g, str):
                out.degraded(f"{item}.corroborated_by", ref, g)
                continue
            r2, s2 = g
            if r2 == spine or r2 in column:
                out.degraded(f"{item}.corroborated_by", ref, f"run {r2} already corroborates (or is the spine)")
                continue
            if s2.action.type != step.action.type or _target_shape(s2.action) != _target_shape(step.action):
                out.degraded(f"{item}.corroborated_by", ref,
                             f"a {s2.action.type} on {_target_shape(s2.action)} is not the spine step's shape")
                continue
            column[r2] = s2
        if len(kept) > 1 and len(column) < len(kept) and _dismissal_step(step):
            # A dismissal-shaped click that some kept run never performed cannot be a main-path
            # requirement: the overlay may not appear on replay. It is interrupt-shaped (M4/I4).
            missing = sorted(kept - set(column))
            out.no(item, node.step, f"a dismissal-shaped click that kept run(s) {missing} never performed belongs in "
                                    "`interrupts`, not on the main path (an ad may not show on replay); "
                                    "promoted to an interrupt candidate")
            promoted.append((node.step, [ref_of(r, s) for r, s in column.items() if r != rid]))
            return None
        action = step.action
        anchor_ok = len({_sig(s) for s in column.values()}) == 1
        what = ["recorded chain"]
        if node.target is not None:
            if node.target.step != node.step:
                out.no(f"{item}.target", node.target.step, "target must point at this edge's own step")
            else:
                got_t = _apply_target(action, node.target, step, column, spine, params, ctx)
                if isinstance(got_t, str):
                    out.no(f"{item}.target", node.step, got_t)
                else:
                    action, w = got_t
                    anchor_ok = True
                    what = [w]
                    out.ok(f"{item}.target", node.step, w)
                    if node.target.name_param:
                        referenced.add(node.target.name_param)
        dwell_param: str | None = None
        pname: str | None = None
        if node.value_param is not None:
            got_v = _bind_value(action, node.value_param, column, spine, params, ctx,
                                {node.step, *node.corroborated_by})
            if isinstance(got_v, str):
                out.no(f"{item}.value_param", node.step, got_v)
            else:
                action, dwell, w = got_v
                pname = node.value_param
                referenced.add(pname)
                what.append(w)
                out.ok(f"{item}.value_param", node.step, w)
                if dwell == "seconds":
                    dwell_param = pname
        if len(column) == 1 and len(kept) > 1:
            out.degraded(item, node.step,
                         "singleton: no other kept run corroborates this step (the replay gate tests it)")
        else:
            out.ok(item, node.step, f"{step.action.type}, corroborated by {len(column) - 1} run(s); " + "; ".join(what))
        emit = _EmitStep(action, _Column(column), anchor_ok=anchor_ok, param=pname, col_index=idx)
        if dwell_param is not None:
            emit.dwell_param = dwell_param
            observed = max(float(getattr(s.action, "seconds", 0) or 0) for s in column.values())
            emit.dwell_bound = max(60, 3 * int(observed))
            params[dwell_param].report.default = _num_str(params[dwell_param].report.default)
            params[dwell_param].report.values_by_run = {
                r: _num_str(v) for r, v in params[dwell_param].report.values_by_run.items()}
        main_refs.update(ref_of(r, s) for r, s in column.items())
        main_targets.add(_canonical_locator(action))
        return emit

    for idx, node in enumerate(draft.main):
        item = f"main[{idx}]"
        if isinstance(node, DraftEdge):
            emit = _edge_emit(idx, node, item)
            if emit is not None:
                emits.append(emit)
                item_of_emit[idx] = item
                applied_nodes += 1
        elif isinstance(node, DraftRepeat):
            got_f = _check_fold(node, rec, kept, spine, params, ctx)
            if isinstance(got_f, str):
                out.no(item, node.body[0].step if node.body and isinstance(node.body[0], DraftEdge) else None, got_f)
                # today's behaviour for the region: the covers' spine steps as individual edges
                spine_covers = sorted((rec.position[r], r) for r in node.covers
                                      if r in rec.by_ref and rec.by_ref[r][0] == spine and rec.position[r] > last_pos)
                for _p, ref in spine_covers:
                    e = _edge_emit(idx, DraftEdge(step=ref), f"{item}.covers")
                    if e is not None:
                        emits.append(e)
                continue
            emit, per_run, what = got_f
            spine_positions = [rec.position[ref_of(spine, s)] for s in per_run[spine]]
            if min(spine_positions) <= last_pos:
                out.no(item, node.body[0].step, "the fold's spine steps are out of the main path's order")
                continue
            last_pos = max(spine_positions)
            emit.col_index = idx
            if node.count.param:
                referenced.add(node.count.param)
            emits.append(emit)
            item_of_emit[idx] = item
            applied_nodes += 1
            main_refs.update(ref_of(r, s) for r, steps in per_run.items() for s in steps)
            main_targets.add(_canonical_locator(emit.action))
            out.ok(item, node.body[0].step, what)
        else:  # DraftBranch
            got_b = _check_branch(node, rec, kept, spine, out, item)
            if got_b is None:
                spine_arm = next((a for a in node.arms if spine in a.runs), None)
                for sub in (spine_arm.then if spine_arm else []):
                    if isinstance(sub, DraftEdge):
                        e = _edge_emit(idx, sub, f"{item}.spine_arm")
                        if e is not None:
                            emits.append(e)
                continue
            emits.append(got_b)
            applied_nodes += 1
            out.ok(item, None, f"Branch with {len(node.arms)} arm(s)")

    if not any(isinstance(e, _EmitStep) for e in emits):
        return _fallback(ctx, draft, out, "no main-path step materialized")
    if applied_nodes / len(draft.main) < FALLBACK_FLOOR:
        return _fallback(ctx, draft, out, f"only {applied_nodes} of {len(draft.main)} main nodes materialized")

    # 4. interrupts (I1–I6)
    cands: list[tuple[int, int, AgentStep, int]] = []  # (support, order, step, run)
    interrupts = list(draft.interrupts)
    declared_refs = {i.step for i in interrupts} | {r for i in interrupts for r in i.also_seen}
    for ref, also in promoted:
        if ref not in declared_refs:
            interrupts.append(DraftInterrupt(step=ref, also_seen=also, why="promoted from the main path"))
    for i, intr in enumerate(interrupts):
        got_i = _check_interrupt(i, intr, rec, kept, main_refs, main_targets, ctx, out)
        if got_i is not None:
            rid, step, support = got_i
            cands.append((support, rec.position[intr.step], step, rid))
            out.ok(f"interrupts[{i}]", intr.step,
                   f"dismissal {_locator_selector(step.action.locator)!r}, support {support}")
    cands.sort(key=lambda c: (-c[0], c[1]))
    if len(cands) > MAX_INTERRUPTS:
        for support, _o, step, rid in cands[MAX_INTERRUPTS:]:
            out.degraded("interrupts", ref_of(rid, step),
                         f"beyond the {MAX_INTERRUPTS}-interrupt cap (support {support})")
        cands = cands[:MAX_INTERRUPTS]
    interrupt_cands = [(rid, step) for _s, _o, step, rid in cands]

    # 5. params → reports (M14: only referenced params reach the artifact; a derived param
    #    references its source)
    unit_params: set[str] = set()
    for name in list(referenced):  # a derived param references its source
        if (p := params.get(name)) is not None and p.derive is not None:
            referenced.add(p.derive.from_param)
            unit_params.add(p.derive.from_param)
    confirmed: dict[str, ParamReport] = {}
    for name, p in params.items():
        if name in referenced:
            confirmed[name] = p.report
        else:
            out.degraded(f"params[{name}]", None, "declared but referenced by no edge, target or count — dropped")

    # 6. compile through the merge's emitter
    values_by_run = {rid: dict(ctx.values_by_run.get(rid, {})) for rid in sorted(kept)}
    try:
        wf, edge_by_col = _compile_emits(emits, interrupt_cands, name=ctx.name, version=ctx.version, task=ctx.task,
                                         n_runs=len(kept), run_values=values_by_run, confirmed=confirmed)
    except (ValueError, KeyError) as exc:
        return _fallback(ctx, draft, out, f"the emit plan did not compile: {exc}")
    for o in out.outcomes:
        m = re.match(r"^main\[(\d+)\]", o.item)
        if m and o.status != "rejected":
            o.transition = edge_by_col.get(int(m.group(1)))

    # derived params carry `derive`, no caller-facing default
    dwell_params = {e.dwell_param for e in emits if isinstance(e, _EmitStep) and e.dwell_param}
    new_params: list[Param] = []
    for p in wf.params:
        r = params.get(p.name)
        if p.name in dwell_params :
            p = p.model_copy(update={"description": f"{p.description}; {UNIT_NOTE}"})
        if r is not None and r.derive is not None:
            new_params.append(Param(name=p.name, required=False, derive=r.derive, description=(
                f"derived: {r.derive.from_param} / {r.derive.divide_by:g} ({r.derive.rounding}), min 1; "
                "the recordings' per-run counts: "
                + ", ".join(f"run {k}: {v}" for k, v in r.report.values_by_run.items()))))
        else:
            new_params.append(p)
    wf = wf.model_copy(update={"params": new_params})

    # 6b. media gates — an INVARIANT, not a draft choice (the compiler's _gate_media_states rule,
    #     generalized off the trajectory): a dwell, a folded gesture or a press whose recorded
    #     reading (taken just before the step ran, i.e. describing the state it runs FROM) shows the
    #     long content playing must run from a state gated on media_playing(min_duration_s) — else a
    #     replay spends the phase on a pre-roll ad in the same element while every selector holds
    #     (measured: the live MOP artifact's 60 s replay pressed six times against a 0:15 ad).
    _gate_media(wf, emits, out)

    # 7. accept (M13)
    conditions = [c for i, cond in enumerate(draft.accept)
                  if (c := _check_condition(i, cond, rec, kept, out)) is not None]
    validated = bool(conditions)
    if conditions:
        main_states = [s for s in wf.states if s.id.startswith("s")]
        final = main_states[-1] if main_states else wf.states[-1]
        existing = [c.model_dump(mode="json") for c in final.conditions]
        fresh = []
        for c in State(id="_accept", conditions=conditions).conditions:  # validated Trigger models
            if c.model_dump(mode="json") in existing:
                continue
            if c.type == "media_playing" and any(e.type == "media_playing" for e in final.conditions):
                continue  # the phase gate (6b) already holds the state to the content; one predicate suffices
            if c.type == "url_matches" and any(
                e.type == "url_matches" and re.search(e.pattern, c.pattern.removeprefix("^").replace("\\", ""))
                for e in final.conditions
            ):
                continue  # the state already recognizes this page (the compile's own base-URL condition)
            fresh.append(c)
        final.conditions = [*final.conditions, *fresh]
        if any(isinstance(c, MediaPlaying) for c in conditions):
            final.timeout_ms = max(final.timeout_ms, MEDIA_GATE_TIMEOUT_MS)
        wf.accept_states = [final.id]
    else:
        out.warnings.append("not-validated (no postcondition): no accept condition could be witnessed")
        wf.accept_states = []

    # 8. M14: the schema's own validators have the last word
    try:
        wf = Workflow.model_validate(wf.model_dump(mode="json"))
    except ValueError as exc:
        return _fallback(ctx, draft, out, f"the materialized workflow does not validate: {exc}")
    return GenerateOutcome(workflow=wf, draft=draft, outcomes=out.outcomes, warnings=out.warnings, validated=validated)


def _media_threshold(steps: list[AgentStep]) -> float | None:
    """min over the runs whose reading shows content ≥ MEDIA_GATE_MIN_CONTENT_S of half its duration,
    capped — the compiler's ad/content separator, taken at its most permissive across runs."""
    cands = []
    for st in steps:
        r = media_reading(st)
        if r is not None and r[0] == "PLAYING" and r[2] is not None and r[2] >= MEDIA_GATE_MIN_CONTENT_S:
            cands.append(min(round(r[2] / 2), MEDIA_GATE_CAP_S))
    return float(min(cands)) if cands else None


def _gate_media(wf: Workflow, emits: list, out: _Recorder) -> None:
    k = 0
    for emit in emits:
        if not isinstance(emit, _EmitStep):
            continue
        k += 1  # _compile_emits numbers main-path transitions t1, t2, … one per _EmitStep
        region = emit.dwell_param is not None or emit.repeat_param is not None or emit.repeat_count is not None
        if not region and emit.action.type not in ("press", "wait"):
            continue
        threshold = _media_threshold(list(emit.col.steps.values()))
        if threshold is None:
            continue
        t = wf.transition(f"t{k}")
        state = wf.state(t.target if region else t.source)  # a region runs on its own (self-loop) state
        if any(c.type == "media_playing" for c in state.conditions):
            continue
        state.conditions = [*state.conditions, MediaPlaying(min_duration_s=threshold)]
        state.timeout_ms = max(state.timeout_ms, MEDIA_GATE_TIMEOUT_MS)
        spine_step = emit.col.steps.get(min(emit.col.steps))
        out.degraded(f"main[{emit.col_index}].gate", ref_of(min(emit.col.steps), spine_step) if spine_step else None,
                     f"{state.id} gated on media_playing(min_duration_s={threshold:g}) — the recordings show the "
                     f"content playing when this {emit.action.type} ran; the draft did not ask for it")


def _num_str(v: str) -> str:
    n = _number_in(v)
    return v if n is None else (str(int(n)) if n == int(n) else str(n))


def _check_branch(node: DraftBranch, rec: _Recordings, kept: set[int], spine: int, out: _Recorder, item: str,
                  ) -> _EmitBranch | None:
    """A Branch: every arm's guard is the visibility of its `when` step's recorded target; arms are
    plain edges from that arm's runs; guards must be expressible and distinct. Else spine arm only."""
    arms: list[tuple[dict, list[AgentStep]]] = []
    runs_by_arm: list[list[int]] = []
    guards: set[str] = set()
    for j, arm in enumerate(node.arms):
        got = rec.resolve(arm.when, kept)
        if isinstance(got, str):
            out.no(item, arm.when, f"arm {j}: {got}")
            return None
        rid, when = got
        guard = _anchor(when.action)
        key = _canonical_locator(when.action)
        if guard is None or key in guards:
            out.no(item, arm.when, f"arm {j}: its guard is not expressible or not distinct")
            return None
        guards.add(key)
        steps: list[AgentStep] = []
        for sub in arm.then:
            if not isinstance(sub, DraftEdge):
                out.no(item, arm.when, f"arm {j}: only plain edges are supported inside a branch arm")
                return None
            g = rec.resolve(sub.step, kept)
            if isinstance(g, str) or g[0] not in arm.runs:
                why = g if isinstance(g, str) else "the step is not from one of the arm runs"
                out.no(item, sub.step, f"arm {j}: {why}")
                return None
            steps.append(g[1])
        if not steps:
            out.no(item, arm.when, f"arm {j} has no steps")
            return None
        arms.append((guard, steps))
        runs_by_arm.append(sorted(set(arm.runs) & kept))
    return _EmitBranch(arms, runs_by_arm)


Materializer = Callable[[WorkflowDraft, GeneratorContext], GenerateOutcome]
