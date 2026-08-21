"""Trigger predicates: the conditions a state carries (its guards/anchors).

A state is recognized when ALL of its triggers hold (conjunction). Each trigger is a
structured, serializable predicate — never a fixed sleep, never prose, never code.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from netgent.schema.actions import Locator


class UrlMatches(BaseModel):
    type: Literal["url_matches"] = "url_matches"
    pattern: str  # regex, matched with re.search against page.url


class TitleContains(BaseModel):
    type: Literal["title_contains"] = "title_contains"
    text: str


class SelectorVisible(BaseModel):
    type: Literal["selector_visible"] = "selector_visible"
    selector: str  # CSS selector


class SelectorHidden(BaseModel):
    type: Literal["selector_hidden"] = "selector_hidden"
    selector: str  # CSS selector


class ElementVisible(BaseModel):
    """An element addressed by a durable locator chain (the same chains actions use —
    role+name, label, test-id …) is visible. Discovery emits this for the element the
    next edge acts on: the page is "ready" when its target can be seen."""

    type: Literal["element_visible"] = "element_visible"
    locator: Locator


class TextVisible(BaseModel):
    """Some visible element contains this text (substring, case-insensitive)."""

    type: Literal["text_visible"] = "text_visible"
    text: str


class VideoPlaying(BaseModel):
    """A <video> is present and its currentTime advances between two polls — a watch
    page is only "watching" when the player actually runs, not when the URL says so."""

    type: Literal["video_playing"] = "video_playing"
    selector: str = "video"  # CSS selector of the video element
    sample_ms: int = Field(default=300, gt=0)  # gap between the two currentTime samples


Trigger = Annotated[
    Union[UrlMatches, TitleContains, SelectorVisible, SelectorHidden, ElementVisible, TextVisible, VideoPlaying],
    Field(discriminator="type"),
]
