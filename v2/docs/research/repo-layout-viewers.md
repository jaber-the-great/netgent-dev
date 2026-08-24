# Where run-viewers and report generators live — a source survey

*Survey date: 2026-08-24. All findings below were read from source in shallow clones of the
named repositories at the commits cited; paths are repo-relative. Anything I could not read
directly is marked **unverified**.*

## Question

NetGent v2 has one orphan top-level module, `v2/src/netgent/trajectory.py` (89 lines). It loads a
`schema.records.RunRecord` and renders it two ways: `render_text()` (a timeline) and
`render_html()` (a self-contained page, screenshots inlined via the `screenshot` field). It
imports **only** `netgent.schema.records` — no Playwright, no LLM SDK. Its consumers today:

- `src/netgent/cli/trajectory_command.py:14` — a function-local import inside the Typer command.
- `tests/unit/test_trajectory.py:4` — imports `load_record, render_html, render_text` directly.
- `tests/integration/test_executor_e2e.py:88` — imports `load_record, render_html` directly.
- `src/netgent/cli/run.py:64` — only prints the hint string `netgent trajectory …`.

Where should this live: `core/`, `cli/`, a new `report/`, or somewhere else? And should the
future exploration-trajectory viewer (for the agent's `trajectory.json`, written at
`agent/explore_agent/browser_agent.py:113`) sit beside it?

## Per-project findings

### 1. browser-use/browser-use — `9a2db2d` (2026-08-24)

**Verified.** The history model and its renderer are *siblings inside the agent package*:

- `browser_use/agent/views.py` — `AgentHistoryList` (`:595`), a pydantic model with
  `save_to_file` (`:627`), `load_from_file` (`:695`), `urls()` (`:769`), `screenshots()` (`:788`).
- `browser_use/agent/gif.py` — `create_history_gif(task, history, output_path='agent_history.gif', …)`.
  It imports `AgentHistoryList` from `agent/views`, `PLACEHOLDER_4PX_SCREENSHOT` from
  `browser/views`, and `CONFIG` from `browser_use.config`; PIL is `TYPE_CHECKING`-only and
  imported lazily at call time.

Who depends on it: only `browser_use/beta/service.py:6622` (`_generate_gif_if_requested`), with a
**function-local** import at `:6629`. In `browser_use/agent/service.py:42` the import is
commented out. The renderer is *not* re-exported: `browser_use/__init__.py:83` lists
`AgentHistoryList` in its lazy-export map, but not `create_history_gif`.

**No HTML/report generation exists at this commit.** `grep -rln '<!DOCTYPE html|render_html|html_report' browser_use/`
returns zero. The rich run viewer is the hosted Cloud UI, fed by `browser_use/agent/cloud_events.py`.
The `eval/` directory that older releases carried is absent from the tree — **unverified** whether
it was removed or renamed; only its absence at HEAD is verified.

CLI: `browser_use/cli.py` is 464 lines and imports nothing from `agent/gif.py`; its only
first-party imports are `init_cmd` and `skills.install`. It is an interactive TUI, not a viewer.

Tests: `tests/ci/browser/test_output_paths.py:178` parametrizes the `generate_gif` *Agent option*
and asserts on files on disk. **No test imports `gif.py` directly.**

"Core"-like modules: there is **no `core/` package**. The foundation is five flat top-level
modules — `config.py` (525 lines), `exceptions.py` (5), `logging_config.py` (328),
`observability.py` (204), `utils.py` (870) — plus a two-file `browser_use/screenshots/` package
(`service.py`, a `ScreenshotService` that writes step screenshots to disk).

### 2. Skyvern-AI/skyvern — `10fd44b`, v1.0.51 (2026-08-24)

**Verified.** Skyvern splits *capture* (Python) from *viewing* (React) completely.

- Capture: `skyvern/forge/sdk/artifact/` — `manager.py`, `models.py`, `storage/{base,local,s3,gcs,azure,factory}.py`,
  plus `storage/run_recording_clips.py` for video. `models.py` enumerates artifact kinds:
  `RECORDING` (`:11`), `SCREENSHOT_LLM|_ACTION|_FINAL|_PROXY|_PRE_SUBMIT` (`:27–31`),
  `HTML_SCRAPE|_ACTION` (`:53–56`), `TRACE` (`:59`). **Storage only — no rendering anywhere in it.**
- `skyvern/forge/sdk/trace/{base,lmnr}.py` is Laminar telemetry, not a local viewer.
- Viewing: `skyvern-frontend/src/routes/workflows/workflowRun/` — `ActionCard.tsx`,
  `ActionCardMinimal.tsx`, `ThoughtCard.tsx`, `ObserverThoughtScreenshot.tsx`, `BlockCard.tsx`,
  `RunCard.tsx`, `ResizableTimelineSplit.tsx`. This is the *same shape* as NetGent's
  `render_html` — one card per step with a screenshot — implemented as a web app instead.
- Evaluation reports: `evaluation/` is a **top-level directory outside the shipped package**, with
  `evaluation/core/utils.py` (a `SkyvernClient`), `evaluation/script/create_webvoyager_evaluation_result.py`
  (a Typer script emitting CSV/markdown), and ~15 committed markdown tables at
  `evaluation/results/webvoyager-*.md`.

`forge/sdk/core/` contains: `async_http_client.py`, `aiohttp_helper.py`, `asyncio_helper.py`,
`curl_converter.py`, `security.py`, `rate_limiter.py`, `retry.py`, `hashing.py`,
`http_request_authorization.py`, `skyvern_context.py`, `event_source_stream.py`, `permissions/`.
Pure cross-cutting infra — **zero rendering**.

Notably, Skyvern has **five different `core/` directories** meaning different things:
`skyvern/core/` (only `script_generations/` — the workflow-run → Python-script compiler; "core" as
*core domain transform*), `skyvern/forge/sdk/core/` (infra), `skyvern/cli/core/` (CLI-local:
`artifacts.py`, `action_log.py`, `trajectory_store.py`, `result.py`), `skyvern/client/core/`
(generated Fern SDK boilerplate), `evaluation/core/` (eval helpers).

### 3. browserbase/stagehand — `5b5ce6a` (2026-08-24)

**Verified.** Stagehand v3 is a pnpm monorepo:
`packages/{docs,evals,extension,integrations,protocol,sdk-go,sdk-python,sdk-ts}`. The
`lib/logger.ts` from the older layout no longer exists; loggers now live at
`packages/extension/logger.ts` (runtime) and `packages/evals/logger.ts` (eval runs).

All reporting lives in `packages/evals/`, a first-class workspace package:

- `packages/evals/lib/braintrust-report.ts` — the data layer (`collectExperimentMetrics`,
  `fetchManyExperimentData`, `benchCaseDiffs`, `summarizeBenchAgentConfigs`).
- `packages/evals/scripts/render-braintrust-core-report.ts` — **1,478 lines**, writes a
  self-contained HTML comparison report (default `/tmp/stagehand-evals-braintrust-report.html`,
  with an `openAfter` flag).
- `packages/evals/summary.ts` — `generateSummary(results, experimentName, …)`.
- `packages/evals/tui/` — the terminal view: `results.ts` (`printResultsTable`), `progress.ts`,
  `format.ts`, `preview.ts`, `repl.ts`, `commandTree.ts`, `banner.ts`.

**Tests import the renderers directly**: `packages/evals/tests/lib/braintrust-report.test.ts`,
`tests/tui/results.test.ts`, `tests/summary.test.ts`. The shipped SDK (`packages/sdk-ts/src/`)
contains no report code at all.

`core/` here means the *eval domain*: `packages/evals/core/{contracts,fixtures,runtime,targets,tasks,tools}`.
The other one, `packages/integrations/core/`, is a generated client package.

### 4. omxyz/lumen — `b1ad26a` (2026-03-29)

**Verified.** A flat `src/`: `agent.ts`, `session.ts`, `types.ts`, `errors.ts`, `logger.ts`, plus
`browser/`, `loop/`, `memory/`, `model/`. `LumenLogger` is at `src/logger.ts:39` — a 124-line
single-class module with a `static readonly NOOP` (`:123`), level from `LUMEN_LOG`, consumed by
`agent.ts` and `session.ts`. Semantic history is `src/loop/history.ts` (`class HistoryManager`,
the file's only export); serialization is `src/session.ts:180`, `serialize(): SerializedHistory`
delegating to `this.history.toJSON(...)`.

**There is no viewer.** `grep -rln '<!doctype|viewer'` over `src/`, `evals/`, and
`docs/architecture/` returns nothing. `evals/webvoyager/run.ts` dumps raw JSON into
`evals/webvoyager/results/*.json` and stops there. No `core/` directory.

### 5. magnitudedev/browser-agent (Magnitude) — `f1b587c` (2026-02-08)

**Verified — the clearest precedent for NetGent.** The report viewer lives *in evals, beside the runner*:

- `evals/webvoyager/viewer.ts` (207 lines) — a Bun HTTP server on port 8000 that reads
  `./results` and `data/patchedTasks.jsonl` and serves the page (`Bun.file("./viewer.html").text()`, `:59`).
- `evals/webvoyager/viewer.html` (692 lines) — the static single-page UI.
- Siblings in the same directory: `wv.ts`, `wv-runner.ts`, `data/`, `results/`.

`evals/` is a top-level directory *outside* `packages/` — not published, not importable by the SDK.

The shipped packages show two more relevant conventions:
- `packages/magnitude-test/src/renderer/{index.ts,debugRenderer.ts}` — an explicit `renderer/`
  subpackage defining a `TestRenderer` interface, kept separate from `src/runner/`; the concrete
  terminal UI is a further `src/term-app/{uiRenderer,termAppRenderer,drawingUtils,uiState}.ts`.
- `packages/magnitude-core/src/memory/rendering/{index,renderJsonParts,renderXmlParts}.ts` —
  a `rendering/` folder nested *inside the thing it renders*, with a colocated
  `renderJsonParts.test.ts`. (This renders memory for the LLM prompt, not for humans.)

No `core/` directory; `packages/magnitude-core/src/common/{actions,events,failure,retry,util}.ts`
plus root-level `logger.ts`/`types.ts`/`util.ts` play that role.

### 6. microsoft/playwright — `1c56da0` (2026-08-24)

**Verified.** Playwright is the fullest expression of the split, in *four* layers:

| Layer | Path |
|---|---|
| Trace data model | `packages/trace/src/{trace.ts,snapshot.ts,har.ts}` — standalone package, `DEPS.list` is `[*]` (depends on nothing) |
| Recording | `packages/playwright-core/src/server/trace/recorder/{tracing.ts,snapshotter.ts,snapshotterInjected.ts}` |
| Serving glue | `packages/playwright-core/src/server/trace/viewer/traceViewer.ts` — `startTraceViewerServer` (`:90`), `runTraceViewerApp` (`:196`), `runTraceInBrowser` (`:206`) |
| Viewer UI | `packages/trace-viewer/` — a Vite app (`index.html`, `uiMode.html`, `snapshot.html`, `src/ui/`, `src/sw/`); its `src/DEPS.list` permits only `@web/**` and `ui/` |

The CLI is a pure dispatcher: `packages/playwright-core/src/cli/program.ts:208` declares
`.command('show-trace [trace]')` and its action does nothing but pick between `runTraceInBrowser`
and `runTraceViewerApp`. No viewer logic in the CLI.

The same layering repeats for test reports:
- `packages/playwright/src/reporters/` — `base.ts` (721), `html.ts` (848), `blob`, `json`, `junit`,
  `github`, `dot`, `line`, `list`, `merge`, `multiplexer`, `teleEmitter`, `reporterV2`,
  `internalReporter`, `chromeTrace`. A **first-class named subpackage** with its own `DEPS.list`
  restricting it to `@isomorphic/**`, `@utils/**`, `../common/`, `../util.ts` and five npm packages.
- `packages/html-reporter/` — the report UI as a separate Vite package, with component tests
  colocated (`chip.spec.ts`, `headerView.spec.ts`, `testCaseView.spec.ts`, `testFileView.spec.ts`).
- CLI: `packages/playwright/src/program.ts:101` `show-report` → `showReport` imported from
  `./cli/reportActions` (`:27`), which wraps `reporters/html.ts`.

Behaviour tests live outside both: `tests/playwright-test/reporter-html.spec.ts` et al.

**No `core/` anywhere in Playwright.** The foundation packages are `packages/utils/` (crypto, env,
fileUtils, httpServer, debugLogger, network, processLauncher, zipFile, image_tools) and
`packages/isomorphic/` (pure shared logic), plus `packages/protocol/` and `packages/web/`.

### 7. pytest and pytest-html

**pytest — `c99f595` (2026-08-24).** `src/_pytest/` is the private implementation; `src/pytest/`
is a thin public façade. The renderers are **flat sibling modules at the same level as `runner.py`
and `main.py`**:
- `src/_pytest/reports.py` (694 lines) — the report *data model* (`TestReport`, `CollectReport`).
- `src/_pytest/terminal.py` (1,805 lines) — the human renderer; its docstring is literally
  "Terminal reporting of the full testing process." It is a built-in plugin, registered by name
  at `src/_pytest/config/__init__.py:325`.
- `src/_pytest/junitxml.py` (707) — the XML report. `src/_pytest/pastebin.py` — the paste report.
- `src/_pytest/_io/` — output primitives: `terminalwriter.py` (258), `pprint.py`, `saferepr.py`, `wcwidth.py`.

No `core/`. Model and renderer are separate modules, one level, no subpackage.

**pytest-html — `dd163c5` (2026-08-10).** An entirely separate distribution whose package is flat
and whose names map 1:1 onto NetGent's problem:
- `report_data.py` (155) — the model.
- `basereport.py` (377) — shared render logic + Jinja template loading.
- `report.py` (41) — linked-assets variant.
- **`selfcontained_report.py` (39)** — base64-inlines CSS and media into one file. Exactly
  NetGent's `render_html`.
- `plugin.py` (140) — the pytest-hook wiring (the "CLI" seam); it picks `SelfContainedReport` at `:111`.
- `resources/index.jinja2`, `resources/style.css`, `scripts/*.js`.

Tests (`testing/test_unit.py`, `test_integration.py`) drive the plugin through `pytester` rather
than importing the renderer classes.

### 8. What `core/` actually is, across these repos

I searched every clone for a directory named `core` (excluding `node_modules`/`.git`):

- **browser-use: none. lumen: none. magnitude: none. playwright: none. pytest: none. pytest-html: none.**
- **skyvern: five**, meaning three different things (infra, core domain transform, generated SDK boilerplate).
- **stagehand: two**, both meaning "the domain of this package" (`evals/core`, `integrations/core`).

Where a foundation layer exists it is called something else — `_pytest/_io` + flat modules
(pytest), `packages/utils` + `packages/isomorphic` (Playwright), `src/common` + root modules
(Magnitude), flat `config.py`/`utils.py`/`logging_config.py` (browser-use), flat
`logger.ts`/`errors.ts`/`types.ts` (lumen). Its contents are consistently: **config, errors,
logging, retry/async helpers, filesystem/crypto/network utilities, context propagation.**

**Not one project puts human-facing rendering in its foundation layer.** Skyvern's
`forge/sdk/core/` has none; Playwright's `packages/utils` has none (its only renderer-named file,
`isomorphic/ariaSnapshotRenderer.ts`, serializes a data format, not a report); pytest's `_io/` has
only text primitives, with `terminal.py` sitting outside it.

## Patterns

| Project | Viewer / report location | Foundation package | CLI relationship | Tests import it directly? |
|---|---|---|---|---|
| browser-use | `browser_use/agent/gif.py` (beside `agent/views.py`) | none — flat `config.py`, `exceptions.py`, `logging_config.py`, `utils.py` | CLI ignores it; agent service imports it lazily | No (driven via `Agent(generate_gif=…)`) |
| skyvern | React app `skyvern-frontend/src/routes/workflows/workflowRun/`; eval markdown in top-level `evaluation/` | `forge/sdk/core/` = http/retry/security/context | CLI has its own `cli/core/` (artifacts, action_log, trajectory_store) | n/a (frontend `.test.tsx` colocated) |
| stagehand | `packages/evals/{lib/braintrust-report.ts, scripts/render-…-report.ts, summary.ts, tui/}` | `packages/evals/core` = eval domain, not infra | eval `cli.ts` is inside the same package | **Yes** — `tests/lib/braintrust-report.test.ts`, `tests/tui/results.test.ts` |
| lumen | none | none — flat `logger.ts`/`errors.ts`/`types.ts` | n/a | n/a |
| magnitude | `evals/webvoyager/viewer.{ts,html}`; `magnitude-test/src/renderer/` + `src/term-app/` | `magnitude-core/src/common/` | `renderer/` is imported by `runner/`, selected in `cli.ts` | Colocated (`renderJsonParts.test.ts`) |
| playwright | `packages/trace-viewer/`, `packages/html-reporter/`, `packages/playwright/src/reporters/` | `packages/utils`, `packages/isomorphic` | CLI is a one-line dispatcher (`show-trace`, `show-report`) | Component specs inside the package; behaviour specs in `tests/` |
| pytest | `_pytest/terminal.py`, `_pytest/junitxml.py` (flat siblings of `runner.py`) | none — `_pytest/_io/` for primitives | renderer is a named built-in plugin | Via `pytester` |
| pytest-html | `pytest_html/{basereport,report,selfcontained_report}.py` | none | `plugin.py` is the seam and picks the variant | Via `pytester` |

Three stable rules fall out:

1. **The renderer is never in the foundation/`core` layer.** 0 of 8.
2. **The renderer is never *inside* the CLI.** The CLI declares the command and dispatches;
   the rendering code is a library the CLI calls (Playwright is the extreme: `show-trace`'s action
   body is four lines). Skyvern is the only partial exception, and there the CLI-local code is
   artifact *plumbing*, not rendering.
3. **The renderer lives next to the data it renders** — `gif.py` beside `views.py`,
   `reporters/` beside the runner, `terminal.py` beside `reports.py`, `viewer.ts` beside `wv.ts`.
   Once there are ≥3 output formats or a real UI, it graduates to a named subpackage
   (`reporters/`, `renderer/`, `trace-viewer/`) — but not before.

## Recommendation for NetGent

**Move `trajectory.py` into a new `netgent/report/` package. Do not put it in `core/`, and do not
fold it into `cli/`.**

Concretely:

```
src/netgent/report/__init__.py      # re-export load_record, render_text, render_html, write_html
src/netgent/report/run.py           # today's trajectory.py — RunRecord → text / self-contained HTML
src/netgent/report/exploration.py   # later: AgentTrajectory → text / HTML
```

Reasoning, mapped to the evidence:

- **Not `core/`.** Zero of eight projects put rendering in their foundation layer, and NetGent's
  own `core/__init__.py` states its contract: "imports nothing but stdlib. No Playwright, no LLM
  SDKs… the pydantic models live in netgent.schema." `trajectory.py` imports
  `schema.records` — putting it in `core/` would immediately invert NetGent's declared
  `core ← browser ← executor ← agent` direction and make `tests/unit/test_import_boundaries.py`
  a weaker statement than it is now.
- **Not `cli/`.** Two tests import the renderer directly (`tests/unit/test_trajectory.py:4`,
  `tests/integration/test_executor_e2e.py:88`), and the integration test uses it as a *library*
  to dump a page after a real run. CLAUDE.md already scopes `cli/` as "thin Typer wrappers", and
  the survey backs that: every project keeps the CLI a dispatcher. Burying an HTML generator
  behind a Typer callback would make it un-importable from evals and notebooks for no gain.
- **Not `schema/`.** The strongest counter-proposal, on the pytest precedent that `reports.py`
  (model) and `terminal.py` (renderer) are siblings. But NetGent's `schema/` is the *artifact
  contract* — the thing `netgent schema` emits as JSON Schema and external consumers validate
  against. Adding an HTML-emitting module to it muddies that boundary; Playwright makes the same
  choice by keeping `packages/trace` (format) free of `packages/trace-viewer` (UI).
- **Not `evals/`,** despite Magnitude and Stagehand doing exactly that. Their viewers render
  *benchmark* results; NetGent's renders a *product* run reachable from `netgent run --trajectory`.
  NetGent's `evals/` already has its own human-facing renderers (`evals/observation.py:130 table()`,
  `evals/matrix.py:54 build()`) and they should stay there — that split matches Stagehand's
  (`evals/tui/` for eval output, nothing in the SDK) rather than contradicting it.
- **Why a package rather than leaving a flat `netgent/report.py`.** A flat module would be
  defensible today (pytest and pytest-html both stay flat at ~1,000 lines). But NetGent is
  about to have a *second* record type to render — the exploration `trajectory.json` from
  `agent/explore_agent/browser_agent.py:113` — and probably a third (validation diffs). Two
  renderers of two artifacts is precisely the point where Playwright reaches for `reporters/`
  and Magnitude for `renderer/`. Making it a package now costs one `__init__.py`.

**Naming.** `report/` over `viewer/`, `render/`, or `trajectory/`. "Viewer" implies an interactive
app (Playwright's `trace-viewer` is a Vite SPA; Magnitude's `viewer.ts` is an HTTP server) —
NetGent emits a static file, so the honest word is *report*, matching `reporters/` (Playwright),
`selfcontained_report.py` (pytest-html), and `render-braintrust-core-report.ts` (Stagehand). Keep
the module name `run.py`, not `trajectory.py`: it renders a `RunRecord`, and "trajectory" is
already overloaded in this repo (the CLI command, the `--trajectory DIR` bundle, and
`AgentTrajectory`). The CLI command name `netgent trajectory` can stay as-is — it names the
artifact bundle, not the module.

**Yes, the exploration-trajectory viewer belongs beside it,** as `report/exploration.py`. Both are
"one artifact → text or self-contained HTML", both are read-only over a pydantic model, and both
want the same CSS and card layout — which is the argument for a shared `report/_html.py` helper
once the second one lands. The precedent is `packages/playwright/src/reporters/`, where `html.ts`,
`json.ts`, `junit.ts`, and `github.ts` all sit together over a common `base.ts` rather than each
living next to its own consumer. Guard it the same way `core/` is guarded: `report/` may import
`schema/`, and nothing else first-party.

One follow-on: `report/` should be added to `FORBIDDEN` in `tests/unit/test_import_boundaries.py`
with `["playwright", "langchain", "langgraph", "langchain_core"]`, which preserves today's
property that `netgent trajectory` works without a browser installed — the stated reason for the
module's existing docstring constraint.

## Verification notes

- Every path, line number, and symbol above was read from a shallow clone made 2026-08-24, except
  where marked. Commits: browser-use `9a2db2d2db42c6f68a871f011b3b25fdcaa71847`; skyvern
  `10fd44bc4e71a5f5203426624636d6bb280fe4c4`; stagehand `5b5ce6ab961e6760f0c751fd4fc9d54834b37ef1`;
  lumen `b1ad26a0784645ac3a97d402db99cd5d17f86334`; magnitude `f1b587c4173d8242bdb551991de54e70c4d2faf3`;
  playwright `1c56da0de3003f3a39280f8e72ef64b63c330004`; pytest `c99f595a896eb84c1dda4f4b85a0929c52011e27`;
  pytest-html `dd163c5408bc76933379aa4b96949a82fdda79c8`.
- **Unverified:** whether browser-use's `eval/` directory (with its report generator) existed in
  earlier releases and was removed. Only its absence at `9a2db2d` was checked; the shallow clone
  has no history to confirm.
- **Unverified:** whether Stagehand's older `lib/logger.ts` was moved or rewritten into
  `packages/extension/logger.ts`. Only the current layout was read.
- **Partially verified:** Skyvern's React viewer was surveyed by file listing plus component names
  (`ActionCard.tsx`, `ThoughtCard.tsx`, `ResizableTimelineSplit.tsx`); I did not read their bodies,
  so "one card per step with a screenshot" is inferred from naming, not from the JSX.
- The lumen clone is at a 2026-03-29 HEAD, ~5 months older than the others; its "no viewer"
  finding may be stale if the project has since added one.
- Line counts are `wc -l` on the cloned files.
