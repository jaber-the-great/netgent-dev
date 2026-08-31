"""The planner's values: the plan it emits. Pydantic, like the other agents' models."""

from pydantic import BaseModel, Field, field_validator


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


class TaskVariation(BaseModel):
    """One exploration run's task: the text the explorer is given, and the concrete values it embodies.

    `values` maps a PROPOSED parameter name (snake_case, e.g. video_query, watch_time) to the
    concrete value this variation uses. The names are hypotheses: the merge confirms a name as a
    workflow `Param` only if its values actually vary across runs and appear in the trajectories.
    """

    task_text: str = Field(description="The full task for this run, with this variation's values written in.")
    values: dict[str, str] = Field(
        default_factory=dict,
        description="Proposed param name -> the concrete value this variation uses (verbatim in task_text).",
    )

    @field_validator("values", mode="before")
    @classmethod
    def _values_to_str(cls, value: object) -> object:
        # Models return numbers for durations/counts; the artifact's params are strings.
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        return value


class VariationPlan(BaseModel):
    """The variation planner's structured answer: N same-family tasks with their values."""

    variations: list[TaskVariation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="Risks, ambiguities, or assumptions worth flagging.")


def normalize_variation_plan(
    plan: VariationPlan, task: str, n: int, pinned: dict[str, str] | None = None
) -> VariationPlan:
    """Make an LLM-drafted plan safe to run: exactly `n` variations, variation 1 is the base task
    verbatim, every variation carries the same value names (run 1's names are canonical — its
    values become the params' defaults), and `pinned` values are forced onto variation 2.

    Pure, so tests can pin the rules without a model.
    """
    notes = list(plan.notes)
    variations = [v.model_copy(deep=True) for v in plan.variations]
    if not variations:
        variations = [TaskVariation(task_text=task)]
        notes.append("planner returned no variations; using the base task only")
    # Variation 1 is the task exactly as asked: its values become the artifact's defaults.
    variations[0].task_text = task
    if pinned:
        target = variations[1] if len(variations) > 1 and n > 1 else variations[0]
        for name, value in pinned.items():
            target.values[name] = value
            if value.lower() not in target.task_text.lower():
                target.task_text += f" Use {name} = {value!r}."
        for name in pinned:  # a pinned name is canonical even if the planner missed it
            variations[0].values.setdefault(name, pinned[name])
    # Run 1's names are canonical: fill gaps with the base value, drop names run 1 lacks.
    canonical = dict(variations[0].values)
    for v in variations:
        dropped = sorted(set(v.values) - set(canonical))
        if dropped:
            notes.append(f"dropped value name(s) {dropped} not present in the base variation")
        v.values = {name: v.values.get(name, base) for name, base in canonical.items()}
    if len(variations) < n:
        notes.append(f"planner returned {len(variations)} variation(s); repeating the base task to reach {n}")
        while len(variations) < n:
            variations.append(variations[0].model_copy(deep=True))
    return VariationPlan(variations=variations[:n], notes=notes)
