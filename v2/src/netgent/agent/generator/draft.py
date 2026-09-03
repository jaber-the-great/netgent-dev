"""The WorkflowDraft: a complete workflow whose every leaf is a POINTER into the recordings.

The LLM may choose structure (which steps, in what order, what loops, what is an interrupt, what
"done" means) and it may choose among options the browser layer already computed (which rung of a
locator ladder, which recorded literal is a param). It may never author content: no selector, no
regex, no URL, no id, no bound, no number the recordings do not contain. `materialize.py` resolves
every pointer against the stored AgentSteps and rejects, per item, what it cannot re-derive
(docs/research/generator-agent-v2.md §B.2). Pure pydantic — no langchain, no langgraph.
"""

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentStep

# ── addressing ───────────────────────────────────────────────────────────────

StepRef = Annotated[
    str,
    Field(
        pattern=r"^r\d+\.s\d+\.\d+$",
        description="A recorded step: r<run>.s<AgentStep.n>.<AgentStep.item>. Recordings are immutable, "
        "so this address is stable across rounds — unlike a merge column index.",
    ),
]

_REF = re.compile(r"^r(\d+)\.s(\d+)\.(\d+)$")


def ref_of(run: int, step: AgentStep) -> str:
    return f"r{run}.s{step.n}.{step.item}"


def parse_ref(ref: str) -> tuple[int, int, int] | None:
    """(run, n, item), or None when `ref` is not a StepRef."""
    m = _REF.match(ref or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


class LocatorRef(BaseModel):
    """Which rung of a recorded step's ladder to use, and how to close it."""

    step: StepRef
    rung: int = Field(
        default=0, ge=0,
        description="Index into that step's locator ladder as printed (the rung marked * is the chain the "
        "explorer used).",
    )
    nth: int | None = Field(
        default=None, ge=0,
        description="Append .nth(i) — 'the i-th match of this rung'. Only for a rung the recordings "
        "measured as resolving to > i elements with the acted element AT index i.",
    )
    name_param: str | None = Field(
        default=None,
        description="For a get_by_role rung only: replace the accessible name with ${param}. The recorded "
        "name must contain that run's value of the param, in every run.",
    )


# ── parameters ───────────────────────────────────────────────────────────────

WitnessField = Literal["text", "value", "url", "seconds", "press_count", "media_jump"]


class ParamWitness(BaseModel):
    """The literal this param took in ONE recorded step. No witness, no param."""

    step: StepRef
    field: WitnessField
    literal: str = Field(description="EXACTLY the substring/number recorded in that field of that step.")


class DraftParam(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["user", "page", "derived"] = "user"
    witnesses: list[ParamWitness] = Field(default_factory=list)
    # kind="derived": computed from another param at replay time, never supplied by the caller.
    # This is how "fast-forward 30s" becomes "3 presses" without the caller ever seeing presses (§D).
    derived_from: str | None = None
    divide_by: float | None = Field(default=None, gt=0)
    rounding: Literal["ceil", "floor", "nearest"] = "ceil"
    why: str = ""


# ── the control program ──────────────────────────────────────────────────────


class DraftEdge(BaseModel):
    kind: Literal["edge"] = "edge"
    step: StepRef = Field(description="The recorded SPINE step whose ACTION this transition carries.")
    target: LocatorRef | None = Field(
        default=None,
        description="None: keep the recorded chain. Set: use this rung instead (positional / text-param).",
    )
    value_param: str | None = Field(
        default=None,
        description="Bind this action's value field to ${param}. The param must have a witness on THIS step "
        "(or on one of its corroborating steps).",
    )
    corroborated_by: list[StepRef] = Field(
        default_factory=list,
        description="The same real step, as recorded in the OTHER runs. One per achieved run where it "
        "occurred. This is what lets code check support without a column index.",
    )
    why: str = ""


class CountSpec(BaseModel):
    """How many times a Repeat runs."""

    constant: int | None = Field(default=None, gt=0)
    param: str | None = Field(default=None, description="A DraftParam name; its value is the iteration count.")


class DraftRepeat(BaseModel):
    kind: Literal["repeat"] = "repeat"
    body: list["DraftNode"]
    count: CountSpec
    covers: list[StepRef] = Field(
        default_factory=list,
        description="EVERY recorded step, in every run, that this Repeat replaces. Code checks that they "
        "are contiguous per run, share one action signature, and occur in every kept run.",
    )
    why: str = ""


class DraftBranchArm(BaseModel):
    when: StepRef = Field(description="The step whose target's visibility guards this arm.")
    then: list["DraftNode"]
    runs: list[int] = Field(description="The runs that took this arm.")


class DraftBranch(BaseModel):
    kind: Literal["branch"] = "branch"
    arms: list[DraftBranchArm] = Field(min_length=2)
    why: str = ""


# A plain union, NOT a pydantic discriminated one: `Field(discriminator="kind")` emits the OpenAPI
# `discriminator` keyword into the JSON schema, which the claude-code route's strict validator
# rejects ("unknown keyword"). Each node's `kind` Literal disambiguates the union on its own.
DraftNode = Union[DraftEdge, DraftRepeat, DraftBranch]


# ── interrupts, accept, run policy ───────────────────────────────────────────


class DraftInterrupt(BaseModel):
    """A pop-up/ad handler. Code builds the anchor state, the done state, the resolve edge, the scope
    and max_fires; the LLM supplies only the classification and the evidence."""

    step: StepRef = Field(description="A recorded click that DISMISSED something.")
    rung: int | None = Field(default=None, description="A ladder rung to anchor on; None: the recorded chain.")
    also_seen: list[StepRef] = Field(default_factory=list, description="The same overlay in other runs.")
    why: str = Field(default="", description="What the reasoning or the task text says this dismisses.")


class DraftCondition(BaseModel):
    """A state condition, named by the recorded step that WITNESSES it. Code derives the predicate's
    content (the URL pattern, the selector, the duration threshold) from that step; the LLM never
    writes a pattern."""

    type: Literal["url_matches", "selector_visible", "selector_hidden", "media_playing"]
    witness: StepRef
    rung: int | None = None  # for selector_visible/hidden: which rung of that step's ladder (None: recorded)
    playing: bool = True  # for media_playing
    why: str = ""


class ExcludedRun(BaseModel):
    run: int
    reason: Literal["restarted", "off_task_detour", "truncated", "duplicate_of_another_run"]
    evidence: StepRef = Field(description="The step that shows it (e.g. the click that restarted the flow).")
    why: str = ""


class WorkflowDraft(BaseModel):
    spine: int = Field(description="The run whose step order the main path follows.")
    kept_runs: list[int] = Field(description="Runs that corroborate the main path (includes the spine).")
    excluded: list[ExcludedRun] = Field(default_factory=list)
    params: list[DraftParam] = Field(default_factory=list)
    main: list[DraftNode] = Field(default_factory=list)
    interrupts: list[DraftInterrupt] = Field(default_factory=list)
    accept: list[DraftCondition] = Field(min_length=1)
    notes: list[str] = Field(
        default_factory=list,
        description="What you considered and rejected, and anything the evidence could not settle.",
    )


DraftRepeat.model_rebuild()
DraftBranchArm.model_rebuild()
