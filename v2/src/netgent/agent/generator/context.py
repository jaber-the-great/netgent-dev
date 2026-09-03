"""What one generator compile needs. Passed as LangGraph `Runtime.context`, never checkpointed —
the same slot the explorer and verifier use. No langchain/langgraph import.

Everything here is a stored value: the achieved runs' recordings, the merge's evidence trail and
its own artifact (the fallback), the round's episodes and replay, and earlier rounds. The agent
owns no live resource (docs/research/generator-agent-v2.md §A)."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from netgent.agent.generator.merge import GeneralizedTrajectory, RunInput
    from netgent.agent.llm import LLM
    from netgent.agent.replay import ReplayReport
    from netgent.agent.rounds import RoundRecord
    from netgent.agent.triage import Episode
    from netgent.schema.workflow import Workflow

MAX_REPAIRS = 2
MAX_STEPS_SHOWN = 400  # the sampling red line (§G.3)


@dataclass(frozen=True, slots=True, kw_only=True)
class GeneratorContext:
    task: str
    runs: tuple["RunInput", ...]  # every run, in run order (achieved ones form the evidence; run 1 is the spine)
    generalized: "GeneralizedTrajectory"  # the merge's evidence trail (alignment + dispositions + keys)
    fallback: "Workflow"  # the merge's own artifact: what a fully-rejected draft returns
    llm: "LLM | None" = None  # None only for the pure materialize path (tests, the offline eval)
    url: str | None = None
    name: str = "workflow"
    version: str = "1"
    episodes: tuple["Episode", ...] = ()
    replay: "ReplayReport | None" = None
    prior: tuple["RoundRecord", ...] = ()  # earlier rounds, for the "you already tried this" block
    max_repairs: int = MAX_REPAIRS
    max_steps_shown: int = MAX_STEPS_SHOWN
    values_by_run: dict[int, dict[str, str]] = field(default_factory=dict)  # filled from runs when empty

    def __post_init__(self) -> None:
        if self.max_repairs < 0:
            raise ValueError("max_repairs must be >= 0")
        if not self.values_by_run:
            object.__setattr__(self, "values_by_run", {r.run: dict(r.values) for r in self.runs})

    def achieved(self) -> list["RunInput"]:
        return [r for r in self.runs if r.achieved and not r.scoped]
