# The Discovery agent: explore → synthesize → validate

**Status:** implemented on `eugene/v2-discovery` (2026-08-21). Code: `agent/evidence.py`,
`agent/synthesis.py`, `agent/validate.py`, `cli/generate.py`. Background:
[`research/long-horizon-agents.md`](research/long-horizon-agents.md) §3 (Explore → Consolidate)
and §4 (Branch / ε-transitions).

## Why record-and-compile was not enough

`netgent generate` used to be record-and-compile: one goal-directed agent run, and the one
successful path became a linear workflow whose states were recognized by URL alone. Observed
failure modes:

- a cookie dialog appeared in one Twitch exploration and not another, so one artifact had a
  "Proceed" click and another didn't — that is a **conditional branch**, not a fixed step;
- a "watching" state verified only by URL: a paused or black player passes;
- incidental steps (click a field, then fill it; survey scrolls) were baked in;
- failed steps were dropped rather than informing the artifact.

## The mechanism

```
             ┌──────────── explore (LLM) ────────────┐   ┌── synthesize (code) ──┐   ┌── validate (0 LLM) ──┐
 task ──►  run 1 (defaults)  run 2 (defaults)  run 3 (variation) ──► ONE workflow ──► replay × (1 + variations)
           each run records: action + page evidence per step           core path        pass → validated: true
                                                                       ε-branches       fail → relax once, retry
                                                                       evidence guards  still fail → validated: false (loud)
```

### 1. Evidence capture (`agent/evidence.py`)

After every dispatched action the agent records a `PageEvidence` on the `AgentStep`: URL,
title, a bounded sample of salient visible text (headings/buttons/links/labels, ≤40 items),
whether a `<video>` is present and whether its `currentTime` advanced across a short gap, and
the visibility of a few durable locators. Right before the *next* action is dispatched the
previous step's evidence is refreshed — the page has had the LLM's think time to settle — and
the next action's target locator is probed. So each state's evidence includes "the element the
next edge needs was visible here". Cheap, deterministic, best-effort (never fails a run), and
agent-only: the schema and executor never see it.

### 2. Multiple explorations (`netgent generate --runs N --variation name=value`)

`--runs N` explores the task N times in fresh sessions with the default samples; each
`--variation name=value` adds one exploration with an alternate sample for a declared
`--param` (the task text gets the value substituted). Every trajectory is persisted under
`--trajectory`. Runs that don't reach `done` are excluded from synthesis and counted in provenance.

### 3. Synthesis (`agent/synthesis.py`) — pure, deterministic, unit-testable

1. **Abstract** each run: sample values → `${name}` in actions, URLs, evidence (case-insensitive,
   literal and URL-encoded forms).
2. **Minimize** each run, only where the outcome provably did not depend on the step:
   `click(X)` immediately followed by `fill(X)`; consecutive identical fills; a scroll after
   which the evidence fingerprint (URL, title, text sample) is unchanged.
3. **Align** runs by longest common subsequence over action keys (the action minus timeouts).
   Actions in every successful run are the **core path** → one transition each, states `s1…sN`.
4. **Optional steps** (in some runs only, e.g. the cookie "Proceed") become a `Branch` at the
   state where they occurred. Each distinct variant is an arm guarded by a state whose
   condition is `element_visible` on the variant's first target; the arm is an ε-transition
   (`noop`) into that interstitial state followed by the variant's own edges; the `else` arm is
   a single ε-edge. Both converge on a join state `sNj`. `probe_ms` (3 s) bounds how long replay
   watches for a late interstitial. Variants whose leading steps have no locator (scroll, wait,
   bare key press) can't be guarded and are dropped as incidental — noted in provenance. If no
   run had an empty gap there is no `else`: an unmatched branch is new territory, a hard failure.
5. **Conditions** per state, only from evidence that agrees across all runs:
   `url_matches` (query-stripped, when the step navigated), `element_visible` for the next
   edge's target, `video_playing` (else `selector_visible: video`), and — with ≥2 runs — one
   `text_visible` for a text that newly appeared in every run and is not param-bound.
   The last state is the accept state.

Everything stays inside the formalism: states carry conditions, transitions carry exactly one
action from the closed set, and the control program is a bounded regular expression. Prior art
for consolidating several agent attempts into one guarded workflow is ReUseIt
(arXiv:2510.14308); the result here is NetGent's NFA, not a script.

### 4. Validation (`agent/validate.py`)

The synthesized workflow is replayed through the ordinary executor in a fresh session with
**zero LLM calls** — once with the defaults, once per variation. If an edge fails on a *state
condition*, the unmet conditions on that state are dropped (a too-strict evidence guard) and
every replay runs again, once. Action failures can't be relaxed and are reported as-is. The
artifact is written either way, with a provenance block; `validated: false` is printed in red
and the command exits 1.

### 5. Provenance block

```yaml
provenance:
  generated_at: '2026-08-21T18:02:11+00:00'
  generator: anthropic/claude-haiku-4-5-20251001
  runs: 3                      # explorations attempted
  successful_runs: 3
  variations: [{channel: bobross}]
  validated: true
  validation:                  # every replay, first attempt and (if any) the retry
  - {params: {channel: monstercat}, success: true, edges_ok: 5}
  - {params: {channel: bobross}, success: true, edges_ok: 5}
  relaxed: []                  # "state: condition_type" dropped after a failed replay
  notes: [...]                 # synthesis decisions: minimization, branches, exclusions
```

## Limitations / next

- Only *observed* variation is recorded. An interstitial that never appeared during the N
  explorations yields no branch; validation will catch it only if it appears then.
- Failed exploration steps are not yet turned into recovery arms; they are excluded and counted.
- No `Repeat` inference (pagination / scroll-feed loops) yet; the schema supports it.
- `text_visible` needs ≥2 runs and picks one text; it is the most site-fragile condition and the
  first thing relaxation drops.
- Relaxation is by condition *type* on the failing state (the run record carries types, not ids).
- Validation is one replay per param set; flaky conditions can still pass by luck.
