"""Variation planning for `--runs N`: one LLM call → N same-family tasks with proposed
param values, normalized in code (base first, consistent names, pinned values, padding)."""

import asyncio

import pytest

from netgent.agent import FakeLLM
from netgent.agent.planner import (
    TaskVariation,
    VariationPlan,
    build_variations_content,
    normalize_variation_plan,
)

pytest.importorskip("langgraph")

from netgent.agent.planner.graph import VARIATION_PLANNER, create_variation_planner, plan_variations  # noqa: E402

BASE = "Go to YouTube and watch a video for 5 seconds"
DRAFT = VariationPlan(
    variations=[
        TaskVariation(task_text="Go to YouTube and watch a lofi video for 5 seconds",
                      values={"video_query": "lofi", "watch_time": 5}),
        TaskVariation(task_text="Go to YouTube and watch a cat video for 10 seconds",
                      values={"video_query": "cat video", "watch_time": 10}),
        TaskVariation(task_text="Go to YouTube and watch a news video for 7 seconds",
                      values={"video_query": "news", "watch_time": 7}),
    ],
)


def test_variation_planner_is_one_compiled_graph():
    mermaid = VARIATION_PLANNER.get_graph().draw_mermaid()
    assert VARIATION_PLANNER.name == "variation_planner"
    assert "__start__ --> draft_variations;" in mermaid and "draft_variations --> __end__;" in mermaid
    assert create_variation_planner().get_graph().draw_mermaid() == mermaid


def test_prompt_layout_carries_task_count_and_pinned():
    [block] = build_variations_content(BASE, 3, "https://youtube.com", {"watch_time": "9"})
    assert f"TASK: {BASE}" in block["text"] and "N: 3" in block["text"]
    assert "watch_time = '9'" in block["text"]
    assert "PINNED" not in build_variations_content(BASE, 2)[0]["text"]


def test_values_coerce_to_strings():
    assert DRAFT.variations[0].values == {"video_query": "lofi", "watch_time": "5"}


def test_normalize_keeps_base_task_verbatim_and_run1_values():
    plan = normalize_variation_plan(DRAFT, BASE, 3)
    assert len(plan.variations) == 3
    assert plan.variations[0].task_text == BASE  # run 1 IS the asked task
    assert plan.variations[0].values == {"video_query": "lofi", "watch_time": "5"}
    assert plan.variations[1].values["watch_time"] == "10"


def test_normalize_pads_with_the_base_and_notes_it():
    short = VariationPlan(variations=[DRAFT.variations[0]])
    plan = normalize_variation_plan(short, BASE, 3)
    assert len(plan.variations) == 3
    assert plan.variations[2].task_text == BASE
    assert any("repeating the base task" in n for n in plan.notes)


def test_normalize_drops_names_missing_from_the_base_and_fills_gaps():
    draft = VariationPlan(
        variations=[
            TaskVariation(task_text="a", values={"q": "x"}),
            TaskVariation(task_text="b", values={"speed": "2"}),  # not a base name -> dropped
        ]
    )
    plan = normalize_variation_plan(draft, "a", 2)
    assert plan.variations[1].values == {"q": "x"}  # gap filled from the base
    assert any("dropped value name" in n for n in plan.notes)


def test_normalize_pins_values_onto_variation_two():
    plan = normalize_variation_plan(DRAFT, BASE, 3, pinned={"watch_time": "42"})
    assert plan.variations[1].values["watch_time"] == "42"
    assert "42" in plan.variations[1].task_text  # written in so the explorer can use it
    assert plan.variations[0].values["watch_time"] == "5"  # base untouched


def test_graph_runs_through_the_llm_seam():
    llm = FakeLLM([], verdicts=[DRAFT])
    plan = asyncio.run(plan_variations(BASE, llm=llm, n=3, url="https://youtube.com"))
    assert [v.values["watch_time"] for v in plan.variations] == ["5", "10", "7"]
    assert plan.variations[0].task_text == BASE
    assert "N: 3" in llm.judged[0][0]["text"]
    with pytest.raises(ValueError, match="n must be"):
        asyncio.run(plan_variations(BASE, llm=llm, n=0))
