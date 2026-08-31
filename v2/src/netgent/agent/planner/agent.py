"""`PlannerAgent` — a thin façade over the compiled planner graph (the explorer's shape).
Holds the LLM and the step cap; `run()` delegates to `graph.plan()`."""

from typing import TYPE_CHECKING

from netgent.agent.planner.context import MAX_PLAN_STEPS, PlannerContext
from netgent.agent.planner.models import Plan, VariationPlan

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


class PlannerAgent:
    def __init__(self, llm: "LLM", *, max_steps: int = MAX_PLAN_STEPS):
        self.llm = llm
        self.max_steps = max_steps
        PlannerContext(llm=llm, max_steps=max_steps)  # validate the knobs now

    async def run(self, task: str, url: str | None = None) -> Plan:
        """Decompose `task` into ordered sub-goals for the explorer."""
        from netgent.agent.planner.graph import plan  # lazy: langgraph is in the `generate` extra

        return await plan(task, llm=self.llm, url=url, max_steps=self.max_steps)

    async def variations(
        self, task: str, n: int, url: str | None = None, pinned: dict[str, str] | None = None
    ) -> VariationPlan:
        """N same-family variations of `task` for multi-run exploration (`--runs N`)."""
        from netgent.agent.planner.graph import plan_variations  # lazy: langgraph

        return await plan_variations(task, llm=self.llm, n=n, url=url, pinned=pinned)
