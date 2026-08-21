"""The browser agent: observe → decide → act, until done or stuck.

An LLM-driven loop over a stealth BrowserSession, run as a LangGraph StateGraph
(`agent/graph.py`). Each step it snapshots the interactive DOM, asks the LLM for one atomic
action, resolves it to a durable locator and dispatches it, and records a trajectory step.
Long-horizon safety: a step cap and observation-based stuck detection.

This is also the seed of compile-time Discovery — a completed agent trajectory is what the
Workflow Generator compiles into an NFA. CAPTCHA solving is out of scope: the prompt
instructs the model to stop, and nothing here attempts a challenge.
"""

import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from netgent.agent.llm import LLM
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.schema.actions import Action, GotoAction

logger = get_logger(__name__)

MAX_REPEAT = 3  # consecutive steps with an unchanged observation → declare stuck


class AgentStep(BaseModel):
    n: int
    kind: str
    reasoning: str
    url: str
    screenshot: str | None = None
    error: str | None = None
    # The resolved, durable-locator action that was dispatched (None for done/stop or
    # failed steps). This is what `netgent generate` compiles into a workflow transition.
    action: Action | None = None


class AgentTrajectory(BaseModel):
    task: str
    success: bool = False
    stopped_reason: str = ""
    steps: list[AgentStep] = Field(default_factory=list)


class BrowserAgent:
    def __init__(self, llm: LLM, max_steps: int = 25, run_dir: Path | None = None, upload_file: Path | None = None):
        self.llm = llm
        self._max_steps = max_steps
        self._run_dir = run_dir
        # File the agent offers to any file input via kind="upload". A default sample is
        # created on demand so uploads work autonomously without the caller supplying one.
        self._upload_file = upload_file
        # Persists across run() calls, so ONE agent can work several tasks (e.g. every form
        # in a sweep) with continuous memory — what worked on an earlier task informs the next.
        self.history: list[str] = []

    def note(self, text: str) -> None:
        """Append a marker to the agent's memory (e.g. 'moving on to form 3 of 21')."""
        self.history.append(text)

    def upload_path(self) -> str:
        if self._upload_file is None:
            sample = Path(tempfile.gettempdir()) / "netgent-upload-sample.txt"
            if not sample.exists():
                sample.write_text("netgent sample upload\n")
            self._upload_file = sample
        return str(self._upload_file)

    async def capture_screenshot(self, session: BrowserSession, step: AgentStep) -> None:
        """Best-effort per-step screenshot into the run dir (never fails the run)."""
        if self._run_dir is None:
            return
        rel = f"screenshots/step-{step.n:02d}.png"
        try:
            await session.screenshot(self._run_dir / rel)
            step.screenshot = rel
        except Exception:  # noqa: BLE001 — a screenshot must never fail the run
            pass

    async def run(
        self,
        session: BrowserSession,
        task: str,
        url: str | None = None,
        frame_filter: list[str] | None = None,
        max_steps: int | None = None,
    ) -> AgentTrajectory:
        from netgent.agent.explore_agent.graph import build_agent_graph  # lazy: langgraph is in the `generate` extra

        traj = AgentTrajectory(task=task)
        if url:
            await session.page.goto(url)
            # Record the starting navigation as a real step, so a compiled workflow
            # begins with this goto instead of assuming an already-open page.
            traj.steps.append(
                AgentStep(n=0, kind="goto", reasoning="starting URL", url=session.page.url, action=GotoAction(url=url))
            )

        budget = max_steps or self._max_steps
        graph = build_agent_graph(self, session, task, frame_filter=frame_filter, max_steps=budget)
        # Each loop iteration is up to three graph steps (observe, decide, act); the
        # recursion limit is a backstop above the agent's own step budget, never the cap.
        final = await graph.ainvoke({"steps": []}, config={"recursion_limit": 3 * budget + 8})

        traj.steps.extend(final.get("steps", []))
        traj.success = bool(final.get("success", False))
        traj.stopped_reason = final.get("stopped_reason", "")

        if self._run_dir is not None:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            (self._run_dir / "trajectory.json").write_text(traj.model_dump_json(indent=2) + "\n")
        return traj
