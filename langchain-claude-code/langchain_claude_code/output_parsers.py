"""Structured-output parsing helpers for ChatClaudeCode.

``ChatClaudeCode.with_structured_output`` uses the SDK's native
``output_format={"type": "json_schema", ...}``; the CLI returns the validated
object in ``ResultMessage.structured_output``, which the chat model stashes in
``AIMessage.additional_kwargs["structured_output"]``. The parsers here read it
back out and (for pydantic schemas) instantiate the model class. Parsing the
message text is only a fallback for CLI versions that fail to emit the field.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, TypeAdapter

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def schema_to_json_schema(schema: dict[str, Any] | type) -> dict[str, Any]:
    """A JSON schema for ``schema``: dict passthrough, pydantic/TypedDict via pydantic."""
    if isinstance(schema, dict):
        return schema
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    return TypeAdapter(schema).json_schema()


def _extract_json_text(text: str) -> str:
    match = _JSON_FENCE.search(text)
    if match:
        return match.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


def parse_structured_message(message: BaseMessage, schema: dict[str, Any] | type) -> Any:
    """The structured value carried by ``message``, validated against ``schema``.

    Reads ``additional_kwargs["structured_output"]`` (the CLI-validated
    object); falls back to parsing the message text as JSON. Raises
    :class:`OutputParserException` when neither yields a valid value, so
    LangChain's ``include_raw`` fallback shape works as documented.
    """
    if not isinstance(message, AIMessage):
        raise OutputParserException(f"Expected an AIMessage, got {type(message).__name__}.")
    data = message.additional_kwargs.get("structured_output")
    if data is None:
        text = message.text if isinstance(message.content, str) else str(message.content)
        try:
            data = json.loads(_extract_json_text(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise OutputParserException(
                "No structured_output in the CLI result and the message text is "
                f"not valid JSON: {exc}"
            ) from exc
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            return schema.model_validate(data)
        except Exception as exc:
            raise OutputParserException(f"Structured output failed validation: {exc}") from exc
    return data


def make_structured_output_parser(schema: dict[str, Any] | type) -> RunnableLambda[Any, Any]:
    """A runnable mapping the model's AIMessage to the parsed structured value."""
    return RunnableLambda(lambda message: parse_structured_message(message, schema))
