"""Conversions between LangChain messages and Claude Agent SDK messages.

The Claude Agent SDK is single-prompt: one ``query()`` call carries one user
prompt (a string, or one streaming-input user message whose content is a list
of Anthropic-API content blocks). LangChain conversations are lists of
messages. This module flattens a LangChain message list into that shape and
converts the SDK's response messages back into an :class:`~langchain_core.messages.AIMessage`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from claude_agent_sdk.types import (
    AssistantMessage as SDKAssistantMessage,
)
from claude_agent_sdk.types import (
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.ai import UsageMetadata
from langchain_core.messages.tool import tool_call as create_tool_call

if TYPE_CHECKING:
    from collections.abc import Sequence

IMAGE_OMITTED_NOTE = "[image omitted: unsupported image block format]"


def _image_block_to_anthropic(block: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a LangChain image content block to an Anthropic API image block.

    Handles the Anthropic-native shape (passed through), LangChain v1 data
    blocks (``source_type``/``base64``/``url``), and OpenAI-style
    ``image_url`` blocks (data URIs and http(s) URLs). Returns ``None`` for
    shapes that cannot be converted.
    """
    block_type = block.get("type")
    if block_type == "image" and isinstance(block.get("source"), dict):
        return block  # Already Anthropic-native.
    if block_type == "image":
        # LangChain v1 standard content blocks.
        if block.get("source_type") == "base64" or ("base64" in block and "url" not in block):
            data = block.get("data") or block.get("base64")
            mime = block.get("mime_type") or "image/png"
            if isinstance(data, str):
                return {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": data},
                }
        url = block.get("url") if block.get("source_type") in (None, "url") else None
        if isinstance(url, str):
            if url.startswith("data:"):
                return _data_uri_to_image_block(url)
            return {"type": "image", "source": {"type": "url", "url": url}}
        return None
    if block_type == "image_url":
        image_url = block.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else image_url
        if not isinstance(url, str):
            return None
        if url.startswith("data:"):
            return _data_uri_to_image_block(url)
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _data_uri_to_image_block(url: str) -> dict[str, Any] | None:
    """``data:<mime>;base64,<data>`` -> Anthropic base64 image block."""
    try:
        header, data = url.split(",", 1)
        mime = header.removeprefix("data:").split(";")[0] or "image/png"
    except ValueError:
        return None
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}


def _content_to_parts(content: str | list[Any]) -> tuple[str, list[dict[str, Any]]]:
    """Split LangChain message content into (text, anthropic image blocks).

    Non-text, non-image blocks are dropped; unconvertible image blocks are
    replaced by a visible note in the text so the model knows something was
    removed rather than silently losing it.
    """
    if isinstance(content, str):
        return content, []
    texts: list[str] = []
    images: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            texts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text", "")))
        elif block.get("type") in ("image", "image_url"):
            converted = _image_block_to_anthropic(block)
            if converted is not None:
                images.append(converted)
            else:
                texts.append(IMAGE_OMITTED_NOTE)
    return "\n".join(texts), images


def _message_text(message: BaseMessage) -> tuple[str, list[dict[str, Any]]]:
    text, images = _content_to_parts(message.content)
    if isinstance(message, ToolMessage):
        text = f"[tool result {message.tool_call_id}]\n{text}"
    return text, images


def convert_messages(
    messages: Sequence[BaseMessage],
) -> tuple[str | None, str | list[dict[str, Any]]]:
    """Flatten a LangChain message list into ``(system_prompt, prompt)``.

    - Every :class:`SystemMessage` (wherever it appears) contributes to the
      single ``system_prompt`` the CLI takes.
    - A single trailing human turn is passed verbatim. A longer history is
      flattened into a ``Human:``/``Assistant:`` transcript, since the SDK has
      no native multi-turn input.
    - Image blocks in human messages become Anthropic API image blocks; when
      any are present the prompt is returned as a content-block list for the
      SDK's streaming-input mode, otherwise as a plain string.
    """
    system_parts: list[str] = []
    conversation: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            text, _ = _content_to_parts(message.content)
            system_parts.append(text)
        else:
            conversation.append(message)
    system_prompt = "\n\n".join(part for part in system_parts if part) or None

    if not conversation:
        raise ValueError("No user or assistant messages to send.")

    blocks: list[dict[str, Any]] = []
    single_human = len(conversation) == 1 and isinstance(conversation[0], HumanMessage)
    for message in conversation:
        text, images = _message_text(message)
        if single_human:
            if text:
                blocks.append({"type": "text", "text": text})
        else:
            role = "Assistant" if isinstance(message, AIMessage) else "Human"
            blocks.append({"type": "text", "text": f"{role}: {text}"})
        blocks.extend(images)

    if not any(block["type"] != "text" for block in blocks):
        return system_prompt, "\n\n".join(block["text"] for block in blocks)
    return system_prompt, blocks


def prompt_to_stream_message(prompt: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap content blocks in the SDK streaming-input user-message envelope.

    The shape mirrors what the SDK itself writes for string prompts
    (``claude_agent_sdk._internal.client``); content blocks pass through to
    the CLI verbatim, which is how image input reaches the model.
    """
    return {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }


def usage_from_result(result: ResultMessage) -> UsageMetadata | None:
    """Map ``ResultMessage.usage`` to LangChain ``usage_metadata``.

    Follows the ``langchain-anthropic`` convention: ``input_tokens`` is the
    total prompt size including cache reads and cache writes, with the
    split reported under ``input_token_details``.
    """
    usage = result.usage or {}
    if not usage:
        return None
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    input_tokens = int(usage.get("input_tokens") or 0) + cache_read + cache_creation
    output_tokens = int(usage.get("output_tokens") or 0)
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_token_details={
            "cache_read": cache_read,
            "cache_creation": cache_creation,
        },
    )


def result_to_ai_message(
    assistant_messages: list[SDKAssistantMessage],
    result: ResultMessage,
    *,
    expect_structured: bool = False,
) -> AIMessage:
    """Build the final :class:`AIMessage` for one completed ``query()``.

    Content comes from the last SDK assistant message (the final answer in a
    multi-turn run); ``ResultMessage.result`` is the fallback when no
    assistant message was captured. Tool-use blocks — possible only when the
    caller opted into CLI tools or MCP servers — surface as LangChain
    ``tool_calls``. When structured output was requested,
    ``ResultMessage.structured_output`` lands in
    ``additional_kwargs["structured_output"]`` for the output parsers.
    """
    text_parts: list[str] = []
    tool_calls = []
    model_name: str | None = None
    if assistant_messages:
        last = assistant_messages[-1]
        model_name = last.model
        for block in last.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(create_tool_call(name=block.name, args=block.input, id=block.id))
            elif isinstance(block, ThinkingBlock):
                continue  # Not surfaced; enable via the `thinking` option if needed.
    content = "\n".join(text_parts) if text_parts else (result.result or "")

    additional_kwargs: dict[str, Any] = {}
    if expect_structured:
        additional_kwargs["structured_output"] = result.structured_output

    response_metadata: dict[str, Any] = {
        "model_name": model_name,
        "stop_reason": result.stop_reason,
        "session_id": result.session_id,
        "num_turns": result.num_turns,
        "duration_ms": result.duration_ms,
        "duration_api_ms": result.duration_api_ms,
        "total_cost_usd": result.total_cost_usd,
    }
    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        usage_metadata=usage_from_result(result),
        response_metadata=response_metadata,
        additional_kwargs=additional_kwargs,
    )


def format_result_error(result: ResultMessage) -> str:
    """Human-readable error text for a failed ``ResultMessage``."""
    detail = result.result or (json.dumps(result.errors) if result.errors else "no detail")
    status = f" (HTTP {result.api_error_status})" if result.api_error_status else ""
    return f"claude CLI run failed [{result.subtype}]{status}: {detail}"
