"""The planner as LangGraph sees it — the explorer's shape: one compiled module-level graph, its
rendered structure, the prompt layout, and a run with no key through the FakeLLM seam."""

import asyncio

import pytest

from netgent.agent import FakeLLM
from netgent.agent.planner import Plan, PlannerAgent, PlannerContext, PlanStep, build_planner_content

pytest.importorskip("langgraph")

from netgent.agent.planner.graph import PLANNER, create_planner_agent, plan  # noqa: E402

PLAN = Plan(
    goal="the form is submitted",
    steps=[PlanStep(description="fill the form", expected_outcome="all fields hold values"),
           PlanStep(description="submit it", expected_outcome="a confirmation message")],
    notes=["the date format is unknown"],
)


def test_planner_is_one_compiled_graph():
    mermaid = PLANNER.get_graph().draw_mermaid()
    assert PLANNER.name == "planner"
    assert "__start__ --> draft;" in mermaid and "draft --> __end__;" in mermaid
    assert create_planner_agent().get_graph().draw_mermaid() == mermaid


def test_prompt_layout_carries_task_and_url():
    [block] = build_planner_content("book a room", "https://x")
    assert block["text"] == "TASK: book a room\nSTART URL: https://x\n\nPlan:"
    assert "START URL: (none)" in build_planner_content("t")[0]["text"]


def test_graph_runs_through_the_llm_seam_and_caps_the_steps():
    llm = FakeLLM([], verdicts=[PLAN])
    out = asyncio.run(plan("submit the form", llm=llm, max_steps=1))
    assert out.goal == PLAN.goal and len(out.steps) == 1 and out.notes == PLAN.notes
    assert out.as_tasks() == ["fill the form Done when: all fields hold values"]
    assert "TASK: submit the form" in llm.judged[0][0]["text"]
    with pytest.raises(ValueError, match="max_steps"):
        PlannerContext(llm=llm, max_steps=0)


def test_agent_facade_delegates_to_plan():
    out = asyncio.run(PlannerAgent(FakeLLM([], verdicts=[PLAN])).run("submit the form"))
    assert [s.description for s in out.steps] == ["fill the form", "submit it"]
    with pytest.raises(ValueError, match="max_steps"):
        PlannerAgent(FakeLLM([]), max_steps=0)
