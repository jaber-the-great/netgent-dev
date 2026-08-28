"""The judge: evidence in, structured verdict out. Pure except for the one LLM call."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from netgent.agent.explorer.browser_agent import AgentTrajectory

MAX_SCREENSHOTS = 3  # the final state and the two steps before it (browser-use judges from the final one)

JUDGE_SYSTEM = """You are a strict verifier of web-automation runs. You are given a TASK a user
asked for, and EVIDENCE of what the browser showed after an automated agent worked on it.
Decide whether the task was ACHIEVED, judging ONLY from the evidence: the final page
observation, the texts that appeared during the run, dialogs, the final URL, the action log
and screenshots. The agent's own claims are deliberately not shown to you.

Rules:
- Break the task into its concrete requirements (each thing the user asked for, including the
  PARAMETERS given — the exact value must have been used, not a different one).
- A requirement counts as achieved only if the evidence SHOWS it (a confirmation message, the
  right URL, the right value in a field, the video playing, the ad gone, …). Absence of evidence
  is NOT achievement: if you cannot see it, it is unmet.
- Actions that were dispatched are not proof they worked; look for their effect on the page.
- Filled fields are not an outcome. If the task is to submit/send/book/post/watch, achievement
  means the RESULT is visible: a confirmation message or dialog, a success page/URL, the next
  screen, the video playing. A form that still shows its Submit button with no confirmation
  anywhere in the observation, the texts seen, or the dialogs was NOT submitted — say so.
- If the run ended because the agent got stuck or ran out of steps, that is strong evidence
  the task was not completed; only overrule it when the outcome is plainly visible.
- Be specific: for every unmet requirement say what is missing, and for every achieved one cite
  the evidence line or screenshot that proves it.
- Confidence: high when the evidence directly shows the outcome, low when you are inferring."""


class Verdict(BaseModel):
    """The judge's structured answer."""

    achieved: bool = Field(
        description="True only if EVERY requirement of the task is shown achieved by the evidence."
    )
    confidence: Literal["high", "medium", "low"] = "medium"
    unmet: list[str] = Field(
        default_factory=list, description="Each requirement not shown achieved, and what is missing."
    )
    evidence: list[str] = Field(
        default_factory=list, description="Observation lines / screenshots proving the achieved parts."
    )


class Evidence(BaseModel):
    """What the judge sees. Built from a trajectory; never carries the explorer's reasoning."""

    task: str
    params: dict[str, str] = Field(default_factory=dict)
    action_log: list[str] = Field(default_factory=list)  # "3. fill 'Email' = 'a@b.c'" — what ran, and failures
    final_observation: str = ""
    final_url: str = ""
    texts_seen: list[str] = Field(default_factory=list)
    dialogs: list[str] = Field(default_factory=list)
    # How the run ended when the harness ended it (stuck / budget) — objective, not the agent's
    # narration; empty when the agent declared done itself.
    run_ended: str = ""
    screenshots: list[bytes] = Field(default_factory=list)  # PNGs, oldest first, at most MAX_SCREENSHOTS

    @classmethod
    def from_trajectory(
        cls,
        task: str,
        traj: AgentTrajectory,
        params: dict[str, str] | None = None,
        run_dir: Path | None = None,
        max_screenshots: int = MAX_SCREENSHOTS,
    ) -> Evidence:
        log = []
        for s in traj.steps:
            a = s.action
            what = ""
            if a is not None:
                d = a.model_dump()
                loc = d.get("locator")
                target = ""
                if loc:
                    last = loc[-1]
                    target = f" {last.get('args', [''])[0]!r}" if last.get("args") else ""
                    if last.get("kwargs", {}).get("name"):
                        target = f" {last['kwargs']['name']!r}"
                val = next((str(d[k]) for k in ("text", "value", "url", "keys", "seconds") if d.get(k) is not None), "")
                what = f"{d.get('type')}{target}" + (f" = {val!r}" if val else "")
            else:
                what = s.kind
            line = f"{s.n}. {what}"
            if s.error:
                line += f" -> FAILED: {s.error[:120]}"
            if s.dialogs:
                line += f" -> dialog: {' | '.join(s.dialogs)[:160]}"
            log.append(line)
        shots: list[bytes] = []
        if run_dir is not None:
            paths = [run_dir / s.screenshot for s in traj.steps if s.screenshot]
            for p in paths[-max_screenshots:]:
                try:
                    shots.append(p.read_bytes())
                except OSError:
                    continue
        return cls(
            task=task,
            params=dict(params or {}),
            action_log=log,
            final_observation=traj.final_observation,
            final_url=traj.final_url or (traj.steps[-1].url if traj.steps else ""),
            texts_seen=list(traj.texts_seen),
            dialogs=list(traj.dialogs),
            run_ended="" if traj.success else (traj.stopped_reason or "the agent gave up"),
            screenshots=shots,
        )


def build_judge_content(ev: Evidence) -> list[dict]:
    """The HumanMessage content blocks (text, then images). Pure — tests pin the layout."""
    params = "; ".join(f"${{{k}}} = {v!r}" for k, v in ev.params.items()) or "(none)"
    text = (
        f"TASK: {ev.task}\nPARAMETERS: {params}\n\n"
        f"ACTION LOG (what was dispatched; not proof of effect):\n" + ("\n".join(ev.action_log) or "(none)") + "\n\n"
        f"FINAL URL: {ev.final_url}\n\n"
        f"FINAL OBSERVATION:\n{ev.final_observation or '(none)'}\n\n"
        "TEXTS SEEN DURING THE RUN (including banners that have since vanished):\n"
        + ("\n".join(f"- {t}" for t in ev.texts_seen[-80:]) or "(none)") + "\n\n"
        "DIALOGS: " + (" | ".join(ev.dialogs) or "(none)") + "\n\n"
        + (f"RUN ENDED BY THE HARNESS: {ev.run_ended}\n\n" if ev.run_ended else "")
        + (f"{len(ev.screenshots)} screenshot(s) follow, oldest first; the last is the final state.\n"
           if ev.screenshots else "")
        + "\nVerdict:"
    )
    content: list[dict] = [{"type": "text", "text": text}]
    for png in ev.screenshots:
        b64 = base64.b64encode(png).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    return content


async def judge_trajectory(llm, ev: Evidence) -> Verdict:
    """One LLM call → Verdict. `llm` is the agent's LLM seam (LangChainLLM / FakeLLM)."""
    return await llm.judge(JUDGE_SYSTEM, build_judge_content(ev), Verdict)
