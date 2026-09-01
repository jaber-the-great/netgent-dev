"""Unit tests for ChatClaudeCode against a fake query() — the safe defaults are the contract."""

import pytest
from claude_agent_sdk.types import StreamEvent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from langchain_claude_code import ChatClaudeCode, ClaudeCodeError
from tests.unit_tests.conftest import make_assistant, make_result

MODEL = "claude-haiku-4-5-20251001"


def llm(**kwargs):
    return ChatClaudeCode(model=MODEL, **kwargs)


class TestSafeDefaults:
    """The point of the package: the CLI subprocess is a model, not an agent."""

    def test_lockdown_options(self, fake_query):
        llm().invoke("hi")
        options = fake_query.last_options
        assert options.tools == []  # no built-in tools
        assert options.setting_sources == []  # no user/project settings
        assert options.permission_mode == "dontAsk"
        assert options.mcp_servers == {}
        assert options.strict_mcp_config is True
        assert options.max_turns == 3
        assert "no-session-persistence" in options.extra_args
        assert "disable-slash-commands" in options.extra_args
        assert options.model == MODEL

    def test_subscription_auth_strips_credentials(self, fake_query):
        llm().invoke("hi")
        env = fake_query.last_options.env
        assert env["ANTHROPIC_API_KEY"] == ""
        assert env["ANTHROPIC_AUTH_TOKEN"] == ""

    def test_api_key_auth_passes_env_through(self, fake_query):
        llm(auth="api_key").invoke("hi")
        env = fake_query.last_options.env
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env

    def test_explicit_env_wins_over_auth(self, fake_query):
        llm(env={"ANTHROPIC_API_KEY": "sk-mine"}).invoke("hi")
        assert fake_query.last_options.env["ANTHROPIC_API_KEY"] == "sk-mine"

    def test_tools_none_is_coerced_to_empty(self, fake_query):
        llm(tools=None).invoke("hi")
        assert fake_query.last_options.tools == []

    def test_opt_in_knobs_pass_through(self, fake_query):
        llm(
            tools=["Bash"],
            allowed_tools=["Bash(ls:*)"],
            permission_mode="default",
            max_turns=5,
            cwd="/tmp/scratch",
            persist_session=True,
            enable_slash_commands=True,
        ).invoke("hi")
        options = fake_query.last_options
        assert options.tools == ["Bash"]
        assert options.allowed_tools == ["Bash(ls:*)"]
        assert options.permission_mode == "default"
        assert options.max_turns == 5
        assert str(options.cwd) == "/tmp/scratch"
        assert "no-session-persistence" not in options.extra_args
        assert "disable-slash-commands" not in options.extra_args

    def test_bind_tools_raises_and_never_enables_cli_tools(self, fake_query):
        with pytest.raises(NotImplementedError, match="with_structured_output"):
            llm().bind_tools([{"name": "f", "description": "", "input_schema": {}}])
        assert fake_query.calls == []  # nothing was ever sent


class TestMessages:
    def test_system_message_becomes_system_prompt(self, fake_query):
        llm().invoke([SystemMessage("be terse"), HumanMessage("hi")])
        assert fake_query.last_options.system_prompt == "be terse"
        assert fake_query.last_prompt == "hi"

    def test_no_system_message_means_no_system_prompt(self, fake_query):
        llm().invoke("hi")
        assert fake_query.last_options.system_prompt is None

    def test_history_is_flattened(self, fake_query):
        llm().invoke(
            [
                HumanMessage("one"),
                AIMessage("two"),
                HumanMessage("three"),
            ]
        )
        assert fake_query.last_prompt == "Human: one\n\nAssistant: two\n\nHuman: three"

    def test_image_goes_through_stream_input(self, fake_query):
        content = [
            {"type": "text", "text": "what colour?"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,QUJD"},
            },
        ]
        llm().invoke([HumanMessage(content=content)])
        [stream_message] = fake_query.last_prompt
        blocks = stream_message["message"]["content"]
        assert blocks[0] == {"type": "text", "text": "what colour?"}
        assert blocks[1] == {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
        }

    def test_unconvertible_image_dropped_with_note(self, fake_query):
        llm().invoke([HumanMessage(content=[{"type": "image", "nonsense": True}])])
        assert "[image omitted" in fake_query.last_prompt

    def test_stop_sequences_rejected(self, fake_query):
        with pytest.raises(ValueError, match="stop sequences"):
            llm().invoke("hi", stop=["END"])


class TestResults:
    def test_text_and_usage(self, fake_query):
        message = llm().invoke("hi")
        assert message.content == "hello from claude"
        # langchain-anthropic convention: input includes cache read+creation
        assert message.usage_metadata["input_tokens"] == 10 + 100 + 200
        assert message.usage_metadata["output_tokens"] == 5
        assert message.usage_metadata["input_token_details"] == {
            "cache_read": 100,
            "cache_creation": 200,
        }
        assert message.response_metadata["model_name"] == MODEL
        assert message.response_metadata["session_id"] == "sess-1"

    def test_error_result_raises(self, fake_query):
        fake_query.script = [
            make_result(subtype="error_during_execution", is_error=True, result="boom")
        ]
        with pytest.raises(ClaudeCodeError, match="error_during_execution.*boom"):
            llm().invoke("hi")

    async def test_agenerate(self, fake_query):
        message = await llm().ainvoke("hi")
        assert message.content == "hello from claude"

    async def test_astream_yields_deltas(self, fake_query):
        fake_query.script = [
            StreamEvent(
                uuid="u1",
                session_id="s",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "hel"},
                },
            ),
            StreamEvent(
                uuid="u2",
                session_id="s",
                event={
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "lo"},
                },
            ),
            make_assistant("hello"),
            make_result(result="hello"),
        ]
        chunks = [chunk async for chunk in llm().astream("hi")]
        # langchain-core may append a synthetic final chunk; check the deltas
        # and that exactly one chunk carries usage.
        assert [c.content for c in chunks if c.content] == ["hel", "lo"]
        usages = [c.usage_metadata for c in chunks if c.usage_metadata]
        assert len(usages) == 1
        assert usages[0]["output_tokens"] == 5
        assert fake_query.last_options.include_partial_messages is True


class TestStructuredOutput:
    class City(BaseModel):
        city: str
        population_millions: float

    def test_output_format_and_parsing(self, fake_query):
        fake_query.script = [
            make_assistant("Paris blah"),
            make_result(structured_output={"city": "Paris", "population_millions": 2.16}),
        ]
        result = llm().with_structured_output(self.City).invoke("capital of france?")
        options = fake_query.last_options
        assert options.output_format == {
            "type": "json_schema",
            "schema": self.City.model_json_schema(),
        }
        assert result == self.City(city="Paris", population_millions=2.16)
        # lockdown holds for structured calls too
        assert options.tools == []
        assert options.setting_sources == []

    def test_dict_schema_returns_dict(self, fake_query):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        fake_query.script = [make_assistant(), make_result(structured_output={"x": 1})]
        result = llm().with_structured_output(schema).invoke("x?")
        assert result == {"x": 1}
        assert fake_query.last_options.output_format == {"type": "json_schema", "schema": schema}

    def test_include_raw_success(self, fake_query):
        fake_query.script = [
            make_assistant(),
            make_result(structured_output={"city": "Paris", "population_millions": 2.16}),
        ]
        out = llm().with_structured_output(self.City, include_raw=True).invoke("?")
        assert set(out) == {"raw", "parsed", "parsing_error"}
        assert out["parsed"] == self.City(city="Paris", population_millions=2.16)
        assert out["parsing_error"] is None
        assert isinstance(out["raw"], AIMessage)

    def test_include_raw_parse_failure(self, fake_query):
        fake_query.script = [
            make_assistant("not json at all"),
            make_result(structured_output=None, result="not json at all"),
        ]
        out = llm().with_structured_output(self.City, include_raw=True).invoke("?")
        assert out["parsed"] is None
        assert out["parsing_error"] is not None

    def test_text_json_fallback_when_no_structured_output(self, fake_query):
        fake_query.script = [
            make_assistant('```json\n{"city": "Paris", "population_millions": 2.16}\n```'),
            make_result(structured_output=None, result="ignored"),
        ]
        result = llm().with_structured_output(self.City).invoke("?")
        assert result.city == "Paris"
