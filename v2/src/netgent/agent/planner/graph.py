"""The planner as a LangGraph StateGraph — functions + ONE compiled graph, the explorer's shape.

    START → draft → END

`draft` is the one LLM call: task (+ url) in, Plan out, through the agent's LLM seam.
`PLANNER` is compiled once at import; the LLM travels as `Runtime.context` (a PlannerContext).
`plan()` is the one run API. The planner is not yet wired into the orchestrator: it is the
cold-start hypothesis generator of docs/OVERVIEW.md ("The Planner's two jobs"), and how its
plan feeds the explorer fleet is an open design question there.

This module imports langgraph at module level; `netgent.agent.planner` resolves it lazily.
"""

from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from netgent.agent.planner.context import PlannerContext
from netgent.agent.planner.models import Plan
from netgent.agent.planner.prompt import PLANNER_SYSTEM, build_planner_content

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


class PlannerState(TypedDict, total=False):
    task: str
    url: str | None
    plan: Any  # Plan (draft's output)


async def draft(state: PlannerState, runtime: Runtime[PlannerContext]) -> dict:
    """Task → Plan: the one LLM call, bounded to the context's max_steps."""
    ctx = runtime.context
    content = build_planner_content(state["task"], state.get("url"))
    plan: Plan = await ctx.llm.judge(PLANNER_SYSTEM, content, Plan)
    if len(plan.steps) > ctx.max_steps:
        plan = plan.model_copy(update={"steps": plan.steps[: ctx.max_steps]})
    return {"plan": plan}


def create_planner_agent() -> CompiledStateGraph:
    """Build and compile the planner graph. Same shape as `create_explorer_agent`."""
    return (
        StateGraph(PlannerState, context_schema=PlannerContext)
        .add_node("draft", draft)
        .add_edge(START, "draft")
        .add_edge("draft", END)
        .compile(name="planner")
    )


PLANNER = create_planner_agent()  # compiled ONCE


async def plan(
    task: str,
    *,
    llm: "LLM",
    url: str | None = None,
    max_steps: int | None = None,
    graph: CompiledStateGraph | None = None,
) -> Plan:
    """The ONE run API: decompose `task` into a Plan. `graph` defaults to PLANNER."""
    graph = PLANNER if graph is None else graph
    ctx = PlannerContext(llm=llm) if max_steps is None else PlannerContext(llm=llm, max_steps=max_steps)
    final = await graph.ainvoke({"task": task, "url": url}, context=ctx)
    return final["plan"]
