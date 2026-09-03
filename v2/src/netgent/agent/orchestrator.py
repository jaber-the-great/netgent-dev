"""The orchestrator: NetGent's entry point that chains the agents into the pipeline.

Single run (`--parallel 1`):

    START → explore → verify → generate → replay → END
               │          │                  │
               └─ failed ─┴─ not achieved ───┴─ replay FAILED (artifact still written) ► END, error set

    The replay is the single-run gate (generator-agent-v2.md §I.4): the compiled artifact is
    replayed with zero LLM on the recorded value set — twice when params are declared, the
    determinism half of the metamorphic check (one exploration has no unseen value set to vary).

Multi-run (`--parallel N --rounds R`, the default — the closed loop with a typed merge):

    START → plan → explore_run ×N (Send, parallel; fresh memory each; verify per run, private retry)
                 → merge (pure code: typed-key alignment of ALL runs so far → the evidence trail with
                          StepKeys, and the FALLBACK artifact)
                 → generate (the generator agent: gather → draft → materialize ⇄ repair; every choice a
                             pointer into the recordings, re-derived by code; the merge's artifact below
                             the floor)
                 → replay (zero-LLM metamorphic check: same state sequence per value set; a value set
                           that passed in an earlier round may not fail now)
                 → triage (pure code: verdicts + merge trail + replay → typed Episodes)
                 → END if the replay passed on ≥ 2 unseen value sets (or the round budget is spent)
                 → plan_next (ONE LLM call: next variations / scoped sub-tasks)
                 → explore_run ×k (usually 1-2) → merge → generate → … up to `--rounds` rounds.

The exit is replay-decided; the judge never grades the artifact. The RoundContext (agent/rounds.py)
accumulates across rounds and is persisted as <name>.trajectories/context.json.

One LangGraph StateGraph each, one node per agent. Independence policy
(docs/research/trajectory-memory.md §C.4): runs share ONLY a short read-only hints block
(interrupt anchors seen in earlier runs) — never a step sequence, never an element to click
for the task, never a value; each run gets a fresh ExplorerMemory via `explore()`, and a
verifier retry's task suffix stays inside its own run.

`orchestrate()` is what `netgent generate` calls. The agents stay independent modules — the
orchestrator is the only place that knows the order they run in.
"""

import operator
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.agent.llm import LLM
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.schema.units import coerce_number, number_text
from netgent.schema.workflow import Workflow, dump_workflow

logger = get_logger(__name__)

Stage = Literal["plan", "explore", "verify", "merge", "generate", "replay", "triage", "round"]
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
    # Multi-run exploration: the planner drafts `runs` same-family task variations, each
    # explored independently (fresh memory), judged per run; the achieved runs are merged by
    # the typed-key merge into ONE generalized workflow, then replay-checked with zero LLM.
    # runs=1 keeps the single-run pipeline above, byte-for-byte.
    runs: int = Field(default=1, ge=1)
    # How many of those runs execute at once (each in its own browser). Runs are independent
    # samples by design (trajectory-memory.md §C.4), so they fan out with LangGraph `Send` and
    # concurrency cannot change the artifact — only wall-clock time. The CLI exposes ONE knob,
    # `--parallel N`, which sets both to N (5 by default); the split survives here because a
    # scripted FakeLLM is consumed in order, so the tests need runs=N with parallel=1.
    parallel: int = Field(default=1, ge=1)
    variation: dict[str, str] = Field(default_factory=dict)  # pin one variation's values (--variation)
    # The closed loop (`--rounds R`, runs > 1 only): after the replay check, triage → plan_next →
    # another round of explorations merged with everything so far, until the replay passes on
    # ≥ 2 unseen value sets or the budget is spent. 1 = today's single round.
    max_rounds: int = Field(default=3, ge=1)


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
    replay: Any = None  # the zero-LLM ReplayReport: the last round's (multi-run) or the single-run gate's
    context: Any = None  # the RoundContext (agent/rounds.py): every round's evidence, at <store>/context.json
    rounds: int = 0  # rounds run
    episodes: list = Field(default_factory=list)  # the last round's triage Episodes


class OrchestrationState(TypedDict, total=False):
    trajectory: Any
    verdict: Any
    attempt: int  # exploration attempts so far (the verifier may ask for another)
    task_suffix: str  # what the verifier found unmet, appended to the task on re-exploration
    workflow: Any
    replay: Any  # the single-run gate's ReplayReport
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

    async def generate(state: OrchestrationState) -> Command[Literal["replay"]]:
        warnings: list[str] = []
        wf = compile_trajectory(state["trajectory"], name=req.name, params=req.params, warnings=warnings)
        if req.out is not None:
            dump_workflow(wf, req.out)
        emit("generate", f"compiled {len(wf.transitions)} transitions, {len(wf.states)} states")
        for w in warnings:
            emit("generate", f"WARNING: {w}")
        for p in wf.params:
            emit("generate", f"param {p.name} (default: {p.default!r})")
        return Command(update={"workflow": wf}, goto="replay")

    async def replay(state: OrchestrationState) -> Command[Literal["__end__"]]:
        """The single-run gate (generator-agent-v2.md §I.4): the artifact must replay with zero LLM
        on the value set it was recorded with. With declared params the set is replayed twice —
        one exploration has no unseen set to vary, so the metamorphic check degenerates to
        determinism (same state sequence both times), exactly `select_replay_sets`' no-unseen rule.
        A failure leaves the artifact on disk and sets the error; the CLI exits non-zero."""
        from netgent.agent.replay import replay_check

        wf: Workflow = state["workflow"]
        values = {p.name: p.default or "" for p in wf.params if p.derive is None}
        value_sets = [values, dict(values)] if values else [values]
        emit("replay", f"zero-LLM replay × {len(value_sets)}: {value_sets}")
        report = await replay_check(wf, value_sets, headless=req.headless, run_dir_base=_store_root(req))
        for r in report.runs:
            emit("replay", f"{'ok' if r.success else 'FAILED'} {r.values} -> states {r.signature}"
                 + (f" ({r.error})" if r.error else ""))
        if report.passed:
            emit("replay", f"replay passed on the recorded value set ({len(report.runs)} run(s), "
                 "same state sequence), zero LLM")
            return Command(update={"replay": report}, goto=END)
        emit("replay", f"replay check FAILED: {[r.signature for r in report.runs]}")
        return Command(
            update={"replay": report,
                    "error": "replay check failed: the compiled workflow did not replay on the recorded value "
                             f"set ({[r.signature for r in report.runs]}); the artifact is written for inspection"},
            goto=END,
        )

    return (
        StateGraph(OrchestrationState)
        .add_node("explore", explore)
        .add_node("verify", verify)
        .add_node("generate", generate)
        .add_node("replay", replay)
        .add_edge(START, "explore")
        .compile()
    )


class MultiRunState(TypedDict, total=False):
    plan: Any  # the planner's VariationPlan (round 1)
    # Send payload keys, one explore_run task each: the run's global 1-based number, its round,
    # the TaskVariation to explore, and whether it is a scoped sub-task (evidence, not a spine).
    k: int
    round: int
    variation: Any
    scoped: bool
    start_url: str | None
    inputs: Annotated[list, operator.add]  # merge RunInput per finished run, ALL rounds — fan-in
    reports: Annotated[list, operator.add]  # per-run summary dicts — fan-in
    workflow: Any
    generalized: Any
    replay: Any
    context: Any  # the RoundContext, replaced each node that advances it
    fallback: Any  # the merge's own Workflow — what the generator degrades to
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


def _run_values(gen, rid: int) -> dict[str, str]:
    """The artifact's value set for exploration run `rid` (its planned values under the params)."""
    return {p.name: p.values_by_run.get(rid, p.default) or p.default or "" for p in gen.params}


def select_replay_sets(wf, gen, achieved_runs: list[int], previous_failed: list[dict[str, str]],
                       max_sets: int = 3, run_values: dict[int, dict[str, str]] | None = None) -> list[dict[str, str]]:
    """The value sets to replay: the artifact's defaults first, then UNSEEN sets (≠ defaults):
    sets that failed last round come first (they must pass now), then the newest runs' values
    (the latest round's runs were planned to exercise the episodes). At most `max_sets`.
    With no unseen set, the defaults twice (the determinism check).

    `run_values` (run → the planner's declared values) is where a run's value for a param the
    AGENT bound but the merge did not (fast_forward_time, realized only through presses) comes
    from; without it the gate would replay such a knob at its default every time."""
    # Derived params are computed from their source at resolve time (never caller-supplied), so
    # a value set names only the task's own knobs.
    defaults = {p.name: p.default or "" for p in wf.params if p.derive is None}
    unseen: list[dict[str, str]] = []
    declared = run_values or {}

    numeric = {p.name for p in wf.params
               if p.derive is None and p.default and p.default.strip() == number_text(p.default)}

    def _values_of(rid: int) -> dict[str, str]:
        merged = _run_values(gen, rid)
        out: dict[str, str] = {}
        for name in defaults:
            value = merged.get(name) or declared.get(rid, {}).get(name) or defaults[name]
            # A declared value keeps the planner's spelling ('30s'); a param whose default is a bare
            # number (a dwell count) needs the number, as the merge normalizes it.
            out[name] = number_text(value) if name in numeric and coerce_number(value) is not None else value
        return out

    for values in [*previous_failed, *(_values_of(rid) for rid in sorted(achieved_runs, reverse=True))]:
        values = {name: values.get(name, defaults[name]) for name in defaults}
        if values != defaults and values not in unseen:
            unseen.append(values)
    sets = [defaults, *unseen[: max_sets - 1]]
    if len(sets) == 1:
        sets.append(dict(defaults))
    return sets


def build_multi_orchestration_graph(req: GenerateRequest, llm: LLM, listen: Listener | None = None,
                                    generator_llm: LLM | None = None):
    """Compile plan → explore_run (×N) → merge → generate → replay → triage → {END | plan_next → …}.
    `generator_llm` is the generator agent's own model (settings.generator_agent_model); None: `llm`."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, Send

    from netgent.agent.explorer.decision import DEFAULT_KINDS
    from netgent.agent.explorer.graph import EXPLORER
    from netgent.agent.explorer.graph import explore as run_explorer
    from netgent.agent.generator.graph import GENERATOR
    from netgent.agent.generator.graph import generate as run_generator
    from netgent.agent.generator.merge import RunInput, merge_trajectories
    from netgent.agent.llm import scoped_llm, usage_of
    from netgent.agent.planner.graph import NEXT_ROUND_PLANNER, VARIATION_PLANNER
    from netgent.agent.planner.graph import plan_next as run_next_round_planner
    from netgent.agent.planner.graph import plan_variations as run_variation_planner
    from netgent.agent.planner.models import TaskVariation
    from netgent.agent.replay import ReplayReport, ReplayRun, replay_check
    from netgent.agent.rounds import GeneralizedSummary, ReplaySummary, RoundContext, RoundRecord, RunSummary
    from netgent.agent.store import TrajectoryStore
    from netgent.agent.triage import triage as run_triage
    from netgent.agent.verifier.graph import VERIFIER
    from netgent.agent.verifier.graph import verify as run_verifier

    def emit(stage: Stage, text: str) -> None:
        logger.info("%s: %s", stage, text)
        if listen:
            listen(stage, text)

    store = TrajectoryStore(_store_root(req))

    def sends(round_: int, variations: list, first_k: int, scoped: list | None = None) -> list:
        out = [Send("explore_run", {"k": first_k + i, "round": round_, "variation": v, "scoped": False,
                                    "start_url": req.url}) for i, v in enumerate(variations)]
        for st in scoped or []:
            out.append(Send("explore_run", {
                "k": first_k + len(out), "round": round_, "scoped": True, "start_url": st.start_url,
                "variation": TaskVariation(task_text=st.task_text, values=dict(st.values)),
            }))
        return out

    async def plan(state: MultiRunState) -> Command[Literal["explore_run"]]:  # goto is a list of Send
        emit("round", f"round 1/{req.max_rounds}")
        emit("plan", f"planning {req.runs} task variations")
        plan_llm = scoped_llm(llm)
        variation_plan = await run_variation_planner(
            req.task, llm=plan_llm, n=req.runs, url=req.url, pinned=req.variation or None, graph=VARIATION_PLANNER
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
        base = variation_plan.variations[0]
        context = RoundContext(
            task=req.task, url=req.url, runs_per_round=req.runs, max_rounds=req.max_rounds,
            canonical_names=list(base.values), base_values=dict(base.values),
            rounds=[RoundRecord(round=1, variations=list(variation_plan.variations),
                                usage={"plan": usage_of(plan_llm)})],
        )
        store.save_context(context)
        # Fan out: one explore_run task per variation, in parallel up to `req.parallel`
        # (top-level RunnableConfig `max_concurrency`, set in orchestrate()). The runs are
        # independent samples, so nothing is lost by not sequencing them — the read-only
        # HINTS block is the one thing sequencing gave, and it was context, never a step.
        return Command(update={"plan": variation_plan, "context": context},
                       goto=sends(1, variation_plan.variations, 1))

    async def explore_run(state: MultiRunState) -> dict:
        k, round_, variation = state["k"], state["round"], state["variation"]
        scoped = bool(state.get("scoped"))
        url = state.get("start_url") or req.url
        run_dir = store.run_dir(k)
        store.save_variation(k, {**variation.model_dump(), "round": round_, "scoped": scoped})
        run_llm = scoped_llm(llm)  # its own usage counters: tokens stay attributable under --parallel
        hints = ""  # parallel runs have no earlier runs to learn overlay anchors from
        max_attempts = 1 + (req.verify_retries if req.judge else 0)
        attempts, achieved, verdict, traj, suffix = 0, False, None, None, ""
        while True:
            attempts += 1
            task = _variation_task(variation, hints, suffix)
            emit("explore", f"run {k} (round {round_}{', scoped' if scoped else ''}): {variation.task_text}"
                 + (f" (attempt {attempts})" if attempts > 1 else ""))
            async with BrowserSession(headless=req.headless) as session:
                # memory=None → a FRESH ExplorerMemory per attempt: runs are independent samples.
                traj = await run_explorer(
                    session, task, llm=run_llm, url=url, max_steps=req.max_steps, run_dir=run_dir,
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
                traj, variation.task_text, llm=run_llm, params=variation.values, run_dir=run_dir, graph=VERIFIER
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
        usage = usage_of(run_llm)
        store.save_usage(k, usage)
        if usage and usage.get("calls"):
            emit("explore", f"run {k}: LLM usage: {usage['calls']} calls, "
                 f"{usage['input_tokens']:,} input + {usage['output_tokens']:,} output tokens")
        # Fan-in: the list reducers on MultiRunState append this run's results; `merge` runs
        # once, after every explore_run task of the superstep has finished (the
        # explore_run→merge edge), and sorts inputs by run number.
        return {
            "inputs": [RunInput(run=k, trajectory=traj, values=dict(variation.values), achieved=achieved,
                                scoped=scoped)],
            "reports": [{"run": k, "round": round_, "task": variation.task_text, "values": dict(variation.values),
                         "scoped": scoped, "achieved": achieved, "attempts": attempts, "usage": usage,
                         "steps": len(traj.steps), "success": traj.success, "stopped_reason": traj.stopped_reason,
                         "unmet": list(verdict.unmet) if verdict is not None else []}],
        }

    def _round_of(state: MultiRunState) -> int:
        return len(state["context"].rounds)

    async def merge(state: MultiRunState) -> Command[Literal["generate", "__end__"]]:
        context: RoundContext = state["context"]
        round_ = _round_of(state)
        record = context.rounds[-1]
        record.runs = [RunSummary(
            run=r["run"], round=r["round"], task_text=r["task"], values=r["values"], scoped=r["scoped"],
            achieved=r["achieved"], attempts=r["attempts"], success=r["success"], stopped_reason=r["stopped_reason"],
            steps=r["steps"], unmet=r["unmet"], usage=r["usage"],
        ) for r in sorted(state["reports"], key=lambda r: r["run"]) if r["round"] == round_]
        for r in record.runs:
            record.usage[f"run-{r.run}"] = r.usage
        inputs = sorted(state["inputs"], key=lambda i: i.run)  # fan-in arrives in completion order
        achieved = [i for i in inputs if i.achieved and not i.scoped]
        if not achieved:
            record.exit = "unpassable"
            store.save_context(context)
            return Command(update={"context": context, "error": "no run achieved the task — nothing to merge"},
                           goto=END)
        emit("merge", f"merging {len(achieved)}/{len([i for i in inputs if not i.scoped])} achieved runs "
             "(typed-key alignment, pure code)")
        warnings: list[str] = []
        try:
            outcome = merge_trajectories(inputs, name=req.name, warnings=warnings)
        except ValueError as exc:
            record.exit = "error"
            store.save_context(context)
            return Command(update={"context": context, "error": f"merge failed: {exc}"}, goto=END)
        store.save_generalized(outcome.generalized, round_=round_)
        for w in warnings:
            emit("merge", f"WARNING: {w}")
        record.generalized = GeneralizedSummary.from_generalized(outcome.generalized)
        emit("merge", f"fallback artifact: {len(outcome.workflow.transitions)} transitions, "
             f"{len(outcome.workflow.interrupts)} interrupt(s), accept_states={outcome.workflow.accept_states}")
        store.save_context(context)
        return Command(update={"fallback": outcome.workflow, "generalized": outcome.generalized, "context": context},
                       goto="generate")

    async def generate(state: MultiRunState) -> Command[Literal["replay"]]:
        """The generator agent, after the merge, on the merge's alignment: gather → draft →
        materialize ⇄ repair. The merge's artifact is the fallback; the replay stays the gate."""
        context: RoundContext = state["context"]
        round_ = _round_of(state)
        record = context.rounds[-1]
        inputs = sorted(state["inputs"], key=lambda i: i.run)
        prior = context.rounds[:-1]
        last_replay = None
        if prior and prior[-1].replay:
            last_replay = ReplayReport(runs=[ReplayRun(**r.model_dump()) for r in prior[-1].replay],
                                       passed=prior[-1].replay_passed)
        gen_llm = scoped_llm(generator_llm or llm)
        achieved = [i for i in inputs if i.achieved and not i.scoped]
        emit("generate", f"drafting the artifact from {len(achieved)} recording(s) (the generator agent; "
             "the merge's artifact is the fallback)")
        outcome = await run_generator(
            task=req.task, runs=inputs, generalized=state["generalized"], fallback=state["fallback"], llm=gen_llm,
            url=req.url, name=req.name, episodes=list(prior[-1].episodes) if prior else None, replay=last_replay,
            prior=list(prior), graph=GENERATOR,
        )
        record.draft_outcomes = list(outcome.outcomes)
        record.used_fallback = outcome.used_fallback
        record.repairs_used = outcome.repairs_used
        record.validated = outcome.validated
        record.usage["generate"] = usage_of(gen_llm)
        store.save_draft(round_, outcome)
        for o in outcome.outcomes:
            if o.status != "applied":
                emit("generate", f"draft {o.item}{f' ({o.ref})' if o.ref else ''}: {o.status} — {o.reason}")
        for w in outcome.warnings:
            emit("generate", f"WARNING: {w}")
        rate = record.draft_acceptance_rate
        emit("generate", f"draft: {record.draft_applied}/{len(outcome.outcomes)} items applied"
             f"{f' ({rate:.0%})' if rate is not None else ''}, {outcome.repairs_used} repair(s)"
             f"{', FALLBACK to the merge artifact' if outcome.used_fallback else ''}"
             f"{'' if outcome.validated else ', not-validated (no postcondition)'}")
        wf = outcome.workflow
        if req.out is not None:
            dump_workflow(wf, req.out)
        emit("generate", f"compiled {len(wf.transitions)} transitions, {len(wf.states)} states, "
             f"{len(wf.interrupts)} interrupt(s), accept_states={wf.accept_states}")
        for p in wf.params:
            emit("generate", f"param {p.name} (default: {p.default!r}) — {p.description}")
        store.save_context(context)
        return Command(update={"workflow": wf, "context": context}, goto="replay")

    async def replay(state: MultiRunState) -> Command[Literal["triage"]]:
        context: RoundContext = state["context"]
        round_ = _round_of(state)
        wf, gen = state["workflow"], state["generalized"]
        previous_failed = [r.values for rd in context.rounds[:-1] for r in rd.replay if not r.success]
        run_values = {i.run: dict(i.values) for i in state["inputs"] if i.achieved and not i.scoped}
        value_sets = select_replay_sets(wf, gen, list(gen.achieved_runs), previous_failed, run_values=run_values)
        emit("replay", f"zero-LLM replay × {len(value_sets)}: {value_sets}")
        report = await replay_check(wf, value_sets, headless=req.headless, run_dir_base=store.round_dir(round_))
        for r in report.runs:
            emit("replay", f"{'ok' if r.success else 'FAILED'} {r.values} -> states {r.signature}"
                 + (f" ({r.error})" if r.error else ""))
        defaults = value_sets[0]
        unseen = [r for r in report.runs if r.values != defaults]
        unseen_passed = sum(1 for r in unseen if r.success)
        passed = report.passed and bool(unseen) and unseen_passed >= min(2, len(unseen))
        # The regression clause (generator-agent-v2.md §I.3): a round that fixes the targeted value
        # set by breaking one that passed before is not progress.
        previously_passed = [r.values for rd in context.rounds[:-1] for r in rd.replay if r.success]
        regressions = [r.values for r in report.runs if not r.success and r.values in previously_passed]
        if regressions:
            passed = False
            emit("replay", f"REGRESSION: {regressions} passed in an earlier round and failed now")
        record = context.rounds[-1]
        record.replay = ReplaySummary.from_report(report)
        record.replay_passed = passed
        record.unseen_passed = unseen_passed
        if passed:
            emit("replay", f"metamorphic check passed: same state sequence for every value set "
                 f"({unseen_passed} unseen), zero LLM")
        else:
            emit("replay", f"replay check FAILED this round: {[r.signature for r in report.runs]}")
        store.save_context(context)
        return Command(update={"replay": report, "context": context}, goto="triage")

    async def triage(state: MultiRunState) -> Command[Literal["plan_next", "__end__"]]:
        context: RoundContext = state["context"]
        round_ = _round_of(state)
        record = context.rounds[-1]
        verdicts = {r["run"]: type("V", (), {"unmet": r["unmet"]})() for r in state["reports"]}
        inputs = sorted(state["inputs"], key=lambda i: i.run)
        episodes = run_triage(generalized=state["generalized"], replay=state["replay"],
                              runs=[i for i in inputs if not i.scoped], verdicts=verdicts)
        record.episodes = episodes
        store.save_episodes(round_, episodes)
        for e in episodes:
            emit("triage", e.as_line())
        if not episodes:
            emit("triage", "no episodes")
        update: dict[str, Any] = {"context": context}
        if record.replay_passed:
            record.exit = "passed"
            store.save_context(context)
            return Command(update=update, goto=END)
        if any(e.kind == "unpassable" for e in episodes):
            record.exit = "unpassable"
            update["error"] = "triage: unpassable — " + "; ".join(e.detail for e in episodes if e.kind == "unpassable")
            store.save_context(context)
            return Command(update=update, goto=END)
        if round_ >= req.max_rounds:
            record.exit = "max_rounds"
            update["error"] = (f"replay check failed after {round_} round(s): the compiled workflow did not replay "
                               f"identically for every value set ({[r.signature for r in record.replay]})")
            store.save_context(context)
            return Command(update=update, goto=END)
        store.save_context(context)
        return Command(update=update, goto="plan_next")

    async def plan_next(state: MultiRunState) -> Command[Literal["explore_run", "__end__"]]:
        context: RoundContext = state["context"]
        round_ = _round_of(state)
        record = context.rounds[-1]
        plan_llm = scoped_llm(llm)
        emit("plan", f"planning round {round_ + 1} from {len(record.episodes)} episode(s)")
        next_plan = await run_next_round_planner(context, llm=plan_llm, graph=NEXT_ROUND_PLANNER)
        record.next_plan = next_plan
        record.usage["plan_next"] = usage_of(plan_llm)
        store.save_next_plan(round_, next_plan)
        for v in next_plan.next_variations:
            vals = ", ".join(f"{k}={val!r}" for k, val in v.values.items()) or "(no values)"
            emit("plan", f"next variation: {v.task_text} [{vals}]")
        for st in next_plan.scoped_subtasks:
            emit("plan", f"scoped sub-task: {st.task_text} @ {st.start_url}")
        for note in next_plan.notes:
            emit("plan", f"note: {note}")
        if not next_plan.next_variations and not next_plan.scoped_subtasks:
            record.exit = "no_next_runs"
            store.save_context(context)
            return Command(update={"context": context,
                                   "error": f"replay check failed and the planner proposed no round {round_ + 1} runs"},
                           goto=END)
        first_k = max(i.run for i in state["inputs"]) + 1
        variations = list(next_plan.next_variations) + [
            TaskVariation(task_text=st.task_text, values=dict(st.values)) for st in next_plan.scoped_subtasks]
        context.rounds.append(RoundRecord(round=round_ + 1, variations=variations))
        store.save_context(context)
        emit("round", f"round {round_ + 1}/{req.max_rounds}: {len(next_plan.next_variations)} variation(s), "
             f"{len(next_plan.scoped_subtasks)} scoped sub-task(s)")
        return Command(
            update={"context": context},
            goto=sends(round_ + 1, next_plan.next_variations, first_k, next_plan.scoped_subtasks),
        )

    return (
        StateGraph(MultiRunState)
        .add_node("plan", plan)
        .add_node("explore_run", explore_run)
        .add_node("merge", merge)
        .add_node("generate", generate)
        .add_node("replay", replay)
        .add_node("triage", triage)
        .add_node("plan_next", plan_next)
        .add_edge(START, "plan")
        .add_edge("explore_run", "merge")
        .compile()
    )


async def orchestrate(req: GenerateRequest, llm: LLM, listen: Listener | None = None, *,
                      generator_llm: LLM | None = None) -> GenerateResult:
    """Run the pipeline. `runs=1`: explore → verify → generate → replay (the single-run gate). `runs>1`:
    plan variations → explore ×N (verify per run) → typed merge → the generator agent → zero-LLM
    replay check. `generator_llm`: the generator agent's own model (None: `llm`)."""
    if req.runs == 1:
        graph = build_orchestration_graph(req, llm, listen)
        final = await graph.ainvoke({})
        return GenerateResult(
            trajectory=final.get("trajectory"),
            workflow=final.get("workflow"),
            verdict=final.get("verdict"),
            replay=final.get("replay"),
            error=final.get("error"),
        )
    graph = build_multi_orchestration_graph(req, llm, listen, generator_llm=generator_llm)
    # `max_concurrency` is a TOP-LEVEL config key (pregel reads it there, not from
    # `configurable`); it bounds how many explore_run Send tasks — browsers — run at once.
    final = await graph.ainvoke({}, config={
        "recursion_limit": (4 * req.runs + 20) * req.max_rounds, "max_concurrency": req.parallel,
    })
    inputs = final.get("inputs") or []
    spine = next((i.trajectory for i in inputs if i.achieved and not i.scoped), None)
    context = final.get("context")
    return GenerateResult(
        trajectory=spine,
        workflow=final.get("workflow"),
        error=final.get("error"),
        variations=final.get("plan"),
        run_reports=sorted(final.get("reports") or [], key=lambda r: r["run"]),
        generalized=final.get("generalized"),
        replay=final.get("replay"),
        context=context,
        rounds=len(context.rounds) if context is not None else 0,
        episodes=list(context.rounds[-1].episodes) if context is not None and context.rounds else [],
    )
