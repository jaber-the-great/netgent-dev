"""The run-time NFA executor: walk the control sequence, evaluate states, dispatch edges.

Semantics per edge: the source state must already be recognized, the edge's single atomic
action is dispatched, then the target state's conditions are awaited. Zero LLM calls.
"""

import time

from netgent.browser.errors import NetgentBrowserError, TriggerTimeoutError
from netgent.browser.session import BrowserSession
from netgent.core.records import EdgeRecord, RunRecord, utcnow
from netgent.core.workflow import Transition, Workflow


class ControlSequenceError(Exception):
    """The control sequence is not walkable (edge fired from a state we are not in)."""


class Executor:
    def __init__(self, session: BrowserSession, workflow: Workflow):
        self._session = session
        self._workflow = workflow

    async def run(self) -> RunRecord:
        wf = self._workflow
        record = RunRecord(workflow_name=wf.name)
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
                record.finished_at = utcnow()
                return record
            current = transition.target

        record.success = True
        record.finished_at = utcnow()
        return record

    async def _fire(self, transition: Transition) -> EdgeRecord:
        started_at = utcnow()
        start = time.monotonic()
        outcome, error, latency = "ok", None, None
        try:
            await self._session.dispatch(transition.action)
            latency = await self._session.wait_for_state(self._workflow.state(transition.target))
        except TriggerTimeoutError as exc:
            outcome, error = "trigger_timeout", str(exc)
        except NetgentBrowserError as exc:
            outcome, error = "action_error", str(exc)
        return EdgeRecord(
            transition_id=transition.id,
            source=transition.source,
            target=transition.target,
            action_type=transition.action.type,
            outcome=outcome,
            started_at=started_at,
            duration_ms=(time.monotonic() - start) * 1000,
            trigger_latency_ms=latency,
            url_after=self._session.page.url,
            error=error,
        )
