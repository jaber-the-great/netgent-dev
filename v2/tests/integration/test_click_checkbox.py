"""A single ClickAction handles checkboxes (toggle) and radios (select) at dispatch."""

import asyncio

from netgent.browser.session import BrowserSession
from netgent.schema.actions import ClickAction, LocatorStep

FIXTURE = """<!doctype html><html><body>
<input type="checkbox" id="tos">
<input type="radio" name="g" id="r1"><input type="radio" name="g" id="r2">
<button id="btn" onclick="document.title='CLICKED'">Go</button>
</body></html>"""


def _click(id_):
    return ClickAction(locator=[LocatorStep(fn="locator", args=[f"#{id_}"])])


def test_click_toggles_checkbox_and_selects_radio_and_clicks_button(tmp_path):
    page = tmp_path / "f.html"
    page.write_text(FIXTURE)

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(page.as_uri())
            # checkbox: click toggles on, click again toggles off
            await s.dispatch(_click("tos"))
            on = await s.page.locator("#tos").is_checked()
            await s.dispatch(_click("tos"))
            off = await s.page.locator("#tos").is_checked()
            # radio: click selects
            await s.dispatch(_click("r2"))
            r2 = await s.page.locator("#r2").is_checked()
            # button: plain click fires the handler
            await s.dispatch(_click("btn"))
            title = await s.page.title()
            return on, off, r2, title

    on, off, r2, title = asyncio.run(_run())
    assert on is True and off is False  # checkbox toggled both ways
    assert r2 is True  # radio selected
    assert title == "CLICKED"  # button clicked normally
