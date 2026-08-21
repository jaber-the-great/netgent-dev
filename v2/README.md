# NetGent v2

Compile browser workflows into deterministic, replayable NFAs: an LLM explores a task **once,
at generate time**; every replay is **zero-LLM**. States carry conditions, transitions carry
exactly one atomic action. Read [`docs/OVERVIEW.md`](docs/OVERVIEW.md) first.

## Setup

```sh
cd v2
uv sync --extra generate          # generate/agent need an LLM SDK; run does not
uv run patchright install chromium   # patched Playwright; real Google Chrome is used when installed
uv run ruff check src tests
NETGENT_BROWSER_TESTS=1 uv run pytest -q
```

Put `ANTHROPIC_API_KEY` (or another provider's key) in `v2/.env`. `netgent doctor` checks the setup.

## Generate → run

Workflows are **generated, never hand-written**. `netgent generate` explores the task, synthesizes
one workflow from the explorations, validates it with zero LLM calls, and writes the artifact with a
provenance block ([`docs/discovery-agent.md`](docs/discovery-agent.md)):

```sh
uv run netgent generate "Search Twitch for the channel monstercat, open it, wait ONCE with \
  seconds=10 to watch the stream, then declare done." \
  --url https://www.twitch.tv --out examples/twitch-live.yaml \
  -p channel=monstercat --variation channel=bobross --runs 2 \
  --model anthropic/claude-haiku-4-5-20251001 --trajectory runs/twitch

uv run netgent run examples/twitch-live.yaml --param channel=bobross   # zero LLM
```

- `-p name=sample` declares a parameter; every occurrence of the sample becomes `${name}`.
- `--runs N` explores N times with the defaults (fresh session each); `--variation name=value`
  adds one exploration with an alternate sample. Steps present in only some runs become guarded
  ε-branches (cookie walls); conditions are derived from page evidence shared by all runs
  (`element_visible`, `video_playing`, `text_visible`, `url_matches`).
- `--validate` (default) replays the result once per param set; the artifact records
  `provenance.validated`. An unvalidated artifact is written, printed loudly, and exits 1.

Other commands: `netgent agent` (bare exploration), `netgent trajectory` (render a run record),
`netgent schema`, `netgent eval`, `netgent doctor`.

## Stealth

With Patchright installed the browser spoofs nothing (real Chrome, native UA); the CDP-level
automation leaks are closed at the binary level. Measured 31/31 on bot.sannysoft.com and "Normal"
on browserscan.net bot-detection, headless and headed.

## Layout

`schema/` (pydantic artifact models; no playwright/LLM imports) ← `browser/` (Playwright session,
trigger evaluation) ← `executor/` (control-program interpreter, zero LLM) ← `agent/` (explore,
evidence, synthesis, validation; imports LLM SDKs lazily). `tests/test_import_boundaries.py`
enforces the direction. `examples/` are generated artifacts.
