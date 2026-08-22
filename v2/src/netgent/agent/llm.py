"""The single LLM call site for the agent.

`LLM` is the seam: one `decide()` method returning a validated AgentDecision. `LangChainLLM`
implements it via langchain's structured output (the `netgent[generate]` extra); `FakeLLM`
replays scripted decisions for tests with no network. Keeping model access behind one method
means swapping frameworks later is a one-file change, not a sprawl.
"""

from typing import Protocol

from netgent.agent.explore_agent.decision import AgentDecision

# litellm-style "provider/model" → langchain model_provider id.
_PROVIDER_ALIAS = {
    "gemini": "google_genai",
    "google": "google_genai",
    "openai": "openai",
    "anthropic": "anthropic",
}


class LLM(Protocol):
    async def decide(
        self, system: str, task: str, observation: str, history: list[str], image: bytes | None = None
    ) -> AgentDecision: ...


class LangChainLLM:
    """Structured-output decisions from a chat model. Imports langchain lazily."""

    def __init__(self, model: str = "gemini/gemini-2.5-flash"):
        from langchain.chat_models import init_chat_model  # lazy: only when actually used

        provider, _, name = model.partition("/")
        if not name:  # bare model name, no provider prefix
            provider, name = "gemini", provider
        chat = init_chat_model(name, model_provider=_PROVIDER_ALIAS.get(provider, provider), temperature=0)
        self._model = chat.with_structured_output(AgentDecision, include_raw=True)
        # Running totals across decide() calls — what an exploration cost (evals compare
        # observation backends by these).
        self.usage: dict[str, int] = {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "observation_chars": 0, "images": 0,
        }

    async def decide(
        self, system: str, task: str, observation: str, history: list[str], image: bytes | None = None
    ) -> AgentDecision:
        hist = "\n".join(history[-10:]) if history else "(none yet)"
        prompt = f"{system}\n\nTASK: {task}\n\nRECENT STEPS:\n{hist}\n\nOBSERVATION:\n{observation}\n\nNext action:"
        if image is not None:
            # Multimodal: the same text PLUS a Set-of-Marks screenshot whose numbers are the
            # observation indices. One HumanMessage with a text block and an image block
            # (LangChain's provider-agnostic content-blocks form; Anthropic/OpenAI both accept it).
            import base64

            from langchain_core.messages import HumanMessage

            b64 = base64.b64encode(image).decode()
            message = HumanMessage(content=[
                {"type": "text", "text": prompt + "\n\nThe screenshot shows the SAME numbered elements "
                 "(the box label = the [index] in the list). Use it to disambiguate and to read text "
                 "that only appears as pixels (e.g. a canvas)."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ])
            result = await self._model.ainvoke([message])
            self.usage["images"] += 1
        else:
            result = await self._model.ainvoke(prompt)
        self.usage["calls"] += 1
        self.usage["observation_chars"] += len(observation)
        meta = getattr(result.get("raw"), "usage_metadata", None) or {}
        self.usage["input_tokens"] += int(meta.get("input_tokens", 0) or 0)
        self.usage["output_tokens"] += int(meta.get("output_tokens", 0) or 0)
        parsed = result.get("parsed")
        if parsed is None:
            raise ValueError(f"structured output failed: {result.get('parsing_error')}")
        return parsed


class FakeLLM:
    """Returns scripted decisions in order (tests). Raises if the script runs out."""

    def __init__(self, script: list[AgentDecision]):
        self._script = list(script)
        self._i = 0

    async def decide(
        self, system: str, task: str, observation: str, history: list[str], image: bytes | None = None
    ) -> AgentDecision:
        del image  # FakeLLM ignores the screenshot; scripts are deterministic
        if self._i >= len(self._script):
            raise AssertionError("FakeLLM script exhausted")
        decision = self._script[self._i]
        self._i += 1
        return decision


def make_llm(model: str) -> LLM:
    return LangChainLLM(model)
