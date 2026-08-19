"""The agent's per-step decision — the LLM's structured output.

Actions reference an element by its `index` in the current observation (not a raw locator),
which the agent resolves to a durable locator chain from the element's candidate selectors.
"""

from typing import Literal

from pydantic import BaseModel, Field

AgentActionKind = Literal[
    "click", "fill", "select", "check", "uncheck", "upload",
    "hover", "press", "goto", "scroll", "go_back", "done", "stop",
]


class AgentDecision(BaseModel):
    """One step. `done`=task complete; `stop`=cannot proceed (e.g. a CAPTCHA appeared)."""

    reasoning: str = Field(description="Brief why for this step.")
    kind: AgentActionKind
    index: int | None = Field(default=None, description="Element index from the observation (interaction actions).")
    text: str | None = Field(default=None, description="Text to type (fill).")
    value: str | None = Field(default=None, description="Option value/label (select).")
    url: str | None = Field(default=None, description="URL (goto).")
    keys: str | None = Field(default=None, description="Key or combo (press), e.g. 'Enter'.")
    down: bool | None = Field(default=None, description="Scroll direction: true=down, false=up (scroll).")
    pages: float | None = Field(default=None, description="Scroll amount in viewport pages, e.g. 1.0 (scroll).")
    success: bool = Field(default=False, description="For done/stop: whether the task was achieved.")
