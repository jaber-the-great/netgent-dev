"""The generator's values: what materialize did with each draft item (DraftOutcome) and what a
compile returns (GenerateOutcome). Pydantic, like the other agents' models: they are graph state,
they serialize into context.json, and the orchestrator/evals read them without importing the graph."""

from typing import Literal

from pydantic import BaseModel, Field

from netgent.agent.generator.draft import WorkflowDraft
from netgent.schema.workflow import Workflow


class DraftOutcome(BaseModel):
    """What materialize did with one draft item — the evidence trail behind draft_acceptance_rate.
    Same role, and same JSON shape, as the retired HintOutcome."""

    item: str  # "main[3].target", "params[1]", "interrupts[0]", "accept[0]", "runs"
    ref: str | None = None  # the StepRef it acted on
    status: Literal["applied", "rejected", "degraded"]
    reason: str = ""
    transition: str | None = None  # the edge it landed on


class GenerateOutcome(BaseModel):
    workflow: Workflow
    draft: WorkflowDraft | None = None
    outcomes: list[DraftOutcome] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated: bool = True  # False: no witnessed postcondition survived (§B.4 step 5)
    used_fallback: bool = False  # the merge's artifact was returned wholesale (§B.4 step 6)
    repairs_used: int = 0

    @property
    def rejections(self) -> list[str]:
        """The rejected items, verbatim — the repair turn's counter-examples."""
        return [f"{o.item}{f' ({o.ref})' if o.ref else ''}: {o.reason}"
                for o in self.outcomes if o.status == "rejected"]


def acceptance_rate(outcomes: list[DraftOutcome]) -> float | None:
    """applied ÷ proposed, or None when nothing was proposed."""
    if not outcomes:
        return None
    return sum(1 for o in outcomes if o.status == "applied") / len(outcomes)
