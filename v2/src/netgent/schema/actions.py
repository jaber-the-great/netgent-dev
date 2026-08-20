"""The action IR: one atomic action per transition, from a closed parameterized set.

Locators are stored as structured chains and replayed by whitelist reflection —
never generated code, never `exec` (docs/browser-layer-design.md §1).
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

DEFAULT_TIMEOUT_MS = 5000

# Playwright Locator/Page methods a stored chain may call. This whitelist is the
# security boundary for replay.
ALLOWED_LOCATOR_FNS = frozenset(
    {
        "get_by_role",
        "get_by_text",
        "get_by_label",
        "get_by_placeholder",
        "get_by_test_id",
        "get_by_title",
        "get_by_alt_text",
        "locator",
        "frame_locator",
        "filter",
        "nth",
    }
)


class LocatorStep(BaseModel):
    """One call in a locator chain, e.g. {fn: get_by_role, args: [button], kwargs: {name: Submit}}."""

    fn: str
    args: list[str | int | float | bool] = Field(default_factory=list)
    kwargs: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("fn")
    @classmethod
    def _fn_in_whitelist(cls, value: str) -> str:
        if value not in ALLOWED_LOCATOR_FNS:
            raise ValueError(f"locator fn {value!r} is not in the replay whitelist {sorted(ALLOWED_LOCATOR_FNS)}")
        return value


Locator = list[LocatorStep]


class _ActionBase(BaseModel):
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    @field_validator("timeout_ms")
    @classmethod
    def _zero_means_default(cls, value: int) -> int:
        # Playwright treats timeout=0 as infinite — a footgun for a determinism engine.
        return DEFAULT_TIMEOUT_MS if value == 0 else value


class GotoAction(_ActionBase):
    type: Literal["goto"] = "goto"
    url: str


class ClickAction(_ActionBase):
    type: Literal["click"] = "click"
    locator: Locator


class FillAction(_ActionBase):
    type: Literal["fill"] = "fill"
    locator: Locator
    text: str


class PressAction(_ActionBase):
    """Press a key combination, on an element if a locator is given, else on the page."""

    type: Literal["press"] = "press"
    keys: str
    locator: Locator | None = None


class SelectAction(_ActionBase):
    type: Literal["select"] = "select"
    locator: Locator
    value: str


class ScrollAction(_ActionBase):
    """Scroll by viewport pages (browser-use's model): the LLM picks a direction and a
    fraction of a viewport, converted to pixels at dispatch. pages=10 ≈ to the end.
    """

    type: Literal["scroll"] = "scroll"
    down: bool = True
    pages: float = 1.0


class UploadFileAction(_ActionBase):
    """Set the file(s) on a file input (Playwright .set_input_files)."""

    type: Literal["upload_file"] = "upload_file"
    locator: Locator
    paths: list[str]


class GoBackAction(_ActionBase):
    """Navigate back in browser history."""

    type: Literal["go_back"] = "go_back"


class WaitAction(_ActionBase):
    """Dwell on the page — e.g. watch a video / let a stream play. Core to NetGent's
    purpose: the dwell is when the interesting network traffic happens."""

    type: Literal["wait"] = "wait"
    seconds: float = Field(gt=0, le=3600)


class HoverAction(_ActionBase):
    """Hover over an element (opens menus, fires prefetch)."""

    type: Literal["hover"] = "hover"
    locator: Locator


class NoopAction(_ActionBase):
    """The ε-transition action: changes nothing; the edge exists to move between states."""

    type: Literal["noop"] = "noop"


Action = Annotated[
    Union[
        GotoAction,
        ClickAction,
        FillAction,
        PressAction,
        SelectAction,
        ScrollAction,
        UploadFileAction,
        GoBackAction,
        WaitAction,
        HoverAction,
        NoopAction,
    ],
    Field(discriminator="type"),
]
