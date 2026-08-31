"""The planner's values: the plan it emits. Pydantic, like the other agents' models."""

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """One sub-goal for the explorer, in plain language, with the page evidence that shows it done."""

    description: str = Field(description="What to accomplish in this step, as an instruction to a browser agent.")
    expected_outcome: str = Field(
        default="", description="What the page should visibly show once this step is done (a message, a URL, …)."
    )


class Plan(BaseModel):
    """The planner's structured answer: the task decomposed into ordered sub-goals."""

    goal: str = Field(description="The task restated as one concrete, verifiable outcome.")
    steps: list[PlanStep] = Field(default_factory=list, description="Ordered sub-goals, each one explorer run's task.")
    notes: list[str] = Field(default_factory=list, description="Risks, ambiguities, or assumptions worth flagging.")

    def as_tasks(self) -> list[str]:
        """The steps as explorer tasks (what `explore()` is given)."""
        return [
            s.description + (f" Done when: {s.expected_outcome}" if s.expected_outcome else "") for s in self.steps
        ]
