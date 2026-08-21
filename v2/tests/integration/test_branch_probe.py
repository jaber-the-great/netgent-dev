"""Branch.probe_ms: an interstitial that appears a beat AFTER the page does is still
seen within the bounded probe window; with probe_ms=0 the ε-arm is taken instead."""

import asyncio

import pytest

from netgent.browser.session import BrowserSession
from netgent.executor.engine import Executor
from netgent.schema.workflow import Workflow

PAGE = """<!doctype html><html><head><title>Late Popup</title></head><body>
<button id="late" style="display:none" onclick="this.style.display='none';document.title='dismissed'">Late</button>
<script>setTimeout(() => late.style.display='inline', 400)</script>
</body></html>"""


@pytest.fixture
def url(tmp_path):
    p = tmp_path / "late.html"
    p.write_text(PAGE)
    return p.as_uri()


def _wf(url: str, probe_ms: int) -> Workflow:
    return Workflow.model_validate(
        {
            "name": "late",
            "start_state": "init",
            "states": [
                {"id": "init"},
                {"id": "page", "conditions": [{"type": "title_contains", "text": "Late Popup"}]},
                {"id": "popup", "conditions": [{"type": "selector_visible", "selector": "#late"}]},
                {"id": "joined"},
            ],
            "transitions": [
                {"id": "open", "source": "init", "target": "page", "action": {"type": "goto", "url": url}},
                {"id": "eps_in", "source": "page", "target": "popup", "action": {"type": "noop"}},
                {
                    "id": "dismiss",
                    "source": "popup",
                    "target": "joined",
                    "action": {"type": "click", "locator": [{"fn": "locator", "args": ["#late"]}]},
                },
                {"id": "eps", "source": "page", "target": "joined", "action": {"type": "noop"}},
            ],
            "control": [
                {"kind": "edge", "edge": "open"},
                {
                    "kind": "branch",
                    "arms": [
                        {
                            "when": "popup",
                            "then": [{"kind": "edge", "edge": "eps_in"}, {"kind": "edge", "edge": "dismiss"}],
                        }
                    ],
                    "else": [{"kind": "edge", "edge": "eps"}],
                    "probe_ms": probe_ms,
                },
            ],
        }
    )


@pytest.mark.parametrize("probe_ms,expected", [(2000, ["open", "eps_in", "dismiss"]), (0, ["open", "eps"])])
def test_probe_window_decides_the_arm(url, probe_ms, expected):
    async def _run():
        async with BrowserSession(headless=True) as s:
            return await Executor(s, _wf(url, probe_ms)).run()

    record = asyncio.run(_run())
    assert record.success, [e.error for e in record.edges]
    assert [e.transition_id for e in record.edges] == expected
