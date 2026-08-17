# Browser Layer Research — Batch B: Environment-Style Playwright Stacks

Deep source read of the three most rigorously engineered *environment*-style Playwright observation/action
layers in the ecosystem, done for the design of NetGent v2's browser layer (Playwright-only, NL specs
compiled to a deterministic NFA, **zero LLM calls at run time**, product = realistic network-traffic datasets).

Everything below was read from source in shallow clones taken **2026-08-17**. Line numbers refer to those
commits.

| Repo | Commit read | Last commit date | Version | License | Package under study |
|---|---|---|---|---|---|
| [ServiceNow/BrowserGym](https://github.com/ServiceNow/BrowserGym) | `9e779f0` | 2026-03-17 | `browsergym-core` **0.14.3** | Apache-2.0 | `browsergym/core`, `browsergym/experiments` |
| [ServiceNow/AgentLab](https://github.com/ServiceNow/AgentLab) | `cbc35a9` | 2026-03-17 | hatch-vcs (git tags) | Apache-2.0 | `src/agentlab/{experiments,agents,analyze,benchmarks}` |
| [web-arena-x/webarena](https://github.com/web-arena-x/webarena) | `dce0468` | 2025-11-26 | `0.1.0` (setup.py) | Apache-2.0 | `browser_env/` |

**Reading order that matters for NetGent:** WebArena has the *typed, serializable* action system (closest to a
compiled NFA edge). BrowserGym has the *rigorous* observation layer (element identity across iframes/shadow
DOM). AgentLab has the *reproducibility discipline* (what you record so a run can be re-run and diffed).
None of the three is a replay engine — but two of them contain one hiding in a corner
(`TeacherForcingAgent`, `ReproAgent`), and those two corners are the most instructive code in this batch.

---

# 1. ServiceNow/BrowserGym (`browsergym-core`)

Monorepo of separately-published namespace packages under `browsergym/`: `core`, `experiments`, plus
benchmark adapters (`miniwob`, `webarena`, `webarena_verified`, `webarenalite`, `visualwebarena`,
`assistantbench`). Only `core` and `experiments` matter here.

## 1.1 Module map

### `browsergym/core/src/browsergym/core/`

| File | LOC | What it actually does |
|---|---:|---|
| `env.py` | 690 | `BrowserEnv(gym.Env)` — the whole environment. Launches Chromium, owns the `BrowserContext`, tracks the "active page" via a JS callback hack, runs `reset()` / `step()` / `_get_obs()`, retries observation extraction on detached frames. |
| `observation.py` | 624 | All extraction. `_pre_extract` / `_post_extract` (bid marking), `extract_dom_snapshot`, `extract_merged_axtree`, `extract_all_frame_axtrees`, `extract_screenshot`, `extract_dom_extra_properties`, `extract_focused_element_bid`, `MarkingError`. Pure CDP, no Playwright locators. |
| `chat.py` | 95 | `Chat` — a **second browser instance** rendering an HTML chatbox, used as the human↔agent channel. `expose_function("send_user_message")`, `wait_for_user_message()` blocks on `page.wait_for_function("USER_MESSAGE_RECEIVED", polling=100, timeout=0)`. |
| `task.py` | 111 | `AbstractBrowserTask` — `setup(page) -> (goal, info)`, `validate(page, chat_messages) -> (reward, done, msg, info)`, optional `cheat()`, `teardown()`. Task also declares `viewport`, `slow_mo`, `timeout`, `locale`, `timezone_id`. `OpenEndedTask` is the trivial impl. |
| `registration.py` | 76 | `register_task()` → `gym.register("browsergym/<id>")`. `frozen_partial` prevents task kwargs from being overridden at env-creation time. Carries a `nondeterministic: bool = True` flag straight into gym metadata. |
| `constants.py` | 5 | `BROWSERGYM_ID_ATTRIBUTE = "bid"`, `BROWSERGYM_VISIBILITY_ATTRIBUTE`, `BROWSERGYM_SETOFMARKS_ATTRIBUTE`, `EXTRACT_OBS_MAX_TRIES = 5`. |
| `spaces.py` | 140 | `Unicode`, `Float`, `Integer`, `AnyDict`, `AnyBox`, `Anything` — gym `Space` subclasses that let the obs dict hold arbitrary JSON/ndarray. |
| `__init__.py` | 30 | Module-global singleton Playwright (`_get_global_playwright()` / `_set_global_playwright()`), plus `get_global_demo_mode()`. |
| `action/base.py` | 73 | `AbstractActionSet` ABC (`describe`, `example_action`, `to_python_code`, `to_tool_descriptor`) and **`execute_python_code(code, page, send_message_to_user, report_infeasible_instructions)`** — a bare `exec()` with a 4-key globals dict. Its own docstring says "WARNING: this is not safe!". |
| `action/highlevel.py` | 595 | `ACTION_SUBSETS` (the named action vocabularies), `HighLevelAction` dataclass, `HighLevelActionSet`. |
| `action/functions.py` | 658 | The 30-odd action *primitives* (`click`, `fill`, `press`, `scroll`, `goto`, `tab_focus`, `mouse_*`, `keyboard_*`, `upload_file`, `send_msg_to_user`, `report_infeasible`, `noop`). Module-level `page`, `send_message_to_user`, `demo_mode`, `retry_with_force` are **placeholders** — the functions are never called in-process; their *source* is copied into generated code. |
| `action/utils.py` | 317 | `get_elem_by_bid` (the frame-walking locator resolver), `call_fun` (retry-with-force), `map_coordinates` (screenshot↔page scale), plus demo-mode visual effects (`smooth_move_visual_cursor_to`, `highlight_by_box`, `check_for_overlay`). |
| `action/parsers.py` | 92 | pyparsing grammar. `highlevel_action_parser` parses Python-ish call syntax into `(name, args)`; `action_docstring_parser` parses each primitive's docstring `Examples:` block **using the same parser**. |
| `action/python.py` | 112 | `PythonActionSet` — the escape hatch: the "action" is raw Playwright Python; `to_python_code` just strips markdown fences. |
| `javascript/frame_mark_elements.js` | 295 | The injected marker. Assigns bids, records visibility ratios via `IntersectionObserver`, computes set-of-marks flags, writes live `value`/`checked` back into DOM attributes, smuggles the bid into ARIA attributes. |
| `javascript/frame_unmark_elements.js` | 41 | Strips the ARIA smuggling back out. |
| `../utils/obs.py` | 554 | Serializers: `flatten_dom_to_str`, `flatten_axtree_to_str`, `prune_html`, `overlay_som`, `_process_bid`. This is where the DOM/AXTree become LLM text. |
| `../utils/mcp_server.py` | 192 | FastMCP server exposing the env as MCP tools. Not core. |

### `browsergym/experiments/src/browsergym/experiments/`

| File | What it does |
|---|---|
| `loop.py` (980) | `EnvArgs`, `AbstractAgentArgs`, `StepTimestamps`, `StepInfo`, `ExpArgs`, `ExpResult`, `get_exp_result`, `yield_all_exp_results`. The artifact format. |
| `agent.py` (112) | `Agent` ABC (`action_set`, `obs_preprocessor`, `get_action`), `AgentInfo` dataclass, `default_obs_preprocessor` (adds `dom_txt`, `axtree_txt`, `pruned_html`; **deletes** `dom_object`/`axtree_object` so they never hit disk). |
| `benchmark/base.py` (260) | `Benchmark` and `HighLevelActionSetArgs` — the *serializable* description of an action set (`subsets`, `multiaction`, `strict`, `retry_with_force`, `demo_mode`) with a `make_action_set()` factory. Also task-dependency graphs and split subsetting. |

## 1.2 Action system

**Actions are strings.** `BrowserEnv.action_space = Unicode()` (`env.py:203`). There is no action object.
The whole system is *string → Python source → `exec()`*.

The pipeline in `BrowserEnv.step()` (`env.py:432-465`):

```python
code = self.action_mapping(action)      # default: HighLevelActionSet().to_python_code
execute_python_code(code, self.page, send_message_to_user, report_infeasible_instructions)
```

### `HighLevelActionSet.__init__` (`highlevel.py:298`)

Builds two things from a list of Python function objects:

1. **`self.action_set: dict[str, HighLevelAction]`** — for prompting. For each allowed function it extracts
   `f"{func.__name__}{inspect.signature(func)}"` and runs `action_docstring_parser.parse_string(func.__doc__)`
   to split the docstring into `description` + machine-parsed `examples`. *The examples in the docstring are
   parsed with the same grammar the agent's output is parsed with* — a malformed example is a hard failure at
   import time. That's a genuinely good idea: the prompt and the parser can't drift.
2. **`self.python_includes: str`** — a preamble of literal source code, assembled by
   `inspect.getsource()` over every function in `action/utils.py` and every allowed action in
   `action/functions.py`, prefixed with `import playwright.sync_api` and the `demo_mode`/`retry_with_force`
   literals (`highlevel.py:346-381`).

### `to_python_code(action)` (`highlevel.py:488`)

```python
function_calls = highlevel_action_parser.parse_string(code, parse_all=True)   # strict=True
#                or .search_string(code)  → skip prose between calls          # strict=False
python_code  = self.python_includes
for name, args in function_calls:
    if name not in self.action_set: raise NameError(...)
    python_code += name + "(" + ", ".join(repr(a) for a in args) + ")\n"
```

So the emitted program is **the entire action library re-inlined on every single step**, followed by one or
more call lines. `multiaction=False` rejects >1 call.

### The parser (`parsers.py`)

`_build_highlevel_action_parser()` builds a pyparsing grammar for Python-literal-only call syntax: strings
(via `ast.literal_eval` on `python_quoted_string`), numbers, `True`/`False`/`None`, lists, tuples, dicts with
string keys, positional args and `name=value` args (`NamedArgument` dataclass). Python comments are ignored.
Positional-after-keyword is a parse error. It deliberately cannot express arbitrary expressions — a
whitelist-by-grammar, not by validation.

### Element addressing: `get_elem_by_bid` (`action/utils.py:6`)

The bid encodes its own frame path. `"abDb123"` means: element `123` inside frame `abDb`, inside `abD`,
inside `a`, inside the main frame. The resolver walks it character-class by character-class:

```python
while bid[i:] and not bid[i:].isnumeric():
    i += 1
    while bid[i:] and bid[i].isalpha() and bid[i].isupper(): i += 1
    frame_elem = current_frame.get_by_test_id(bid[:i])
    current_frame = frame_elem.frame_locator(":scope")
elem = current_frame.get_by_test_id(bid)
```

This works because `reset()` calls `pw.selectors.set_test_id_attribute(BROWSERGYM_ID_ATTRIBUTE)`
(`env.py:259`), rebinding Playwright's `get_by_test_id` from `data-testid` to `bid`. Neat: no custom selector
engine, just a global rebind.

### Execution details worth stealing (or avoiding)

- Every locator op carries a **hardcoded `timeout=500`** (`functions.py`, e.g. `elem.click(..., timeout=500)`).
  Fast-fail by design; the env's `context.set_default_timeout(timeout)` does *not* apply.
- `call_fun(do, retry_with_force)` (`utils.py:281`) catches `TimeoutError` and retries with `force=True` —
  a one-line escalation policy that converts "element is covered" into "click anyway".
- `fill()` has an `enable_autocomplete_menu` mode that fills *n-1* chars then `type()`s the last one, purely to
  trigger autocomplete. This is a real-world affordance most stacks lack.
- `new_tab` / `tab_close` / `tab_focus` reassign the module-global `page` **and** dispatch a synthetic
  `pageshow` event so the env's active-page callback fires (`functions.py:552`, `581`, `604`).
- `scroll` / all `mouse_*` funnel coordinates through `map_coordinates(page, x, y)`, which divides by
  `page._bgym_scale_factor` — the hi-DPI screenshot scale. Coordinates in actions are *screenshot* space, not
  page space.

### `to_tool_description(api="openai"|"anthropic")` (`highlevel.py:532`)

Reflects `inspect.signature` into a JSON Schema per action. Note the bug-shaped line
`signature = inspect.signature(globals()[tool_name])` — it resolves against `highlevel.py`'s own globals, so it
only works for actions imported at the top of that module (all built-ins are; `custom_actions` are not).

## 1.3 Observation pipeline

`BrowserEnv._get_obs()` (`env.py:616`) is a retry loop (`EXTRACT_OBS_MAX_TRIES = 5`) around:

```
_pre_extract(page, tags_to_mark)              # inject + run frame_mark_elements.js recursively
dom      = extract_dom_snapshot(page)         # CDP DOMSnapshot.captureSnapshot
axtree   = extract_merged_axtree(page)        # CDP Accessibility.getFullAXTree per frame, merged
focused  = extract_focused_element_bid(page)  # JS walk through shadow roots + PW walk through iframes
extra    = extract_dom_extra_properties(dom, scale_factor)
_post_extract(page)                           # frame_unmark_elements.js
screenshot = extract_screenshot(page)         # CDP Page.captureScreenshot
```

Retry is keyed on a **string-matched allowlist of transient errors** (`env.py:646-654`):
`"Frame was detached"`, `"Frame with the given frameId is not found"`, `"Execution context was destroyed"`,
`"Frame has been detached"`, `"Cannot mark a child frame without a bid"`, `"Cannot read properties of
undefined"`. On the last try `_pre_extract(..., lenient=True)` downgrades the missing-bid failure to a warning.
Crude, but it encodes real hard-won knowledge about which Playwright errors are worth retrying.

### Element identity: how bids are assigned (`frame_mark_elements.js`)

Per frame, in `window`:

- `window.browsergym_elem_counter` — monotonic integer, elements get `"0"`, `"1"`, `"2"`, …
- `window.browsergym_frame_id_generator` — an `IFrameIdGenerator` (line 259) producing `a, b, …, z, aA, aB, …`
  for `<iframe>`/`<frame>` elements only.
- Global bid = `parent_bid + local_id`. Hence the frame-path encoding that `get_elem_by_bid` decodes.

Stability rules (lines 109-140):

- If the element already carries a `bid` attribute, **reuse it** — so bids are stable across successive
  extractions within one page lifetime.
- If it's the frame's *first* visit and the attribute already exists → `throw` (someone else is using `bid`).
- If the bid is a duplicate within this pass → discard and regenerate.

**The counters live on `window`.** A navigation, a reload, or a re-created iframe resets them. So bids are
stable *within* a page instance and meaningless *across* navigations. Any NetGent NFA that stored bids as edge
targets would break on the first page load.

`document.querySelectorAll('*')` is walked with shadow roots spliced in-order into the array (lines 64-70), so
shadow DOM is marked too. `tags_to_mark` is `"standard_html"` (a hardcoded 130-tag allowlist) or `"all"`.

### The ARIA smuggling hack

CDP's `DOMSnapshot` gives you attributes; CDP's `Accessibility.getFullAXTree` does **not** — AX nodes have no
way to carry a custom attribute. BrowserGym's workaround (`frame_mark_elements.js:145-146`):

```js
push_bid_to_attribute(bid, elem, "aria-roledescription");
push_bid_to_attribute(bid, elem, "aria-description");   // fallback for generic nodes
```

writing `"browsergym_id_<bid> <original content>"`. Then on the Python side,
`extract_data_items_from_aria()` (`observation.py:197`) regex-strips it back out of both the AXTree
(`extract_all_frame_axtrees`, lines 505-533 → sets `node["browsergym_id"]`) and the DOM snapshot
(`pop_bids_from_attribute`, line 259). `_post_extract` then removes the attributes from the live page.

This is clever and it is also a **live mutation of the page under observation**. It changes accessible names,
it fires mutation observers, and if extraction throws mid-way the page is left dirty. For NetGent — whose
output *is* the network traffic — any page mutation that could trigger a fetch is a contamination risk.

### Extra per-element properties (`extract_dom_extra_properties`, `observation.py:293`)

Walks the DOM snapshot's flattened document array, builds the iframe tree via `contentDocumentIndex`,
accumulates each document's absolute offset (parent node bounds − `scrollOffsetX/Y`), and emits
`extra_properties[bid] = {visibility, bbox, clickable, set_of_marks}` with `bbox` in **absolute page
coordinates scaled by `scale_factor`**. `clickable` comes from CDP's `isClickable`; `visibility` and
`set_of_marks` come from attributes the injected JS wrote.

`visibility` is computed by an `IntersectionObserver` with 11 thresholds, and the JS **awaits** all observed
elements being visited, up to a 1000 ms budget, before returning (lines 185-193). Over-budget is a warning, not
an error. This is the only place BrowserGym genuinely waits on rendering.

Set-of-marks (lines 148-180) is a heuristic port of WebVoyager: element captures its own center click, has an
interactive tag / `onclick` / `cursor: pointer`, area ≥ 20 px², not inside an already-marked button, not the
sole child of a marked role-bearing `<span>` — and marking a child *unmarks* all ancestors.

### Screenshot (`extract_screenshot`, `observation.py:115`)

CDP, not `page.screenshot()`. It temporarily `Emulation.setDeviceMetricsOverride`s `deviceScaleFactor` to
`page._bgym_scale_factor`, captures, then **restores the original metrics explicitly** rather than clearing the
override. Chromium is launched with `--disable-features=OverlayScrollbars,ExtendedOverlayScrollbars` and
`ignore_default_args=["--hide-scrollbars"]` (`env.py:266-277`) specifically so scrollbars appear in screenshots.

### Serialization (`utils/obs.py`)

`flatten_dom_to_str` walks the snapshot as HTML text (natbot-derived) then `BeautifulSoup(...).prettify()`.
`flatten_axtree_to_str` DFS-prints `[bid] Role 'name' value=… , prop=…`, with `skip_generic`,
`remove_redundant_static_text` (drops a StaticText whose content is already in the parent name),
`hide_bid_if_invisible`, and the filter family `filter_visible_only` / `filter_with_bid_only` /
`filter_som_only` (all routed through `_process_bid`, line 196). `prune_html` unwraps
attribute-free structural tags and decomposes `style`/`link`/`script`/`br`.

## 1.4 Waiting / synchronization

There is no page-ready model. There is a fixed sequence, in `post_step()` (`env.py:467-538`):

1. `time.sleep(self.pre_observation_delay)` — **default 0.5 s**, "wait for JS events to be fired". The
   docstring specifically calls out autocomplete menus appearing after a fill.
2. `self.context.cookies()` — a documented hack to "trigger all waiting Playwright callbacks on the stack"
   (links to the Playwright multithreading doc). This is how the `expose_binding` active-page callbacks get
   flushed.
3. `_wait_dom_loaded()` (`env.py:563`):

```python
for page in self.context.pages:
    try: page.wait_for_load_state("domcontentloaded", timeout=3000)
    except playwright.sync_api.Error: pass
    for frame in page.frames:
        try: frame.wait_for_load_state("domcontentloaded", timeout=3000)
        except playwright.sync_api.Error: pass
```

Note: **`domcontentloaded`, not `networkidle`**, per page *and* per frame, and timeouts are swallowed silently.
There is no `wait_for_selector`, no `expect()`, no condition-based waiting anywhere in `core` except
`Chat.wait_for_user_message`'s `page.wait_for_function`.

`step()` also parses its own timeout out of the exception message:

```python
match = re.match("TimeoutError: Timeout ([0-9]+)ms exceeded.", self.last_action_error)
if match: info["action_exec_timeout"] = float(match.groups()[0]) / 1000
```

so that `StepInfo` can subtract dead time from `action_exec_stop` and get a clean video clip boundary
(`loop.py:197-199`). Ugly parsing, genuinely useful signal.

### Active page tracking

Playwright has no notion of a focused tab. BrowserGym fakes it (`env.py:299-327`) with
`context.expose_binding("browsergym_page_activated", ...)` plus an `add_init_script` registering capture-phase
listeners on `focus`, `focusin`, `load`, `pageshow`, `mousemove`, `mouseup`, `mousedown`, `wheel`, `keyup`,
`keydown`, `input`, `touchstart`, `touchend`, and `visibilitychange`. `_activate_page_from_js` maintains
`self.page_history` as an insertion-ordered dict used as an LRU; `_active_page_check` (`env.py:592`) recovers
by popping closed pages off that history, opening a new page if all are closed.

`_task_validate()` (`env.py:540`) snapshots `self.page` and `page_history` *before* calling `task.validate()`
and restores them after, because validators navigate. Defensive, and correct.

## 1.5 Instrumentation & replay

**Video:** `record_video_dir` → `BrowserContext(record_video_dir=.../task_video, record_video_size=viewport)`
plus a separate `chat_video/` from the `Chat`'s own context. `reset()` returns
`info["recording_start_time"]`, `info["recording_file"]`, and `info["chat"]{recording_start_time, recording_file}`,
so step timestamps can be mapped to video offsets. The code comments this as "a bit hacky".

**HAR: none.** `record_har_path` appears nowhere in the repo. No network capture at all in `core`.

**Playwright tracing: only in one benchmark adapter,** and this is the single most NetGent-relevant thing in
the whole repo:

- `browsergym/webarena_verified/.../task.py:131` — `page.context.tracing.start(snapshots=True)`
- `browsergym/webarena_verified/.../evaluators.py:100-108` — on task completion, `tracing.stop(path=trace.zip)`
  then `NetworkTrace.from_content(trace_path)` and evaluate against `expected_backend_state` /
  `expected_retrieve_value` / `expected_ui_state`.

i.e. the newest BrowserGym benchmark grades tasks **by parsing the network trace out of a Playwright
`trace.zip`**. That's exactly NetGent's substrate, used as an oracle.

**Experiment artifacts** (`experiments/loop.py`). `ExpArgs.prepare(exp_root)` creates
`<date>_<agent>_on_<task>_<seed>/` and writes `exp_args.pkl`. `ExpArgs.run()` then produces:

| Artifact | Written by |
|---|---|
| `exp_args.pkl` | `prepare()` — full pickled config, agent args + env args |
| `package_versions.txt` | `save_package_versions()` — every installed dist, `name==version` |
| `experiment.log` | `_set_logger()` — a per-experiment `FileHandler` on the root logger |
| `step_{i}.pkl.gz` | `StepInfo.save_step_info()` — gzipped pickle of the whole `StepInfo` |
| `screenshot_step_{i}.png`, `screenshot_som_step_{i}.png` | popped out of `obs` before pickling |
| `goal_object.pkl.gz` | written once; `obs["goal_object"]` set to `None` as a load-me-from-there sentinel |
| `summary_info.json` | `save_summary_info()` — `n_steps`, `cum_reward`, `cum_raw_reward`, `err_msg`, `stack_trace`, `terminated`, `truncated`, plus `stats.cum_*` / `stats.max_*` |
| `task_video/*.webm`, `chat_video/*.webm` | Playwright, if `record_video` |
| `tape.json` | opt-in `ExpResult.save_tape()` |

`StepInfo` (`loop.py:146`) holds `step, obs, reward, raw_reward, terminated, truncated, action, agent_info,
stats, profiling: StepTimestamps, task_info`. `StepTimestamps` records `env_start`, `action_exec_start`,
`action_exec_stop`, `action_exect_after_timeout`, `env_stop`, `agent_start`, `agent_stop`.

`ExpResult` (`loop.py:602`) is a lazy reader over that directory: `exp_args`, `steps_info`, `summary_info`,
`screenshots`, `screenshots_som`, `logs`, `chat_video_path`, `task_video_path`, `flat_exp_args`,
`get_exp_record()`, and a `status` property returning `"done" | "error" | "incomplete"` — derived purely from
files on disk, so a crashed or still-running experiment is legible. `yield_all_exp_results()` globs
`**/exp_args.pkl` and skips dirs starting with `_` or `.`; `_move_old_exp()` renames a re-run's old dir to
`_<name>`, which is how "hidden" dirs arise.

`ExpResult.tape` (`loop.py:690`) converts an episode into TapeAgents format. Notably it re-parses the recorded
action string with `highlevel_action_parser.parse_string(step_info.action, parse_all=True)` and emits one
`browsergym_action` step per call with `name` + `arguments` — **the only place the codebase turns a recorded
action back into structured data**. That is precisely the direction NetGent needs, and it's an afterthought here.

**What is *not* recorded, and therefore what cannot be replayed:** cookies/storage state at each step, network
activity, the DOM snapshot or AXTree (the default `obs_preprocessor` deletes `dom_object`/`axtree_object`
before they're pickled), or any element-identity mapping. You can *look at* a BrowserGym run. You cannot
re-execute it.

## 1.6 Testability

`tests/core/` — 3,000+ lines, and the best-tested layer of the three.

- `tests/conftest.py` reuses `pytest-playwright`'s fixture instance:
  `browsergym.core._set_global_playwright(playwright)` — works around
  microsoft/playwright-python#2053. Small detail, saves a lot of pain.
- **All fixtures are local `file://` pages** under `tests/core/data/`: `textbox.html`, `hover.html`,
  `dblclick.html`, `long_page.html`, `obstructed_checkbox_page.html`, `lots_of_iframes.html`,
  `basic_iframe_site/`, `basic_shadow_dom_site/`, `basic_shadow_iframe_site/`, `input_type/`. Zero network
  dependence in the core suite.
- `DISPLAY_BROWSER` env var flips `headless=False` and `slow_mo=1000` for eyeballing a failing test
  (`test_actions_highlevel.py:21-22`).
- `test_actions_highlevel.py` (1,363 lines): `test_action_parser` exercises the grammar directly (including
  every rejection case: `a(1-)`, `a(1/2)`, positional-after-keyword); `test_valid_action` / `test_invalid_action`
  cover the whole vocabulary; then behavioural tests — `test_click_through_frames`, `test_fill_through_iframe`,
  `test_iframe_bid`, `test_forced_actions` (parametrized on `retry_with_force`), `test_tab_actions`,
  `test_mouse_down_up`. `_IS_MAC_OS` branches exist for modifier keys.
- `test_observation.py` (819 lines): `test_extract_axtree_multi_iframe`, `test_simple_shadowdom`,
  `test_nested_shadowdom`, `test_dom_has_bids_no_aria` (parametrized over many pages — asserts the ARIA
  smuggling was fully cleaned up), `test_dom_to_text`, `test_axtree_to_text`,
  `test_axtree_to_text_remove_redundant`, `test_extract_focused_element_bid_through_iframes`,
  `test_extract_focused_element_bid_through_shadowdom`, `test_tags_to_mark`.
- `test_gym_envs.py`: `test_active_page` (the multi-tab callback hack), `test_max_episode_steps`,
  `test_demo_mode` (parametrized), `test_resizeable_window`.
- `tests/experiments/test_exp_loop.py`: a 15-line `MiniwobTestAgent` that regexes a bid out of `axtree_txt` and
  emits `click("<bid>")`. Full loop coverage without an LLM.

## 1.7 Judgment

**Worth stealing:**

- Frame-path-encoding element IDs (`abDb123`) + `set_test_id_attribute` rebinding. You get iframe traversal for
  free from a flat string ID, with no custom selector engine.
- Docstring examples parsed by the production parser. Prompt/parser drift becomes an import-time error.
- `HighLevelActionSetArgs` (`benchmark/base.py:26`) — the action set is itself a serializable, hashable
  dataclass with a `make_action_set()` factory. That's the right shape for something a compiler emits.
- `ExpResult` as a lazy, filesystem-derived view with a `status` property. Crash-tolerant by construction.
- The transient-error allowlist in `_get_obs`. That list is empirical knowledge you'd otherwise rediscover.
- Local `file://` test fixtures for every DOM edge case.
- `webarena_verified`'s `tracing.start(snapshots=True)` → `trace.zip` → `NetworkTrace.from_content()`.

**Benchmark-specific baggage:**

- `exec()`-ing a freshly-concatenated copy of the entire action library on every step. For an NFA replaying
  thousands of edges this is pure overhead and an un-auditable execution boundary. Compile once, or don't
  compile at all.
- The `Chat` second browser — a whole extra Chromium process for a UI channel. Irrelevant with no LLM at run time.
- `demo_mode` (animated cursors, box-shadow "wave" overlays, `page.wait_for_timeout(1000)` per highlight). It
  mutates the page and injects `setInterval` timers; for traffic capture it's contamination.
- The gym `Env`/`Space` scaffolding. `AnyDict`/`Anything`/`AnyBox` exist only to satisfy `gym.spaces` for
  values gym can't describe. NetGent has no RL consumer.
- `task.validate()` returning a reward. NetGent's terminal condition is "spec satisfied", not "scored".
- ARIA smuggling. Necessary only because you want bids inside the CDP AXTree. If NetGent's compiled NFA
  addresses elements by durable selector rather than by ephemeral ID, this whole mechanism disappears.

---

# 2. ServiceNow/AgentLab

AgentLab is the experiment harness *above* BrowserGym: agent implementations, LLM plumbing, study
orchestration, and analysis UIs. For NetGent only the reproducibility machinery is load-bearing.

## 2.1 Module map (`src/agentlab/`)

| Path | What it does |
|---|---|
| `experiments/loop.py` (962) | A **fork** of `browsergym.experiments.loop`, not a wrapper. Diffs below. |
| `experiments/study.py` (834) | `AbstractStudy`, `Study`, `SequentialStudies`, `make_study()`. A study = (agents × benchmark) → `exp_args_list`. `find_incomplete()`, `run(n_jobs, parallel_backend, strict_reproducibility, n_relaunch)`, `get_results()`, `append_to_journal()`, `Study.load()` / `load_most_recent()`. |
| `experiments/reproducibility_util.py` (374) | The provenance layer. Detailed below. |
| `experiments/exp_utils.py` (191) | `RESULTS_DIR` (env `AGENTLAB_EXP_ROOT`, else `~/agentlab_results`), `run_exp`, `_episode_timeout`, `timeout_manager` (SIGALRM-based hard wall-clock kill), `add_dependencies`, `order`, `hide_some_exp`. |
| `experiments/launch_exp.py`, `graph_execution_ray.py`, `multi_server.py` | Parallel execution: joblib or Ray, with a task-dependency DAG and per-worker server assignment. |
| `experiments/args.py` | `CrossProd`, `Choice` etc. for hyperparameter sweeps over agent args. |
| `agents/agent_args.py` | `AgentArgs` base: `set_benchmark(benchmark, demo_mode)` and **`set_reproducibility_mode()`** (raises `NotImplementedError` by default; impls set temperature 0). |
| `agents/generic_agent/reproducibility_agent.py` (308) | The replay agent. Detailed below. |
| `agents/{generic_agent,tool_use_agent,visual_agent,hitl_agent,...}` | Agent implementations. `dynamic_prompting.py` (876) is the prompt-flag system. |
| `benchmarks/abstract_env.py` | `AbstractEnv`, `AbstractEnvArgs`, `AbstractBenchmark`, `add_step_timing_to_env_info_decorator`. AgentLab's own env interface, so non-browser envs (OSWorld, GAIA) fit the same loop. |
| `benchmarks/{osworld,gaia,multitool_gym}.py` | Non-browser environments implementing that interface. |
| `analyze/agent_xray.py` (1,485) | Gradio app: browse results dir → agent → task → seed → step; screenshots, SOM overlay, AXTree, pruned HTML, chat messages, logs, stats, per-step timing. |
| `analyze/episode_to_html.py` (442) | `exp_result_to_html()` — static self-contained HTML export of an episode. |
| `analyze/overlay_utils.py` (435) | `parse_function_calls(code_string)` via `ast`, `find_bids_and_xy_pairs`, `annotate_action` — **draws the action's target bbox / xy onto the step screenshot**, colour-coded per argument, with `create_colored_html` linking the code text to the drawing. |
| `analyze/inspect_results.py` (897) | Pandas aggregation over `ExpResult.get_exp_record()`. |
| `reproducibility_journal.csv` (repo root) | Committed, append-only ledger of study results. |

### Diff vs BrowserGym's loop (`experiments/loop.py`)

- `EnvArgs` gains `pre_observation_delay`; `make_env` defaults `use_raw_page_output=True`.
- `StepTimestamps` gains six fields: `wait_for_page_loading_start/stop`, `validation_start/stop`,
  `get_observation_start/stop` — populated from `env_info` (which is why `BrowserEnv.post_step` emits them).
  Result: you can attribute wall-clock to *waiting* vs *validating* vs *observing* per step.
- Guards for non-dict `obs` (`isinstance(self.obs, dict)`), for envs without a `Chat`, and a `TapeAgent` hook.
- Drops `ExpResult.tape` (moved to `agentlab.analyze.tapes`).

## 2.2 Deterministic re-running — the actual mechanism

Two independent layers.

### (a) Provenance capture — `reproducibility_util.get_reproducibility_info()` (line 180)

Collects, before a study runs:

```
git_user, agent_names, benchmark, study_id, comment,
benchmark_version, date, os, python_version, playwright_version,
agentlab_version, agentlab_git_hash, agentlab__local_modifications,
browsergym_version, browsergym_git_hash, browsergym__local_modifications
```

The sharp edge: `add_git_info()` **raises `ValueError` if the module's working tree has uncommitted changes**,
unless `ignore_changes=True` (which is what `strict_reproducibility=False` sets). A whitelist exempts files
that always churn (`*/reproducibility_script.py`, `*reproducibility_journal.csv`, `*main.py`,
`*inspect_results.ipynb`). `_get_benchmark_version()` resolves the *benchmark's* version from its distribution
metadata, not the harness's.

`assert_compatible(info, old_info)` (line 250) compares every key except `date`/`avg_reward`/`std_err`/
`n_completed`/`n_err` and raises on any drift — used when resuming/relaunching a study.

`append_to_journal()` (line 324) appends one CSV row per agent to the git-tracked
`reproducibility_journal.csv`, joining the provenance dict with `avg_reward`, `std_err`, `n_err`, `n_completed`.
Reproducibility is treated as a **versioned, committed artifact**, not a runtime flag. That is the strongest
idea in AgentLab.

### (b) Trace replay — `ReproAgent` (`agents/generic_agent/reproducibility_agent.py`)

```python
class ReproChatModel:                       # line 35
    def __call__(self, messages):
        if len(messages) >= len(self.old_messages):
            return make_assistant_message("<action>None</action>")
        old_response = self.old_messages[len(messages)]
        time.sleep(self.delay)
        return old_response
```

`ReproAgent.get_action(obs)` (line 91) loads `step_info = ExpResult(repro_dir).get_step_info(step)`, pulls
`agent_info["chat_messages"]`, swaps in a `ReproChatModel` over them, and calls `GenericAgent.get_action`
normally. `reproduce_study(original_study_dir)` (line 156) rebuilds an entire `exp_args_list` from an old
study, one `ReproAgentArgs(_repro_dir=...)` per experiment.

Then it **measures divergence**: `_make_diff` produces a `difflib.HtmlDiff` of old vs new message strings
(viewable in xray), and `_diff_stats` (line 223) returns `{lines_added, lines_removed, difference_ratio}` as
step stats.

The key architectural point: **the LLM is replayed, the environment is re-executed live.** The agent's
*decisions* are frozen; the browser's *behaviour* is not. So the diff between old and new prompt text is a
direct measurement of environment non-determinism — same decisions, did the page come back the same? This is
an inversion worth internalizing for NetGent, whose situation is the mirror image (no LLM at run time at all,
so *only* environment non-determinism remains, and it has nothing masking it).

A backward-compat detail (line 106): if only 2 chat messages were saved, it reconstructs the third from
`step_info.action` as `<action>{recorded_action}</action>`. The recorded action string is treated as the
authoritative fallback — recording the *action* mattered more than recording the LLM response.

## 2.3 Observation / action / waiting

AgentLab adds none of these. Observation comes from `BrowserEnv`; the agent's `obs_preprocessor` decides what
persists (see `dynamic_prompting.py` for the flag matrix: `use_ax_tree`, `use_html`, `use_screenshot`,
`use_som`, `filter_visible_elements_only`, `extract_visible_tag`, `extract_coords`, …). Actions are BrowserGym
strings; `HighLevelActionSetArgs` is the serializable handle. The only timing addition is the six extra
`StepTimestamps` fields plus `EnvArgs.pre_observation_delay`.

`add_step_timing_to_env_info_decorator` (`benchmarks/abstract_env.py`) wraps any `step()` to inject
`action_exec_start` / `action_exec_stop` / `action_exec_timeout` into `env_info` if absent — the minimum
contract the loop needs from a non-BrowserGym env.

## 2.4 Instrumentation & replay artifacts

Same on-disk format as BrowserGym (AgentLab reads it with its own `ExpResult`), plus:

- Study-level: `study.pkl`, per-study `reproducibility_info`, aggregated results via `get_results()`.
- `analyze/overlay_utils.annotate_action` — draws the action target on the screenshot by `ast`-parsing the
  action string, finding `bid`-shaped and `(x, y)`-shaped arguments, and looking up
  `obs["extra_element_properties"][bid]["bbox"]`. A cheap, high-value debugging affordance: you see *where the
  action landed*, per step, without instrumenting the browser.
- `episode_to_html.exp_result_to_html` — one static HTML file per episode, `embed_images` optional.

Still: **no HAR, no tracing, no storage-state snapshots per step.**

## 2.5 Testability

`tests/` mirrors the package: `experiments/` (`test_study.py`, `test_launch_exp.py`, `test_ray.py`,
`test_reproducibility_util.py`, `test_args.py`, `test_exp_configs.py`, `test_multi_server.py`), `agents/`,
`llm/` (7 files), `analyze/` (`test_inspect_results.py`, `test_overlay_utils.py`), `benchmarks/`.
`exp_utils.MockedExpArgs` (line 133) is a fake `ExpArgs` with timestamp checks used to unit-test the
dependency-graph scheduler without launching browsers. Most agent tests are LLM-free or mock the chat model.

## 2.6 Judgment

**Worth stealing:**

- Provenance-as-committed-artifact: `reproducibility_journal.csv` + refusing to run with a dirty working tree.
  For NetGent, the analogue is: *a captured dataset row should carry the NFA hash, the compiler version, the
  Playwright version, and the browser build*, and a replay should refuse to proceed if the NFA changed.
- `assert_compatible` on resume.
- Replay-one-layer, re-execute-the-rest, then **diff and quantify** (`difference_ratio` as a per-step stat).
  NetGent should emit an equivalent per-edge divergence metric.
- `set_reproducibility_mode()` as an explicit, opt-in agent capability that raises if unsupported.
- Per-phase step timestamps (wait / validate / observe). You cannot tune a synchronization strategy you
  haven't instrumented.
- `annotate_action` — screenshot + drawn target, derived entirely from recorded data.
- SIGALRM `timeout_manager` for hard per-episode wall-clock bounds.

**Baggage:** the fork-not-wrap of `loop.py` (two copies now drift); Ray/joblib/multi-server orchestration;
the Gradio xray app; the entire `llm/` subtree (~4,000 lines) — irrelevant to a zero-LLM-at-runtime system;
`dynamic_prompting.py`'s flag matrix, which exists to ablate prompts.

---

# 3. web-arena-x/webarena (`browser_env/`)

The oldest of the three (2023 lineage) and the least polished — but it is the only one with a **typed,
serializable, parseable, comparable** action representation. For NetGent that makes it the most directly
relevant.

## 3.1 Module map

| File | LOC | What it does |
|---|---:|---|
| `actions.py` | 1,586 | `Action` TypedDict, `ActionTypes` IntEnum, `get_action_space()`, ~18 `create_*_action()` builders, `action2str`, `action2create_function`, `is_equivalent`, `execute_action` + ~15 `execute_*` primitives, async `aexecute_*` twins, `parse_playwright_code`, `create_playwright_action`, `create_id_based_action`, `ActionParsingError`. |
| `processors.py` | 732 | `ObservationProcessor` ABC, `TextObervationProcessor` [sic], `ImageObservationProcessor`, `ObservationHandler`, `ObservationMetadata`, `create_empty_metadata`. |
| `envs.py` | 269 | `ScriptBrowserEnv(gym.Env)`, `PlaywrightScript` dataclass + `parse_action` (a vestigial second parser). |
| `async_envs.py` | 153 | `AsyncScriptBrowserEnv` — async twin, image-only observations. |
| `auto_login.py` | 159 | Cookie/session-state minting: `renew_comb`, `is_expired`, `get_site_comb_from_filepath`, `main`. |
| `constants.py` | 295 | `ROLES` (85 ARIA roles), `SPECIAL_LOCATORS` (`alt_text`/`label`/`placeholder`), `SPECIAL_KEYS`, `SPECIAL_KEY_MAPPINGS`, `ASCII_CHARSET`, `FREQ_UNICODE_CHARSET`, `PLAYWRIGHT_LOCATORS`, `PLAYWRIGHT_ACTIONS`, `IGNORED_ACTREE_PROPERTIES`, and every `*_MAX_LENGTH` bound. |
| `utils.py` | 80 | `DetachedPage`, `StateInfo`, `AccessibilityTreeNode`, `DOMNode`, `BrowserConfig`, `BrowserInfo`, `png_bytes_to_numpy`. |
| `trajectory.py` | 6 | `Trajectory = list[Union[StateInfo, Action]]`. Six lines, and it's the right abstraction: a trajectory is an *alternating* state/action tape. |
| `helper_functions.py` | 191 | `RenderHelper` (writes `render_{task_id}.html`), `get_render_action`, `get_action_description`. |
| `env_config.py` | 51 | Site URLs from env vars (asserts all present), `ACCOUNTS`, `URL_MAPPINGS`. |

Outside `browser_env/`: `run.py` (the eval loop), `agent/agent.py` (`TeacherForcingAgent`, `PromptAgent`),
`evaluation_harness/`, `scripts/` (`collect_obs.py`, `generate_test_data.py`, `check_error_runs.py`).

## 3.2 Action system — the interesting one

### `Action` is a flat, fixed-schema TypedDict (`actions.py:94`)

```python
class Action(TypedDict):
    action_type: int              # ActionTypes
    coords: npt.NDArray[np.float32]
    element_role: int             # index into ROLES + SPECIAL_LOCATORS
    element_name: str
    text: list[int]               # per-character indices into _id2key
    page_number: int
    url: str
    nth: int
    element_id: str
    direction: str
    key_comb: str
    pw_code: str
    answer: str
    raw_prediction: str
```

**Every action carries every field.** There is no union, no per-type payload. `create_none_action()`
(line 428) returns the all-zeros/empty instance and every other builder is
`action = create_none_action(); action.update({...}); return action`. Crude, but it makes the type trivially
serializable and gym-space-describable.

`get_action_space()` (line 352) returns a `gymnasium.spaces.Dict` with `Discrete`, `Box`, `Text`,
`MultiDiscrete` per field. That's why `text` is `list[int]` rather than `str`: `_key2id` / `_id2key`
(line 326) index over `SPECIAL_KEYS + ASCII_CHARSET + FREQ_UNICODE_CHARSET + ["\n"]` so typing fits a
`MultiDiscrete(TYPING_MAX_LENGTH)`. This is pure RL-framework tax and the thing most worth *not* copying —
it makes every action carry an encoding/decoding step for no benefit outside gym.

### `ActionTypes(IntEnum)` (line 240) — 18 members, deliberately layered

```
NONE=0
SCROLL=1  KEY_PRESS=2                        # universal
MOUSE_CLICK=3  KEYBOARD_TYPE=4  MOUSE_HOVER=5 # low level (coordinates)
CLICK=6  TYPE=7  HOVER=8                      # mid level (element-addressed)
PAGE_FOCUS=9  NEW_TAB=10  GO_BACK=11  GO_FORWARD=12  GOTO_URL=13  PAGE_CLOSE=14   # page level
CHECK=15  SELECT_OPTION=16                    # high level (Playwright-only)
STOP=17
```

`__str__` returns `"ACTION_TYPES.CLICK"`. The tiering — low (coords) / mid (element) / high (Playwright
locator) — is exactly the axis a compiled NFA cares about: each tier has a different determinism profile.

### Three serialization directions

1. **`action2str(action, action_set_tag, semantic_element)`** (line 112) → human/prompt string:
   `"click [12] where [12] is <button 'Submit'>"`, `"type [3] [hello] where …"`, `"scroll [down]"`,
   `"press [Enter]"`, `"goto [url]"`, `"stop [answer]"`.
2. **`action2create_function(action)`** (line 163) → **Python source that reconstructs the action**:
   `"create_click_action(element_id='12', element_role='button', element_name='Submit', pw_code='')"`.
   A round-trippable textual form. This is the closest thing in any of the three repos to a serialized,
   re-executable action.
3. **Parsers, string → `Action`:**
   - `create_id_based_action(action_str)` (line 1504) — regex per verb over the DSL the agent emits:
     `click [12]`, `hover [12]`, `type [3] [text] [1]` (trailing `[0]/[1]` = press-Enter flag; defaults to
     `[1]`, appending `"\n"` to the text), `press [Ctrl+a]`, `scroll [down]`, `goto [url]`, `new_tab`,
     `go_back`, `go_forward`, `tab_focus [2]`, `close_tab`, `stop [answer]`. Raises `ActionParsingError`.
   - `create_playwright_action(playwright_code)` (line 1431) — takes real Playwright source
     (`page.get_by_role("button", name="Submit").click()`), splits the chain on `r"\.(?![^\(\)]*\))"` (a dot
     not inside parens), matches the **last** call to pick the action type, and stores the whole string in
     `pw_code`.
   - `parse_playwright_code(code)` (line 1362) — the validator. Must start with `"page."`. Splits the chain,
     `ast.parse`es each segment, extracts `(function_name, arguments, keywords)` into `ParsedPlaywrightCode`,
     and **whitelists** every name against `PLAYWRIGHT_LOCATORS + PLAYWRIGHT_ACTIONS`, requiring the final
     call to be an action. `locate(locator_calls, page)` (line 970) then rebuilds the chain by reflection:
     `locator = getattr(locator, fn)(*args, **kwargs)`.

That last pair is the single most reusable idea for NetGent: **a Playwright locator chain stored as a
validated, structured list of `{function_name, arguments, keywords}`, replayed by `getattr` reflection against
a whitelist** — no `exec`, no code generation, JSON-serializable end to end.

### `is_equivalent(a, b)` (line 277)

Per-type structural equality:

| Type | Equality rule |
|---|---|
| `SCROLL` | direction normalized to up/down |
| `KEY_PRESS` | `key_comb` |
| `MOUSE_CLICK` / `MOUSE_HOVER` | `np.allclose(coords)` |
| `KEYBOARD_TYPE` | `text` |
| `CLICK` / `HOVER` / `TYPE` | **first available of**: `element_id`, else `(element_role, element_name)`, else `pw_code`; if none → `False` |
| `GOTO_URL` | `url` |
| `PAGE_FOCUS` | `page_number` |
| `CHECK` / `SELECT_OPTION` | `pw_code` |
| `STOP` | `answer` |
| `NEW_TAB` / `GO_BACK` / `GO_FORWARD` / `PAGE_CLOSE` | always `True` |

Used in `run.py`'s `early_stop()` for loop detection: if the last *k* actions are all equivalent, abort; for
`TYPE`, if the same typing action appears ≥ k times anywhere in the trajectory, abort. Directly tested in
`tests/test_browser_env/test_actions.py::test_is_equivalent`, which exhaustively iterates
`ActionTypes.__members__` against `create_random_action()` pairs.

The fallback ladder (`element_id` → role+name → `pw_code`) is a **precedence order over addressing schemes**,
and it appears twice more — in `execute_action` and implicitly in the builders. That ladder is the design
NetGent needs, just with the tiers reordered for durability.

### `execute_action(action, page, browser_ctx, observation_processor)` (line 1098)

One `match` over `action_type`. For `CLICK`/`HOVER`/`TYPE` it walks the same ladder:

```python
if action["element_id"]:
    center = observation_processor.get_element_center(element_id)   # cached bbox from THIS observation
    execute_mouse_click(center[0], center[1], page)                 # normalized viewport coords
elif action["element_role"] and action["element_name"]:
    execute_focus(role, name, nth, page); execute_click_current(page)
elif action["pw_code"]:
    execute_playwright_click(locator_code=parse_playwright_code(pw_code)[:-1], page=page)
else:
    raise ValueError("No proper locator found for click action")
```

Three things to note:

- **`element_id` clicks are coordinate clicks.** `get_element_center` (`processors.py:641`) reads
  `obs_nodes_info[element_id]["union_bound"]`, computes the centre, and divides by viewport size. The action
  is then executed as `page.mouse.click(x*w, y*h)`. So an id-addressed action is only valid against the
  observation it was generated from — it is fundamentally not replayable across runs.
- **`execute_focus`** (line 898) is the role+name path: for every frame, `get_by_role(role, name=name)` (or
  `get_by_alt_text` / `get_by_label` / `get_by_placeholder` for the three `SPECIAL_LOCATORS`), keep locators
  passing `is_in_viewport(locator, viewport, threshold=0.3)`, sort **row-major** by `(y, x)`, take `nth`,
  `.focus()`. Then `execute_click_current` does `page.locator("*:focus").click()`, falling back to scanning
  `page.frames[1:]`. Viewport-relative and ordering-sensitive — but it *is* a semantic addressing scheme.
- `execute_type` clicks the element then `page.keyboard.type(text)` — it does not `fill()`. Combined with the
  `[1]` enter-flag appending `"\n"`, a "type" is genuinely a keystroke sequence.

Every sync primitive has an `aexecute_*` twin. `aexecute_action` raises `NotImplementedError` for every
`element_id` branch — the async path never got the observation-processor wiring.

## 3.3 Observation pipeline

`ObservationHandler` (`processors.py:668`) owns a `TextObervationProcessor` and an
`ImageObservationProcessor` and exposes `get_observation(page, client) -> {"text": ..., "image": ...}`,
`get_observation_metadata()`, and `action_processor` (whichever processor the action space addresses).

### `TextObervationProcessor.process()` (line 583)

1. Build a tab-title header: `"Tab 0 (current): Title | Tab 1: Title"`.
2. `fetch_browser_info(page, client)` (line 62):
   - CDP `DOMSnapshot.captureSnapshot({computedStyles: [], includeDOMRects: True, includePaintOrder: True})`
   - a **bounds calibration hack**: `n = bounds[0][2] / viewport_width`, then divide every bound by `n`
     ("in some cases, the bounds are scaled somehow")
   - window metrics via `page.evaluate`: `pageYOffset`, `pageXOffset`, `screen.width`, `screen.height`,
     `devicePixelRatio` — with `assert device_pixel_ratio == 1.0`. Hi-DPI is simply unsupported.
   - Wrapped in a `try` whose `except` does `page.wait_for_load_state("load", timeout=500)` and retries once.
     That is the *entire* page-readiness strategy in the observation path.
3. Then either the HTML or the AXTree branch.

**HTML branch** — `fetch_page_html` (line 174) flattens the snapshot into `DOMNode` dicts, and for *every
node* calls `get_bounding_client_rect(client, backendNodeId)` (line 110), which is CDP `DOM.resolveNode` +
`Runtime.callFunctionOn` evaluating `getBoundingClientRect()` (with a `document.createRange()` special case
for text nodes). **Two CDP round-trips per DOM node per observation.** On a real page that is thousands of
round-trips. This is the single worst performance decision in the batch.

`current_viewport_only` then prunes: nodes with no bound, zero width/height, or
`get_element_in_viewport_ratio(...) < 0.6` are removed via `remove_node_in_graph`, which **splices children
into the parent's `childIds` at the removed node's index** and marks the node `parentId = "[REMOVED]"`. Tree
surgery that preserves document order — worth noting as a technique.

`parse_html` (line 321) DFS-prints `[{cursor}] <tag attrs> value` and records
`obs_nodes_info[cursor] = {backend_id, union_bound, text}`.

**AXTree branch** — `fetch_page_accessibility_tree` (line 363): CDP `Accessibility.getFullAXTree({})`
(**main frame only** — no per-frame merge, unlike BrowserGym), dedupe repeated `nodeId`s, then the same
per-node `get_bounding_client_rect` cost, then the same viewport pruning. `parse_accessibility_tree`
(line 473) prints `[{nodeId}] Role 'name' prop: value`, dropping `IGNORED_ACTREE_PROPERTIES` and
invalidating empty generic nodes (`generic`, `img`, `list`, `strong`, `paragraph`, `banner`, `navigation`,
`Section`, `LabelText`, `Legend`, `listitem`). `clean_accesibility_tree` (line 560) drops a `StaticText`
line whose content already appears in any of the previous 3 lines.

### Element ID stability — the crucial contrast with BrowserGym

WebArena's `element_id` is:

- **HTML mode:** the node's index in the flattened `dom_tree` array.
- **AXTree mode:** the CDP `nodeId` string of the AX node.

Both are **regenerated from scratch on every observation**, and both are only meaningful via
`obs_nodes_info`, which the processor overwrites each `process()` call. There is no marking, no injected
attribute, no persistence. `MAX_ELEMENT_ID = 1000` is just a gym-space bound.

Consequence: a WebArena action referencing `element_id` is bound to exactly one observation. Replay is
impossible by construction. BrowserGym's bids are strictly better (stable within a page instance, frame-path
encoded) — and still not good enough for cross-run replay.

### `ImageObservationProcessor` (line 653)

`png_bytes_to_numpy(page.screenshot())`; on exception, `page.wait_for_event("load")` then retry. That's it.
No CDP, no scale factor, no SOM overlay.

## 3.4 Waiting / synchronization

Essentially absent, and the code says so:

```python
# hard sleep TODO[shuyanzh] suboptimal, may need to check network
if self.sleep_after_execution > 0:
    time.sleep(self.sleep_after_execution)
```
(`envs.py:250-252`, and the same block in `reset()` at line 210.)

The complete inventory of waits in `browser_env/`:

| Location | Wait |
|---|---|
| `envs.py:210,251` | `time.sleep(sleep_after_execution)` — CLI default **0.0** |
| `processors.py:605` | `page.wait_for_load_state("load", timeout=500)` — only as a retry after `fetch_browser_info` throws |
| `processors.py:663` | `page.wait_for_event("load")` — only after `page.screenshot()` throws |
| `actions.py:883` | `await page.wait_for_load_state("load")` — async click path only |
| `auto_login.py:48` | `time.sleep(1)` |

Playwright's auto-waiting inside `locator.click()` etc. does the real work; the env layer adds nothing. There
is no per-state readiness predicate anywhere — which is exactly the gap NetGent's state triggers must fill.

## 3.5 Instrumentation & replay

**Playwright tracing** (`envs.py:148-149`, `223-225`) — the only first-class capture in this batch:

```python
if self.save_trace_enabled:
    self.context.tracing.start(screenshots=True, snapshots=True)
...
def save_trace(self, trace_path): 
    if self.save_trace_enabled: self.context.tracing.stop(path=trace_path)
```

Enabled by `run.py --save_trace_enabled`; `run.py` writes `{result_dir}/traces/{task_id}.zip`.
`screenshots=True, snapshots=True` gives the Trace Viewer's time-travel DOM. **No `record_har_path`**, though
a Playwright trace does carry network entries — which is precisely what
`browsergym/webarena_verified` later exploits via `NetworkTrace.from_content(trace.zip)`.

**`storage_state` as the reproducible starting condition.** `ScriptBrowserEnv.setup(config_file)` reads a
task JSON containing `storage_state`, `start_url` (multiple URLs joined by `" |AND| "` → one tab each), and
`geolocation`, and passes `storage_state` straight to `browser.new_context()`. `auto_login.py` mints those
files: `renew_comb(comb)` logs into each site combination with hardcoded `ACCOUNTS` credentials via ordinary
Playwright calls and dumps `context.storage_state(path=f"{auth_folder}/{'.'.join(comb)}_state.json")`;
`is_expired(storage_state, url, keyword, url_exact)` validates freshness by loading a URL in a throwaway
context and checking the final URL or a keyword in the content; `main()` runs all singles and pairs across an
8-worker `ThreadPoolExecutor` and asserts none are expired. `run.py` (lines ~250-270) shells out to
`browser_env/auto_login.py --auth_folder <tmpdir> --site_list <comb>` **per task**, rewrites the config to
point at the fresh file, and asserts it exists. Sessions are minted fresh, not reused.

**Trajectory + rendering.** `Trajectory = list[StateInfo | Action]` (alternating tape).
`StateInfo = {"observation": {...}, "info": {...}}` where `info` carries
`DetachedPage(url, content)` (the full HTML at that step), `fail_error`, and `observation_metadata`
(i.e. `obs_nodes_info`). `RenderHelper` (`helper_functions.py`) appends to `render_{task_id}.html` per step:
URL, text observation, optional base64 screenshot, previous action description, and — via
`get_render_action` — the raw prediction, `repr(action)`, and `action2str(...)`.

**Replay: `TeacherForcingAgent`** (`agent/agent.py:47`). This is the replay engine:

```python
def reset(self, test_config_file):
    ref = json.load(open(test_config_file))["reference_action_sequence"]
    self.set_action_set_tag(ref["action_set_tag"])
    self.set_actions(ref["action_sequence"])

def set_actions(self, action_seq):
    for a_str in action_seq.strip().split("\n"):
        cur_action = (create_playwright_action(a_str) if tag == "playwright"
                      else create_id_based_action(a_str))
        cur_action["raw_prediction"] = a_str
        ...
def next_action(self, trajectory, intent, meta_data): return self.actions.pop(0)
```

A task config can embed `reference_action_sequence = {action_set_tag, action_sequence}`, and the harness will
execute it with zero model calls. **This is structurally what NetGent's runtime is** — a recorded, typed
action sequence replayed against a live browser — and it is ~30 lines. Its weakness is exactly the one NetGent
must fix: `create_id_based_action` produces `element_id`s, which resolve through the *current* observation's
`obs_nodes_info` and therefore silently mis-click if the page changed. The `"playwright"` tag is the sound
one, because `pw_code` addresses semantically.

## 3.6 Testability

`tests/test_browser_env/` (827 lines) + `tests/conftest.py`.

`conftest.py` defines five function-scoped fixtures, each a differently-configured env
(`script_browser_env`, `current_viewport_script_browser_env`, `accessibility_tree_script_browser_env`,
`accessibility_tree_current_viewport_script_browser_env`, and an async one), each `yield`ing then closing —
explicitly so a failed test doesn't leak a browser.

- `test_actions.py` — pure unit tests of `is_equivalent` over `ActionTypes.__members__` × `create_random_action()`.
- `test_playwright_actions.py` — `create_playwright_action` end-to-end against **live public sites**
  (`demo.playwright.dev/todomvc`, `littlewebhut.com` for iframes). One test `@pytest.mark.skip`ped
  "not important, but the site is flaky" — a candid admission of the cost of this choice.
- `test_script_browser_env.py` — env-level, also live (`example.com` → `rfc-editor.org`), plus
  `gymnasium.vector.AsyncVectorEnv` usage.
- `test_auth_cookie.py` — writes a `storage_state` JSON to `/tmp`, resets with it, asserts the session took
  (`saucedemo.com`).
- `test_action_functionalities.py` (331 lines) — per-action behaviour.

Contrast with BrowserGym: WebArena tests against the live internet and is correspondingly flaky; BrowserGym
tests against `file://` fixtures and isn't. For NetGent, BrowserGym's choice is obviously right for the
determinism layer — with a small live-site suite kept separate and allowed to be flaky.

## 3.7 Judgment

**Worth stealing:**

- The typed action object itself: `ActionTypes` enum + per-type `create_*` builders + `action2str` +
  `action2create_function` + `is_equivalent`. That is a complete, tested action IR.
- The **tiering** (coords / element / Playwright-locator) as an explicit axis, and the **precedence ladder**
  through it at execution time.
- `parse_playwright_code` → `list[ParsedPlaywrightCode]` → `locate()` by reflection against a whitelist.
  Structured, JSON-serializable, `exec`-free locator chains. This is the best single idea in the batch.
- `is_equivalent` for loop/repeat detection — an NFA that can't tell "I did this already" will spin.
- `Trajectory = list[StateInfo | Action]` — the alternating tape as the canonical recording format.
- `auto_login.py`'s whole shape: mint `storage_state` per site-combination, **validate freshness with a
  cheap probe**, refresh per run into a tempdir. Directly reusable for NetGent's authenticated captures.
- `context.tracing.start(screenshots=True, snapshots=True)` as the default capture.
- `remove_node_in_graph`'s child-splicing tree surgery.

**Baggage / anti-patterns:**

- Encoding text as `list[int]` via `_key2id` to satisfy `MultiDiscrete`. Pure gym tax.
- One flat `Action` TypedDict with every field always present. Serializable, but unvalidatable — nothing stops
  a `SCROLL` carrying a `url`. A tagged union / discriminated `pydantic` model gets the same serializability
  with real validation.
- `get_bounding_client_rect` per node via two CDP round-trips. Use `DOMSnapshot`'s `layout.bounds` (as
  BrowserGym does) instead.
- Ordinal `element_id`s regenerated per observation. Non-replayable by construction.
- `assert device_pixel_ratio == 1.0` and the `bounds[0][2] / viewport_width` calibration fudge.
- `reward = float(success)` — "the action didn't throw" is not task success.
- Live-internet tests.
- Duplicated sync/async implementations of every primitive, with the async one already incomplete.

---

# 4. Cross-cutting comparison

| Dimension | BrowserGym | AgentLab | WebArena |
|---|---|---|---|
| Action representation | `str` (`Unicode()` space) | inherits BrowserGym | `Action` TypedDict + `ActionTypes` IntEnum |
| Action → execution | parse → **generate Python source** → `exec()` | inherits | `match action_type` dispatch, direct Playwright calls |
| Action serializable to JSON | no (string only) | no | **yes** (flat dict; `np.float32` coords aside) |
| Action parseable from string | yes (pyparsing, Python-call syntax) | yes | **yes, two dialects** (`click [12]` DSL; `page.…` Playwright code) |
| Action comparable | no | no | **yes** (`is_equivalent`) |
| Element identity | injected `bid` attribute, frame-path encoded, stable within page instance | inherits | ordinal index / AX `nodeId`, regenerated every observation |
| DOM source | CDP `DOMSnapshot.captureSnapshot` | inherits | CDP `DOMSnapshot` + per-node `DOM.resolveNode`+`Runtime.callFunctionOn` |
| AXTree source | CDP `Accessibility.getFullAXTree` **per frame, merged** | inherits | CDP `getFullAXTree`, main frame only |
| Screenshot | CDP `Page.captureScreenshot` + `Emulation.setDeviceMetricsOverride` (hi-DPI) | inherits | `page.screenshot()` |
| Injected JS | `frame_mark_elements.js` / `frame_unmark_elements.js` | — | none |
| Waiting | 0.5 s sleep + `cookies()` flush + `domcontentloaded` per page & per frame (3 s, swallowed) | + 6 phase timestamps | `time.sleep(sleep_after_execution)` (default 0) |
| Condition waiting | none (except chat) | none | none |
| Video | Playwright `record_video_dir` (task + chat) | inherits | none |
| Playwright tracing | only `webarena_verified` adapter | — | **first-class** (`save_trace_enabled`) |
| HAR | none | none | none |
| Network capture | via `trace.zip` → `NetworkTrace.from_content` (`webarena_verified`) | — | via `trace.zip` (unused) |
| Session state | `pw_context_kwargs={"storage_state": ...}` | `EnvArgs.storage_state` | `storage_state` in task config + `auto_login.py` minting/validation |
| Per-step artifacts | `step_{i}.pkl.gz` + PNG + `summary_info.json` | same + phase timings | `render_{task_id}.html` + `DetachedPage.content` in `info` |
| Replay mechanism | none | `ReproAgent` — replays LLM, re-executes env, diffs | `TeacherForcingAgent` — replays typed action list, no LLM |
| Provenance | `package_versions.txt` | **git hashes + dirty-tree refusal + committed CSV journal** | none |
| Tests | `file://` fixtures, ~3k lines, thorough | unit + mocked scheduler | live internet, flaky |

---

# 5. Lessons for NetGent v2

Ordered by how much they change the design.

### 5.1 Make the action a validated, tagged union — WebArena's IR, not its encoding

`ActionTypes` + `create_*` + `is_equivalent` + `action2str` is the right skeleton, and NetGent should adopt it
almost wholesale. But fix the two things WebArena got wrong:

- Replace the flat "every field always present" TypedDict with a **discriminated union** (pydantic
  `Field(discriminator="type")` or a tagged dataclass hierarchy). Same JSON serializability, plus validation —
  a `Scroll` cannot carry a `url`, and a malformed compiled NFA fails at load, not at edge 400.
- Drop `_key2id`/`MultiDiscrete` entirely. Text is `str`. There is no gym consumer.

Keep, verbatim in spirit:
- `is_equivalent` — needed for NFA self-loop detection and for diffing a replay against its recording.
- `action2str` — needed for logs, dataset labels, and human-readable NFA dumps.
- The tiering: NetGent's tiers should be **`selector` (durable) → `role+name+nth` (semantic) → `coords`
  (last resort)**, i.e. WebArena's ladder inverted so that the *most* durable addressing wins.

### 5.2 Store locator chains as structured data, replay by reflection — never `exec`

`parse_playwright_code` → `list[ParsedPlaywrightCode{function_name, arguments, keywords}]` → `locate()` via
`getattr(locator, fn)(*args, **kwargs)` against `PLAYWRIGHT_LOCATORS + PLAYWRIGHT_ACTIONS`
(`webarena/browser_env/actions.py:970`, `1362`) is the single most transplantable design in this batch.

```json
{"type": "click",
 "locator": [{"fn": "get_by_role", "args": ["button"], "kwargs": {"name": "Submit"}},
             {"fn": "nth",         "args": [0],        "kwargs": {}}],
 "timeout_ms": 5000}
```

This is JSON-serializable, diffable, hashable (→ NFA edge identity), auditable, and executes with no code
generation and no `exec`. Compare BrowserGym, which re-inlines and `exec`s ~700 lines of action-library source
on **every step** (`highlevel.py:346-381`, `488-530`) — an un-auditable boundary and needless overhead at
NFA-replay scale. The compiler emits the JSON; the runtime walks it; the whitelist is the security boundary.

### 5.3 Element identity is the load-bearing decision — and neither repo solves it

- WebArena: ordinal indices, regenerated per observation → **replay impossible**.
- BrowserGym: injected `bid` attributes on `window`-scoped counters → stable within a page instance,
  **reset by every navigation**, and the ARIA-smuggling required to surface them into the AXTree
  *mutates the live page*.

For NetGent, whose product is the network traffic, page mutation during observation is a contamination
source, and any ID scheme keyed to a page instance is useless in a compiled NFA. So:

- **Compile time (LLM present):** use marking freely. Inject bids, extract DOM + merged AXTree + SOM, let the
  LLM see everything. Then *resolve* each chosen element into a durable locator chain — `get_by_role`,
  `get_by_test_id`, `get_by_label`, stable attribute selectors — and store **that**, plus enough fingerprint
  (role, accessible name, tag, text, a bbox for sanity-checking) to detect drift at replay.
- **Run time (no LLM):** no injection, no marking, no ARIA rewriting. Resolve the stored chain, verify the
  fingerprint, act. If the fingerprint mismatches → a typed `ElementDriftError` on that NFA edge, not a silent
  mis-click.

BrowserGym's frame-path bid encoding (`get_elem_by_bid`, `action/utils.py:6`) is still worth borrowing *as a
shape*: encode the iframe path into the stored locator so replay traverses frames deterministically without a
search. And `pw.selectors.set_test_id_attribute(...)` (`env.py:259`) is the clean way to bind a custom
attribute if NetGent ever controls the page.

### 5.4 State triggers are the gap all three leave open — build the thing they don't have

The entire synchronization strategy across all three repos is: a fixed sleep, then `domcontentloaded`, with
failures swallowed.

| | BrowserGym | WebArena |
|---|---|---|
| | `sleep(0.5)` + `context.cookies()` flush + `domcontentloaded` per page/frame @3 s, exceptions passed | `sleep(sleep_after_execution)`, default 0 |

Nobody waits on a *condition*. NetGent's NFA states are exactly conditions, so the trigger primitive is the
core innovation and there is no prior art here to copy — only two things to steal around the edges:

- **BrowserGym's `_wait_dom_loaded` iterating `page.frames`, not just the page** (`env.py:563`). Whatever
  predicate NetGent evaluates, evaluate it per-frame.
- **BrowserGym's `context.cookies()` callback-flush hack** (`env.py:490`). If NetGent uses `expose_binding`
  for in-page trigger signalling, it will hit the same pending-callback problem.

Design the trigger as a composable predicate — URL pattern ∧ selector present ∧ AX node with role+name ∧
network-quiet-for-N-ms — evaluated on a polling loop with an explicit timeout, and record *which* conjunct
fired and how long it took. That last part is what makes a flaky trigger debuggable. A network-quiescence
conjunct is uniquely available to NetGent, since it is already listening to the network.

### 5.5 Capture the network from the start — it is the product

None of the three sets `record_har_path`. Two use `context.tracing.start(screenshots=True, snapshots=True)`
(`webarena/browser_env/envs.py:149`; `browsergym/webarena_verified/.../task.py:131`), and the newest
BrowserGym benchmark grades tasks by `NetworkTrace.from_content(trace.zip)`
(`webarena_verified/.../evaluators.py:108`). Direction of travel is clear.

For NetGent: capture **both**, they answer different questions.
- `record_har_path` on the context → the dataset artifact: clean, standard, parseable, shippable.
- `context.tracing.start(screenshots=True, snapshots=True)` → the debugging artifact: time-travel DOM aligned
  to the same timeline, which is how you diagnose "edge 12 fired at the wrong moment."

Then **align them to NFA edges**, which nothing here does: record `edge_id`, `state_id`, and monotonic
start/stop timestamps per edge, so HAR entries can be attributed to the edge that caused them. BrowserGym's
`StepTimestamps` + `recording_start_time` (`loop.py:134-143`, `env.py:402-408`) is the pattern — it exists
purely so video frames can be sliced per step. Do the same for HAR entries, and it becomes trivial to answer
"which requests did this workflow step generate?" That is the dataset's actual value.

Also copy BrowserGym's `re.match("TimeoutError: Timeout ([0-9]+)ms exceeded.", ...)` trick in spirit
(`env.py:462`): subtract dead time from the edge's window so a timed-out edge doesn't smear its neighbours'
traffic — but get the number from a structured exception, not a regex over a message string.

### 5.6 Sessions: mint, validate, refresh — WebArena's `auto_login.py` shape

`auto_login.py` is small and exactly right for authenticated capture:

- `renew_comb(comb)` → login flow → `context.storage_state(path=...)`, one file per site *combination*
  (so multi-site tasks get one context with all sessions).
- `is_expired(storage_state, url, keyword, url_exact)` → **a cheap probe that validates freshness before the
  run** by loading a URL in a throwaway context and checking the landing URL or a content keyword.
- `run.py` re-mints into a tempdir per task and asserts the file exists.

For NetGent this maps to: a `sessions/` layer with per-site login NFAs (compiled once), storage-state files as
the durable output, a freshness predicate per site, and automatic re-mint on failure. Do **not** copy the
hardcoded credentials in `env_config.py:ACCOUNTS`.

### 5.7 Reproducibility as an artifact, not a flag — AgentLab's journal

`get_reproducibility_info()` (`reproducibility_util.py:180`) captures git hashes of *both* the harness and the
environment library, refuses to run with a dirty working tree (unless `strict_reproducibility=False`), records
`playwright_version` / `python_version` / OS / benchmark version, and `append_to_journal()` writes it to a
**git-tracked** `reproducibility_journal.csv`. `assert_compatible()` blocks incompatible resumes.

NetGent's analogue: every captured dataset directory carries a manifest with

```
nfa_hash, spec_hash, compiler_version, netgent_version, netgent_git_hash,
playwright_version, chromium_build, os, python_version, date, target_site_probe_result
```

and a replay refuses to proceed against a changed `nfa_hash` unless explicitly forced. A traffic dataset whose
provenance you can't reconstruct is not a dataset.

### 5.8 Record enough to re-execute — which none of them do

BrowserGym's default `obs_preprocessor` **deletes `dom_object` and `axtree_object`** before pickling
(`experiments/agent.py:19-20`), so the richest observation data never reaches disk. WebArena keeps
`DetachedPage(url, content)` in `info` but its `element_id`s are dead the moment the observation is replaced.

NetGent should record per NFA edge:

| Field | Why |
|---|---|
| `edge_id`, `from_state`, `to_state` | attribution |
| serialized action (the §5.1 union) | the thing being replayed |
| resolved locator chain + element fingerprint | drift detection |
| trigger predicate + which conjunct fired + latency | flaky-trigger diagnosis |
| `t_start`, `t_end` (monotonic) | HAR/trace slicing |
| URL before / after, storage-state hash | state verification |
| screenshot (optional), outcome, error | debugging |

Then follow BrowserGym's `ExpResult` (`loop.py:602`): a **lazy, filesystem-derived reader** with a `status`
property computed from which files exist, so a crashed run is still legible. And follow `ExpResult.tape`
(`loop.py:690`) — the one place BrowserGym turns a recorded action *back* into structured
`{name, arguments}` — except make that the primary format rather than an export.

### 5.9 Test against `file://` fixtures

BrowserGym's core suite (`tests/core/data/`: `basic_iframe_site/`, `basic_shadow_dom_site/`,
`basic_shadow_iframe_site/`, `lots_of_iframes.html`, `obstructed_checkbox_page.html`, `long_page.html`,
`input_type/`) is entirely local, and its 3,000 lines of tests are correspondingly stable. WebArena tests
against `demo.playwright.dev` and `littlewebhut.com` and has a test skipped as
`"not important, but the site is flaky"`.

For a determinism engine this is not a close call. Build a `tests/fixtures/` of local pages covering: nested
iframes, shadow DOM, iframe-inside-shadow-DOM, delayed/async content, SPA route changes without navigation,
autocomplete menus, obstructed/overlaid elements, infinite scroll, and — NetGent-specific — pages that fire
known request patterns so HAR assertions are exact. Keep a small, separately-marked live-site suite; let it be
flaky; never gate CI on it.

Steal two more test details: BrowserGym's `conftest.py` reusing `pytest-playwright`'s Playwright instance
(`browsergym.core._set_global_playwright(playwright)`, working around playwright-python#2053), and the
`DISPLAY_BROWSER` env var that flips `headless=False, slow_mo=1000` for eyeballing a failure.

### 5.10 Replay-and-diff is the correctness harness

`ReproAgent` freezes the LLM and re-executes the environment, then reports `difference_ratio` per step
(`reproducibility_agent.py:223`). NetGent has no LLM at run time, so *every* divergence between two runs of
the same NFA is environment non-determinism — the exact quantity the project needs to measure and minimize.

Build "run the same NFA twice, diff the traces" as a first-class command, reporting per edge: did the trigger
fire, at what latency, did the locator resolve to the same fingerprint, and how similar was the resulting HAR
(request count, URL multiset, method/status distribution). AgentLab's `_diff_stats` shape —
`{lines_added, lines_removed, difference_ratio}` as a *step stat* rather than a report — is right: the
divergence metric belongs in the recorded data, not in a separate analysis pass.

And borrow `annotate_action` (`analyze/overlay_utils.py:341`) — parse the recorded action, look up the target
bbox, draw it on the step screenshot. Derived entirely from recorded data, costs nothing at run time, and
turns "edge 12 mis-clicked" from a hypothesis into a picture.

### 5.11 Things to explicitly not carry over

- **The gym `Env`/`Space` scaffolding.** `Unicode()`, `AnyDict`, `Anything`, `AnyBox`, `MultiDiscrete` text
  encoding, `spaces.Dict` observation spaces — all of it exists to satisfy a Gymnasium contract NetGent has no
  consumer for. It actively distorts the action type (§5.1).
- **Code generation + `exec` as the execution boundary** (`highlevel.py:488` → `base.py:execute_python_code`).
  Structured dispatch instead (§5.2).
- **Demo mode** (`action/utils.py:96-278`) — animated SVG cursors, box-shadow overlays, `setInterval` timers,
  `page.wait_for_timeout(1000)` per highlight. It mutates the page, injects timers, and slows every action.
  For traffic capture it is contamination.
- **The `Chat` second browser** (`core/chat.py`) — an entire extra Chromium for a human channel that a
  zero-LLM runtime doesn't have.
- **`reward` / `task.validate()`** — NetGent's terminal condition is "the NFA reached an accepting state", not
  a score.
- **Per-node `DOM.resolveNode` + `Runtime.callFunctionOn`** (`processors.py:110`) — use `DOMSnapshot`'s
  `layout.bounds` (`observation.py:400-418`).
- **ARIA smuggling** (`frame_mark_elements.js:145`) — only needed to get custom IDs into the CDP AXTree.
  Compile-time-only; never at run time.
- **`assert device_pixel_ratio == 1.0`** and the `bounds[0][2] / viewport_width` calibration fudge
  (`processors.py:78-92`) — handle scale explicitly, as BrowserGym does with `_bgym_scale_factor` and
  `map_coordinates` (`action/utils.py:291`).
- **Duplicated sync/async implementations** (`actions.py`'s `execute_*` / `aexecute_*` twins, where the async
  branch already raises `NotImplementedError` for `element_id`). Pick one concurrency model.

---

## Appendix — fastest paths back into the source

| Question | Read |
|---|---|
| How do I represent an action as JSON? | `webarena/browser_env/actions.py:94-424` (`Action`, `ActionTypes`, `create_none_action`) |
| How do I compare two actions? | `webarena/browser_env/actions.py:277` (`is_equivalent`) |
| How do I store a locator chain without `exec`? | `webarena/browser_env/actions.py:1362` (`parse_playwright_code`), `:970` (`locate`) |
| How do I parse an action DSL from a string? | `webarena/browser_env/actions.py:1504` (`create_id_based_action`) |
| How do I replay a fixed action sequence? | `webarena/agent/agent.py:47` (`TeacherForcingAgent`) |
| How do I give every element a stable ID across iframes + shadow DOM? | `browsergym/core/.../javascript/frame_mark_elements.js`, `core/action/utils.py:6` (`get_elem_by_bid`) |
| How do I extract DOM + AXTree + bboxes efficiently? | `browsergym/core/.../observation.py:216`, `:293`, `:536` |
| How do I merge per-frame AXTrees? | `browsergym/core/.../observation.py:536` (`extract_merged_axtree`) |
| How do I track the "active tab"? | `browsergym/core/.../env.py:299-327`, `:575`, `:592` |
| What do I wait for after an action? | `browsergym/core/.../env.py:467-538` (`post_step`), `:563` (`_wait_dom_loaded`) |
| What does a crash-tolerant artifact reader look like? | `browsergym/experiments/.../loop.py:602` (`ExpResult`) |
| How do I turn a recorded action back into structured data? | `browsergym/experiments/.../loop.py:712` (`_create_tape_segment`) |
| How do I grade a task from network traffic? | `browsergym/webarena_verified/.../evaluators.py:95-115`, `task.py:131` |
| How do I capture provenance so a run is reproducible? | `agentlab/experiments/reproducibility_util.py:180`, `:250`, `:324` |
| How do I replay one layer and measure divergence? | `agentlab/agents/generic_agent/reproducibility_agent.py:35`, `:91`, `:223` |
| How do I mint and validate session cookies? | `webarena/browser_env/auto_login.py:35` (`is_expired`), `:61` (`renew_comb`) |
| How do I draw the action target onto a screenshot? | `agentlab/analyze/overlay_utils.py:341` (`annotate_action`) |
