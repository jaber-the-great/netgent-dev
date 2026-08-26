"""Rich-text naming + upload chooser-fallback (the two action-layer fixes measured on
browser-use's Rich Text and Material-UI stress forms)."""

import asyncio

from netgent.browser import BrowserSession
from netgent.schema.actions import LocatorStep, UploadFileAction

QUILL_LIKE = """<!doctype html><html><head><title>RT</title></head><body>
<label>Email Address</label>
<div class="editor" contenteditable="true" data-placeholder="Enter your email address"><p><br></p></div>
<input id="plain" placeholder="Plain">
</body></html>"""

CHOOSER_WIDGET = """<!doctype html><html><head><title>Up</title></head><body>
<label id="lbl" for="real" style="border:1px solid;padding:6px">UPLOAD FILE</label>
<input id="real" type="file" style="display:none">
<div id="echo"></div>
<script>document.getElementById('real').addEventListener('change', (e) => {
  document.getElementById('echo').textContent = e.target.files[0].name;
});</script></body></html>"""


def test_contenteditable_named_from_data_placeholder_and_children_suppressed(serve):
    srv = serve({"/": QUILL_LIKE})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            return await s.snapshot()

    snap = asyncio.run(_run())
    editors = [e for e in snap.elements if e.tag == "div"]
    assert [e.name for e in editors] == ["Enter your email address"]  # named, and only the ROOT
    assert editors[0].role == "textbox"  # contenteditable's implicit role: shown as fillable
    assert not any(e.tag in ("p", "br") for e in snap.elements)  # editor internals suppressed


def test_contenteditable_text_is_observed_as_value(serve):
    from netgent.schema.actions import FillAction, LocatorStep

    srv = serve({"/": QUILL_LIKE})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            await s.dispatch(FillAction(locator=[LocatorStep(fn="locator", args=[".editor"])], text="a@b.co"))
            return next(e for e in (await s.snapshot()).elements if e.tag == "div").value

    assert asyncio.run(_run()) == "a@b.co"  # the fill is visible in the next observation


def test_upload_falls_back_to_file_chooser_when_locator_is_the_label(serve, tmp_path):
    """The agent sometimes captures the styled label instead of the hidden input; the
    dispatcher must still land the file (click + intercepted chooser)."""
    srv = serve({"/": CHOOSER_WIDGET})
    f = tmp_path / "cv.txt"
    f.write_text("x")

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            action = UploadFileAction(locator=[LocatorStep(fn="locator", args=["#lbl"])], paths=[str(f)])
            await s.dispatch(action)  # direct set_input_files fails (label) -> chooser route
            await s.page.wait_for_timeout(200)
            return await s.page.locator("#echo").inner_text()

    assert asyncio.run(_run()) == "cv.txt"
