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
_WRAPPER_NAME_KEY = "$PARAMETER_NAME"
_MAX_ENVELOPE_DEPTH = 4  # envelopes nest at most a few levels


def _json_object(value: Any) -> dict[str, Any] | None:
    """`value` as a JSON object: a dict as is, a JSON string decoding to one; else None."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            inner = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(inner, dict):
            return inner
    return None


def unwrap_envelope(data: Any, schema: dict[str, Any] | type) -> Any:
    r"""Undo the CLI's structured-output envelope, when there is one.

    Measured (Claude Code 2.1.x), one wrapper at a time, any of them nested in another:

    - the field-name envelope: for a schema with a dict-valued field the CLI may return
      ``{"<field>": "<the whole answer as a JSON string>"}`` — a plan whose
      ``variations[].values`` is a dict came back as ``{"values": "{"variations": [...]}"}``;
    - the tool-parameter wrapper, in two spellings: ``{"$PARAMETER_NAME": "response",
      "$PARAMETER_VALUE": "<json>"}`` and ``{"$PARAMETER_NAME": "response", "value": "<json>"}``
      (the second is what ended a live planner call: ``got keys ['$PARAMETER_NAME', 'value']``);
    - the answer as a JSON *string* inside any of these, or as a plain object
      (``{"value": {...}}``).

    Rule: drop a ``$PARAMETER_NAME`` key when exactly one other key remains; then a single-key
    dict whose only value is (or decodes to) a JSON object, where the key is a known envelope
    key or not a property of the schema — or a declared property whose object carries the
    schema's own properties — is replaced by that object, recursively. A genuine single-field
    answer whose value is not an object, or whose object is the field's own value, is left alone.
    """
    properties = _schema_properties(schema)
    for _ in range(_MAX_ENVELOPE_DEPTH):
        if not isinstance(data, dict):
            break
        if _WRAPPER_NAME_KEY in data and len(data) == 2:
            data = {k: v for k, v in data.items() if k != _WRAPPER_NAME_KEY}
        if len(data) != 1:
            break
        ((key, value),) = data.items()
        inner = _json_object(value)
        if inner is None:
            break
        is_string = isinstance(value, str)
        # An envelope: a known wrapper key, a key the schema does not declare, or a declared
        # key whose value carries the schema's own properties. A declared key holding a plain
        # object that shares no property with the schema is that field's own value — unless it
        # arrived as a JSON string, the field-name envelope's signature.
        envelope_key = is_string and key in _ENVELOPE_KEYS
        if key not in properties or (properties & set(inner)) or envelope_key:
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
        _reject_foreign_object(data, schema)
        try:
            return schema.model_validate(data)
        except Exception as exc:
            raise OutputParserException(f"Structured output failed validation: {exc}") from exc
    return data


def _reject_foreign_object(data: Any, schema: type[BaseModel]) -> None:
    """Reject a non-empty object that shares no field name with ``schema``.

    A model whose fields all have defaults would otherwise validate it into an
    empty instance — silently.
    """
    if isinstance(data, dict) and data and schema.model_fields:
        fields = schema.model_fields
        names = set(fields) | {f.alias for f in fields.values() if f.alias}
        if not (set(data) & names):
            raise OutputParserException(
                f"Structured output has none of {sorted(names)}; got keys {sorted(data)[:6]}"
            )


def make_structured_output_parser(schema: dict[str, Any] | type) -> RunnableLambda[Any, Any]:
    """A runnable mapping the model's AIMessage to the parsed structured value."""
    return RunnableLambda(lambda message: parse_structured_message(message, schema))
