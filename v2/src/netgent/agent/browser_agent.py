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
from netgent.schema.actions import Action, GotoAction, WaitAction

logger = get_logger(__name__)

MAX_REPEAT = 3  # identical (kind,index) decisions in a row → declare stuck


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
        self._llm = llm
        self._max_steps = max_steps
        self._run_dir = run_dir
        # File the agent offers to any file input via kind="upload". A default sample is
        # created on demand so uploads work autonomously without the caller supplying one.
        self._upload_file = upload_file
        # Persists across run() calls, so ONE agent can work several tasks (e.g. every form
        # in a sweep) with continuous memory — what worked on an earlier task informs the next.
        self._history: list[str] = []

    def note(self, text: str) -> None:
        """Append a marker to the agent's memory (e.g. 'moving on to form 3 of 21')."""
        self._history.append(text)

    def _upload_path(self) -> str:
        if self._upload_file is None:
            sample = Path(tempfile.gettempdir()) / "netgent-upload-sample.txt"
            if not sample.exists():
                sample.write_text("netgent sample upload\n")
            self._upload_file = sample
        return str(self._upload_file)

    async def run(
        self,
        session: BrowserSession,
        task: str,
        url: str | None = None,
        frame_filter: list[str] | None = None,
        max_steps: int | None = None,
    ) -> AgentTrajectory:
        traj = AgentTrajectory(task=task)
        if url:
            await session.page.goto(url)
            # Record the starting navigation as a real step, so a compiled workflow
            # begins with this goto instead of assuming an already-open page.
            traj.steps.append(
                AgentStep(
                    n=0,
                    kind="goto",
                    reasoning="starting URL",
                    url=session.page.url,
                    action=GotoAction(url=url),
                )
            )

        history = self._history  # instance-level: memory carries across run() calls
        prev_observation: str | None = None
        no_progress = 0

        for n in range(1, (max_steps or self._max_steps) + 1):
            snapshot = await session.snapshot()
            if frame_filter is not None:  # focus on one form (iframe) for a sweep
                snapshot = snapshot.scoped_to(frame_filter)
            observation = format_observation(snapshot)

            # Stuck detection is observation-based: an action that changes nothing (a failed
            # fill, a scroll at the bottom, re-doing a done step) makes no progress. A scroll
            # that reveals a new batch DOES change the observation, so paging isn't penalized.
            if prev_observation is not None:
                no_progress = no_progress + 1 if observation == prev_observation else 0
            if no_progress >= MAX_REPEAT:
                reason = f"stuck: {MAX_REPEAT} steps with no change on screen"
                traj.stopped_reason = reason
                traj.steps.append(AgentStep(n=n, kind="stop", reasoning=reason, url=snapshot.url, error=reason))
                break
            prev_observation = observation

            try:
                decision = await self._llm.decide(SYSTEM_PROMPT, task, observation, history)
            except Exception as exc:  # noqa: BLE001 — a bad LLM response shouldn't crash the run
                logger.warning("step %d: LLM decision failed: %s", n, exc)
                history.append(f"{n}. (your last response was invalid: {exc}) — return a valid decision")
                prev_observation = None  # don't count this as a no-change step
                continue
            logger.info("step %d: %s — %s", n, decision.kind, decision.reasoning)

            if decision.kind in ("done", "stop"):
                traj.success = decision.kind == "done" and decision.success
                traj.stopped_reason = decision.reasoning
                traj.steps.append(self._step(n, decision, snapshot.url))
                break

            error = None
            action = None
            try:
                upload = self._upload_path() if decision.kind == "upload" else None
                action = to_action(decision, snapshot, upload_path=upload)
                await session.dispatch(action)
            except (ExecutionError, ValueError) as exc:
                error = str(exc)
                logger.warning("step %d failed: %s", n, error)

            step = self._step(n, decision, session.page.url, error=error)
            if error is None:
                step.action = action  # the compilable record of what actually ran
            if self._run_dir is not None:
                rel = f"screenshots/step-{n:02d}.png"
                try:
                    await session.screenshot(self._run_dir / rel)
                    step.screenshot = rel
                except Exception:  # noqa: BLE001 — a screenshot must never fail the run
                    pass
            traj.steps.append(step)
            # Feed failures back so the agent can recover instead of repeating them.
            outcome = f" -> FAILED: {error}" if error else ""
            if error is None and isinstance(action, WaitAction):
                outcome = f" -> DONE WAITING: you already watched/waited {action.seconds:g}s. Do NOT wait again."
            history.append(f"{n}. {decision.kind}({decision.index}) {decision.reasoning}{outcome}")
        else:
            traj.stopped_reason = f"reached max_steps={max_steps or self._max_steps}"

        if self._run_dir is not None:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            (self._run_dir / "trajectory.json").write_text(traj.model_dump_json(indent=2) + "\n")
        return traj

    @staticmethod
    def _step(n: int, decision: AgentDecision, url: str, error: str | None = None) -> AgentStep:
        return AgentStep(n=n, kind=decision.kind, reasoning=decision.reasoning, url=url, error=error)
