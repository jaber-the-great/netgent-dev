"""A compiled anchor must resolve exactly what its edge's action resolves.

The archive.org regression (docs/research/media-platforms-eval.md): the explorer's captured
chain was `get_by_role("link", name="Web icon An illustration of a")` — Playwright's own
selector generator shortens accessible names to a ≤30-character word prefix, which is fine
because get_by_role matches by SUBSTRING. The compiler rendered the anchor as
`role=link[name="…" i]`, and Playwright's public `role=` engine matches that EXACTLY: the
click found one element, the anchor guarding it found none, and replay died on edge 1.

Here the accessible name is longer than every cap in the pipeline (the walker's 120-char
`clean()`, Playwright's 30-char prefix), the captured chain carries a strict prefix of it,
and the compiled anchor — the chain itself — must hold on zero-LLM replay.
"""

import asyncio

import pytest

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.browser.locators import capture_locator
from netgent.browser.session import BrowserSession
from netgent.executor.engine import Executor
from netgent.schema.actions import ClickAction, GotoAction
from netgent.schema.triggers import SelectorVisible
from netgent.schema.workflow import State

LONG_NAME = (
    "Web icon An illustration of a computer application window showing the Wayback Machine "
    "archive of billions of web pages captured over more than twenty five years of crawling"
)
assert len(LONG_NAME) > 120

PAGE = f"""<!doctype html><html><head><title>Anchor fixture</title></head><body>
<a href="#" aria-label="{LONG_NAME}"
   onclick="document.getElementById('result').style.display='block'; return false;">web</a>
<a href="#" aria-label="Wayback Machine home">home</a>
<div id="result" style="display:none"><button id="next">Next</button></div>
</body></html>"""


def test_compiled_anchor_holds_for_a_truncated_accessible_name(serve):
    srv = serve({"/": PAGE})

    async def run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            snap = await s.snapshot()
            (link,) = [el for el in snap.elements if el.tag == "a" and el.name.startswith("Web icon")]
            chain, note = await capture_locator(s, link)
            # The stored chain names the link by a PREFIX of its accessible name (whichever
            # stage shortened it) — the shape that broke the archive.org replay.
            assert chain[-1].fn == "get_by_role" and chain[-1].args == ["link"], (chain, note)
            captured = str(chain[-1].kwargs["name"])
            assert LONG_NAME.startswith(captured) and len(captured) < len(LONG_NAME), captured
            assert not chain[-1].kwargs.get("exact")

            traj = AgentTrajectory(task="open the web archive", success=True, steps=[
                AgentStep(n=0, kind="goto", reasoning="start", url=srv.url("/"), action=GotoAction(url=srv.url("/"))),
                AgentStep(n=1, kind="click", reasoning="open", url=srv.url("/"), action=ClickAction(locator=chain)),
                AgentStep(n=2, kind="click", reasoning="continue", url=srv.url("/"),
                          action=ClickAction(locator=[{"fn": "locator", "args": ["#next"]}])),
            ])
            wf = compile_trajectory(traj, name="anchor")
            (url_cond, anchor) = wf.state("s1").conditions
            assert anchor.type == "selector_visible" and anchor.locator == chain

            # The old rendering of that same name is unsatisfiable on this page — the bug.
            old = SelectorVisible(selector=f'role=link[name="{captured}" i]')
            assert (await s.condition_report(State(id="old", conditions=[old])))[0][1] is False
            # The chain form holds, because it IS what the click resolves.
            assert (await s.condition_report(State(id="new", conditions=[anchor])))[0][1] is True

            await s.page.goto("about:blank")
            record = await Executor(s, wf).run()
            assert record.success, [e.error for e in record.edges]
            assert [e.outcome for e in record.edges] == ["ok", "ok", "ok"]
            assert all(c.met for c in record.edges[0].conditions)  # s1: url + the chain anchor
            return record

    asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
