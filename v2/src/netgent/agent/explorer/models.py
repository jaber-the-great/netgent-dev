"""The explorer's values: what it remembers (StepRecord), what it records (AgentStep), and
what a run returns (AgentTrajectory). Pydantic, so they round-trip through a LangGraph
checkpoint serializer (measured, docs/research/langgraph-agent-structure.md §3a) and the
generator/verifier can read them without importing the agent."""

from typing import Literal

from pydantic import BaseModel, Field

from netgent.schema.actions import Action, LocatorStep


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
    # The candidate ladder the browser layer computed for the acted element, as the live page
    # resolved it at capture time (browser/locators.py::probe_ladder) — M0 of the generator
    # agent design (docs/research/generator-agent.md §C.2.1). Every rung, not just the one the
    # action kept, so a later compile can choose a different rung (the positional one) and
    # check it against the recording without re-exploring. Parallel lists, one entry per rung:
    # the chain, its kind (id/role/test_id/label/css/structural), how many elements it
    # resolved to (-1: unresolvable), and the acted element's index among its matches where
    # that was computed. Compile-time provenance; never replayed. Empty for page-level actions.
    locator_candidates: list[list[LocatorStep]] = Field(default_factory=list)
    candidate_kinds: list[str] = Field(default_factory=list)
    match_counts: list[int] = Field(default_factory=list)
    match_indices: list[int | None] = Field(default_factory=list)
    # The acted DomElement's identity (tag, role, name, type, frame_path) — the zero-LLM
    # signal browser-use's variable detector keys on; a check on a param claim, never a proposer.
    element: dict = Field(default_factory=dict)
    # The model's working memory at this step (AgentDecision fields), kept as provenance so
    # a bad compile can be read back; the compiler ignores them.
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""
    # Playback state observed just BEFORE this step ran ("video PLAYING at 0:21 / 8:35"),
    # from the step's own snapshot. Objective page evidence (not the model's narration), so
    # the verifier can check timed watch/pause/seek phases from consecutive readings.
    media: str | None = None
    # Wall-clock (epoch seconds) when the step record was made. With `media`, this is what
    # lets a verifier tell a seek jump from natural playback: position advancing MORE than
    # the wall-clock between readings is a jump; advancing less is buffering/stall.
    t: float | None = None


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
