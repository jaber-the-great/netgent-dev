"""End-to-end: a compiled workflow replayed through real Chromium against a local fixture.

No network, no LLM — the fixture page reveals #result only after the button is clicked,
so the target state's conditions genuinely gate on the action having worked.
"""

import asyncio

import pytest

from netgent.browser.session import BrowserSession
from netgent.executor.engine import Executor
from netgent.schema.actions import ClickAction, GotoAction, LocatorStep
from netgent.schema.triggers import SelectorVisible
from netgent.schema.workflow import State, Transition, Workflow

FIXTURE_HTML = """<!doctype html>
<html><head><title>NetGent Fixture</title></head><body>
<button onclick="setTimeout(() => {
  document.getElementById('result').style.display = 'block';
}, 200)">Go</button>
<div id="result" style="display:none">done!</div>
</body></html>"""


@pytest.fixture
def fixture_url(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(FIXTURE_HTML)
    return page.as_uri()


def make_workflow(url: str) -> Workflow:
    return Workflow(
        name="e2e-fixture",
        start_state="init",
        states=[
            State(id="init"),  # no conditions: recognized immediately
            State(id="page", conditions=[{"type": "title_contains", "text": "NetGent Fixture"}]),
            State(
                id="done",
                conditions=[{"type": "selector_visible", "selector": "#result"}],
                timeout_ms=5000,
            ),
        ],
        transitions=[
            Transition(id="open", source="init", target="page", action=GotoAction(url=url)),
            Transition(
                id="go",
                source="page",
                target="done",
                action=ClickAction(locator=[LocatorStep(fn="get_by_role", args=["button"], kwargs={"name": "Go"})]),
            ),
        ],
    )


def test_workflow_replays_end_to_end(fixture_url):
    async def _run():
        async with BrowserSession(headless=True) as session:
            return await Executor(session, make_workflow(fixture_url)).run()

    record = asyncio.run(_run())
    assert record.success, [e.error for e in record.edges]
    assert [e.outcome for e in record.edges] == ["ok", "ok"]
    # The delayed reveal (200ms) must show up as trigger latency, proving the
    # executor waited on the condition rather than racing past it.
    assert record.edges[1].trigger_latency_ms > 150
    # per-edge condition report is captured even without a run dir
    assert record.edges[1].conditions and record.edges[1].conditions[0].met


def test_trajectory_bundle_written(fixture_url, tmp_path):
    run_dir = tmp_path / "traj"

    async def _run():
        async with BrowserSession(headless=True) as session:
            return await Executor(session, make_workflow(fixture_url), run_dir=run_dir).run()

    record = asyncio.run(_run())
    assert record.success
    # record.json + one screenshot per edge exist and are referenced from the record
    assert (run_dir / "record.json").is_file()
    for edge in record.edges:
        assert edge.screenshot is not None
        assert (run_dir / edge.screenshot).is_file()
    # the saved record renders to a self-contained HTML page
    from netgent.trajectory import load_record, render_html

    doc = render_html(load_record(run_dir / "record.json"))
    assert "screenshots/open.png" in doc


def test_trigger_timeout_fails_loudly(fixture_url):
    wf = make_workflow(fixture_url)
    # Sabotage: expect a selector that never appears, with a short budget.
    wf.states[2].conditions = [SelectorVisible(selector="#never")]
    wf.states[2].timeout_ms = 800

    async def _run():
        async with BrowserSession(headless=True) as session:
            return await Executor(session, wf).run()

    record = asyncio.run(_run())
    assert not record.success
    assert record.edges[-1].outcome == "trigger_timeout"
    assert "selector_visible" in record.edges[-1].error
