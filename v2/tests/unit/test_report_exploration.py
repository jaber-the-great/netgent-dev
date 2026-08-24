"""Exploration trajectories render as a text timeline; run records keep their symbols."""


from netgent.report import render_exploration_text
from netgent.report.exploration import is_exploration
from netgent.report.run import _SYMBOL


def test_exploration_timeline(tmp_path):
    data = {
        "task": "search for cats",
        "success": True,
        "stopped_reason": "done",
        "steps": [
            {"n": 0, "kind": "goto", "reasoning": "starting URL", "url": "https://x/", "action": {"type": "goto", "url": "https://x/"}},
            {"n": 1, "kind": "fill", "reasoning": "type", "url": "https://x/", "error": "timeout"},
            {"n": 2, "kind": "done", "reasoning": "finished", "url": "https://x/watch"},
        ],
    }
    assert is_exploration(data)
    text = render_exploration_text(data)
    assert "SUCCESS (3 steps): search for cats" in text
    assert "✓ 0. goto [goto]" in text
    assert "✗ 1. fill" in text and "error: timeout" in text
    assert "■ 2. done" in text
    assert text.endswith("stopped: done")
    assert not is_exploration({"edges": [], "workflow_name": "w"})


def test_every_edge_outcome_has_a_symbol():
    assert set(_SYMBOL) >= {"ok", "trigger_timeout", "action_error", "param_error"}
