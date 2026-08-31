"""The trajectory store: per-run folders under <name>.trajectories, failed attempts kept,
verdicts marked, generalized.json at the root."""

import json

from netgent.agent.planner import TaskVariation
from netgent.agent.store import TrajectoryStore
from netgent.agent.verifier import Verdict


def test_store_layout_and_writers(tmp_path):
    store = TrajectoryStore(tmp_path / "yt.trajectories")
    d1 = store.run_dir(1)
    assert d1 == tmp_path / "yt.trajectories" / "run-1" and d1.is_dir()

    store.save_variation(1, TaskVariation(task_text="watch a cat video", values={"video_query": "cat"}))
    var = json.loads((d1 / "variation.json").read_text())
    assert var["task_text"] == "watch a cat video" and var["values"] == {"video_query": "cat"}

    store.save_verdict(1, Verdict(achieved=False, unmet=["no video played"]), achieved=False, attempts=2)
    v = json.loads((d1 / "verdict.json").read_text())
    assert v["achieved"] is False and v["attempts"] == 2  # failed runs are stored too, marked
    assert v["verdict"]["unmet"] == ["no video played"]

    path = store.save_generalized({"params": {"video_query": "cat"}})
    assert path == store.root / "generalized.json"
    assert json.loads(path.read_text())["params"] == {"video_query": "cat"}


def test_stash_failed_attempt_preserves_the_first_run(tmp_path):
    store = TrajectoryStore(tmp_path / "w.trajectories")
    d = store.run_dir(3)
    (d / "trajectory.json").write_text("{}")
    (d / "screenshots").mkdir()
    (d / "screenshots" / "step-01.png").write_bytes(b"png")

    store.stash_failed_attempt(3, attempt=1)
    assert not (d / "trajectory.json").exists()
    assert (d / "trajectory.failed-attempt-1.json").read_text() == "{}"
    assert (d / "screenshots.failed-attempt-1" / "step-01.png").exists()
    store.stash_failed_attempt(3, attempt=2)  # nothing to stash: a no-op, not an error
