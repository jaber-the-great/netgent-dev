"""The agent's per-step decision — the LLM's structured output.

Actions reference an element by its `index` in the current observation (not a raw locator),
which the agent resolves to a durable locator chain from the element's candidate selectors.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AgentActionKind = Literal[
    "click", "fill", "select", "upload",
    "hover", "press", "goto", "scroll", "go_back", "wait", "done",
]


class AgentDecision(BaseModel):
    """One step. `done` is the only exit: success=True when the task is complete,
    success=False when it cannot proceed (e.g. a CAPTCHA appeared) — say why in `reasoning`."""

    # `reasoning` (and the working-memory fields below) stay FIRST: format-restricted output
    # degrades reasoning, and free-form tokens generated before the constrained fields are the
    # standard mitigation (Tam et al. 2024, arXiv:2408.02442). Do not "tidy" the field order.
    evaluation: str = Field(
        default="",
        description="One sentence on whether your PREVIOUS action achieved its goal, ending in "
        "'Verdict: Success', 'Verdict: Failure' or 'Verdict: Unclear'. Judge from the observation — an "
        "action that dispatched without error may still have done nothing. Empty on the first step.",
    )
    memory: str = Field(
        default="",
        description="1-2 sentences of progress you must not lose: counts, values entered, what is left.",
    )
    next_goal: str = Field(default="", description="The immediate goal this action serves.")
    reasoning: str = Field(description="Brief why for this step.")
    kind: AgentActionKind
    index: int | None = Field(default=None, description="Element index from the observation (interaction actions).")

    @field_validator("index", mode="before")
    @classmethod
    def _coerce_index(cls, value: object) -> object:
        # The model sometimes echoes the observation's "[3]" bracket form as the index.
        if isinstance(value, str):
            digits = re.sub(r"[^0-9]", "", value)
            return int(digits) if digits else None
        return value
    text: str | None = Field(default=None, description="Text to type (fill).")
    value: str | None = Field(default=None, description="Option value/label (select).")
    url: str | None = Field(default=None, description="URL (goto).")
    keys: str | None = Field(default=None, description="Key or combo (press), e.g. 'Enter'.")
    down: bool | None = Field(default=None, description="Scroll direction: true=down, false=up (scroll).")
    seconds: float | None = Field(default=None, description="How long to dwell/watch, in seconds (wait).")
    pages: float | None = Field(default=None, description="Scroll amount in viewport pages, e.g. 1.0 (scroll).")
    success: bool = Field(
        default=False, description="For done: whether the task was achieved (false = giving up; explain why)."
    )
    # Parameter conveyance (docs/research/browser-agent-prompting.md §7.3): the model DECLARES
    # which ${name} a value came from, so the compiler binds structurally instead of
    # string-matching the sample value back out of the artifact.
    param: str | None = Field(
        default=None,
        description="If text/value/url (or a clicked element's name) is a PARAMETER's sample value, that "
        "parameter's name (without ${}). Null for a literal that is not a parameter.",
    )
