"""The agent's per-step decision — the LLM's structured output.

Actions reference an element by its `index` in the current observation (not a raw locator),
which the agent resolves to a durable locator chain from the element's candidate selectors.

`done` is NOT an action kind: it is a boolean exit with `success`, enforced by a model
validator so it can never carry an index or sit beside an action (browser-use guards the same
thing at runtime; docs/research/browser-agent-tool-calling.md §5.7). The field validators are
Skyvern's coercion ladder (`parse_actions.py`, ibid. §5.5): repair what a model plausibly
emits instead of spending a whole step on a parse failure.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

AgentActionKind = Literal[
    "click", "fill", "select", "upload",
    "hover", "press", "goto", "scroll", "go_back", "wait",
]
ALL_KINDS: frozenset[str] = frozenset(AgentActionKind.__args__)
# The convergent core every surveyed DOM agent has. hover/press/goto are opt-in per task:
# AgentOccam's largest single gain (+9.4 SR on WebArena) came from deleting them.
DEFAULT_KINDS: frozenset[str] = frozenset({"click", "fill", "select", "upload", "scroll", "go_back", "wait"})
OPT_IN_KINDS: frozenset[str] = ALL_KINDS - DEFAULT_KINDS

# Aliases a model emits for our kinds (Skyvern's action_type.upper() + legacy-alias map).
_KIND_ALIASES = {
    "type": "fill", "input": "fill", "input_text": "fill", "enter_text": "fill", "type_text": "fill",
    "select_option": "select", "dropdown": "select",
    "upload_file": "upload", "file": "upload",
    "press_key": "press", "keypress": "press", "key": "press",
    "navigate": "goto", "open": "goto", "go_to": "goto",
    "back": "go_back", "goback": "go_back",
    "check": "click", "uncheck": "click", "toggle": "click",  # Mind2Web/Skyvern: toggles ARE clicks
    "sleep": "wait",
}
# Key names Playwright rejects but models use (measured: 'Return' cost a step, then a run).
_KEY_ALIASES = {
    "return": "Enter", "enter": "Enter", "esc": "Escape", "escape": "Escape", "tab": "Tab",
    "space": "Space", "spacebar": "Space", "backspace": "Backspace", "delete": "Delete", "del": "Delete",
    "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
    "arrowup": "ArrowUp", "arrowdown": "ArrowDown", "arrowleft": "ArrowLeft", "arrowright": "ArrowRight",
    "arrow_up": "ArrowUp", "arrow_down": "ArrowDown", "arrow_left": "ArrowLeft", "arrow_right": "ArrowRight",
    "pageup": "PageUp", "pagedown": "PageDown", "home": "Home", "end": "End",
    "ctrl": "Control", "control": "Control", "cmd": "Meta", "command": "Meta", "meta": "Meta",
    "alt": "Alt", "option": "Alt", "shift": "Shift",
}


def normalize_keys(keys: str) -> str:
    """'Return' → 'Enter', 'ctrl+a' → 'Control+a', 'arrow down' → 'ArrowDown'; unknown names pass."""
    parts = [p for p in re.split(r"\s*\+\s*", keys.strip()) if p]
    out = []
    for p in parts:
        k = p.strip().lower().replace(" ", "")
        out.append(_KEY_ALIASES.get(k, p.strip()))
    return "+".join(out) if out else keys


class AgentDecision(BaseModel):
    """One step: exactly one atomic action, or `done`. `done` is the only exit: success=True
    when the task is complete, success=False when it cannot proceed (e.g. a CAPTCHA appeared)
    — say why in `reasoning`."""

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
    done: bool = Field(default=False, description="True to end the run instead of acting (then set success).")
    success: bool = Field(
        default=False, description="With done: whether the task was achieved (false = giving up; explain why)."
    )
    kind: AgentActionKind | None = Field(default=None, description="The action to take (omit when done).")
    index: int | None = Field(default=None, description="Element index from the observation (interaction actions).")
    text: str | None = Field(default=None, description="Text to type (fill).")
    value: str | None = Field(default=None, description="Option value/label (select).")
    url: str | None = Field(default=None, description="URL (goto).")
    keys: str | None = Field(default=None, description="Key or combo (press), e.g. 'Enter'.")
    down: bool | None = Field(default=None, description="Scroll direction: true=down, false=up (scroll).")
    seconds: float | None = Field(default=None, description="How long to dwell/watch, in seconds (wait).")
    pages: float | None = Field(default=None, description="Scroll amount in viewport pages, e.g. 1.0 (scroll).")
    # Parameter conveyance (docs/research/browser-agent-prompting.md §7.3): the model DECLARES
    # which ${name} a value came from, so the compiler binds structurally instead of
    # string-matching the sample value back out of the artifact.
    param: str | None = Field(
        default=None,
        description="If text/value/url (or a clicked element's name) is a PARAMETER's sample value, that "
        "parameter's name (without ${}). Null for a literal that is not a parameter.",
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_done_kind(cls, data: object) -> object:
        # Accept the pre-Stage-3 shape kind="done" (and a model that still emits it).
        if isinstance(data, dict):
            kind = str(data.get("kind") or "").strip().lower()
            if kind in ("done", "finish", "finished", "complete", "stop"):
                data = {**data, "kind": None, "done": True}
        return data

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        k = v.strip().lower().replace(" ", "_").replace("-", "_")
        return _KIND_ALIASES.get(k, k) or None

    @field_validator("index", mode="before")
    @classmethod
    def _coerce_index(cls, value: object) -> object:
        # The model sometimes echoes the observation's "[3]" bracket form as the index, or a
        # float ("3.0" from Gemini).
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            digits = re.sub(r"[^0-9]", "", value)
            return int(digits) if digits else None
        return value

    @field_validator("keys", mode="before")
    @classmethod
    def _normalize_keys(cls, v: object) -> object:
        return normalize_keys(v) if isinstance(v, str) and v.strip() else v

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "AgentDecision":
        if self.done:
            self.kind = None  # done is returned alone — never with an action
        elif self.kind is None:
            raise ValueError("return an action `kind`, or done=true")
        # "LLM sometimes hallucinates and returns element id for non-web actions" (Skyvern);
        # scroll keeps its index (it anchors the frame), press keeps it (the field to type into).
        if self.kind in ("goto", "go_back", "wait"):
            self.index = None
        return self
