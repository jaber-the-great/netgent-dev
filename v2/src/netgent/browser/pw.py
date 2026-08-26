"""The single Playwright import chokepoint (docs/browser-layer-design.md §"Package structure").

Every other module under `browser/` imports Playwright names from here, so the
Patchright-or-Playwright decision is made exactly once and `PATCHED_BROWSER` is the one
capability flag the rest of the layer keys on.
"""

try:  # Patchright: a patched Playwright that closes the CDP-level leaks (Runtime.enable,
    # Console.enable, automation flags). Same API, so it is a drop-in when installed.
    from patchright.async_api import (
        Browser,
        BrowserContext,
        Frame,
        FrameLocator,
        Locator,
        Page,
        Playwright,
        async_playwright,
    )

    PATCHED_BROWSER = True
except ImportError:  # pragma: no cover — plain Playwright fallback
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Frame,
        FrameLocator,
        Locator,
        Page,
        Playwright,
        async_playwright,
    )

    PATCHED_BROWSER = False

__all__ = [
    "PATCHED_BROWSER",
    "Browser",
    "BrowserContext",
    "Frame",
    "FrameLocator",
    "Locator",
    "Page",
    "Playwright",
    "async_playwright",
]
