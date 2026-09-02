# langchain-claude-code

The local **Claude Code CLI** as a LangChain chat model, driven through the
official [Claude Agent SDK for Python](https://github.com/anthropics/claude-agent-sdk-python) —
**locked down to a plain model by default**.

```python
from langchain_claude_code import ChatClaudeCode

llm = ChatClaudeCode(model="claude-haiku-4-5-20251001")  # or "haiku"/"sonnet"/"opus"
llm.invoke("Say hello")
```

## Why this package (vs. community Claude-Code adapters)

Community adapters run the CLI as an **agent**: default toolset (Bash, Read,
Edit, …), sometimes `bypassPermissions`. If your prompts contain untrusted
text (web pages, user input), that text can drive shell commands and file
reads on your machine. Here the CLI is reduced to a **model**; every
capability is an explicit, documented opt-in.

### Defaults

| Option | this package | SDK default | typical community adapter |
|---|---|---|---|
| built-in tools (`tools`) | `[]` — none | CLI default toolset | full toolset |
| settings (`setting_sources`) | `[]` — no `~/.claude`, no project settings, no CLAUDE.md | all sources | all sources |
| permission mode | `dontAsk` (deny anything not pre-approved) | `default` (may prompt) | often `bypassPermissions` |
| MCP servers | none, `strict_mcp_config=True` — blocks claude.ai-connected servers too | account/project servers load | account/project servers load |
| max turns | `1` — no agentic loops | unlimited | unlimited |
| session persistence | off (`--no-session-persistence`) | transcripts on disk | transcripts on disk |
| skills / slash commands | off (`--disable-slash-commands`) | on | on |
| system prompt | empty (yours only) | — | sometimes Claude Code's agent prompt |

Verified against `claude-agent-sdk` 0.2.150: with these defaults the model
reports **no tools available** (including the account's claude.ai MCP servers,
which leak in without `strict_mcp_config`).

## Auth

`auth="subscription"` (default) blanks `ANTHROPIC_API_KEY` /
`ANTHROPIC_AUTH_TOKEN` in the subprocess env so the CLI uses the claude.ai
login. `auth="api_key"` passes your environment through and bills the API.

> **Terms caveat:** Anthropic's consumer terms restrict how claude.ai
> subscription access may be driven from third-party harnesses. Review the
> current policy before relying on `auth="subscription"` for production runs.

## Structured output (native)

`with_structured_output` uses the SDK's `output_format={"type": "json_schema", ...}`;
the CLI returns the validated object in `ResultMessage.structured_output`. No
prompt-injected schemas, no fenced-JSON scraping (text parsing exists only as
a fallback for older CLIs).

```python
from pydantic import BaseModel


class City(BaseModel):
    city: str
    population_millions: float


ChatClaudeCode(model="haiku").with_structured_output(City).invoke(
    "Capital of France and its population?"
)  # -> City(city='Paris', population_millions=2.16)
```

`include_raw=True` returns LangChain's standard
`{"raw": AIMessage, "parsed": ..., "parsing_error": ...}`.

## Messages, images, streaming, usage

- `SystemMessage` → the CLI's `--system-prompt`; a multi-message history is
  flattened into a `Human:`/`Assistant:` transcript (the SDK is single-prompt).
- Image blocks in human messages (Anthropic-native, LangChain v1 data blocks,
  or `image_url` data URIs/URLs) are forwarded via the SDK's streaming-input
  content blocks — verified to reach the model. Unconvertible blocks are
  replaced with a visible `[image omitted…]` note.
- `usage_metadata` follows the `langchain-anthropic` convention:
  `input_tokens` includes cache reads/writes, split out under
  `input_token_details` (`cache_read` / `cache_creation`).
- `.astream()` yields real token deltas (`include_partial_messages`); sync
  `.stream()` falls back to a single chunk.

## Tool calling

`bind_tools` raises `NotImplementedError`, deliberately. LangChain tool
calling needs the model to *return* tool calls for your code to execute; the
Claude Code CLI only *executes its own built-in tools inside the subprocess*,
and mapping `bind_tools` onto those would silently grant shell/file access.
Use `with_structured_output` for structured decisions, or `langchain-anthropic`
against the API for real tool calling.

## Prompt hygiene: the CLI knows who you are

The CLI injects account identity into its context. Measured in practice: asked
for "plausible sample values" on a web form, the model typed the **real
account email** as the sample value. If you generate synthetic data through
this model, say so in your system prompt, e.g.:

> Never use the operator's real identity (name, email, phone) in generated
> values; invent plausible synthetic data instead.

## Opt-in agent mode (dangerous)

Everything is a constructor knob: `tools`, `allowed_tools`, `permission_mode`,
`mcp_servers`, `max_turns`, `cwd`, `setting_sources`, `persist_session`,
`enable_slash_commands`. Only loosen them with trusted prompt content, and
prefer an empty scratch `cwd`.

## Development

```bash
uv sync --all-groups
make lint type test              # unit tests use a fake query(); no CLI needed
make integration_tests           # real CLI + subscription; gated by LANGCHAIN_CLAUDE_CODE_INTEGRATION=1
```
