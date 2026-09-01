"""MEDIA line: a <video>'s own playback state reaches the observation, and it changes while
the media plays even when the page's control labels do not (the YouTube frozen-control-bar
case that made stuck detection fire on a playing video)."""

import asyncio

from netgent.browser import BrowserSession
from netgent.browser.dom import format_observation

# A muted autoplaying <video> (allowed without a gesture) with a generated 2-second WebM-free
# source: a MediaSource is overkill — a canvas captureStream gives a real, playing <video>.
PAGE = """<!doctype html><html><body>
<button id="play">Play (k)</button>
<video id="v" muted autoplay playsinline></video>
<script>
  const c = document.createElement('canvas'); c.width = 64; c.height = 64;
  const ctx = c.getContext('2d'); let i = 0;
  setInterval(() => { ctx.fillStyle = i++ % 2 ? 'red' : 'blue'; ctx.fillRect(0, 0, 64, 64); }, 50);
  const v = document.getElementById('v'); v.srcObject = c.captureStream(20); v.play();
</script></body></html>"""


def test_media_line_reports_playback_and_changes_while_labels_freeze(serve):
    srv = serve({"/": PAGE})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            await s.page.wait_for_timeout(600)
            a = await s.snapshot()
            await s.page.wait_for_timeout(1200)
            b = await s.snapshot()
            return a, b

    a, b = asyncio.run(_run())
    assert a.media and a.media[0].tag == "video" and a.media[0].muted
    assert not b.media[0].paused and b.media[0].current_time > a.media[0].current_time
    oa, ob = format_observation(a), format_observation(b)
    assert "MEDIA: video " in oa and "playing muted" in ob
    assert oa != ob  # the observation moves with the media, so stuck detection cannot misfire
    assert [ln for ln in oa.splitlines() if ln.startswith("[")] == [ln for ln in ob.splitlines() if ln.startswith("[")]
