"""The run-time NFA executor: interpret the control program over the graph. Zero LLM calls.

The graph is flat (states carry conditions, transitions carry one atomic action). The control
program is a bounded regexp over transitions — concatenation, capped Repeat, guard-dispatched
Branch — walked by a small recursive interpreter. The per-edge contract is unchanged: the source
state must be current, dispatch the action, await the target state's conditions.

When `run_dir` is set the executor writes a trajectory bundle (record.json + per-edge screenshots).
"""

import time
from pathlib import Path

from netgent.browser.session import BrowserSession
from netgent.core.errors import ControlSequenceError, ExecutionError, ParamError, TriggerTimeoutError
from netgent.core.logger import get_logger
from netgent.executor.params import ParamContext
from netgent.schema.control import Branch, Call, ControlNode, EdgeStep, Repeat
from netgent.schema.records import ConditionCheck, EdgeRecord, RunRecord, utcnow
from netgent.schema.workflow import Transition, Workflow

logger = get_logger(__name__)


class Executor:
    def __init__(
        self,
        session: BrowserSession,
        workflow: Workflow,
        run_dir: Path | None = None,
        params: dict[str, str] | None = None,
    ):
        self._session = session
        self._workflow = workflow
        self._run_dir = run_dir
        self._provided = params
        self._ctx: ParamContext | None = None
        self._record = RunRecord(workflow_name=workflow.name, workflow_version=workflow.version)
        self._current = workflow.start_state
        self._aborted = False
        self._interrupt_fires: dict[str, int] = {i.id: 0 for i in workflow.interrupts}

    async def run(self) -> RunRecord:
        if self._workflow.params:  # build the param context (may raise ParamError for a missing static)
            self._ctx = ParamContext(self._workflow.params, self._provided, self._session)
        await self._run_nodes(self._workflow.as_control())
        if not self._aborted:
            self._record.success = await self._reached_accept_state()
        self._record.finished_at = utcnow()
        if self._run_dir is not None:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            (self._run_dir / "record.json").write_text(self._record.model_dump_json(indent=2) + "\n")
        return self._record

    async def _reached_accept_state(self) -> bool:
        accept = self._workflow.accept_states
        if not accept:
            return True  # legacy: success = the program ran without a failed edge
        for state_id in accept:
            report = await self._session.condition_report(self._workflow.state(state_id))
            if all(met for _, met in report):
                return True
        return False

    async def _run_nodes(self, nodes: list[ControlNode]) -> None:
        for node in nodes:
            if self._aborted:
                return
            await self._sweep_interrupts()  # ε-sweep between atomic steps, never inside one
            if self._aborted:
                return
            match node:
                case EdgeStep():
                    await self._run_edge(node.edge)
                case Repeat():
                    await self._run_repeat(node)
                case Branch():
                    await self._run_branch(node)
                case Call():
                    raise ExecutionError("sub-workflow Call is not executable yet (library not wired)")

    async def _run_edge(self, edge_id: str) -> None:
        transition = self._workflow.transition(edge_id)
        if transition.source != self._current:
            raise ControlSequenceError(
                f"transition {edge_id!r} fires from {transition.source!r} but current state is {self._current!r}"
            )
        edge = await self._fire(transition)
        self._record.edges.append(edge)
        if edge.outcome != "ok":
            logger.error("edge %s failed (%s): %s", edge.transition_id, edge.outcome, edge.error)
            self._aborted = True
            return
        logger.debug(
            "edge %s: %s -> %s ok (%.0fms, recognized in %.0fms)",
            edge.transition_id, edge.source, edge.target, edge.duration_ms, edge.trigger_latency_ms or 0,
        )
        self._current = transition.target

    async def _sweep_interrupts(self) -> None:
        """Check in-scope interrupt anchors; on a hit, run the resolution chain and re-anchor.

        Runs between control-program nodes (and between Repeat iterations, since those go
        through _run_nodes), so an interrupt never splits an atomic action. Each interrupt
        fires at most max_fires times — the bounded-traversal red line.
        """
        for interrupt in self._workflow.interrupts:
            if self._aborted:
                return
            if self._current not in interrupt.scope:
                continue
            anchor = self._workflow.state(interrupt.state)
            fired = False
            # "Resolved" means the anchor no longer holds or the fire budget is spent —
            # NOT that the resolve chain's target state was recognized. Chained pop-ups
            # (YouTube "ad 1 of 2") re-satisfy the anchor with the same selector the
            # instant it is dismissed, so the target's selector_hidden never comes true;
            # the bounded re-fire below is what max_fires exists for.
            while self._interrupt_fires[interrupt.id] < interrupt.max_fires:
                report = await self._session.condition_report(anchor)
                if not report or not all(met for _, met in report):
                    break
                self._interrupt_fires[interrupt.id] += 1
                fired = True
                logger.info(
                    "interrupt %s: anchor %s holds at %s (fire %d/%d) — resolving",
                    interrupt.id, interrupt.state, self._current,
                    self._interrupt_fires[interrupt.id], interrupt.max_fires,
                )
                for edge_id in interrupt.resolve:
                    edge = await self._fire(self._workflow.transition(edge_id))
                    if edge.outcome == "trigger_timeout":
                        # The action ran but the pop-up didn't settle (e.g. a chained ad
                        # re-showed the same skip button): re-check the anchor and re-fire.
                        # Recorded as "recovered", not a failure — the sweep handled it.
                        edge = edge.model_copy(update={"outcome": "recovered"})
                        self._record.edges.append(edge)
                        logger.info(
                            "interrupt %s: resolve edge %s did not settle (%s) — re-checking anchor",
                            interrupt.id, edge_id, edge.error,
                        )
                        break
                    self._record.edges.append(edge)
                    if edge.outcome != "ok":
                        logger.error("interrupt %s: resolve edge %s failed: %s", interrupt.id, edge_id, edge.error)
                        self._aborted = True
                        return
            if not fired:
                continue
            # Back to the program: the page must still look like the state we were in.
            try:
                await self._session.wait_for_state(self._workflow.state(self._current))
            except TriggerTimeoutError as exc:
                logger.error("interrupt %s: state %s lost after resolution: %s", interrupt.id, self._current, exc)
                self._aborted = True
                return

    async def _run_repeat(self, node: Repeat) -> None:
        count = self._resolve_count(node.count)
        limit = min(count, node.max_iterations) if count is not None else node.max_iterations
        for i in range(limit):
            if node.until and await self._all_hold(node.until):
                logger.debug("repeat: `until` satisfied after %d iteration(s)", i)
                return
            await self._run_nodes(node.body)
            if self._aborted:
                return
        if node.until and not await self._all_hold(node.until):
            # cap hit without the semantic stop — a soft stop; flag it (flow-drift signal).
            logger.warning("repeat: hit max_iterations=%d without `until` satisfied", limit)

    async def _run_branch(self, node: Branch) -> None:
        for arm in node.arms:
            report = await self._session.condition_report(self._workflow.state(arm.when))
            if all(met for _, met in report):
                logger.debug("branch: arm when=%s matched", arm.when)
                await self._run_nodes(arm.then)
                return
        if node.else_ is not None:
            logger.debug("branch: no arm matched, taking else")
            await self._run_nodes(node.else_)
            return
        raise ExecutionError(f"branch: no arm matched at state {self._current!r} and no else — new territory")

    def _resolve_count(self, count: str | int | None) -> int | None:
        if count is None or isinstance(count, int):
            return count
        if "${" in count:
            raise ExecutionError(f"repeat.count {count!r} is an unresolved param — run resolve_params() first")
        # A "${param}" count arrives here as the substituted string (resolve_params walks
        # strings; Repeat.count keeps its declared str type) — e.g. "${watch_time}" -> "10".
        try:
            return int(float(count))
        except ValueError as exc:
            raise ExecutionError(f"repeat.count {count!r} did not resolve to a number") from exc

    async def _all_hold(self, triggers) -> bool:
        from netgent.schema.workflow import State

        report = await self._session.condition_report(State(id="_probe", conditions=triggers))
        return all(met for _, met in report)

    async def _fire(self, transition: Transition) -> EdgeRecord:
        target_state = self._workflow.state(transition.target)
        started_at = utcnow()
        start = time.monotonic()
        outcome, error, latency = "ok", None, None
        try:
            action = transition.action
            if self._ctx is not None:  # substitute ${params} against the live page
                action = await self._ctx.resolve_action(action)
            await self._session.dispatch(action)
            latency = await self._session.wait_for_state(target_state)
        except ParamError as exc:  # before ExecutionError — ParamError is a subclass
            outcome, error = "param_error", str(exc)
        except TriggerTimeoutError as exc:
            outcome, error = "trigger_timeout", str(exc)
        except ExecutionError as exc:
            outcome, error = "action_error", str(exc)

        conditions = [ConditionCheck(type=t, met=met) for t, met in await self._session.condition_report(target_state)]

        media = None
        try:  # playback reading for the record — never allowed to fail an edge
            media = await self._session.media_summary()
        except Exception:  # noqa: BLE001 — including sessions/fakes without the probe
            media = None

        screenshot_rel = None
        if self._run_dir is not None:
            screenshot_rel = f"screenshots/{transition.id}.png"
            try:
                await self._session.screenshot(self._run_dir / screenshot_rel)
            except Exception as exc:  # a screenshot must never fail the run
                logger.warning("screenshot for edge %s failed: %s", transition.id, exc)
                screenshot_rel = None

        return EdgeRecord(
            transition_id=transition.id,
            source=transition.source,
            target=transition.target,
            action_type=transition.action.type,
            outcome=outcome,
            started_at=started_at,
            duration_ms=(time.monotonic() - start) * 1000,
            trigger_latency_ms=latency,
            conditions=conditions,
            url_after=self._session.page.url,
            screenshot=screenshot_rel,
            media=media,
            error=error,
        )
