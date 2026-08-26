"""Generic action-fallback ladders (browser/actions.py) — the mechanisms every mature agent
converges on (Skyvern chain_click / input_sequentially / normal_select ladder, browser-use
readback+retry, Stagehand trusted-input typing). Fixtures are element-CLASS patterns
(controlled inputs, overlays, non-native dropdowns), not any specific site."""

import asyncio

from netgent.browser import BrowserSession
from netgent.schema.actions import ClickAction, FillAction, LocatorStep, SelectAction

CONTROLLED_INPUT = """<!doctype html><html><head><title>C</title></head><body>
<input id="ctl" placeholder="Controlled">
<script>
// A framework-controlled input that REJECTS untrusted writes: synthetic input events
// (Playwright's fill) get reverted; only trusted key events stick.
const el = document.getElementById('ctl');
el.addEventListener('input', (e) => { if (!e.isTrusted) el.value = ''; });
</script></body></html>"""

COVERED_BUTTON = """<!doctype html><html><head><title>O</title></head><body>
<button id="buy" onclick="document.getElementById('echo').textContent='bought'">Buy</button>
<div style="position:fixed;inset:0;background:rgba(0,0,0,.01)"></div>
<div id="echo"></div>
</body></html>"""

DIV_DROPDOWN = """<!doctype html><html><head><title>D</title></head><body>
<div id="dd" role="button" tabindex="0">Select country</div>
<ul id="menu" role="listbox" style="display:none">
  <li role="option">United States</li><li role="option">Canada</li>
</ul>
<div id="echo"></div>
<script>
document.getElementById('dd').addEventListener('click', () => {
  document.getElementById('menu').style.display = 'block';
});
for (const li of document.querySelectorAll('[role=option]'))
  li.addEventListener('click', () => { document.getElementById('echo').textContent = li.textContent; });
</script></body></html>"""


def _run(html, coro):
    async def go(serve_fn):
        srv = serve_fn({"/": html})
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            return await coro(s)
    return go


def test_fill_escalates_to_trusted_typing_on_controlled_input(serve):
    async def steps(s):
        await s.dispatch(FillAction(locator=[LocatorStep(fn="locator", args=["#ctl"])], text="a@b.co", timeout_ms=3000))
        return await s.page.locator("#ctl").input_value()

    assert asyncio.run(_run(CONTROLLED_INPUT, steps)(serve)) == "a@b.co"


def test_click_falls_back_to_js_when_overlay_intercepts(serve):
    async def steps(s):
        await s.dispatch(ClickAction(locator=[LocatorStep(fn="locator", args=["#buy"])], timeout_ms=1500))
        return await s.page.locator("#echo").inner_text()

    assert asyncio.run(_run(COVERED_BUTTON, steps)(serve)) == "bought"


def test_select_expands_and_picks_on_non_native_dropdown(serve):
    async def steps(s):
        action = SelectAction(locator=[LocatorStep(fn="locator", args=["#dd"])], value="Canada", timeout_ms=3000)
        await s.dispatch(action)
        return await s.page.locator("#echo").inner_text()

    assert asyncio.run(_run(DIV_DROPDOWN, steps)(serve)) == "Canada"
