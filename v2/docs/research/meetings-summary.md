# NetGent V2 — Meeting Series Summary

Source: three Slack-huddle-style ASR transcripts (RTF). Meeting 1 (~38 min), Meeting 2 (~60 min), Meeting 3 (~46 min). Transcription quality is poor (ASR artifacts: "Netgen/NSA" = NetGent/NFA, "Asian" = agent, "yammo" = YAML, "Pomana" = Pomona, "scala draw/Excalibur" = Excalidraw).

## Participants

- **Eugene Vuong** — owns the NetGent V2 design doc, the YAML/DSL grammar, and the Excalidraw diagrams. Wrote NetGent V1. In New York during Meeting 2; wrote the design doc on a plane.
- **Manni Moghimi** — the automata-theory counterpart; works from a physical whiteboard at the lab (UCSB Systems & Networking Lab). Pushes the formal NFA framing.
- **Arpit** — advisor/PI, referenced but never present. Standing constraints: minimize LLM reliance, justify vs. baseline, separate bootstrapping from execution.

Only two speakers appear in any transcript.

---

## Meeting 1 — Vocabulary collision

Topics: Eugene's written definitions of state / transition / "on-handler" for interruptions (pop-ups, cookie banners); interruption as first-class NFA state vs. out-of-band handler; state granularity. Worked example: YouTube flow (home → search → video list → video) with pop-ups injected.

**Decisions / agreements**
- A state runs action(s); on completion, triggers/conditions pick the next state; a transition is the condition bridging two states.
- One atomic action per state (Manni conceded this was better than his idea) — a pop-up can occur between any two actions, so trigger checks must run after each one. Bonus: fewer states to recreate on change.
- Pop-up/on-handler question is an optimization, not a blocker.
- Repair heuristic: if the home page drifts, only recreate the home page state; reuse downstream states.
- "Interruption vs. real state" classification can only happen AFTER the graph exists (via graph reduction on densely connected nodes).

**The big reveal (~25:00)**: their models are inverted duals. Eugene: actions inside states, element/hook guards on transitions. Manni: guards/anchors inside states, actions on transitions. This invalidated the earlier "consensus" in the same call.

**Disagreements / risks**
- Manni: nobody (human or agent) can consistently define "pop-up"; relying on an LLM for it adds nondeterminism and will draw Arpit's push-back.
- Manni's red line: any rule that creates states/transitions in an uncontrolled/exponential manner. Large graphs per se are fine.
- Manni's risk against Eugene's model: no "word" (input sequence) → on breakage, the executor gets stuck, mints a new state, and can't determine the successor — losing intermediate transitions.
- Eugene's risk against Manni's model: more states → more transitions → more conditions to break; LLM may mint a NEW state instead of healing an existing one.
- Eugene: "an NFA is meant to be predictable, but we're using an NFA for an unpredictable website."

**Actions**: Manni to write down his definitions + diagram the same YouTube example and post to the shared doc. Open: which formulation is better.

---

## Meeting 2 — Broadening; locating the real gap

Walkthrough of the (explicitly named) "NetGent V2 Design doc." Manni: high-level architecture "looks solid." Terminology fix: the "interaction script generator" box is really the workflow generator; the output circle is the workflow.

**Error taxonomy (a real deliverable)**
- **UI drift** — same source/destination state, but the guard/hook breaks (element renamed).
- **Flow drift** — the transition now leads somewhere else; new state or edge needed.
- **Website jitter** — Eugene's rare (~1–5%) unaccounted event; Manni argues it collapses into flow drift.
- Agreed to collapse the doc's "website side" vs. "agent side" error columns into one NFA-centric taxonomy (removed section marked in red, not deleted).

**Decisions**
- Errors must be classified — feeds the repair loop and makes paper metrics.
- Expiry/decay on states/transitions for de-dup — based on usage count relative to path frequency, not wall-clock time.
- Add a **validation/error agent** — explicitly what NetGent V1 lacked (V1 "would just create states and there was no validation").
- Circular transitions are NOT a risk: the planner emits a finite "word" (explicit transition sequence) per run, so traversal is bounded; no determinization needed.
- Atomic operations are a closed set (<15: click, type, wait, fast-forward, …), parameterized — wait(t), click(element), type(x, y). Given to the planner as context. Parameterization prevents graph explosion. Strongest, least contested agreement.
- YouTube reference model: ~3 real states (home, video list, watch page) + login page + empty initial state.
- No coding until the fixing/repair process is specified.

**The central admission (~20:43)**: Eugene — "we didn't explain a lot about how it FIXES the workflow, that's why we're confused." The design doc only covers cold-start creation. Both agree: creating a workflow is the easy part; repairing it is the hard part. This becomes the Meeting 3 agenda.

**Evaluation**: reuse NetGent metrics but compare vs. a plain-LLM-agent baseline (can do everything but not reproducibly, and burns tokens every run). Proposed metrics: hit rate of generated states/workflows; number and complexity of completable workflows.

**Disagreements / concerns**
- Pop-up-as-state vs. on-handler recurs. Manni briefly proposes "every guarded transition goes to a new state," retracts it (fast-forward/pause must stay on the same state).
- Eugene: a pop-up can fire before OR after a click, so handling can't be pinned to a state boundary; handlers run around each step, scoped local or global.
- Manni's state identity: two pages are the same state if their STATIC content (template HTML, no data) matches — so login-page and login-page+popup are different states.
- Methodological split (Manni, ~38:53): Manni is NFA-first then grammar; Eugene is grammar-first then counterexamples. Manni: "I don't think this translates to your grammar that well." Eugene: restrictiveness is the point.
- Open unknowns named: de-duping, healing/fixing, agent memory/context relevance (stale flows fed to the LLM cause hallucination).

**Actions**: Eugene — finish doc, especially the repair path; enumerate error types; survey prior papers. Manni — write his definitions into the doc; produce the numbered NFA. Both — adversarial grammar scenarios. Logistics: use the lab smart board via Zoom next time.

---

## Meeting 3 — Convergence on Manni's formalism; the gap is "Discovery"

**Formal definitions locked in**
- **State** = circle; carries a hook/anchor = element/HTML condition (guard for being in that state).
- **Transition** = edge; carries a single ATOMIC action (type/click/wait/fast-forward). Re-decided as single, not a set.
- **Word** = the finite transition sequence the planner emits to reach the goal; renamed "control"/control sequence.
- **ε-transition** = forced transition with no action — how an interruption/pop-up is modeled. Each pop-up type gets its own state; resolving one (click X / Decline) is an ordinary transition back.
- Rationale for single-atomic transitions: sets break more easily and can hide mid-sequence state changes. Accepted cost: bigger graph. Manni: "larger graph isn't our problem; creation of a lot of states because of one bad decision is."

**Head-to-head healing comparison** (test: YouTube renames the search-bar element)
- Eugene's model: the state breaks → must recreate it, then can't know the successor; must feed the LLM goal + actions run and ask "what's next." Eugene concedes this.
- Manni's model: transitions break, not states → both endpoints known, so only re-derive the broken transition + changed hook. No state loss, no downstream loss, less LLM dependence, no whole-graph context dump.
- No formal winner declared, but the asymmetry favors Manni's model; Eugene concedes the mechanics.

**Discovery / repair architecture** (includes explicit push-back on Arpit)
- Healing embedded INSIDE execution, not a separate process — consciously contradicting Arpit's separate-bootstrapping-from-execution rule. Eugene doesn't object.
- On transition failure: don't relaunch discovery from scratch — enter "discovery mode," branch locally, inspect the page, rewrite the transition, re-check and update the next state's element conditions.
- Reconnection: match the candidate page against every known state's hook conditions (+ optional text description) to avoid minting duplicates; genuinely new intermediates (e.g. cookie "pop-up 2") get added.
- Transition selection: natural-language description of intended action matched against the current state's outgoing transitions; atomicity makes mismatch detection easy.
- Acknowledged as the simplest possible discovery strategy; optimize later.

**On-handler resolution**: the fight dissolves — the NFA translates mechanically into Eugene's grammar with each state rendered as an on-trigger clause listing its outgoing transitions. States become the on/triggers; transitions stay transitions. Eugene accepts; Manni to write it up.

**End state**: Manni — "we have the NFA, states, and transitions figured out; the only thing left is Discovery — somebody has definitely solved that, we just need the right paper." Eugene — spec "basically almost done."

**Actions**: Manni — write his NFA design into the spec in Eugene's grammar style; grammar TODO after talking to Arpit; send whiteboard photos. Eugene — send relevant papers; try to make his flow work with Manni's model; build small-scale prototypes of both designs. Both — more healing test scenarios. Deferred: full implementation.

**Disagreements / risks**
- Process split, unresolved: Eugene wants a small prototype NOW to settle design empirically; Manni wants theory closed first. Partial convergence: small-scale prototype only.
- Manni's strongest risk statement: "we're too deep into design… if we didn't account for something and it's a breaking thing, we're cooked." And: "we're discovering issues we didn't know about yesterday, right now."
- Manni flags this as harder than their prior project ("Pomona"); rusty on state machines.
- Mutual process request: put things in writing rather than explaining verbally — both admit they just agree in conversation.

---

## Narrative arc & cross-cutting threads

1. **Meeting 1**: they believe they agree; the state/transition duality reveal invalidates the consensus. Survives: one-atomic-action rule; interruptions identifiable only post-hoc from graph structure.
2. **Meeting 2**: system-level broadening (error taxonomy, expiry, validation agent, metrics, baseline); Eugene names the real gap — the doc only covers cold start, not repair.
3. **Meeting 3**: convergence on Manni's NFA formalism (guards in states, atomic actions on edges, ε-transitions for pop-ups, control sequences); healing head-to-head favors Manni; on-handler dissolves via grammar translation; healing embedded in execution against Arpit's rule; remaining open problem = the Discovery agent.

Cross-cutting:
- The pop-up/interruption question spans all three meetings and is dissolved (via representation translation), never won.
- The planner-emitted "word"/control sequence goes from novelty (M1) to load-bearing (kills circularity risk in M2; gives the healing advantage in M3).
- Absent-advisor (Arpit) pressure shapes design throughout; the bootstrapping/execution separation is consciously overridden.
- Shared red line: combinatorial state growth from a single bad rule (graph size itself is fine).
- Every meeting ends with "write it down and I'll read it."

## Caveats

- ASR transcripts with heavy crosstalk; quotes reflect garbled wording.
- Possible chronology wrinkle: Meeting 3 contains an apology for tripping up on states/transitions "today" (the Meeting 1 event), suggesting Meetings 1 and 3 may share a calendar day with Meeting 2 adjacent. Content ordering 1→2→3 is self-consistent.
