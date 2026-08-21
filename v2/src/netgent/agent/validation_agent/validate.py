"""Zero-LLM validation: replay a workflow fresh and report what held and what didn't."""

from pydantic import BaseModel, Field

from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger
from netgent.executor.engine import Executor
from netgent.schema.workflow import Workflow, resolve_params

logger = get_logger(__name__)


class ReplayResult(BaseModel):
    params: dict[str, str] = Field(default_factory=dict)
    success: bool
    edges_ok: int
    failed_edge: str | None = None  # transition id of the first failing edge
    error: str | None = None


class ValidationReport(BaseModel):
    replays: list[ReplayResult] = Field(default_factory=list)

    @property
    def validated(self) -> bool:
        return bool(self.replays) and all(r.success for r in self.replays)


async def validate_workflow(
    workflow: Workflow,
    param_sets: list[dict[str, str]] | None = None,
    *,
    headless: bool = True,
) -> ValidationReport:
    """Replay `workflow` once per param set (default: its own defaults) in a fresh session each.

    Statics are resolved upfront (so ${name} in state conditions works); dynamics resolve
    from the live page at dispatch, exactly as `netgent run` does. No LLM is involved.
    """
    report = ValidationReport()
    for params in param_sets or [{}]:
        wf = resolve_params(workflow, params)
        async with BrowserSession(headless=headless) as session:
            record = await Executor(session, wf, params=params).run()
        failed = next((e for e in record.edges if e.outcome != "ok"), None)
        result = ReplayResult(
            params=params,
            success=record.success,
            edges_ok=sum(1 for e in record.edges if e.outcome == "ok"),
            failed_edge=failed.transition_id if failed else None,
            error=failed.error if failed else None,
        )
        verdict = "ok" if result.success else f"FAILED at {result.failed_edge}"
        logger.info("validation %s: %s", params or "defaults", verdict)
        report.replays.append(result)
    return report
