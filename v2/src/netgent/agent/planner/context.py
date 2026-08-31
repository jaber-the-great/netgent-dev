"""What one planning run needs. Passed as LangGraph `Runtime.context`, never checkpointed —
the same slot the explorer and verifier use. No langchain/langgraph import."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from netgent.agent.llm import LLM

MAX_PLAN_STEPS = 12  # a plan longer than this is a sign the task should be split by the caller


@dataclass(frozen=True, slots=True)
class PlannerContext:
    llm: "LLM"
    max_steps: int = MAX_PLAN_STEPS  # plans are truncated to this many steps

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be >= 1")
