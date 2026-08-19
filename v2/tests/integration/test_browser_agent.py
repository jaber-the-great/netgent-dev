"""The full browser-agent loop against a real form fixture, driven by a scripted FakeLLM.

Exercises observe → decide → resolve-to-locator → dispatch end to end with no network/API key:
the agent finds elements by the index it saw in the observation, so the decisions are written
against the observation the real page produces.
"""

import asyncio

import pytest

from netgent.agent import AgentDecision, BrowserAgent, FakeLLM
from netgent.agent.observation import format_observation
from netgent.browser.session import BrowserSession

FORM = """<!doctype html><html><head><title>Agent Form</title></head><body>
<input id="name" name="name" type="text" placeholder="Name">
<input id="email" name="email" type="email" placeholder="Email">
<button type="submit" onclick="if(name.value&&email.value.includes('@')){
  document.title='DONE'; document.getElementById('ok').style.display='block';}">Submit</button>
<div id="ok" style="display:none">submitted</div>
</body></html>"""


@pytest.fixture
def form_url(tmp_path):
    p = tmp_path / "form.html"
    p.write_text(FORM)
    return p.as_uri()


def _index_of(session, placeholder):
    """Helper unused at runtime; documents that decisions target observed indices."""
    raise NotImplementedError


def test_agent_completes_a_form_with_scripted_llm(form_url, tmp_path):
    async def _observe_indices():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(form_url)
            snap = await s.snapshot()
            names = [e.name for e in snap.interactive()]
            return names, format_observation(snap)

    names, _obs = asyncio.run(_observe_indices())
    name_i = names.index("Name")
    email_i = names.index("Email")

    script = [
        AgentDecision(reasoning="type the name", kind="fill", index=name_i, text="Ada"),
        AgentDecision(reasoning="type the email", kind="fill", index=email_i, text="ada@example.com"),
        AgentDecision(reasoning="submit the form", kind="click", index=names.index("Submit")),
        AgentDecision(reasoning="the form was submitted", kind="done", success=True),
    ]

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await BrowserAgent(FakeLLM(script), run_dir=tmp_path / "traj").run(s, "fill the form", form_url)

    traj = asyncio.run(_run())
    assert traj.success, [(s.kind, s.error) for s in traj.steps]
    assert [s.kind for s in traj.steps] == ["fill", "fill", "click", "done"]
    assert (tmp_path / "traj" / "trajectory.json").is_file()
    # screenshots captured for the acting steps
    assert any(s.screenshot for s in traj.steps)


def test_agent_stops_on_captcha_signal(form_url, tmp_path):
    # The model is instructed to `stop` on a CAPTCHA; the agent must not attempt anything.
    script = [AgentDecision(reasoning="a CAPTCHA is blocking the task", kind="stop", success=False)]

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await BrowserAgent(FakeLLM(script)).run(s, "do the thing", form_url)

    traj = asyncio.run(_run())
    assert not traj.success
    assert "CAPTCHA" in traj.stopped_reason


def test_agent_detects_stuck_loop(form_url):
    # Same no-op decision repeated → the loop detector must break, not spin to max_steps.
    script = [AgentDecision(reasoning="scroll", kind="scroll", down=True, pages=0.5) for _ in range(10)]

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await BrowserAgent(FakeLLM(script), max_steps=25).run(s, "scroll forever", form_url)

    traj = asyncio.run(_run())
    assert not traj.success
    assert "stuck" in traj.stopped_reason
    assert len(traj.steps) < 10  # broke early
