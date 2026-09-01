"""Integration tests: real `claude` CLI over the claude.ai subscription.

Skipped unless LANGCHAIN_CLAUDE_CODE_INTEGRATION=1 — each test is a real,
billed model call.
"""

import base64
import os
import struct
import zlib

import pytest
from pydantic import BaseModel

from langchain_claude_code import ChatClaudeCode

pytestmark = pytest.mark.skipif(
    os.getenv("LANGCHAIN_CLAUDE_CODE_INTEGRATION") != "1",
    reason="set LANGCHAIN_CLAUDE_CODE_INTEGRATION=1 to run real CLI calls",
)

MODEL = "claude-haiku-4-5-20251001"


def llm(**kwargs):
    return ChatClaudeCode(model=MODEL, **kwargs)


def red_png(size: int = 64) -> str:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


def test_invoke():
    message = llm().invoke("Reply with exactly: PONG")
    assert "PONG" in message.content
    assert message.usage_metadata["input_tokens"] > 0
    assert message.usage_metadata["output_tokens"] > 0


def test_structured_output():
    class City(BaseModel):
        city: str
        population_millions: float

    result = (
        llm()
        .with_structured_output(City)
        .invoke("What is the capital of France and its approximate city-proper population?")
    )
    assert isinstance(result, City)
    assert result.city == "Paris"


def test_no_tools_available():
    message = llm().invoke(
        "List the names of every tool you can call right now. "
        "If you have none, reply with exactly: NO TOOLS"
    )
    assert "NO TOOLS" in message.content.upper()


def test_cannot_read_files():
    message = llm().invoke("Read the file /etc/hosts and print its first line verbatim.")
    assert "localhost" not in message.content


def test_image_input():
    content = [
        {"type": "text", "text": "What single colour dominates this image? One word."},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{red_png()}"},
        },
    ]
    from langchain_core.messages import HumanMessage

    message = llm().invoke([HumanMessage(content=content)])
    assert "red" in message.content.lower()


async def test_astream():
    chunks = [chunk async for chunk in llm().astream("Count from 1 to 5, digits only.")]
    assert len(chunks) > 1
    text = "".join(chunk.content for chunk in chunks)
    assert "5" in text
    # langchain-core appends a synthetic final chunk; usage rides on ours.
    assert any(chunk.usage_metadata is not None for chunk in chunks)
