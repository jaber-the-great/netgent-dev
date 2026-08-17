"""The compiled workflow artifact: states carry conditions, transitions carry one action.

The artifact's schema is these pydantic models. JSON and YAML are both accepted on disk —
they parse to the same tree, so the format is a loader detail chosen by file extension.
"""

import json
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field, model_validator

from netgent.core.actions import Action
from netgent.core.triggers import Trigger

DEFAULT_STATE_TIMEOUT_MS = 10_000


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
    start_state: str
    states: list[State]
    transitions: list[Transition]
    # Optional explicit control sequence (transition ids). Defaults to listed order.
    control_sequence: list[str] | None = None

    @model_validator(mode="after")
    def _validate_graph(self) -> Self:
        state_ids = [s.id for s in self.states]
        if len(state_ids) != len(set(state_ids)):
            raise ValueError("duplicate state ids")
        transition_ids = [t.id for t in self.transitions]
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("duplicate transition ids")
        known = set(state_ids)
        if self.start_state not in known:
            raise ValueError(f"start_state {self.start_state!r} is not a declared state")
        for t in self.transitions:
            if t.source not in known:
                raise ValueError(f"transition {t.id!r}: unknown source state {t.source!r}")
            if t.target not in known:
                raise ValueError(f"transition {t.id!r}: unknown target state {t.target!r}")
        if self.control_sequence is not None:
            unknown = set(self.control_sequence) - set(transition_ids)
            if unknown:
                raise ValueError(f"control_sequence references unknown transitions: {sorted(unknown)}")
        return self

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
