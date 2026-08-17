# Browser Agent Repos — Batch 1 (Flagship Products)

Survey notes on four flagship open-source browser-agent projects. All facts below were verified against
shallow clones taken **2026-08-16** (star counts and metadata via the GitHub API on the same date), plus
the GitHub API for the companion `browser-use/benchmark` repo. Where something does **not** exist in a
repo, it is called out explicitly rather than padded.

| Repo | Stars | Language | License | Version | Last push |
|---|---|---|---|---|---|
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | 109,438 | Python | MIT | 0.13.8 | 2026-08-16 |
| [Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern) | 22,761 | Python (+TS UI) | AGPL-3.0 | 1.0.48 | 2026-08-17 |
| [browserbase/stagehand](https://github.com/browserbase/stagehand) | 23,955 | TypeScript | MIT | 4.0.1 | 2026-08-16 |
| [lavague-ai/LaVague](https://github.com/lavague-ai/LaVague) | 6,385 | Python | Apache-2.0 | 1.1.19 | **2025-01-21 (dormant)** |

---

## browser-use/browser-use

> "Make websites accessible for AI agents." — the most-starred browser agent framework (109k★), Python, MIT.
> Drives Chrome directly over CDP (via [`cdp-use`](https://github.com/browser-use/cdp-use)), not Playwright.

### Repo/Folder Setup

Top-level layout ([tree](https://github.com/browser-use/browser-use/tree/main)):

| Path | What it is |
|---|---|
| [`browser_use/`](https://github.com/browser-use/browser-use/tree/main/browser_use) | The library package (details below) |
| [`examples/`](https://github.com/browser-use/browser-use/tree/main/examples) | 113 runnable `.py` examples: `getting_started/`, `features/`, `use-cases/`, `models/`, `browser/`, `cloud/`, `custom-functions/`, `integrations/`, `sandbox/`, `ui/`, `apps/`, `file_system/`, `observability/`, `beta_agent/` |
| [`tests/`](https://github.com/browser-use/browser-use/tree/main/tests) | `ci/` (the CI suite), `agent_tasks/` (YAML live-agent eval tasks), `mind2web_data/`, `scripts/` (manual debug scripts) |
| [`bin/`](https://github.com/browser-use/browser-use/tree/main/bin) | `setup.sh`, `test.sh`, `lint.sh` |
| [`skills/`](https://github.com/browser-use/browser-use/tree/main/skills) | Agent skill packs shipped for coding agents: `browser-use`, `cloud`, `open-source`, `qa`, `remote-browser`, `x402` |
| [`docker/`](https://github.com/browser-use/browser-use/tree/main/docker) | Base-image build scripts; plus root `Dockerfile`, `Dockerfile.fast` |
| `scripts/`, `static/`, `server.json` | One sync script; README images; MCP registry manifest |

Inside [`browser_use/`](https://github.com/browser-use/browser-use/tree/main/browser_use):

| Path | What it is |
|---|---|
| [`agent/`](https://github.com/browser-use/browser-use/tree/main/browser_use/agent) | Agent loop — `service.py`, `views.py`, `prompts.py`, `system_prompts/*.md`, `message_manager/`, `judge.py`, `variable_detector.py`, `gif.py`, `cloud_events.py` |
| [`browser/`](https://github.com/browser-use/browser-use/tree/main/browser_use/browser) | CDP browser control — `session.py`, `session_manager.py`, `profile.py`, `events.py`, `watchdogs/`, `chrome.py`, `video_recorder.py`, `cloud/` |
| [`dom/`](https://github.com/browser-use/browser-use/tree/main/browser_use/dom) | Page → LLM serialization — `serializer/`, `enhanced_snapshot.py`, `markdown_extractor.py`, `service.py`, plus injected `*.js` |
| [`llm/`](https://github.com/browser-use/browser-use/tree/main/browser_use/llm) | Provider adapters: `anthropic/`, `openai/`, `google/`, `groq/`, `azure/`, `aws/`, `deepseek/`, `mistral/`, `ollama/`, `openrouter/`, `litellm/`, `cerebras/`, `oci_raw/`, `browser_use/` |
| [`tools/`](https://github.com/browser-use/browser-use/tree/main/browser_use/tools) | Action registry — `registry/`, `service.py`, `extraction/`. `controller/` is a back-compat alias |
| [`actor/`](https://github.com/browser-use/browser-use/tree/main/browser_use/actor) | Low-level primitives — `page.py`, `mouse.py`, `element.py` |
| [`mcp/`](https://github.com/browser-use/browser-use/tree/main/browser_use/mcp) | MCP client **and** server — `server.py`, `client.py`, `controller.py`, `manifest.json` |
| `skills/`, `filesystem/`, `sandbox/`, `sync/`, `telemetry/`, `tokens/`, `integrations/gmail/`, `beta/`, `screenshots/` | Skill install, agent scratch FS, sandboxed runs, cloud sync, PostHog telemetry, token accounting, Gmail OTP integration, beta agent wrapper |
| `cli.py`, `config.py`, `observability.py` | CLI entry, settings, tracing hooks |

**Language / package manager.** Python `>=3.11,<4.0`, [`uv`](https://docs.astral.sh/uv/) + hatchling, single
[`pyproject.toml`](https://github.com/browser-use/browser-use/blob/main/pyproject.toml). Formatting is ruff
(single quotes, **tabs**, 130 cols); type checking is pyright.

**Install.**
```bash
uv add browser-use          # or: pip install browser-use
# dev:
./bin/setup.sh              # installs uv, uv venv, uv sync --dev --all-extras
uvx playwright install chromium --with-deps --no-shell   # Playwright is used only to fetch the Chromium binary
```
Extras: `cli`, `core`, `aws`, `oci`, `video`, `examples`, `eval`, `all`.

**Configuration** ([`.env.example`](https://github.com/browser-use/browser-use/blob/main/.env.example)):
`BROWSER_USE_API_KEY` (their hosted LLM/cloud), or bring your own — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`, `DEEPSEEK_API_KEY`, `GROK_API_KEY`,
`NOVITA_API_KEY`, AWS Bedrock creds. Browser knobs: `BROWSER_USE_HEADLESS`, `BROWSER_USE_EXECUTABLE_PATH`,
`BROWSER_USE_USER_DATA_DIR`, `BROWSER_USE_PROXY_SERVER`/`_USERNAME`/`_PASSWORD`. Ops: `ANONYMIZED_TELEMETRY`,
`BROWSER_USE_LOGGING_LEVEL`, `BROWSER_USE_CLOUD_SYNC`, `BROWSER_USE_VERSION_CHECK`.

**Entry points.** `[project.scripts]` maps **four** aliases — `browser-use`, `browseruse`, `bu`, `browser` —
all to [`browser_use.cli:main`](https://github.com/browser-use/browser-use/blob/main/browser_use/cli.py)
(plus deprecated `browser-use-tui`). Library usage is `Agent(task=..., llm=ChatBrowserUse(...)).run()`.
MCP server mode: `uvx browser-use[cli] --mcp` ([CLAUDE.md:56](https://github.com/browser-use/browser-use/blob/main/CLAUDE.md)).

### Evals

**The real benchmark lives in a separate repo: [`browser-use/benchmark`](https://github.com/browser-use/benchmark)**
(116★, Python), linked from the main README. The main repo itself contains only a 2-task smoke eval.

**BU Bench V1** — 100 hand-selected tasks, composed of: Custom page-interaction 20, WebBench 20, Mind2Web 2 20,
GAIA 20 (public validation split only), BrowseComp 20. The task set is Fernet-encrypted
(`BU_Bench_V1.enc`) to prevent training-data contamination. Run with:
```bash
uv run python run_eval.py                       # default: ChatBrowserUse + cloud browser
uv run python run_framework_eval.py --list-frameworks
uv run python run_framework_eval.py --framework browser-use --browser browser-use-cloud --model bu-2-0
```
`frameworks/` holds adapters so *other* agents can be measured on the same set: `stagehand`,
`browserbase_agent`, `claude_cua`, `codex_harness`, `claude_code_harness`, `pi_harness`, `bcode`, `but`/`but_rust`.

Committed scores in [`official_results/`](https://github.com/browser-use/benchmark/tree/main/official_results)
(each file is `{tasks_completed, tasks_successful, total_steps, total_duration, total_cost}`):

| Config | Success / 100 |
|---|---|
| BrowserUseCloudAPI v4, `bu-v4-luna` | **78** |
| browser-use 0.13.7 + `claude-opus-4-7` | 74 |
| browser-use 0.13.7 + `bu-2-0` | 68 |
| browser-use 0.13.7 + `gpt-5.5` | 66 |

(Additional result files exist for `bu-v4-opus-4-8`, `gemini-3.5-flash`, `gpt-5.6-luna`, `deepseek-v4-flash-0731`, `qwen3.6-plus`.)

Other suites in that repo: **Stealth Bench V1** (71 tasks measuring anti-bot evasion across browser providers —
`browser-use-cloud`, `anchor`, `browserbase`, `browserless`, `hyperbrowser`, `onkernel`, `steel`,
`local_headful`, `local_headless`) and **Online-Mind2Web** (`online-mind2web/official_plots/`, plots only).
The main README additionally claims **#1 on the [Odysseys leaderboard](https://odysseysbench.com/leaderboard)
at 87.4% average** over 200 long-horizon tasks — that number is not reproducible from either repo.

**In-repo eval** — [`tests/ci/evaluate_tasks.py`](https://github.com/browser-use/browser-use/blob/main/tests/ci/evaluate_tasks.py)
over [`tests/agent_tasks/*.yaml`](https://github.com/browser-use/browser-use/tree/main/tests/agent_tasks).
Each YAML is `{name, task, judge_context[], max_steps}`; the runner forks one subprocess per task (max 10
parallel), runs the agent with `ChatBrowserUse`, and grades the transcript with
`ChatGoogle('gemini-3.1-flash-lite')` returning `{success, explanation}`. It only fails CI at a **0%** pass rate.
As of this commit there are exactly **two** tasks (`amazon_laptop.yaml`, `browser_use_pip.yaml`) — the README
in that folder invites contributions. Launched by the `evaluate-tasks` job in
[`.github/workflows/test.yaml`](https://github.com/browser-use/browser-use/blob/main/.github/workflows/test.yaml),
which posts a per-task pass/fail table as a PR comment.

Two more eval workflows are **closed-source pass-throughs**:
- [`.github/workflows/eval-on-pr.yml`](https://github.com/browser-use/browser-use/blob/main/.github/workflows/eval-on-pr.yml) — POSTs the PR SHA to a private `EVAL_PLATFORM_URL` with test case `InteractionTasks_v8`; only runs for OWNER/MEMBER/COLLABORATOR PRs.
- [`.github/workflows/cloud_evals.yml`](https://github.com/browser-use/browser-use/blob/main/.github/workflows/cloud_evals.yml) — `repository_dispatch` into the private `browser-use/cloud` repo to build a cloud eval image.

**Dead data:** [`tests/mind2web_data/processed.json`](https://github.com/browser-use/browser-use/blob/main/tests/mind2web_data/processed.json)
(677 KB) is referenced by **zero** files in the repo — a leftover from a removed Mind2Web harness.

### Test Cases

**Framework:** pytest, configured in `[tool.pytest.ini_options]` of `pyproject.toml` — `asyncio_mode = "auto"`,
`timeout = 300`, markers `slow`/`integration`/`unit`/`asyncio`, `testpaths = ["tests"]`, xdist with
`--dist=loadscope`. Dev deps pin `pytest==9.0.2`, `pytest-asyncio`, `pytest-httpserver`, `pytest-timeout`, `pytest-xdist`.

**Layout** — 100 `test_*.py` files total, 99 under [`tests/ci/`](https://github.com/browser-use/browser-use/tree/main/tests/ci):

| Directory | Count | Contents |
|---|---|---|
| `tests/ci/` (root) | 54 | Per-action/per-feature tests; convention is `test_action_<EventName>.py` |
| `tests/ci/browser/` | 17 | Real headless Chromium over CDP — `test_dom_serializer.py`, `test_cross_origin_click.py`, `test_true_cross_origin_click.py`, `test_navigation_slow_pages.py`, `test_proxy.py`, `test_tabs.py`, `test_screenshot.py`, `test_profile_copy.py`, `test_cloud_browser.py`, + HTML fixtures (`test_page_template.html`, `iframe_template.html`) |
| `tests/ci/models/` | 10 | Per-provider LLM adapters + `test_llm_schema_optimizer.py`, `model_test_helper.py` |
| `tests/ci/security/` | 7 | `test_sensitive_data.py`, `test_domain_filtering.py`, `test_ip_blocking.py`, `test_upload_file_containment.py`, `test_download_filename_sanitization.py`, `test_mcp_allowed_domains.py`, `test_security_flags.py` |
| `tests/ci/infrastructure/` | 7 | Registry core/validation/param-injection, config, filesystem, URL shortening, version check |
| `tests/ci/interactions/` | 4 | `test_dropdown_native.py`, `test_dropdown_aria_menus.py`, `test_radio_buttons.py`, `test_autocomplete_interaction.py` |

**House rules** (documented in [CLAUDE.md:88–90](https://github.com/browser-use/browser-use/blob/main/CLAUDE.md)):
*never mock anything except the LLM*, and *never use real remote URLs* — every browser scenario is served by
`pytest-httpserver`. `tests/ci/conftest.py` provides `create_mock_llm` and forces test env vars so nothing
talks to production.

**Notable tests:**
- [`test_action_loop_detection.py`](https://github.com/browser-use/browser-use/blob/main/tests/ci/test_action_loop_detection.py) — asserts the action-hash normalizer treats `"site:example.com answers votes"` and `"votes answers site:example.com"` as the same action, so re-ordered/re-cased searches trip cycle-breaking.
- [`browser/test_true_cross_origin_click.py`](https://github.com/browser-use/browser-use/blob/main/tests/ci/browser/test_true_cross_origin_click.py) — clicking inside genuinely cross-origin (OOPIF) iframes with `cross_origin_iframes=True`.
- `test_message_compaction.py`, `test_llm_output_truncation.py`, `test_llm_retries.py`, `test_fallback_llm.py`, `test_multi_act_guards.py`, `test_redact_cascade.py`, `test_event_bus_resilience.py`.

**CI** ([`.github/workflows/`](https://github.com/browser-use/browser-use/tree/main/.github/workflows)):
`test.yaml` discovers every `tests/ci/test_*.py` at runtime and fans out **one matrix job per test file**
(~100 parallel jobs, 4-min timeout each), with weekly-keyed caches for the Chromium binary, the uv venv, and
browser-use extensions. `lint.yml` runs three jobs: ruff `--select PLE` (syntax), `pre-commit run --all-files`,
and `pyright`. Others: `docker.yml`, `package.yaml`, `publish.yml`, `install-script.yml`, `claude.yml`,
`stale-bot.yml`, plus the two eval workflows above.

---

## Skyvern-AI/skyvern

> "Automate browser based workflows with AI" — 22.8k★, Python backend + React UI, AGPL-3.0. Positions itself
> as a **Playwright extension** (`page.act/extract/validate/prompt`) plus a hosted workflow product.

### Repo/Folder Setup

| Path | What it is |
|---|---|
| [`skyvern/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern) | The backend package (details below) |
| [`skyvern-frontend/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern-frontend) | React/Vite UI (npm, `.nvmrc`); `packages/skyvern-ui` is the packaged build |
| [`skyvern-ts/client`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern-ts) | Generated TypeScript client (`@skyvern/client`) |
| [`alembic/`](https://github.com/Skyvern-AI/skyvern/tree/main/alembic) | DB migrations; `alembic.ini`, `run_alembic_check.sh` |
| [`evaluation/`](https://github.com/Skyvern-AI/skyvern/tree/main/evaluation) | WebVoyager/Odysseys eval harness — datasets, scripts, committed results |
| [`prompt_evaluation/`](https://github.com/Skyvern-AI/skyvern/tree/main/prompt_evaluation) | Essentially empty — one file, `extract_action/scripts/install_directory.py` |
| [`tests/`](https://github.com/Skyvern-AI/skyvern/tree/main/tests) | pytest suites (see below) |
| `docs/` + `fern/` | Mintlify docs site + Fern API-doc/SDK generation config |
| `integrations/` | `make`, `mcp`, `n8n` connectors |
| `k8s/`, `kubernetes-deployment/`, `bitwarden-cli-server/`, `.superset/` | Deployment and ops |
| `skills/skyvern`, `scripts/`, `.claude/` | Coding-agent skill pack, ops scripts |

Inside [`skyvern/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern):

| Path | What it is |
|---|---|
| [`forge/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern/forge) | Agent core + API — `agent.py`, `api_app.py`, `prompts/` (Jinja prompt templates), `sdk/` (db, artifacts, routes, workflow models), `taskv3/`, `failure_classifier.py`, `log_redaction.py` |
| [`webeye/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern/webeye) | Browser layer — `browser_factory.py`, `browser_manager.py`, `real_browser_manager.py`, `scraper/`, `skycdp/` (their CDP client), `actions/`, `cdp_download_interceptor.py`, `dialog_handler.py`, `video_utils.py` |
| [`library/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern/library) | The Playwright-extension SDK — `skyvern_browser_page_ai.py`, `skyvern_browser_page_agent.py`, `ai_locator.py`, `skyvern_locator.py` |
| [`services/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern/services) | `run_service.py`, `block_service.py`, `script_service.py`, `script_reviewer*`, `otp_service.py`, `cleanup_service.py`, … |
| [`cli/`](https://github.com/Skyvern-AI/skyvern/tree/main/skyvern/cli) | Typer CLI — `quickstart.py`, `run_commands.py`, `doctor.py`, `mcp.py`/`mcp_tools/`, `credential.py`, `schedule_command.py` |
| `core/script_generations/`, `client/`, `schemas/`, `experimentation/`, `browser_extension/`, `utils/` | Codegen from recorded runs, generated client, pydantic schemas, feature flags, browser extension bridge |

**Language / package manager.** Python `>=3.11,<3.15`, `uv` + hatchling
([`pyproject.toml`](https://github.com/Skyvern-AI/skyvern/blob/main/pyproject.toml), `uv.lock`), optional
extras `local` / `server` / `ui` / `all`. Frontend is npm. Lint/type: ruff, mypy (`mypy.ini`), flake8, pre-commit.

**Install.**
```bash
# Option A — pip
pip install "skyvern[all]"
skyvern quickstart              # SQLite at ~/.skyvern/data.db by default
# Postgres instead: skyvern quickstart --database-string=postgresql+psycopg://user:pass@host:5432/db

# Option B — Docker Compose (Postgres + API + UI)
git clone https://github.com/skyvern-ai/skyvern.git && cd skyvern
cp .env.example .env            # add your LLM key
docker compose up -d            # UI on http://localhost:8080

# From source
./run_skyvern.sh                # uv sync; run_alembic_check.sh; python -m skyvern.forge
```
Playwright/Chromium is pulled in through the `local`/`server` extras.

**Configuration** ([`.env.example`](https://github.com/Skyvern-AI/skyvern/blob/main/.env.example)) is
enable-flag driven: `ENABLE_OPENAI` + `OPENAI_API_KEY`, `ENABLE_ANTHROPIC`, `ENABLE_GEMINI`, `ENABLE_XAI`,
`ENABLE_AZURE*` (incl. per-deployment GPT-5/mini/nano blocks), `ENABLE_NOVITA`, `ENABLE_VOLCENGINE`,
`ENABLE_YUTORI` — then you pick `LLM_KEY` and `SECONDARY_LLM_KEY` (the cheap model for select/SVG work).
Browser: `BROWSER_TYPE=chromium-headful|chromium-headless`, `BROWSER_STREAMING_MODE=cdp|vnc`,
`BROWSER_ACTION_TIMEOUT_MS`, `MAX_STEPS_PER_RUN=50`, `VIDEO_PATH`. Infra: `DATABASE_STRING`, `PORT=8000`,
`REDIS_URL`, `ENABLE_LOG_ARTIFACTS`, `LMNR_*` (Laminar tracing). Credentials:
`CREDENTIAL_VAULT_TYPE=skyvern|bitwarden|gcp|azure`, `LOCAL_CREDENTIAL_VAULT_KEY`,
`SKYVERN_AUTH_BITWARDEN_*`, `OP_SERVICE_ACCOUNT_TOKEN` (1Password), plus GCS storage options.

**Entry points.** `[project.scripts] skyvern = "skyvern.__main__:main"` — a Typer CLI
(`skyvern quickstart`, `skyvern run server`, `skyvern run ui`, `skyvern init`, MCP + schedule + credential
subcommands). Library entry is the AI-augmented page object:
`page.act(prompt)`, `page.extract(prompt, schema)`, `page.validate(prompt)`, `page.prompt(...)`, and
`page.agent.run_task/login/download_files/run_workflow`. TS client: `npm install @skyvern/client`.

### Evals

Skyvern is the only repo in this batch that **commits raw per-task benchmark results**.

**Datasets** ([`evaluation/datasets/`](https://github.com/Skyvern-AI/skyvern/tree/main/evaluation/datasets)):
- `webvoyager_tasks.jsonl` — **635** tasks (`{web_name, id, ques, web}`) across 15 sites
- `webvoyager_reference_answer.json` — ground-truth answers used by the judge
- `webvoyager_compute_use_tasks.jsonl` (49), `webvoyager_outdated_tasks.jsonl` (7)
- `odysseys_tasks.json` — the **Odysseys** benchmark, 200 long-horizon multi-site tasks (45 easy / 46 medium / 109 hard), vendored verbatim from [ljang0/Odysseys](https://github.com/ljang0/Odysseys) (MIT), rubric-graded at ~6.1 checkpoints/task, documented in [`ODYSSEYS_ATTRIBUTION.md`](https://github.com/Skyvern-AI/skyvern/blob/main/evaluation/datasets/ODYSSEYS_ATTRIBUTION.md)

**Harness** ([`evaluation/`](https://github.com/Skyvern-AI/skyvern/tree/main/evaluation)):
- [`core/utils.py`](https://github.com/Skyvern-AI/skyvern/blob/main/evaluation/core/utils.py) — `WebVoyagerTestCase`, `load_webvoyager_case_from_json` (joins tasks to reference answers); `core/` also exports `Evaluator` and `SkyvernClient`
- [`script/create_webvoyager_task_v2.py`](https://github.com/Skyvern-AI/skyvern/blob/main/evaluation/script/create_webvoyager_task_v2.py) — queues each task as a Task-v2 run; first rewrites each question through the `check-evaluation-goal` prompt (flagging `is_updated`), then writes a `<group_id>-webvoyager-record.jsonl`
- [`script/eval_webvoyager_task_v2.py`](https://github.com/Skyvern-AI/skyvern/blob/main/evaluation/script/eval_webvoyager_task_v2.py) — reads that record file in batches of 5, pulls the workflow run, and LLM-judges the output into an `assertion` boolean; emits CSV with `id/status/assertion/failure_reason/url/question/answer/summary/output/…`
- `script/create_webvoyager_workflow.py`, `script/create_webvoyager_evaluation_result.py`

Both scripts are Typer CLIs taking `--base-url` and `--cred`; they need a running Skyvern server. **They are not
wired into CI** — root `pytest.ini` `norecursedirs` explicitly skips `eval` and `prompt_evaluation`.

**Committed results** — [`evaluation/results/webvoyager-*.md`](https://github.com/Skyvern-AI/skyvern/tree/main/evaluation/results),
15 markdown tables with per-task id / status / question / Skyvern run link / summary / output. Note that
`webvoyager-Coursera.md` is misnamed: it holds the **full 635-task aggregate**.

| File | completed | failed | timed_out |
|---|---|---|---|
| **Coursera.md (full 635-task aggregate)** | **546 (86.0%)** | 80 | 9 |
| BBC-News | 40 | 1 | 0 |
| Cambridge-Dictionary | 40 | 3 | 0 |
| Google-Map | 39 | 2 | 0 |
| Google-Search | 39 | 4 | 0 |
| Allrecipes | 39 | 5 | 1 |
| Google-Flights | 38 | 1 | 3 |
| Wolfram-Alpha | 38 | 7 | 0 |
| ArXiv | 37 | 4 | 1 |
| Booking | 37 | 5 | 2 |
| ESPN | 35 | 7 | 2 |
| Apple | 34 | 8 | 0 |
| Amazon | 31 | 10 | 0 |
| Github | 30 | 10 | 0 |
| Huggingface | 30 | 10 | 0 |

⚠️ Caveat: the `status` column is *workflow run status*, not the LLM-judged `assertion` — the committed tables
omit the assertion column, so 86.0% is "ran to completion", an upper bound on task success. It does line up
with the maintainers' headline number.

**Reported numbers** (README):
- **85.8% on WebVoyager** — [Skyvern 2.0 technical report](https://www.skyvern.com/blog/skyvern-2-0-state-of-the-art-web-navigation-with-85-8-on-webvoyager-eval/) ([README:51](https://github.com/Skyvern-AI/skyvern/blob/main/README.md))
- **64.4% on [WebBench](https://webbench.ai/)**, claimed SOTA, and best-in-class on WRITE tasks (forms/login/downloads) — [README:391](https://github.com/Skyvern-AI/skyvern/blob/main/README.md), charts at `fern/images/performance/webbench_overall.png` and `webbench_write.png`

**Gap:** the Odysseys *evaluator* is not open-sourced. `pyproject.toml:314` excludes
`scripts/benchmark/evaluators/_odysseys_upstream_full_traj.py` from ruff, but `scripts/benchmark/` does not
exist in this repo — only the dataset is vendored, the harness lives in their internal/cloud tree.

### Test Cases

**Framework:** pytest. Root [`pytest.ini`](https://github.com/Skyvern-AI/skyvern/blob/main/pytest.ini) sets
`--capture=no`, a `workday_offline` opt-in marker, and
`norecursedirs = tests/manual tests/evals scripts/cdp-download-poc tests/sdk eval infra/gcp-agent prompt_evaluation internal-tools`.
`tests/pytest.ini` adds `asyncio_mode = auto`. Root `conftest.py`, `mypy.ini`, `.flake8`, `.pre-commit-config.yaml`.

**Scale: 888 `test_*.py` files** (864 under `tests/unit/` alone, 723 of them flat in `tests/unit/`) — by far the
largest suite in this batch, and clearly a bug-regression-per-file culture (e.g.
`test_copilot_sky11865_mint_satisfiability.py`, `test_element_click_navigation_timeout_skips_fallback.py`).

| Path | Notes |
|---|---|
| [`tests/unit/`](https://github.com/Skyvern-AI/skyvern/tree/main/tests/unit) | The bulk. Sub-packages: `workflow/` (32), `forge/sdk/db/` (19), `webeye/` (13), `browser_extension/` (11), `forge/sdk/routes/streaming/` (10), `services/`, `google/`, `microsoft/`, `submission/`, `copilot/`, `embedded/`, `db/`, `utils/`. Support: `conftest.py`, `helpers.py`, `fixtures/`, `force_stub_app.py`, `_mcp_browser_fakes.py`, `_fingerprint_expectations.py` |
| `tests/unit/golden_prompts/` | Prompt **snapshot** tests — `extract-action.control.txt`, `check-user-goal.control.txt`, `auto-completion-choose-option.control.txt`, etc., with `regenerate.py`. Prompt drift fails a test |
| [`tests/unit_tests/`](https://github.com/Skyvern-AI/skyvern/tree/main/tests/unit_tests) | 14 older tests (token counter, URL validators, streaming screencast, alembic loop, OpenRouter integration) |
| [`tests/smoke_tests/`](https://github.com/Skyvern-AI/skyvern/tree/main/tests/smoke_tests) | Real-LLM prompt smoke tests against **captured page state** — `test_prompts.py` replays `data/geico_closest_coverage/` and `data/workable_yes_or_no/` (element trees + screenshots + navigation payloads); also `test_pdf_fill_block.py`, `test_pdf_fill_benchmark_smoke.py`, `test_while_loop_pagination.py`, `browser_extension/run_extension_smoke.py` |
| [`tests/sdk/`](https://github.com/Skyvern-AI/skyvern/tree/main/tests/sdk) | Python **and** TypeScript SDK e2e against shared fixtures in `tests/sdk/web/` (`click.html`, `combobox.html`, `input.html`, `login.html`, `upload.html`, `download_file.html`). Needs `SKYVERN_API_KEY`, a running server, and Chrome CDP on `:9222`. Excluded from the default pytest run |
| `tests/test_agent.py`, `test_cli_doctor.py`, `test_runtime_config_route.py` | Top-level odds and ends |

**Notable tests:**
- 12 `test_*.js` files driven from Python siblings (`test_dom_scrape_crash_guards.js/.py`, `test_scraper_shadow_text.js/.py`, `test_datatables_select_checkbox_interactability.js/.py`) — the injected DOM utilities get unit-tested in-browser.
- Architecture-enforcement tests: `test_no_direct_db_delegates.py` (paired with `scripts/check_no_direct_db_delegates.sh`), `test_no_tests_in_shipped_package.py`, `test_dependency_python_version_markers.py`, `test_api_docs_taxonomy.py`.
- Security: `test_webhook_ssrf.py`, `test_workflow_copilot_prompt_injection.py`, `test_llm_prompt_secret_redaction.py`, `test_secret_encryption.py`, `test_forge_log_redaction.py`, `test_security_headers.py`.

**CI** ([`.github/workflows/ci.yml`](https://github.com/Skyvern-AI/skyvern/blob/main/.github/workflows/ci.yml)):
one `test` job on ubuntu with a **Postgres service container** — `uv sync --extra server --group dev`,
`npm ci` for the frontend, `pre-commit run --all-files`, `./run_alembic_check.sh`, then `uv run pytest`
(with dummy API keys injected so provider-gated code paths initialize). Plus `fe-lint-build` (frontend lint +
build) and `pip-package-smoke` (matrix Python 3.11/3.13 running `scripts/test-pip-ui-package.sh` in a slim
container). Other workflows: `build-docker-image`, `auto-release`, `sdk-release`, `ts-sdk-release`,
`publish-fern-docs`, `preview-fern-docs`, `update-openapi`, `zizmor` (GitHub-Actions security linting),
`claude-code-review`, `auto-merge-sync`, `sync-skyvern-cloud`.

---

## browserbase/stagehand

> "The SDK For Browser Agents" — 24k★, TypeScript, MIT. v4 is a pnpm/turbo **monorepo** shipping TS, Python,
> and Go SDKs on top of a Chrome **extension** that runs next to the browser.

### Repo/Folder Setup

pnpm workspace (`packages/*` + `packages/integrations/*`) driven by turborepo.

| Path | What it is |
|---|---|
| [`packages/sdk-ts/`](https://github.com/browserbase/stagehand/tree/main/packages/sdk-ts) | `@browserbasehq/stagehand` (v4.0.1) — `src/`, `tests/`, `examples/`, built with tsdown |
| [`packages/sdk-python/`](https://github.com/browserbase/stagehand/tree/main/packages/sdk-python) | `stagehand` on PyPI — uv build backend; `src/stagehand/_generated` is generated from the protocol by `scripts/generate.py` |
| [`packages/sdk-go/`](https://github.com/browserbase/stagehand/tree/main/packages/sdk-go) | Go SDK, flat package (`browser.go`, `cdp_client.go`, `chrome_launcher.go`, …) with 24 `*_test.go`; `go:embed`s a prebuilt `internal/extensionassets/stagehand-extension.zip` |
| [`packages/extension/`](https://github.com/browserbase/stagehand/tree/main/packages/extension) | **The actual agent runtime** — `service-worker.ts`, `content-script.ts`, `dom/`, `handlers/`, `controllers/`, `llm/`, `inference.ts`, `rpcRouter.ts`, `understudy/`, `manifest.json` |
| [`packages/protocol/`](https://github.com/browserbase/stagehand/tree/main/packages/protocol) | JSON-RPC protocol + schema registry; the committed `stagehand.v4.json` is the drift gate |
| [`packages/evals/`](https://github.com/browserbase/stagehand/tree/main/packages/evals) | The eval harness (see below) |
| [`packages/integrations/`](https://github.com/browserbase/stagehand/tree/main/packages/integrations) | Adapters: `claude-code`, `codex`, `crewai`, `deepagents`, `eve`, `mastra`, `pi`, `vercel-ai`, `core` |
| [`packages/docs/`](https://github.com/browserbase/stagehand/tree/main/packages/docs) | Mintlify docs, versioned `v2/`, `v3/`, `v4/`, plus its own `tests/` |
| Root config | `turbo.json`, `pnpm-workspace.yaml` (catalog pinning), `vitest.config.ts`, `vitest.integration.config.ts`, `oxlint.config.ts`, `.oxfmtrc.json`, `justfile`, `.changeset/`, `rules/` (ast-grep lint rules), `scripts/` |

**Language / package manager.** TypeScript on Node `>=22.18` (devEngines: pnpm 11.10, node 24.18); Python via
`uv`; Go 1.26. Lint/format is **oxlint + oxfmt** (not ESLint/Prettier).

**Install.**
```bash
pnpm install && pnpm build      # workspace
pnpm build:cli                  # links the `evals` binary
# consumers:
npm i @browserbasehq/stagehand
pip install stagehand
```

**Configuration** — [`.env.example`](https://github.com/browserbase/stagehand/blob/main/.env.example) is
deliberately tiny: `OPENAI_API_KEY`, `BROWSERBASE_API_KEY`, optional `CHROME_PATH` (only if Chrome can't be
auto-detected). Evals additionally read `ANTHROPIC_API_KEY`, `GOOGLE_GENERATIVE_AI_API_KEY`,
`BROWSERBASE_PROJECT_ID`, `BRAINTRUST_API_KEY`.

**Entry points.** Library-first, no agent CLI:
```typescript
const browser = await browserbase.launch({ apiKey: BROWSERBASE_API_KEY });
const stagehand = await Stagehand.create({ browser, model: { modelName: "openai/gpt-5.4-mini", apiKey } });
await stagehand.act("click on the stagehand repo");
const { data } = await stagehand.observe("find the latest PR");
const { data: parsed } = await stagehand.extract("extract author and title", schema);
```
Root scripts: `pnpm test`, `pnpm test:unit`, `pnpm test:integration`, `pnpm check`, `pnpm build`, `pnpm build:cli`.
The one CLI is `evals` (from `packages/evals/bin/evals`).

### Evals

The most developed eval tooling of the four — an interactive TUI plus a single-shot CLI, in
[`packages/evals/`](https://github.com/browserbase/stagehand/tree/main/packages/evals)
([README](https://github.com/browserbase/stagehand/blob/main/packages/evals/README.md)).

```bash
pnpm build:cli
evals                                  # REPL/TUI
evals run extract -t 3 -c 5            # category, 3 trials, concurrency 5
evals run b:webvoyager -l 10           # dataset-backed benchmark suite
evals run --preview                    # resolve the plan without spending tokens
evals list [--detailed] | evals new bench extract my_task | evals experiments
```
Flags: `-e local|browserbase`, `-t trials`, `-c concurrency`, `-m model`, `--api`,
`--harness stagehand|claude_code|codex`, `-l/-s/-f` for suite shaping.
Defaults in [`evals.config.json`](https://github.com/browserbase/stagehand/blob/main/packages/evals/evals.config.json):
`env=local`, `trials=3`, `concurrency=10`, per-benchmark `limit: 25`.

**Committed datasets** ([`packages/evals/datasets/`](https://github.com/browserbase/stagehand/tree/main/packages/evals/datasets)):

| Dataset | Rows | Notes |
|---|---|---|
| `webvoyager/WebVoyager_data.jsonl` | 642 | Standard WebVoyager `{web_name,id,ques,web}` |
| `webtailbench/WebTailBench_data.jsonl` | 609 | Browserbase's own long-tail set; each row carries a `precomputed_rubric` with per-criterion descriptions |
| `onlineMind2Web/onlineMind2Web.jsonl` | 300 | Online-Mind2Web |
| `odysseysbench/OdysseysBench_data.jsonl` | 200 | Odysseys, built by `scripts/build-odysseysbench-dataset.ts` |

**Suites**: [`suites/webvoyager.ts`](https://github.com/browserbase/stagehand/blob/main/packages/evals/suites/webvoyager.ts),
`onlineMind2Web.ts`, `webtailbench.ts`, `odysseysbench.ts` (env overrides `EVAL_MAX_K`, `EVAL_WEBVOYAGER_LIMIT`,
`EVAL_WEBVOYAGER_SAMPLE`).
**Framework**: `framework/benchRunner.ts`, `benchPlanner.ts`, `benchHarness.ts`, `adHocRubric.ts`,
`rubricCache.ts`, `verifierGate.ts`, `verifierAdapter.ts`, `trajectoryGroup.ts`, `metrics.ts`, plus
external-harness drivers `claudeCodeRunner.ts` / `codexRunner.ts` / `codexCodeBridge.ts` so Claude Code and
Codex can be benchmarked *through* Stagehand.

**Hand-written bench tasks** — auto-discovered from `packages/evals/tasks/bench/<category>/`, no registration:
**40 act + 25 extract + 12 observe = 77**. Many run against static clones at
`browserbase.github.io/stagehand-eval-sites/` (e.g.
[`tasks/bench/act/amazon_add_to_cart.ts`](https://github.com/browserbase/stagehand/blob/main/packages/evals/tasks/bench/act/amazon_add_to_cart.ts)),
and the names map onto the product's differentiators: `heal_custom_dropdown.ts`, `heal_scroll_50.ts`,
`heal_simple_google_search.ts` (self-healing), `csr_in_oopif.ts`, `csr_in_spif.ts`, `iframes_nested.ts`,
`iframe_scroll.ts`, `namespace_xpath.ts`, `hidden_input_dropdown.ts`, `multi_tab.ts`.

**Scoring**: [`scoring.ts`](https://github.com/browserbase/stagehand/blob/main/packages/evals/scoring.ts) —
`exactMatch`, `passRate`, `errorMatch` over a `{_success: boolean}` task return. Runs stream to
**Braintrust** when `BRAINTRUST_API_KEY` is set (`framework/braintrust.ts`, `lib/braintrust-report.ts`,
`evals experiments` for diffing); otherwise a local summary prints.

**No scores are committed in this repo.** Per-model accuracy/cost/speed numbers are published on the external
leaderboard at <https://www.stagehand.dev/evals>, linked from
[`packages/docs/v4/configuration/models.mdx:1358`](https://github.com/browserbase/stagehand/blob/main/packages/docs/v4/configuration/models.mdx)
and `best-practices/cost-optimization.mdx:15`. (That page is JS-rendered and returned 404 to a plain fetch, so
no numbers are quoted here.) Note a version skew: v2/v3 docs
([`packages/docs/v3/basics/evals.mdx:50`](https://github.com/browserbase/stagehand/blob/main/packages/docs/v3/basics/evals.mdx))
still advertise WebBench, GAIA and OSWorld, but v4 dropped WebBench — and there's a test that says so:
[`packages/evals/tests/tui/parse.test.ts:55`](https://github.com/browserbase/stagehand/blob/main/packages/evals/tests/tui/parse.test.ts)
— `it("does not advertise nonexistent WebBench")`.

**Evals do not run in CI** — `ci.yml` has no eval job; only the harness's own unit tests run.

### Test Cases

**Frameworks:** vitest (TS), pytest (Python SDK), `go test` (Go SDK). Two vitest configs enforce a hard split:

- [`vitest.config.ts`](https://github.com/browserbase/stagehand/blob/main/vitest.config.ts) — the cacheable unit suite: `packages/{protocol,docs,evals,integrations/core,extension,sdk-ts}/tests/**`, `packages/protocol/json-rpc/tests/**`, `packages/extension/understudy/**`, `rules/ast-grep/**`, `scripts/**`; **explicitly excludes** `packages/sdk-ts/tests/integration/**`.
- [`vitest.integration.config.ts`](https://github.com/browserbase/stagehand/blob/main/vitest.integration.config.ts) — only `packages/sdk-ts/tests/integration/**`, 60s test/hook timeouts, `fileParallelism: false` (real Chrome).

Counts: **48** `*.test.ts` in `packages/sdk-ts/tests` (31 of them integration), **54** in `packages/evals/tests`,
**46** in `packages/extension`, **28** in `packages/protocol`, **11** in `packages/integrations`, **17** pytest
files in `packages/sdk-python/tests`, **24** `*_test.go` in `packages/sdk-go`, plus `packages/docs/tests/sdk-reference.test.ts`.

**Categories & notable tests:**
- *Integration (real Chrome)* — [`tests/integration/`](https://github.com/browserbase/stagehand/tree/main/packages/sdk-ts/tests/integration): `contextDomainPolicy.test.ts` (network-level allow/deny), `clipboard.test.ts`, `coordinateClick.test.ts`, `fileUpload.test.ts`, `pageDragAndDrop.test.ts`, `nestedDiv.test.ts`, `textSelectorInnermost.test.ts`, `unicodeWellFormed.test.ts`, `cdpSessionDetached.test.ts`, `userDataDir.test.ts`, locator/keyboard/scroll/screenshot coverage. [`scripts/test-integration.ts`](https://github.com/browserbase/stagehand/blob/main/scripts/test-integration.ts) requires every integration file to belong to **exactly one** semantic group (`local/browser-lifecycle`, `local/context-network`, `local/frames-shadow`, …) and **throws on drift**, so a new test can't silently escape the CI matrix.
- *Browser-runtime smoke* — `tests/browser-runtime/stagehandBrowserbaseSmoke.test.ts` (real Browserbase session; internal-head PRs only) and `stagehandLaunchConnectSmoke.test.ts`.
- *Contract/drift* — `packageContract.test.ts`, `runtimeCompatibility.test.ts`, `protocol-schema-type-sync.test.ts`, Python `test_generated_models.py` / `test_generated_input_types.py`, `packages/docs/tests/sdk-reference.test.ts` (docs API reference must match the SDK).
- *Eval-harness unit tests* — `tests/cli.test.ts`, `tests/tui/parse.test.ts`, `tests/framework/{scoring,assertions,metrics,core-runner,persistTrajectory,claudeCodeRunner,braintrust-optional}.test.ts`, `tests/core/{tool-contract,tool-registry,task-portability,fixtures}.test.ts`.

**CI** ([`.github/workflows/ci.yml`](https://github.com/browserbase/stagehand/blob/main/.github/workflows/ci.yml)) —
change-gated fan-out of ~60 jobs:

| Job | What it does |
|---|---|
| `determine-changes` | `dorny/paths-filter` gates the per-SDK jobs |
| `check` | `pnpm build`, then **`git diff --exit-code -- packages/protocol/stagehand.v4.json`** (protocol drift gate), `pnpm check` (fmt/lint/typecheck), `uv lock --check`, generate `--check`, ruff format+check, `ty check`, Go generate `--check`, gofmt, `go vet`, examples check |
| `cancel-after-check-failure` | Cancels the whole run if `check` fails, so the fan-out doesn't burn runners |
| `build` | turbo build + artifact upload (extension dist, sdk-ts dist, evals dist, protocol json) |
| `unit-ts` / `browser-ts` | turbo `test:unit` + root `vitest run`; `test:browser` with a verified Chrome, plus a Browserbase smoke test on internal-head PRs |
| `python-checks` / `python-wheel-smoke` | `uv run --locked pytest`; then install the **built wheel** in an isolated env and run `scripts/smoke.py` against real Chrome |
| `extension-drift` | The `go:embed`'d `stagehand-extension.zip` must byte-match a fresh extension build (`go run ./internal/extensionpack --check`) — fork-gated behind `safe-to-test` |
| `go-checks` / `go-windows` | Full Go suite with Chrome; Windows-only process-management tests (`TestConfigureChromeProcessUsesDedicatedProcessGroupWindows`, taskkill graceful-then-forceful, finished-process error handling) |
| `discover-integration` → `integration/<group>` | Discovers integration groups and fans out a matrix (max-parallel 20), uploading CTRF reports and V8 coverage per group |

Other workflows: `release.yml` (changesets), `publish-python.yml`, `preview.yml`.

---

## lavague-ai/LaVague

> "Large Action Model framework to develop AI Web Agents" — 6.4k★, Python, Apache-2.0.
> **Dormant:** last commit `9024bb8` on **2025-01-21** ("CI: drop cron schedule run (#633)"). Included here as
> a historical/architectural reference, not an active option.

### Repo/Folder Setup

Poetry multi-package repo (each subdirectory is its own PyPI distribution).

| Path | What it is |
|---|---|
| [`lavague-core/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-core) | The framework — `lavague/core/{world_model,action_engine,agents,navigation,retrievers,python_engine,base_driver,memory,logger,token_counter,evaluator,display,extractors}.py` |
| [`lavague-integrations/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-integrations) | `contexts/` (openai, gemini, anthropic, fireworks, cache), `drivers/` (selenium, playwright), `retrievers/` (cohere) |
| [`lavague-server/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-server) | Driver server backing the Chrome extension; `lavague-serve` CLI |
| [`lavague-gradio/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-gradio) | Gradio demo UI (`agent.demo(...)`) |
| [`lavague-qa/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-qa) | Gherkin `.feature` → runnable pytest/Playwright test generation; `lavague-qa` CLI |
| [`lavague-tests/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-tests) | Live-site task runner; `lavague-test` CLI |
| [`extension_chrome/`](https://github.com/lavague-ai/LaVague/tree/main/extension_chrome) | Chrome extension (TS + webpack) |
| `_lavague/` | Meta-package bundle for the umbrella `lavague` dist |
| `docs/`, `mkdocs.yml`, `.readthedocs.yaml`, `examples/`, `tests/` | mkdocs site, example scripts/notebooks, the (single) unit test |

**Language / package manager.** Python `^3.10`, **Poetry** (per-package `pyproject.toml` + `poetry.lock`);
extension uses npm/yarn + webpack. Formatting: ruff (pinned `0.0.292` in CI).

**Install & configure.**
```bash
pip install lavague     # umbrella: lavague-core + drivers-selenium + contexts-openai + gradio
export OPENAI_API_KEY=...
```
Alternative contexts need `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `FIREWORKS_API_KEY`, `HF_TOKEN`.
Ops flags: `LAVAGUE_TELEMETRY=NONE`, `LAVAGUE_UNIQUE_USER_ID`, `DISABLE_LAVAGUE_ANIMATION`.
Browser driver is a real Chrome via Selenium (default) or Playwright; the Chrome-extension driver requires
running `lavague-serve` and loading the unpacked extension.

**Entry points.** Library:
```python
from lavague.core import WorldModel, ActionEngine
from lavague.core.agents import WebAgent
from lavague.drivers.selenium import SeleniumDriver

agent = WebAgent(WorldModel(), ActionEngine(SeleniumDriver(headless=False)))
agent.get("https://huggingface.co/docs")
agent.run("Go on the quicktour of PEFT")
agent.demo("Go on the quicktour of PEFT")   # Gradio
```
Console scripts (there is **no** top-level `lavague` command):
`lavague-test` → `lavague.tests.cli:cli`, `lavague-qa` → `lavague.qa.cli:cli`, `lavague-serve` → `lavague.server.cli:cli`.
Driver feature support is uneven — per the README table, Playwright has no headless-agent or multi-tab support
("coming soon"), and the Chrome extension can't handle iframes.

### Evals

**There is no standard web-agent benchmark in this repo.** No WebVoyager, WebArena, Mind2Web, GAIA, or OSWorld
harness, dataset, or score exists anywhere in the tree, and the README/docs report no success rates or
leaderboard placements. What does exist is *component-level* evaluation:

- [`lavague-core/lavague/core/evaluator.py`](https://github.com/lavague-ai/LaVague/blob/main/lavague-core/lavague/core/evaluator.py) — an abstract `Evaluator` with two concrete subclasses:
  - `RetrieverEvaluator` — scores an HTML retriever's ability to surface the ground-truth node
  - `LLMEvaluator` — scores the Navigation Engine's generated action (Selenium code) against the ground-truth XPath
  Both return pandas DataFrames / CSV; `Evaluator.compare(results, metrics)` renders seaborn bar charts.
- Docs: [`docs/docs/module-guides/evaluation.md`](https://github.com/lavague-ai/LaVague/blob/main/docs/docs/module-guides/evaluation.md); example notebook `examples/eval_example.ipynb`.
- Datasets are external, on Hugging Face under the project's "BigAction" initiative: `BigAction/the-meta-wave-raw` (250 rows of instruction + ground-truth node + XPath) and `BigAction/the-wave-250`.

The closest thing to a task-success benchmark is the `lavague-tests` runner (below), which prints an aggregate
like `Result: 80 % (8 / 10)` — but **no results are committed** to the repo and it is never run in CI.

### Test Cases

Minimal, and the weakest of the four by a wide margin.

- **Unit tests: exactly one file** — [`tests/lavague-core/lavague/core/utilities/test_format_utils.py`](https://github.com/lavague-ai/LaVague/blob/main/tests/lavague-core/lavague/core/utilities/test_format_utils.py). There is no pytest configuration anywhere, and **no workflow invokes pytest**. Effectively there is no unit test suite.
- **[`lavague-tests/`](https://github.com/lavague-ai/LaVague/tree/main/lavague-tests) is the real testing surface**, but it is a live-agent runner, not a test framework: `lavague/tests/{cli,runner,config,test,setup}.py` plus declarative `sites/<name>/config.yml`. Eleven site folders: `google.com`, `amazon.com`, `reddit.com`, `nytimes.com`, `youtube.com`, `huggingface.co`, `weather.com`, `jotform.com`, `wilkipedia.org` [sic], and two locally-served static sites (`examples/`, `iframe/` with `type: static` and their own `www/` HTML, including nested-iframe pages).
  Each task declares `url`, `prompt`, `max_steps`, `n_attempts` and an `expect:` list in a small assertion DSL over properties **URL / Status / Output / Steps / HTML / Tabs** with operators *is, is not, is lower than, is greater than, contains, does not contain*:
  ```yaml
  tasks:
    - name: HuggingFace navigation
      url: https://huggingface.co/docs
      prompt: Go on the quicktour of PEFT
      expect:
        - URL is https://huggingface.co/docs/peft/quicktour
        - Status is success
        - HTML contains PEFT offers parameter-efficient methods for finetuning large pretrained models
  ```
  Run with `lavague-test [-d dir] [-s site] [--display]`; exit code 0 iff every assertion passes. Requires live LLM keys and real network access.
- **CI** — only four workflows ([`.github/workflows/`](https://github.com/lavague-ai/LaVague/tree/main/.github/workflows)), none of which runs pytest:
  - `format.yaml` — `ruff format --check .`
  - `docs-code.yaml` — extracts the Python block from `README.md`, asserts it is identical to the one in `docs/index.md`, installs the local packages, and **executes it against a live OpenAI key**. This is the only real integration check that runs on push.
  - `docs-checker.yaml` — `pyspelling` and a bullet-point format check run on push; but `README-link-checker`, `docs-link-checker`, `docs-examples-checker` (executes every Python snippet in the docs) and `lavague-qa-checker` (runs `lavague-qa` against amazon.fr) are all gated on `if: github.event_name == 'schedule'` — **and the `schedule:` cron block is commented out**, which was the repo's final commit (#633). Those four jobs therefore never fire. Failures notify a Discord webhook.
  - `publish.yaml` — on every push, compares each `pyproject.toml` version against PyPI and auto-publishes if newer.

---

## Cross-Repo Notes

- **Where the evals actually live varies a lot.** Skyvern is the only one that commits raw per-task benchmark results in the main repo. browser-use moved its benchmark to a separate repo (`browser-use/benchmark`) and keeps the production eval platform closed. Stagehand ships the best *harness* but publishes scores only on an external site. LaVague has no task benchmark at all.
- **Contamination control** is an emerging pattern: browser-use Fernet-encrypts `BU_Bench_V1.enc` / `Stealth_Bench_V1.enc` and asks people not to publish plaintext tasks; Skyvern rewrites WebVoyager prompts through a `check-evaluation-goal` LLM pass before running (and tracks `is_updated`) because many original tasks have gone stale.
- **LLM-as-judge is universal**: browser-use judges with `gemini-3.1-flash-lite`, Skyvern with an `Evaluator` against reference answers, Stagehand with per-task rubrics (`precomputed_rubric` in WebTailBench, `adHocRubric.ts`/`verifierGate.ts` elsewhere).
- **Test-suite scale is inversely related to how "agentic" the tested surface is.** Skyvern (888 files) and browser-use (100 files, one CI job each) test deterministic plumbing exhaustively — DOM serialization, CDP, credentials, workflow blocks — and treat agent success as a separate, LLM-judged eval. Stagehand goes further and enforces *structural* invariants in CI (protocol JSON drift, embedded-extension drift, integration-group membership, generated-code drift).
- **Shared benchmark gravity**: WebVoyager, Online-Mind2Web, and Odysseys appear in three of the four repos; browser-use and Stagehand both ship adapters to benchmark *each other* and external harnesses (Claude Code, Codex) on their own task sets.

*Sources: shallow clones of each repo at HEAD on 2026-08-16 (browser-use `eb41269`, skyvern `ef7b59b`, stagehand `0af36da`, LaVague `9024bb8`); GitHub API for repo metadata and `browser-use/benchmark`; [Browserbase evaluations page](https://www.browserbase.com/evaluations) and [Stagehand Evals](https://www.stagehand.dev/evals) for the external leaderboard reference.*
