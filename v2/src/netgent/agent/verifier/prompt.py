"""The judge's prompt: the system rules and the evidence rendered as message content. Pure."""

import base64

from netgent.agent.verifier.models import Evidence

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
- Timed media phases (watch/pause/fast-forward/seek for N seconds) are judged from the MEDIA
  TIMELINE, when present: each entry is the playback position observed just BEFORE that step
  ran, stamped [t+Ns] with wall-clock seconds since the first reading. Compare CONSECUTIVE
  readings, position delta against wall-clock delta — the video keeps playing while the agent
  decides between actions, so NEVER compute an expected final position by summing the task's
  durations. A seek/fast-forward totals the amount position advanced MORE than wall-clock
  across its steps (position +45s over 15s of wall-clock = a +30s seek). A pause shows as
  position frozen while wall-clock advances. A watch/dwell of N seconds is satisfied by a
  wait of N wall-clock seconds with the player PLAYING — buffering can make position advance
  less than wall-clock, and that still counts as watching; PAUSED does not. An `audio
  (detached)` reading is the page's real player (held in script, not in the DOM) and counts
  like any other; `NOT LOADED (no source)` means the player had nothing to play — nothing was
  watched.
  Small drifts of a few seconds are normal.
- Be specific: for every unmet requirement say what is missing, and for every achieved one cite
  the evidence line or screenshot that proves it.
- Confidence: high when the evidence directly shows the outcome, low when you are inferring."""


def build_judge_content(ev: Evidence) -> list[dict]:
    """The HumanMessage content blocks (text, then images). Pure — tests pin the layout."""
    params = "; ".join(f"${{{k}}} = {v!r}" for k, v in ev.params.items()) or "(none)"
    text = (
        f"TASK: {ev.task}\nPARAMETERS: {params}\n\n"
        f"ACTION LOG (what was dispatched; not proof of effect):\n" + ("\n".join(ev.action_log) or "(none)") + "\n\n"
        + ("MEDIA TIMELINE (playback position observed just BEFORE each step ran):\n"
           + "\n".join(ev.media_timeline) + "\n\n" if ev.media_timeline else "")
        + f"FINAL URL: {ev.final_url}\n\n"
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
