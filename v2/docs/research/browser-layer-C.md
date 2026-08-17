# Browser Layer Deep Dive — Skyvern `webeye`, browser-use `browser/`, and Playwright's native capture

Research for the NetGent v2 browser layer. NetGent v2 compiles natural-language workflow specs into
deterministic, replayable NFA-based automation (LLM at compile time only, **zero LLM calls at run
time**), and its product is **realistic network-traffic datasets** — so network capture is a
first-class output, not a debugging aid.

**Method.** Shallow clones (`git clone --depth 1`) of `Skyvern-AI/skyvern` and
`browser-use/browser-use` into `/tmp/browser-layer-research-C/`, read at HEAD on 2026-08-17.
Playwright claims are checked against the **installed** `playwright==1.58.0` in
`~/anaconda3/lib/python3.11/site-packages/playwright` (generated API + `_impl/`), not only the docs
site — the docs' small-model summary hallucinated a `Tracing.start_har()` that does not exist in
1.58. All file paths below are repo-relative.

Sizes for calibration:

| Layer | LOC | Largest files |
|---|---:|---|
| `skyvern/webeye/` (incl. `actions/`, `scraper/`, `skycdp/`, `utils/`) | ~43.5k | `actions/handler.py` 12,106 · `scraper/domUtils.js` 3,733 · `cdp_download_interceptor.py` 2,236 · `utils/page.py` 2,145 |
| `browser_use/browser/` + `dom/` + `actor/` + `tools/` | ~30k | `browser/session.py` 4,133 · `watchdogs/default_action_watchdog.py` 3,746 · `tools/service.py` 2,317 · `dom/serializer/serializer.py` 1,332 |

---

# Part 1 — Skyvern `skyvern/webeye/`

Skyvern is **Playwright-native** (with a per-run pluggable driver seam), which makes it the closer
analogue for NetGent v2. Its `webeye` package is the browser layer; `skyvern/library/` is the
"Playwright-extension SDK" wrapper; and — critically for NetGent —
`skyvern/core/script_generations/` is a *compile-agent-run-to-deterministic-Python* pipeline that is
almost exactly the v2 thesis.

## 1.1 Module map

### Session lifecycle & construction

| File | What it actually does |
|---|---|
| `browser_factory.py` (1,300) | `BrowserContextFactory` — a **registry of creator functions keyed by `settings.BROWSER_TYPE`** (`register_type("chromium-headless"/"chromium-headful"/"cdp-connect", …)` at the bottom of the file). `build_browser_args()` is the single place where `record_har_path`, `record_video_dir`, `record_video_size`, `viewport`, `locale`, `timezone_id`, Chromium `args`, and `ignore_default_args` are assembled. `create_browser_context()` is the one chokepoint that, after the creator returns, layers on: cookie restore (`restore_session_cookies` / `restore_banked_cookies`), console-log capture (`set_browser_console_log`), popup-video registration (`set_popup_video_listener`), download listener (`set_download_file_listener`), dialog handler (`set_dialog_handler`), and origin-scoped header rewriting via `context.route("**/*", …)` (`_apply_origin_scoped_headers`). |
| `browser_manager.py` (113) | Pure `Protocol`. Interesting for NetGent: the manager interface itself declares the artifact getters — `get_video_artifacts()`, **`get_har_data()`**, `get_browser_console_log()`. Capture is a first-class manager responsibility, not a side effect. |
| `real_browser_manager.py` (1,635) | The concrete manager. Owns per-run/per-workflow/per-script `BrowserState` caches, persistent-session leasing, and the artifact readers (`get_har_data` at :1131 just reads `browser_artifacts.har_path` off disk; `get_video_artifacts` at :1081 runs the webm→mp4 finalization). |
| `browser_state.py` (133) | `BrowserState` `Protocol` — the driving surface: `get_working_page()`, `must_get_working_page()`, `set_working_page()`, `navigate_to_url()`, `list_valid_pages()`, `close_current_open_page()`, `reload_page()`, `take_fullpage_screenshot()`, `scrape_website()`. Also pins `engine_selection` per state. |
| `real_browser_state.py` (871) | Concrete state. Notable methods: `check_and_fix_state()` (self-heal: reconnect, reopen a lost working page), `_reopen_lost_working_page()`, `_close_all_other_pages()`, `close_pages_opened_after()`, `validate_browser_context()`, `_wait_for_settle()`, `detach_remote_driver()`. This is where "which tab is the agent on" lives. |
| `browser_engine.py` (514) | Per-**run** engine selection seam. `BrowserEngineSelection` carries the driver factory *and the driver's public exception identity* (`is_engine_timeout_error(exc)`), so timeout classification is engine-correct rather than `isinstance(e, playwright.TimeoutError)`. Engines: `playwright` (stock), `rustwright`, `skycdp`. Constructing a spec never imports the driver package; selecting an absent one fails closed with `BrowserEngineUnavailable`. |
| `browser_artifacts.py` (121) | `BrowserArtifacts` pydantic model: `video_artifacts`, `har_path`, `traces_dir`, `browser_session_dir`, `browser_console_log_path`, plus `DownloadBinding` (`RUN_DIR` vs `SESSION_DIR`) and a `_discarded_pages` tombstone set so a page closed before it became the working page can't have its video re-registered after an await. |
| `persistent_sessions_manager.py` / `default_persistent_sessions_manager.py` (208 / 928) | Long-lived browser sessions shared across runs, with leasing. |
| `attach_only.py`, `cdp_ports.py`, `cdp_connection.py`, `cdp_retry.py`, `cdp_credentials.py`, `profile_cookie_merge.py`, `session_cookies.py`, `browser_profile_utils.py`, `chromium_preferences.json` | Attach-only worker enforcement; CDP URL/header plumbing (`redact_cdp_url`, `merge_cdp_connect_headers`); retries; cookie/profile persistence. `chromium_preferences.json` is a template with `MASK_DOWNLOAD_DEFAULT_DIRECTORY` placeholders written into `user_data_dir/Default/Preferences` before launch. |

### Observation (scraping)

| File | What it does |
|---|---|
| `scraper/scraper.py` (1,251) | `scrape_website()` (retry wrapper) → `scrape_web_unsafe()` (the real thing). Also `get_interactable_element_tree()`, `add_frame_interactable_elements()`, `filter_frames()`, `get_frame_text()`, `build_element_dict()`, `hash_element()`, `trim_element_tree()`. |
| `scraper/scraped_page.py` (539) | `ScrapedPage` model + `ElementTreeBuilder` ABC. Holds `elements`, `id_to_css_dict`, `id_to_element_dict`, `id_to_frame_dict`, **`id_to_element_hash`**, **`hash_to_element_ids`**, `element_tree`, `element_tree_trimmed`, `screenshots`, `html`, `extracted_text`. `json_to_html()` renders the tree to the LLM-facing pseudo-HTML. Three render variants: `build_element_tree` / `build_economy_elements_tree` (drops SVG) / `build_lean_elements_tree` (href/src compression, cached by 4-flag tuple). |
| `scraper/domUtils.js` (3,733) | The injected JS. `buildTreeFromBody()` → `buildElementTree()` → `buildElementObject()`; visibility (`isElementVisible`, `expectHitTarget`), interactability (`isInteractable`, `isHoverPointerElement`, `hasAngularClickBinding`, `isKendoDropdownValueTrigger`, …), `getSelectOptions`, `getVisibleText`, `getOpenAriaPopupTrigger`, `uniqueId()`, `removeAllUniqueIds()`, and a `MutationObserver` (`window.globalObserverForDOMIncrement`) for incremental (dropdown) trees. |
| `scraper/cursorOverlay.js` (141) | Draws a synthetic cursor for the video recording. Cosmetic. |
| `utils/page.py` (2,145) | `SkyvernFrame` — the frame/page facade. Screenshot helpers (`take_split_screenshots`, `_scrolling_screenshots_helper`, `_merge_images_by_position`), `evaluate()` with navigation-recovery, `wait_for_page_ready()`, `safe_wait_for_animation_end()`, `build_tree_from_body()`, `read_blob_url_bytes()`, `read_http_url_bytes()`, blob-URL retention install/teardown. |
| `utils/dom.py` (1,604) | `SkyvernElement` — the element facade over a Playwright `Locator`, resolved by `[unique_id='XX']`. ~60 predicates (`is_auto_completion_input`, `is_spinbtn_input`, `is_readonly`, `find_label_for`, `find_blocking_element`, `should_use_navigation_instead_click`, …). This is where most of Skyvern's real-world robustness lives. |
| `dom_inspection.py`, `main_world_eval.py`, `transient_page_observer.py`, `browser_object_predicates.py`, `cursor_visualization.py`, `string_util.py` | `main_world_eval.py` routes `page.evaluate` through a single CDP `Runtime.evaluate` with an opaque text prefix when configured. `transient_page_observer.py` uses **`page.expose_binding(TRANSIENT_TEXT_BINDING_NAME, record_text_event)`** (`:137`) + a MutationObserver to capture short-lived toast/error text that would be gone by the next scrape. |

### Action definition vs execution

| File | What it does |
|---|---|
| `actions/action_types.py` (65) | `ActionType` StrEnum — 30 members. `is_web_action()` marks the element-targeting subset. `POST_ACTION_EXECUTION_ACTION_TYPES` lists which types trigger a post-action screenshot. |
| `actions/actions.py` (499) | The **data model**. `Action` base (`action_type`, `element_id`, **`skyvern_element_hash`**, `skyvern_element_data`, `xpath`, `intention`, `text`, `option`, …) plus one subclass per type. `Action.validate()` is a hand-written dispatch from `action_type` → concrete class. Several fields are `Field(exclude=True)` "transient, never serialized" (`observation_epoch`, `observation_digest`, `prefilter_typeahead`). |
| `actions/parse_actions.py` (1,553) | LLM JSON → `Action` objects. **Pure LLM-loop baggage for NetGent.** |
| `actions/handler.py` (12,106) | The **execution** side. `ActionHandler` (`:3473`) is a class-level registry: `_handled_action_types`, `_setup_action_types`, `_teardown_action_types`, populated by `ActionHandler.register_action_type(ActionType.CLICK, handle_click_action)` etc. at `:7779–7800`. `_handle_action()` (`:4335`) wraps every dispatch in `asyncio.timeout(_resolve_action_execution_timeout(action))` and a long `except` ladder that converts known failures into `ActionFailure` rather than raising. Handlers are `(action, page, scraped_page, task, step) -> list[ActionResult]`. |
| `actions/caching.py` (268) | **The most NetGent-relevant file in the repo.** `retrieve_action_plan()` replays a previously recorded action list against a fresh page by matching `cached_action.skyvern_element_hash` into `scraped_page.hash_to_element_ids`. See §1.6. |
| `actions/responses.py` (114) | `ActionResult` / `ActionSuccess` / `ActionFailure` / `ActionAbort`. |
| `actions/handler_utils.py` (161) | Low-level primitives: `input_sequentially`, `keypress` (with `hold`/`duration`/`repeat`), `drag`, `left_mouse`, `download_file`. |

### Instrumentation

| File | What it does |
|---|---|
| `cdp_download_interceptor.py` (2,236) | Full CDP **Fetch**-domain download interception (see §1.5). |
| `cdp_frame_publisher.py` (394) | Periodic (1 s) CDP screenshot publisher for remote/reused-CDP contexts where Playwright's in-process `record_video_dir` cannot reach. |
| `video_utils.py` (375) | ffmpeg/ffprobe post-processing: `prepare_recording_for_upload()` (webm → h264 mp4, `+faststart`), `_remux_webm()` (stream-copy with `-cues_to_front` to repair an unfinalized Matroska segment when `context.close()` was killed mid-shutdown), `probe_media_duration_seconds()`, `cut_recording_segment()` (frame-accurate re-encoded clip), `plan_run_segment()` (map a run's wall-clock window onto offsets inside a shared session recording). |
| `dialog_handler.py` (184) | `set_dialog_handler(browser_context)` registers `page.on("dialog", …)` on existing + future pages, deduped by two `WeakSet`s. `alert` and `beforeunload` auto-accept; `confirm`/`prompt` with no task context auto-accept; otherwise **an LLM call decides**, bounded by `asyncio.wait_for(..., DIALOG_LLM_TIMEOUT)` because "JS dialogs block the page's JS thread while open". |
| `navigation.py` (178) | `navigate_with_retry()` + `validate_navigation_destination()` + `revalidate_redirect_chain()`. See §1.4. |
| `skycdp/` (~2,300 across 20 files) | A **from-scratch raw-CDP driver shaped like Playwright's API**: `connection.py`, `transport.py`, and `facade/{page,browser,elements,input,locator,evaluation,network,network_events,routing,dialogs,artifacts,timeouts}.py`. `facade/network.py` re-implements Playwright's route chain (`continue_`/`fulfill`/`abort`/`fallback`) over `Fetch.*`; `facade/network_events.py` re-implements `page.on("request"/"response")` over `Network.*`. Read these two if you want to know exactly what Playwright's network surface costs and guarantees — the module docstrings are unusually candid. |

## 1.2 Boundaries

Skyvern's separation is clean and worth copying:

```
BrowserContextFactory   →  creates a BrowserContext + BrowserArtifacts + cleanup_func   (construction)
BrowserManager          →  owns/caches/leases BrowserStates per task/workflow/script    (lifecycle)
BrowserState            →  which page is "working", navigate, reconnect, screenshot     (driving)
ScrapedPage             →  one immutable observation of the page                        (observation)
ActionHandler registry  →  ActionType → handler coroutine                               (dispatch)
handle_*_action         →  SkyvernElement/SkyvernFrame + Playwright Locator calls       (execution)
```

Two seams matter most:

1. **Action *definition* (`actions/actions.py`) is completely separate from action *execution*
   (`actions/handler.py`).** The `Action` model is a serializable pydantic record with a database
   identity (`action_id`, `source_action_id`), and the registry maps type → coroutine at import
   time. That means an action list is a *durable artifact* you can persist, diff, and replay — which
   is precisely NetGent's transition-label representation.

2. **Setup/handler/teardown triple.** `register_setup_for_action_type` / `register_action_type` /
   `register_teardown_for_action_type` let cross-cutting concerns (screenshot before/after,
   download-settle, challenge-solver wait) attach per action type without every handler
   re-implementing them. For NetGent this is the natural hook point for *per-transition network
   capture markers*.

The action-execution timeout is per-action and type-dependent
(`_resolve_action_execution_timeout`, `handler.py:4469`), enforced by `asyncio.timeout()` around
setup+handler+teardown, and the expiry is distinguished from an inner `asyncio.TimeoutError` by
checking `execution_timeout_scope.expired()` (`:4427`) — a detail that is easy to get wrong.

## 1.3 DOM / observation pipeline

`scrape_web_unsafe()` (`scraper/scraper.py:487`) is the whole pipeline:

1. `page = await browser_state.must_get_working_page()`; reject `about:blank` unless the page has
   "meaningful" child frames (`:525–535` — Edge's PDF interstitial renders into an iframe on
   `about:blank`).
2. `SkyvernFrame.create_instance(page, engine_selection=…)` → `_wait_for_scrape_ready()` (§1.4).
3. `get_interactable_element_tree(page, scrape_exclude, must_included_tags, engine_selection)` →
   `skyvern_page.build_tree_from_body(...)` which `evaluate`s `buildTreeFromBody()` from
   `domUtils.js`. Then, for each visible child frame (`filter_frames`,
   `add_frame_interactable_elements`), it recurses and grafts the subtree onto the parent's iframe
   node. There is a **hard-won comment at `:806–816`**: the flat `elements` list and the nested
   `element_tree` must *both* be written, because Playwright's deserializer revives repeated objects
   by reference (one write reaches both) but a raw-CDP `returnByValue` is a JSON round-trip that
   copies them — so on the CDP engine the flat write alone left `<iframe></iframe>` in the tree.
4. If `elements` is empty → `empty_page_retry_wait()` and re-run once.
5. `cleanup_element_tree(...)` (caller-supplied) then `trim_element_tree(...)`.
6. Screenshots: `SkyvernFrame.take_split_screenshots()` scrolls the page and stitches
   (`_merge_images_by_position`), then scrolls back to the saved `(x, y)`.
7. `build_element_dict(elements)` builds the five lookup maps including the hashes.
8. `get_frame_text(page.main_frame)` for text, `skyvern_frame.get_content()` for HTML.
9. `advance_observation_epoch(page, main_frame_url, element_hashes, destinations)` — stamps a
   monotonic "observation epoch" plus a digest of the element hashes, so a stale action planned
   under an older observation can be detected.

### Element ID stability — two mechanisms

**Within a page load: `unique_id`.** `domUtils.js:2182` does
`var element_id = element.getAttribute("unique_id") ?? (await uniqueId()); element.setAttribute("unique_id", element_id)`.
`uniqueId()` (`:1898`) generates a 4-char id: char 1 encodes `window.GlobalSkyvernFrameIndex` (or a
random symbol from `~!@#$%^&*()-_+=` when the frame index is unknown), chars 2–4 are a base-62
counter. Because the attribute is **written into the live DOM and re-read on the next scrape**, the
same element keeps the same id across re-scrapes *of the same document*. `id_to_css_dict[id]` is
literally `[unique_id='XX']`, so every action resolves through a Playwright locator on that
attribute. The MutationObserver explicitly skips `unique_id` attribute mutations (`:3415`) to avoid
an infinite loop. `removeAllUniqueIds()` (`:3691`) cleans up.

**Across page loads / across runs: `skyvern_element_hash`.** `hash_element(element)`
(`scraper/scraper.py:229`) = `sha256(json.dumps(clean_element_before_hashing(element), sort_keys=True))`,
where `clean_element_before_hashing` strips exactly `id`, `rect`, `frame_index`, and the
`unique_id` attribute — i.e. everything positional or session-local. The result is a
**structure-and-content hash** that survives a reload and (usually) survives a different run of the
same site. `hash_to_element_ids` is `dict[str, list[str]]` precisely because collisions are
expected and must be detectable.

This is the design NetGent needs, and Skyvern's own failure mode is documented: `caching.py:96`
bails out of replay entirely when `len(matching_element_ids) > 1`.

## 1.4 Waiting / synchronization

**Navigation** (`navigation.py:112`, `navigate_with_retry`):

- Fail closed *before* dispatch: `validate_navigation_destination(url)` on a thread, rejecting
  non-http(s) schemes and private/loopback/link-local/metadata hosts using the **browser's WHATWG
  canonicalization** (`canonical_navigation_host`), not `urllib.parse` — numeric-IP and backslash
  authority tricks are caught.
- **Progressive `wait_until` degradation**: `_DEGRADATION_MAP = {"load": ["load", "domcontentloaded", "commit"], …}`.
  Attempt *n* uses `degradation[min(n, len-1)]`. A page that never fires `load` still succeeds on
  attempt 3 at `commit`.
- After `goto` returns, `revalidate_redirect_chain()` walks `response.request.redirected_from`
  (bounded at `_MAX_REDIRECT_HOPS = 100`) and re-validates every hop, because `goto` follows
  redirects at the network layer and a public entry point can land on an internal host.
- Error triage by string matching: `SKIP_INNER_NAV_RETRY_ERRORS` → raise immediately;
  `PERMANENT_NAV_ERRORS` → don't retry. Backoff is a flat `await sleep(1)`.

**Page readiness** (`utils/page.py`), two modes, selected by
`SkyvernContext.enable_page_ready_wait`:

- Default: `safe_wait_for_animation_end(caller=…)` (`:1900`) — `wait_for_load_state("load")` then
  poll `isAnimationFinished()` from `domUtils.js` every 100 ms. Timeouts are **swallowed**
  (`LOG.debug` + `return`), with the outcome recorded on an OTel span as
  `animation_result = finished|timeout|error`. The comment notes a 124× p95/p50 ratio in production
  — i.e. the timeout path is the common tail.
- Enhanced: `wait_for_page_ready()` (`:1940`) — three independent, independently-timed, all-failures-
  swallowed checks, ordered **longest timeout first**:
  1. `_wait_for_loading_indicators_gone()` — polls a hardcoded selector list
     (`[class*="spinner"]`, `[class*="skeleton"]`, `[role="progressbar"]`, `[aria-busy="true"]`, …)
     for a *visible* match.
  2. `frame.wait_for_load_state("networkidle")`.
  3. `_wait_for_dom_stable(stable_ms, timeout_ms)` — an injected `MutationObserver` promise that
     resolves once no *significant* mutation (childList, characterData, or an attribute change on an
     element with non-zero `getBoundingClientRect()`) has fired for `stable_ms`.

  Notably this is described as "designed for **cached action execution**" — i.e. Skyvern reached for
  a stronger readiness signal exactly when it stopped having an LLM to re-observe and correct.

**Scrape retries** (`scrape_website`, `:259`): a hand-unrolled three-attempt ladder on
`NoElementFound` — attempt 1, `sleep(3)`, attempt 2, then an explicit
`page.goto(page.url)` ("`page.reload()` on a POST-result document can resubmit the form") + `sleep(3)`,
attempt 3. The outer generic retry (`max_retries`) is **set to 0 in staging and production**, per the
docstring — the real retry policy is the inner ladder.

**Script-path waiting** (`core/script_generations/skyvern_page.py`):
`_wait_for_selector_with_retry()` (`:261`) retries `locator.wait_for(state="attached")` only on
timeout / "execution context destroyed", re-acquiring the locator each attempt ("in case the DOM was
replaced entirely"), and explicitly **never retries interaction failures** to avoid
double-submitting. `_prepare_element()` (`:319`) does `wait_for(state="visible")` →
`scroll_into_view_if_needed()` → `sleep(0.15)`, each best-effort.

## 1.5 Instrumentation — exactly how Skyvern captures

### Network → HAR (Playwright-native, with a real gap)

`BrowserContextFactory.build_browser_args()` (`browser_factory.py:624`) sets:

```python
har_dir = f"{settings.HAR_PATH}/{utcnow:%Y-%m-%d}/{BrowserContextFactory.get_subdir()}.har"
args = {..., "record_har_path": har_dir, "record_video_dir": video_dir, ...}
```

where `get_subdir()` is the current `task_id` → `request_id` → random UUID. For the two local
creators (`_create_headless_chromium`, `_create_headful_chromium`) this goes straight into
`playwright.chromium.launch_persistent_context(**browser_args)`, and
`browser_artifacts.har_path = browser_args["record_har_path"]`. `get_har_data()`
(`real_browser_manager.py:1131`) later just reads that file off disk.

**The gap:** `_connect_to_cdp_browser()` (`browser_factory.py:1191`) *computes* `browser_args` and
sets `browser_artifacts.har_path = browser_args["record_har_path"]` (`:1206–1208`) — but the actual
`browser.new_context(...)` call at `:1254` passes only `record_video_dir`, `record_video_size`,
`viewport`, `extra_http_headers`. **No `record_har_path`.** And when an existing context is reused
(`contexts[0]`, `:1262`) there is no opportunity to set it at all, since HAR recording is a
context-construction option in Playwright. So on the `cdp-connect` path the artifact record points
at a HAR file that is never written, and `get_har_data` falls through to
`LOG.warning("HAR data not found for task")` + `return b""`.

> **Lesson for NetGent, stated bluntly:** *HAR is a context-construction option.* If your capture
> plan is `record_har_path`, then every code path that obtains a context — including "attach to an
> existing remote browser and reuse `contexts[0]`" — must go through a constructor you control, or
> capture silently disappears with no error.

There are **no** HAR knobs beyond the path: Skyvern never sets `record_har_content`,
`record_har_mode`, or `record_har_url_filter`, so it always gets Playwright's defaults
(`embed` content — see §3 for the `.zip` special case — and `full` mode).

### Network → CDP (for interception, not capture)

Two separate CDP network surfaces exist, and the distinction is exactly the one NetGent must make:

- **`skycdp/facade/network.py`** — the **Fetch** domain. Pauses a request so a handler can rewrite
  it. Module docstring: *"Every paused request must be answered exactly once… a handler that raises,
  forgets, or answers twice does not produce an error — it produces a page that stops loading. That
  makes the failure mode of this module silence."* `dispatch()` walks handlers newest-first;
  `fallback()` declines while accumulating overrides, `continue_()` ends the chain; an unmatched
  request is continued, and a handler that **raises** gets `route.abort("failed")` — fail closed,
  because "a guard that errors must not become a guard that permits".
- **`skycdp/facade/network_events.py`** — the **Network** domain, observe-only. Re-implements
  `page.on("request"/"response"/"requestfinished"/"requestfailed"/"pageerror")` over
  `Network.requestWillBeSent` / `responseReceived` / `loadingFinished` / `loadingFailed` /
  `Runtime.exceptionThrown`. Three facts here are load-bearing for NetGent:
  - **Request identity must be stable across events.** The same `NetworkRequest` object is emitted
    for `request`, `response`, and `requestfinished`, because the consumer keeps admitted requests in
    a `set` and later tests `response.request not in self._admitted_requests`.
  - **`Network.enable` is not free.** *"Chrome then streams three events per subresource, and
    measured against a real browser it cost **+127 ms** on `goto` (175 → 302 ms)"* — so it is enabled
    only for pages that actually subscribe.
  - **The enable/navigate race is real.** `page.on` is synchronous; scheduling the enable from it
    loses the race against a `goto` on the next line and *silently drops every request that beat it
    onto the wire*. The fix: `ensure_enabled()` starts the enable, `settled()` awaits it before the
    next navigation.
  - **Response bodies are lazy and bounded.** `Network.getResponseBody` refuses a body that has not
    finished arriving, so `response_body()` waits on a per-request `asyncio.Event` (30 s cap) before
    asking; and only the last `_MAX_TRACKED_REQUESTS = 500` requests stay addressable (oldest-first
    eviction), because "Chrome discards the bodies itself long before then".

### Video

Two independent paths:

1. **Playwright-native** — `record_video_dir` (+ optional `record_video_size` from
   `settings.BROWSER_RECORDING_WIDTH/HEIGHT`) on the context. `set_popup_video_listener()`
   (`browser_factory.py:325`) hooks `browser_context.on("page", …)` *and* iterates
   `browser_context.pages` for already-existing pages, resolving `page.video.path()` through
   `resolve_artifact_path()`. That helper exists for a nasty reason documented at `:291`: Patchright
   resolves `Video.path()` from **one future shared across awaiters**, so a bare timeout-cancel on
   any awaiter poisons it for all the others — hence `asyncio.shield` + a done-callback that consumes
   the abandoned task's exception.
2. **CDP screencast** — `cdp_frame_publisher.py`, for remote/reused-CDP contexts Playwright's
   in-process recorder can't reach. Periodic (1 s) CDP screenshots, hashed and written to a temp dir.

Post-processing (`video_utils.py`) is where the real lessons are: a `.webm` from a context whose
`close()` was killed mid-shutdown has an unknown-size Segment, no `Duration`, and no `Cues` — the
`_remux_webm` stream-copy with `-cues_to_front 1 -reserve_index_space 200k` repairs it. And
`plan_run_segment()` + `cut_recording_segment()` exist because a *session* recording spans multiple
runs, so per-run clips are located by wall-clock overlap with `ffprobe`-measured duration, and the
cut **re-encodes** rather than stream-copies (a keyframe-aligned stream copy would pull in the
previous run's frames as pre-roll).

### Downloads

Three layers, in increasing desperation:

1. **Chromium preferences** — `update_chromium_browser_preferences()` writes
   `user_data_dir/Default/Preferences` from `chromium_preferences.json`, substituting the download
   dir. Plus `downloads_path=` on the context.
2. **`Browser.setDownloadBehavior`** — `rebind_download_dir()` (`browser_factory.py:472`) opens
   `browser.new_browser_cdp_session()` (or `page.context.new_cdp_session(page)` for
   `launch_persistent_context` browsers, which expose no owning `Browser`) and sends
   `{"behavior": "allow", "downloadPath": download_dir}`. Fails **open** — a rebind failure must
   never break a launch.
3. **`CDPDownloadInterceptor`** (`cdp_download_interceptor.py`, 2,236 lines) — full **Fetch**-domain
   interception, used *"for remote CDP browsers where `Browser.setDownloadBehavior` with a local
   `downloadPath` does not work (e.g. Playwright bug #38805 — remote Windows Chrome ignoring Linux
   paths)"*. Flow per the module docstring: enable `Fetch` at both request and response stages;
   request stage → authorize then continue/fail-closed; response non-download →
   `Fetch.continueResponse`; response download → `Fetch.takeResponseBodyAsStream` → disk →
   `Fetch.fulfillRequest`. Also handles `Fetch.authRequired` for proxy 407s, and a
   `Browser.downloadWillBegin` monitor mode (`{behavior: "deny", eventsEnabled: True}`) that saves
   files over HTTP when remote CDP has no valid local `downloadPath`. Bounds everywhere:
   `MAX_FILE_SIZE_BYTES = 100 MB`, `MAX_PENDING_BROWSER_DOWNLOAD_TASKS = 64`.

Plus a Playwright-level `set_download_file_listener()` (`browser_factory.py:375`) whose only job is
**filename repair**: if `download.path()` has no suffix, derive one from `suggested_filename`, then
from a `filename=` query param, then from the URL path.

### Console

`set_browser_console_log()` (`browser_factory.py:264`) registers `browser_context.on("console", …)`
and appends `{iso8601}[{msg.type}]{msg.text} {location kvs}` lines to a per-context log file under an
`asyncio.Lock`, with a 5 s lock-acquisition timeout after which it reads unlocked and warns
"may be incomplete".

### Tracing

`BrowserArtifacts.traces_dir` exists as a field. Nothing in `webeye/` ever calls
`context.tracing.start()`. Skyvern does not use Playwright tracing.

## 1.6 `skyvern/library/` — the Playwright-extension SDK, and the compile-to-script pipeline

`skyvern/library/` is thin. `SkyvernBrowserPage` (`skyvern_browser_page.py:18`) extends
`SkyvernPage` and adds `frame_switch`/`frame_main`/`frame_list` plus `.act(prompt)` and a `.agent`
attribute. `SdkSkyvernPageAi` (`skyvern_browser_page_ai.py:32`) is a pure RPC shim — every
`ai_click` / `ai_input_text` / `ai_select_option` is `await self._browser.skyvern.run_sdk_action(...)`
against the server.

**The interesting layer is one level down: `skyvern/core/script_generations/`.**

`SkyvernPage` (`skyvern_page.py:83`) is *"a lightweight adapter for the selected driver"* that
subclasses Playwright's `Page` and forwards unknown attributes via a `__getattribute__` override
(`:106`) — so it *is* a Playwright page with extra methods. Its public methods (`click`, `fill`,
`type`, `select_option`, `upload_file`, `extract`, `validate`, `fill_form`, `download_file`, …) each
take a **selector and/or a prompt**, with `ai="fallback"` as the default:

```python
await page.click("#open-invoice-button")                       # deterministic
await page.click(prompt="Click the 'Open Invoice' button")     # LLM
await page.click("#open-invoice-button", prompt="…")           # selector first, LLM on failure
await page.click('[data-automation-id="nextButton"]', mode="direct")  # raw Playwright, no AI, no prep
```

`mode="direct"` (`:411–418`) is the pure-Playwright escape hatch: `locator.click(timeout=…)`, no AI
fallback, no element prep — *"the action is still recorded in the DB so it appears in the timeline"*.
LLM calls on this path are counted against a budget (`ctx.script_llm_call_count`, `_track_ai_call`).

`generate_script.py` (4,222 lines) emits this Python from a completed agent run; `CLAUDE.md` in the
same directory documents the caching model:

- Blocks are cached **progressively** — only blocks that actually executed this run get a
  `script_block` row + a non-null `run_signature`. `run_with: code` requires *all* top-level blocks
  to have both; otherwise the whole workflow falls back to `run_with: agent`.
- **Conditional blocks are never cached** — they always run via agent so conditions are evaluated at
  runtime — but cacheable blocks *inside* branches are cached when they execute. Run 1 takes branch
  A and caches it; run 2 takes branch B and caches it, preserving A.
- Script generation was moved from per-action to per-block completion, cutting generation frequency
  10–50×.

### `actions/caching.py` — the replay algorithm, and where it gives up

`retrieve_action_plan(task, step, scraped_page)` is the closest thing in either repo to NetGent's
replay:

1. Load the cached action list; load this task's already-executed actions; match them pairwise on
   `source_action_id`. Any executed action **without** a `source_action_id` means the run already
   fell back to no-cache mode → return `[]` permanently.
2. For each remaining cached action, look up `scraped_page.hash_to_element_ids[action.skyvern_element_hash]`:
   - exactly one match → replay it, rewriting `element_id` and `skyvern_element_data` from the
     *current* scrape;
   - **more than one match → `LOG.warning("Found multiple elements with the same hash, stop matching")` and break**;
   - zero matches → break.
3. Hash-less actions (`TERMINATE`, `COMPLETE`, `NULL_ACTION`, `SOLVE_CAPTCHA`, `WAIT`) must be the
   *first* action in a step, so the page is re-scraped after them.
4. `check_for_unsupported_actions()` — only `INPUT_TEXT`, `WAIT`, `CLICK`, `COMPLETE`,
   `DOWNLOAD_FILE` are cacheable at all, and only `INPUT_TEXT` is cacheable with a query.
5. `personalize_actions()` — actions carrying an `intention` get **an LLM round-trip at replay
   time** to re-fill the value.

**Read this as a list of what not to inherit.** Skyvern's replay still calls an LLM (step 5), still
has an escape hatch to the agent (step 1), and covers 5 of 30 action types. NetGent's zero-LLM
constraint means steps 1 and 5 must be replaced by compile-time parameter binding, and the "multiple
hash matches" case must become a *compile-time* error (disambiguate the selector when you have the
LLM) rather than a runtime bail-out.

## 1.7 Testability

Skyvern has ~888 pytest files, overwhelmingly **unit tests with fakes**, not browser-driving tests.
`tests/unit/` contains ~30 browser-layer files
(`test_real_browser_manager.py`, `test_real_browser_state_active_page.py`,
`test_browser_session_recording_artifacts.py`, `test_browser_session_download_artifacts.py`,
`test_dom_scrape_crash_guards.py`, `test_scrape_frame_decision.py`, `test_browser_engine.py`, …)
built from `unittest.mock.AsyncMock`/`MagicMock` and small hand-rolled fakes
(`tests/unit/_mcp_browser_fakes.py`).

The design that makes this possible is deliberate: `navigation.py` takes `NavigateFunc`,
`SettleFunc`, and `SleepFunc` as **parameters** so `navigate_with_retry` can be tested with plain
fakes, and `_navigation_hop_urls` duck-types `response.request.redirected_from` explicitly *"so the
shared helper stays decoupled from playwright and testable with plain fakes"*. Likewise
`validate_navigation_destination` is a pure function called via `asyncio.to_thread`.

There is essentially **no real-browser integration suite** in `webeye/`. That is a gap NetGent should
not copy — see browser-use below.

---

# Part 2 — browser-use `browser_use/`

browser-use drives **raw CDP** via `cdp-use`, with no Playwright at all. The *layering* is what
matters here, plus its instrumentation, which is a from-scratch reimplementation of things
Playwright gives away — an excellent enumeration of the cost of not using Playwright.

## 2.1 Module map

### `browser_use/browser/`

| File | LOC | What it does |
|---|---:|---|
| `session.py` | 4,133 | `BrowserSession` — the god object. Owns the `ResilientEventBus`, the `SessionManager`, the CDP root client, focus target, cached selector map. Handles `BrowserStartEvent`, `NavigateToUrlEvent`, `SwitchTabEvent`, `CloseTabEvent`, `Tab*Event`, `BrowserStopEvent` itself; everything else is a watchdog. `attach_all_watchdogs()` at `:1680`. |
| `session_manager.py` | 918 | **Single source of truth for targets and sessions**, driven by `Target.attachedToTarget` / `detachedFromTarget`. Also owns the **per-target `Page.lifecycleEvent` buffer** (`_lifecycle_events: dict[TargetID, deque]`, `:53`) fed by *one global handler* registered once on the root client — because `cdp-use`'s event registry is single-slot per CDP method. |
| `events.py` | 667 | ~40 `bubus.BaseEvent` subclasses. Every event carries `event_timeout` from `_get_timeout('TIMEOUT_<EventName>', default)` so **every timeout is env-overridable by name**. Ends with `_check_event_names_dont_overlap()`, an import-time assertion that no event name is a substring of another ("hand written in blood by a human! not LLM slop"). |
| `watchdog_base.py` | 321 | `BaseWatchdog` — see §2.2. |
| `profile.py` | 1,288 | `BrowserProfile`. `record_har_path` / `record_har_content` / `record_har_mode`, `record_video_dir` / `record_video_size` / `record_video_format` / `record_video_framerate`, `downloads_path`, `traces_dir` (**vestigial — grep shows it is only ever declared, never read**), `user_data_dir`, `storage_state`, `args`, `deterministic_rendering`, `cross_origin_iframes`, `max_iframes`, `max_iframe_depth`. |
| `video_recorder.py` | 141 | `VideoRecorderService` — decodes base64 PNG screencast frames with PIL, resizes, pads to a 16-px macroblock multiple, appends to an `imageio` h264 writer. Optional dep (`browser-use[video]`). |
| `views.py` / `chrome.py` / `demo_mode.py` / `python_highlights.py` / `_cdp_timeout.py` / `cloud/` | | `BrowserStateSummary`, `PageInfo`, `NetworkRequest`; Chrome launch args; demo overlay; PIL bounding-box drawing; CDP timeout wrapper; cloud browser. |

### `browser_use/browser/watchdogs/` (15 files)

| Watchdog | LISTENS_TO | Problem it solves |
|---|---|---|
| `default_action_watchdog.py` (3,746) | Click/Type/Scroll/GoBack/GoForward/Refresh/Wait/SendKeys/UploadFile/ScrollToText/ClickCoordinate | All actual interaction. |
| `dom_watchdog.py` (877) | `TabCreatedEvent`, `BrowserStateRequestEvent` | Builds the serialized DOM + screenshot + page info into a `BrowserStateSummary`. |
| `downloads_watchdog.py` (1,503) | BrowserLaunch, TabCreated, TabClosed, BrowserStateRequest, BrowserStopped, NavigationComplete | `Browser.setDownloadBehavior` + `Browser.downloadWillBegin` + `Browser.downloadProgress` + `Network.responseReceived` sniffing for downloadable content; PDF auto-download. |
| `har_recording_watchdog.py` (779) | BrowserConnected, BrowserStop | **Hand-written HAR 1.2 writer over the CDP Network domain.** §2.5. |
| `recording_watchdog.py` (223) | BrowserConnected, BrowserStop, AgentFocusChanged | CDP `Page.startScreencast` → `VideoRecorderService`. Re-targets the screencast when agent focus changes tabs. |
| `screenshot_watchdog.py` (88) | ScreenshotEvent | `Page.captureScreenshot`. |
| `local_browser_watchdog.py` (506) | BrowserLaunch, BrowserKill, BrowserStop | Spawns/kills the local Chrome subprocess. |
| `security_watchdog.py` (296) | NavigateToUrl, NavigationComplete, TabCreated | `allowed_domains` enforcement. |
| `storage_state_watchdog.py` (373) | BrowserConnected, BrowserStop, Save/LoadStorageState | Cookie+localStorage persistence; auto-save interval. |
| `aboutblank_watchdog.py` (259) | BrowserStop, BrowserStopped, TabCreated, TabClosed | Keeps a blank tab alive; DVD-screensaver animation. |
| `popups_watchdog.py` (145) | TabCreated | JS dialog auto-handling. |
| `permissions_watchdog.py` (43) | BrowserConnected | `Browser.grantPermissions`. |
| `captcha_watchdog.py` (207) | BrowserConnected, BrowserStopped | Listens for solver events from the browser proxy. |
| `crash_watchdog.py` (336) | — | **Commented out** in `attach_all_watchdogs` (`session.py:1704–1708`). |

### `browser_use/dom/`

| File | LOC | What it does |
|---|---:|---|
| `service.py` | 1,231 | `DomService`. `_get_all_trees(target_id)` fires four CDP calls concurrently with a 10 s `asyncio.wait` and per-task retry: `DOMSnapshot.captureSnapshot(computedStyles=REQUIRED_COMPUTED_STYLES, includePaintOrder=True, includeDOMRects=True)`, `DOM.getDocument(depth=-1, pierce=True)`, `Accessibility.getFullAXTree` per frame, and a device-pixel-ratio probe. Also a `Runtime.evaluate` with `includeCommandLineAPI=True` to call DevTools' `getEventListeners()` for click-listener detection, bounded at `_MAX_JS_CLICK_LISTENER_ELEMENTS = 100` and skipped entirely above 10k elements, with `DOM.describeNode` resolution batched at `_DESCRIBE_NODE_BATCH_SIZE = 20`. |
| `enhanced_snapshot.py` | 181 | `build_snapshot_lookup()` — flattens `DOMSnapshot` string-table indirection into `dict[backendNodeId, EnhancedSnapshotNode]`. `REQUIRED_COMPUTED_STYLES` is a deliberately tiny 10-property list ("prevents Chrome crashes on heavy sites"). Contains a 3,000× optimization note: converting `nodes['isClickable']['index']` from list to `set` took 20k-element pages from 5,925 ms to 2 ms. **CDP bounds are device pixels; divided by `device_pixel_ratio` to get CSS pixels.** |
| `serializer/serializer.py` | 1,332 | `DOMTreeSerializer.serialize_accessible_elements()` — 4 steps: simplify → paint-order removal → optimize (drop useless parents) → bbox containment filtering → assign indices. |
| `serializer/clickable_elements.py`, `paint_order.py`, `html_serializer.py`, `eval_serializer.py` | | `ClickableElementDetector`; `PaintOrderRemover`; the `[5]<input …>` LLM text format; the `[i_5] <input …>` eval format. |
| `views.py`, `utils.py`, `markdown_extractor.py` | | `EnhancedDOMTreeNode`, `SerializedDOMState`, `DOMSelectorMap`, `DOMInteractedElement`; markdown extraction. |

### `browser_use/actor/` and `browser_use/tools/`

`actor/` (`page.py` 565, `element.py` 1,182, `mouse.py` 152) is a **Playwright-shaped facade over
CDP**: `Page.goto/go_back/reload/evaluate/press/screenshot/set_viewport_size/get_elements_by_css_selector/get_element(backend_node_id)`,
`Element.click/fill/hover/focus/check/select_option/drag_to/get_attribute/get_bounding_box/screenshot/evaluate`,
`Mouse.click/move/down/up/scroll`. Its README is explicit about the differences that bite:
`get_elements_by_css_selector()` **returns immediately with no auto-waiting** (the single biggest
functional gap vs Playwright locators), `evaluate()` **must** use `(...args) => {}` form and always
returns a string, and there is no `element.submit()` / `dispatch_event()` / `get_property()`.

`tools/` is the **action registry**: `registry/service.py:291` `Registry.action(description,
param_model=None, domains=None, terminates_sequence=False)` is a decorator that normalizes the
function signature (`_normalize_action_function_signature`), builds a pydantic param model via
`create_model`, and stores a `RegisteredAction`. Special parameters are dependency-injected by name
from a fixed allow-list (`_get_special_param_types`: `browser_session`, `page_url`, `cdp_client`,
`page_extraction_llm`, `file_system`, `available_file_paths`, `has_sensitive_data`,
`extraction_schema`, `context`). `execute_action()` validates params against the model, then calls.
`tools/service.py` registers ~25 actions: `search`, `navigate`, `go_back`, `wait`, `click`, `input`,
`upload_file`, `switch`, `close`, `extract`, `search_page`, `find_elements`, `scroll`, `send_keys`,
`find_text`, `screenshot`, `save_as_pdf`, `dropdown_options`, `select_dropdown`, `write_file`,
`replace_file`, `read_file`, `evaluate`, `done`.

## 2.2 The watchdog / event system — what it actually solves

`BaseWatchdog` is a pydantic model with `event_bus: EventBus` and `browser_session: BrowserSession`,
`model_config = {extra: 'forbid', validate_assignment: False, revalidate_instances: 'never'}`.
`attach_to_session()` (`:243`) reflects over `dir(self)`, finds every `on_<EventName>` method, looks
up `<EventName>` in `browser_use.browser.events`, and registers it. Two class vars, `LISTENS_TO` and
`EMITS`, are *asserted* against the discovered handlers — a handler for an undeclared event is an
`AssertionError`; a declared event with no handler is a warning.

Registration wraps the handler in `make_unique_handler` (`:93`) which adds four things:

1. **A circuit breaker.** If `not browser_session.is_cdp_connected` and the event is not one of the
   eight `LIFECYCLE_EVENT_NAMES`, the handler is skipped — or, if `is_reconnecting`, it *waits* on
   `_reconnect_event` up to `RECONNECT_WAIT_TIMEOUT` and raises `ConnectionError` on failure. This
   is the fix for "every handler hangs on a dead WebSocket until its own timeout".
2. **Causality-aware debug logging** — walks `event_parent_id` two levels up to print
   `↲ triggered by on_X#1a2b ↲ under Y#3c4d`.
3. **CDP session repair on failure** — on any handler exception, tries
   `get_or_create_cdp_session(target_id=agent_focus_target_id, focus=True)` to re-establish the
   session, then **re-raises the original error with its traceback preserved**.
4. **Duplicate-registration detection** — handlers get a unique name
   `f'{WatchdogClass}.{handler}'` and a second registration raises `RuntimeError`.

`__del__` (`:293`) does "a bit of magic": cancels any private attribute named `*_task` or iterates
any `*_tasks` collection and cancels each.

**What the architecture buys, honestly assessed.** It solves a real problem: ~15 independent
concerns (downloads, storage, security, video, HAR, permissions, popups, crash recovery) each need to
observe browser lifecycle without knowing about each other, and each needs its own timeout and
failure isolation. Declaring `record_har_path` and having a HAR watchdog materialize
(`session.py:1817–1820`) is genuinely nice.

The costs are equally real and visible in the source: `session.py:1680–1829` is 150 lines of manual
`Watchdog.model_rebuild(); self._x = Watchdog(...); self._x.attach_to_session()` with ~25 lines of
commented-out `event_bus.on(...)` calls left behind from the pre-reflection era; the handler
discovery is name-based reflection with runtime assertions instead of static typing; `CrashWatchdog`
is instantiated-then-commented-out; and `BaseWatchdog.__del__` cancelling attributes by name suffix
is the kind of thing you write when ownership is unclear.

**For NetGent:** the *ideas* worth taking are (a) capture components declared by config and attached
independently, (b) per-event named, env-overridable timeouts, (c) a connection circuit-breaker in
front of every handler. The *implementation* — a reflective pub/sub bus — is overkill for a
deterministic NFA runner where the transition sequence is known at compile time. A plain list of
"capture plugins" with explicit `on_start` / `on_navigate` / `on_stop` hooks gets you (a) and (c) at
a fraction of the complexity.

## 2.3 DOM / observation pipeline

`BrowserStateRequestEvent` → `DOMWatchdog.on_BrowserStateRequestEvent` (`dom_watchdog.py:244`):

1. Skip DOM build entirely for non-`http(s)` URLs.
2. `_get_pending_network_requests()` (`:93`) — an injected JS snippet using
   `performance.getEntriesByType('resource')`, treating `entry.responseEnd === 0` as pending, then
   filtering by a **hardcoded ad/tracking domain list** (`doubleclick.net`, `googletagmanager.com`,
   `hotjar.com`, `segment.com`, `newrelic.com`, `/beacon/`, `/telemetry/`, …), skipping anything
   loading >10 s, and skipping images/fonts loading >3 s. Wrapped in
   `asyncio.wait_for(..., timeout=2.0)` because on slow CI it could hang 15 s+.
3. If pending requests exist → `asyncio.sleep(0.3)`.
4. Build DOM + screenshot concurrently, each with its own budget
   (`asyncio.wait_for(screenshot_task, remaining_screenshot_budget)`), title at 1.0 s, page info at
   1.0 s. **On DOM failure it falls back to the previous cached state**; tests
   (`test_dom_listener_detection.py`) pin that behavior.

**Element index stability — `selector_index` *is* the CDP `backendNodeId`.**
`_allocate_selector_index` (`serializer.py:645`):

```python
def _allocate_selector_index(self, backend_node_id: int) -> int:
    if backend_node_id not in self._selector_map:
        return backend_node_id                      # identity, not a counter
    while self._next_synthetic_index in self._reserved_backend_node_ids:
        self._next_synthetic_index += 1
    selector_index = self._next_synthetic_index      # collision → synthetic
    self._next_synthetic_index += 1
    return selector_index
```

`_reserve_backend_node_ids()` walks the whole tree first so synthetic indices can never collide with
a real backend id. Collisions happen because **OOPIFs are separate CDP sessions with independent
backendNodeId spaces** — `tests/ci/browser/test_dom_selector_index_collisions.py` builds exactly
that case (`backend_node_id=5` in session `main` and session `iframe`) and asserts
`list(selector_map) == [5, 101]`. Node identity is therefore the **pair** `(session_id, backend_node_id)`:
`BrowserSession._get_cached_node_by_backend_id(backend_node_id, session_id)` and
`_previous_node_ids = {(str(n.session_id), n.backend_node_id) …}` for `is_new` marking
(`serializer.py:72–79`, `:758–762`).

`backendNodeId` is stable for a node's lifetime within a document but **does not survive
navigation**, so browser-use's indices are stable within a page and meaningless across one. There is
no cross-load content hash — `DOMInteractedElement` exists for history replay, but
`test_dom_selector_index_collisions.py::test_history_remapping_prefers_the_original_frame` shows
remapping is frame-preference-based, not hash-based. **Skyvern's `skyvern_element_hash` is the
better primitive for NetGent.**

**Injected JS.** browser-use injects far less than Skyvern: the pending-request probe, the iframe
scroll-position probe, the `getEventListeners()` click-listener probe, and highlight overlays. The
heavy lifting is done by CDP domains (`DOMSnapshot`, `DOM`, `Accessibility`) rather than page JS.

## 2.4 Waiting / synchronization

`BrowserSession._navigate_and_wait()` (`session.py:1008`) is the core, and it is a good design:

- **Adaptive default timeout** (`:1030–1038`): `3.0 s` if the target URL is same-domain as the
  current URL, else `8.0 s`.
- `Page.navigate` itself is wrapped in `asyncio.wait_for(..., nav_timeout or 20.0)` "heavy sites can
  block here for 10s+".
- **`wait_until` is a floor, not an equality**: `acceptable_events = {'networkIdle'}`, plus `'load'`
  for `load`/`domcontentloaded`, plus `'DOMContentLoaded'` for `domcontentloaded`. A higher signal
  always satisfies a lower request.
- **Stale-event rejection**: `Page.navigate` returns a `loaderId`; lifecycle events carrying a
  different `loaderId` are skipped, and events with no `loaderId` are only trusted if their
  `timestamp >= nav_start_time`.
- **Same-document navigations short-circuit**: no `loaderId` in the `Page.navigate` result means a
  fragment/History-API navigation that is already committed and will emit no new lifecycle events —
  returning immediately instead of burning the timeout.
- **A timeout is reported, not swallowed**: returns `f'timeout after {timeout}s waiting for {wait_until!r} (saw: …)'`,
  surfaced as `NavigationCompleteEvent.loading_status`. A distinct message for "no lifecycle events
  received at all" flags a monitoring failure.

Everything else is per-event `event_timeout` on the bus, overridable via
`TIMEOUT_<EventName>` env vars.

Two hard-won architectural facts, both recorded in the tests:

- `cdp-use`'s event registry is **single-slot per CDP method**. A per-session
  `Page.lifecycleEvent` closure replaces the previous one, so only the most recently attached target
  recorded events — every earlier tab burned its full readiness timeout. Fixed by moving the buffer
  into `SessionManager` behind **one** global handler (`session_manager.py:49–53, :112–132`).
- `Network.enable` must be sent per session/target, and `page.on` being synchronous makes the
  enable-vs-navigate race silent (Skyvern's `skycdp/facade/network_events.py` docstring documents the
  same trap).

## 2.5 Instrumentation — exactly how browser-use captures

### Network → HAR, hand-written

`HarRecordingWatchdog` (`watchdogs/har_recording_watchdog.py`, 779 lines) is a from-scratch HAR 1.2
writer. On `BrowserConnectedEvent` (only if `profile.record_har_path`):

```python
cdp_session = await self.browser_session.get_or_create_cdp_session()
await cdp_session.cdp_client.send.Network.enable(session_id=cdp_session.session_id)
await cdp_session.cdp_client.send.Page.enable(session_id=cdp_session.session_id)
cdp = self.browser_session.cdp_client.register
cdp.Network.requestWillBeSent(...); cdp.Network.responseReceived(...); cdp.Network.dataReceived(...)
cdp.Network.loadingFinished(...); cdp.Network.loadingFailed(...)
cdp.Page.lifecycleEvent(...);      cdp.Page.frameNavigated(...)
```

Per request it accumulates a `_HarEntryBuilder` (URL, method, headers, `postData`, status, response
headers, MIME, `encodedDataLength`, `remoteIPAddress`/`remotePort`, `securityDetails`, protocol
normalized to `HTTP/1.1|HTTP/2.0`). On `loadingFinished` it **fires `Network.getResponseBody` as a
detached `asyncio.create_task`** (`:413`). On `BrowserStopEvent` it writes the HAR atomically
(`.tmp` → `replace`), honoring `record_har_content` (`embed` inline / `attach` to a
`{stem}_har_parts/` sidecar with sha1-named files / `omit`) and `record_har_mode`
(`minimal` = same-origin-as-page-document only).

**Its limitations are the interesting part, and every one is a trap NetGent could fall into:**

| Limitation | Where | Consequence |
|---|---|---|
| **HTTPS only** — `if not _is_https(url): return` | `:214`, `_include_entry:689` | Every plain-HTTP request is silently dropped. Fatal for a local-testbed traffic dataset. |
| **Favicons filtered** to match Playwright | `:692` | Minor, but a silent omission. |
| **DNS / connect / SSL / send timings are hardcoded `0`** | `_compute_timings:717–733` | Only `wait` (request→response) and `receive` (response→finished) are real. "CDP doesn't provide this breakdown directly" — true of `Network.*`; `Network.responseReceivedExtraInfo` and the `timing` field on `Response` do carry more. |
| **Body fetch is fire-and-forget** | `:413` `_asyncio.create_task(_fetch_body(...))` with a bare `except: pass` | On `BrowserStopEvent` the writer reads `entry.response_body` with no barrier against in-flight fetches. Late or failed fetches fall back to `encoded_data` (accumulated from `dataReceived`, which carries only *lengths*, not bytes — `params.get('data')` is `.encode('latin1')`'d, which is not the body). Bodies can be silently empty or wrong. |
| **`Network.enable` sent to one session only** | `:172–174` | Requests from other targets/OOPIFs/tabs are not enabled, even though the *handlers* are registered on the root client. Multi-tab and cross-origin-iframe traffic is under-captured. |
| **`postData` is whatever `requestWillBeSent` carries** | `:224` | CDP truncates large bodies and sets `hasPostData` instead; `Network.getRequestPostData` is never called. Large POSTs lose their body. |
| **No WebSocket capture** | — | `Network.webSocket*` events are not registered at all. |
| **HAR written only on `BrowserStopEvent`** | `:200` | A crash loses everything; nothing is streamed. |

### Video → CDP screencast

`RecordingWatchdog` (`watchdogs/recording_watchdog.py`) starts `Page.startScreencast(format='png',
quality=90, maxWidth/maxHeight=viewport, everyNthFrame=1)` on the focused session, registers
`Page.screencastFrame`, and **acks every frame** (`Page.screencastFrameAck`) as a detached task —
Chrome throttles until acked. On `AgentFocusChangedEvent` it stops the old session's screencast and
starts one on the new target, so the video follows the agent across tabs. Viewport size comes from
`Page.getLayoutMetrics().cssVisualViewport`.

`VideoRecorderService` decodes each base64 PNG with PIL, resizes to the target viewport (BICUBIC,
"faster than LANCZOS and good enough"), pads to a 16-px macroblock multiple with black bars, and
appends the numpy array to an `imageio` h264/yuv420p writer.

**Fidelity caveat:** CDP screencast is *frame-on-change*, not fixed-rate. The writer is opened at a
fixed `fps` (default 30) and frames are appended one-per-event, so **wall-clock timing is not
preserved** — a page idle for 10 s contributes ~0 frames, and playback speed is arbitrary. Skyvern's
Playwright `record_video_dir` + ffprobe-duration + `plan_run_segment` approach preserves the
timeline; this one does not.

### Downloads

`DownloadsWatchdog` sends `Browser.setDownloadBehavior` and registers `Browser.downloadWillBegin` +
`Browser.downloadProgress` (`:507–517`), plus `Network.responseReceived` sniffing for downloadable
content types (`:718`, with its own `Network.enable` at `:726` — a *second*, independent enable).
`DefaultActionWatchdog._execute_click_with_download_detection()` (`:44`) wraps every click: wait
0.5 s for a `downloadWillBegin`, then up to 30 s for completion, correlating by CDP download `guid`,
and returns `download_in_progress` metadata rather than hanging if it times out.

### Storage / console / tracing

`StorageStateWatchdog` persists cookies + localStorage (`_cdp_get_origins` walks the frame tree and
runs per-origin `Runtime.evaluate` for localStorage). There is no console-log capture watchdog.
`traces_dir` on the profile is dead code.

## 2.6 Testability — `tests/ci/browser/`, concretely

This is the part NetGent should copy most directly.

**~100 files in `tests/ci/`, one CI job per file.** 20 of them under `tests/ci/browser/`
(4,289 LOC): `test_navigation.py` (396), `test_tabs.py` (671), `test_dom_serializer.py` (585),
`test_session_start.py` (436), `test_dom_selector_index_collisions.py` (241),
`test_dom_listener_detection.py` (225), `test_output_paths.py` (219), `test_cdp_headers.py` (177),
`test_screenshot.py` (163), `test_navigation_slow_pages.py` (188), `test_navigation_readiness.py` (139),
`test_cross_origin_click.py` (138), `test_true_cross_origin_click.py` (136),
`test_dom_serializer_session_identity.py` (140), `test_proxy.py` (113), `test_profile_copy.py` (63),
plus three HTML fixture templates (`test_page_template.html`, `test_page_stacked_template.html`,
`iframe_template.html`).

**The `pytest-httpserver` pattern.** `tests/ci/conftest.py` does two things at import time:

```python
socketserver.ThreadingMixIn.block_on_close = False   # httpserver hangs on shutdown otherwise
socketserver.ThreadingMixIn.daemon_threads = True
```

Then every test takes the plugin's function-scoped `httpserver` fixture and declares its routes
inline:

```python
async def test_navigation_detects_readiness_without_burning_timeout(httpserver, browser_session):
    httpserver.expect_request('/fast').respond_with_data(SIMPLE_HTML, content_type='text/html')
    start = time.monotonic()
    await browser_session.navigate_to(httpserver.url_for('/fast'))
    assert time.monotonic() - start < FAST_NAVIGATION_BOUND_S
```

Four idioms carry the suite:

1. **`respond_with_data(html, content_type='text/html')`** for static pages. `test_dom_serializer.py`
   uses a *session*-scoped `HTTPServer()` started manually and serves three HTML files read from
   disk, so complex DOM fixtures live as real `.html` files you can open in a browser.
2. **`respond_with_handler(fn)`** to inject latency deterministically. The best example:

   ```python
   def slow_image(request):
       time.sleep(5)
       return Response(b'', content_type='image/png')

   httpserver.expect_request('/hanging').respond_with_data(
       '<html><body><img src="/slow-img">never finishes loading</body></html>', content_type='text/html')
   httpserver.expect_request('/slow-img').respond_with_handler(slow_image)

   status = await browser_session._navigate_and_wait(url, target_id, timeout=1.0, wait_until='load')
   assert status is not None and 'timeout' in status
   ```

   `DOMContentLoaded` fires immediately; `load` is held hostage by the stalled subresource. That is a
   readiness-semantics test you cannot write against a live site.
3. **`expect_ordered_request` in a loop** to allow N hits on the same path
   (`test_output_paths.py:24` registers `/` ten times).
4. **Timing assertions as the actual regression check.** `test_navigation_readiness.py` asserts
   `elapsed < 2.5 s` where the pre-fix path burned the 3 s / 8 s fallback. The docstring names the
   root cause (`cdp-use`'s single-slot event registry) — the test *is* the documentation.

**Mock-LLM harness.** `conftest.create_mock_llm(actions: list[str] | None)` returns an
`AsyncMock(spec=BaseChatModel)` that yields a caller-supplied list of JSON action blobs in sequence
and then a `done` action. `test_output_paths.py` scripts a 5-step navigate→click→type→click→done
trajectory as literal JSON. **For NetGent this is directly reusable: it is exactly how you drive a
fixed transition sequence through an agent-shaped API without an LLM.**

**Pure-unit serializer tests.** `test_dom_selector_index_collisions.py` never starts a browser: a
`_node(...)` factory builds `EnhancedDOMTreeNode`s by hand and feeds them to
`DOMTreeSerializer(...).serialize_accessible_elements()`. Index-allocation, session identity,
highlight labelling, and pagination metadata are all tested this way, with `monkeypatch` for the few
CDP touch-points. Fast, deterministic, no browser.

**Cross-origin coverage is real.** `test_cross_origin_click.py` uses two `httpserver` paths (same
origin, different frame); `test_true_cross_origin_click.py` embeds an actual
`<iframe src="https://example.com">` with `cross_origin_iframes=True`, which is the only way to
exercise real OOPIF target switching.

---

# Part 3 — What a Playwright-only framework gets for free, and where it stops

Verified against installed `playwright==1.58.0`.

## 3.1 HAR recording — `browser.new_context(...)` / `browser_type.launch_persistent_context(...)`

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `record_har_path` | `str \| Path` | — | Enables HAR for **all pages in the context**. |
| `record_har_content` | `"omit" \| "embed" \| "attach"` | see below | `attach` writes bodies to separate files archived alongside. |
| `record_har_mode` | `"full" \| "minimal"` | `"full"` | `minimal` omits sizes, timings, page, cookies, security — routing data only. |
| `record_har_omit_content` | `bool` | `False` | Legacy; equivalent to `content="omit"`. |
| `record_har_url_filter` | `str \| Pattern` | — | Glob or regex; entries outside it are not recorded. |

**Undocumented-on-the-docs-site but visible in `_impl/_browser_context.py:303–325`:** the default
content policy depends on the *filename extension* —

```python
default_policy = "attach" if record_har_path.endswith(".zip") else "embed"
content_policy = record_har_content or ("omit" if record_har_omit_content is True else default_policy)
```

So `record_har_path="out.har"` embeds bodies as base64/text inline; `record_har_path="out.zip"`
attaches them as separate files inside the zip. **For a traffic dataset, `.zip` + `attach` is
almost certainly what you want** — it keeps large binary bodies out of a single giant JSON and gives
you content-addressable files.

**What HAR gives you:** full request/response lines, headers, cookies, `postData`, response content
(subject to `content` mode), sizes, `serverIPAddress`, `_securityDetails` (TLS), timings, and page
grouping. It's written by the Playwright **driver** (Node), not by your Python process, so it doesn't
compete with your event loop.

**What HAR does not give you:**

- **No WebSocket frames.** Long-standing gap; Chrome's own DevTools HAR export has a
  `_webSocketMessages` field, Playwright's does not. Feature requests
  [#17838](https://github.com/microsoft/playwright/issues/17838) (closed),
  [#17848](https://github.com/microsoft/playwright/issues/17848),
  [#30315](https://github.com/microsoft/playwright/issues/30315). **Workaround:**
  `page.on("websocket")` → `ws.on("framesent"/"framereceived")` (`WebSocket` class exists in
  `async_api/_generated.py:981` with both events), or `context.route_web_socket()` (`:13361`) for
  interception. You must merge these into the HAR yourself.
- **No packet-level detail.** HAR is application-layer. No TCP/TLS handshakes, no retransmits, no
  per-packet timing, no DNS queries, no QUIC frames. **If NetGent's dataset is meant to be
  pcap-realistic, HAR cannot be the only capture** — you need a real packet capture
  (tcpdump/tshark) alongside, plus `SSLKEYLOGFILE` if you want to decrypt it. Chromium honors
  `SSLKEYLOGFILE`; you can set it in the launch `env`.
- **No media-stream detail.** MSE/HLS/DASH segment requests appear as ordinary HTTP entries, but
  WebRTC (SRTP over UDP) is entirely invisible to HAR.
- **HAR is flushed on `context.close()`.** A killed process loses the file. (Skyvern hits the mirror
  of this problem for video and fixes it with an ffmpeg remux; there is no equivalent HAR repair.)
- **Not settable after context creation.** `_initialize_har_from_options` runs during context
  construction. There is no "start HAR now" on an existing context — you must own every context
  constructor (this is exactly the bug in Skyvern's `cdp-connect` path, §1.5).
- **Service-worker and extension traffic** is not reliably attributed.

## 3.2 HAR replay — `context.route_from_har()` / `page.route_from_har()`

`async_api/_generated.py:13430` (context) and `:9660` (page). Parameters: `har`, `url` (glob/regex),
`not_found` (`"abort" | "fallback"`, default abort), `update` (bool), `update_content`
(`"embed" | "attach"`), `update_mode` (`"full" | "minimal"`, default minimal when updating).
Implementation in `_impl/_har_router.py` — `harOpen` on the driver's local-utils channel, then each
route is looked up via `harLookup`.

**This is directly relevant to NetGent**: a compiled workflow can ship with a recorded HAR and replay
against it hermetically (`not_found="abort"` makes any un-recorded request a hard failure — a
perfect determinism check), or run in `update=True` mode to refresh the recording. It's the cheapest
possible "did the site change under us" detector.

## 3.3 Tracing — `context.tracing`

`Tracing.start(name=, title=, snapshots=, screenshots=, sources=)`, `start_chunk(title=, name=)`,
`stop_chunk(path=)`, `stop(path=)`, plus `group(...)`/`group_end()` for labelled sections
(`_generated.py:15142–15310`). `tracesDir` is set on `browser_type.launch()`.

Per the in-package docstring, `snapshots=True` captures a **DOM snapshot on every action** and
**records network activity**. The trace is a zip consumed by the Trace Viewer.

**Assessment for NetGent:** tracing is a *debugging* artifact, not a dataset artifact. Its network
record is not HAR-shaped and is not a documented stable format; it's tied to the viewer. There is no
`Tracing.start_har()` in 1.58 (the docs-site summarizer invented one — do not build on it). Use
tracing for developer triage of a failed replay; use HAR for the dataset. `start_chunk`/`stop_chunk`
is the natural per-NFA-transition boundary if you do want traces.

## 3.4 CDP access from Playwright Python

`browser_context.new_cdp_session(page_or_frame)` (`_generated.py:13670`) returns a `CDPSession` with
`send(method, params)`, `on(event, handler)`, `detach()`. Also `browser.new_browser_cdp_session()`
for browser-scoped domains (this is how Skyvern sends `Browser.setDownloadBehavior`,
`browser_factory.py:533`). Chromium only. Works over `connect_over_cdp` (Skyvern's entire
`cdp-connect` path depends on it).

**Limits that matter:**

- A `CDPSession` is bound to **one page/frame target**. `Network.enable` on it covers that target
  only — the exact under-capture bug in browser-use's HAR watchdog. For a multi-tab or OOPIF-heavy
  workflow you must open a session per target, driven by `Target.attachedToTarget`
  (which is why browser-use needed `SessionManager` at all).
- CDP events fire on Playwright's event loop, so a chatty domain competes with your driving code —
  Skyvern measured `Network.enable` at **+127 ms on a single `goto`**.
- Mixing CDP interception with Playwright's `context.route()` is asking for trouble: both pause
  requests, and a request answered twice (or not at all) hangs the page silently. Pick one.
- `Network.getResponseBody` only works after `loadingFinished`, only while Chrome still holds the
  body, and never for bodies Chrome discarded.

## 3.5 `expose_binding` / `expose_function` / `add_init_script`

`page.expose_binding` (`:8845`) and `context.expose_binding` (`:13122`) install a JS function that
calls back into Python with a `source` dict (`page`, `frame`, `context`). Skyvern's
`transient_page_observer.py:137` uses it with a MutationObserver to capture toast/error text that
would vanish before the next observation — a genuinely good pattern for NetGent, whose observations
are sparse by design (one per NFA transition, not one per LLM step).

`context.add_init_script(...)` runs before every document in every frame — the right place for
injected DOM-annotation JS, since it survives navigation without a re-inject race.

---

# Part 4 — Judgment

## Serves deterministic replay + network capture

| From | What | Why |
|---|---|---|
| Skyvern | **`skyvern_element_hash`** = sha256 of the element dict minus `id`/`rect`/`frame_index`/`unique_id` (`scraper/scraper.py:229`) | The only cross-page-load, cross-run element identity in either repo. This is NetGent's transition-target key. |
| Skyvern | **`hash_to_element_ids: dict[str, list[str]]`** | Ambiguity is *representable*, so it can be detected instead of silently resolving to the wrong element. |
| Skyvern | **Action data model separate from execution registry** (`actions/actions.py` vs `handler.py:3473`) | Makes an action list a durable, diffable, replayable artifact. |
| Skyvern | **setup/handler/teardown per action type** | The clean hook point for per-transition capture markers. |
| Skyvern | **`navigate_with_retry` progressive `wait_until` degradation** + pre-dispatch destination validation + post-hoc redirect-chain revalidation (`navigation.py`) | Bounded, deterministic, and testable with plain fakes. |
| Skyvern | **`wait_for_page_ready`** = loading-indicators → networkidle → MutationObserver DOM-stability, longest-timeout-first, all failures swallowed (`utils/page.py:1940`) | Explicitly built for the *cached/no-LLM* execution path — the exact regime NetGent lives in. |
| Skyvern | **`video_utils.py`** — webm remux repair, `plan_run_segment`, `cut_recording_segment` | Wall-clock-anchored per-run clips from a shared session recording. |
| Skyvern | **`mode="direct"`** on `SkyvernPage.click` (`skyvern_page.py:411`) | The pure-Playwright path that still records to the timeline. This is what every NetGent action should be. |
| Skyvern | **`BrowserEngineSelection.is_engine_timeout_error(exc)`** | Timeout classification that doesn't hardcode one driver's exception identity. |
| browser-use | **`_navigate_and_wait`** — adaptive same-domain timeout, `loaderId` staleness rejection, same-document short-circuit, timeout *reported* not swallowed (`session.py:1008`) | Best navigation-readiness logic in either repo. Port the semantics even though the CDP mechanics don't apply. |
| browser-use | **Per-event named, env-overridable timeouts** (`events.py:_get_timeout`) | Every timeout tunable by name without a code change. |
| browser-use | **`(session_id, backend_node_id)` as node identity**, synthetic-index collision avoidance (`serializer.py:645`) | The OOPIF collision is real and will bite any iframe-heavy workflow. |
| browser-use | **`REQUIRED_COMPUTED_STYLES`** — 10 properties, not 200 (`enhanced_snapshot.py:17`) | "Prevents Chrome crashes on heavy sites." Capture cost is a first-class constraint. |
| browser-use | **The entire `tests/ci/browser/` + `pytest-httpserver` pattern** | See §2.6. Adopt wholesale. |
| browser-use | **`_execute_click_with_download_detection`** (0.5 s start / 30 s complete, guid-correlated) | Bounded, non-hanging download detection around every click. |
| Playwright | **`record_har_path=".../x.zip"` + `record_har_content="attach"` + `record_har_mode="full"`** | Free, driver-side, out-of-process, content-addressed bodies. |
| Playwright | **`route_from_har(har, not_found="abort")`** | Hermetic replay + a free drift detector. |
| Playwright | **`add_init_script` + `expose_binding`** | Navigation-surviving DOM annotation; observation of transient state between sparse observations. |

## LLM-loop baggage NetGent does not need

- **`actions/parse_actions.py` (1,553 lines)** — LLM JSON → actions. Gone entirely.
- **`caching.py::personalize_actions` / `get_user_detail_answers`** — an LLM round-trip *at replay
  time* to re-fill values. Replace with compile-time parameter binding.
- **`caching.py`'s "fall back to no-cache mode"** everywhere. NetGent has nothing to fall back to; a
  hash miss must be a hard, loud failure with an artifact bundle, not a silent degrade.
- **Element-tree rendering for LLMs** — `json_to_html`, `build_economy_elements_tree`,
  `build_lean_elements_tree`, the 4-flag lean cache, `RESERVED_ATTRIBUTES`, `approx_count_tokens`,
  token-budget-driven screenshot reduction (`scraper.py:570–572`), href hashing to save tokens. All
  of it exists to fit a page into a context window.
- **Scrolling split screenshots** (`take_split_screenshots`, `_merge_images_by_position`) — a
  vision-model input. Keep *one* post-action screenshot for the artifact bundle; drop the stitching.
- **`dialog_handler.py`'s LLM decision path** — replace with a compiled per-dialog policy
  (`accept`/`dismiss`/`accept_with_text`) recorded at compile time. Keep the structure: the
  `_registered_contexts`/`_registered_pages` `WeakSet` dedup and the single `_respond` chokepoint are
  both correct.
- **`browser-use/tools/` action registry with pydantic-model-per-action + LLM-facing descriptions,
  `done`/`extract`/`search`/`write_file`/`read_file`** — agent affordances, not automation
  primitives.
- **browser-use's `is_new` node marking, `ClickableElementDetector`, paint-order removal, bbox
  containment filtering, `getEventListeners()` probing** — all exist to decide *what to show a
  model*. NetGent knows its target at compile time; it needs *resolve and verify*, not *discover*.
- **`markdown_extractor.py`, `dom/playground/`, `demo_mode.py`, `python_highlights.py`,
  highlight overlays** — demo/observability for a human watching an agent.
- **The `bubus` event bus itself** — see §2.2. The problems it solves (independent capture
  components, connection circuit-breaking, per-handler timeouts) are real; a reflective pub/sub bus is
  not the minimum solution for a runner whose transition order is known at compile time.
- **`skyvern/webeye/skycdp/` (~2,300 lines)** — a from-scratch Playwright-shaped CDP driver. Read the
  `network.py` and `network_events.py` docstrings for the traps, then never build this.
- **CAPTCHA solving, TOTP handling, credential vaults, proxy-session headers, `attach_only` /
  compliance degrade paths** — product surface.

---

# Lessons for NetGent v2

**1. Make capture a construction-time contract, and let exactly one code path build a context.**
Playwright's HAR/video are `new_context()` options — they cannot be turned on later. Skyvern proves
the failure mode: `browser_factory.py:1206` records `har_path` on the artifacts while `:1254` never
passes `record_har_path` to `new_context`, so on `cdp-connect` the HAR silently doesn't exist and
`get_har_data` returns `b""` with a warning nobody reads. Give NetGent one `BrowserFactory.create()`
that returns `(context, CaptureBundle, cleanup)` where `CaptureBundle` holds the *actual* paths the
context was constructed with, and **assert at run start that every declared capture is live** — an
enabled-but-absent capture must abort the run, not warn.

**2. Default to `record_har_path=".../run.zip"`, `record_har_content="attach"`,
`record_har_mode="full"`.** The `.zip` extension flips Playwright's internal default to `attach`
(`_impl/_browser_context.py:314`), giving content-addressed body files instead of a multi-hundred-MB
JSON. `full` keeps sizes, timings, cookies, and `_securityDetails` — all of which a traffic dataset
wants and `minimal` throws away. Never set `record_har_url_filter` for dataset runs.

**3. HAR is not sufficient for "realistic network traffic" — say so in the spec and plan the
supplements now.** HAR is application-layer only. It has **no WebSocket frames**
([#17838](https://github.com/microsoft/playwright/issues/17838),
[#30315](https://github.com/microsoft/playwright/issues/30315)), no TCP/TLS/QUIC detail, no DNS, no
WebRTC. Three supplements, in priority order: (a) `page.on("websocket")` +
`ws.on("framesent"/"framereceived")` into a sidecar JSONL merged post-run — cheap and pure
Playwright; (b) `SSLKEYLOGFILE` in the Chromium launch `env` plus a `tshark`/`tcpdump` sidecar if you
need packet-level ground truth — this is the only path to pcap realism; (c) a `CDPSession` on
`Network.responseReceivedExtraInfo` if you want the DNS/connect/SSL timing breakdown that browser-use
had to hardcode to `0` (`har_recording_watchdog.py:717–733`). Write the HAR + WS + pcap correlation
key (request URL + `wallTime`) into the design *before* implementing, or you will never be able to
join them.

**4. Element identity = a content hash, computed at compile time, verified at run time. Ambiguity is
a compile-time error.** Adopt Skyvern's `hash_element` (`sha256` of the element dict with `id`,
`rect`, `frame_index`, and the injected id attribute stripped) and its
`hash_to_element_ids: dict[str, list[str]]` shape so collisions are representable. But invert the
policy: Skyvern *discovers* a multi-match at run time and bails
(`caching.py:96`); NetGent should detect it **while the LLM is still available at compile time** and
either disambiguate (add an ancestor path or an `nth` to the hash input) or refuse to emit the
transition. At run time, a hash miss or a multi-match is a hard failure with a full artifact bundle.
Additionally, use `(frame_identity, backend_node_id)`-style scoping like browser-use
(`serializer.py:645`, `test_dom_selector_index_collisions.py`) — OOPIF backend-id collisions are real
and will silently target the wrong element in an iframe-heavy workflow.

**5. Steal `wait_for_page_ready` and `_navigate_and_wait` wholesale; they are the deterministic
half.** Readiness: `_wait_for_loading_indicators_gone` → `wait_for_load_state("networkidle")` →
MutationObserver DOM-stability, each independently timed, longest-timeout-first, every failure
swallowed and *recorded* (`utils/page.py:1940`). It is not an accident that Skyvern built this
specifically for its cached/no-LLM path. Navigation: adaptive 3 s same-domain / 8 s cross-domain
default, `wait_until` treated as a floor not an equality, and — crucially — **a readiness timeout
returned as a status string rather than swallowed** (`session.py:1121–1129`). For NetGent, that
status is the difference between "the transition fired late" and "the transition fired against a
half-loaded page", which is the difference between a good dataset row and a corrupt one. Also take
the progressive `load → domcontentloaded → commit` degradation from `navigation.py:97`.

**6. Structure actions as `(data model) × (registry) × (setup/handler/teardown)`.** Skyvern's
`ActionHandler.register_action_type` + `register_setup_for_action_type` +
`register_teardown_for_action_type` (`handler.py:3489–3518`) with handlers typed
`(action, page, scraped_page, task, step) -> list[ActionResult]` maps directly onto NFA transition
labels. Wrap every dispatch in `asyncio.timeout(per_action_type_budget)` and distinguish "my budget
expired" from "an inner call timed out" via `timeout_scope.expired()` (`:4427`). Use the
setup/teardown slots for capture markers — a monotonic timestamp + a HAR-joinable sequence number
written before and after every transition is what turns a HAR into a *labelled* dataset.

**7. Copy `tests/ci/browser/` almost verbatim.** `pytest-httpserver`, function-scoped, routes
declared inline in each test; `socketserver.ThreadingMixIn.block_on_close = False` +
`daemon_threads = True` in `conftest.py` or the servers hang on shutdown; complex DOM fixtures as
real `.html` files loaded by a session-scoped server (`test_dom_serializer.py`); `respond_with_handler`
with a `time.sleep` to make a subresource stall so `DOMContentLoaded` fires but `load` never does
(`test_navigation_readiness.py:85–95`) — that is how you test readiness semantics without a live
site; and **timing assertions as the regression check** (`assert elapsed < 2.5`) with the root cause
in the docstring. Add browser-use's `create_mock_llm(actions=[...])` idea as a *fixture that feeds a
fixed transition list*, and add pure-unit serializer/hash tests that never start a browser
(`test_dom_selector_index_collisions.py` builds `EnhancedDOMTreeNode`s by hand). Skyvern's ~888
mostly-mocked unit tests with essentially no real-browser browser-layer suite is the anti-pattern to
avoid — though its *testable-by-construction* design (`navigate_with_retry` taking
`NavigateFunc`/`SettleFunc`/`SleepFunc` as parameters) is worth copying exactly.

**8. Capture components: independent and config-declared, but not an event bus.** browser-use's
watchdogs get the shape right — declare `record_har_path` and a HAR component materializes
(`session.py:1817`), each with isolated failure and its own timeout. Take that, plus the circuit
breaker (`watchdog_base.py:98`: skip/wait when the connection is dead rather than hanging until
timeout) and per-component named env-overridable timeouts (`events.py:_get_timeout`). Do **not** take
the reflective pub/sub bus: `attach_all_watchdogs` is 150 lines of manual wiring with 25 lines of
commented-out legacy registration and a `CrashWatchdog` that is instantiated then commented out. A
`list[CapturePlugin]` with explicit `on_context_created` / `on_transition_start` /
`on_transition_end` / `on_run_end` hooks gives you the same isolation with static call graphs — which
matters a lot more when your execution order is fixed at compile time.

**9. Fire-and-forget capture tasks lose data; barrier before you write.** browser-use's HAR watchdog
schedules `Network.getResponseBody` as a detached `asyncio.create_task` with a bare `except: pass`
(`har_recording_watchdog.py:391–413`), then writes the HAR on `BrowserStopEvent` with no barrier — so
bodies are silently missing or fall back to `encoded_data`, which is accumulated from
`Network.dataReceived` and contains lengths, not bytes. If NetGent ever supplements HAR with CDP,
every capture task must be tracked in a set and drained under a deadline before the artifact is
written, and a drain timeout must be recorded in the manifest. Same lesson for video: Skyvern's
`_remux_webm` with `-cues_to_front 1` exists solely because a context killed mid-`close()` leaves an
unfinalized Matroska segment (`video_utils.py:154`, `:229`). **Assume the process dies at the worst
moment and make every artifact either atomically-written or repairable.**

**10. Budget the observation, and measure it.** `Network.enable` costs **+127 ms on a single `goto`**
(175 → 302 ms) — measured, in `skycdp/facade/network_events.py`'s docstring. browser-use trimmed
`DOMSnapshot` computed styles to 10 properties to stop crashing Chrome, caps click-listener probing
at 100 elements and skips it above 10k DOM nodes, and found a 3,000× win converting one CDP list to a
set (`enhanced_snapshot.py:87–90`). NetGent's advantage is that it needs *far less* observation than
either — one targeted element resolution per transition, not a full serialized tree — so the right
default is: **HAR via Playwright's out-of-process driver (near-zero in-process cost), no
`Network.enable` unless a WebSocket/timing supplement demands it, and DOM observation scoped to the
transition's target element.** Because capture cost distorts the timings in the dataset you are
producing, record the observation overhead per transition in the manifest so downstream consumers can
account for it.

**11. Ship a hermetic replay mode from day one.** `context.route_from_har(har, not_found="abort")`
turns a recorded run into a deterministic fixture where *any* un-recorded request is a hard failure —
the cheapest possible detector for "the site changed under the compiled workflow", and a way to run
the whole NFA suite in CI with no network. Pair it with `update=True` for a refresh path. This is
free, it is pure Playwright, and neither Skyvern nor browser-use uses it.

**12. Keep the Playwright escape hatch explicit and make it the default.** `SkyvernPage.click(...,
mode="direct")` (`skyvern_page.py:411`) — raw `locator.click(timeout=...)`, no fallback, no element
prep, still recorded to the timeline — is the shape of every NetGent run-time action. Skyvern's
`SkyvernPage.__getattribute__` forwarding (`:106`) lets the wrapper *be* a Playwright `Page` so
anything you didn't wrap still works; that is a good trick, but be aware it makes the wrapper's
surface implicit and untyped. Prefer explicit delegation with a documented list of what NetGent adds
on top of `Page`.

---

## Appendix — quick file index for follow-up reading

**Skyvern (highest value first):** `webeye/actions/caching.py` · `webeye/scraper/scraper.py:229-256`
(hashing) & `:487-701` (pipeline) · `webeye/navigation.py` · `webeye/utils/page.py:1900-2146`
(readiness) · `webeye/browser_factory.py:624-702` (capture args) & `:1191-1295` (the CDP HAR gap) ·
`webeye/video_utils.py` · `webeye/skycdp/facade/network_events.py` (docstring) ·
`webeye/actions/handler.py:3473-3520, 4334-4470` (registry + dispatch) ·
`core/script_generations/CLAUDE.md` & `skyvern_page.py:255-430`.

**browser-use:** `tests/ci/browser/test_navigation_readiness.py` · `tests/ci/conftest.py` ·
`tests/ci/browser/test_dom_selector_index_collisions.py` · `browser/session.py:1008-1130` ·
`browser/watchdogs/har_recording_watchdog.py` · `browser/watchdog_base.py` · `browser/events.py` ·
`dom/serializer/serializer.py:633-767` · `dom/enhanced_snapshot.py` · `actor/README.md`.

**Playwright (installed 1.58.0):** `_impl/_browser_context.py:303-325` (HAR default-policy logic) ·
`_impl/_har_router.py` · `async_api/_generated.py:13846-14061` (`new_context` capture params),
`:15142-15310` (`Tracing`), `:13430`/`:9660` (`route_from_har`), `:13361`/`:9593`
(`route_web_socket`), `:981-1060` (`WebSocket` frame events), `:13670` (`new_cdp_session`).
