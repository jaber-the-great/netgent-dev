"""Trigger predicates: the conditions a state carries (its guards/anchors).

A state is recognized when ALL of its triggers hold (conjunction). Each trigger is a
structured, serializable predicate — never a fixed sleep, never prose.
"""

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from netgent.schema.actions import Locator
from netgent.schema.units import coerce_number

_PARAM_REF = re.compile(r"^\$\{\w+\}$")
# The settle budget of a state that asserts a media position: long enough for the element's
# properties to reflect the last action, far too short for normal playback to reach a floor
# the phases did not (a seek is ≥ 5 s per gesture; a dwell is ≥ 1 s per slice).
GOAL_GATE_MAX_TIMEOUT_MS = 2000


class UrlMatches(BaseModel):
    type: Literal["url_matches"] = "url_matches"
    pattern: str  # regex, matched with re.search against page.url


class TitleContains(BaseModel):
    type: Literal["title_contains"] = "title_contains"
    text: str


class _ElementTrigger(BaseModel):
    """A trigger about one element, named EITHER by a locator chain OR by a selector string.

    `locator` is the same whitelisted chain an action carries (`get_by_role`, `frame_locator`,
    `nth`, …), evaluated by the same resolver actions use — so a state anchored on the next
    edge's target holds exactly when that edge's element resolves. The compiler emits this
    form: a hand-rendered selector string cannot reproduce a chain's semantics (Playwright's
    public `role=` engine matches `[name="…" i]` EXACTLY, `get_by_role(name=…)` by SUBSTRING —
    an anchor built the first way from a name Playwright's own generator had shortened to a
    30-character prefix matched nothing on replay while the click it guarded matched one
    element; measured on archive.org, docs/research/media-platforms-eval.md).

    `selector` is a CSS/Playwright selector evaluated in `frame_path` (one CSS selector per
    iframe hop, outermost first; empty = top frame) — the hand-writable form.
    """

    selector: str | None = None
    frame_path: list[str] = Field(default_factory=list)
    locator: Locator | None = None

    @model_validator(mode="after")
    def _one_element_reference(self) -> "_ElementTrigger":
        if (self.selector is None) == (self.locator is None):
            raise ValueError(f"{self.type} needs exactly one of `selector` or `locator`")
        if self.locator is not None and self.frame_path:
            raise ValueError(f"{self.type}: `frame_path` goes with `selector`; a locator carries its own frame steps")
        return self


class SelectorVisible(_ElementTrigger):
    """The element (see `_ElementTrigger`) is visible."""

    type: Literal["selector_visible"] = "selector_visible"


class SelectorHidden(_ElementTrigger):
    """The element exists but is hidden.

    Holds only for a RESOLVED-and-hidden element: a reference that matches nothing does not
    satisfy it, so a typo'd or drifted selector can never recognize a state by accident.
    """

    type: Literal["selector_hidden"] = "selector_hidden"


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
    """A media element is in the given playback state.

    Evaluated from the media element's own properties (paused/ended/duration) — the one
    playback signal that cannot lie or freeze — over every live element, in the DOM or held
    by script only (a `new Audio()` player is the player). An element with nothing loaded
    (no source, readyState 0) is neither playing nor paused content. `min_duration_s` is the
    ad gate: sites play ads in the same media element as the content, so "a video is playing"
    is true during an ad too — "a video at least this long is playing" is not (a 7-minute song
    vs a 90-second ad). A replay whose seeks/dwells are gated this way waits out or skips an ad
    instead of silently spending its watch time on it. Matches nothing → does not hold (same
    resolved-only discipline as SelectorHidden). `frame_path` restricts the check to one
    iframe; empty = any frame (the compiler cannot tell which frame a player lives in from a
    step's reading, and a gate is about the page's playback).

    `min_position_s` is the goal gate: the media's playhead must be at least this far in. A
    replay that walked the right states but spent its dwells and seeks on nothing (or pressed
    once where the task said a minute) has the content at the wrong position, and only the
    position says so. A number, or ONE `${param}` reference resolved by `resolve_params` with
    the same unit coercion a Repeat count gets ('60s', '1m') — never arithmetic in the artifact.
    The materializer sets it on the accept state only where every kept recording's playhead
    on entering that state witnessed it. State recognition POLLS, and 1× playback satisfies any
    floor given time (measured: a one-press replay of a 60 s seek passed after 56 s of polling),
    so a state carrying it must be recognized within GOAL_GATE_MAX_TIMEOUT_MS — the Workflow
    validator refuses a longer `timeout_ms`, and no artifact can ship a pollable goal gate.
    """

    type: Literal["media_playing"] = "media_playing"
    playing: bool = True  # True: playing (not paused, not ended); False: paused
    min_duration_s: float | None = None  # only media at least this long counts (filters ads)
    min_position_s: float | str | None = None  # playhead ≥ this many seconds; a number or "${param}"
    frame_path: list[str] = Field(default_factory=list)

    @field_validator("min_position_s")
    @classmethod
    def _number_or_one_param_reference(cls, value: float | str | None) -> float | str | None:
        if value is None or isinstance(value, (int, float)):
            return value
        if _PARAM_REF.match(value) or coerce_number(value) is not None:
            return value
        raise ValueError(
            f"media_playing.min_position_s {value!r} must be a number (with an optional unit) or a single "
            "${param} reference — no expressions in the artifact; derive a param for a sum"
        )


Trigger = Annotated[
    Union[UrlMatches, TitleContains, SelectorVisible, SelectorHidden, DialogMatches, MediaPlaying],
    Field(discriminator="type"),
]
