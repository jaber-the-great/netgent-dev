"""The planner's values: the plan it emits. Pydantic, like the other agents' models."""

import re

from pydantic import BaseModel, Field, field_validator

from netgent.agent.generator.hints import GeneralizationHint

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


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


class ScopedSubtask(BaseModel):
    """A segment to explore on its own ("search for X and open the first result") from a start
    URL — evidence for one column, never a merge spine."""

    task_text: str = Field(description="The segment as a task for the browser agent, with concrete values written in.")
    start_url: str = Field(description="Where the segment starts.")
    values: dict[str, str] = Field(default_factory=dict, description="Param name -> the value the segment uses.")

    @field_validator("values", mode="before")
    @classmethod
    def _values_to_str(cls, value: object) -> object:
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items()}
        return value


class NextRoundPlan(BaseModel):
    """The next-round planner's structured answer: what to explore next, and typed hints the
    generator may act on (a closed vocabulary; code re-derives every hint from the recordings)."""

    next_variations: list[TaskVariation] = Field(
        default_factory=list, description="Full-task variations to explore next (same family; values verbatim)."
    )
    scoped_subtasks: list[ScopedSubtask] = Field(
        default_factory=list, description="Optional segments to explore on their own (evidence only)."
    )
    generalization_hints: list[GeneralizationHint] = Field(
        default_factory=list, description="Per-episode typed hints for the generator, keyed by column."
    )
    notes: list[str] = Field(default_factory=list, description="What was considered and why.")


def normalize_next_round_plan(
    plan: NextRoundPlan,
    *,
    n: int,
    canonical_names: list[str],
    base_values: dict[str, str],
    columns: list[int],
) -> NextRoundPlan:
    """Make an LLM-drafted next-round plan safe to run (pure; tests pin the rules):

    - at most `n` runs in total (full variations first, scoped sub-tasks fill the remainder);
    - every variation carries exactly the canonical value names (unknown names dropped, gaps
      filled from the base values) and every value appears VERBATIM in its task_text (else the
      sentence "Use name = 'value'." is appended, as `normalize_variation_plan` does);
    - hints name an existing column, at most one per column; a param name must be canonical
      and snake_case, else it is cleared (the hint stays: a fold can still be constant).
    """
    notes = list(plan.notes)
    canonical = list(canonical_names)
    variations: list[TaskVariation] = []
    for v in plan.next_variations:
        text = (v.task_text or "").strip()
        if not text:
            notes.append("dropped a variation with empty task_text")
            continue
        dropped = sorted(set(v.values) - set(canonical))
        if dropped:
            notes.append(f"dropped value name(s) {dropped} not among the canonical names {canonical}")
        values = {name: v.values.get(name, base_values.get(name, "")) for name in canonical}
        for name, value in values.items():
            if value and value.lower() not in text.lower():
                text += f" Use {name} = {value!r}."
        variations.append(TaskVariation(task_text=text, values=values))
    variations = variations[:n]
    scoped: list[ScopedSubtask] = []
    for st in plan.scoped_subtasks:
        if not st.task_text.strip() or not st.start_url.strip():
            notes.append("dropped a scoped sub-task with no task_text/start_url")
            continue
        if len(variations) + len(scoped) >= n:
            notes.append("scoped sub-task dropped: the round's run budget is spent")
            break
        scoped.append(st.model_copy(update={"values": {k: val for k, val in st.values.items() if k in canonical}}))
    hints: list[GeneralizationHint] = []
    seen: set[int] = set()
    for h in plan.generalization_hints:
        if h.column not in columns:
            notes.append(f"dropped a hint for unknown column {h.column}")
            continue
        if h.column in seen:
            notes.append(f"dropped a second hint for column {h.column}")
            continue
        seen.add(h.column)
        h = h.model_copy(deep=True)
        if h.param_name is not None and (not _NAME_RE.match(h.param_name) or h.param_name not in canonical):
            notes.append(f"hint for column {h.column}: param_name {h.param_name!r} is not a canonical name; cleared")
            h.param_name = None
        if h.repeat_fold is not None and h.repeat_fold.count_param is not None and (
            not _NAME_RE.match(h.repeat_fold.count_param) or h.repeat_fold.count_param not in canonical
        ):
            notes.append(
                f"hint for column {h.column}: count_param {h.repeat_fold.count_param!r} is not canonical; cleared"
            )
            h.repeat_fold.count_param = None
        hints.append(h)
    return NextRoundPlan(next_variations=variations, scoped_subtasks=scoped, generalization_hints=hints, notes=notes)
