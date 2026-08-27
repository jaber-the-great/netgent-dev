"""The single LLM call site for the agent.

`LLM` is the seam: one `decide()` method returning a validated AgentDecision. `LangChainLLM`
implements it via langchain's structured output (the `netgent[generate]` extra); `FakeLLM`
replays scripted decisions for tests with no network. Keeping model access behind one method
means swapping frameworks later is a one-file change, not a sprawl.

Message layout (docs/research/browser-agent-prompting.md §6.2 #8): the static part — system
prompt + task — goes in a SystemMessage marked as a cache prefix; the step-varying part —
history + observation — goes last in a HumanMessage. browser-use (`prompts.py:433-434`) and
Skyvern (`stable_prefix_ordering`) lay their prompts out the same way. Whether the prefix is
actually cached is provider- and length-dependent (Anthropic: ≥4096 tokens on Haiku 4.5, 1024
on Sonnet 4.x); `usage["cache_read_tokens"]` reports what happened.
"""

from typing import Protocol

from netgent.agent.explorer.decision import AgentDecision

# litellm-style "provider/model" → langchain model_provider id.
_PROVIDER_ALIAS = {
    "gemini": "google_genai",
    "google": "google_genai",
    "openai": "openai",
    "anthropic": "anthropic",
}

HISTORY_WINDOW = 10  # history lines shown per step


class LLM(Protocol):
    async def decide(self, system: str, task: str, observation: str, history: list[str]) -> AgentDecision: ...


def render_prompt(system: str, task: str, observation: str, history: list[str]) -> tuple[str, str]:
    """(static prefix, step-varying suffix) — the two message bodies `decide()` sends.

    Pure, so tests can pin the layout without a model: the prefix is byte-identical across
    the steps of one run (a cache-prefix requirement), the suffix carries what changes.
    """
    hist = "\n".join(history[-HISTORY_WINDOW:]) if history else "(none yet)"
    static = f"{system}\n\nTASK: {task}"
    dynamic = f"RECENT STEPS:\n{hist}\n\nOBSERVATION:\n{observation}\n\nNext action:"
    return static, dynamic


class LangChainLLM:
    """Structured-output decisions from a chat model. Imports langchain lazily."""

    def __init__(self, model: str = "gemini/gemini-2.5-flash"):
        from langchain.chat_models import init_chat_model  # lazy: only when actually used

        provider, _, name = model.partition("/")
        if not name:  # bare model name, no provider prefix
            provider, name = "gemini", provider
        self._provider = _PROVIDER_ALIAS.get(provider, provider)
        chat = init_chat_model(name, model_provider=self._provider, temperature=0)
        self._model = chat.with_structured_output(AgentDecision, include_raw=True)
        # Running totals across decide() calls — what an exploration cost (the evals under
        # `netgent eval stress` report these per run). `input_tokens` is the provider's total
        # (cache reads and writes included), so it stays comparable across layouts.
        self.usage: dict[str, int] = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "observation_chars": 0,
            "history_chars": 0,
        }
        # Per-call usage, in order — the per-step numbers the optimisation doc tables.
        self.calls: list[dict[str, int]] = []

    def _messages(self, system: str, task: str, observation: str, history: list[str]) -> list:
        from langchain_core.messages import HumanMessage, SystemMessage

        static, dynamic = render_prompt(system, task, observation, history)
        if self._provider == "anthropic":
            # Explicit cache breakpoint after the static prefix (tools → system → messages is
            # the provider's prefix order, so the tool schema is cached with it).
            content: str | list = [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}}]
        else:
            content = static  # OpenAI/Gemini cache stable prefixes implicitly
        return [SystemMessage(content=content), HumanMessage(content=dynamic)]

    async def decide(self, system: str, task: str, observation: str, history: list[str]) -> AgentDecision:
        result = await self._model.ainvoke(self._messages(system, task, observation, history))
        meta = getattr(result.get("raw"), "usage_metadata", None) or {}
        details = meta.get("input_token_details") or {}
        call = {
            "input_tokens": int(meta.get("input_tokens", 0) or 0),
            "output_tokens": int(meta.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(details.get("cache_read", 0) or 0),
            "cache_creation_tokens": int(details.get("cache_creation", 0) or 0),
            "observation_chars": len(observation),
            "history_chars": sum(len(h) + 1 for h in history[-HISTORY_WINDOW:]),
        }
        self.calls.append(call)
        self.usage["calls"] += 1
        for k, v in call.items():
            self.usage[k] += v
        parsed = result.get("parsed")
        if parsed is None:
            raise ValueError(f"structured output failed: {result.get('parsing_error')}")
        return parsed


class FakeLLM:
    """Returns scripted decisions in order (tests). Raises if the script runs out."""

    def __init__(self, script: list[AgentDecision]):
        self._script = list(script)
        self._i = 0

    async def decide(self, system: str, task: str, observation: str, history: list[str]) -> AgentDecision:
        if self._i >= len(self._script):
            raise AssertionError("FakeLLM script exhausted")
        decision = self._script[self._i]
        self._i += 1
        return decision


def make_llm(model: str) -> LLM:
    return LangChainLLM(model)
