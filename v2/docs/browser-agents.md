# Browser Agent Repos — Survey

A survey of 32 open-source browser-agent repositories, covering three things per repo:

1. **Repo/folder setup** — structure, language/tooling, install/config, entry points
2. **Evals** — what the maintainers evaluated the agent on (benchmarks, scores, harness locations)
3. **Test cases** — what is tested programmatically (frameworks, layout, CI)

Researched **2026-08-16** by seven Opus 5 (xhigh) research agents, each working from shallow clones
of the repos at HEAD plus GitHub API metadata and the underlying papers. Repos were sourced from the
[Awesome GUI Agent](https://github.com/showlab/Awesome-GUI-Agent) and
[Awesome Web Agents](https://github.com/steel-dev/awesome-web-agents) (steel-dev) lists plus known
flagship projects. Closed-source products on those lists (OpenAI Operator, Project Mariner, Manus,
Runner H, Harpa, …) and pure scraper/search-API entries (FireCrawl, Crawl4AI, Exa, Serper) are
omitted — there's no agent repo to analyze. This document is the synthesis; the full per-repo deep
dives (with file-level citations) live in [`research/`](research/):

- [Batch 1 — Flagship products](research/browser-agents-batch-1.md): browser-use, Skyvern, Stagehand, LaVague
- [Batch 2 — Academic agents](research/browser-agents-batch-2.md): SeeAct, WebVoyager, AutoWebGLM, Agent-E
- [Batch 3 — Benchmarks/environments](research/browser-agents-batch-3.md): WebArena, Mind2Web, WebShop, WebLINX
- [Batch 4 — Newer/misc](research/browser-agents-batch-4.md): Nanobrowser, Notte, UI-TARS-desktop, DeepResearch (ex-WebAgent)
- [Batch 5 — Awesome-list autonomous agents](research/browser-agents-batch-5.md): Surf.new, AgentGPT, Browserable, Openwork, Webwright
- [Batch 6 — Dev-tool agents / infrastructure](research/browser-agents-batch-6.md): steel-browser, Tarsier, Bytebot, VimGPT, Lumen
- [Batch 7 — Awesome-list benchmarks](research/browser-agents-batch-7.md): Bananalyzer, MiniWoB++, WebCanvas, WorkArena, WebGames, HUD

---

## Master table

| Repo | Stars | Lang | What it is | Headline eval | Tests | CI |
|---|---:|---|---|---|---|---|
| [browser-use](https://github.com/browser-use/browser-use) | 109k | Python | CDP-driven agent framework | BU Bench V1: 78/100 (separate repo); claims #1 Odysseys 87.4% | ~100 pytest files, 1 CI job per file | ✅ heavy |
| [Skyvern](https://github.com/Skyvern-AI/skyvern) | 22.8k | Python+TS | Playwright-extension agent + workflow product | WebVoyager 85.8% (raw per-task results committed); WebBench 64.4% | **888 pytest files** | ✅ |
| [Stagehand](https://github.com/browserbase/stagehand) | 24k | TS | Browser-agent SDK (TS/Py/Go) on a Chrome extension | WebVoyager/WebTailBench/OnlineMind2Web/Odysseys harness; scores on external leaderboard only | ~230 files across 3 languages | ✅ ~60-job fan-out |
| [LaVague](https://github.com/lavague-ai/LaVague) | 6.4k | Python | Large Action Model framework — **dormant since 2025-01** | none (component-level only) | 1 unit test file, no pytest in CI | ⚠️ dead cron jobs |
| [SeeAct](https://github.com/OSU-NLP-Group/SeeAct) | 850 | Python | GPT-4V + Playwright agent (ICML'24) | Online Mind2Web 90 tasks: 51.1% oracle / 37.8% real, human-judged | none | none |
| [WebVoyager](https://github.com/MinorJerry/WebVoyager) | 1.1k | Python | GPT-4V + Selenium agent; defines the WebVoyager benchmark | 643 tasks, 59.1% (human-labeled); GPT-4V auto-judge κ=0.70 | none | none |
| [AutoWebGLM](https://github.com/THUDM/AutoWebGLM) | 929 | Python | ChatGLM3-6B web agent — eval/data release, **no weights** | AutoWebBench, Mind2Web 59.5 avg step SR, MiniWoB++ 89.3%, WebArena 18.2% | only vendored WebArena suite (inert) | none |
| [Agent-E](https://github.com/EmergenceAI/Agent-E) | 1.2k | Python | AG2 planner + browser-nav agent | WebVoyager 73.2% — scored by terminal prompt to a human | none (benchmark runner only) | none |
| [WebArena](https://github.com/web-arena-x/webarena) | 1.6k | Python | Self-hosted live-website env, 812 tasks | GPT-4+CoT 14.41% vs human 78.24% | 31 pytest tests | ✅ pytest + mypy --strict |
| [Mind2Web](https://github.com/OSU-NLP-Group/Mind2Web) | 1.0k | Python | Offline benchmark, 2,350 tasks / 137 sites | MindAct Flan-T5-XL: 52.0 step SR cross-task | **none** | **none** |
| [WebShop](https://github.com/princeton-nlp/WebShop) | 583 | Python | Simulated e-commerce gym, 12,087 instructions | IL+RL: 62.4 score / 28.7% SR (human 59.6%) | 17 pytest tests (reward fn + scrapers) | ✅ |
| [WebLINX](https://github.com/McGill-NLP/weblinx) | 163 | Python | Conversational-navigation benchmark, 2,337 demos | Llama-3-8B-Web 28.88 overall (in-repo leaderboard) | 7 unittest tests (1 empty stub) | ✅ |
| [Nanobrowser](https://github.com/nanobrowser/nanobrowser) | 13.6k | TS | Chrome-extension multi-agent (free Operator alternative) | **none** | 1 file (guardrails), **no CI** | none |
| [Notte](https://github.com/nottelabs/notte) | 2.0k | Python | Patchright agent framework + hosted API | WebVoyager30 ×8 runs: 79.0% LLM-judged vs Browser-Use 60.2% (separate repo) | 88 pytest files | ✅ 5 workflows, hardened fork gate |
| [UI-TARS-desktop](https://github.com/bytedance/UI-TARS-desktop) | 38.6k | TS | ByteDance GUI-agent stack (Agent TARS + desktop app) | infra perf only; model benchmarks live in the UI-TARS model repo | ~128 Vitest/Playwright files | ✅ incl. CI-gated perf benchmarks |
| [DeepResearch](https://github.com/Alibaba-NLP/DeepResearch) (ex-WebAgent) | 19.8k | Python | Tongyi ReAct research agent — search/fetch APIs, not browser control (except `NestBrowse/`) | HLE/BrowseComp/GAIA/WebWalkerQA judge pipeline; WebSailor-V2 BrowseComp-EN 35.3 | **none, no `.github/` at all** | none |

### Additions from the Awesome Web Agents list (batches 5–7)

| Repo | Stars | Lang | What it is | Headline eval | Tests | CI |
|---|---:|---|---|---|---|---|
| [Surf.new](https://github.com/steel-dev/surf.new) | 512 | TS+Py | Steel's playground UI for pluggable agents (browser-use, Claude CU) | none | 3 files | minimal |
| [AgentGPT](https://github.com/reworkd/AgentGPT) | 36.3k | TS+Py | **Archived**; not actually browser-driving (no Playwright/CDP anywhere — tools are search/wiki/code) | none | 17 files | ✅ |
| [Browserable](https://github.com/browserable/browserable) | 1.2k | JS | Self-hostable browser-automation library | "90.4% WebVoyager" claimed in prose, **zero supporting code** | effectively none | none |
| [Openwork](https://github.com/accomplish-ai/openwork) | 10.9k | — | → `coworker`; **history force-wiped** to a one-line README. ~112 Vitest files + Electron E2E reconstructed from forks | none | (in forks only) | — |
| [Webwright](https://github.com/microsoft/Webwright) | 5.9k | Python | MSR agent that writes/runs Playwright scripts in a terminal workspace | Online-Mind2Web **86.7%**, Odysseys 60.1% (GPT-5.4); harness not in repo | 16 files | ✅ |
| [steel-browser](https://github.com/steel-dev/steel-browser) | 7.5k | TS | Browser API/sandbox for agents (no LLM in the tree) | scrape-pipeline eval harness only (frozen fixtures + invariants) | 65 vitest tests — **CI never runs them** | ⚠️ |
| [Tarsier](https://github.com/reworkd/tarsier) | 1.8k | Py+TS | Vision/OCR perception layer for web agents | 278-page snapshot corpus; headline claim internal/unpublished | 24 pytest fns | ✅ |
| [Bytebot](https://github.com/bytebot-ai/bytebot) | 11.1k | TS | Containerized desktop/computer-use agent — **archived** | none | **zero** (jest scaffolding only) | build-only |
| [VimGPT](https://github.com/ishan0102/vimGPT) | 2.6k | Python | GPT-4V + Vimium experiment | none | none | none |
| [Lumen](https://github.com/omxyz/lumen) | 56 | TS | Vision-first CDP agent with deterministic replay/action cache | WebVoyager 25-task slice: 25/25 vs Stagehand 19/25 (pass@3 + judge feedback — not comparable to published numbers) | 147 vitest tests | ✅ |
| [Bananalyzer](https://github.com/reworkd/bananalyzer) | 327 | Python | Eval framework: 282+18 frozen MHTML/HAR extraction examples (all `json_match`) — dormant | defines the benchmark; no in-repo baselines | 64 pytest tests | ✅ |
| [MiniWoB++](https://github.com/Farama-Foundation/miniwob-plusplus) | 396 | HTML+Py | Classic RL gym: 128 registered Gymnasium envs | defines the benchmark; no in-repo baselines | 22 test fns | ✅ 5-Py × 2-OS matrix |
| [WebCanvas](https://github.com/iMeanAI/WebCanvas) | 280 | Python | Live-web eval (Mind2Web-Live: 104 tasks / 443 key nodes) | checked-in leaderboard; scores swing 23.6%→42.3% on IP region alone | **none** | **none** |
| [WorkArena](https://github.com/ServiceNow/WorkArena) | 267 | Python | Enterprise tasks on live ServiceNow instances (33 atomic / 19,912 instances + 682 L2/L3) | via BrowserGym; no in-repo baselines | 50 test fns | ✅ incl. nightly instance probe |
| [WebGames](https://github.com/convergence-ai/webgames) | 68 | TS | 150 hand-built challenges (53 families × easy/base/hard) | best model 50.0% vs human 95.7%; 61/150 unsolved by any model | ~none | none |
| [HUD](https://github.com/hud-evals/hud-python) | 291 | Python | SDK/protocol for authoring browser/CU RL environments — no benchmark of its own | n/a | **1,016 pytest tests**, 58% coverage gate | ✅ |

Star counts and repo state as of 2026-08-16. Note `Alibaba-NLP/WebAgent` was renamed to
`Alibaba-NLP/DeepResearch`; the old URL 301-redirects. Two awesome-list repos are archived
(AgentGPT, Bytebot) and one was wiped (Openwork/coworker) — the list itself is ahead of reality.

---

## 1. Repo/folder setup

### Common shapes

- **Python + uv is the modern default** for agent frameworks (browser-use, Skyvern, Notte, Agent-E);
  older research code uses conda + pinned `requirements.txt` (WebArena, Mind2Web, WebShop, WebVoyager,
  DeepResearch). TS projects are uniformly **pnpm + Turborepo monorepos** (Stagehand, Nanobrowser,
  UI-TARS-desktop).
- **Browser control splits three ways**: raw **CDP** (browser-use via `cdp-use`, Skyvern's own
  `skycdp`, Nanobrowser via `chrome.debugger`), **Playwright/forks** (SeeAct, WebArena, Agent-E,
  Notte via the stealth fork *Patchright*, LaVague optionally), and **Selenium** (WebVoyager,
  WebShop's site env). A fourth camp has no browser at all — DeepResearch drives search/fetch APIs.
- **Config is env-var driven everywhere** except Nanobrowser (keys entered in the extension UI and
  stored in `chrome.storage`). Skyvern has the largest config surface (per-provider enable flags,
  credential vaults: Bitwarden/1Password/GCP/Azure). WebArena is the heaviest to stand up: seven
  self-hosted Docker sites (or an AWS AMI) that hard-assert on import.
- **Entry points**: flagships ship CLIs (`browser-use`/`bu`, `skyvern quickstart`, `agent-tars`) and
  library APIs; research repos are `python run.py`-style scripts. Stagehand and Notte are
  library-first with near-identical local vs. hosted API surfaces.

### One line each

- **browser-use** — `browser_use/` package (agent loop, CDP browser layer, DOM serializer, 14 LLM
  provider adapters, MCP client+server), 113 runnable examples, `uv` + hatchling.
- **Skyvern** — backend `skyvern/` (agent `forge/`, browser `webeye/`, Playwright-extension
  `library/`), React frontend, alembic migrations, Docker Compose or `pip install "skyvern[all]"`.
- **Stagehand** — v4 monorepo: TS/Python/Go SDKs over a Chrome extension runtime
  (`packages/extension/`), a JSON-RPC `protocol/` package used as a drift gate, `packages/evals/`.
- **LaVague** — Poetry multi-package repo (core / integrations / server / QA / tests packages);
  architecture reference only, dormant.
- **SeeAct** — dual implementation: research `src/` + PyPI `seeact_package/` sharing ~80% code by copy.
- **WebVoyager** — flat scripts (`run.py`, `utils.py`, `prompts.py`); OpenAI key passed as a CLI flag.
- **AutoWebGLM** — no root packaging; three separately-installed eval environments (MiniWoB++,
  vendored WebArena, offline scorer). Model weights not released.
- **Agent-E** — `ae/` package (planner + browser-nav agents, 10 atomic skills, FastAPI server), uv.
- **WebArena** — gym-style `browser_env/`, `evaluation_harness/`, 812 task configs, Docker/AMI hosting.
- **Mind2Web** — 31 files: two-stage pipeline (DeBERTa candidate ranker → MindAct action prediction),
  Hydra configs; test splits ship password-protected against LLM crawlers.
- **WebShop** — Flask site + `gym` text env, Pyserini/Lucene search index, `setup.sh` data bootstrap.
- **WebLINX** — pip package `weblinx` (single dep: tqdm; everything else extras) + repo-level
  `modeling/` for baselines; offline data from HuggingFace.
- **Nanobrowser** — MV3 extension monorepo; agent system in the background service worker
  (`navigator.ts`, `planner.ts` — the documented Validator agent doesn't exist; docs drift).
- **Notte** — uv workspace of six packages (core/browser/agent/sdk/llm/integrations) with a thin
  `notte` facade; deterministic scripted actions + LLM only where needed is the core pitch.
- **UI-TARS-desktop** — two nested pnpm workspaces; three browser-operation paths (DOM MCP server,
  visual-grounding operator, hybrid switch in Agent TARS). Its `browser-use` package explicitly
  credits Nanobrowser and mirrors its layout.
- **DeepResearch** — flat research layout: `inference/` (8-GPU vLLM launcher + ReAct agent),
  `evaluation/` (LLM judges), `WebAgent/` (one subdir per paper: WebWalker, WebDancer, WebSailor,
  WebShaper, WebWatcher, NestBrowse, …). Python 3.10.0 exactly.

Batches 5–7 (compact — full trees in the research files):

- **Surf.new** — Next.js frontend + FastAPI backend with a pluggable `api/plugins/` agent contract
  (browser-use, Claude computer-use) running against remote Steel sessions.
- **Webwright** — small (~4.1k LoC) Python package; the agent authors and executes Playwright
  scripts in a terminal workspace rather than emitting per-step actions.
- **steel-browser** — npm-workspaces monorepo: Fastify + Puppeteer/CDP API with session/proxy/
  anti-detect plugins, React session viewer; env-var config, no LLM keys anywhere.
- **Tarsier** — Python + TS perception library (screenshot tagging + OCR → text for LLMs), consumed
  by agents rather than being one.
- **Lumen** — vision-first screenshot→model→action loop over CDP with an action cache enabling
  zero-token deterministic reruns.
- **Bananalyzer** — pytest-generating CLI: you subclass `AgentRunner`, it fans your agent out over
  frozen MHTML/HAR site snapshots and scores JSON extraction.
- **MiniWoB++** — 128 self-contained HTML task pages registered as Gymnasium environments; Selenium
  driver; the reward function is the whole eval.
- **WebCanvas** — live-web runner scoring intermediate "key nodes" rather than only final state;
  ships the Mind2Web-Live split (104 tasks).
- **WorkArena** — BrowserGym-compatible task suite generated against a (paid) live ServiceNow
  instance; nightly CI probes the instance pool.
- **WebGames** — Vite/React site of 150 hand-built anti-agent challenges with per-task secret
  passwords for self-verification.
- **HUD** — MCP-based SDK for authoring browser/computer-use RL environments and tasksets with
  verifiable rewards; the strongest engineering in batches 5–7.
- Skipped as not-really-browser-agents or dead: AgentGPT (archived; no browser control), Bytebot
  (archived), Openwork (wiped), VimGPT (experiment), Browserable (template-fork hygiene).

---

## 2. Evals — what they tested the agents on

### Benchmark landscape

**WebVoyager is the gravitational center**: used by Skyvern (85.8%, all 635 per-task results
committed), Agent-E (73.2%, human-scored), Stagehand (642-task dataset in-repo, scores external),
Notte (WebVoyager30 subset, 79.0%), browser-use (disputed 89% claim), and of course the original
repo (59.1%). Second tier: **Online-Mind2Web** and **Odysseys** (200 long-horizon tasks) appear in
browser-use, Stagehand, and Skyvern. Research/API agents target **GAIA / BrowseComp / HLE /
WebWalkerQA** instead (DeepResearch family). The benchmark repos define their own: WebArena (812,
end-to-end success), Mind2Web (2,350, step metrics), WebShop (dense reward), WebLINX (per-turn
IM × IoU/chrF), AutoWebBench (1,451 bilingual step tasks).

### Recurring patterns

- **Eval code often isn't in the main repo.** browser-use → `browser-use/benchmark` (task set
  Fernet-encrypted against training contamination); Notte → `nottelabs/open-operator-evals`;
  Stagehand publishes scores only on stagehand.dev/evals; Skyvern's Odysseys evaluator is closed.
  Skyvern is the only flagship committing raw per-task results in-tree (caveat: its committed 86.0%
  table is run-completion status, not the LLM-judged assertion).
- **LLM-as-judge is universal** for live-site evals — browser-use (gemini-flash-lite), WebVoyager
  (GPT-4V, 85.3% human agreement), Notte/Stagehand (rubrics), DeepResearch (per-dataset judges:
  qwen2.5-72b for GAIA, gpt-4o for BrowseComp). The notable exceptions are fully human-scored:
  SeeAct's online 90-task eval and Agent-E's 643 tasks (terminal Pass/Fail prompt to the operator).
- **Nobody runs an agent benchmark in CI.** browser-use comes closest (a 2-task LLM-judged smoke
  eval per PR that fails only at 0%); Notte explicitly excludes its WebVoyager scripts from CI.
  Benchmark numbers are one-off published artifacts, not continuously verified properties.
- **Contamination control is emerging**: encrypted task sets (browser-use), password-protected test
  splits + canary GUIDs (Mind2Web), stale-task rewriting through an LLM pass (Skyvern).
- **Methodology contributions worth stealing**: Notte's WebVoyager30 ×8-runs design (variance, not
  coverage, is the binding constraint) plus its self-report vs. judge *alignment* metric
  (Browser-Use over-claims at 1.14–1.53×); WebArena's `EvaluatorComb` multiplying string/URL/
  live-DOM-state evaluators so tasks can assert on post-hoc *server state*; WebShop's dense
  decomposable reward that makes RL trainable.

### Selected headline numbers

| Agent | Benchmark | Score | Scoring |
|---|---|---|---|
| Skyvern 2.0 | WebVoyager (635) | 85.8% | LLM judge vs reference answers |
| browser-use (bu-v4-luna) | BU Bench V1 (100) | 78% | LLM judge |
| Notte (gemini-2.0-flash) | WebVoyager30 ×8 | 79.0% | GPT-4 judge (official prompt) |
| Agent-E | WebVoyager (643) | 73.2% | 5 human evaluators |
| WebVoyager (GPT-4V) | WebVoyager (643) | 59.1% | human experts |
| SeeAct | Online Mind2Web (90) | 37.8% (51.1% oracle grounding) | human |
| AutoWebGLM-6B | WebArena (812) | 18.2% | programmatic evaluators |
| GPT-4 + CoT | WebArena (812) | 14.41% (human 78.24%) | programmatic evaluators |
| WebSailor-V2 30B | BrowseComp-EN | 35.3 | LLM judge |

Numbers are not comparable across rows — task sets, judges, and success definitions all differ;
several (browser-use's 89% WebVoyager claim) are disputed by third-party reproduction (Notte
measured 60.2% on its harness).

### Additions from batches 5–7

- **Benchmark repos come in three shapes**: frozen datasets with a runner (Bananalyzer's 300 MHTML/HAR
  snapshots, WebGames' 150 React challenges), live-system harnesses (WorkArena against real ServiceNow
  instances, WebCanvas against the open internet), and RL gyms (MiniWoB++'s 128 envs). The live ones
  are the least reproducible: WebCanvas documents the same agent scoring 23.6% vs 42.3% depending on
  IP region alone.
- **Unverifiable claims are common.** Browserable's "90.4% WebVoyager" appears only in prose;
  Tarsier's "10–20% better" OCR claim is internal and unpublished; Lumen's committed 25/25
  WebVoyager result uses a 25-task slice with pass@3 and judge-feedback injection. Webwright is the
  only batch-5/6 repo with credible published numbers (86.7% Online-Mind2Web), and even it ships no
  runnable harness.
- **WebGames' human-gap number is the cleanest frontier signal** in the survey: best model 50.0%
  vs 95.7% human, with 61 of 150 tasks unsolved by any tested model.

---

## 3. Test cases — what they test programmatically

### The headline finding

**Test rigor and eval sophistication are uncorrelated — often inverted.** The entire academic batch
(SeeAct, WebVoyager, AutoWebGLM, Agent-E) has **zero unit tests and zero CI on the default branch**;
their `test/` directories, where present, are benchmark runners. Mind2Web — the most-forked eval
protocol surveyed — has no tests and no `.github/` at all, as does DeepResearch despite its
elaborate judging pipeline. Meanwhile the production frameworks test heavily but only the
*deterministic plumbing*, never agent success:

| Tier | Repos | Scale |
|---|---|---|
| Heavy | HUD (1,016 tests + coverage gate), Skyvern (888 pytest files), UI-TARS (~128 Vitest), Stagehand (~230 across TS/Py/Go), Lumen (147), browser-use (100), Notte (88) | full CI |
| Targeted | steel-browser (65 — but CI never runs them), Bananalyzer (64), WorkArena (50), WebArena (31), Tarsier (24), MiniWoB++ (22), WebShop (17), Webwright (16), WebLINX (7) | mostly CI |
| Token/none | Nanobrowser (1 file, no CI), LaVague (1 file, dead CI), all of batch 2, Mind2Web, DeepResearch, Bytebot, VimGPT, Browserable, WebCanvas, WebGames | — |

A second-order finding from batches 5–6: **stars are anti-correlated with verification**. The 11k★
archived Bytebot has zero tests; 56★ Lumen has 147 passing tests, CI, and the only reproducible
agent benchmark in its batch. And "tests exist" ≠ "tests run" — steel-browser's well-designed
65-test scrape harness is never invoked by its CI, which only builds Docker images.

### Patterns worth copying

- **Mock only the LLM.** browser-use's house rule: never mock anything except the LLM, never touch
  real remote URLs — every browser test runs real headless Chromium against `pytest-httpserver`
  pages. Its CI fans out one matrix job per test file (~100 parallel, 4-min timeout each).
- **Regression-per-file culture.** Skyvern's 888 files are largely one-bug-one-test
  (`test_element_click_navigation_timeout_skips_fallback.py`), plus golden-prompt snapshot tests
  (prompt drift fails CI), in-browser tests of injected JS, and architecture-enforcement tests
  (`test_no_direct_db_delegates.py`).
- **Structural drift gates.** Stagehand's CI diffs the committed protocol JSON, byte-compares the
  Go-embedded extension zip against a fresh build, and *throws* if an integration test doesn't
  belong to exactly one CI matrix group. There's even a test asserting the CLI "does not advertise
  nonexistent WebBench."
- **Contract snapshots.** UI-TARS snapshot-tests the exact tool set (name/description/JSON schema)
  each browser-control mode exposes — changing the agent's tool contract fails CI. Its action-parser
  suite includes a dedicated `hallucinationCases.test.ts` for malformed VLM output.
- **Test the grader.** WebShop's best tests pin the reward function (fuzzy category matching,
  title-similarity thresholds) — the correctness guarantee for every published number. WebArena's
  evaluator tests replay scripted actions through the real browser env via a `TeacherForcingAgent`
  and assert the evaluator's 1.0/0.0. Anti-pattern: WebLINX's leaderboard-producing
  `eval/metrics.py` has no tests at all, and one shipped test is an empty stub.
- **Docs as tests.** Notte executes README/docs code blocks with `pytest-examples` and
  pip-installs the published package in a throwaway venv; Stagehand asserts its docs API reference
  matches the SDK. Notte also has the best CI security story: fork PRs run without secrets until a
  maintainer reviews and dispatches the trusted suite.
- **Live-site tests are quarantined**, not gated: Notte's WebVoyager-style script replays and
  nightly authenticated-site runs (GitHub/Uber/LeetCode with MFA bot accounts) live outside the
  merge-blocking suite; Agent-E's 32 auto-scored live tasks are documented as inherently flaky.

---

## 4. Takeaways for netgent

1. **Separate "tests" from "evals" explicitly.** Every serious project treats them as different
   artifacts: deterministic pytest/vitest suites gate merges; LLM-judged benchmarks are offline,
   versioned, and published. Don't put agent-success assertions in CI.
2. **Test the deterministic layer exhaustively, mock only the LLM** (browser-use), and unit-test
   whatever computes your metrics (WebShop) — a silent grader bug corrupts every number you report.
3. **For evals, prefer few tasks × many runs with a judge + reliability metrics** (Notte's
   WebVoyager30 ×8, alignment, task-reliability) over one pass at a big task set; and consider
   contamination controls (encryption, canaries) if you publish the task set.
4. **WebVoyager (with an LLM judge) is the de-facto comparable benchmark** for live browser agents;
   WebArena for reproducible end-to-end success; Mind2Web/WebLINX only measure per-step agreement.
   New work increasingly converges on **BrowserGym/AgentLab** as the harness layer.
5. **Commit your raw per-task results** (Skyvern is the only flagship that does) — it's cheap and
   makes claims verifiable; unpublished result files are exactly why browser-use's 89% is disputed,
   and why Browserable's 90.4% and Tarsier's "10–20% better" claims carry no weight.
6. **If you need a harder/cheaper eval than WebVoyager**: WebGames for adversarial capability
   ceilings (self-verifying passwords, huge human-model gap), Bananalyzer/Mind2Web for cheap frozen
   offline runs, WorkArena for enterprise workflows, MiniWoB++ for RL. Check repo health first —
   of the 32 repos surveyed, three are archived/wiped and several more are dormant.
