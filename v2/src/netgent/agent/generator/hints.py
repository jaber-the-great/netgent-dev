"""Generalization hints — the closed vocabulary `plan_next` may speak and the generator can act on.

A hint is a typed CHOICE among options the recordings already contain, never a selector, a
regex, an action or artifact content (docs/research/generator-agent.md §C.0, §C.3). Code
re-derives every hint from the recordings before applying it (the validation rules of §C.4);
a rejected hint leaves the draft unchanged and is recorded as `HintOutcome(rejected, reason)`
in generalized.json and the round context, so `hint_acceptance_rate` is a number per round
(docs/research/eval-framework.md §2.2 stage 7).
"""

from typing import Literal

from pydantic import BaseModel, Field

HintIntent = Literal["positional", "text_contains_param", "instance"]


class RepeatFold(BaseModel):
    """Fold consecutive identical steps at the hinted column into ONE Repeat.

    `kind` names the folded action (press: N identical key presses = one gesture, e.g. three
    `l` = a 30 s fast-forward). `count_param` is the planner param whose per-run values
    explain the per-run iteration counts; code binds it only if the counts equal the planned
    numbers, or equal them divided by one constant integer factor in every run (10 s per
    press) — then the artifact's Param is the COUNT, with the factor in its description.
    """

    kind: Literal["press", "click"] = "press"
    count_param: str | None = None


class GeneralizationHint(BaseModel):
    """One typed edit request, keyed by the merge's column index."""

    column: int = Field(description="The aligned column (generalized.json `columns[].index`) this hint is about.")
    intent: HintIntent = Field(
        default="instance",
        description="positional: the task meant 'the N-th item', switch the column to the structural rung + nth; "
        "text_contains_param: the target's accessible name contains a param value (param_name); "
        "instance: keep the recorded target.",
    )
    param_name: str | None = Field(
        default=None, description="For text_contains_param / repeat_fold: the planner param name (snake_case)."
    )
    repeat_fold: RepeatFold | None = Field(default=None, description="Fold consecutive identical steps here.")
    why: str = Field(default="", description="One clause of evidence from the task text or the episodes.")


class HintOutcome(BaseModel):
    """What the generator did with a hint — the evidence trail behind hint_acceptance_rate."""

    hint: GeneralizationHint
    status: Literal["applied", "rejected"]
    reason: str = ""  # why it was rejected, or what was applied (a rung, a Repeat, a param)
    transition: str | None = None  # the main-path transition the applied edit landed on


def acceptance_rate(outcomes: list[HintOutcome]) -> float | None:
    """applied ÷ proposed, or None when nothing was proposed."""
    if not outcomes:
        return None
    return sum(1 for o in outcomes if o.status == "applied") / len(outcomes)
