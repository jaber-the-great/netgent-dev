"""Exploration trajectories render as a text timeline; run records keep their symbols."""


from netgent.report import render_exploration_html, render_exploration_text
from netgent.report.exploration import is_exploration
from netgent.report.run import _SYMBOL


def test_exploration_timeline(tmp_path):
    data = {
        "task": "search for cats",
        "success": True,
        "stopped_reason": "done",
        "steps": [
            {"n": 0, "kind": "goto", "reasoning": "starting URL", "url": "https://x/",
             "action": {"type": "goto", "url": "https://x/"}},
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


def test_exploration_html_inlines_screenshots(tmp_path):
    (tmp_path / "screenshots").mkdir()
    png = bytes.fromhex("89504e470d0a1a0a")  # a PNG signature is enough for inlining
    (tmp_path / "screenshots" / "step-01.png").write_bytes(png)
    data = {
        "task": "t", "success": False, "stopped_reason": "stuck",
        "steps": [
            {"n": 1, "kind": "click", "reasoning": "go", "url": "https://x/", "screenshot": "screenshots/step-01.png",
             "action": {"type": "click", "locator": [{"fn": "locator", "args": ["#go"]}]}},
            {"n": 2, "kind": "fill", "reasoning": "nope", "url": "https://x/", "screenshot": "screenshots/missing.png",
             "error": "timeout"},
        ],
    }
    doc = render_exploration_html(data, tmp_path)
    assert "data:image/png;base64,iVBORw0KGgo=" in doc  # step 1 inlined
    assert doc.count("<img") == 1  # missing screenshot is skipped, not broken
    assert "FAILED" in doc and "stuck" in doc and "timeout" in doc
    assert "&quot;type&quot;: &quot;click&quot;" in doc  # action JSON escaped into the card
