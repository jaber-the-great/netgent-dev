# NetGent — repo guide for Claude Code

NetGent (UCSB SNL) compiles natural-language browser workflows into deterministic, replayable
automata. Its product is realistic **network-traffic datasets**: an LLM is used only at
compile time; every replay is **zero-LLM**.

- `v1/` — the original implementation (frozen; reference only).
- `v2/` — the rewrite. **All active work happens here.** Read `v2/docs/OVERVIEW.md` first.

## The v2 formalism (normative — from Manni)

An NFA: **states carry conditions** (triggers: `url_matches`, `selector_visible`,
`selector_hidden`, `title_contains`, …), **transitions carry exactly one atomic action** from a
closed set (goto, click, fill, press, select, scroll, upload_file, go_back, wait, hover, noop).
Pop-ups are ε-transitions (`noop`). Control flow is a bounded regular expression
(`control_sequence`, `Branch`, `Repeat`) — no code in artifacts, ever.

## The pipeline

```
netgent generate "<task>" --url … -p name=sample [--runs N --variation name=value]
   explore (LLM agent, N runs)  →  synthesize (pure code: one NFA)  →  validate (zero-LLM replay)
netgent run workflow.yaml --param name=value        # deterministic, zero LLM
```

### Hard rules

1. **Workflows are generated, never hand-written.** To test a site, run `generate`; only edit
   the compiler/agent when debugging. `v2/examples/*.yaml` are compiler output.
2. **Zero LLM at run time.** Nothing under `executor/` or `browser/` may call a model.
3. **Import boundaries** (enforced by `tests/unit/test_import_boundaries.py`):
   `schema/` (no playwright/langchain) ← `browser/` (no langchain) ← `executor/` (no langchain)
   ← `agent/` (may import LangChain, lazily).
4. **Secrets:** `v2/.env` is gitignored and must stay so. Never print or commit keys.
5. **Shared repos:** anything pushed under Eugene's name to a shared repo (e.g. `SNL-UCSB/scrums`)
   is shown verbatim and approved first. Pushing to Eugene's own feature branch is fine.

## Layout (`v2/src/netgent/`)

| Package | Role |
|---|---|
| `schema/` | pydantic artifact models: workflow, actions, triggers, control (`Branch`/`Repeat`/`Param`), records |
| `browser/` | Playwright session (Patchright when installed), stealth profile, DOM snapshot across frames/shadow DOM, trigger evaluation, action dispatch |
| `executor/` | control-program interpreter + parameter resolution (static + page-extracted, with guards) |
| `agent/` | the compile-time agents, one package each: `explore_agent/` (LangGraph observe→decide→act loop, observation, sweep), `workflow_generator_agent/` (trajectories → NFA), `validation_agent/` (zero-LLM replay check); `orchestrator.py` chains them (the entry behind `netgent generate`, itself a LangGraph); shared LLM seam in `llm.py` |
| `cli/` | Typer commands: `run`, `generate`, `agent`, `trajectory`, `schema`, `doctor`, and the `eval` sub-app (`eval dataset` replay benchmark, `eval observation` DOM/AX/hybrid A/B, `eval som` Set-of-Marks check, `eval stress {sweep,challenge}`, `eval matrix`) |
| `evals/` | the runners behind `netgent eval` (importable functions, no `sys.exit`); `v2/evals/*.py` are shims |
| `core/` | settings (pydantic-settings, `.env`), errors, logger |

## Dev commands

```bash
cd v2
uv sync --extra generate && uv run patchright install chromium
uv run ruff check src tests
NETGENT_BROWSER_TESTS=1 uv run pytest -q        # full suite incl. real-browser tests
uv run netgent doctor
```

Conventions: `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` (no aliases); models are
`provider/model` strings (cheap exploration model: `anthropic/claude-haiku-4-5-20251001`);
`--headed` to watch a run; `--trajectory DIR` to keep screenshots + records.

## Branches

- `eugene/v2-scaffold` — main v2 line.
- `eugene/v2-discovery` — explore→synthesize→validate discovery agent (review before merging).

## Skills (LangChain / LangGraph / Deep Agents)

The official LangChain skills are installed in `.claude/skills/` (gitignored — `.claude/` is
ignored). Use them whenever work touches the LLM seam (`agent/llm.py`), the planned
planner/discovery/validation agents, LangGraph orchestration, or evals:

- `langchain-fundamentals`, `langchain-middleware`, `langchain-dependencies`, `langchain-rag`
- `langgraph-fundamentals`, `langgraph-persistence`, `langgraph-human-in-the-loop`, `langgraph-cli`
- `deep-agents-core`, `deep-agents-memory`, `deep-agents-orchestration`, `managed-deep-agents`, `swarm`
- `eval-engineering`, `langsmith-online-eval-engineering`, `ecosystem-primer`, plus `*-quickstart`

Reinstall on a fresh clone: `npx skills add langchain-ai/langchain-skills --skill '*' --yes`
(or clone the repo and run `./install.sh --yes <this-dir>`).

NetGent uses LangChain for the model seam (`init_chat_model` + `with_structured_output` in
`agent/llm.py`) and **LangGraph for the browser agent's loop** (`agent/graph.py`: a `StateGraph`
observe → decide → act with `Command` routing; `netgent agent --graph` prints it as Mermaid).
Keep LangChain/LangGraph usage inside `agent/`, imported lazily, behind the `LLM` protocol.
