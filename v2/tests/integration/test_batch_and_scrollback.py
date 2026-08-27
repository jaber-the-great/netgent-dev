"""Batch execution semantics (one AgentStep per executed item, the two guards) and the
viewport scrollback policy on the exact geometry of the YouTube Skip case — against a real
browser with a scripted LLM."""

import asyncio

from netgent.agent import AgentDecision, BrowserAgent, FakeLLM
from netgent.agent.explorer.decision import AgentAction
from netgent.browser.dom import format_observation
from netgent.browser.session import BrowserSession

FORM = """<!doctype html><html><head><title>Batch</title></head><body>
<input id="name" placeholder="Name"><input id="email" placeholder="Email">
<a id="go" href="#done" onclick="document.getElementById('ok').style.display='block'">Submit</a>
<input id="after" placeholder="After">
<div id="ok" style="display:none">submitted</div>
</body></html>"""


def test_batch_executes_in_order_one_step_per_item_and_stops_at_a_navigation(tmp_path):
    page = tmp_path / "b.html"
    page.write_text(FORM)
    script = [
        AgentDecision(reasoning="fill both, submit, then keep going", kind="fill", index=0, text="Ada", then=[
            AgentAction(kind="fill", index=1, text="ada@x.io"),
            AgentAction(kind="click", index=2),  # navigates (#done) → the 4th item must be skipped
            AgentAction(kind="fill", index=3, text="never"),
        ]),
        AgentDecision(reasoning="done", done=True, success=True),
    ]

    async def _run():
        async with BrowserSession(headless=True) as s:
            agent = BrowserAgent(FakeLLM(script), max_actions_per_step=4)
            traj = await agent.run(s, "fill and submit", page.as_uri())
            after = await s.page.locator("#after").input_value()
            return traj, agent.history, after

    traj, history, after = asyncio.run(_run())
    assert traj.success
    expected = [(1, 0, "fill"), (1, 1, "fill"), (1, 2, "click"), (2, 0, "done")]
    assert [(s.n, s.item, s.kind) for s in traj.steps[1:]] == expected
    assert all(s.action is not None for s in traj.steps[1:4])  # each executed item is compilable
    assert after == ""  # the queued fill after the navigating click never ran
    notes = [r.note for r in history if r.kind == "note"]
    assert any("page changed after action 3" in n and "1 queued action(s) were skipped" in n for n in notes)


def test_single_action_default_ignores_a_batch(tmp_path):
    page = tmp_path / "s.html"
    page.write_text(FORM)
    script = [
        AgentDecision(reasoning="try to batch", kind="fill", index=0, text="Ada",
                      then=[AgentAction(kind="fill", index=1, text="x")]),
        AgentDecision(reasoning="done", done=True, success=True),
    ]

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await BrowserAgent(FakeLLM(script)).run(s, "t", page.as_uri())

    traj = asyncio.run(_run())
    assert [s.kind for s in traj.steps] == ["goto", "fill", "done"]  # max_actions_per_step=1: head only


def test_failed_item_aborts_the_rest_of_the_batch(tmp_path):
    page = tmp_path / "f.html"
    page.write_text(FORM)
    script = [
        AgentDecision(reasoning="bad then good", kind="fill", index=0, text="Ada", then=[
            AgentAction(kind="select", index=1, value="x"),  # not a dropdown → fails
            AgentAction(kind="fill", index=3, text="never"),
        ]),
        AgentDecision(reasoning="give up", done=True, success=False),
    ]

    async def _run():
        async with BrowserSession(headless=True) as s:
            agent = BrowserAgent(FakeLLM(script), max_actions_per_step=4)
            traj = await agent.run(s, "t", page.as_uri())
            return traj, agent.history

    traj, history = asyncio.run(_run())
    kinds = [(s.kind, s.error is not None) for s in traj.steps[1:]]
    assert kinds == [("fill", False), ("select", True), ("done", False)]
    assert any("1 queued action(s) were skipped" in (r.note or "") for r in history)


PLAYER = """<!doctype html><html><head><title>Player</title><style>
body{margin:0} #player{height:500px;background:#000;position:relative}
#skip{position:absolute;top:400px;left:20px} #below{height:3000px}
</style></head><body>
<div id="player"><button id="skip">Skip Ad</button></div>
<div id="below"><button id="like">Like</button></div>
</body></html>"""


def test_skip_button_stays_observed_after_scrolling_one_page(tmp_path):
    """The YouTube Skip geometry: after one page of scroll the player's control sits a few
    hundred px above the viewport top. The old 60 px cut dropped it; one viewport of
    scrollback keeps it listed and actionable."""
    page = tmp_path / "p.html"
    page.write_text(PLAYER)

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(page.as_uri())
            await s.page.set_viewport_size({"width": 1000, "height": 700})
            await s.page.mouse.wheel(0, 700)
            # wait on the scroll itself, not a fixed delay — 300ms flaked on loaded CI runners
            await s.page.wait_for_function("window.scrollY >= 700")
            snap = await s.snapshot()
            return snap

    snap = asyncio.run(_run())
    skip = next(e for e in snap.elements if e.name == "Skip Ad")
    assert -snap.viewport_height <= skip.bbox.y < -60, skip.bbox  # the exact band the old cut removed
    obs = format_observation(snap)
    assert 'button "Skip Ad"' in obs and "(↑" not in obs
    import os

    os.environ["NETGENT_OBS_SCROLLBACK"] = "0"
    try:
        legacy = format_observation(snap)
    finally:
        del os.environ["NETGENT_OBS_SCROLLBACK"]
    assert 'button "Skip Ad"' not in legacy and "(↑ 2 elements further above" in legacy  # Skip and Like both dropped
