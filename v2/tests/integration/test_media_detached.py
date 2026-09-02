"""Media the DOM walker cannot see: a `new Audio()` never inserted into the page (SoundCloud's
player), a <video> with no source (Twitch when the stream never attaches), and a static
<audio> the page's script never touched (no JS wrapper — the heap query alone would miss it).

Also the footprint rule: the readings are taken in OUR isolated world, so a page-side getter
trap on the main world's HTMLMediaElement.prototype never fires.
"""

import asyncio
import base64
import struct

import pytest

from netgent.browser import BrowserSession
from netgent.browser.dom.serializer import media_line
from netgent.schema.triggers import MediaPlaying
from netgent.schema.workflow import State


def _silent_wav_data_uri(seconds: float = 3.0, rate: int = 8000) -> str:
    n = int(seconds * rate)
    body = struct.pack("<%dh" % n, *([0] * n))
    header = (
        b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(body))
    )
    return "data:audio/wav;base64," + base64.b64encode(header + body).decode("ascii")


WAV = _silent_wav_data_uri()

PAGE = f"""<!doctype html><html><head><title>Detached media</title></head><body>
<!-- Twitch's shape: a visible player element whose stream never attached -->
<video id="dead" width="320" height="180"></video>
<!-- a static element no script ever touches (no JS wrapper exists for it) -->
<audio id="static" src="{WAV}" controls></audio>
<button id="play" onclick="window.track.play()">Play</button>
<button id="pause" onclick="window.track.pause()">Pause</button>
<script>
  // SoundCloud's shape: the player is an Audio object held by script, never in the DOM.
  window.track = new Audio("{WAV}"); window.track.loop = true; window.track.muted = true;
  // A page-side trap: if anyone reads currentTime through the MAIN world's prototype, the
  // document gets stamped. Our reader must never trigger it.
  const desc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'currentTime');
  Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {{
    configurable: true,
    get() {{ document.documentElement.setAttribute('data-trapped', '1'); return desc.get.call(this); }},
    set(v) {{ desc.set.call(this, v); }},
  }});
</script>
</body></html>"""


def test_detached_audio_and_unloaded_video_are_observed(serve):
    srv = serve({"/": PAGE})

    async def holds(s, **kw) -> bool:
        report = await s.condition_report(State(id="probe", conditions=[MediaPlaying(**kw)]))
        return report[0][1]

    async def run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            snap = await s.snapshot()
            lines = [media_line(m) for m in snap.media]
            # before play: the dead video is visible → NOT LOADED; the static audio is visible
            # (controls) → PAUSED; the detached track has not started → not listed
            assert "video NOT LOADED (no source)" in lines, lines
            assert any(line.startswith("audio PAUSED at 0:00 / 0:03") for line in lines), lines
            assert not any("(detached)" in line for line in lines), lines
            assert not await holds(s)  # nothing playing; a source-less element is not "paused content"

            await s.page.click("#play")
            await asyncio.sleep(0.4)
            snap = await s.snapshot()
            by_tag = {(m.tag, m.attached): m for m in snap.media}
            track = by_tag[("audio", False)]
            assert not track.paused and track.duration == 3 and track.muted and track.ready_state == 4
            lines = [media_line(m) for m in snap.media]
            assert lines[0].startswith("audio (detached) PLAYING at 0:0") and lines[0].endswith("[muted]"), lines
            assert "video NOT LOADED (no source)" in lines
            # the replay-side reading (no DOM walk) sees the same
            summary = await s.media_summary()
            assert summary is not None and summary.startswith("audio (detached) PLAYING"), summary
            # the media_playing gate counts a detached player
            assert await holds(s)
            assert await holds(s, min_duration_s=2.0)
            assert not await holds(s, min_duration_s=600.0)

            await s.page.click("#pause")
            await asyncio.sleep(0.2)
            snap = await s.snapshot()
            track = next(m for m in snap.media if not m.attached)
            assert track.paused  # a started-and-paused detached player stays listed
            assert await holds(s, playing=False)
            assert not await holds(s)

            # none of those reads went through the main world's prototype
            assert await s.page.evaluate("document.documentElement.getAttribute('data-trapped')") is None
            # …and the page itself was not fingerprinted with a global or a patched native
            probe = await s.page.evaluate(
                "() => ({ globals: Object.getOwnPropertyNames(window).filter(k => k.startsWith('__')),"
                " qsa: Document.prototype.querySelectorAll.toString() })",
                isolated_context=False,
            )
            assert probe["globals"] == [] and "[native code]" in probe["qsa"]

    asyncio.run(run())


def test_detached_audio_inside_a_cross_site_iframe_carries_its_frame_path(serve):
    """An out-of-process iframe (a different site: `localhost` vs `127.0.0.1`) is its own CDP
    target, so its detached player is searched for and read like the top document's. (Detached
    players inside SAME-process child frames are deliberately not searched — each heap walk
    is a full GC of the whole isolate; dom/media.py.)"""
    child = f"""<!doctype html><html><body>
<button id="go" onclick="window.t = new Audio('{WAV}'); window.t.loop = true; window.t.muted = true;
  window.t.play()">go</button>
</body></html>"""
    child_srv = serve({"/child": child})
    child_url = f"http://localhost:{child_srv.port}/child"
    srv = serve({"/": f'<!doctype html><html><body><iframe name="player" src="{child_url}"></iframe></body></html>'})

    async def run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"))
            await s.page.wait_for_load_state("networkidle")
            await s.page.frame_locator('iframe[name="player"]').locator("#go").click()
            await asyncio.sleep(0.4)
            snap = await s.snapshot()
            (track,) = [m for m in snap.media if not m.attached]
            assert not track.paused and track.frame_path == ['iframe[name="player"]']
            # a frame-scoped gate finds it; a gate scoped to a frame that has no player does not
            report = await s.condition_report(State(id="p", conditions=[
                MediaPlaying(frame_path=['iframe[name="player"]']),
                MediaPlaying(frame_path=['iframe[name="other"]']),
                MediaPlaying(),  # any frame
            ]))
            assert [met for _, met in report] == [True, False, True]

    asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
