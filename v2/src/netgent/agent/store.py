"""The trajectory store: every run of one `netgent generate --runs N`, persisted as memory.

Layout, under the workflow's memory folder `<out-dir>/<name>.trajectories/`:

    run-1/
      trajectory.json                  # written by explore(run_dir=...)
      screenshots/step-*.png           # written by explore(run_dir=...)
      variation.json                   # the planner's task_text + values for this run
      verdict.json                     # the verifier's judgment (+ achieved, attempts)
      trajectory.failed-attempt-1.json # a not-achieved first attempt, kept before the retry
      screenshots.failed-attempt-1/
    run-2/ ...
    generalized.json                   # the merge's induced artifact (the cross-run memory)

Failed and unachieved runs are stored too, marked in verdict.json — they are memory; their
divergence points are what future guards are mined from. Pure file I/O, zero LLM.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _dump(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=2) + "\n"
    return json.dumps(obj, indent=2) + "\n"


class TrajectoryStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, k: int) -> Path:
        """The directory for run `k` (1-based), created on first use. Hand it to
        `explore(run_dir=...)`, which writes trajectory.json + screenshots/ into it."""
        d = self.root / f"run-{k}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_variation(self, k: int, variation: BaseModel | dict) -> None:
        (self.run_dir(k) / "variation.json").write_text(_dump(variation))

    def stash_failed_attempt(self, k: int, attempt: int) -> None:
        """Keep a not-achieved attempt's artifacts before the retry overwrites them."""
        d = self.run_dir(k)
        traj = d / "trajectory.json"
        if traj.exists():
            traj.rename(d / f"trajectory.failed-attempt-{attempt}.json")
        shots = d / "screenshots"
        if shots.exists():
            shots.rename(d / f"screenshots.failed-attempt-{attempt}")

    def save_verdict(self, k: int, verdict: BaseModel | dict | None, achieved: bool, attempts: int = 1) -> None:
        data = {
            "achieved": achieved,  # the merge's spine takes only achieved runs
            "attempts": attempts,
            "verdict": json.loads(verdict.model_dump_json()) if isinstance(verdict, BaseModel) else verdict,
        }
        (self.run_dir(k) / "verdict.json").write_text(_dump(data))

    def save_generalized(self, generalized: BaseModel | dict) -> Path:
        path = self.root / "generalized.json"
        path.write_text(_dump(generalized))
        return path
