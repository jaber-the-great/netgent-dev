"""The generator as a LangGraph StateGraph — functions + ONE compiled graph, the explorer's shape.

    START → gather → draft → materialize → {END | repair → materialize …}   (repairs ≤ max_repairs)

`gather` is pure: recordings + the merge's trail + episodes + replay + prior rounds → Evidence.
`draft` is the one LLM call: Evidence in, WorkflowDraft out. `materialize` is pure: the draft is
resolved against the recordings, every rejection recorded, never fatal. `repair` (bounded) feeds
the rejections back verbatim — CEGIS with the materializer as the counter-example generator
(docs/research/generator-agent-v2.md §A.1, §K.5). The recordings, the fallback artifact and the
LLM travel as `Runtime.context` (a GeneratorContext), never in state. `generate()` is the one run
API. A draft that fails to arrive (a seam error, a script without drafts) yields the merge's
artifact with a warning: the worst case is today's output.

This module imports langgraph at module level; `netgent.agent.generator` resolves it lazily.
"""

from typing import TYPE_CHECKING, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from netgent.agent.generator.context import MAX_REPAIRS, GeneratorContext
from netgent.agent.generator.draft import WorkflowDraft
from netgent.agent.generator.evidence import Evidence, gather_evidence
from netgent.agent.generator.materialize import materialize as run_materialize
from netgent.agent.generator.models import GenerateOutcome
from netgent.agent.generator.prompt import (
    GENERATOR_SYSTEM,
    REPAIR_SYSTEM,
    build_generator_content,
    build_repair_content,
)
from netgent.core.logger import get_logger

if TYPE_CHECKING:
    from netgent.agent.generator.merge import GeneralizedTrajectory, RunInput
    from netgent.agent.llm import LLM
    from netgent.agent.replay import ReplayReport
    from netgent.agent.rounds import RoundRecord
    from netgent.agent.triage import Episode
    from netgent.schema.workflow import Workflow

logger = get_logger(__name__)


class GeneratorState(TypedDict, total=False):
    evidence: Any  # Evidence (gather's output) — pure, cacheable, no LLM
    draft: Any  # WorkflowDraft (the LLM's output)
    outcome: Any  # GenerateOutcome: workflow + per-item DraftOutcomes + warnings
    rejections: list[str]  # what materialize refused, verbatim, for the repair turn
    repairs: int
    notes: list[str]  # repair-loop bookkeeping folded into the final outcome's warnings


def _fallback_outcome(ctx: GeneratorContext, draft: WorkflowDraft | None, reason: str) -> GenerateOutcome:
    return GenerateOutcome(workflow=ctx.fallback, draft=draft, warnings=[f"fallback to the merge's artifact: {reason}"],
                           used_fallback=True, validated=bool(ctx.fallback.accept_states))


async def gather(state: GeneratorState, runtime: Runtime[GeneratorContext]) -> dict:
    """Recordings + merge trail + episodes + replay + prior → Evidence. Pure."""
    return {"evidence": gather_evidence(runtime.context)}


async def draft(state: GeneratorState, runtime: Runtime[GeneratorContext],
                ) -> Command[Literal["materialize", "__end__"]]:
    """Evidence → WorkflowDraft: the one LLM call, through the agent's LLM seam."""
    ctx = runtime.context
    ev: Evidence = state["evidence"]
    if ctx.llm is None:
        return Command(update={"outcome": _fallback_outcome(ctx, None, "no LLM configured")}, goto=END)
    try:
        got = await ctx.llm.judge(GENERATOR_SYSTEM, build_generator_content(ev), WorkflowDraft)
    except Exception as exc:  # noqa: BLE001 — a seam failure must not lose the merge's artifact
        logger.warning("generator draft failed: %s", exc)
        return Command(update={"outcome": _fallback_outcome(ctx, None, f"the draft call failed: {exc}")}, goto=END)
    if not isinstance(got, WorkflowDraft):
        return Command(update={"outcome": _fallback_outcome(ctx, None, "the model returned no draft")}, goto=END)
    return Command(update={"draft": got, "repairs": 0}, goto="materialize")


def _rank(o: GenerateOutcome) -> tuple[int, int]:
    """Lower is better: a fallback loses to any materialized draft; then fewer rejections."""
    return (1 if o.used_fallback else 0, len(o.rejections))


def _issues(o: GenerateOutcome) -> list[str]:
    """What the repair turn is told: the rejections, plus the reason a draft was discarded."""
    return [*o.rejections, *(w for w in o.warnings if w.startswith("fallback to"))]


async def materialize(state: GeneratorState, runtime: Runtime[GeneratorContext],
                      ) -> Command[Literal["repair", "__end__"]]:
    """WorkflowDraft + recordings → Workflow + outcomes. Routes to END when nothing was rejected
    or the repair budget is spent; else to repair. Keeps the better of the previous and the
    repaired outcome (no fallback, then fewer rejections; the later one on a tie)."""
    ctx = runtime.context
    repairs = state.get("repairs", 0)
    outcome = run_materialize(state["draft"], ctx)
    outcome.repairs_used = repairs
    draft_ = state["draft"]
    notes = list(state.get("notes") or [])
    previous: GenerateOutcome | None = state.get("outcome")
    if previous is not None and _rank(outcome) > _rank(previous):
        notes.append(f"repair {repairs} was worse (fallback={outcome.used_fallback}, {len(outcome.rejections)} "
                     f"rejection(s)); kept the previous draft")
        outcome = previous.model_copy(update={"repairs_used": repairs})
        draft_ = previous.draft
    issues = _issues(outcome)
    done = not issues or repairs >= ctx.max_repairs or ctx.llm is None
    if done and notes:
        outcome = outcome.model_copy(update={"warnings": [*outcome.warnings, *notes]})
    return Command(update={"outcome": outcome, "rejections": issues, "draft": draft_, "notes": notes},
                   goto=END if done else "repair")


async def repair(state: GeneratorState, runtime: Runtime[GeneratorContext],
                 ) -> Command[Literal["materialize", "__end__"]]:
    """The rejections, verbatim, plus the surviving draft → a revised WorkflowDraft (≤ max_repairs calls)."""
    ctx = runtime.context
    content = build_repair_content(state["evidence"], state["draft"], state["rejections"])
    try:
        got = await ctx.llm.judge(REPAIR_SYSTEM, content, WorkflowDraft)
    except Exception as exc:  # noqa: BLE001 — keep the outcome we have
        logger.warning("generator repair failed: %s", exc)
        got = None
    if not isinstance(got, WorkflowDraft):
        outcome: GenerateOutcome = state["outcome"]
        outcome.warnings.append("the repair turn returned no draft; kept the previous outcome")
        return Command(update={"outcome": outcome}, goto=END)
    return Command(update={"draft": got, "repairs": state.get("repairs", 0) + 1}, goto="materialize")


def create_generator_agent() -> CompiledStateGraph:
    """Build and compile gather → draft → materialize ⇄ repair. Same shape as `create_verifier_agent`."""
    return (
        StateGraph(GeneratorState, context_schema=GeneratorContext)
        .add_node("gather", gather)
        .add_node("draft", draft)
        .add_node("materialize", materialize)
        .add_node("repair", repair)
        .add_edge(START, "gather")
        .add_edge("gather", "draft")
        .compile(name="generator")
    )


GENERATOR = create_generator_agent()  # compiled ONCE


async def generate(
    *,
    task: str,
    runs: list["RunInput"],
    generalized: "GeneralizedTrajectory",
    fallback: "Workflow",
    llm: "LLM | None",
    url: str | None = None,
    name: str = "workflow",
    version: str = "1",
    episodes: list["Episode"] | None = None,
    replay: "ReplayReport | None" = None,
    prior: list["RoundRecord"] | None = None,
    max_repairs: int = MAX_REPAIRS,
    graph: CompiledStateGraph | None = None,
) -> GenerateOutcome:
    """The ONE run API: draft the artifact from the recordings, on the merge's alignment, with the
    merge's artifact as the fallback. `graph` defaults to GENERATOR."""
    graph = GENERATOR if graph is None else graph
    ctx = GeneratorContext(task=task, runs=tuple(runs), generalized=generalized, fallback=fallback, llm=llm, url=url,
                           name=name, version=version, episodes=tuple(episodes or ()), replay=replay,
                           prior=tuple(prior or ()), max_repairs=max_repairs)
    final = await graph.ainvoke({}, context=ctx)
    return final["outcome"]
