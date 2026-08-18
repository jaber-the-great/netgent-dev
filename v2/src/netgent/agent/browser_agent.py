"""The browser agent: observe → decide → act, until done or stuck.

An LLM-driven loop over a stealth BrowserSession. Each step it snapshots the interactive DOM,
asks the LLM for one atomic action, resolves it to a durable locator and dispatches it, and
records a trajectory step. Long-horizon safety: a step cap and repeat-action loop detection.

This is also the seed of compile-time Discovery — a completed agent trajectory is what the
Workflow Generator will later compile into an NFA. CAPTCHA solving is out of scope: the prompt
instructs the model to stop, and nothing here attempts a challenge.
"""

import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from netgent.agent.decision import AgentDecision
from netgent.agent.llm import LLM
from netgent.agent.observation import format_observation, to_action
from netgent.agent.prompt import SYSTEM_PROMPT
from netgent.browser.session import BrowserSession
from netgent.core.errors import ExecutionError
from netgent.core.logger import get_logger

logger = get_logger(__name__)

MAX_REPEAT = 3  # identical (kind,index) decisions in a row → declare stuck


class AgentStep(BaseModel):
    n: int
    kind: str
    reasoning: str
    url: str
    screenshot: str | None = None
    error: str | None = None


class AgentTrajectory(BaseModel):
    task: str
    success: bool = False
    stopped_reason: str = ""
    steps: list[AgentStep] = Field(default_factory=list)


class BrowserAgent:
    def __init__(self, llm: LLM, max_steps: int = 25, run_dir: Path | None = None, upload_file: Path | None = None):
        self._llm = llm
        self._max_steps = max_steps
        self._run_dir = run_dir
        # File the agent offers to any file input via kind="upload". A default sample is
        # created on demand so uploads work autonomously without the caller supplying one.
        self._upload_file = upload_file

    def _upload_path(self) -> str:
        if self._upload_file is None:
            sample = Path(tempfile.gettempdir()) / "netgent-upload-sample.txt"
            if not sample.exists():
                sample.write_text("netgent sample upload\n")
            self._upload_file = sample
        return str(self._upload_file)

    async def run(self, session: BrowserSession, task: str, url: str | None = None) -> AgentTrajectory:
        traj = AgentTrajectory(task=task)
        if url:
            await session.page.goto(url)

        history: list[str] = []
        last_key: tuple[str, int | None] | None = None
        repeats = 0

        for n in range(1, self._max_steps + 1):
            snapshot = await session.snapshot()
            observation = format_observation(snapshot)
            decision = await self._llm.decide(SYSTEM_PROMPT, task, observation, history)
            logger.info("step %d: %s — %s", n, decision.kind, decision.reasoning)

            if decision.kind in ("done", "stop"):
                traj.success = decision.kind == "done" and decision.success
                traj.stopped_reason = decision.reasoning
                traj.steps.append(self._step(n, decision, snapshot.url))
                break

            key = (decision.kind, decision.index)
            repeats = repeats + 1 if key == last_key else 0
            last_key = key
            if repeats >= MAX_REPEAT:
                traj.stopped_reason = f"stuck: repeated {decision.kind} {repeats + 1}×"
                traj.steps.append(self._step(n, decision, snapshot.url, error=traj.stopped_reason))
                break

            error = None
            try:
                upload = self._upload_path() if decision.kind == "upload" else None
                action = to_action(decision, snapshot, upload_path=upload)
                await session.dispatch(action)
            except (ExecutionError, ValueError) as exc:
                error = str(exc)
                logger.warning("step %d failed: %s", n, error)

            step = self._step(n, decision, session.page.url, error=error)
            if self._run_dir is not None:
                rel = f"screenshots/step-{n:02d}.png"
                try:
                    await session.screenshot(self._run_dir / rel)
                    step.screenshot = rel
                except Exception:  # noqa: BLE001 — a screenshot must never fail the run
                    pass
            traj.steps.append(step)
            history.append(f"{n}. {decision.kind}({decision.index}) {decision.reasoning}")
        else:
            traj.stopped_reason = f"reached max_steps={self._max_steps}"

        if self._run_dir is not None:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            (self._run_dir / "trajectory.json").write_text(traj.model_dump_json(indent=2) + "\n")
        return traj

    @staticmethod
    def _step(n: int, decision: AgentDecision, url: str, error: str | None = None) -> AgentStep:
        return AgentStep(n=n, kind=decision.kind, reasoning=decision.reasoning, url=url, error=error)
