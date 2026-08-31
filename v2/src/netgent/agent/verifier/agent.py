"""`VerifierAgent` — a thin façade over the compiled verifier graph, the explorer's shape
(`explorer/agent.py`). Holds the per-agent knobs (the LLM, where the screenshots are, how
many to show); `run()` delegates to `graph.verify()`, which invokes the module-level
`VERIFIER` with a VerifierContext. No judging logic here."""

from pathlib import Path
from typing import TYPE_CHECKING

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.verifier.context import VerifierContext
from netgent.agent.verifier.models import MAX_SCREENSHOTS, Verdict

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


class VerifierAgent:
    def __init__(self, llm: "LLM", *, run_dir: Path | None = None, max_screenshots: int = MAX_SCREENSHOTS):
        self.llm = llm
        self.run_dir = run_dir
        self.max_screenshots = max_screenshots
        VerifierContext(llm=llm, run_dir=run_dir, max_screenshots=max_screenshots)  # validate the knobs now

    async def run(self, traj: AgentTrajectory, task: str, params: dict[str, str] | None = None) -> Verdict:
        """Judge `traj` against `task` from page evidence (never the explorer's reasoning)."""
        from netgent.agent.verifier.graph import verify  # lazy: langgraph is in the `generate` extra

        return await verify(
            traj, task, llm=self.llm, params=params, run_dir=self.run_dir, max_screenshots=self.max_screenshots
        )
