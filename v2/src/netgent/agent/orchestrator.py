"""The orchestrator: NetGent's entry point that chains the agents into the pipeline.

    START → explore → generate → validate → END
               │          │
               └─ failed ─┴───────────────► END

One LangGraph StateGraph, one node per agent:
- explore  (explorer)            LLM drives the browser; output: a trajectory
- generate (generator) pure code; output: the workflow (NFA) artifact
- validate (validator)         zero-LLM replay; output: a per-edge report

`orchestrate()` is what `netgent generate` calls. Each stage opens its own fresh browser
session, so exploration state can never leak into validation. The agents stay independent
modules — the orchestrator is the only place that knows the order they run in.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from netgent.agent.explorer.browser_agent import AgentTrajectory, BrowserAgent
from netgent.agent.generator.compiler import compile_trajectory
from netgent.agent.llm import LLM
from netgent.agent.validator.validate import ValidationReport, validate_workflow
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.schema.workflow import Workflow, dump_workflow

logger = get_logger(__name__)

Stage = Literal["explore", "verify", "generate", "validate"]
Listener = Callable[[Stage, str], None]  # (stage, human-readable event) → for CLI progress


class GenerateRequest(BaseModel):
    """Everything the pipeline needs; the CLI builds one of these from its flags."""

    task: str
    url: str | None = None
    name: str = "workflow"
    params: dict[str, str] = Field(default_factory=dict)  # name -> sample value used in exploration
    max_steps: int = 25
    # Extra action kinds to offer the explorer beyond decision.DEFAULT_KINDS (hover/press/goto/
    # go_back are opt-in: rarely needed, and measured to cost steps when always available).
    allow_kinds: list[str] = Field(default_factory=list)
    max_actions_per_step: int = 1  # >1 lets one decision carry a bounded batch (each item = one transition)
    headless: bool = True
    out: Path | None = None  # write the artifact here (yaml/json by suffix)
    trajectory_dir: Path | None = None
    validate_replay: bool = True  # run the validation agent after generating
    # The verifier: an LLM judge of the exploration from page evidence (agent/verifier). Advisory —
    # a "not achieved" re-explores (up to `verify_retries` more times, with the unmet points
    # appended to the task); "achieved" proceeds but never replaces the replay validation.
    judge: bool = True
    verify_retries: int = 1


class GenerateResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    trajectory: AgentTrajectory | None = None
    workflow: Workflow | None = None
    report: ValidationReport | None = None
    verdict: Any = None  # the verifier's Verdict (None when judging is off)
    error: str | None = None  # set when a stage stopped the pipeline

    @property
    def validated(self) -> bool:
        return self.report is not None and self.report.validated


class OrchestrationState(TypedDict, total=False):
    trajectory: Any
    verdict: Any
    attempt: int  # exploration attempts so far (the verifier may ask for another)
    task_suffix: str  # what the verifier found unmet, appended to the task on re-exploration
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

    # Screenshots are the judge's evidence: keep a run dir even when the caller asked for none.
    run_dir = req.trajectory_dir
    if run_dir is None and req.judge:
        import tempfile

        run_dir = Path(tempfile.mkdtemp(prefix="netgent-explore-"))

    async def explore(state: OrchestrationState) -> Command[Literal["verify", "generate", "__end__"]]:
        attempt = state.get("attempt", 0) + 1
        emit("explore", f"exploring: {req.task}" + (f" (attempt {attempt})" if attempt > 1 else ""))
        from netgent.agent.explorer.decision import DEFAULT_KINDS

        agent = BrowserAgent(
            llm,
            max_steps=req.max_steps,
            run_dir=run_dir,
            allowed_kinds=DEFAULT_KINDS | set(req.allow_kinds),
            max_actions_per_step=req.max_actions_per_step,
        )
        # The params are declared to the explorer as ${name} = 'sample' placeholders (Stagehand's
        # %var% contract): it types the sample AND reports `param` on the step that used it, so
        # the compiler binds ${name} structurally (the prompt's PARAMETERS rule).
        task = req.task
        if req.params:
            decl = "; ".join(f"${{{k}}} = {v!r}" for k, v in req.params.items())
            task = (
                f"{req.task}\n\nPARAMETERS: {decl}\n"
                "Where the task refers to one of these, the value above is the sample to type or pick, "
                "and you must set `param` to its name on that step."
            )
        if state.get("task_suffix"):
            task = f"{task}\n\n{state['task_suffix']}"
        async with BrowserSession(headless=req.headless) as session:
            traj = await agent.run(session, task, req.url)
        for s in traj.steps:
            emit("explore", f"{s.n}. {s.kind} — {s.reasoning}" + (f" [FAILED: {s.error}]" if s.error else ""))
        usage = getattr(llm, "usage", None)  # LangChainLLM tracks it; the LLM protocol doesn't require it
        if usage and usage.get("calls"):
            emit(
                "explore",
                f"LLM usage: {usage['calls']} calls, "
                f"{usage['input_tokens']:,} input + {usage['output_tokens']:,} output tokens",
            )
        if not traj.success:
            reason = traj.stopped_reason or "not completed"
            emit("explore", f"exploration failed: {reason}")
            return Command(
                update={"trajectory": traj, "attempt": attempt, "error": f"exploration failed: {reason}"}, goto=END
            )
        return Command(update={"trajectory": traj, "attempt": attempt}, goto="verify" if req.judge else "generate")

    async def verify(state: OrchestrationState) -> Command[Literal["explore", "generate", "__end__"]]:
        """The LLM judge (advisory). Sees page evidence, never the explorer's reasoning."""
        from netgent.agent.verifier import Evidence, judge_trajectory

        traj = state["trajectory"]
        ev = Evidence.from_trajectory(req.task, traj, params=req.params, run_dir=run_dir)
        verdict = await judge_trajectory(llm, ev)
        emit("verify", f"judge: {'achieved' if verdict.achieved else 'NOT achieved'} ({verdict.confidence} confidence)"
             + (f" — unmet: {'; '.join(verdict.unmet)}" if verdict.unmet else ""))
        for e in verdict.evidence[:4]:
            emit("verify", f"evidence: {e}")
        if verdict.achieved:
            return Command(update={"verdict": verdict}, goto="generate")
        if state.get("attempt", 1) <= req.verify_retries:
            unmet = "; ".join(verdict.unmet) or "the task outcome was not visible on the page"
            suffix = (
                "A previous attempt was judged NOT achieved from the page evidence. Unmet: "
                f"{unmet}. Make sure the page visibly shows each requirement before declaring done."
            )
            emit("verify", "re-exploring with the unmet points")
            return Command(update={"verdict": verdict, "task_suffix": suffix}, goto="explore")
        return Command(
            update={
                "verdict": verdict,
                "error": "verifier: task not achieved — " + ("; ".join(verdict.unmet) or "no evidence"),
            },
            goto=END,
        )

    async def generate(state: OrchestrationState) -> Command[Literal["validate", "__end__"]]:
        warnings: list[str] = []
        wf = compile_trajectory(state["trajectory"], name=req.name, params=req.params, warnings=warnings)
        if req.out is not None:
            dump_workflow(wf, req.out)
        emit("generate", f"compiled {len(wf.transitions)} transitions, {len(wf.states)} states")
        for w in warnings:
            emit("generate", f"WARNING: {w}")
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
        .add_node("verify", verify)
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
        verdict=final.get("verdict"),
        error=final.get("error"),
    )
