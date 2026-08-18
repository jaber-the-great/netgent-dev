# Long-Horizon Web Agents → NetGent V2

**Question.** What do the literature and the strongest open-source systems say about building a web
agent that reliably completes MANY-step tasks, and which of those ideas map onto (a) NetGent's
compile-time Discovery/Planner pipeline, (b) the NFA artifact itself, and (c) the T0–T3 healing
ladder?

**Status:** research survey, written 2026-08-18. All papers verified against arXiv abstracts /
project pages; all repos verified against live code or GitHub API on 2026-08-18. Unverified details
are flagged inline. Grounded against `OVERVIEW.md` (formalism §2, architecture §3, healing §4, open
problems §7), the current schema (`v2/src/netgent/schema/workflow.py`), and `related-work.md`
(which this document complements: that file owns state identity + selector repair; this one owns
long-horizon planning, memory, and control flow).

**The one-line answer.** The field converged on four ingredients for long horizons — (1) a
hierarchical planner that decomposes before acting, (2) an externalized, mutable plan/progress
state (never raw history), (3) induced, reusable workflow memory, and (4) a completion judge as the
stop condition — and NetGent's architecture already contains a place for each: the Planner, the
control sequence, the NFA artifact itself, and the Validation Agent. What NetGent uniquely adds is
that its artifact *solves* the two problems that cripple long-horizon agents at run time:
irreversibility (the compiled prefix is a zero-LLM checkpoint you can replay to get back anywhere)
and context exhaustion (the run side carries no context at all). What NetGent currently *lacks* is
control flow: the linear `control_sequence` cannot express the loops, branches, and shared
sub-flows that every production long-horizon workflow system (most visibly Skyvern's block DSL) has
been forced to grow.

---

## 1. What the field found (compressed)

### 1.1 The long-horizon problem is real and unsolved

- **Odysseys** (Jang, Koh, Fried, Salakhutdinov; CMU; arXiv:2604.24964, Apr 2026) — 200
  long-horizon tasks from real browsing sessions, evaluated on the live Internet with rubric-based
  grading (avg 6.1 rubrics/task). Best frontier model: **44.5% success**; *trajectory efficiency*
  (rubric score per step) of frontier agents is **1.15%** — agents waste almost every step. This is
  the direct benchmark for "many-step web task" and the strongest argument for NetGent's thesis:
  per-step LLM decision-making degrades with horizon length, so freeze the decisions.
- **WebArena** (Zhou et al., ICLR 2024, arXiv:2307.13854): 812 multi-page tasks; launch SOTA 14.4%
  vs. human 78.2%; today ~71–74% with heavy scaffolding (leaderboard numbers vary with step budget;
  secondhand). **WorkArena++** (ServiceNow, NeurIPS 2024 D&B, arXiv:2407.05291): 682 *compositional*
  enterprise tasks — success requires carrying intermediate results across sub-tasks, exactly the
  decomposition/progress-tracking failure mode.
- Contrarian datapoint — **AgentOccam** (Yang et al., Amazon, ICLR 2025, arXiv:2410.13825): with NO
  search, roles, examples, or feedback, purely realigning the observation/action space beat
  contemporaneous multi-agent and search systems on WebArena (43.1%). Lesson for Discovery: fix
  what the model sees before adding machinery.

### 1.2 Planning & decomposition

- **Agent-E** (Emergence AI, arXiv:2407.13032): planner/executor hierarchy; task-adaptive DOM
  distillation; **change observation** — after every action, what changed on the page is fed back
  as verification signal. Beats prior SOTA on WebVoyager by 10–30%. Its future-work section
  describes compiling/caching workflows — i.e., NetGent V2 unbuilt (`related-work.md` already flags
  this: quote it in the intro).
- **ADaPT** (Prasad et al., Findings of NAACL 2024, arXiv:2311.05772): **decompose only on
  failure** — try the (sub)task directly; when the executor fails, recursively decompose that
  sub-task into AND/OR children. +27–33 pts across ALFWorld/WebShop/TextCraft. Decomposition depth
  adapts to task difficulty; no wasted upfront planning.
- **Plan-and-Act** (Erdogan et al., ICML 2025, arXiv:2503.09572): separate Planner emitting a
  structured NL plan + Executor grounding each step; planner trained by **reverse-annotating action
  trajectories with plans**. 57.6% WebArena-Lite SOTA. The reverse-annotation move is
  Learn-by-Interact's "backward construction" (Su et al., arXiv:2501.10893): derive the
  instruction/plan *from* the trajectory after the fact — already in `related-work.md` as R15.
- **WebDART** (arXiv:2510.06587): type each subtask by *capability* — **navigate / extract /
  execute** — and continuously replan as pages reveal shortcuts. +13.7 pts on WebChoreArena, up to
  14.7 fewer steps.

### 1.3 Search, backtracking, and the irreversibility wall

- **Tree Search for LM Agents** (Koh et al., arXiv:2407.01476): best-first search in the *live*
  environment with an LM value function; +28–40% relative. But backtracking works by actually
  re-navigating, and the authors and everyone after them hit the same wall: **real web actions are
  irreversible and exploration is slow**.
- **WebPilot** (Zhang et al., AAAI 2025, arXiv:2408.15978): the fix is structural — **decompose
  globally, search locally**: hierarchical task decomposition shrinks the space, then a
  web-tailored MCTS runs *within one subtask only*, with reflective plan adjustment between
  subtasks. 37.2% WebArena (GPT-4o), +93% relative over flat tree search.
- **WebDreamer** (Gu et al., TMLR 2025, arXiv:2411.06559): the other fix — don't backtrack,
  **simulate**: an LLM world model predicts each candidate action's outcome; commit to the best.
  4–5× cheaper than real search; works on live sites where search is infeasible.
- **LATS** (Zhou et al., ICML 2024, arXiv:2310.04406) unifies MCTS with Reflexion-style verbal
  reflections on failed branches fed to future rollouts.

The trichotomy to remember: *reflect-and-retry needs resets, tree search needs reversibility, the
live web grants neither* — so either simulate (WebDreamer) or prevent (Agent-E change observation).
**NetGent has a fourth option nobody in this literature has: replay.** Because Discovery freezes
every accepted step into a deterministic edge as it goes, "return to state S" is a zero-LLM re-run
of the compiled prefix in a fresh context. The NFA-under-construction *is* the checkpointing
mechanism, and it makes bounded local search safe on a live site — for non-destructive actions
(§3, phase invariant P3).

### 1.4 Memory & workflow reuse

- **Agent Workflow Memory** (Wang et al., arXiv:2409.07429): induce *workflows* — abstracted,
  parameterized sub-routines — from successful trajectories; store as text; inject at inference.
  +51.1% relative on WebArena (35.6%, then-SOTA text agent). Online variant needs only an LLM
  success judge.
- **ASI** (Wang et al., arXiv:2504.06821): same, but induce *programs* and **verify by execution**
  during induction: +11.3% over text workflows, 10–15% fewer steps. **SkillWeaver** (Zheng et al.,
  arXiv:2504.07079): explore → propose skill → practice → distill into a Python API library;
  skills transfer between agents (+54.3% to a weak agent given a strong agent's library).
- The gradient text → verified program → transferable API is the field walking toward what NetGent
  already is: **the NFA artifact is workflow memory in its terminal form** — fully abstracted,
  parameterized, execution-verified, transferable, and (uniquely) *repairable*. AWM/ASI/SkillWeaver
  are the papers to frame against, not to copy (`related-work.md` "Avoid": don't re-derive their
  induction). What IS worth copying: skills *compose hierarchically* (AWM's online memory builds
  later workflows from earlier ones) and *transfer across sites* — the argument for a shared
  sub-workflow library (login, cookie-consent, player-start) across NetGent's 50+ example catalog.

### 1.5 State tracking, progress, context — what the model sees at step 40

- Consensus recipe (AgentOccam, Mobile-Agent-v2 arXiv:2406.01014, Synapse arXiv:2306.07863, Agent-E):
  **pruned current observation + running progress note/plan + a few retrieved artifacts — never raw
  history.** Mobile-Agent-v2's three roles are the cleanest published split: a planning agent
  compresses history into a progress note; a decision agent acts from screen+progress+focus memory;
  a reflection agent diffs before/after screens to verify each action.
- Every strong OSS harness externalizes the plan as *first-class mutable state*: browser-use
  (~110k★) keeps a `PlanItem{text, status}` list plus a sandboxed `todo.md`, re-rendered into the
  prompt each step, with a replan nudge after 3 consecutive failures; Magentic-One (microsoft/
  autogen) keeps a **task ledger** (facts + plan) and a per-turn **progress ledger**
  (`is_request_satisfied / is_in_loop / is_progress_being_made / next_speaker`), with `max_stalls`
  triggering a full re-plan; deepagents (~28k★) does todo-middleware + filesystem offload +
  subagent context isolation.
- **Stop conditions:** semantic beats numeric everywhere. Skyvern blocks carry NL
  `complete_criterion` / `terminate_criterion` evaluated by a ValidationBlock; notte gates the
  agent's own "done" claim behind a `CompletionValidator` judge; step caps (5–25/task typical) are
  backstops with forced-done at exhaustion (browser-use). Judges are cheap and good enough:
  Pan et al. (COLM 2024, arXiv:2404.06474) get 74–93% oracle agreement and show a mediocre judge
  suffices to drive Reflexion (+29% on WebArena); **WebJudge** (Xue et al., COLM 2025,
  arXiv:2504.01382) reaches 85–87% human agreement by extracting task-critical key points first —
  and its key-point extraction is essentially WebCanvas key-node authoring (`related-work.md` R26).

### 1.6 The OSS convergence: cache deterministic plans, heal on miss

Every serious production system independently arrived at NetGent's shape: **Skyvern** (~23k★)
compiles workflows into cached Python blocks, falls back to AI on selector miss, records "fallback
episodes," and an LLM `script_reviewer` repairs the cached code (capped 5/day/workflow);
**Stagehand** (~24k★) caches `act()` by instruction+page-content with variable-*keys*-not-values,
`selfHeal` on replay failure; **notte** wraps scripted steps in an `AgentFallback` context manager;
**browser-use** replays saved `AgentHistoryList`. None has a formal state machine, principled state
identity, or artifact-level repair with validation — the gap `related-work.md` already claims. The
long-horizon addendum from this survey: **Skyvern is also the only one with real control flow** —
its block DSL has `FOR_LOOP` (over an extracted list, nestable), `WHILE_LOOP` (condition + 1000-
iteration cap + synthetic cap-hit failures distinct from real failures), `CONDITIONAL` (branch
criteria), `VALIDATION`, and per-block `max_retries` / output-parameter dataflow. Production
long-horizon workflows demanded loops, branches, and parameters; NetGent's schema should assume the
same demand (§4).

---

## 2. Deliverable (a): mechanism × where it lives in NetGent × priority

Columns: **Compile** = Planner/Discovery/Generator/Validator (LLM present); **Artifact** = becomes
structure in the NFA (zero LLM at run time); **Healing** = T0–T3 ladder.

| # | Mechanism (source) | Where it lives in NetGent | Priority |
|---|---|---|---|
| 1 | Hierarchical decomposition — plan globally, act locally (Agent-E, WebPilot HTD, Plan-and-Act) | **Compile**: Planner segments the NL spec into milestone subgoals before Discovery touches a browser. **Artifact**: milestones become `segment` labels on states (§4.4) — provenance + progress metric, no runtime logic. | **P0** — this is the missing Discovery algorithm's outer loop |
| 2 | Capability-typed subtasks: navigate / extract / execute (WebDART) | **Compile**: the Planner tags each segment; the tag selects the Discovery observation mode (Agent-E's per-skill DOM views) and the Generator's edge vocabulary. | P1 |
| 3 | On-failure recursive decomposition (ADaPT) | **Compile**: Discovery's inner loop — attempt a segment directly; only when it stalls, decompose that segment and recurse. Avoids over-planning trivial segments. | **P0** |
| 4 | Bounded local search within one subtask (WebPilot; Koh et al. budgeted best-first) | **Compile**: Discovery explores within a segment under a step budget, using **checkpoint-by-replay** (§3, P3) instead of in-place backtracking. **Healing**: T3 is exactly this mechanism re-entered at the failure point — same code path, smaller budget. | **P0** (it *is* T3; building it once for both is the design win) |
| 5 | Post-action change observation as verification (Agent-E; Mobile-Agent-v2 before/after diff) | **Compile**: Discovery's accept/reject signal per atomic action — and the raw material from which the Generator authors the *destination trigger* (which conjunct of the observed change is the durable "I arrived" signal). **Artifact**: the destination guard IS frozen change observation; the runtime already uses it as the breakage detector (OVERVIEW §3.1). | **P0** — closes the loop between exploration evidence and guard authoring |
| 6 | Externalized mutable plan / progress ledger (browser-use PlanItem+todo.md, Magentic-One ledgers, Mobile-Agent-v2 progress note) | **Compile**: the Discovery agent's working state — segment list with status, progress note, `is_progress_being_made` self-check. Never enters the artifact; the frozen control program (§4.1) is the plan's terminal form. | P1 |
| 7 | Stall/loop detection → replan (Magentic-One `max_stalls`; browser-use replan-after-3-failures) | **Compile**: Discovery's escalation rule — stall ⇒ ADaPT-decompose or abandon segment. **Healing**: the runtime analogue is already designed (failure classification → ladder); add a heal-rate/stall cap that aborts the run (R17 agrees). | P1 |
| 8 | Semantic completion judge as stop condition (WebJudge, Pan et al., Skyvern `complete_criterion`, notte CompletionValidator) | **Compile**: the Validation Agent's oracle — WebJudge-style per-milestone rubrics authored by the Planner *before* exploration (this answers OVERVIEW §3.1's "circular, no stated oracle" objection). **Artifact**: each milestone's rubric compiles into that state's guard conjunction + explicit `accept` states (§4.4) — the judge's criteria become machine-checkable conditions, so no judge exists at run time. | **P0** for compile; the artifact half is cheap |
| 9 | Workflow/skill memory with hierarchical composition & transfer (AWM, ASI, SkillWeaver, Voyager) | **Artifact**: the NFA is the induced skill; add `use`/sub-workflow references (§4.3) so login/consent/player-start compile once and are shared across the catalog — SkillWeaver's transfer result, in NFA form. **Compile**: Discovery consults the library before exploring (retrieve-before-explore). | P1 (P0 for login specifically — `sessions/` already plans it) |
| 10 | Backward construction — derive the plan from the trajectory (Learn-by-Interact; Plan-and-Act reverse annotation; = R15) | **Compile**: the Generator labels states/segments/parameters from what the trace demonstrably did, not from what the Planner intended. Divergence between intended and demonstrated plan is a validation finding. | P1 |
| 11 | Observation/action-space alignment before machinery (AgentOccam; Synapse state abstraction) | **Compile**: Discovery's observation layer (DOM distillation, pruned AX tree). Do this before adding search or roles — it beat both. | **P0**, and cheap |
| 12 | Checkpoint/resume (LangGraph persistence; browser-use serialized history) | **Compile**: checkpoint-by-replay (§3 P3) — the compiled prefix is the checkpoint; plus persist Discovery's segment ledger so a crashed compile resumes at the last frozen state, not from scratch. **Artifact**: run records already align to `edge_id` (capture contract); a run interrupted at state S is resumable by replay-to-S for free. | P1 |
| 13 | Loops / conditionals / parameters in the workflow representation (Skyvern block DSL; AWM parameterized workflows) | **Artifact**: §4 — the schema additions. Bounded `repeat`, guard-dispatched `branch`, `call`, declared `params`. | **P0** — v1's own catalog needs it (§4.0) |
| 14 | Simulate-before-commit / world models (WebDreamer) | Mostly **not needed**: replay-checkpointing removes the irreversibility pressure that motivates simulation. Keep as the escape hatch for *destructive* frontier actions Discovery must not execute twice (predict, ask human, or mark the edge `destructive` and validate only once). | P2 |
| 15 | Reflection memory across attempts (Reflexion, LATS, ExACT contrastive reflection) | **Compile**: failed segment attempts produce a one-line "what went wrong" note retrieved on retry of *that segment* — scoped, not global. **Healing**: the negative cache (§4.1 of OVERVIEW) is the runtime analogue and already exists in the design. | P2 |
| 16 | Per-step LLM value functions, full MCTS at run time, judge models at run time | **Nowhere.** These are what the compile/run split exists to eliminate; Odysseys' 1.15% trajectory efficiency is the cost of keeping them. | — (anti-requirement) |

---

## 3. Deliverable (b): how Discovery should explore a long workflow

A concrete proposal for the unspecified Discovery algorithm (OVERVIEW §7.1.2), assembled from the
mechanisms above. It composes with `related-work.md`'s P1 recommendations (R7–R15 handle state
identity/dedup; this handles the long-horizon control loop around them).

### Phase 0 — Plan (Planner, no browser)

From the NL spec + input schema, the Planner emits a **milestone plan**: an ordered list of
segments, each with
- a subgoal in NL ("reach the video watch page with playback started"),
- a capability type (`navigate` | `extract` | `execute` | `dwell`) — WebDART's typing, plus `dwell`
  for NetGent's traffic-generating states (watch for N minutes) which no benchmark task has,
- a **completion rubric**: 2–5 checkable conditions in the WebJudge/WebCanvas key-node style
  ({URL pattern, element present, value}) — authored *before* exploration, so validation has an
  oracle that isn't circular,
- an irreversibility annotation: does this segment plausibly contain destructive actions
  (submit/purchase/send/delete)?

This is Plan-and-Act's planner with WebJudge's rubric extraction moved to authoring time.
Milestones for a streaming workflow: home → search results → watch page → playing → dwell(300s) →
stop. Note the milestone count is small (5–10) even when the edge count is large — segments are the
unit of planning; edges are the unit of execution.

### Phase 1 — Explore, segment by segment (Discovery, browser open)

For each segment, run an **attempt-first loop** (ADaPT):

1. **Attempt directly.** The Discovery agent acts step-by-step with: pruned observation (AX-tree /
   distilled DOM per the segment's capability type — AgentOccam/Agent-E), the segment subgoal, its
   rubric, a running progress note, and retrieved library sub-workflows (§4.3) if any match. One
   atomic action per step (the formalism's constraint is also Agent-E's prompt rule — convergent).
2. **Freeze as you go.** After each action, capture the **change observation** (DOM mutation diff +
   URL change + network activity). If the action visibly advanced (non-empty, non-transient diff),
   immediately mint the candidate edge (action IR + locator chain + fingerprint) and candidate
   destination state (guard conjunction drafted *from the diff*: which conjuncts changed and then
   stabilized). Dedup against known states via dual-key (R2) before minting. The graph grows in
   lockstep with exploration — this is what makes P3 possible.
3. **Detect stalls, then decompose.** Magentic-One-style self-check every step: is progress being
   made toward the rubric? Loop detected (revisiting a known state without rubric progress) or
   budget half-spent with no rubric conditions met ⇒ **decompose this segment** (ADaPT): the
   Planner splits the subgoal into 2–4 children with their own rubrics and recurse, depth-capped
   at 2. Only stubborn segments pay for decomposition.
4. **Complete the segment** when the rubric's conditions all hold (checked programmatically, LLM
   confirms only ambiguous conditions). The rubric conditions then *become* the milestone state's
   guard conjunction — judge criteria compiled into structure.

**Invariants during Phase 1:**

- **P1 (budget).** Per-segment step budget (default ~2× the Planner's step estimate) and a global
  budget; exhaustion ⇒ escalate to human with the segment ledger. Never unbounded.
- **P2 (one-action edges).** Discovery may *reason* over multi-step intentions but emits one atomic
  action per step, so every accepted step is exactly one edge. No batch actions to unfreeze later.
- **P3 (checkpoint-by-replay, the load-bearing one).** When Discovery wants to try an alternative
  from an earlier state S — wrong branch taken, A/B candidate actions, or verifying a guard fires
  reliably — it does **not** press Back. It discards the context, replays the already-frozen edge
  path from start to S deterministically (zero LLM), and resumes exploring. This converts WebPilot's
  "search locally" from unsafe live-site backtracking into cheap replay, and it stress-tests the
  frozen prefix as a free side effect: **a prefix that doesn't replay is a compile-time bug found at
  compile time.** Cost is wall-clock, not tokens.
- **P4 (destructive frontier).** Edges matching the destructive-action policy (submit/purchase/
  delete patterns or Planner annotation) are executed at most once, never replay-crossed during
  exploration (checkpoints must stop before them), and flagged for single-shot validation. This is
  the answer to OVERVIEW §7.1.2's safety gap; WebDreamer-style outcome prediction is the P2-priority
  fallback where even one execution is unacceptable.
- **P5 (pop-ups).** An unexpected interstitial during any attempt mints an ε-state + resolving
  transition (the formalism's design), then re-checks the pre-interruption guard. Discovery treats
  it as an interruption to record, not a plan failure.

### Phase 2 — Consolidate (offline, no browser)

The offline pass NetGent gets *because* it is not an online crawler (R11), extended for long
horizons:

1. Backward construction (R15/Learn-by-Interact): re-derive each segment label and the workflow's
   parameter slots from what the trace demonstrably did; abstract concrete values (search terms,
   video titles) into declared `params` — AWM's abstraction step, done once, offline.
2. **Loop detection:** a trajectory that re-enters a known state with a repeated action pattern
   (pagination, scroll-feed, carousel) collapses into a `repeat` node (§4.2) with an observed and a
   declared bound — APE-style coarsening applied to control flow, and the schema-level kill of the
   Nd3 "crawler generates its own near-duplicates" explosion (ICSE 2020).
3. Branch discovery: states where Discovery observed divergent successors for the same action
   context (logged-in vs. logged-out home, cookie wall present/absent) become `branch` nodes
   dispatched on successor guards (§4.2) — recording *observed* variation, never speculating.
4. Sub-workflow extraction: segments matching library entries (login, consent) are replaced by
   `call` references; novel reusable segments are proposed to the library with their rubric as the
   interface contract.
5. Validation (the Validation Agent): re-execute the full control program from scratch N times
   (per-milestone rubrics = the oracle), plus guard-distinctness checks (R11) and parameter sweeps.
   Milestone rubrics make partial credit reportable: "compiles through milestone 4 of 6" — Odysseys'
   rubric scoring, applied to compilation.

### Cost shape

LLM calls scale with *decisions* (≈ edge count + stall/decompose events + rubric confirmations),
not with replayed steps; replay makes retries wall-clock-expensive but token-free. That is the
correct asymmetry for the product: compile cost is paid once, and Odysseys says the alternative —
per-step deliberation — wastes ~99% of its steps.

---

## 4. Deliverable (c): what the NFA schema lacks for long horizons

### 4.0 The evidence it's needed

Current schema (`v2/src/netgent/schema/workflow.py`): flat `states` + `transitions` + an optional
**linear** `control_sequence: list[str] | None`. No loops, no branches, no parameters, no
composition, no accept states.

- NetGent's own catalog needs loops and dwell immediately: v1's streaming/conferencing flows
  (`v1/examples/`) watch for N minutes, scroll feeds K times, keep a two-person Meet alive —
  a linear word cannot express "stay here 300 s emitting traffic" or "next-page ×20" without
  unrolling (20 unrolled copies of a pagination edge = the state-explosion red line, OVERVIEW §7.4,
  triggered by the *representation*, not the site).
- Skyvern's production DSL grew `FOR_LOOP`/`WHILE_LOOP`/`CONDITIONAL`/`VALIDATION` + parameters +
  iteration caps + synthetic cap-hit failures — the market's revealed preference for exactly these
  four constructs. AWM's induced workflows are parameterized and hierarchically composed. Both
  arrived where this section proposes NetGent go.

### 4.1 Design principle: structure the word, keep the graph flat

Keep `states`/`transitions` exactly as they are (the formalism is untouched — nodes carry
conditions, edges carry one atomic action). Replace the linear `control_sequence` with a
**control program**: a small recursive structure over transition ids. Formally this upgrades the
planner's word from a fixed string over the transition alphabet to a **bounded regular expression**
(concatenation, bounded Kleene repetition, guard-dispatched union) — still finite, still requiring
no determinization, so Meeting 2's "traversal is bounded" property survives. It also answers
OVERVIEW §7.3's "is NFA the right word?" more honestly: graph = labelled transition system; control
program = the regular expression the executor traverses over it.

### 4.2 Proposed schema additions (pydantic sketch)

```python
class EdgeStep(BaseModel):        # today's control_sequence entry
    edge: str                     # transition id

class Repeat(BaseModel):          # loops: pagination, scroll-feed, dwell-with-keepalive
    body: list[ControlNode]
    max_iterations: int                        # ALWAYS present — the red-line backstop (Skyvern: 1000; ours should be task-scale)
    until: list[Trigger] | None = None         # semantic stop: exit early when conditions hold ("no Next button")
    count: str | int | None = None             # fixed or param-bound ("${pages}"); count and until composable
    # cap-hit without `until` satisfied is a distinct failure class (Skyvern's synthetic loop failure),
    # classified as flow drift, not action failure.

class BranchArm(BaseModel):
    when: str                     # a STATE id — dispatch by which successor guard holds (branch-on-state)
    then: list[ControlNode]

class Branch(BaseModel):          # observed variation: logged-in vs not, cookie wall present/absent
    arms: list[BranchArm]         # guards evaluated in order; overlap resolved by order
    else_: list[ControlNode] | None = None     # no arm matches ⇒ unknown territory ⇒ T3, not a silent skip

class Call(BaseModel):            # sub-workflows: login, consent, player-start — SkillWeaver transfer, NFA form
    workflow: str                 # library ref, version-pinned
    bind: dict[str, str] = {}     # caller params/literals → callee declared params

ControlNode = EdgeStep | Repeat | Branch | Call   # discriminated union, like the Action IR

class Param(BaseModel):           # workflow-level parameterization (M2: "parameterization is what
    name: str; description: str = ""; required: bool = True; default: str | None = None
    secret: bool = False          # secrets: Stagehand's rule — keys may appear in prompts/cache keys, values never

class Workflow(BaseModel):
    ...
    params: list[Param] = []
    control: list[ControlNode] | None = None   # replaces control_sequence (keep the old field one release, deprecated)
    accept_states: list[str] = []              # explicit success condition — replay succeeded iff an accept state's
                                               # guard held at program end (v1's end_state, formalized)
    milestones: list[Milestone] = []           # §4.4
```

Deliberate exclusions, to stay inside the red line (OVERVIEW §7.4): no `while` without
`max_iterations`, no computed jumps/goto, no data-dependent expressions beyond param substitution
and trigger evaluation, no recursion (`Call` depth-capped at 2, cycles rejected at load), no
arbitrary code blocks (Skyvern's `CODE` block is where its auditability ends — NetGent should not
follow). Everything remains statically enumerable: the executor can compute the maximum edge count
of any control program before running it.

### 4.3 Sub-workflow library

`Call` requires a library: named, versioned workflow files whose interface is (declared params,
entry guard, exit/accept guard). Login is the forcing case — `sessions/` already plans "login NFAs"
(browser-layer-design package structure), and every one of the 50+ catalog workflows against an
authenticated site duplicates it today. Healing composes cleanly: a heal inside a called
sub-workflow lands in the *library* entry (one fix propagates to every caller), with shadow
validation before commit exactly as for top-level workflows. This is the artifact-shaped version of
SkillWeaver's agent-to-agent skill transfer.

### 4.4 Milestones (segments) on states

```python
class Milestone(BaseModel):
    id: str; description: str
    state: str                    # the milestone's anchor state (guard = compiled rubric, §3 Phase 0)
    segment_edges: list[str] = [] # provenance: which edges Phase 1 attributed to this segment
```

Three payoffs, none requiring runtime logic: (1) partial-credit reporting for both compile and
replay ("reached milestone 4/6" — Odysseys/WebCanvas rubric scoring); (2) T3 re-exploration scope —
heal within the current segment's boundary before widening; (3) dataset labeling — HAR aligned to
`edge_id` rolls up to labeled phases ("search", "playback"), which is directly valuable for the
ML-for-networking consumers.

### 4.5 What this does to the executor and the healing ladder

The executor grows a control-program interpreter (a stack of iterators over `ControlNode`s) but the
per-edge contract — assert source guard, ε-sweep, resolve, act, await destination guard — is
unchanged. New failure classifications slot into the existing taxonomy: `Repeat` cap-hit with
`until` unmet ⇒ flow drift; no `Branch` arm matches ⇒ new territory ⇒ T3; `Call` failure ⇒ heal in
the library entry. Nothing about T0–T2 changes at all.

---

## 5. Deliverable (d): must-cite references

1. **Odysseys** — Jang, Koh, Fried, Salakhutdinov. *Odysseys: Benchmarking Web Agents on Realistic
   Long-Horizon Tasks.* arXiv:2604.24964 (2026). The long-horizon problem statement and the 1.15%
   trajectory-efficiency number that motivates compile-once/replay-forever.
2. **Agent Workflow Memory** — Wang, Mao, Fried, Neubig. arXiv:2409.07429 (2024). The
   induce-abstract-reuse loop; NetGent's artifact framed as workflow memory in terminal form.
   (Cite with ASI, arXiv:2504.06821, for the text→verified-program gradient.)
3. **ADaPT** — Prasad et al. *As-Needed Decomposition and Planning with Language Models.* Findings
   of NAACL 2024, arXiv:2311.05772. Discovery's attempt-first, decompose-on-failure inner loop.
4. **WebPilot** — Zhang et al. AAAI 2025, arXiv:2408.15978. Decompose-globally/search-locally — the
   shape of both Discovery's per-segment exploration and T3; NetGent's replay-checkpoint is the
   principled fix for its live-site backtracking problem.
5. **Agent-E** — Abuelsaad et al. arXiv:2407.13032 (2024). Hierarchical planner/executor, DOM
   distillation, change observation (= NetGent's destination guard, discovered independently); its
   future-work paragraph describes NetGent V2 — quote it in the intro (per `related-work.md`).

Supporting (cite by section): AgentOccam arXiv:2410.13825 (observation alignment before machinery);
WebJudge arXiv:2504.01382 + Pan et al. arXiv:2404.06474 (judges → compiled rubrics); WebDreamer
arXiv:2411.06559 (irreversibility framing); Skyvern & Stagehand (OSS convergence on
cache-then-heal; Skyvern's block DSL as the control-flow precedent); WorkArena++ arXiv:2407.05291
(compositional eval); Learn-by-Interact arXiv:2501.10893 (backward construction).

---

## 6. Verification notes

Compiled from three parallel verified surveys (papers: planning/search; papers: memory/recovery/
judges; OSS repos via clone/API, cleaned up after use). Flagged low-confidence items carried
forward: Agent-E's oft-quoted ~73% WebVoyager SR (abstract says only "10–30% better in most
categories"); WebArena current-leaderboard numbers (scaffold-dependent, secondhand); some venue
labels (LATS ICML'24, WebPilot AAAI'25 verified; AWM ICML'25, ExACT ICLR'25 not confirmed against
proceedings). All arXiv IDs, titles, author lists (except WebDreamer's full ordering), mechanisms,
and OSS code claims (browser-use `PlanItem`, Skyvern `BlockType`/block schemas, Stagehand caching
docs, Magentic-One ledgers, AWM pipeline, notte `AgentFallback`) were checked against primary
sources on 2026-08-18.
