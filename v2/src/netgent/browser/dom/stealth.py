"""Stealth hardening for a realistic (non-trivially-detectable) Chromium.

Purpose is traffic realism, not deception of a specific target: a browser that trips
`navigator.webdriver`-style automation flags produces unrepresentative traffic, which
defeats NetGent's dataset goal. These are the standard, publicly-documented evasions
that plain Playwright supports with no patched binary — launch args, an init script,
and context options. CAPTCHA solving is explicitly out of scope.

The residual signals that need a patched binary (CDP Runtime.enable execution-context
leak, some WebGL entropy) are documented in docs/research/stealth-browser.md and are the
honest ceiling of this approach.
"""

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

    user_agent: str = DEFAULT_USER_AGENT
    locale: str = "en-US"
    timezone_id: str = "America/Los_Angeles"
    viewport_width: int = 1280
    viewport_height: int = 800
    launch_args: list[str] = field(default_factory=lambda: list(STEALTH_LAUNCH_ARGS))
    init_script: str = STEALTH_INIT_SCRIPT

    def launch_kwargs(self, headless: bool) -> dict:
        """Kwargs for chromium.launch(). channel='chrome' uses real Chrome when present."""
        return {"headless": headless, "args": self.launch_args}

    def context_kwargs(self) -> dict:
        """Kwargs for browser.new_context() — consistent UA/locale/tz/viewport/headers."""
        return {
            "user_agent": self.user_agent,
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "viewport": {"width": self.viewport_width, "height": self.viewport_height},
            "extra_http_headers": {
                "Accept-Language": f"{self.locale},en;q=0.9",
                "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
            },
        }
