"""The orchestrator: NetGent's entry point that chains the agents into the pipeline.

Single run (`--runs 1`, the default — unchanged):

    START → explore → verify → generate → END
               │          │
               └─ failed ─┴─ not achieved (retries spent) ► END

Multi-run (`--runs N`, the ReUseIt-style loop with a typed merge):

    START → plan → explore_run ↺ (×N, fresh memory each; verify per run, private retry)
                 → merge (pure code: typed-key alignment → ONE generalized NFA)
                 → replay (zero-LLM metamorphic check: same state sequence per value set) → END

One LangGraph StateGraph each, one node per agent. Independence policy
(docs/research/trajectory-memory.md §C.4): runs share ONLY a short read-only hints block
(interrupt anchors seen in earlier runs) — never a step sequence, never an element to click
for the task, never a value; each run gets a fresh ExplorerMemory via `explore()`, and a
verifier retry's task suffix stays inside its own run.

`orchestrate()` is what `netgent generate` calls. The agents stay independent modules — the
orchestrator is the only place that knows the order they run in.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.agent.llm import LLM
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.schema.workflow import Workflow, dump_workflow

logger = get_logger(__name__)

Stage = Literal["plan", "explore", "verify", "merge", "generate", "replay"]
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
    # The verifier: an LLM judge of the exploration from page evidence (agent/verifier). Advisory —
    # a "not achieved" re-explores (up to `verify_retries` more times, with the unmet points
    # appended to the task); "achieved" proceeds to generation.
    judge: bool = True
    verify_retries: int = 1
    # Multi-run exploration (`--runs N`): the planner drafts N same-family task variations,
    # each explored independently (fresh memory), judged per run; the achieved runs are merged
    # by the typed-key merge into ONE generalized workflow, then replay-checked with zero LLM.
    # runs=1 keeps the single-run pipeline above, byte-for-byte.
    runs: int = Field(default=1, ge=1)
    variation: dict[str, str] = Field(default_factory=dict)  # pin one variation's values (--variation)


class GenerateResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    trajectory: AgentTrajectory | None = None
    workflow: Workflow | None = None
    verdict: Any = None  # the verifier's Verdict (None when judging is off)
    error: str | None = None  # set when a stage stopped the pipeline
    # Multi-run outputs (None on the single-run path):
    variations: Any = None  # the planner's VariationPlan
    run_reports: list[dict] = Field(default_factory=list)  # per-run {run, task, values, achieved, attempts}
    generalized: Any = None  # the merge's GeneralizedTrajectory (also at <store>/generalized.json)
    replay: Any = None  # the zero-LLM ReplayReport (the metamorphic check)


class OrchestrationState(TypedDict, total=False):
    trajectory: Any
    verdict: Any
    attempt: int  # exploration attempts so far (the verifier may ask for another)
    task_suffix: str  # what the verifier found unmet, appended to the task on re-exploration
    workflow: Any
    error: str


def build_orchestration_graph(req: GenerateRequest, llm: LLM, listen: Listener | None = None):
    """Compile the explore → verify → generate graph bound to one request."""
    from langgraph.graph import END, START, StateGraph  # lazy: the `generate` extra
    from langgraph.types import Command

    # Imported here, not inside the nodes, and EXPLORER/VERIFIER are named in the nodes' own source: that is
    # what LangGraph's static walk (get_function_nonlocals → find_subgraph_pregel) needs to list
    # the explorer and verifier as the nodes' subgraphs, so get_subgraphs()/get_graph(xray=True)/Studio
    # show observe → decide → act and gather → judge nested in the pipeline (langgraph-agent-structure.md §3d, C → A).
    from netgent.agent.explorer.decision import DEFAULT_KINDS
    from netgent.agent.explorer.graph import EXPLORER
    from netgent.agent.explorer.graph import explore as run_explorer
    from netgent.agent.verifier.graph import VERIFIER
    from netgent.agent.verifier.graph import verify as run_verifier

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
        # The params are declared to the explorer as ${name} = 'sample' values to use verbatim; the
        # compiler then binds ${name} by sweeping the sample values out of the trajectory.
        task = req.task
        if req.params:
            decl = "; ".join(f"${{{k}}} = {v!r}" for k, v in req.params.items())
            task = (
                f"{req.task}\n\nPARAMETERS: {decl}\n"
                "Where the task refers to one of these, type or pick the value above exactly as given."
            )
        if state.get("task_suffix"):
            task = f"{task}\n\n{state['task_suffix']}"
        async with BrowserSession(headless=req.headless) as session:
            traj = await run_explorer(
                session, task, llm=llm, url=req.url, max_steps=req.max_steps, run_dir=run_dir,
                allowed_kinds=DEFAULT_KINDS | set(req.allow_kinds), max_actions_per_step=req.max_actions_per_step,
                graph=EXPLORER,
            )
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
        verdict = await run_verifier(
            state["trajectory"], req.task, llm=llm, params=req.params, run_dir=run_dir, graph=VERIFIER
        )
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

    async def generate(state: OrchestrationState) -> Command[Literal["__end__"]]:
        warnings: list[str] = []
        wf = compile_trajectory(state["trajectory"], name=req.name, params=req.params, warnings=warnings)
        if req.out is not None:
            dump_workflow(wf, req.out)
        emit("generate", f"compiled {len(wf.transitions)} transitions, {len(wf.states)} states")
        for w in warnings:
            emit("generate", f"WARNING: {w}")
        for p in wf.params:
            emit("generate", f"param {p.name} (default: {p.default!r})")
        return Command(update={"workflow": wf}, goto=END)

    return (
        StateGraph(OrchestrationState)
        .add_node("explore", explore)
        .add_node("verify", verify)
        .add_node("generate", generate)
        .add_edge(START, "explore")
        .compile()
    )


class MultiRunState(TypedDict, total=False):
    plan: Any  # the planner's VariationPlan
    k: int  # 1-based index of the NEXT run to explore
    inputs: list  # merge RunInput per finished run (achieved or not)
    reports: list  # per-run summary dicts
    workflow: Any
    generalized: Any
    replay: Any
    error: str


def _store_root(req: GenerateRequest) -> Path:
    """`<out-dir>/<name>.trajectories` — the workflow's memory folder."""
    if req.out is not None:
        return req.out.parent / f"{req.name}.trajectories"
    if req.trajectory_dir is not None:
        return req.trajectory_dir / f"{req.name}.trajectories"
    import tempfile

    return Path(tempfile.mkdtemp(prefix="netgent-multitraj-")) / f"{req.name}.trajectories"


def _site_hints(prior: list[AgentTrajectory]) -> str:
    """The ONLY thing runs share (independence policy §C.4): interrupt anchors seen by
    earlier runs, as context — never a step sequence, never an element for the task."""
    from netgent.agent.generator.compiler import _target_selector, is_interruption_step

    sels: list[str] = []
    for traj in prior:
        for s in traj.steps:
            if s.action is not None and s.error is None and is_interruption_step(s):
                sel = _target_selector(s.action)
                if sel and sel not in sels:
                    sels.append(sel)
    if not sels:
        return ""
    return (
        "HINTS (independent earlier runs hit overlays/pop-ups on this site; context only — "
        "decide from the page, not from this): dismissal controls previously seen: "
        + ", ".join(sels[:3]) + "."
    )


def _variation_task(variation, hints: str, suffix: str) -> str:
    """The explorer task for one run: the variation's text, its values declared the same way
    `-p` declares samples on the single-run path, the shared hints, this run's own retry suffix."""
    task = variation.task_text
    if variation.values:
        decl = "; ".join(f"${{{k}}} = {v!r}" for k, v in variation.values.items())
        task += (
            f"\n\nPARAMETERS: {decl}\n"
            "Where the task refers to one of these, type or pick the value above exactly as given."
        )
    if hints:
        task += f"\n\n{hints}"
    if suffix:
        task += f"\n\n{suffix}"
    return task


def build_multi_orchestration_graph(req: GenerateRequest, llm: LLM, listen: Listener | None = None):
    """Compile plan → explore_run (×N) → merge → replay, bound to one request."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command

    from netgent.agent.explorer.decision import DEFAULT_KINDS
    from netgent.agent.explorer.graph import EXPLORER
    from netgent.agent.explorer.graph import explore as run_explorer
    from netgent.agent.generator.merge import RunInput, merge_trajectories
    from netgent.agent.planner.graph import VARIATION_PLANNER
    from netgent.agent.planner.graph import plan_variations as run_variation_planner
    from netgent.agent.replay import replay_check
    from netgent.agent.store import TrajectoryStore
    from netgent.agent.verifier.graph import VERIFIER
    from netgent.agent.verifier.graph import verify as run_verifier

    def emit(stage: Stage, text: str) -> None:
        logger.info("%s: %s", stage, text)
        if listen:
            listen(stage, text)

    store = TrajectoryStore(_store_root(req))

    async def plan(state: MultiRunState) -> Command[Literal["explore_run"]]:
        emit("plan", f"planning {req.runs} task variations")
        variation_plan = await run_variation_planner(
            req.task, llm=llm, n=req.runs, url=req.url, pinned=req.variation or None, graph=VARIATION_PLANNER
        )
        # `-p name=sample` names are proposals too: the base run uses the sample; the merge
        # confirms the name only if the planner also varied it.
        for name, sample in req.params.items():
            for v in variation_plan.variations:
                v.values.setdefault(name, sample)
        for i, v in enumerate(variation_plan.variations, 1):
            vals = ", ".join(f"{k}={val!r}" for k, val in v.values.items()) or "(no values)"
            emit("plan", f"variation {i}: {v.task_text} [{vals}]")
        for note in variation_plan.notes:
            emit("plan", f"note: {note}")
        return Command(update={"plan": variation_plan, "k": 1}, goto="explore_run")

    async def explore_run(state: MultiRunState) -> Command[Literal["explore_run", "merge"]]:
        k = state.get("k", 1)
        variation = state["plan"].variations[k - 1]
        run_dir = store.run_dir(k)
        store.save_variation(k, variation)
        hints = _site_hints([i.trajectory for i in state.get("inputs", [])])
        max_attempts = 1 + (req.verify_retries if req.judge else 0)
        attempts, achieved, verdict, traj, suffix = 0, False, None, None, ""
        while True:
            attempts += 1
            task = _variation_task(variation, hints, suffix)
            emit(
                "explore",
                f"run {k}/{req.runs}: {variation.task_text}" + (f" (attempt {attempts})" if attempts > 1 else ""),
            )
            async with BrowserSession(headless=req.headless) as session:
                # memory=None → a FRESH ExplorerMemory per attempt: runs are independent samples.
                traj = await run_explorer(
                    session, task, llm=llm, url=req.url, max_steps=req.max_steps, run_dir=run_dir,
                    allowed_kinds=DEFAULT_KINDS | set(req.allow_kinds),
                    max_actions_per_step=req.max_actions_per_step, graph=EXPLORER,
                )
            for s in traj.steps:
                emit("explore", f"run {k}: {s.n}. {s.kind} — {s.reasoning}"
                     + (f" [FAILED: {s.error}]" if s.error else ""))
            if not traj.success:
                emit("explore", f"run {k}: exploration failed: {traj.stopped_reason or 'not completed'}")
                break
            if not req.judge:
                achieved = True
                break
            verdict = await run_verifier(
                traj, variation.task_text, llm=llm, params=variation.values, run_dir=run_dir, graph=VERIFIER
            )
            achieved = verdict.achieved
            emit("verify", f"run {k}: judge says {'achieved' if achieved else 'NOT achieved'}"
                 + (f" — unmet: {'; '.join(verdict.unmet)}" if verdict.unmet else ""))
            if achieved or attempts >= max_attempts:
                break
            unmet = "; ".join(verdict.unmet) or "the task outcome was not visible on the page"
            suffix = (
                "A previous attempt was judged NOT achieved from the page evidence. Unmet: "
                f"{unmet}. Make sure the page visibly shows each requirement before declaring done."
            )
            store.stash_failed_attempt(k, attempts)
            emit("verify", f"run {k}: re-exploring with the unmet points (private to this run)")
        store.save_verdict(k, verdict, achieved, attempts)
        inputs = [*state.get("inputs", []),
                  RunInput(run=k, trajectory=traj, values=dict(variation.values), achieved=achieved)]
        reports = [*state.get("reports", []),
                   {"run": k, "task": variation.task_text, "values": dict(variation.values),
                    "achieved": achieved, "attempts": attempts}]
        return Command(
            update={"k": k + 1, "inputs": inputs, "reports": reports},
            goto="explore_run" if k < req.runs else "merge",
        )

    async def merge(state: MultiRunState) -> Command[Literal["replay", "__end__"]]:
        inputs = state["inputs"]
        achieved = [i for i in inputs if i.achieved]
        if not achieved:
            return Command(update={"error": "no run achieved the task — nothing to merge"}, goto=END)
        emit("merge", f"merging {len(achieved)}/{len(inputs)} achieved runs (typed-key alignment, pure code)")
        warnings: list[str] = []
        try:
            outcome = merge_trajectories(inputs, name=req.name, warnings=warnings)
        except ValueError as exc:
            return Command(update={"error": f"merge failed: {exc}"}, goto=END)
        store.save_generalized(outcome.generalized)
        for w in warnings:
            emit("merge", f"WARNING: {w}")
        wf = outcome.workflow
        if req.out is not None:
            dump_workflow(wf, req.out)
        emit("generate", f"compiled {len(wf.transitions)} transitions, {len(wf.states)} states, "
             f"{len(wf.interrupts)} interrupt(s), accept_states={wf.accept_states}")
        for p in wf.params:
            emit("generate", f"param {p.name} (default: {p.default!r}) — {p.description}")
        return Command(update={"workflow": wf, "generalized": outcome.generalized}, goto="replay")

    async def replay(state: MultiRunState) -> Command[Literal["__end__"]]:
        wf = state["workflow"]
        gen = state["generalized"]
        achieved = [i for i in state["inputs"] if i.achieved]
        value_sets: list[dict[str, str]] = [{p.name: p.default or "" for p in wf.params}]
        for other in achieved[1:2]:  # the second achieved run's values — the metamorphic pair
            value_sets.append({
                p.name: next((g.values_by_run.get(other.run) for g in gen.params if g.name == p.name), None)
                or p.default or ""
                for p in wf.params
            })
        if len(value_sets) == 1:
            value_sets.append(dict(value_sets[0]))  # determinism check: same values, same sequence
        emit("replay", f"zero-LLM replay × {len(value_sets)}: {value_sets}")
        report = await replay_check(wf, value_sets, headless=req.headless, run_dir_base=store.root)
        for r in report.runs:
            emit("replay", f"{'ok' if r.success else 'FAILED'} {r.values} -> states {r.signature}"
                 + (f" ({r.error})" if r.error else ""))
        update: dict[str, Any] = {"replay": report}
        if report.passed:
            emit("replay", "metamorphic check passed: same state sequence for every value set, zero LLM")
        else:
            update["error"] = "replay check failed: the compiled workflow did not replay identically for " \
                              f"every value set ({[r.signature for r in report.runs]})"
        return Command(update=update, goto=END)

    return (
        StateGraph(MultiRunState)
        .add_node("plan", plan)
        .add_node("explore_run", explore_run)
        .add_node("merge", merge)
        .add_node("replay", replay)
        .add_edge(START, "plan")
        .compile()
    )


async def orchestrate(req: GenerateRequest, llm: LLM, listen: Listener | None = None) -> GenerateResult:
    """Run the pipeline. `runs=1`: explore → verify → generate (unchanged). `runs>1`:
    plan variations → explore ×N (verify per run) → typed merge → zero-LLM replay check."""
    if req.runs == 1:
        graph = build_orchestration_graph(req, llm, listen)
        final = await graph.ainvoke({})
        return GenerateResult(
            trajectory=final.get("trajectory"),
            workflow=final.get("workflow"),
            verdict=final.get("verdict"),
            error=final.get("error"),
        )
    graph = build_multi_orchestration_graph(req, llm, listen)
    final = await graph.ainvoke({}, config={"recursion_limit": 4 * req.runs + 16})
    inputs = final.get("inputs") or []
    spine = next((i.trajectory for i in inputs if i.achieved), None)
    return GenerateResult(
        trajectory=spine,
        workflow=final.get("workflow"),
        error=final.get("error"),
        variations=final.get("plan"),
        run_reports=final.get("reports") or [],
        generalized=final.get("generalized"),
        replay=final.get("replay"),
    )
