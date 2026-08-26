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
            from netgent.browser.locators import unique_locator_for

            for e in files:
                await s.resolve(await unique_locator_for(s, e)).set_input_files(str(sample))
            return await s.page.locator("#echo").inner_text()

    assert asyncio.run(_run()) == "f1:cv.txt;f2:cv.txt;"


ARIA_AND_HIDDEN_RADIO = """<!doctype html><html><head><title>A</title></head><body>
<span id="country-label">Country</span>
<div id="dd" role="button" aria-haspopup="listbox" aria-labelledby="country-label dd" tabindex="0">\u200b</div>
<label style="display:inline-block;padding:4px">
  <input type="radio" name="c" value="email" style="opacity:0;position:absolute;width:0;height:0">Email me
</label>
<span id="visible-text">just text</span>
</body></html>"""


def test_aria_labelledby_names_and_hidden_labeled_radios_are_observed(serve):
    srv = serve({"/": ARIA_AND_HIDDEN_RADIO})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            snap = await s.snapshot()
            dd = next(e for e in snap.elements if e.role == "button" and e.tag == "div")
            radio = next((e for e in snap.elements if e.type == "radio"), None)
            return dd.name, radio

    name, radio = asyncio.run(_run())
    assert name == "Country"  # resolved via aria-labelledby, not the zero-width text
    assert radio is not None and radio.name == "Email me"  # hidden input, visible label
    assert radio.bbox.w > 0  # geometry reported from the LABEL, not the 0x0 input
