# Stealth Playwright (Chromium) — Implementation Guide for `browser/dom/`

**Scope & intent.** NetGent V2 drives Playwright/Chromium to generate *realistic* network-traffic
datasets. "Realistic" here means the automated browser should not trip **trivial, JS-observable
bot/automation fingerprinting** that would make its traffic unrepresentative of a real user's
session. This is a defensive/research goal: we want the *network behavior* (TLS, HTTP/2, timing,
resource waterfalls, cookies) to look like an ordinary Chrome, not to defeat any specific vendor.

**Out of scope (explicitly).** No CAPTCHA solving of any kind. No adversarial evasion of a *named*
anti-bot service as an end in itself. We harden the fingerprint surface and pace actions like a
human; we document the honest ceiling of what plain Python Playwright can and cannot do.

This guide is source-derived. It reads the actual mechanisms in `rebrowser-patches`, `patchright`,
`puppeteer-extra-plugin-stealth`, `nodriver`, and `undetected-chromedriver`, and marks for each
evasion whether it is reproducible in **plain Python Playwright** (launch args + `add_init_script` +
context options, no forked binary) or requires a patched driver.

---

## 0. TL;DR / what to build

Build `browser/dom/stealth.py` exposing three things the session layer composes:

1. `STEALTH_LAUNCH_ARGS` + `IGNORE_DEFAULT_ARGS` — the Chromium flag set (§4.1).
2. `stealth_context_kwargs(...)` — the `new_context(...)` options: UA, locale, timezone, viewport,
   `Accept-Language`, permissions (§4.3).
3. `INIT_SCRIPT` — one JS bundle registered via `context.add_init_script(...)` that patches the
   JS-surface leaks with native-looking descriptors (§4.4).

Then a **human-timing** layer (§7) that jitters dwell/inter-action delays, because NetGent already
owns action pacing and this is the single cheapest realism win.

**The one thing you cannot fix in plain Playwright:** the CDP `Runtime.enable`
execution-context leak (§5). Everything else in the "high impact" tier below is achievable
natively. If a target turns out to actually probe the `Runtime.enable` side channel, the escape
hatch is to swap the driver for **`rebrowser-playwright`** or **`patchright`** (drop-in Python
packages, §6) — no code changes to our layer beyond the import.

---

## 1. The detection surface — concrete signals

Sites flag automation by reading JS properties and by comparing headers/JS/IP for internal
consistency. The signals below are the ones actually checked by the common test suites
(`bot.sannysoft.com`, CreepJS, fpscanner, browser-use/stress-tests) and by the evasion tools'
own detectors. For each: what's read, the **bot tell**, and the fix tier.

| # | Signal | What's read (JS / header) | Bot tell | Human value | Fix tier |
|---|--------|---------------------------|----------|-------------|----------|
| 1 | **navigator.webdriver** | `navigator.webdriver` | `true` under `--enable-automation` | `false` | **A** flag |
| 2 | **Headless UA** | `navigator.userAgent` / `appVersion` | contains `HeadlessChrome` | `Chrome/…` | **A** ctx/CDP |
| 3 | **window.chrome / chrome.runtime** | `window.chrome`, `.runtime`, `.app`, `.csi`, `.loadTimes` | `undefined` in old headless | populated | **B** init |
| 4 | **permissions vs Notification** | `Notification.permission` vs `permissions.query({name:'notifications'})` | `denied` while query says `prompt` (contradiction) | consistent | **B** init |
| 5 | **plugins / mimeTypes empty** | `navigator.plugins.length`, `navigator.mimeTypes.length` | `0` (classic headless) | ≥1 (PDF viewer) | **B** init |
| 6 | **WebGL vendor/renderer** | `getParameter(37445/37446)` via `WEBGL_debug_renderer_info` | `Google Inc.` / `SwiftShader` (software) | real GPU (`ANGLE (Intel…)`) | **B** init / **A** flag |
| 7 | **Canvas fingerprint** | `toDataURL()` / `getImageData()` hash | deterministic, software-render artifacts | per-device noise | **C** init |
| 8 | **Audio fingerprint** | `OfflineAudioContext` `getChannelData()` hash | deterministic | per-device noise | **C** init |
| 9 | **CDP Runtime.enable leak** | `Error.stack`/`console.debug` getter fires when inspector serializes | detectable that Runtime domain is enabled | never fires | **D** driver-only |
| 10 | **outerWidth/Height, screen** | `window.outerWidth/Height`, `screen.*` vs `innerWidth` | `0` in headless; inner==screen exactly | outer ≥ inner + chrome UI | **B** flag/init |
| 11 | **Accept-Language / sec-ch-ua** | HTTP `Accept-Language`, `Sec-CH-UA*` vs JS `navigator.languages`/`userAgentData` | missing/empty AL; header UA ≠ JS UA | all consistent | **A** ctx |
| 12 | **Timezone / locale vs IP** | `Intl.DateTimeFormat().resolvedOptions().timeZone`, `getTimezoneOffset()` vs geo-IP | UTC / host TZ ≠ IP region | matches exit IP | **A** ctx (+proxy) |
| 13 | **iframe contentWindow / srcdoc** | injected globals leaking into child frames; `about:srcdoc`; OOPIF gaps | webdriver/patched props present in frames | clean frames | **B** init (all-frames) |
| 14 | **navigator.hardwareConcurrency / deviceMemory** | those props | odd/low values | plausible (4/8, 8) | **C** init |
| 15 | **navigator.languages / vendor / platform** | those props | empty / mismatched | populated, consistent | **B** init/ctx |
| 16 | **Function.toString integrity** | `patchedFn.toString()` | shows JS/proxy source instead of `[native code]` | `[native code]` | **B** init (meta) |
| 17 | **media codecs** | `HTMLMediaElement.canPlayType('video/mp4; codecs="avc1…"')` | `''` (Chromium lacks proprietary codecs) | `probably` | **C** init |
| 18 | **cdc_ / $cdc_ props** | `window` keys `/^[a-z]{27}(Array\|Promise\|Symbol)$/i`, `document.$cdc_…` | present (Selenium/chromedriver only) | absent | **N/A** — Playwright never injects these |
| 19 | **Automation infobar** | affects window metrics / visible chrome | "controlled by automated test software" bar | absent | **A** flag |
| 20 | **Honeypot / hidden fields** | server checks if `display:none`/offscreen input got filled | bot fills invisible field | left empty | **behavior** (§7) |

**Tier legend.** **A** = trivial + high impact (do first). **B** = init-script/config, medium cost,
real impact. **C** = fingerprint noise/spoof, higher cost, only matters against fingerprint-diffing
sites. **D** = cannot be fixed without a patched driver.

**Note on #18:** the `cdc_`/`$cdc_` document properties are a **Selenium/chromedriver** leak
(chromedriver injects a JS bootstrap declaring globals named `cdc_asdjfla…Array/Promise/Symbol` and
sets `document.$cdc_…`). Playwright does **not** use chromedriver and does not inject these — so this
entire class is a non-issue for us. It's listed only so reviewers know why it's absent from our
init script. (`undetected-chromedriver` neutralizes it by binary-patching the chromedriver
executable: `re.search(rb"\{window\.cdc.*?;\}", content)` replaced with a same-length
space-padded `console.log(...)`.)

---

## 2. Prioritized checklist (impact vs cost)

Ranked by **detection-impact ÷ implementation-cost**. Do them top-down; stop when the target's
test suite passes.

### Tier A — do first (cheap, high impact, all native)
1. **Launch flag `--disable-blink-features=AutomationControlled`** → makes `navigator.webdriver`
   report `false`. Single flag, kills signal #1. *(Modern Playwright already sets webdriver=false,
   but this flag is the belt-and-suspenders and also suppresses other Blink automation behaviors.)*
2. **`ignore_default_args=["--enable-automation"]`** → removes the infobar (#19) and the switch
   that historically forces webdriver true.
3. **`channel="chrome"`** (use installed Google Chrome, not bundled Chromium) → real branded UA,
   real proprietary media codecs (#17), populated `window.chrome`/plugins, real UA-CH brands.
   Biggest single realism win for the least code. Fall back to bundled Chromium only if Chrome
   isn't installed.
4. **Headed, or `--headless=new`** (never old headless) → fixes UA `HeadlessChrome` (#2),
   populates plugins/`window.chrome`, non-zero `outer*` (#10). For NetGent traffic realism prefer
   **headed under a virtual display (Xvfb)** on the capture host; use `--headless=new` only where a
   display is unavailable.
5. **Context UA + `locale` + `timezone_id`** aligned to the exit IP (#2, #11, #12). If using a
   proxy, set these to match the proxy's geolocation.
6. **`extra_http_headers={"Accept-Language": ...}`** consistent with `navigator.languages` (#11).

### Tier B — init-script bundle (medium cost, real impact, all native)
7. **`navigator.webdriver` delete** on the prototype (defense in depth with #1).
8. **`window.chrome` stub** (`app`/`csi`/`loadTimes`/`runtime`) if not using `channel="chrome"` (#3).
9. **`permissions.query` ↔ `Notification.permission` consistency** shim (#4).
10. **plugins/mimeTypes** spoof if empty (#5) — only needed on bundled Chromium/headless.
11. **WebGL vendor/renderer** override to a plausible real GPU when SwiftShader is in use (#6).
12. **`Function.prototype.toString` spoofing** so every patched getter/method reports
    `[native code]` (#16) — *this is the meta-evasion that makes 7–11 undetectable; without it the
    patches are trivially caught.*
13. **hardwareConcurrency / deviceMemory / languages / vendor / platform** getters (#14, #15).
14. Ensure the init script runs in **every frame** (`add_init_script` on the context does this) (#13).

### Tier C — fingerprint noise (higher cost, only vs fingerprint-diffing)
15. **Canvas** per-session noise (#7).
16. **Audio** per-session noise (#8).
17. **media.codecs** `canPlayType` spoof (#17) — free if you use `channel="chrome"`.

### Tier D — cannot fix natively (document the ceiling)
18. **CDP `Runtime.enable` execution-context leak** (#9) → requires `rebrowser-playwright` or
    `patchright` (§5, §6).

### Behavior (orthogonal, high realism value)
19. **Human timing**: dwell/jitter between actions, realistic scroll, no honeypot fills (§7).

---

## 3. Why the two "hard" leaks can't be patched from Python (the ceiling)

Two categories are **driver-internal** and provably unreachable from `add_init_script` / launch
args, because they happen in the Node driver process *before* any page JS runs and are properties
of CDP itself, not JS you can redefine:

**(a) The `Runtime.enable` execution-context leak (#9).** To map a frame to a V8 execution-context
id for `page.evaluate`, Playwright's driver sends the CDP command `Runtime.enable`. Side effect:
this arms the V8 inspector/console plumbing so it becomes **observable from inside the page**. The
canonical detection (DataDome, cited in rebrowser's README) creates an `Error` and defines a getter
on its `.stack`; when the now-enabled inspector serializes console/error objects, that getter fires
— pure page JS, no proxy or fingerprint involved. Because it's genuine CDP behavior:
- `add_init_script` runs *in the page* and can only mask JS-surface properties; it cannot un-send a
  CDP command or disarm inspector state.
- No launch flag stops the driver from calling `Runtime.enable`.
- Opening your own `context.new_cdp_session()` doesn't help — the driver already enabled Runtime on
  its own connection to the target.

The only fixes: a **patched driver** that never sends `Runtime.enable` and resolves context ids via
side channels (rebrowser/patchright, §6), or driving raw CDP yourself and never enabling Runtime
(nodriver's architecture).

**(b) `Console.enable` side channel.** A related inspector-domain leak; patchright suppresses it as
a *consequence* of never enabling Runtime (console events simply never fire). Same reasoning: not
reachable from Python.

Everything else in Tiers A–C **is** reachable natively. That's the honest boundary.

---

## 4. Copy-pasteable plain-Playwright implementation

This is the concrete content for `browser/dom/stealth.py`. It is self-contained, no forked binary.

### 4.1 Launch args

```python
# browser/dom/stealth.py
"""Native stealth layer for Playwright/Chromium — launch args, context options, init script.

No forked binary. Covers Tier A/B/C of docs/research/stealth-browser.md. The CDP Runtime.enable
leak (Tier D) is NOT covered here — swap the driver for rebrowser-playwright/patchright if a target
actually probes it (see §5/§6 of that doc).
"""

# Flags that reduce automation signals without changing traffic shape.
STEALTH_LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",  # navigator.webdriver -> false (#1)
    "--disable-infobars",                             # kill "controlled by automated software" bar (#19)
    "--no-first-run",
    "--no-default-browser-check",
    "--no-service-autorun",
    "--password-store=basic",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--disable-features=IsolateOrigins,site-per-process",  # keep OOPIFs in-process so init script
                                                           # applies consistently to child frames (#13)
    # Prefer real GPU. Only add SwiftShader/software-GL flags if the host has no GPU; a software
    # renderer is itself a tell (#6) that you then have to spoof in the init script.
]

# Playwright passes --enable-automation by default; strip it (removes infobar + webdriver switch).
IGNORE_DEFAULT_ARGS: list[str] = ["--enable-automation"]
```

**Flag notes (derived from nodriver `config.py` and patchright `chromiumSwitchesPatch.ts`):**
- Do **not** pass `--disable-extensions`, `--disable-default-apps`,
  `--disable-component-extensions-with-background-pages` — puppeteer-extra's `defaultArgs` evasion
  and patchright both *remove* these because their presence is an automation tell. Playwright adds
  some of them by default; if you want to match patchright exactly, extend `IGNORE_DEFAULT_ARGS`
  with the ones Playwright injects (audit via `playwright.chromium.launch(args=[])` debug logging).
- `--headless=new` is set automatically by Playwright when `headless=True` on recent versions; do
  **not** use the old headless. Verify with `navigator.userAgent` not containing `HeadlessChrome`.
- Keep `--no-sandbox` **out** of the default set; only add it in containerized CI where sandboxing
  is unavailable (it's a minor tell and a security downgrade).

### 4.2 Choosing the browser: `channel="chrome"` vs bundled Chromium

| | bundled Chromium | `channel="chrome"` (installed Google Chrome) |
|---|---|---|
| UA / brands | `Chromium`, generic UA-CH | real `Google Chrome` UA + branded UA-CH |
| Proprietary media codecs (#17) | absent (`canPlayType` → `''`) | present (`probably`) |
| `window.chrome`, plugins | sparse | populated |
| Reproducibility | pinned to Playwright version | tracks system Chrome |

**Recommendation:** default to `channel="chrome"` for realism; this alone clears signals #2, #3,
#5, #17 with zero init-script code. Keep a bundled-Chromium fallback (with the full init script) for
hosts without Chrome installed, since NetGent needs to run unattended.

### 4.3 Context options

```python
def stealth_context_kwargs(
    *,
    user_agent: str | None = None,   # omit to inherit the real Chrome UA (best with channel="chrome")
    locale: str = "en-US",
    timezone_id: str = "America/Los_Angeles",  # set to match the exit IP / proxy geolocation (#12)
    viewport: dict | None = None,    # None -> use the real window size (headed); else e.g. 1920x1080
    accept_language: str = "en-US,en;q=0.9",   # MUST be consistent with navigator.languages (#11)
) -> dict:
    kwargs: dict = {
        "locale": locale,
        "timezone_id": timezone_id,
        "extra_http_headers": {"Accept-Language": accept_language},
        # Grant nothing extra; a real first-visit session has default permissions. Do NOT blanket
        # grant geolocation/notifications — an all-granted profile is itself anomalous.
        "permissions": [],
        # color_scheme / reduced_motion left at defaults (light / no-preference) to match a
        # typical desktop.
    }
    if user_agent is not None:
        kwargs["user_agent"] = user_agent
    if viewport is not None:
        kwargs["viewport"] = viewport
    else:
        kwargs["no_viewport"] = True   # headed: use the real OS window size (outer* != 0, #10)
    return kwargs
```

**Consistency is the rule that matters more than any single value.** A "clean" fingerprint with
`timezone_id=America/Los_Angeles` but an IP in Frankfurt is *more* anomalous than an honest default.
When NetGent runs through a proxy, derive `locale` / `timezone_id` / `Accept-Language` from the
proxy exit geolocation, and if you override `user_agent`, keep the platform token, `sec-ch-ua`
brands, and `navigator.platform` all mutually consistent (see §4.5 caveat on UA-CH).

### 4.4 The init-script bundle

Register **once on the context** so it runs in every page and every child frame before page scripts:

```python
await context.add_init_script(INIT_SCRIPT)
```

The bundle below ports the reproducible evasions from `puppeteer-extra-plugin-stealth`. The critical
piece is `makeNativeString` + the `Function.prototype.toString` proxy — it's what stops each patch
from being caught by `fn.toString()` returning JS source instead of `[native code]` (#16). Patch the
**prototype**, not the instance, and copy the original descriptor shape, so patched props don't show
up in `Object.getOwnPropertyNames(navigator)`.

```javascript
// INIT_SCRIPT (assign as a Python string in stealth.py)
(() => {
  'use strict';

  // ---- toString integrity layer (the meta-evasion, #16) --------------------
  // Cache natives FIRST (our script runs before page scripts), so a page that later overwrites
  // Reflect/toString can't observe our use of them.
  const nativeToStringStr = Function.prototype.toString.toString(); // "function toString() { [native code] }"
  const makeNativeString = (name = '') =>
    nativeToStringStr.replace(/toString/, name || 'toString');

  const patchedToOriginal = new WeakMap(); // patched fn -> string it should report

  const toStringProxy = new Proxy(Function.prototype.toString, {
    apply(target, ctx, args) {
      if (ctx === toStringProxy) return makeNativeString('toString');          // toString.toString()
      if (patchedToOriginal.has(ctx)) return patchedToOriginal.get(ctx);        // our patched fns
      // Cross-realm safety: delegate if called on a fn from another window/realm (iframes).
      try {
        const sameProto = Object.getPrototypeOf(Function.prototype.toString)
          .isPrototypeOf(ctx.toString);
        if (!sameProto) return ctx.toString();
      } catch (_) { /* fall through */ }
      return Reflect.apply(target, ctx, args);
    },
  });
  // eslint-disable-next-line no-extend-native
  Function.prototype.toString = toStringProxy;

  // Redefine a getter/value while making its accessor report [native code].
  const defineNative = (obj, prop, getter) => {
    const orig = Object.getOwnPropertyDescriptor(obj, prop);
    const g = function () { return getter(); };
    patchedToOriginal.set(g, makeNativeString('get ' + prop));
    Object.defineProperty(obj, prop, {
      get: g,
      configurable: orig ? orig.configurable : true,
      enumerable: orig ? orig.enumerable : false,
    });
  };
  // Replace a native method with a wrapper that still reports [native code].
  const wrapMethod = (obj, prop, impl) => {
    const orig = obj[prop];
    const wrapped = function (...a) { return impl.call(this, orig, a); };
    patchedToOriginal.set(wrapped, makeNativeString(prop));
    obj[prop] = wrapped;
  };

  const navProto = Object.getPrototypeOf(navigator);

  // ---- #1 navigator.webdriver ---------------------------------------------
  try { delete navProto.webdriver; } catch (_) {}
  defineNative(navProto, 'webdriver', () => false);

  // ---- #3 window.chrome stub (skip if channel="chrome" already provides it) -
  if (!window.chrome) {
    const noop = () => {};
    window.chrome = {
      app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
      runtime: { OnInstalledReason: {}, OnRestartRequiredReason: {}, PlatformArch: {}, PlatformOs: {}, connect: noop, sendMessage: noop, id: undefined },
      csi: function () { return { onloadT: Date.now(), startE: Date.now(), pageT: 0, tran: 15 }; },
      loadTimes: function () { return {}; },
    };
    for (const k of ['csi', 'loadTimes']) patchedToOriginal.set(window.chrome[k], makeNativeString(k));
  }

  // ---- #4 permissions.query <-> Notification.permission consistency --------
  if (window.Notification && navigator.permissions && navigator.permissions.query) {
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    wrapMethod(navigator.permissions, 'query', function (orig, args) {
      const params = args[0];
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return origQuery(...args);
    });
  }

  // ---- #14/#15 plausible hardware + locale props ---------------------------
  defineNative(navProto, 'hardwareConcurrency', () => 8);
  defineNative(navProto, 'deviceMemory', () => 8);
  defineNative(navProto, 'languages', () => Object.freeze(['en-US', 'en']));
  defineNative(navProto, 'vendor', () => 'Google Inc.');

  // ---- #5 plugins/mimeTypes: only spoof if empty (bundled Chromium/headless) -
  if (navigator.plugins && navigator.plugins.length === 0) {
    const fakePlugin = (name, filename, desc) => ({ name, filename, description: desc, length: 1 });
    const plugins = [
      fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('Microsoft Edge PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
      fakePlugin('WebKit built-in PDF', 'internal-pdf-viewer', 'Portable Document Format'),
    ];
    plugins.item = (i) => plugins[i]; plugins.namedItem = (n) => plugins.find(p => p.name === n);
    defineNative(navProto, 'plugins', () => plugins);
  }

  // ---- #6 WebGL vendor/renderer: mask SwiftShader with a plausible real GPU -
  // Only meaningful when software rendering is in use; harmless otherwise. Pick a value that is
  // internally consistent with the OS you claim (Intel on macOS/Windows here).
  const spoofGL = (proto) => {
    if (!proto) return;
    wrapMethod(proto, 'getParameter', function (orig, args) {
      const p = args[0];
      if (p === 37445) return 'Intel Inc.';                       // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return 'Intel Iris OpenGL Engine';         // UNMASKED_RENDERER_WEBGL
      return orig.apply(this, args);
    });
  };
  if (window.WebGLRenderingContext) spoofGL(WebGLRenderingContext.prototype);
  if (window.WebGL2RenderingContext) spoofGL(WebGL2RenderingContext.prototype);

  // ---- #17 media codecs (free if channel="chrome") -------------------------
  if (window.HTMLMediaElement) {
    wrapMethod(HTMLMediaElement.prototype, 'canPlayType', function (orig, args) {
      const t = (args[0] || '').toLowerCase();
      if (t.includes('avc1') || t === 'video/mp4') return 'probably';
      if (t.includes('mp4a') || t === 'audio/aac' || t === 'audio/x-m4a') return 'probably';
      return orig.apply(this, args);
    });
  }

  // ---- #10 outer dimensions (headless can report 0) ------------------------
  if (!window.outerWidth)  try { window.outerWidth  = window.innerWidth;  } catch (_) {}
  if (!window.outerHeight) try { window.outerHeight = window.innerHeight + 85; } catch (_) {}
})();
```

> **Tier C canvas/audio noise** is deliberately omitted from the default bundle: adding per-call
> noise to `getImageData`/`toDataURL`/`getChannelData` risks *breaking* legitimate page rendering
> logic and is only worth it against sites that diff canvas hashes across sessions. If needed, add a
> deterministic-per-profile (not per-call-random) noise function so the same NetGent profile is
> stable across a session — otherwise the *instability itself* becomes the tell.

### 4.5 Caveat: UA-Client-Hints when overriding `user_agent`

If you set a custom `user_agent`, Chromium's `Sec-CH-UA*` request headers and
`navigator.userAgentData` brands are **not** automatically updated to match — a mismatch a server
can catch (#11). puppeteer-extra's `user-agent-override` fixes this via CDP
`Network.setUserAgentOverride` with a full `userAgentMetadata`. In plain Playwright the equivalent
is a CDP session:

```python
cdp = await context.new_cdp_session(page)
await cdp.send("Network.setUserAgentOverride", {
    "userAgent": ua,
    "acceptLanguage": "en-US,en;q=0.9",
    "platform": "MacIntel",
    "userAgentMetadata": {  # keep brands/platform/version consistent with `ua`
        "brands": [{"brand": "Chromium", "version": "140"},
                   {"brand": "Google Chrome", "version": "140"},
                   {"brand": "Not?A_Brand", "version": "24"}],
        "fullVersion": "140.0.0.0", "platform": "macOS", "platformVersion": "14.0.0",
        "architecture": "arm64", "model": "", "mobile": False,
    },
})
```

**Simplest path: don't override the UA at all.** With `channel="chrome"` the real Chrome UA and
UA-CH are already consistent — overriding is what *creates* the inconsistency you then have to
repair. Only override when you must emulate a different platform/version.

### 4.6 Wiring into `BrowserSession`

The current `browser/session.py` launches with `chromium.launch(headless=...)` and bare
`new_context()`. Thread the stealth layer in at the two seams:

```python
# in BrowserSession.__aenter__
from netgent.browser.dom import stealth

self._browser = await self._playwright.chromium.launch(
    headless=self._headless,
    channel="chrome",                      # fall back to None (bundled) if Chrome absent
    args=stealth.STEALTH_LAUNCH_ARGS,
    ignore_default_args=stealth.IGNORE_DEFAULT_ARGS,
)
self._context = await self._browser.new_context(**stealth.stealth_context_kwargs())
await self._context.add_init_script(stealth.INIT_SCRIPT)   # runs in every page + frame
self._page = await self._context.new_page()
```

Keep a config switch (`stealth: bool`) so datasets can be generated with/without hardening for
comparison — that's also the cleanest way to *measure* the effect for the paper (§8).

---

## 5. Residual signals that CANNOT be fixed natively (the documented ceiling)

| Signal | Why unreachable from Python Playwright | Native mitigation possible? |
|--------|--------------------------------------------|-----------------------------|
| **CDP `Runtime.enable` execution-context leak (#9)** | The driver sends `Runtime.enable` internally before page JS runs; it arms an in-page-detectable inspector side channel that is CDP state, not a JS property | **No.** Needs patched driver (rebrowser/patchright) or self-driven CDP that never enables Runtime |
| **`Console.enable` inspector leak** | Same domain family; only avoidable by never enabling Runtime | **No** (fork-only) |
| **Closed shadow-root behavior / injected-script timing** | patchright injects init scripts by rewriting the HTML response (Fetch interception + CSP rewrite) because with Runtime disabled the normal path is unreliable; this is a driver rewrite | **No** — but this only matters *after* you've already switched to a fork; vanilla's `add_init_script` timing is fine for vanilla |
| **Input-event CDP origin** (`Input.dispatchMouseEvent` trustedness quirks) | Synthetic events from CDP can differ from OS-level input in low-level flags | Partial only; full fix needs OS-level input injection (CDP-Patches lib) — usually overkill for traffic realism |

**Practical stance for NetGent:** ship the native layer (§4). It clears the entire "trivial
bot-detection" bar the project cares about (signals #1–#8, #10–#17, #19–#20). Treat the
`Runtime.enable` leak as a *known, documented* residual. If a specific target in the dataset turns
out to gate on it, flip the driver import (§6) — a config change, not a rewrite.

---

## 6. The driver-swap escape hatch (when you need Tier D)

Both fixes for the `Runtime.enable` leak ship as **drop-in Python packages** exposing the same
Playwright API — our `browser/dom/` layer works unchanged; only the import moves.

### Option 1 — `rebrowser-playwright` (surgical, closest to vanilla)
Minimal patch: it wraps every internal `Runtime.enable` call in a guard so it's never sent, and
lazily resolves execution-context ids via side channels. Three modes via
`REBROWSER_PATCHES_RUNTIME_FIX_MODE`:
- **`addBinding`** (default) — real main-world access via a random-named `Runtime.addBinding` +
  isolated-world dispatch. Best general default.
- **`alwaysIsolated`** — evaluates only in an isolated world; page can't observe your JS at all, at
  the cost of no main-world variable access.
- **`enableDisable`** — enable then immediately disable Runtime (small residual risk).

```python
# swap: from playwright.async_api import async_playwright
from rebrowser_playwright.async_api import async_playwright  # same API surface
```
Keeps Playwright's architecture; `page.pause()` breaks with the fix on; Chromium-only.

### Option 2 — `patchright` (aggressive fork, maximum surface reduction)
Deletes `Runtime.enable` outright and rebuilds context resolution (via
`Runtime.evaluate {serialization:"idOnly"}` + `DOM.*` node-resolution), bindings (pull model via
`Runtime.queryObjects`/`getProperties` instead of the pushed `Runtime.bindingCalled`), the selector
engine (can pierce **closed** shadow roots via `DOM.describeNode {pierce:true}`), init-script
injection (rewrites the HTML `<head>` and CSP headers), and strips the automation command flags
(removes `--enable-automation`, `--disable-*` tells; adds
`--disable-blink-features=AutomationControlled`; forces `--headless=new`).

```python
from patchright.async_api import async_playwright   # drop-in; this is what Notte uses
```
Trade-offs: **console API is disabled** (a consequence of never enabling Runtime), init-script
injection has route-style side effects with a theoretical timing-attack surface, further from
vanilla behavior. Chromium-only; full low-level input trustedness additionally needs CDP-Patches.

**Recommendation:** stay on vanilla Playwright + our §4 layer for the default dataset generation.
Keep `rebrowser-playwright` as the documented one-line upgrade for targets that probe #9;
reach for `patchright` only if you also need closed-shadow-root interaction or its flag hygiene.
Note the cost for the paper: a patched driver diverges from stock Chrome DevTools behavior, so
record which driver produced which dataset.

---

## 7. Human-timing (behavioral realism — NetGent already owns pacing)

Fingerprint hardening makes a *snapshot* look human; timing makes the *trace* look human. Since
NetGent's executor already sequences actions (`browser/session.py` dispatch loop), this is nearly
free and materially changes the network traffic shape (inter-request gaps, think-time, scroll-driven
lazy loads).

Concrete knobs to add around `dispatch(...)`:
- **Inter-action dwell.** Sample a think-time before each action instead of firing back-to-back.
  Log-normal fits human dwell better than uniform: e.g. `random.lognormvariate(mu, sigma)` clamped
  to ~[0.3s, 4s], with longer tails after navigations/page loads.
- **Per-keystroke typing.** Prefer `locator.press_sequentially(text, delay=…)` (or `type`) with a
  jittered per-key delay (~60–180ms) over `fill()` for form fields you want to look organic. `fill()`
  sets the value instantly (fine for speed, less realistic).
- **Mouse movement / hover before click.** A brief `hover()` then `click()` with a small gap
  produces `mousemove`/`mouseover` events a bare `click()` skips. Optional; do it for primary CTAs.
- **Scroll to trigger lazy-load.** Incremental `mouse.wheel(0, Δ)` steps with pauses, rather than a
  single jump, so lazy-loaded resources fire on a human-like cadence — this is high-value for
  *traffic* realism specifically.
- **Jitter, don't fix, all delays.** A constant 500ms gap is itself a signature. Draw from a
  distribution and vary per action type.
- **Respect visibility / honeypots (#20).** Never fill `display:none`/offscreen/`aria-hidden`
  inputs; gate interaction on `is_visible()` + computed-style checks (the browser-use stress-tests
  specifically plant these).

Keep timing parameters in config so a run can be labeled "human-paced" vs "fast" for the dataset —
another axis the evaluation (§8) can compare.

---

## 8. How to verify

Automate these as tests in `v2/tests/` (an integration test that boots a stealth context, visits a
probe page, and asserts on scraped values). Treat them as regression guards on the init script.

### 8.1 Self-hosted assertions (no external dependency, deterministic — preferred)
Evaluate directly in the page and assert. These map 1:1 to §1's signals:

```python
async def assert_stealth(page):
    checks = await page.evaluate("""() => ({
        webdriver: navigator.webdriver,                                   // expect false
        ua_headless: /HeadlessChrome/.test(navigator.userAgent),          // expect false
        has_chrome: !!window.chrome,                                      // expect true
        plugins: navigator.plugins.length,                                // expect > 0
        languages: navigator.languages.length,                            // expect > 0
        webgl_vendor: (() => { const c=document.createElement('canvas').getContext('webgl');
            const e=c && c.getExtension('WEBGL_debug_renderer_info');
            return e ? c.getParameter(e.UNMASKED_VENDOR_WEBGL) : null; })(),   // expect not SwiftShader
        hw: navigator.hardwareConcurrency,                                // expect plausible (>=4)
        webdriver_tostring: navigator.permissions.query.toString(),       // expect [native code]
        outer_w: window.outerWidth,                                       // expect > 0
    })""")
    assert checks["webdriver"] is False
    assert checks["ua_headless"] is False
    assert checks["has_chrome"] is True
    assert checks["plugins"] > 0
    assert "[native code]" in checks["webdriver_tostring"]
    assert "SwiftShader" not in (checks["webgl_vendor"] or "")
    assert checks["outer_w"] > 0
```

**The most important single assertion is the `toString` one** — if a patched function reports
anything other than `[native code]`, the whole init script is trivially detectable and every other
patch is moot.

### 8.2 Third-party bot-test pages (visual/scored, good for spot-checks)
- **`https://bot.sannysoft.com/`** — rows to eyeball green: *WebDriver (New)*, *WebDriver
  Advanced*, *Chrome (New)*, *Permissions (New)*, *Plugins Length (Old)*, *Languages (Old)*, *WebGL
  Vendor*, *WebGL Renderer*, *Broken Image Dimensions*, plus the fpscanner block. Automate by
  screenshotting and/or scraping the result cells; a fully passing native setup shows no red on the
  Intoli/fpscanner rows.
- **CreepJS `https://abrahamjuliot.github.io/creepjs/`** — reports a "trust score" and, crucially, a
  **lie/inconsistency count**. Our goal is *not* a perfect score (real browsers don't score
  perfectly) but **zero detected lies** — i.e. our spoofs are internally consistent. A high lie
  count means a spoof contradicts another signal; chase those down. Scrape the lies list where
  possible.
- **`fingerprint-scan` / `browserleaks.com/webgl` / `browserleaks.com/canvas`** — confirm WebGL and
  canvas values are plausible and stable per profile.

### 8.3 What "good" looks like (acceptance bar)
1. §8.1 assertions all pass, headed **and** `--headless=new`.
2. sannysoft: no red on WebDriver/Chrome/Permissions/Plugins/Languages/WebGL rows.
3. CreepJS: **zero lies** detected (score can be middling; consistency is the target).
4. `channel="chrome"` run passes with the init script *disabled for signals #3/#5/#17* (proving the
   real-Chrome path doesn't need those spoofs) — a useful A/B that also validates the fallback.
5. Timing: inter-request gaps in the captured HAR are distributed, not constant (sanity-check the
   dataset the layer exists to produce).

### 8.4 The one you cannot self-test natively
The `Runtime.enable` leak (#9) requires a page that runs the inspector-detection trick. If you need
to confirm the ceiling, test against a known probe (e.g. rebrowser's own `bot-detector` page) with
vanilla vs `rebrowser-playwright` and observe the difference — this documents *why* the fork exists
rather than something our native layer can fix.

---

## 9. Sources

- `rebrowser/rebrowser-patches` — the `Runtime.enable` leak mechanism and the guarded-suppression +
  context-resolution fix (`addBinding`/`alwaysIsolated`/`enableDisable` modes).
- `Kaliiiiiiiiii-Vinyzu/patchright` (+ `patchright-python`) — full-fork evasions: Runtime.enable
  deletion, console suppression, closed-shadow-root piercing, flag stripping, init-script-via-network.
- `berstend/puppeteer-extra` → `puppeteer-extra-plugin-stealth/evasions/*` — the 16 evasion modules
  and the `_utils` toString-spoofing machinery ported in §4.4.
- `ultrafunkamsterdam/nodriver` — bare-CDP architecture, clean default arg set, no `Runtime.enable`.
- `ultrafunkamsterdam/undetected-chromedriver` — the `cdc_`/`$cdc_` chromedriver leak and binary
  patch (context for why Playwright is unaffected), runtime JS-injection evasions.
- `microsoft/playwright` — `launch(args=, ignore_default_args=, channel=)`, `new_context` options,
  `add_init_script`, `new_cdp_session` / `Network.setUserAgentOverride`.
- `bot.sannysoft.com`, CreepJS (`abrahamjuliot.github.io/creepjs`), `antoinevastel/fpscanner`,
  `browser-use/stress-tests` — verification targets and the interaction/honeypot surface.
