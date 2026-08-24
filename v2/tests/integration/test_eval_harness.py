"""The eval harness runs the committed forms dataset end-to-end against real Chromium."""

import asyncio
from pathlib import Path

from netgent.evals.dataset import run_dataset

DATASET = Path(__file__).parents[2] / "evals" / "datasets" / "forms"


def test_forms_dataset_all_pass(tmp_path):
    summary = asyncio.run(run_dataset(DATASET, tmp_path / "results", headless=True))
    assert summary.total == 3
    assert summary.passed == 3, [(t.task, t.error) for t in summary.tasks if not t.passed]
    assert summary.success_rate == 1.0
    # each task produced a trajectory bundle + the summary is written
    assert (tmp_path / "results" / "summary.json").is_file()
    for t in summary.tasks:
        assert (tmp_path / "results" / t.task / "record.json").is_file()
    # the shadow-DOM form was really filled (Playwright pierces open shadow roots)
    shadow = next(t for t in summary.tasks if t.task == "shadow")
    assert shadow.passed
