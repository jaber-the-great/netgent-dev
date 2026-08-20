"""Run records: the trajectory a replay writes down, per NFA edge.

A RunRecord is NetGent's trajectory: the complete, typed, per-edge sequence of what was
done, whether the target state was recognized, and how long it took. It is an artifact
(saved, compared across runs), not a log (docs/browser-layer-design.md §5, §5.8).
"""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

EdgeOutcome = Literal["ok", "trigger_timeout", "action_error", "param_error"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConditionCheck(BaseModel):
    """One state condition and whether it held when the target state was evaluated."""

    type: str
    met: bool


class EdgeRecord(BaseModel):
    transition_id: str
    source: str
    target: str
    action_type: str
    outcome: EdgeOutcome
    started_at: datetime
    duration_ms: float
    trigger_latency_ms: float | None = None  # how long the target state took to be recognized
    conditions: list[ConditionCheck] = Field(default_factory=list)  # which conjuncts held/failed
    url_after: str | None = None
    screenshot: str | None = None  # path (relative to the run dir) of the post-edge screenshot
    error: str | None = None


class RunRecord(BaseModel):
    workflow_name: str
    workflow_version: str = "1"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    success: bool = False
    edges: list[EdgeRecord] = Field(default_factory=list)

    @property
    def duration_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000
