# Browser Agents Survey — Batch 5 (Autonomous Web Agents)

Research notes for five open-source autonomous web/browser-agent repositories sourced from
[`steel-dev/awesome-web-agents`](https://github.com/steel-dev/awesome-web-agents). Each repo was
shallow-cloned (`git clone --depth 1`) and inspected directly; all paths below are repo-relative and
were verified against the cloned trees. Metadata (stars, language, last push) captured **2026-08-16**
via the GitHub API.

| Repo | Stars | Language | License | Last push | Has evals? | Has tests? |
|---|---:|---|---|---|---|---|
| [steel-dev/surf.new](https://github.com/steel-dev/surf.new) | 512 | TypeScript + Python | MIT | 2025-07-17 | ❌ none | ⚠️ 3 files (2 jest + 1 manual script) |
| [reworkd/AgentGPT](https://github.com/reworkd/AgentGPT) 🗄️ **archived** | 36,307 | TypeScript + Python | GPL-3.0 | 2025-04-29 | ❌ none | ✅ 17 files, real CI |
| [browserable/browserable](https://github.com/browserable/browserable) | 1,201 | JavaScript | MIT | 2025-08-27 | ⚠️ claim only (WebVoyager 90.4%) | ❌ effectively none |
| [accomplish-ai/openwork](https://github.com/accomplish-ai/openwork) → `coworker` 🪦 **wiped** | 10,947 | — (repo emptied) | — | 2026-08-13 | ❌ none | ✅ ~112 files *(in forks)* |
| [microsoft/Webwright](https://github.com/microsoft/Webwright) | 5,918 | Python | MIT | 2026-08-03 | ✅ published, but harness not in repo | ✅ 16 files + CI |

> **Two repos are not what their URL suggests.**
>
> - **`reworkd/AgentGPT` is archived (read-only).** It is also *not a browser-control agent* — despite
>   "in your browser" in the tagline, the agent runs *inside* a web UI and its tools are
>   search/Wikipedia/code/image. There is no Playwright, Selenium, Puppeteer, or CDP dependency
>   anywhere in the repo. It is included here because awesome-web-agents lists it, and it is the
>   most-starred repo in this batch by a wide margin.
> - **`accomplish-ai/openwork` 301-redirects to [`accomplish-ai/coworker`](https://github.com/accomplish-ai/coworker),
>   whose history has been force-wiped.** The repo today is a single commit (`a60802b`,
>   "mark project as unsupported") containing one file: a `README.md` reading "# Coworker / This project
>   is no longer supported." Analysis below is reconstructed from surviving forks, and labelled as such.

---

## surf.new

Steel.dev's "playground for testing web agents" — a Next.js chat UI plus a FastAPI backend that runs
pluggable agents (browser-use, Claude computer-use) against a remote Steel browser session.
Self-described as "an open-source alternative to OpenAI Operator". **512 stars · TypeScript +
Python · MIT.**

Main-branch HEAD at time of clone: `cc865e9` (2025-05-22, "feat: add claude 4 models"); the repo's
`pushed_at` of 2025-07-17 reflects activity on a non-default branch.

### Repo/Folder Setup

A single-repo hybrid: Next.js 15 App Router frontend at the root, FastAPI backend under `api/`,
run concurrently by one `npm run dev`.

```
surf.new/
├── api/                          # FastAPI backend (the agent runtime)
│   ├── index.py                  # ★ backend entry point — all HTTP routes
│   ├── providers.py              # LLM factory: OpenAI / Azure / Anthropic / Gemini / DeepSeek / Ollama
│   ├── models.py  schemas.py     # ModelConfig, ModelProvider; ChatRequest / SessionRequest pydantic
│   ├── streamer.py               # streams agent output in Vercel AI SDK wire format
│   ├── middleware/profiling_middleware.py
│   ├── utils/{prompt.py,types.py}
│   ├── Dockerfile
│   └── plugins/                  # ★ the pluggable-agent system
│       ├── README.md             # "Contributing a New Plugin" — the folder contract
│       ├── __init__.py           # WebAgentType enum + AGENT_CONFIGS (per-agent model/setting schema)
│       ├── base/{agent.py,tools.py}
│       ├── browser_use/          # agent.py + system_prompt.py — wraps the `browser-use` library
│       ├── claude_computer_use/  # agent.py, prompts.py, tools.py, tests.py
│       └── example_plugin/       # scaffold for new agents
├── app/                          # Next.js App Router
│   ├── page.tsx  chat/page.tsx   # landing + chat surfaces
│   ├── contexts/                 # ChatContext, SettingsContext, SteelContext
│   ├── hooks/  stores/  providers/
│   └── tests/                    # ★ the only jest tests (2 files, both markdown-rendering)
├── components/
│   ├── ui/Browser.tsx            # live Steel session viewer iframe
│   ├── ui/SettingsDrawer.tsx     # runtime model/provider/API-key entry
│   └── markdown/                 # hand-rolled markdown parser (Block/Inline/List/Table parsers)
├── monitor/                      # separate tiny Node service: health-checks the backend,
│                                 #   triggers a Railway redeploy if unhealthy (node-cron)
├── types/agents.ts  hooks/  lib/  public/
├── jest.config.js  jest.setup.js  __mocks__/   # jsdom + babel-jest via next/babel
├── package.json  package-lock.json             # npm
└── pyproject.toml  requirements.txt  uv.lock   # uv / pip (Python ≥3.11)
```

**Language / package managers:** TypeScript 5.6 + React 18 + Next.js (latest) via **npm**; Python
≥3.11 via **uv** (`uv.lock`, and `npm run fastapi-dev` shells out to `uv run`). Note the duplicated
dependency declaration — a pinned `requirements.txt` *and* a looser `pyproject.toml`.

**Browser driver:** none is installed locally by default. The agent connects over CDP to a **Steel**
session (`STEEL_CONNECT_URL`, default `wss://connect.steel.dev`); `playwright==1.49.1` is a
dependency and is used for the CDP client, plus `browser-use==0.1.30` for the browser-use plugin.

**Install / configure:**

```bash
npm install
python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cp .env.example .env.local     # ← see gotcha below
npm run dev                    # concurrently: next dev -p 3001 + uvicorn api.index:app --reload
npm run dev:win                # Windows: disables --reload (SelectorEventLoop can't spawn Playwright)
```

> ⚠️ **The README's setup step is wrong in the checkout:** it says `cp .env.example .env.local`, but
> there is no `.env.example` in the repo. The only env template is
> [`.env.local.example`](https://github.com/steel-dev/surf.new/blob/main/.env.local.example), and it
> contains just two lines: `API_URL=http://localhost:8000` and
> `STEEL_CONNECT_URL=wss://connect.steel.dev`.

**API keys.** No LLM key is required in `.env` — keys are normally typed into the UI's
`components/ui/SettingsDrawer.tsx` and sent per-request as `ChatRequest.api_key`
([`api/schemas.py:21`](https://github.com/steel-dev/surf.new/blob/main/api/schemas.py)). The backend
falls back to environment variables when the request omits a key
([`api/providers.py`](https://github.com/steel-dev/surf.new/blob/main/api/providers.py)):
`OPENAI_API_KEY`, `AZURE_OPENAI_{API_KEY,ENDPOINT,API_VERSION}`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, plus `STEEL_API_KEY` / `STEEL_API_URL` / `STEEL_CONNECT_URL`
for the browser session.

**Entry points.** The user-facing entry is the chat UI at `http://localhost:3001`. Programmatically,
the FastAPI surface in [`api/index.py`](https://github.com/steel-dev/surf.new/blob/main/api/index.py)
is the agent API: `POST /api/sessions` (create Steel session), `POST /api/sessions/{id}/{pause,resume,release}`,
`POST /api/chat` (run the agent, streaming), `GET /api/agents` (returns `AGENT_CONFIGS`),
`GET /api/ollama/models`, `GET /healthcheck`. Adding an agent means dropping a folder in
`api/plugins/` and registering it in `WebAgentType` / `AGENT_CONFIGS` / `get_web_agent()`
([`api/plugins/__init__.py`](https://github.com/steel-dev/surf.new/blob/main/api/plugins/__init__.py)).

### Evals

**None.** There is no benchmark harness, no eval directory, no scored task set, and no reported
success rate anywhere in the repo or README. A full-tree grep for `webvoyager|webarena|mind2web|osworld|benchmark`
returns exactly one hit, and it is a false positive — the string `evaluation_previous_goal`, a field
name from the upstream browser-use library, at
[`api/plugins/browser_use/agent.py:252`](https://github.com/steel-dev/surf.new/blob/main/api/plugins/browser_use/agent.py).

This is consistent with the project's stated purpose: surf.new is a **playground / demo harness for
comparing agents by hand**, not a measured agent. Evaluation is the human watching the live browser
pane.

### Test Cases

**Framework:** Jest 29 + Testing Library (`@testing-library/react` 16, `jest-dom` 6) in a **jsdom**
environment, configured in [`jest.config.js`](https://github.com/steel-dev/surf.new/blob/main/jest.config.js)
with `babel-jest` + the `next/babel` preset and CSS/image mocks in `__mocks__/`. Run with `npm test`
(also `test:watch`, `test:file`).

**Layout & coverage — 3 test files total, none of which test an agent:**

| Path | Lines | What it covers |
|---|---:|---|
| [`app/tests/Markdown.test.tsx`](https://github.com/steel-dev/surf.new/blob/main/app/tests/Markdown.test.tsx) | 480 | ~30 cases over the hand-rolled markdown renderer |
| [`app/tests/CodeBlock.test.tsx`](https://github.com/steel-dev/surf.new/blob/main/app/tests/CodeBlock.test.tsx) | 225 | `CodeBlock` component; mocks `react-syntax-highlighter`, Lucide icons, prism styles |
| [`api/plugins/claude_computer_use/tests.py`](https://github.com/steel-dev/surf.new/blob/main/api/plugins/claude_computer_use/tests.py) | 327 | **not a pytest suite** — a manual script (see below) |

`jest.config.js` declares `collectCoverageFrom` over `app/**` and `components/**` but sets
`collectCoverage: false`, and coverage is never collected in CI (there is no CI).

**Notable cases.** `Markdown.test.tsx` is the most substantive suite and is genuinely
adversarial about LLM output quirks — beyond the happy path it asserts graceful degradation on
`handles unclosed formatting gracefully`, `handles unclosed code blocks gracefully`,
`handles malformed tables gracefully`, plus `renders memory blocks correctly` and
`renders goal blocks correctly` (agent-specific `MemoryGoalBlock` syntax), emoji, non-Latin scripts,
and code blocks nested inside lists. That matters here because the markdown parser is what renders
streaming agent reasoning.

`api/plugins/claude_computer_use/tests.py` is **not collected by any runner**: it has no pytest
config (no pytest dependency at all), it imports `from tools import ...` (a bare import that only
resolves if run from inside that directory), and it needs a live `STEEL_API_KEY` plus real network
access. It defines `test_basic_navigation()`, `test_claude_computer_tool_mouse()`, and
`test_claude_computer_tool_stress()`, driven by a `main()` in which **the first two calls are
commented out** and only the stress test runs. It is a developer scratchpad, executed by hand via
`python tests.py`.

**CI: none.** There is no `.github/` directory in the repository — no workflows, no issue templates.
The only automation is a **Husky** `commit-msg` hook running **commitlint**
(`commitlint.config.js`, conventional commits) and lint/format config (ESLint 8 + Prettier +
`eslint-plugin-tailwindcss` + `simple-import-sort`). Nothing runs `npm test` automatically.

---

## AgentGPT

The 2023-era viral autonomous-agent app: name a goal, and a browser-hosted agent loops
think → task → execute → learn. **36,307 stars · TypeScript + Python · GPL-3.0 · 🗄️ ARCHIVED**
(read-only; last commit `18b073a`, 2025-04-28).

**Scope caveat, restated:** this is an *agent that runs in your browser*, not an agent that *drives*
a browser. Grepping `platform/pyproject.toml` and `next/package.json` for
`playwright|selenium|puppeteer|browser-use` returns **nothing**. Its action space is the tool set in
[`platform/reworkd_platform/web/api/agent/tools/`](https://github.com/reworkd/AgentGPT/tree/main/platform/reworkd_platform/web/api/agent/tools):
`search.py` (Serper), `sidsearch.py`, `wikipedia_search.py`, `code.py`, `image.py` (Replicate),
`reason.py`, `conclude.py`. Web *access* is via search APIs, not page interaction.

### Repo/Folder Setup

Four-part monorepo (frontend / backend / db / cli), wired together by `docker-compose.yml` and a
setup CLI.

```
AgentGPT/
├── next/                       # ★ frontend — Next.js 13 (pages router), T3-stack style
│   ├── src/pages/              # incl. pages/api/ (NextAuth, tRPC) and pages/agent/
│   ├── src/services/agent/     # client-side agent orchestration (autonomous loop driver)
│   ├── src/services/{api,workflow}/  src/server/{api,auth}/
│   ├── src/components/         # console/, dialog/, drawer/, landing/, pdf/, sidebar/, templates/
│   ├── src/{stores,hooks,ui,types,utils,lib,env,layout}/
│   ├── prisma/                 # schema + useSqlite.sh (CI swaps MySQL→SQLite)
│   ├── __tests__/              # ★ 3 jest tests
│   ├── jest.config.cjs         # next/jest, jsdom
│   └── package.json  Dockerfile  entrypoint.sh  wait-for-db.sh
├── platform/                   # ★ backend — FastAPI + LangChain 0.0.295 + OpenAI 0.28
│   └── reworkd_platform/
│       ├── web/api/agent/      # the agent core
│       │   ├── agent_service/  # agent_service.py, open_ai_agent_service.py, mock_agent_service.py
│       │   ├── task_output_parser.py   # parses the LLM's task-list output
│       │   ├── model_factory.py  analysis.py  prompts.py  helpers.py  dependancies.py [sic]
│       │   └── tools/          # search, sidsearch, wikipedia, code, image, reason, conclude
│       ├── web/api/{auth,memory,models,metadata}/  web/api/error_handling.py
│       ├── services/           # anthropic.py, aws/s3.py, pinecone/, tokenizer/, security.py, ssl.py
│       ├── db/{crud,models}/   # MySQL via SQLAlchemy 2 async + aiomysql
│       ├── settings.py         # pydantic settings, all REWORKD_PLATFORM_* prefixed
│       ├── conftest.py         # ★ pytest fixtures (creates/drops a real test DB)
│       └── tests/              # ★ 14 pytest files
├── db/                         # MySQL 8 container + setup.sql
├── cli/                        # ★ the recommended entry point: TypeScript setup CLI
├── docs/                       # Mintlify docs (introduction, key-concepts, schemas, features/)
├── scripts/  setup.sh  setup.bat  docker-compose.yml  .env.example
└── .github/workflows/{python.yml,node.js.yml,sponsors.yml,webhooks.yml}
```

**Language / package managers:** Node ≥18 + **npm** (`next/package-lock.json`, `cli/package-lock.json`);
Python 3.11 + **Poetry** (`platform/pyproject.toml`, `platform/poetry.lock`). Backend is `pydantic <2.0`,
`fastapi ^0.98`, `langchain ^0.0.295`, `openai ^0.28` — a 2023 stack, frozen.

**Install / configure.** The blessed path is the bundled CLI:

```bash
./setup.sh            # macOS/Linux  (setup.bat on Windows)
# → prompts for keys, writes .env, then `docker-compose up`
```

`docker-compose.yml` brings up `agentgpt_db` (MySQL 8), `agentgpt_platform` (FastAPI, :8000), and
`agentgpt_frontend` (Next.js, :3000). All backend settings are read from `REWORKD_PLATFORM_*`
environment variables. From
[`.env.example`](https://github.com/reworkd/AgentGPT/blob/main/.env.example) the required/optional keys are:
`REWORKD_PLATFORM_OPENAI_API_KEY` (required), `REWORKD_PLATFORM_SERP_API_KEY` (Serper, optional),
`REWORKD_PLATFORM_REPLICATE_API_KEY` (image gen, optional), `REWORKD_PLATFORM_SID_*` (SID OAuth),
`NEXTAUTH_SECRET` / `NEXTAUTH_URL` plus Google/GitHub/Discord OAuth client pairs, and the
MySQL `REWORKD_PLATFORM_DATABASE_*` / `DATABASE_*` pairs. `NEXT_PUBLIC_MAX_LOOPS=100` /
`REWORKD_PLATFORM_MAX_LOOPS` cap the autonomy loop. A
`REWORKD_PLATFORM_FF_MOCK_MODE_ENABLED` flag swaps in `mock_agent_service.py` so the whole app runs
with no LLM calls — a nice touch for local dev and for the frontend tests.

**Entry points.** Users hit `http://localhost:3000` and type a goal. The backend agent API is
[`platform/reworkd_platform/web/api/agent/views.py`](https://github.com/reworkd/AgentGPT/blob/main/platform/reworkd_platform/web/api/agent/views.py)
(`/api/agent/start`, `/analyze`, `/execute`, `/create` — the four steps of the loop), served by
`uvicorn` against `reworkd_platform.web.application:get_app`.

### Evals

**None.** A grep across all `.py`/`.ts`/`.tsx`/`.md`/`.mdx` for
`webvoyager|webarena|mind2web|osworld|benchmark|evals/` returns **zero** matches. There is no eval
directory, no task set, no scored run, and no reported success rate — in the repo, README, or
`docs/`. Given the 2023 timeframe (predating WebArena/WebVoyager adoption) and that AgentGPT was a
product funnel for Reworkd's commercial platform, agent quality was never measured in-repo.

The closest thing to a quality mechanism is `REWORKD_PLATFORM_MAX_LOOPS` — a hard cap on runaway
loops — and the output-parser tests below, which pin down how robustly LLM output is parsed rather
than how well the agent performs.

### Test Cases

Genuinely the best-maintained test setup of the three "classic" repos in this batch: **17 test files,
~1,350 lines**, split across two runners, both wired into GitHub Actions.

**Backend — pytest.** [`platform/reworkd_platform/tests/`](https://github.com/reworkd/AgentGPT/tree/main/platform/reworkd_platform/tests):

```
tests/
├── agent/
│   ├── test_task_output_parser.py   # ★ parametrized LLM-output-parsing torture test
│   ├── test_analysis.py             # pydantic validation of the agent's tool-choice object
│   ├── test_model_factory.py        # LLM construction from settings
│   ├── test_crud.py                 # agent run persistence
│   └── test_tools.py                # tool registry / naming
├── memory/memory_with_fallback_test.py   # note the inverted `_test.py` naming
├── test_token_service.py (105 ln)  test_schemas.py (61)  test_helpers.py (45)
├── test_security.py  test_dependancies.py  test_s3.py  test_settings.py
├── test_oauth_installers.py  test_reworkd_platform.py
└── ../conftest.py                   # session-scoped fixtures: create_database() → meta.create_all()
                                     #   → AsyncClient with get_db_session overridden → drop_database()
```

`[tool.pytest.ini_options]` in `platform/pyproject.toml` sets `filterwarnings = ["error", ...]`
(warnings are failures) and pins `REWORKD_PLATFORM_DB_BASE=reworkd_platform_test` so tests never
touch the dev DB. Tests are async via `anyio` with an `asyncio` backend fixture.

**Notable case — `test_task_output_parser.py`.** This is the interesting one and the most
transferable to any LLM agent: `TaskOutputParser` has to turn free-form model text into a task list,
and the suite pins both directions. Success cases include a clean JSON array, an array buried in
prose (`'Some random stuff ["1: Hello"]'` → `["Hello"]`), an empty array, and prefix stripping
(`"Task 1: Do something"` → `"Do something"`); `test_parse_with_completed_tasks` asserts already-done
tasks are filtered out. Failure cases are a 9-way parametrized list asserting `OutputParserException`
on non-arrays, bare numbers, `"[abc]"`, and three flavours of unbalanced brackets
(`"[1, 2, 3"`, `"'item1', 'item2']"`, `"['item1', 'item2"`). `test_analysis.py` complements it by
asserting the agent cannot select a nonexistent tool or pass an empty `search` argument — both raise
`ValidationError` at the pydantic layer.

**Frontend — jest.** [`next/__tests__/`](https://github.com/reworkd/AgentGPT/tree/main/next/__tests__),
3 files: `message-service.test.ts` (77 ln), `with-retries.test.ts` (69 ln, retry/backoff wrapper),
`whitespace.test.ts` (16 ln). Config is [`next/jest.config.cjs`](https://github.com/reworkd/AgentGPT/blob/main/next/jest.config.cjs)
via `next/jest` with `jest-environment-jsdom`. There are **no component tests and no browser/E2E
tests** — no Playwright or Cypress anywhere in the repo.

**CI — two path-filtered workflows:**

- [`.github/workflows/python.yml`](https://github.com/reworkd/AgentGPT/blob/main/.github/workflows/python.yml)
  ("Testing Platform", `pull_request` on `platform/**`) runs three parallel jobs on Python 3.11 +
  Poetry: **black --check**, **mypy** (`strict = true`, with `exclude = "tests"`), and **pytest**
  with `--cov="reworkd_platform"` against a real `bitnami/mysql:8.0.30` **service container** with a
  `mysqladmin ping` healthcheck — so the DB-backed CRUD tests execute for real, not against mocks.
- [`.github/workflows/node.js.yml`](https://github.com/reworkd/AgentGPT/blob/main/.github/workflows/node.js.yml)
  (push + PR on `next/**`) runs Node 18, `npm ci`, `npm test` with a dummy `OPENAI_API_KEY=sk-0000000000`,
  then `./prisma/useSqlite.sh && npm run postinstall` to verify the schema still generates after being
  swapped from MySQL to SQLite.

Also present: `dependabot.yml`, issue/PR templates, and a `.pre-commit-config.yaml` +
`.flake8` in `platform/`. Notably, **CI never builds the frontend** (`npm run build` is absent) and
there is no lint job for `next/`.

---

## browserable

Self-hostable, Docker-Compose-deployed browser-automation platform for AI agents: a task queue, a
multi-agent runner, a remote-browser abstraction, an admin UI, and a JS SDK. **1,201 stars ·
JavaScript · MIT.** Last commit `a3af19a`, 2025-08-27.

### Repo/Folder Setup

Six independent Node services in one repo — **not** a workspace monorepo. There is no root
`package.json`, no pnpm/turbo/lerna config; each directory has its own `package.json` and is built
into its own Docker image.

```
browserable/
├── tasks/                    # ★ the agent runtime — Express service (port 2003), the heart of the repo
│   ├── agents/
│   │   ├── browserable.js    # ★ 7,295 lines — the browser agent (DOM/xpath extraction, vision, actions)
│   │   ├── jarvis.js         # 4,438 lines — the orchestrator that plans and dispatches to agents
│   │   ├── deepresearch.js   # 637 lines — SERP-based research agent
│   │   ├── generative.js     # 301 lines
│   │   └── base.js           # 183 lines — BaseAgent: shared `end` / `error` actions contract
│   ├── prompts/agents/{browserable,jarvis,deepresearch}/   # prompt modules per agent
│   │   └── browserable/{action,extract,navigation,vision}Prompts.js
│   ├── logic/                # flow.js, datatable.js, vectors.js, account.js, api_key.js, logs.js …
│   │   └── integrations/{base,browser,deepresearch}.js
│   ├── services/             # browser.js (remote-browser providers), llm.js, db.js, mongodb.js,
│   │                         #   queue.js (Bull), redisPublisher.js, s3.js, email.js, alerts.js
│   ├── routes/               # api.js, flow.js, jarvis.js, account.js, user.js, otp.js, test-utils.js
│   ├── app.js  bin/www  pm2.json  Dockerfile
├── browser/                  # local Playwright browser service (api-server.js + browser-manager.js, ~200 ln)
├── ui/                       # admin dashboard (port 2001) — React 18 + Redux Toolkit + sagas
│   └── ⚠️ a fork of the "React Redux Saga Boilerplate" (see Test Cases)
├── docs/                     # Mintlify site (port 2002): quickstart, guides/, js-sdk/, rest-api/
├── sdk/browserable-js/       # published npm SDK (+ sdk/examples/js-sdk-test)
├── cli/                      # `npx browserable` — 356-line setup wizard (clone → docker compose → open UI)
└── deployment/
    ├── docker-compose.dev.yml   # ★ the actual entry point
    ├── .env                     # committed Supabase/Postgres defaults (placeholder secrets)
    ├── browserable.sql
    └── supabase-docker/
```

**Language / package manager:** Node ≥14, **npm**, CommonJS throughout `tasks/`. Key deps:
`playwright ^1.50.1`, `openai ^4.94`, `zod`, `bull` (Redis queues), `mongodb`, `pg`, `sharp` +
`canvas` + `gifencoder` (screenshot annotation and run GIFs), `tiktoken`/`gpt-tokenizer`, and remote
browser SDKs `@browserbasehq/sdk`, `@hyperbrowser/sdk`, `steel-sdk`.

**Install / configure.** Two documented paths:

```bash
npx browserable                                       # CLI wizard: clones, builds, starts, opens the UI
# or
cd deployment && docker-compose -f docker-compose.dev.yml up
```

The compose file starts ~10 containers: `tasks`, `ui`, `docs`, `browserable-redis` (redis:6.2.6),
`browserable-mongodb` (mongo:latest), `mongo-express`, `minio` + `minio-createbucket` (S3),
`pgadmin`, and `db` (supabase/postgres:15.8.1.060). Services land on 2001 (UI), 2002 (docs),
2003 (tasks API), 27017, 6379, 9000/9001, 3300, 8000.

**API keys are *not* set via env files** — the documented flow is to open the admin dashboard at
`http://localhost:2001/dash/@admin/settings` and paste (a) one LLM provider key (Gemini / OpenAI /
Claude) and (b) one remote-browser provider key (Hyperbrowser or Steel). Under the hood
`tasks/` still reads a large env surface (`grep process.env`): `OPENAI_API_KEY`, `CLAUDE_API_KEY`,
`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID`,
`HYPER_BROWSER_API_KEY`, `LOCAL_BROWSER_SERVICE_URL`, `BROWSER_CONCURRENCY`, `BROWSER_WIDTH`/`HEIGHT`,
`MONGODB_URL`, `S3_*`, `SMTP_*`, `GOOGLE_CLIENT_*`, `DISCORD_*`, `SINGLE_USER_MODE`, `CORS_DOMAINS`.

> ⚠️ `deployment/.env` is **committed** with working placeholder secrets (`POSTGRES_PASSWORD`,
> `JWT_SECRET`, pre-signed Supabase `ANON_KEY`/`SERVICE_ROLE_KEY`, `DASHBOARD_PASSWORD=this_password_is_insecure_and_should_be_updated`).
> Fine for local dev, a live hazard if deployed as-is.

**Entry points.** (1) Admin UI at `:2001` — create a task in the browser. (2) REST API on the tasks
service — `POST /api/v1/task/create`, documented under
[`docs/rest-api/endpoint/`](https://github.com/browserable/browserable/tree/main/docs/rest-api/endpoint)
(create-task, list-tasks, task-runs, task-run-status, task-run-result, task-run-gif, task-run-stop,
tool-input, health, check). (3) The **JS SDK**:

```ts
import { Browserable } from 'browserable-js';
const b = new Browserable({ apiKey: '...' });
const { data } = await b.createTask({ task: '...', agent: 'BROWSER_AGENT' });
await b.waitForRun(taskId);
```

### Evals

**A headline number with no code behind it.** The README states:

> "It is currently at **90.4% on the Web Voyager benchmarks**."

and `docs/getting-started/introduction.mdx:11` repeats it ("90.4% on the Web Voyager benchmark").
Those are the **only two occurrences of the string in the entire repository** — a full-tree grep for
`webvoyager|web voyager|90.4` finds nothing else.

Concretely, the repo contains:

- ❌ no eval directory, no WebVoyager task JSON, no runner script, no results file;
- ❌ no per-task scoring/judge code (WebVoyager is normally scored by a GPT-4V judge — no such code
  exists here);
- ❌ no methodology note: the model used, subset of the 643 WebVoyager tasks, number of trials, or
  date are all unstated;
- ❌ no CI job, script, or npm task that could reproduce it.

So the claim is **unreproducible from this repo**. Treat 90.4% as a marketing figure, not a
verifiable result. (For calibration: it would place browserable at or above the strongest published
WebVoyager numbers of its era, which makes the absence of any harness more conspicuous.)

The only shipped observability that resembles evaluation is per-run artifacts — the task-run **GIF**
endpoint (`docs/rest-api/endpoint/task-run-gif.mdx`, built by `gifencoder` in `tasks/logic/logs.js`)
and the run status/result endpoints, i.e. tooling for a human to review a single run.

### Test Cases

**Effectively none for the agent.** Total automated test files in the repo: **two**, neither of which
touches `tasks/agents/`, which is where the ~12,900 lines of agent logic live.

| Path | Framework | Reality |
|---|---|---|
| [`sdk/browserable-js/src/index.test.ts`](https://github.com/browserable/browserable/blob/main/sdk/browserable-js/src/index.test.ts) | Jest + ts | 95 lines, `jest.mock('axios')` — asserts the SDK's `createTask`/`getTaskRun` call the right URLs and unwrap responses. Pure HTTP-client tests; no agent, no browser. |
| [`ui/cypress/integration/basic.js`](https://github.com/browserable/browserable/blob/main/ui/cypress/integration/basic.js) | Cypress | ⚠️ **Not browserable's test at all.** It is the untouched boilerplate spec: `describe("btw-Boilerplate")`, asserting `cy.title().should("include", "React Redux Saga Boilerplate")` and rendering "react"/"redux" GitHub repo grids. It would fail against the actual admin UI. |

`ui/` is a fork of the *React Redux Saga Boilerplate* and still carries the template's whole test
apparatus without any browserable-specific tests: `npm run validate` (typecheck → eslint →
stylelint → `jest --bail --coverage` → build → size-limit), `test:e2e` via
`start-server-and-test` + `cypress run --record` (**with the boilerplate author's Cypress record key
still hard-coded in `package.json`**), `.codeclimate.yml`, and a `.travis.yml` that runs
`npm run validate` under xvfb with a CodeClimate reporter. None of it is connected to this project's
CI, and there are no `*.spec.tsx` files under `ui/src`.

Two more decoys worth naming explicitly:

- [`tasks/routes/test-utils.js`](https://github.com/browserable/browserable/blob/main/tasks/routes/test-utils.js)
  is **not a test helper** — it is a live Express route (`POST /test-utils`) that accepts a multipart
  upload and pushes it to S3, used to debug MinIO config. It is mounted in the running service.
- `browser/package.json` and `cli/package.json` both declare
  `"test": "echo \"Error: no test specified\" && exit 1"`.

**CI:** the only GitHub Actions workflow in the repo is
[`ui/.github/workflows/push.yml`](https://github.com/browserable/browserable/blob/main/ui/.github/workflows/push.yml)
— and because it lives under `ui/`, not the repo root, **GitHub never runs it**. Even if it did, it
only reports webpack bundle stats to packtracker.io using a `PT_PROJECT_TOKEN` secret. There is **no
root `.github/` directory**: no test job, no lint job, no build job, no Docker build check.

---

## openwork (→ coworker / Accomplish)

An open-source, locally-running **desktop** AI agent (Electron) that automates file management,
document creation, and **browser tasks**, built on top of [opencode](https://github.com/sst/opencode)
with bring-your-own API keys. **10,947 stars · 1,291 forks · originally MIT.**

> 🪦 **Current state: the repository is empty.** `accomplish-ai/openwork` 301-redirects to
> [`accomplish-ai/coworker`](https://github.com/accomplish-ai/coworker). A fresh clone yields exactly
> **one commit** (`a60802b`, "mark project as unsupported") and **one file**, `README.md`, whose
> entire contents are:
>
> ```markdown
> # Coworker
>
> This project is no longer supported.
> ```
>
> The API confirms it: `size: 0`, `language: null`, `license: null`, `0` releases, `0` tags, a single
> `main` branch — the history was force-pushed away rather than the repo being archived. It is the
> only repo left in the `accomplish-ai` org. Naming went **Openwork → Accomplish™ → Coworker**;
> the 0.4.14-era README still points at `accomplish-ai/accomplish`, which also redirects to `coworker`.
>
> **Everything below is reconstructed from surviving forks**, which retain the pre-wipe code:
> - [`awakened-sudo/openwork`](https://github.com/awakened-sudo/openwork) — pristine snapshot at the
>   2026-01-14 launch state (v0.1.0, "Openwork")
> - [`shuv1337/openwork`](https://github.com/shuv1337/openwork) — upstream history through
>   **2026-04-03, v0.4.14** ("Accomplish"), the most-developed state I could recover
>
> Paths cite the fork; they were upstream paths. Nothing here can be verified against the origin repo
> anymore.

### Repo/Folder Setup

pnpm workspace monorepo (`pnpm@9.15.0`, Node ≥20). It grew a lot in three months — the January
snapshot was `apps/desktop` + `packages/shared`; by 0.4.14:

```
accomplish/                        (package name: "accomplish", private, MIT)
├── apps/
│   ├── desktop/                   # ★ Electron app — the product
│   │   ├── src/main/              # main process: ipc/, opencode/, store/, utils/
│   │   ├── src/preload/  src/renderer/{components,pages,stores,lib,styles}/
│   │   ├── skills/  resources/  scripts/   # bundle-skills.cjs, download-nodejs.cjs, package.cjs
│   │   ├── __tests__/             # vitest unit + integration
│   │   └── e2e/                   # ★ Playwright-driven Electron E2E (see Test Cases)
│   ├── web/                       # shared React UI, consumed by desktop's renderer
│   └── daemon/                    # standalone background daemon (scheduler, crash resilience)
├── packages/
│   └── agent-core/                # ★ the agent engine
│       ├── src/…                  # opencode adapter, providers, sandbox, storage, skills, daemon
│       ├── mcp-tools/             # ★ the agent's action space, each an MCP server
│       │   ├── dev-browser/       # Playwright/CDP browser service + SKILL.md + relay/screencast
│       │   ├── dev-browser-mcp/   # ★ MCP wrapper: browser_* tools + AX-snapshot pipeline
│       │   ├── desktop-control/   # OS-level control
│       │   ├── ask-user-question/  file-permission/  safe-file-deletion/
│       │   ├── start-task/  complete-task/  report-thought/  report-checkpoint/
│       │   └── request-connector-auth/
│       └── tests/                 # vitest unit + integration + connectors
├── docs/qa-suites/                # ★ manual QA test matrices (see Evals)
├── scripts/                       # dev.cjs, predev.cjs, dev-remote.cjs, dev-kill.cjs
├── .github/workflows/             # ci.yml, release.yml, commitlint.yml, stale.yml,
│                                  #   refresh-agent-core-split.yml
├── .devcontainer/  .husky/  .snyk  .lintstagedrc.mjs
├── AGENTS.md  CLAUDE.md  AD.md  TRADEMARKS.md
└── README.md + 11 translations (zh-CN, ja, ko, ru, es, tr, ar, id, ta, hi)
```

**How the browser part works.** Unlike the other repos here, browser control is a **skill + MCP
server**, not a hardcoded loop.
[`mcp-tools/dev-browser/SKILL.md`](https://github.com/shuv1337/openwork/blob/main/packages/agent-core/mcp-tools/dev-browser/SKILL.md)
instructs the model that `browser_*` MCP tools are the *only* way to touch a browser, explicitly
banning `open`/`xdg-open`/`start`/`webbrowser` (which would launch the user's default browser rather
than the automation-controlled Chrome). Its headline optimisation is `browser_script`, a batched
action list (`goto`, `waitForLoad`, `waitForSelector`, `waitForNavigation`, `findAndFill`,
`findAndClick`, …) executed in **one** round-trip and returning a snapshot — pitched as "5–10× faster"
than per-action calls, with a full login flow as the worked example. The `dev-browser-mcp/src/snapshot/`
pipeline (`parser`, `compactor`, `differ`, `priority`, `tokens`, `manager`) is a token-budgeted
accessibility-snapshot compressor: parse the AX tree, prioritise, diff against the previous snapshot,
and compact to fit a token budget.

**Install / configure (as of 0.4.14).** End users download a signed installer — macOS arm64/x64
`.dmg`, Windows x64 `.exe`, Linux arm64/x64 `.AppImage` and `.deb` — from `downloads.accomplish.ai`.
No API key is set in a file: you pick a provider in-app (OpenAI, Anthropic, Google, xAI, Bedrock,
Vertex, NVIDIA NIM, GitHub Copilot, Moonshot, Azure Foundry, HuggingFace local inference) or point it
at **Ollama** for fully local models, and grant per-folder filesystem permissions at runtime.
Developers run:

```bash
pnpm install
pnpm dev                     # scripts/dev.cjs → desktop + web + daemon
pnpm build:desktop           # or package / package:mac / package:win / package:linux
```

### Evals

**No benchmark evals.** Grepping the 0.4.14 tree for `webvoyager|webarena|mind2web|osworld|gaia|benchmark`
returns one incidental hit inside `dev-browser-mcp/src/integration.test.ts`; there is no benchmark
harness, task set, or reported success rate, and the README markets capabilities ("clean up messy
folders", "automate browser workflows like research and form entry") without a single number.

What exists instead is a **manual QA matrix**, which is the closest this project comes to structured
evaluation — [`docs/qa-suites/`](https://github.com/shuv1337/openwork/tree/main/docs/qa-suites),
2 markdown files:

- `task-execution-tests.md` — a table of scripted scenarios with stable IDs, steps, and expected
  outcomes across **Task Lifecycle** (`EXEC-LIFE-01`…`04`: starts / completes / fails gracefully /
  stoppable mid-run), **Concurrency** (`EXEC-CONC-01`…`03`: three parallel tasks, isolated pages,
  one finishing doesn't disturb another), **Execution Logs** (`EXEC-LOG-01`…`03`: real-time streaming,
  scrollback, persistence across reload), and **Task-Scoped Permission Prompts** (`EXEC-PROMPT-01`…`03`:
  a permission or `AskUserQuestion` card must appear only on its originating task's page and survive
  tab switches).
- `permissions-filesystem-tests.md` — the same treatment for the filesystem-permission model.

These are human-executed checklists, not automated scoring, and they measure *product* behaviour
(lifecycle, isolation, permissions) rather than *task success rate on web tasks*.

### Test Cases

The most thorough automated test setup in this batch: **~112 test files** at 0.4.14, all
**Vitest**, plus a Playwright E2E layer for the Electron app, all wired into CI.

**Layout (file counts by directory):**

```
packages/agent-core/tests/
├── unit/opencode/       (11)  adapter, auth, cli-resolver, config-builder, config-generator,
│                              log-watcher, message-processor, resolve-task-config, stream-parser,
│                              task-manager, tool-classification
│   ├── completion/       (3)  completion-enforcer, completion-state, prompts
│   └── proxies/          (3)  azure-foundry-proxy, azure-token-manager, moonshot-proxy
├── unit/providers/       (4)  ollama, vertex, validation, tool-support-testing
├── unit/daemon/          (4)  client-lifecycle, scheduler-jobs, socket-path, socket-transport
├── unit/sandbox/         (3)  docker-provider, native-provider, disabled-provider
├── unit/storage/         (3)  database, favorites, secure-storage
├── unit/utils/           (3)  fetch, process-error-classifier, task-validation
├── unit/{skills,services}/(2) skills-manager, summarizer
├── connectors/           (1)  mcp-oauth.unit.test.ts
└── integration/          (1)  full-flow.test.ts
packages/agent-core/mcp-tools/
├── dev-browser-mcp/src/snapshot/  (6)  compactor, differ, manager, parser, priority, tokens
├── dev-browser-mcp/src/           (2)  connection.test.ts, integration.test.ts
└── desktop-control/src/__tests__/ (3)
apps/desktop/__tests__/{unit,integration,main,renderer}/   (~19)
apps/desktop/e2e/specs/         (8)  + e2e/provider-tests/specs/ (4)
apps/web/__tests__/{unit,integration}/                     (~26)
apps/daemon/__tests__/unit/     (6)
```

**Categories.** Unit and integration are separated by *config file*, not just convention:
`apps/desktop` has `vitest.unit.config.ts` and `vitest.integration.config.ts`, exposed as
`test:unit` / `test:integration` / `test:coverage` / `test:watch`. Integration tests exercise the
Electron **main** process for real — `appSettings`, `secureStorage`, `permission-api`, `taskHistory`,
`freshInstallCleanup`, `bundled-node`, `system-path`, `opencode/cli-path`, `opencode/config-generator` —
plus renderer-level React integration tests (`App`, `Header`, `SettingsDialog`, `Sidebar`,
`TaskHistory`, `TaskInputBar`, `StreamingText`, `Execution`/`Home` pages, `taskStore`).

**Notable / interesting cases:**

- **AX-snapshot compression** (`dev-browser-mcp/src/snapshot/*.test.ts`, 6 files) — the token
  budgeter, differ, and priority ranker each get their own suite. This is the piece most agent repos
  leave untested, and it is exactly where silent context blowups come from.
- **E2E on a real Electron binary** — [`apps/desktop/e2e/`](https://github.com/shuv1337/openwork/tree/main/apps/desktop/e2e)
  uses Playwright's Electron driver with page-object models (`home.page.ts`, `execution.page.ts`,
  `settings.page.ts`) and a fixture (`fixtures/electron-app.ts`) that launches the app with
  `E2E_SKIP_AUTH=1` and `E2E_MOCK_TASK_EVENTS=1`, so the UI flow is tested without burning LLM
  tokens. Specs: `home`, `execution`, `favorites`, `daemon`, `settings-providers`, `settings-bedrock`.
  Runs are containerised (`e2e/docker/{Dockerfile,entrypoint.sh,run-e2e.sh}`) so Linux Electron E2E
  is reproducible; native modes exist too (`test:e2e:native`, `--ui`, `--debug`, project filters
  `electron-fast` / `electron-integration` / `provider-e2e`).
- **Live-provider E2E** — `e2e/provider-tests/specs/{openai,google,bedrock-api-key,ollama}.spec.ts`
  drive the real settings flow against real providers, with credentials loaded by
  `secrets-loader.ts` from a gitignored file (`secrets.example.json` is the template) and a local
  `helpers/ollama-server.ts` for the offline case. Kept as a separate Playwright *project* so they
  never block normal CI.
- **Sandbox providers** — `unit/sandbox/{docker,native,disabled}-provider.test.ts`: three
  interchangeable isolation backends, each with its own suite, for an agent that executes arbitrary
  local work.
- **`process-error-classifier` and `completion-enforcer`** — small but telling: the agent has explicit
  logic for "did this task actually finish?" and "was this crash the model's fault or the OS's?", and
  both are pinned by tests.

**CI** ([`.github/workflows/ci.yml`](https://github.com/shuv1337/openwork/blob/main/.github/workflows/ci.yml),
path-filtered on `apps/**`, `packages/**`, `pnpm-lock.yaml`, with `cancel-in-progress` concurrency):
parallel jobs for **Core Package Tests** (`pnpm -F @accomplish_ai/agent-core test`, after
`pnpm rebuild better-sqlite3 --recursive`), **Unit Tests**, **Integration Tests**, **Type Check**
(`pnpm typecheck` across all workspaces), and **E2E Tests (Docker)**; a **Coverage Report** job runs
after unit+integration, uploads `apps/desktop/coverage/` (30-day retention) and writes a coverage
table into `$GITHUB_STEP_SUMMARY`. Other workflows: `release.yml` (version bump → six parallel build
jobs for macOS arm64/x64, Linux arm64/x64, Windows → `create-release`), `commitlint.yml`, `stale.yml`,
and `refresh-agent-core-split.yml`. Local guards: Husky + lint-staged + Prettier + a `.snyk` policy.

---

## Webwright

Microsoft Research's minimal "SWE-style" browser agent: give a coding model a **terminal**, let it
write and debug Playwright **Python scripts**, and the agent's browsing history becomes a single
re-runnable code file. Reports SOTA on two real-website benchmarks. **5,918 stars · Python · MIT.**
Last commit `bc26750`, 2026-08-03.

Its thesis is explicitly anti-harness: *"No multi-agent system, no graph engine, no plugin layer, no
hidden orchestration — just a terminal, a browser, and a model."* The persistent state is the
**workspace** (code, screenshots, logs), not the browser session — the browser is disposable. Design
inspiration is credited to `SWE-agent/mini-swe-agent`.

### Repo/Folder Setup

A single small Python package (~4,100 LoC across `src/`, ~1,500 of it the core loop + env + CLI),
plus a skills/plugin layer and a demo dashboard.

```
Webwright/
├── src/webwright/
│   ├── run/cli.py              # ★ CLI entry point (175 ln) — `webwright` / `python -m webwright.run.cli`
│   ├── run/doctor.py           # `webwright doctor` — environment self-check (147 ln)
│   ├── agents/default.py       # ★ the whole agent loop (467 ln): query → execute_actions → observe,
│   │                           #   + history compaction, AX-snapshot pruning, plan.md, debug artifacts
│   ├── environments/
│   │   ├── local_browser.py    # (567 ln) browser_mode: local_launch | local_cdp | local_persistent
│   │   └── local_workspace.py  # (296 ln) the terminal: executes bash, persists steps/logs/screenshots
│   ├── models/                 # base.py (587) + openai_model.py (157), anthropic_model.py (192),
│   │                           #   openrouter_model.py (206)
│   ├── tools/                  # image_qa.py (141), self_reflection.py (611),
│   │                           #   persistent_local_browser.py (314), skill_use.py (149)
│   ├── config/                 # ★ stackable YAML: base.yaml + model_{openai,claude,openrouter}.yaml
│   │                           #   + local_browser.yaml, persistent_browser.yaml, crafted_cli.yaml,
│   │                           #   task_showcase.yaml   (prompts live here, as Jinja templates)
│   ├── skill_factory/          # ★ 15 modules: init, build, learn, update, route, recommend/retrieve,
│   │                           #   decide, fill, gate, execute, library, llm, prompt, entry_shim
│   │   └── examples/           # learned_library/, trajectories/{lax_ord,sea_jfk,sfo_bos}/,
│   │                           #   flights.skill.yaml, batch.example.json, solve_with_library.sh
│   └── utils/{logging,runtime,serialize}.py   exceptions.py
├── skills/webwright/           # ★ portable agent skill (Claude Code / Codex / OpenClaw / Hermes)
│   ├── SKILL.md
│   ├── commands/{run.md,craft.md}
│   └── reference/{workflow.md,playwright_patterns.md,cli_tool_mode.md}
├── .claude-plugin/{plugin.json,marketplace.json}   .codex-plugin/plugin.json
├── assets/task_showcase/       # small Flask dashboard (app.py + templates/ + tasks/) for repeatable runs
├── assets/compare_trajectory/  # static trajectory viewer (Webwright vs Codex vs Copilot traces)
├── docs/skill_factory/{manual.md,reference.md}
├── tests/                      # conftest.py + skill_factory/ (14) + unit/ (2)
├── pyproject.toml              # setuptools; console_script `webwright = webwright.run.cli:app`
└── .github/workflows/skills-tests.yml
```

**Language / package manager:** Python ≥3.10, **setuptools** via `pip install -e .` (no
poetry/uv/lock file). Deliberately tiny dependency set — `httpx`, `jinja2`, `pydantic`, `pyyaml`,
`rich`, `typer`, `playwright`, `python-dotenv`, `platformdirs`. No LangChain, no agent framework.

**Install / configure:**

```bash
pip install -e .
playwright install chromium
export OPENAI_API_KEY=...        # or ANTHROPIC_API_KEY / OPENROUTER_API_KEY
```

Env vars, by source: `OPENAI_API_KEY` (with `model_openai.yaml`), `ANTHROPIC_API_KEY`
(`model_claude.yaml`), `OPENROUTER_API_KEY` (`model_openrouter.yaml`); `BROWSERBASE_API_KEY` +
`BROWSERBASE_PROJECT_ID` only when `browser_mode=browserbase`; `LOCAL_BROWSER_CDP_URL` /
`BROWSER_CDP_URL` for attaching to an already-running Chrome/Edge (`local_browser.yaml`); and for the
Skill Factory, `OPENAI_ENDPOINT` + `OPENAI_MODEL` (any OpenAI-compatible gateway; `init`, `learn`,
`build`, `route` all honour them), `SKILL_MODEL` / `SKILL_MODEL_ENDPOINT`, `SKILL_AGENT_MAX_TOKEN`.
`webwright doctor` checks the environment (including screenshot capture).

**Entry points — three of them:**

1. **CLI** (the reference path). Configs are *stacked* with repeated `-c`:
   ```bash
   python -m webwright.run.cli \
       -c base.yaml -c model_openai.yaml \
       -t "Search for flights from SEA to JFK on 2026-08-15 to 2026-08-20" \
       --start-url https://www.google.com/flights \
       --task-id demo_openai -o outputs/default
   ```
   Flags: `-c` config(s), `-t` task, `--start-url`, `--task-id`, `-o` output dir, `--debug`.
   Every run writes `trajectory.json`, `raw_responses.jsonl`, screenshots, and a `final_script.py`.
2. **As a plugin/skill inside another coding agent** — `.claude-plugin/` and `.codex-plugin/`
   manifests share `skills/webwright/`; install via `/plugin marketplace add microsoft/Webwright` then
   `/plugin install webwright@webwright` (Claude Code), `codex plugin marketplace add …` (Codex),
   `openclaw plugins install …`, or a symlink into `~/.hermes/skills/` (Hermes). Commands:
   `/webwright:run` (one-shot script) and `/webwright:craft` (a *parameterized* `argparse` CLI tool).
   No extra API key — the host agent's subscription drives the loop.
3. **Skill Factory CLI** — `python -m webwright.skill_factory {init,build,learn,update,route}`,
   e.g. `learn outputs/ --library ./library`; a learned skill is a plain CLI you run with no model:
   `python …/learned_library/<id>/skill.py --origin-city Seattle --origin-code SEA … --date 2026-08-26`
   (~40 s, zero tokens).

### Evals

The strongest eval story in this batch — **published, quantified, and compared against baselines** —
but the **harness itself is not in the repo**. Numbers live in the README, the
[MSR blog post](https://www.microsoft.com/en-us/research/articles/webwright-a-terminal-is-all-you-need-for-web-agents/),
and the [project page](https://microsoft.github.io/Webwright/); `assets/` ships the result charts
(`om2w_autoeval_step100.png`, `odysseys_eval_step100.png`).

**Reported results (100-step budget, real websites):**

| Benchmark | Tasks | Model | Score | Note |
|---|---:|---|---:|---|
| **Online-Mind2Web** | 300 | GPT-5.4 | **86.7%** | "highest among open-sourced harnesses in the AutoEval category" |
| Online-Mind2Web | 300 | Claude Opus 4.7 | 84.7% | stronger on the hard split: **80.5%** vs 76.6% for GPT-5.4 (N=100) |
| **Odysseys** (long-horizon) | 200 | GPT-5.4 | **60.1%** | avg 76.1 steps; **+15.6 pp** over prior SOTA (Opus 4.6, 44.5%) and **+26.6 pp** over base GPT-5.4 (33.5%, xy-coordinate prediction) |

Additional claims: code-as-action beats a reproduced GPT-5.4 screenshot+xy-coordinate baseline across
all difficulty splits; and with 5+ generated CLI tools available, even **Qwen-3.5-9B** completes
Online-Mind2Web-site tasks.

**A second, self-contained eval — the Skill Factory ablation** — is documented *in-repo* at
[`src/webwright/skill_factory/README.md`](https://github.com/microsoft/Webwright/blob/main/src/webwright/skill_factory/README.md)
(lines 244–267), with the setup fully specified: **WebArena**, 10 retrieve-type task templates across
3 self-hosted sites (shopping-admin, gitlab, map), 3 train solves + 2 held-out instances per template,
every task solved both with and without the library, gpt-5.4, 100 runs total.

| | with library | from scratch | Δ |
|---|---:|---:|---:|
| held-out accuracy (20) | **70%** | 55% | **+15 pp** |
| held-out avg steps | **14.7** | 17.1 | −2.4 |
| train accuracy (30) | **86.7%** | 76.7% | +10 pp |
| train avg steps | **13.7** | 15.9 | −2.2 |

with the failure analysis spelled out: 4 of 20 held-out tasks rescued outright, 6 more solved in
fewer steps, best case 33 → 10 steps; **7 of 30 train solves failed the ground-truth gate** and never
entered the library; retrieval stayed correct for all 20 held-out solves as the library grew to 10
skills. The README is also unusually candid about the limits — a `strict` replay "proves only that
the skill reproduced its training run in the original environment," and a skill learned on Linux can
break on macOS (`Control+A` to clear a field is the given example).

**Where the eval code lives: it doesn't.** There is no `evals/`, no Online-Mind2Web or Odysseys task
JSON, no AutoEval judge, no runner script or launch command for the headline benchmarks. A grep for
`webvoyager|webarena|mind2web|osworld|odyssey|benchmark` hits only prose (README, skill_factory
README, docs) and incidental config/prompt text. The reproducible pieces that *are* shipped are the
per-task machinery an eval would sit on top of:

- `--task-id` + `-o outputs/…` conventions, and `trajectory.json` / `raw_responses.jsonl` /
  `agent_response.json` artifacts per run;
- `src/webwright/skill_factory/examples/{tasks,batch}.example.json` and `solve_with_library.sh` —
  batch task specs and a with/without-library wrapper, i.e. the shape of the Skill Factory
  experiment;
- the gate in `skill_factory/gate.py`, which supports `method="gold"` (compare against ground truth)
  as well as `method="self_verify"` — the scoring primitive;
- `assets/task_showcase/` (Flask dashboard over `task.json` + `report.json` per task) and
  `assets/compare_trajectory/` (upload two traces, compare token usage and trajectories), with a
  worked token comparison in the README: 424k total tokens for the Webwright harness vs 3.29M for the
  same task via the Codex skill.

So: **evals are real and reported, but not runnable from this repo** — you'd have to reimplement the
Online-Mind2Web / Odysseys drivers yourself.

### Test Cases

**Framework: pytest — sort of.** 16 files, ~1,900 lines, in [`tests/`](https://github.com/microsoft/Webwright/tree/main/tests),
with `tests/conftest.py` doing exactly one thing: prepending `src/` to `sys.path` so tests import the
package without installing it. There is **no `[tool.pytest.ini_options]`** in `pyproject.toml` and
pytest is not a declared dependency.

The suite is deliberately split by style, which matters because **CI runs each file as a plain script**
(`PYTHONPATH=src python "$t"`), not under pytest:

- **Script-style** (`def run(): assert …` + `if __name__ == "__main__": run()`, some also exposing
  `def test_all(): run()` so pytest collects them): `test_gate`, `test_library`, `test_learn`,
  `test_learned_example`, `test_retrieve_decide`, `test_evolve`, `test_route`.
- **pytest-style** (`monkeypatch`, `tmp_path`, `capsys`, `pytest.raises`, parametrization):
  `test_build_init` (412 ln), `test_fill`, `test_execute`, `test_entry_shim`, `test_llm_env`,
  `test_recommend`, plus both files in `tests/unit/` (`test_doctor`, `test_tool_model_routing`).
  ⚠️ These have no `__main__` block, so the CI loop imports and exits without asserting anything —
  **the pytest-style files are effectively no-ops in CI** and only run if you invoke `pytest` locally.

Everything is **LLM-free and site-free**: the one LLM call in `init` is stubbed, the solve subprocess
is stubbed, `_refine` is monkeypatched, and fake skill bodies stand in for browser-driving code. The
test docstrings state this explicitly.

**Notable cases:**

- [`test_learned_example.py`](https://github.com/microsoft/Webwright/blob/main/tests/skill_factory/test_learned_example.py)
  — "lock the flagship property": asserts the *checked-in* learned skill was aggregated from
  `n_solves >= 3`, that ≥2 parameters were genuinely lifted, that `meta["template"]` contains
  `{{param}}` placeholders, that pipeline boilerplate didn't leak into the template
  (`"Additionally, write" not in template`), that **no run artifacts were accidentally committed**
  (directory contains only `skill.py`, `meta.json`, `replays.json`), and that `skill.py` compiles.
  A repository-integrity test masquerading as a unit test — and a good idea.
- [`test_entry_shim.py`](https://github.com/microsoft/Webwright/blob/main/tests/skill_factory/test_entry_shim.py)
  — the CLI shim must make a skill runnable by `--flags` **without** changing the positional
  `taskspec.json` path that replay depends on; it asserts both invocation styles hand the skill body
  an *identical* taskspec and that hyphenated flags map to underscored params. This is the
  backwards-compatibility contract for the whole learned-skill library.
- [`test_gate.py`](https://github.com/microsoft/Webwright/blob/main/tests/skill_factory/test_gate.py)
  — the admission gate: `self_verify` rejects `None`/`[]`/`""`, enforces the declared
  `output_schema` (a dict must not pass an array schema), and `gold` admits only on exact match.
- `test_fill.py` — "slot filling never invents": an unstated slot must come back `None`, not a
  hallucinated value; malformed model replies degrade safely; the model isn't called at all when
  there are no param names.
- `test_execute.py` — `run_skill` failure modes via a fake skill switched by params: crash, timeout
  (`timeout=1` against a 30 s sleep), empty result, missing file.
- `test_evolve.py` / `test_route.py` — library growth (add vs widen vs drop) and that a clean
  `verdict: run` **never reaches the agent** (`assert not called`), i.e. zero-token reuse actually
  bypasses the model.
- `tests/unit/` — only 2 files, both outside the Skill Factory: `test_doctor.py` (screenshot check)
  and `test_tool_model_routing.py` (tool model-config resolution, `pytest.raises(FileNotFoundError)`).

**CI** — one workflow,
[`.github/workflows/skills-tests.yml`](https://github.com/microsoft/Webwright/blob/main/.github/workflows/skills-tests.yml),
and its scope is narrow: it triggers **only** on changes to `src/webwright/skill_factory/**`,
`src/webwright/tools/skill_use.py`, or `tests/skill_factory/**`. On Ubuntu + Python 3.12 it
`pip install httpx pyyaml jinja2 pydantic` (**not the package itself, and not playwright**), loops
`for t in tests/skill_factory/test_*.py; do PYTHONPATH=src python "$t"; done`, then runs a "wrapper
usage check (F6)" asserting `solve_with_library.sh` exits 1 when called with no args.

Consequences worth naming: **the core agent loop, environments, models, and CLI have no CI coverage
at all** — a change to `agents/default.py` or `environments/local_browser.py` triggers nothing;
`tests/unit/` is never run by CI; there is no lint, format, or type-check job; and there are no
Playwright/browser tests anywhere (unsurprising, since the agent's action space is "write arbitrary
Python", which is hard to unit-test). The tested surface is precisely the newest subsystem, the Skill
Factory.

---

## Cross-Repo Observations

**1. Eval rigour is bimodal, and correlates with who's paying for it.** Of five repos, exactly one
(Webwright, Microsoft Research) reports benchmark numbers with a named benchmark, task count, model,
step budget, and baseline comparison — and it is the only repo backed by a research lab with a paper
and a blog post. browserable states "90.4% on Web Voyager" twice in prose with **zero** supporting
code, methodology, or date. The remaining three report nothing. Product-shaped repos measure demos;
research-shaped repos measure benchmarks.

**2. Even the best eval story ships no eval code.** Webwright's Online-Mind2Web (86.7%) and Odysseys
(60.1%) numbers cannot be reproduced from the repo — no task files, no AutoEval judge, no runner.
This matches the pattern in earlier batches: the harness that generated the headline number is
consistently the piece that stays private, while the agent is open-sourced. The exception is
Webwright's own Skill Factory ablation (WebArena, 55% → 70%), which is fully specified in-repo
including the failure analysis — notable because it's the result that supports a *design* claim
rather than a *leaderboard* claim.

**3. "Tests" and "agent quality" are almost entirely disjoint.** Across all five repos, essentially
no test asserts that an agent completes a web task. What *is* tested is the plumbing around the
model: output parsing (AgentGPT's `TaskOutputParser` — 3 success + 9 failure parametrizations),
snapshot/token budgeting (openwork's 6 files over the AX-snapshot compressor), slot filling that
"never invents" (Webwright's `test_fill`), admission gates and replay contracts (Webwright), and
markdown rendering of streaming output (surf.new's 30 cases, including three "malformed input
degrades gracefully" tests). This is the correct instinct — determinism is testable, model behaviour
isn't — but it means CI green says nothing about whether the agent works.

**4. Two of five repos in this batch are dead, and one died violently.** AgentGPT is archived
(36k stars, frozen on a 2023 LangChain/OpenAI-0.28 stack). openwork/coworker (10.9k stars, 1.3k forks)
had its **entire git history force-pushed away** and replaced with a one-line "no longer supported"
README — no archive flag, no final release, no tag. The 1,291 forks are now the only record of a
project that shipped signed installers for five platforms and had a ~112-file test suite three months
before it vanished. For a survey, forks are a load-bearing artifact.

**5. The action-space design splits three ways, and the newest designs abandon the per-step loop.**
(a) *Per-step DOM/vision actions* — browserable (7,295-line `browserable.js` doing xpath generation,
DOM settling, vision annotation) and surf.new (via browser-use / Claude computer-use). (b) *Batched
tool calls over an AX snapshot* — openwork's `browser_script`, which bundles a whole login flow into
one MCP round-trip explicitly because per-action calls are "5–10× slower". (c) *Code-as-action* —
Webwright, where the model writes free-form Playwright Python in a terminal and the browser is
disposable. Both (b) and (c) are motivated by the same observation: round-trips, not reasoning, are
the bottleneck on long-horizon tasks. Webwright's Odysseys result (+26.6 pp over an xy-coordinate
baseline) is the strongest published evidence for (c).

**6. Reusable-skill libraries are the emerging second layer.** Webwright's Skill Factory distills
solved trajectories into *executable, parameterized, replay-verified* Python skills that run with no
model in ~40 s; openwork ships `SKILL.md`-style skills plus a `skills-manager` and slash-command
autocomplete. Both are betting that the durable artifact of an agent run is code, not a transcript.
Webwright's twist — gate on correctness *before* distillation, then require the distilled skill to
replay its own recorded answers standalone *after* — is the only verification scheme in this batch
that could actually keep a self-growing library from rotting.

**7. Configuration has moved out of `.env` and into the UI, which makes repos harder to evaluate.**
surf.new, browserable, and openwork all take LLM/browser API keys through a settings screen at
runtime rather than environment files (surf.new's `.env.local.example` has two non-secret lines;
browserable's docs say "paste your key in the admin dashboard"; openwork is BYO-key in-app with an
Ollama path for fully local). Convenient for users, but it means there's no declarative record of
what a run was configured with — and no way to script a fair comparison without reverse-engineering
the settings store. Webwright is the counter-example: stackable YAML configs (`-c base.yaml -c
model_openai.yaml`) make a run fully reproducible from the command line.

**8. Small, sharp repos out-test big ones.** Webwright (~4.1k LoC of source) has 16 test files and a
CI workflow; browserable (~15k LoC in `tasks/agents/` alone) has one meaningful test file — an SDK
HTTP-client test — plus a Cypress spec still asserting `"React Redux Saga Boilerplate"` from the UI
template it was forked from, and a workflow file parked at `ui/.github/` where GitHub will never run
it. Repo size and test coverage were inversely related across this batch.

**9. Path-filtered CI quietly leaves the agent uncovered.** Webwright's only workflow triggers solely
on `skill_factory/**` + `tools/skill_use.py` — so the core loop, environments, and models have zero
CI. Worse, its CI executes test files as bare scripts (`python test_x.py`), which means the six
pytest-style files with no `__main__` block **pass vacuously**. AgentGPT is the batch's best-practice
example in contrast: path filters *plus* black + strict mypy + pytest against a real MySQL service
container, and a schema-generation check on the frontend side.

---

*Compiled 2026-08-16. Repos shallow-cloned into `/tmp/browser-agent-research/`; all cited paths
verified against the cloned trees at the commits noted per repo. openwork/coworker analysis is
reconstructed from forks and cannot be verified against the origin repository.*
