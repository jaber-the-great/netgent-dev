"""langchain-tests standard unit-test suite for ChatClaudeCode."""

from langchain_tests.unit_tests import ChatModelUnitTests

from langchain_claude_code import ChatClaudeCode


class TestChatClaudeCodeStandard(ChatModelUnitTests):
    @property
    def chat_model_class(self) -> type[ChatClaudeCode]:
        return ChatClaudeCode

    @property
    def chat_model_params(self) -> dict:
        return {"model": "claude-haiku-4-5-20251001"}

    @property
    def has_tool_calling(self) -> bool:
        # bind_tools is overridden only to raise; the CLI cannot return tool
        # calls to the caller without enabling its built-in tools.
        return False
