"""Shared fake `query()` plumbing: no CLI, no network.

`fake_query` monkeypatches `langchain_claude_code.chat_models.query` with an
async generator that records the (prompt, options) it was called with and
replays scripted SDK messages.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
)

from langchain_claude_code import chat_models

DEFAULT_USAGE = {
    "input_tokens": 10,
    "output_tokens": 5,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 200,
}


def make_result(**overrides: Any) -> ResultMessage:
    base: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1200,
        "duration_api_ms": 1000,
        "is_error": False,
        "num_turns": 1,
        "session_id": "sess-1",
        "stop_reason": "end_turn",
        "usage": dict(DEFAULT_USAGE),
        "result": "hello from claude",
    }
    base.update(overrides)
    return ResultMessage(**base)


def make_assistant(text: str = "hello from claude", **overrides: Any) -> AssistantMessage:
    base: dict[str, Any] = {
        "content": [TextBlock(text=text)],
        "model": "claude-haiku-4-5-20251001",
    }
    base.update(overrides)
    return AssistantMessage(**base)


@dataclass
class FakeQuery:
    """Records every call and replays a scripted message list."""

    script: list[Any] = field(default_factory=lambda: [make_assistant(), make_result()])
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def last_options(self) -> ClaudeAgentOptions:
        return self.calls[-1]["options"]

    @property
    def last_prompt(self) -> Any:
        return self.calls[-1]["prompt"]

    async def __call__(self, *, prompt: Any, options: ClaudeAgentOptions) -> Any:
        if isinstance(prompt, str):
            materialized: Any = prompt
        else:  # async iterable of stream-input dicts — materialize for inspection
            materialized = [message async for message in prompt]
        self.calls.append({"prompt": materialized, "options": options})
        for message in self.script:
            yield message


@pytest.fixture
def fake_query(monkeypatch: pytest.MonkeyPatch) -> FakeQuery:
    fake = FakeQuery()
    monkeypatch.setattr(chat_models, "query", fake)
    return fake
