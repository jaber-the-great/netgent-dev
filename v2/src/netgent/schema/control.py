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


class ParamSource(BaseModel):
    """Where a DYNAMIC parameter's value comes from — extracted from the live page at
    runtime, so a value observed on one page can feed a later step's ${name}.

    kind: text (element inner text) | input_value (a field's value) | attribute (an
    element attribute) | url_group (a capture group of a regex over the current URL).
    """

    kind: Literal["text", "input_value", "attribute", "url_group"]
    selector: str | None = None  # CSS, for text/input_value/attribute
    frame_path: list[str] = Field(default_factory=list)  # iframe chain the selector lives in; [] = top
    attribute: str | None = None  # for kind=attribute
    pattern: str | None = None  # regex over page.url, for kind=url_group
    group: int = 1  # which capture group, for kind=url_group


class ParamDerivation(BaseModel):
    """A param COMPUTED from another param at resolve time — never supplied by the caller.

    The bridge between the task's vocabulary ("fast-forward 45 seconds") and the artifact's
    ("press `l` five times"), for gestures whose unit the recordings measured. Closed and tiny
    on purpose: one source param, one divisor, one rounding rule, a floor. No expressions.
    (docs/research/generator-agent-v2.md §D.4)
    """

    from_param: str
    divide_by: float = Field(default=1.0, gt=0)
    rounding: Literal["ceil", "floor", "nearest"] = "ceil"
    min: int = Field(default=1, ge=0)


class Param(BaseModel):
    """A workflow parameter, substituted as ${name} in action string fields.

    Static (source=None): supplied by the caller / default. Dynamic (source set):
    extracted from the page at runtime. Derived (derive set): computed from another
    param by `resolve_params`, never caller-supplied. `guard` is a regex the resolved
    value must match — a failed extraction or validation is a healable drift signal.
    """

    name: str
    description: str = ""
    required: bool = True
    default: str | None = None
    secret: bool = False  # secret values never appear in logs/records; only the name may
    source: ParamSource | None = None  # None = static (caller-provided); set = dynamic
    guard: str | None = None  # regex the resolved value must match
    derive: ParamDerivation | None = None  # set ⇒ computed at resolve time; the caller may not pass it


class Interrupt(BaseModel):
    """A scoped, bounded ε-interrupt: a pop-up/ad state and how to resolve it.

    The formalism's "pop-ups are states reached by ε-transitions": `state` is the pop-up
    state (its conditions are the anchor — "is the pop-up here?"), `resolve` is the chain
    of ordinary one-action transitions that dismisses it. The executor sweeps in-scope
    interrupts between control-program nodes: when the anchor holds, it runs the chain,
    re-verifies the state it was in, and continues the program where it left off.

    `scope` lists the main-path states the interrupt is armed from (in-scope ε-edges —
    never global). `max_fires` is the mandatory red-line backstop, like Repeat.max_iterations:
    it keeps the executed run statically bounded (|program| + Σ max_fires × |resolve|).
    `resolve_timeout_ms` bounds how long each resolve edge waits for its done state: the done
    state is a NEGATIVE condition on an element just clicked, so a full state timeout is the
    wrong budget (measured: six phantom interrupts burned ~63 s of a ~104 s replay at 10 s
    each; generator-agent-v2.md §F.3).
    """

    id: str
    description: str = ""
    state: str  # the pop-up state; its conditions are the anchor
    resolve: list[str] = Field(min_length=1)  # transition ids, chained from `state`
    scope: list[str] = Field(min_length=1)  # main-path state ids this interrupt is armed from
    max_fires: int = Field(default=3, gt=0)
    resolve_timeout_ms: int = Field(default=2000, gt=0)


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
