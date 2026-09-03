"""`GeneratorAgent` — a thin façade over the compiled generator graph, the verifier's shape
(`verifier/agent.py`). Holds the per-agent knobs (the LLM, the repair budget); `run()` delegates
to `graph.generate()`, which invokes the module-level `GENERATOR` with a GeneratorContext. No
drafting or resolving logic here."""

from typing import TYPE_CHECKING

from netgent.agent.generator.context import MAX_REPAIRS
from netgent.agent.generator.models import GenerateOutcome

if TYPE_CHECKING:
    from netgent.agent.generator.merge import GeneralizedTrajectory, RunInput
    from netgent.agent.llm import LLM
    from netgent.schema.workflow import Workflow


class GeneratorAgent:
    def __init__(self, llm: "LLM | None", *, max_repairs: int = MAX_REPAIRS):
        if max_repairs < 0:
            raise ValueError("max_repairs must be >= 0")
        self.llm = llm
        self.max_repairs = max_repairs

    async def run(self, task: str, runs: list["RunInput"], generalized: "GeneralizedTrajectory",
                  fallback: "Workflow", **kw) -> GenerateOutcome:
        """Draft the artifact from the recordings on the merge's alignment; fall back to the merge's."""
        from netgent.agent.generator.graph import generate  # lazy: langgraph is in the `generate` extra

        return await generate(task=task, runs=runs, generalized=generalized, fallback=fallback, llm=self.llm,
                              max_repairs=self.max_repairs, **kw)
