"""The browser agent: observe → decide → act, until done or stuck.

An LLM-driven loop over a BrowserSession, run as a LangGraph StateGraph
(`agent/graph.py`). Each step it snapshots the interactive DOM, asks the LLM for one atomic
action, resolves it to a durable locator and dispatches it, and records a trajectory step.
Long-horizon safety: a step cap and observation-based stuck detection.

This is also the seed of compile-time Discovery — a completed agent trajectory is what the
Workflow Generator compiles into an NFA. CAPTCHA solving is out of scope: the prompt
instructs the model to return done(success=false), and nothing here attempts a challenge.
"""

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from netgent.agent.explorer.decision import ALL_KINDS, DEFAULT_KINDS, MAX_BATCH
from netgent.agent.explorer.memory import FOLD_MIN_STEPS, MAX_FOLDS, ExplorerMemory  # noqa: F401 — re-exported
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.schema.actions import Action

if TYPE_CHECKING:  # llm.py imports StepRecord from here; keep the cycle type-only
    from netgent.agent.explorer.context import ExplorerContext
    from netgent.agent.llm import LLM

logger = get_logger(__name__)

MAX_REPEAT = 3  # consecutive steps with an unchanged observation → declare stuck


class StepRecord(BaseModel):
    """One acted step, as the agent REMEMBERS it — typed, like browser-use's HistoryItem and
    Skyvern's action_history dicts (docs/research/browser-agent-memory.md §6.2a). Compile-time
    only: the generator reads AgentStep, never this. Rendered into the prompt by `to_line()` /
    `to_block()` (agent/llm.py owns the window)."""

    n: int
    kind: str  # an action kind, or "note" (a caller marker) / "fold" (a compacted task)
    index: int | None = None
    target: str = ""  # element name or tag[type] — survives index renumbering (Notte hide_interactions)
    reasoning: str = ""
    outcome: Literal["ok", "failed", "waited", "invalid"] = "ok"
    error: str | None = None
    # The model's own working memory (AgentDecision fields); empty when it gave none.
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""
    note: str | None = None  # text of a note/fold record

    def to_line(self) -> str:
        """Compact form (older steps)."""
        if self.kind in ("note", "fold"):
            return self.note or ""
        what = self.target or (str(self.index) if self.index is not None else "")
        tail = {
            "ok": "",
            "failed": f" -> FAILED: {self.error}",
            "waited": f" -> DONE WAITING: {self.error or 'the dwell is complete'}. Do NOT wait again.",
            "invalid": f" -> INVALID: {self.error}",
        }[self.outcome]
        return f"{self.n}. {self.kind}({what}) {self.reasoning}{tail}"

    def to_block(self) -> str:
        """Full form (the last few steps): the line, then the model's evaluation/memory/goal."""
        parts = []
        if self.evaluation:
            parts.append(f"   eval: {self.evaluation}")
        if self.memory:
            parts.append(f"   memory: {self.memory}")
        if self.next_goal:
            parts.append(f"   goal: {self.next_goal}")
        return "\n".join([self.to_line(), *parts])


class AgentStep(BaseModel):
    n: int  # the LLM step that produced it
    item: int = 0  # position within that step's batch (0 = the decision's own action)
    kind: str
    reasoning: str
    url: str
    screenshot: str | None = None
    # JS dialogs this step's action raised ("<type>: <message>"), auto-accepted by the
    # browser layer. Recorded so the compiler can anchor the post-step state on a dialog
    # when it is the page's only feedback (schema DialogMatches).
    dialogs: list[str] = []
    error: str | None = None
    # The resolved, durable-locator action that was dispatched (None for done or
    # failed steps). This is what `netgent generate` compiles into a workflow transition.
    action: Action | None = None
    # How the action's locator was cross-checked at capture time (R4): whether Playwright's
    # own generator agreed, and which chain was kept. Compile-time provenance, not replayed.
    locator_check: str | None = None
    # The ${param} the explorer declared this step's value came from (decision.param), so the
    # compiler binds the placeholder structurally. Compile-time provenance, not replayed.
    param: str | None = None
    # The model's working memory at this step (AgentDecision fields), kept as provenance so
    # a bad compile can be read back; the compiler ignores them.
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""


class AgentTrajectory(BaseModel):
    # Every distinct text observed during the run (in observation scope). Success banners
    # are often transient — hidden a few seconds after appearing — so verification reads
    # what was seen, not only the final page.
    # Evidence for the verifier (agent/verifier): the page as it was when the run ended.
    final_observation: str = ""
    final_url: str = ""
    dialogs: list[str] = Field(default_factory=list)

    task: str
    success: bool = False
    stopped_reason: str = ""
    texts_seen: list[str] = []
    steps: list[AgentStep] = Field(default_factory=list)


def upload_path(ctx: "ExplorerContext") -> str:
    """The file offered to a file input: the caller's, else a sample created on demand."""
    if ctx.upload_file is not None:
        return str(ctx.upload_file)
    sample = Path(tempfile.gettempdir()) / "netgent-upload-sample.txt"
    if not sample.exists():
        sample.write_text("netgent sample upload\n")
    return str(sample)


async def capture_screenshot(ctx: "ExplorerContext", step: AgentStep) -> None:
    """Best-effort per-step screenshot into the run dir (never fails the run)."""
    if ctx.run_dir is None:
        return
    rel = f"screenshots/step-{step.n:02d}{f'-{step.item}' if step.item else ''}.png"
    try:
        await ctx.session.screenshot(ctx.run_dir / rel)
        step.screenshot = rel
    except Exception:  # noqa: BLE001 — a screenshot must never fail the run
        pass


class Agent:
    def __init__(
        self,
        llm: "LLM",
        max_steps: int = 25,
        run_dir: Path | None = None,
        upload_file: Path | None = None,
        allowed_kinds: frozenset[str] | set[str] | None = None,
        max_actions_per_step: int = 1,
    ):
        self.llm = llm
        self._max_steps = max_steps
        # How many atomic actions one decision may carry (1 = today's semantics; up to
        # MAX_BATCH). Each executed item is still one AgentStep → one transition.
        if not 1 <= max_actions_per_step <= MAX_BATCH:
            raise ValueError(f"max_actions_per_step must be 1..{MAX_BATCH}")
        self.max_actions_per_step = max_actions_per_step
        # The action kinds this agent may emit. hover/press/goto are opt-in (decision.py
        # DEFAULT_KINDS); the prompt and the structured-output schema both reflect the set.
        kinds = frozenset(allowed_kinds) if allowed_kinds is not None else DEFAULT_KINDS
        unknown = kinds - ALL_KINDS
        if unknown:
            raise ValueError(f"unknown action kinds {sorted(unknown)}; choose from {sorted(ALL_KINDS)}")
        self.allowed_kinds: frozenset[str] = kinds
        self._run_dir = run_dir
        # File the agent offers to any file input via kind="upload". A default sample is
        # created on demand so uploads work autonomously without the caller supplying one.
        self._upload_file = upload_file
        # Cross-run memory (history, noticed texts) and the settle watcher: one ExplorerMemory
        # persists across run() calls, so ONE agent can work several tasks (e.g. every form in
        # a sweep) with continuous memory.
        self.memory = ExplorerMemory()

    @property
    def history(self) -> list[StepRecord]:
        return self.memory.history

    @history.setter
    def history(self, value: list[StepRecord]) -> None:  # `agent.history += [...]` keeps the shared list
        self.memory.history[:] = value

    @property
    def noticed(self) -> list[str]:
        return self.memory.noticed

    def start_watch(self, coro) -> None:
        self.memory.start_watch(coro)

    def stop_watch(self) -> None:
        self.memory.stop_watch()

    def drain_noticed(self) -> list[str]:
        return self.memory.drain_noticed()

    def note(self, text: str) -> None:
        """See ExplorerMemory.note."""
        self.memory.note(text)

    async def run(
        self,
        session: BrowserSession,
        task: str,
        url: str | None = None,
        frame_filter: list[str] | None = None,
        max_steps: int | None = None,
    ) -> AgentTrajectory:
        from netgent.agent.explorer.graph import explore  # lazy: langgraph is in the `generate` extra

        return await explore(
            session, task, llm=self.llm, memory=self.memory, url=url, frame_filter=frame_filter,
            max_steps=max_steps or self._max_steps, run_dir=self._run_dir, allowed_kinds=self.allowed_kinds,
            max_actions_per_step=self.max_actions_per_step, upload_file=self._upload_file,
        )
