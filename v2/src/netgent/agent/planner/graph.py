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
from netgent.agent.planner.models import (
    NextRoundPlan,
    Plan,
    VariationPlan,
    normalize_next_round_plan,
    normalize_variation_plan,
)
from netgent.agent.planner.prompt import (
    NEXT_ROUND_SYSTEM,
    PLANNER_SYSTEM,
    VARIATIONS_SYSTEM,
    build_next_round_content,
    build_planner_content,
    build_variations_content,
)

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


class VariationState(TypedDict, total=False):
    task: str
    url: str | None
    n: int
    pinned: dict[str, str]
    plan: Any  # VariationPlan (draft_variations' output)


async def draft_variations(state: VariationState, runtime: Runtime[PlannerContext]) -> dict:
    """Task → N same-family variations with proposed param values: the one LLM call,
    normalized in code (exactly N, base first, consistent names, pinned values applied)."""
    ctx = runtime.context
    content = build_variations_content(state["task"], state["n"], state.get("url"), state.get("pinned"))
    plan: VariationPlan = await ctx.llm.judge(VARIATIONS_SYSTEM, content, VariationPlan)
    if not plan.variations and state["n"] > 1:
        # An empty plan is a wasted round (three identical runs infer nothing): ask once more,
        # naming the shape — measured on the claude-code route, where an enveloped answer
        # validated as a plan with no variations.
        retry = [*content, {"type": "text", "text": f"\nYour previous answer contained no variations. Return exactly "
                                                     f"{state['n']} variations, each with task_text and values."}]
        plan = await ctx.llm.judge(VARIATIONS_SYSTEM, retry, VariationPlan)
    return {"plan": normalize_variation_plan(plan, state["task"], state["n"], state.get("pinned"))}


def create_variation_planner() -> CompiledStateGraph:
    """Build and compile the variation-planner graph. Same shape as `create_planner_agent`."""
    return (
        StateGraph(VariationState, context_schema=PlannerContext)
        .add_node("draft_variations", draft_variations)
        .add_edge(START, "draft_variations")
        .add_edge("draft_variations", END)
        .compile(name="variation_planner")
    )


VARIATION_PLANNER = create_variation_planner()  # compiled ONCE


async def plan_variations(
    task: str,
    *,
    llm: "LLM",
    n: int,
    url: str | None = None,
    pinned: dict[str, str] | None = None,
    graph: CompiledStateGraph | None = None,
) -> VariationPlan:
    """The ONE run API for `--runs N`: N same-family task variations, each carrying its
    intended concrete values under proposed param names. `graph` defaults to VARIATION_PLANNER."""
    if n < 1:
        raise ValueError("n must be >= 1")
    graph = VARIATION_PLANNER if graph is None else graph
    final = await graph.ainvoke(
        {"task": task, "url": url, "n": n, "pinned": dict(pinned or {})}, context=PlannerContext(llm=llm)
    )
    return final["plan"]


class NextRoundState(TypedDict, total=False):
    context: Any  # RoundContext (agent/rounds.py)
    plan: Any  # NextRoundPlan (draft_next_round's output)


async def draft_next_round(state: NextRoundState, runtime: Runtime[PlannerContext]) -> dict:
    """RoundContext → NextRoundPlan: the ONE LLM call of the closed loop's planner, normalized
    in code (≤ N runs, canonical names, values verbatim, hints on existing columns)."""
    ctx = runtime.context
    rc = state["context"]
    plan: NextRoundPlan = await ctx.llm.judge(NEXT_ROUND_SYSTEM, build_next_round_content(rc), NextRoundPlan)
    return {"plan": normalize_next_round_plan(
        plan, n=rc.runs_per_round, canonical_names=rc.canonical_names, base_values=rc.base_values,
        columns=[c.index for c in rc.latest_columns()],
    )}


def create_next_round_planner() -> CompiledStateGraph:
    """Build and compile the next-round planner graph. Same shape as `create_planner_agent`."""
    return (
        StateGraph(NextRoundState, context_schema=PlannerContext)
        .add_node("draft_next_round", draft_next_round)
        .add_edge(START, "draft_next_round")
        .add_edge("draft_next_round", END)
        .compile(name="next_round_planner")
    )


NEXT_ROUND_PLANNER = create_next_round_planner()  # compiled ONCE


async def plan_next(context, *, llm: "LLM", graph: CompiledStateGraph | None = None) -> NextRoundPlan:
    """The ONE run API for round ≥ 2: the accumulated RoundContext in, the next round's
    variations / scoped sub-tasks / generalization hints out. `graph` defaults to NEXT_ROUND_PLANNER."""
    graph = NEXT_ROUND_PLANNER if graph is None else graph
    final = await graph.ainvoke({"context": context}, context=PlannerContext(llm=llm))
    return final["plan"]
