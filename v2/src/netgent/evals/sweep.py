"""ONE agent completes every form on a page, one at a time, with verification.

A single ExplorerAgent — one continuous memory — works through all the forms: what worked on
an earlier form (date formats, how to satisfy a validator) informs the later ones. The sweep
stays deterministic around it: it enumerates the forms, scopes the agent to one form at a
time, and VERIFIES success by looking for a success marker in that form's own text — not the
agent's self-report. NetGent's philosophy: deterministic orchestration, verified outcomes.
"""

from pydantic import BaseModel, Field

from netgent.agent.explorer.agent import ExplorerAgent
from netgent.agent.llm import LLM
from netgent.browser.session import BrowserSession
from netgent.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MARKERS = ("dumbledore", "success", "submitted", "thank you", "completed")

FORM_TASK = (
    "Fill in THIS form completely with plausible values and submit it: text/email fields, "
    "dates in the format= the field shows (YYYY-MM-DD for native date inputs; "
    "if a date is rejected, retry as MM/DD/YYYY), "
    "dropdowns from their options, click radios/checkboxes, upload "
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
    judge_achieved: bool | None = None  # the LLM judge's verdict (None = judging off)
    judge_unmet: list[str] = Field(default_factory=list)
    judge_evidence: list[str] = Field(default_factory=list)


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


async def _form_succeeded(
    session: BrowserSession,
    frame_path: list[str],
    markers: tuple[str, ...],
    dialog_mark: int = 0,
    texts_seen: list[str] | None = None,
) -> bool:
    """True if the form under `frame_path` showed success, in any of three page-observed ways:
    a success dialog raised since `dialog_mark` (this attempt — dialogs are one-shot and the
    agent's own snapshots already drained them), a marker in a text the agent's observations
    SAW during the run (`texts_seen` — success banners are often transient, hidden again a few
    seconds later, so a post-run snapshot alone misses them), or a marker still visible in the
    frame's text right now. All three are the walker's own reads of the page, never the
    agent's self-report."""
    new_dialogs = session.dialogs_seen()[dialog_mark:]
    if any(m in d.lower() for d in new_dialogs for m in markers):
        return True
    if any(m in t.lower() for t in (texts_seen or ()) for m in markers):
        return True
    snapshot = await session.snapshot()
    return any(
        text.frame_path == frame_path and any(m in text.text.lower() for m in markers)
        for text in snapshot.texts
    )


async def sweep_forms(
    session: BrowserSession,
    llm: LLM,
    *,
    max_steps_per_form: int = 30,
    retries: int = 2,
    markers: tuple[str, ...] = DEFAULT_MARKERS,
    max_actions_per_step: int = 1,
    judge: bool = False,
) -> SweepResult:
    """Complete and verify every form on the current page — with ONE agent.

    A single agent (one memory) is walked through the forms; each form is attempted up to
    `retries + 1` times (LLM runs vary, and a later attempt has more budget), stopping as
    soon as a success marker is verified.
    """
    frame_paths = await _form_frame_paths(session)
    result = SweepResult(total=len(frame_paths))
    logger.info("sweep: %d forms found", len(frame_paths))

    run_dir = None
    if judge:  # the judge wants screenshots
        import tempfile
        from pathlib import Path

        run_dir = Path(tempfile.mkdtemp(prefix="netgent-sweep-"))
    agent = ExplorerAgent(
        llm, max_steps=max_steps_per_form, max_actions_per_step=max_actions_per_step, run_dir=run_dir
    )
    for i, frame_path in enumerate(frame_paths):
        verified = False
        traj = None
        for attempt in range(retries + 1):
            budget = max_steps_per_form + attempt * (max_steps_per_form // 2)  # more room each retry
            agent.note(f"--- now working form {i + 1} of {len(frame_paths)} (attempt {attempt + 1}) ---")
            dialog_mark = len(session.dialogs_seen())  # only THIS attempt's dialogs count
            traj = await agent.run(session, FORM_TASK, frame_filter=frame_path, max_steps=budget)
            verified = await _form_succeeded(session, frame_path, markers, dialog_mark, traj.texts_seen)
            if verified:
                break
            logger.info("sweep: form %d attempt %d not verified, retrying", i + 1, attempt + 1)
        last_error = next((s.error for s in reversed(traj.steps) if s.error), None) if traj else None
        judged = None
        unmet: list[str] = []
        cited: list[str] = []
        if judge and traj is not None:
            from netgent.agent.verifier.graph import verify

            verdict = await verify(traj, FORM_TASK, llm=llm, run_dir=run_dir)
            judged, unmet, cited = verdict.achieved, list(verdict.unmet), list(verdict.evidence)
            logger.info("sweep: form %d judge=%s page=%s", i + 1, judged, verified)
        result.forms.append(
            FormResult(
                form=i,
                frame_path=frame_path,
                submitted=verified,
                agent_success=bool(traj and traj.success),
                steps=len(traj.steps) if traj else 0,
                stopped_reason=traj.stopped_reason if traj else "",
                last_error=last_error,
                judge_achieved=judged,
                judge_unmet=unmet,
                judge_evidence=cited,
            )
        )
        result.submitted += int(verified)
        logger.info("sweep: form %d/%d %s", i + 1, len(frame_paths), "OK" if verified else "not verified")

    return result
