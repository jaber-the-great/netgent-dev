"""M0 — the candidate ladder on the record: the walker emits a structural (positional) rung
for list items, the probe counts every rung against the live page, and the explorer stores
the whole ladder on the AgentStep so a later compile can pick a different rung offline."""

import asyncio
import json

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.explorer.models import AgentTrajectory
from netgent.browser.locators import probe_ladder
from netgent.browser.session import BrowserSession

LIST_PAGE = """<!doctype html><html><head><title>Results</title></head><body>
<h1>Results</h1>
<ul id="results">
  <li><a href="/watch-a">Cat video A</a></li>
  <li><a href="/watch-b">Cat video B</a></li>
  <li><a href="/watch-c">Cat video C</a></li>
</ul>
</body></html>"""


def test_walker_emits_a_structural_rung_and_the_probe_indexes_it(tmp_path):
    page = tmp_path / "list.html"
    page.write_text(LIST_PAGE)

    async def run():
        async with BrowserSession() as s:
            await s.page.goto(page.as_uri())
            snap = await s.snapshot()
            links = [e for e in snap.elements if e.tag == "a"]
            assert len(links) == 3
            structural = [c for c in links[0].candidates if c.kind == "structural"]
            assert structural and structural[0].value == "#results > li > a"
            first = await probe_ladder(s, links[0])
            second = await probe_ladder(s, links[1])
            return first, second

    first, second = asyncio.run(run())
    k = first.rung("structural")
    assert k is not None and first.kinds[k] == "structural"
    assert first.counts[k] == 3 and first.indices[k] == 0  # the first item is match 0
    assert second.counts[second.rung("structural")] == 3 and second.indices[second.rung("structural")] == 1
    assert first.counts[first.rung("role")] == 1  # the title-keyed rung is unique, and wins


def test_explorer_records_the_ladder_on_the_step(tmp_path):
    from netgent.agent.explorer.graph import explore

    page = tmp_path / "list.html"
    page.write_text(LIST_PAGE)
    llm = FakeLLM([
        AgentDecision(reasoning="open the first result", kind="click", index=0),
        AgentDecision(reasoning="done", done=True, success=True),
    ])

    async def run():
        async with BrowserSession() as s:
            return await explore(s, "open the first result", llm=llm, url=page.as_uri(), run_dir=tmp_path / "run")

    traj = asyncio.run(run())
    (click,) = [st for st in traj.steps if st.kind == "click"]
    assert click.action is not None and click.action.locator[-1].fn == "get_by_role"  # the winner, as before
    assert click.candidate_kinds == ["role", "css", "structural"]
    assert [c[-1].args[0] for c in click.locator_candidates][1:] == [
        "#results > li:nth-of-type(1) > a", "#results > li > a",
    ]
    assert click.match_counts == [1, 1, 3] and click.match_indices == [None, None, 0]
    assert click.element == {"tag": "a", "role": None, "name": "Cat video A", "type": None, "frame_path": []}
    # the record round-trips: an older trajectory without these fields still loads (defaults)
    data = json.loads((tmp_path / "run" / "trajectory.json").read_text())
    back = AgentTrajectory.model_validate(data)
    assert back.steps[1].match_counts == [1, 1, 3]
    for key in ("locator_candidates", "candidate_kinds", "match_counts", "match_indices", "element"):
        data["steps"][1].pop(key)
    assert AgentTrajectory.model_validate(data).steps[1].locator_candidates == []
