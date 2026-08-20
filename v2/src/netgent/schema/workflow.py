"""The compiled workflow artifact: states carry conditions, transitions carry one action.

The artifact's schema is these pydantic models. JSON and YAML are both accepted on disk —
they parse to the same tree, so the format is a loader detail chosen by file extension.
"""

import json
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from netgent.schema.actions import Action
from netgent.schema.control import Branch, ControlNode, EdgeStep, Milestone, Param, Repeat
from netgent.schema.triggers import Trigger

DEFAULT_STATE_TIMEOUT_MS = 10_000


def _edges_in(nodes: list[ControlNode]) -> set[str]:
    """Every transition id referenced anywhere in a control program (for validation)."""
    edges: set[str] = set()
    for node in nodes:
        if isinstance(node, EdgeStep):
            edges.add(node.edge)
        elif isinstance(node, Repeat):
            edges |= _edges_in(node.body)
        elif isinstance(node, Branch):
            for arm in node.arms:
                edges |= _edges_in(arm.then)
            if node.else_:
                edges |= _edges_in(node.else_)
    return edges


def _states_in(nodes: list[ControlNode]) -> set[str]:
    """Every state id referenced by Branch arms in a control program (for validation)."""
    states: set[str] = set()
    for node in nodes:
        if isinstance(node, Repeat):
            states |= _states_in(node.body)
        elif isinstance(node, Branch):
            for arm in node.arms:
                states.add(arm.when)
                states |= _states_in(arm.then)
            if node.else_:
                states |= _states_in(node.else_)
    return states


class State(BaseModel):
    """A node: recognized when all of its conditions hold."""

    id: str
    description: str = ""
    conditions: list[Trigger] = Field(default_factory=list)
    timeout_ms: int = DEFAULT_STATE_TIMEOUT_MS


class Transition(BaseModel):
    """An edge: exactly one atomic action, from source state to target state."""

    id: str
    source: str
    target: str
    action: Action


class Workflow(BaseModel):
    name: str
    # Revision of THIS workflow: "1", "2", ... — bump when the flow is re-compiled/edited.
    # Provenance for run records and datasets, so traces from different revisions aren't conflated.
    version: str = Field(default="1", pattern=r"^[1-9][0-9]*$")

    @field_validator("version", mode="before")
    @classmethod
    def _int_version_ok(cls, value: object) -> object:
        # YAML parses an unquoted `version: 2` as an int — accept it as "2".
        return str(value) if isinstance(value, int) else value
    start_state: str
    states: list[State]
    transitions: list[Transition]
    params: list[Param] = Field(default_factory=list)
    # Legacy linear plan (transition ids); superseded by `control`. Kept one release, deprecated.
    control_sequence: list[str] | None = None
    # The control program: a bounded regular expression over transitions (loops/branches/calls).
    control: list[ControlNode] | None = None
    # Success condition: replay succeeded iff an accept state's guard holds at program end.
    # Empty = legacy behavior (success = every edge ok).
    accept_states: list[str] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> Self:
        state_ids = [s.id for s in self.states]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("duplicate state ids")
        transition_ids = [t.id for t in self.transitions]
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("duplicate transition ids")
        known = set(state_ids)
        known_edges = set(transition_ids)
        if self.start_state not in known:
            raise ValueError(f"start_state {self.start_state!r} is not a declared state")
        for t in self.transitions:
            if t.source not in known:
                raise ValueError(f"transition {t.id!r}: unknown source state {t.source!r}")
            if t.target not in known:
                raise ValueError(f"transition {t.id!r}: unknown target state {t.target!r}")
        if self.control_sequence is not None:
            unknown = set(self.control_sequence) - known_edges
            if unknown:
                raise ValueError(f"control_sequence references unknown transitions: {sorted(unknown)}")
        if self.control is not None:
            if self.control_sequence is not None:
                raise ValueError("set either control or control_sequence, not both")
            unknown_e = _edges_in(self.control) - known_edges
            if unknown_e:
                raise ValueError(f"control references unknown transitions: {sorted(unknown_e)}")
            unknown_s = _states_in(self.control) - known
            if unknown_s:
                raise ValueError(f"control (branch) references unknown states: {sorted(unknown_s)}")
        for milestone in self.milestones:
            if milestone.state not in known:
                raise ValueError(f"milestone {milestone.id!r}: unknown state {milestone.state!r}")
        unknown_accept = set(self.accept_states) - known
        if unknown_accept:
            raise ValueError(f"accept_states reference unknown states: {sorted(unknown_accept)}")
        return self

    def as_control(self) -> list[ControlNode]:
        """The control program to run: `control`, else `control_sequence`, else declared order."""
        if self.control is not None:
            return self.control
        ids = self.control_sequence if self.control_sequence is not None else [t.id for t in self.transitions]
        return [EdgeStep(edge=i) for i in ids]

    def state(self, state_id: str) -> State:
        for s in self.states:
            if s.id == state_id:
                return s
        raise KeyError(state_id)

    def transition(self, transition_id: str) -> Transition:
        for t in self.transitions:
            if t.id == transition_id:
                return t
        raise KeyError(transition_id)


def resolve_params(workflow: Workflow, values: dict[str, str] | None = None) -> Workflow:
    """Substitute ${name} in the workflow's string fields from params + provided values.

    Missing required params raise ValueError. Returns a new, re-validated Workflow.
    """
    values = dict(values or {})
    resolved: dict[str, str] = {}
    for p in workflow.params:
        if p.source is not None:  # dynamic: extracted from the live page at dispatch, not here
            continue
        if p.name in values:
            resolved[p.name] = values[p.name]
        elif p.default is not None:
            resolved[p.name] = p.default
        elif p.required:
            raise ValueError(f"missing required param {p.name!r}")

    def sub(node: object) -> object:
        if isinstance(node, str):
            for name, value in resolved.items():
                node = node.replace("${" + name + "}", value)
            return node
        if isinstance(node, list):
            return [sub(x) for x in node]
        if isinstance(node, dict):
            return {k: sub(v) for k, v in node.items()}
        return node

    data = sub(workflow.model_dump(mode="json"))
    return Workflow.model_validate(data)


def load_workflow(path: Path | str) -> Workflow:
    """Load a compiled workflow from a .json, .yaml, or .yml file."""
    path = Path(path)
    text = path.read_text()
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        raise ValueError(f"unsupported workflow format {suffix!r} (expected .json, .yaml, or .yml)")
    return Workflow.model_validate(data)


def dump_workflow(workflow: Workflow, path: Path | str) -> None:
    """Write a workflow to disk; format chosen by the file extension."""
    path = Path(path)
    data = workflow.model_dump(mode="json", exclude_none=True)
    suffix = path.suffix.lower()
    if suffix == ".json":
        path.write_text(json.dumps(data, indent=2) + "\n")
    elif suffix in (".yaml", ".yml"):
        path.write_text(yaml.safe_dump(data, sort_keys=False))
    else:
        raise ValueError(f"unsupported workflow format {suffix!r} (expected .json, .yaml, or .yml)")
