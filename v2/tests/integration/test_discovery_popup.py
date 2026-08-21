"""Explore → synthesize → validate on a local fixture whose cookie popup shows on the
FIRST visit only (localStorage). Two scripted explorations in one browser context see
the popup present and then absent; synthesis must emit a guarded ε-branch, and the
executor must take the click arm in a fresh session and the ε-arm in a warmed one —
zero LLM either way."""

import asyncio
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from netgent.agent import AgentDecision, BrowserAgent, FakeLLM
from netgent.agent.synthesis import Exploration, synthesize
from netgent.agent.validate import relax, replay_once
from netgent.browser.session import BrowserSession
from netgent.executor.engine import Executor
from netgent.schema.workflow import resolve_params

PAGE = """<!doctype html><html><head><title>Popup Fixture</title></head><body>
<div id="cookie" style="display:none;position:fixed;top:0;background:#eee;padding:8px">
  We use cookies
  <button id="proceed" onclick="localStorage.seen='1';this.parentNode.style.display='none'">Proceed</button>
</div>
<h1>Search</h1>
<input id="q" placeholder="Query">
<button id="go" onclick="location.href='done.html?q='+encodeURIComponent(q.value)">Go</button>
<script>
  // interstitial shows until dismissed once (localStorage needs a real origin: served over http)
  if (!localStorage.seen) cookie.style.display='block';
</script>
</body></html>"""

DONE = """<!doctype html><html><head><title>Done</title></head><body>
<h1>Results ready</h1><p id="msg">thanks</p>
</body></html>"""


@pytest.fixture
def site(tmp_path):
    (tmp_path / "index.html").write_text(PAGE)
    (tmp_path / "done.html").write_text(DONE)
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a, **k: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()


def _names(snapshot):
    return [e.name for e in snapshot.interactive()]


async def _explore(session, url, with_popup: bool, query: str):
    await session.page.goto(url)
    names = _names(await session.snapshot())
    script = []
    if with_popup:
        script.append(AgentDecision(reasoning="dismiss cookies", kind="click", index=names.index("Proceed")))
        after = [n for n in names if n != "Proceed"]
    else:
        after = names
    script += [
        AgentDecision(reasoning="type query", kind="fill", index=after.index("Query"), text=query),
        AgentDecision(reasoning="submit", kind="click", index=after.index("Go")),
        AgentDecision(reasoning="results shown", kind="done", success=True),
    ]
    traj = await BrowserAgent(FakeLLM(script)).run(session, f"search for {query}", url)
    assert traj.success, [(s.kind, s.error) for s in traj.steps]
    return Exploration(traj, {"query": query})


def test_popup_branch_synthesized_and_replays_both_ways(site):
    async def _main():
        async with BrowserSession(headless=True) as s:
            first = await _explore(s, site, with_popup=True, query="cats")  # first visit: popup
            second = await _explore(s, site, with_popup=False, query="dogs")  # same context: no popup
        result = synthesize([first, second], name="popup")
        wf = result.workflow

        # evidence captured on every acting step
        assert all(st.evidence is not None for st in first.trajectory.steps if st.action is not None)
        # core path: goto, fill, click (the Proceed click is optional → branch)
        assert [wf.transition(n.edge).action.type for n in wf.control if n.kind == "edge"] == ["goto", "fill", "click"]
        branch = next(n for n in wf.control if n.kind == "branch")
        assert wf.transition(branch.arms[0].then[-1].edge).action.locator[-1].args == ["#proceed"]
        assert wf.transition("t2").action.text == "${query}"
        # evidence conditions: the query field is the next target; done page has new text
        assert any(c.type == "element_visible" for c in wf.state("s1j").conditions)
        assert any(c.type == "text_visible" and c.text == "Results ready" for c in wf.state("s3").conditions)

        # fresh session (popup present): zero-LLM replay takes the click arm
        fresh = await replay_once(wf, {"query": "birds"})
        assert fresh.success, fresh
        # warmed session (popup absent): the ε-arm
        async with BrowserSession(headless=True) as s:
            await s.page.goto(site)
            await s.page.click("#proceed")
            record = await Executor(s, resolve_params(wf, {"query": "fish"}), params={"query": "fish"}).run()
        assert record.success, [e.error for e in record.edges]
        assert "t1_eps" in [e.transition_id for e in record.edges]
        assert "t1b1_1" not in [e.transition_id for e in record.edges]
        assert record.edges[-1].url_after.endswith("done.html?q=fish")
        return wf

    asyncio.run(_main())


def test_validation_relaxes_a_too_strict_condition(site):
    async def _main():
        async with BrowserSession(headless=True) as s:
            x = await _explore(s, site, with_popup=True, query="cats")
        wf = synthesize([x], name="strict").workflow
        # sabotage the final state with a condition the page never satisfies
        data = wf.model_dump(mode="json")
        data["states"][-1]["conditions"].append({"type": "text_visible", "text": "never shown"})
        data["states"][-1]["timeout_ms"] = 800
        from netgent.schema.workflow import Workflow

        strict = Workflow.model_validate(data)
        failed = await replay_once(strict, {"query": "x"})
        assert not failed.success and failed.unmet == ["text_visible"]
        assert failed.failed_state == strict.accept_states[0]
        relaxed, dropped = relax(strict, failed)
        assert dropped == [f"{failed.failed_state}: text_visible"]
        assert (await replay_once(relaxed, {"query": "x"})).success

    asyncio.run(_main())
