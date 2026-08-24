"""Trajectory rendering (text + HTML) from a RunRecord — no browser needed."""

from netgent.report import load_record, render_html, render_text
from netgent.schema.records import ConditionCheck, EdgeRecord, RunRecord, utcnow


def _record() -> RunRecord:
    return RunRecord(
        workflow_name="demo",
        workflow_version="2",
        finished_at=utcnow(),
        success=False,
        edges=[
            EdgeRecord(
                transition_id="open",
                source="init",
                target="home",
                action_type="goto",
                outcome="ok",
                started_at=utcnow(),
                duration_ms=120.0,
                trigger_latency_ms=15.0,
                conditions=[ConditionCheck(type="url_matches", met=True)],
                url_after="https://example.com",
                screenshot="screenshots/open.png",
            ),
            EdgeRecord(
                transition_id="submit",
                source="home",
                target="done",
                action_type="click",
                outcome="trigger_timeout",
                started_at=utcnow(),
                duration_ms=5000.0,
                conditions=[ConditionCheck(type="selector_visible", met=False)],
                error="state 'done' not recognized within 5000ms; unmet conditions: ['selector_visible']",
            ),
        ],
    )


def test_render_text_shows_edges_and_conditions():
    text = render_text(_record())
    assert "demo v2 — FAILED (2 edges)" in text
    assert "1. ✓ open: goto (init → home)" in text
    assert "2. ✗ submit: click" in text
    assert "○ selector_visible" in text  # unmet condition marker
    assert "recognized home in 15ms" in text


def test_render_html_is_self_contained_and_embeds_screenshot():
    doc = render_html(_record())
    assert doc.startswith("<!doctype html>")
    assert "screenshots/open.png" in doc
    assert "url_matches" in doc and "selector_visible" in doc
    assert "FAILED" in doc


def test_record_round_trips_from_disk(tmp_path):
    path = tmp_path / "record.json"
    path.write_text(_record().model_dump_json())
    loaded = load_record(path)
    assert loaded.workflow_name == "demo"
    assert loaded.edges[1].outcome == "trigger_timeout"
    assert loaded.duration_ms is not None
