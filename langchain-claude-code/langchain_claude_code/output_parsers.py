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


_ENVELOPE_KEYS = frozenset({"$PARAMETER_VALUE", "value", "values", "result", "output", "response"})


def unwrap_envelope(data: Any, schema: dict[str, Any] | type) -> Any:
    r"""Undo the CLI's structured-output envelope, when there is one.

    Measured (Claude Code 2.1.x): for a schema with a dict-valued field the CLI may return
    ``{"<field>": "<the whole answer as a JSON string>"}`` — e.g. a plan whose
    ``variations[].values`` is a dict came back as ``{"values": "{\"variations\": [...]}"}`` —
    or the tool-parameter wrapper ``{"$PARAMETER_NAME": "response", "$PARAMETER_VALUE": "<json>"}``.
    Rule: a single-key dict whose only value is a JSON string decoding to an object, where the
    key is not a property of the schema or is a known envelope key, is replaced by that object
    (recursively). A genuine single-field answer whose value is not a JSON object is left alone.
    """
    properties = _schema_properties(schema)
    for _ in range(4):  # bounded: envelopes nest at most a few levels
        if not isinstance(data, dict):
            break
        # The tool-parameter wrapper (measured, Claude Code 2.1.257, a NextRoundPlan schema):
        # {"$PARAMETER_NAME": "response", "$PARAMETER_VALUE": "<the answer as a JSON string>"}.
        if "$PARAMETER_VALUE" in data and set(data) <= {"$PARAMETER_NAME", "$PARAMETER_VALUE"}:
            data = {"$PARAMETER_VALUE": data["$PARAMETER_VALUE"]}
        if len(data) != 1:
            break
        ((key, value),) = data.items()
        if not isinstance(value, str):
            break
        try:
            inner = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            break
        if not isinstance(inner, dict):
            break
        # An envelope: a known wrapper key, a key the schema does not declare, or a declared
        # key whose string value decodes to an object carrying the schema's own properties.
        if key in _ENVELOPE_KEYS or key not in properties or (properties & set(inner)):
            data = inner
            continue
        break
    return data


def _schema_properties(schema: dict[str, Any] | type) -> set[str]:
    try:
        js = schema_to_json_schema(schema)
    except Exception:  # an unusual schema: no property knowledge
        return set()
    return set((js or {}).get("properties", {}) or {})


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
    data = unwrap_envelope(data, schema)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            return schema.model_validate(data)
        except Exception as exc:
            raise OutputParserException(f"Structured output failed validation: {exc}") from exc
    return data


def make_structured_output_parser(schema: dict[str, Any] | type) -> RunnableLambda[Any, Any]:
    """A runnable mapping the model's AIMessage to the parsed structured value."""
    return RunnableLambda(lambda message: parse_structured_message(message, schema))
