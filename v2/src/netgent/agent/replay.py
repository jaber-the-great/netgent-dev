"""The zero-LLM replay check: the compiled workflow must walk the SAME state sequence for
every parameter value set (a metamorphic test — the output contract of `--runs N`).

Replays use the executor and the browser only — no model anywhere (the old validator package
was removed; this is the pipeline's replacement, kept deliberately small). The state
signature excludes interrupt resolutions (pop-ups are stochastic across replays — that is
what ε-interrupts are FOR) and collapses self-loop repeats (a dwell's length varies with
``${watch_time}``); what must agree is the sequence of main-path states.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from netgent.browser.session import BrowserSession
from netgent.executor.engine import Executor
from netgent.schema.records import RunRecord
from netgent.schema.workflow import Workflow, resolve_params


class ReplayRun(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    success: bool = False
    signature: list[str] = Field(default_factory=list)
    error: str | None = None
    # Where it stopped, when it did: the first non-ok main-path edge, its outcome
    # (trigger_timeout / action_error / param_error) and the target state's unmet conjuncts —
    # what the triage (agent/triage.py) reads to name the failing column.
    failed_edge: str | None = None
    outcome: str | None = None
    unmet: list[str] = Field(default_factory=list)


class ReplayReport(BaseModel):
    runs: list[ReplayRun] = Field(default_factory=list)
    passed: bool = False  # every replay succeeded AND all signatures agree


def state_signature(record: RunRecord) -> list[str]:
    """The states a run visited, in order: interrupt edges (ti*/recovered) excluded,
    consecutive self-loop repeats collapsed, a failure recorded as its edge and stop."""
    sig: list[str] = []
    for e in record.edges:
        if e.outcome == "recovered" or e.transition_id.startswith("ti"):
            continue
        if e.outcome != "ok":
            sig.append(f"FAILED@{e.transition_id}")
            break
        if e.source == e.target and sig and sig[-1] == e.target:
            continue
        sig.append(e.target)
    return sig


def replay_run_from_record(values: dict[str, str], record: RunRecord) -> ReplayRun:
    """A ReplayRun read off a RunRecord (the live check, or a stored replay-N/record.json)."""
    failed = next((e for e in record.edges if e.outcome not in ("ok", "recovered")), None)
    return ReplayRun(
        values=values, success=record.success, signature=state_signature(record),
        error=failed.error if failed else None,
        failed_edge=failed.transition_id if failed else None,
        outcome=failed.outcome if failed else None,
        unmet=[c.type for c in failed.conditions if not c.met] if failed else [],
    )


async def replay_workflow(
    wf: Workflow, values: dict[str, str], *, headless: bool = True, run_dir: Path | None = None
) -> RunRecord:
    """One deterministic replay with `values` (statics substituted upfront, like `netgent run`)."""
    resolved = resolve_params(wf, values)
    async with BrowserSession(headless=headless) as session:
        return await Executor(session, resolved, run_dir=run_dir, params=values).run()


async def replay_check(
    wf: Workflow,
    value_sets: list[dict[str, str]],
    *,
    headless: bool = True,
    run_dir_base: Path | None = None,
) -> ReplayReport:
    """Replay `wf` once per value set and require the same state signature from each."""
    report = ReplayReport()
    for i, values in enumerate(value_sets, 1):
        run_dir = (run_dir_base / f"replay-{i}") if run_dir_base is not None else None
        try:
            record = await replay_workflow(wf, values, headless=headless, run_dir=run_dir)
            report.runs.append(replay_run_from_record(values, record))
        except Exception as exc:  # noqa: BLE001 — a crashed replay is a failed check, not a crash
            report.runs.append(ReplayRun(values=values, success=False, error=str(exc)))
    signatures = {tuple(r.signature) for r in report.runs}
    report.passed = bool(report.runs) and all(r.success for r in report.runs) and len(signatures) == 1
    return report
