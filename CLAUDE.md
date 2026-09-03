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
Pop-ups are ε-transitions (`noop`): scoped, bounded `Interrupt`s swept by the executor between
atomic steps. Control flow is a bounded regular expression (`control_sequence`, `Branch`,
`Repeat`) — no code in artifacts, ever.

## The pipeline

```
netgent generate "<task>" --url … -p name=sample [--parallel N --rounds R --variation name=value]
   plan (LLM: N variations) → explore ×N (LLM agent, parallel) → verify (LLM judge, advisory)
   → merge (pure code: typed-key alignment of ALL runs → one NFA; typed hints applied only where the
     recordings prove them) → replay (zero-LLM metamorphic check per value set) → triage (pure code →
     typed Episodes) → END if the replay passed on ≥ 2 unseen value sets, else plan_next (ONE LLM
     call → next variations + generalization hints) → another round, up to --rounds (default 3)
netgent run workflow.yaml --param name=value        # deterministic, zero LLM
```

The exit is replay-decided; the judge never grades the artifact. Each round's evidence lives in
`<name>.trajectories/` (`run-k/`, `round-r/{generalized,episodes,next_plan}.json`, `context.json`).

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
| `schema/` | pydantic artifact models: workflow, actions, triggers, control (`Branch`/`Repeat`/`Interrupt`/`Param`), records |
| `browser/` | the Playwright layer, split by role: `pw.py` (the single Playwright/Patchright import, `PATCHED_BROWSER`), `profile.py` (`BrowserProfile`: real Chrome, nothing spoofed), `factory.py` (launch → context → page → CDP, client-hints repair; capture hooks in here), `session.py` (`BrowserSession` facade), `resolution.py` (locator chains), `actions.py` (dispatch), `triggers.py` (state conditions, polling), `dom/` (`models.py`, `observer.py` — snapshot across frames/shadow DOM, `serializer.py` — the observation text the agent reads, `closed_shadow.py` — closed roots over CDP, `scripts/*.js` — the injected walker) |
| `executor/` | control-program interpreter + parameter resolution (static + page-extracted, with guards) |
| `agent/` | the compile-time agents, one package each: `explorer/` (functions + one compiled LangGraph: `graph.py` observe→decide→act nodes, `create_explorer_agent()`/`EXPLORER`, `explore()`; `context.py` the per-run `ExplorerContext`, `memory.py` the cross-run `ExplorerMemory`, `agent.py` the thin `ExplorerAgent` façade, `models.py` the values incl. the M0 locator ladder on `AgentStep`, plus decision/prompt/actions), `planner/` (task → `Plan`; `plan_variations()` the N same-family variations of `--parallel`; `plan_next()` the closed loop's ONE call: `NextRoundPlan` = next variations + scoped sub-tasks + typed `GeneralizationHint`s, normalized in code), `generator/` (`compiler.py` one run → NFA; `merge.py` N runs → one NFA with dispositions, hints applied only where re-derivable, every hint's outcome recorded; `hints.py` the closed hint vocabulary), `verifier/` (LLM judge from page evidence, same layout: `graph.py` gather→judge, `VERIFIER`, `verify()`; `context.py`, `models.py`, `prompt.py`, `agent.py` the `VerifierAgent` façade), `triage.py` (pure code: verdicts + merge trail + replay → typed `Episode`s), `rounds.py` (the `RoundContext` persisted as `context.json`), `replay.py` (the zero-LLM metamorphic check), `store.py` (the trajectory store); `orchestrator.py` chains them (the entry behind `netgent generate`, itself a LangGraph: the single-run graph and the round loop); shared LLM seam in `llm.py` (`scoped()` views give each parallel run its own usage counters) |
| `cli/` | Typer commands: `run`, `generate`, `agent`, `trajectory`, `schema`, `doctor`, and the `eval` group (`dataset`, `observation`, `stress`, `matrix`) |
| `evals/` | the runners behind `netgent eval` — importable functions returning rows/markdown, no `sys.exit`; results land in `v2/evals/results/<eval>/` |
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
`provider:model` strings as `init_chat_model` takes them, `/` also accepted (cheap exploration model:
`anthropic:claude-haiku-4-5-20251001`; Gemini is `google_genai:gemini-…`; `claude-code:sonnet` routes
to the local Claude Code CLI via the sibling `langchain-claude-code` package — subscription-billed,
`uv sync --extra claude-code`); `--headed` to watch a run; `--trajectory DIR` to keep screenshots + records.

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
`agent/llm.py`) and **LangGraph for the browser agent's loop** (`agent/explorer/graph.py`: a
`StateGraph` observe → decide → act with `Command` routing, compiled once at import as `EXPLORER`;
the live session/LLM/memory travel as `Runtime[ExplorerContext]`, never in state — see
`v2/docs/research/langgraph-agent-structure.md`).
Keep LangChain/LangGraph usage inside `agent/`, behind the `LLM` protocol; only `explorer/graph.py` may
import langgraph at module level, and nothing in `netgent.agent.__init__` imports it eagerly.
