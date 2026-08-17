# Browser Agents — Batch 7: Benchmarks & Evaluation Frameworks

Deep dive into six open-source benchmark / evaluation repos for web and computer-use agents, for the
browser-agent survey.

**Method:** every repo was shallow-cloned (`git clone --depth 1`) into `/tmp/browser-agent-research/batch7/`
and read directly; metadata came from `gh repo view`. Dataset counts (task totals, eval-node counts,
category breakdowns) were computed by parsing the shipped data files, not copied from prose. Where a repo
reports no baseline numbers or has no tests, that is stated explicitly rather than padded.

**Snapshot date:** 2026-08-16. Stars and HEAD commits are as of that date.

| Repo | Stars | Language | License | HEAD at review | Tasks in benchmark | Test suite | CI |
|---|---|---|---|---|---|---|---|
| [reworkd/bananalyzer](https://github.com/reworkd/bananalyzer) | 327 | Python | MIT | `d1b1ae5` (2024-10-20) | 282 train + 18 test examples | pytest, 64 tests | ✅ GH Actions (lint/mypy/pytest/publish) |
| [Farama-Foundation/miniwob-plusplus](https://github.com/Farama-Foundation/miniwob-plusplus) | 396 | HTML + Python | MIT | `33c3b4d` (2026-08-13) | 128 Gymnasium envs | pytest, 22 test fns + 26 test classes | ✅ GH Actions (5 Python × 2 OS matrix) |
| [iMeanAI/WebCanvas](https://github.com/iMeanAI/WebCanvas) | 280 | Python | MIT | `b9f2891` (2025-02-06) | Mind2Web-Live: 104 tasks / 443 key nodes shipped | ❌ none | ❌ none |
| [ServiceNow/WorkArena](https://github.com/ServiceNow/WorkArena) | 267 | Python | Apache-2.0 | `a772230` (2026-02-03) | L1: 33 atomic tasks / 19,912 instances; L2+L3: 682 | pytest, 50 test fns | ✅ GH Actions (4 workflows incl. nightly instance-pool probe) |
| [convergence-ai/webgames](https://github.com/convergence-ai/webgames) | 68 | TypeScript | "Other" (see repo) | `309866f` (2025-06-02) | 150 challenges (53 families × easy/base/hard) | 1 vitest file + 1 pytest file | ❌ none |
| [hud-evals/hud-python](https://github.com/hud-evals/hud-python) | 291 | Python | MIT | `5c6194b` (2026-08-15) | no fixed benchmark — SDK for authoring tasksets | pytest, 1,016 tests in 21 dirs | ✅ GH Actions (pytest + ruff + `ty`, coverage gate 58%) |

**Headline for the survey:** these six split cleanly into three shapes. Two are **datasets with a runner**
(bananalyzer's 300 frozen MHTML/HAR snapshots; webgames' 150 hand-built React challenges) — the benchmark
*is* the repo's content. Two are **live-environment harnesses** where the task set is generated against a
real system (WorkArena against ServiceNow instances; WebCanvas against the live internet), which makes them
the most operationally expensive to run and the hardest to reproduce. MiniWoB++ is the classic **RL-gym**
shape: 128 registered Gymnasium environments, a reward function, and no agent at all. hud-python is the
outlier — a **protocol/SDK** with no benchmark of its own, but by far the strongest engineering (1,016 tests,
a coverage gate, three lint/type jobs in CI).

---

## reworkd/bananalyzer

> "Open source AI Agent evaluation framework for web tasks 🐒🍌" — 327★, Python, MIT.
> A pytest-generating CLI that runs a user-supplied agent against 300 frozen website snapshots (MHTML/HAR)
> and scores structured-JSON extraction. **Dormant since 2024-10-20.**

### Repo/Folder Setup

Top-level layout ([tree](https://github.com/reworkd/bananalyzer/tree/main)):

| Path | What it is |
|---|---|
| [`bananalyzer/`](https://github.com/reworkd/bananalyzer/tree/main/bananalyzer) | The package (1,730 LOC total across 18 files) |
| [`bananalyzer/runner/`](https://github.com/reworkd/bananalyzer/tree/main/bananalyzer/runner) | Test generation + execution: `generator.py`, `runner.py`, `evals.py`, `agent_runner.py`, `website_responder.py`, `null_agent_wrapper.py` |
| [`bananalyzer/data/`](https://github.com/reworkd/bananalyzer/tree/main/bananalyzer/data) | Dataset loading: `example_schemas.py` (Pydantic models), `example_fetching.py` (git/S3 download), `example_s3.py`, `example_detail_schemas.py` |
| [`static/`](https://github.com/reworkd/bananalyzer/tree/main/static) | **The dataset.** 4 JSON index files + 320 per-example asset folders, each holding an `index.mhtml` / `index.html` / `index.har` |
| [`tests/`](https://github.com/reworkd/bananalyzer/tree/main/tests) | The framework's own pytest suite (10 files, 64 tests) |
| [`scripts/format.sh`](https://github.com/reworkd/bananalyzer/blob/main/scripts/format.sh) | ruff format wrapper |
| [`fetch.ipynb`](https://github.com/reworkd/bananalyzer/blob/main/fetch.ipynb) | Notebook that captures new examples via Playwright + Chrome DevTools "save as MHTML" |

The four dataset index files in `static/`:

| File | Contents |
|---|---|
| [`examples.json`](https://github.com/reworkd/bananalyzer/blob/main/static/examples.json) | 282 training examples |
| [`test_examples.json`](https://github.com/reworkd/bananalyzer/blob/main/static/test_examples.json) | 18 held-out test examples |
| [`schemas.json`](https://github.com/reworkd/bananalyzer/blob/main/static/schemas.json) | 14 named output schemas (`job_posting`, `contact`, `contract`, `contract_2`, `contract_3`, `forum`, `ecommerce`, `attorney`, `listing_url`, `listing_document`, …) |
| [`goals.json`](https://github.com/reworkd/bananalyzer/blob/main/static/goals.json) | Default goal strings for `contact` and `contract` schemas |

**Language / package manager.** Python `>=3.11,<4.0`, Poetry
([`pyproject.toml`](https://github.com/reworkd/bananalyzer/blob/main/pyproject.toml), version `0.12.0`).
Runtime deps: Playwright ≥1.47, Pydantic 2, pytest 8 + `pytest-asyncio` + `pytest-xdist` + `pytest-html`,
`deepdiff`, `boto3`, `tabulate`. Lint = ruff, types = mypy in `strict = true` mode (over `bananalyzer/` only).

**Install & configure.**
```bash
pip install bananalyzer                 # ships as a PyPI package with the `bananalyze` entry point
playwright install chromium
# On macOS, fix CRLF in the shipped MHTML or pages render blank:
unix2dos static/*/*.mhtml
```
No API keys are needed by the framework itself — the *agent* you plug in supplies its own. Optional S3
config: `--examples_bucket <bucket>` pulls extra examples from a public bucket into `examples_s3.json`;
`--download` re-clones the repo's `static/` folder into `~/.bananalyzer_data`
([`example_fetching.py:55`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/data/example_fetching.py)).

**Main entry point.** You write a file defining a subclass of
[`AgentRunner`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/runner/agent_runner.py) —
a single `async def run(self, page: Page, eval_context: Example) -> AgentResult` — then:
```bash
bananalyze ./tests/banalyzer.py     # a single agent file
bananalyze .                        # scan a directory for exactly one AgentRunner subclass
bananalyze --download               # dataset only
```
`bananalyze` is `bananalyzer.__main__:main`. Note the discovery is strict: `load_agent_from_path`
([`__main__.py:250`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/__main__.py)) raises if it
finds zero *or more than one* runner in the path.

**Filter flags** (from `parse_args`, [`__main__.py:47`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/__main__.py)):
`--headless`, `-id`, `-tags` / `-skip_tags`, `-d/--domain`, `-i/--intent`, `-c/--category`, `--subcategory`,
`--type`, `--source_type`, `-n` (xdist workers, default `logical`), `--dist` (default `loadscope`), `-skip`,
`--count` (repeat each test N times), `--test` (use the held-out set), `--single_browser_instance`, `--junitxml`.

### Evals

**Task set.** 300 examples total. Parsed breakdown of the 282-example training set:

| Dimension | Breakdown |
|---|---|
| `type` (intent) | `listing_detail` 134, `detail` 117, `listing` 31 |
| `source` | `mhtml` 189, `har` 75, `html` 16, `hosted` 2 |
| `category` | government 116, healthcare 58, software 48, synthetic 16, education 13, e-commerce 13, legal 5, clothing 4, + 6 more |
| `subcategory` | download 107, contact 73, careers 38, forum 16, commerce 16, synthetic 15, contract 8, … |
| `tags` | `urls` 43, `regression` 17, `pagination` 17, `synthetic` 16, `contract` 6, `accordion` 4, `images` 4, `enqueue` 3, `text-nodes` 3, + 4 singletons |
| eval type | `json_match` 282/282 (the `end_url_match` type is implemented but unused in the shipped data) |

The three intents are defined in the README and enforced by the `ExampleType` literal in
[`bananalyzer/data/example_schemas.py:19`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/data/example_schemas.py):
`listing` (scrape all detail-page links off a listing page), `detail` (extract JSON from one detail page),
`listing_detail` (extract everything from the listing page without navigating).

**Metrics.** There is no aggregate "success rate" score object — the metric *is* pytest pass rate, computed
per field. The generator ([`runner/generator.py:36`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/runner/generator.py))
emits `@pytest.mark.parametrize("key", [...])` over every key of the expected JSON, so **one test per
extracted field**, not per example. The custom pytest plugin
([`bananalyzer/hooks.py`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/hooks.py)) tags each
test with `bananalyzer_category` / `bananalyzer_subcategory` / `bananalyzer_type` marks and prints a
`tabulate` breakdown per dimension plus a Total/Passed/Failed/Percent-Passed summary at the end of the run.
`--junitxml` output is post-processed by [`bananalyzer/junit.py`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/junit.py)
to inject `bananalyzer_version` and `git_commit_sha` properties.

**Matching logic** lives in [`bananalyzer/runner/evals.py`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/runner/evals.py)
and is more forgiving than a naive `==`:
- `pre_process` collapses newlines to spaces, strips whitespace, and maps `""` → `None`.
- `sort_keys_based_on_expected` reorders the actual dict/list to match expected before diffing.
- The final compare is `DeepDiff(..., ignore_order=True, report_repetition=True)`.
- Per-field compares go through `is_string_similar` with `tolerance=2`: alphanumeric content must match
  exactly, then up to 2 punctuation/whitespace differences are forgiven, with a `SequenceMatcher` ratio ≥ 0.8
  fallback.
- If expected and actual are *both* `None` for a field, the test **`pytest.skip`s** rather than passing —
  so skipped tests silently shrink the denominator.

**Reported baselines: none.** The repo contains no leaderboard, no results file, and no published scores for
any model. It ships a `NullAgentRunner` that returns `example.evals[0].expected` verbatim so the suite passes
trivially — that is the only "baseline" present.

**How a run is launched.** `run_tests` ([`runner/runner.py:99`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/runner/runner.py))
writes one temporary `.py` file per example into `.banana_cache/`, each containing a session-scoped Playwright
fixture (1280×1024 Chromium, `ignore_https_errors=True`, a hardcoded Chrome-119 UA) plus the generated test
class, then calls `pytest.main()` on the lot with `-n <workers> --dist loadscope`. HAR-sourced examples get
`context.route_from_har(..., not_found="abort", update=False)` so all network traffic is replayed offline;
MHTML/HTML examples are served as `file://` URLs by
[`StaticFileResponder`](https://github.com/reworkd/bananalyzer/blob/main/bananalyzer/runner/website_responder.py).

### Test Cases

**Framework:** pytest (+ `pytest-mock`, `pytest-cov`). **64 test functions across 10 files** in
[`tests/`](https://github.com/reworkd/bananalyzer/tree/main/tests). This is a genuine unit-test suite for the
harness — it does **not** test agents.

| File | What it covers |
|---|---|
| [`test_evals.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_evals.py) | `sanitize_string`, `is_string_similar` (heavily parametrized over tolerance), field-match pass/fail/skip |
| [`test_example_eval.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_example_eval.py) | 18 tests — JSON eval over dicts/lists/options, `expected` XOR `options` validation, `None`-value handling, ignoring `__`-prefixed keys, URL eval, schema/goal defaulting, HAR path resolution (valid + invalid) |
| [`test_sort_keys.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_sort_keys.py) | `sort_keys_based_on_expected` over large nested structures, empty structures, mismatched types |
| [`test_generator.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_generator.py) | Generated pytest source for single/multiple evals; class-name derivation from URL (with/without `www.`, collision suffixes) |
| [`test_runner.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_runner.py) | End-to-end: builds passing/failing/erroring synthetic tests, runs them through `run_tests`, asserts exit codes and that the JUnit XML carries the injected properties |
| [`test_examples.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_examples.py) | Dataset loading (success, JSON decode error, file-not-found), S3 HAR download with a mocked boto3 client, schema/goal lookups |
| [`test___main__.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test___main__.py) | Arg parsing, including the underscore→hyphen normalization of `-id` |
| [`test_website_responder.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_website_responder.py) | Responder dispatch for mhtml / hosted / unknown source |
| [`test_junit.py`](https://github.com/reworkd/bananalyzer/blob/main/tests/test_junit.py) | Git SHA resolution, `GITHUB_SHA` override |

**Notable case:** `test_runner.py` is a meta-test — it generates pytest files, runs pytest inside pytest, and
verifies the enriched XML report. `test_example_eval.py::test_json_eval_ignores___attributes` pins the
convention that keys beginning with `__` are excluded from matching.

**CI:** one workflow,
[`.github/workflows/python.yml`](https://github.com/reworkd/bananalyzer/blob/main/.github/workflows/python.yml),
on push/PR to `main`, Python 3.12. Four jobs: `check-version` (compares `pyproject.toml` version against the
live PyPI version), `lint` (`ruff format --check`), `mypy` (`mypy .`), `pytest` (installs Chromium then
`pytest -vv .`). A `publish` job gated on all four pushes to PyPI when the version is new.

---

## Farama-Foundation/miniwob-plusplus

> "A collection of reinforcement learning environments for simple web interaction tasks" — 396★, HTML +
> Python, MIT. The canonical RL web benchmark: 128 Gymnasium environments driven by Selenium.
> **Explicitly in maintenance mode** (stated at the top of the README), but still actively kept green —
> HEAD is 2026-08-13.

### Repo/Folder Setup

| Path | What it is |
|---|---|
| [`miniwob/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/miniwob) | The Python package |
| [`miniwob/html/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/miniwob/html) | **The environments themselves**, as static web pages: `miniwob/` (130 task HTML files), `core/` (`core.js`, `core.css`, jQuery-UI, d3, `record.js`), `common/special/` (per-task JS for the complex ones — `book-flight`, `email-inbox`, `order-food`, `search-engine`, `tic-tac-toe`, `text-editor`, `navigate-tree`, `click-pie`, `drag-cube`, `social-media`, …), `flight/` (full mirrored Alaska Airlines / American Airlines sites for the FlightWoB tasks) |
| [`miniwob/envs/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/miniwob/envs) | `miniwob_envs.py` (125 env classes, each a docstring + a `subdomain` string) and `flightwob_envs.py` (3) |
| `miniwob/{environment,selenium_instance,selenium_actions,action,observation,spaces,dom,fields,reward,screenshot,http_server,registration,constants}.py` | The Gymnasium/Selenium machinery |
| [`miniwob/scripts/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/miniwob/scripts) | `record.py` (demonstration-recording server), `dump_observation.py`, `gen_env_classes.py` (codegen for the env classes) |
| [`tests/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/tests) | 1,583 LOC pytest suite |
| [`docs/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/docs) | Sphinx site for [miniwob.farama.org](https://miniwob.farama.org/); `_scripts/gen_mds.py` and `gen_env_list.py` generate per-env pages from class docstrings |
| [`viewer/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/viewer) | Standalone HTML/JS viewer for recorded demonstrations |
| [`py.Dockerfile`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/py.Dockerfile) | Container image for the Python side |

**Language / package manager.** Python ≥3.10 (CI covers 3.10–3.14), setuptools + `pyproject.toml`, published
to PyPI as `miniwob`. Deps: `gymnasium>=1.2.3`, `selenium>=4.5`, `numpy`, `pillow`. Lint via pre-commit
(black, isort, pyright basic).

**Install & configure.**
```bash
pip install miniwob
# Chrome/Chromium + a version-matched chromedriver on PATH:
export PATH=$PATH:/path/to/chromedriver
# or pin both explicitly (must be set together):
export MINIWOB_CHROME_BINARY=/path/to/chrome
export MINIWOB_CHROMEDRIVER=/path/to/chromedriver
```
No API keys, no Docker required, no network access at run time (pages are served from the installed package
via `miniwob/http_server.py`). The two `MINIWOB_*` vars are the only configuration; setting only one is a
hard error, asserted by
[`tests/test_selenium_instance.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/test_selenium_instance.py).

**Main entry point.** Registration happens through the Gymnasium entry-point hook
(`[project.entry-points."gymnasium.envs"] __root__ = "miniwob.registration:register_miniwob_envs"`), so:
```python
import gymnasium, miniwob
gymnasium.register_envs(miniwob)
env = gymnasium.make("miniwob/click-test-2-v1", render_mode="human")
obs, info = env.reset()
action = env.unwrapped.create_action(ActionTypes.CLICK_ELEMENT, ref=element["ref"])
obs, reward, terminated, truncated, info = env.step(action)
```
There is **no agent, no runner, and no CLI benchmark command** — this repo ships environments only.

### Evals

**Task set: 128 registered environments** in
[`miniwob/registration.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/miniwob/registration.py)
(verified by parsing the file). The doc-site grouping in
[`docs/_scripts/gen_env_list.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/docs/_scripts/gen_env_list.py)
splits them as:

| Group | Count | Notes |
|---|---|---|
| Original Tasks | 77 | The original OpenAI MiniWoB set |
| No-delay Tasks | 6 | Animation-free variants (`*-nodelay`) |
| Additional Tasks | 12 | MiniWoB++ additions |
| Debug Tasks | 12 | Easier variants for debugging |
| Flight Search Tasks | 3 | FormWoB ports: `flight.Alaska`, `flight.Alaska-auto`, `flight.AA` — real mirrored airline sites in an iframe |
| Hidden Test Tasks | 18 | Intended as a held-out test set; were not on the original OpenAI site |

`miniwob/html/miniwob/` holds 130 HTML files; 5 (`button-delay`, `chase-circle`, `hover-shape`,
`moving-items`, `simon-says`) have no registered env class. 25 of the 128 are flagged `nondeterministic=True`
in the registry, each with an inline comment naming the cause (jQuery datepicker state persisting across
resets, `setInterval` physics loops, `twbsPagination` plugin leakage, `scrollTop()` not resetting, …).

**Metric: reward.** Defined in
[`miniwob/reward.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/miniwob/reward.py) —
0.0 during an episode, then in `[-1, 1]` on termination. Four pluggable *reward processors*, selected via
`gymnasium.make(..., reward_processor=...)`:

| Processor | Semantics |
|---|---|
| `get_original_reward` | Default. Positive reward scaled by remaining time; some tasks give partial credit |
| `get_raw_reward` | Partial credit kept, time penalty removed |
| `get_binary_reward` | −1 / +1 only — "used in most previous publications" |
| `get_thresholded_reward(threshold=…)` | For continuous-partial-credit tasks (e.g. `bisect-angle`), binarize at a threshold |

**Action space** is configurable per env via `ActionSpaceConfig.get_preset(name)`
([`miniwob/action.py:117`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/miniwob/action.py)),
with presets that reproduce the action spaces of three prior papers — a genuinely useful benchmarking
feature: `all_supported` (14 action types), `shi17` (coordinate mouse + press-key, per *World of Bits*),
`liu18` (element-click + focus-and-type-field, per *Workflow-Guided Exploration*), `humphreys22`
(binned 51×51 coordinates + press-key + type-field). A `_mac_os` suffix swaps the allowed key set.

**Observation space** ([`docs/content/observation_space.md`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/docs/content/observation_space.md)):
a dict of `utterance` (str), `fields` (tuple of key-value pairs extracted from the utterance), `screenshot`
(H×W×3 uint8), `dom_elements` (tuple of dicts with `ref`, `parent`, geometry, `tag`, `text`, `value`, flags).

**Reported baselines: none in-repo.** No leaderboard, no results table, no scores. The README points at
[Shi et al. 2017](http://proceedings.mlr.press/v70/shi17a/shi17a.pdf) and
[Liu et al. 2018 (ICLR)](https://arxiv.org/abs/1802.08802) for published numbers. Human demonstrations live
in a separate repo, [stanfordnlp/miniwob-plusplus-demos](https://github.com/stanfordnlp/miniwob-plusplus-demos);
[`docs/content/demonstrations.md`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/docs/content/demonstrations.md)
documents the JSON format and how to record your own (`python -m miniwob.record out/`, then append
`?record=true` to a task URL).

**How an "eval run" is launched:** there isn't one. You write your own loop over `env.step()`. The closest
thing the repo has to a benchmark run is `tests/test_api.py`, which sweeps *every* registered env.

### Test Cases

**Framework:** pytest + `pytest-timeout` + `pytest-xdist`, installed via the `testing` extra.
`filterwarnings = ["error", ...]` in `pyproject.toml` turns warnings into failures with a short allowlist.
Six files, 1,583 LOC.

| File | What it covers |
|---|---|
| [`tests/test_api.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/test_api.py) | **The big one.** Parametrized over `get_all_registered_miniwob_envs()` — i.e. all 128 envs — runs Gymnasium's `check_env` on each, then asserts the observation space is a `Dict` with exactly `{utterance, dom_elements, screenshot, fields}` and that `FlattenObservation` produces the right sub-space types |
| [`tests/test_action.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/test_action.py) | 774 LOC, 26 test classes built on a `RepeatedTester` base. One class per action pattern: `TestClickTest2`, `TestEnterTextFocusAndTypeField`, `TestUseAutocomplete(NoDelay)`, `TestClickPie`, `TestDragBox(WithMove)`, `TestCopyPaste`, `TestScrollText2(WithPressKey)`, and three preset-conformance classes — `TestShi17Preset`, `TestLiu18Preset`, `TestHumphreys22Preset` |
| [`tests/test_environment.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/test_environment.py) | Env lifecycle, seeding (`TestMiniWoBSeed`), render modes, utterance-field extraction, and a `RewardProcessorTester` hierarchy with a parametrized class per reward processor |
| [`tests/test_selenium_instance.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/test_selenium_instance.py) | Driver construction: honours `MINIWOB_CHROME_BINARY`/`MINIWOB_CHROMEDRIVER`, falls back to Selenium discovery, and **rejects a partially-set pair** |
| [`tests/test_spaces.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/test_spaces.py) | Unicode handling in the custom spaces |
| [`tests/utils.py`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/tests/utils.py) | Not a test — houses `StripNondeterministicInfo` |

**Notable:** `StripNondeterministicInfo` is the most interesting engineering in the suite. It is a Gymnasium
wrapper used *only in tests* that makes determinism checking possible against a real browser: it re-indexes
DOM `ref`/`parent` codes so they start from 0, rounds `getBoundingClientRect()` floats to 1 decimal to absorb
sub-pixel drift, zeroes the timing-dependent `tampered` flag, quantizes screenshot pixels to the nearest 8 to
absorb anti-aliasing jitter, and drops the wall-clock `elapsed` key from `info`. `test_api.py` also carries an
explicit retry policy: a `RETRY_EXCEPTION` tuple (`MoveTargetOutOfBoundsException`, `JavascriptException`,
`SessionNotCreatedException`, urllib3 timeouts) with 3 attempts, and on `AssertionError` it bumps `wait_ms`
by 100 and retries — a candid acknowledgement that browser-backed determinism is flaky.

**CI:** five workflows in [`.github/workflows/`](https://github.com/Farama-Foundation/miniwob-plusplus/tree/main/.github/workflows).
[`build.yml`](https://github.com/Farama-Foundation/miniwob-plusplus/blob/main/.github/workflows/build.yml)
is the test job: matrix of `{ubuntu-latest, macos-latest} × {3.10, 3.11, 3.12, 3.13, 3.14}` = 10 combos,
30-minute timeout, installs Chrome 152 + matching chromedriver via `browser-actions/setup-chrome@v2`, then
runs the all-envs sweep separately from the rest:
```bash
pytest -n logical -v --timeout=120 tests/test_api.py
pytest -v --timeout=60 --ignore=tests/test_api.py tests/
```
Plus `pre-commit.yml`, `build-publish.yml` (PyPI trusted publishing on release), and two Sphinx docs
workflows (main-branch and per-tag versioned deploys).

---

## iMeanAI/WebCanvas

> "All-in-one Web Agent framework for post-training" — 280★, Python, MIT.
> Online/live-web evaluation using **key-node** annotations; ships the Mind2Web-Live benchmark and a
> reference agent. Paper: [arXiv 2406.12373](https://arxiv.org/abs/2406.12373). **Last commit 2025-02-06.**

### Repo/Folder Setup

| Path | What it is |
|---|---|
| [`agent/`](https://github.com/iMeanAI/WebCanvas/tree/main/agent) | The reference agent, split by module |
| `agent/LLM/` | Provider adapters: `openai.py`, `claude.py`, `gemini.py`, `togetherai.py`, plus `token_calculator.py` / `token_utils.py` for the cost metric, and a [`README.md`](https://github.com/iMeanAI/WebCanvas/blob/main/agent/LLM/README.md) documenting every API-key env var |
| `agent/Environment/html_env/` | Playwright wrapper: `async_env.py`, `build_tree.py`, `actions.py`, `active_elements.py` |
| `agent/Plan/` | `planning.py`, `action.py` — the planning loop and the 14-verb action enum |
| `agent/Memory/` | `short_memory/history.py`, `long_memory/{website_knowledge,reference_trace}.py`, `retriever.py` |
| `agent/Prompt/` | Prompt sets per observation mode: `base_prompts.py`, `vision_prompts.py`, `dom_vision_prompts.py`, `dom_vision_disc_prompts.py`, `vision_to_dom_prompts.py` |
| `agent/Reward/global_reward.py` | LLM-as-judge self-reward used for in-run guidance |
| [`evaluate/`](https://github.com/iMeanAI/WebCanvas/tree/main/evaluate) | **The evaluation code** (1,240 LOC) — see below |
| [`data/`](https://github.com/iMeanAI/WebCanvas/tree/main/data) | `dataset_io.py` (GraphQL download/upload against the iMean platform), `raw_data_processor.py`, and `example/` with the two shipped task files |
| [`configs/setting.toml`](https://github.com/iMeanAI/WebCanvas/blob/main/configs/setting.toml) | The single config file: task mode, step caps, file paths, and a full token price table |
| [`evaluate.py`](https://github.com/iMeanAI/WebCanvas/blob/main/evaluate.py) | The CLI entry point |
| [`experiment_results.py`](https://github.com/iMeanAI/WebCanvas/blob/main/experiment_results.py) | Metric aggregation → `result.json` |
| [`Mind2web-live_Leaderboard.md`](https://github.com/iMeanAI/WebCanvas/blob/main/Mind2web-live_Leaderboard.md) | Checked-in leaderboard |
| `scripts/run_evaluation.sh` | **Empty file (0 bytes)** — a stub |

**Language / package manager.** Python 3.11, plain `requirements.txt` (no `pyproject.toml`, not packaged for
PyPI). Playwright is pinned to `1.32.1`. Also pulls `openai`, `anthropic`, `google-generativeai`, `tiktoken`,
`sanic`, `flask`, `transformers==4.33.2`, `nltk`, `bs4`, `lxml`.

**Install & configure.**
```bash
conda create -n webcanvas python=3.11 && conda activate webcanvas
pip install -r requirements.txt
npm init -y && npm install axios          # yes — a Node dependency inside a Python project
export OPENAI_API_KEY=…                   # and/or ANTHROPIC_API_KEY, GOOGLE_API_KEY, TOGETHER_API_KEY
export GOOGLE_API_KEY=… GOOGLE_CX=…       # Google Custom Search — required, since "Google blocked GUI agent based search lately"
export BROWSERBASE_API_KEY=…              # optional cloud browser
export GRAPHQL_USERNAME=… GRAPHQL_PASSWORD=…   # only for dataset download/upload
```
This is the heaviest configuration burden in the batch: LLM keys **plus** a Google Custom Search key **plus**
optionally Browserbase **plus** platform credentials, and it runs against the live internet.

**Main entry point.**
```bash
python evaluate.py \
  --global_reward_mode dom_reward \
  --index -1 \
  --single_task_name "Find Dota 2 game and add all DLC to cart in steam." \
  --planning_text_model gpt-4o-mini \
  --global_reward_text_model gpt-4o-mini
```
Batch-vs-single is controlled by `task_mode` in `configs/setting.toml`, not by a flag. Dataset I/O is separate:
`python data/dataset_io.py download --challenge-id … --save-path …` and
`python data/dataset_io.py upload --file-path … --challenge-id … --name … --base-model …`.

### Evals

**Task set.** The shipped
[`data/example/mind2web-live_test_20241024.json`](https://github.com/iMeanAI/WebCanvas/blob/main/data/example/mind2web-live_test_20241024.json)
holds **104 tasks with 443 key-node evaluation steps** (parsed directly). A second file,
`example_130.json`, holds 130 tasks. The README describes the full Mind2Web-Live dataset as **542 tasks with
2,439 intermediate evaluation states**, hosted on
[HuggingFace](https://huggingface.co/datasets/iMeanAI/Mind2Web-Live) — the repo ships only the test split.

Each task is `{index, task, reference_task_length, evaluation[]}`, where each evaluation entry is a
`match_function_name` plus content. Distribution of the 443 key nodes:

| Match function | Count |
|---|---|
| `url_included_match` | 258 |
| `element_path_exactly_match` | 90 |
| `url_exactly_match` | 47 |
| `element_value_exactly_match` | 26 |
| `url_semantic_match` | 18 |
| `element_value_semantic_match` | 4 |

**Eval code.** Two parallel implementations of the same evaluator hierarchy
(`URLEvaluator` / `ElementEvaluator` / `TextEvaluator` / `MatchFunction`):
- [`evaluate/step_score.py`](https://github.com/iMeanAI/WebCanvas/blob/main/evaluate/step_score.py) (239 LOC) — the
  original, operates on HTML content and the agent's action.
- [`evaluate/step_score_js.py`](https://github.com/iMeanAI/WebCanvas/blob/main/evaluate/step_score_js.py) (228 LOC) — the
  v0.0.4 "JavaScript event-listener based" evaluator that takes a Playwright `page` and compares element
  handles (`is_same_element`). This is what decouples evaluation from the action space and lets purely
  visually-grounded agents be scored.
- [`evaluate/task_score.py`](https://github.com/iMeanAI/WebCanvas/blob/main/evaluate/task_score.py) (32 LOC) —
  `TaskLengthEvaluator` (full credit if steps < `alpha=1.2` × reference length, else `ref/actual`) and
  `FinishTaskEvaluator` (1 iff every key node was hit).
- [`evaluate/evaluate_utils.py`](https://github.com/iMeanAI/WebCanvas/blob/main/evaluate/evaluate_utils.py) (738 LOC) —
  `run_task`, `step_evaluate`, `step_event_evaluate`, config reading, and the per-step orchestration.

**Metrics**, computed in
[`experiment_results.py::evaluate`](https://github.com/iMeanAI/WebCanvas/blob/main/experiment_results.py):
`task_counts`, `average_step_score_rate`, `average_efficiency_score` (steps ÷ key nodes completed),
`usd_efficiency_score` (total token cost ÷ key nodes completed), `key_node_completion_rate` (Σ numerators ÷
Σ denominators across all `task_score` fractions), `task_success_rate` (fraction with status `finished`), and
`task_near_success_rate` (exactly one key node short). Token accounting uses `tiktoken`, falling back to
`cl100k_base` for non-OpenAI models — the README explicitly warns those figures are approximate.

**Reported baselines.** The repo checks in two sets of numbers. The
[leaderboard](https://github.com/iMeanAI/WebCanvas/blob/main/Mind2web-live_Leaderboard.md):

| Agent | Model | Completion rate | Task success rate |
|---|---|---|---|
| SeeAct-V | GPT-4o | 50.8% | 19.2% |
| SeeAct-V | GPT-4 | 50.7% | 23.1% |
| AGUVIS | AGUVIS-72B | — | 27.1% |
| WebDreamer | GPT-4o | 49.9% | 25.0% |
| WebCanvas | GPT-4 | 48.8% | 23.1% |
| WebCanvas | Claude-3-Sonnet | 47.9% | 22.1% |
| WebCanvas | GPT-4o | 47.6% | 22.1% |
| WebCanvas | GPT-4-turbo | 44.3% | 21.1% |

And a USD-efficiency table in the README: GPT-4o 51.4% completion / 28.8% success / $0.142 per key node;
Llama-3.1-405B 47.8% / 24.0% / $0.174; Llama-3.1-70B 44.8% / 20.2% / $0.031; GPT-4o-mini 42.9% / 21.2% /
**$0.004**; GPT-3.5-turbo 42.5% / 17.3% / $0.092.

**The most survey-relevant finding in this repo** is its environment-sensitivity table — the same
`gpt-3.5-turbo-0125` agent scores 40.2% / 16.5% (US + Windows + Chrome), 42.1% / 20.2% (US + Windows +
Firefox), 36.5% / 15.4% (US + Linux + Chrome), 42.3% / 21.2% (Singapore), and **23.6% / 8.65% (UK)**. A ~2×
swing in task success from IP region alone, on an identical agent, is a direct quantification of why
live-web benchmarks are hard to reproduce.

### Test Cases

**None.** There is no `tests/` directory, no test file anywhere in the repo, no pytest/unittest dependency in
`requirements.txt`, and no `.github/` directory at all — so **no CI**. `scripts/run_evaluation.sh`, the only
shell script, is a zero-byte stub. The `interaction_mode = true` default in `configs/setting.toml` means the
reference workflow expects a human to intervene when the live web throws a CAPTCHA or network error, which is
fundamentally incompatible with automated testing.

---

## ServiceNow/WorkArena

> "How Capable are Web Agents at Solving Common Knowledge Work Tasks?" — 267★, Python, Apache-2.0.
> A BrowserGym task package that generates enterprise knowledge-work tasks against **live ServiceNow
> instances**. Papers: [WorkArena, ICML 2024](https://arxiv.org/abs/2403.07718) and
> [WorkArena++, NeurIPS 2024](https://arxiv.org/abs/2407.05291).

### Repo/Folder Setup

| Path | What it is |
|---|---|
| [`src/browsergym/workarena/`](https://github.com/ServiceNow/WorkArena/tree/main/src/browsergym/workarena) | The package (`browsergym-workarena` on PyPI, v0.5.3), namespaced into BrowserGym |
| `…/tasks/` | Atomic task families, one module each: `form.py`, `list.py`, `knowledge.py`, `navigation.py`, `service_catalog.py`, `dashboard.py`, `send_chat_message.py`, `mark_duplicate_problem.py`, plus `base.py` and `comp_building_block.py` |
| `…/tasks/compositional/` | ~30 modules of L2/L3 compositional tasks: `dash_do_*`, `navigate_and_do(_infeasible)`, `onboard_user`, `offboard_user`, `expense_management`, `maximize_investment_return`, `manage_change_request_schedule`, `warranty_check`, `work_assignment`, `find_and_order_item`, `filter_and_do`, `delete_record`, … |
| `…/tasks/compositional/utils/curriculum.py` | `AGENT_CURRICULUM` and `HUMAN_CURRICULUM` — the bucket/weight/seed sampling definitions |
| `…/api/` | 16 modules wrapping the ServiceNow Table API (`incident.py`, `problem.py`, `user.py`, `change_request.py`, `cost_center.py`, `expense_line.py`, `knowledge.py`, `report.py`, `ui_themes.py`, …) |
| `…/data_files/task_configs/` | **33 JSON config files**, one per atomic task — this is where the 19,912 instances live. Sizes are substantial: `filter_user_list_task.json` is 56 MB, `filter_change_request_list_task.json` 12.8 MB |
| `…/data_files/setup_files/` | Instance-setup fixtures: `forms/` (6 expected-field JSONs), `lists/` (9 expected-column JSONs), `knowledge/` (KB articles + an autopublish workflow XML), `ui_themes/` (update-set XML) |
| `…/human_eval/tool.py` | The `workarena-human-eval` CLI for collecting human baselines |
| `…/install.py` | The `workarena-install` CLI that provisions a ServiceNow instance |
| [`tests/`](https://github.com/ServiceNow/WorkArena/tree/main/tests) | 12 files, 1,133 LOC |
| [`dev/requirements.txt`](https://github.com/ServiceNow/WorkArena/blob/main/dev/requirements.txt) | Dev deps (`pytest==7.3.2`, `pytest-xdist`, `pytest-playwright`, black 24.2.0, `-e ..`) |
| `src/workarena_test.py`, `src/wa_action_traces.py` | Loose demo scripts at `src/` root — the latter monkey-patches Playwright to extract action traces without touching task code |
| `scripts/`, `monitor_pool_usage.py`, `make_human_eval_curriculum.py`, `generate_knowledge_base.ipynb` | Trace extraction, pool telemetry, curriculum generation |

**Language / package manager.** Python >3.7, hatchling + `hatch-requirements-txt`. Deps: `browsergym-core>=0.2`,
`Faker`, `english-words`, `numpy`, `requests`, `tenacity`, `tqdm`, `huggingface_hub`.

**Install & configure.** Notably, the ServiceNow instance is now **provisioned from a gated pool**, not
self-hosted:
1. Request access to [huggingface.co/datasets/ServiceNow/WorkArena-Instances](https://huggingface.co/datasets/ServiceNow/WorkArena-Instances) and wait for approval.
2. Authenticate (`huggingface-cli login` or `HUGGING_FACE_HUB_TOKEN`).
3. `pip install browsergym-workarena && playwright install`.

`__init__.py` hard-fails at import if `playwright != 1.44.0` — an unusually strict pin. `instance.py` then
downloads the pool file from the gated HF repo and XOR-decrypts the credentials
([`instance.py:33`](https://github.com/ServiceNow/WorkArena/blob/main/src/browsergym/workarena/instance.py)).
Escape hatches: set `SNOW_INSTANCE_URL` + `SNOW_INSTANCE_UNAME` + `SNOW_INSTANCE_PWD` together to use your own
instance, or `SNOW_INSTANCE_POOL` to point at a local pool file. Two console scripts are registered:
`workarena-install` and `workarena-human-eval`.

**Main entry point.** There is no benchmark CLI. The README's own recommendation is to run WorkArena through
[AgentLab](https://github.com/ServiceNow/AgentLab), which drives BrowserGym in parallel and reports to the
[BrowserGym leaderboard](https://huggingface.co/spaces/ServiceNow/browsergym-leaderboard). Directly:
```python
from browsergym.core.env import BrowserEnv
from browsergym.workarena import ATOMIC_TASKS, get_all_tasks_agents

env = BrowserEnv(task_entrypoint=ATOMIC_TASKS[0], headless=False)
env.reset()
env.task.cheat(env.page, cheat_messages)          # oracle solver
reward, stop, message, info = env.task.validate(env.page, cheat_messages)
```
L2/L3 sets come from `get_all_tasks_agents(filter="l2")` (or `"l3"`, or `"l2.<category>"`), which returns
`(task_class, seed)` tuples sampled deterministically from `meta_seed=42`.

### Evals

**Task set.**
- **WorkArena-L1 (ICML 2024):** 33 atomic tasks, **19,912 unique instances**. The task→category map in
  [`__init__.py:70`](https://github.com/ServiceNow/WorkArena/blob/main/src/browsergym/workarena/__init__.py)
  groups them into 7 categories: `form` (5), `list-filter` (6), `list-sort` (6), `service catalog` (9),
  `dashboard` (4), `menu` (2), `knowledge` (1).
- **WorkArena++ / L2 & L3 (NeurIPS 2024):** **682 tasks**, each sampling from thousands of configurations.
  L2 and L3 are the *same* compositional task classes specialized to a level via
  `specialize_task_class_to_level` (a small `exec`-based class factory at
  [`tasks/compositional/__init__.py:12`](https://github.com/ServiceNow/WorkArena/blob/main/src/browsergym/workarena/tasks/compositional/__init__.py)).

The compositional curriculum
([`tasks/compositional/utils/curriculum.py:55`](https://github.com/ServiceNow/WorkArena/blob/main/src/browsergym/workarena/tasks/compositional/utils/curriculum.py))
defines 5 capability categories, each with weighted task buckets and a seed budget:

| Category | Buckets | `num_seeds` |
|---|---|---|
| `planning_and_problem_solving` | 7 (duplicate-problem marking, workload balancing, work assignment, 4 scheduling variants) | 2 |
| `information_retrieval` | 8 (dash-and-order/create-incident/create-problem/request, min/max filter, warranty check, find-and-order) | 7 |
| `data_driven_decision_making_and_reasoning` | 13 (expense management, investment return, mean/median/mode compute-and-act) | 1 |
| `sophisticated_memory` | 6 (navigate-and-create/order/filter/sort, on/offboard user) | 8 |
| `contextual_understanding_infeasible_tasks` | 8 (infeasible navigate-and-* , each with and without a required reason) | 4 |

The `HUMAN_CURRICULUM` is a smaller variant with fewer buckets and seeds, used by the human-eval tool.

**Metric.** Binary reward from `task.validate(page, chat_messages) -> (reward, done, message, info)`; L1
reward is 0/1. Compositional tasks are iterables of subtasks (`len(env.task)`, `cheat(..., subtask_idx=i)`),
so partial progress is expressible. The **oracle `cheat()` function** is the distinguishing design choice:
every task ships a Playwright solver that provably completes it, which is what makes the task-validity tests
below possible.

**Reported baselines: none in-repo.** No results file, no leaderboard markdown, no numbers in the README. The
ICML 2024 abstract states only that "current agents show promise on WorkArena" while "there remains a
considerable gap towards achieving full task automation," and highlights a gap between open and proprietary
models — it does not give per-model rates in the abstract. Live numbers live on the external
[BrowserGym leaderboard](https://huggingface.co/spaces/ServiceNow/browsergym-leaderboard). The repo *does*
contain the human-baseline collection machinery
([`human_eval/tool.py`](https://github.com/ServiceNow/WorkArena/blob/main/src/browsergym/workarena/human_eval/tool.py) —
annotator email, curriculum loading, validation/abandon/infeasible flags, per-task result logging) but no
collected results.

### Test Cases

**Framework:** pytest + `pytest-xdist` + `pytest-playwright`, with two custom markers (`slow`, and an
undeclared-but-used `pricy`). 12 files, 1,133 LOC, 50 test functions. Because every test drives a real
ServiceNow instance, the suite is graded by cost:

| File | What it covers |
|---|---|
| [`tests/test_task_general.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_task_general.py) | `test_cheat`, parametrized over **all `ATOMIC_TASKS` × 1 seed** — runs the oracle solver and asserts `validate()` returns reward 1. The core "are all 33 tasks still solvable?" probe |
| [`tests/test_compositional.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_compositional.py) | `test_cheat_compositional` over all compositional tasks × levels 2–3, marked `@pytest.mark.pricy`. Four further sampled-set tests (agent L2/L3, human L2/L3) are all `@pytest.mark.skip(reason="Tests are too slow")` |
| [`tests/test_snow_instance.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_snow_instance.py) | Instance health: reachable, active, credentials valid, WorkArena installed |
| [`tests/test_task_from_config.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_task_from_config.py) | 323 LOC — a per-task cheat test driven from each shipped JSON config (menu, impersonation, and each of the 9 catalog orders). **All are `@pytest.mark.skip`ped** as too slow |
| [`tests/test_random_config_generation.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_random_config_generation.py) | Cheat-from-random-config over `RANDOMLY_CONFIGURALBE_TASKS` — also skipped |
| [`tests/test_filter_list_task.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_filter_list_task.py) | Filter validation, including a parametrized **negative** suite asserting the exact rejection message for malformed queries |
| [`tests/test_compositional_utils.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_compositional_utils.py) | Pure-logic tests: the knapsack solver used to compose tasks, and that invalid config generators are rejected |
| [`tests/test_task_setup.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_task_setup.py) | Instance mutations the benchmark depends on: add-to-cart disabled, top-items panel removed |
| [`tests/test_validate.py`](https://github.com/ServiceNow/WorkArena/blob/main/tests/test_validate.py), `test_api.py`, `test_utils.py` | Config validation, user-preference API, and `ui_login` vs `url_login` with correct/wrong credentials |

**Notable:** a large share of the declared suite is `@pytest.mark.skip`ped for slowness — the compositional
sampled-set tests and nearly all of `test_task_from_config.py`. What actually runs in CI is the fast
non-instance logic plus the atomic `cheat` sweep. The `test_filter_list_task.py` negative cases (asserting
exact error strings for bad filters) are the sharpest unit tests in the repo.

**CI:** four workflows in [`.github/workflows/`](https://github.com/ServiceNow/WorkArena/tree/main/.github/workflows).
- [`unit_tests.yml`](https://github.com/ServiceNow/WorkArena/blob/main/.github/workflows/unit_tests.yml) — on push/PR plus a Sunday-midnight cron. Four jobs: `code-format` (`black --check`), `browsergym-workarena-fast` (`pytest -n 5 -m 'not slow and not pricy' --slowmo 1000`), `browsergym-workarena-slow` (`-m 'slow and not pricy'`), and `end-to-end-tests` (`-m 'pricy' --slowmo 1800`, **cron-only**). All take `SNOW_INSTANCE_*` from repo secrets.
- [`instance_pool_ci.yml`](https://github.com/ServiceNow/WorkArena/blob/main/.github/workflows/instance_pool_ci.yml) — **daily at 03:00 UTC**, runs `test_task_general.py` with 20 workers then `test_snow_instance.py`, to detect when the shared instance pool drifts and breaks tasks. This is the most interesting CI design in the batch: a nightly integrity check on a *live third-party SaaS environment* that the benchmark's validity depends on.
- [`pool-telemetry.yml`](https://github.com/ServiceNow/WorkArena/blob/main/.github/workflows/pool-telemetry.yml) — daily `monitor_pool_usage.py`, reporting to Weights & Biases.
- [`pypi.yml`](https://github.com/ServiceNow/WorkArena/blob/main/.github/workflows/pypi.yml) — build, Sigstore-sign, publish on tag.

---

## convergence-ai/webgames

> "Challenges for general-purpose web-browsing AI agents" — 68★, TypeScript, license "Other".
> 150 hand-built React mini-games, each easy for a human and hard for an agent, each emitting a unique
> password on completion. Live at [webgames.convergence.ai](https://webgames.convergence.ai).
> **Last commit 2025-06-02.**

### Repo/Folder Setup

| Path | What it is |
|---|---|
| [`webgames/`](https://github.com/convergence-ai/webgames/tree/main/webgames) | The React + Vite + TypeScript SPA — the benchmark itself |
| `webgames/src/pages/` | **168 `.tsx` files**, one component per challenge. Most families exist in three variants: `BrickBuster.tsx`, `BrickBusterEasy.tsx`, `BrickBusterHard.tsx`. Each exports `PASSWORD_<Name>` and `TASK_ID_<Name>` alongside the component |
| `webgames/src/router/routes.ts` | 2,510 LOC of hand-written route table wiring every page to its id + password |
| `webgames/src/components/` | Shared UI: `Layout`, `BannerAd`, `RecipeCard`, `RequireAuth`, `Stopwatch`, `WeeklyCalendar` |
| `webgames/src/wasm/code_gen/` | A Rust/WASM crate for one of the challenges |
| `webgames/functions/api/` | Two Cloudflare Pages Functions: `record-view.ts`, `record-completion.ts` |
| `webgames/db/schema.sql` | Cloudflare D1 schema — `completions` and `views` tables (task_id, timestamps, UA, IP, user_id, host, url). This is how the **human** baseline is collected |
| [`evals/inspect_ai_webgames.py`](https://github.com/convergence-ai/webgames/blob/main/evals/inspect_ai_webgames.py) | Minimal Inspect-AI scaffolding: HF dataset loader + scorer |
| [`evals/browseruse_webgames/`](https://github.com/convergence-ai/webgames/tree/main/evals/browseruse_webgames) | The real eval harness — an Inspect-AI solver wrapping `browser-use`, plus `webgames_tasks.jsonl`, a SLURM script, and one pytest file |
| [`analysis/`](https://github.com/convergence-ai/webgames/tree/main/analysis) | `analyse.py`, `webgames_categories.csv`, `webgames_tasks.jsonl`, a notebook, and `outputs2/` with 20 result CSVs + charts |
| `scratch/generate_form.py` | A one-off helper |

**Language / package manager.** TypeScript + React 18 + Vite 6 + Tailwind, **pnpm**. Deployment targets
Cloudflare Pages (`wrangler.toml`, D1 binding). The two eval/analysis subprojects are separate Python
`uv` projects (`>=3.11`) with their own `pyproject.toml` + `uv.lock`.

**Install & configure.**
```bash
cd webgames && pnpm install && pnpm run dev        # the benchmark, purely client-side
pnpm run dev:all                                    # with wrangler + D1 for the completion API
```
No API keys for the benchmark itself. The browser-use eval needs OpenAI / Anthropic / Google keys via
`.env` (`load_dotenv()`), and for the Qwen models a reachable vLLM endpoint — those base URLs are
**hardcoded to Convergence's SLURM hostnames** (`http://slurmus-a3nodeset-2:8007/v1`), so that path is not
reproducible outside their cluster.

**Main entry points.**
- Play/agent-target: any URL under `https://webgames.convergence.ai/<task_id>`.
- Dataset: [`convergence-ai/webgames` on HuggingFace](https://huggingface.co/datasets/convergence-ai/webgames), or `?showDownloads=true` on the site for CSV/JSONL, or the checked-in `webgames_tasks.jsonl`.
- Eval: `uv run browseruse_webgames.py` (or the SLURM wrapper `run_webgames_slurm.sh`).

### Evals

**Task set: 150 tasks**, parsed from
[`analysis/webgames_tasks.jsonl`](https://github.com/convergence-ai/webgames/blob/main/analysis/webgames_tasks.jsonl).
Each row is `{path, title, description, icon, tags, password, difficulty, variant, base_task, id}`.
53 base task families; `variant` ∈ {easy, base, hard}. The `difficulty` field breaks down as easy 63,
hard 51, medium 25, unset 11.

Five capability categories are defined in
[`analysis/webgames_categories.csv`](https://github.com/convergence-ai/webgames/blob/main/analysis/webgames_categories.csv)
as **fractional weights per game** (a game can split across categories — e.g. `buttons` is 0.4 technical
fluency / 0.4 adversarial resistance / 0.2 visual comprehension): technical fluency, real-time
responsiveness, adversarial resistance, cognitive abilities, visual comprehension.

**Metric: exact substring match on the password.** Both scorers are three lines —
`correct = target.text in answer`, wrapped with Inspect-AI's `accuracy()` and `stderr()` metrics
([`evals/inspect_ai_webgames.py:52`](https://github.com/convergence-ai/webgames/blob/main/evals/inspect_ai_webgames.py)).
This is the cleanest grading design in the batch: because success is a secret string the page only reveals on
genuine completion, there is nothing to partially credit and nothing to hallucinate past.

**Agent scaffold.** `browser_agent_solver()` in
[`evals/browseruse_webgames/browseruse_webgames.py`](https://github.com/convergence-ai/webgames/blob/main/evals/browseruse_webgames/browseruse_webgames.py)
constructs a `browser_use.Agent` with `max_steps=20`, `enable_memory=False`, `max_failures=30`, a free port
per instance, and `use_vision` toggled off for the `-textonly` model variants. The full `AgentHistoryList`
(goals, actions, results, screenshots) is converted into Inspect `ChatMessage`s so traces are inspectable.

**Reported baselines — the richest results set in this batch.** From
[`analysis/outputs2/01_overall_success_per_model.csv`](https://github.com/convergence-ai/webgames/blob/main/analysis/outputs2/01_overall_success_per_model.csv):

| Model | Overall success |
|---|---|
| gemini-2.5-pro-preview-05-06 | **50.0%** |
| claude-3-7-sonnet-20250219 | 44.7% |
| gemini-2.5-flash-preview-04-17 | 42.0% |
| gemini-2.5-pro-preview-05-06-textonly | 41.3% |
| gpt-4o | 39.3% |
| gpt-4o-mini | 34.7% |
| qwen2.5-vl-72b-instruct | 26.7% |
| qwen2.5-vl-32b-instruct | 24.7% |
| claude-3-7-sonnet-20250219-computeruse | 22.0% |
| qwen2.5-vl-7b-instruct | 12.7% |

Per-category (weighted) success across all models
([`04_success_rate_per_category.csv`](https://github.com/convergence-ai/webgames/blob/main/analysis/outputs2/04_success_rate_per_category.csv)):
adversarial resistance 51.1%, technical fluency 45.6%, real-time responsiveness 26.3%, cognitive abilities
22.9%, **visual comprehension 18.5%**.

Headline findings from the README: best model ~50% vs **95.7% human success** on base tasks; **61 of 150
tasks unsolved by any model**; 11 of 53 task families completely unsolved; a 14% drop easy→base and 15%
base→hard; a 15% drop from removing vision (though text-only sometimes *beat* vision on reasoning tasks);
Qwen2.5-VL scaled 12.4%→25% from 7B→32B but barely improved 32B→72B. Note the counter-intuitive result that
Claude 3.7 **with** computer-use scored 22.0% vs 44.7% without — the DOM-driven browser-use scaffold beat raw
computer-use by 2×.

`analysis/outputs2/` also ships 20 CSVs and matching PDF/PNG charts, including
`08_tasks_unsolved_by_any_model.csv`, `09_tasks_solved_by_exactly_one_model.csv`, and
`10_parent_tasks_unsolved_at_any_difficulty.csv`.

### Test Cases

**Minimal — two test files total.**

- [`webgames/src/pages/LadyBirdPlanner.test.tsx`](https://github.com/convergence-ai/webgames/blob/main/webgames/src/pages/LadyBirdPlanner.test.tsx) —
  the **only** frontend test, covering **1 of 168 pages**. It renders `LadyBirdPlanner`, clicks the ⬇️ button,
  and asserts the grid cell at `4,1` has `data-current-position="true"`. It still contains commented-out
  debug scaffolding and a live `console.log`. Framework: vitest + `@testing-library/react` + jsdom, configured
  in [`vitest.config.ts`](https://github.com/convergence-ai/webgames/blob/main/webgames/vitest.config.ts) with
  [`src/setupTests.ts`](https://github.com/convergence-ai/webgames/blob/main/webgames/src/setupTests.ts)
  extending `expect` with jest-dom matchers and auto-cleaning after each test. Run via `pnpm test`.
- [`evals/browseruse_webgames/test_webgames_dataset.py`](https://github.com/convergence-ai/webgames/blob/main/evals/browseruse_webgames/test_webgames_dataset.py) —
  one pytest function, `test_load_webgames_dataset`. Writes a dummy JSONL with 2 valid and 3 malformed rows,
  asserts exactly 2 samples load, and checks the generated prompt text, target password, and metadata dict of
  each. A genuinely good little test — it pins the *malformed-row-skipping* behaviour, which is the only
  place the loader can silently shrink the benchmark.

**CI: none.** There is no `.github/` directory at the repo root or under `webgames/`. Lint (`eslint
--max-warnings 0`) and `tsc -b` exist as pnpm scripts but nothing runs them automatically. Given that the
benchmark's correctness rests on 168 hand-written page components each emitting the right password, 1 test
covering 1 page is the weakest test-to-surface ratio in this batch.

---

## hud-evals/hud-python

> "RL environments + evals for AI agents. Define once, train anything." — 291★, Python, MIT.
> Not a benchmark: a **protocol + SDK + CLI** for authoring environments, tasks, and graders, running them
> as evals across models, and feeding the rewards into RL training. v0.6.13, HEAD 2026-08-15 — the most
> actively developed repo in the batch.

### Repo/Folder Setup

| Path | What it is |
|---|---|
| [`hud/environment/`](https://github.com/hud-evals/hud-python/tree/main/hud/environment) | Environment spec + server: `env.py` (the `Environment` object and `@env.template()` decorator), `server.py`, `workspace.py`, `namespace.py`, `file_tracker.py`, `egress.py`, `robot/` |
| [`hud/eval/`](https://github.com/hud-evals/hud-python/tree/main/hud/eval) | The rollout engine: `task.py`, `taskset.py`, `run.py`, `job.py`, `runtime.py`, `sync.py`, `compose.py`, `chat.py`, `file_tracking.py`, `docker-seccomp.json` |
| [`hud/capabilities/`](https://github.com/hud-evals/hud-python/tree/main/hud/capabilities) | The five connection protocols: `ssh.py`, `mcp.py`, **`cdp.py`** (Chrome DevTools Protocol), `rfb.py` (VNC), `robot.py` |
| [`hud/agents/`](https://github.com/hud-evals/hud-python/tree/main/hud/agents) | Built-in harnesses: `claude/`, `openai/`, `gemini/`, `openai_compatible/`, **`browser_use/`**, `robot/`, `misc/`, plus `base.py` and `tool_agent.py` |
| [`hud/graders/`](https://github.com/hud-evals/hud-python/tree/main/hud/graders) | `text.py` (`exact_match`, `contains*`, `numeric_match`, `f1_score`, `normalize`), `bash.py` (`BashGrader`), `judge.py` (`LLMJudgeGrader`), `combine.py`, `results.py` |
| [`hud/cli/`](https://github.com/hud-evals/hud-python/tree/main/hud/cli) | Typer CLI: `eval`, `serve`, `deploy`, `init`, `sync`, `task`, `jobs`, `trace`, `models`, `login`, `set`, `cancel`, `qa`, `presets`, `templates` |
| [`hud/integrations/harbor/`](https://github.com/hud-evals/hud-python/tree/main/hud/integrations/harbor) | Experimental adapter converting **Harbor** task directories into HUD tasksets (and back) |
| `hud/{clients,telemetry,train,patches,utils}/` | MCP clients, tracing/export, `TrainingClient`, v5 compat shims, helpers |
| [`cookbooks/`](https://github.com/hud-evals/hud-python/tree/main/cookbooks) | 5 standalone `uv` projects: `rl-training` (2048), `fireworks-rl-training`, `connect4-selfplay`, `codex-coding`, `a2a-chat` |
| [`docs/v6/`](https://github.com/hud-evals/hud-python/tree/main/docs/v6) | 35 `.mdx` pages powering [docs.hud.ai](https://docs.hud.ai) |
| [`AGENTS.md`](https://github.com/hud-evals/hud-python/blob/main/AGENTS.md), `CLAUDE.md` | Repo-map + working-style guide for coding agents |

**Language / package manager.** Python `>=3.11,<3.13`, hatchling, **`uv` pinned to exactly `0.12.2`**.
Published to PyPI as `hud` (formerly `hud-python`). Lint = ruff with a very wide rule selection (~26 rule
families incl. bandit `S`, bugbear `B`, Perflint, `ANN` annotations); types = `ty==0.0.67` with
`--error-on-warning` and `blanket-ignore-comment = "error"`.

**Install & configure.**
```bash
uv tool install hud --python 3.12     # CLI
pip install hud                       # library
hud set HUD_API_KEY=your-key          # or export HUD_API_KEY
hud init my-env
```
Optional extras declare the heavier paths: `browseruse` (`browser-use>=0.11.13`), `robot` (openpi-client,
PyAV, gymnasium), `modal`, `daytona`, `bedrock`, `train` (torch), `dev`. Notably, **no API key is required
for a purely local run** — without `HUD_API_KEY`, rollouts run and grade entirely on-machine with no platform
calls.

**Main entry points.**
```bash
hud eval tasks.py claude               # first task, one rollout
hud eval tasks.py claude --all --group 3
hud eval "My Taskset" claude --remote  # hosted infra
hud serve env.py -p 9000               # long-lived control channel
hud task start fix_bug  --url tcp://127.0.0.1:8765
hud task grade fix_bug  --url tcp://127.0.0.1:8765 --answer "..."
hud deploy && hud sync tasks my-taskset
```
Or programmatically: `Taskset.from_file("tasks.py").run(agent, runtime=LocalRuntime("env.py"), group=8)`.
Six runtimes select *where* each rollout runs without touching the environment: `LocalRuntime`,
`DockerRuntime`, `ModalRuntime`, `DaytonaRuntime`, `HUDRuntime`, and a raw `Runtime("tcp://host:port")`.

### Evals

**The repo ships no benchmark and no task set.** That is the design: an environment is an async generator
registered with `@env.template()` that `yield`s a prompt, receives the agent's answer, and `yield`s a reward.
Named tasksets (the docs reference `Taskset.from_api("SheetBench-50")`) live on the hud.ai platform, not in
this repo.

**Protocol.** Three messages define the whole contract: a **manifest** (capabilities + tasks),
**`tasks.start`** → prompt, **`tasks.grade`** → reward. In between the agent drives capabilities directly.
Capabilities relevant to browser agents: **`cdp/1.3`**
([`hud/capabilities/cdp.py`](https://github.com/hud-evals/hud-python/blob/main/hud/capabilities/cdp.py)) opens
a WebSocket to a Chromium page target and speaks CDP JSON-RPC, discovering targets via `GET /json` and
creating one via `/json/new` if none exist; **`rfb`** exposes full computer-use over VNC. The
[`BrowserUseAgent`](https://github.com/hud-evals/hud-python/blob/main/hud/agents/browser_use/agent.py) reads
the `cdp/1.3` binding's URL and hands it to the `browser-use` SDK — deliberately using `client.binding(...)`
(wire data) rather than `client.open(...)`, because browser-use owns the session.

**Metrics: reward, defined by the task author.** Graders
([`hud/graders/`](https://github.com/hud-evals/hud-python/tree/main/hud/graders), documented at
[`docs/v6/reference/graders.mdx`](https://github.com/hud-evals/hud-python/blob/main/docs/v6/reference/graders.mdx))
come in three tiers: plain comparison helpers returning `0.0`–`1.0` (`exact_match`, `contains`,
`contains_any/all`, `numeric_match`, `f1_score`); async graders (`BashGrader` runs `/bin/bash -lc <cmd>` and
scores by exit code; `LLMJudgeGrader` scores against criteria); and `combine(...)` which runs several graders
in parallel and returns a weighted `EvaluationResult` with each `SubScore` preserved in the trace. The docs
draw a useful distinction between *grading the answer* and *grading the world* ("outcome verification" — did
the tests pass, was the file written, is the service responding).

**Results objects.** Every rollout is a `Run` with a `trace_id` and a `reward`; runs group into a `Job`.
`hud jobs`, `hud jobs <id>`, `hud trace <id>` read them from the terminal; with an API key everything also
lands on hud.ai. Because `Run` carries the reward, the same rollouts feed `TrainingClient.step(runs,
learning_rate=…, group_size=8)` for GRPO — evals and training data are the same artifact.

**Reported baselines: none.** No numbers, no leaderboard — appropriate for an SDK. The README's demo GIF
shows an agent on "SheetBench," a platform-hosted taskset.

**Existing-benchmark interop** is the `harbor` integration
([`hud/integrations/harbor/`](https://github.com/hud-evals/hud-python/tree/main/hud/integrations/harbor)):
`taskset = await harbor.adapt("./benchmark")` turns a Harbor task directory into a runnable HUD taskset, and
export works in reverse. It is explicitly labelled experimental.

### Test Cases

**Framework:** pytest with `asyncio_mode = "auto"`, `pytest-mock`, `pytest-cov`. **1,016 test functions
across 21 `tests/` directories**, colocated next to the code they test. `testpaths = ["hud"]` and
`addopts = "-m 'not integration'"` — integration tests (requiring `HUD_API_KEY`, network, or Docker) are
excluded by default and there is exactly one such marker in the tree.

| Directory | Tests | Focus |
|---|---|---|
| [`hud/eval/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/eval/tests) | 180 | `test_rollout.py`, `test_task.py`, `test_job.py`, `test_local_runtime.py`, `test_docker_provider.py`, `test_hosted.py`, `test_sync.py`, `test_chat.py`, `test_file_tracking_observer.py` |
| [`hud/environment/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/environment/tests) | 159 | `test_server.py`, `test_manifest.py`, `test_sessions.py`, `test_capability_backing.py`, `test_workspace.py`, `test_tunnel.py`, `test_loader.py`, `test_robot_regressions.py` |
| [`hud/agents/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/agents/tests) | 125 | One file per harness (`test_claude_agent.py`, `test_openai_agent.py`, `test_gemini_agent.py`, `test_openai_compatible_agent.py`, `test_claude_sdk_agent.py`) plus `test_provider_native_tools.py`, `test_apply_patch.py`, `test_trace.py` |
| [`hud/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/tests) | 116 | `test_graders.py`, `test_types.py`, `test_settings.py`, `test_trace.py`, `test_robot.py` |
| [`hud/cli/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/cli/tests) + `cli/utils/tests/` | 101 + 67 | Every CLI surface: `test_deploy.py`, `test_eval_config.py`, `test_eval_bedrock.py`, `test_qa.py`, `test_sync_export.py`, `test_registry.py`, `test_tasks.py`, `test_version_check.py` |
| [`hud/telemetry/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/telemetry/tests) | 67 | `test_exporter.py`, `test_instrument.py` |
| [`hud/utils/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/utils/tests) | 67 | Exceptions, gateway, serialization, process, platform, console |
| [`hud/integrations/harbor/tests/`](https://github.com/hud-evals/hud-python/tree/main/hud/integrations/harbor/tests) | 58 | `test_harbor.py`, `test_contract.py`, `test_integration.py` |
| `hud/capabilities/tests/` | 17 | `test_ssh.py`, `test_rfb.py` |
| `hud/agents/{claude,gemini,openai}/tools/tests/` | 13 / 9 / 15 | Per-provider computer-tool schema conformance, incl. `test_strict_schema.py` |
| `hud/clients/tests/`, `hud/train/tests/`, `hud/patches/tests/` | 7 / 5 / 2 | Connect, training client, warning suppression |

**Notable cases.**
- [`hud/conftest.py`](https://github.com/hud-evals/hud-python/blob/main/hud/conftest.py) is an autouse fixture
  that monkeypatches `settings.api_key = None` and disables telemetry for every non-integration test. The
  docstring explains exactly why: without it, any developer with `HUD_API_KEY` set would spam the production
  platform with fake jobs while running unit tests — "CI never catches it because CI has no API key."
- `hud/integrations/harbor/tests/tasks/` contains **five complete fixture task directories**
  (`hello-mcp`, `agent-lifecycle`, `phase-boundary`, `verifier-lifecycle`, `sidecar-reachability`), each with
  its own `task.toml`, `instruction.md`, `environment/Dockerfile` (some with `compose.yaml` and a real MCP
  server), `solution/solve.sh`, and `tests/test.sh`. The adapter is tested against real Harbor task layouts,
  not mocks.
- `hud/environment/tests/test_robot_regressions.py` and `hud/tests/test_robot.py` pin the robot wire protocol
  against a checked-in contract shape (`hud-evals/robot-template`'s `contract_lerobot.json`).

**CI:** [`.github/workflows/ci.yml`](https://github.com/hud-evals/hud-python/blob/main/.github/workflows/ci.yml)
on push to `main` and PRs to any branch. Three jobs: `test` (matrix 3.11/3.12, `uv run --with=".[dev]" pytest
--cov`), `lint-ruff` (`ruff format --check` + `ruff check`), `lint-ty` (`ty check --error-on-warning`).
Coverage has a hard gate: `fail_under = 58` in `[tool.coverage.report]`.
[`release.yml`](https://github.com/hud-evals/hud-python/blob/main/.github/workflows/release.yml) builds and
publishes on GitHub release, then force-pushes the release SHA to a `docs` branch that docs.hud.ai builds from.

---

## Cross-Repo Observations

**1. Three architectures, three reproducibility profiles.** The batch cleanly separates into *frozen
snapshots* (bananalyzer's 320 MHTML/HAR captures, webgames' self-contained SPA, miniwob's local HTML) which
are perfectly reproducible offline; *live-system harnesses* (WorkArena against ServiceNow, WebCanvas against
the open internet) which are not; and an *SDK* (hud-python) which is agnostic. WebCanvas quantifies the cost
of the live approach better than anyone: identical agent, identical tasks, **23.6% → 42.3% task-success swing
from IP region and OS/browser alone.** Any survey claim about live-web benchmark numbers needs that caveat
attached.

**2. Everyone converged on substring/JSON matching; nobody uses an LLM judge as the primary metric.**
webgames uses `target in answer` on a secret password. bananalyzer uses `DeepDiff` with fuzzy string
tolerance. WebCanvas uses URL/element/text exact-and-include matchers (only 22 of 443 key nodes use a
`*_semantic_match`). MiniWoB uses a numeric reward from JS. WorkArena uses a binary `validate()`. Only
hud-python ships an `LLMJudgeGrader`, and even there it is one option among several, meant to be *combined*
with deterministic subscores. For a benchmark, cheap deterministic grading is still the consensus.

**3. Oracle solvers and secret passwords are the two ways to make a task self-verifying.** WorkArena's
`cheat()` — a Playwright solver shipped with every task — is what lets its CI ask "is this task still solvable
on today's ServiceNow instance?" nightly. webgames' per-task password is the inverse trick: the environment,
not the grader, decides success, so a model cannot bluff. Both designs make the benchmark testable in a way
that a static expected-output file never can be.

**4. Test coverage tracks whether the repo is a product or a paper artifact.** hud-python (a live commercial
SDK) has 1,016 tests, a 58% coverage gate, and three CI jobs. MiniWoB++ (a Farama-standards library) has a
10-way OS×Python matrix that sweeps all 128 environments through `check_env`. bananalyzer has 64 real unit
tests and a 4-job pipeline. WorkArena has a serious suite but skips much of it for cost. WebCanvas — the one
with a published paper and a leaderboard — has **zero tests and zero CI**; webgames has one test covering 1 of
168 pages. There is an inverse relationship in this batch between "has an academic paper" and "has a test
suite."

**5. The three-tier difficulty design is underused.** webgames is the only repo that systematically ships
easy/base/hard variants of each task family (53 families × 3), and it is the only repo that can therefore
report a difficulty gradient (14% drop easy→base, 15% base→hard). MiniWoB has "Debug Tasks" (12 easier
variants) and WorkArena has L1/L2/L3, but neither reports a per-level curve in-repo. If a survey wants to
argue about *where* agents break rather than *whether*, webgames' design is the one to point at.

**6. Scaffolding matters as much as the model.** webgames' clearest single number:
`claude-3-7-sonnet` scored **44.7% via browser-use (DOM) vs 22.0% via computer-use (pixels)** — the same
model, halved by the harness. That is echoed by the category breakdown (visual comprehension 18.5%, the worst
of five) and by MiniWoB++ shipping four distinct action-space presets specifically so results across papers
are comparable. Benchmark numbers without an action-space/observation-mode label are close to meaningless.

**7. Maintenance status varies enormously.** hud-python (2026-08-15), MiniWoB++ (2026-08-13, though formally
in maintenance mode), and WorkArena (2026-02-03) are alive. webgames (2025-06-02), WebCanvas (2025-02-06), and
bananalyzer (2024-10-20) are effectively dormant — bananalyzer for nearly two years, with a roadmap of
unchecked boxes ("Translate WebArena evals," "Translate Mind2Web evals," "captcha solving") that were never
delivered.

**8. Two repos have documentation drift worth noting.** bananalyzer's README points at
`bananalyzer/data/schemas.py` for the `ExampleType` enum; the file is actually
`bananalyzer/data/example_schemas.py`. WebCanvas ships `scripts/run_evaluation.sh` as a 0-byte file. Neither
is fatal, but both are the kind of thing that costs a first-time user an hour.
