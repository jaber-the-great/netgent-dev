"""The evidence triggers against local fixtures: element_visible (locator chain),
text_visible, video_playing (a canvas-stream <video> whose currentTime really advances)."""

import asyncio

import pytest

from netgent.agent.evidence import capture_evidence
from netgent.browser.session import BrowserSession
from netgent.schema.actions import LocatorStep
from netgent.schema.triggers import ElementVisible, TextVisible, VideoPlaying
from netgent.schema.workflow import State

VIDEO = """<!doctype html><html><head><title>Player</title></head><body>
<h1>Now Playing</h1>
<button id="play">Play</button>
<video id="v" muted></video>
<script>
  const c = document.createElement('canvas'); c.width = 64; c.height = 64;
  const ctx = c.getContext('2d'); let i = 0;
  setInterval(() => { ctx.fillStyle = i++ % 2 ? '#f00' : '#00f'; ctx.fillRect(0, 0, 64, 64); }, 50);
  play.onclick = () => { v.srcObject = c.captureStream(25); v.play(); };
</script>
</body></html>"""


@pytest.fixture
def player(tmp_path):
    p = tmp_path / "player.html"
    p.write_text(VIDEO)
    return p.as_uri()


def test_video_playing_and_text_and_element_triggers(player):
    async def _main():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(player)
            play = [LocatorStep(fn="get_by_role", args=["button"], kwargs={"name": "Play"})]
            assert await s._holds(ElementVisible(locator=play))
            assert not await s._holds(ElementVisible(locator=[LocatorStep(fn="locator", args=["#nope"])]))
            assert await s._holds(TextVisible(text="now playing"))  # substring, case-insensitive
            assert not await s._holds(TextVisible(text="paused"))
            # present but not running: video_playing must NOT hold
            before = await capture_evidence(s, probes=[play])
            assert before.video_present and not before.video_playing and before.probes[0].visible
            assert not await s._holds(VideoPlaying())
            await s.page.click("#play")
            await s.page.wait_for_timeout(300)
            assert await s._holds(VideoPlaying())
            after = await capture_evidence(s)
            assert after.video_playing and "Now Playing" in after.texts
            # and as a state guard through the polling loop
            latency = await s.wait_for_state(State(id="watching", conditions=[VideoPlaying()], timeout_ms=3000))
            assert latency >= 0

    asyncio.run(_main())
