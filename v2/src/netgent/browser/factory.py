"""Browser construction: launch → context → page → CDP session, as one `BrowserHandle`.

Owns the launch-time details a session should not care about: the channel fallback, the
headless user-agent flag, and the client-hints repair. Capture (HAR/tracing) hooks in here at
context creation when the capture subsystem lands (docs/browser-layer-design.md §4).
"""

from dataclasses import dataclass
from typing import Any

from netgent.browser.profile import BrowserProfile, user_agent_metadata
from netgent.browser.pw import Browser, BrowserContext, Page, Playwright, async_playwright
from netgent.core.logger import get_logger

logger = get_logger(__name__)


# browser.version per channel, so the headless UA flag needs only one extra launch per process.
_VERSION_CACHE: dict[str | None, str] = {}


@dataclass
class BrowserHandle:
    """Everything `launch` built, in creation order; `close` tears it down in reverse."""

    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page
    cdp: Any | None  # CDP session: closed-shadow observation (Patchright) + headless client-hints repair


async def _browser_version(playwright: Playwright, profile: BrowserProfile) -> str:
    """The channel's real version, via a throwaway launch (memoized per process)."""
    channel = profile.channel
    if channel not in _VERSION_CACHE:
        kwargs = profile.launch_kwargs(headless=True)
        try:
            browser = await playwright.chromium.launch(**kwargs)
        except Exception:  # noqa: BLE001 — channel not installed: fall back to bundled Chromium
            if "channel" not in kwargs:
                raise
            kwargs.pop("channel")
            browser = await playwright.chromium.launch(**kwargs)
        _VERSION_CACHE[channel] = browser.version
        await browser.close()
    return _VERSION_CACHE[channel]


async def launch(profile: BrowserProfile, headless: bool) -> BrowserHandle:
    """Start Playwright, launch the profile's browser, open a context + page + CDP session."""
    playwright = await async_playwright().start()
    # Headless Chrome stamps "HeadlessChrome/<ver>" into its UA. Only the LAUNCH flag
    # reaches ServiceWorkers/SharedWorkers (the context option leaves them leaking); the
    # real version keeps the UA in step with the binary.
    user_agent = profile.headless_user_agent(await _browser_version(playwright, profile)) if headless else None
    launch_kwargs = profile.launch_kwargs(headless, user_agent)
    try:
        browser = await playwright.chromium.launch(**launch_kwargs)
    except Exception:  # noqa: BLE001 — e.g. channel="chrome" but Chrome isn't installed
        if "channel" not in launch_kwargs:
            raise
        launch_kwargs.pop("channel")
        browser = await playwright.chromium.launch(**launch_kwargs)
    context = await browser.new_context(**profile.context_kwargs(headless))
    page = await context.new_page()
    try:
        cdp = await context.new_cdp_session(page)
    except Exception as exc:  # noqa: BLE001 — everything below is best-effort
        logger.warning("CDP session unavailable: %s", exc)
        cdp = None
    handle = BrowserHandle(playwright=playwright, browser=browser, context=context, page=page, cdp=cdp)
    if user_agent and cdp is not None:
        await _repair_client_hints(handle, user_agent)
    return handle


async def _repair_client_hints(handle: BrowserHandle, user_agent: str) -> None:
    """The --user-agent flag empties the high-entropy client hints (architecture,
    platformVersion, fullVersionList) on the page. Re-issue the UA over CDP with a complete
    userAgentMetadata: the browser's own brands/platform (read from a routed https page —
    userAgentData needs a secure context) plus the host's real architecture and OS version.
    Measured byte-identical to real headed Chrome on headers, page and both worker types."""
    page = handle.page
    probe_url = "https://netgent.invalid/client-hints"
    try:
        await page.route(probe_url, lambda route: route.fulfill(status=200, body="", content_type="text/html"))
        await page.goto(probe_url)
        hints = await page.evaluate(
            "() => navigator.userAgentData ? {brands: navigator.userAgentData.brands, "
            "platform: navigator.userAgentData.platform} : null"
        )
        await page.unroute(probe_url)
        await page.goto("about:blank")
        if not hints:
            return
        metadata = user_agent_metadata(handle.browser.version, hints["brands"], hints["platform"])
        await handle.cdp.send(
            "Emulation.setUserAgentOverride", {"userAgent": user_agent, "userAgentMetadata": metadata}
        )
    except Exception as exc:  # noqa: BLE001 — a headless UA with empty hints beats a crash
        logger.warning("client-hints repair skipped: %s", exc)


async def close(handle: BrowserHandle) -> None:
    """Tear down in reverse creation order; never raises from the CDP detach."""
    if handle.cdp is not None:
        try:
            await handle.cdp.detach()
        except Exception:  # noqa: BLE001 — teardown must never raise
            pass
    if handle.context:
        await handle.context.close()
    if handle.browser:
        await handle.browser.close()
    if handle.playwright:
        await handle.playwright.stop()
