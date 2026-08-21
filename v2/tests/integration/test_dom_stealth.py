"""DOM snapshot + stealth hardening against real Chromium and local fixtures.

Uses shadow-DOM and nested-interactive fixtures (the kinds of pages browser-use's
stress-tests corpus is built from) served locally — no live sites.
"""

import asyncio

import pytest

from netgent.browser.session import PATCHED_BROWSER, BrowserSession

SHADOW_FIXTURE = """<!doctype html><html><head><title>Shadow Form</title></head><body>
<h1>outer</h1>
<button id="plain">Plain Button</button>
<div id="host"></div>
<script>
  const root = document.getElementById('host').attachShadow({mode: 'open'});
  root.innerHTML = '<input type="text" placeholder="Email in shadow"><button>Shadow Submit</button>';
</script>
</body></html>"""


@pytest.fixture
def shadow_url(tmp_path):
    p = tmp_path / "shadow.html"
    p.write_text(SHADOW_FIXTURE)
    return p.as_uri()


def test_snapshot_pierces_shadow_dom(shadow_url):
    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(shadow_url)
            return await s.snapshot()

    snap = asyncio.run(_run())
    names = {e.name for e in snap.interactive()}
    # both the light-DOM button and the shadow-DOM input+button must be found
    assert "Plain Button" in names
    assert "Shadow Submit" in names
    assert any("shadow" in (e.name or "").lower() for e in snap.interactive())
    # every element carries at least a css candidate for the Generator to store
    assert all(e.candidates for e in snap.interactive())


def test_stealth_hides_webdriver_flag():
    async def _run(stealth):
        async with BrowserSession(headless=True, stealth=stealth) as s:
            await s.page.goto("about:blank")
            return await s.page.evaluate("navigator.webdriver")

    assert asyncio.run(_run(True)) in (False, None)  # hidden under stealth
    if not PATCHED_BROWSER:  # plain Playwright: the vanilla tell must still be present
        assert asyncio.run(_run(False)) is True


def test_stealth_fingerprint_is_consistent_with_the_real_binary():
    """No spoofed strings: the UA must match the launched browser's major version, carry
    no 'HeadlessChrome' stamp, and the page must look like a normal Chrome (plugins,
    window.chrome) WITHOUT any JS patching of navigator."""

    async def _run():
        async with BrowserSession(headless=True, stealth=True) as s:
            await s.page.goto("about:blank")
            fp = await s.page.evaluate(
                "({ua: navigator.userAgent, langs: navigator.languages, plugins: navigator.plugins.length, "
                "chrome: !!window.chrome, pluginArray: Object.prototype.toString.call(navigator.plugins)})"
            )
            return s._browser.version, fp

    version, fp = asyncio.run(_run())
    assert "HeadlessChrome" not in fp["ua"]
    assert f"Chrome/{version.split('.')[0]}." in fp["ua"]  # UA major == real binary major
    assert fp["langs"][0].startswith("en")
    assert fp["plugins"] > 0
    assert fp["chrome"] is True
    if PATCHED_BROWSER:  # native profile: a REAL PluginArray, not a spoofed JS array
        assert fp["pluginArray"] == "[object PluginArray]"
