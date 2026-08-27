"""The validation agent replays a generated workflow with zero LLM and reports edge outcomes."""

import asyncio

from netgent.agent.explorer.browser_agent import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.agent.validator import validate_workflow

FIXTURE = """<!doctype html><html><head><title>Hello</title></head><body>
<input id="name" placeholder="name">
<button id="go" onclick="document.getElementById('ok').style.display='block'">Go</button>
<div id="ok" style="display:none">welcome</div>
</body></html>"""


def test_validator_replays_compiled_workflow(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    traj = AgentTrajectory(
        task="fill the name and press go",
        success=True,
        steps=[
            AgentStep(n=0, kind="goto", reasoning="start", url=page.as_uri(),
                      action={"type": "goto", "url": page.as_uri()}),
            AgentStep(n=1, kind="fill", reasoning="name", url=page.as_uri(),
                      action={"type": "fill", "locator": [{"fn": "locator", "args": ["#name"]}], "text": "Ada"}),
            AgentStep(n=2, kind="click", reasoning="go", url=page.as_uri(),
                      action={"type": "click", "locator": [{"fn": "locator", "args": ["#go"]}]}),
            AgentStep(n=3, kind="done", reasoning="done", url=page.as_uri()),
        ],
    )
    wf = compile_trajectory(traj, name="hello", params={"who": "Ada"})

    report = asyncio.run(validate_workflow(wf, [{}, {"who": "Grace"}]))
    assert report.validated, [(r.params, r.failed_edge, r.error) for r in report.replays]
    assert [r.edges_ok for r in report.replays] == [3, 3]


def test_validator_reports_a_failing_edge(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    traj = AgentTrajectory(
        task="click something that does not exist",
        success=True,
        steps=[
            AgentStep(n=0, kind="goto", reasoning="start", url=page.as_uri(),
                      action={"type": "goto", "url": page.as_uri()}),
            AgentStep(n=1, kind="click", reasoning="nope", url=page.as_uri(),
                      action={"type": "click", "locator": [{"fn": "locator", "args": ["#missing"]}],
                              "timeout_ms": 500}),
        ],
    )
    wf = compile_trajectory(traj, name="broken")
    report = asyncio.run(validate_workflow(wf))
    assert not report.validated
    # The anchored compiler guards s1 on t2's target (#missing), so the drift surfaces
    # at t1's recognition — before the doomed click — as a trigger timeout naming it.
    assert report.replays[0].failed_edge == "t1"
    assert "selector_visible" in (report.replays[0].error or "")
