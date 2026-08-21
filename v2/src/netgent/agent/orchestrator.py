"""The orchestrator: NetGent's entry point that chains the agents into the pipeline.

    START → explore → generate → validate → END
               │          │
               └─ failed ─┴───────────────► END

One LangGraph StateGraph, one node per agent:
- explore  (explore_agent)            LLM drives the browser; output: a trajectory
- generate (workflow_generator_agent) pure code; output: the workflow (NFA) artifact
- validate (validation_agent)         zero-LLM replay; output: a per-edge report

`orchestrate()` is what `netgent generate` calls. Each stage opens its own fresh browser
session, so exploration state can never leak into validation. The agents stay independent
modules — the orchestrator is the only place that knows the order they run in.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from netgent.agent.explore_agent.browser_agent import AgentTrajectory, BrowserAgent
from netgent.agent.llm import LLM
from netgent.agent.validation_agent.validate import ValidationReport, validate_workflow
from netgent.agent.workflow_generator_agent.compiler import compile_trajectory
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.schema.workflow import Workflow, dump_workflow

logger = get_logger(__name__)

Stage = Literal["explore", "generate", "validate"]
Listener = Callable[[Stage, str], None]  # (stage, human-readable event) → for CLI progress


class GenerateRequest(BaseModel):
    """Everything the pipeline needs; the CLI builds one of these from its flags."""

    task: str
    url: str | None = None
    name: str = "workflow"
    params: dict[str, str] = Field(default_factory=dict)  # name -> sample value used in exploration
    max_steps: int = 25
    headless: bool = True
    observation: str | None = None  # dom | ax (None → NETGENT_OBSERVATION)
    out: Path | None = None  # write the artifact here (yaml/json by suffix)
    trajectory_dir: Path | None = None
    validate_replay: bool = True  # run the validation agent after generating


class GenerateResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    trajectory: AgentTrajectory | None = None
    workflow: Workflow | None = None
    report: ValidationReport | None = None
    error: str | None = None  # set when a stage stopped the pipeline

    @property
    def validated(self) -> bool:
        return self.report is not None and self.report.validated


class OrchestrationState(TypedDict, total=False):
    trajectory: Any
    workflow: Any
    report: Any
    error: str


def build_orchestration_graph(req: GenerateRequest, llm: LLM, listen: Listener | None = None):
    """Compile the explore → generate → validate graph bound to one request."""
    from langgraph.graph import END, START, StateGraph  # lazy: the `generate` extra
    from langgraph.types import Command

    def emit(stage: Stage, text: str) -> None:
        logger.info("%s: %s", stage, text)
        if listen:
            listen(stage, text)

    async def explore(state: OrchestrationState) -> Command[Literal["generate", "__end__"]]:
        emit("explore", f"exploring: {req.task}")
        agent = BrowserAgent(llm, max_steps=req.max_steps, run_dir=req.trajectory_dir)
        async with BrowserSession(headless=req.headless, stealth=True, observation=req.observation) as session:
            traj = await agent.run(session, req.task, req.url)
        for s in traj.steps:
            emit("explore", f"{s.n}. {s.kind} — {s.reasoning}" + (f" [FAILED: {s.error}]" if s.error else ""))
        if not traj.success:
            reason = traj.stopped_reason or "not completed"
            emit("explore", f"exploration failed: {reason}")
            return Command(update={"trajectory": traj, "error": f"exploration failed: {reason}"}, goto=END)
        return Command(update={"trajectory": traj}, goto="generate")

    async def generate(state: OrchestrationState) -> Command[Literal["validate", "__end__"]]:
        wf = compile_trajectory(state["trajectory"], name=req.name, params=req.params)
        if req.out is not None:
            dump_workflow(wf, req.out)
        emit("generate", f"compiled {len(wf.transitions)} transitions, {len(wf.states)} states")
        for p in wf.params:
            emit("generate", f"param {p.name} (default: {p.default!r})")
        return Command(update={"workflow": wf}, goto="validate" if req.validate_replay else END)

    async def validate(state: OrchestrationState) -> Command[Literal["__end__"]]:
        emit("validate", "zero-LLM replay with defaults")
        report = await validate_workflow(state["workflow"], headless=req.headless)
        for r in report.replays:
            verdict = f"replay ok ({r.edges_ok} edges)" if r.success else f"replay FAILED at {r.failed_edge}: {r.error}"
            emit("validate", verdict)
        update: dict[str, Any] = {"report": report}
        if not report.validated:
            update["error"] = "artifact written but did not replay cleanly"
        return Command(update=update, goto=END)

    return (
        StateGraph(OrchestrationState)
        .add_node("explore", explore)
        .add_node("generate", generate)
        .add_node("validate", validate)
        .add_edge(START, "explore")
        .compile()
    )


async def orchestrate(req: GenerateRequest, llm: LLM, listen: Listener | None = None) -> GenerateResult:
    """Run the pipeline: explore → generate → validate. The entry point behind `netgent generate`."""
    graph = build_orchestration_graph(req, llm, listen)
    final = await graph.ainvoke({})
    return GenerateResult(
        trajectory=final.get("trajectory"),
        workflow=final.get("workflow"),
        report=final.get("report"),
        error=final.get("error"),
    )


def orchestration_graph_mermaid() -> str:
    """The pipeline's structure as a Mermaid diagram (`netgent generate --graph`)."""
    from langgraph.graph import START, StateGraph
    from langgraph.types import Command

    async def explore(state: OrchestrationState) -> Command[Literal["generate", "__end__"]]: ...

    async def generate(state: OrchestrationState) -> Command[Literal["validate", "__end__"]]: ...

    async def validate(state: OrchestrationState) -> Command[Literal["__end__"]]: ...

    graph = (
        StateGraph(OrchestrationState)
        .add_node("explore", explore)
        .add_node("generate", generate)
        .add_node("validate", validate)
        .add_edge(START, "explore")
        .compile()
    )
    return graph.get_graph().draw_mermaid()
