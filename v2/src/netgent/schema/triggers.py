"""Trigger predicates: the conditions a state carries (its guards/anchors).

A state is recognized when ALL of its triggers hold (conjunction). Each trigger is a
structured, serializable predicate — never a fixed sleep, never prose.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class UrlMatches(BaseModel):
    type: Literal["url_matches"] = "url_matches"
    pattern: str  # regex, matched with re.search against page.url


class TitleContains(BaseModel):
    type: Literal["title_contains"] = "title_contains"
    text: str


class SelectorVisible(BaseModel):
    """An element matching `selector` is visible.

    `frame_path` is the iframe chain to evaluate in (one CSS selector per hop, outermost
    first — the same chain a locator's `frame_locator` steps carry); empty = top frame.
    """

    type: Literal["selector_visible"] = "selector_visible"
    selector: str  # CSS selector
    frame_path: list[str] = Field(default_factory=list)


class SelectorHidden(BaseModel):
    """An element matching `selector` exists but is hidden.

    Holds only for a RESOLVED-and-hidden element: a selector that matches nothing does not
    satisfy it, so a typo'd or drifted selector can never recognize a state by accident.
    """

    type: Literal["selector_hidden"] = "selector_hidden"
    selector: str  # CSS selector
    frame_path: list[str] = Field(default_factory=list)


class DialogMatches(BaseModel):
    """A JavaScript dialog (alert/confirm/prompt) raised by the LAST transition's action
    matches `pattern`.

    Some pages confirm an action ONLY via a dialog — e.g. `alert('Form submitted
    successfully')` — which the browser layer auto-accepts and records
    (browser/dialogs.py). No DOM or URL change exists for the other triggers to anchor
    on, so the state after such a transition is recognized by the dialog itself. The
    pattern is matched with re.search against the recorded "<type>: <message>" entries
    raised since the last dispatched action, so an old dialog can never satisfy a later
    state.
    """

    type: Literal["dialog_matches"] = "dialog_matches"
    pattern: str  # regex, matched with re.search against "<type>: <message>"


class MediaPlaying(BaseModel):
    """A <video>/<audio> element in `frame_path` is in the given playback state.

    Evaluated from the media element's own properties (paused/ended/duration) — the one
    playback signal that cannot lie or freeze. `min_duration_s` is the ad gate: sites play
    ads in the same media element as the content, so "a video is playing" is true during an
    ad too — "a video at least this long is playing" is not (a 7-minute song vs a 90-second
    ad). A replay whose seeks/dwells are gated this way waits out or skips an ad instead of
    silently spending its watch time on it. Matches nothing → does not hold (same
    resolved-only discipline as SelectorHidden).
    """

    type: Literal["media_playing"] = "media_playing"
    playing: bool = True  # True: playing (not paused, not ended); False: paused
    min_duration_s: float | None = None  # only media at least this long counts (filters ads)
    frame_path: list[str] = Field(default_factory=list)


Trigger = Annotated[
    Union[UrlMatches, TitleContains, SelectorVisible, SelectorHidden, DialogMatches, MediaPlaying],
    Field(discriminator="type"),
]
