"""Option building, environment handling, and CLI discovery for ChatClaudeCode.

Everything that decides *what the Claude Code CLI subprocess is allowed to do*
lives here, so the lockdown is auditable in one place:

- :func:`build_env` — which credentials the subprocess sees.
- :func:`build_options` — which tools, settings, MCP servers, and CLI flags it
  gets. The defaults reduce the CLI to a plain model: no tools, no filesystem
  settings, no MCP servers, no session persistence, no skills.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from claude_agent_sdk.types import ClaudeAgentOptions

if TYPE_CHECKING:
    from pathlib import Path

    from claude_agent_sdk.types import McpServerConfig, PermissionMode, ToolsPreset

AuthMode = Literal["subscription", "api_key"]

#: Env vars that make the CLI bill the API instead of the claude.ai login.
#: Overriding them with "" in the subprocess env makes the CLI treat them as
#: unset (the SDK merges ``options.env`` over the inherited ``os.environ``, so
#: keys cannot be *removed*, only blanked).
_API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

#: Extra CLI flags applied by default (``None`` = boolean flag):
#: ``--no-session-persistence`` — no transcript written under ~/.claude;
#: ``--disable-slash-commands`` — no skills, even if a future option combination
#: would surface them.
SAFE_EXTRA_ARGS: dict[str, str | None] = {
    "no-session-persistence": None,
    "disable-slash-commands": None,
}


def build_env(auth: AuthMode, env: dict[str, str] | None = None) -> dict[str, str]:
    """Build the ``ClaudeAgentOptions.env`` overlay for the subprocess.

    Args:
        auth: ``"subscription"`` blanks ``ANTHROPIC_API_KEY`` /
            ``ANTHROPIC_AUTH_TOKEN`` so the CLI falls back to the claude.ai
            login; ``"api_key"`` passes the inherited environment through.
        env: Extra variables for the subprocess. Applied last, so an explicit
            entry here wins over the ``auth`` handling.
    """
    overlay: dict[str, str] = {}
    if auth == "subscription":
        overlay.update(dict.fromkeys(_API_CREDENTIAL_VARS, ""))
    if env:
        overlay.update(env)
    return overlay


def build_options(
    *,
    model: str,
    auth: AuthMode = "subscription",
    system_prompt: str | None = None,
    tools: list[str] | dict[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    permission_mode: PermissionMode = "dontAsk",
    setting_sources: list[Any] | None = None,
    mcp_servers: dict[str, McpServerConfig] | None = None,
    strict_mcp_config: bool = True,
    max_turns: int | None = 1,
    cwd: str | Path | None = None,
    cli_path: str | Path | None = None,
    env: dict[str, str] | None = None,
    persist_session: bool = False,
    enable_slash_commands: bool = False,
    max_budget_usd: float | None = None,
    fallback_model: str | None = None,
    effort: Any = None,
    thinking: Any = None,
    output_format: dict[str, Any] | None = None,
    include_partial_messages: bool = False,
    max_buffer_size: int | None = None,
) -> ClaudeAgentOptions:
    """Build :class:`ClaudeAgentOptions` with the safe-by-default lockdown.

    ``tools=None`` and ``setting_sources=None`` here mean "use the safe
    default" (``[]`` — nothing), NOT the SDK's meaning of ``None`` ("CLI
    defaults" — the full Claude Code toolset and every settings file). Callers
    who genuinely want the CLI defaults must construct
    :class:`ClaudeAgentOptions` themselves; this package never produces that
    configuration.
    """
    extra_args = dict(SAFE_EXTRA_ARGS)
    if persist_session:
        del extra_args["no-session-persistence"]
    if enable_slash_commands:
        del extra_args["disable-slash-commands"]

    return ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        tools=cast("list[str] | ToolsPreset", tools) if tools is not None else [],
        allowed_tools=list(allowed_tools or []),
        disallowed_tools=list(disallowed_tools or []),
        permission_mode=permission_mode,
        setting_sources=list(setting_sources) if setting_sources is not None else [],
        mcp_servers=dict(mcp_servers or {}),
        strict_mcp_config=strict_mcp_config,
        max_turns=max_turns,
        cwd=cwd,
        cli_path=cli_path,
        env=build_env(auth, env),
        extra_args=extra_args,
        max_budget_usd=max_budget_usd,
        fallback_model=fallback_model,
        effort=effort,
        thinking=thinking,
        output_format=output_format,
        include_partial_messages=include_partial_messages,
        max_buffer_size=max_buffer_size,
    )
