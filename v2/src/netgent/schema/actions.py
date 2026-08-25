"""The action IR: one atomic action per transition, from a closed parameterized set.

Locators are stored as structured chains and replayed by whitelist reflection —
never generated code, never `exec` (docs/browser-layer-design.md §1).
"""

from typing import Annotated, Literal, Union

from pydantic import AfterValidator, BaseModel, Field, field_validator

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


# What each receiver in a chain can be asked next. A chain starts on the Page; get_by_*/
# locator move to a Locator; frame_locator moves to a FrameLocator, which has no `filter`
# and — having no fill/click — is never a legal END of a chain (measured:
# hasattr(FrameLocator, "filter") == hasattr(FrameLocator, "fill") == False).
_QUERY_FNS = frozenset(ALLOWED_LOCATOR_FNS - {"frame_locator", "filter", "nth"})
_NEXT: dict[str, dict[str, str]] = {
    "page": {**{fn: "locator" for fn in _QUERY_FNS}, "frame_locator": "frame"},
    "locator": {
        **{fn: "locator" for fn in _QUERY_FNS},
        "frame_locator": "frame",
        "filter": "locator",
        "nth": "locator",
    },
    "frame": {**{fn: "locator" for fn in _QUERY_FNS}, "frame_locator": "frame", "nth": "frame"},
}


def validate_locator_chain(chain: list[LocatorStep]) -> list[LocatorStep]:
    """Reject chains that can never resolve to an actionable Locator, at load time.

    Type-checks the receiver sequence (Page → Locator | FrameLocator → …): `filter`/`nth`
    cannot open a chain, `filter` cannot follow `frame_locator`, and a chain cannot end on a
    FrameLocator. Without this a schema-legal chain surfaced as an AttributeError at replay.
    """
    if not chain:
        raise ValueError("locator chain is empty")
    receiver = "page"
    for i, step in enumerate(chain):
        nxt = _NEXT[receiver].get(step.fn)
        if nxt is None:
            raise ValueError(
                f"step {i} ({step.fn!r}) cannot follow a {receiver!r} receiver — "
                f"allowed here: {sorted(_NEXT[receiver])}"
            )
        receiver = nxt
    if receiver != "locator":
        raise ValueError(
            "locator chain ends on a frame_locator (a FrameLocator has no fill/click) — add the element step"
        )
    return chain


Locator = Annotated[list[LocatorStep], AfterValidator(validate_locator_chain)]


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
