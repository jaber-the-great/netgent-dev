"""The verifier as a LangGraph StateGraph — functions + ONE compiled graph, the explorer's shape.

    START → gather → judge → END

`gather` is pure: it turns the trajectory into Evidence (what ran, what the page showed — never
the explorer's reasoning). `judge` is the one LLM call: Evidence in, Verdict out. `VERIFIER` is
compiled once at import; the LLM and the screenshot directory travel as `Runtime.context`
(a VerifierContext), never in state. `verify()` is the one run API.

This module imports langgraph at module level; `netgent.agent.verifier` resolves it lazily.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.verifier.context import VerifierContext
from netgent.agent.verifier.models import Evidence, Verdict
from netgent.agent.verifier.prompt import JUDGE_SYSTEM, build_judge_content

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


class VerifierState(TypedDict, total=False):
    task: str  # the user's task, as asked (not the explorer's augmented copy)
    trajectory: Any  # AgentTrajectory
    params: dict[str, str]
    evidence: Any  # Evidence (gather's output)
    verdict: Any  # Verdict (judge's output)


async def gather(state: VerifierState, runtime: Runtime[VerifierContext]) -> dict:
    """Trajectory → Evidence. Pure, except for reading the screenshots off disk."""
    ctx = runtime.context
    ev = Evidence.from_trajectory(
        state["task"], state["trajectory"], params=state.get("params"), run_dir=ctx.run_dir,
        max_screenshots=ctx.max_screenshots,
    )
    return {"evidence": ev}


async def judge(state: VerifierState, runtime: Runtime[VerifierContext]) -> dict:
    """Evidence → Verdict: the one LLM call, through the agent's LLM seam."""
    verdict = await judge_trajectory(runtime.context.llm, state["evidence"])
    return {"verdict": verdict}


async def judge_trajectory(llm: "LLM", ev: Evidence) -> Verdict:
    """One LLM call → Verdict. `llm` is the agent's LLM seam (LangChainLLM / FakeLLM)."""
    return await llm.judge(JUDGE_SYSTEM, build_judge_content(ev), Verdict)


def create_verifier_agent() -> CompiledStateGraph:
    """Build and compile gather → judge. Same shape as `create_explorer_agent`."""
    return (
        StateGraph(VerifierState, context_schema=VerifierContext)
        .add_node("gather", gather)
        .add_node("judge", judge)
        .add_edge(START, "gather")
        .add_edge("gather", "judge")
        .add_edge("judge", END)
        .compile(name="verifier")
    )


VERIFIER = create_verifier_agent()  # compiled ONCE


async def verify(
    traj: AgentTrajectory,
    task: str,
    *,
    llm: "LLM",
    params: dict[str, str] | None = None,
    run_dir: Path | None = None,
    max_screenshots: int | None = None,
    graph: CompiledStateGraph | None = None,
) -> Verdict:
    """The ONE run API: judge `traj` against `task` from page evidence. The orchestrator's
    verify node and the sweep's judge mode end here. `graph` defaults to VERIFIER."""
    graph = VERIFIER if graph is None else graph
    ctx = VerifierContext(llm=llm, run_dir=run_dir) if max_screenshots is None else VerifierContext(
        llm=llm, run_dir=run_dir, max_screenshots=max_screenshots
    )
    final = await graph.ainvoke({"task": task, "trajectory": traj, "params": dict(params or {})}, context=ctx)
    return final["verdict"]
