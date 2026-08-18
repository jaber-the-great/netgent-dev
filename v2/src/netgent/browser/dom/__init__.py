"""DOM layer: stealth hardening + compile-time DOM observation.

- stealth.py  — StealthProfile: launch args, init script, context options for a
  realistic (non-trivially-detectable) Chromium. No CAPTCHA handling.
- snapshot.py — DomSnapshot: interactive-element extraction (shadow DOM + iframe aware).
"""

from netgent.browser.dom.snapshot import BBox, DomElement, DomSnapshot, SelectorCandidate
from netgent.browser.dom.stealth import DEFAULT_USER_AGENT, StealthProfile

__all__ = [
    "DEFAULT_USER_AGENT",
    "BBox",
    "DomElement",
    "DomSnapshot",
    "SelectorCandidate",
    "StealthProfile",
]
