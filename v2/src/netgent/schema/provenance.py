"""Provenance: how a workflow artifact was produced and whether it was validated.

Written by `netgent generate` (explore → synthesize → validate). A consumer can tell at a
glance whether the artifact replayed cleanly with zero LLM calls before it was written,
and for which parameter values. `validated: false` is loud, never silent.
"""

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """One zero-LLM replay of the synthesized workflow with a concrete param set."""

    params: dict[str, str] = Field(default_factory=dict)
    success: bool
    edges_ok: int = 0
    failed_edge: str | None = None  # transition id that failed, if any
    failed_state: str | None = None  # its target state
    unmet: list[str] = Field(default_factory=list)  # unmet condition types at the failure
    error: str | None = None


class Provenance(BaseModel):
    generated_at: str  # ISO-8601 UTC
    generator: str | None = None  # LLM used for exploration (provider/model)
    runs: int = 1  # explorations attempted
    successful_runs: int = 1  # explorations that reached `done`
    variations: list[dict[str, str]] = Field(default_factory=list)  # alternate param samples explored
    validated: bool = False  # every validation replay passed
    validation: list[ValidationResult] = Field(default_factory=list)
    relaxed: list[str] = Field(default_factory=list)  # conditions dropped after a failed validation
    notes: list[str] = Field(default_factory=list)  # synthesis decisions worth reading (minimization, branches)
