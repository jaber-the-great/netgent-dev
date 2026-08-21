"""Upload through the VISIBLE control: a <label role=button> (MUI-style) or a <button> beside a
hidden <input type=file> must still end up as set_input_files on the real input."""

import asyncio

from netgent.agent.explore_agent.decision import AgentDecision
from netgent.agent.explore_agent.observation import to_action
from netgent.browser.session import BrowserSession

PAGE = """<!doctype html><html><body>
<form id=f>
  <label role="button" tabindex="0" id="lbl">UPLOAD FILE <input type=file hidden id=real></label>
  <div class="form-group"><button type=button id=btn>Choose file</button>
    <input type=file style="display:none" id=real2></div>
</form>
<div id=out></div>
<script>
for (const id of ['real','real2']) document.getElementById(id).addEventListener('change', e =>
  document.getElementById('out').textContent += id + ':' + e.target.files[0].name + ' ');
</script></body></html>"""


def test_upload_via_label_and_button(tmp_path):
    page = tmp_path / "u.html"
    page.write_text(PAGE)
    sample = tmp_path / "sample.txt"
    sample.write_text("x")

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(page.as_uri())
            snap = await s.snapshot()
            for name in ("UPLOAD FILE", "Choose file"):
                idx = next(i for i, e in enumerate(snap.elements) if e.name == name)
                action = to_action(AgentDecision(reasoning="", kind="upload", index=idx), snap, upload_path=str(sample))
                await s.dispatch(action)
            return await s.page.locator("#out").inner_text()

    assert asyncio.run(_run()).strip() == "real:sample.txt real2:sample.txt"
