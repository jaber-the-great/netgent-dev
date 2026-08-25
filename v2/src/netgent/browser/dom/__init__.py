"""DOM layer: compile-time DOM observation.

- snapshot.py — DomSnapshot: interactive-element extraction (shadow DOM + iframe aware).

The browser's environment configuration lives one level up in `browser/profile.py`.
"""

from netgent.browser.dom.snapshot import BBox, DomElement, DomSnapshot, SelectorCandidate

__all__ = [
    "BBox",
    "DomElement",
    "DomSnapshot",
    "SelectorCandidate",
]
