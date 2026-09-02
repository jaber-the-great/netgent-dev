"""The round context: what one `netgent generate --runs N --rounds R` accumulates across rounds.

Round r = plan → explore ×k → verify → merge (all runs so far) → compile → replay → triage →
{END | plan_next}. Everything the next round's planner may read, and everything the eval
bench scores per round (eval-framework.md §2.2 stage 7 — rounds_to_pass, episodes_per_round,
hint_acceptance_rate, tokens per run), lives here as typed records and is persisted as
`<name>.trajectories/context.json`. Pure pydantic; nothing here imports langchain.
"""

from typing import Any

from pydantic import BaseModel, Field

from netgent.agent.generator.hints import HintOutcome, acceptance_rate
from netgent.agent.generator.merge import GeneralizedTrajectory
from netgent.agent.planner.models import NextRoundPlan, TaskVariation
from netgent.agent.replay import ReplayReport
from netgent.agent.triage import Episode


class RunSummary(BaseModel):
    run: int
    round: int
    task_text: str
    values: dict[str, str] = Field(default_factory=dict)
    scoped: bool = False  # a scoped sub-task run: evidence, not a merge spine
    achieved: bool = False
    attempts: int = 1
    success: bool = False  # the explorer's own claim (recorded, never consulted)
    stopped_reason: str = ""
    steps: int = 0
    unmet: list[str] = Field(default_factory=list)  # the judge's unmet points
    usage: dict[str, int] | None = None  # this run's own LLM usage (a scoped view of the seam)


class ReplaySummary(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    success: bool = False
    signature: list[str] = Field(default_factory=list)
    failed_edge: str | None = None
    outcome: str | None = None
    unmet: list[str] = Field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_report(cls, report: ReplayReport | None) -> list["ReplaySummary"]:
        if report is None:
            return []
        return [cls(values=r.values, success=r.success, signature=r.signature, failed_edge=r.failed_edge,
                    outcome=r.outcome, unmet=r.unmet, error=(r.error or "")[:200] or None) for r in report.runs]


class ColumnSummary(BaseModel):
    index: int
    disposition: str
    action_type: str
    target: str | None = None
    param: str | None = None
    field: str | None = None
    support: int = 0
    runs: list[int] = Field(default_factory=list)
    values_by_run: dict[int, str] = Field(default_factory=dict)
    transition: str | None = None


class ParamSummary(BaseModel):
    name: str
    default: str = ""
    values_by_run: dict[int, str] = Field(default_factory=dict)


class GeneralizedSummary(BaseModel):
    """A compact generalized.json: what the planner reads and the bench scores."""

    achieved_runs: list[int] = Field(default_factory=list)
    params: list[ParamSummary] = Field(default_factory=list)
    columns: list[ColumnSummary] = Field(default_factory=list)
    interrupts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    hints: list[HintOutcome] = Field(default_factory=list)

    @classmethod
    def from_generalized(cls, gen: GeneralizedTrajectory) -> "GeneralizedSummary":
        return cls(
            achieved_runs=list(gen.achieved_runs),
            params=[ParamSummary(name=p.name, default=p.default, values_by_run=dict(p.values_by_run))
                    for p in gen.params],
            columns=[ColumnSummary(
                index=c.index, disposition=c.disposition, action_type=c.action_type,
                target=(c.target or None), param=c.param, field=c.field, support=c.support, runs=list(c.runs),
                values_by_run=dict(c.values_by_run), transition=c.transition,
            ) for c in gen.columns],
            interrupts=list(gen.interrupts), warnings=list(gen.warnings), hints=list(gen.hints),
        )


class RoundRecord(BaseModel):
    round: int
    variations: list[TaskVariation] = Field(default_factory=list)  # what this round explored
    runs: list[RunSummary] = Field(default_factory=list)
    generalized: GeneralizedSummary | None = None  # the merge of ALL achieved runs so far
    replay: list[ReplaySummary] = Field(default_factory=list)
    replay_passed: bool = False
    unseen_passed: int = 0  # value sets other than the artifact's defaults that replayed
    episodes: list[Episode] = Field(default_factory=list)
    # The hints THIS round's merge consumed (proposed by the previous round's plan_next), each
    # applied or rejected with a reason — hint_acceptance_rate is applied ÷ proposed.
    hints: list[HintOutcome] = Field(default_factory=list)
    next_plan: NextRoundPlan | None = None  # what plan_next proposed for the next round
    usage: dict[str, dict[str, int] | None] = Field(default_factory=dict)  # "plan" | "plan_next" | "run-k"
    exit: str = ""  # "" while the loop continues; passed | max_rounds | no_next_runs | unpassable | error

    def hint_acceptance_rate(self) -> float | None:
        return acceptance_rate(self.hints)


class RoundContext(BaseModel):
    task: str
    url: str | None = None
    runs_per_round: int = 1
    max_rounds: int = 1
    canonical_names: list[str] = Field(default_factory=list)  # run 1's value names, the params' universe
    base_values: dict[str, str] = Field(default_factory=dict)  # variation 1's values (the defaults)
    rounds: list[RoundRecord] = Field(default_factory=list)

    @property
    def current(self) -> RoundRecord:
        return self.rounds[-1]

    def latest_columns(self) -> list[ColumnSummary]:
        for r in reversed(self.rounds):
            if r.generalized is not None:
                return r.generalized.columns
        return []

    def all_values_seen(self) -> list[dict[str, str]]:
        return [r.values for rd in self.rounds for r in rd.runs]

    def total_usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for rd in self.rounds:
            for u in rd.usage.values():
                for k, v in (u or {}).items():
                    total[k] = total.get(k, 0) + int(v)
        return total
