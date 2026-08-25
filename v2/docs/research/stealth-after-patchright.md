# Stealth after Patchright — what `StealthProfile` still needs to do

*Source-derived and measured, 2026-08-25. Host: macOS 26.5.2, Apple M3 Pro, Google Chrome
151.0.7922.175, `patchright==1.62.1`, `playwright==1.62.0`, residential IP. Every number below
came from a run on this machine; nothing here is quoted from a blog post.*

> **Status (2026-08-25): implemented on `eugene/v2-scaffold`.** `StealthProfile` → `BrowserProfile`
> (`browser/profile.py`); the spoof fallback and the duplicate `AutomationControlled` switch are gone;
> the headless UA is a `--user-agent=` launch flag plus one CDP `Emulation.setUserAgentOverride`
> carrying the browser's own brands and the host's real architecture / OS version — step 2 below,
> now **measured**: headers, page, ServiceWorker and SharedWorker byte-identical to real headed
> Chrome. Headed runs `no_viewport`; locale/timezone default to the host; `storage_state` added as
> the warm-profile axis. Regression: `tests/integration/test_browser_profile.py`.

## Question

`patchright>=1.62.1` is a hard dependency (`v2/pyproject.toml:12`), so `PATCHED_BROWSER` in
`browser/session.py:24` is always `True` and the legacy spoofing branch of `StealthProfile` is
dead code. Given that, three questions:

1. What does Patchright actually patch, and what does it explicitly *not* cover?
2. What detection surface is left under Patchright + real Chrome, headless and headed — and
   which parts of it matter for **traffic realism** (the dataset is the product) rather than
   for beating a named vendor?
3. What should `browser/dom/stealth.py` keep, delete, and add?

The short answer, which the rest of this document supports: Patchright plus stock Chrome already
clears every public detector we can reach. The remaining defects in our own code are **self-inflicted
consistency bugs** introduced by the three things we still override — `user_agent` (headless only),
`locale`, and `viewport` — plus the behavioural/session axis we do not model at all.

---

## What Patchright covers

Line numbers are into the bundled driver shipped with the installed wheel,
`v2/.venv/lib/python3.11/site-packages/patchright/driver/package/lib/coreBundle.js` (a webpack
bundle that preserves `// packages/playwright-core/src/server/...` provenance comments, so each
site can be attributed to its upstream file). "PW" = the same bundle from `playwright==1.62.0`.

| Vector | Patched? | How | Source ref |
|---|---|---|---|
| `Runtime.enable` leak | **Yes** | All Chromium-side calls deleted. PW sends it at `crPage.ts` (PW bundle :37386, :37587) and `crServiceWorker.ts` (:37974); in the Patchright bundle those sites are gone — the only survivors are WebKit/Electron (`wkPage.ts` :48806, `electron.ts` :46165), which Patchright does not claim to support. | patchright bundle vs PW bundle; README "Runtime.enable Leak" |
| Execution-context resolution without `Runtime.enable` | **Yes** | Evaluates `globalThis` with `Runtime.evaluate {serializationOptions:{serialization:"idOnly"}}` and parses the context id out of the returned `objectId` (`"<ctxId>.<n>.<n>"`), memoised per frame; the utility world comes from `Page.createIsolatedWorld` which returns its `executionContextId` directly. | `frames.ts` region, bundle :17845-17875 (`Page.createIsolatedWorld` at :17861); worker variant at `crPage.ts` :39742-39756 |
| `Console.enable` leak | **Yes**, by amputation | Chromium call sites removed; console API is simply unavailable. WebKit still calls it (:48593, :49790). | README: "patches this leak by disabling the Console API all together" |
| Command-line flag tells | **Yes** | Set-diff of `chromiumSwitches()` (Patchright bundle :36569; PW :34639) — **removed** (11): `--allow-pre-commit-input`, `--disable-back-forward-cache`, `--disable-client-side-phishing-detection`, `--disable-component-extensions-with-background-pages`, `--disable-component-update`, `--disable-default-apps`, `--disable-extensions`, `--disable-ipc-flooding-protection`, `--disable-popup-blocking`, `--metrics-recording-only`, `--unsafely-disable-devtools-self-xss-warnings`. **Added** (1): `--disable-blink-features=AutomationControlled`. | measured set-diff of the two bundles |
| `--enable-automation` | **N/A in 1.62** | Neither bundle puts it in `chromiumSwitches`; both only carry `ignoreDefaultArgs:["--enable-automation"]` in unrelated config paths. The README's claim is historical. | both bundles, grep `enable-automation` |
| Init-script injection | **Partly rewritten** | Normal path is still `Page.addScriptToEvaluateOnNewDocument` into the **main** world (`crPage.ts` `_evaluateOnNewDocument`, :40003-40010). Additionally, on `route.fulfill()` of a `text/html` response Patchright inlines the init scripts as a `<script class="<20-byte random hex>" id=…>document.getElementById(…)?.remove();…</script>` tag, rewriting `Content-Security-Policy` headers *and* `<meta http-equiv>` CSP to permit it (`crNetworkManager.ts` fulfill, :38141-38200), and filters `[class=<tag>]` out of DOM queries (:39583, :39654). | bundle, cited lines |
| Closed shadow roots | **Yes** | Normal locators and XPaths pierce closed roots. NetGent relies on this for *acting*; for *observing* it reads closed roots from outside the page with the same CDP pierce (`browser/closed_shadow.py`: `DOM.describeNode(pierce)` → `DOM.resolveNode` into a `Page.createIsolatedWorld` world) — the earlier main-world `attachShadow` registry was a measured prototype lie and is gone (iframes-shadow-dom.md R8). | README "Closed Shadow Roots" |
| Utility-world name | **No** | Still `__playwright_utility_world_<page guid>` (:39083), identical to PW (:37051). Not page-observable without `Runtime.enable`, but note that `rebrowser-patches` randomises it. | both bundles |
| UA / headless stamp / client hints | **No** | Nothing in the bundle touches the `HeadlessChrome` UA token; `calculateUserAgentMetadata()` (`crPage.ts` :38998) is inherited verbatim from PW and derives only `platform`/`platformVersion`/`architecture`/`mobile` from the UA string. | bundle :38998-39041; measured below |
| TLS/HTTP2, IP, behaviour | **No** | Out of scope for a driver patch. | — |

**What Patchright recommends and why.** From `patchright-1.62.1.dist-info/METADATA` ("Best Practice
– use Chrome without Fingerprint Injection"):

```py
playwright.chromium.launch_persistent_context(
    user_data_dir="...", channel="chrome", headless=False, no_viewport=True,
    # do NOT add custom browser headers or user_agent
)
```

The stated reasoning is consistent with what we measured: real Chrome ships a coherent
UA/UA-CH/GPU/font identity, and every override you add is one more field you must keep in sync
with a binary that updates every six weeks. `headless=False` avoids the UA stamp; `no_viewport`
avoids Playwright's device-metrics emulation; a persistent `user_data_dir` gives the profile a
history.

**What it documents as not covered** (driver repo README, "Bugs"): init scripts are injected via
Playwright Routes, so they inherit route-related bugs and are "vulnerable to timing attacks",
though "no antibot currently checks" for that; the console API is dead; only Chromium is patched;
low-level input trustedness needs the separate CDP-Patches project. The README's pass-list
(Cloudflare, Kasada, Akamai, DataDome, Fingerprint.com, CreepJS, Sannysoft, BrowserScan…) is a
vendor claim, and the README is also a sponsor page for four proxy vendors — treat the list as a
hypothesis, which is why we measured.

---

## Residual vectors

Cost is engineering cost to NetGent, not runtime cost.

| Vector | Headless (measured) | Headed (measured) | Who detects it | What fixes it | Cost |
|---|---|---|---|---|---|
| **`HeadlessChrome` UA token** | Present in raw Chrome 151 (`--headless` = new headless still stamps it). Our context `user_agent` override hides it **on the page only**. | Absent. | Trivial substring check; CreepJS. | Headed (ideally Xvfb on Linux), or the `--user-agent=` **launch flag** instead of the context option. | low |
| **Worker/ServiceWorker UA** | **Leaks.** Page says `Chrome/151.0.0.0`, ServiceWorker and SharedWorker say `HeadlessChrome/151.0.0.0`; SW `userAgentData.brands` is `[]`. | Consistent everywhere. | CreepJS reads a worker scope and prints the raw UA — this is the single worst residual. | `--user-agent=` launch flag (measured: fixes page + SW + SharedWorker, SW brands repopulate). | low |
| **UA-CH high-entropy drift** | With our override: `architecture:"x86"`, `platformVersion:"10_15_7"`. Real: `arm` / `26.5.2`. CreepJS renders "macOS Catalina … macOS 10_15_7 x86" beside an "Apple M3 Pro" GPU string. | Correct (`arm`/`26.5.2`) — because we don't override headed. | Any cross-check of `sec-ch-ua-arch` vs WebGL renderer; CreepJS. | Don't override, or override *and* send a full `userAgentMetadata` via CDP. **Note:** the `--user-agent` flag makes `architecture`/`platformVersion` come back as empty strings — a different lie. | med |
| **Low-entropy `sec-ch-ua*`** | **Fine.** Overriding the UA did *not* break brands: header and `navigator.userAgentData.brands` both `"Google Chrome";v="151"` in every configuration tested. The 2024-era warning in `stealth-browser.md` §4.5 does not reproduce on Chrome 151. | Fine. | — | nothing | — |
| **`--disable-blink-features=AutomationControlled`** | Already in Patchright's own switch list; passing it again is a no-op. `navigator.webdriver === false` (the real-Chrome value, not `undefined`). | same | Sannysoft "WebDriver (New)", rebrowser `navigatorWebdriver`. | nothing — delete our copy | low |
| **WebGL / canvas / audio** | **Identical to headed** on macOS: `ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro)`, canvas hash `64ff2a9e`, audio sum `124.04348155876505`. New headless uses the real GPU; no SwiftShader. | same | — | nothing on macOS. On a headless Linux/container host expect SwiftShader — **not measured here**. | — |
| **screen / viewport / DPR** | `viewport=1280×800` ⇒ `screen` 1280×800, `availHeight == height`, DPR 1, `outerHeight == innerHeight`. Real windows have browser chrome (outer 880 vs inner 800) and a Mac has `availHeight < height`. | Same distortion when `viewport` is set: screen forced to 1280×800, DPR 1. With `no_viewport`: screen 1512×982, avail 1512×949, DPR 2, inner 1200×818, outer 1200×905 — fully realistic. | Sannysoft `PHANTOM_WINDOW_HEIGHT` prints all of it; CreepJS Screen section. | `no_viewport=True` headed; headless is stuck with screen==window. | low |
| **locale / Accept-Language** | `locale="en-US"` ⇒ `Accept-Language: en-US` and `navigator.languages == ["en-US"]`. Real Chrome sends `en-US,en;q=0.9` / `["en-US","en"]`. | identical defect | Sannysoft prints "Languages (Old) en-US"; any q-value check. | Drop `locale`, or set `"en-US,en"` — measured to restore both, but `Intl…resolvedOptions().locale` then becomes `"en"`. | low |
| **timezone** | `Intl` zone, `Date` offset (420) and CreepJS's zone all agree. | same | — | nothing | — |
| **fonts** | All 15 probe fonts present incl. Zapfino/Papyrus; CreepJS loads 18/51 with a macOS-specific list. | same | — | nothing on macOS; a slim Linux container is a real tell — **not measured**. | — |
| **plugins / pdfViewerEnabled** | 5 real PDF entries, `pdfViewerEnabled: true`, passes "Plugins is of type PluginArray". | same | Sannysoft | nothing — and *never* re-add the fake `PluginArray`. | — |
| **permissions** | `Notification.permission === "default"`, `permissions.query('notifications') === "prompt"` — consistent. | same | Sannysoft "Permissions (New)". | nothing | — |
| **WebRTC / IP** | Host candidates mDNS-obfuscated (`*.local`); the STUN srflx candidate exposes the public v4+v6 address — exactly what real Chrome does. | same | Only matters under a proxy (WebRTC would bypass it). | policy: proxy-aware WebRTC config, or accept. | med |
| **TLS / HTTP2** | JA4 `t13d1516h2_8daaf6152771_806a8c22fdea`, HTTP/2 Akamai fp `1:65536;2:0;4:6291456;6:262144\|15663105\|0\|m,a,s,p`. | **Byte-identical to headless.** JA3 *hashes* differ run-to-run — Chrome's GREASE extension shuffling, not a mode difference. | JA3/JA4 checks. | nothing to do: we are real Chrome's BoringSSL stack. A browser-level tool cannot change this — which is the point. | — |
| **Behaviour: pacing, dwell, mouse** | Not modelled. Actions fire as fast as the trigger loop allows (`POLL_INTERVAL_S = 0.1`), clicks have no approach path except in `_scroll`. | same | Any request-timing/interaction-entropy model — and, more importantly, **this is what makes our dataset unrepresentative**. | dwell distribution + mouse approach + typing cadence. | med |
| **Session: cold profile** | Every run: no cookies, no history, no cache, no `storage_state`. Every navigation is `Sec-Fetch-Site: none`. | same | Skyvern's stated heuristic ("creating a fresh browser for every step is suspicious"); reputation systems. | persistent `user_data_dir` / `storage_state` as a scenario axis. | med |
| **IP reputation** | Residential here. | same | Every commercial vendor. | infrastructure, not code. | — |

---

## What other tools do

| Tool | Mechanism | Class |
|---|---|---|
| **Patchright** | Rebuilds Playwright's Chromium driver: no `Runtime.enable`/`Console.enable`, context ids via `objectId` parsing, sanitised flag list, closed-shadow piercing, route-based init-script injection. Explicitly recommends spoofing nothing. | **driver patch** |
| **rebrowser-patches** | Surgical patch to stock Puppeteer/Playwright: guards `Runtime.enable` (`addBinding` / `alwaysIsolated` / `enableDisable` modes), strips `//# sourceURL=pptr:` markers, randomises the utility-world name. README is explicit that "this fix alone won't make your browser bulletproof" — proxies and fingerprints remain the user's problem. | **driver patch** |
| **browser-use** | Had `BrowserSession(stealth=True)` → Patchright (`d3c14e17`, 2025-06-05; `b526882d`, #1915). **Removed**: `7d83d6b3` (2025-08-27) "remove deprecated `stealth` option", `4bd8d353` (2025-10-01) "stealth browser infra" → docs now point at Browser Use Cloud. Local defaults keep `--disable-blink-features=AutomationControlled` in `CHROME_DEFAULT_ARGS`. Their **Stealth Bench V1** (71 tasks, `browser-use/benchmark`) scores providers — `browser-use-cloud`, `anchor`, `browserbase`, `browserless`, `hyperbrowser`, `onkernel`, `steel` — against `local_headful` and `local_headless` as the two local baselines. That headful/headless split is the same axis this document lands on. | **was driver patch → now infra** |
| **Skyvern** | Docs: `AutomationControlled` disabled, `enable-automation` suppressed, "viewport, user agent, locale and timezone matched to real consumer browsers"; a `stealth-chromium` persistent-browser type. Its three structural recommendations are behavioural, not fingerprint: residential proxies ("datacenter IPs are the single most common bot signal"), reuse browser sessions across steps, use browser profiles for repeat visits. Also solves CAPTCHAs (out of scope for us). | **flags + JS-free config + infra** |
| **Browserbase / Stagehand** | Basic stealth in-product; **Advanced Stealth is a custom in-house Chromium build, Scale-plan only** — server-side, not something a client library can reproduce. Third-party benchmarking (ScrapeOps, 2026-04) reports Browserbase returning an identical fingerprint hash across sessions, i.e. zero entropy — worth knowing before treating any hosted "stealth" as a realism oracle. | **modified binary + infra** |
| **Camoufox** | Firefox fork patching at the C++ level: navigator/screen/WebGL/AudioContext/geo/timezone injection, protocol-level WebRTC IP spoofing, bundled cross-platform fonts with randomised letter spacing, headless made indistinguishable, and a patched Juggler that hides Playwright's page agent from page scope. Its thesis is ours inverted: "all injected JavaScript is detectable in some way" — so do it in C++ instead of not doing it. | **modified binary** |
| **nodriver** | No chromedriver, no Selenium — direct CDP. "Fresh profile on each run, cleans up on exit", best-practice flags by default. | **driver replacement** |
| **undetected-chromedriver** | Binary-patches the chromedriver executable to stop `cdc_`-style variable injection. README is blunt about the ceiling: "THIS PACKAGE DOES NOT … hide your ip address". Superseded in practice by nodriver (same author). | **driver patch** |
| **Notte** | Ships Patchright as its install step (`patchright install --with-deps chromium`) — same posture as NetGent. | **driver patch** |
| **Lumen / Magnitude** | No stealth layer found in the repo notes; both drive stock Playwright. Their contribution to this file is the mouse-approach-before-scroll mechanic already borrowed in `session.py`. | **none** |

The pattern: everyone who stayed local converged on *don't spoof, patch the driver*; everyone who
went commercial converged on *modified binary + residential IPs*, i.e. infrastructure. Nobody
successful is still shipping a `navigator.plugins` init script.

---

## Measurements

Harness: `/tmp/stealth_measure/{probe,exp,exp2,creep,tls}.py`, driving the repo's own
`BrowserSession` (native profile) plus bare-Patchright control arms. Header echo used a local
`127.0.0.1` server (a secure context, so client hints are sent) cross-checked against
`https://httpbin.org/headers`.

### Detector verdicts

| Detector | Headless | Headed |
|---|---|---|
| `bot.sannysoft.com` | All pass. WebDriver (New) "missing (passed)", WebDriver Advanced "passed", Chrome (New) "present (passed)", Permissions "prompt", Plugins Length 5 + "Plugins is of type PluginArray passed", every `PHANTOM_*` / `HEADCHR_*` / `SELENIUM_DRIVER` / `CHR_*` row "ok". | Identical. |
| `browserscan.net/bot-detection` | **"Test Results: Normal"**; "Headless Chrome: Normal"; "CDP: Normal"; "Dev Tool: Normal". | Identical. |
| `bot-detector.rebrowser.net` | 🟢 `runtimeEnableLeak` "No leak detected", 🟢 `navigatorWebdriver`, 🟢 `viewport` "different from default values used in automation libraries", 🟢 `pwInitScripts` "No window.__pwInitScripts detected", 🟢 `bypassCsp`, 🟢 `useragent`. `dummyFn`/`sourceUrlLeak`/`mainWorldExecution`/`exposeFunctionLeak` ⚪️ (never triggered — we don't touch the main world through those paths). | Identical. |
| `fingerprint.com/products/bot-detection/` | `{"bot": "not_detected"}` | `{"bot": "not_detected"}` |
| `abrahamjuliot.github.io/creepjs` | "chromium: true / 44% like headless / **33% headless** / 0% stealth". Worker section is `ServiceWorkerGlobalScope` and prints `HeadlessChrome/151.0.0.0`; Navigator section prints "macOS Catalina … macOS 10_15_7 x86". | "44% like headless / **0% headless** / 0% stealth". Worker is `WorkerGlobalScope`, UA `Chrome/151.0.0.0`. |
| `arh.antoinevastel.com/bots/areyouheadless` | **502 Bad Gateway (site down)** — not measured. | 502. |

CreepJS's aggregate *trust score* panel never rendered in either mode inside 90 s (it needs their
backend); the per-section ratings above did. Recorded as not-measured rather than inferred.

### Consistency probes

**UA vs UA-CH vs headers** (native profile, headless):

```
Header  User-Agent : …Chrome/151.0.0.0 Safari/537.36        ← rewritten by us
Header  sec-ch-ua  : "Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"   ← correct
page    userAgent  : …Chrome/151.0.0.0
page    brands     : Google Chrome 151 / Chromium 151        ← correct
page    getHighEntropyValues → architecture "x86", platformVersion "10_15_7"   ← WRONG (real: arm / 26.5.2)
ServiceWorker  userAgent : …HeadlessChrome/151.0.0.0         ← LEAK
ServiceWorker  brands    : []                                ← LEAK
SharedWorker   userAgent : …HeadlessChrome/151.0.0.0         ← LEAK
```

Raw Patchright + `channel="chrome"`, no context options, headless: UA `HeadlessChrome/151.0.0.0`
but `sec-ch-ua` still `"Google Chrome";v="151"`, `architecture: "arm"`, `platformVersion: "26.5.2"`.
So Chrome's client hints never leak headless — **only the UA string does**.

The `--user-agent=` launch flag (instead of the context option) was measured to fix the worker
leak completely: page, ServiceWorker and SharedWorker all report `Chrome/151.0.0.0` and SW brands
repopulate. Its cost: page-level `getHighEntropyValues()` returns `architecture: ""` and
`platformVersion: ""`. Trading a wrong value for an empty one — both are lies, and which is
cheaper to detect is **untested**.

**Locale.** `locale="en-US"` ⇒ `Accept-Language: en-US`, `navigator.languages ["en-US"]`.
`locale="en-US,en"` ⇒ `Accept-Language: en-US,en;q=0.9`, `languages ["en-US","en"]`, but
`Intl…resolvedOptions().locale == "en"`. No locale at all ⇒ `en-US,en;q=0.9`, `["en-US","en"]`,
`Intl "en-US"` — i.e. the do-nothing option is the only one that gets all three right.

**Screen / viewport / DPR.**

| config | screen | avail | inner | outer | DPR |
|---|---|---|---|---|---|
| headless, viewport 1280×800 | 1280×800 | 1280×800 | 1280×800 | 1280×800 | 1 |
| headed, viewport 1280×800 | 1280×800 | 1280×800 | 1280×800 | 1282×880 | 1 |
| headed, `no_viewport=True` | 1512×982 | 1512×949 | 1200×818 | 1200×905 | 2 |
| raw headless, no options | 1280×720 | 1280×720 | 1280×720 | 1280×720 | 1 |

`colorDepth` is 30 headed (real display) and 24 headless.

**WebGL / canvas / audio.** Headless and headed produced identical values on this host:
unmasked vendor `Google Inc. (Apple)`, renderer `ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro,
Unspecified Version)`, canvas hash `64ff2a9e`, audio sum `124.04348155876505`. The legacy profile's
`Intel Iris OpenGL Engine` spoof would have *replaced* a truthful GPU string with a false one.

**TLS/HTTP2** (`tls.peet.ws/api/all`): JA4 and the Akamai HTTP/2 fingerprint are identical headless
and headed; JA3 hashes differ per connection because Chrome GREASEs its extension order. Nothing at
the Playwright layer can move these, and nothing needs to.

---

## Recommendation for `StealthProfile`

### Keep

- **`channel="chrome"` with the Chromium fallback** (`stealth.py:110-113`, `session.py:95-101`).
  Justification: it is what produces `"Google Chrome";v="151"` brands and a real ANGLE/Metal
  renderer, and it is Patchright's own documented best practice.
- **`launch_args=[]` for the default profile.** Patchright's `chromiumSwitches()` is already the
  hardened list; our args would only be redundant (`AutomationControlled`) or harmful.
- **`init_script=""`.** Measured: zero JS injection scores all-pass on Sannysoft and green on
  rebrowser's `pwInitScripts`. Anything we inject can only subtract.
- **`timezone_id`.** Consistent across `Intl`, `Date` and CreepJS; keep it as an explicit dataset
  variation axis.
- **`viewport` as an *option*.** Deterministic geometry is worth a lot for replay stability; it is
  simply the wrong *default* headed.

### Delete

- **The entire unpatched fallback**: `DEFAULT_USER_AGENT`, `STEALTH_LAUNCH_ARGS`,
  `STEALTH_INIT_SCRIPT`, and the `user_agent`/`extra_http_headers` branch of `context_kwargs()`.
  It is unreachable (Patchright is a hard dep) *and* every one of its spoofs is measurably worse
  than nothing: a 5-element fake `PluginArray` replaces 5 genuine PDF plugin entries; a pinned
  Chrome-140 UA and hand-written `sec-ch-ua` drift 11 major versions from the binary; the WebGL
  override replaces a true `ANGLE … Apple M3 Pro` with `Intel Iris OpenGL Engine`; the
  `navigator.webdriver → undefined` shim contradicts real Chrome, which returns `false`. Keep the
  plain-Playwright *import* fallback in `session.py` for an "unpatched control" experiment arm,
  but let that arm launch honestly rather than spoofing.
- **Our copy of `--disable-blink-features=AutomationControlled`** — already in Patchright's switch list.

### Add / change

1. **Move the headless UA rewrite to `--user-agent=<real-version UA>`** (launch arg), replacing the
   context-level `user_agent` set in `session.py:104-107`. This is the only measured fix for the
   ServiceWorker/SharedWorker `HeadlessChrome` leak, which is currently the loudest thing we emit.
2. **Restore the high-entropy hints** the flag zeroes, by sending one
   `Emulation.setUserAgentOverride` with a *complete* `userAgentMetadata` (brands, `fullVersionList`,
   `platform`, real `platformVersion`, real `architecture`) over the CDP session `__aenter__`
   already opens (used for closed-shadow observation and this repair). **Unverified** — must be measured against the SW
   probe before shipping, since it may re-break what the flag fixed.
3. **Prefer headed-under-a-virtual-display for dataset runs.** Headed removes the UA rewrite, the
   worker leak and the UA-CH drift in one move (CreepJS: 33% headless → 0%). On Linux that means
   Xvfb + `headless=False`; this is exactly the `local_headful` vs `local_headless` axis
   browser-use's Stealth Bench scores. Keep `--headless` as the fast path, not the default for
   published datasets.
4. **`no_viewport=True` in headed mode** (default), with the fixed viewport kept as an opt-in for
   deterministic replay. Measured: real screen 1512×982, `availHeight` 949, DPR 2, window chrome
   present — the fixed-viewport path forces screen==viewport, `availHeight==height` and DPR 1.
5. **Drop `locale` from the default profile**; expose it only as an explicit scenario axis, and when
   set, write it as `"en-US,en"` and accept that `Intl` resolves to `"en"`. Today's `"en-US"` gives
   a single-entry `navigator.languages` and a q-value-free `Accept-Language`, which no real Chrome
   sends.
6. **Add a session/profile axis**: `user_data_dir` (persistent context) or `storage_state`, so runs
   can start warm. Both Patchright's best-practice block and Skyvern's guidance point here, and for
   a *traffic* dataset a cold profile changes the waterfall (no cache hits, no cookies, every
   navigation `Sec-Fetch-Site: none`), which is a realism defect independent of detection.
7. **Add behavioural pacing hooks**: a dwell distribution between actions, a mouse approach path
   before clicks (the `_scroll` mechanic generalised), and typing cadence. For a project whose
   output is network traffic, timing is not a stealth nicety — it is the shape of the data.

### Rename

Yes — `StealthProfile` → **`BrowserProfile`** (and `native()` → `default()`). After the deletions,
nothing in the class deceives anyone: it selects a channel, a locale, a timezone, a window
geometry and a profile directory. Those are the same knobs we want as *dataset variation axes*,
which is the honest framing for a paper: not "evasion settings" but "environment configuration",
with fidelity to a real Chrome as the acceptance criterion. `stealth: bool | StealthProfile` on
`BrowserSession.__init__` becomes `profile: BrowserProfile | None`, which also removes the
awkward `stealth=False` = "vanilla" meaning.

---

## Verification notes

- **Single host.** All measurements are macOS 26.5.2 / Apple M3 Pro / Chrome 151.0.7922.175 on a
  residential IP. Three results are known to be platform-bound and are **not verified elsewhere**:
  WebGL under headless (macOS new headless uses the real Metal GPU; a GPU-less Linux container
  should fall back to SwiftShader), the font list, and IP reputation. Re-run `probe.py` on the CI
  host before generalising.
- **Not measured:** `areyouheadless` (502 for the whole session); CreepJS's aggregate trust score
  (panel never rendered); whether a full `userAgentMetadata` over CDP repairs the hints without
  re-breaking workers (recommendation 2); whether the empty-string `architecture` produced by
  `--user-agent` is detected in practice.
- **Unexplained but reproducible:** passing `--user-agent=` changed headless window metrics from
  `outer == inner` (1280×800) to `outer 1282×880`, across four runs; a `--window-size` flag did not.
  Mechanism unknown; flagged rather than explained.
- **Corrects the earlier note.** `stealth-browser.md` §4.5 warns that overriding `user_agent`
  leaves `Sec-CH-UA*` and `userAgentData.brands` stale. On Chrome 151 + Playwright 1.62 that does
  **not** reproduce: low-entropy brands stayed correct in every configuration. The real breakage is
  narrower and different — high-entropy `architecture`/`platformVersion`, and workers. Likewise
  §5's description of Patchright injecting init scripts "by rewriting the HTML response" is only
  true on the `route.fulfill()` path in 1.62.1; the normal path is
  `Page.addScriptToEvaluateOnNewDocument` into the main world.
- **Vendor claims are not evidence.** Patchright's README pass-list and Browserbase's "advanced
  stealth" are marketing surfaces (Patchright's README is also a sponsor page for four proxy
  vendors). Only the six detectors run above, plus the in-page probes, are load-bearing here.
- Reproduce with: `uv run python /tmp/stealth_measure/probe.py {raw,native}-{headless,headed}`,
  `exp.py`, `exp2.py`, `tls.py`. Raw JSON and per-detector screenshots are in
  `/tmp/stealth_measure/` (not committed).
