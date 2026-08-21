"""Stealth hardening for a realistic (non-trivially-detectable) browser.

Purpose is traffic realism, not deception of a specific target: a browser that trips
`navigator.webdriver`-style automation flags produces unrepresentative traffic, which
defeats NetGent's dataset goal. CAPTCHA solving is explicitly out of scope.

Two profiles:
- `StealthProfile.native()` — used when the PATCHED binary (Patchright) is installed, which
  closes the CDP-level leaks (Runtime.enable, Console.enable, automation flags) that no
  JS can hide. It spoofs NOTHING: real Google Chrome (channel="chrome"), its own UA and
  headers, no init script. Only headless mode gets one override — Chrome's own
  "HeadlessChrome" UA stamp, rewritten with the REAL version so nothing drifts.
  Measured: 31/31 on bot.sannysoft.com, headless and headed.
- `StealthProfile()` — the plain-Playwright fallback: launch args + an init script patching
  the cheap JS-visible tells. Its spoofs are themselves detectable (fake PluginArray, pinned
  UA/sec-ch-ua that drift from the binary); see docs/research/stealth-browser.md.
"""

import sys
from dataclasses import dataclass, field

# A recent, real desktop Chrome UA. Keep the major version aligned with the launched
# Chromium; a stale UA is itself a detection signal.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Launch args that remove the most common automation tells.
STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",  # drops navigator.webdriver + the tell
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

# Injected before any page script runs. Patches the cheap JS-visible tells.
STEALTH_INIT_SCRIPT = """
(() => {
  // navigator.webdriver — the single loudest signal
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  // plugins / mimeTypes — headless reports empty
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(i => ({ name: `Plugin ${i}`, filename: `plugin${i}.dll` })),
  });

  // languages — headless can report []
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

  // chrome runtime object present in real Chrome, absent in headless
  window.chrome = window.chrome || { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };

  // permissions.query — headless returns 'denied' for notifications inconsistently
  const origQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (origQuery) {
    window.navigator.permissions.query = (params) =>
      params && params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : origQuery(params);
  }

  // WebGL vendor/renderer — headless swiftshader gives it away
  const getParam = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (p) {
    if (p === 37445) return 'Intel Inc.';            // UNMASKED_VENDOR_WEBGL
    if (p === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
    return getParam.call(this, p);
  };
})();
"""


@dataclass(frozen=True)
class StealthProfile:
    """Everything needed to launch and configure a hardened Chromium context."""

    user_agent: str | None = DEFAULT_USER_AGENT  # None = the browser's own (native) UA
    locale: str = "en-US"
    timezone_id: str = "America/Los_Angeles"
    viewport_width: int = 1280
    viewport_height: int = 800
    launch_args: list[str] = field(default_factory=lambda: list(STEALTH_LAUNCH_ARGS))
    init_script: str = STEALTH_INIT_SCRIPT  # "" = inject nothing
    channel: str | None = None  # "chrome" = real Google Chrome instead of bundled Chromium

    @classmethod
    def native(cls) -> "StealthProfile":
        """Profile for a PATCHED binary (Patchright): spoof nothing.

        JS-level spoofs (fake plugins, WebGL strings, a pinned UA + sec-ch-ua) are
        themselves detectable and drift out of sync with the real browser version. With
        the CDP leaks patched at the binary level, the most realistic fingerprint is real
        Chrome's own, untouched. Falls back to bundled Chromium if Chrome isn't installed.
        """
        return cls(user_agent=None, init_script="", channel="chrome", launch_args=[])

    @staticmethod
    def headless_user_agent(browser_version: str) -> str:
        """Real Chrome's UA for this host/version, minus the 'HeadlessChrome' stamp.
        Chrome's UA carries a reduced version (major.0.0.0) and a frozen OS string."""
        major = browser_version.split(".")[0]
        os_part = {
            "darwin": "Macintosh; Intel Mac OS X 10_15_7",
            "win32": "Windows NT 10.0; Win64; x64",
        }.get(sys.platform, "X11; Linux x86_64")
        return f"Mozilla/5.0 ({os_part}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"

    def launch_kwargs(self, headless: bool) -> dict:
        """Kwargs for chromium.launch(). channel='chrome' uses real Chrome when present."""
        kwargs: dict = {"headless": headless, "args": self.launch_args}
        if self.channel:
            kwargs["channel"] = self.channel
        return kwargs

    def context_kwargs(self) -> dict:
        """Kwargs for browser.new_context() — consistent locale/tz/viewport (+ UA/headers
        only for the unpatched profile; the native profile keeps the browser's own)."""
        kwargs: dict = {
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
        }
        if self.user_agent:
            kwargs["user_agent"] = self.user_agent
            kwargs["extra_http_headers"] = {
                "Accept-Language": f"{self.locale},en;q=0.9",
                "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            }
        return kwargs
