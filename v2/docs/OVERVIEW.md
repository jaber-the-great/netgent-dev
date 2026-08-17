# NetGent v2 — Orientation

The document to read first. It states what NetGent is, which formalism is normative, what the
architecture is, what V2 changes relative to V1, what exists in this repo today, and what is still
undecided. Every claim cites a source file and section; where sources disagree, both sides are given
with a note on which is newer.

**Status:** orientation doc, written 2026-08-17 from the design record in [`research/`](research/),
the browser-layer conclusion in [`browser-layer-design.md`](browser-layer-design.md), and the V1
source tree under `v1/src/netgent/`. It is not a spec — the spec (repair path, Discovery algorithm)
does not exist yet; see §7.

---

## 1. What NetGent is

**The thesis.** An LLM explores a web application once and compiles what it learned into a
deterministic, parameterized, replayable artifact modeled as a state machine; every subsequent run
replays that artifact with **zero LLM calls on the happy path**
(`research/design-doc-review.md` §2 "Stated purpose"; `research/proposed-ai-agent.md` §1). The
argument against "just run a browser agent every time" is cost and reproducibility: V1's own numbers
are ESPN uncached at 278k tokens / $0.098 per run vs. $0.15 one-time when cached
(`research/github-recon.md` §"What V1 is").

**The product is network traffic.** NetGent is not a general web-automation framework that happens to
be reproducible. The deliverable is realistic, repeatable network traffic datasets for ML-for-networking
research — which is why replay timing, per-edge HAR attribution, and trace stability across replays
are first-class requirements rather than nice-to-haves (`v1/README.md` §intro;
`research/proposed-ai-agent.md` §1 "Replayable"; `browser-layer-design.md` §"The three findings",
finding 1 and §4 "Align everything to NFA edges"). It is also the one metric no competing system can
report (`research/related-work.md` §P3, R30).

**Who it's for.** UCSB Systems & Networking Lab (SNL) and downstream consumers of the traffic
datasets. Secondary audience: the paper's reviewers — the evaluation section and the design are the
same artifact (`research/proposed-ai-agent.md` §2, principle 10).

**Lineage.**
- **V1** — arXiv:2509.00625, *NetGent: Agent-Based Automation of Network Application Workflows*,
  Daneshamooz, Vuong, Koduru, Chandrasekaran, Gupta (UCSB). Users write natural-language rules
  defining state-dependent actions; these compile to NFAs that a state-synthesis component translates
  into reusable executable code; 50+ workflows across video streaming, live streaming, conferencing,
  social media, scraping (`v1/README.md` §intro). Repo: `SNL-UCSB/netgent`, dormant since 2026-06-26
  (`research/github-recon.md` §Part 1). Note that Arpit Gupta, the advisor referenced throughout the
  meeting record, is the paper's last author.
- **V1.5** — `EugeneVuong/netgent`, a ground-up Playwright/async rewrite with a working mid-run agent
  repair loop and a cross-run learning module (`evolution.py`), but two regressions that matter:
  `gen_workflow()` emits a single `always_true` state with a flat action list — **the NFA is gone** —
  and `generate_selectors()` computes a fallback ladder then returns `selectors[0]`
  (`research/github-recon.md` §"What V1.5 already has").
- **V2** — this repo's `v2/`. The stated differentiators over V1 are a **validation/error agent** and
  a **healing/repair capability** (`research/README.md` §"One-paragraph project summary";
  `research/meetings-summary.md` §Meeting 2 "Decisions").

---

## 2. The formalism (normative)

Adopted in Meeting 3 and recorded in `research/meetings-summary.md` §"Meeting 3 — Formal definitions
locked in". This is **Manni Moghimi's** model. It is normative; Eugene Vuong's model is superseded.

| Object | Definition |
|---|---|
| **State** | A node carrying a **hook/anchor** — an element/HTML condition that answers "am I here?". States carry no actions. |
| **Transition** | An edge carrying **exactly one atomic action** (`click`, `type`, `wait`, `fast-forward`, …). Re-decided in M3 as single, not a set. |
| **Atomic action set** | Closed and parameterized, fewer than 15 ops — `wait(t)`, `click(element)`, `type(x, y)`. Handed to the planner as context. Parameterization is what prevents graph explosion (M2, "strongest, least contested agreement"). |
| **ε-transition** | A forced transition with no action. This is how an interruption/pop-up is modeled: each pop-up type gets its own state; resolving it (click X / Decline) is an ordinary transition back. |
| **Word / control sequence** | The finite transition sequence the planner emits to reach the goal. Renamed from "word" to "control" in M3. Traversal is therefore bounded and no determinization is needed (M2). |

**Why single-atomic transitions.** Action *sets* break more easily and can hide a mid-sequence state
change; with one action per edge, a breakage localizes to one edge and **both endpoints survive**.
The accepted cost is a bigger graph — Manni: *"larger graph isn't our problem; creation of a lot of
states because of one bad decision is"* (`research/meetings-summary.md` §M3).

**What this superseded.** Eugene's model was the exact dual: actions inside states, element/hook
guards on transitions, with pop-ups handled by an out-of-band `on` handler rather than as states. The
duality was discovered mid-Meeting-1 and invalidated the consensus reached earlier in that same call
(`research/meetings-summary.md` §M1 "The big reveal"). Meeting 3 ran a head-to-head healing test
(YouTube renames the search-bar element): under Eugene's model the *state* breaks, must be recreated,
and the executor then cannot determine the successor without dumping goal + history to an LLM; under
Manni's model the *transition* breaks, both endpoints are known, and only the broken edge plus one
hook need re-deriving. No formal winner was declared, but Eugene conceded the mechanics
(`research/meetings-summary.md` §M3 "Head-to-head healing comparison").

**The on-handler fight dissolved rather than being won.** The NFA translates mechanically into
Eugene's grammar with each state rendered as an on-trigger clause listing its outgoing transitions.
States become the `on`/triggers; transitions stay transitions. So ε-states and `on:` handlers are
*notational variants of the same graph*, not competing designs
(`research/meetings-summary.md` §M3 "On-handler resolution").

**Where the design-doc PDF still lags.** The "NetGent V2 Design Doc" (10 pp., Google Docs export) is
the artifact most likely to be shown to the advisor, and it has not caught up:

- It presents both formalisms side by side under their authors' names with **no adjudication and no
  "superseded" marker** (`research/design-doc-review.md` §8.4a).
- It contains a multi-paragraph argument *against* pop-up-as-state (the "N steps × M pop-ups ⇒ N×M
  transitions" claim) plus a deliberately dense hairball diagram built to make the adopted design look
  bad. The review notes this argument is a strawman: `on:` handlers pay the same M-checks-per-step
  cost, ε-edges are not hand-authored, and pop-up states are shared across sources — the distinction
  is representational, not combinatorial (`research/design-doc-review.md` §8.3, §8.4b).
- Its only concrete artifact, the Verizon Fios YAML, encodes **Eugene's** model (`states[].steps[]` +
  `next[].when`) and must be rewritten (`research/design-doc-review.md` §3 "The workflow artifact",
  §8.4e).
- `Validation/Error Fixing` (p. 9) and `Metrics/Evaluation` (p. 10) are **empty headings**;
  `Grammar: TODO!` (p. 6) (`research/design-doc-review.md` §1 inventory, §6).
- The load-bearing formalism exists in the doc only as two whiteboard photographs — including an
  `Abs NFA` / `Conc NFA` (abstract vs. concrete) distinction that sounds load-bearing and appears
  nowhere in prose (`research/design-doc-review.md` §0 finding 4, §8.5.6).

**Authority order** when sources disagree: Meeting 3 record > Meeting 2 > Meeting 1 > design-doc PDF.
`research/README.md` §"Where design and doc diverge" states this explicitly. Caveat carried from the
source: the meeting summaries derive from poor-quality ASR transcripts, and
`research/design-doc-review.md` §Appendix recommends confirming M3 attributions with both authors
before treating them as frozen.

---

## 3. Architecture

### 3.1 Two lifecycles, one graph

The system has a **compile side** (LLM present, runs once per workflow) and a **run side** (no LLM,
runs forever). The design-doc diagram covers only the first and terminates at the `Workflow` artifact
— everything the meetings called the hard part lives off-diagram
(`research/design-doc-review.md` §3 "What the diagram does not contain", §8.1).

**Compile side — the agent pipeline** (`research/README.md` §summary;
`research/design-doc-review.md` §3 "Components"):

```
Prompt + input schema
        │
        ▼
   Planner Agent ──delegates──▶ Discovery Agent fleet ──traces──▶ Workflow Generator ──▶ Validation Agent ──▶ Workflow artifact
        ▲                                                              │                      │
        └──────────── "Missing gaps?" ─────────────────────────────────┘   "Script failed?" ──┘
```

- **Planner** — generates plans/hypotheses, orchestrates the Discovery fleet, adjusts strategy. The
  review flags this as unfalsifiable: no plan representation, no hypothesis representation, no
  adjustment rule (`research/design-doc-review.md` §8.2).
- **Discovery fleet** — explores under Planner guidance; captures action logs, saved HTML, HAR, and an
  action summary. A *data-capture spec, not an algorithm* — see §7.1 (`research/design-doc-review.md`
  §8.2).
- **Workflow Generator** (labelled *Interaction Script Generator* in the diagram — terminology drift
  fixed in prose only, `research/design-doc-review.md` §8.4c) — emits the replayable artifact.
- **Validation Agent** — generates test cases across parameter values, different videos, different
  pop-ups. The single clearest V1→V2 delta (`research/design-doc-review.md` §4, decision 4). Two
  problems recorded: it validates at *authoring* time against an unchanged site, a different problem
  from runtime healing; and "generate tests that pass to prove dynamism" is circular with no stated
  oracle (`research/design-doc-review.md` §8.1 opening, §8.4h).

**Run side — the executor** (`research/proposed-ai-agent.md` §3.2). Per edge: assert the source
state's guard → sweep in-scope ε-edges (interrupt check between *every* step) → resolve the target
element → readiness gate → execute the single atomic action with recorded pacing → await the
destination guard. **The destination guard is the breakage detector** — no separate monitoring layer.
Failure classification then falls out mechanically (guard matches on retry ⇒ jitter; next edge's
target unresolvable ⇒ UI drift; landed on a different *known* state ⇒ flow drift, re-plan by graph
search; page matches no known state ⇒ new territory, T3; locator ambiguity ⇒ hard stop).

### 3.2 How the browser layer implements it

[`browser-layer-design.md`](browser-layer-design.md) is the newest design artifact in the repo
(2026-08-17) and is where the formalism meets code. Its package structure:

```
src/netgent/
├── core/         # pure types: actions.py (action IR), triggers.py, states.py (NFA), records.py
├── browser/      # pw.py, factory.py, session.py, executor.py, resolution.py, triggers.py,
│                 # observation/, capture/   — never imports an LLM SDK
├── synthesis/    # the LLM side (later)
└── sessions/     # auth: login NFAs, storage-state minting (later)
```

The import rule — `core` imports nothing, `browser` imports `core`, `synthesis` imports both — is
what makes `run` trustworthy, and it is meant to be enforced by a test, not a convention
(`browser-layer-design.md` §"Package structure").

Three decisions carry the formalism directly:

1. **Action IR** (`browser-layer-design.md` §1) — pydantic discriminated union, auto-registered,
   JSON round-trippable. Locators stored as **structured chains** and executed by whitelist
   reflection, never `exec`. This is the concrete form of "transitions carry one atomic action from a
   closed parameterized set": the union *is* the closed set, and the compile-time prompt schema is
   derived from the models so they cannot drift.
2. **Element identity** (`browser-layer-design.md` §2) — resolve at compile time while the LLM is
   present (mark freely, disambiguate, or refuse to emit the transition); verify at run time with no
   page mutation, because mutation contaminates both the DOM and the network trace that *is* the
   product. Mismatch raises a typed **`ElementDriftError` naming the NFA edge**
   (`research/browser-layer-B.md` §5.3). Per-snapshot IDs (`bid`, `mmid`, `B1`) never appear in the
   artifact.
3. **Triggers** (`browser-layer-design.md` §3) — a structured conjunction: URL predicate ∧ selector
   visible/enabled ∧ DOM-quiescent (MutationObserver, not `networkidle`) ∧ network-quiet-for-N-ms.
   Evaluated per-frame, recording *which conjunct fired and its latency*. This is the piece with no
   prior art: none of the nine surveyed browser layers has a condition-based wait primitive — all
   synchronize with fixed sleeps plus `domcontentloaded`, failures swallowed
   (`browser-layer-design.md` §"The three findings", finding 1). **Every remaining fixed sleep in the
   codebase is a bug report: it means a trigger couldn't be expressed.**

Plus **capture as a construction-time contract** (`browser-layer-design.md` §4): `factory.py` is the
only place a context is created, HAR/tracing are `new_context()` options that cannot be enabled later,
a declared-but-absent capture must abort the run, and every capture artifact is aligned to `edge_id`
so HAR entries are attributable to the transition that caused them — *"that attribution is the
dataset's value"*.

### 3.3 Terminology reconciliation (and the conflicts)

| Meeting record | Research docs | Browser layer | Notes |
|---|---|---|---|
| state hook / anchor | guard, guard conjunction | trigger predicate | Same role: "am I in this state?". The browser layer's version is **strictly richer** — a conjunction including DOM quiescence and network quiet, which the meetings never contemplated (`browser-layer-design.md` §3 vs. `research/meetings-summary.md` §M3). |
| word | control sequence | (not yet named) | M3 renamed it; the design-doc PDF still says "Word" (`research/design-doc-review.md` §8.3 table). |
| atomic action (<15, closed) | transition action | action IR discriminated union | Compatible. The meetings never enumerated the set; the whiteboard lists three ops and uses a fourth (`research/design-doc-review.md` §8.4j). |
| ε-transition to pop-up state | ε-edge, EFG/EIG formalism | (unimplemented) | `research/related-work.md` R12 notes this is Memon's 20-year-old EIG structural-event removal — free formal credibility. |

**Open conflict — the artifact format.** The design doc and the meetings assume **YAML**
(`research/design-doc-review.md` §3 "The workflow artifact", §4 decision 7 — the best-reasoned
section in the doc). The research conclusions assume **JSON**: `research/github-recon.md`
§"Suggested V2 artifact shape" specifies per-edge and per-state JSON records, and
`browser-layer-design.md` §1 shows a JSON locator chain as the action IR. The v2 CLI skeleton has
already picked a side without a decision record — `netgent run` takes a "compiled workflow/NFA JSON
file" (`v2/src/netgent/cli/run.py:10`). **Newer sources say JSON; this is unresolved and should be
recorded explicitly** (see §7).

Secondary conflict: the design doc claims scope over "browsers **and terminal shells**" and, in the
grammar section, per-ISP webscraper configs — four mutually inconsistent scopes, none reconciled
(`research/design-doc-review.md` §2 "Scope"). Everything in `browser-layer-design.md` is browser-only.

---

## 4. Self-healing

The differentiator, and the half of the system that is designed but not specified.

### 4.1 The T0–T3 ladder

Fires only on executor failure (`research/proposed-ai-agent.md` §3.3):

| Tier | Mechanism | LLM cost |
|---|---|---|
| **T0** | Try the guard's remaining ranked locators. | 0 |
| **T1** | Deterministic re-matching: score the stored fingerprint against region-pruned candidates using Similo++'s GA-optimized weights; solve all of a state's broken guards **jointly** (resolved guards anchor unresolved ones, per UITestFix). Accept at score ≥ 0.6, exactly-one, unclaimed, not in the negative cache. | 0 |
| **T2** | LLM shortlist disambiguation — one bounded call. Input is a DOM excerpt + accessibility tree + page and element screenshots; the model returns a choice **plus the attributes that justify it**, verified programmatically before acceptance. Action method and arguments are frozen; only the locator may change. | 1 small call per broken guard |
| **T3** | Bounded local re-exploration: enter discovery mode at the failure point with goal + completed prefix + expected destination; try a few candidate actions; after each, match the page against **all known state fingerprints** to reconnect rather than mint duplicates; splice the recovered path in as new states/edges. | capped steps + budget |

T3 is the repair no linear-script system can make, and it is the direct implementation of Meeting 3's
discovery-mode design: *don't relaunch discovery from scratch — branch locally, inspect the page,
rewrite the transition, re-check the next state's element conditions; reconnect by matching the
candidate page against every known state's hook conditions*
(`research/meetings-summary.md` §M3 "Discovery / repair architecture"). Transition selection uses a
natural-language description of the intended action matched against the current state's outgoing
transitions — atomicity is what makes mismatch detection easy.

**Write-back** is what stops the artifact from rotting: an accepted heal lands in a candidate graph
version, the run continues on it immediately, and it becomes canonical only after shadow validation.
Rejected heals enter a permanent negative cache; failures escalate to a human with the heal journal
(`research/proposed-ai-agent.md` §3.3). Stagehand's heal-with-write-back is named the single best
mechanism in the whole OSS survey (`research/github-recon.md` §"The five findings that matter most",
#2); V1.5's agent-repair loop is ahead of the field but lacks exactly this
(`research/github-recon.md` #1).

Two constraints on repair quality, both empirical: **81.7% of match-restoring web-test repairs
re-break within six months** (ASE 2025), so repairs must raise robustness (rewrite toward role+name,
never lower the selector-quality score) rather than restore matches
(`research/related-work.md` §Executive summary #4, R19). And **ambiguity is a miss** — a locator
matching more than one element, or a candidate already claimed this run, is a failure, never
"click the first one" (`research/proposed-ai-agent.md` §2, principle 5).

### 4.2 Healing lives inside execution — the conscious override

Meeting 3 decided healing is embedded **inside** execution, not run as a separate process,
consciously contradicting Arpit's standing "separate bootstrapping from execution" rule. Eugene did
not object (`research/meetings-summary.md` §M3 "Discovery / repair architecture"). The review's
position is that this is a defensible call that must be written down *with its justification* before
it is presented, and it currently appears nowhere in the design doc
(`research/design-doc-review.md` §8.1 closing).

`research/proposed-ai-agent.md` §2, principle 8 refines this into a form that keeps most of the
advisor's guarantee: *"Healing runs inside execution; commitment runs outside it"* — the heal patches
the live run immediately, but becomes canonical only after shadow validation of a new graph version.
This is newer than the meeting decision (2026-08-06 vs. the meeting series) and is the version to
present.

### 4.3 Where it hooks into the browser layer

The seam is `browser/resolution.py`. Run-time resolution verifies the stored fingerprint after
resolving the locator chain; a mismatch raises a typed **`ElementDriftError` naming the NFA edge**
rather than silently mis-clicking (`browser-layer-design.md` §2;
`research/browser-layer-B.md` §5.3). That error is the T0 entry point: everything below it (ranked
fallbacks, fingerprint scoring) is a deterministic retry inside the resolution layer, and only T2/T3
cross into `synthesis/` and need a model. The failure-classification table in
`research/proposed-ai-agent.md` §3.2 is the dispatch rule that decides which tier to enter.

The other seam is the destination trigger: a trigger conjunct that times out is returned as *status*,
never swallowed (`browser-layer-design.md` §3), which is what distinguishes "site drifted" from
"we were too fast". `research/related-work.md` R22/R23 gives the full dispatch — 0 matches → ladder;
>1 → add scope, never `nth`; found-but-not-actionable → the *prior* transition is wrong;
passes-at-longer-timeout → timing only (wait synthesis, don't touch selectors).

---

## 5. V1 → V2: what actually changes

### 5.1 What V1 actually does (from the code)

V1 is a LangGraph state machine with four nodes: `program_controller → {state_executor |
state_synthesis → web_agent}` (`v1/src/netgent/agent.py:90-110`).

- **`ProgramController.check()`** (`v1/src/netgent/components/program_controller/controller.py:17-53`)
  is the whole matching engine: for every state in the repository, evaluate its `checks` as a
  **conjunction** via the trigger registry; a state matches iff all pass. If more than one state
  matches and `allow_multiple_states=False` (the default), it raises `ValueError`. There are three
  trigger types — `url` (**exact string equality**, `v1/src/netgent/browser/controller/base.py:456`),
  `text`, and `element` (CSS/XPath). This is state identity as hand-tuned detector conjunctions, and
  it fails loudly at runtime: the Twitch commit `0bb957a` had a "Watching Stream" state checking only
  `<video>`, which also matched the home-page autoplay preview → both states matched → hard crash
  (`research/github-recon.md` §"What V1 is").
- **`StateSynthesis`** (`v1/src/netgent/components/state_synthesis/state_synthesis.py`) is a 3-node
  sub-graph: `_select_state` picks which `StatePrompt` to run — and the LLM sees **only the URL, the
  page title, and the history of action names** (lines 74-83), not the DOM and not a screenshot,
  despite the paper's "observe" framing (`research/github-recon.md` §"What V1 is");
  `_define_trigger` asks the LLM to pick from candidates the controller enumerates by injecting JS
  into the page (`base.py:545-575`, `browser/utils/find_trigger.py`); `_prompt_action` writes a
  natural-language instruction for the web agent. **`WebAgent`**
  (`components/web_agent/web_agent.py`) then drives the browser against a marked DOM, and
  `resolve_element_action` (`base.py:577-613`) converts its `mmid` into a replayable action carrying
  **one selector** — `enhanced_css_selector or css_selector or xpath` — plus absolute screen
  coordinates as a fallback.
- **`StateExecutor.run()`** (`v1/src/netgent/components/state_executor/executor.py:45-58`) replays a
  state's `actions` as a flat list with a fixed `time.sleep(action_period)` between them; the outer
  loop sleeps `transition_period` (default 3s) before every check cycle (`agent.py:177-178`).
- **The registries** (`v1/src/netgent/browser/registry/{action,trigger}.py`) are metaclass-based:
  decorators inherited through the class hierarchy, duplicate-name detection at class creation, and
  `inspect.signature.bind()` validation on dispatch. Good machinery; the recon says keep it
  (`research/github-recon.md` §Part 3 Copy #7).
- **The artifact** is a JSON list of states, each `{name, description, checks[], actions[],
  end_state, executed[]}` — see `v1/examples/basic_example/states/google_result.json`. There are
  **no transitions**: the "NFA" is implicit, since the next state is whichever state's checks happen
  to match after the current state's actions run. The shipped selectors show the fragility directly:
  `"h3.LC20lb.MBeuO.DKV0Md"`, a bare `"span"`, and `"url": "chrome://new-tab-page/"`.
- **Controllers**: PyAutoGUI over SeleniumBase (default), Playwright (execution only —
  `llm_enabled=True` raises `NotImplementedError` for lack of a perception layer, `agent.py:42-58`),
  and Desktop over a macOS host bridge. Two CLI modes: `-e` execute, `-g` generate
  (`v1/src/netgent/cli.py:1-12, 185, 245`).

**Recovery in V1 is whole-state regeneration, and it fires only when *zero* states match.** A
wrong-but-matching detector is undetectable. There is no runtime validation, no selector fallback, no
healing, and no compile-time state-distinctness check (`research/github-recon.md` §"What V1 is").

### 5.2 The delta

**Carries forward:**

| From V1 | Why |
|---|---|
| NFA / compile-to-data | The paper's central contribution and the right call — Skyvern compiles to Python and needs an LLM to repair its own codegen (`research/proposed-ai-agent.md` §2.1; `research/github-recon.md` §Part 3 Avoid #4). Explicitly: **don't lose the NFA** (`research/github-recon.md` §"Five findings" #5). |
| Cache-first replay, zero LLM on the happy path | The cost/reproducibility thesis. |
| Metaclass action/trigger registry | `research/github-recon.md` §Part 3 Copy #7. |
| Trigger/action separation | Becomes guards-in-states / actions-on-edges — the same split, re-attached to the correct objects. |
| The 50+ example workflows under `v1/examples/` | A ready-made regression corpus across streaming, conferencing, and social media (`v1/README.md`). |
| V1.5's `evolution.py` (cross-run generation experience) | Novel; nothing surveyed has it (`research/github-recon.md` §"What V1.5 already has"). |

**Replaced, and why:**

| V1 behavior | V2 | Reason |
|---|---|---|
| State holds an action list; next state is whatever matches | Transition holds exactly one atomic action; planner emits an explicit control sequence | Breakage localizes to one edge with both endpoints known (`research/meetings-summary.md` §M3). |
| Implicit successor (match-whatever-fires) | Explicit edges + bounded control sequence | Kills the "executor gets stuck and can't determine the successor" failure Manni identified (§M1 risks). |
| One CSS selector + absolute screen coordinates | Ranked locator chain + Similo++ fingerprint, ambiguity = failure | `selectors[0]` → `"div"` and `button.cikFpu` in shipped workflows; element identity is the weakest component and **fails silently** (`research/github-recon.md` §"Five findings" #3). |
| `check_url` exact string equality | URL template / route predicate | Breaks on any tracking parameter (`research/github-recon.md` §"What V1.5 already has"). |
| Detector conjunction as state identity, no distinctness check | Intensional guard conjunction + dual-key dedup + compile-time distinctness check | The Twitch collision class of bug (`research/related-work.md` R1–R3; `research/github-recon.md` §Part 3 Copy #5). |
| `time.sleep(action_period)` / `transition_period` | Trigger predicates with DOM-quiescence and network-quiet conjuncts | Sleeps corrupt the traffic measurement, which is the product (`browser-layer-design.md` §3; `research/related-work.md` R23). |
| No validation | Validation Agent + validate-by-re-execution | V1 "would just create states and there was no validation" (`research/meetings-summary.md` §M2). |
| Whole-state regeneration, only on zero-match | T0–T3 ladder with write-back, triggered by the destination guard | §4 above. |
| LLM sees URL + title only | Rich compile-time perception; run time observes almost nothing | Asymmetric by design (`browser-layer-design.md` §"What changed", item 4). |
| SeleniumBase + PyAutoGUI screen coordinates | Playwright, no page mutation at run time | Coordinates aren't durable; mutation contaminates the trace (`browser-layer-design.md` §2). |
| No capture | HAR + tracing as a construction-time contract, aligned per edge | The dataset is the product (`browser-layer-design.md` §4). |

---

## 6. Current repo state

**Exists and works:**

- `v2/pyproject.toml` — package `netgent` 2.0.0a0, Python ≥3.11, hatchling, ruff (line-length 120,
  `E,F,I,PLE,ASYNC,B`), pytest. **One runtime dependency: `typer`.** Entry point
  `netgent = netgent.cli:main`.
- `v2/src/netgent/cli/` — a Typer app with four commands registered in `commands.py`, one module
  each, plus `--version`. `netgent doctor` is **fully implemented** (`cli/doctor.py`): checks Python
  version, `.env` presence, LLM keys matched against the provider prefix of
  `NETGENT_GENERATOR_MODEL`, Chrome/Chromium detection with a candidate-path list plus `which`
  fallback, and credentials-file validity — exits 1 on any error.
- `v2/.env.example` — the config contract. Notable: *"Only `netgent generate` and `netgent eval` need
  an LLM key; `netgent run` executes compiled workflows with no LLM calls"* — the thesis restated as
  an operational invariant. litellm-style `provider/model` strings
  (`NETGENT_GENERATOR_MODEL=gemini/gemini-2.5-pro`), an optional cheap `NETGENT_SECONDARY_MODEL`,
  browser settings, and **site credentials kept separate from LLM keys**
  (`NETGENT_CREDENTIALS_FILE`).
- `v2/evals/` — `datasets/` and `results/` (both `.gitkeep`), with `evals/README.md` stating the rule
  taken from the survey: evals are offline and LLM-judged, `tests/` is deterministic and gates CI,
  **nothing in `evals/` runs in CI**, and raw per-task results are committed so numbers stay
  verifiable (`browser-agents.md` §4, takeaways 1 and 5).
- `v2/docs/` — this document plus `browser-layer-design.md`, `browser-agents.md`, and
  `research/` (16 files: the meeting/design record, the three browser-layer deep dives, and seven
  browser-agent survey batches).

**Skeleton only — exits 1 with "not implemented yet":** `netgent run` (`cli/run.py:17`),
`netgent generate` (`cli/generate.py:19`), `netgent eval` (`cli/evaluate.py:19`).

**Empty:** `v2/src/netgent/__init__.py` is a zero-byte file. There is no `core/`, no `browser/`, no
`synthesis/`, no `sessions/` — the entire structure in `browser-layer-design.md`
§"Package structure" is unbuilt. `v2/tests/` contains only `ci/.gitkeep`: **zero tests**, despite the
testing plan in `browser-layer-design.md` §7 (local fixture pages via `pytest-httpserver`, pure-unit
tests for the serializer/fingerprint/action IR, live-site tests quarantined to `generate` only).

**Version control:** most of `v2/` is still untracked (`docs/research/`, `docs/browser-*.md`,
`evals/`, `src/netgent/cli/`, `.env.example` all show as `??`). The staged v2 files are the package
skeleton only. Branch: `dev/v2`; `v1/` is the V1 tree relocated wholesale in the staged rename.

**Designed but unbuilt, in dependency order:** the action IR and NFA types (`core/`), the Playwright
chokepoint + capture factory, the trigger engine, resolution + `ElementDriftError`, the executor,
then the healing ladder, then Discovery. `research/proposed-ai-agent.md` §6 phases this deliberately
so that phases 1–3 (executor, identity + T0/T1, T2/T3 + write-back) need **no Discovery work at all**
— hand-authored graphs suffice — which keeps the hardest research question off the critical path and
doubles as the small-scale prototype that settles the remaining design disagreements empirically.

---

## 7. Open problems & decision log

### 7.1 The unspecified halves

1. **The repair spec.** The design exists in the Meeting 3 record and in
   `research/proposed-ai-agent.md` §3.3; it has never been written as a spec.
   `research/design-doc-review.md` §8.1 gives the ten-row table of what a repair path minimally needs
   — trigger, localization, classification, re-derivation context, re-attachment, ripple, persistence,
   termination, escalation, isolation — and marks **every row absent**. Meeting 2 set the gate:
   *"No coding until the fixing/repair process is specified"* (`research/meetings-summary.md` §M2) —
   a gate the CLI skeleton and browser-layer design have already partly overtaken.
2. **The Discovery algorithm.** Named, never specified: no exploration policy (goal-directed vs.
   exhaustive — the doc implies both), no termination criterion, no budget, no fleet-concurrency
   semantics, no ingestion story for the captured HAR/HTML (neither fits a context window), and no
   destructive-action safety policy for a live site where the agent will click Submit/Delete/Purchase
   (`research/design-doc-review.md` §8.2, §8.5.4). Manni's closing bet — *"somebody has definitely
   solved that, we just need the right paper"* — is now hedged by
   `research/related-work.md` §P1 (R7–R15).
3. **State identity.** The primitive everything depends on: de-duplication, termination, and repair
   reconnection. Manni's criterion is *two pages are the same state iff their static content (template
   HTML, data stripped) matches* (`research/meetings-summary.md` §M2). The research answer is
   intensional — a guard conjunction of route + affordance set + requires/forbids, never a similarity
   threshold, because ICSE 2020 showed the best universal threshold reaches only F1 ≈ 0.60 and
   SimHash within-app is worse than random (`research/related-work.md` §Executive summary #2, R1–R3).
   These are compatible (an exact normalized-template hash is not a threshold) but have never been
   written as one rule.
4. **Metrics and evaluation.** An empty heading in the design doc. Meeting 2 agreed on two baselines
   — NetGent V1 **and** a plain-LLM browser agent — and proposed hit rate plus count/complexity of
   completable workflows (`research/meetings-summary.md` §M2). `research/proposed-ai-agent.md` §5 and
   `research/related-work.md` §P3 give the full plan (BrowserGym + WorkArena/REAL/WebArena,
   ReproBreak for the repair loop, heal precision, and trace fidelity as the headline).

### 7.2 Decisions already made

| # | Decision | Source (authoritative) |
|---|---|---|
| 1 | Manni's formalism is normative; Eugene's is superseded | `research/meetings-summary.md` §M3; `research/README.md` §"Where design and doc diverge" |
| 2 | One atomic action per transition, from a closed parameterized set (<15 ops) | `research/meetings-summary.md` §M1, §M2, §M3 |
| 3 | Pop-ups are states reached by ε-transitions; each pop-up type gets its own state | `research/meetings-summary.md` §M3 |
| 4 | Planner emits a finite control sequence; circular transitions are a non-issue; no determinization | `research/meetings-summary.md` §M2, §M3 |
| 5 | Healing is embedded inside execution (overriding Arpit's separation rule), with commitment kept outside via shadow validation | `research/meetings-summary.md` §M3; refined by `research/proposed-ai-agent.md` §2, principle 8 (newer) |
| 6 | Compile to data, never to generated source code | `research/proposed-ai-agent.md` §2.1; `research/github-recon.md` §Part 3 Avoid #4 |
| 7 | Add a Validation/error agent — the explicit V1→V2 differentiator | `research/meetings-summary.md` §M2 |
| 8 | Ambiguity is a miss: accept only exactly-one-match and not-already-claimed | `research/proposed-ai-agent.md` §2, principle 5; `research/github-recon.md` §Part 3 Copy #2 |
| 9 | Errors are classified (UI drift / flow drift / jitter) to feed the repair loop; jitter collapses into flow drift or a retry policy | `research/meetings-summary.md` §M2; `research/design-doc-review.md` §8.4f |
| 10 | Package split — final naming (2026-08-17): `core / browser / executor / agent`, i.e. browser-layer-design.md's `synthesis` is named `agent`, the run-time NFA traversal gets its own `executor` package, and `sessions` is deferred. One-directional import rule (core ← browser ← executor ← agent) enforced by a test; only `browser` imports Playwright; only `agent` imports LLM SDKs | `v2/src/netgent/*/__init__.py`; `browser-layer-design.md` §"Package structure" (naming superseded) |
| 11 | Element identity resolved at compile time, verified at run time; typed `ElementDriftError`; no run-time page mutation | `browser-layer-design.md` §2 |
| 12 | Capture is a construction-time contract; a declared-but-absent capture aborts the run; artifacts aligned to `edge_id` | `browser-layer-design.md` §4 |
| 13 | Evals are separate from tests; no agent-success assertions in CI; raw per-task results committed | `browser-agents.md` §4; `v2/evals/README.md` |
| 14 | Expiry/decay on states and transitions keyed to usage frequency, not wall-clock | `research/meetings-summary.md` §M2 |
| 15 | Synthesis stack: LangChain + LangGraph (chosen 2026-08-17 for LangSmith logging and v1 continuity, against the field trend documented in `research/agent-frameworks.md`), contained by three rules — quarantined in `synthesis/` behind the import-boundary test, shipped as the optional `netgent[generate]` extra so `run` installs framework-free, and all model calls behind a single call-site seam for a cheap exit. pydantic 2 is a core dependency (the action IR). | `pyproject.toml` (`[project.optional-dependencies] generate`); `research/agent-frameworks.md` §Recommendation (recommended against; overridden) |

### 7.3 Decisions still open

- **YAML vs. JSON artifact.** Design doc and meetings say YAML; `research/github-recon.md`
  §"Suggested V2 artifact shape", `browser-layer-design.md` §1, and `v2/src/netgent/cli/run.py:10`
  all say JSON. No decision record exists either way. The design doc promises "alternative
  implementations" (plural) and presents exactly one (`research/design-doc-review.md` §8.5.1).
- **Scope.** Browser-only, or browsers *and* terminal shells? Nothing in the formalism, the atomic-op
  set, or the grammar accommodates a terminal (`research/design-doc-review.md` §2). **No non-goals
  are stated anywhere** — for a project whose named central risk is uncontrolled state growth, this
  is a live omission.
- **Is "NFA" the right word?** There is no alphabet, no start/accept states, no transition relation,
  and nothing actually nondeterministic once the planner emits an explicit control sequence — the
  runtime object is a deterministically-traversed labelled transition system. Either commit to the
  formal tuple or use an accurate weaker term before a reviewer finds it
  (`research/design-doc-review.md` §8.5.2). Related: `Grammar: TODO!` is still open, pending a
  conversation with Arpit (`research/meetings-summary.md` §M3 Actions).
- **Agentic edges.** `research/proposed-ai-agent.md` §2, principle 9 and `research/related-work.md`
  R13 argue that steps which cannot be frozen (calendars, volatile lists) should stay `agent` edges —
  90% deterministic plus 10% honest beats 100% deterministic that breaks weekly. Never discussed in
  the meetings; sits unadjudicated against Arpit's "minimize LLM reliance" constraint, for which the
  LLM-budget table in `research/proposed-ai-agent.md` §4 is the proposed answer.
- **The Planner's two jobs.** Cold-start hypothesis generator and fleet orchestrator, *and* runtime
  emitter of the control sequence — same name, different lifecycle, never distinguished
  (`research/design-doc-review.md` §8.4d).
- **Process split.** Eugene wants a small prototype now to settle the design empirically; Manni wants
  the theory closed first. Partial convergence on "small-scale prototype only"
  (`research/meetings-summary.md` §M3 Disagreements); the phasing in
  `research/proposed-ai-agent.md` §6 is the concrete proposal for satisfying both.
- **Non-functional:** credentials and secret redaction in captured HAR/HTML (a HAR of a login flow
  contains session tokens), retention, destructive-action policy, cost/latency budget, ToS posture,
  concurrency of runs against a graph mid-heal — all absent
  (`research/design-doc-review.md` §8.6; `research/proposed-ai-agent.md` §7).

### 7.4 The shared red line

Both authors named the same risk, and it is the thing to check at every phase demo: **any rule that
mints states in an uncontrolled or exponential manner.** Large graphs per se are fine
(`research/meetings-summary.md` §M1, §M3; `research/proposed-ai-agent.md` §7). The layered
mitigations are dual-key hashing, a fixed classification vocabulary for the LLM, APE-style coarsening
caps, and dedup in the improvement loop — but none of them is built yet.

---

## Reading order for a new contributor

1. This document.
2. `research/meetings-summary.md` — the formalism, in the authors' own terms.
3. `browser-layer-design.md` — how it becomes code; read §1–§4 closely.
4. `research/proposed-ai-agent.md` — the forward plan, especially §3.3 (healing) and §6 (phasing).
5. `research/design-doc-review.md` — read before touching the design-doc PDF, so you know what in it
   is stale.
6. `research/related-work.md` and `research/github-recon.md` — reference material; consult by section.
