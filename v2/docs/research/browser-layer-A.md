# Browser-Layer Deep Dive A — notte, Agent-E, LaVague

Source-level study of the browser layer in three Playwright-based agent frameworks, done to inform the
design of NetGent v2's browser layer (Playwright-only; `generate` compiles NL specs to an NFA using an
LLM, `run` replays the NFA with **zero** LLM calls; the product is realistic network-traffic datasets).

Everything below was read from shallow clones taken **2026-08-17**. Nothing is inferred from READMEs or
docs — where a repo *lacks* something (network capture, tests, iframe support), that is called out
explicitly rather than papered over.

| Repo | Commit read | Last commit date | Browser lib | Layout |
|---|---|---|---|---|
| [nottelabs/notte](https://github.com/nottelabs/notte) | `796ff3b` | 2026-08-14 | **patchright** 1.55 (playwright swappable) | uv monorepo, 6 packages |
| [EmergenceAI/Agent-E](https://github.com/EmergenceAI/Agent-E) | `f218c3c` | 2025-05-12 | playwright (async) | single `ae/` package |
| [lavague-ai/LaVague](https://github.com/lavague-ai/LaVague) | `9024bb8` | 2025-01-21 (**dormant**) | playwright (**sync**) + selenium | poetry monorepo, driver plugins |

Reading order below is roughly best→worst for our purposes. Short version up front:

- **notte** has the cleanest *lifecycle* decomposition and the one seam that matters most for a
  compile/replay split (`NodeResolutionPipe`), but its browser package is polluted with LLM pipelines.
- **Agent-E** has one genuinely clever trick (`mmid` smuggled through `aria-keyshortcuts`) and one
  genuinely good instinct (post-action DOM-mutation detection), inside an otherwise singleton-global
  design that should not be copied.
- **LaVague** is dormant and rough, but contains the single most NetGent-relevant idea in all three
  repos: every driver capability has a **do-it** form *and* an **emit-the-code-that-does-it** form,
  plus the best readiness predicate (`JS_WAIT_DOM_IDLE`) and the best test harness (local static server).

---

## 1. nottelabs/notte — `packages/notte-browser/`

`notte-browser` v1.4.4.dev, ~8k lines of Python across 50 files, depends on `notte_core` (types) and
`notte_llm` (model calls). Declared deps ([`packages/notte-browser/pyproject.toml`](https://github.com/nottelabs/notte/blob/main/packages/notte-browser/pyproject.toml)):
`patchright~=1.55`, `maincontentextractor`, `markdownify`, `pillow`, `tqdm`.

### 1.1 Module map

**Browser plumbing (3 files, the actual driver):**

| File | Lines | What it actually does |
|---|---|---|
| `playwright_async_api.py` | 100 | **Backend shim.** A top-level `match config.browser_backend` picks `playwright.async_api` or `patchright.async_api` and re-exports `Browser, BrowserContext, Page, Locator, CDPSession, FrameLocator, Response, TimeoutError, Error, async_playwright`. Also `getPlaywrightOrPatchrightTimeoutError()` / `...Error()` which return a *tuple* of both libs' exception classes for use in `except` clauses. Nothing else in the codebase imports playwright directly. |
| `playwright.py` | 179 | `PlaywrightManager(BaseModel, BaseWindowManager)` — owns the `Playwright` process. `astart`/`astop`, `create_playwright_browser(options)` (chromium/chrome launch, `options.get_chrome_args()`, 30 s creation timeout), `connect_cdp_browser(options)`, `get_browser_resource(options, browser)` (`new_context` with viewport / clipboard perms / proxy / UA / extra headers, then `context.pages[-1]` or `new_page()`), `new_window()` → `BrowserWindow` with an `on_close` closure that closes the browser then stops playwright. |
| `window.py` | 704 | `BrowserWindowOptions` (viewport & aspect-ratio defaulting, `get_chrome_args()`, `from_request(SessionStartRequest)`), `BrowserResource`, `ScreenshotMask`, and **`BrowserWindow`** — the real driving surface. `page` property self-heals to `context.pages[-1]` if the current page closed; CDP session cache keyed by `id(page)` with close-pruning; `goto`/`goto_and_wait` (3 tries, HTTP-status-aware, 407→`InvalidProxyError`); `long_wait`/`short_wait`; `snapshot()`; `screenshot()` (CDP fast path, 3 attempts × 10 s, falls back to Playwright screenshot when a mask is needed); `a11y()`; `snapshot_metadata()`; `set_cookies`/`get_cookies`; `is_file()`/`download_file()`. |

**Session & execution:**

| File | Lines | What it does |
|---|---|---|
| `session.py` | 1223 | `NotteSession(AsyncResource, SyncResource)` — the user-facing façade. Holds the window, a `BrowserController`, three LLM pipes, tools, vault, persona, a `Trajectory`, and `_snapshot`. `aobserve()` = snapshot → action listing → `Observation`. `aexecute()` = `parse_action` → `NodeResolutionPipe.forward` → vault substitution → `controller.execute` (wrapped in `asyncio.wait_for(timeout=action.timeout/1000)`) → `ExecutionResult` appended to the trajectory. Carries ~30 `@overload`s of `aexecute` — one per action TypedDict — purely for IDE/typing ergonomics. |
| `controller.py` | 525 | `BrowserController` — the raw executor, three methods. `execute()` dispatches on action class and afterwards, **only if `_can_create_tab(action)`**, short-waits and auto-switches to a newly opened tab. `execute_browser_action()` handles goto / goto_new_tab / switch_tab / close_tab / wait / back / forward / reload / press_key / scroll / form_fill / captcha. `execute_interaction_action()` handles click / fill / multi_factor_fill / fallback_fill / check / select_dropdown_option / upload_file / download_file. |
| `resolution.py` | 56 | `NodeResolutionPipe.forward(action, snapshot)` — **the compile/replay seam**, see §1.2. |
| `errors.py` | 379 | Typed error hierarchy + `capture_playwright_errors()` decorator (applied to `BrowserController.execute`) mapping raw Playwright exceptions into `InvalidLocatorRuntimeError` / `PlaywrightRuntimeError` / `NotteBaseError` with separate `dev_message` / `user_message` / `agent_message` fields. |

**DOM subsystem (`dom/`):**

| File | Lines | What it does |
|---|---|---|
| `buildDomNode.js` | 43 KB | The injected DOM walker (adapted from browser-use). Three `WeakMap` caches (`boundingRects`, `clientRects`, `computedStyles`) plus an `xpathCache`. Key predicates: `isInteractiveElement`, `isTopElement` (elementFromPoint + shadow-root-aware), `isInExpandedViewport(el, viewportExpansion)`, `isPointerElementWithHover` (walks *stylesheets* looking for `:hover` rules that set `cursor:pointer`), `getDisabledReason`, `isHeuristicallyInteractive`, `isElementDistinctInteraction`, `getXPathTree(el, stopAtBoundary=true)` (stops at shadow roots and iframes). Returns a flat `{map: {id: nodeData}, rootId}` with a monotonically increasing `highlightIndex` on interactive nodes. |
| `parsing.py` | 192 | `ParseDomTreePipe.forward(page)`: read the JS from disk → `page.evaluate(js, {highlight_elements, focus_element, viewport_expansion, enable_pointer_elements})` → `_reconstruct_dom_tree` (flat map → tree) → `_parse_node` building `DOMElementNode`s with `css_path` and **`notte_selector = ":".join([parent_notte_selector, str(hash(xpath)), str(hash(css_path))])`** (a URL-rooted structural fingerprint chain) → `generate_sequential_ids` → `to_notte_domnode()`. |
| `id_generation.py` | 41 | `generate_sequential_ids(root)` — iterative DFS (`stack.extend(reversed(children))`) assigning `B1, B2, I1, L1, …` = role short-id + per-role counter, **only** to nodes with `highlight_index is not None`. |
| `csspaths.py` | 157 | `xpath_to_css_path` + `build_csspath` — lifted verbatim from browser-use's `browser/context.py` (the comment says so on line 1). nth-of-type conversion, regex-validated class names, a `SAFE_ATTRIBUTES` allow-list (`id,name,type,placeholder,aria-*,role,for,autocomplete,alt,title,src,href,target` + `data-testid/-cy/-qa/-id`). |
| `locate.py` | 166 | `locate_element(page, selectors)` — **if `selectors.playwright_selector` is set, returns `page.locator(...)` immediately** (line 28-29, the replay fast path); otherwise descends `frame_locator(css)` per iframe ancestor, then tries each candidate from `selectors.selectors()` in order and returns the first whose `count() == 1`. Plus `selectors_through_shadow_dom(node)` (builds a `>>`-joined piercing locator) and `locate_file_upload_element(node)` (label→`for`, children ≤3 deep, siblings). |
| `dropdown_menu.py`, `../form_filling.py` | 163 / 651 | Heuristic custom-dropdown and form fillers (multi-selector field discovery, select handling). |

**LLM-facing pipelines, all *inside* the browser package:**
`tagging/` (action-space construction: `MainActionSpacePipe.with_perception("fast"|"deep")` → `SimpleActionSpacePipe`
pure-DOM vs `LlmActionSpacePipe` with listing/parser/validation retries; `tagging/type.py::NotteActionProxy.forward`
maps an id prefix + role to a concrete `InteractionAction` subclass), `rendering/` (DomNode → `interaction_only` /
`json` / `markdown` text, with `pruning.py` folding single-child chains and dropping hidden nodes), `scraping/`
(markdownify / main-content-extractor / image classification / structured LLM output), `action_selection/pipe.py`
(LLM filter of the action space given NL instructions), `tools/base.py` (`BaseTool` registry for email/SMS actions),
`captcha.py`, `vault.py` (`VaultSecretsScreenshotMask` blanks secrets out of screenshots),
`workflow_variables.py` (LLM pass that turns a recorded trajectory's literal values into named variables).

**Types consumed from `notte-core`:** `BrowserSnapshot`/`SnapshotMetadata`/`ViewportData`/`TabsData`
(`browser/snapshot.py`), `DomNode`/`InteractionDomNode`/`NodeSelectors`/`ComputedDomAttributes`/`A11yTree`
(`browser/dom_tree.py`, 815 lines), `NodeRole`/`NodeType` (`browser/node_type.py`), `Observation`/
`ExecutionResult`/`Screenshot`/`TimedSpan` (`browser/observation.py`), the action models
(`actions/actions.py`, 1375 lines), `ActionSpace` (`space.py`), `Trajectory` (`trajectory.py`), and the
global `config` (`common/config.py` + `config.toml`).

### 1.2 Boundaries

**Lifecycle → driving → semantics is a clean three-layer split**, and it's the best of the three repos:

```
PlaywrightManager  (owns the Playwright process; new_window())
  └── BrowserWindow   (owns context+page; goto/screenshot/snapshot/cookies/waits)
        └── NotteSession (owns semantics: observe/execute/scrape/trajectory)
```

`NotteSession.astart()` (session.py:207) constructs a `PlaywrightManager` per session and asks it for a
window; `astop()` closes the window and drops it. A caller can also inject a pre-built `BrowserWindow`
(`NotteSession(window=...)`), which is how remote/CDP sessions are attached.

**Action definitions vs execution are cleanly separated, and definitions are data.**
Definitions live in `notte-core/actions/actions.py`: pydantic models with `__init_subclass__` hooks that
auto-register into three class-level registries (`ACTION_REGISTRY`, `BROWSER_ACTION_REGISTRY`,
`INTERACTION_ACTION_REGISTRY`), and discriminated unions built from those registries at import time:

```python
BrowserActionUnion = Annotated[reduce(operator.or_, BrowserAction.BROWSER_ACTION_REGISTRY.values()),
                               Field(discriminator="type")]
```

Each action declares `type: Literal["click"]`, `category`, `description`, an `execution_message()`
(model-facing narration) and a `non_agent_fields()` set (what to hide from the LLM — notably `selector`,
`selectors`, `timeout`, `text_label`). `InteractionAction` adds `id`, `selector: str | NodeSelectors | None`,
`press_enter`, `timeout` (with a validator that rewrites `timeout=0` → default, because Playwright treats 0 as
infinite). A `field_validator(mode="before")` coerces a bare selector string into `NodeSelectors` via
`NodeSelectors.from_unique_selector()`, which sniffs the prefix (`xpath=`, `css=`, `internal:`, `~text`).

Execution lives in `controller.py` as one centralized `match` per action class — actions have no `.execute()`
method. Session-level pseudo-actions (`ScrapeAction`, `EvaluateJsAction`, `ToolAction`, `HelpAction`) are
intercepted in `session.py` *before* the controller and the controller explicitly no-ops them.

**The seam that matters: `NodeResolutionPipe`** (`resolution.py`, 56 lines) sits between parse and execute:

```python
if isinstance(action, BrowserAction): return action      # nothing to resolve
if action.selector is not None:      return action       # <-- REPLAY PATH: no snapshot needed
if snapshot is None:                 raise NoSnapshotObservedError()
selector_map = {inode.id: inode for inode in snapshot.interaction_nodes()}
if action.id not in selector_map:    raise InvalidActionError(...)
action.selector = await NodeResolutionPipe.resolve_selectors(selector_map[action.id], verbose)
```

That third line is the entire generate/run split in one branch: an action carrying a `selector` executes with
no observation, no DOM parse, and no LLM. Their own sample scripts exploit exactly this — `tests/scripts/sample_script.py`
and `tests/integration/test_basic_scripts.py` do
`page.aexecute(type="fill", selector='internal:role=combobox[name="Where to?"i]', value="paris")` with no
preceding `observe()`.

### 1.3 DOM / observation pipeline

`BrowserWindow.snapshot()` (window.py:504) produces a `BrowserSnapshot`:

1. `page.content()` (or `locator(selector).inner_html()` when scoped) → `html_content`
2. `screenshot()` → CDP `Page.captureScreenshot` (jpeg q85) or Playwright fallback
3. `dom_tree_parsers["default"].forward(page)` → `DomNode` tree (injected JS, see above)
4. `snapshot_metadata()` → title, url, and **six separate `page.evaluate` round-trips** for
   `scrollX/scrollY/innerWidth/innerHeight/scrollWidth/scrollHeight`, plus a `title()` per tab
5. If `is_file()` (checked from the retained navigation `Response`'s `content-type`), a synthetic
   `download_file` node is spliced in as child 0.

**`a11y_tree` is always `None`.** `BrowserWindow.a11y()` exists (double `page.accessibility.snapshot()`,
`interesting_only` both True and False) but `snapshot()` hard-codes `a11y_tree=None` (window.py:579). The
injected-JS DOM walker fully replaced the accessibility path.

**Element identity is three parallel handles per node:**

| Handle | Where computed | Stability |
|---|---|---|
| `B1` / `I2` / `L3` id | `dom/id_generation.py` DFS | **Per-snapshot only.** Re-derived every observe; a new element shifts every subsequent id. |
| `NodeSelectors` | `dom/parsing.py` + `csspaths.py` | `{css_selector, xpath_selector, playwright_selector, notte_selector, in_iframe, iframe_parent_css_selectors, in_shadow_root, python_selector}` — the durable handle. |
| `notte_selector` | `parsing.py:119` | `url:hash(xpath):hash(css):…` chained through ancestors. A structural fingerprint, not a locator. |

Notte is explicit about id instability. `NotteSession.previous_interaction_actions` returns `None` the moment
`self.snapshot.clean_url != last_observation.clean_url` ("the page has significantly changed"), and
`BrowserSnapshot.compare_with(other)` compares the *sets* of interaction-node ids to decide whether a page
changed under it. Durable replay therefore goes through `selector=`, effectively always a Playwright
`internal:role=…` selector.

### 1.4 Waiting / synchronization

Defaults from `packages/notte-core/src/notte_core/config.toml`:

```toml
timeout_goto_ms = 10000   timeout_default_ms = 8000   timeout_action_ms = 15000
timeout_evaluate_js_ms = 45000   wait_retry_snapshot_ms = 1000   wait_short_ms = 500
empty_page_max_retry = 5   viewport_expansion = 0   focus_element = -1
```

- `short_wait()` = `page.wait_for_timeout(500)`.
- `long_wait()` = `wait_for_load_state("networkidle", timeout=10s)` (timeout **swallowed** with a warning) + `short_wait()`.
- After any interaction action, `if original_url != window.page.url: await window.long_wait()` (controller.py:473).
- After a tab-creating action (`Click`/`Goto`/`GotoNewTab`/`PressKey` only — `_can_create_tab`), `short_wait()`
  then compare `len(context.pages)`; if it grew, `switch_tab(-1)` → `bring_to_front()` → `long_wait()`.
- `goto_and_wait` retries up to 3×, treating a `PlaywrightTimeoutError` as "long_wait then retry", and treats
  `page.url == "about:blank"` as "navigation silently didn't happen".
- Snapshot-level readiness: `snapshot()` recurses up to `empty_page_max_retry=5` with a 1 s wait whenever the
  DOM parse comes back empty; `_interaction_action_listing` (session.py:296) re-snapshots if >10 s elapsed
  since `snapshot.metadata.timestamp` and restarts the listing when `compare_with` shows the interaction set moved.
- Scroll verifies its own effect: reads `window.scrollY` before and after and raises `ScrollActionFailedError`
  if unchanged.

**There is no predicate/conditional wait anywhere.** A repo-wide grep for
`wait_for_selector|wait_for_function|wait_for_url|expect_` returns exactly four hits: one `wait_for_load_state`
in `long_wait`, and three `expect_file_chooser`/`expect_download` inside upload/download. The only wait *action*
is `WaitAction(time_ms)` — a fixed sleep. For NetGent's trigger concept there is nothing to borrow here.

### 1.5 Instrumentation

**No network capture of any kind.** Grepping `packages/` for
`record_har|record_video|tracing|Network.enable|page.route|context.route|Fetch.enable` returns **zero hits**.
The only CDP use is `Page.captureScreenshot` (window.py:399) and `Target.getTargetInfo` (window.py:326).
The one `page.on("response")` handler (window.py:210) exists solely to retain the last *navigation* response
so `is_file()` can read its `content-type`.

What does exist:

- **`Trajectory`** (`notte-core/trajectory.py`, 476 lines) — append-only list of
  `Observation | Screenshot | ExecutionResult | AgentCompletion`, grouped into steps by
  `AgentStepStart`/`AgentStepStop` markers, with per-type `set_callback` overloads, `step_iterator()`,
  `filter_by_type()`, `last_observation`/`last_result`, and `_view(start, stop)` slices.
- **`NotteSession.replay()`** → `ScreenshotReplay.from_bytes(...).get(quality=90)` → an animated WebP
  (`notte-core/utils/webp_replay.py`).
- **Profiling**: `@profiler.profiled(service_name="observation"|"execution")` sprinkled through window /
  controller / parsing, gated on `enable_profiling`; usage telemetry via `@track_usage("local.session.*")`.

### 1.6 Testability

- **Mocks**: `tests/mock/mock_browser.py` — `MockBrowserDriver` / `MockBrowserPage` / `MockLocator`
  (a dataclass whose `click`/`fill` just log) returning a hand-built one-link `BrowserSnapshot`;
  `tests/mock/snapshot_factory.py::make_snapshot(url)`; `tests/mock/mock_service.py::MockLLMService` +
  a `patch_llm_service` fixture; `mock_vault.py`, `mock_env.py`.
- **Offline DOM fixtures**: `tests/data/*.html` — dozens of saved real pages (`duckduckgo.html`,
  `github_signin.html`, `checkout/{anthropologie,polywood,article,joybird,society6,arhaus,…}.html`).
- **`tests/browser/`** (10 files) is mostly pure-Python assertions over hand-built `DomNode` trees
  (`test_context.py` builds a `nested_graph` fixture), plus a few live-site tests — one of which is
  `@pytest.mark.skip(reason="website no longer accessible?")`, which is the honest failure mode of this approach.
- **`tests/integration/test_resolution.py`** is the interesting one: parametrized over 16 live URLs
  (google, google/flights, linkedin, instagram, bbc, amazon, arxiv, espn, …), it observes with
  `perception_type="fast"` and asserts `NodeResolutionPipe.forward` succeeds for **every** interaction node,
  reporting an error *percentage* in the assertion message. `@pytest.mark.flaky(reruns=2, reruns_delay=5)`.
- **No local fixture server.** Live sites plus flaky-reruns is the whole strategy, and `conftest.py` documents
  the flaky-marker convention as policy.

### 1.7 Judgment

**Serves deterministic replay well — copy these:**

1. `playwright_async_api.py` as a single import chokepoint for the browser lib. Every other module imports
   `Page`/`Locator` from it. Swapping playwright↔patchright (or stubbing for tests) is a one-file change.
2. The three-layer lifecycle split (process / context+page / semantics).
3. `NodeResolutionPipe`'s early return when a selector is already present. This is the compile/replay seam,
   and it costs 3 lines.
4. Actions as pydantic models with registry-built discriminated unions: a compiled program serializes to
   JSON for free and `parse_action()` gives you a validating loader with a clear error surface.
5. `NodeSelectors.selectors()` returning an *ordered candidate list* (playwright → `css=` → `xpath=`) with
   `count() == 1` disambiguation in `locate_element` — cheap robustness that costs one round-trip per candidate.
6. `capture_playwright_errors()` normalizing raw Playwright exceptions into a typed hierarchy with separate
   dev/user/agent messages.
7. Self-verifying actions (scroll checks `scrollY` actually moved). A replay engine should do this for every
   action it can cheaply check.

**Over-engineered or actively wrong for our use case:**

1. The entire `tagging/` + `rendering/` + `scraping/` + `action_selection/` LLM stack lives *inside* the
   browser package. For a design where the LLM only runs at compile time, none of this belongs below the
   compile boundary.
2. `session.py` at 1223 lines with ~30 `@overload`s of `aexecute` — that's ~200 lines of typing scaffolding
   for one method. A `parse_action(**kwargs)` + one signature is enough.
3. Persona / vault / captcha / storage / tools all wired into the session constructor.
4. Sequential positional ids (`B1`, `I2`) are an LLM affordance with *negative* value for replay: they look
   stable, they aren't, and they silently shift when the page gains an element.
5. **Random viewport jitter in headless mode** (`window.py:99-105`: `random.randint(-50, 50)` on both
   dimensions) is directly hostile to reproducibility — with `viewport_expansion = 0`, viewport size determines
   which elements are even observed. Anti-bot value, determinism cost. Do not copy.
6. `long_wait()`'s `networkidle` is both slow and semantically wrong for streaming/polling/websocket pages —
   and with no predicate-wait available, there is nothing better to reach for.
7. `snapshot_metadata()` doing six `page.evaluate` round-trips for six numbers.

---

## 2. EmergenceAI/Agent-E — `ae/core/`, `ae/utils/`

~2.4k lines across `ae/core/skills/` and `ae/utils/`. AutoGen-based multi-agent (planner + browser-nav).

### 2.1 Module map

| File | Lines | What it actually does |
|---|---|---|
| `ae/core/playwright_manager.py` | 453 | `PlaywrightManager` — a **singleton** (`__new__` guarding `cls._instance`; `_playwright`, `_browser_context`, `_screenshots_dir` are all *class* attributes). Four unrelated jobs in one class: **(a) lifecycle** — `start_playwright`, `create_browser_context` (chromium only; `launch_persistent_context(user_dir, channel="chrome", args=["--disable-blink-features=AutomationControlled", "--disable-session-crashed-bubble", "--disable-infobars"], no_viewport=True)`, with a `tempfile.mkdtemp()` retry when the profile dir is locked), `get_current_page` (last non-closed page; recreates the context if it died), `close_all_tabs`, `close_except_specified_tab`, `go_to_homepage`; **(b) handler wiring** — `set_navigation_handler` (two `page.on("domcontentloaded", …)` + `page.expose_function("dom_mutation_change_detected", …)`), `set_overlay_state_handler`, `set_user_response_handler` (both `context.expose_function`); **(c) the in-page chat UI** — `notify_user`, `prompt_user` (blocks on an `asyncio.Event` until the human answers *inside the page*), `highlight_element` (adds a CSS class for a pulsating border), `update_processing_state`, `command_completed`; **(d) screenshots** — `take_screenshots(name, page, full_page=True, load_state='domcontentloaded', timeout=5s)` writing `{time_ns}_{name}.png`. |
| `ae/core/ui_manager.py` | ~230 | Injects `ae/ui/injectOverlay.js` on every `domcontentloaded`; maintains conversation history rendered *into the page under test*. |
| `ae/utils/get_detailed_accessibility_tree.py` | 529 | **The observation pipeline** — see §2.3. `__inject_attributes`, `do_get_accessibility_info`, `__fetch_dom_info`, `__cleanup_dom`, `__prune_tree`, `__should_prune_node`, `get_element_attributes`. |
| `ae/utils/dom_mutation_observer.py` | 88 | Installs a `MutationObserver(document, {subtree, childList, characterData})` that pushes `[{tag, content}]` for newly added *visible, non-empty-text* nodes (skipping `SCRIPT/NOSCRIPT/STYLE` and anything inside `#agentDriveAutoOverlay`) into the exposed `window.dom_mutation_change_detected`. Python side is a plain `subscribe`/`unsubscribe` callback list. Re-installed on every `domcontentloaded`. |
| `ae/utils/dom_helper.py` | 45 | `wait_for_non_loading_dom_state(page, max_wait_millis)` — polls `document.readyState != "loading"` every 50 ms. `get_element_outer_html(element, page, tag)` — rebuilds an opening tag from a 15-attribute allow-list (`id,name,aria-label,placeholder,href,src,aria-autocomplete,role,type,data-testid,value,selected,aria-labelledby,aria-describedby,aria-haspopup`). |
| `ae/core/skills/*.py` | ~900 | The action layer, one file per skill: `open_url.py::openurl`, `click_using_selector.py::{click, do_click, perform_javascript_click, perform_playwright_click}`, `enter_text_using_selector.py::{entertext, bulk_enter_text, do_entertext, custom_fill_element}`, `press_key_combination.py::{press_key_combination, do_press_key_combination}`, `get_dom_with_content_type.py::{get_dom_with_content_type, get_filtered_text_content}`, `get_url.py::geturl`, `pdf_text_extractor.py`, `get_user_input.py`, `pause_flow.py`, `enter_text_and_click.py` (registered-out). |
| `ae/core/skills/skill_registry.py` | 29 | A `@skill(description, name)` decorator appending `{name, func, description}` to a module-global list. **Used only for dynamically loaded external skills** (`ADDITIONAL_SKILL_DIRS` env var); every built-in skill bypasses it. |
| `ae/core/agents/browser_nav_agent.py` | ~180 | Where skills are actually bound — `__register_skills()` does, per skill, `self.agent.register_for_llm(description=LLM_PROMPTS["CLICK_PROMPT"])(click_element)` **and** `self.browser_nav_executor.register_for_execution()(click_element)`. |
| `ae/utils/autogen_sequential_function_call.py` | 85 | `UserProxyAgent_SequentialFunctionExecution` — runs a batch of tool calls one at a time and **skips all remaining calls in the batch** once any result contains the substring `"as a consequence of this action"`. |
| `ae/utils/detect_llm_loops.py` | 46 | Terminates when the last 3 tool calls *and* the last 3 tool responses are identical. |

### 2.2 Boundaries

**There essentially are none.** `PlaywrightManager` is a singleton that every skill *re-instantiates inline*:

```python
# repeated verbatim at the top of click(), entertext(), openurl(), get_dom_with_content_type(), …
browser_manager = PlaywrightManager(browser_type='chromium', headless=False)
page = await browser_manager.get_current_page()
```

No session object is threaded anywhere; the browser is ambient global state. There is no executor or
dispatcher — each skill is an `async def` that fetches the page itself, takes its own before/after
screenshots, highlights its own element, notifies the UI, and returns a **natural-language string**.
Action *definition* and *execution* are the same Python object: the schema is the function's
`Annotated[...]` signature, and the description is a prompt string from `ae/core/prompts.py`; AutoGen
registers the same callable twice (once for the LLM's tool schema, once into the executor's function map).

The one real seam is the `do_*` convention: `do_click(page, selector, wait_before_execution)`,
`do_entertext(page, selector, text, use_keyboard_fill)`, `do_press_key_combination(browser_manager, page, combo)`
— page-parameterized inner functions with no singleton dependency and no UI side-effects. That's the API
that should have been the public one.

### 2.3 DOM / observation pipeline

`do_get_accessibility_info(page, only_input_fields)` (get_detailed_accessibility_tree.py:496), four phases:

1. **`__inject_attributes(page)`** — one `page.evaluate` over `document.querySelectorAll('*')` that sets
   `mmid = ++id` on every element **and mirrors it into `aria-keyshortcuts`** (stashing any pre-existing value
   into `orig-aria-keyshortcuts`). The comment explains why: `aria-keyshortcuts` is a rarely-used ARIA
   attribute that Chrome *surfaces in the accessibility tree*, so the DOM identity survives the a11y snapshot.
2. **`page.accessibility.snapshot(interesting_only=True)`**, dumped to `ae/log_files/json_accessibility_dom.json`.
3. **`__cleanup_dom(page)`** — restores `aria-keyshortcuts` from `orig-aria-keyshortcuts` and removes the injected value.
4. **`__fetch_dom_info`** — walks the a11y tree, reads `node['keyshortcuts']` back as the mmid, and for each
   node runs **one `page.evaluate` doing `document.querySelector('[mmid="…"]')`** to pull
   `['name','aria-label','placeholder','mmid','id','for','data-testid']` + tag + input `type` + `<select>`
   options + listbox/`ul` children + `innerText`. Then a long de-duplication pass (drop `name` if it equals
   `description`/`aria-label`/`text`; drop `role` if it equals `tag`; drop `role` for links; …). Then
   `__prune_tree` / `__should_prune_node` drop `generic`-with-no-children, `separator`, `LineBreak`, and
   name+role-only nodes, and "unravel" wrapper nodes by splicing their children into the parent.
   Result dumped to `json_accessibility_dom_enriched.json`.

**Element reference = the `mmid` integer**, handed to the LLM as a CSS selector `[mmid='114']`.
**mmids are reassigned from 1 on every DOM fetch**, so they are valid only until the next fetch. The
prompts and the skill return strings compensate by instructing the model to re-fetch the DOM after any
DOM-changing action. **iframes are in `tags_to_ignore`** — cross-frame content is simply not observed.
Shadow DOM is not handled at all.

`get_dom_with_content_type(content_type)` exposes three views: `all_fields` (full enriched tree),
`input_fields` (`only_input_fields=True` prunes to `input/button/textarea` + `role=button`), and
`text_only` (a `page.evaluate` that hides `#agente-overlay`, grabs `body.innerText`, appends all `img` alt
texts, then restores visibility).

### 2.4 Waiting / synchronization

- `wait_for_non_loading_dom_state(page, 2000)` before every DOM fetch (poll `readyState` every 50 ms).
- `openurl`: `page.goto(url, timeout=timeout*1000)` where `timeout` **defaults to 3 seconds**, and the
  `PlaywrightTimeoutError` is caught and logged as
  `"happens more often than not, but does not seem to be a problem"`.
- `do_click`: `asyncio.wait_for(page.wait_for_selector(selector, state="attached", timeout=2000), timeout=2000)`
  — note the unit mismatch, `asyncio.wait_for` takes *seconds*, so the outer bound is 2000 s and does nothing.
  Then `scroll_into_view_if_needed(timeout=200)` and `wait_for_element_state("visible", timeout=200)`, both
  wrapped in bare `except: pass`.
- **Playwright's own click is disabled.** `perform_playwright_click` exists but the call site is commented out
  with `# Playwright click seems to fail more often than not, disabling it for now and just going with JS click`.
  `perform_javascript_click` does `document.querySelector(sel).click()` in-page, first forcing
  `element.target = "_self"` on anchors.

**The interesting mechanism — post-action change detection instead of pre-action condition waiting.**
Every mutating skill does:

```python
subscribe(detect_dom_changes)
result = await do_click(page, selector, wait_before_execution)
await asyncio.sleep(0.1)          # let the observer fire
unsubscribe(detect_dom_changes)
if dom_changes_detected:
    return f"Success: … As a consequence of this action, new elements have appeared in view: {dom_changes_detected}. "
           f"This means that the action to click {selector} is not yet executed and needs further interaction. "
           f"Get all_fields DOM to complete the interaction."
```

and the sequential executor aborts the rest of the tool-call batch when it sees that phrase. The JS click
adds a second signal: it compares `aria-expanded` before and after and reports a menu opening.

### 2.5 Instrumentation

- **No network capture, no HAR, no tracing, no CDP, no video.** Grep for
  `record_har|record_video|tracing|route(|CDPSession|new_cdp_session` over `ae/` → zero hits.
  `PW_TEST_SCREENSHOT_NO_FONTS_READY=1` is set at import time (playwright_manager.py:21).
- **Screenshots**: `take_screenshots(f"{function_name}_start"/"_end", page)` brackets every skill, gated on a
  global flag, written as `{time_ns}_{name}.png` full-page.
- **JSON dumps**: raw + enriched a11y tree written to *fixed paths* under `ae/log_files/` on every fetch
  (overwritten each time, not run-scoped), plus `text_only_dom.txt`.
- **Benchmark artifacts**: `test/tests_processor.py` creates per-task `logs_for_task_{id}/snapshots/` folders
  and writes results JSON + a `tabulate` summary.

### 2.6 Testability

There are **no unit tests of the browser layer**. `test/` is a WebVoyager-style **live-site benchmark harness**:
`test/tasks/*.json` (`webvoyager_test.json`, `webvoyager_sampled_data.json`, `annotator_dry_run_webvoyager_tasks_30.json`),
`tests_processor.py` driving the full agent against real sites, `evaluators.py` scoring by URL match /
string match / LLM judge (`evaluator_router`), results tabulated to console + JSON. `test/test_utils.py` and
`test/test_config_auditor.py` are the only unit-ish tests. No mock page, no fixture server, no offline HTML.

### 2.7 Judgment

**Worth stealing:**

1. **The `mmid` → `aria-keyshortcuts` trick.** Injecting an attribute chosen *because it surfaces in the
   accessibility tree*, then cleaning it up, is the cheapest correct way to reconcile a11y semantics with DOM
   identity — two `page.evaluate` calls total. If NetGent ever wants a11y-derived labels at compile time
   without giving up DOM addressability, this is the technique.
2. **Post-action mutation detection as a generic "did anything happen" signal.** This is the seed of a good
   trigger primitive: no polling, no per-site selectors, fires on the actual DOM delta. Note that they discard
   almost all of it (only `childList` additions with non-empty `innerText`, plus `characterData`) — for
   NetGent, a richer delta (attributes, removals, URL, network quiescence) collapsed into a structured
   `PageDelta` object would be the natural generalization.
3. The `do_*(page, …)` inner functions — page-parameterized, side-effect-free, testable.
4. `get_element_outer_html`'s 15-attribute allow-list as a compact "what did I actually touch" record for logs.

**Do not copy:**

1. Singleton `PlaywrightManager` re-instantiated inside every skill. One browser per process, no parallelism,
   no injection point for tests, and the "current page" is whatever was last opened globally.
2. **The in-page chat overlay.** `injectOverlay.js` on every `domcontentloaded`, `context.expose_function`
   handlers, and a blocking human-input prompt rendered *into the page under test*. For a framework whose
   product is captured traffic and page state, injecting a UI into every observed page is contamination —
   both of the DOM and of the network trace.
3. `__fetch_dom_info` doing one `page.evaluate` **per node**. Hundreds of CDP round-trips per observation;
   a single batched evaluate returning a `{mmid: attrs}` map is the obvious fix.
4. Fixed-path artifact dumps (`ae/log_files/json_accessibility_dom.json`) — not run-scoped, races across
   concurrent sessions.
5. **Prose as protocol.** Skills return English, and control flow is driven by
   `"as a consequence of this action" in content.lower()`. One prompt reword silently breaks the executor.
6. 3-second `goto` timeout with a swallowed exception, and `except: pass` around visibility checks.
7. mmids that reset to 1 every fetch while looking like stable ids.

---

## 3. lavague-ai/LaVague — `lavague-core/base_driver.py` + `lavague-integrations/drivers/`

Dormant since 2025-01-21. Two drivers ship: Selenium (886 lines, the reference implementation) and
Playwright (420 lines, **sync API**, and noticeably less complete).

### 3.1 Module map

| File | Lines | What it actually does |
|---|---|---|
| `lavague-core/lavague/core/base_driver.py` | 646 | `BaseDriver(ABC)` (~35 abstract/virtual methods), `DOMNode(ABC)`, `InteractionType` enum (`CLICK/HOVER/SCROLL/TYPE`), `ScrollDirection` enum that **carries its own JS** (`get_page_script`, `get_script_element_is_scrollable`, `get_script_page_is_scrollable`), and four shared JS blobs: **`JS_SETUP_GET_EVENTS`** (monkey-patches `EventTarget.prototype.addEventListener/removeEventListener` to record handlers into `element.eventListenerList` and defines `window.getEventListeners` — installed as an *init script* so it applies to every document), **`JS_GET_INTERACTIVES`**, **`JS_WAIT_DOM_IDLE`**, **`JS_GET_SCROLLABLE_PARENT`**. Concrete base behaviour: `save_screenshot` (content-addressed by MD5 into `./screenshots/<md5(url)>/`), `get_screenshots_whole_page(max=30)` (scroll-and-shoot), `get_obs()` → `{html, screenshots_path, url, date, tab_info}`, and highlight bookkeeping (`highlight_nodes`, `_add_highlighted_destructors`, `remove_highlight`). |
| — its `code_for_*` half | — | **A parallel "emit the code" API on the same class**: `code_for_init()`, `code_for_get(url)`, `code_for_back()`, `code_for_execute_script(js)`, `code_for_resize(w,h)`. `BaseDriver.__init__` also runs `extract_code_from_funct(self.init_function)` + `extract_imports_from_lines(...)` and stashes `self.import_lines`, so the driver can emit a standalone script that reproduces itself. |
| `…/drivers/playwright/base.py` | 420 | `PlaywrightDriver(BaseDriver)`, **sync** `playwright.sync_api`. `default_init_code` launches chromium (or `launch_persistent_context` when `user_data_dir`), fixed Chrome-107 UA, `--disable-web-security --disable-site-isolation-trials --disable-notifications`, `context.add_init_script(JS_SETUP_GET_EVENTS)`, `new_page()`, `set_viewport_size`. Driving: `resolve_xpath(x) -> Locator` = `page.locator(f"xpath={x}")`; `click`, `set_value` (clear→click→fill→optional Enter), `perform_wait`, `scroll_up/down`; `get_possible_interactions()` runs `JS_GET_INTERACTIVES`; `exec_code(json)` parses the LLM's JSON action list and dispatches. `get_capability()` returns a ~100-line **prompt string** containing the action schema and two full few-shot HTML examples. |
| `…/drivers/selenium/base.py` | 886 | The richer reference driver — see §3.2/§3.4 for what the Playwright one lacks. `XPathResolved` context manager (restores the default frame on `__exit__`), recursive `resolve_xpath` that splits the xpath on `"iframe"` and `switch_frame`s, `is_idle()` reading Chrome's performance log, YAML `exec_code` with 8 actions, `scroll` with scrollable-container detection, `SeleniumNode(DOMNode)`, `BrowserbaseRemoteConnection`. |
| `lavague-core/…/navigation.py` | 639 | `NavigationEngine.execute_instruction` — retriever → prompt → LLM → extractor → `_verify_llm_reponse(response, authorized_xpaths)` → `driver.get_highlighted_element(action)` → `driver.exec_code(action)`, up to `n_attempts=5`, logging every attempt. `NavigationControl.execute_instruction` — a string-matching dispatcher for `SCROLL_DOWN/SCROLL_UP/WAIT/BACK/SCAN/MAXIMIZE_WINDOW/SWITCH_TAB N` that records `inspect.getsource(self.driver.scroll_down)` as the step's "code". |
| `lavague-core/…/retrievers.py` | 632 | HTML → model-consumable. `InteractiveXPathRetriever.get_html_with_xpath` (BeautifulSoup; adds `xpath="…"` to every element that `get_possible_interactions()` flagged, recursing into iframes via `driver.switch_frame`), `OpsmSplitRetriever._add_xpath_attributes` (adds xpaths to *all* elements), `UniqueXPathRetriever` (re-evaluates xpaths in-page and clones matched nodes with `clonedElement.setAttribute('xpath', xpath)`), `BM25HtmlRetriever`, `SemanticRetriever`, `filter_for_xpathed_nodes`. |
| `lavague-core/…/extractors.py` | 198 | `extract_xpaths_from_html` (regex `xpath=["'](.*?)["']`, defined as `r_get_xpaths_from_html` in base_driver), `YamlFromMarkdownExtractor`, `DynamicExtractor`. |
| `lavague-core/…/logger.py` | 199 | `AgentLogger` (per-step dicts → pandas), `LocalLogger` (JSONL), `LocalDBLogger` (sqlite, screenshots as BLOBs). |
| `lavague-qa/lavague/qa/{generator,utils}.py` | ~400 | Gherkin `.feature` → one agent run → **a standalone pytest+selenium file**. `get_nav_action_code(action)` maps `click`/`setValue`/`setValueAndEnter`/`dropdownSelect` to `WebDriverWait(browser,10).until(EC.element_to_be_clickable((By.XPATH,'…')))` + `browser.execute_script('arguments[0].click();', element)`; `get_nav_control_code(instruction)` maps the control verbs. |

### 3.2 Boundaries

`BaseDriver` **is** the boundary, and it is very wide — it spans six concerns at once: lifecycle
(`default_init_code`/`destroy`), navigation, DOM reading, interactivity scanning, screenshots/highlighting,
scroll math, action dispatch (`exec_code`), code emission (`code_for_*`), **and the LLM prompt**
(`get_capability`). There is no session/context/page split at all: `SeleniumDriver.driver` and
`PlaywrightDriver.page` are the whole thing.

**Action definitions live in three places that are already out of sync:**

1. `driver.get_capability()` — prose schema in the prompt. Playwright driver advertises 5 actions
   (`click`, `setValue`, `setValueAndEnter`, `wait`, `fail`).
2. `driver.exec_code()` — the dispatcher. Playwright handles 6 (adds `failNoElement`/`failAmbiguous`, drops
   `fail`); Selenium handles 8 (adds `dropdownSelect`, `hover`, `scroll`) **and parses YAML instead of JSON**.
3. `navigation.py::JSON_SCHEMA` — a shape validator that only checks `{action: {name, args}}`.

Nothing keeps them consistent, and they aren't. The executor (`NavigationEngine.execute_instruction`)
delegates dispatch straight back into the driver, so "executor" and "raw plumbing" are fused too.

### 3.3 DOM / observation pipeline

`driver.get_html()` → retriever annotates elements with an `xpath="…"` attribute → chunk + rank →
**the annotated HTML chunks are the model's entire view of the page**. There is no snapshot object, no
element tagging, no id scheme.

XPaths are generated two ways: in JS by `JS_GET_INTERACTIVES`'s `traverse(node, xpath)` (per-tag sibling
counting → `/html/body/div[2]/span`, with `*[local-name()='svg']` for SVG, and it *descends into same-origin
iframes* by recursing on `child.contentWindow.document.body`), or in Python by
`retrievers._generate_xpath(element)` walking BeautifulSoup parents.

`JS_GET_INTERACTIVES` returns `{xpath: ["CLICK", "TYPE", …]}` — elements typed by **capability**, derived from
`checkVisibility()`, bounding-box size ≥5px, computed style, `window.getEventListeners(e)` (available thanks
to the `JS_SETUP_GET_EVENTS` init script), `role`, tag, `cursor === 'pointer'`, `aria-haspopup`, and
`label[for]`. With `foregroundOnly`, it walks up from `document.elementFromPoint(center)` to confirm the
element is actually on top.

**Stability**: an absolute XPath is stable across steps as long as the DOM doesn't reflow, and it is
*meaningful in a generated script* — which is precisely why `lavague-qa` can emit it verbatim into a pytest
file. It is not robust to any structural change. Hallucination is guarded at compile time by
`_verify_llm_reponse(response, authorized_xpaths)` (navigation.py:400): every emitted xpath must appear in
`authorized_xpaths` (extracted from the exact chunks that were in the prompt), and the failure is classified —
`ElementOutOfContextException` if it resolves but wasn't in context, `HallucinatedException` if it doesn't
resolve at all.

### 3.4 Waiting / synchronization — the best of the three

**`JS_WAIT_DOM_IDLE`** (base_driver.py:595) is a real quiescence predicate:

```js
return new Promise(resolve => {
    const timeout = arguments[0] || 10000;
    const stabilityThreshold = arguments[1] || 100;
    let mutationObserver, timeoutId = null;
    const waitForIdle = () => { if (timeoutId) clearTimeout(timeoutId);
                                timeoutId = setTimeout(() => resolve(true), stabilityThreshold); };
    mutationObserver = new MutationObserver(waitForIdle);
    mutationObserver.observe(document.body, {childList: true, attributes: true, subtree: true});
    waitForIdle();
    setTimeout(() => { resolve(false); mutationObserver.disconnect(); … }, timeout);
});
```

i.e. *resolve once no mutation has fired for 100 ms*, with a 10 s ceiling that resolves `false`. Composed:

- `PlaywrightDriver.wait_for_idle()` = `page.wait_for_load_state("networkidle", timeout=self.waiting_completion_timeout)`
  then `wait_for_dom_stable(remaining_budget)`.
  **Bug worth knowing:** `waiting_completion_timeout` defaults to `10` (seconds, per the Selenium driver's use of
  it with `WebDriverWait`) but Playwright's `timeout=` is **milliseconds** — so the networkidle wait is
  effectively 10 ms and always falls through to the DOM-stability wait. Which, ironically, is the better signal.
- `SeleniumDriver.wait_for_idle()` = `WebDriverWait(driver, 10).until(lambda d: self.is_idle())` then DOM stability.
  `is_idle()` reads Chrome's CDP performance log and counts in-flight requests:
  `Network.requestWillBeSent` adds a request id, `Network.loadingFinished`/`loadingFailed` discards it;
  `Page.frameStartedLoading`/`Browser.downloadWillBegin` increment a counter, `frameStoppedLoading` and
  completed/cancelled `downloadProgress` decrement it. Idle ⇔ `len(request_ids) == 0 and active <= 0`.
- `wait_for_idle()` is called after **every** action inside `exec_code`, plus `time.sleep(time_between_actions=1.5)`
  between engine instructions.
- Small state predicates exist too: `is_bottom_of_page()`, `can_scroll(direction)`, `check_visibility(xpath)`.

No per-element condition waits in the driver itself. Notably, the **generated** pytest is stricter than the
agent: `get_click_action` emits `WebDriverWait(browser, 10).until(EC.element_to_be_clickable((By.XPATH, …)))`.

### 3.5 Instrumentation

- **Selenium driver has the only real network instrumentation in any of the three repos**:
  `chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})` (base.py:122) gives a full CDP
  `Network.*` / `Page.*` / `Browser.*` event stream via `driver.get_log("performance")`. It is consumed
  **only** by `is_idle()` and then discarded — nothing persists it as data.
- **Playwright driver: nothing.** No HAR, no tracing, no `route`, no video, no CDP session.
- Screenshots: content-addressed by MD5 under `./screenshots/<md5(url)>/`; `get_obs()` clears that folder on
  every observation unless the previous op was a whole-page `SCAN`.
- Logs: `AgentLogger.add_log(dict)` per engine step carrying `navigation_engine_input`, `retrieved_html`,
  `retrieval_time`, `llm_raw_response`, `action_generation_time`, the full prompt, model name, per-attempt
  `action_outcomes` with `success`/`error`, and `vision_data` (screenshot + bbox + viewport per touched
  element). `LocalLogger` → JSONL, `LocalDBLogger` → sqlite with image BLOBs. `utilities/profiling.py::time_profiler`
  spans around retrieval, inference, and code execution.

### 3.6 Testability

- `tests/` contains **exactly one file** (`tests/lavague-core/lavague/core/utilities/test_format_utils.py`).
  The driver classes have no unit tests.
- `lavague-tests/` is the real harness, and it's the best testing idea across all three repos:

  ```yaml
  # lavague-tests/sites/examples/config.yml
  type: static
  port: 8000
  directory: www
  tasks:
    - name: Navigate using link
      url: http://localhost:8000
      prompt: Go to the menu
      max_steps: 1
      expect:
        - URL is http://localhost:8000/menu.html
        - HTML contains <h1>Menu</h1>
  ```

  `lavague/tests/setup.py::StaticServer` spins up `http.server.SimpleHTTPRequestHandler` on a daemon thread
  for the duration of the run; `config.py::TestConfig` parses tasks; `test.py::ExpectTest` parses the
  `URL is …` / `HTML contains …` assertion DSL; `runner.py` aggregates results with token/cost accounting.
  Live-site directories (`amazon.com`, `nytimes.com`, `reddit.com`, `youtube.com`, `iframe`, …) sit alongside
  the static ones, so the same harness covers both.

### 3.7 Judgment

**The one big idea worth taking:**

**`exec_code` / `code_for_*` duality.** Every driver capability has a "do it now" form and an "emit the source
that does it" form, so an agent run compiles to a standalone script. `lavague-qa` is a working end-to-end
demo: Gherkin feature → one LLM-driven run → a pytest file that runs forever with zero LLM calls. That is
structurally *exactly* NetGent's `generate` → `run` split, and it validates the approach.

**Also worth taking:**

1. `JS_WAIT_DOM_IDLE` — mutation quiescence with a stability threshold and a hard ceiling. Portable in ~20
   lines, and strictly better than `networkidle` for SPA and streaming pages.
2. `JS_GET_INTERACTIVES` returning `{xpath: [capabilities]}`. Typing elements by **capability**
   (`CLICK`/`TYPE`/`HOVER`/`SCROLL`) rather than by tag is the right abstraction for *validating at replay
   time that a compiled action is still applicable to the element it resolved to*.
3. `JS_SETUP_GET_EVENTS` installed as an init script to make `window.getEventListeners` available in normal
   page context (it's a DevTools-only API otherwise). notte's `buildDomNode.js` needs the same thing and
   falls back to sniffing `on*` attributes because it doesn't do this.
4. `_verify_llm_reponse` distinguishing hallucination from out-of-context, as a compile-time gate.
5. The `lavague-tests` static-site harness — declarative site + tasks + expectations, local HTTP server.

**Do not copy:**

1. `code_for_init()` reconstructing source by **string-editing its own function's source lines**
   (`extract_code_from_funct` + manual `if`/`else` skipping with `ignore_next` / `keep_else` counters,
   rewriting `self.headless` → `False` textually). Unmaintainable. Emit from a parameterized template.
2. A ~35-method `BaseDriver` spanning six concerns, of which the Playwright implementation degrades or omits
   ~8 (no iframe traversal in `resolve_xpath`, no `get_nodes`/`DOMNode`, no dropdown/upload/hover/scroll-container,
   `execute_script` fakes Selenium's `arguments[0]` calling convention). The abstraction leaks by construction
   because it was shaped around Selenium.
3. Three out-of-sync sources of truth for the action schema, in two different serialization formats
   (JSON for Playwright, YAML for Selenium).
4. Prompt text — including two pages of a Dutch Google cookie banner — living inside the driver class.
5. Per-URL screenshot folders under CWD, cleared on each `get_obs()`. Global mutable state on disk.
6. Sync Playwright API + `time.sleep`.

---

## Cross-cutting observations

**Nobody captures network traffic.** Across ~10k lines of browser-layer code in three frameworks, there is
exactly one CDP network subscription (LaVague's Selenium `goog:loggingPrefs`) and it is used only to decide
"is the page idle", then thrown away. Zero HAR, zero `route()`, zero `context.tracing`, zero video. Every one
of these frameworks treats the network as an implementation detail of page loading. **For NetGent this is not a
gap to fill from prior art — it is the axis on which the whole design differs, and there is no reference
implementation to copy.**

**Nobody has a conditional-wait primitive.** All three converge on the same two moves: a fixed sleep, and
"wait until things stop changing" (`networkidle`, mutation quiescence, in-flight request counting). None has a
first-class *predicate on page state that gates an action*. Agent-E's post-action mutation subscription and
LaVague's `is_idle()`/`can_scroll()`/`check_visibility()` are the closest analogues, and both are ad hoc.
NetGent's trigger concept has no prior art here either — which is a design opportunity and a warning that
it's genuinely the hard part.

**Element-identity strategies, ranked for replay:**

| Strategy | Repo | Replay verdict |
|---|---|---|
| Playwright `internal:role=…` selector stored on the action | notte | **Best.** Semantic, survives reflow, resolves with no snapshot. |
| Ordered candidate list (playwright → css → xpath) with `count()==1` | notte | **Best.** Cheap fallback chain. |
| Absolute XPath | LaVague | Workable in generated scripts; brittle to any structural change. |
| Per-snapshot sequential ids (`B1`, `I2`) | notte | Compile-time only. Looks stable, isn't. |
| Per-fetch integer `mmid` | Agent-E | Compile-time only, and shorter-lived than notte's. |
| Structural fingerprint (`notte_selector`) | notte | Not a locator — useful for *detecting* that a node changed. |

---

## Lessons for NetGent v2

Concrete, in rough priority order.

**Architecture**

1. **Adopt notte's three-layer lifecycle split, verbatim in shape**: a process-owner
   (`PlaywrightManager`-equivalent), a page/context owner (`BrowserWindow`-equivalent), and a semantic layer.
   Agent-E's singleton and LaVague's monolithic `BaseDriver` both demonstrate the failure mode of collapsing
   these: untestable, unparallelizable, and no place to inject a recording context.
2. **One import chokepoint for Playwright** (notte's `playwright_async_api.py`). Every module imports
   `Page`/`Locator`/`BrowserContext` from `netgent.browser.pw` and nothing else touches `playwright.*`
   directly. This is what makes a fake page for unit tests a 50-line file instead of a mocking nightmare.
3. **Keep the LLM out of the browser package entirely.** notte's biggest structural mistake is that
   `notte-browser` imports `notte_llm` and ships four LLM pipelines. For NetGent the browser layer must be
   importable and runnable with no model provider configured at all — that property is what makes `run`
   trustworthy, and it should be enforced with an import-lint rule, not a convention.

**The action IR — the compile artifact**

4. **Actions are pydantic models with a `Literal` discriminator, auto-registered, unioned.** Copy notte's
   `__init_subclass__` registry + `reduce(operator.or_, REGISTRY.values())` pattern
   (`notte-core/actions/actions.py`). You get: JSON round-trip of the compiled NFA for free, a validating
   loader (`parse_action`) with real error messages, and exhaustiveness checking on the executor's `match`.
5. **Exactly one source of truth for the action schema.** LaVague's three out-of-sync definitions (prompt
   prose, dispatcher `match`, JSON schema) is the anti-pattern. Derive the compile-time prompt/tool schema
   *from* the pydantic models — never hand-write it alongside them.
6. **Every action carries its own resolved selector and its own timeout.** notte's `InteractionAction.selector`
   plus the `timeout=0 → default` validator (Playwright treats 0 as infinite — a real footgun) are both
   worth copying directly.
7. **Store an ordered candidate-selector list, not a single string.** `NodeSelectors.selectors()` +
   `locate_element`'s "first candidate with `count()==1` wins" is ~15 lines and buys real resilience. Record
   at compile time: role-based Playwright selector, `data-testid`-style attribute selector, css path, xpath —
   in that preference order.
8. **Never put per-snapshot sequential ids in the compiled artifact.** They exist for the model at compile
   time and must be resolved away before the NFA is written out. Both notte (`B1`/`I2`) and Agent-E (`mmid`)
   re-derive theirs on every observation.

**The resolution seam**

9. **`NodeResolutionPipe`'s early return is the whole generate/run split.** Make it explicit and typed:
   an `UnresolvedAction` (has an element *reference*, needs a snapshot) and a `ResolvedAction` (has selectors,
   executes standalone). `generate` emits only `ResolvedAction`s; `run` accepts only `ResolvedAction`s and can
   assert that statically. notte gets this right but leaves it implicit in an `if`.
10. **Verify applicability at replay, don't just fire blindly.** LaVague's capability typing
    (`{xpath: [CLICK, TYPE]}`) points the way: before executing a compiled `fill`, confirm the resolved
    element still accepts text. notte's self-checking scroll (compare `scrollY` before/after → raise) is the
    same instinct applied to effects. Cheap pre/post assertions are what turn a replay failure from
    "silently produced garbage traffic" into "failed loudly at step 7".

**Triggers / synchronization**

11. **Build the trigger primitive on mutation quiescence, not `networkidle`.** Port LaVague's
    `JS_WAIT_DOM_IDLE` (mutation observer + stability threshold + hard ceiling, resolving `true`/`false` so
    the caller knows whether it *converged* or *timed out*). All three repos' `networkidle` usage is either
    slow, wrong for streaming pages, or (in LaVague's Playwright driver) accidentally a 10 ms no-op.
12. **Compose triggers from several signals, and make them structured objects.** The vocabulary the prior art
    implies: DOM quiescence, URL predicate, selector-visible/enabled predicate, in-flight-request count
    (LaVague's `is_idle` request-id set is the right shape and NetGent will already have the CDP `Network.*`
    stream), and a mutation *delta* (Agent-E). Each should be an evaluable predicate with a timeout and a
    defined not-satisfied outcome — never a substring in an English string (Agent-E's
    `"as a consequence of this action" in content.lower()` is the cautionary tale).
13. **A fixed sleep is a fallback, not a trigger.** All three lean on `wait_short_ms` / `time.sleep(1.5)` /
    `asyncio.sleep(0.1)` as load-bearing synchronization. Every such sleep in NetGent should be attributable
    to a trigger that couldn't be expressed, and that's a bug report.

**Instrumentation — where NetGent must invent**

14. **Hook capture at context creation, not per action.** `browser.new_context(record_har_path=…,
    record_video_dir=…)` and `context.tracing.start(...)` are context-level in Playwright, which means the
    capture boundary belongs in the `BrowserWindow`-equivalent's constructor — the layer notte already has
    and the other two lack. This is another reason not to collapse the lifecycle layers.
15. **Prefer CDP `Network.*` over HAR if per-request timing fidelity matters**; LaVague's `is_idle()` shows
    the event bookkeeping (`requestWillBeSent` → `loadingFinished|loadingFailed`) needed to reconstruct
    in-flight state. HAR is the convenient default; a raw CDP event log is the superset. Decide early,
    because it determines whether the window owns a persistent `CDPSession` (notte caches one per page keyed
    by `id(page)` and prunes on close — copy that cache, including the `_drop_on_close` handler).
16. **Run-scoped artifact directories, always.** Agent-E writes `json_accessibility_dom.json` to a fixed path
    on every observation; LaVague writes screenshots to `./screenshots/<md5(url)>/` under CWD and clears it
    mid-run. For a dataset product, artifacts are the deliverable: one directory per run, immutable,
    content-addressed where it helps (LaVague's MD5 screenshot naming is a good idea in a bad location).
17. **Inject nothing into the page you are recording, beyond what observation requires.** Agent-E's chat
    overlay, `expose_function` bindings, and CSS highlight classes all contaminate both the DOM and the
    network trace. Compile-time-only injection (the DOM walker, the mutation observer) is fine; anything
    that persists into `run` is a defect. Agent-E's `__cleanup_dom` — restoring `aria-keyshortcuts` after
    reading it — is the right discipline, applied in the wrong codebase.

**Determinism hazards found in the wild**

18. **Do not randomize the viewport.** notte jitters headless viewport dimensions by ±50 px
    (`window.py:99-105`) for anti-bot reasons. With viewport-relative element filtering, that changes what
    the DOM walker even sees. If NetGent ever wants UA/viewport variation for traffic realism, it must be a
    *seeded, recorded* parameter of the run, not `random.randint` at construction time.
19. **Pin every clock.** `time_between_actions=1.5`, `wait_short_ms=500`, `wait_before_execution` — these are
    scattered magic numbers in all three repos. NetGent's compiled NFA should carry its own timing profile so
    two runs of the same artifact produce comparable traces.

**Testability**

20. **Steal `lavague-tests` wholesale.** A `sites/<name>/{config.yml,www/}` layout with a threaded
    `http.server` fixture, declarative tasks, and `expect:` assertions gives fast, offline, fully
    deterministic end-to-end tests — the only harness of the three that a CI run can trust. notte's live-site
    integration tests already contain a `@pytest.mark.skip(reason="website no longer accessible?")`, which is
    where that road ends.
21. **Keep offline HTML fixtures for the DOM/observation layer** (notte's `tests/data/*.html` of real
    checkout pages) so parser changes are testable without a browser at all.
22. **Live-site tests are for the compiler, not the runtime.** `run` must be testable against static fixtures
    end-to-end; only `generate` needs the messy real web, and those tests should be quarantined and expected
    to be flaky (notte's `@pytest.mark.flaky(reruns=2, reruns_delay=5)` convention, documented in
    `conftest.py`, is a reasonable way to live with that).
