"""Playwright layer: session/context lifecycle, capture contract, element resolution,
trigger evaluation, and observation. The only package that imports playwright.

- pw.py — the single Playwright/Patchright import chokepoint (`PATCHED_BROWSER`).
- profile.py — `BrowserProfile`: real Chrome, nothing spoofed.
- factory.py — launch → context → page → CDP session (`BrowserHandle`); capture hooks in here.
- session.py — `BrowserSession`, the facade the executor and agents drive.
- resolution.py / actions.py / triggers.py — locator chains, action dispatch, state conditions.
- dialogs.py — alert/confirm/prompt auto-accepted and queued for the next observation.
- dom/ — observation: models, `DomObserver`, closed-shadow CDP reader, injected scripts.

Import rule: imports core. Never imports an LLM SDK — `netgent run` must work with no
model provider configured.
"""

from netgent.browser.dom.models import BBox, DomElement, DomSnapshot, SelectorCandidate, TextBlock
from netgent.browser.profile import BrowserProfile
from netgent.browser.pw import PATCHED_BROWSER
from netgent.browser.session import BrowserSession

__all__ = [
    "PATCHED_BROWSER",
    "BBox",
    "BrowserProfile",
    "BrowserSession",
    "DomElement",
    "DomSnapshot",
    "SelectorCandidate",
    "TextBlock",
]
