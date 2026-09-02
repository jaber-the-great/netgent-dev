"""Triage — pure code that turns one round's evidence into typed Episodes the next round acts on.

Inputs: this round's per-run verdicts, the merge's evidence trail (`GeneralizedTrajectory`:
column dispositions, warnings, params, the transition each column compiled to), the zero-LLM
replay report, and the runs themselves (their recorded steps carry the locator ladders of M0).
Output: `Episode`s in a closed vocabulary (docs/research/agent-verification.md §6.4 shape):

    positional_target  an aligned click column whose targets differ across runs, match no
                       planned value, and sit on a list-like container ("the first result")
    unbound_value      a value field that differs across runs and matches no planned value
    conditional_step   a step present in k < N runs, dismissal-shaped (an interrupt candidate)
    flow_drift         the replay stopped at an edge (FAILED@tN) whose column has no more
                       specific episode; carries the unmet conjuncts
    unpassable         no run achieved the task (every run failed the same way)
    judge_unmet        a judge caveat on an achieved run that no passing replay contradicts

Authority (§6.4, generator-agent.md §B.8.3): replay and merge signals are authoritative;
the judge's are advisory and are dropped when a replay with that run's values passed.
Zero LLM; nothing here imports langchain.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentStep
from netgent.agent.generator.merge import ColumnReport, GeneralizedTrajectory, RunInput
from netgent.agent.replay import ReplayReport

EpisodeKind = Literal[
    "positional_target", "unbound_value", "conditional_step", "flow_drift", "unpassable", "judge_unmet",
]
Source = Literal["replay", "merge", "judge"]

# Roles whose instances are list members — a click on one is plausibly "the N-th item".
_LISTY_ROLES = frozenset({
    "link", "listitem", "option", "row", "cell", "gridcell", "article", "heading", "treeitem", "menuitem", "tab",
})
_NTH_RE = re.compile(r":nth-(of-type|child)\(|>>\s*nth=")


class Episode(BaseModel):
    kind: EpisodeKind
    source: Source
    column: int | None = None  # generalized.json `columns[].index`
    transition: str | None = None  # the main-path edge (replay: where it stopped)
    action_type: str | None = None
    field: str | None = None  # unbound_value: the differing action field
    runs: list[int] = Field(default_factory=list)  # the runs this evidence comes from
    observed: dict[int, str] = Field(default_factory=dict)  # per-run targets / values
    planned: dict[str, dict[int, str]] = Field(default_factory=dict)  # planner name -> per-run values
    replay_values: dict[str, str] = Field(default_factory=dict)  # the value set that failed (replay)
    unmet: list[str] = Field(default_factory=list)  # replay: unmet conjunct types; judge: its unmet points
    confirmed_by_replay: bool = False
    detail: str = ""

    def as_line(self) -> str:
        """One compact line for the next-round planner (and the round log)."""
        where = f" column {self.column}" if self.column is not None else ""
        edge = f" at {self.transition}" if self.transition else ""
        obs = "; ".join(f"run {r}: {v[:70]!r}" for r, v in sorted(self.observed.items()))
        bits = [f"{self.kind}{where}{edge} [{self.source}{', replay-confirmed' if self.confirmed_by_replay else ''}]"]
        if self.action_type:
            bits.append(f"{self.action_type}{'.' + self.field if self.field else ''}")
        if obs:
            bits.append(obs)
        if self.unmet:
            bits.append("unmet: " + "; ".join(u[:80] for u in self.unmet))
        if self.replay_values:
            bits.append(f"replay values {self.replay_values}")
        if self.detail:
            bits.append(self.detail[:160])
        return " — ".join(bits)


def _step_at(runs: list[RunInput], col: ColumnReport) -> dict[int, AgentStep]:
    """The recorded steps behind a column, by run — matched on the column's per-run targets."""
    from netgent.agent.generator.merge import _canonical_locator

    out: dict[int, AgentStep] = {}
    by_run = {r.run: r for r in runs}
    for rid, target in col.targets_by_run.items():
        run = by_run.get(rid)
        if run is None:
            continue
        for s in run.trajectory.steps:
            if s.action is not None and s.error is None and s.action.type == col.action_type \
                    and _canonical_locator(s.action) == target:
                out[rid] = s
                break
    return out


def _list_like(step: AgentStep | None, target: str) -> bool:
    """Does the click sit on a list-like container? The M0 ladder is the real signal (a
    structural rung exists); a listy role or a positional css path is the fallback for
    records made before M0."""
    if step is not None and "structural" in step.candidate_kinds:
        return True
    role = None
    if step is not None:
        locator = getattr(step.action, "locator", None) or []
        for st in locator:
            if st.fn == "get_by_role" and st.args:
                role = str(st.args[0])
        role = role or (step.element or {}).get("role")
    if role in _LISTY_ROLES:
        return True
    m = re.match(r"role=(\w+)", target or "")
    if m and m.group(1) in _LISTY_ROLES:
        return True
    return bool(_NTH_RE.search(target or ""))


def _planned_values(runs: list[RunInput], rids: list[int]) -> dict[str, dict[int, str]]:
    by_run = {r.run: r.values for r in runs}
    names = sorted({n for rid in rids for n in by_run.get(rid, {})})
    return {n: {rid: by_run.get(rid, {}).get(n, "") for rid in rids} for n in names}


def _run_value_set(gen: GeneralizedTrajectory, rid: int) -> dict[str, str]:
    return {p.name: p.values_by_run.get(rid, p.default) for p in gen.params}


def triage(
    *,
    generalized: GeneralizedTrajectory,
    replay: ReplayReport | None,
    runs: list[RunInput],
    verdicts: dict[int, object] | None = None,
) -> list[Episode]:
    """One round's evidence → typed Episodes (see the module docstring for the rules)."""
    verdicts = verdicts or {}
    achieved = [r for r in runs if r.achieved]
    if not achieved:
        unmet = sorted({u for v in verdicts.values() for u in (getattr(v, "unmet", None) or [])})
        reasons = sorted({r.trajectory.stopped_reason[:80] for r in runs if r.trajectory.stopped_reason})
        return [Episode(
            kind="unpassable", source="merge", runs=[r.run for r in runs], unmet=unmet,
            detail="no run achieved the task" + (f"; stopped: {' | '.join(reasons)}" if reasons else ""),
        )]

    episodes: list[Episode] = []
    by_column: dict[int, Episode] = {}
    for col in generalized.columns:
        steps = _step_at(runs, col)
        if col.disposition == "target-varies" and col.action_type == "click":
            spine = min(col.targets_by_run) if col.targets_by_run else None
            if _list_like(steps.get(spine) if spine is not None else None, col.target or ""):
                ep = Episode(
                    kind="positional_target", source="merge", column=col.index, transition=col.transition,
                    action_type="click", runs=col.runs, observed=dict(col.targets_by_run),
                    planned=_planned_values(runs, col.runs),
                    detail="targets differ across runs and match no planned value; a list-like target — "
                           "the task may mean a position, not a title",
                )
                episodes.append(ep)
                by_column[col.index] = ep
        elif col.disposition == "value-diverges":
            ep = Episode(
                kind="unbound_value", source="merge", column=col.index, transition=col.transition,
                action_type=col.action_type, field=col.field, runs=col.runs, observed=dict(col.values_by_run),
                planned=_planned_values(runs, col.runs),
                detail=f"{col.action_type}.{col.field} differs across runs and matches no planned value; "
                       "kept run 1's",
            )
            episodes.append(ep)
            by_column[col.index] = ep
        elif col.disposition == "interrupt":
            ep = Episode(
                kind="conditional_step", source="merge", column=col.index, action_type=col.action_type,
                runs=col.runs, observed=dict(col.targets_by_run),
                detail=f"present in {col.support}/{len(achieved)} runs, dismissal-shaped: an interrupt candidate",
            )
            episodes.append(ep)
            by_column[col.index] = ep

    # Replay: authoritative. A failed edge confirms the episode already on its column, or is
    # flow drift of its own.
    col_of_edge = {c.transition: c.index for c in generalized.columns if c.transition}
    for rr in (replay.runs if replay is not None else []):
        if rr.success or rr.failed_edge is None:
            continue
        col_index = col_of_edge.get(rr.failed_edge)
        existing = by_column.get(col_index) if col_index is not None else None
        if existing is not None:
            existing.confirmed_by_replay = True
            existing.transition = rr.failed_edge
            existing.replay_values = dict(rr.values)
            existing.unmet = list(rr.unmet)
            continue
        ep = Episode(
            kind="flow_drift", source="replay", column=col_index, transition=rr.failed_edge,
            action_type=next((c.action_type for c in generalized.columns if c.index == col_index), None),
            replay_values=dict(rr.values), unmet=list(rr.unmet), confirmed_by_replay=True,
            detail=f"replay stopped at {rr.failed_edge} ({rr.outcome}): {(rr.error or '')[:160]}",
        )
        episodes.append(ep)
        if col_index is not None:
            by_column[col_index] = ep

    # Judge: advisory. A caveat on an achieved run stands only if no passing replay with that
    # run's own values contradicts it.
    passed_sets = [rr.values for rr in (replay.runs if replay is not None else []) if rr.success]
    for r in achieved:
        v = verdicts.get(r.run)
        unmet = list(getattr(v, "unmet", None) or [])
        if not unmet:
            continue
        if _run_value_set(generalized, r.run) in passed_sets:
            continue  # the artifact replays for this run's values: the caveat is contradicted
        episodes.append(Episode(
            kind="judge_unmet", source="judge", runs=[r.run], unmet=unmet,
            detail="the judge's caveat on an achieved run; no passing replay contradicts it",
        ))
    return episodes

