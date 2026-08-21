"""ONE agent completes every form on a page, one at a time, with verification.

A single BrowserAgent — one continuous memory — works through all the forms: what worked on
an earlier form (date formats, how to satisfy a validator) informs the later ones. The sweep
stays deterministic around it: it enumerates the forms, scopes the agent to one form at a
time, and VERIFIES success by looking for a success marker in that form's own text — not the
agent's self-report. NetGent's philosophy: deterministic orchestration, verified outcomes.
"""

from pydantic import BaseModel, Field

from netgent.agent.explore_agent.browser_agent import BrowserAgent
from netgent.agent.llm import LLM
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MARKERS = ("dumbledore", "success", "submitted", "thank you", "completed")

FORM_TASK = (
    "Fill in THIS form completely with plausible values and submit it: text/email fields, "
    "dates as YYYY-MM-DD, dropdowns from their options, click radios/checkboxes, upload "
    "for file inputs. Fix any [required]/[invalid] field, then click this form's Submit. "
    "Stop with done when this form shows a success/confirmation message."
)


class FormResult(BaseModel):
    form: int
    frame_path: list[str]
    submitted: bool  # verified: a success marker appeared in this form
    agent_success: bool  # what the agent claimed
    steps: int
    stopped_reason: str = ""  # why the agent's run for this form ended
    last_error: str | None = None  # last action error seen, if any


class SweepResult(BaseModel):
    total: int = 0
    submitted: int = 0
    forms: list[FormResult] = Field(default_factory=list)


async def _form_frame_paths(session: BrowserSession) -> list[list[str]]:
    """Distinct frames that hold an actual form — a fillable field AND a submit button.

    Requiring a field (not just any button) excludes the top document, whose only
    "buttons" belong to page chrome around the embedded form iframes.
    """
    snapshot = await session.snapshot()
    fields = {"input", "select", "textarea"}
    by_frame: dict[tuple[str, ...], set[str]] = {}
    order: list[list[str]] = []
    for el in snapshot.elements:
        key = tuple(el.frame_path)
        if key not in by_frame:
            by_frame[key] = set()
            order.append(el.frame_path)
        by_frame[key].add(el.tag)
    return [fp for fp in order if (by_frame[tuple(fp)] & fields) and "button" in by_frame[tuple(fp)]]


async def _form_succeeded(session: BrowserSession, frame_path: list[str], markers: tuple[str, ...]) -> bool:
    snapshot = await session.snapshot()
    for text in snapshot.texts:
        if text.frame_path == frame_path and any(m in text.text.lower() for m in markers):
            return True
    return False


async def sweep_forms(
    session: BrowserSession,
    llm: LLM,
    *,
    max_steps_per_form: int = 30,
    retries: int = 2,
    markers: tuple[str, ...] = DEFAULT_MARKERS,
) -> SweepResult:
    """Complete and verify every form on the current page — with ONE agent.

    A single agent (one memory) is walked through the forms; each form is attempted up to
    `retries + 1` times (LLM runs vary, and a later attempt has more budget), stopping as
    soon as a success marker is verified.
    """
    frame_paths = await _form_frame_paths(session)
    result = SweepResult(total=len(frame_paths))
    logger.info("sweep: %d forms found", len(frame_paths))

    agent = BrowserAgent(llm, max_steps=max_steps_per_form)
    for i, frame_path in enumerate(frame_paths):
        verified = False
        traj = None
        for attempt in range(retries + 1):
            budget = max_steps_per_form + attempt * (max_steps_per_form // 2)  # more room each retry
            agent.note(f"--- now working form {i + 1} of {len(frame_paths)} (attempt {attempt + 1}) ---")
            traj = await agent.run(session, FORM_TASK, frame_filter=frame_path, max_steps=budget)
            verified = await _form_succeeded(session, frame_path, markers)
            if verified:
                break
            logger.info("sweep: form %d attempt %d not verified, retrying", i + 1, attempt + 1)
        last_error = next((s.error for s in reversed(traj.steps) if s.error), None) if traj else None
        result.forms.append(
            FormResult(
                form=i,
                frame_path=frame_path,
                submitted=verified,
                agent_success=bool(traj and traj.success),
                steps=len(traj.steps) if traj else 0,
                stopped_reason=traj.stopped_reason if traj else "",
                last_error=last_error,
            )
        )
        result.submitted += int(verified)
        logger.info("sweep: form %d/%d %s", i + 1, len(frame_paths), "OK" if verified else "not verified")

    return result
