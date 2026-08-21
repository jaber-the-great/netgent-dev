"""The Validation agent: replay a synthesized workflow fresh, with ZERO LLM calls.

A synthesized artifact is a hypothesis until it replays. Validation runs the compiled
workflow through the ordinary executor in a fresh browser session — once with the
default params, once per explored variation — and records the outcome in the artifact's
provenance. If an edge fails on a state *condition* (a too-strict evidence guard), the
offending conditions are relaxed once and the replay is repeated; an action failure
(locator not found) cannot be relaxed and is reported as-is. The caller decides what to
do with `validated: false` — never silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from netgent.browser.session import BrowserSession
from netgent.core.errors import NetgentError
from netgent.core.logger import get_logger
from netgent.executor.engine import Executor
from netgent.schema.provenance import ValidationResult
from netgent.schema.workflow import Workflow, resolve_params

logger = get_logger(__name__)


@dataclass
class ValidationOutcome:
    workflow: Workflow  # possibly relaxed
    results: list[ValidationResult]  # the final round (one per param set)
    relaxed: list[str] = field(default_factory=list)  # "state: condition_type" dropped
    first_round: list[ValidationResult] = field(default_factory=list)  # only when a retry happened

    @property
    def validated(self) -> bool:
        return bool(self.results) and all(r.success for r in self.results)


async def replay_once(
    workflow: Workflow, values: dict[str, str], headless: bool = True, run_dir: Path | None = None
) -> ValidationResult:
    """One fresh-session, zero-LLM replay with concrete param values."""
    try:
        resolved = resolve_params(workflow, values)
    except ValueError as exc:
        return ValidationResult(params=values, success=False, error=f"params: {exc}")
    try:
        async with BrowserSession(headless=headless, stealth=True) as session:
            record = await Executor(session, resolved, run_dir=run_dir, params=values).run()
    except NetgentError as exc:  # e.g. Branch with no matching arm and no else
        return ValidationResult(params=values, success=False, error=str(exc))
    ok = [e for e in record.edges if e.outcome == "ok"]
    failed = next((e for e in record.edges if e.outcome != "ok"), None)
    if failed is not None:
        return ValidationResult(
            params=values,
            success=False,
            edges_ok=len(ok),
            failed_edge=failed.transition_id,
            failed_state=failed.target,
            unmet=[c.type for c in failed.conditions if not c.met],
            error=failed.error,
        )
    if not record.success:  # every edge ran, but no accept state held at the end
        accept = workflow.accept_states[0] if workflow.accept_states else None
        return ValidationResult(
            params=values,
            success=False,
            edges_ok=len(ok),
            failed_state=accept,
            error=f"accept state {accept!r} did not hold at program end",
        )
    return ValidationResult(params=values, success=True, edges_ok=len(ok))


def relax(workflow: Workflow, failure: ValidationResult) -> tuple[Workflow, list[str]]:
    """Drop the conditions that blocked recognition of the failing state.

    Unmet evidence conditions go first; `url_matches` is dropped only when it was itself
    unmet. When the executor could not say which (accept-state failure), every non-URL
    condition on that state is dropped. The exact conditions dropped are also removed from
    the states that follow on the SAME page (up to the next state with a URL condition):
    they rest on the same evidence context, which replay has just shown to be unreliable.
    Returns the relaxed workflow and what was dropped; an empty list means nothing was
    relaxable (an action error, or a bare state).
    """
    if failure.failed_state is None:
        return workflow, []
    data = workflow.model_dump(mode="json")
    states = data["states"]
    idx = next((i for i, s in enumerate(states) if s["id"] == failure.failed_state), None)
    if idx is None:
        return workflow, []
    failed = states[idx]
    if failure.unmet:
        kill_types = set(failure.unmet)
    else:
        kill_types = {c["type"] for c in failed["conditions"] if c["type"] != "url_matches"}
    killed = [c for c in failed["conditions"] if c["type"] in kill_types]
    if not killed:
        return workflow, []
    dropped: list[str] = []
    for i in range(idx, len(states)):
        state = states[i]
        if i > idx and any(c["type"] == "url_matches" for c in state["conditions"]):
            break  # a new page: its evidence stands on its own
        keep = []
        for cond in state["conditions"]:
            if cond in killed:
                dropped.append(f"{state['id']}: {cond['type']}")
            else:
                keep.append(cond)
        state["conditions"] = keep
    return Workflow.model_validate(data), dropped


async def validate_workflow(
    workflow: Workflow,
    param_sets: list[dict[str, str]],
    headless: bool = True,
    run_dir: Path | None = None,
    retry: bool = True,
) -> ValidationOutcome:
    """Replay for every param set; on a condition failure relax once and replay again."""

    async def _round(wf: Workflow, tag: str) -> list[ValidationResult]:
        out = []
        for i, values in enumerate(param_sets, 1):
            sub = run_dir / f"{tag}-{i}" if run_dir is not None else None
            result = await replay_once(wf, values, headless=headless, run_dir=sub)
            logger.info("validation %s/%d %s: %s", tag, i, values, "ok" if result.success else result.error)
            out.append(result)
        return out

    results = await _round(workflow, "validate")
    if all(r.success for r in results) or not retry:
        return ValidationOutcome(workflow=workflow, results=results)
    failure = next(r for r in results if not r.success)
    relaxed_wf, dropped = relax(workflow, failure)
    if not dropped:
        return ValidationOutcome(workflow=workflow, results=results)
    logger.warning("relaxing %s and re-validating", dropped)
    again = await _round(relaxed_wf, "revalidate")
    return ValidationOutcome(workflow=relaxed_wf, results=again, relaxed=dropped, first_round=results)
