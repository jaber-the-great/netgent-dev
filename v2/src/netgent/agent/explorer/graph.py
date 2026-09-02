"""The browser agent's loop as a LangGraph StateGraph — functions + ONE compiled graph.

    START → observe → decide → act → observe → …
                 │        │
                 │        ├─ done ──────► END
                 └─ stuck ───────────► END        (budget exhausted: observe ─► END)

Three async node functions route with `Command`, so each node both updates state and picks
the next node. `EXPLORER` is compiled once at import; what a run needs (the live session,
the LLM, the cross-run memory, the knobs) travels as `Runtime.context` — an ExplorerContext —
which LangGraph never checkpoints, so nothing un-serializable is in state
(docs/research/langgraph-agent-structure.md §3a). `explore()` is the one run API. Semantics
are exactly the former hand-written loop: one snapshot per step, observation-based stuck
detection, invalid LLM output costs a step but never crashes, failures echoed into history,
and the step budget.

This module is the ONLY place in the explorer that imports langgraph at module level; nothing
in `netgent.agent.__init__` imports it eagerly, so the `generate` extra stays optional.
"""

import asyncio
import operator
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command

from netgent.agent.explorer.actions import to_action
from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.decision import DEFAULT_KINDS, TERMINATES_BATCH
from netgent.agent.explorer.memory import ExplorerMemory
from netgent.agent.explorer.models import AgentStep, AgentTrajectory, StepRecord
from netgent.agent.explorer.prompt import build_system_prompt
from netgent.browser.dom import element_lines, format_observation, media_line
from netgent.browser.locators import capture_locator, durable_locator
from netgent.browser.session import BrowserSession
from netgent.core.errors import ExecutionError
from netgent.core.logger import get_logger
from netgent.schema.actions import GotoAction, WaitAction

if TYPE_CHECKING:
    from netgent.agent.llm import LLM

logger = get_logger(__name__)

MAX_REPEAT = 3  # consecutive steps with an unchanged observation → declare stuck
SETTLE_WATCH_S = 6.0
# The same action on the same target, over and over, while the page keeps changing in
# irrelevant ways (a video timer, live chat) defeats observation-equality stuck detection —
# measured: 12 consecutive clicks on one ad overlay on YouTube. Nudge at REPEAT_NUDGE, stop at
# REPEAT_STOP (browser-use's "repeated failure" guard, tool-calling doc §5.2).
REPEAT_NUDGE = 3
REPEAT_STOP = 6  # how long after an action the page is sampled for text that appears (then vanishes)


def _media_of(snapshot) -> str | None:
    """The snapshot's playback state as one compact string for the step record (verifier
    evidence): 'video PLAYING at 0:21 / 8:35'. None when the page has no observed media."""
    return "; ".join(media_line(m) for m in snapshot.media[:3]) or None


async def _watch_texts(
    session: BrowserSession, known: set[str], seconds: float, found: list[str], frame_filter: list[str] | None = None
) -> None:
    """Sample the page for NEW text for `seconds`, appending finds to `found` (alerts first).

    Success banners are often transient: Formik's shows 1 s after Submit and hides 3 s later,
    inside the window the LLM spends deciding the next step — so a single snapshot per step
    misses it and the agent re-submits (measured, headed sweep). Sampling while the model
    thinks (and during a `wait`) costs no latency; whatever appeared is fed back as a note and
    into `texts_seen`, which post-run verification reads. Read-only DOM walks; never blocks a
    dispatch (a snapshot that fails mid-navigation is simply skipped)."""
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            snap = await session.snapshot(drain_dialogs=False)  # peek: leave dialogs for observe()
            if frame_filter is not None:  # a sweep: ONLY this form's frame, never a neighbour's banner
                snap = snap.scoped_to(frame_filter)
        except Exception:  # noqa: BLE001 — mid-navigation: try again on the next tick
            await asyncio.sleep(0.5)
            continue
        for t in sorted(snap.texts, key=lambda t: not t.alert):
            if t.text not in known:
                known.add(t.text)
                found.append(t.text)
        await asyncio.sleep(0.6)


class AgentState(TypedDict, total=False):
    n: int  # step number of the step being worked on
    snapshot: Any  # DomSnapshot for the current step
    observation: str
    prev_observation: str | None  # the diff-free rendering of the previous step (equality check)
    prev_keys: dict[str, str] | None  # element key → rendered line of the previous snapshot (the diff)
    prev_texts: set[str] | None  # text blocks of the previous snapshot (NEW TEXT section)
    prev_url: str | None
    no_progress: int
    texts_seen: list[str]
    decision: Any  # AgentDecision for the current step
    steps: Annotated[list[AgentStep], operator.add]  # the trajectory, appended per step
    last_action_key: str  # "kind|index|text" of the previous step's first action
    repeat_count: int  # consecutive steps with the same first action
    success: bool
    stopped_reason: str


async def observe(state: AgentState, runtime: Runtime[ExplorerContext]) -> Command[Literal["decide", "__end__"]]:
    ctx = runtime.context  # the kwarg MUST be named `runtime` (langgraph/_internal/_runnable.py:230-243)
    n = state.get("n", 0) + 1
    if n > ctx.max_steps:
        return Command(update={"stopped_reason": f"reached max_steps={ctx.max_steps}"}, goto=END)
    snapshot = await ctx.session.snapshot()
    if ctx.frame_filter is not None:  # focus on one form (iframe) for a sweep
        snapshot = snapshot.scoped_to(ctx.frame_filter)
    # The diff-free rendering is what stuck detection compares; the model gets the diffed
    # one only with NETGENT_OBS_DIFF=1 — OFF by default, by measurement: the `*` markers and
    # new-text section (with the memory fields) cost +45% calls on the 21-form sweep for a
    # lower score and changed nothing on the challenge (explorer-optimisation.md §2). The
    # diff is suppressed across a navigation so a new page is not starred wholesale.
    plain = format_observation(snapshot)
    same_page = state.get("prev_url") == snapshot.url and diff_enabled()
    observation = format_observation(
        snapshot,
        previous=state.get("prev_keys") if same_page else None,
        previous_texts=state.get("prev_texts") if same_page else None,
    )

    # Accumulate every text observed during the run: success banners are often transient
    # (hidden again after ~3 s), so post-run verification must be able to check what was
    # SEEN, not only what is still on screen (sweep._form_succeeded).
    seen = list(state.get("texts_seen") or [])
    known = set(seen)
    fresh = [t.text for t in snapshot.texts if t.text not in known]

    # Stuck detection is observation-based: an action that changes nothing on screen
    # makes no progress; a scroll that reveals a new batch does change it. The rendered
    # slice caps visible text, so a page changing OUTSIDE that slice (an ad's captions,
    # a live ticker) can compare byte-equal while demonstrably alive — never-seen text
    # is the tiebreaker (measured: 'stuck: no change on screen' fired mid-ad while
    # texts_seen was recording the ad's captions advancing).
    prev = state.get("prev_observation")
    no_progress = state.get("no_progress", 0)
    if prev is not None:
        no_progress = no_progress + 1 if plain == prev and not fresh else 0
    # Deliberately NOT written back into the step record: telling the model "no visible
    # change" made it re-run the action whenever the change was invisible to the walker
    # (measured, explorer-optimisation.md); the hard stop below stays.
    if no_progress >= MAX_REPEAT:
        reason = f"stuck: {MAX_REPEAT} steps with no change on screen"
        stop = AgentStep(n=n, kind="done", reasoning=reason, url=snapshot.url, error=reason,
                         media=_media_of(snapshot), t=snapshot.taken_at or time.time())
        return Command(update={"n": n, "steps": [stop], "stopped_reason": reason}, goto=END)
    seen += fresh[:50]
    return Command(
        update={
            "n": n,
            "snapshot": snapshot,
            "observation": observation,
            "prev_observation": plain,
            "prev_keys": element_lines(snapshot),
            "prev_texts": {t.text for t in snapshot.texts},
            "prev_url": snapshot.url,
            "no_progress": no_progress,
            "texts_seen": seen[-400:],
        },
        goto="decide",
    )

async def decide(state: AgentState, runtime: Runtime[ExplorerContext]) -> Command[Literal["act", "observe", "__end__"]]:
    ctx = runtime.context
    system_prompt = build_system_prompt(ctx.allowed_kinds, ctx.max_actions_per_step)
    n = state["n"]
    # Text the settle watcher caught after the last action that has since VANISHED (still
    # visible text is already in the observation): tell the model before it decides.
    seen = list(state.get("texts_seen") or [])
    gone = [t for t in ctx.memory.drain_noticed() if t not in (state.get("prev_texts") or set())]
    if gone:
        seen += [t for t in gone if t not in seen]
        ctx.memory.history.append(StepRecord(
            n=n, kind="note",
            note=f"{n}. appeared after your previous action and has since vanished: "
            + " | ".join(t[:120] for t in gone[:6]),
        ))
    try:
        decision = await ctx.llm.decide(
            system_prompt, ctx.task, state["observation"], ctx.memory.history,
            allowed_kinds=ctx.allowed_kinds, max_actions=ctx.max_actions_per_step,
        )
    except Exception as exc:  # noqa: BLE001 — a bad LLM response shouldn't crash the run
        logger.warning("step %d: LLM decision failed: %s", n, exc)
        ctx.memory.history.append(StepRecord(n=n, kind="invalid", outcome="invalid", error=str(exc)[:200],
                                  reasoning="(your last response was invalid) — return a valid decision"))
        # not a no-change step
        return Command(update={"prev_observation": None, "texts_seen": seen[-400:]}, goto="observe")
    logger.info("step %d: %s — %s", n, "done" if decision.done else decision.kind, decision.reasoning)

    if decision.done:
        step = AgentStep(n=n, kind="done", reasoning=decision.reasoning, url=state["snapshot"].url,
                         media=_media_of(state["snapshot"]), t=state["snapshot"].taken_at or time.time())
        return Command(
            update={
                "steps": [step],
                "success": decision.success,
                "stopped_reason": decision.reasoning,
                "texts_seen": seen[-400:],
            },
            goto=END,
        )
    return Command(update={"decision": decision, "texts_seen": seen[-400:]}, goto="act")

async def act(state: AgentState, runtime: Runtime[ExplorerContext]) -> Command[Literal["observe", "__end__"]]:
    """Execute the decision's action(s) — one AgentStep per EXECUTED item, so a batch of
    three fills compiles to three transitions exactly as three single steps would.
    Two guards end a batch early (browser-use multi_act, Skyvern agent.py:3209): a static
    one (TERMINATES_BATCH kinds) and a runtime one (the URL changed → the pre-batch
    snapshot's indices mean nothing). A failed item aborts the remainder; the model is told
    which items did not run."""
    ctx = runtime.context
    n, decision, snapshot = state["n"], state["decision"], state["snapshot"]
    items = decision.actions()[:ctx.max_actions_per_step]
    steps: list[AgentStep] = []
    seen = list(state.get("texts_seen") or [])
    known = set(seen) | {t.text for t in snapshot.texts}
    # Repeated-action guard (see REPEAT_NUDGE).
    first = items[0] if items else None
    key = f"{first.kind}|{first.index}|{first.text or first.value or first.url or ''}" if first else ""
    repeat = state.get("repeat_count", 0) + 1 if key and key == state.get("last_action_key") else 1
    if repeat >= REPEAT_STOP:
        reason = f"stuck: repeated the same action {repeat} times ({first.kind} on element {first.index})"
        stop = AgentStep(n=n, kind="done", reasoning=reason, url=ctx.session.page.url, error=reason)
        return Command(update={"steps": [stop], "stopped_reason": reason, "texts_seen": seen[-400:]}, goto=END)
    if repeat >= REPEAT_NUDGE:
        ctx.memory.history.append(StepRecord(
            n=n, kind="note",
            note=f"{n}. you have now issued the SAME action {repeat} times ({first.kind} on [{first.index}]) "
            "and the goal is still not reached — it is not working. Do something different, or if the "
            "ctx.task's outcome is already visible, declare done.",
        ))
    for i, item in enumerate(items):
        if i > 0:
            if ctx.session.page.url != steps[-1].url or ctx.session.page.url != snapshot.url:
                ctx.memory.history.append(StepRecord(
                    n=n, kind="note", note=f"{n}. page changed after action {i}: {len(items) - i} queued "
                    "action(s) were skipped — decide again from the new observation",
                ))
                break
        error = None
        action = None
        note = None
        try:
            if item.kind not in ctx.allowed_kinds:
                raise ValueError(
                    f"{item.kind} is not available in this task; use one of "
                    f"{', '.join(sorted(ctx.allowed_kinds))}"
                )
            upload = upload_path(ctx) if item.kind == "upload" else None
            # Verified per item, against the live page: items 2..k run after the page may
            # have re-rendered, so the R1/R4 check must not reuse item 1's probe.
            locator_for, note = await _verified_locator(ctx.session, snapshot, item.index)
            action = to_action(item, snapshot, upload_path=upload, locator_for=locator_for)
            # Carry the closed-shadow capability flag from the chosen element onto the action,
            # so a plain-Playwright replayer refuses instead of timing out (R8).
            elems = snapshot.interactive()
            if item.index is not None and 0 <= item.index < len(elems):
                if elems[item.index].requires_closed_shadow and hasattr(action, "requires_closed_shadow"):
                    action = action.model_copy(update={"requires_closed_shadow": True})
            if isinstance(action, WaitAction):
                # Watch WHILE waiting: the dwell is exactly when a banner comes and goes.
                watch = asyncio.create_task(
                    _watch_texts(ctx.session, known, action.seconds, ctx.memory.noticed, ctx.frame_filter)
                )
                try:
                    await ctx.session.dispatch(action)
                finally:
                    watch.cancel()
                    await asyncio.gather(watch, return_exceptions=True)
                during = ctx.memory.drain_noticed()
                if during:
                    seen += [t for t in during if t not in seen]
                    ctx.memory.history.append(StepRecord(
                        n=n, kind="note",
                        note=f"{n}. appeared on the page during the wait: "
                        + " | ".join(t[:120] for t in during[:6]),
                    ))
            else:
                await ctx.session.dispatch(action)
        except (ExecutionError, ValueError) as exc:
            error = str(exc)
            logger.warning("step %d.%d failed: %s", n, i, error)

        step = AgentStep(
            n=n, item=i, kind=item.kind or "", reasoning=decision.reasoning, url=ctx.session.page.url, error=error,
            evaluation=decision.evaluation, memory=decision.memory, next_goal=decision.next_goal,
            media=_media_of(snapshot), t=snapshot.taken_at or time.time(),
        )
        if error is None:
            step.action = action  # the compilable record of what actually ran
            step.locator_check = note
            step.dialogs = ctx.session.dialogs_since_last_action()  # THIS item's own dialogs (per item)
        await capture_screenshot(ctx, step)
        steps.append(step)
        # Feed outcomes back so the agent recovers instead of repeating itself.
        record = StepRecord(
            n=n, kind=item.kind or "", index=item.index, target=_target_label(snapshot, item.index),
            reasoning=decision.reasoning if i == 0 else f"(batched action {i + 1} of {len(items)})",
            error=error, outcome="failed" if error else "ok",
            evaluation=decision.evaluation if i == 0 else "", memory=decision.memory if i == 0 else "",
            next_goal=decision.next_goal if i == 0 else "",
        )
        if error is None and isinstance(action, WaitAction):
            record.outcome, record.error = "waited", f"you already watched/waited {action.seconds:g}s"
        ctx.memory.history.append(record)
        if error is not None:
            if i + 1 < len(items):
                ctx.memory.history.append(StepRecord(
                    n=n, kind="note", note=f"{n}. action {i + 1} failed, so {len(items) - i - 1} queued "
                    "action(s) were skipped",
                ))
            break  # a failed item aborts the remainder (universal across the survey)
        if item.kind in TERMINATES_BATCH:
            break
    # Keep sampling while the next observation is rendered and the model decides.
    if steps and steps[-1].error is None and not isinstance(steps[-1].action, WaitAction):
        ctx.memory.start_watch(
            _watch_texts(ctx.session, known, SETTLE_WATCH_S, ctx.memory.noticed, ctx.frame_filter)
        )
    drained = ctx.memory.drain_noticed()
    seen += [t for t in drained if t not in seen]
    return Command(
        update={"steps": steps, "texts_seen": seen[-400:], "last_action_key": key, "repeat_count": repeat},
        goto="observe",
    )


def create_explorer_agent() -> CompiledStateGraph:
    """Build and compile the observe → decide → act graph. Mirrors `create_agent` /
    `create_react_agent`: a function returning a compiled graph, nodes reading their run
    dependencies from `Runtime[ExplorerContext]`. Called once at import (`EXPLORER`)."""
    return (
        StateGraph(AgentState, context_schema=ExplorerContext)
        .add_node("observe", observe)
        .add_node("decide", decide)
        .add_node("act", act)
        .add_edge(START, "observe")
        .compile(name="explorer")
    )


EXPLORER = create_explorer_agent()  # compiled ONCE — Studio-, xray- and langgraph.json-visible


async def explore(
    session: BrowserSession,
    task: str,
    *,
    llm: "LLM",
    memory: ExplorerMemory | None = None,
    url: str | None = None,
    frame_filter: list[str] | None = None,
    max_steps: int = 25,
    run_dir: Path | None = None,
    allowed_kinds: frozenset[str] | set[str] = DEFAULT_KINDS,
    max_actions_per_step: int = 1,
    upload_file: Path | None = None,
    graph: CompiledStateGraph | None = None,
) -> AgentTrajectory:
    """The ONE run API: `ExplorerAgent.run`, the sweep, the stress eval and the orchestrator's
    explore node all end here. Navigates to `url` (recorded as step 0), runs the compiled
    explorer (`graph`, default EXPLORER — pass one compiled with a checkpointer to persist)
    with the per-run dependencies in `context=`, then assembles the trajectory: steps, texts
    seen (including what the settle watcher caught), the final observation scoped like the
    run, and this run's dialogs. `memory` is shared across calls for a sweep (default: fresh)."""
    graph = EXPLORER if graph is None else graph
    memory = memory or ExplorerMemory()
    traj = AgentTrajectory(task=task)
    dialog_mark = len(session.dialogs_seen())  # only THIS run's dialogs are its evidence
    if url:
        await session.page.goto(url)
        # Record the starting navigation as a real step, so a compiled workflow
        # begins with this goto instead of assuming an already-open page.
        traj.steps.append(
            AgentStep(n=0, kind="goto", reasoning="starting URL", url=session.page.url, action=GotoAction(url=url))
        )

    ctx = ExplorerContext(
        session=session, llm=llm, memory=memory, task=task, max_steps=max_steps, frame_filter=frame_filter,
        allowed_kinds=frozenset(allowed_kinds), max_actions_per_step=max_actions_per_step, run_dir=run_dir,
        upload_file=upload_file,
    )
    # Each loop iteration is up to three graph steps (observe, decide, act); the
    # recursion limit is a backstop above the agent's own step budget, never the cap.
    final = await graph.ainvoke({"steps": []}, config={"recursion_limit": 3 * max_steps + 8}, context=ctx)

    traj.steps.extend(final.get("steps", []))
    traj.success = bool(final.get("success", False))
    traj.stopped_reason = final.get("stopped_reason", "")
    memory.stop_watch()
    traj.texts_seen = list(final.get("texts_seen") or [])
    traj.texts_seen += [t for t in memory.drain_noticed() if t not in traj.texts_seen]
    try:  # the final page, for the verifier — scoped like the run was
        snap = await session.snapshot()
        if frame_filter is not None:
            snap = snap.scoped_to(frame_filter)
        traj.final_observation = format_observation(snap)
        traj.final_url = snap.url
    except Exception:  # noqa: BLE001 — a page mid-navigation: leave the evidence empty
        pass
    traj.dialogs = list(session.dialogs_seen())[dialog_mark:]

    if run_dir is not None:
        _write_trajectory(run_dir, traj)
    return traj



def upload_path(ctx: ExplorerContext) -> str:
    """The file offered to a file input: the caller's, else a sample created on demand."""
    if ctx.upload_file is not None:
        return str(ctx.upload_file)
    sample = Path(tempfile.gettempdir()) / "netgent-upload-sample.txt"
    if not sample.exists():
        sample.write_text("netgent sample upload\n")
    return str(sample)


async def capture_screenshot(ctx: ExplorerContext, step: AgentStep) -> None:
    """Best-effort per-step screenshot into the run dir (never fails the run)."""
    if ctx.run_dir is None:
        return
    rel = f"screenshots/step-{step.n:02d}{f'-{step.item}' if step.item else ''}.png"
    try:
        await ctx.session.screenshot(ctx.run_dir / rel)
        step.screenshot = rel
    except Exception:  # noqa: BLE001 — a screenshot must never fail the run
        pass


def _write_trajectory(run_dir: Path, traj: AgentTrajectory) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trajectory.json").write_text(traj.model_dump_json(indent=2) + "\n")


def diff_enabled() -> bool:
    return os.getenv("NETGENT_OBS_DIFF", "0") == "1"


def _target_label(snapshot, index: int | None) -> str:
    """A name for the acted element that survives index renumbering: its accessible name,
    else tag[type]. Empty for page-level actions."""
    elems = snapshot.interactive()
    if index is None or not (0 <= index < len(elems)):
        return ""
    el = elems[index]
    return el.name or (f"{el.tag}[{el.type}]" if el.type else el.tag)


async def _verified_locator(session: BrowserSession, snapshot, index: int | None):
    """(locator builder, provenance note) for the chosen element, verified against the live
    page: unique (R1) and cross-checked with Playwright's own generator (R4).

    Resolution is async (it counts matches in the browser) while `to_action` is pure, so
    the chain is built here and handed in. Any failure falls back to the unverified chain.
    """
    elems = snapshot.interactive()
    if index is None or not (0 <= index < len(elems)):
        return durable_locator, None
    try:
        chain, note = await capture_locator(session, elems[index])
    except Exception as exc:  # noqa: BLE001 — verification is best-effort; dispatch fails loudly
        logger.warning("locator verification failed for element %d: %s", index, exc)
        return durable_locator, f"verification failed: {exc}"
    return (lambda _el: chain), note
