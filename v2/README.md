# NetGent v2

Agent-based automation of network application workflows: an LLM agent explores a task
once (`netgent generate`), NetGent compiles the trajectory into a deterministic NFA
workflow, and `netgent run` replays it with zero LLM calls.

## Quickstart

```bash
cd v2
uv sync --extra generate        # deps, incl. patchright (a patched Playwright)
uv run patchright install chromium   # fallback browser; real Google Chrome is used when installed
cp .env.example .env            # add your LLM key (e.g. ANTHROPIC_API_KEY)

uv run netgent doctor
uv run netgent generate "Search YouTube for cat videos and play the first result" \
  --url https://www.youtube.com -p "query=cat videos" --out cat-video.yaml
uv run netgent run cat-video.yaml --param "query=dog videos"
```

Stealth: with Patchright installed the browser spoofs nothing (real Chrome, native UA);
the CDP-level automation leaks are closed at the binary level. Measured 31/31 on
bot.sannysoft.com and "Normal" on browserscan.net bot-detection, headless and headed.

Tests: `NETGENT_BROWSER_TESTS=1 uv run pytest -q` · Lint: `uv run ruff check src tests`
