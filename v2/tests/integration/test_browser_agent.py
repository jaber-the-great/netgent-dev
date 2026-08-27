"""The full browser-agent loop against a real form fixture, driven by a scripted FakeLLM.

Exercises observe → decide → resolve-to-locator → dispatch end to end with no network/API key:
the agent finds elements by the index it saw in the observation, so the decisions are written
against the observation the real page produces.
"""

import asyncio

import pytest

from netgent.agent import AgentDecision, BrowserAgent, FakeLLM
from netgent.browser.dom import format_observation
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
        AgentDecision(reasoning="the form was submitted", done=True, success=True),
    ]

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await BrowserAgent(FakeLLM(script), run_dir=tmp_path / "traj").run(s, "fill the form", form_url)

    traj = asyncio.run(_run())
    assert traj.success, [(s.kind, s.error) for s in traj.steps]
    assert [s.kind for s in traj.steps] == ["goto", "fill", "fill", "click", "done"]
    assert (tmp_path / "traj" / "trajectory.json").is_file()
    # screenshots captured for the acting steps
    assert any(s.screenshot for s in traj.steps)


def test_agent_stops_on_captcha_signal(form_url, tmp_path):
    # On a CAPTCHA the model returns done(success=False); the agent must not attempt anything.
    script = [AgentDecision(reasoning="a CAPTCHA is blocking the task", done=True, success=False)]

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


REVEAL = """<!doctype html><html><head><title>Reveal</title></head><body>
<button id="open" onclick="document.getElementById('menu').style.display='block';
  document.getElementById('msg').style.display='block'">Country</button>
<div id="menu" style="display:none"><div role="option" id="ca">Canada</div></div>
<div id="msg" role="status" style="display:none">Menu opened</div>
</body></html>"""


def test_agent_sees_new_elements_starred_and_new_text_after_its_own_action(tmp_path):
    """The observation diff: the option that appeared because of the click is marked `*`
    and the transient status text is listed under NEW TEXT — and neither on the first step."""
    page = tmp_path / "reveal.html"
    page.write_text(REVEAL)
    seen: list[str] = []

    class Capturing(FakeLLM):
        async def decide(self, system, task, observation, history, **kw):
            seen.append(observation)
            return await super().decide(system, task, observation, history, **kw)

    script = [
        AgentDecision(reasoning="open the menu", kind="click", index=0, memory="opening", next_goal="pick Canada"),
        AgentDecision(reasoning="pick", kind="click", index=1, evaluation="menu opened. Verdict: Success"),
        AgentDecision(reasoning="done", done=True, success=True),
    ]

    async def _run():
        async with BrowserSession(headless=True) as s:
            agent = BrowserAgent(Capturing(script))
            traj = await agent.run(s, "pick Canada", page.as_uri())
            return traj, agent.history

    traj, history = asyncio.run(_run())
    assert traj.success
    assert "CHANGED SINCE LAST STEP" not in seen[0] and "*[" not in seen[0]
    assert "CHANGED SINCE LAST STEP: 1 new element (marked *), 1 new text line (see NEW TEXT)." in seen[1]
    assert ' *[1] div (option) "Canada"' in seen[1] and '  [0] button "Country"' in seen[1]
    assert "NEW TEXT SINCE LAST STEP:\n  !ALERT Menu opened" in seen[1]
    # the typed memory carries the model's own fields and the element name, not just an index
    assert history[0].target == "Country" and history[0].memory == "opening"
    assert history[1].evaluation.endswith("Verdict: Success")
    assert traj.steps[1].memory == "opening" and traj.steps[1].action is not None
