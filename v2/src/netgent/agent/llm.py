"""The single LLM call site for the agent.

`LLM` is the seam: one `decide()` method returning a validated AgentDecision. `LangChainLLM`
implements it via langchain's structured output (the `netgent[generate]` extra); `FakeLLM`
replays scripted decisions for tests with no network. Keeping model access behind one method
means swapping frameworks later is a one-file change, not a sprawl.

Message layout (docs/research/browser-agent-prompting.md §6.2 #8): the static part — system
prompt + task — goes in a SystemMessage; the step-varying part — history + observation — goes
last in a HumanMessage. browser-use (`prompts.py:433-434`) and Skyvern
(`stable_prefix_ordering`) lay their prompts out the same way. No explicit cache breakpoints:
providers that cache stable prefixes implicitly may still do so, and `usage["cache_read_tokens"]`
reports whatever happened.

Models are named the way `init_chat_model` names them — `provider:model` (`anthropic:claude-…`,
`google_genai:gemini-…`, `openai:gpt-…`); a `/` separator is accepted and rewritten to `:`.

History rendering (browser-agent-memory.md §6.2a): fold/note records are always shown (they
are a sweep's cross-task memory, bounded by MAX_FOLDS), then the last HISTORY_WINDOW acted
records — the last FULL_BLOCKS of them with the model's own eval/memory/goal, older ones as
one line each.
"""

import os
from typing import TYPE_CHECKING, Protocol

from netgent.agent.explorer.decision import ALL_KINDS, MAX_BATCH, AgentAction, AgentDecision
from netgent.agent.explorer.models import StepRecord

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

DEFAULT_MODEL = "google_genai:gemini-2.5-flash"

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
        max_actions: int = 1,
    ) -> AgentDecision: ...

    async def judge(self, system: str, content: list[dict], schema: type) -> object: ...


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
    """NETGENT_MEMORY_FIELDS=1 adds evaluation/memory/next_goal to the schema the model fills.
    OFF by default, by measurement: on the 21-form sweep the fields (with the observation diff)
    cost +45% LLM calls and +130% input tokens for a lower score, and on the challenge they
    changed nothing (docs/research/explorer-optimisation.md §2). browser-use's flash mode
    drops them the same way."""
    return os.getenv("NETGENT_MEMORY_FIELDS", "0") == "1"


def decision_schema(
    memory_fields: bool = True, allowed_kinds: frozenset[str] | None = None, max_actions: int = MAX_BATCH
) -> type:
    """The structured-output schema the model fills: AgentDecision, or a variant without the
    working-memory fields, with `kind` narrowed to the task's allowed set, and/or without the
    `then` batch (max_actions == 1 — today's one-action semantics). Built with pydantic from
    AgentDecision's own fields so the variants never drift; `decide()` converts the result
    back to an AgentDecision (which re-runs the coercion validators)."""
    kinds = frozenset(allowed_kinds) if allowed_kinds is not None else ALL_KINDS
    if memory_fields and kinds == ALL_KINDS and max_actions >= MAX_BATCH:
        return AgentDecision
    from typing import Literal

    from pydantic import Field, create_model

    kind_ann = Literal[tuple(sorted(kinds))] | None if kinds != ALL_KINDS else None  # type: ignore[valid-type]
    action_fields = {}
    for name, f in AgentAction.model_fields.items():
        action_fields[name] = (kind_ann if name == "kind" and kind_ann is not None else f.annotation, f)
    item_model = create_model("AgentActionVariant", __base__=AgentAction, **action_fields)
    fields = {}
    for name, f in AgentDecision.model_fields.items():
        if not memory_fields and name in MEMORY_FIELDS:
            continue
        if name == "then":
            if max_actions <= 1:
                continue
            fields[name] = (list[item_model], Field(default_factory=list, max_length=max_actions - 1,
                                                    description=f.description))
            continue
        ann = f.annotation
        if name == "kind" and kind_ann is not None:
            ann = kind_ann
        fields[name] = (ann, f)
    return create_model("AgentDecisionVariant", __doc__=AgentDecision.__doc__, **fields)


def model_ref(model: str) -> str:
    """`provider/model` (NetGent's older spelling) → `provider:model`, what `init_chat_model` parses."""
    return model.replace("/", ":", 1)


class LangChainLLM:
    """Structured-output decisions from a chat model. Imports langchain lazily.

    `model` is a `provider:model` string handed to `init_chat_model`, or an already-built
    `BaseChatModel` (tests inject `GenericFakeChatModel` here)."""

    def __init__(self, model: "str | BaseChatModel" = DEFAULT_MODEL):
        if isinstance(model, str):
            from langchain.chat_models import init_chat_model  # lazy: only when actually used

            ref = model_ref(model)
            # Claude 4.7+ / Claude 5 models reject `temperature` outright (400: "deprecated
            # for this model") — omit it for anthropic; keep 0 elsewhere for determinism.
            anthropic = ref.startswith("anthropic:") or ref.rsplit(":", 1)[-1].startswith("claude")
            self._chat = init_chat_model(ref, **({} if anthropic else {"temperature": 0}))
        else:
            self._chat = model
        self._structured: dict[tuple, object] = {}  # per (allowed kinds, max_actions)
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
        return [SystemMessage(content=static), HumanMessage(content=dynamic)]

    def _structured_model(self, allowed_kinds: frozenset[str] | None, max_actions: int):
        key = (frozenset(allowed_kinds) if allowed_kinds is not None else ALL_KINDS, max_actions)
        if key not in self._structured:
            schema = decision_schema(memory_fields_enabled(), key[0], max_actions)
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
        max_actions: int = 1,
    ) -> AgentDecision:
        """One decision. Notte's ladder (browser-agent-tool-calling.md §5.5): a response that
        fails validation is retried in place with the validator's errors appended, up to
        PARSE_RETRIES times, before the failure costs the agent a step."""
        from langchain_core.messages import HumanMessage

        model = self._structured_model(allowed_kinds, max_actions)
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

    async def judge(self, system: str, content: list[dict], schema: type):
        """One structured call for the verifier: a system prompt and a multimodal human
        message (text + screenshots). Same retry ladder as decide()."""
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self._chat.with_structured_output(schema, include_raw=True)
        messages = [SystemMessage(content=system), HumanMessage(content=content)]
        last_error = "no response"
        text_len = sum(len(c.get("text", "")) for c in content if c.get("type") == "text")
        for _attempt in range(PARSE_RETRIES + 1):
            result = await model.ainvoke(messages)
            self._record(result, " " * text_len, [])
            parsed = result.get("parsed")
            if parsed is not None:
                return parsed
            last_error = str(result.get("parsing_error"))
            messages = [
                *messages,
                HumanMessage(content=f"Your response was invalid: {last_error[:600]}\nReturn a valid verdict."),
            ]
        raise ValueError(f"judge structured output failed after {PARSE_RETRIES + 1} attempts: {last_error}")


class FakeLLM:
    """Returns scripted decisions in order (tests). Raises if the script runs out.
    `verdicts` scripts the judge the same way (default: every judgment is "achieved")."""

    def __init__(self, script: list[AgentDecision], verdicts: list | None = None):
        self._script = list(script)
        self._i = 0
        self._verdicts = list(verdicts or [])
        self.judged: list[list[dict]] = []  # the content each judge() call received (tests inspect it)

    async def judge(self, system, content, schema):
        self.judged.append(content)
        if self._verdicts:
            return self._verdicts.pop(0)
        return schema(achieved=True, confidence="high")

    async def decide(self, system, task, observation, history, allowed_kinds=None, max_actions=1) -> AgentDecision:
        if self._i >= len(self._script):
            raise AssertionError("FakeLLM script exhausted")
        decision = self._script[self._i]
        self._i += 1
        return decision


def make_llm(model: "str | BaseChatModel") -> LLM:
    return LangChainLLM(model)
