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
    type: Literal["selector_visible"] = "selector_visible"
    selector: str  # CSS selector


class SelectorHidden(BaseModel):
    type: Literal["selector_hidden"] = "selector_hidden"
    selector: str  # CSS selector


Trigger = Annotated[
    Union[UrlMatches, TitleContains, SelectorVisible, SelectorHidden],
    Field(discriminator="type"),
]
