"""Dynamic parameters end to end: a value observed on the page feeds a later step.

A fixture reveals a confirmation code after 'submit'; a workflow extracts it as a dynamic
param and navigates to a URL built from it — verified by the resulting state.
"""

import asyncio

from netgent.browser.session import BrowserSession
from netgent.executor.engine import Executor
from netgent.schema.control import ParamSource
from netgent.schema.workflow import Param, State, Transition, Workflow

FIXTURE = """<!doctype html><html><head><title>Confirm</title></head><body>
<button id="go" onclick="document.getElementById('code').textContent='ORD-77'">Submit</button>
<div id="code"></div>
<div id="target" style="display:none">landed</div>
</body></html>"""


def test_extract_value_reads_text_input_and_url(tmp_path):
    page = tmp_path / "c.html"
    page.write_text(FIXTURE)

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(page.as_uri())
            await s.page.click("#go")
            text = await s.extract_value(ParamSource(kind="text", selector="#code"))
            grp = await s.extract_value(ParamSource(kind="url_group", pattern=r"/([a-z]+)\.html$"))
            missing = await s.extract_value(ParamSource(kind="text", selector="#nope"))
            return text, grp, missing

    text, grp, missing = asyncio.run(_run())
    assert text == "ORD-77"
    assert grp == "c"
    assert missing is None


def test_dynamic_param_flows_into_a_later_edge(tmp_path):
    # Extract the confirmation code shown after submit, then navigate to a URL built from it.
    page = tmp_path / "c.html"
    page.write_text(FIXTURE)
    base = page.parent.as_uri()

    wf = Workflow(
        name="dyn",
        start_state="init",
        params=[Param(name="code", source=ParamSource(kind="text", selector="#code"), guard=r"^ORD-\d+$")],
        states=[
            State(id="init"),
            State(id="submitted", conditions=[{"type": "selector_visible", "selector": "#code"}]),
            State(id="confirmed", conditions=[{"type": "url_matches", "pattern": "code=ORD-77"}]),
        ],
        transitions=[
            Transition(id="open", source="init", target="init",
                       action={"type": "goto", "url": f"{base}/c.html"}),
            Transition(id="submit", source="init", target="submitted",
                       action={"type": "click", "locator": [{"fn": "locator", "args": ["#go"]}]}),
            # this URL uses the dynamic param extracted from the page above
            Transition(id="confirm", source="submitted", target="confirmed",
                       action={"type": "goto", "url": f"{base}/c.html?code=${{code}}"}),
        ],
        control_sequence=["open", "submit", "confirm"],
    )

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await Executor(s, wf).run()

    record = asyncio.run(_run())
    assert record.success, [(e.transition_id, e.outcome, e.error) for e in record.edges]
    assert record.edges[-1].url_after.endswith("code=ORD-77")
