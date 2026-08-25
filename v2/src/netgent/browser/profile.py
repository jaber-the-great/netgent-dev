"""BrowserProfile: the environment a session runs in — configured for FIDELITY to a real
Chrome, not for evasion.

Detection is handled one level down: Patchright patches the driver (no Runtime.enable /
Console.enable, hardened launch switches, closed-shadow piercing), and real Google Chrome
(channel="chrome") supplies its own UA, client hints, plugins and GPU strings. Measured with
zero JS injection: all-pass on bot.sannysoft.com, "Normal" on browserscan.net, no leak on
bot-detector.rebrowser.net, "not_detected" on fingerprint.com — headless and headed
(docs/research/stealth-after-patchright.md). Anything we inject can only subtract, so this
module injects nothing.

What remains is self-inflicted and measured:

- Headless Chrome stamps "HeadlessChrome/<ver>" into its UA. Playwright's context-level
  `user_agent` hides that on the page only — ServiceWorkers and SharedWorkers still report
  HeadlessChrome (CreepJS "33% headless"). The `--user-agent=` LAUNCH flag covers page and
  both worker types; its side effect (empty high-entropy client hints) is repaired by one
  CDP `Emulation.setUserAgentOverride` carrying the browser's own brands and the host's real
  architecture / platform version. Result: byte-identical to real headed Chrome on headers,
  page, ServiceWorker and SharedWorker.
- A fixed viewport headed forces screen == viewport, DPR 1 and no window chrome; real Chrome
  shows the display. Headed therefore runs `no_viewport` unless a viewport is asked for.
- A `locale` forces a single-entry `navigator.languages` and a q-value-free Accept-Language,
  which no real Chrome sends. The default leaves locale and timezone to the host.

Every field is an explicit dataset-variation axis, off by default.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

# Chrome's UA carries a reduced version (major.0.0.0) and a frozen OS string per platform.
_FROZEN_OS = {
    "darwin": "Macintosh; Intel Mac OS X 10_15_7",
    "win32": "Windows NT 10.0; Win64; x64",
}


@dataclass(frozen=True)
class BrowserProfile:
    """Launch + context configuration. Defaults = real Chrome, host environment, nothing spoofed."""

    channel: str | None = "chrome"  # real Google Chrome; None = bundled Chromium
    locale: str | None = None  # e.g. "en-US"; None = the host's (the only setting real Chrome matches)
    timezone_id: str | None = None  # e.g. "America/Los_Angeles"; None = the host's
    viewport: tuple[int, int] | None = None  # fixed (w, h) for deterministic geometry; None = natural
    storage_state: str | None = None  # path to a saved storage state (cookies + localStorage) to start warm

    @classmethod
    def default(cls) -> BrowserProfile:
        return cls()

    @classmethod
    def bare(cls) -> BrowserProfile:
        """Bundled Chromium, no channel — the unpatched-binary control arm for experiments."""
        return cls(channel=None)

    @staticmethod
    def headless_user_agent(browser_version: str) -> str:
        """Real Chrome's UA for this host/version, minus the 'HeadlessChrome' stamp."""
        major = browser_version.split(".")[0]
        os_part = _FROZEN_OS.get(sys.platform, "X11; Linux x86_64")
        return f"Mozilla/5.0 ({os_part}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"

    def launch_kwargs(self, headless: bool, user_agent: str | None = None) -> dict:
        """Kwargs for chromium.launch(). `user_agent` becomes the --user-agent flag (the only
        override that reaches workers). No other switches: Patchright's own list is already
        the hardened one (our old `--disable-blink-features=AutomationControlled` was a duplicate)."""
        kwargs: dict = {"headless": headless, "args": [f"--user-agent={user_agent}"] if user_agent else []}
        if self.channel:
            kwargs["channel"] = self.channel
        return kwargs

    def context_kwargs(self, headless: bool) -> dict:
        """Kwargs for browser.new_context(): only what was explicitly asked for."""
        kwargs: dict = {}
        if self.locale:
            kwargs["locale"] = self.locale
        if self.timezone_id:
            kwargs["timezone_id"] = self.timezone_id
        if self.viewport:
            kwargs["viewport"] = {"width": self.viewport[0], "height": self.viewport[1]}
        elif not headless:
            kwargs["no_viewport"] = True  # the real window and display geometry, DPR included
        if self.storage_state:
            kwargs["storage_state"] = self.storage_state
        return kwargs


def user_agent_metadata(browser_version: str, brands: list[dict], ua_platform: str) -> dict:
    """The `userAgentMetadata` for CDP Emulation.setUserAgentOverride, completing what the
    --user-agent flag empties. `brands` and `ua_platform` are read from the running browser
    (they stay correct under the flag); architecture / bitness / platformVersion come from the
    host, as Chrome itself derives them. platformVersion follows Chrome's reporting: the macOS
    version, the Linux kernel version, and Windows 10.0.0 / 15.0.0 (by build number)."""
    major = browser_version.split(".")[0]
    machine = platform.machine().lower()
    architecture = "arm" if machine in ("arm64", "aarch64") else "x86"
    if sys.platform == "darwin":
        platform_version = platform.mac_ver()[0]
    elif sys.platform == "win32":
        build = int((platform.version().split(".") + ["0", "0", "0"])[2] or 0)
        platform_version = "15.0.0" if build >= 22000 else "10.0.0"
    else:
        platform_version = platform.release().split("-")[0]
    full_version_list = [
        {"brand": b["brand"], "version": browser_version if b["version"] == major else f"{b['version']}.0.0.0"}
        for b in brands
    ]
    return {
        "brands": brands,
        "fullVersionList": full_version_list,
        "platform": ua_platform,
        "platformVersion": platform_version,
        "architecture": architecture,
        "model": "",
        "mobile": False,
        "bitness": "64",
        "wow64": False,
    }
