"""The verifier's values: what the judge sees (Evidence) and what it answers (Verdict).
Pydantic, like the explorer's models: they are graph state, they serialize, and the
orchestrator/evals read them without importing the graph."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentTrajectory

MAX_SCREENSHOTS = 3  # the final state and the two steps before it (browser-use judges from the final one)


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
    # "9. [t+42s] wait = '15.0' — video PLAYING at 0:04 / 8:35": playback position observed
    # just BEFORE each step ran, stamped with wall-clock seconds since the first reading.
    # Consecutive readings are how timed watch/pause/seek phases are verified: position delta
    # vs wall-clock delta tells a seek jump from natural playback — a summed "expected final
    # position" is wrong because playback continues between actions. Empty for runs that
    # never observed media.
    media_timeline: list[str] = Field(default_factory=list)
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
        timeline = []
        t0 = next((s.t for s in traj.steps if s.media and s.t), None)
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
            if s.media:
                at = f"[t+{s.t - t0:.0f}s] " if s.t and t0 is not None else ""
                timeline.append(f"{s.n}. {at}{what} — {s.media}")
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
            media_timeline=timeline,
            final_observation=traj.final_observation,
            final_url=traj.final_url or (traj.steps[-1].url if traj.steps else ""),
            texts_seen=list(traj.texts_seen),
            dialogs=list(traj.dialogs),
            run_ended="" if traj.success else (traj.stopped_reason or "the agent gave up"),
            screenshots=shots,
        )
