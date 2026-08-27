"""The bounded action batch (`then`) on a decision — schema, validation, prompt reflection —
(docs/research/browser-agent-tool-calling.md §5.1). Execution semantics are covered by the
integration test in tests/integration/test_browser_agent.py."""

import pytest
from pydantic import ValidationError

from netgent.agent.explorer.decision import DEFAULT_KINDS, MAX_BATCH, AgentAction, AgentDecision
from netgent.agent.explorer.prompt import build_system_prompt
from netgent.agent.llm import decision_schema


def test_decision_actions_are_the_head_plus_then_in_order():
    d = AgentDecision(reasoning="fill both then submit", kind="fill", index=1, text="Ada",
                      then=[AgentAction(kind="fill", index=2, text="a@b.co"), AgentAction(kind="click", index=3)])
    acts = d.actions()
    assert [a.kind for a in acts] == ["fill", "fill", "click"]
    assert acts[0].text == "Ada" and acts[2].index == 3
    assert AgentDecision(reasoning="r", kind="click", index=1).actions()[0].kind == "click"
    assert AgentDecision(reasoning="r", done=True).actions() == []


def test_batch_is_bounded_and_every_item_needs_a_kind():
    too_many = [AgentAction(kind="fill", index=i, text="x") for i in range(MAX_BATCH)]
    with pytest.raises(ValidationError):
        AgentDecision(reasoning="r", kind="fill", index=0, text="x", then=too_many)
    with pytest.raises(ValidationError, match="needs a kind"):
        AgentDecision(reasoning="r", kind="fill", index=0, text="x", then=[AgentAction(index=1)])
    # done drops any batch
    assert AgentDecision(reasoning="r", done=True, then=[AgentAction(kind="click", index=1)]).then == []


def test_batched_items_get_the_same_coercions():
    d = AgentDecision(reasoning="r", kind="fill", index=0, text="x",
                      then=[AgentAction(kind="Press Key", index="[4]", keys="Return")])
    assert d.then[0].kind == "press" and d.then[0].index == 4 and d.then[0].keys == "Enter"


def test_schema_without_batching_has_no_then_field():
    single = decision_schema(True, DEFAULT_KINDS, max_actions=1)
    assert "then" not in single.model_fields
    batched = decision_schema(True, DEFAULT_KINDS, max_actions=3)
    assert "then" in batched.model_fields
    props = batched.model_json_schema()["properties"]["then"]
    assert props.get("maxItems") == 2
    # the batch items carry the narrowed kind set too
    item = batched.model_fields["then"].annotation.__args__[0]
    with pytest.raises(ValidationError):
        item(kind="hover", index=1)
    assert AgentDecision.model_validate(
        batched(reasoning="r", kind="fill", index=0, text="x", then=[item(kind="click", index=1)]).model_dump()
    ).then[0].kind == "click"


def test_prompt_mentions_batching_only_when_enabled():
    single = build_system_prompt(DEFAULT_KINDS, 1)
    assert "BATCHING" not in single and "exactly ONE" in single
    batched = build_system_prompt(DEFAULT_KINDS, 4)
    assert "BATCHING" in batched and "up to 3 more actions" in batched and "- then:" in batched
