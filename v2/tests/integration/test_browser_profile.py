"""DOM snapshot + browser-profile fidelity against real Chrome and local fixtures.

Uses shadow-DOM and nested-interactive fixtures (the kinds of pages browser-use's
stress-tests corpus is built from) served locally — no live sites.
"""

import asyncio
import platform
import sys

import pytest

from netgent.browser.profile import BrowserProfile
from netgent.browser.session import BrowserSession

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


def test_webdriver_flag_is_false_without_any_injection():
    """Real Chrome reports navigator.webdriver === false (the `undefined` an init-script shim
    produces is itself a tell). Patchright's launch switches, no JS of ours."""

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto("about:blank")
            return await s.page.evaluate("navigator.webdriver")

    assert asyncio.run(_run()) is False


def test_fingerprint_is_consistent_with_the_real_binary():
    """No spoofed strings: the UA must match the launched browser's major version, carry
    no 'HeadlessChrome' stamp, and the page must look like a normal Chrome (plugins,
    window.chrome, a REAL PluginArray) without any JS patching of navigator."""

    async def _run():
        async with BrowserSession(headless=True) as s:
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
    assert len(fp["langs"]) >= 2  # host default ["en-US", "en"]; a forced locale collapses this to one
    assert fp["plugins"] > 0
    assert fp["chrome"] is True
    assert fp["pluginArray"] == "[object PluginArray]"


SW_PAGE = """<!doctype html><html><body><h1>workers</h1><script>
window.__sw = new Promise((resolve) => {
  navigator.serviceWorker.register('/sw.js').then(async () => {
    navigator.serviceWorker.addEventListener('message', (e) => resolve(e.data));
    const ready = await navigator.serviceWorker.ready;
    ready.active.postMessage('ping');
  }).catch(e => resolve({error: String(e)}));
  setTimeout(() => resolve({error: 'timeout'}), 10000);
});
window.__shared = new Promise((resolve) => {
  const src = "onconnect = (e) => { const p = e.ports[0];"
    + " p.onmessage = () => p.postMessage({ua: navigator.userAgent}); };";
  const w = new SharedWorker(URL.createObjectURL(new Blob([src], {type: 'text/javascript'})));
  w.port.onmessage = (e) => resolve(e.data);
  w.port.start(); w.port.postMessage(1);
  setTimeout(() => resolve({error: 'timeout'}), 8000);
});
</script></body></html>"""
SW_JS = """self.addEventListener('message', (e) => {
  e.source.postMessage({ua: navigator.userAgent,
    brands: navigator.userAgentData ? navigator.userAgentData.brands : null});
});
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
"""
HINTS_JS = """async () => ({
  ua: navigator.userAgent, brands: navigator.userAgentData.brands, platform: navigator.userAgentData.platform,
  high: await navigator.userAgentData.getHighEntropyValues(['architecture', 'platformVersion', 'fullVersionList'])})"""


@pytest.mark.skipif(sys.platform == "win32", reason="platformVersion mapping on Windows is best-effort")
def test_headless_ua_reaches_workers_and_keeps_client_hints(serve):
    """The measured leak (docs/research/stealth-after-patchright.md): a context-level UA hides
    HeadlessChrome on the page but ServiceWorker/SharedWorker still report it, and the launch
    flag that fixes them empties the high-entropy client hints. Both must hold at once:
    every scope says Chrome, and the hints carry the host's real architecture / OS version."""
    srv = serve({"/": SW_PAGE, "/sw.js": SW_JS})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            page = await s.page.evaluate(HINTS_JS)
            sw = await s.page.evaluate("() => window.__sw", isolated_context=False)  # main world
            shared = await s.page.evaluate("() => window.__shared", isolated_context=False)
            return s._browser.version, page, sw, shared

    version, page, sw, shared = asyncio.run(_run())
    for scope, ua in (("page", page["ua"]), ("service worker", sw.get("ua")), ("shared worker", shared.get("ua"))):
        assert ua and "HeadlessChrome" not in ua, (scope, ua, sw, shared)
    assert sw["brands"], "the service worker's brands emptied — the UA is no longer coming from the launch flag"
    high = page["high"]
    expect_arch = "arm" if platform.machine().lower() in ("arm64", "aarch64") else "x86"
    assert high["architecture"] == expect_arch
    assert high["platformVersion"] not in ("", "10_15_7")  # empty = flag alone; 10_15_7 = the old context override
    if sys.platform == "darwin":
        assert high["platformVersion"] == platform.mac_ver()[0]
    assert {b["version"] for b in high["fullVersionList"]} >= {version}  # full version restored, from the binary
    assert [b["brand"] for b in high["fullVersionList"]] == [b["brand"] for b in page["brands"]]


def test_headed_uses_the_real_display_geometry():
    """A fixed viewport headed forces screen == viewport and DPR 1; the default profile leaves
    the window and screen alone, so screen geometry is the display's, not the viewport's."""

    async def _run(profile):
        async with BrowserSession(headless=False, profile=profile) as s:
            await s.page.goto("about:blank")
            return await s.page.evaluate(
                "({sw: screen.width, sh: screen.height, iw: innerWidth, ih: innerHeight, dpr: devicePixelRatio})"
            )

    natural = asyncio.run(_run(None))
    fixed = asyncio.run(_run(BrowserProfile(viewport=(1280, 800))))
    assert (fixed["iw"], fixed["ih"]) == (1280, 800)
    assert (natural["sw"], natural["sh"]) != (natural["iw"], natural["ih"])  # a real window inside a real screen
