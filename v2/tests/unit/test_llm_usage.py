"""Per-run LLM usage: a `scoped()` view of the seam counts its own calls (so `--parallel > 1`
runs stay attributable) while the parent keeps the grand total; FakeLLM's view is itself."""

import asyncio

import pytest

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.llm import LangChainLLM, decision_schema, scoped_llm, usage_of


def test_fake_llm_scoped_view_is_itself():
    llm = FakeLLM([AgentDecision(reasoning="r", kind="click", index=0)])
    assert scoped_llm(llm) is llm and usage_of(llm) is None


def test_scoped_views_count_separately_and_roll_up():
    pytest.importorskip("langchain_core")
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, *args, **kwargs):
            return self

    name = decision_schema(False).__name__
    call = lambda i: AIMessage(content="", tool_calls=[{"name": name, "args": {"reasoning": "ok", "kind": "click", "index": 0}, "id": f"c{i}"}])  # noqa: E731,E501
    llm = LangChainLLM(FakeModel(messages=iter([call(i) for i in range(3)])))
    a, b = scoped_llm(llm), scoped_llm(llm)
    assert a is not llm and a is not b and a._chat is llm._chat

    async def run():
        await a.decide("S", "T", "O", [])
        await b.decide("S", "T", "O", [])
        await b.decide("S", "T", "O", [])

    asyncio.run(run())
    assert usage_of(a)["calls"] == 1 and usage_of(b)["calls"] == 2
    assert usage_of(llm)["calls"] == 3 and len(llm.calls) == 3  # the parent's grand total
    assert len(a.calls) == 1 and len(b.calls) == 2
