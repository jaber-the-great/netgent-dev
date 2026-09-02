"""DOM observation models: a page's interactive elements as a structured tree.

Compile-time observation only. These objects are NOT part of the workflow artifact —
they feed the (LLM) Discovery/Generator so it can choose elements and emit durable
locator chains. At run time nothing here is used; the executor drives resolved locators.

The walker (dom/scripts/snapshot.js, run by dom/observer.py) pierces shadow DOM and iframes
(the stress-tests corpus is built to break naive walkers: nested iframes, shadow-DOM forms,
contenteditable, web components).
Each element carries an ordered candidate-selector list (role/test-id/label/css) so the
Generator can store the most durable one first.
"""

from pydantic import BaseModel, Field


class SelectorCandidate(BaseModel):
    kind: str  # role | test_id | label | css
    role: str | None = None
    name: str | None = None
    value: str | None = None


class BBox(BaseModel):
    x: int
    y: int
    w: int
    h: int


class DomElement(BaseModel):
    tag: str
    role: str | None = None
    name: str = ""
    type: str | None = None
    checked: bool | None = None  # checkbox/radio state
    disabled: bool = False
    required: bool = False
    invalid: bool = False  # required-but-invalid: silently blocks native form submit
    options: list[str] | None = None  # <select> option values
    value: str | None = None
    format: str | None = None  # expected input format, e.g. YYYY-MM-DD (native) or MM/DD/YYYY (picker/attr)
    picker: str | None = None  # datepicker library / signal behind `format` (attr, bootstrap-datepicker, …)
    frame_path: list[str] = Field(default_factory=list, alias="framePath")
    # Captured from inside a CLOSED shadow root: only Patchright (CDP describeNode pierce) can
    # resolve it, so a plain-Playwright replay must refuse. Set by the walker when it descends
    # a root handed in over CDP (browser/dom/closed_shadow.py, R8).
    requires_closed_shadow: bool = Field(default=False, alias="requiresClosedShadow")
    bbox: BBox
    candidates: list[SelectorCandidate] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class TextBlock(BaseModel):
    text: str
    alert: bool = False  # role=alert/status — a confirmation/error message
    frame_path: list[str] = Field(default_factory=list)  # which frame the text is in


class MediaState(BaseModel):
    """A media element's playback and load state, read from its properties.

    The properties are ground truth: they keep ticking while a player's on-screen controls
    are auto-hidden and their labels/timers frozen (YouTube stops updating hidden controls —
    the accessibility strings lied to the agent; currentTime cannot).

    The element need not be in the DOM: a `new Audio()` a site never inserts (SoundCloud) is
    still the player, found over CDP (dom/media.py) and reported with `attached=False`. Load
    state tells "nothing to play" from "paused": `ready_state` is HTMLMediaElement.readyState
    (0 HAVE_NOTHING … 4 HAVE_ENOUGH_DATA), `network_state` its networkState (0 EMPTY, 1 IDLE,
    2 LOADING, 3 NO_SOURCE), `has_source` whether any src/currentSrc/srcObject/<source> is set.
    None/defaults on records taken before these were observed."""

    tag: str  # video | audio
    current: int  # currentTime, whole seconds
    duration: int | None = None  # None while unknown (streaming/not loaded)
    paused: bool = False
    ended: bool = False
    muted: bool = False
    attached: bool = True  # in the DOM; False = held by script only (still the live player)
    ready_state: int | None = None
    network_state: int | None = None
    has_source: bool = True
    frame_path: list[str] = Field(default_factory=list)

    @property
    def loaded(self) -> bool:
        """Has media to play (metadata or more); False for a source-less/failed element."""
        return self.ready_state is None or self.ready_state > 0

    @property
    def playing(self) -> bool:
        return not self.paused and not self.ended and self.loaded


class DomSnapshot(BaseModel):
    url: str
    title: str
    elements: list[DomElement] = Field(default_factory=list)
    texts: list[TextBlock] = Field(default_factory=list)
    media: list[MediaState] = Field(default_factory=list)  # playing/paused <video>/<audio>
    # Wall-clock (epoch seconds) when this snapshot was taken. Pairs with `media`: the only
    # way to tell a seek jump from natural playback is position delta vs wall-clock delta.
    taken_at: float = 0.0
    viewport_height: int = 0  # top-frame innerHeight; 0 = unknown (show everything)
    # Frames whose walk failed (detached mid-snapshot, unreachable): their elements are
    # missing from this observation. Counted and named so the agent and the trajectory can
    # see the observation shrank, instead of it silently looking complete (browser-use #4778).
    frames_skipped: int = 0
    skipped_frames: list[str] = Field(default_factory=list)  # "<url>: <error>" per skipped frame
    # JavaScript dialogs (alert/confirm/prompt) the page raised since the previous snapshot,
    # auto-accepted and recorded as "<type>: <message>" (browser/dialogs.py). Often the only
    # success/error feedback a plain form gives — invisible in the DOM.
    dialogs: list[str] = Field(default_factory=list)

    def interactive(self) -> list[DomElement]:
        return self.elements

    def scoped_to(self, frame_path: list[str]) -> "DomSnapshot":
        """A copy restricted to one frame — its elements + texts only. Used to focus the
        agent on a single form (iframe) so a sweep can complete forms one at a time.

        viewport_height is zeroed so the observation is NOT paged: a single bounded form
        should be shown whole, otherwise fields page out of view and the agent scroll-
        thrashes looking for inputs it already filled."""
        return DomSnapshot(
            url=self.url,
            title=self.title,
            elements=[e for e in self.elements if e.frame_path == frame_path],
            texts=[t for t in self.texts if t.frame_path == frame_path],
            media=[m for m in self.media if m.frame_path == frame_path],
            taken_at=self.taken_at,
            viewport_height=0,
            frames_skipped=self.frames_skipped,
            skipped_frames=self.skipped_frames,
            dialogs=self.dialogs,  # page-modal: belongs to whichever form is being worked
        )
