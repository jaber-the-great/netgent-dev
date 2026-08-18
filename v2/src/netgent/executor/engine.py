"""The run-time NFA executor: walk the control sequence, evaluate states, dispatch edges.

Semantics per edge: the source state must already be recognized, the edge's single atomic
action is dispatched, then the target state's conditions are awaited. Zero LLM calls.

When `run_dir` is set the executor writes a trajectory bundle: record.json plus one
screenshot per edge under screenshots/. That directory is the viewable agent trajectory.
"""

import time
from pathlib import Path

from netgent.browser.session import BrowserSession
from netgent.core.errors import ControlSequenceError, ExecutionError, TriggerTimeoutError
from netgent.core.logger import get_logger
from netgent.schema.records import ConditionCheck, EdgeRecord, RunRecord, utcnow
from netgent.schema.workflow import Transition, Workflow

logger = get_logger(__name__)


class Executor:
    def __init__(self, session: BrowserSession, workflow: Workflow, run_dir: Path | None = None):
        self._session = session
        self._workflow = workflow
        self._run_dir = run_dir  # if set, capture per-edge screenshots + write record.json

    async def run(self) -> RunRecord:
        wf = self._workflow
        record = RunRecord(workflow_name=wf.name, workflow_version=wf.version)
        sequence = wf.control_sequence or [t.id for t in wf.transitions]

        current = wf.start_state
        for transition_id in sequence:
            transition = wf.transition(transition_id)
            if transition.source != current:
                raise ControlSequenceError(
                    f"transition {transition.id!r} fires from {transition.source!r} but current state is {current!r}"
                )
            edge = await self._fire(transition)
            record.edges.append(edge)
            if edge.outcome != "ok":
                logger.error("edge %s failed (%s): %s", edge.transition_id, edge.outcome, edge.error)
                break
            logger.debug(
                "edge %s: %s -> %s ok (%.0fms, recognized in %.0fms)",
                edge.transition_id,
                edge.source,
                edge.target,
                edge.duration_ms,
                edge.trigger_latency_ms or 0,
            )
            current = transition.target
        else:
            record.success = True

        record.finished_at = utcnow()
        if self._run_dir is not None:
            self._write_bundle(record)
        return record

    async def _fire(self, transition: Transition) -> EdgeRecord:
        target_state = self._workflow.state(transition.target)
        started_at = utcnow()
        start = time.monotonic()
        outcome, error, latency = "ok", None, None
        try:
            await self._session.dispatch(transition.action)
            latency = await self._session.wait_for_state(target_state)
        except TriggerTimeoutError as exc:
            outcome, error = "trigger_timeout", str(exc)
        except ExecutionError as exc:
            outcome, error = "action_error", str(exc)

        conditions = [ConditionCheck(type=t, met=met) for t, met in await self._session.condition_report(target_state)]

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
            error=error,
        )

    def _write_bundle(self, record: RunRecord) -> None:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        (self._run_dir / "record.json").write_text(record.model_dump_json(indent=2) + "\n")
