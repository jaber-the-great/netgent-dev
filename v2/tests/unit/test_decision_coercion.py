"""Stage 3 action-space hardening (docs/research/browser-agent-tool-calling.md §5.5, §5.7):
`done` as a boolean exit, Skyvern's coercion ladder on the decision, the narrowed schema for
opt-in kinds, press-with-index, and the in-place retry ladder in the LLM seam."""

import asyncio

import pytest
from pydantic import ValidationError

from netgent.agent.explorer.actions import to_action
from netgent.agent.explorer.decision import ALL_KINDS, DEFAULT_KINDS, AgentDecision, normalize_keys
from netgent.agent.llm import PARSE_RETRIES, LangChainLLM, decision_schema
from netgent.browser.dom import BBox, DomElement, DomSnapshot, SelectorCandidate
from netgent.schema.actions import PressAction


def test_done_is_a_boolean_exit_never_an_action():
    d = AgentDecision(reasoning="finished", done=True, success=True)
    assert d.done and d.kind is None and d.success
    # the legacy / model-emitted kind="done" (and synonyms) coerce to the boolean
    legacy = AgentDecision(reasoning="x", kind="done", success=False)
    assert legacy.done and legacy.kind is None and not legacy.success
    assert AgentDecision(reasoning="x", kind="Finish").done
    # done with an action → done wins, the action is dropped (done must be returned alone)
    both = AgentDecision(reasoning="x", done=True, kind="click", index=3)
    assert both.kind is None
    with pytest.raises(ValidationError, match="return an action"):
        AgentDecision(reasoning="x")


def test_kind_aliases_and_case_are_repaired():
    assert AgentDecision(reasoning="r", kind="Click", index=1).kind == "click"
    assert AgentDecision(reasoning="r", kind="TYPE", index=1, text="x").kind == "fill"
    assert AgentDecision(reasoning="r", kind="input_text", index=1, text="x").kind == "fill"
    assert AgentDecision(reasoning="r", kind="select_option", index=1, value="a").kind == "select"
    assert AgentDecision(reasoning="r", kind="upload file", index=1).kind == "upload"
    assert AgentDecision(reasoning="r", kind="press-key", keys="Enter").kind == "press"
    assert AgentDecision(reasoning="r", kind="navigate", url="http://x").kind == "goto"
    assert AgentDecision(reasoning="r", kind="check", index=1).kind == "click"
    with pytest.raises(ValidationError):
        AgentDecision(reasoning="r", kind="teleport", index=1)


def test_index_coercion_and_pageless_kinds_drop_their_index():
    assert AgentDecision(reasoning="r", kind="click", index="[3]").index == 3
    assert AgentDecision(reasoning="r", kind="click", index=3.0).index == 3
    assert AgentDecision(reasoning="r", kind="click", index="").index is None
    assert AgentDecision(reasoning="r", kind="wait", index=4, seconds=1).index is None
    assert AgentDecision(reasoning="r", kind="goto", index=4, url="http://x").index is None
    assert AgentDecision(reasoning="r", kind="press", index=4, keys="Enter").index == 4  # the field to type in
    assert AgentDecision(reasoning="r", kind="scroll", index=4).index == 4  # anchors the frame


def test_key_names_are_normalised_to_playwright_names():
    """The baseline died on 'Return' (Unknown key) — every run, same card."""
    assert normalize_keys("Return") == "Enter"
    assert normalize_keys("enter") == "Enter"
    assert normalize_keys("ctrl+a") == "Control+a"
    assert normalize_keys("Arrow Down") == "ArrowDown"
    assert normalize_keys("Shift+Tab") == "Shift+Tab"
    assert normalize_keys("F5") == "F5"  # unknown names pass through
    assert AgentDecision(reasoning="r", kind="press", keys="Return").keys == "Enter"


def test_press_with_index_targets_that_element():
    snap = DomSnapshot(url="u", title="t", elements=[
        DomElement(tag="input", type="search", name="Search", bbox=BBox(x=0, y=0, w=1, h=1),
                   candidates=[SelectorCandidate(kind="css", value="#q")]),
    ])
    act = to_action(AgentDecision(reasoning="r", kind="press", index=0, keys="Return"), snap)
    assert isinstance(act, PressAction) and act.keys == "Enter" and act.locator is not None
    assert to_action(AgentDecision(reasoning="r", kind="press", keys="Enter"), snap).locator is None


def test_schema_variant_narrows_kind_to_the_allowed_set():
    assert decision_schema(True, ALL_KINDS) is AgentDecision
    core = decision_schema(True, DEFAULT_KINDS)
    kind_schema = core.model_json_schema()["properties"]["kind"]
    literals = {v for opt in kind_schema.get("anyOf", [kind_schema]) for v in opt.get("enum", [])}
    assert literals == set(DEFAULT_KINDS)
    d = AgentDecision.model_validate(core(reasoning="r", kind="click", index=1).model_dump())
    assert d.kind == "click"
    with pytest.raises(ValidationError):
        core(reasoning="r", kind="hover", index=1)


def test_llm_seam_retries_an_invalid_response_in_place_before_giving_up():
    """Notte's ladder: a failed parse is retried with the error fed back; the step is only
    lost after PARSE_RETRIES+1 attempts."""

    class Structured:
        def __init__(self, outcomes):
            self.outcomes, self.inputs = list(outcomes), []

        async def ainvoke(self, messages):
            self.inputs.append(messages)
            return self.outcomes.pop(0)

    llm = LangChainLLM.__new__(LangChainLLM)
    llm.usage = {k: 0 for k in ("calls", "input_tokens", "output_tokens", "cache_read_tokens",
                               "cache_creation_tokens", "observation_chars", "history_chars")}
    llm.calls = []
    good = AgentDecision(reasoning="ok", kind="click", index=0)
    fake = Structured([{"parsed": None, "parsing_error": "kind: field required", "raw": None},
                       {"parsed": good, "raw": None}])
    llm._structured = {(ALL_KINDS, 1): fake}
    got = asyncio.run(llm.decide("S", "T", "O", []))
    assert got is good and llm.usage["calls"] == 2 and llm.usage["parse_retries"] == 1
    # the retry carries the validator's complaint after the original two messages
    assert len(fake.inputs[1]) == 3 and "field required" in fake.inputs[1][-1].content

    fake = Structured([{"parsed": None, "parsing_error": "bad", "raw": None}] * (PARSE_RETRIES + 1))
    llm._structured = {(ALL_KINDS, 1): fake}
    with pytest.raises(ValueError, match="after 3 attempts"):
        asyncio.run(llm.decide("S", "T", "O", []))


def test_llm_seam_runs_the_real_structured_output_path_on_a_fake_chat_model():
    """LangChain's own test double (docs: langchain/test/unit-testing): a GenericFakeChatModel
    injected through the LLM seam drives with_structured_output → PydanticToolsParser → the
    retry ladder, with no key and no network. `bind_tools` must be a no-op for the fake, as in
    langgraph-bigtool's tests, or with_structured_output refuses the model."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, *args, **kwargs):
            return self

    name = decision_schema(False).__name__
    call = lambda args, i: AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])  # noqa: E731
    fake = FakeModel(messages=iter([
        call({"kind": "click", "index": 0}, 1),  # no reasoning → validation error → retried in place
        call({"reasoning": "ok", "kind": "click", "index": 0}, 2),
    ]))
    llm = LangChainLLM(fake)
    got = asyncio.run(llm.decide("S", "T", "O", []))
    assert got.kind == "click" and got.index == 0 and got.reasoning == "ok"
    assert llm.usage["calls"] == 2 and llm.usage["parse_retries"] == 1
