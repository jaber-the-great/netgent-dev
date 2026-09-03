"""The executor's position gate: media_playing(min_position_s) holds only when the playhead is past
the floor — evaluated from the element's own currentTime, zero LLM. A "${param}" nobody resolved
never holds, so a mis-wired artifact cannot pass vacuously."""

import asyncio

from netgent.browser.dom.models import MediaState
from netgent.browser.triggers import TriggerEngine
from netgent.schema.triggers import MediaPlaying


def _engine(*media: MediaState) -> TriggerEngine:
    async def read() -> list[MediaState]:
        return list(media)

    return TriggerEngine(page=None, resolver=None, media=read)  # type: ignore[arg-type]


def _holds(engine: TriggerEngine, **kw) -> bool:
    return asyncio.run(engine.holds(MediaPlaying(**kw)))


def test_the_playhead_must_be_past_the_floor():
    at_42 = _engine(MediaState(tag="video", current=42, duration=273, ready_state=4))
    assert _holds(at_42)
    assert _holds(at_42, min_position_s=42)
    assert _holds(at_42, min_position_s="30s")  # the unit coercion a Repeat count gets
    assert not _holds(at_42, min_position_s=60)  # six presses were asked for, one was made
    assert not _holds(at_42, min_position_s="1m")
    assert _holds(at_42, min_duration_s=120, min_position_s=40)
    assert not _holds(at_42, min_duration_s=300, min_position_s=40)  # the ad gate still applies


def test_an_unresolved_reference_never_holds():
    at_500 = _engine(MediaState(tag="video", current=500, duration=600, ready_state=4))
    assert not _holds(at_500, min_position_s="${expected_media_position}")


def test_the_longest_element_past_the_floor_is_enough():
    ad = MediaState(tag="video", current=3, duration=15, ready_state=4)
    content = MediaState(tag="video", current=86, duration=273, ready_state=4)
    assert _holds(_engine(ad, content), min_duration_s=120, min_position_s=60)
    assert not _holds(_engine(ad), min_duration_s=120, min_position_s=60)
