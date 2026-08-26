"""Hidden file inputs are observed (dom/scripts/snapshot.js).

Custom upload widgets hide the real <input type=file> (Bootstrap custom-file: opacity 0;
Material UI: display:none behind a styled <label>). Playwright's set_input_files works on a
hidden input, so dropping them from the observation left the agent clicking the styled label
(native chooser we don't drive) or erroring "Node is not an HTMLInputElement" — measured on
browser-use's jQuery-Bootstrap and Material-UI stress forms.
"""

import asyncio

from netgent.browser import BrowserSession

HIDDEN_UPLOADS = """<!doctype html><html><head><title>Up</title></head><body>
<label for="f1" style="border:1px solid #888;padding:4px">UPLOAD FILE</label>
<input id="f1" type="file" style="display:none">
<input id="f2" type="file" style="opacity:0;width:200px;height:30px">
<input id="t1" type="text" style="display:none" placeholder="really hidden text stays hidden">
<div id="echo"></div>
<script>
for (const id of ['f1', 'f2']) document.getElementById(id).addEventListener('change', (e) => {
  document.getElementById('echo').textContent += id + ':' + e.target.files[0].name + ';';
});
</script></body></html>"""


def test_hidden_file_inputs_are_observed_and_fillable(serve, tmp_path):
    srv = serve({"/": HIDDEN_UPLOADS})
    sample = tmp_path / "cv.txt"
    sample.write_text("x")

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            snap = await s.snapshot()
            files = [e for e in snap.elements if e.type == "file"]
            assert len(files) == 2, [(e.tag, e.type, e.name) for e in snap.elements]
            # ordinary hidden elements are still filtered — only file inputs are exempt
            assert not any(e.type == "text" for e in snap.elements)
            from netgent.agent.explore_agent.observation import unique_locator_for

            for e in files:
                await s.resolve(await unique_locator_for(s, e)).set_input_files(str(sample))
            return await s.page.locator("#echo").inner_text()

    assert asyncio.run(_run()) == "f1:cv.txt;f2:cv.txt;"
