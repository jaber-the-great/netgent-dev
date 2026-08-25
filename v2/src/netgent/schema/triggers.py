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


Trigger = Annotated[
    Union[UrlMatches, TitleContains, SelectorVisible, SelectorHidden],
    Field(discriminator="type"),
]
