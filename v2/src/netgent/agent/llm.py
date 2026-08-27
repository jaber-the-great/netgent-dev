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

History rendering (browser-agent-memory.md §6.2a): fold/note records are always shown (they
are a sweep's cross-task memory, bounded by MAX_FOLDS), then the last HISTORY_WINDOW acted
records — the last FULL_BLOCKS of them with the model's own eval/memory/goal, older ones as
one line each.
"""

import os
from typing import Protocol

from netgent.agent.explorer.browser_agent import StepRecord
from netgent.agent.explorer.decision import ALL_KINDS, AgentDecision

# litellm-style "provider/model" → langchain model_provider id.
_PROVIDER_ALIAS = {
    "gemini": "google_genai",
    "google": "google_genai",
    "openai": "openai",
    "anthropic": "anthropic",
}

HISTORY_WINDOW = 10  # acted records shown per step
FULL_BLOCKS = 3  # of which the most recent are rendered with eval/memory/goal
MEMORY_FIELDS = ("evaluation", "memory", "next_goal")
PARSE_RETRIES = 2  # in-place retries with the validation error fed back, before the step is lost


class LLM(Protocol):
    async def decide(
        self,
        system: str,
        task: str,
        observation: str,
        history: list[StepRecord],
        allowed_kinds: frozenset[str] | None = None,
    ) -> AgentDecision: ...


def render_history(history: list[StepRecord]) -> str:
    if not history:
        return "(none yet)"
    context = [r for r in history if r.kind in ("note", "fold")]
    acted = [r for r in history if r.kind not in ("note", "fold")][-HISTORY_WINDOW:]
    lines = [r.to_line() for r in context]
    older, recent = acted[:-FULL_BLOCKS], acted[-FULL_BLOCKS:]
    lines += [r.to_line() for r in older]
    lines += [r.to_block() for r in recent]
    return "\n".join(lines)


def render_prompt(system: str, task: str, observation: str, history: list[StepRecord]) -> tuple[str, str]:
    """(static prefix, step-varying suffix) — the two message bodies `decide()` sends.

    Pure, so tests can pin the layout without a model: the prefix is byte-identical across
    the steps of one run (a cache-prefix requirement), the suffix carries what changes.
    """
    static = f"{system}\n\nTASK: {task}"
    dynamic = f"RECENT STEPS:\n{render_history(history)}\n\nOBSERVATION:\n{observation}\n\nNext action:"
    return static, dynamic


def memory_fields_enabled() -> bool:
    """NETGENT_MEMORY_FIELDS=0 removes evaluation/memory/next_goal from the schema the model
    fills (the A/B arm — browser-use's flash mode does the same)."""
    return os.getenv("NETGENT_MEMORY_FIELDS", "1") != "0"


def decision_schema(memory_fields: bool = True, allowed_kinds: frozenset[str] | None = None) -> type:
    """The structured-output schema the model fills: AgentDecision, or a variant without the
    working-memory fields and/or with `kind` narrowed to the task's allowed set. Built with
    pydantic from AgentDecision's own fields so the variants never drift; `decide()` converts
    the result back to an AgentDecision (which re-runs the coercion validators)."""
    kinds = frozenset(allowed_kinds) if allowed_kinds is not None else ALL_KINDS
    if memory_fields and kinds == ALL_KINDS:
        return AgentDecision
    from typing import Literal

    from pydantic import create_model

    fields = {}
    for name, f in AgentDecision.model_fields.items():
        if not memory_fields and name in MEMORY_FIELDS:
            continue
        ann = f.annotation
        if name == "kind" and kinds != ALL_KINDS:
            ann = Literal[tuple(sorted(kinds))] | None  # type: ignore[valid-type]
        fields[name] = (ann, f)
    return create_model("AgentDecisionVariant", __doc__=AgentDecision.__doc__, **fields)


class LangChainLLM:
    """Structured-output decisions from a chat model. Imports langchain lazily."""

    def __init__(self, model: str = "gemini/gemini-2.5-flash"):
        from langchain.chat_models import init_chat_model  # lazy: only when actually used

        provider, _, name = model.partition("/")
        if not name:  # bare model name, no provider prefix
            provider, name = "gemini", provider
        self._provider = _PROVIDER_ALIAS.get(provider, provider)
        self._chat = init_chat_model(name, model_provider=self._provider, temperature=0)
        self._structured: dict[frozenset[str], object] = {}  # per allowed-kinds set
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

    def _messages(self, system: str, task: str, observation: str, history: list[StepRecord]) -> list:
        from langchain_core.messages import HumanMessage, SystemMessage

        static, dynamic = render_prompt(system, task, observation, history)
        if self._provider == "anthropic":
            # Explicit cache breakpoint after the static prefix (tools → system → messages is
            # the provider's prefix order, so the tool schema is cached with it).
            content: str | list = [{"type": "text", "text": static, "cache_control": {"type": "ephemeral"}}]
        else:
            content = static  # OpenAI/Gemini cache stable prefixes implicitly
        return [SystemMessage(content=content), HumanMessage(content=dynamic)]

    def _structured_model(self, allowed_kinds: frozenset[str] | None):
        key = frozenset(allowed_kinds) if allowed_kinds is not None else ALL_KINDS
        if key not in self._structured:
            schema = decision_schema(memory_fields_enabled(), key)
            self._structured[key] = self._chat.with_structured_output(schema, include_raw=True)
        return self._structured[key]

    def _record(self, result: dict, observation: str, history: list[StepRecord]) -> None:
        meta = getattr(result.get("raw"), "usage_metadata", None) or {}
        details = meta.get("input_token_details") or {}
        call = {
            "input_tokens": int(meta.get("input_tokens", 0) or 0),
            "output_tokens": int(meta.get("output_tokens", 0) or 0),
            "cache_read_tokens": int(details.get("cache_read", 0) or 0),
            "cache_creation_tokens": int(details.get("cache_creation", 0) or 0),
            "observation_chars": len(observation),
            "history_chars": len(render_history(history)),
        }
        self.calls.append(call)
        self.usage["calls"] += 1
        for k, v in call.items():
            self.usage[k] += v

    async def decide(
        self,
        system: str,
        task: str,
        observation: str,
        history: list[StepRecord],
        allowed_kinds: frozenset[str] | None = None,
    ) -> AgentDecision:
        """One decision. Notte's ladder (browser-agent-tool-calling.md §5.5): a response that
        fails validation is retried in place with the validator's errors appended, up to
        PARSE_RETRIES times, before the failure costs the agent a step."""
        from langchain_core.messages import HumanMessage

        model = self._structured_model(allowed_kinds)
        messages = self._messages(system, task, observation, history)
        last_error = "no response"
        for _attempt in range(PARSE_RETRIES + 1):
            result = await model.ainvoke(messages)
            self._record(result, observation, history)
            parsed = result.get("parsed")
            if parsed is not None:
                try:
                    if isinstance(parsed, AgentDecision):
                        return parsed
                    return AgentDecision.model_validate(parsed.model_dump())
                except Exception as exc:  # noqa: BLE001 — a validator refused the variant's content
                    last_error = str(exc)
            else:
                last_error = str(result.get("parsing_error"))
            self.usage["parse_retries"] = self.usage.get("parse_retries", 0) + 1
            messages = [
                *messages,
                HumanMessage(content=f"Your response was invalid: {last_error[:600]}\nReturn a valid decision."),
            ]
        raise ValueError(f"structured output failed after {PARSE_RETRIES + 1} attempts: {last_error}")


class FakeLLM:
    """Returns scripted decisions in order (tests). Raises if the script runs out."""

    def __init__(self, script: list[AgentDecision]):
        self._script = list(script)
        self._i = 0

    async def decide(self, system, task, observation, history, allowed_kinds=None) -> AgentDecision:
        if self._i >= len(self._script):
            raise AssertionError("FakeLLM script exhausted")
        decision = self._script[self._i]
        self._i += 1
        return decision


def make_llm(model: str) -> LLM:
    return LangChainLLM(model)
