"""The create_agent explorer (explorer_v2) against real form fixtures, driven by LangChain's
own test double (GenericFakeChatModel scripting tool calls) — the v2 counterpart of
test_agent.py. Same behaviours: completes a form, records compilable steps, stops on done
(success=false), on an unchanged screen, and on a repeated futile action."""

import asyncio

import pytest

from netgent.agent import ExplorerMemory
from netgent.browser.session import BrowserSession

pytest.importorskip("langchain")

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

from netgent.agent.explorer_v2 import ExplorerAgent, explore  # noqa: E402

FORM = """<!doctype html><html><head><title>Agent Form</title></head><body>
<input id="name" name="name" type="text" placeholder="Name">
<input id="email" name="email" type="email" placeholder="Email">
<button type="submit" onclick="if(name.value&&email.value.includes('@')){
  document.title='DONE'; document.getElementById('ok').style.display='block';}">Submit</button>
<div id="ok" style="display:none">submitted</div>
</body></html>"""


class FakeModel(GenericFakeChatModel):
    def bind_tools(self, *args, **kwargs):
        return self


def call(name, i, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}"}])


def script(*turns):
    return FakeModel(messages=iter(list(turns)))


@pytest.fixture
def form_url(tmp_path):
    p = tmp_path / "form.html"
    p.write_text(FORM)
    return p.as_uri()


def test_v2_completes_a_form_with_scripted_tool_calls(form_url, tmp_path):
    model = script(
        call("fill", 1, index=0, text="Ada", reasoning="type the name"),
        call("fill", 2, index=1, text="ada@example.com", reasoning="type the email"),
        call("click", 3, index=2, reasoning="submit the form"),
        call("done", 4, success=True, reasoning="the form was submitted"),
    )
    memory = ExplorerMemory()

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await explore(s, "fill the form", model=model, memory=memory, url=form_url,
                                 run_dir=tmp_path / "traj")

    traj = asyncio.run(_run())
    assert traj.success, [(s.kind, s.error) for s in traj.steps]
    assert [s.kind for s in traj.steps] == ["goto", "fill", "fill", "click", "done"]
    assert all(s.action is not None for s in traj.steps[1:4])  # compilable: resolved durable locators
    assert traj.steps[1].action.text == "Ada" and traj.steps[3].url.endswith("form.html")
    assert (tmp_path / "traj" / "trajectory.json").is_file() and any(s.screenshot for s in traj.steps)
    assert [r.kind for r in memory.history] == ["fill", "fill", "click"] and memory.history[0].target == "Name"


REVEAL = """<!doctype html><html><body><button id="go"
  onclick="document.getElementById('ok').style.display='block'">Submit</button>
<div id="ok" style="display:none">Success! The secret is: dumbledore</div></body></html>"""


def test_v2_records_texts_seen_for_the_sweeps_verification(tmp_path):
    """texts_seen is what sweep._form_succeeded reads: text that appeared after an action must be
    in it even though v2 has no settle watcher (the next turn's snapshot catches it)."""
    page = tmp_path / "r.html"
    page.write_text(REVEAL)
    model = script(call("click", 1, index=0, reasoning="submit"), call("done", 2, success=True, reasoning="ok"))

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await explore(s, "submit", model=model, url=page.as_uri())

    traj = asyncio.run(_run())
    assert any("dumbledore" in t for t in traj.texts_seen) and "dumbledore" in traj.final_observation


def test_v2_stops_on_done_without_acting(form_url):
    model = script(call("done", 1, success=False, reasoning="a CAPTCHA is blocking the task"))

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await ExplorerAgent(model).run(s, "do the thing", form_url)

    traj = asyncio.run(_run())
    assert not traj.success and "CAPTCHA" in traj.stopped_reason
    assert [s.kind for s in traj.steps] == ["goto", "done"]


def test_v2_detects_an_unchanged_screen(form_url):
    model = script(*(call("scroll", i, down=True, pages=0.5, reasoning="scroll") for i in range(10)))

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await ExplorerAgent(model, max_steps=25).run(s, "scroll forever", form_url)

    traj = asyncio.run(_run())
    assert not traj.success and "stuck" in traj.stopped_reason and len(traj.steps) < 10


def test_v2_truncates_a_turn_to_max_actions_and_a_text_reply_costs_a_step(form_url):
    """Two tool calls in one turn with max_actions_per_step=1: the second is dropped
    (browser-use's truncation). A plain-text reply is an invalid step: re-observe, continue."""
    model = script(
        AIMessage(content="I will fill the form now."),  # no tool call
        AIMessage(content="", tool_calls=[
            {"name": "fill", "args": {"index": 0, "text": "Ada", "reasoning": "name"}, "id": "a"},
            {"name": "fill", "args": {"index": 1, "text": "x@y.z", "reasoning": "email"}, "id": "b"},
        ]),
        call("done", 3, success=True, reasoning="done"),
    )
    agent = ExplorerAgent(model)

    async def _run():
        async with BrowserSession(headless=True) as s:
            traj = await agent.run(s, "t", form_url)
            return traj, await s.page.locator("#email").input_value()

    traj, email = asyncio.run(_run())
    assert [s.kind for s in traj.steps] == ["goto", "fill", "done"] and email == ""
    assert any(r.kind == "invalid" for r in agent.history)


def test_v2_stops_after_repeating_the_same_futile_action(serve):
    page = """<!doctype html><html><body><button id="x">Dismiss</button><div id="chat"></div>
    <script>let i = 0; setInterval(() => { const a = document.createElement('a'); a.href = '#';
      a.textContent = 'chat message ' + (++i); document.getElementById('chat').appendChild(a); }, 15);</script>
    </body></html>"""
    srv = serve({"/": page})
    model = script(*(call("click", i, index=0, reasoning="dismiss the overlay") for i in range(12)))
    agent = ExplorerAgent(model, max_steps=12)

    async def _run():
        async with BrowserSession(headless=True) as s:
            return await agent.run(s, "watch the video", srv.url("/"))

    traj = asyncio.run(_run())
    assert not traj.success and traj.stopped_reason.startswith("stuck: repeated the same action 6 times")
    assert any(r.kind == "note" and "SAME action 3 times" in (r.note or "") for r in agent.history)
