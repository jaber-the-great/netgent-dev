"""media_playing trigger + media_summary against a real page with a real <audio> element.

The media is a generated WAV data-URI (no network, no fixtures): ~2 s of silence, looped,
muted, autoplaying — enough for the element's paused/duration properties to be live.
"""

import asyncio
import base64
import struct

import pytest

from netgent.browser import BrowserSession
from netgent.schema.triggers import MediaPlaying
from netgent.schema.workflow import State


def _silent_wav_data_uri(seconds: float = 2.0, rate: int = 8000) -> str:
    n = int(seconds * rate)
    body = struct.pack("<%dh" % n, *([0] * n))
    header = (
        b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(body))
    )
    return "data:audio/wav;base64," + base64.b64encode(header + body).decode("ascii")


PAGE = f"""<!doctype html><html><body>
<audio id="a" src="{_silent_wav_data_uri()}" autoplay muted loop controls></audio>
</body></html>"""


def test_media_playing_trigger_and_summary():
    async def run():
        async with BrowserSession(headless=True) as s:
            await s.page.set_content(PAGE)
            # Autoplay may need a nudge in headless; play() via the element is deterministic.
            await s.page.evaluate("document.getElementById('a').play()")
            await asyncio.sleep(0.3)

            async def holds(**kw) -> bool:
                report = await s.condition_report(State(id="probe", conditions=[MediaPlaying(**kw)]))
                return report[0][1]

            assert await holds()  # something is playing
            assert await holds(min_duration_s=1.0)  # ...and it is at least 1 s long
            assert not await holds(min_duration_s=600.0)  # the ad gate: too short does not count
            assert not await holds(playing=False)  # nothing is paused

            summary = await s.media_summary()
            assert summary is not None and summary.startswith("audio PLAYING at 0:0") and "[muted]" in summary

            await s.page.evaluate("document.getElementById('a').pause()")
            assert await holds(playing=False)
            assert not await holds()
            assert "PAUSED" in (await s.media_summary())

            # a page with no media: the trigger does not hold (resolved-only), summary is None
            await s.page.set_content("<html><body><p>quiet</p></body></html>")
            assert not await holds()
            assert not await holds(playing=False)
            assert await s.media_summary() is None

    asyncio.run(run())


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
