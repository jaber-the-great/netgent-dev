"""Run records: what a replay writes down, per NFA edge (docs/browser-layer-design.md §5)."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

EdgeOutcome = Literal["ok", "trigger_timeout", "action_error"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EdgeRecord(BaseModel):
    transition_id: str
    source: str
    target: str
    action_type: str
    outcome: EdgeOutcome
    started_at: datetime
    duration_ms: float
    trigger_latency_ms: float | None = None  # how long the target state took to be recognized
    url_after: str | None = None
    error: str | None = None


class RunRecord(BaseModel):
    workflow_name: str
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    success: bool = False
    edges: list[EdgeRecord] = Field(default_factory=list)
