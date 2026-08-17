# Browser Agents Survey — Batch 6: Dev Tools / Agent Infrastructure

Repos sourced from [steel-dev/awesome-web-agents](https://github.com/steel-dev/awesome-web-agents). This batch covers infrastructure and perception layers rather than end-to-end agents — with two exceptions (bytebot, lumen) that ship a full agent loop.

**Research method:** each repo shallow-cloned (`git clone --depth 1`) and read directly; metadata from `gh repo view`; external claims verified by fetching primary sources. Star counts and commit dates as of **2026-08-16**.

---

## Summary Table

| Repo | Stars | Lang | License | Last commit | Evals in repo? | Tests in repo? | CI runs tests? |
|---|---|---|---|---|---|---|---|
| [steel-dev/steel-browser](https://github.com/steel-dev/steel-browser) | 7,495 | TypeScript | Apache-2.0 | 2026-07-20 | ⚠️ Yes — but for the **scrape/markdown pipeline**, not agents | ✅ 9 files / 65 tests (vitest) | ❌ **No** — CI only builds Docker images |
| [reworkd/tarsier](https://github.com/reworkd/tarsier) | 1,761 | Python + TS | MIT | 2024-09-30 | ⚠️ Snapshot/perf harness over 278 pages; headline benchmark is **internal & unpublished** | ✅ 13 files / 24 test funcs (pytest) | ✅ ruff + mypy + pytest |
| [bytebot-ai/bytebot](https://github.com/bytebot-ai/bytebot) | 11,088 | TypeScript | Apache-2.0 | 2025-09-11 (**ARCHIVED**) | ❌ **None** | ❌ **None** (jest scaffolding only, zero spec files) | ❌ No — 3 Docker build workflows only |
| [ishan0102/vimGPT](https://github.com/ishan0102/vimGPT) | 2,648 | Python | MIT | 2024-09-25 | ❌ **None** | ❌ **None** (no CI workflows at all) | ❌ No |
| [omxyz/lumen](https://github.com/omxyz/lumen) | 56 | TypeScript | MIT | 2026-03-29 | ✅ **WebVoyager runner + committed result JSONs + 2 competitor baselines** | ✅ 22 files / 147 tests (vitest), verified passing | ✅ Node 20/22 matrix: build + typecheck + test |

**Headline:** only one of five repos (lumen) benchmarks its agent on a public web-agent benchmark. Star count is inversely correlated with eval rigor here — the 11k-star repo has zero tests and zero evals; the 56-star repo has the only reproducible WebVoyager harness.

---

## Steel Browser

> Open-source browser API / sandbox for AI agents — session management, CDP control, proxying, anti-detect fingerprinting, and page→markdown/PDF/screenshot tooling. **7,495 stars · TypeScript · Apache-2.0 · v0.5.2**

Steel is deliberately *not* an agent: it provides the browser your agent drives. There is no LLM in the dependency tree and no API key in the config. This shapes everything below — its "evals" measure content extraction quality, not task success.

### Repo/Folder Setup

npm **workspaces** monorepo (`workspaces: ["api", "ui", "repl"]`), Node ≥22, TypeScript throughout.

| Path | What it is |
|---|---|
| [`api/`](https://github.com/steel-dev/steel-browser/tree/main/api) | The product. Fastify server wrapping Puppeteer/CDP. `@steel-browser/api` |
| `api/src/modules/` | REST route groups: `sessions/`, `actions/`, `cdp/`, `files/`, `logs/`, `selenium/` (each = `.controller.ts` + `.routes.ts` + `.schema.ts`) |
| `api/src/services/cdp/` | Core CDP service — `plugins/`, `instrumentation/` (network + browser-interaction recording), `utils/`, `errors/` |
| `api/src/plugins/` | Fastify plugins: `browser-session.ts`, `browser-socket/`, `request-logger.ts`, `file-storage.ts`, `selenium.ts`, `ui-plugin.ts` |
| `api/src/utils/scrape/` | HTML→markdown pipeline (`defuddle`-based). **This is where the eval suite lives.** |
| `api/extensions/recorder/` | Bundled Chrome extension for session recording (own `package.json`, webpack) |
| `api/selenium/` | Vendored `chromedriver2` + `selenium-server.jar` for the Selenium-compat session mode |
| `api/openapi/` | OpenAPI spec generator (`npm run generate:openapi`) |
| [`ui/`](https://github.com/steel-dev/steel-browser/tree/main/ui) | React/Vite session-viewer + debugger. Includes generated `src/steel-client/` |
| [`repl/`](https://github.com/steel-dev/steel-browser/tree/main/repl) | Minimal Puppeteer scratchpad — single file, `src/script.ts` |
| [`docs/`](https://github.com/steel-dev/steel-browser/tree/main/docs) | `ARCHITECTURE.md`, `DEVELOPMENT_SETUP.md`, `PLUGIN_DEVELOPMENT.md`, `TROUBLESHOOTING.md` |

**Install & configure**

```bash
# Fastest — prebuilt combined image
docker run -p 3000:3000 -p 9223:9223 ghcr.io/steel-dev/steel-browser

# Split API + UI
docker compose up                                   # or DOCKER_DEFAULT_PLATFORM=linux/arm64 for M-series
docker compose -f docker-compose.dev.yml up --build  # contributors: builds from local source

# Native
npm install && npm run dev    # API :3000, UI :5173
```

Config is env-var only — [`api/.env.example`](https://github.com/steel-dev/steel-browser/blob/main/api/.env.example): `NODE_ENV`, `HOST`/`PORT`/`DOMAIN`, `USE_SSL`, `CHROME_HEADLESS`, `CHROME_EXECUTABLE_PATH`, `CHROME_ARGS`, `CDP_REDIRECT_PORT` (9223), `PROXY_URL`, `LOG_LEVEL`, `ENABLE_CDP_LOGGING`, `SKIP_FINGERPRINT_INJECTION`, `DEFAULT_TIMEZONE`, `DEFAULT_HEADERS`. The root [`.env.example`](https://github.com/steel-dev/steel-browser/blob/main/.env.example) holds only the UI's `VITE_API_URL` / `VITE_WS_URL`. **No LLM keys anywhere.** Chrome must exist at a standard path or `CHROME_EXECUTABLE_PATH` (resolution logic in `api/src/utils/browser.ts`).

**Entry points**

- HTTP API on `:3000` — `POST /v1/sessions` (stateful, then connect Puppeteer/Playwright/Selenium via CDP) or the Quick Actions endpoints (`/v1/scrape`, `/v1/screenshot`, `/v1/pdf`).
- Swagger/Scalar docs at `http://localhost:3000/documentation`; UI at `/ui` or `:5173`; CDP debugger on `:9223`.
- SDKs: `steel-sdk` (Node/Python) with `baseURL` override pointing at self-hosted.
- REPL: `cd repl && npm start`.

### Evals

**There is no agent benchmark.** What Steel calls "eval" is a two-tier regression harness for the HTML→markdown scrape pipeline, at [`api/src/utils/scrape/__tests__/`](https://github.com/steel-dev/steel-browser/tree/main/api/src/utils/scrape/__tests__). It is unusually well-designed for what it is, and the [README](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/README.md) is explicit that the *competitive* benchmark is not here:

> "This is the fast per-PR gate. It is intentionally separate from the competitive, LLM-judge benchmark (Steel vs Firecrawl/Jina), which is slow, costs money, needs a live deploy, and is run occasionally by hand."

So the Firecrawl/Jina comparison exists but **no code, data, or numbers are published in the repo.**

**Tier 0 — frozen-fixture regression** ([`markdown.test.ts`](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/markdown.test.ts)). Seven fixtures in `fixtures/`, gzipped so the suite never touches the network:

| Fixture | Shape exercised |
|---|---|
| `article.html.gz` | Long-form article (LessWrong post) — body extraction, footnotes |
| `wikipedia.html.gz` | Tables, dense links, site-specific extractor |
| `arxiv.html.gz` | Math→LaTeX, modal/nav/TOC noise removal |
| `sec.html.gz` | 10 MB SEC filing — robustness, ~11s, **heavy lane only** |
| `synthetic.html` | Hand-built kitchen sink: relative URLs, srcset, base64 img, fenced code, table, nav/footer |
| `fallback.html` | Content trapped in a `role="dialog"` overlay — exercises full-page fallback |
| `api.json` | JSON-response fencing |

Word-count bands are pinned in [`baseline.json`](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/baseline.json) (e.g. `article: 9700–13200`, `sec: 148000–210000`).

**Tier 1 — label-free invariants** ([`eval/`](https://github.com/steel-dev/steel-browser/tree/main/api/src/utils/scrape/__tests__/eval)). Rather than page-specific canaries, 11 invariants that must hold for *any* page, split `error` (gates CI) vs `warn` (reported only), in [`eval/invariants.ts`](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/eval/invariants.ts):

- **error:** `no-script-style-leak`, `no-relative-links`, `no-mangled-links`, `non-empty-when-contentful`, `no-secret-leak` (regexes for OpenAI `sk-`, AWS `AKIA`, GitHub `ghp_`, Slack `xox*`, JWT, PEM private keys)
- **warn:** `no-leaked-chrome-tags`, `no-empty-image-src`, `no-empty-or-fragment-links`, `balanced-code-fences`, `no-html-comments`, `size-ratio-sane`

[`eval/corpus.ts`](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/eval/corpus.ts) is a registry tagged by category (`longform-article`, `reference`, `academic-html`, `gov-listing`, `synthetic-kitchensink`, `spa-modal-fallback`) with an explicit "grow this toward a few hundred pages" comment. [`eval/corpus.test.ts`](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/eval/corpus.test.ts) runs every entry through the real pipeline and **hard-stubs `fetch` to throw** — a network call during extraction is treated as a session-proxy bypass and fails the test.

**How an eval run is launched**

```bash
npm run test -w api          # light corpus, incl. invariant gate
npm run test:heavy -w api    # SCRAPE_EVAL_HEAVY=1 — adds the 10 MB SEC fixture
npm run eval:report -w api   # tsx .../eval/runEval.ts → eval-report.json
```

[`eval/runEval.ts`](https://github.com/steel-dev/steel-browser/blob/main/api/src/utils/scrape/__tests__/eval/runEval.ts) is the aggregate view: per-page table, per-invariant pass rates, latency **p50/p95/max**, empty-output rate, extractor mix, error/warn counts. It writes `eval-report.json` for trend tracking and exits non-zero on any error-level violation.

### Test Cases

**Framework:** vitest 3.2.4 ([`api/vitest.config.ts`](https://github.com/steel-dev/steel-browser/blob/main/api/vitest.config.ts) — `include: ["src/**/*.test.ts"]`, 30s timeout). Tests are colocated next to source, not in a top-level `tests/`.

**9 test files, 65 `it()` blocks total:**

| File | Focus |
|---|---|
| `services/cdp/instrumentation/browser-interaction-script.test.ts` (11) | The injected recorder script — click/doubleClick payloads, **redaction of sensitive inputs via test attributes**, "omits input text by default while preserving length and redaction metadata", drag suppressing the following click, scroll debouncing, nested scroll containers, no duplicate listeners |
| `.../browser-interaction-sanitize.test.ts` (6) | Drops malformed/unknown payloads, truncates text, keeps only finite numeric pointer values |
| `.../browser-interaction-events.test.ts` (5) | CDP binding attachment, **fallback when `runImmediately` is unsupported**, main-frame-only navigation recording, no double-counting binding calls as raw CDP events |
| `.../browser-logger.test.ts` (4) | Context merging, dynamic + functional context updates, event fields beating context fields |
| `.../target-manager.test.ts` (1) | Captures network requests from **dedicated worker targets** (added by the most recent commit, #325) |
| `services/cdp/utils/validation.test.ts` (19) | `isSimilarConfig` — CA-certificate array comparison (order-insensitive, subset, add/remove), headless/proxy/userAgent mismatch |
| `utils/scrape/__tests__/markdown.test.ts` (12) | See evals above, plus `isJsonContentType`, `jsonToMarkdown`, `stripBase64Images` |
| `.../eval/invariants.test.ts` (14) | Each invariant fed crafted bad markdown to prove it catches its failure mode, plus a clean-markdown pass and a severity-subset check |
| `.../eval/corpus.test.ts` (6, parameterized) | The corpus gate |

**Notable:** the invariant *tests* are meta-tests — they verify the eval harness itself detects what it claims to. That's rare and worth copying.

**CI setup — and a real gap.** [`.github/workflows/`](https://github.com/steel-dev/steel-browser/tree/main/.github/workflows) has 6 workflows: `build-docker.yml` (multi-arch push to GHCR on main), `check-build.yml` (PR gate — builds the 3 Dockerfiles), `pr-checks.yml` (conventional-commit title, labeler, breaking-change warnings), `release.yml` (auto semver bump + changelog), `auto-assign.yml`, `welcome.yml`.

> **`grep -rn "npm run test\|vitest" .github/` returns nothing.** No workflow executes the test suite. The [husky pre-commit hook](https://github.com/steel-dev/steel-browser/blob/main/.husky/pre-commit) runs `pretty` → `lint` → `build`, also skipping tests. The eval README says "use in CI" for `test:heavy`, and `docs/DEVELOPMENT_SETUP.md` documents a testing section — but nothing wires it up. The 65 tests and the whole invariant harness are, as committed, developer-local only.

---

## Tarsier

> Vision/perception utilities for web agents: visually tags interactable elements (`[@3]`, `[#7]`, `[$12]`) and OCRs a page screenshot into a whitespace-structured "ASCII-art" text representation. **1,761 stars · Python (+TypeScript) · MIT · v0.8.2**

Not an agent — a perception layer you drop into one. GitHub reports the primary language as Jupyter Notebook (the two cookbook files skew it); the package is Python with a TypeScript-compiled JS payload.

### Repo/Folder Setup

Dual toolchain: **Poetry** for the Python package, **npm** for the injected browser script.

| Path | What it is |
|---|---|
| [`tarsier/`](https://github.com/reworkd/tarsier/tree/main/tarsier) | The package. `core.py` (the `Tarsier` class), `text_format.py`, `_utils.py`, `__main__.py` (CLI) |
| `tarsier/tag_utils.ts` | The element-tagging logic — compiled to `tag_utils.min.js` by esbuild and shipped in the wheel (`include = ["tarsier/**/*.min.js"]`, `exclude = ["tarsier/**/*.ts"]`) |
| `tarsier/adapter/` | Browser abstraction: `playwright.py`, `selenium.py`, `_base.py`, `types.py` |
| `tarsier/ocr/` | `ocr_service.py` — Google Cloud Vision and Microsoft Azure implementations |
| [`tests/`](https://github.com/reworkd/tarsier/tree/main/tests) | pytest suite + `mock_html/` (33 hand-written HTML fixtures) |
| [`cookbook/`](https://github.com/reworkd/tarsier/tree/main/cookbook) | `langchain-web-agent.ipynb`, `llama-index-web-agent.ipynb` — the "agent" examples |
| [`tarsier-snapshots/`](https://github.com/reworkd/tarsier/tree/main/tarsier-snapshots) | **Separate Poetry project** holding the snapshot corpus (278 pages) — see Evals |
| `scripts/` | `setup.sh`, `format.sh` |

**Install & configure**

```bash
pip install tarsier          # consumers
./scripts/setup.sh           # contributors: npm install && npm run build && poetry install
npm run build                # required after editing any .ts
```

Python `>=3.11,<4.0`. Runtime deps pull in both `playwright` and `selenium`. **An OCR credential is mandatory** — Google Cloud Vision service-account JSON, or Azure `{"key": ..., "endpoint": ...}`. Tests read them from `TARSIER_GOOGLE_OCR_CREDENTIALS` / `TARSIER_MICROSOFT_OCR_CREDENTIALS` (see [`tests/.env.example`](https://github.com/reworkd/tarsier/blob/main/tests/.env.example)); the snapshot project uses a flattened form (`TYPE`, `PROJECT_ID`, `PRIVATE_KEY`, …, see [`tarsier-snapshots/.env.example`](https://github.com/reworkd/tarsier/blob/main/tarsier-snapshots/.env.example)).

**Entry points**

- Library: `tarsier.page_to_text(page, tag_text_elements=True)` → `(text, tag_to_xpath)`; `page_to_image(...)` → tagged PNG bytes; `remove_tags(page)`.
- CLI: `python -m tarsier <credentials.json> <url> [-v] [--ocr_provider google|microsoft]` ([`tarsier/__main__.py`](https://github.com/reworkd/tarsier/blob/main/tarsier/__main__.py)) — launches headed Chromium, prints the OCR'd page text and optionally the xpath map.

Tag vocabulary: `[#ID]` text-insertable, `[@ID]` hyperlink, `[$ID]` other interactable, `[ID]` plain text.

### Evals

**The headline number is unpublished.** The [README](https://github.com/reworkd/tarsier/blob/main/README.md#L42) claims:

> "On our internal benchmarks, unimodal GPT-4 + Tarsier-Text beats GPT-4V + Tarsier-Screenshot by 10-20%!"

No benchmark name, task count, dataset, harness, or raw numbers accompany this — no code in the repo produces it. Treat as a marketing claim. Reworkd separately maintains [**bananalyzer**](https://github.com/reworkd/bananalyzer), their open web-agent eval framework, which *is* pinned here as a dev dependency (`bananalyzer = "0.10.8"`) — but only as a **corpus source**, not as a scoring harness.

**What does exist — the snapshot corpus** ([`tarsier-snapshots/`](https://github.com/reworkd/tarsier/tree/main/tarsier-snapshots)). Per its [README](https://github.com/reworkd/tarsier/blob/main/tarsier-snapshots/README.md):

> "We use MHTML pages found in our bananalyzer repo as site targets. For each site on bananalyzer, we store both the screenshot of the page along with the OCR text output. These sites will not change over time therefore they serve as ideal candidates for snapshotting."

[`tarsier_snapshots/snapshots.py`](https://github.com/reworkd/tarsier/blob/main/tarsier-snapshots/tarsier_snapshots/snapshots.py) loads `bananalyzer.data.examples.get_training_examples()`, filters to `source == "mhtml"`, and for each renders at 1440×1024 (Harambe's viewport), waits 3s, then writes `snapshots/<example_id>/screenshot.png` + `ocr.txt`. **278 snapshot directories are committed.** Each `ocr.txt` ends with a `cl100k_base` token count, and the script aggregates them into [`snapshots/token_statistics.txt`](https://github.com/reworkd/tarsier/blob/main/tarsier-snapshots/snapshots/token_statistics.txt):

```
Min tokens: 3          Max tokens: 15761
Average tokens: 1869.0   Median: 1318.0
p50: 1318.0   p90: 3231.0   p99: 10399.75
```

This is a **cost/consistency** measurement, not a task-success measurement: it tells you what a Tarsier page representation costs in the LLM context, and gives a visual diff target when the tagger changes. There is **no accuracy scoring, no pass/fail, no golden OCR comparison** — regressions are caught by a human eyeballing the committed PNGs/text in a PR diff.

**How to run it**

```bash
cd tarsier-snapshots
cp .env.example .env && $EDITOR .env   # Google Vision creds
poetry install
poetry run python tarsier_snapshots/snapshots.py   # regenerates all 278 + token stats
```

**Performance regression harness** — [`tests/test_snapshot_execution_time.py`](https://github.com/reworkd/tarsier/blob/main/tests/test_snapshot_execution_time.py). 15 hand-picked bananalyzer example IDs each carry a hardcoded latency budget, e.g.:

```python
{"id": "h4q2uwr0z0sVFM0q5AV7n", "expected_page_to_image_time": 1.0, "expected_page_to_text_time": 3.0},
{"id": "ct6PuXzujbOlM9zaARUpa", "expected_page_to_image_time": 3.0, "expected_page_to_text_time": 12.0},
```

and asserts `page_to_image` / `page_to_text` complete under budget. **Skipped entirely under `GITHUB_ACTIONS`** (`examples = []` when in CI) — so like Steel, the most interesting harness never runs automatically.

### Test Cases

**Framework:** pytest + `pytest-asyncio` + `pytest-playwright` + `pytest-mock` + `pytest-cov`. Run with `poetry run pytest .`.

**Layout:** flat [`tests/`](https://github.com/reworkd/tarsier/tree/main/tests) with `adapter/` and `ocr/` subpackages; **13 test files, 24 test functions**, but heavy parametrization multiplies the real case count.

[`tests/conftest.py`](https://github.com/reworkd/tarsier/blob/main/tests/conftest.py) supplies the fixtures: `browser`/`context`/`async_page` (async Playwright), `sync_page`, `chrome_driver` (Selenium via `webdriver-manager`), `credentials` (parameterized over OCR providers), `tarsier`, and a `page_context` context manager that serves `mock_html/*.html` over `file://`. Headless is toggled by `GITHUB_ACTIONS` — **headed locally, headless in CI**. Notably, the `credentials` fixture has Microsoft commented out:

```python
# "microsoft", # TODO: Uncomment once microsoft OCR is better.
#              # Basic tarsier text tests fail with it right now
```

— an honest, in-tree admission that the Azure backend fails the suite.

**Categories**

- **Element-tagging correctness** — [`test_elements.py`](https://github.com/reworkd/tarsier/blob/main/tests/test_elements.py) (570 lines) is the heart: **23 parametrized HTML fixtures**, each asserting the exact expected tag metadata (`xpath`, `opening_tag_html`, `element_name`, `element_text`, `text_node_index`, `id_symbol`, `id_string`, `tarsier_id`) *and* the expected page text. Cases: `text_only`, `hyperlink_only`, `interactable_only`, `insertable_only`, `combination`, `br_elem`, `display_contents`, `icon_buttons`, `dropdown`, `iframe`, `image_inside_button`, `image_inside_link`, `image_and_text`, `different_image_sizes`, `hidden_image`, `invalid_text_nodes`, `full_xpath` — plus **five non-Latin scripts**: `japanese`, `russian`, `chinese`, `arabic`, `hindi`. Two extra tests cover text nodes being query-selectable and dropdown option text *not* leaking into the representation.
- **E2E across drivers** — [`test_e2e.py`](https://github.com/reworkd/tarsier/blob/main/tests/test_e2e.py): async Playwright + Selenium both exercised; sync Playwright is `@pytest.mark.skipif(reason="Sync Playwright is not yet supported")`.
- **Artifact cleanup** — [`test_artifact_removal.py`](https://github.com/reworkd/tarsier/blob/main/tests/test_artifact_removal.py) runs against a committed `.mhtml` page and asserts `remove_tags()` leaves no `#__tarsier_id` residue. Colour-tagging assertions are commented out pending a merge.
- **XML namespace handling** — [`test_namespace.py`](https://github.com/reworkd/tarsier/blob/main/tests/test_namespace.py): `test_fix_namespaces`, `test_xpath_namespace` (SVG/XHTML xpath breakage).
- **Adapters** — [`adapter/test_playwright.py`](https://github.com/reworkd/tarsier/blob/main/tests/adapter/test_playwright.py) (mocked `run_js`, `take_screenshot`, `set_viewport_size`; real viewport read-back), [`adapter/test_selenium.py`](https://github.com/reworkd/tarsier/blob/main/tests/adapter/test_selenium.py).
- **OCR** — `ocr/test_dummy.py` (no-text OCR path), `ocr/test_google.py` + `ocr/test_microsoft.py` (invalid-credential handling only).
- **CLI** — [`test_cli.py`](https://github.com/reworkd/tarsier/blob/main/tests/test_cli.py): default/non-default arg parsing, unknown-provider error.
- **Font formatting** — `test_text_formatting.py`, parametrized.

**CI setup:** one workflow, [`.github/workflows/python.yml`](https://github.com/reworkd/tarsier/blob/main/.github/workflows/python.yml), on push/PR to `main`, Python 3.12 + Node 20 — four parallel jobs plus a gated publish:

1. `check-version` — compares `pyproject.toml` version against the live PyPI version to decide whether to publish
2. `ruff` — `poetry run ruff format --check .`
3. `mypy` — `poetry run mypy .` (config is `strict = true`, files = `tarsier`)
4. `pytest` — `npm ci && npm run lint && npm run build` (compiles the TS first), `poetry run playwright install chromium`, then `poetry run pytest -vv --cov="tarsier" .` with **real OCR credentials injected from repo secrets** — meaning CI makes live Google Vision API calls
5. `publish` — needs all of the above; auto `poetry publish --build` to PyPI when on `main` and the version is new

This is the strongest CI in the batch: real browsers, real OCR calls, type + format gates, and automated release.

**Status note:** last commit **2024-09-30** — roughly two years dormant. Deps are pinned to that era (`playwright ^1.44`, `pytest-asyncio <0.25`).

---

## Bytebot

> Self-hosted AI **desktop** agent — a containerized Ubuntu/XFCE desktop the agent sees and controls via screenshots + nut.js input, with a NestJS task API and a Next.js UI. **11,088 stars · TypeScript · Apache-2.0**

> [!WARNING]
> **This repository is ARCHIVED (read-only).** Last commit `3d37894`, **2025-09-11**. Broader in scope than a browser agent — it drives Firefox, Thunderbird, VS Code, 1Password and a terminal inside the container.

### Repo/Folder Setup

npm per-package (each package has its own `package-lock.json`; there is **no workspace root** — no root `package.json` at all). Three NestJS services + one Next.js app.

| Path | What it is |
|---|---|
| [`packages/bytebotd/`](https://github.com/bytebot-ai/bytebot/tree/main/packages/bytebotd) | The desktop daemon that runs *inside* the container. `computer-use/` (REST action API + validation pipe), `nut/` (nut.js mouse/keyboard/screen), `input-tracking/` (records human demos), `mcp/` (MCP server exposing computer-use tools, with a `compressor.ts`) |
| `packages/bytebotd/root/` | Baked container filesystem — `supervisord.conf`, XFCE xfconf XML, LightDM autologin, Firefox/Thunderbird enterprise `policies.json`, `.desktop` launchers for Firefox/Thunderbird/VS Code/1Password/terminal |
| [`packages/bytebot-agent/`](https://github.com/bytebot-ai/bytebot/tree/main/packages/bytebot-agent) | The brain. `agent/` (`agent.processor.ts`, `agent.computer-use.ts`, `agent.scheduler.ts`, `agent.tools.ts`, `input-capture.service.ts`), per-provider adapters `anthropic/` `openai/` `google/` (each `.service.ts` + `.tools.ts`), `tasks/` (controller + gateway + service), `messages/`, `summaries/`, `proxy/`, `prisma/` |
| [`packages/bytebot-agent-cc/`](https://github.com/bytebot-ai/bytebot/tree/main/packages/bytebot-agent-cc) | Claude-Code-backed variant of the agent (its own Prisma schema + Dockerfile) |
| [`packages/bytebot-ui/`](https://github.com/bytebot-ai/bytebot/tree/main/packages/bytebot-ui) | Next.js task UI with embedded noVNC viewer; custom `server.ts` |
| [`packages/bytebot-llm-proxy/`](https://github.com/bytebot-ai/bytebot/tree/main/packages/bytebot-llm-proxy) | LiteLLM config only (`litellm-config.yaml` + Dockerfile) |
| `packages/shared/` | Shared TS types/utils, built by every other package's `build` script |
| [`docker/`](https://github.com/bytebot-ai/bytebot/tree/main/docker) | 5 compose files: `docker-compose.yml`, `.core.yml`, `.development.yml`, `.proxy.yml`, `docker-compose-claude-code.yml` |
| [`helm/`](https://github.com/bytebot-ai/bytebot/tree/main/helm) | Umbrella chart + subcharts for agent / desktop / llm-proxy / ui / postgresql; `values-simple.yaml`, `values-proxy.yaml` |
| [`docs/`](https://github.com/bytebot-ai/bytebot/tree/main/docs) | Mintlify site (`docs.json`) — `quickstart.mdx`, `core-concepts/`, `api-reference/`, `rest-api/`, `deployment/`, `guides/` |

**Install & configure**

```bash
git clone https://github.com/bytebot-ai/bytebot.git && cd bytebot
echo "ANTHROPIC_API_KEY=sk-ant-..." > docker/.env   # or OPENAI_API_KEY / GEMINI_API_KEY
docker-compose -f docker/docker-compose.yml up -d
open http://localhost:9992
```

Also 1-click Railway, and Helm for Kubernetes. Postgres 16 is required (`DATABASE_URL`, default `postgresql://postgres:postgres@postgres:5432/bytebotdb`); the desktop container runs `privileged: true` with `shm_size: 2g`. Other env: `BYTEBOT_DESKTOP_BASE_URL`, `BYTEBOT_AGENT_BASE_URL`, `BYTEBOT_DESKTOP_VNC_URL`, `DISPLAY=:0`.

**Entry points / ports**

| Port | Surface |
|---|---|
| `9992` | Tasks UI (main interface) |
| `9991` | Agent REST API — `POST /tasks` with `{"description": "..."}` |
| `9990` | Desktop API — `POST /computer-use`; `/vnc` (noVNC); `/websockify`; **`/mcp` (MCP SSE endpoint)** |

Dev entry points are standard Nest/Next: `npm run start:dev` per package (each first builds `../shared`).

### Evals

**None.** `grep -rin "benchmark\|osworld\|webarena\|webvoyager\|eval\|evaluation\|success rate"` across `README.md` and the entire `docs/` tree returns **zero matches**. There is no eval directory, no task set, no scoring harness, and no published success rate anywhere in the repo — notable for a computer-use agent, where OSWorld/WindowsAgentArena are the obvious targets. Positioning is entirely capability-narrative ("Download all invoices from our vendor portals and organize them into a folder") with demo videos.

### Test Cases

**None.** This is the starkest finding in the batch. Searching the whole tree for `*.spec.ts`, `*.test.ts`, `jest.config*`, or a `test/` directory returns **nothing**.

What *is* present is unmodified NestJS scaffolding. [`packages/bytebot-agent/package.json`](https://github.com/bytebot-ai/bytebot/blob/main/packages/bytebot-agent/package.json) declares a full jest setup:

```json
"scripts": {
  "test": "jest",
  "test:watch": "jest --watch",
  "test:cov": "jest --coverage",
  "test:debug": "node --inspect-brk ... jest --runInBand",
  "test:e2e": "jest --config ./test/jest-e2e.json"
},
"jest": { "rootDir": "src", "testRegex": ".*\\.spec\\.ts$", "transform": {"^.+\\.(t|j)s$": "ts-jest"}, ... }
```

with `jest`, `ts-jest`, `@nestjs/testing`, `supertest`, `@types/jest`, `@types/supertest` all installed. The same block is duplicated in `bytebot-agent-cc` and `bytebotd`. But:

- **zero `.spec.ts` files exist** anywhere, so `npm test` matches nothing
- **`./test/jest-e2e.json` does not exist**, so `npm run test:e2e` fails outright
- `format` scripts reference `"test/**/*.ts"` — a directory that was never created

`bytebot-ui` and `shared` don't even declare a test script.

**CI setup:** [`.github/workflows/`](https://github.com/bytebot-ai/bytebot/tree/main/.github/workflows) has exactly three workflows — `build-agent.yaml`, `build-desktop.yaml`, `build-ui.yaml`. All three are path-filtered Docker buildx jobs pushing multi-arch (`linux/amd64,linux/arm64`) `:edge` images to GHCR on push to `main`. **No test job, no lint job, no typecheck job, and no PR-triggered workflow at all** — every workflow is `on: push: branches: [main]`. Nothing gates a pull request.

---

## vimGPT

> Browse the web with GPT-4V and Vimium — screenshot the page with Vimium's yellow hint overlays showing, ask the vision model which hint to press. **2,648 stars · Python · MIT**

A proof-of-concept, and honest about it. Four Python files, ~250 lines total. Last commit **2024-09-25**.

### Repo/Folder Setup

**No package manager beyond a pinned `requirements.txt`; no packaging, no `setup.py`/`pyproject.toml`; no subdirectories.** The complete file list:

| File | What it is |
|---|---|
| [`main.py`](https://github.com/ishan0102/vimGPT/blob/main/main.py) | Entry point + the agent loop. Argparse for `--voice`, optional `WhisperMic` capture, then `while True:` → capture → `vision.get_actions` → `driver.perform_action` until `done` |
| [`vimbot.py`](https://github.com/ishan0102/vimGPT/blob/main/vimbot.py) | `Vimbot` class — sync Playwright `launch_persistent_context` with Vimium side-loaded via `--load-extension`, 1080×720 viewport. `navigate`/`type`/`click`/`capture`. `capture()` presses `Escape` then `f` to make Vimium paint hint labels before screenshotting |
| [`vision.py`](https://github.com/ishan0102/vimGPT/blob/main/vision.py) | OpenAI call. Resizes to 1080px wide, base64-encodes, one big prompt instructing JSON-only output with keys `navigate`/`type`/`click`/`done`. Includes a **second LLM call as a JSON repair fallback** when `json.loads` fails |
| [`setup.sh`](https://github.com/ishan0102/vimGPT/blob/main/setup.sh) | Three lines: curl the Vimium `master.zip` from GitHub, unzip to `./vimium-master`, delete the zip |
| `requirements.txt` | Fully pinned (`openai==1.1.2`, `playwright==1.39.0`, `Pillow==10.1.0`, `pydantic==2.4.2`, plus `whisper-mic`, `instructor`) |
| `.pre-commit-config.yaml` | trailing-whitespace, end-of-file-fixer, `ssort`, `isort --profile black`, `black --line-length 120` |
| `.github/FUNDING.yml` | The only thing in `.github/` |

**Install & run**

```bash
pip install -r requirements.txt
./setup.sh                    # downloads Vimium into ./vimium-master
echo "OPENAI_API_KEY=sk-..." > .env
python main.py                # prompts for your objective at stdin
python main.py --voice        # WhisperMic captures the objective by speech
```

Hardcoded: model is `gpt-4o` (upgraded from the original GPT-4V), `max_tokens=100`, start page is `https://www.google.com`, `vimium_path = "./vimium-master"`. Chromium is launched **headed by default** (`Vimbot(headless=False)`); the `headless` param exists but `main.py` never passes it, and Vimium hint rendering is the whole mechanism, so headless is not really viable.

### Evals

**None.** No benchmark, no task set, no scoring, no reported success rate anywhere in the repo.

The README's "Shoutouts" section links [VisualWebArena (arXiv 2401.13649)](https://arxiv.org/abs/2401.13649) with a "(page 9)" pointer, which can read as though vimGPT was benchmarked there. **It was not.** Fetching the full paper text, vimGPT appears exactly once, in footnote 3 of the related-work discussion:

> "GPT-4V-ACT and vimGPT propose similar interfaces. […] Most have been proof-of-concept demos, and to the best of our knowledge, we are the first to systematically benchmark this on a realistic and interactive web environment."

So it is cited as prior art with a *similar interface*, explicitly characterized as a proof-of-concept demo, and **no success rate is reported for it**. (For context, VisualWebArena's own best VLM agent scores 16.4%, GPT-4V 15.05%, vs 88.7% human.) The README's other shoutouts — HackerNews thread, WIRED coverage — are press, not evaluation.

The README's "Ideas" list does read as a candid self-assessment of failure modes: low resolution causing detection failures, no cycle-detection ("Build a graph-based retry mechanism that makes sure we aren't falling into cycles, i.e. recursively clicking on the same element"), no JSON mode, no history/context retention between steps.

### Test Cases

**None.** No test files, no test framework in `requirements.txt`, no `tests/` directory, and **no GitHub Actions workflows** — `.github/` contains only `FUNDING.yml`.

The only automated quality gate is the pre-commit config (formatting and import sorting), which runs locally and is not enforced by CI. Given the repo is ~250 lines with a single hardcoded prompt, that is a defensible scope choice — but it should be recorded as *zero programmatic verification*, not as light testing.

---

## Lumen

> Vision-first browser agent with self-healing deterministic replay — screenshot → model → action, no DOM scraping and no selectors. Described in its README as "[Jina's](https://usejina.com) underlying browser agent." **56 stars · TypeScript · MIT · v0.2.0 (`@omxyz/lumen`)**

Newest and smallest repo in the batch (created 2026-03-01, last commit 2026-03-29) and by a wide margin the most rigorous on evals and tests.

### Repo/Folder Setup

Single npm package, ESM-only, built with `tsup`. Node `^20.19.0 || >=22.12.0`.

| Path | What it is |
|---|---|
| [`src/agent.ts`](https://github.com/omxyz/lumen/blob/main/src/agent.ts), `src/session.ts` | Public surface — `Agent.run()`, `new Agent()`, `agent.stream()`, `Agent.resume()` |
| `src/loop/` | The perception loop and everything bolted onto it: `perception.ts`, `planner.ts`, `history.ts` (2-tier compaction), `state.ts` (`StateStore`), `router.ts`, `policy.ts` (domain allow/block), `verifier.ts` + `confidence-gate.ts` (termination gates), `repeat-detector.ts` (3-layer stall detection), `action-verifier.ts`, `action-cache.ts`, `checkpoint.ts`, `child.ts` (sub-task delegation), `monitor.ts`, `streaming-monitor.ts` |
| `src/browser/` | `cdp.ts` (raw WebSocket CDP), `cdptab.ts`, `tab.ts` (interface), `viewport.ts`, `launch/local.ts`, `launch/browserbase.ts` |
| `src/model/` | `adapter.ts` (+ `withRetry`), `anthropic.ts`, `google.ts`, `openai.ts`, `custom.ts` (OpenAI-compatible), `decoder.ts` (`ActionDecoder` — normalizes every provider's coordinate format to viewport pixels) |
| `src/memory/` | `site-kb.ts` + `default-site-kb.json` (domain-specific navigation tips), `workflow.ts` (reusable routines from successful runs) |
| [`tests/`](https://github.com/omxyz/lumen/tree/main/tests) | `unit/` (12 files) + `integration/` (10 files + `mock-tab.ts`, `mock-adapter.ts`) |
| [`evals/webvoyager/`](https://github.com/omxyz/lumen/tree/main/evals/webvoyager) | The benchmark harness — see below |
| [`examples/`](https://github.com/omxyz/lumen/tree/main/examples) | 7 runnable scripts: `smoke-test.ts` (mock-only, no API key), `todomvc-test.ts`/`todomvc-debug.ts`, `spa-test.ts`, `complex-task.ts`, `long-running-task.ts`, `travel-research.ts` |
| [`docs/`](https://github.com/omxyz/lumen/tree/main/docs) | VitePress site — `guide/`, `guide/use-cases/` (19 pages incl. [`evaluations.md`](https://github.com/omxyz/lumen/blob/main/docs/guide/use-cases/evaluations.md)), `architecture/overview.md` + [`comparison.md`](https://github.com/omxyz/lumen/blob/main/docs/architecture/comparison.md), `reference/` |

**Install & configure**

```bash
npm install @omxyz/lumen     # requires Node ≥20.19 + Chrome/Chromium for local mode
```

Keys via env: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`, `OPENAI_API_KEY` — or passed inline as `apiKey`. No Docker, no database, no server.

**Entry points**

```typescript
import { Agent } from "@omxyz/lumen";

// one-shot
const result = await Agent.run({
  model: "anthropic/claude-sonnet-4-6",
  browser: { type: "local", headless: true },
  instruction: "Find the price of the top result for 'mechanical keyboard' on Amazon.",
  maxSteps: 15,
});

// streaming
for await (const event of agent.stream({ instruction: "..." })) { /* step_start | action | done */ }
```

Models are `"provider/model-id"`; unrecognized prefixes fall through to `CustomAdapter` (works against Ollama: `{ model: "llama3.2-vision", baseURL: "http://localhost:11434/v1", apiKey: "ollama" }`). Browser is `{ type: "local" }` or Browserbase.

Repo scripts: `build` (tsup), `typecheck`, `lint`, `test`, `test:watch`, `eval`, `docs:dev|build|preview`.

### Evals

**The only repo in this batch with a real, runnable, public web-agent benchmark.**

**Location:** [`evals/webvoyager/`](https://github.com/omxyz/lumen/tree/main/evals/webvoyager)

| File | Role |
|---|---|
| [`run.ts`](https://github.com/omxyz/lumen/blob/main/evals/webvoyager/run.ts) | 790-line runner — dataset loading, date adaptation, three framework drivers, LLM judge, retry logic, reporting |
| `data.jsonl` | **642 tasks** — the full WebVoyager set (`{web_name, id, ques, web}`) |
| `diverse_sample.jsonl` | 30-task curated subset, exactly 2 per site × 15 sites |
| [`browser_use_webvoyager.py`](https://github.com/omxyz/lumen/blob/main/evals/webvoyager/browser_use_webvoyager.py) | Python subprocess bridge for the browser-use baseline (spawned from `.venv/bin/python3`) |
| `results/` | **7 committed result JSONs** with full per-task detail |

**How a run is launched**

```bash
npm run eval                    # = tsx --env-file .env evals/webvoyager/run.ts → 25 tasks, lumen
npm run eval -- 5               # 5 tasks
npm run eval -- 25 stagehand    # same tasks, Stagehand CUA
npm run eval -- 25 browser-use  # same tasks, browser-use (via Python subprocess)

MODEL=google/gemini-2.0-flash npm run eval
SITES=Allrecipes,GitHub npm run eval
DATA_FILE=diverse_sample.jsonl npm run eval
TASKS=GitHub--1,Amazon--0 npm run eval     # rerun specific IDs
```

**Methodology** (all constants in `run.ts`):

- **Sampling:** `sampleStratified()` buckets by `web_name` and draws evenly, shuffled by a **seeded mulberry32 PRNG (seed 42)** — so all three frameworks see the identical task set. Good hygiene.
- `MAX_STEPS = 50`, `TASK_TIMEOUT_MS = 600_000` (10 min), `TRIALS = 3`
- **Judge:** `gemini-2.5-flash` with a structured `{evaluation: "YES"|"NO", reasoning}` schema, fed the question, the agent's reasoning/result text, **and a final screenshot**
- **Date adaptation:** ~200 lines (`adaptDatesInInstruction`, `adaptTimeSensitiveInstruction`) shift WebVoyager's hardcoded 2023/2024 dates forward while preserving relative gaps, because travel sites reject stale dates. Also rewrites "yesterday"/"today" and the `2023-24` season string. A real, rarely-handled problem with a thorough fix.
- **Retry with feedback injection (Reflexion-style):** on failure the judge's reason is appended to the instruction — `[IMPORTANT: A previous attempt at this task failed. The evaluator said: "…". Try a DIFFERENT approach this time.]` — and the task is re-run, up to 3 trials.
- Lumen runs with `siteKB`, `actionVerifier: true`, `checkpointInterval: 5`, `compactionThreshold: 0.6`, and a `ModelVerifier` termination gate.

**Reported results** (README, "WebVoyager Benchmark (preliminary)") — 25 tasks stratified across 15 sites, all on Claude Sonnet 4.6:

| Metric | Lumen | browser-use | Stagehand |
|---|---|---|---|
| Success rate | **25/25 (100%)** | **25/25 (100%)** | 19/25 (76%) |
| Avg steps (all) | 14.4 | 8.8 | 23.1 |
| Avg time (all) | **77.8s** | 109.8s | 207.8s |
| Avg tokens | 104K | N/A | 200K |

Cross-checked against the committed JSONs (all timestamped 2026-03-09):

| Result file | Framework | Total | Passed | Pass rate | Avg steps | Avg tokens | Tasks needing retry |
|---|---|---|---|---|---|---|---|
| `…lumen-…-1773085919685.json` | lumen | 25 | 25 | 100% | 14.4 | 104,091 | **2** |
| `…browser-use-…-1773085921801.json` | browser-use | 25 | 25 | 100% | 8.8 | 0 *(not instrumented)* | **0** |
| `…stagehand-…-1773085921245.json` | stagehand | 25 | 19 | 76% | 23.1 | 199,629 | **9** |
| 4 smaller files (2–5 tasks) | lumen ×3, stagehand ×1 | | | 100% | | | |

Stagehand's 6 failures cluster on Apple (0/2), Booking (0/2), Google Map (1/2), BBC News (1/2).

**Caveats worth carrying into the survey** — the README labels this "preliminary," and that label is doing real work:

1. **This is pass@3-with-feedback, not standard WebVoyager single-pass.** A task counts as passed if any of 3 attempts succeeds, with the judge's critique fed back in between. Published WebVoyager numbers are not directly comparable.
2. **25 of 642 tasks (3.9%).** The full `data.jsonl` is committed but the reported run uses the stratified sample.
3. **100% exceeds published WebVoyager SOTA** (the repo's own references table cites Surfer 2 at 97.1%, Magnitude at 93.9%). Two frameworks hitting a perfect score on a 25-task slice is a signal the slice is easy and/or the judge is lenient, not that both are superhuman.
4. **Judge-only scoring** — Gemini 2.5 Flash as sole arbiter, no human verification pass, no inter-rater check.
5. **browser-use token accounting is broken** (`avgTokens: 0`, the Python bridge's `total_input_tokens()` path silently swallows exceptions), so the token column can't compare all three.
6. The docs say "The default dataset is `evals/webvoyager/data.jsonl` (25 tasks across 15 sites)" — the file actually holds 642 tasks; 25 is the runner's default sample limit.

Separately, [`docs/architecture/comparison.md`](https://github.com/omxyz/lumen/blob/main/docs/architecture/comparison.md) is a source-read comparison (not a benchmark) of Lumen vs Stagehand / browser-use / Skyvern / Magnitude across page understanding, context management, stall detection, safety, and LOC — useful survey material, but self-authored.

### Test Cases

**Framework:** vitest 3.x ([`vitest.config.ts`](https://github.com/omxyz/lumen/blob/main/vitest.config.ts) — `globals: true`, `environment: "node"`, `include: ["tests/**/*.test.ts"]`).

**Verified by running it:** `npm ci && npm test` → **22 test files, 147 tests, all passing in 3.91s.** (The README says "140 tests, ~3.5s" — slightly stale, in the right direction.)

**Layout & categories**

| Dir | Files | Tests | Focus |
|---|---|---|---|
| [`tests/unit/`](https://github.com/omxyz/lumen/tree/main/tests/unit) | 12 | 106 | `repeat-detector` (23), `decoder` (12), `perception-cache` (11), `action-cache` (9), `streaming-monitor` (9), `normalize` (8), `policy` (8), `router` (8), `history` (6), `gate` (5), `state` (5), `history-toolids` (3) |
| [`tests/integration/`](https://github.com/omxyz/lumen/tree/main/tests/integration) | 10 (+2 mock helpers) | 41 | `live-challenges` (18), `loop` (4), `preaction-hook` (3), `options` (3), then 2 each for `child`, `compaction`, `gate`, `policy-integration`, `repeat-detector`, `writestate` |

**Everything is mocked** — `MockBrowserTab` implements the `BrowserTab` interface and records calls; `MockAdapter` queues canned model responses; `CDPTab` is tested against a hand-rolled fake `CDPSession`. **No Chrome is launched and no API key is needed**, which is why the whole suite runs in under 4 seconds and works cleanly in CI. Real-browser verification is pushed out to `examples/` and `evals/`.

**Notable test cases**

- [`tests/integration/live-challenges.test.ts`](https://github.com/omxyz/lumen/blob/main/tests/integration/live-challenges.test.ts) (18 tests) is the most interesting file in the batch — a regression suite written from three bugs found during real E2E runs (the `wikipedia_shannon` and `columbia_tuition` tasks), documented in the file header:
  - **Challenge 1 — text-only model response.** When the model replies with prose and no `tool_use` block, the loop must inject a screenshot action rather than hang with no recorded assistant turn. Tests cover: loop continues and terminates next step, screenshot injection, step count preserved, `maxSteps` still fires after all-empty responses.
  - **Challenge 2 — URL bar emulation over CDP.** CDP `Input` events reach page content, not browser chrome, so the address bar is unreachable; `CDPTab` intercepts `Ctrl+L` → type → `Enter` and converts it into a real `Page.navigate`. 10 tests: scheme prepending, no double-prefixing, `Escape` cancels the mode, `F6` also activates it, a second `Ctrl+L` starts a fresh buffer, modifier keys outside the mode dispatch normally.
  - **Challenge 3 — base64 token overflow.** `wireHistory` holds raw base64 PNGs (300 KB+ each); passing them to the Haiku summarize call caused a **217k-token overflow**. Tests assert `AnthropicAdapter.summarize()` strips base64, that serialized safe history is "orders of magnitude smaller," that only the last 20 messages are summarized, and that non-screenshot messages pass through unmodified.
- `tests/unit/repeat-detector.test.ts` (23 tests) — the largest unit file, split into `RepeatDetector`, category detection, **URL stall detection**, and `nudgeMessage` describe blocks.
- `tests/unit/decoder.test.ts` — `fromAnthropic` / `fromGoogle` / `fromGeneric`, i.e. coordinate-format normalization per provider, the exact place multi-provider vision agents silently break.
- `tests/integration/repeat-detector.test.ts` — "reaches maxSteps if agent never self-corrects" (the slowest test at ~2s, since it drives 10 real loop steps against mocks).

**CI setup:** [`.github/workflows/`](https://github.com/omxyz/lumen/tree/main/.github/workflows), three workflows:

1. **`ci.yml`** — on PR **and** push to `main`, **Node 20 and 22 matrix**: `npm ci` → `npm run build` → `npm run typecheck` → `npm test`. The only repo in this batch that gates PRs on tests.
2. **`release.yml`** — on `v*` tags: build → **test** → `npm publish --access public --provenance` (npm provenance attestation, `id-token: write`).
3. **`deploy-docs.yml`** — VitePress build → GitHub Pages.

Note `.gitignore` excludes compiled `.js`/`.d.ts` artifacts from `tests/`, `evals/`, and `examples/` — everything runs through `tsx`/`vitest` from source.

---

## Cross-Repo Observations

**1. Only one of five evaluates the agent it ships.** Lumen is alone in running a public web-agent benchmark with committed results and a reproducible runner. Steel evaluates its scrape pipeline (not an agent — reasonably, since it isn't one). Tarsier measures snapshot consistency and latency, not task success. Bytebot and vimGPT publish nothing. For a survey, this means **eval maturity in this segment is essentially binary**, and it does not track adoption.

**2. Stars are anti-correlated with verification.** Bytebot (11,088 ⭐) has zero tests and zero evals; vimGPT (2,648 ⭐) has zero of both and no CI at all; Lumen (56 ⭐) has 147 passing tests, a PR-gating CI matrix, and a benchmark harness. Steel (7,495 ⭐) sits in between: real tests that CI never runs. Adoption in this space is driven by demo quality and deployment ergonomics, not by demonstrated reliability.

**3. Tests exist but don't run — the recurring failure mode.** Three of five repos have a gap between declared and executed testing:
   - **Steel:** 65 real vitest tests + a purpose-built invariant harness, and *no workflow invokes them*. The eval README even says "use in CI" for the heavy lane.
   - **Tarsier:** the performance-regression suite is explicitly `skipif(GITHUB_ACTIONS)`, so latency budgets never gate a PR (its functional pytest suite *does* run, with live OCR credentials).
   - **Bytebot:** full jest configuration, `@nestjs/testing` + `supertest` installed, five test scripts declared — and zero test files. `npm run test:e2e` points at a `test/jest-e2e.json` that doesn't exist.

   When surveying, "has tests" must be checked against "CI runs tests"; the two diverge often here.

**4. Frozen-fixture / offline determinism is the shared design pattern.** Every repo that tests seriously avoids the live web:
   - Steel gzips 6 real pages into `fixtures/` and **stubs `fetch` to throw** so a network call during extraction fails the test as a proxy bypass
   - Tarsier snapshots 278 bananalyzer **MHTML** pages precisely because "these sites will not change over time"
   - Lumen mocks the browser and model entirely (`MockBrowserTab`, `MockAdapter`, fake `CDPSession`) — 147 tests in 3.9s with no Chrome and no API key
   
   The consensus: **push live-web verification into a separate, manually-triggered eval lane; keep the test lane hermetic.** Lumen's split (mocked `tests/` gate PRs, `evals/` run by hand) is the cleanest expression.

**5. Two-tier eval design (Steel and Lumen, independently).** Both separate a cheap deterministic gate from an expensive on-demand benchmark. Steel: frozen fixtures + label-free invariants in CI, LLM-judge competitive benchmark by hand (and unpublished). Lumen: mocked unit/integration in CI, WebVoyager with an LLM judge by hand. Steel's **label-free invariants** are the more transferable idea — properties that must hold for *any* output (no script leakage, no relative links, no secret leakage, balanced fences) scale to a growing corpus without new labels, and its `invariants.test.ts` even meta-tests that each invariant catches its own failure mode.

**6. LLM-as-judge is now the default scoring method, with known softness.** Lumen uses Gemini 2.5 Flash with screenshot + reasoning; Steel's unpublished benchmark also uses an LLM judge. Neither has a human-verification or inter-rater pass. Lumen's 25/25 for two of three frameworks is the visible symptom — on a small slice with a lenient judge and 3 feedback-injected retries, ceilings get hit fast. **Any survey table quoting these numbers should annotate trial count, judge model, subset size, and whether feedback was injected on retry**; otherwise they aren't comparable to published WebVoyager results.

**7. Marketing claims outrunning published evidence — verify before citing.** Two instances found:
   - Tarsier's README: "unimodal GPT-4 + Tarsier-Text beats GPT-4V + Tarsier-Screenshot by 10-20%" on *internal* benchmarks — no dataset, harness, or numbers published.
   - vimGPT's README links VisualWebArena "(page 9)" under "Shoutouts." Verified against the full paper: vimGPT appears only in **footnote 3** as related work — "GPT-4V-ACT and vimGPT propose similar interfaces" — in a sentence that goes on to call such projects "proof-of-concept demos." **No score is reported for vimGPT.**

**8. The Set-of-Marks vs pure-vision split is visible across the batch.** vimGPT (2023) and Tarsier (2023–24) both solve grounding by *annotating the page* — Vimium hint labels and `[@3]`-style tags respectively, so a text-or-weak-vision model can name a target. Lumen (2026) sends raw screenshots and has the model emit pixel coordinates, with `ActionDecoder` normalizing provider formats. That tracks model capability improving to the point where the annotation layer became optional: Tarsier's own README argues text-tagging beat screenshots by 10–20% *for GPT-4-era models*, a claim Lumen's architecture implicitly treats as expired.

**9. Deployment shape maps cleanly onto scope.** Steel and Bytebot are infrastructure and ship Docker + compose + Helm + 1-click cloud buttons (Bytebot needs a privileged container, `shm_size: 2g`, and Postgres). Tarsier and Lumen are libraries and ship a `pip install` / `npm install` with no server. vimGPT ships a `requirements.txt` and a shell script that curls a zip. **Only Bytebot requires a database**, and only Bytebot and Steel require Docker for a realistic deployment.

**10. Archival and dormancy risk.** Bytebot is **archived read-only** (last commit 2025-09-11) despite 11k stars — worth flagging in any recommendation. Tarsier (2024-09-30) and vimGPT (2024-09-25) are ~2 years dormant with era-pinned dependencies. Only Steel (2026-07-20) and Lumen (2026-03-29) are actively maintained. Three of five repos in this "infrastructure" batch are effectively frozen.
