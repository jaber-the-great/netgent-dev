"""Planner — decomposes a task into ordered sub-goals for the explorer (compile-time only).

docs/OVERVIEW.md gives the Planner two jobs — cold-start hypothesis generator / fleet
orchestrator, and runtime emitter of the control sequence. This package is the first: one LLM
call that turns a task (+ start URL) into a `Plan` of explorer-sized steps, each
with the page outcome that proves it done. It is not yet wired into the orchestrator.

Same layout as the explorer: `models.py` (Plan, PlanStep), `prompt.py` (PLANNER_SYSTEM,
build_planner_content), `context.py` (PlannerContext, passed as LangGraph `Runtime.context`),
`agent.py` (`PlannerAgent`, a thin façade), `graph.py` (the `draft` node,
`create_planner_agent()`, the module-level `PLANNER`, and `plan()` — the one run API).
`plan`, `PLANNER` and `create_planner_agent` import langgraph and are resolved lazily.
"""

from netgent.agent.planner.agent import PlannerAgent
from netgent.agent.planner.context import MAX_PLAN_STEPS, PlannerContext
from netgent.agent.planner.models import (
    NextRoundPlan,
    Plan,
    PlanStep,
    ScopedSubtask,
    TaskVariation,
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

__all__ = [
    "MAX_PLAN_STEPS",
    "NEXT_ROUND_PLANNER",
    "NEXT_ROUND_SYSTEM",
    "NextRoundPlan",
    "PLANNER",
    "PLANNER_SYSTEM",
    "VARIATIONS_SYSTEM",
    "VARIATION_PLANNER",
    "Plan",
    "PlanStep",
    "PlannerAgent",
    "PlannerContext",
    "ScopedSubtask",
    "TaskVariation",
    "VariationPlan",
    "build_next_round_content",
    "build_planner_content",
    "build_variations_content",
    "create_next_round_planner",
    "create_planner_agent",
    "create_variation_planner",
    "normalize_next_round_plan",
    "normalize_variation_plan",
    "plan",
    "plan_next",
    "plan_variations",
]

_LAZY = {
    "NEXT_ROUND_PLANNER", "PLANNER", "VARIATION_PLANNER", "create_next_round_planner", "create_planner_agent",
    "create_variation_planner", "plan", "plan_next", "plan_variations",
}


def __getattr__(name: str):  # PEP 562: the graph module imports langgraph
    if name in _LAZY:
        from netgent.agent.planner import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
