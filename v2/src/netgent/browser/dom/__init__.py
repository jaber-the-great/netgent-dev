"""DOM layer: compile-time DOM observation.

- models.py — DomSnapshot & friends: interactive-element extraction (shadow DOM + iframe aware).
- observer.py — DomObserver: walks every frame and joins closed shadow roots by frame path.
- serializer.py — format_observation: renders a DomSnapshot as the numbered list the agent reads.
- closed_shadow.py — closed shadow roots read from OUTSIDE the page over CDP (R8).
- scripts/ — the injected JavaScript (walker, frame selector, frame content origin) as .js files.

The browser's environment configuration lives one level up in `browser/profile.py`.
"""

from netgent.browser.dom.models import BBox, DomElement, DomSnapshot, SelectorCandidate, TextBlock
from netgent.browser.dom.observer import DomObserver
from netgent.browser.dom.serializer import element_key, format_observation

__all__ = [
    "BBox",
    "DomElement",
    "DomObserver",
    "DomSnapshot",
    "SelectorCandidate",
    "TextBlock",
    "element_key",
    "format_observation",
]
