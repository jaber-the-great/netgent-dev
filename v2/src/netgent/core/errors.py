"""The error taxonomy — pure types, part of the domain vocabulary.

Defined in core so every layer shares one hierarchy: browser and executor raise these,
the CLI and (later) the healing ladder catch them. Error classification feeds repair
(OVERVIEW.md decision #9: UI drift / flow drift / jitter).
"""


class NetgentError(Exception):
    """Base class for all netgent failures."""


# ── Artifact-level: the compiled workflow itself is unusable ─────────────────


class WorkflowError(NetgentError):
    """The workflow artifact is invalid or not walkable."""


class ControlSequenceError(WorkflowError):
    """The control sequence fires an edge from a state the run is not in."""


# ── Execution-level: replay failed against the live page ────────────────────


class ExecutionError(NetgentError):
    """Base class for run-time replay failures."""


class TriggerTimeoutError(ExecutionError):
    """A state's conditions were not recognized within its budget (flow drift signal)."""

    def __init__(self, state_id: str, unmet: list[str], timeout_ms: int):
        self.state_id = state_id
        self.unmet = unmet
        self.timeout_ms = timeout_ms
        super().__init__(f"state {state_id!r} not recognized within {timeout_ms}ms; unmet conditions: {unmet}")


class ActionDispatchError(ExecutionError):
    """An edge's action failed to execute against the live page."""


class LocatorResolutionError(ExecutionError):
    """A stored locator chain could not be resolved on the live page (UI drift signal)."""


class ElementDriftError(ExecutionError):
    """The resolved element no longer matches its compile-time fingerprint (UI drift signal).

    Reserved for the resolution/fingerprint layer (docs/browser-layer-design.md §2).
    """


class ParamError(ExecutionError):
    """A parameter couldn't be resolved: missing required value, a dynamic extraction that
    failed, or a value that failed its `validate` guard. A healable drift signal."""
