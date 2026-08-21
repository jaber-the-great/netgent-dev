"""Validation agent — proves a generated workflow replays, with ZERO LLM calls.

Replays the artifact through the ordinary executor in a fresh browser session, once per
parameter set, and reports per-replay edge outcomes. A workflow that does not validate is
reported loudly; it is never silently accepted.
"""

from netgent.agent.validation_agent.validate import ReplayResult, ValidationReport, validate_workflow

__all__ = ["ReplayResult", "ValidationReport", "validate_workflow"]
