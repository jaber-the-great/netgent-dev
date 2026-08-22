"""The LLM seam builds a multimodal message when handed an image, and FakeLLM ignores it."""

import asyncio

from netgent.agent import FakeLLM
from netgent.agent.explore_agent.decision import AgentDecision


def test_fake_llm_ignores_image():
    llm = FakeLLM([AgentDecision(reasoning="x", kind="click", index=0)])
    out = asyncio.run(llm.decide("sys", "task", "obs", [], image=b"\x89PNG..."))
    assert out.kind == "click"


def test_langchain_llm_builds_image_block(monkeypatch):
    from netgent.agent import llm as llm_mod

    captured = {}

    class FakeStructured:
        async def ainvoke(self, payload):
            captured["payload"] = payload

            class R(dict):
                pass

            r = R(parsed=AgentDecision(reasoning="ok", kind="click", index=0), raw=None)
            return r

    class FakeChat:
        def with_structured_output(self, *a, **k):
            return FakeStructured()

    def fake_init(name, **k):
        return FakeChat()

    monkeypatch.setattr(llm_mod, "init_chat_model", fake_init, raising=False)
    # init_chat_model is imported lazily inside __init__; patch the source module too
    import langchain.chat_models as cm

    monkeypatch.setattr(cm, "init_chat_model", fake_init)

    model = llm_mod.LangChainLLM("anthropic/claude-haiku-4-5-20251001")

    # text-only: payload is a string
    asyncio.run(model.decide("sys", "task", "obs", []))
    assert isinstance(captured["payload"], str)

    # with image: payload is [HumanMessage] whose content has a text block and an image_url block
    asyncio.run(model.decide("sys", "task", "obs", [], image=b"\x89PNGfake"))
    msgs = captured["payload"]
    assert isinstance(msgs, list) and len(msgs) == 1
    blocks = msgs[0].content
    kinds = [b["type"] for b in blocks]
    assert "text" in kinds and "image_url" in kinds
    img_block = next(b for b in blocks if b["type"] == "image_url")
    assert img_block["image_url"]["url"].startswith("data:image/png;base64,")
    assert model.usage["images"] == 1
