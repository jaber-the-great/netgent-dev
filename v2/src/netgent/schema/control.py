"""The control program: how the executor traverses the graph, beyond a linear sequence.

The graph stays flat (states carry conditions, transitions carry one atomic action). What
changes is the *word* the planner emits over the transition alphabet: from a fixed string
(`control_sequence`) to a bounded regular expression — concatenation, capped repetition,
guard-dispatched branching, and (schema-only for now) sub-workflow calls.

Everything stays statically enumerable: no unbounded loops (max_iterations is mandatory),
no goto, no code. The executor can bound the max edge count before running.
See docs/research/long-horizon-agents.md §4.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from netgent.schema.triggers import Trigger


class EdgeStep(BaseModel):
    """Fire one transition (today's control_sequence entry)."""

    kind: Literal["edge"] = "edge"
    edge: str  # transition id


class Repeat(BaseModel):
    """Bounded loop: pagination, scroll-feed, dwell-with-keepalive.

    Runs `body` up to `max_iterations` times. Stops early when `until` conditions all hold
    (semantic stop, e.g. "no Next button"). `count` fixes the iteration count (int, or a
    "${param}" reference). max_iterations is the mandatory red-line backstop.
    """

    kind: Literal["repeat"] = "repeat"
    body: list[ControlNode]
    max_iterations: int = Field(gt=0)
    until: list[Trigger] | None = None
    count: str | int | None = None


class BranchArm(BaseModel):
    when: str  # a STATE id — this arm runs if that state's guard currently holds
    then: list[ControlNode]


class Branch(BaseModel):
    """Guard-dispatched branch: logged-in vs not, cookie wall present/absent.

    Arms are evaluated in order; the first whose `when` state holds runs. If none match,
    `else_` runs, or — with no else — it is new territory (a hard failure, never a silent skip).
    """

    kind: Literal["branch"] = "branch"
    arms: list[BranchArm]
    else_: list[ControlNode] | None = Field(default=None, alias="else")

    model_config = {"populate_by_name": True}


class Call(BaseModel):
    """Invoke a versioned sub-workflow (login, consent, player-start). Schema-only for now;
    the executor does not yet resolve a workflow library (docs/research/long-horizon-agents.md §4.3).
    """

    kind: Literal["call"] = "call"
    workflow: str  # library ref
    bind: dict[str, str] = Field(default_factory=dict)  # caller values → callee params


ControlNode = Annotated[
    Union[EdgeStep, Repeat, Branch, Call],
    Field(discriminator="kind"),
]


class Param(BaseModel):
    """A workflow-level parameter, substituted as ${name} in action string fields."""

    name: str
    description: str = ""
    required: bool = True
    default: str | None = None
    secret: bool = False  # secret values never appear in logs/records; only the name may


class Milestone(BaseModel):
    """A named segment anchor (reporting/heal-scope/dataset-labeling; no runtime logic)."""

    id: str
    description: str = ""
    state: str
    segment_edges: list[str] = Field(default_factory=list)


# Resolve the forward reference in Repeat.body / BranchArm.then.
Repeat.model_rebuild()
Branch.model_rebuild()
BranchArm.model_rebuild()
