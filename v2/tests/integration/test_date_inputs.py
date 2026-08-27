"""Date inputs: the observation carries a format= hint from signals the page exposes, and a
keystroke-driven datepicker keeps a typed date (docs/research/browser-agent-date-inputs.md).

Fixtures reproduce the two mechanisms measured on browser-use's stress forms: an attribute
that states the format (angular-ui-bootstrap's uib-datepicker-popup) with framework-side
invalidity (ng-invalid), and a bootstrap-datepicker-style widget that binds keyup only and
wipes the field on blur when nothing was typed key-by-key.
"""

import asyncio

from netgent.browser import BrowserSession
from netgent.browser.dom import format_observation
from netgent.schema.actions import FillAction, LocatorStep

L = lambda css: [LocatorStep(fn="locator", args=[css])]  # noqa: E731

HINTS = """<!doctype html><html lang="en-US"><body>
<label for="dob">Date of Birth</label>
<input id="dob" type="text" uib-datepicker-popup="MM/dd/yyyy" class="ng-invalid" required>
<div class="input-group date"><label for="bs">Start</label><input id="bs" type="text"></div>
<label for="ph">Ends</label><input id="ph" type="text" placeholder="dd/mm/yyyy">
<label for="nat">Native</label><input id="nat" type="date">
<label for="plain">Nickname</label><input id="plain" type="text">
</body></html>"""

# bootstrap-datepicker semantics: only keyup feeds the widget; blur re-renders the field
# from what the widget captured (forceParse) — nothing captured → the value is wiped.
PICKER = """<!doctype html><html><body>
<div class="input-group date"><input id="d" type="text"></div>
<input id="other" type="text">
<script>
  const d = document.getElementById('d'); let captured = '';
  d.addEventListener('keyup', () => { captured = d.value; });
  d.addEventListener('blur', () => { d.value = captured; });
</script></body></html>"""


def test_observation_shows_format_from_attribute_placeholder_and_picker_ancestor(serve):
    srv = serve({"/": HINTS})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            snap = await s.snapshot()
            return {e.name: e for e in snap.interactive()}, format_observation(snap)

    els, text = asyncio.run(_run())
    assert els["Date of Birth"].format == "MM/DD/YYYY" and els["Date of Birth"].picker == "attr"
    assert els["Date of Birth"].invalid  # ng-invalid: framework-side rejection is surfaced
    assert els["Start"].format == "MM/DD/YYYY" and els["Start"].picker == "bootstrap-datepicker"
    assert els["Ends"].format == "DD/MM/YYYY"
    assert els["Native"].format == "YYYY-MM-DD"
    assert els["Nickname"].format is None  # never guessed from a label
    assert 'input[text] "Date of Birth" format=MM/DD/YYYY' in text
    assert 'input[text] "Start" format=MM/DD/YYYY picker=bootstrap-datepicker' in text


def test_fill_survives_a_keystroke_only_datepicker_and_leaves_native_dates_alone(serve):
    srv = serve({"/": PICKER, "/native.html": '<input id="n" type="date"><input id="o">'})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            await s.dispatch(FillAction(locator=L("#d"), text="05/15/1990"))
            await s.page.locator("#other").click()  # the blur that wipes a fill()-only value
            picker_value = await s.page.locator("#d").input_value()
            await s.page.goto(srv.url("/native.html"))
            await s.dispatch(FillAction(locator=L("#n"), text="1990-05-15"))
            native_value = await s.page.locator("#n").input_value()
            return picker_value, native_value

    picker_value, native_value = asyncio.run(_run())
    assert picker_value == "05/15/1990"  # typed per key, committed on blur
    assert native_value == "1990-05-15"  # native date: still fill(), never per-key typing
