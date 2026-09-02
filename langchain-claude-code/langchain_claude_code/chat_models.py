"""ChatClaudeCode: the Claude Code CLI as a LangChain chat model.

The CLI is driven through the official Claude Agent SDK
(``claude-agent-sdk``), but locked down so it behaves like a *model*, not an
agent: no built-in tools, no filesystem settings, no MCP servers, no session
persistence, one turn. Every capability is an explicit opt-in on the
constructor. This is the difference from community Claude-Code adapters,
which run the CLI with its default agent toolset (and untrusted prompt text
can then drive file reads or shell commands).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from operator import itemgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from claude_agent_sdk import query
from claude_agent_sdk.types import (
    AssistantMessage as SDKAssistantMessage,
)
from claude_agent_sdk.types import (
    ClaudeAgentOptions,
    EffortLevel,
    PermissionMode,
    ResultMessage,
    SettingSource,
    StreamEvent,
)
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import LangSmithParams
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableMap, RunnablePassthrough
from pydantic import BaseModel, ConfigDict, Field

from langchain_claude_code._client_utils import AuthMode, build_options
from langchain_claude_code._compat import (
    convert_messages,
    format_result_error,
    prompt_to_stream_message,
    result_to_ai_message,
)
from langchain_claude_code.output_parsers import (
    make_structured_output_parser,
    schema_to_json_schema,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from langchain_core.language_models import LanguageModelInput
    from langchain_core.tools import BaseTool


class ClaudeCodeError(RuntimeError):
    """A ``claude`` CLI run finished with an error result."""


def _run_coroutine_sync(coro: Any) -> Any:
    """Run a coroutine from sync code, tolerating an already-running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Called from inside a running event loop (e.g. a notebook): run the
    # coroutine on a private loop in a worker thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


class ChatClaudeCode(BaseChatModel):
    """Claude via the local Claude Code CLI (Claude Agent SDK), tools off.

    Safe by default — the subprocess is reduced to a plain chat model:

    - ``tools=[]``: every built-in CLI tool (Bash, Read, Edit, …) removed.
    - ``setting_sources=[]``: no user/project/local settings, no CLAUDE.md.
    - ``permission_mode="dontAsk"``: anything not pre-approved is denied
      (the strictest non-interactive mode).
    - ``mcp_servers={}`` with ``strict_mcp_config=True``: no MCP servers —
      including the account's claude.ai-connected servers, which the CLI
      otherwise injects.
    - ``max_turns=1``: no agentic loops.
    - ``--no-session-persistence`` and ``--disable-slash-commands``: no
      transcript on disk, no skills.

    Every one of these is an explicit opt-in knob; loosening them turns the
    subprocess back into an agent that executes what the model asks, so never
    do that with untrusted text in the prompt.

    Auth: with the default ``auth="subscription"`` the subprocess env has
    ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` blanked, so the CLI uses
    the claude.ai login. Note Anthropic's consumer terms restrict how
    subscription access may be driven from other harnesses — review the
    current policy before relying on it. ``auth="api_key"`` passes the
    inherited environment through and bills the API.

    Example:
        .. code-block:: python

            from langchain_claude_code import ChatClaudeCode

            llm = ChatClaudeCode(model="claude-haiku-4-5-20251001")
            llm.invoke("Say hello")
    """

    model_config = ConfigDict(populate_by_name=True)

    model: str
    """Model for the CLI: a full id (``claude-haiku-4-5-20251001``) or a CLI
    alias (``haiku``, ``sonnet``, ``opus``)."""

    auth: AuthMode = "subscription"
    """``"subscription"`` blanks API-key env vars in the subprocess so the
    claude.ai login is used; ``"api_key"`` passes the environment through."""

    tools: list[str] | dict[str, Any] | None = Field(default_factory=list)
    """Built-in CLI tools available to the model. Default ``[]`` = none.

    DANGER: any entry here (or the ``{"type": "preset", "preset":
    "claude_code"}`` full set) lets model output execute on your machine.
    ``None`` is coerced to ``[]`` — this package never silently enables the
    CLI's default toolset."""

    allowed_tools: list[str] = Field(default_factory=list)
    """Tool names/rules auto-approved without prompting (only meaningful once
    ``tools`` is non-empty)."""

    disallowed_tools: list[str] = Field(default_factory=list)
    """Tool names removed from the model's context even if enabled."""

    permission_mode: PermissionMode = "dontAsk"
    """CLI permission mode. ``"dontAsk"`` (default) denies anything not
    pre-approved and never blocks on an interactive prompt. Loosening this
    (e.g. ``"bypassPermissions"``) is dangerous with tools enabled."""

    setting_sources: list[SettingSource] = Field(default_factory=list)
    """Which filesystem settings the CLI loads. Default ``[]`` = none (no
    ~/.claude settings, no project .claude/, no CLAUDE.md)."""

    mcp_servers: dict[str, Any] = Field(default_factory=dict)
    """MCP servers to expose. Default none; combined with
    ``strict_mcp_config=True`` this also blocks servers configured on the
    claude.ai account or in settings files."""

    strict_mcp_config: bool = True
    """Only use MCP servers from ``mcp_servers``, ignoring every other source
    (project .mcp.json, user settings, claude.ai-connected servers)."""

    max_turns: int | None = 1
    """Maximum conversation turns per call. 1 (default) forbids agentic
    loops. (Native structured output still works: the CLI's schema emission
    is not blocked by this limit.)"""

    cwd: str | Path | None = None
    """Working directory for the subprocess. Defaults to the process cwd —
    with tools enabled, prefer an empty scratch directory."""

    cli_path: str | Path | None = None
    """Path to the ``claude`` executable. Default: the SDK's discovery
    (bundled CLI, then PATH)."""

    env: dict[str, str] = Field(default_factory=dict)
    """Extra environment variables for the subprocess. Applied after the
    ``auth`` handling, so an explicit credential entry here wins."""

    persist_session: bool = False
    """Keep the CLI session transcript on disk (drops
    ``--no-session-persistence``)."""

    enable_slash_commands: bool = False
    """Allow skills/slash commands (drops ``--disable-slash-commands``)."""

    max_budget_usd: float | None = None
    """Stop a call once its API cost exceeds this budget (API-key auth)."""

    fallback_model: str | None = None
    """Model the CLI falls back to when the primary is unavailable."""

    effort: EffortLevel | None = None
    """Reasoning effort (``"low"`` … ``"max"``); CLI default when ``None``."""

    thinking: dict[str, Any] | None = None
    """Thinking configuration (a :class:`claude_agent_sdk.types.ThinkingConfig`
    dict, e.g. ``{"type": "disabled"}``). CLI default (adaptive on supported
    models) when ``None``."""

    timeout: float | None = 600.0
    """Seconds before a non-streaming call is aborted. ``None`` disables."""

    max_buffer_size: int | None = None
    """Max bytes buffered from the CLI stdout (SDK default when ``None``)."""

    stop: list[str] | None = None
    """Stop sequences. The CLI exposes no stop-sequence parameter, so any
    non-empty value raises at call time (accepted here only for LangChain's
    standard-parameter surface)."""

    temperature: float | None = None
    """Accepted for LangChain API compatibility only — the Claude Code CLI
    exposes no temperature parameter, so this value is IGNORED."""

    max_tokens: int | None = None
    """Accepted for LangChain API compatibility only — the Claude Code CLI
    exposes no max-output-tokens parameter, so this value is IGNORED."""

    max_retries: int | None = None
    """Accepted for LangChain API compatibility only — retries are handled by
    the CLI itself, so this value is IGNORED."""

    @property
    def _llm_type(self) -> str:
        return "claude-code"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "auth": self.auth,
            "tools": self.tools,
            "permission_mode": self.permission_mode,
            "max_turns": self.max_turns,
        }

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> LangSmithParams:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "claude-code"
        params["ls_model_name"] = kwargs.get("model", self.model)
        return params

    def _build_options(self, system_prompt: str | None, **kwargs: Any) -> ClaudeAgentOptions:
        """One ``ClaudeAgentOptions`` per call, from fields + per-call kwargs."""
        return build_options(
            model=kwargs.get("model", self.model),
            auth=self.auth,
            system_prompt=system_prompt,
            tools=self.tools if self.tools is not None else [],
            allowed_tools=self.allowed_tools,
            disallowed_tools=self.disallowed_tools,
            permission_mode=self.permission_mode,
            setting_sources=self.setting_sources,
            mcp_servers=self.mcp_servers,
            strict_mcp_config=self.strict_mcp_config,
            max_turns=kwargs.get("max_turns", self.max_turns),
            cwd=self.cwd,
            cli_path=self.cli_path,
            env=self.env,
            persist_session=self.persist_session,
            enable_slash_commands=self.enable_slash_commands,
            max_budget_usd=self.max_budget_usd,
            fallback_model=self.fallback_model,
            effort=self.effort,
            thinking=self.thinking,
            output_format=kwargs.get("output_format"),
            include_partial_messages=kwargs.get("include_partial_messages", False),
            max_buffer_size=self.max_buffer_size,
        )

    @staticmethod
    def _check_stop(stop: list[str] | None) -> None:
        if stop:
            raise ValueError(
                "ChatClaudeCode does not support stop sequences: the Claude "
                "Code CLI exposes no stop-sequence parameter."
            )

    async def _consume_query(
        self, messages: Sequence[BaseMessage], **kwargs: Any
    ) -> tuple[list[SDKAssistantMessage], ResultMessage]:
        """Run one ``query()`` and collect assistant messages + the result."""
        system_prompt, prompt = convert_messages(messages)
        options = self._build_options(system_prompt, **kwargs)

        if isinstance(prompt, str):
            prompt_arg: Any = prompt
        else:
            stream_message = prompt_to_stream_message(prompt)

            async def _one() -> Any:
                yield stream_message

            prompt_arg = _one()

        assistant_messages: list[SDKAssistantMessage] = []
        result: ResultMessage | None = None
        async for message in query(prompt=prompt_arg, options=options):
            if isinstance(message, SDKAssistantMessage):
                # Sub-agent traffic carries parent_tool_use_id; only top-level
                # messages form the reply.
                if message.parent_tool_use_id is None:
                    assistant_messages.append(message)
            elif isinstance(message, ResultMessage):
                result = message
        if result is None:
            raise ClaudeCodeError("claude CLI ended without a result message.")
        if result.is_error:
            raise ClaudeCodeError(format_result_error(result))
        return assistant_messages, result

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._check_stop(stop or self.stop)
        consume = self._consume_query(messages, **kwargs)
        if self.timeout is not None:
            assistant_messages, result = await asyncio.wait_for(consume, self.timeout)
        else:
            assistant_messages, result = await consume
        ai_message = result_to_ai_message(
            assistant_messages,
            result,
            expect_structured=kwargs.get("output_format") is not None,
        )
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return _run_coroutine_sync(self._agenerate(messages, stop=stop, **kwargs))  # type: ignore[no-any-return]

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """Token streaming via the SDK's ``include_partial_messages``.

        Yields top-level assistant text deltas as they arrive, then a final
        empty chunk carrying usage and response metadata. (Sync ``.stream()``
        falls back to a single chunk from ``invoke``.)
        """
        self._check_stop(stop or self.stop)
        system_prompt, prompt = convert_messages(messages)
        options = self._build_options(system_prompt, include_partial_messages=True, **kwargs)

        if isinstance(prompt, str):
            prompt_arg: Any = prompt
        else:
            stream_message = prompt_to_stream_message(prompt)

            async def _one() -> Any:
                yield stream_message

            prompt_arg = _one()

        expect_structured = kwargs.get("output_format") is not None
        assistant_messages: list[SDKAssistantMessage] = []
        async for message in query(prompt=prompt_arg, options=options):
            if isinstance(message, StreamEvent):
                if message.parent_tool_use_id is not None:
                    continue
                event = message.event
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        text = delta["text"]
                        chunk = ChatGenerationChunk(message=AIMessageChunk(content=text))
                        if run_manager:
                            await run_manager.on_llm_new_token(text, chunk=chunk)
                        yield chunk
            elif isinstance(message, SDKAssistantMessage):
                if message.parent_tool_use_id is None:
                    assistant_messages.append(message)
            elif isinstance(message, ResultMessage):
                if message.is_error:
                    raise ClaudeCodeError(format_result_error(message))
                final = result_to_ai_message(
                    assistant_messages, message, expect_structured=expect_structured
                )
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        usage_metadata=final.usage_metadata,
                        response_metadata=final.response_metadata,
                        additional_kwargs=final.additional_kwargs,
                    )
                )

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | BaseTool | Any],
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """Not supported — and deliberately NOT mapped to CLI built-in tools.

        LangChain tool calling needs the model to emit tool-call requests for
        the *caller* to execute; the Claude Code CLI only executes its own
        built-in tools inside the subprocess, and this package will not
        silently enable those. Use ``with_structured_output`` (native JSON
        schema output) to get validated structured decisions instead, or use
        ``langchain-anthropic`` against the API for real tool calling.
        """
        raise NotImplementedError(
            "ChatClaudeCode does not support bind_tools. The Claude Code CLI "
            "executes tools inside its own subprocess rather than returning "
            "tool calls to the caller, and enabling its built-in tools from "
            "bind_tools would silently grant shell/file access. Use "
            "with_structured_output() for structured decisions, or "
            "langchain-anthropic for API tool calling."
        )

    def with_structured_output(
        self,
        schema: dict[str, Any] | type,
        *,
        include_raw: bool = False,
        method: Literal["json_schema", "function_calling", "json_mode"] = "json_schema",
        strict: bool | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, dict[str, Any] | BaseModel]:
        """Model wrapper returning outputs formatted to match ``schema``.

        Uses the SDK's native structured output: the JSON schema is passed as
        ``output_format={"type": "json_schema", ...}`` and the CLI returns the
        validated object in ``ResultMessage.structured_output`` — no prompt
        injection, no fenced-JSON scraping (text parsing remains only as a
        fallback for older CLIs).

        Args:
            schema: A pydantic model class (parsed instances are returned), or
                a JSON-schema dict / TypedDict (dicts are returned).
            include_raw: When True, return
                ``{"raw": AIMessage, "parsed": ..., "parsing_error": ...}``
                instead of raising on parse failure.
            method: Accepted for LangChain API compatibility; every method is
                served by the CLI's native JSON-schema output (there is no
                separate function-calling path).
            strict: Accepted for API compatibility; the CLI's structured
                output is always schema-validated, so this is ignored.
        """
        _ = (method, strict)
        if kwargs:
            raise ValueError(f"Received unsupported arguments {kwargs}")
        json_schema = schema_to_json_schema(schema)
        bound = self.bind(output_format={"type": "json_schema", "schema": json_schema})
        parser = make_structured_output_parser(schema)
        if not include_raw:
            return bound | parser

        parser_assign = RunnablePassthrough.assign(
            parsed=itemgetter("raw") | parser,
            parsing_error=lambda _: None,
        )
        parser_none = RunnablePassthrough.assign(parsed=lambda _: None)
        parser_with_fallback = parser_assign.with_fallbacks(
            [parser_none], exception_key="parsing_error"
        )
        return RunnableMap(raw=bound) | parser_with_fallback


__all__ = ["ChatClaudeCode", "ClaudeCodeError"]
