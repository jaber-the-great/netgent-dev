# Browser Agents Survey — Batch 4 (Newer / Miscellaneous Agents)

Research notes for four open-source browser/web-agent repositories. Each was shallow-cloned
(`git clone --depth 1`) and inspected directly; all paths below are repo-relative and were verified
against the cloned trees. Metadata (stars, language, last push) captured **2026-08-16** via the
GitHub API.

| Repo | Stars | Language | License | Last push | Has evals? | Has tests? |
|---|---:|---|---|---|---|---|
| [nanobrowser/nanobrowser](https://github.com/nanobrowser/nanobrowser) | 13,565 | TypeScript | Apache-2.0 | 2025-11-24 | ❌ none | ⚠️ 1 file |
| [nottelabs/notte](https://github.com/nottelabs/notte) | 1,993 | Python | SSPL-1.0 | 2026-08-14 | ✅ separate repo | ✅ 88 files |
| [bytedance/UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) | 38,609 | TypeScript | Apache-2.0 | 2026-08-05 | ⚠️ perf only | ✅ ~128 files |
| [Alibaba-NLP/WebAgent](https://github.com/Alibaba-NLP/WebAgent) → `DeepResearch` | 19,832 | Python | Apache-2.0 | 2026-02-27 | ✅ extensive | ❌ none |

> **Note on repo #4:** `Alibaba-NLP/WebAgent` now **301-redirects to
> [`Alibaba-NLP/DeepResearch`](https://github.com/Alibaba-NLP/DeepResearch)**. The repo was renamed
> when Tongyi DeepResearch became the headline project; the original WebAgent family lives on as the
> [`WebAgent/`](https://github.com/Alibaba-NLP/DeepResearch/tree/main/WebAgent) subdirectory. Cloning
> the old URL still works and lands you in the renamed repo.

---

## nanobrowser

Open-source Chrome extension (Manifest V3) that runs a multi-agent web-automation loop entirely in
the browser using your own LLM API keys — positioned as a free alternative to OpenAI Operator.
**13,565 stars · TypeScript · Apache-2.0.**

### Repo/Folder Setup

pnpm workspace monorepo orchestrated by Turborepo; each workspace is bundled independently with Vite.

```
nanobrowser/
├── chrome-extension/        # MV3 extension core: manifest + background service worker
│   ├── manifest.js          # MV3 manifest generator (permissions, side_panel, options_page)
│   └── src/background/
│       ├── index.ts         # service-worker entry point; chrome.runtime message router
│       ├── agent/           # the multi-agent system
│       │   ├── agents/      # base.ts, navigator.ts, planner.ts, errors.ts
│       │   ├── actions/     # builder.ts (~31 KB action registry), schemas.ts (zod)
│       │   ├── prompts/     # base.ts, navigator.ts, planner.ts + templates/
│       │   ├── messages/    # conversation/message-history management
│       │   └── event/       # execution event bus streamed to the side panel
│       ├── browser/         # context.ts, page.ts, views.ts + dom/ (clickable/, history/)
│       ├── services/        # analytics.ts, speechToText.ts, guardrails/
│       └── task/manager.ts  # task lifecycle
├── pages/                   # three separately-bundled UI surfaces
│   ├── side-panel/          # main chat UI (React 18 + Tailwind)
│   ├── options/             # settings page (LLM providers, per-agent model choice)
│   └── content/             # content script injected into pages for DOM access
├── packages/                # shared workspaces
│   ├── storage/lib/settings/  # agentModels.ts, llmProviders.ts, firewall.ts, generalSettings.ts
│   ├── shared/  ui/  i18n/  schema-utils/
│   └── dev-utils/  hmr/  zipper/  vite-config/  tailwind-config/  tsconfig/
├── turbo.json  pnpm-workspace.yaml  package.json
└── CLAUDE.md (→ AGENTS.md symlink), Tech_Report.pdf-free; FAQ.md, PRIVACY.md
```

**Language / package manager:** TypeScript 5.5, **pnpm 9.15.1**, Node **≥22.12.0** (`.nvmrc` pins
`22.12.0`). Turborepo 2.5 + Vite 6. LLM access via **LangChain.js** — `@langchain/{openai,anthropic,
google-genai,groq,ollama,deepseek,cerebras,xai}` are direct deps of
[`chrome-extension/package.json`](https://github.com/nanobrowser/nanobrowser/blob/master/chrome-extension/package.json).
`puppeteer-core` is a dependency but the extension drives the page through the **`chrome.debugger`
API** (see `permissions` in `chrome-extension/manifest.js`), not a spawned browser.

**Install / configure:**

```bash
pnpm install
pnpm build          # → dist/ ; then chrome://extensions → Developer mode → Load unpacked → dist/
pnpm dev            # watch mode (__DEV__=true)
pnpm zip            # → dist-zip/nanobrowser.zip (what release artifacts are)
```

There are **no LLM env vars**. API keys are entered at runtime in the extension's Options page and
persisted in `chrome.storage` via `packages/storage/lib/settings/llmProviders.ts`; models are then
assigned per-agent (Navigator / Planner) via `agentModels.ts`. The only `.env` in the repo is
[`.env.example`](https://github.com/nanobrowser/nanobrowser/blob/master/.env.example), which holds a
single build-time key: `VITE_POSTHOG_API_KEY` (analytics). Manifest permissions requested:
`storage, scripting, tabs, activeTab, debugger, unlimitedStorage, webNavigation` plus
`host_permissions: ['<all_urls>']`.

**Entry points for a user:** install from the Chrome Web Store (or load `dist/` unpacked) → click the
toolbar icon → the **side panel** chat UI (`pages/side-panel`) is the sole interface. There is no CLI,
no SDK, and no programmatic API surface.

> ⚠️ **Docs drift worth noting:** `CLAUDE.md:81-91` describes three agents — "Navigator, Planner,
> **Validator**". Grepping `chrome-extension/src/background/agent/` for `Validator` returns **zero
> hits**; the shipped system is two agents (`navigator.ts`, `planner.ts`). The docs are stale.

### Evals

**None.** This is the clearest finding for this repo. A case-insensitive grep across all `.ts`,
`.tsx`, `.md`, and `.json` files for `webvoyager|webarena|mind2web|gaia|osworld|benchmark` returns
**zero matches**. The README contains no scores, no success rates, and no benchmark section — its
"model recommendations" section is qualitative advice only ("Planner: Claude Sonnet 4 — better
reasoning"), and it defers empirical model comparison to a
[community gist](https://gist.github.com/maximus2600/75d60bf3df62986e2254d5166e2524cb) and Discord.
There is no `eval/`, `benchmark/`, or task-set directory anywhere in the tree.

### Test Cases

**Nearly nonexistent — one test file, 132 lines, and no CI at all.**

- **Framework:** Vitest 2.1.9, declared only in `chrome-extension/package.json`
  (`"test": "pnpm vitest run"`). There is **no `vitest.config.*` file anywhere in the repo** — it runs
  on Vitest defaults.
- **Layout:** `chrome-extension/src/**/__tests__/*.test.ts`. In practice that resolves to exactly one
  file:
  [`chrome-extension/src/background/services/guardrails/__tests__/guardrails.test.ts`](https://github.com/nanobrowser/nanobrowser/blob/master/chrome-extension/src/background/services/guardrails/__tests__/guardrails.test.ts).
- **Category:** pure unit tests of the **prompt-injection guardrail layer** — no browser, no LLM, no
  DOM. 20 `describe`/`it` blocks across three suites: *Sanitizer*, *Strictness options*, and
  *Messages utils integration*.
- **Notable cases** (genuinely interesting, and the only security-relevant tests in the repo):
  - **Zero-width-character evasion**: input `'Please ig​nore previous instructions...'` must still
    be flagged `ThreatType.TASK_OVERRIDE` and rewritten to `[BLOCKED_OVERRIDE_ATTEMPT]`, with
    `[​-‍﻿]` stripped from the output.
  - **Whitespace normalization invariants**: collapse runs of spaces/tabs, reduce 3+ blank lines to
    exactly two, but preserve newlines.
  - **Strict vs. loose mode**: `api key: abc123` triggers `ThreatType.SENSITIVE_DATA` only under
    `{strict: true}`; asserts `sanitizeStrict(x) ≡ sanitize(x, {strict: true})`.
  - **`wrapUntrustedContent`** must preserve its warning banners and tags around scraped page content.
- **CI: there is none.** `.github/` contains only `FUNDING.yml` and `ISSUE_TEMPLATE/` — **no
  `.github/workflows/` directory exists**. Nothing runs tests, lint, or type-check on push or PR. The
  only automated gate is a Husky `pre-commit` hook running `lint-staged` → `prettier --write`
  (formatting only, not tests).
- **Dead e2e script:** root `package.json` defines `"e2e": "pnpm build && pnpm zip && turbo e2e"` and
  `turbo.json` declares an `e2e` task, but **no workspace package defines an `e2e` script** — grepping
  `'"e2e"'` across all `package.json` files matches only the root definition. The command is a no-op.

---

## Notte

Full-stack Python web-agent framework — local Playwright/Patchright sessions plus a hosted cloud
browser API (sessions, vaults, personas, workflows). **1,993 stars · Python · SSPL-1.0.**

### Repo/Folder Setup

uv workspace with six independently-versioned packages, all at version `1.4.4.dev`.

```
notte/
├── src/notte/__init__.py    # the `notte` facade package — re-exports from the workspace members
├── packages/
│   ├── notte-core/src/notte_core/     # actions/, browser/, credentials/, data/, space.py,
│   │                                  # trajectory.py, config.toml, errors/
│   ├── notte-browser/src/notte_browser/  # session.py, playwright.py, controller.py, captcha.py,
│   │                                  # form_filling.py, vault.py, window.py, resolution.py
│   │                                  # + dom/, tagging/, scraping/, rendering/,
│   │                                  #   action_selection/, tools/
│   ├── notte-agent/src/notte_agent/   # agent.py, main.py, workflow.py, agent_fallback.py,
│   │                                  # falco/ (the default agent: agent.py, perception.py,
│   │                                  #   prompt.py), common/ (validator.py, parser.py, ...)
│   ├── notte-sdk/src/notte_sdk/       # client.py, endpoints/, websockets/, types.py
│   ├── notte-llm/  notte-integrations/
├── tests/                   # 88 pytest files (see Test Cases)
├── examples/                # quickstart.py, cli_agent.py + 9 runnable scenario dirs
│                            #   (auth-vault-agent, order-on-ubereats, session-solve-captcha,
│                            #    scrape-nike-products, star-our-repo, email-notifier-agent, ...)
├── docs/                    # Mintlify site + sphinx SDK-reference generator + snippet testers
├── typing_cases/            # basedpyright/ty overload-resolution regression cases
├── scripts/  templates/  browserarena/  notte-cli/  notte-skills/   ← last four are git submodules
├── makefile                 # the canonical task runner
└── pyproject.toml  uv.lock  .pre-commit-config.yaml  .python-version (3.11)
```

**Language / package manager:** Python **≥3.11** (`.python-version` = `3.11`), managed with **uv**
(`[tool.uv.workspace] members = ["packages/*", "."]`), built with hatchling. Lint/format: **ruff**
(line-length 120); type-checking: **basedpyright** (`failOnWarnings = true`) plus `ty`.

**Submodules** (`.gitmodules`) point at four sibling repos:
[`browserarena`](https://github.com/nottelabs/browserarena) (28★, TS — cloud-browser-provider
comparison), [`notte-cli`](https://github.com/nottelabs/notte-cli),
[`notte-skills`](https://github.com/nottelabs/notte-skills), and
[`templates`](https://github.com/nottelabs/templates). A plain `--depth 1` clone leaves these as
empty directories.

**Install / configure:**

```bash
pip install notte
patchright install --with-deps chromium      # note: patchright (stealth Playwright fork), not playwright
# dev setup:
make install                                  # uv sync --dev --all-extras && uv export > requirements.txt
```

Env vars from [`.env.example`](https://github.com/nottelabs/notte/blob/main/.env.example) split into
two blocks — **SDK config** (`NOTTE_API_URL=api.notte.cc`, `NOTTE_API_KEY`) and **local dev** LLM keys
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`,
`DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY` + `ENABLE_OPENROUTER`). Only one provider key is required;
the README advises setting several to dodge rate limits.

**Entry points.** Two symmetric surfaces — the local one and the hosted one differ only by the import:

```python
# local (open-source features, your own LLM keys)
import notte
with notte.Session(headless=False) as session:
    agent = notte.Agent(session=session, reasoning_model='gemini/gemini-2.5-flash', max_steps=30)
    response = agent.run(task="doom scroll cat memes on google images")

# hosted (cloud browser sessions, vaults, personas, CAPTCHA solving)
from notte_sdk import NotteClient
client = NotteClient(api_key=os.getenv("NOTTE_API_KEY"))
with client.Session(open_viewer=True) as session:
    agent = client.Agent(session=session, reasoning_model='gemini/gemini-2.5-flash', max_steps=30)
    response = agent.run(task="...")
```

`src/notte/__init__.py` is a thin re-export facade: `Session` ← `notte_browser.session.NotteSession`,
`Agent`/`AgentFallback` ← `notte_agent`, `NotteClient` ← `notte_sdk.client`. Lower-level primitives
(`GotoAction`, `ClickAction`, `FillAction`, `ScrapeAction`, `session.aobserve()`, `session.aexecute()`)
are exposed for scripted/deterministic automation, which is Notte's core pitch: script the
deterministic parts, invoke the LLM only where needed.

### Evals

Notte is the **only repo in this batch that publishes head-to-head, reproducible agent benchmark
numbers** — but the eval code lives in a **separate repo**, not in `notte/`.

**Reported results** (README.md:75-83, reproduced verbatim from
[`nottelabs/open-operator-evals`](https://github.com/nottelabs/open-operator-evals), 47★):

| Rank | Provider | Agent Self-Report | LLM Evaluation | Time per Task | Task Reliability |
|---|---|---|---|---|---|
| 🏆 | **Notte** (v1.3.3, `gemini/gemini-2.0-flash`) | **86.2%** | **79.0%** | **47s** | **96.6%** |
| 2 | Browser-Use (v0.1.40, `openai/gpt-4o`) | 77.3% | 60.2% | 113s | 83.3% |
| 3 | Convergence proxy-lite (`a4389c5`) | 38.4% | 31.4% | 83s | 50% |

- **Benchmark:** **WebVoyager30** — a 30-task subset sampled across 15 sites from WebVoyager's ~600
  tasks, introduced by Notte specifically to make multi-run evaluation affordable. Each task is run
  **8×** per provider (240 runs), capped at **20 steps / 6 minutes**, headless.
- **Metrics:** *Agent Self-Report* (agent's own success claim), *LLM Evaluation* (GPT-4 judge using
  WebVoyager's official evaluation prompt), *Alignment* (self-report ÷ LLM-eval; >1.0 = the agent
  over-claims), *Mismatch* (count of claimed-success/judge-disagree), and *Task Reliability*
  (% of tasks solved at least once across the 8 attempts).
- **Explicit reproduction dispute:** the eval README states Browser-Use's self-reported
  [89% WebVoyager SOTA claim](https://browser-use.com/posts/sota-technical-report) could **not** be
  reproduced, and notes their result files aren't published for verification.
- **Cost disclosure:** WebVoyager30 × 8 tries ≈ $0 for Notte (Gemini free tier) and Convergence,
  ≈ **$20** for Browser-Use with GPT-4o (7.4M input + 145K output tokens).
- **Environment caveat, disclosed:** run on an M1 MacBook, Python 3.11, from a **residential Swiss
  IP** — which triggers German-language cookie-consent popups visible in the replays and makes tasks
  harder.

**Where the eval code lives** (in `nottelabs/open-operator-evals`, *not* in `notte/`):

| Path | Purpose |
|---|---|
| `eval/run.py` | Harness entry point — `RunParameters` (n_jobs, tries_per_task, evaluator, max_task_duration_in_s), `pebble`-based process pool, `cloudpickle` |
| `eval/agent_handlers/` | One adapter per system: `falco.py` (Notte), `browseruse.py`, `browseruse_api.py`, `convergence.py`, `mock.py` |
| `eval/evaluators/webvoyager.py` | The GPT-4 LLM-judge implementing WebVoyager's official prompt |
| `eval/data/webvoyager/webvoyager_simple.jsonl` | **The WebVoyager30 task set** (+ `webvoyager.jsonl` full set, `_single`, `_convergence`, `_excluded`, `archive/`) |
| `eval/data/gaia/GAIA_webvoyager.jsonl` | A GAIA task file — present but not used in the published table |
| `configs/*.toml` | Per-provider run configs: `notte.headless.gemini.toml`, `browseruse.headless.openai.toml`, `convergence.headless.toml` |
| `WebVoyager30/<Provider>/<timestamp>/<task>/` | **Full published artifacts** — `results.json`, `results_no_screenshot.json`, `summary.webp` replay per run |

**Launching an eval run** — config is piped in on stdin:

```bash
cat configs/notte.headless.gemini.toml | uv run python -m eval.run
```

The config declares `n_jobs = 4`, `tries_per_task = 8`, `evaluator = "webvoyager"`,
`max_task_duration_in_s = 360`, `task_set.name = "WebVoyager30"`, and agent params
(`max_steps = 20`, `use_vision = true`, `headless = true`, pinned user-agent, `pool = "None"` for
local vs. anchor/browserbase/steel for hosted).

### Test Cases

The most thoroughly tested repo in this batch: **88 Python test files** under `tests/`.

- **Framework:** pytest 8.3+ with a deep plugin stack declared in `pyproject.toml`'s dev group:
  `pytest-asyncio` (strict mode, session-scoped loop), `pytest-xdist[psutil]` (parallel),
  `pytest-cov`, `pytest-mock`, `pytest-timeout` (**300s global timeout**, thread method),
  `pytest-rerunfailures` (flaky retries), `pytest-order`, `pytest-examples` (executes docs/README
  code blocks), `freezegun`.
- **Layout** (`testpaths = ["tests"]`):

| Directory | Files | What it covers |
|---|---:|---|
| `tests/integration/sdk/` | 15 | Live SDK calls against staging: sessions, agents, vault, personas, profiles, cookies, CDP, workflows, workflow runs, steps, scraping, interaction, `file_storage/` (upload/download/readonly) |
| `tests/sdk/` | 18 | SDK unit tests: client, typed dicts, overload ordering, OpenAPI spec conformance, orphan-model detection, proxy settings, replay frames, endpoint paths, log timeouts, version check |
| `tests/browser/` | 9 | DOM tree building & pointer elements, clipboard isolation, node types, screenshot types, window options, fallback logging, raw file handling, tools |
| `tests/llms/` | 6 | Prompt-discrepancy checks (action-listing, extract-data), engine, structured output, OpenRouter models |
| `tests/actions/` | 5 | Action parsing, execution, form fill, email verification, typed dicts |
| `tests/pipe/` | 6 | Perception pipeline: action listing/main/retry, scraping pruning/schema/url-percentage |
| `tests/agent/` | 3 | `test_main_agent.py`, `test_validator.py`, `test_consistent_trajectory.py` |
| `tests/config/`, `tests/utils/`, `tests/cache/`, `tests/scripts/`, `tests/code/`, `tests/chapter/` | 13 | Config resolution, encryption, image/url utils, centralized cache, script validator |
| `tests/examples/` | 2 | `test_examples.py`, `test_readme.py` |
| `tests/mock/` | 5 | Shared fixtures: `mock_browser.py`, `mock_env.py`, `mock_service.py`, `mock_vault.py`, `snapshot_factory.py` |
| `tests/integration/` (top) | 6 | `test_webvoyager_scripts.py`, `test_special_actions.py`, `test_basic_scripts.py`, `test_resolution.py`, `test_telemetry.py`, `test_window_options.py` |

- **Notable / interesting test cases:**
  - **`tests/integration/test_webvoyager_scripts.py`** — real-web smoke tests replaying hand-scripted
    WebVoyager-style trajectories against **live sites** (HuggingFace model search, Google search,
    Reddit, BBC) using raw `GotoAction`/`FillAction`/`ClickAction` with `perception_type="fast"`. It
    encodes real-world flakiness: the Google test branches on whether the cookie-consent dialog
    appeared (`if not page.snapshot.dom_node.find("I1"): click B3`), and the Reddit/BBC tests carry
    `@pytest.mark.skip(reason="This test is not working on the CI for some reason")`. This file is
    **excluded from CI** by `make test-cicd`.
  - **`tests/examples/test_readme.py`** — uses `pytest-examples` `find_examples`/`eval_example` to
    **execute the Python code blocks in README.md**, and separately spins up a throwaway `venv` to
    `pip install` the published package and verify the documented import works.
  - **`tests/agent/test_main_agent.py`** — end-to-end live agent run
    (`agent.run(task="...extract pricing tiers...", url="https://notte.cc")`) asserting a non-empty
    answer and `response.success`, wrapped in `@pytest.mark.flaky(reruns=3, reruns_delay=5)`.
  - **`tests/sdk/test_no_orphan_models.py` / `test_openapi_spec.py` / `test_overload_order.py`** — API
    surface hygiene enforced as tests rather than lint.
  - **`typing_cases/`** — a separate basedpyright/`ty` project (`pyrightconfig.json`, `ty.toml`) that
    regression-tests **overload resolution** for `scrape` (`scrape_overloads.py`).
  - **`tests/conftest.py`** — points `NOTTE_CONFIG_PATH` at a test-only TOML and sets
    `DISABLE_GPU=true` when `GITHUB_ACTIONS` is set.

- **Make targets:** `make test` (`pytest -n 3 tests`), `make test-cicd` (same minus the WebVoyager,
  examples, and readme suites), `make test-sdk`, `make test-agent`, `make test-docs`,
  `make test-readme`, `make test-examples`, `make test-sdk-staging` (rewrites `NOTTE_API_URL` to
  staging, runs, then restores it).

- **CI — 5 workflows in `.github/workflows/`:**
  - **`test-cicd.yml`** — the main suite, on push-to-main / PR / `workflow_dispatch`. Runs on
    `blacksmith-4vcpu-ubuntu-2404`, 20-min timeout. Installs uv, caches **patchright chromium**
    (`PLAYWRIGHT_BROWSERS_PATH`) and pre-commit, runs `pre-commit run --all-files`, then
    `pytest -n logical tests` with coverage → posts a coverage comment via
    `MishaKav/pytest-coverage-comment`. **Notable security design, documented in an in-file comment
    block:** it deliberately uses `pull_request` and never `pull_request_target`; an `IS_TRUSTED` env
    guard (`github.event.pull_request.head.repo.full_name == github.repository`) gates every
    secret-consuming step so **fork PRs run install + pre-commit only**, and a maintainer must
    `workflow_dispatch` with a PR number *after reviewing the diff* to run the secret-backed suite.
  - **`nightly-examples.yml`** — cron `0 6 * * *`, 75-min timeout. Runs the `examples/` suite against
    **live authenticated sites** using bot credentials in secrets: GitHub (with
    `BOT_GITHUB_COM_MFA_SECRET`), LeetCode, Uber (with MFA), plus SMTP and a hardcoded test credit
    card (`4242424242424242`). Reports to Slack via webhook.
  - **`docs-tests-cicd.yml`** — path-filtered on `docs/**`; a `syntax-check` job that pytest-executes
    doc snippets, gated ahead of a `type-check` job.
  - **`nightly-test-release.yml`**, **`pypi-release.yml`** — release verification and publishing.

---

## UI-TARS-desktop *(browser-operation side)*

ByteDance's multimodal agent stack — two shipped products in one monorepo: **Agent TARS** (a
CLI/Web-UI general agent with a hybrid browser agent) and **UI-TARS Desktop** (an Electron GUI agent
driven by the UI-TARS VLM). **38,609 stars · TypeScript · Apache-2.0.**

### Repo/Folder Setup

Two nested pnpm workspaces: the root workspace (`pnpm-workspace.yaml`) and a **separate inner
workspace under `multimodal/`** with its own `pnpm-lock.yaml`, `pnpm-workspace.yaml`, and
`vitest.config.mts`. This split matters — CI treats them as two independent builds.

```
UI-TARS-desktop/
├── apps/ui-tars/                    # the Electron desktop app (UI-TARS Desktop)
│   ├── src/  electron.vite.config.ts  forge.config.ts  electron-builder.yml
│   ├── e2e/app.test.ts              # Playwright + electron-playwright-helpers
│   └── playwright.config.ts
├── packages/agent-infra/            # ★ the browser-operation layer
│   ├── browser/src/                 # base-browser.ts, local-browser.ts, remote-browser.ts,
│   │                                # browser-finder/ (locates installed Chrome/Edge/Firefox)
│   ├── browser-use/src/             # a full DOM-based browser agent (see note below)
│   │   ├── agent/{actions,agents,event,messages,prompts}/
│   │   ├── browser/  dom/{,history}/
│   │   └── test/
│   ├── mcp-servers/browser/         # ★ @agent-infra/mcp-server-browser — the shipped MCP server
│   │   ├── src/{index,server,context,store,request-context,constants,typings}.ts
│   │   ├── tests/  Dockerfile  Dockerfile.http  smithery.yaml  server.json
│   ├── mcp-servers/{commands,filesystem,search}/
│   ├── mcp-benchmark/               # transport/proxy perf benchmarks
│   ├── mcp-client/  mcp-http-server/  mcp-shared/  search/  logger/  shared/  create-new-mcp/
├── packages/ui-tars/                # the UI-TARS SDK & operators
│   ├── sdk/                         # GUIAgent SDK
│   ├── operators/browser-operator/  # ★ browser as a GUI-agent target (coordinate-based)
│   ├── operators/{browserbase,nut-js,adb}/
│   ├── action-parser/               # parses VLM output → structured actions
│   └── cli/  electron-ipc/  shared/  utio/  visualizer/
├── multimodal/                      # the Agent TARS inner workspace
│   ├── agent-tars/{core,cli,interface}/   # core/src/environments/{local,aio,base}/
│   ├── gui-agent/                   # action-parser/, agent-sdk/, cli/,
│   │                                # operator-{browser,nutjs,adb,aio}/, shared/
│   ├── tarko/                       # 22 sub-packages: agent, agent-server, agent-ui, llm,
│   │                                # model-provider, mcp-agent, context-engineer, agio, ...
│   ├── omni-tars/  websites/
│   └── benchmark/content-extraction/  # ★ page-content-extraction benchmark
├── examples/{gui-agent-2.0,operator-browserbase,presets}/
├── infra/pdk/  rfcs/  docs/  scripts/  patches/
└── turbo.json  vitest.config.mts  vitest.workspace.mts  codecov.yml  .changeset/
```

**Language / package manager:** TypeScript 5.7, **pnpm 9.10.0**, Node **≥20** (root; `multimodal/`
CI uses Node 22, and the Agent TARS CLI requires **Node ≥22**). Turborepo 2.4, Vitest 3, rslib for
library builds, Electron Forge + electron-builder for the desktop app, Changesets for releases.

**Three distinct browser-operation paths** — worth separating, since the repo mixes them:

1. **DOM/accessibility path** — `packages/agent-infra/mcp-servers/browser` (published as
   `@agent-infra/mcp-server-browser`): a Puppeteer-based MCP server that exposes the page via
   *structured accessibility data with label indices*, explicitly "no vision models needed", with an
   optional vision mode. Installed by MCP clients with
   `npx @agent-infra/mcp-server-browser@latest`; also ships `Dockerfile`, `Dockerfile.http`, and a
   `smithery.yaml`.
2. **Visual-grounding path** — `packages/ui-tars/operators/browser-operator` + `multimodal/gui-agent/
   operator-browser`: the browser as a screenshot/coordinate target for the UI-TARS VLM, same
   interface as the `nut-js` (desktop) and `adb` (Android) operators.
3. **Hybrid** — Agent TARS picks between them via `BrowserControlMode`: `'hybrid' | 'dom' |
   'visual-grounding'` (`multimodal/agent-tars/core/src/types`).

> **Cross-repo lineage:** `packages/agent-infra/browser-use/README.md` credits, verbatim, "[alexchenzl]
> for creating a great **[nanobrowser](https://github.com/nanobrowser/nanobrowser)** Chrome extension
> from which we got a lot of technical references when implementing browser in Electron" (alongside
> browser-use and puppeteer). The directory layout mirrors nanobrowser's almost exactly:
> `agent/{actions,agents,event,messages,prompts}/` + `dom/history/`. So repo #1 in this batch is a
> direct ancestor of part of repo #3.

**Install / configure:**

```bash
# Agent TARS (browser agent, CLI):
npx @agent-tars/cli@latest
npm install -g @agent-tars/cli@latest          # requires Node >= 22
agent-tars --provider volcengine --model doubao-1-5-thinking-vision-pro-250428 --apiKey ...
agent-tars --provider anthropic --model claude-3-7-sonnet-latest --apiKey ...

# UI-TARS Desktop:
brew install --cask ui-tars                     # or download from the Releases page
# then grant macOS Accessibility + Screen Recording permissions (docs/quick-start.md)

# From source:
pnpm install && pnpm dev:ui-tars                # turbo run ui-tars-desktop#dev
```

Root [`.env.example`](https://github.com/bytedance/UI-TARS-desktop/blob/main/.env.example) is the VLM
endpoint config only: `VLM_PROVIDER`, `VLM_BASE_URL`, `VLM_API_KEY`, `VLM_MODEL_NAME` (the example
points at a HuggingFace Inference Endpoint). Model API keys for Agent TARS are passed as CLI flags or
via its config file. `docs/quick-start.md` notes the Browser Operator requires an installed
Chrome/Edge/Firefox, and that the desktop app supports **single-monitor setups only**.

### Evals

**No agent-task benchmarks in this repo.** A repo-wide grep for
`online-mind2web|webvoyager|osworld|androidworld|gaia-benchmark` matches **nothing** outside a
scraped copy of the OSU-NLP GUI-Agents paper list sitting in benchmark fixture data. The headline
UI-TARS model scores (OSWorld, Online-Mind2Web, AndroidWorld, etc.) live in the
[UI-TARS model repo](https://github.com/bytedance/UI-TARS) and the
[paper (arXiv:2501.12326)](https://arxiv.org/abs/2501.12326), which is all this repo cites — see the
Citation section of `README.md`. The README has no benchmark table at all.

What this repo *does* benchmark is **infrastructure performance**, in two places:

1. **`packages/agent-infra/mcp-benchmark/`** — MCP transport and HTTP-proxy throughput for the
   **browser MCP server**, measured with `vitest bench`.
   - Code: `benchmarks/browser_server.bench.ts`, helper `helpers/utils.ts`.
   - Launch: `cd packages/agent-infra/mcp-benchmark && pnpm run benchmark`
     (`vitest bench --run --silent`; `pnpm run dev` for the non-silent variant).
   - Published results (`README.md`): transports — InMemory **4,539 hz** (fastest) > StreamableHTTP
     744 hz > SSE 608 hz > **Stdio 6.77 hz** (slowest); proxies — `mcp-http-server` sse **941 hz** >
     mcp-http-server mcp 827 hz > mcp-proxy(TS) mcp 722 hz > supergateway sse 450 hz >
     mcp-proxy(Python) mcp **195 hz**.
   - **CI-gated:** [`.github/workflows/benchmark.yml`](https://github.com/bytedance/UI-TARS-desktop/blob/main/.github/workflows/benchmark.yml)
     runs it on every PR touching `packages/agent-infra/mcp-*/**`.

2. **`multimodal/benchmark/content-extraction/`** — compares four **page-content-extraction
   strategies** used to feed page text to an LLM, on time, output length, and token count.
   - Code: `src/index.ts`, `src/strategies/`; results checked in under `result/<site>/<strategy>/`
     (`original.md`, `result.md`, `summary/results.json`) for `developer.mozilla.org` and
     `github.com/OSU-NLP-Group/GUI-Agents-Paper-List`.
   - Launch: `pnpm bench` (`ts-node src/index.ts --save`) or `pnpm bench:memory`
     (`node --expose-gc … tsx src/index.ts`).
   - Published results: on an 829,024-char page — `RawContent` 153,825 tokens (baseline, 492 ms);
     `CurrentMarkdown` 29,623 tokens / **19.26%** of baseline (494 ms); `Readability` (Mozilla)
     35,457 tokens / 23.05% (622 ms); `Optimized` 79,581 tokens / 51.73% (589 ms). Motivated
     explicitly by OOM failures on large pages.
   - Not wired into CI.

There is also a `GAIA` *cameo*: `multimodal/omni-tars/mcp-agent/examples/question.ts` hardcodes three
GAIA questions (`GAIA_P1`–`P3`, with task IDs in comments) used by `examples/claude.ts` as a manual
smoke script. It is an example, not an eval — no scoring, no dataset, no runner.

### Test Cases

**~128 test/bench files**, unevenly distributed: `multimodal/` 82, `packages/agent-infra/` 28,
`packages/ui-tars/` 9, `apps/` 8, `infra/` 1.

- **Framework:** **Vitest 3** throughout, with a root `vitest.workspace.mts`
  (`defineWorkspace(['src/*', 'packages/*'])`) and per-package `vitest.config.mts`. Coverage via
  `@vitest/coverage-istanbul` → lcov → **Codecov**, with per-component flags (`codecov.yml`; the
  browser MCP server carries its own `component=mcp_server_browser` badge). E2E uses **Playwright
  1.49** + `electron-playwright-helpers`.
- **Categories:**
  - **Unit** — the bulk. Heaviest concentration on **action parsing**: `packages/ui-tars/action-parser/
    test/` and `multimodal/gui-agent/action-parser/test/` (`actionParser.test.ts`,
    `coordinates.test.ts`, `defaultActionParser.test.ts`, `functionCallactionParser.test.ts`,
    `xmlParser.test.ts`, `hallucinationCases.test.ts`, plus `index.bench.ts`).
  - **Integration (browser)** — `packages/agent-infra/mcp-servers/browser/tests/`: `tools/`
    (`action.test.ts`, `content.test.ts`, `download.test.ts`, `evaluate.test.ts`, `navigate.test.ts`,
    `navigate.bench.ts`, `tabs.test.ts`), `resources/resources.test.ts`, `utils/utils.test.ts`, plus
    module-format matrix tests (`server_esm.test.mts`, `server_cjs.test.cts`,
    `server-in-memory.test.ts`, `server-test.test.ts`) and `__snapshots__/`.
  - **Agent-level** — `multimodal/agent-tars/core/tests/`: `browser/` (`browser-tools-manager`,
    `browser-control-validator`, `parse-action`), `environments/` (`aio-environment`,
    `agent-tars-aio-integration`), `filesystem/`, `shared/`.
  - **E2E** — `apps/ui-tars/e2e/app.test.ts`: launches the packaged Electron binary via
    `findLatestBuild()`/`parseElectronApp()`, drives `electronApp.firstWindow()`, and captures
    `pageerror`/console output.
- **Notable test cases:**
  - **`multimodal/agent-tars/core/tests/browser-control-strategies.test.ts`** — the most
    survey-relevant test here. An `it.each(['hybrid', 'dom', 'visual-grounding'])` that instantiates
    a real `AgentTARS` per mode, initializes it, and **snapshots the exact registered tool set**
    (name + description + JSON schema) into
    `tests/__snapshots__/browser_tools_{hybrid,dom,visual-grounding}.snap`. It pins the
    browser-control contract: changing which tools a mode exposes fails CI.
  - **`packages/agent-infra/mcp-servers/browser/tests/server-in-memory.test.ts`** — wires an MCP
    `Client` to `createServer({launchOptions:{headless:true}})` over `InMemoryTransport.createLinkedPair()`,
    serves fixtures from a local `express` app, and asserts on rendered output using `jimp`/`sharp`
    for image comparison.
  - **`hallucinationCases.test.ts`** (gui-agent action-parser) — a dedicated suite for malformed /
    hallucinated VLM action output.
  - The **ESM/CJS matrix** (`server_esm.test.mts`, `server_cjs.test.cts`, `tests/index.cjs`) —
    verifies the published MCP server loads correctly under both module systems, which matters
    because it's distributed via `npx`.
- **CI — 8 workflows in `.github/workflows/`:**
  - **`test.yml`** ("CI Test, Typecheck") — PR + push-to-main, **`paths-ignore: multimodal/**`**. Runs
    on `macos-latest`, installs **Chrome 120** via `browser-actions/setup-chrome`, then
    `turbo run typecheck` + `turbo run coverage` → Codecov with `fail_ci_if_error: true`.
  - **`agent_tars_test.yml`** ("Agent TARS Build") — the mirror image, `paths: multimodal/**`, on
    `ubuntu-latest` with Node 22: `pnpm install && pnpm bootstrap && pnpm test` inside `multimodal/`.
  - **`e2e-ui-tars.yml`** — Electron E2E on a **3-OS matrix** (`macos-latest`, `macos-13`,
    `windows-latest`), `fail-fast: false`, running `turbo run ui-tars-desktop#test:e2e`.
    `playwright.config.ts` sets `retries: 2` in CI, `workers: 1`, 60 s timeout.
  - **`benchmark.yml`** — the MCP benchmark, path-filtered (above).
  - **`secretlint.yml`**, **`secret-scan.yml`**, **`scorecard.yml`** (OSSF), **`release-ui-tars.yml`**.
  - All third-party actions are **pinned to commit SHAs**, not tags.

---

## Alibaba-NLP/WebAgent → Alibaba-NLP/DeepResearch

Alibaba Tongyi Lab's research-model family for long-horizon information seeking. The repo now
headlines **Tongyi DeepResearch-30B-A3B** (30.5B total / 3.3B active, 128K context) and keeps the
original WebAgent family — WebWalker, WebDancer, WebSailor, WebShaper, WebWatcher and successors — as
a subdirectory. **19,832 stars · Python · Apache-2.0.**

> **Important framing for a browser-agent survey:** despite the name, these are **not browser
> automation agents**. The core loop is a ReAct agent over *API tools* — `search` (Serper),
> `visit` (Jina Reader), `scholar`, `python` (SandboxFusion), `file_parser` (Dashscope) — with no
> Playwright/Puppeteer/CDP anywhere. The single exception is **`WebAgent/NestBrowse/`**
> ("Nested Browser-Use Learning", [arXiv:2512.23647](https://arxiv.org/pdf/2512.23647)), whose
> `toolkit/browser.py` adds genuine `Visit` / `Click` / `Fill` tools driven through an MCP client
> (`toolkit/mcp_client.py`).

### Repo/Folder Setup

Flat research-code layout — no packaging, no `setup.py`/`pyproject.toml`, no importable package.

```
DeepResearch/  (clones from either WebAgent or DeepResearch URL)
├── inference/               # ★ the Tongyi DeepResearch runtime
│   ├── run_react_infer.sh   # main entry point: launches 8 vLLM servers, waits, then infers
│   ├── run_multi_react.py   # parallel rollout driver (--dataset/--output/--max_workers/...)
│   ├── react_agent.py       # the ReAct agent, built on qwen_agent's FnCallAgent
│   ├── prompt.py
│   ├── tool_search.py  tool_visit.py  tool_scholar.py  tool_python.py  tool_file.py
│   ├── file_tools/
│   └── eval_data/           # example.jsonl, example_with_file.jsonl, file_corpus/
├── evaluation/              # ★ benchmark judging
│   ├── evaluate_deepsearch_official.py
│   ├── evaluate_hle_official.py
│   ├── prompt.py            # JUDGE_PROMPT_GAIA / _XBENCH / _BROWSECOMP_OFFICIAL
│   └── README.md
├── WebAgent/                # the agent family (each subdir = one paper)
│   ├── WebWalker/src/       # agent.py, rag_system.py, evaluate.py, app.py (Streamlit demo)
│   ├── WebDancer/           # demos/{agents,tools,llm,gui}/, scripts/{run_demo,deploy_model}.sh,
│   │                        # datasets/{sample_qa,sample_traj}.jsonl
│   ├── WebSailor/           # src/{react_agent,run_multi_react,evaluate,tool_search,tool_visit}.py,
│   │                        # src/run.sh, dataset/sailorfog-QA.jsonl
│   ├── WebShaper/data/webshaper.500.jsonl
│   ├── WebWatcher/          # infer/{vl_search_r1,evaluation,scripts_eval,docker_env}/,
│   │                        # browsecomp-vl/{bc_vl_level1,bc_vl_level2}.jsonl + images/
│   ├── NestBrowse/          # ★ infer_async_nestbrowse.py, toolkit/{browser,mcp_client,
│   │                        #   tool_explore,tool_search}.py, vllm_deploy.sh
│   ├── WebWeaver/           # react_agent_{outline_write,search_id}.py, run_search.sh, eval_data/
│   ├── AgentFold/           # infer.py, serve.sh
│   ├── ParallelMuse/        # compressed_reasoning_aggregation.py, ...partial_rollout.py, tools/
│   └── WebResearcher/  WebLeaper/  WebResummer/  WebSailor-V2/   (papers + assets; some code)
├── Agent/{AgentScaler,AgentFounder}/     # README + assets only
├── requirements.txt         # 188 fully-pinned lines (vllm, qwen-agent, torch, transformers, ...)
├── .env.example             # ★ the whole configuration surface
├── Tech_Report.pdf  FAQ.md  README.md
```

**Language / package manager:** Python **3.10.0 exactly** ("using other versions may cause dependency
issues"), plain `pip install -r requirements.txt` into a conda/virtualenv. 188 pinned deps including
`vllm`, `qwen-agent`, `transformers`, `alibabacloud-*`, `compressed-tensors`. Serving requires
**8 GPUs** by default.

**Install / configure:**

```bash
conda create -n react_infer_env python=3.10.0 && conda activate react_infer_env
pip install -r requirements.txt
cp .env.example .env          # then fill in keys
bash inference/run_react_infer.sh
```

`.env` keys (from `.env.example`):

| Var | Purpose |
|---|---|
| `SERPER_KEY_ID` | [Serper.dev](https://serper.dev/) — web search + Google Scholar |
| `JINA_API_KEYS` | [Jina.ai](https://jina.ai/) — web page reading (the "visit" tool) |
| `API_KEY` / `API_BASE` / `SUMMARY_MODEL_NAME` | OpenAI-compatible endpoint for page summarization |
| `DASHSCOPE_API_KEY` / `_API_BASE` | Alibaba Dashscope — PDF/Office parsing, video analysis |
| `SANDBOX_FUSION_ENDPOINT` | [SandboxFusion](https://github.com/bytedance/SandboxFusion) Python-interpreter sandbox (comma-separated endpoints) |
| `MODEL_PATH`, `DATASET`, `OUTPUT_PATH` | Weights path, eval file, results dir |
| `ROLLOUT_COUNT=3`, `TEMPERATURE=0.85`, `PRESENCE_PENALTY=1.1`, `MAX_WORKERS=30` | Inference hyperparameters |
| `USE_IDP`, `IDP_KEY_ID/SECRET` | Optional advanced document parsing |
| `TORCHDYNAMO_*`, `NCCL_*`, `GLOO_SOCKET_IFNAME` | Multi-GPU/distributed knobs |

**Entry point:** `bash inference/run_react_infer.sh`. It sources `../.env`, validates `MODEL_PATH`,
launches **8 `vllm serve` processes on ports 6001–6008** (one per `CUDA_VISIBLE_DEVICES`), polls
`/v1/models` on each with a 6000 s timeout, then execs:

```
python -u run_multi_react.py --dataset $DATASET --output $OUTPUT_PATH --max_workers $MAX_WORKERS \
  --model $MODEL_PATH --temperature $TEMPERATURE --presence_penalty $PRESENCE_PENALTY \
  --total_splits ${WORLD_SIZE:-1} --worker_split $((${RANK:-0}+1)) --roll_out_count $ROLLOUT_COUNT
```

A **GPU-free path** exists: the README documents pointing `call_server` in `inference/react_agent.py`
at [OpenRouter](https://openrouter.ai/alibaba/tongyi-deepresearch-30b-a3b) with model
`alibaba/tongyi-deepresearch-30b-a3b` (adjusting content concatenation per the comments on lines
88–90). Demos: `WebAgent/WebWalker/src/app.py` (Streamlit) and
`WebAgent/WebDancer/scripts/run_demo.sh` (Gradio GUI).

### Evals

**This repo is essentially an eval harness** — the whole pipeline exists to produce benchmark numbers.

**Benchmarks targeted.** Tongyi DeepResearch reports on **Humanity's Last Exam (HLE)**,
**BrowseComp** (EN), **BrowseComp-ZH**, **WebWalkerQA**, **xbench-DeepSearch**, **FRAMES**, and
**SimpleQA**. The `--dataset` choices actually implemented in
`evaluation/evaluate_deepsearch_official.py:453` are:
`["gaia", "browsecomp_zh", "browsecomp_en_full", "webwalker", "xbench-deepsearch"]`, with HLE handled
by the separate `evaluate_hle_official.py`. Notably absent: **no WebVoyager, WebArena, Mind2Web, or
OSWorld** — none of the classic browser-control benchmarks. The headline numbers themselves are only
published as images (`assets/benchmark.png`, `assets/performance.png`) and in the
[paper](https://arxiv.org/pdf/2510.24701) / [blog](https://tongyi-agent.github.io/blog/introducing-tongyi-deep-research/),
not as text in the repo.

**Scores stated in-repo** (all quoted verbatim from the sub-project READMEs):

| System | Reported result | Source |
|---|---|---|
| WebShaper-32B | **GAIA 60.19**, **WebWalkerQA 52.50** (claimed SOTA) | `WebAgent/README.md:77`, `WebAgent/WebShaper/readme.md:13` |
| WebDancer-32B | **GAIA 64.1 Pass@3**, **WebWalkerQA 62.0** | `WebAgent/README.md:92` |
| WebSailor-72B | **BrowseComp-en 12.0%**, **BrowseComp-zh 30.1%**, **GAIA 55.4%** | `WebAgent/README.md` (WebSailor features) |
| WebSailor-V2 (Qwen3-30B-A3B) | **BrowseComp-EN 35.3**, **BrowseComp-ZH 44.1**, **HLE 30.6** | `WebAgent/WebSailor-V2/README.md:21` |
| WebWatcher-32B | **HLE-VL 18.2% avg** (Pass@1 13.6%), **LiveVQA 58.7%**, **MMSearch 55.3%** | `WebAgent/WebWatcher/README.md:31,38` |
| ReSum / WebResummer (WebSailor-30B-A3B) | **BrowseComp-zh 33.3% Pass@1**, **BrowseComp-en 18.3%** | `WebAgent/WebResummer/README.md:20` |
| WebLeaper | SFT→SFT+RL ablation table, e.g. 37.80 → **38.8**, 69.9 → **73.2** | `WebAgent/WebLeaper/README.md:119-120` |

**Benchmark datasets shipped in-repo:** `WebAgent/WebShaper/data/webshaper.500.jsonl` (500 tasks),
`WebAgent/WebSailor/dataset/sailorfog-QA.jsonl` (SailorFog-QA),
`WebAgent/WebWatcher/browsecomp-vl/bc_vl_level{1,2}.jsonl` + `images/` (BrowseComp-VL, released here),
`WebAgent/WebDancer/datasets/{sample_qa,sample_traj}.jsonl`. WebWalkerQA itself (680 queries over
1,373 webpages, ACL 2025) is pulled from HuggingFace
(`load_dataset("callanwu/WebWalkerQA", split="main")` in `WebAgent/WebWalker/src/evaluate.py`) and has
a [public leaderboard](https://huggingface.co/spaces/callanwu/WebWalkerQALeadeboard).

**How an eval run is launched.**

```bash
# 1. generate predictions
bash inference/run_react_infer.sh              # writes rollouts to $OUTPUT_PATH

# 2. judge them  (evaluation/README.md)
export OPENAI_API_KEY=... OPENAI_API_BASE=... API_KEY=... BASE_URL=... Qwen2_5_7B_PATH=...
python evaluate_all_official.py --input_fp <folder> --dataset <gaia|webwalker|browsecomp_en|browsecomp_zh|xbench-deepsearch>

# HLE:
export API_KEY=... BASE_URL=...
python eval_hle_old_react.py --input_fp <folder> --model_path <qwen model path>
```

Judging is **LLM-as-judge**, with the judge model selected per dataset in
`evaluate_deepsearch_official.py:462-477`: `openai/qwen2.5-72b-instruct` + `JUDGE_PROMPT_GAIA` for
GAIA/WebWalker; `google/gemini-2.0-flash-001` + `JUDGE_PROMPT_XBENCH` for xbench-DeepSearch;
`gpt-4o-2024-08-06` + `JUDGE_PROMPT_BROWSECOMP_OFFICIAL` for both BrowseComp variants. Scores are
averaged over `ROLLOUT_COUNT` rollouts and written to `--restore_result_path` (default
`summary.jsonl`). The HLE judge additionally emits a structured `{extracted_final_answer, reasoning,
correct, confidence, strict}` JSON schema, enabling confidence-calibration analysis.

> ⚠️ **`evaluation/README.md` is out of sync with the code.** It instructs you to run
> `eval_hle_old_react.py` and `evaluate_all_official.py`; the files actually present are
> `evaluate_hle_official.py` and `evaluate_deepsearch_official.py`. It also documents
> `--input_fp`, but `evaluate_deepsearch_official.py`'s argparse defines `--input_folder`. Expect to
> fix the command lines yourself.

### Test Cases

**None. There is no test suite and no CI.** Stated plainly:

- Searching the entire tree for `test_*.py`, `*_test.py`, `conftest.py`, `pytest.ini`, or `tox.ini`
  returns **zero files**.
- **There is no `.github/` directory at all** — no workflows, no issue templates, no CI of any kind.
- No linter or formatter config (no ruff/black/flake8/pre-commit).
- The only files named "test" are `WebAgent/WebSailor/src/scripts/test.sh` (an inference launch
  script, not a test) and `inference/eval_data/example.jsonl` / `example_with_file.jsonl` (2-line
  sample inputs used to smoke-check the data format).
- The nearest analogue to regression testing is the eval pipeline itself: run the rollouts, then
  LLM-judge them. Correctness of the *code* is not verified programmatically anywhere.

This is typical for a research-artifact repo, but it's a real consideration if you plan to depend on
`inference/` or the `WebAgent/*` toolkits — nothing guards against breakage, and the docs/code drift
noted above (`evaluation/README.md`) is a symptom of exactly that.

---

## Cross-Cutting Observations

1. **Eval rigor and test rigor are uncorrelated, and often inverted.** DeepResearch has the most
   sophisticated benchmark tooling in the batch (per-dataset LLM judges, multi-rollout averaging,
   released datasets) and **zero tests and zero CI**. nanobrowser has real (if minimal) unit tests
   and **zero evals and zero CI**. Only Notte does both — and even there the evals are quarantined in
   a separate repo so they don't gate merges.

2. **Nobody in this batch runs an agent benchmark in CI.** Notte's CI explicitly *excludes*
   `test_webvoyager_scripts.py`; UI-TARS CI runs only perf benchmarks; the other two have no CI.
   Benchmark numbers are all published artifacts, not continuously-verified properties.

3. **"Browser agent" spans three unrelated architectures here.** DOM/accessibility-tree control
   (nanobrowser via `chrome.debugger`; Notte via Patchright; UI-TARS's browser MCP server via
   Puppeteer label indices) — vs. screenshot+coordinate visual grounding (UI-TARS operators) — vs.
   no browser at all, just search/fetch APIs (DeepResearch, except NestBrowse). Agent TARS is the only
   one that treats the choice as a runtime switch (`BrowserControlMode: hybrid|dom|visual-grounding`),
   and it's the only project that **snapshot-tests** that contract.

4. **A concrete lineage link inside this batch:** UI-TARS's `@agent-infra/browser-use` package
   explicitly credits nanobrowser as a technical reference, and its
   `agent/{actions,agents,event,messages,prompts}/` + `dom/history/` layout mirrors nanobrowser's
   one-for-one.

5. **Two eval-methodology contributions worth citing in the survey**, both from Notte:
   **WebVoyager30** (30-task subset run 8× — arguing that variance, not coverage, is the binding
   constraint on web-agent evaluation) and the **self-report vs. LLM-judge alignment/mismatch
   metric**, which quantifies how much an agent over-claims success. Notte's alignment ratio is
   ~1.08–1.18; Browser-Use's is 1.14–1.53 on the same harness.

6. **Docs drift is endemic.** nanobrowser's `CLAUDE.md` documents a Validator agent that does not
   exist in the code; DeepResearch's `evaluation/README.md` names two scripts and one flag that don't
   exist. Verify against the tree before citing either.

---

*Clones under `/tmp/browser-agent-research/` were removed after this document was written.*
