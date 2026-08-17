# Proposed AI Agent — A State-Machine-Based Replayable, Self-Healing, Self-Improving Web Agent

Status: proposal (plan only, no implementation) · Date: 2026-08-06 · Author: drafted from the meeting series, design-doc review, GitHub recon, and literature survey (see [README.md](README.md) for companions).

## 1. Goal

One sentence: **an agent that pays LLM cost once to learn a web workflow, compiles what it learned into a formal state machine, replays it deterministically for free thereafter, repairs itself when the site drifts, and gets measurably better the more it runs.**

Three properties define success:

- **Replayable** — after compilation, a run makes zero LLM calls on the happy path. Same graph + same control sequence + same inputs ⇒ same behavior, with realistic recorded pacing (for NetGent, traffic timing is the research product, not a nicety).
- **Self-healing** — when the site changes, the failure is localized to one edge or one guard, repaired through an escalation ladder that starts free and ends with a bounded LLM call, and the fix is written back so the artifact converges instead of rotting.
- **Self-improving** — every run (successful or not) feeds signals back: guards get refreshed on success, fragile selectors get upgraded before they break, hot paths get optimized, dead edges decay, and generation prompts accumulate cross-run experience.

## 2. Design principles (each backed by evidence)

1. **The artifact is data, not code.** Compile to a declarative graph (YAML/JSON), never generated source. (Skyvern generates Python and needs an LLM to repair its own codegen; NetGent V1's compile-to-data was the right call.)
2. **States carry guards; transitions carry single atomic actions.** Manni's formalism from Meeting 3: guards/anchors define "am I here?"; each edge does exactly one thing. Breakage then localizes to an edge, and both endpoints survive a repair.
3. **State identity is intensional, never a similarity threshold.** A state is defined by a guard conjunction (URL template + affordance set + requires/forbids), not by DOM distance. ICSE 2020 proved global-threshold similarity fails (best universal F1 ≈ 0.60; SimHash worse than random within-app).
4. **Element identity is a ranked ladder + rich fingerprint, never one selector string.** (browser-use deleted its CSS generator; V1.5's `selectors[0]` produced `"div"` and hash-classes in shipped workflows.)
5. **Ambiguity is a miss.** A locator that matches more than one element, or a candidate already claimed this run, is treated as failure — never "click the first one." (Healenium/Skyvern enforce this; every silent-wrong-click bug traces to violating it.)
6. **The LLM only ever sees a shortlist, never the whole DOM.** Deterministic scoring ranks; the model disambiguates top-5 and must justify its choice verifiably. (VON Similo LLM: −44% failures.)
7. **Repairs must raise robustness, not restore matches.** 81.7% of match-restoring repairs re-break within six months (ASE 2025). Every heal rewrites toward user-facing identity (role+name) and may never lower the selector-quality score.
8. **Healing runs inside execution; commitment runs outside it.** A heal patches the live run immediately, but becomes canonical only after shadow validation of a new graph version — preserving the safety of bootstrapping/execution separation at the persistence boundary.
9. **Honest agentic edges beat brittle deterministic ones.** At compile time the LLM marks steps that cannot be frozen (calendars, volatile lists); those stay `agent` edges. 90% deterministic + 10% honest beats 100% deterministic that breaks weekly.
10. **Everything is measured.** Cache-hit rate, heal rate, heal precision, LLM tokens per run, trace stability — these are simultaneously the ops dashboard and the paper's evaluation section.

## 3. Architecture overview

```
                        ┌────────────────────────────────────────────┐
                        │              WORKFLOW STORE                │
                        │  versioned graphs · edge/guard stats ·     │
                        │  heal journal · negative cache · policies  │
                        └────────┬───────────────────────▲───────────┘
                                 │ load vN               │ commit vN+1 (after shadow validation)
   NL goal + input schema        │                       │
        │                        ▼                       │
        │              ┌──────────────────┐    ┌─────────┴────────┐
        ├─ no graph ──▶│  DISCOVERY/      │    │  IMPROVEMENT     │◀─ every run's telemetry
        │              │  COMPILER agent  │    │  loop (offline)  │
        │              └────────┬─────────┘    └──────────────────┘
        │                       │ NFA + guards + agentic-edge marks
        ▼                       ▼
  ┌───────────┐        ┌──────────────────┐   step fails   ┌──────────────────┐
  │  PLANNER  │──────▶ │    EXECUTOR      │──────────────▶ │  HEALING ladder  │
  │ (control  │  edges │  (deterministic  │                │  T0→T1→T2→T3     │
  │ sequence) │        │  replay, 0 LLM)  │ ◀───────────── │  + write-back    │
  └───────────┘        └──────────────────┘  patched edge  └──────────────────┘
```

Six components. The Executor is deliberately the dumbest and most important one.

### 3.1 The state machine (the artifact)

- **State** = `{id, url_template, aria_fingerprint (subset-matched accessibility snapshot), requires[], forbids[], compare_level}`. Two pages are the same state iff the guard predicate holds — threshold-free, human-readable, executable at runtime. Popups/interruptions are ordinary states reached by **ε-edges** (no action, forced transition), resolvable back — the 20-year-old EFG/EIG formalism.
- **Transition** = `{id, from, to, action (one of a closed ~15-op parameterized set: click/type/wait/press/goto/…), target: Guard, epsilon?, kind: deterministic|agent, allow_healing, stats}`.
- **Guard** (element identity) = `{intent (NL), ranked locators (role+name → testid → label/text → scoped css), fingerprint (Similo++ properties: name, visible text, type, neighbor texts, aria-label, tag, position, ancestor path, frame), healable}`.
- **Parameterization**: `{{name}}` templates bound from an input schema; keys — never values — participate in any cache identity, so secrets never reach a model and one graph serves all bindings.
- **Control sequence**: the planner emits a finite edge list per run (graph search, not LLM). Traversal is bounded and decidable; loops are safe.

### 3.2 Executor (replay mode)

Per edge: assert source-state guard → sweep in-scope ε-edges (interrupt check between every step) → resolve target element via the ladder under the exactly-one rule → readiness gate (actionability auto-waits + look-ahead resolution of the *next* edge's target) → execute the single atomic action with recorded step-interval pacing → await destination-state guard with timeout. **The destination guard IS the breakage detector** — no separate monitoring needed. Failure classification falls out mechanically:

| Observation | Diagnosis | Response |
|---|---|---|
| destination guard matches after retry | jitter/timing | retry policy; consider wait synthesis, don't touch selectors |
| landed on destination, but next edge's target unresolvable | UI drift on that guard | healing ladder, T0 up |
| landed on a *different known* state | flow drift, known topology | re-plan from here (graph search, no LLM) |
| page matches no known state | flow drift, new territory | T3 local discovery, splice new state(s) |
| locator ambiguity or locator disagreement | wrong-element risk | hard stop + heal; never proceed |

### 3.3 Healing ladder (fires only on executor failure)

- **T0 — ranked fallbacks** (free): try the guard's remaining locators.
- **T1 — deterministic re-matching** (free): score the stored fingerprint against candidates pruned by region/landmark, using Similo++'s GA-optimized weights; solve all of a state's broken guards *jointly* (resolved guards anchor unresolved ones). Accept at score ≥ 0.6, exactly-one, unclaimed, not in the negative cache.
- **T2 — LLM shortlist disambiguation** (one bounded call): input = DOM excerpt + accessibility tree + page & element screenshots; model returns choice + the attributes that justify it; the justification is verified programmatically before acceptance. Action method and arguments are frozen — only the locator may change.
- **T3 — local re-exploration** (bounded agent run): enter discovery mode at the failure point with the goal, completed prefix, and expected destination; try a few candidate actions; after each, match the page against *all known state fingerprints* to reconnect rather than mint duplicates; compile the recovered path into **new states/edges spliced into the graph**. This is the repair capability no linear-script system has.
- **Write-back**: any accepted heal (T1+) lands in a candidate graph version; the run continues on it immediately; it becomes canonical only after shadow validation replays the affected workflows with varied parameters. Failures escalate to a human with the full heal journal (before/after screenshots, scores, candidates). Rejected heals enter the negative cache permanently.

### 3.4 Discovery/Compiler (cold start)

1. An exploration agent runs the NL goal with a capturing controller that snapshots the selector map + aria snapshot *before every action* (full provenance, fresh at act time).
2. Trace segmentation into states via the **dual-key rule**: exact key (normalized-DOM hash) + structure key (tag/role/id/aria skeleton, text stripped, repeated siblings collapsed to one). Hash hit = same state, free. Hash miss = ask the LLM the *classification* question with a fixed vocabulary — "is this difference cosmetic, dynamic-data, a same-page duplicate, or genuinely new?" — only "new" mints a state (kills the list-grows-by-one explosion at the source).
3. **Offline consolidation** (the structural advantage over online crawlers): APE-style refinement — same state + same action → different successors means the state is over-merged, split it (cap splits; coarsen past ~8); negative-evidence merging for the rest. Then **validate by re-execution**: every guard must fire on its own state and nowhere else; every edge must reproduce its successor. Ship only what survives.
4. The LLM marks unfreezable steps as `agent` edges, and writes per-state normalizer masks (timestamps, counters, ads) for the state-identity layer.
5. Label the workflow by what the trace *demonstrably did* (backward construction), not the starting intent.

### 3.5 Improvement loop (offline, continuous — what makes it self-improving)

Runs on telemetry, not on failures:

- **Learn on success**: refresh each guard's fingerprint on every successful resolution, so references track slow drift instead of staling (Healenium's key trick).
- **Predictive maintenance**: track per-attribute stability per site and each guard's match-score trend; a declining score queues a re-derivation *before* the run goes red (Testim's drift detection). Scheduled canary replays catch drift on your clock, not a user's.
- **Robustness ratcheting**: background pass rewrites low-scoring selectors toward role+name; a rewrite ships only after shadow validation (accept-only-if-verified-better).
- **Graph hygiene**: usage-frequency decay archives cold edges/states (archive, not delete — flow drift reverts); heal-count hotspots trigger re-discovery of that region; near-duplicate states detected post-hoc get merged.
- **Generation experience**: cross-run accumulation of what worked/failed per site (V1.5's `evolution.py`, kept and extended) makes each re-discovery cheaper and better than the last.
- **Skill accumulation**: recurring subgraphs (login, cookie-consent, search) get factored into shared sub-machines callable from multiple workflows (SteP's stack semantics), so new workflows start partially compiled.

### 3.6 Store

Versioned graphs (every mutation carries its evidence: trigger, screenshots, scores, prompt/response), edge/guard statistics, the heal journal, the negative cache, per-site normalizer policies, and named terminal outcomes. Rollback is a version pointer move.

## 4. What this asks of an LLM, and when

| Phase | LLM use | Bound |
|---|---|---|
| Replay (happy path) | none | 0 |
| Jitter/T0/T1 heal | none | 0 |
| T2 heal | shortlist disambiguation | 1 small call per broken guard |
| T3 heal | bounded local agent | capped steps + budget |
| Discovery | full agent + classification + normalizer writing | once per workflow (or region) |
| Improvement | selector rewriting, dedup judgment | offline, batched, budgeted |

This table is also the answer to the advisor's "minimize LLM reliance" constraint — reliance becomes *enumerable and measurable* rather than a vibe.

## 5. Evaluation plan (paper-facing)

- **Environments**: WorkArena/++ (task families × seeds = native parameterized replay) + REAL (deterministic, configurable) + WebArena (comparability with AWM/ASI/SkillWeaver), all via BrowserGym. Repair loop on ReproBreak (~4-month version gaps). Robustness on OpenApps/StressWeb perturbations.
- **Protocol**: run 1 explores/compiles; run 2..N replay; compare vs. direct agent execution (PreSkill/PostSkill shape).
- **Metrics**: task success, key-node (waypoint) completion, LLM calls & tokens per run, cost per run, steps, cache-hit rate over time, heal rate, **heal precision** (nobody reports it), and the metric unique to this project: **traffic-trace fidelity/stability across replays**.
- **Positioning**: the defensible claim is redundancy + regeneration + artifact repair on a formal state machine with principled state identity — no surveyed system has all four. (Agent-E's own future-work section describes this system as unbuilt.)

## 6. Phased roadmap (each phase independently demonstrable)

1. **Executor + schema** — define the artifact schema; build the deterministic interpreter; hand-author one reference NFA (e.g. YouTube). *Demo: LLM-free replay of a multi-state workflow with an injected popup.*
2. **Identity + T0/T1** — locator ladders, fingerprints, exactly-one enforcement, Similo scoring. *Demo: replay survives a renamed selector with zero LLM calls.*
3. **T2/T3 + write-back** — shortlist healing, local re-exploration splicing, versioned commit with shadow validation. *Demo: the Meeting-3 healing head-to-head, live.*
4. **Compiler** — capture, dual-key segmentation, consolidation, agent-edge marking. *Demo: NL goal → compiled graph → deterministic replay, end to end.*
5. **Improvement loop** — learn-on-success, drift prediction, decay, sub-machine factoring. *Demo: heal rate and cost per run declining over a multi-week canary series.*
6. **Evaluation harness** — BrowserGym integration + the metrics suite; freeze for the paper.

Phases 1–3 need no Discovery work at all (hand-authored graphs suffice), which de-risks the hardest research question (Discovery) off the critical path — and phases 1–2 double as the small-scale prototype that settles the remaining design disagreements empirically.

## 7. Open questions & risks

- **State-identity policy defaults**: how much normalization ships out of the box vs. is LLM-written per site — needs empirical tuning in phase 2.
- **T3 budget**: how many steps/tokens before escalating to a human; start conservative (≤5 steps), tune on ReproBreak.
- **Non-idempotent actions during discovery/healing**: needs an explicit destructive-action policy (allowlist of safe verbs, confirm-gates on submit/purchase/delete) before any live-site canary runs.
- **Credentials & capture hygiene**: parameter values never in artifacts or model context; HAR/DOM captures of authenticated flows must be redacted before storage.
- **Concurrency**: multiple runs on one graph while a heal is mid-flight — versioning gives isolation, but the locking story needs a design pass in phase 3.
- **The self-inflicted-state risk** (the shared red line from the meetings): any rule that mints states in an uncontrolled way. Mitigations are layered — dual-key hashing, the classification vocabulary, APE coarsening caps, and dedup in the improvement loop — but this is the thing to watch in every phase demo.
