"""DOM layer: compile-time DOM observation.

- models.py — DomSnapshot & friends: interactive-element extraction (shadow DOM + iframe aware).
- observer.py — DomObserver: walks every frame and joins closed shadow roots by frame path.
- serializer.py — format_observation: renders a DomSnapshot as the numbered list the agent reads.
- closed_shadow.py — closed shadow roots read from OUTSIDE the page over CDP (R8).
- media.py — every live media element, attached or not, enumerated over CDP and read in an
  isolated world (a `new Audio()` player is still the player; load state tells "nothing to
  play" from "paused").
- cdp.py — the CDP plumbing both share: sessions per target, frame tree, one isolated world per frame.
- scripts/ — the injected JavaScript (walker, frame selector, frame content origin, media reader) as .js files.

The browser's environment configuration lives one level up in `browser/profile.py`.
"""

from netgent.browser.dom.models import BBox, DomElement, DomSnapshot, SelectorCandidate, TextBlock
from netgent.browser.dom.observer import DomObserver
from netgent.browser.dom.serializer import element_key, element_lines, format_observation, media_line

__all__ = [
    "BBox",
    "DomElement",
    "DomObserver",
    "DomSnapshot",
    "SelectorCandidate",
    "TextBlock",
    "element_key",
    "element_lines",
    "media_line",
    "format_observation",
]
