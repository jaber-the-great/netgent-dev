# Review — "NetGent V2 Design Doc" (Google Docs export, 10 pp.)

**Reviewed:** 2026-08-05
**Source:** `NetGent V2 Design Doc - Google Docs.pdf` (10 pages, 7 embedded images)
**Author:** Eugene Vuong (with a section authored by / attributed to Manni Moghimi, UCSB SNL)
**Cross-referenced against:** `docs/meetings-summary.md` (three meetings, Eugene ↔ Manni)

---

## 0. Verdict up front

The document is a **strong half-spec**. The half it covers — cold-start workflow *creation* (agent roles, data captured, the YAML artifact, why interruptions are hard) — is clear, concrete, and mostly implementable. The half it does not cover — **repair/healing and the Discovery algorithm** — is present only as section headings with no body text, which is precisely the gap the meetings identified.

Three findings dominate:

1. **The repair/healing path is not specified anywhere in the document.** `Validation/Error Fixing` (p. 9) is an empty heading. `Metrics/Evaluation` (p. 10) is an empty heading. The whole runtime half of the system — execute a saved workflow, detect breakage, localize it, fix it, re-attach, persist — is absent, and is not even drawn on the architecture diagram, which terminates at the `Workflow` artifact.
2. **Discovery is named, not specified.** The Discovery Agent section describes *what data it captures* (action logs, HTML, HAR, action summary) but not *how it explores*: no state-identity function, no termination criterion, no exploration policy, no de-duplication, no budget. There is no "discovery mode" on failure at all.
3. **The document lags the meetings, unevenly.** It has clearly been edited after Meeting 2 (Manni's definitions added, the error taxonomy written, the "Agent Side" block red-highlighted for removal) and *partially* after Meeting 3 (the ε-transition appears inside the `Word` example; whiteboard photos pasted in). But the Meeting 3 convergence itself — pop-up-as-state with ε-transitions, healing embedded in execution, reconnection by hook matching, the on-handler→on-trigger-clause translation — is **not written down**. Worse, the doc still contains a multi-paragraph argument *against* the model they converged on, with a diagram built to make it look bad.

There is a fourth, more structural finding: **the load-bearing formalism exists only as a photograph of a whiteboard.** Manni's numbered NFA — the thing Meeting 3 locked in — is two 2048×1536 JPEGs on pp. 5–6. It is not transcribed, not searchable, not diffable, and not reviewable by anyone who wasn't in the room. Concepts visible in the photo (`Abs NFA` vs `Conc NFA`, "Analytics", "trigger/action", "Timer") appear nowhere in the document's prose.

---

## 1. What is actually in the document (inventory)

| Page | Content | Status |
|---|---|---|
| 1 | Title, **Goal**, architecture diagram, **Agent → User Input** (prompt + input schema template) | Complete |
| 2 | **Agent Output**, **Planner Agent**, **Discovery Agent**, **Workflow Generator Agent** | Complete prose, thin on mechanism |
| 3 | **Validation Agent**; **Eugene Workflow Definition (NFA System)** — State, Transition, `on` handler; "Can't we implement another state?" | Complete, but superseded (see §8.3) |
| 4 | YouTube 4-step example; two NFA diagrams (clean linear; pop-up-as-state hairball) | Complete |
| 5 | On-handler diagram; **Manni Workflow Definition (NFA System)** — State, Transition; whiteboard photo #1 | Prose is 2 sentences |
| 6 | **Word** (with example); **Grammar: TODO!**; whiteboard photo #2 (crop of #1); **Workflow Grammar / BQT++ Workflow Grammar** | `Grammar: TODO!` |
| 7 | **YAML-Based Approach** — benefits, pros, cons | Complete |
| 8 | Verizon Fios YAML example (image); **Better than the Baseline (NetGent V1)?** — `Validation Loop` (1 sentence), `Better Grammar:` (empty), `Dynamism:` (empty); **Different from Pramana** | 2 of 3 sub-points empty |
| 9 | **Workflow Breakage Detection** — Website Side: UI Drift, Flow Drift, Website Jitter (with a dangling empty bullet); Agent Side: State Dedupping, Circular Transitions *(entire block red-highlighted)*; **Validation/Error Fixing** | Empty heading at the end |
| 10 | **Metrics/Evaluation** | Empty heading; document ends |

**Editorial signal worth noting:** the `Agent Side` block on p. 9 (heading, `State Dedupping`, `Circular Transitions`, and its two-line bullet) is highlighted in pure red (`1 0 0 rg` fills behind the text). Nothing else in the document is colored. This matches the Meeting 2 decision to collapse the website-side/agent-side split into one NFA-centric taxonomy — marked for removal, not deleted. **The document never states what red means.** A reader outside the meetings cannot tell whether red = delete, = disputed, = TODO.

---

## 2. Purpose and scope

### Stated purpose

> "NetGent is an autonomous AI agent engineered to generate reproducible scripts for complex network tasks across diverse environments, including web browsers and terminal shells. Our objective is to provide a workflow that offers the flexibility of parameter customization while maintaining rigorous task-specific constraints through a deterministic, no-code configuration framework."

Decoded, the value proposition is: **an LLM explores a site once and emits a deterministic, parameterized config; subsequent runs replay that config without an LLM in the loop.** That is a defensible and well-motivated thesis — it is the reproducibility/cost argument against "just run a browser agent every time," and it is exactly the framing Meeting 2 chose for the evaluation baseline.

### Scope, as evidenced by the document

The document carries **four mutually inconsistent scopes**:

| Scope claim | Where | Evidence |
|---|---|---|
| Browsers **and terminal shells** | Goal (p. 1), Pramana section (p. 9) | "Zoom, Shell Commands, etc." |
| Browser web-automation generally | Everything from p. 3 onward | YouTube NFA, `on` handler, browser atomic ops |
| **Per-ISP webscraper configs** | Grammar section (pp. 6–8) | "reproducible/healable webscraper config **for each ISP**"; `isp: verizon` |
| Zoom meeting creation | User Input example (p. 2) | `Prompt: "Create the Zoom meeting under the name {{ user_name }}"` |

The ISP framing appears to be inherited from a prior project ("BQT," never expanded or defined) and sits unreconciled next to the general framing. The shell-command claim is asserted once and never developed: nothing in the NFA formalism, the atomic operation set, or the grammar accommodates a terminal.

### Non-goals

**None are stated.** For a document whose central risk (per both authors) is uncontrolled state growth and scope creep, the absence of an explicit non-goals section is a real omission. Candidates that clearly *should* be non-goals based on the meetings: solving CAPTCHAs, authenticated/paywalled flows beyond simple login, cross-site workflows (that is Pramana's job), and determinizing the NFA.

---

## 3. Architecture and system design

### Components (from the diagram on p. 1 and the prose on pp. 2–3)

```
  Prompt ──► Planner Agent ──► Interaction Script ──► Validation ──► Workflow
               │    ▲             Generator            Agent
               │    │                 ▲  │               │
   "Delegates  │    │                 │  └── "Script Failed?" ──┘
    Agents"    ▼    │                 │
          Discovery │        "Missing Gaps?" ─────────┘
           Agent(s) ┘
```

- **Planner Agent** — "generates self-evolving plans or hypotheses," orchestrates a fleet of Discovery Agents, analyzes the success/failure feedback loop, adjusts strategy.
- **Discovery Agent(s)** — explores paths under Planner guidance; captures **action logs**, **web artifacts (saved HTML)**, **network capture (.har)**, **summary of actions + success/failure**. Equipped with browser automation *and HTTP CLI* capabilities.
- **Workflow Generator Agent** (labelled *Interaction Script Generator* in the diagram) — consumes the prompt + the best methodology, emits the replayable config; falls back to the Planner when it has a gap.
- **Validation Agent** — generates multiple test cases to prove the workflow is "dynamic" (different video, different pop-up, different parameter values); iterates with the Workflow Generator. Described as "where the true refining and fixing step actually happens."
- **Workflow** — the terminal artifact (the YAML config).

### Data flow

Cold start only: `Prompt + input schema → plan → exploration traces → config → validated config`. Two feedback edges: `Missing Gaps? → Planner` and `Script Failed? → Workflow Generator`.

**What the diagram does not contain:** the replay/execution engine, the NFA store, the runtime planner that emits the control sequence, breakage detection, and the repair loop. The system as drawn ends the moment the workflow is created. Everything the meetings identified as the hard part lives off-diagram.

### Tech stack

Barely specified, and only by implication:

- YAML as the config format (chosen by default — see §8.5).
- A browser automation driver — implied by `goto`/`fill`/`press`/`click`/`expect` and by `[data-testid=plan-card]` CSS selectors. Playwright is strongly suggested by the vocabulary but **never named**.
- HAR capture, HTML snapshotting.
- "HTTP CLI capabilities" — an interesting idea (bypass the UI, replay the API call) that is mentioned once and never developed.
- LLM provider, model, prompting strategy, context construction, token budget: **not mentioned at all.** Given that Arpit's standing constraint is "minimize LLM reliance," the absence of any account of *where* LLM calls happen and how many is a notable hole.
- Storage, persistence, versioning of NFAs/configs: not mentioned.

### The workflow artifact (Verizon Fios YAML, p. 8)

This is the single most concrete thing in the document, and it is good work:

```yaml
isp: verizon
schema: 2
version: '1.0'
states:
  - id: search
    steps:
      - type: goto    ; description: "Open the Fios availability checker"    ; param: { url: ... }
      - type: expect  ; description: "Wait for the address field to render"  ; param: { visible: "address" }   # auto-wait, replaces a blind sleep
      - type: fill    ; description: "Enter the street address"              ; param: { in: "address", with: "{{ address.line1 }}" }
      - type: press   ; description: "Select the first autocomplete suggestion" ; param: { keys: [Down, Enter] }
      - type: click   ; description: "Submit the availability check"         ; param: { target: "Continue" }
    next:
      - when: "Good news, Fios Home Internet is available" ; goto: plans      # the edge
      - when: "Be among the first to know"                 ; end: NO_SERVICE
  - id: plans
    steps:
      - type: expect ; param: { visible: { css: "[data-testid=plan-card]" } }
      - type: end    ; param: { result: SERVICEABLE_ONLINE }
on:                                                                          # checked between every step
  - when: "Add a phone plan and save"
    do: [ { type: click, description: "Decline the phone-plan upsell modal", param: { target: "No thanks" } } ]
    max: 3
  - when: { css: "iframe[src*=captcha]" } ; end: CAPTCHA
```

Notable design choices visible only here and nowhere in the prose: every step carries a natural-language `description` (repair affordance — this is what an LLM re-derives against); `expect` replaces blind sleeps; guards accept **either** visible text **or** CSS; `on` handlers carry a `max: 3` loop guard; terminal outcomes are named constants (`NO_SERVICE`, `SERVICEABLE_ONLINE`, `CAPTCHA`).

**The problem:** this YAML encodes **Eugene's** model — states contain step sequences, transitions are `when` conditions. Meeting 3 converged on the inverse. Whichever model wins, this artifact must be rewritten, and the document does not acknowledge that.

---

## 4. Key design decisions and rationale

| # | Decision | Rationale given | Assessment |
|---|---|---|---|
| 1 | Model a site as an NFA | Websites are non-linear; automata give reproducibility | Directionally right, but the formalism is never cashed out (see §8.5) |
| 2 | Parameterize via `{{ }}` in an input schema | Lets the agent know which parts of the config are dynamic | Sound; still phrased as "we will plan to implement" |
| 3 | Split creation across Planner / Discovery / Generator / Validation | Separation of hypothesis, exploration, codegen, verification | Clean and conventional; the strongest part of the doc |
| 4 | Add a Validation Agent | V1 had no validation loop | The single clearest V1→V2 delta; explicitly the differentiator |
| 5 | Global/local `on` handler for interruptions | Pop-ups are non-deterministic; without it they force an error state | **Superseded** by Meeting 3 (ε-transitions); doc unchanged |
| 6 | *Not* modelling pop-ups as states | N steps × M pop-ups ⇒ N×M transitions ⇒ "fragile, unmaintainable web" | **Reversed** by Meeting 3; the argument is also a strawman (§8.4) |
| 7 | Declarative YAML config | Readable, versionable, schema-validatable; separates *what* from *how*; constrains LLM output to valid syntax | Well-argued — the best-reasoned section in the doc |
| 8 | Distinguish UI drift / flow drift / jitter | Different breakage classes need different responses | Good taxonomy; **never connected to a response** |
| 9 | Planner emits a finite transition sequence | Makes circular transitions a non-issue | Load-bearing insight — buried in a red-highlighted bullet |
| 10 | NetGent ≠ Pramana | NetGent = per-application workflow; Pramana = DAG orchestration across workflows, with context passing | Clear and useful boundary |

---

## 5. Requirements, goals, non-goals

### Goals (extracted; the doc never lists them as such)

- G1 — Generate reproducible, replayable scripts for web (and shell) tasks from a natural-language prompt.
- G2 — Support parameterization via an input schema, so one workflow serves many inputs.
- G3 — Return structured output (per the output schema), consumable by downstream Pramana workflows.
- G4 — Survive non-deterministic interruptions (pop-ups, cookie banners, CAPTCHAs).
- G5 — Be *healable* — asserted in the grammar section ("reproducible/**healable** webscraper config") and by the V1 comparison. **Never specified.**
- G6 — Beat NetGent V1 on validation, grammar, and dynamism. Two of those three are empty headings.

### Requirements

There is no requirements section, and no requirement is stated in testable form. No success thresholds, no performance/latency/cost targets, no scale targets (how many sites? how many states per site?), no reliability target.

### Non-goals

None stated. See §2.

---

## 6. Open questions, risks, TBDs

### Explicitly flagged in the document

- `Grammar: TODO!` (p. 6)
- `Better Grammar:` — empty (p. 8)
- `Dynamism:` — empty (p. 8)
- `Validation/Error Fixing` — empty heading (p. 9)
- `Metrics/Evaluation` — empty heading (p. 10)
- `Website Jitter` — a bullet with no text (p. 9)
- `State Dedupping` — heading with no body, inside the red-highlighted block (p. 9)
- The whole `Agent Side` block — red-highlighted, meaning undocumented (p. 9)
- "We propose the following **alternative implementations**" (plural) — one is given (p. 6)

### Unflagged but open

- Which formalism is normative — Eugene's or Manni's? Both are in the document under their own names, with no adjudication and no "superseded" marker.
- What is a state's identity? How do you decide two pages are the same state? (Manni's Meeting-2 answer — matching static template HTML with data stripped — is not in the document.)
- When does discovery stop?
- What is the oracle for "the task succeeded"?
- How are credentials handled? The whiteboard shows `login to YT (user, pass)`; the document says nothing about secrets.
- Where do workflows live between runs, and how are they versioned/rolled back?
- What is "BQT"?

### Risks visible in the document

- **R1 — The repair story is the product differentiator and is unwritten.** The V1 comparison rests on validation + healing; healing has zero words.
- **R2 — No evaluation plan.** Empty metrics section, and the plain-LLM-agent baseline agreed in Meeting 2 is absent. For a paper, this is the critical path.
- **R3 — Two incompatible formalisms in one document**, one of which is embedded in the only concrete artifact.
- **R4 — Combinatorial state growth.** Both authors named this as the shared red line; the document argues about it (pp. 3–4) but never states a bound, a rule, or a guard.
- **R5 — Unbounded LLM reliance.** Not counted, not budgeted, not mentioned — directly against the PI's standing constraint.

---

## 7. Timeline and milestones

**Absent.** There is no schedule, no milestone list, no phasing, no owner assignments, no paper-submission target, and no definition of done. The document also lacks a status/version/date/owner header, which for a two-author document with an unresolved design disagreement makes it impossible to tell which parts are current.

---

## 8. Critique

### 8.1 The repair/healing path — the headline gap

**It is not specified.** The word "heal" appears once, as an adjective in the grammar section. The strongest evidence of the gap is structural: the architecture diagram terminates at `Workflow`. Nothing downstream of workflow creation is modelled.

What the document *does* describe as "fixing" is the **Validation Agent ↔ Workflow Generator** loop, and it is explicit about this being the fixing step: *"This is where the true refining and fixing step actually happens."* But that loop runs at **authoring time**, against a site that has not changed, to fix a config that was never right. Runtime healing — a config that worked last month and broke because the site shipped a redesign — is a different problem with a different trigger, different available context, and different correctness criteria. The document conflates them under one word.

A specified repair path needs, at minimum, the following — **none of which is present**:

| Required | Status |
|---|---|
| **Trigger** — what constitutes a failure? Guard timeout? Wrong post-conditions? Wrong terminal result? | Absent (the `expect`/`when` primitives imply a mechanism, but no policy) |
| **Localization** — which state/transition broke? | Absent |
| **Classification** — map UI drift / flow drift / jitter to a repair action | Taxonomy exists (p. 9); **no mapping to actions** |
| **Re-derivation** — what context is handed to the LLM? Goal, history, current DOM, neighbouring states? | Absent |
| **Re-attachment** — how does a repaired transition find its destination state without minting a duplicate? | Absent (Meeting 3's hook-matching answer is unwritten) |
| **Ripple** — after a repair, which downstream guards must be re-validated? | Absent |
| **Persistence** — is the fix written back? Versioned? Rolled back on regression? | Absent |
| **Termination** — how many repair attempts before giving up? | Only `max: 3` on `on` handlers in the YAML |
| **Escalation** — when does a human get involved? | Absent |
| **Isolation** — does a repair-in-progress block other runs? Is the fix validated before it becomes canonical? | Absent |

The Meeting 3 design — *enter discovery mode locally rather than relaunching discovery; branch at the failure point; inspect the page; rewrite the broken transition; re-check the next state's element conditions; match candidate pages against all known state hooks before creating a new state* — is a genuine, workable answer to about half of this table. **It exists only in the meeting record.** Getting it into the document is the highest-value edit available.

One consequence worth stating plainly: the Meeting 3 decision to embed healing *inside* execution deliberately contradicts Arpit's standing "separate bootstrapping from execution" rule. That is a defensible call, but it is exactly the kind of decision that needs to be written down **with its justification** before it is presented, and it is not in the document at all.

### 8.2 The Discovery process — named, not specified

The Discovery Agent section (p. 2) is a **data-capture spec, not an algorithm.** It tells you what artifacts come out (action logs, HTML, HAR, action summary) and nothing about the search.

Missing:

- **Exploration policy.** Goal-directed or breadth-first? Does it try to build a complete site model or only the path the prompt needs? The diagram implies goal-directed, the "isolate and identify **all** the particular states" phrasing implies exhaustive. These are very different systems.
- **State identity / equivalence.** The core primitive. Without it you cannot de-duplicate, cannot terminate, and cannot re-attach during repair. `State Dedupping` is a heading with no body.
- **Termination criterion.** Nothing.
- **Budget.** Number of agents in the "fleet," step limits, wall-clock limits, cost: nothing.
- **Concurrency semantics.** A "fleet" of agents on one live site — do they share a browser? Are the artifacts merged? How are conflicting observations reconciled? Nothing.
- **Non-idempotent actions.** Discovery on a live site will click "Submit," "Delete," "Purchase." There is no safety policy, no read-only mode, no sandbox, no discussion.
- **How artifacts are consumed.** HAR files and full HTML snapshots are captured, but nothing says how the Workflow Generator turns them into guards and selectors — and raw HTML/HAR will not fit in a context window.
- **Discovery-on-failure.** The Meeting 3 "discovery mode" concept is entirely absent.

The Planner description compounds this: "generates self-evolving plans or hypotheses" and "dynamically adjusts its strategy" are unfalsifiable. There is no plan representation, no hypothesis representation, and no adjustment rule.

Manni's Meeting 3 closing position — "the only thing left is Discovery; somebody has definitely solved that, we just need the right paper" — is a reasonable bet, but the document has **no related-work section at all**, so the bet is unhedged.

### 8.3 Does the document reflect the meeting decisions?

**Partially, and unevenly.** It is not a clean pre- or post-meeting artifact; it has been edited in place at different times, with older material left standing.

**Evidence it post-dates Meeting 2:**
- Manni's definitions are present (a Meeting 1/2 action item).
- The `Workflow Generator Agent` rename landed in the prose (Meeting 2 terminology fix) — though not in the diagram.
- The UI drift / flow drift / jitter taxonomy is written up (a Meeting 2 deliverable).
- The `Agent Side` block is red-highlighted, matching "removed section marked in red, not deleted."
- The `Circular Transitions` bullet states the planner-emits-a-sequence answer (Meeting 2 decision).

**Evidence it post-dates Meeting 3, at least in spots:**
- The `Word` definition exists and its example contains `eps` and `"click on [x]"` — i.e. it already encodes ε-transitions and pop-up-as-state.
- Two whiteboard photos are pasted in (a Meeting 3 action item: "Manni — send whiteboard photos").
- `Grammar: TODO!` matches the Meeting 3 action ("grammar TODO after talking to Arpit").

**Meeting decisions that are NOT in the document:**

| Decision | Meeting | Document status |
|---|---|---|
| One atomic action per state | M1 | **Contradicted** — Eugene's State is still "a sequence of atomic actions" |
| Repair heuristic: recreate only the drifted state, reuse downstream | M1 | Absent |
| Interruption-vs-real-state classifiable only post-hoc via graph reduction | M1 | Absent |
| Collapse website-side/agent-side into one NFA-centric taxonomy | M2 | Marked (red) but **not done** |
| Expiry/decay on states/transitions, keyed to usage frequency | M2 | Absent |
| Errors must be classified to feed the repair loop | M2 | Taxonomy present, linkage absent |
| Atomic ops are a closed parameterized set (<15) | M2 | Only on the whiteboard photo (3 ops listed there) |
| Compare against a plain-LLM-agent baseline | M2 | Absent — only V1 is named as baseline |
| Metrics: hit rate, count/complexity of completable workflows | M2 | **Empty heading** |
| ε-transition as the pop-up mechanism; each pop-up type its own state | M3 | Only implicit, inside the `Word` example |
| Transitions carry a **single** atomic action; guards live in states | M3 | Present as *Manni's* view, not as the decision |
| "Word" renamed to **control / control sequence** | M3 | Still "Word" |
| Healing embedded inside execution (overriding Arpit's rule) | M3 | Absent |
| Discovery mode / local branching on transition failure | M3 | Absent |
| Reconnection by matching candidate pages against all known state hooks | M3 | Absent |
| Transition selection by NL-description matching against outgoing transitions | M3 | Absent |
| On-handler dissolution: states render as on-trigger clauses listing outgoing transitions | M3 | Absent — and the doc still argues the opposite |
| Head-to-head healing comparison favouring Manni's model | M3 | Absent |

**The most damaging consequence:** pages 3–4 contain a sustained argument against pop-up-as-state — "If you have N steps and M potential pop-ups, you would need to define M transitions for every one of those N steps... resulting in a fragile, unmaintainable web of state transitions" — supported by a deliberately dense hairball diagram. Meeting 3 adopted pop-up-as-state with ε-transitions. Anyone reading this document today, including Arpit, will read a confident rebuttal of the current design with no indication that it has been superseded.

### 8.4 Inconsistencies and ambiguities

**a) "State" means two different things.** Eugene: a state holds actions; transitions hold conditions. Manni: a state holds an anchor condition; transitions hold actions. Both definitions are in the document, adjacent, under the same section title pattern, with no adjudication. Every downstream sentence that says "state" is ambiguous.

**b) The N×M argument is a strawman against the ε-transition formulation.** The document's own YAML shows `on:` handlers are "checked between every step" — the M-checks-per-step cost is paid either way. The ε-transition version does not *author* N×M edges; it makes the interrupt check a structural property of the graph, and pop-up states are shared across all sources. The hairball diagram on p. 4 renders ε-edges as if each were hand-written, which is what makes it look bad. The real distinction is representational (where the interrupt logic lives in the syntax), not combinatorial — and Meeting 3's resolution (a state renders as an on-trigger clause) says exactly this. The document's strongest visual argument is arguing against a position nobody holds.

**c) Diagram/text drift.** The diagram says `Interaction Script Generator`; the prose says `Workflow Generator Agent`. Meeting 2 fixed the term in one place only.

**d) The Planner has two unreconciled jobs.** Cold-start hypothesis generator and fleet orchestrator (p. 2), *and* runtime emitter of the transition sequence (p. 9, one bullet, inside the red block). Same name, different lifecycle stage, different inputs, different outputs. Never distinguished.

**e) The YAML implements the losing model.** `states.steps[]` + `next.when` is Eugene's formalism. This is the only executable-looking artifact in the document and it will need rewriting under Meeting 3's model.

**f) "Website Jitter" is a frequency, not a failure mode.** It is defined as "rare obstacles... that may only occur in 5% of runs" — that is a rate, and rate is orthogonal to mechanism. A rare pop-up is a pop-up; a rare extra screen is flow drift. Manni's Meeting 2 argument that it collapses into flow drift is correct and unrecorded. The category also carries a dangling empty bullet.

**g) The taxonomy has no consequences.** Three breakage classes are defined and nothing is said about what the system *does* differently for each. Classification without a dispatch table is documentation, not design.

**h) "Prove that it can be dynamic" is circular.** The Validation Agent "would create multiple test cases that ensure the workflow passes in order to prove that it can be dynamic." Tests that are generated to pass do not prove anything. There is no oracle: nothing states how the system knows the task actually succeeded, especially under parameterization ("different video," "different address"). The output schema is the natural oracle — extract `zoom_code`, assert it is well-formed — but the document never connects the two.

**i) Terminal-state semantics are undefined in the NFA sections.** The p. 4 diagram shows `No Video Available` as a sink with no outgoing edges. Is that failure, or a legitimate terminal result? The YAML answers this properly (`end: NO_SERVICE` vs `end: SERVICEABLE_ONLINE` vs `end: CAPTCHA`) but the prose never does, and the NFA has no notion of accepting states.

**j) Atomic-op inconsistency.** The whiteboard lists three ops (`wait_for`, `click`, `type`) yet uses `ff(X)` in the graph. Meeting 2 agreed on a closed set of fewer than 15. The document's prose never enumerates them.

**k) Undefined terms.** "BQT" and "BQT++" are used as if established. "Pramana" is defined (well). "Hook," "anchor," "guard," "trigger," and "condition" are used interchangeably across the two definition sections.

**l) The `Word` example is not the whiteboard's word.** The prose example is a list of NL action strings; the whiteboard's word is a sequence of roman numerals indexing named transitions. The second is the right representation (it names edges in a graph); the first is ambiguous. Worth resolving.

### 8.5 Questionable choices

**1. "Alternative implementations" (plural) with one alternative.** The document promises a comparison, presents YAML, gives it a benefits section *and* a pros-and-cons section, and never names a competitor. YAML may well be right, but the reasoning presented is one-sided by construction. Obvious contenders worth a paragraph each: a constrained DSL, a Python/JS subset with a restricted API, JSON+JSON-Schema (better machine validation, worse diffs), or a Prolog/datalog-style rule set. The stated cons — logic limitations, constraint rigidity — are real, and the document's own answer to them ("restrictiveness is the point," per the meetings) is not written down.

**2. Calling it an NFA without cashing out the formalism.** There is no alphabet, no start/accept states, no transition relation, no 5-tuple, and — critically — nothing actually *nondeterministic*: no subset construction, no simultaneous active states. Meeting 2 concluded determinization is unnecessary *because* the planner emits an explicit word, which means the runtime object is a deterministically-traversed labelled transition system, not an NFA being simulated. This is a formalism-shaped hole that a reviewer or a PI will find immediately. Either commit to the formal object (define the tuple, state what the nondeterminism buys you) or use a weaker, accurate term.

**3. The V1 comparison is three headings and one sentence.** `Validation Loop: Self-explanatory.` is not an argument. `Better Grammar:` and `Dynamism:` are empty. This section is the entire justification for building V2.

**4. Full HTML + HAR capture with no ingestion story.** Neither fits in a context window. Something must summarize, chunk, or index them, and nothing does.

**5. HTTP CLI capability, mentioned once.** Skipping the UI and replaying the underlying request is potentially the most robust healing strategy available — a network-level workflow does not break on a CSS rename. Raising it in one clause and dropping it is a missed opportunity.

**6. The formalism lives in photographs.** Two whiteboard JPEGs carry the numbered NFA, the atomic-op signatures, the task decomposition, and the word. Concepts appear there and nowhere else in prose — `Abs NFA` / `Conc NFA` (abstract vs. concrete NFA), "Analytics," "trigger/action," "Timer." The abstract/concrete distinction in particular sounds load-bearing and is entirely undocumented. Photos are fine as provenance; they cannot be the spec.

### 8.6 Non-functional concerns absent entirely

- **Security.** The system executes LLM-generated actions against live sites. No sandbox, no allowlist, no destructive-action policy.
- **Credentials.** The reference task is "log in to YouTube (user, pass)." No secret storage, no injection mechanism, no redaction from the captured HTML/HAR artifacts (a HAR of a login flow contains session tokens).
- **Privacy / data retention.** HAR + full HTML of authenticated pages is sensitive. Nothing on retention or scrubbing.
- **Legality and ToS.** Automated ISP-site scraping and YouTube automation have ToS implications; anti-bot measures beyond CAPTCHA (rate limiting, fingerprinting) are unaddressed. `end: CAPTCHA` is a bail-out, not a policy.
- **Cost and latency.** No token budget, no per-run cost target, no discovery-cost ceiling — despite "minimize LLM reliance" being the standing PI constraint.
- **Observability.** No logging, tracing, or debugging story for a failed replay.
- **Concurrency and state sharing.** Multiple runs against one NFA, and repairs landing mid-run, are undiscussed.

### 8.7 What the document does well

Worth stating, because the criticism above is dense:

- **The agent decomposition is clean** and maps well onto how these systems are actually built. Manni's "high-level architecture looks solid" is fair.
- **The YAML example is excellent** and carries more real design than the prose around it: per-step NL `description` fields as a repair affordance, `expect` instead of blind sleeps, dual text/CSS guards, `max` loop guards, named terminal results.
- **The error taxonomy is genuinely useful** and is the correct seed for the repair spec. UI drift vs. flow drift is the right first cut and maps directly onto "re-derive the guard" vs. "re-derive the graph."
- **The Pramana boundary is crisp** — one of the few places the document draws a firm line.
- **The two-diagram contrast** (clean linear NFA vs. pop-up hairball) is an effective piece of visual argumentation, even though its conclusion has been overtaken.
- **Presenting both authors' formalisms side by side, under their names, is intellectually honest** — most design docs would have papered over the disagreement.
- **The reproducibility-vs-LLM-agent thesis is a real thesis**, and the cost argument behind it is sound.

---

## 9. Recommended actions, in priority order

1. **Write the repair path.** Transcribe the Meeting 3 design (discovery mode, local branching, transition rewrite, guard re-check, hook-matching reconnection, NL-description transition selection) and fill the table in §8.1. This is the differentiator and it is blank. Include the deliberate override of the bootstrapping/execution separation, with its justification.
2. **Declare one formalism normative.** Promote Manni's model (guards in states, single atomic actions on transitions, ε-transitions for interrupts, control sequences) to a single "Workflow Model" section. Move Eugene's version to an appendix marked *superseded*, keeping the N×M analysis as recorded rationale with a note on why it does not apply to the ε-formulation. Delete or rewrite the p. 4 hairball diagram — as it stands it argues against the current design.
3. **Extend the architecture diagram past `Workflow`.** Add: workflow store → executor/replay → runtime planner (control sequence) → breakage detector → discovery mode → repair → write-back. Until the diagram shows the runtime, readers will keep assuming the system ends at creation.
4. **Transcribe the whiteboards into prose**, including the numbered NFA, the atomic-op signatures, and the `Abs NFA` / `Conc NFA` distinction. Keep the photos as an appendix.
5. **Specify state identity.** Write down Manni's static-template-HTML criterion (or whatever replaces it). De-duplication, termination, and reconnection all depend on it; `State Dedupping` cannot stay an empty heading.
6. **Specify Discovery as an algorithm**: exploration policy, state-identity check, termination, budget, concurrency, and a destructive-action safety policy. Add the related-work survey — the Meeting 3 bet that "somebody has solved this" needs a citation.
7. **Fill Metrics/Evaluation**: hit rate of generated states/workflows, number and complexity of completable workflows, repair success rate by error class, LLM calls and tokens per run (cold start vs. steady state vs. repair). Name **both** baselines: NetGent V1 *and* a plain LLM browser agent.
8. **Map the taxonomy to responses.** A three-row table: UI drift → re-derive guard for the failing element, keep the graph; flow drift → discovery mode, insert state/edge; jitter → fold into flow drift (per Meeting 2) or define a retry policy. Then finish the Meeting 2 collapse and actually remove the red block.
9. **Complete or cut the V1 comparison.** `Better Grammar` and `Dynamism` need one paragraph each, or the section should go.
10. **Add front matter and hygiene**: owner, status, date, version, a stated editorial convention for red highlighting, a glossary (state, transition, guard/hook/anchor, word/control, ε, BQT), and a scope + **non-goals** section that resolves the browser/shell/ISP/Zoom tension.
11. **Add either the second grammar alternative or a decision record** explaining why YAML was chosen without one.
12. **Add a non-functional section**: credentials, secret redaction in captured artifacts, retention, destructive-action policy, cost/latency budget, ToS posture.
13. **Add a milestone plan.** The document has no dates and no definition of done; Meeting 2's "no coding until the fixing process is specified" is a gate that should be written into it.

---

## Appendix — Method and evidence notes

- Text extracted with `pypdf` (10 pages); all 7 embedded raster images extracted and read visually, since roughly half the document's content — the architecture diagram, three NFA diagrams, the YAML example, and two whiteboard photographs — carries no extractable text.
- The red marking on p. 9 was verified in the PDF content stream: five `1 0 0 rg` filled rectangles at y ≈ 706–784 sit behind the `Agent Side:` heading, `State Dedupping`, `Circular Transitions`, and the two-line NFA/planner bullet. `Validation/Error Fixing` (y ≈ 893) is **not** highlighted. No other page contains non-black, non-grey fills. The document contains no PDF annotations or comments, so any Google Docs comment threads were lost in export — worth requesting separately, as they may contain some of the missing rationale.
- The p. 6 whiteboard image is a zoomed crop of the p. 5 image; they are not two separate boards.
- Meeting attributions come from `docs/meetings-summary.md`, which is itself derived from poor-quality ASR transcripts. Specific decisions attributed to Meeting 3 should be confirmed with both authors before being treated as settled in the spec.
