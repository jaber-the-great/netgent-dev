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

import asyncio
import operator
import os
from typing import Annotated, Any, Literal, TypedDict

from netgent.agent.explorer.actions import to_action
from netgent.agent.explorer.browser_agent import MAX_REPEAT, AgentStep, BrowserAgent, StepRecord
from netgent.agent.explorer.decision import TERMINATES_BATCH
from netgent.agent.explorer.prompt import build_system_prompt
from netgent.browser.dom import element_lines, format_observation
from netgent.browser.locators import capture_locator, durable_locator
from netgent.browser.session import BrowserSession
from netgent.core.errors import ExecutionError
from netgent.core.logger import get_logger
from netgent.schema.actions import WaitAction

logger = get_logger(__name__)

SETTLE_WATCH_S = 6.0  # how long after an action the page is sampled for text that appears (then vanishes)


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
            snap = await session.snapshot()
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
    allowed = agent.allowed_kinds
    max_actions = agent.max_actions_per_step
    system_prompt = build_system_prompt(allowed, max_actions)

    async def observe(state: AgentState) -> Command[Literal["decide", "__end__"]]:
        n = state.get("n", 0) + 1
        if n > max_steps:
            return Command(update={"stopped_reason": f"reached max_steps={max_steps}"}, goto=END)
        snapshot = await session.snapshot()
        if frame_filter is not None:  # focus on one form (iframe) for a sweep
            snapshot = snapshot.scoped_to(frame_filter)
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

        # Stuck detection is observation-based: an action that changes nothing on screen
        # makes no progress; a scroll that reveals a new batch does change it.
        prev = state.get("prev_observation")
        no_progress = state.get("no_progress", 0)
        if prev is not None:
            no_progress = no_progress + 1 if plain == prev else 0
        # Deliberately NOT written back into the step record: telling the model "no visible
        # change" made it re-run the action whenever the change was invisible to the walker
        # (measured, explorer-optimisation.md); the hard stop below stays.
        if no_progress >= MAX_REPEAT:
            reason = f"stuck: {MAX_REPEAT} steps with no change on screen"
            stop = AgentStep(n=n, kind="done", reasoning=reason, url=snapshot.url, error=reason)
            return Command(update={"n": n, "steps": [stop], "stopped_reason": reason}, goto=END)
        # Accumulate every text observed during the run: success banners are often transient
        # (hidden again after ~3 s), so post-run verification must be able to check what was
        # SEEN, not only what is still on screen (sweep._form_succeeded).
        seen = list(state.get("texts_seen") or [])
        known = set(seen)
        seen += [t.text for t in snapshot.texts if t.text not in known][:50]
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

    async def decide(state: AgentState) -> Command[Literal["act", "observe", "__end__"]]:
        n = state["n"]
        # Text the settle watcher caught after the last action that has since VANISHED (still
        # visible text is already in the observation): tell the model before it decides.
        seen = list(state.get("texts_seen") or [])
        gone = [t for t in agent.drain_noticed() if t not in (state.get("prev_texts") or set())]
        if gone:
            seen += [t for t in gone if t not in seen]
            history.append(StepRecord(
                n=n, kind="note",
                note=f"{n}. appeared after your previous action and has since vanished: "
                + " | ".join(t[:120] for t in gone[:6]),
            ))
        try:
            decision = await llm.decide(
                system_prompt, task, state["observation"], history, allowed_kinds=allowed, max_actions=max_actions
            )
        except Exception as exc:  # noqa: BLE001 — a bad LLM response shouldn't crash the run
            logger.warning("step %d: LLM decision failed: %s", n, exc)
            history.append(StepRecord(n=n, kind="invalid", outcome="invalid", error=str(exc)[:200],
                                      reasoning="(your last response was invalid) — return a valid decision"))
            # not a no-change step
            return Command(update={"prev_observation": None, "texts_seen": seen[-400:]}, goto="observe")
        logger.info("step %d: %s — %s", n, "done" if decision.done else decision.kind, decision.reasoning)

        if decision.done:
            step = AgentStep(n=n, kind="done", reasoning=decision.reasoning, url=state["snapshot"].url)
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

    async def act(state: AgentState) -> Command[Literal["observe"]]:
        """Execute the decision's action(s) — one AgentStep per EXECUTED item, so a batch of
        three fills compiles to three transitions exactly as three single steps would.
        Two guards end a batch early (browser-use multi_act, Skyvern agent.py:3209): a static
        one (TERMINATES_BATCH kinds) and a runtime one (the URL changed → the pre-batch
        snapshot's indices mean nothing). A failed item aborts the remainder; the model is told
        which items did not run."""
        n, decision, snapshot = state["n"], state["decision"], state["snapshot"]
        items = decision.actions()[:max_actions]
        steps: list[AgentStep] = []
        seen = list(state.get("texts_seen") or [])
        known = set(seen) | {t.text for t in snapshot.texts}
        for i, item in enumerate(items):
            if i > 0:
                if session.page.url != steps[-1].url or session.page.url != snapshot.url:
                    history.append(StepRecord(
                        n=n, kind="note", note=f"{n}. page changed after action {i}: {len(items) - i} queued "
                        "action(s) were skipped — decide again from the new observation",
                    ))
                    break
            error = None
            action = None
            note = None
            try:
                if item.kind not in allowed:
                    raise ValueError(
                        f"{item.kind} is not available in this task; use one of {', '.join(sorted(allowed))}"
                    )
                upload = agent.upload_path() if item.kind == "upload" else None
                # Verified per item, against the live page: items 2..k run after the page may
                # have re-rendered, so the R1/R4 check must not reuse item 1's probe.
                locator_for, note = await _verified_locator(session, snapshot, item.index)
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
                        _watch_texts(session, known, action.seconds, agent.noticed, frame_filter)
                    )
                    try:
                        await session.dispatch(action)
                    finally:
                        watch.cancel()
                        await asyncio.gather(watch, return_exceptions=True)
                    during = agent.drain_noticed()
                    if during:
                        seen += [t for t in during if t not in seen]
                        history.append(StepRecord(
                            n=n, kind="note",
                            note=f"{n}. appeared on the page during the wait: "
                            + " | ".join(t[:120] for t in during[:6]),
                        ))
                else:
                    await session.dispatch(action)
            except (ExecutionError, ValueError) as exc:
                error = str(exc)
                logger.warning("step %d.%d failed: %s", n, i, error)

            step = AgentStep(
                n=n, item=i, kind=item.kind or "", reasoning=decision.reasoning, url=session.page.url, error=error,
                param=item.param or None,
                evaluation=decision.evaluation, memory=decision.memory, next_goal=decision.next_goal,
            )
            if error is None:
                step.action = action  # the compilable record of what actually ran
                step.locator_check = note
                step.dialogs = session.dialogs_since_last_action()  # THIS item's own dialogs (per item)
            await agent.capture_screenshot(session, step)
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
            history.append(record)
            if error is not None:
                if i + 1 < len(items):
                    history.append(StepRecord(
                        n=n, kind="note", note=f"{n}. action {i + 1} failed, so {len(items) - i - 1} queued "
                        "action(s) were skipped",
                    ))
                break  # a failed item aborts the remainder (universal across the survey)
            if item.kind in TERMINATES_BATCH:
                break
        # Keep sampling while the next observation is rendered and the model decides.
        if steps and steps[-1].error is None and not isinstance(steps[-1].action, WaitAction):
            agent.start_watch(_watch_texts(session, known, SETTLE_WATCH_S, agent.noticed, frame_filter))
        drained = agent.drain_noticed()
        seen += [t for t in drained if t not in seen]
        return Command(update={"steps": steps, "texts_seen": seen[-400:]}, goto="observe")

    return (
        StateGraph(AgentState)
        .add_node("observe", observe)
        .add_node("decide", decide)
        .add_node("act", act)
        .add_edge(START, "observe")
        .compile()
    )


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
