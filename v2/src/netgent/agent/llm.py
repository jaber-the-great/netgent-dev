"""The single LLM call site for the agent.

`LLM` is the seam: one `decide()` method returning a validated AgentDecision. `LangChainLLM`
implements it via langchain's structured output (the `netgent[generate]` extra); `FakeLLM`
replays scripted decisions for tests with no network. Keeping model access behind one method
means swapping frameworks later is a one-file change, not a sprawl.
"""

from typing import Protocol

from netgent.agent.decision import AgentDecision

# litellm-style "provider/model" → langchain model_provider id.
_PROVIDER_ALIAS = {
    "gemini": "google_genai",
    "google": "google_genai",
    "openai": "openai",
    "anthropic": "anthropic",
}


class LLM(Protocol):
    async def decide(self, system: str, task: str, observation: str, history: list[str]) -> AgentDecision: ...


class LangChainLLM:
    """Structured-output decisions from a chat model. Imports langchain lazily."""

    def __init__(self, model: str = "gemini/gemini-2.5-flash"):
        from langchain.chat_models import init_chat_model  # lazy: only when actually used

        provider, _, name = model.partition("/")
        if not name:  # bare model name, no provider prefix
            provider, name = "gemini", provider
        chat = init_chat_model(name, model_provider=_PROVIDER_ALIAS.get(provider, provider), temperature=0)
        self._model = chat.with_structured_output(AgentDecision)

    async def decide(self, system: str, task: str, observation: str, history: list[str]) -> AgentDecision:
        hist = "\n".join(history[-10:]) if history else "(none yet)"
        prompt = f"{system}\n\nTASK: {task}\n\nRECENT STEPS:\n{hist}\n\nOBSERVATION:\n{observation}\n\nNext action:"
        return await self._model.ainvoke(prompt)


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
