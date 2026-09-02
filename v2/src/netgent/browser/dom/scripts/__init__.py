"""The injected JavaScript, shipped as real `.js` files next to this module.

- snapshot.js — the DOM walker (`DOM_SNAPSHOT_JS`); runs in an isolated world per frame.
- frame_selector.js — CSS selector for a frame-owner element (`FRAME_SELECTOR_JS`).
- frame_content_origin.js — an iframe's content-box origin in its parent (`FRAME_CONTENT_ORIGIN_JS`).
- media_reader.js — playback readings for media elements handed in + the frame's attached ones
  (`MEDIA_READER_JS`; `MEDIA_DOM_JS` is its no-argument form: attached elements only).

Each file is a bare function expression preceded by `//` comment lines. `load` strips those
leading comment lines so the string handed to Playwright (`frame.evaluate(src)`, which must
see a function expression) and to CDP (`Runtime.callFunctionOn(functionDeclaration=src)`) is
the bare function, exactly as when these lived as Python string constants.
"""

from functools import cache
from importlib import resources


@cache
def load(name: str) -> str:
    """The function expression in `scripts/<name>`, leading `//` comment / blank lines removed."""
    text = resources.files(__package__).joinpath(name).read_text(encoding="utf-8")
    lines = text.splitlines()
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("//")):
        start += 1
    return "\n".join(lines[start:]).rstrip() + "\n"


DOM_SNAPSHOT_JS = load("snapshot.js")
FRAME_SELECTOR_JS = load("frame_selector.js")
FRAME_CONTENT_ORIGIN_JS = load("frame_content_origin.js")
MEDIA_READER_JS = load("media_reader.js")
# The reader with no handles: the frame's DOM-attached media only — what `frame.evaluate`
# can reach without CDP (the fallback when the heap enumeration is unavailable).
MEDIA_DOM_JS = f"() => ({MEDIA_READER_JS.strip()})()"

__all__ = [
    "DOM_SNAPSHOT_JS",
    "FRAME_CONTENT_ORIGIN_JS",
    "FRAME_SELECTOR_JS",
    "MEDIA_DOM_JS",
    "MEDIA_READER_JS",
    "load",
]
