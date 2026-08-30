"""`ExplorerAgent` — a thin façade over the compiled explorer graph, the way browser-use's
`Agent` wraps its loop.

It holds the per-agent knobs and ONE `ExplorerMemory`, so an agent reused across several
tasks (every form in a sweep) keeps continuous cross-task memory. `run()` builds nothing and
loops nothing: it hands the knobs to `graph.explore()`, which invokes the module-level
`EXPLORER` with the run's dependencies as `Runtime.context`. The loop itself — observe →
decide → act — lives in `graph.py`; the values it produces in `models.py`.

This is also the seed of compile-time Discovery — a completed trajectory is what the
Workflow Generator compiles into an NFA. CAPTCHA solving is out of scope: the prompt
instructs the model to return done(success=false), and nothing here attempts a challenge.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.decision import DEFAULT_KINDS
from netgent.agent.explorer.memory import ExplorerMemory
from netgent.agent.explorer.models import AgentTrajectory, StepRecord
from netgent.browser.session import BrowserSession

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


class ExplorerAgent:
    def __init__(
        self,
        llm: "LLM",
        *,
        max_steps: int = 25,
        run_dir: Path | None = None,
        allowed_kinds: frozenset[str] | set[str] = DEFAULT_KINDS,
        max_actions_per_step: int = 1,
        upload_file: Path | None = None,
        memory: ExplorerMemory | None = None,
    ):
        self.llm = llm
        self.max_steps = max_steps
        self.run_dir = run_dir
        self.allowed_kinds = frozenset(allowed_kinds)
        self.max_actions_per_step = max_actions_per_step
        self.upload_file = upload_file
        # Persists across run() calls: what worked on an earlier task informs the next.
        self.memory = memory if memory is not None else ExplorerMemory()
        # Validate the knobs now, the way a run would (ExplorerContext owns the rules).
        self._context(session=None, task="", frame_filter=None, max_steps=max_steps)  # type: ignore[arg-type]

    @property
    def history(self) -> list[StepRecord]:
        return self.memory.history

    def note(self, text: str) -> None:
        """A marker between tasks (e.g. 'moving on to form 3 of 21'); see ExplorerMemory.note."""
        self.memory.note(text)

    def _context(
        self, session: BrowserSession, task: str, frame_filter: list[str] | None, max_steps: int
    ) -> ExplorerContext:
        return ExplorerContext(
            session=session, llm=self.llm, memory=self.memory, task=task, max_steps=max_steps,
            frame_filter=frame_filter, allowed_kinds=self.allowed_kinds,
            max_actions_per_step=self.max_actions_per_step, run_dir=self.run_dir, upload_file=self.upload_file,
        )

    async def run(
        self,
        session: BrowserSession,
        task: str,
        url: str | None = None,
        frame_filter: list[str] | None = None,
        max_steps: int | None = None,
    ) -> AgentTrajectory:
        """Explore `task` on `session` (optionally starting at `url`), one atomic action per
        step, with this agent's memory. `max_steps` overrides the agent's budget for this run."""
        from netgent.agent.explorer.graph import explore  # lazy: langgraph is in the `generate` extra

        return await explore(
            session, task, llm=self.llm, memory=self.memory, url=url, frame_filter=frame_filter,
            max_steps=max_steps or self.max_steps, run_dir=self.run_dir, allowed_kinds=self.allowed_kinds,
            max_actions_per_step=self.max_actions_per_step, upload_file=self.upload_file,
        )
