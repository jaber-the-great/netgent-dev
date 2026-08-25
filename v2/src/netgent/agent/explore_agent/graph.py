"""The browser agent's loop as a LangGraph StateGraph.

    START → observe → decide → act → observe → …
                 │        │
                 │        ├─ done ──────► END
                 └─ stuck ───────────► END        (budget exhausted: observe ─► END)

Three async nodes route with `Command`, so each node both updates state and picks the next
node. The graph is rebuilt per `BrowserAgent.run()` because the nodes close over the live
session, task, and the agent's cross-run history — nothing un-serializable lives in state
that a checkpointer would need (none is attached). Semantics are exactly the former
hand-written loop: one snapshot per step, observation-based stuck detection, invalid LLM
output costs a step but never crashes, failures echoed into history, and the step budget.
"""

import operator
from typing import Annotated, Any, Literal, TypedDict

from netgent.agent.explore_agent.browser_agent import MAX_REPEAT, AgentStep, BrowserAgent
from netgent.agent.explore_agent.observation import _locator_for, format_observation, to_action, unique_locator_for
from netgent.agent.explore_agent.prompt import SYSTEM_PROMPT
from netgent.browser.session import BrowserSession
from netgent.core.errors import ExecutionError
from netgent.core.logger import get_logger
from netgent.schema.actions import WaitAction

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    n: int  # step number of the step being worked on
    snapshot: Any  # DomSnapshot for the current step
    observation: str
    prev_observation: str | None
    no_progress: int
    decision: Any  # AgentDecision for the current step
    steps: Annotated[list[AgentStep], operator.add]  # the trajectory, appended per step
    success: bool
    stopped_reason: str


def build_agent_graph(
    agent: BrowserAgent,
    session: BrowserSession,
    task: str,
    *,
    frame_filter: list[str] | None = None,
    max_steps: int,
):
    """Compile the observe→decide→act graph bound to one run's session/task/history."""
    from langgraph.graph import END, START, StateGraph  # lazy: the `generate` extra
    from langgraph.types import Command

    history = agent.history  # shared across runs (sweeps), mutated in place
    llm = agent.llm

    async def observe(state: AgentState) -> Command[Literal["decide", "__end__"]]:
        n = state.get("n", 0) + 1
        if n > max_steps:
            return Command(update={"stopped_reason": f"reached max_steps={max_steps}"}, goto=END)
        snapshot = await session.snapshot()
        if frame_filter is not None:  # focus on one form (iframe) for a sweep
            snapshot = snapshot.scoped_to(frame_filter)
        observation = format_observation(snapshot)

        # Stuck detection is observation-based: an action that changes nothing on screen
        # makes no progress; a scroll that reveals a new batch does change it.
        prev = state.get("prev_observation")
        no_progress = state.get("no_progress", 0)
        if prev is not None:
            no_progress = no_progress + 1 if observation == prev else 0
        if no_progress >= MAX_REPEAT:
            reason = f"stuck: {MAX_REPEAT} steps with no change on screen"
            stop = AgentStep(n=n, kind="done", reasoning=reason, url=snapshot.url, error=reason)
            return Command(update={"n": n, "steps": [stop], "stopped_reason": reason}, goto=END)
        return Command(
            update={
                "n": n,
                "snapshot": snapshot,
                "observation": observation,
                "prev_observation": observation,
                "no_progress": no_progress,
            },
            goto="decide",
        )

    async def decide(state: AgentState) -> Command[Literal["act", "observe", "__end__"]]:
        n = state["n"]
        try:
            decision = await llm.decide(SYSTEM_PROMPT, task, state["observation"], history)
        except Exception as exc:  # noqa: BLE001 — a bad LLM response shouldn't crash the run
            logger.warning("step %d: LLM decision failed: %s", n, exc)
            history.append(f"{n}. (your last response was invalid: {exc}) — return a valid decision")
            return Command(update={"prev_observation": None}, goto="observe")  # not a no-change step
        logger.info("step %d: %s — %s", n, decision.kind, decision.reasoning)

        if decision.kind == "done":
            step = AgentStep(n=n, kind=decision.kind, reasoning=decision.reasoning, url=state["snapshot"].url)
            return Command(
                update={
                    "steps": [step],
                    "success": decision.success,
                    "stopped_reason": decision.reasoning,
                },
                goto=END,
            )
        return Command(update={"decision": decision}, goto="act")

    async def act(state: AgentState) -> Command[Literal["observe"]]:
        n, decision, snapshot = state["n"], state["decision"], state["snapshot"]
        error = None
        action = None
        try:
            upload = agent.upload_path() if decision.kind == "upload" else None
            locator_for = await _verified_locator(session, snapshot, decision.index)
            action = to_action(decision, snapshot, upload_path=upload, locator_for=locator_for)
            await session.dispatch(action)
        except (ExecutionError, ValueError) as exc:
            error = str(exc)
            logger.warning("step %d failed: %s", n, error)

        step = AgentStep(n=n, kind=decision.kind, reasoning=decision.reasoning, url=session.page.url, error=error)
        if error is None:
            step.action = action  # the compilable record of what actually ran
        await agent.capture_screenshot(session, step)
        # Feed outcomes back so the agent recovers instead of repeating itself.
        outcome = f" -> FAILED: {error}" if error else ""
        if error is None and isinstance(action, WaitAction):
            outcome = f" -> DONE WAITING: you already watched/waited {action.seconds:g}s. Do NOT wait again."
        history.append(f"{n}. {decision.kind}({decision.index}) {decision.reasoning}{outcome}")
        return Command(update={"steps": [step]}, goto="observe")

    return (
        StateGraph(AgentState)
        .add_node("observe", observe)
        .add_node("decide", decide)
        .add_node("act", act)
        .add_edge(START, "observe")
        .compile()
    )


async def _verified_locator(session: BrowserSession, snapshot, index: int | None):
    """A locator builder for the chosen element, verified unique against the live page.

    Resolution is async (it counts matches in the browser) while `to_action` is pure, so
    the chain is built here and handed in. Any failure falls back to the unverified chain.
    """
    elems = snapshot.interactive()
    if index is None or not (0 <= index < len(elems)):
        return _locator_for
    try:
        chain = await unique_locator_for(session, elems[index])
    except Exception as exc:  # noqa: BLE001 — verification is best-effort; dispatch fails loudly
        logger.warning("locator verification failed for element %d: %s", index, exc)
        return _locator_for
    return lambda _el: chain


def agent_graph_mermaid() -> str:
    """The loop's structure as a Mermaid diagram (for docs / `netgent agent --graph`)."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    # Structure only: bind no-op nodes with the real routing annotations.
    async def observe(state: AgentState) -> Command[Literal["decide", "__end__"]]: ...

    async def decide(state: AgentState) -> Command[Literal["act", "observe", "__end__"]]: ...

    async def act(state: AgentState) -> Command[Literal["observe"]]: ...

    graph = (
        StateGraph(AgentState)
        .add_node("observe", observe)
        .add_node("decide", decide)
        .add_node("act", act)
        .add_edge(START, "observe")
        .compile()
    )
    del END
    return graph.get_graph().draw_mermaid()
