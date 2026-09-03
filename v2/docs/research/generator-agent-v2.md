# The generator as an agent, v2 — the LLM drafts the whole artifact in a vocabulary of *pointers into the recordings*

Research + design doc for NetGent v2 (UCSB SNL). Written 2026-09-02 on `v2/closed-loop-rounds`, after the
Metallica/Master-of-Puppets ("MOP") closed-loop run failed replay in all three rounds. Research and design
only: no source was changed for this doc.

**Status of the decision.** That the generator becomes an LLM agent is *settled* (Eugene, 2026-09-02). This
doc does not re-argue it. It specifies the agent: its graph, its output schema, its validation rules, its
prompts, its model, and where it sits in the closed loop.

**Read first:** [`generator-agent.md`](generator-agent.md) — Parts A (the four measured pain points), B (the
survey of Workflow Use / Skyvern / ReUseIt / AWM / ASI / SkillWeaver / the PBD lineage), C (the
`GeneralizationPlan` patch design), D (the Dream Theater run that shipped it), E (its unverified list).
This doc is Part F in spirit: it *keeps* C.0's contract and C.4's validation discipline, and *replaces* the
patch channel with a full draft. Everything in generator-agent.md Parts A and B is assumed and not repeated.

---

## Summary (10 lines)

1. The MOP run failed replay in all three rounds at `t3`, on every value set — including the one the artifact
   was compiled from. **0 of 5 generalization hints were ever applied** (`hint_acceptance_rate` = 0 in rounds
   2 and 3). 2.41 M input tokens, 308 LLM calls, 48 minutes, 13 explorations, 8 achieved. §1.
2. Three of the five rejections are one bug: `GeneralizationHint.column` is an `int`, and the merge renumbers
   columns every round as runs are added. The same real step was column 4/5 → 6 → 7. The planner **predicted
   this in its own notes** and had no way to express identity. §C.
3. Two are the varying-gesture problem: press counts across runs were `{4,4,3,3,5}`/`{3..10}` against planned
   fast-forward times `{30,45,25,30,50}` — not one constant factor, because the explorer stops on *observed
   media position*, and wall-clock elapses during each tool call (observed jumps 16–34 s per +10 s press). §D.
4. Worse: adding runs made the merge **worse**. Dropped columns went 4 → 7 → **21 of 33**; `aligned` fell 5 → 4.
   One 33-step run (run 12, a self-restart after a judge rejection) pumped 9 of the 21 drops and 4 of the 8
   interrupts, and the search-submit click was dropped at **7/8 support** — which is why even the baseline
   value set fails. The structural intersection over N runs is not a safe artifact builder at N = 8. §1.5.
5. `accept_states: []`, so nothing asserted the goal. The passing Dream Theater run is not the counter-example
   it looks like: it passed partly by **silently dropping the timing half of its own task**. §E.
6. **The design.** The agent emits a complete `WorkflowDraft` — states, transitions, params, control, repeats,
   interrupts, accept — but in a vocabulary where **every leaf is a typed reference into the recordings**: a
   locator is `(run, step, rung)`, a param value is `(run, step, field, literal)`, a trigger is chosen from
   observed conditions. No selector, regex, URL or number the LLM wrote ever reaches the artifact. §B.
7. Code *materializes* the draft: it resolves every reference against the stored `AgentStep`s, rejects what it
   cannot re-derive, and falls back **per region** to the merge's own draft. A wrong LLM still cannot produce
   an artifact worse than today's — C.0's asymmetry is preserved while the expressiveness limit is removed. §B.4.
8. Step identity becomes `StepKey(action_type, target_key, occurrence)` computed by the same pure function on
   both sides, carried on `ColumnReport.key`, and stable across rounds. Column indices become a display detail. §C.
9. The merge stops being the artifact builder and becomes the **evidence engine** (alignment, dispositions,
   keys, per-run witnesses) plus the *fallback* artifact. `plan_next` loses `generalization_hints` entirely;
   triage keeps its Episodes as prompt material. Replay stays the only gate, and gains a mandatory non-empty
   `accept_states`. §I.
10. Model: `anthropic:claude-opus-5` at `effort: high` for the draft, the same model for repair, `claude-code:sonnet`
    for subscription-billed dev runs. The whole evidence bundle for MOP is **~50 k tokens** of compact steps —
    the trajectories are not too big; the *observations* were, and they are not what the generator reads. §G, §H.

---

## 0. What this doc does not repeat

- The survey of how each system decides which literal is a parameter — `generator-agent.md` §B.1–B.8.
- The PBD lineage (CoScripter/Koala, Ringer, Rousillon, SMARTedit) — `generator-agent.md` §B.5,
  `generalization-papers.md` §1.
- The LLM-induction line (AWM, ASI, SkillWeaver, WALT, NSI, WebXSkill) — `generator-agent.md` §B.6,
  `generalization-papers.md` §2.
- The typed-key merge rationale and the runs-independence policy — `trajectory-memory.md` §C.
- Judge limits and the authority order (replay > merge > judge) — `agent-verification.md` §6.4,
  `verification-papers.md`.
- Per-stage eval metrics and the `netgent eval bench` spec — `eval-framework.md` §2.2.
- LangGraph structural conventions (functions + one module-level compiled graph; `Runtime[Context]` for live
  resources; `Command` with `Literal` successors) — `langgraph-agent-structure.md` §5.1–5.4.

**Source discipline.** Everything about NetGent is cited by file and line against `v2/closed-loop-rounds`
(HEAD `b60a79a`). Everything about the MOP run is read from the gitignored bundle at
`trajectories/mop/` and quoted verbatim. External claims are cited by URL. Unverified claims are in §L.

---

# 1. The measured failure — MOP, 2026-09-02

Task, verbatim from `mop.trajectories/context.json`:

> Go to youtube.com search for Metallica - Master of Puppets and play the first video that pops up. If an ad
> is shown skip the ad. When the video starts playing watch for 15s then fast-forward for 30s and then watch
> for 20s. If at any point any pop-ups happen dismiss them

`netgent generate --parallel 5 --rounds 3`, model `claude-code:sonnet`. 13 explorations (8 achieved, 2 scoped,
3 not achieved), **≈2.41 M input / 268 k output tokens over 308 LLM calls, ~48 minutes**. Compare the passing
Dream Theater run: 347 k / 31 k over 43 calls, one round, **6 minutes**. Seven times the tokens, eight times
the wall clock, and a broken artifact.

Final line of `generate.log`:

```
✗ replay check failed after 3 round(s): the compiled workflow did not replay identically for every value set
  ([['s1', 's2', 'FAILED@t3'], ['s1', 's2', 'FAILED@t3'], ['s1', 's2', 'FAILED@t3']])
```

## 1.1 Root cause A — the artifact froze one run's video title

`mop.yaml` `t3`, verbatim:

```yaml
- id: t3
  source: s2
  target: s3
  action:
    type: click
    locator:
    - fn: get_by_role
      args: [link]
      kwargs: {name: 'Master of Puppets (Remastered) 8 minutes, 36 seconds'}
```

The merge knew, and shipped it anyway:

```
[merge] WARNING: column 7: click targets differ across runs and match no planned value — kept run 1's
        selector; replay with other values may not find it
```

This is `generator-agent.md` §A.2 P1 exactly, and triage detected it correctly in **all three rounds**
(`positional_target`, `confirmed_by_replay: true`).

Why the ladder could not save it: in MOP the acted element was reached by an accessible-name rung in 6 of the
8 achieved runs; the ladder for those steps carries `candidate_kinds: ["id","role","structural"]` or shorter,
and `_positional_target` (`merge.py` L428-459) requires **the same structural chain and the same index in
every run** — but two runs (2 and 12) clicked `#movie_player > div:nth-of-type(7) > button` (the player's own
control) and one (run 10) used `get_by_title("Billie Eilish - bad guy")`. The column's eight per-run targets
are three *different kinds of thing*. Contrast Dream Theater, where all five runs happened to record the same
structural CSS `div:nth-of-type(1) > div > div:nth-of-type(2) > yt-lockup-view-model > div > a`, so the column
merged `aligned` and no generalization was needed at all (`hint_acceptance_rate: null`, zero hints emitted).

**The Dream Theater pass was luck of locator capture, not a working mechanism.**

## 1.2 Root cause B — the hint channel is addressed by a number that moves

`GeneralizationHint.column: int` (`agent/generator/hints.py` L33). The merge re-aligns **all runs so far**
each round, so the column index of a fixed real-world step drifts as runs are added:

| round | achieved runs | columns | the video click is column | disposition |
|---|---|---|---|---|
| 1 | 3 (1,2,4) | 15 | 4 and 5 (two candidates) | `target-varies` |
| 2 | 5 (+6,7) | 17 | **6** | `target-varies` |
| 3 | 8 (+10,11,12) | **33** | **7** | `target-varies` |

Every hint was therefore rejected. All five rejections, verbatim from `generate.log`:

```
round 2: hint column 11 instance fold: rejected — per-run press counts {1: 4, 2: 4, 4: 3, 6: 3, 7: 5} do not
         match the planned fast_forward_time values {1: 30.0, 2: 45.0, 4: 25.0, 6: 30.0, 7: 50.0} exactly or
         by one constant factor
round 2: hint column 4 positional: rejected — column 4 is not a main-path column of this merge
round 2: hint column 5 positional: rejected — column 5 is not a main-path column of this merge
round 3: hint column 11 instance fold: rejected — column 11 is not a single-signature press column
round 3: hint column 6 positional: rejected — column 6 is not a main-path column of this merge
```

`hint_acceptance_rate`: `null` (r1), **0** (r2), **0** (r3). `hints_applied`: 0, 0, 0.

The planner diagnosed its own channel, in `round-2/next_plan.json` `notes`, verbatim:

> "Prior hints for positional intent were rejected because the column index cited (4 or 5) did not match the
> merge's actual main-path column for that step in the new round (it had shifted to column 6); flagging this
> instability so the column index given here (6, from round 2's numbering) **may again shift** and should be
> matched to whichever column carries the 'target-varies click … first video' episode in the new merge."

It did shift, to 7. The planner had the right hypothesis, the right evidence and the right prose, and **no
type in which to say it**. That is a design defect in the channel, not in the model. §C fixes it.

## 1.3 Root cause C — a gesture whose count is a control loop, not a constant

54 `press("l")` steps across 13 runs. Locator identical in all 54:
`[{fn: locator, args: ["#movie_player > div:nth-of-type(1) > video"]}]`.

| planned `fast_forward_time` | 25 | 30 | 30 | 30 | 40 | 40 | 45 | 50 | 50 | 60 | 60 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| presses recorded | 3 | 4 | 3 | 4 | 6 | 4 | 4 | 5 | 10 | 6 | 5 |

No monotone relation, let alone a constant factor. The reason is in the explorer's own prompt (`agent/explorer/prompt.py` L85-92), which *instructs* an adaptive
verify-and-count loop: *"send the seek key (one press per step) and VERIFY each press landed … keep pressing
until it reaches N."* A +10 s seek key, observedDownstream, the presses scatter across **five** merge columns (27–31 in round 3) with supports 2, 6, 8, 8, 8.
Only the 8/8 intersection survives, so the artifact hardcodes exactly three presses = 30 s regardless of
`fast_forward_time`, and `fast_forward_time` never became a `Param` at all (`mop.yaml` has three params:
`video_query`, `initial_watch_time`, `second_watch_time`).

## 1.4 Root cause D — no postcondition

```
[generate] compiled 18 transitions, 25 states, 8 interrupt(s), accept_states=[]
```

`merge.py` L1108 sets `accept = [final.id] if final.conditions else []`. MOP's final main state had no
intersected conditions, so the gate degraded to `success = every edge ok` (`schema/workflow.py` L90-91) — the
oracle SkillWeaver's authors document being gamed (`generator-agent.md` §B.6.3).

And the counter-example cuts the other way too: Dream Theater *passed* with `accept_states: [s4]`, four
transitions, one param — having **silently dropped `watch_time`** (its dwell column was present in 4/5 runs and
dropped as "removable"). The passing artifact does not implement the timing half of the task it was compiled
from. A gate that accepts that is not measuring the goal either.

## 1.5 Root cause E — the structural intersection degrades as N grows, and one bad run poisons it

This is the finding the earlier design did not anticipate, and it is the strongest argument for §B.

| round | achieved runs | columns | aligned | param | target-varies | interrupt | **dropped** |
|---|---|---|---|---|---|---|---|
| 1 | 3 | 15 | 5 | 3 | 2 | 1 | 4 |
| 2 | 5 | 17 | 5 | 3 | 1 | 1 | 7 |
| 3 | **8** | **33** | **4** | 3 | 1 | 4 | **21** |

More evidence produced a *worse* artifact: 64 % of round-3 columns dropped, `aligned` down from 5 to 4.

Two mechanisms:

**(a) A single anomalous run pollutes everything.** Run 12 is 33 steps — twice any other run — because after a
judge rejection it *restarted the whole task from inside the browser*. Its own reasoning:

> "the only way to properly demonstrate an explicit ad-skip is to restart the search flow via the YouTube Home
> link and redo the whole flow … I'll click YouTube Home to restart."

That single run contributed **9 of round 3's 21 dropped columns** and **4 of the 8 interrupts** (`YouTube Home`,
a Blinding Lights link twice, the search-submit button). It was `achieved: true` — the judge was right that the
task got done — so nothing excluded it from the merge spine.

**(b) The interrupt classifier is "any 1-of-N click".** `merge.py` L487-496 (`_dismissal_step`) accepts a click
whose *target OR reasoning* looks like a dismissal, and the presence gap does the rest. Round 3 emitted 8
interrupts, of which only `No thanks` (support 8) and `Skip ad` (support 2) are real; **five have support 1**,
including `role=link[name="YouTube Home"]`, a related-video link, and
`#center > yt-searchbox … > button` — the search-submit control. Two of them became `int4` and `int8` with scopes `[s1, s2]` and
`[s1]` — armed on the *first* page. On replay they fire, their `selector_hidden` done-state never holds, and
each burns `max_fires: 3` × 10 s:

```
"error": "state 'i4_done' not recognized within 10000ms; unmet conditions: ['selector_hidden']"
```

Every MOP replay spends **~63 s of its ~104 s** on six phantom interrupt timeouts before reaching the search
box. Column 23 is the worst single artifact: it fuses an ad-skip button, a related-video thumbnail and *the
search-submit button* into one "interrupt" at support 5.

**(c) The intersection deletes load-bearing steps.** The search-submit click was present in 7 of 8 runs and
dropped:

```
[merge] WARNING: column 2: click present in 7/8 runs — the other runs achieved the task without it; dropped
```

One dissenting run (which pressed Enter instead) removed the step that makes the results page appear. **This is
why even the Metallica replay fails at `t3`**: the results page never rendered.

## 1.6 What the five causes have in common

| # | cause | who could have decided it | why code could not |
|---|---|---|---|
| A | title vs position | the task text ("the first video that pops up") | both compile to a `ClickAction` |
| B | which step a hint means | any stable name for the step | `column: int` is not one |
| C | N presses = one gesture with a param count | the reasoning + the MEDIA readings | counts are latency noise; the ratio rule can never fire |
| D | what "done" looks like | the task text + the final observations | intersection produced nothing |
| E | which runs and which steps belong in the artifact | the reasoning ("restart the whole flow"), the run's shape | support thresholds are the wrong statistic |

Rows A, C, D are `generator-agent.md`'s P1/P4/V11 — already known. Row B is a type error. **Row E is new, and
it is the one the patch channel structurally cannot fix**: no per-column edit can say *"run 12 is a restart,
exclude it"*, or *"keep column 2 even though one run skipped it"*, or *"columns 27–31 are one gesture"* — the
last of which changes the numbering of every column after it, which is precisely how a column-indexed patch
eats itself.

---

# A. Architecture — `agent/generator/` becomes an agent package

The repo already has the shape twice (`agent/explorer/`, `agent/verifier/`) and
`langgraph-agent-structure.md` §5.1 states the rule: *a class exists only when it owns a live resource;
everything graph-shaped is a function; the unit of composition is a compiled graph.* The generator owns no
live resource — it reads stored pydantic values and calls the LLM seam — so it is **all functions plus one
module-level compiled graph**.

```
v2/src/netgent/agent/generator/
├── __init__.py      # lazy re-export of GENERATOR / create_generator_agent / generate (PEP 562), like verifier/
├── compiler.py      # unchanged: one trajectory → NFA (still the N=1 path and the unit-test fixture)
├── merge.py          # KEEPS the alignment; loses the "artifact builder" job (§I). Gains ColumnReport.key
├── hints.py          # DELETED (see §I) — its HintOutcome shape moves to draft.py as DraftOutcome
├── draft.py         # NEW: the WorkflowDraft schema (§B.2) — pure pydantic, no langchain, no langgraph
├── materialize.py   # NEW: draft + recordings → Workflow, with per-item outcomes (§B.4). Pure code, zero LLM
├── evidence.py      # NEW: recordings + merge report + episodes → the compact Evidence value (§G.2). Pure
├── context.py       # NEW: GeneratorContext (llm, recordings, merge report, episodes, budget) — Runtime.context
├── models.py        # NEW: Evidence, DraftOutcome, GenerateOutcome (the node values)
├── prompt.py        # NEW: GENERATOR_SYSTEM, REPAIR_SYSTEM, build_generator_content, build_repair_content
├── agent.py         # NEW: GeneratorAgent — thin façade holding the knobs, like VerifierAgent
└── graph.py         # NEW: the StateGraph; imports langgraph at module level (only file in the pkg that may)
```

## A.1 The node loop

```
START → gather ──► draft ──► materialize ──► {END | repair}
                     ▲                          │
                     └──────── repair ◄─────────┘   (bounded: max_repairs, default 2)
```

```python
class GeneratorState(TypedDict, total=False):
    task: str
    evidence: Any            # Evidence (gather's output) — pure, cacheable, no LLM
    draft: Any               # WorkflowDraft (the LLM's output)
    outcome: Any             # GenerateOutcome: workflow + per-item DraftOutcomes + warnings
    rejections: list[str]    # what materialize refused, verbatim, for the repair turn
    repairs: int
```

| node | LLM? | contract |
|---|---|---|
| `gather` | no | recordings + merge report + episodes + prior rounds → `Evidence` (§G.2). Deterministic, so it is unit-testable and the whole prompt is reproducible offline from a stored bundle. |
| `draft` | **yes** (1 call) | `Evidence` → `WorkflowDraft`, via `llm.judge(GENERATOR_SYSTEM, content, WorkflowDraft)` — the existing structured-output seam, no new dependency. |
| `materialize` | no | `WorkflowDraft` + recordings → `Workflow` + `list[DraftOutcome]`. Every rejection is recorded, never fatal (§B.4). Routes to `END` if nothing was rejected **or** `repairs == max_repairs`; else to `repair`. |
| `repair` | **yes** (≤ `max_repairs` calls) | the rejections, verbatim, plus the surviving draft → a revised `WorkflowDraft`. This is CEGIS with the validator as the counter-example generator; it is the one place the agent gets to *see why code said no*. |

**Why a repair loop and not one shot.** MOP's five rejections were all *legible*: "column 4 is not a main-path
column", "counts do not match by one constant factor". Those are exactly the messages a model can act on, and
the closed loop needed a whole extra round (~15 minutes, ~800 k tokens) to try again. A repair turn costs one
LLM call and zero browser time. Bound it at 2 and record `repairs_used` per compile.

**What the agent does *not* get:** no browser, no tools that touch the page, no ability to run a replay. The
replay gate stays outside the agent, in the orchestrator, unchanged (§I). This keeps `agent/generator/` free of
`browser/` at run time and keeps the import boundary test green.

## A.2 The read-only accessors

The agent is a **single structured call over a rendered prompt**, not a tool-using ReAct loop. Reason: the
whole evidence bundle for MOP is ~50 k tokens of compact steps (§G.3) and fits; a tool loop would add turns,
latency and non-determinism for no information gain, and `langgraph-agent-structure.md` §5.4 already refuses
`create_agent` for pipeline stages whose input is fully known up front. If a future task family exceeds the
budget, the escape hatch is `gather` sampling more aggressively, not a tool loop.

What `gather` exposes, all from values already on disk:

| accessor | source | new? |
|---|---|---|
| per-step compact line (action, target, value, media, one-clause reasoning) | `AgentStep` | rendering only |
| per-step locator ladder (rung index, kind, match count, match index) | `AgentStep.locator_candidates/candidate_kinds/match_counts/match_indices` | shipped (M0) |
| cross-run alignment: columns with per-run targets/values and dispositions | `GeneralizedTrajectory.columns` | shipped |
| stable column identity | `ColumnReport.key` | **new, §C** |
| prior rounds' episodes and what each draft item did last round | `RoundRecord.episodes`, `RoundRecord.draft_outcomes` | shipped / renamed |
| replay records: which edge failed, unmet conjuncts, per-value-set | `ReplaySummary` | shipped |
| the judge's unmet points | `RunSummary.unmet` | shipped |
| planner values per run | `RunSummary.values` | shipped |
| final observations / texts seen / final URL / media readings | `AgentTrajectory` | shipped |

`GeneratorContext` (frozen dataclass, `Runtime.context`, never checkpointed — the verifier's shape):

```python
@dataclass(frozen=True, slots=True)
class GeneratorContext:
    llm: "LLM"
    runs: tuple[RunInput, ...]                 # every achieved run, in run order (run 1 is the spine)
    generalized: "GeneralizedTrajectory"       # the merge's evidence trail (alignment + dispositions + keys)
    fallback: "Workflow"                       # the merge's own artifact: what a fully-rejected draft returns
    episodes: tuple[Episode, ...] = ()
    replay: "ReplayReport | None" = None
    prior: tuple["RoundRecord", ...] = ()      # earlier rounds, for the "you already tried this" block
    max_repairs: int = 2
    max_steps_shown: int = 400                 # the sampling red line (§G.3)
```

---

# B. What the agent emits — a full draft, in pointers

## B.1 The decision, argued from the evidence

`generator-agent.md` §C.8 compared *"LLM writes the workflow"* against *"LLM emits a typed patch"* and picked
the patch, on one row: **failure mode**. That reasoning is still correct and this design does not abandon it.
What MOP proves is that the patch's *addressing and vocabulary*, not its failure mode, were the binding
constraint:

| MOP failure | expressible as a per-column patch? |
|---|---|
| A: title → position | yes (and it was proposed, three times) |
| B: which column | **no** — the addressing scheme is the bug |
| C: 5 press columns are one gesture with a derived count | **no** — folding renumbers every later column, so a batch of column-indexed hints is self-invalidating; and the required count is `ceil(t/10)`, which no `count_param` field can express |
| D: accept states | no vocabulary existed (`Expectation` was designed in §C.3 and never implemented) |
| E: exclude run 12; keep the 7/8 search-submit click; do not make five 1-of-N clicks interrupts | **no** — these are statements about *which evidence composes the artifact*, which has no column |

Three of five are inexpressible, and each would need a *new hint kind + a new triage episode kind + a new
merge applier branch* — three code sites per generalization, forever. That is the real cost of the patch: the
vocabulary is closed at design time, and every site teaches us a new kind of intent.

**So: the agent emits the whole artifact.** The failure-mode row is preserved by a different mechanism —
**the draft contains no free-form content at all.** Every leaf is a typed pointer into an immutable recording,
and `materialize` resolves each pointer independently, falling back **per region** to the merge's artifact for
anything it cannot resolve. The worst case is still "the merge's output plus a warning list", exactly as §C.0
promised; the expressiveness ceiling is gone.

Concretely, the draft may not contain: a selector string, a CSS path, a regex, a URL, a key name, a timeout, a
state id, a transition id, a `max_iterations`, a `max_fires`, an `nth` the recordings did not measure, or any
number that is not either a recorded value or a planner-declared value. It contains: run ids, step
coordinates, rung indices, param names, and `why` clauses.

This is Rousillon's containment test and Skyvern's post-SKY-8965 shape applied to the *whole artifact* rather
than to a patch over it — and it is what none of the surveyed systems do: Workflow Use has the LLM write
selectors (`generator-agent.md` §B.1), Skyvern forbids the LLM from choosing at all (§B.3.3), and nobody makes
the artifact itself reference-only.

## B.2 The schema (`agent/generator/draft.py`)

```python
"""The WorkflowDraft: a complete workflow whose every leaf is a POINTER into the recordings.

The LLM may choose structure (which steps, in what order, what loops, what is an interrupt, what
"done" means) and it may choose among options the browser layer already computed (which rung of a
locator ladder, which recorded literal is a param). It may never author content: no selector, no
regex, no URL, no id, no bound, no number the recordings do not contain. `materialize.py` resolves
every pointer against the stored AgentSteps and rejects, per item, what it cannot re-derive.
"""

from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

# ── addressing ───────────────────────────────────────────────────────────────

StepRef = Annotated[str, Field(pattern=r"^r\d+\.s\d+\.\d+$",
    description="A recorded step: r<run>.s<AgentStep.n>.<AgentStep.item>. Recordings are immutable, "
                "so this address is stable across rounds — unlike a merge column index.")]


class LocatorRef(BaseModel):
    """Which rung of a recorded step's ladder to use, and how to close it."""
    step: StepRef
    rung: int = Field(default=0, ge=0,
        description="Index into that step's locator_candidates (0 = the chain the explorer used).")
    nth: int | None = Field(default=None, ge=0,
        description="Append .nth(i) — 'the i-th match of this rung'. Only for a rung the recordings "
                    "measured as resolving to > i elements with the acted element AT index i.")
    name_param: str | None = Field(default=None,
        description="For a get_by_role rung only: replace the accessible name with ${param}. The recorded "
                    "name must contain that run's value of the param, in every run.")


# ── parameters ───────────────────────────────────────────────────────────────

class ParamWitness(BaseModel):
    """The literal this param took in ONE recorded step. No witness, no param."""
    step: StepRef
    field: Literal["text", "value", "url", "seconds", "press_count", "media_jump"]
    literal: str = Field(description="EXACTLY the substring/number recorded in that field of that step.")


class DraftParam(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["user", "page", "derived"] = "user"
    witnesses: list[ParamWitness] = Field(default_factory=list, min_length=0)
    # kind="derived": computed from another param at replay time, never supplied by the caller.
    # This is how "fast-forward 30s" becomes "3 presses" without the caller ever seeing presses (§D).
    derived_from: str | None = None
    divide_by: float | None = Field(default=None, gt=0)
    rounding: Literal["ceil", "floor", "nearest"] = "ceil"
    why: str = ""


# ── the control program ──────────────────────────────────────────────────────

class DraftEdge(BaseModel):
    kind: Literal["edge"] = "edge"
    step: StepRef = Field(description="The recorded step whose ACTION this transition carries.")
    target: LocatorRef | None = Field(default=None,
        description="None: keep the recorded chain. Set: use this rung instead (positional / text-param).")
    value_param: str | None = Field(default=None,
        description="Bind this action's value field to ${param}. The param must have a witness on THIS step.")
    corroborated_by: list[StepRef] = Field(default_factory=list,
        description="The same real step, as recorded in the OTHER runs. One per achieved run where it "
                    "occurred. This is what lets code check support without a column index.")
    why: str = ""


class CountSpec(BaseModel):
    """How many times a Repeat runs."""
    constant: int | None = Field(default=None, gt=0)
    param: str | None = Field(default=None, description="A DraftParam name; its value is the iteration count.")


class DraftRepeat(BaseModel):
    kind: Literal["repeat"] = "repeat"
    body: list["DraftNode"]
    count: CountSpec
    covers: list[StepRef] = Field(default_factory=list,
        description="EVERY recorded step, in every run, that this Repeat replaces. Code checks that they "
                    "are contiguous per run, share one action signature, and occur in every kept run.")
    why: str = ""


class DraftBranchArm(BaseModel):
    when: StepRef = Field(description="The step whose target's visibility guards this arm.")
    then: list["DraftNode"]
    runs: list[int] = Field(description="The runs that took this arm.")


class DraftBranch(BaseModel):
    kind: Literal["branch"] = "branch"
    arms: list[DraftBranchArm] = Field(min_length=2)
    why: str = ""


DraftNode = Annotated[Union[DraftEdge, DraftRepeat, DraftBranch], Field(discriminator="kind")]


# ── interrupts, accept, run policy ───────────────────────────────────────────

class DraftInterrupt(BaseModel):
    """A pop-up/ad handler. Code builds the anchor state, the done state, the resolve edge, the scope
    and max_fires; the LLM supplies only the classification and the evidence."""
    step: StepRef = Field(description="A recorded click that DISMISSED something.")
    rung: int = 0
    also_seen: list[StepRef] = Field(default_factory=list, description="The same overlay in other runs.")
    why: str = Field(description="What the reasoning or the task text says this dismisses.")


class DraftCondition(BaseModel):
    """A state condition, named by the recorded step that WITNESSES it. Code derives the predicate's
    content (the URL pattern, the selector, the duration threshold) from that step; the LLM never
    writes a pattern."""
    type: Literal["url_matches", "selector_visible", "selector_hidden", "media_playing"]
    witness: StepRef
    rung: int = 0          # for selector_visible/hidden: which rung of that step's ladder
    playing: bool = True   # for media_playing
    why: str = ""


class ExcludedRun(BaseModel):
    run: int
    reason: Literal["restarted", "off_task_detour", "truncated", "duplicate_of_another_run"]
    evidence: StepRef = Field(description="The step that shows it (e.g. the click that restarted the flow).")
    why: str = ""


class WorkflowDraft(BaseModel):
    spine: int = Field(description="The run whose step order the main path follows.")
    kept_runs: list[int] = Field(description="Runs that corroborate the main path (includes the spine).")
    excluded: list[ExcludedRun] = Field(default_factory=list)
    params: list[DraftParam] = Field(default_factory=list)
    main: list[DraftNode] = Field(default_factory=list)
    interrupts: list[DraftInterrupt] = Field(default_factory=list)
    accept: list[DraftCondition] = Field(default_factory=list, min_length=1)
    notes: list[str] = Field(default_factory=list,
        description="What you considered and rejected, and anything the evidence could not settle.")


DraftRepeat.model_rebuild(); DraftBranchArm.model_rebuild()
```

Design notes, each traceable to §1:

- **`StepRef` addresses recordings, not columns.** A trajectory is written once and never rewritten, so
  `r1.s10.0` means the same thing in round 1 and round 3. Root cause B cannot recur. §C.
- **`corroborated_by` replaces the support threshold.** The agent states which runs did this step; code
  checks the claim. Root cause E(c) — the 7/8 search-submit drop — becomes an explicit, checkable claim
  instead of a silent statistical rule.
- **`excluded` is the answer to run 12.** It costs one `ExcludedRun` with a pointer to the restart click.
- **`covers` on `DraftRepeat` is the fold's witness set.** It makes the fold checkable *and* removes the
  renumbering hazard: the LLM writes the whole program, so there are no later indices to invalidate.
- **`DraftParam.kind="derived"`** is the fast-forward answer; §D argues it and prices the schema change.
- **`accept` has `min_length=1`.** A draft with no postcondition does not parse. This is V11
  (`generator-agent.md` §C.4) promoted from a validator rule into the type.
- **`title_contains` and `dialog_matches` are deliberately absent** from `DraftCondition`: `AgentStep` records
  neither a page title nor a per-state dialog we can witness offline. Adding either means recording it first.

## B.3 The check-against-recording invariants (`materialize.py`)

Every rule is offline: stored `AgentStep`s only, no browser, no model. Each violation produces a
`DraftOutcome(item, status="rejected", reason=…)` and a **local** fallback; none is fatal.

| # | rule | what it stops |
|---|---|---|
| **M1** | *Ref resolution.* Every `StepRef` must name an existing `(run, n, item)` with `action is not None` and `error is None`, in a kept run. | hallucinated coordinates |
| **M2** | *Spine coherence.* `spine ∈ kept_runs`; `len(kept_runs) ≥ 2` when ≥2 runs achieved; every `DraftEdge.step` belongs to the spine, in strictly increasing `(n, item)` order. | a main path stitched out of order or out of several runs |
| **M3** | *Exclusion budget.* `len(excluded) ≤ ⌊N/3⌋` and ≥3 achieved runs must remain (≥2 if only 3 achieved). An `ExcludedRun.evidence` step must belong to that run. | the agent excluding its way to a trivially-consistent artifact |
| **M4** | *Corroboration.* For each `DraftEdge`, every `corroborated_by` ref must be in a kept run ≠ spine and have the **same `_sig`-shape** (action type + `_target_shape`) as the spine step. An edge corroborated by 0 other runs is kept but flagged `singleton` (it is legal — the search-submit click was one — and it is what the replay gate then tests). | fabricated support |
| **M5** | *Ladder rungs only.* `LocatorRef.rung < len(step.locator_candidates)`; the emitted chain is `locator_candidates[rung]` **verbatim**. No chain is ever assembled from parts. | LLM-authored selectors (§B.1) |
| **M6** | *Ordinals must be measured.* `nth=i` requires `match_counts[rung] > i` **and** `match_indices[rung] == i`, in the spine **and in every corroborating run**. Otherwise reject and keep the recorded chain. | "click the first one" wishful thinking; this is `_positional_target` (`merge.py` L428-459) generalized off the column |
| **M7** | *Name params are containment-checked.* `name_param=p` requires the rung's last step to be `get_by_role(..., name=X)` and, **for every kept run**, that run's declared value of `p` to be a case-insensitive substring of that run's recorded name. This is `_generalize_target` (`merge.py` L384-426) with the column replaced by the corroboration set. | the P1-inverse error: parameterizing a name that does not track the value |
| **M8** | *Literal witness.* Every `DraftParam(kind="user")` needs ≥1 `ParamWitness` whose `literal` is recoverable from the named field of the named step under a **closed** transform set — `identity`, `quote_plus`, `_number_in` numeric equality — and, for a multi-run merge, a witness in **every** kept run whose declared value differs. Values shorter than 3 chars or in the stop-list are refused (raise `_MIN_VALUE_LEN` 2→3, `generator-agent.md` §C.9 #2). | hallucinated params; `generator-agent.md` §C.4 V1/V3 |
| **M9** | *Provenance.* `kind="user"` requires the literal to appear in the task text or in a planner `values` entry; `kind="page"` requires it in `texts_seen` and **not** in the task, and compiles to a dynamic `Param` with a `ParamSource`. A mislabeled `user` is downgraded to `page` with a warning. | §C.4 V2, unchanged |
| **M10** | *Derived params.* `kind="derived"` requires `derived_from` to name a `user` param, `divide_by > 0`, and **≥3 `media_jump` witnesses across ≥2 kept runs** agreeing with `divide_by` to within ±40 % (§D.3). The emitted `Param` carries `derive` and no caller-facing default of its own. | inventing "10 seconds per press" |
| **M11** | *Repeat folds.* `covers` must, per kept run, be contiguous in that run's step order (scroll-only gaps allowed, as `merge.py` L574-576 already does), share one `_sig`, and be non-empty in **every** kept run. `count.param` must resolve; `count.constant` must equal the spine's cover count. `max_iterations` is set by code to `max(10, 3 × max per-run count)`; the LLM never supplies it. | `generator-agent.md` §C.4 V7, off the column |
| **M12** | *Interrupts are dismissals.* The step's action must be a `click`; its chosen rung must be expressible as a selector and must **not** be volatile (`is_volatile_selector`); and — the new rule — **the click must not have changed the page's base URL** in its own run (`_step_effects`, `merge.py` L183-199, already computes this). A dismissal keeps you where you were. | root cause E(b): "YouTube Home", the Blinding Lights link and the search-submit button all changed the base URL and all became interrupts |
| **M13** | *Accept is witnessed.* `url_matches` → code emits `^` + `re.escape(base_url(witness.url))` (a base-URL prefix, never an LLM regex); `selector_visible/hidden` → the rung must resolve to ≥1 element at capture time (`match_counts[rung] ≥ 1`); `media_playing` → the witness step's `media` must contain a `PLAYING` reading, and `min_duration_s` is set by code to half the observed duration, capped, exactly as `_gate_media_states` does (`compiler.py` L156-181). Unwitnessed conditions are dropped; if **all** are dropped the compile reports `not-validated (no postcondition)`. | §C.4 V8/V11 |
| **M14** | *Param closure + schema escape.* Every `${name}` reaching the artifact has a `Param`; every `Param` is referenced; names match `^[a-z][a-z0-9_]*$` and avoid a reserved set; the result is re-validated by pydantic (`validate_locator_chain`, `_validate_graph`). Violations here are **errors**: the offending param is dropped and the draft re-materialized. | §C.4 V9/V10 |

**What is deliberately *not* checked:** whether the agent's *ordering* is the best one, whether a `Branch` is
warranted, whether an interrupt is truly needed. Those are structure, they are cheap to be wrong about
(a spurious interrupt costs a bounded sweep), and **the replay gate is what grades them**.

## B.4 Materialization, and the per-region fallback

```python
def materialize(draft: WorkflowDraft, ctx: GeneratorContext) -> GenerateOutcome:
    """draft + recordings → Workflow. Never raises on a bad draft; records what it refused."""
```

Order of operations:

1. **Resolve the run policy** (M2, M3). If it fails, fall back to the merge's `kept_runs` and continue —
   the draft's *structure* may still be good.
2. **Resolve params** (M8–M10) into `schema.control.Param`s. A rejected param is dropped; every
   `value_param`/`name_param`/`count.param` that referenced it degrades to its recorded literal (M14).
3. **Walk `main`**, emitting one `EdgeStep`/`Repeat`/`Branch` per node. Per node:
   - a rejected `LocatorRef` (M5–M7) → keep the recorded chain, record the reason;
   - a rejected `DraftRepeat` (M11) → **emit its `covers` as individual edges from the spine**, i.e. exactly
     today's behaviour for that region;
   - a rejected `DraftBranch` → emit the spine arm only.
4. **States** are built by the existing anchoring rule (`compiler.py`: a state anchors on the *next* edge's
   target), plus the media gate. Ids (`s1…`, `t1…`, `int1…`) are assigned by code. `Interrupt.scope` is derived
   from base URLs and `max_fires=3`, unchanged.
5. **Accept** (M13). If the surviving set is empty, `outcome.validated = False` and the orchestrator reports
   `not-validated (no postcondition)` rather than shipping.
6. **Whole-draft floor.** If < 50 % of `main` nodes materialized, return `ctx.fallback` (the merge's artifact)
   with `outcome.used_fallback = True`. This is the C.0 guarantee, made explicit and measurable.

```python
class DraftOutcome(BaseModel):
    """What materialize did with one draft item — the evidence trail behind draft_acceptance_rate.
    Same role, and same JSON shape, as the retired HintOutcome (hints.py L49-62)."""
    item: str                      # "main[3].target", "params[1]", "interrupts[0]", "accept[0]"
    ref: StepRef | None = None
    status: Literal["applied", "rejected", "degraded"]
    reason: str = ""
    transition: str | None = None  # the edge it landed on


class GenerateOutcome(BaseModel):
    workflow: Workflow
    draft: WorkflowDraft | None
    outcomes: list[DraftOutcome] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated: bool = True
    used_fallback: bool = False
    repairs_used: int = 0
```

`acceptance_rate(outcomes)` keeps its meaning and its place in `RoundRecord` and `context.json`, so the
eval bench's `hint_acceptance_rate` column becomes `draft_acceptance_rate` with no schema surgery
(`eval-framework.md` §2.2 stage 7).

---

# C. Step identity across rounds

Two different addressing problems, two different answers. Conflating them is what produced root cause B.

## C.1 The draft addresses *recordings*: `StepRef`

`r<run>.s<n>.<item>`. A trajectory is written once by `explore()` and never rewritten; `AgentStep.n` is the
LLM step that produced it and `item` its position in that step's batch. Nothing downstream can renumber it.
This is the whole of the draft's addressing, and it is why the draft is immune to the merge's re-alignment.

Rendering and parsing are three lines in `draft.py`:

```python
_REF = re.compile(r"^r(\d+)\.s(\d+)\.(\d+)$")

def ref_of(run: int, step: AgentStep) -> StepRef:
    return f"r{run}.s{step.n}.{step.item}"

def resolve(ref: StepRef, runs: dict[int, RunInput]) -> tuple[int, AgentStep] | None:
    m = _REF.match(ref)
    if m is None: return None
    rid, n, item = int(m[1]), int(m[2]), int(m[3])
    run = runs.get(rid)
    if run is None: return None
    return next(((rid, s) for s in run.trajectory.steps if s.n == n and s.item == item), None)
```

## C.2 Episodes and cross-round memory address *columns*: `StepKey`

Triage speaks about columns, and an episode must be recognizable next round even though the column moved
(4/5 → 6 → 7). The key must therefore depend on the *kind* of step, not on its instance or its position:

```python
class StepKey(BaseModel):
    """A durable name for an aligned column: (action type, target SHAPE, occurrence among like columns).

    The shape — not the instance — is what survives a value change: the MOP video click is
    ("click", "get_by_role:link", 0) whether the recorded name is Metallica or Linkin Park, which is
    exactly the case where `_canonical_locator` is unstable by construction.
    """
    action: str                    # column.action_type
    shape: str                     # "|".join(str(x) for x in _target_shape(spine_action))
    occurrence: int = 0            # index among MAIN-PATH columns with the same (action, shape)

    def render(self) -> str:
        return f"{self.action}:{self.shape}#{self.occurrence}"
```

`_target_shape` already exists (`merge.py` L168-181: last locator fn + role, `nth` ignored). Three additions,
each a few lines:

1. `ColumnReport.key: str` — set in `report()` (`merge.py` L602-614) after the emit plan is built, so
   `occurrence` counts only main-path columns.
2. `Episode.key: str` — copied from the column, alongside the existing `column: int` (kept for display).
3. `RoundRecord.key_index: dict[str, int]` — the key → column map for this round, so a reader can follow a key
   through `context.json`.

Stability, honestly stated: the key is stable under adding runs, renumbering, and inserting different steps.
It is **not** stable if the spine run changes (the shape is read off the spine's action) or if the prefix gains
another column of the same shape. Both are visible — the key simply fails to match and the episode reads as
new — and neither is silent, which is the whole improvement over `column: int`. The draft never depends on it.

## C.3 Provenance

Every `DraftOutcome` carries the `StepRef` it acted on; every `ColumnReport` carries its `StepKey` and its
`targets_by_run`. Together these let a reader answer, from `context.json` alone: *which recorded step became
which transition, under which claim, and what happened to it on replay* — which is the trail
`agent-verification.md` §6.4 asks for and which the MOP bundle can only reconstruct by hand.

---

# D. The varying-gesture problem (fast-forward)

## D.1 Why the current rule can never fire

`_make_fold` (`merge.py` L733-784) binds a count param only when the per-run press counts equal the planned
values, or equal them divided by **one constant integer factor in every run**. MOP's data:

```
counts  {1: 4, 2: 4, 4: 3, 6: 3, 7: 5}
planned {1: 30, 2: 45, 4: 25, 6: 30, 7: 50}
ratios  {7.5,  11.25, 8.33, 10,   10}
```

There is no such factor, and there never will be, because **the press count is not a function of the
parameter**. The explorer runs a closed loop on observed media position (`explorer/prompt.py` L85-92), and the
YouTube `l` key adds 10 s while the tool call itself takes 6–24 s of real playback, so the observed jump per
press is 16–34 s and the agent's stop condition fires after an unpredictable number of presses. Across 13 runs:
`30 s → {3, 4, 4}`, `40 s → {4, 6}`, `50 s → {5, 10}`, `60 s → {5, 6}`.

Counts are the wrong evidence. The right evidence is already recorded and unused.

## D.2 The signal: `media` + `t`

Every `AgentStep` carries `media` (the reading taken **just before** the step ran, e.g.
`"video PLAYING at 0:28 / 8:35"`) and `t` (epoch seconds when the record was made). For two consecutive press
steps *k*, *k+1* in one run:

```
seek_k  =  pos(k+1) − pos(k)  −  (t(k+1) − t(k))
```

— position advanced, minus what plain playback would have advanced. On MOP's run 1 this is ≈ +10 s per press,
which is exactly the site's seek step, and it is **the number the artifact needs**. The agent's own reasoning
says the same thing in prose (run 1, n=11: *"Video went from ~0:19 … to 0:39 now, confirming two verified +10 s
seeks (jumps so far: 10+10 = 20 of 30)"*), but prose is not checkable and the arithmetic is.

`compiler.py` already parses this format (`_MEDIA_READING_RE`, `_media_readings`, L146-154) for the media gate;
the seek computation is ~10 lines beside it.

## D.3 What the agent says, and what code checks

The agent emits, for the block of presses:

```jsonc
{"kind": "repeat",
 "count": {"param": "fast_forward_presses"},
 "covers": ["r1.s10.0","r1.s11.0","r1.s12.0","r1.s13.0", "r2.s9.0", ..., "r7.s13.0"],
 "why": "the task asks to fast-forward for ${fast_forward_time}; each 'l' press seeks +10s (the runs' media readings show it), so the count is fast_forward_time / 10",
 "body": [{"kind": "edge", "step": "r1.s10.0"}]}
```
```jsonc
{"name": "fast_forward_presses", "kind": "derived", "derived_from": "fast_forward_time",
 "divide_by": 10, "rounding": "ceil",
 "why": "one 'l' press = +10s, measured from the media readings between consecutive presses"}
```

**M10, the validator, in full.** The LLM claims `divide_by`; code re-derives it:

1. For every kept run, take the `covers` steps of that run in order. For each adjacent pair with a parsable
   `media` reading and a `t`, compute `seek_k` as above.
2. Require **≥ 3 usable pairs across ≥ 2 kept runs**.
3. Require the **median** `seek_k` to be within **±40 %** of `divide_by`. (Wide, deliberately: the readings are
   sampled at snapshot time, not at key-press time, and a buffering stall makes one pair useless. A tight band
   would recreate the failure it replaces.)
4. Require, per run, `1 ≤ count ≤ ⌈planned / divide_by⌉ + 2` — an *overshoot band*, not an equality. This is
   the only role counts play: a sanity check that the run really was doing this gesture.
5. On success emit `Param(name=…, derive=ParamDerivation(from_param="fast_forward_time", divide_by=10,
   rounding="ceil", min=1))` and `Repeat(count="${fast_forward_presses}", max_iterations=max(10, 3×max_count))`.
6. On failure: reject the fold, emit `covers`'s spine steps as individual edges — i.e. exactly today's output.

Steps 1–4 are pure functions of stored `AgentStep`s. No browser, no model, no tolerance on the *count*.

## D.4 The schema change this needs, and the alternative

`Repeat.count` takes an int or a `"${param}"` string; there is no arithmetic. Two ways out:

**(a) Make the artifact's param the count** (`generator-agent.md` §C.9 #1's recommendation, "honest and needs
no schema change"). Rejected now, on evidence: the caller's vocabulary would diverge from the task's, and every
downstream number is keyed to the task's vocabulary — `select_replay_sets` (`orchestrator.py` L303-319) builds
metamorphic value sets from the *planner's* names, and `eval-framework.md` §2.2 stage 4 scores `param_recall`
against the suite's declared params. A workflow whose knob is `fast_forward_presses=3` cannot be replayed
against "fast-forward for 45 s", so **the very generalization we are trying to test becomes untestable**.

**(b) A derived param.** ~30 lines, in two files:

```python
# schema/control.py
class ParamDerivation(BaseModel):
    """A param COMPUTED from another param at resolve time — never supplied by the caller.

    The bridge between the task's vocabulary ("fast-forward 45 seconds") and the artifact's
    ("press `l` five times"), for gestures whose unit the recordings measured. Closed and tiny
    on purpose: one source param, one divisor, one rounding rule, a floor. No expressions.
    """
    from_param: str
    divide_by: float = Field(default=1.0, gt=0)
    rounding: Literal["ceil", "floor", "nearest"] = "ceil"
    min: int = Field(default=1, ge=0)

class Param(BaseModel):
    ...
    derive: ParamDerivation | None = None   # set ⇒ required=False and the caller may not pass it

# schema/workflow.py::resolve_params — after the static pass, before substitution:
for p in workflow.params:
    if p.derive is None: continue
    src = resolved.get(p.derive.from_param)
    if src is None: continue
    n = _number_in(src)
    if n is None: continue
    q = n / p.derive.divide_by
    q = math.ceil(q) if p.derive.rounding == "ceil" else math.floor(q) if p.derive.rounding == "floor" else round(q)
    resolved[p.name] = str(max(p.derive.min, int(q)))
```

**Recommend (b).** It keeps the caller's knob equal to the task's knob, which is what replay must vary, and it
generalizes beyond seeks (pagination "load 60 results" at 20 per page; "scroll 5 screens").

## D.5 Should the explorer be constrained to press deterministically?

Three options, and the recommendation is a split.

| option | effect | cost |
|---|---|---|
| **(i) `press` gains a `repeat: int`** — one action, N key sends | counts become exact | **Refuse.** It breaks the normative rule "one atomic action per transition" (`OVERVIEW.md` §2, decision #2), and it hides a mid-gesture state change — the exact failure Manni's argument for atomic transitions is about. `Repeat` is the formalism's answer and it already exists. |
| **(ii) Tell the explorer the count up front** ("press `l` exactly 3 times") | counts become exact | **Refuse.** It makes the recording a demonstration of the *answer* rather than of the *task*, and it needs the compile-time system to already know the site's seek step — which is what we are trying to learn. It also removes the media evidence that D.3 depends on. |
| **(iii) Bound the overshoot in the prompt** — "stop at the **first** press whose verified total meets or exceeds the target; never press again after that" | counts land in `{⌈N/step⌉, ⌈N/step⌉+1}` instead of `{⌈N/step⌉ … 2×}` | **Adopt.** Two lines in `explorer/prompt.py` L85-92. It does not make counts exact (run 1 pressed 4 for 30 s because playback inflated its verified total), which is why the validator must still key on media jumps — but it removes the run-3 class of failure (fast-forwarded past the end of the video into a Mix autoplay) and the run-5/13 class (`"stuck: repeated the same action 6 times"`). |

Keep the adaptive verification itself. It exists because presses genuinely miss when focus is lost — run 4's
first attempt landed **1** press of an intended 3 — and removing it trades a noisy count for a silently wrong
gesture, which is strictly worse under a gate that cannot see the difference.

---

# E. Accept states and goal conditions

## E.1 What the agent proposes

One `DraftCondition` per *checkable* clause of the goal, each naming the recorded step that witnesses it. For
MOP the honest set is two:

```jsonc
[{"type": "url_matches",   "witness": "r1.s14.0", "why": "the task ends on the watch page"},
 {"type": "media_playing", "witness": "r1.s14.0", "playing": true,
  "why": "'watch for 20s' — the content must be playing at the end, and an ad cannot satisfy the duration gate"}]
```

Code derives the content (M13): `url_matches` → `^` + `re.escape(_base_url(step.url))`; `media_playing` →
`min_duration_s` = half the observed content duration, capped, exactly as `_gate_media_states` computes it
(`compiler.py` L156-181); `selector_visible/hidden` → `locator_candidates[rung]` verbatim, requiring
`match_counts[rung] ≥ 1`. **The LLM never writes a pattern, a selector or a threshold.**

`WorkflowDraft.accept` has `min_length=1`, so a draft with no goal does not parse; and if every proposed
condition fails M13 the compile reports `not-validated (no postcondition)` instead of shipping. That is
`generator-agent.md` §C.4 V11, moved from a rule into the type plus one orchestrator branch.

## E.2 What accept states cannot do, and what to do about it

MOP's goal has *temporal* clauses — "watch 15 s, then fast-forward 30 s, then watch 20 s" — which no
end-of-program predicate can express. Three honest positions:

1. **The durations are already carried structurally**, as `Repeat(count="${initial_watch_time}")` over a 1 s
   dwell and (with §D) `Repeat(count="${fast_forward_presses}")`. If those Repeats exist and the params are
   bound, the *program* encodes the timing; the accept state only has to certify the end state.
2. **`Milestone` already exists** (`schema/control.py`, `Workflow.milestones`) and is unused. Let the agent
   attach a `DraftCondition` to a mid-program state as a milestone (`media_playing` after the play click,
   `media_playing` after the seek block). The executor records milestone conditions in the `RunRecord` but does
   **not** gate on them — reporting only, per the model's own docstring. Cheap, and it makes "the replay spent
   its dwells on an ad" visible in the record instead of invisible.
3. **Do not put timing in the gate yet.** A `media_playing` accept plus bound duration params is a large step
   up from `accept_states: []`; asserting *elapsed* playback needs a trigger vocabulary NetGent does not have
   (`media_position_advanced_by`), and inventing one for this doc would be unverified design.

## E.3 Two cheap guards the prior art says to add next to accept states

Both are code-only and neither depends on the accept set being perfect (Skyvern, §K.2):

- **`never_run` / `different_source` coverage.** Track, per transition, whether the *current* version of that
  transition has ever executed in a passing replay. Skyvern's `review_gate.py` carries exactly this per block
  (`BlockCoverage = current_source | different_source | never_run | unknown`). It turns "the artifact shipped
  with an untested region" from an invisible fact into a printed column — which is what actually happened to
  MOP's fast-forward edges and to Dream Theater's missing `watch_time`.
- **`suspicious_success`.** Skyvern's `BuildTestOutcomeVerdict` has a reason code for it. NetGent's version:
  a replay where every edge returned ok, `accept_states` is empty **or** the run took < 50 % of the recorded
  wall-clock, is reported as `suspicious`, not as a pass. Dream Theater's passing round-1 artifact — which
  dropped the entire timing half of its task and still reported `replay_passed=True` — is the fixture.

---

# F. Interrupt classification

## F.1 What went wrong, precisely

`merge.py`'s rule is: a click present in *k < N* runs whose **target or reasoning** matches a dismissal regex
becomes an `Interrupt` candidate. In MOP that produced 8 interrupts, **5 at support 1**, including
`role=link[name="YouTube Home"]`, a related-video link, and the search-submit button — all three from run 12's
self-restart. Two of them armed on `[s1]`/`[s1, s2]`, fired on every replay, never satisfied their own
`selector_hidden` done state, and burned **~63 s of each ~104 s replay** in `max_fires × 10 s` timeouts.

Triage repeated the classification faithfully (`conditional_step` on columns 18, 21, 23, 24), because triage
reads the merge's disposition. Nothing in the chain ever asked *what the click was for*, and the answer was
written down in run 12 step 17's own reasoning:

> "the only way to properly demonstrate an explicit ad-skip is to restart the search flow via the YouTube Home
> link and redo the whole flow … I'll click YouTube Home to restart."

## F.2 The agent's job and the code's invariants

The agent proposes `DraftInterrupt(step, rung, also_seen, why)` from the step reasoning and the task text
("If an ad is shown skip the ad… If at any point any pop-ups happen dismiss them"). Code then requires **all**
of:

| # | invariant | computable from | kills |
|---|---|---|---|
| **I1** | the step's action is a `click` | `AgentStep.action` | today's rule too |
| **I2** | the chosen rung yields an expressible selector, is not volatile (`is_volatile_selector`), and does not match a fragile-id blocklist — steal Skyvern's `_FRAGILE_ID_PATTERNS` (`#ember-\d+`, `#react-select-\d+`, `[data-reactid]`, `#dnn_\w+`) and add it to `browser/locators.py` | the ladder | `#skip-button\:2`-class anchors |
| **I3** | **the click did not change the page's base URL** — `_step_effects` already computes this (`merge.py` L183-195) and `_base_url` keeps the path | recordings | **`YouTube Home` (`/watch`→`/`), the Blinding Lights link (`/watch`→`/watch?v=…` — different path), the search-submit click (`/`→`/results`)**: all three MOP false positives, by one rule |
| **I4** | the step is **not** also a `DraftEdge` on the main path, and its target is not the target of any main-path edge | the draft | column 23's fusion of an ad-skip button with the search-submit button |
| **I5** | support ≥ 2 across kept runs, **or** the task text names its class and the agent's `why` quotes the clause | recordings + task | the four support-1 interrupts from run 12; keeps `Skip ad` at support 2 and `No thanks` at support 8 |
| **I6** | at most **4** interrupts per workflow; ties broken by support then by earliest occurrence | the draft | interrupt sprawl as N grows (MOP: 1 → 1 → 4 dispositioned, 8 emitted) |

I3 and I4 are the two that would have made MOP's replay reach `t3` in ~40 s instead of ~104 s. I5 is the one
that requires the LLM, and it is the only place in the interrupt path where the LLM's judgement is load-bearing:
*"the task says 'if an ad is shown skip the ad', and this click's reasoning says it dismissed the ad overlay"*
is a claim only a reader of the text can make.

## F.3 One executor-side fix worth doing at the same time

A failed interrupt resolution costs a full state timeout (`DEFAULT_STATE_TIMEOUT_MS = 10_000`) per fire. The
done state of an interrupt is a *negative* condition on an element that was just clicked; 10 s is the wrong
budget. Give `Interrupt` a `resolve_timeout_ms: int = 2000` applied to its done state, and MOP's worst case
drops from 63 s to ~12 s. This is a pure `schema/control.py` + `executor/engine.py` change, unrelated to the
agent, and it bounds the damage of every future misclassification.

---

# G. Prompts and the evidence budget

## G.1 The system prompt (`agent/generator/prompt.py`)

```python
GENERATOR_SYSTEM = """You compile browser-exploration recordings into ONE deterministic, replayable workflow.

Several agents explored the same task with different concrete values. Every step they took is recorded:
the action, the element's locator ladder, the page URL, the player state, and the agent's own reasoning.
Your output is a WorkflowDraft: the complete workflow, written entirely as POINTERS INTO THOSE RECORDINGS.

THE ONE RULE: you never author content. You choose.
  - You may NOT write a selector, a CSS path, an XPath, a regex, a URL, a key name, a timeout, a state id,
    a transition id, an iteration bound, or any number that is not a recorded value or a declared value.
  - You MAY choose: which run is the spine, which runs to exclude and why, which recorded steps are on the
    main path and in what order, which rung of a recorded ladder each step should use, which recorded
    literals are parameters, which consecutive steps are one repeated gesture, which clicks are pop-up
    dismissals, and which recorded observations prove the task is done.
Code re-derives every choice from the recordings before applying it. A choice it cannot re-derive is
REJECTED and that part of the draft falls back to the recorded step, unchanged. So a wrong choice costs
nothing: state the intent the evidence supports and say why. Never hedge by omitting a choice.

ADDRESSING. Every step has a reference printed at the start of its line, like `r2.s9.0` (run 2, step 9,
item 0). Copy those references verbatim. Never count lines, never invent a reference, never use a column
number.

WHAT TO DECIDE, in order:

1. SPINE AND EXCLUSIONS. Pick the run whose step order is the cleanest complete demonstration; list the
   other achieved runs that corroborate it. Exclude a run only when the evidence shows it did something
   other than the task once — restarted the flow from the home page, wandered into an unrelated video,
   was cut off. Point at the step that shows it. Excluding is rare; excluding more than a third of the
   runs is refused by code.

2. THE MAIN PATH. One DraftEdge per recorded step that the task genuinely needs, in the spine's order.
   For each, list the same step as recorded in the OTHER runs (`corroborated_by`) — this is the evidence
   that the step is part of the task and not one run's accident. A step that only the spine took is still
   legal if the task needs it; say so in `why`. A step that no run needed twice is probably noise: leave
   it out.

3. TARGETS. Each edge keeps its recorded locator chain unless you say otherwise. Say otherwise when:
   - THE TASK MEANS A POSITION, not an identity ("the first result", "the top row"). Then set `target`
     to a rung whose kind is `structural` (a container-relative path) with `nth` set to the index the
     recordings measured for the acted element. A rung's ladder line prints its kind, how many elements
     it matched, and which one was acted on: `2:structural(12@0)` means rung 2, 12 matches, index 0.
     Prefer the smallest workable index and the most specific container.
   - THE TARGET'S NAME CONTAINS A PARAMETER VALUE in every run (the link is named after the search query).
     Then set `name_param` on a `role` rung.
   If the runs clicked visibly different KINDS of thing at the same point, that usually means the step is
   ambiguous — say so in `notes` rather than guessing.

4. PARAMETERS. A value is a parameter when the task supplies it and the runs used different ones. Give
   every parameter at least one witness per run: the exact literal, the step it appeared in, and which
   field. Values shorter than three characters, and page-furniture words (submit, search, next, ok), are
   refused. Use the parameter names already declared for the runs; do not invent new ones.
   A DERIVED parameter is for a repeated gesture whose count is not what the user says: the user says
   "fast-forward 30 seconds" and the site seeks 10 seconds per key press, so the artifact needs 3 presses.
   Declare `kind: "derived"`, `derived_from` the user's parameter, and `divide_by` the per-iteration
   amount YOU READ OFF THE MEDIA LINES (position advanced, minus the seconds that elapsed between the two
   readings). Code recomputes that number and rejects your claim if the recordings disagree.

5. REPEATED GESTURES. Consecutive steps with the same action and the same target that every kept run
   performed are ONE gesture: a DraftRepeat whose body is a single edge and whose `covers` lists every one
   of those recorded steps, in every run. Its count is a constant if every run did it the same number of
   times, otherwise a parameter — usually a derived one. Dwells (repeated waits) work the same way.

6. POP-UPS. A click is an interrupt when it DISMISSES something that interrupted the task — a cookie
   banner, a consent dialog, an ad overlay, a "no thanks" prompt. It is NOT an interrupt if it navigated
   somewhere, if it is on the main path, or if it is one run's detour. Quote the reasoning or the task
   clause that makes it a dismissal.

7. DONE. At least one condition that a zero-LLM replay can check at the end, each naming the recorded step
   that proves it: the URL the task ends on, an element that is visible when the task has succeeded, or
   the player actually playing content. Choose conditions that would be FALSE if the task silently failed.
   A workflow with no checkable postcondition is not accepted.

Put everything you considered and rejected, and everything the evidence could not settle, in `notes`."""
```

Two things this prompt deliberately does **not** do, both from the survey (§K):

- It does not offer an "if this is hard, make it an agent step" escape. Workflow Use's builder prompt
  *encourages* downgrading dynamic-list targets to LLM-at-run-time steps, with no criterion and no
  measurement — the exact failure NetGent's zero-LLM invariant exists to prevent.
- It does not ask for line numbers or offsets. Aider's measured result is that models are bad at source-line
  addressing; here every reference is **printed on the line the model is reading**, so it copies rather than
  counts.

## G.2 The content builder

```python
def build_generator_content(ev: Evidence) -> list[dict]:
    """The HumanMessage blocks. Pure — tests pin the layout (tests/unit/test_prompt_layout.py)."""
```

Sections, in this order (stable prefix first, so a repair turn re-reads a cached prompt):

```
TASK: <the user's task, verbatim>
START URL: <url>
DECLARED VALUES: video_query, initial_watch_time, fast_forward_time, second_watch_time

RUNS
  run 1  achieved  16 steps  video_query='Metallica - Master of Puppets' initial_watch_time='15s' fast_forward_time='30s' second_watch_time='20s'
  run 2  achieved  15 steps  video_query='Queen - Bohemian Rhapsody' ...
  run 12 achieved  33 steps  ...                                       [judge: 2 attempts]
  run 3  NOT achieved  19 steps  stopped: stuck: repeated the same action 6 times

STEPS
=== run 1 ===
r1.s2.0  fill "Metallica - Master of Puppets" -> combobox "Search"      | ladder 0:id(1) 1:role(1)
         why: type the query into the search box
r1.s4.0  click -> link "Master of Puppets (Remastered) 8 minutes, 36 s"  | ladder 0:role(1@0) 1:structural(20@0)
         url /results -> /watch   why: the first result under the search bar is the official video
r1.s10.0 press 'l' -> video "#movie_player > div:nth-of-type(1) > video" | ladder 0:css(1) 1:structural(1)
         media PLAYING 0:28/8:35  +11s   why: 'l' seeks +10s; verify each press
...
=== run 2 ===  (only steps that differ from run 1's alignment are expanded; the rest are one line)

ALIGNMENT (pure code, this round)
  key click:get_by_role|link#0   disposition target-varies  support 8/8  -> t3
     run 1: role=link[name="Master of Puppets (Remastered) 8 minutes, 36 seconds" i]
     run 2: #movie_player > div:nth-of-type(7) > button
     run 4: role=link[name="AC/DC - Thunderstruck (Official Video) 4 minutes, 53 s" i]   ...
  key wait#0                     disposition param initial_watch_time  15/10/12/15/10/15/10/20 -> t4
  key press:locator#0            disposition aligned   support 8/8  -> t5
  warning: column 2: click present in 7/8 runs — dropped
  warning: column 7: targets differ across runs and match no planned value — kept run 1's selector

EPISODES (pure code, this round)
  positional_target key click:get_by_role|link#0 at t3 [merge, replay-confirmed] — targets differ ...

REPLAY (zero LLM, last round)
  {video_query: 'Metallica - Master of Puppets', ...}: FAILED at t3 (action_error; unmet ['url_matches'])
  {video_query: 'AC/DC - Thunderstruck', ...}:        FAILED at t3
PREVIOUS ATTEMPTS
  round 2 draft: main[3].target positional rung 1 nth 0 — REJECTED: run 2 recorded no structural rung
```

The `PREVIOUS ATTEMPTS` block is the round-over-round memory the hint channel never had: the agent sees the
verbatim reason each of its earlier choices was refused. It is also what makes the acceptance rate
interpretable — a choice rejected twice for the same reason is a prompt bug, not a model failure.

## G.3 Token budget — the trajectories are not the problem

Measured on the MOP bundle:

| | bytes | tokens (÷4) |
|---|---|---|
| one `AgentStep`, compact JSON | 945–1 084 | ~240–270 |
| one `AgentStep`, the line format above | ~300–350 | **~80–90** |
| 8 kept runs × ~16 steps = ~128 steps | — | **~11 k** |
| alignment report (33 columns + 18 warnings) | — | ~2.5 k |
| episodes + replay + prior attempts + runs table | — | ~1.5 k |
| **total prompt** | — | **~16 k** |

For comparison the *exploration* of MOP cost 2.41 M input tokens — 150× the generator's whole prompt. The
`observation_chars` per explorer call averaged 5 836; the generator reads none of them. **The trajectories are
small; the observations were large, and the generator does not need them.** `generator-agent.md` §C.2's worry
about trajectory size is resolved in the negative.

Red lines, enforced in `evidence.py`:

- `max_steps_shown = 400`. Above it, the spine run stays in full and non-spine runs collapse to their
  *divergences from the alignment* (one line per column where they differ), which is what the agent actually
  needs from them.
- **Screenshots are not sent.** They are paths on disk; the verifier already uses them and the generator's
  decisions are all textual. This is a deliberate refusal — 329 PNGs at ~1 500 tokens each would be 30× the
  text budget for evidence the alignment already carries.
- **`evaluation` / `memory` / `next_goal` are omitted** — empty in every MOP step (the memory fields are off).
- Reasoning is truncated to 200 characters. The load-bearing clauses ("I'll click YouTube Home to restart",
  "jumps so far: 10+10 = 20 of 30") are all in the first sentence.

## G.4 The repair prompt

```python
REPAIR_SYSTEM = """Your draft was checked against the recordings. Some choices could not be re-derived and
were rejected; the rest were applied. Below is exactly what was rejected and why.

Revise the draft. Rules:
  - Fix only what was rejected. Repeat every accepted choice unchanged.
  - A rejection is a fact about the recordings, not an opinion. If it says a rung was not recorded, that
    rung does not exist — pick another or keep the recorded chain.
  - If a rejection cannot be fixed with the evidence you have, drop that choice and say so in `notes`.
    Dropping is correct; inventing is not.
Return the complete revised WorkflowDraft."""
```

This is CEGIS with `materialize` as the verifier and each `DraftOutcome.reason` as the counter-example
(§K.5). Bound at `max_repairs = 2`; record `repairs_used`.

---

# H. Model choice

Per `CLAUDE.md`, models are `provider:model` strings for `init_chat_model` (`/` also accepted). Current
Anthropic ids and first-party prices:

| model | id | context | in / out per MTok |
|---|---|---|---|
| Claude Fable 5.1 | `claude-fable-5-1` | 1 M | $10 / $50 |
| **Claude Opus 5** | `claude-opus-5` | 1 M | $5 / $25 |
| Claude Sonnet 5 | `claude-sonnet-5` | 1 M | $2 / $10 |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 200 K | $1 / $5 |

**Recommendation**

| node | model | why |
|---|---|---|
| `draft` | **`anthropic:claude-opus-5`** at `effort: high` | The draft is one long-horizon structural judgement over ~16 k tokens of heterogeneous evidence — exactly the shape that repays reasoning depth. It is one call per compile at ~16 k in / ~4 k out ≈ **$0.18**, against MOP's ~$10+ of exploration. Economising here is false economy. |
| `repair` | **the same model** | The repair turn reasons about *why the validator refused*, which is harder than the draft, not easier; and it is ≤ 2 calls. |
| dev / subscription runs | `claude-code:sonnet` | The existing local route (`langchain-claude-code`), subscription-billed. Use it for iteration; report headline numbers on `anthropic:claude-opus-5`. |
| not recommended | `claude-haiku-4-5` | 200 K context is fine, but the Structured Output Benchmark's 15–25-point gap between *valid* JSON and *correct* JSON widens exactly on nested schemas (§K.7), and `WorkflowDraft` is nested. Haiku belongs on the explorer, where it already is. |
| **refuse** | `claude-fable-5-1` | Fable 5.1 rejects forced tool choice (`tool_choice: any|tool` → 400). LangChain's `with_structured_output` on Anthropic forces a tool call, which is the seam `agent/llm.py` uses for every structured output in the repo. Until the seam moves to `output_config.format`, Fable is not usable here. **Verify before assuming** (§L). |

Two follow-ups worth doing at the same time, neither blocking:

- **Prompt caching.** `Evidence` is a stable prefix and the repair turn appends to it; a `cache_control`
  breakpoint after the evidence block makes the repair call read cache. The MOP explorer already gets cache
  hits (`cache_read_tokens: 134 879` on run 1), so the plumbing exists in the provider path; exposing a
  breakpoint through `agent/llm.py` is the work.
- **Per-node usage.** `scoped_llm` already gives per-run counters; give the generator its own scoped view so
  `RoundRecord.usage["generate"]` lands next to `plan` and `run-k` (`eval-framework.md` §2.2 stage 1 asks for
  the same split on the planner).

---

# I. Composition with the closed loop

## I.1 Where the agent sits

**After the merge, on the merge's alignment. Not instead of it.**

```
round r:  plan / plan_next
            → explore ×k  (LLM, parallel, fresh memory)
            → verify ×k   (LLM judge, advisory)
            → merge       (pure code: alignment + dispositions + StepKeys + the FALLBACK artifact)
            → generate    (the agent: gather → draft → materialize → repair?)   ← NEW
            → replay      (zero LLM, metamorphic, ≥2 unseen value sets)          ← the gate, unchanged
            → triage      (pure code → Episodes)
            → END if passed, else plan_next → round r+1
```

The merge keeps three jobs and loses one:

| merge's job | after |
|---|---|
| align N runs on typed keys | **keeps** — it is the cross-run evidence the agent reads, and it is pure code |
| disposition each column, with per-run targets/values | **keeps** — this is `generator-agent.md` §C.5's precedence table, now presented as *evidence* rather than as a veto |
| build the artifact | **becomes the fallback** — `GeneratorContext.fallback`, returned when < 50 % of the draft materialises |
| apply typed hints | **removed** — `hints.py` is deleted; `merge_trajectories(..., hints=…)` loses its parameter |

Rationale for keeping the merge first rather than handing the agent raw trajectories: the alignment is
information the agent cannot cheaply recompute (a Needleman-Wunsch over N runs with effect-aware scoring), it
is free, and presenting it makes the agent's disagreements *legible* — when the draft's spine differs from the
merge's intersection, that difference is the interesting signal and it lands in `notes`.

Rationale for the agent having the last word rather than the merge: §1.5. At N = 8 the merge's structural
intersection dropped 21 of 33 columns and deleted a load-bearing step at 7/8 support. That is not a rule that
should be able to veto a reader of the evidence.

## I.2 What triage and `plan_next` become

**Triage keeps its job and its vocabulary**, plus `Episode.key` (§C.2) and one addition:

- **`varying_gesture`** — `generator-agent.md` §D.5 #1 asked for it and it is still right, but the definition
  changes with §D: a maximal run of adjacent same-signature columns, present in **every** kept run at count
  ≥ 1, whose per-run counts differ. MOP's press columns 27–31 are the fixture. It is a hint to the *prompt*
  now, not to an applier — the agent reads it as an episode line and decides the fold itself.
- Episodes stop being *instructions* and become *observations*. That is what they always were; the hint
  channel was the thing that pretended otherwise.

**`plan_next` loses `generalization_hints` entirely.** `NextRoundPlan` keeps `next_variations`,
`scoped_subtasks` and `notes`. The planner's remaining job — choosing values that exercise the episodes — is
one it did *well* in MOP (it correctly moved to durations that are multiples of 10, and it correctly diversified
the queries); its failure was only in the channel it had to speak through. `normalize_next_round_plan` loses
its hint branch and its `columns` argument.

This also fixes a second MOP defect: round 2 spent 2 of its 4 runs on `scoped_subtasks`, which are recorded as
evidence and **not merged** (`"2 scoped sub-task run(s) kept as evidence, not merged"`). With the generator
reading recordings directly, a scoped sub-task run becomes usable evidence for one region of the draft rather
than a discarded run — recommend making `scoped` runs visible to `gather` (as steps the agent may reference
but may not put on the spine, enforced by M2).

## I.3 The exit condition

Unchanged in shape, tightened in content:

```
END(passed) iff  replay_check passed on ≥2 unseen value sets
             AND the artifact has ≥1 accept state that held on every passing replay
             AND no value set that passed in an earlier round fails now
```

The third clause is the regression half, from SkillGen (§K.4): a round that fixes the targeted value set by
breaking a previously-passing one is not progress, and MOP's `previous_failed` bookkeeping
(`orchestrator.py` L507) already collects exactly the data needed to check it. It is ~5 lines.

## I.4 The single-run path

`--parallel 1` currently goes `explore → verify → generate(compile_trajectory) → END` with **no replay gate**.
The generator agent works at N = 1 (every M-rule degenerates to "the spine only"), which makes N = 1 strictly
more capable than today — but only if the gate exists, because at N = 1 replay is the *only* verifier of any
claim. This is `generator-agent.md` M3, still unbuilt, and it is now a prerequisite rather than a nicety: ship
the replay node on the single-run path in the same change.

---

# J. Eval

Everything here slots into `eval-framework.md` §2.2's per-stage tables; nothing needs a new harness.

## J.1 The two headline tasks

| task | why it is the fixture | today |
|---|---|---|
| **MOP** — search, play the first result, skip ads, watch 15 s / seek 30 s / watch 20 s, dismiss pop-ups | every one of §1's five root causes fires on it | **fails** at `t3` on all 3 value sets after 3 rounds |
| **Dream Theater** — search, play the first result, watch 5 s | passes today, and must keep passing **without** silently dropping `watch_time` | passes with `watch_time` dropped (§1.4) |

Report `replay_pass^k` (τ-bench form, `eval-framework.md` §2.2 stage 6) over `k = 1..n` on **held-out value
sets the artifact was never compiled from** — for MOP: a query whose first result is a different title, and a
`fast_forward_time` that is *not* a multiple of 10 (e.g. 35 s), which is the case §D's `ceil` rounding exists
for and which no MOP round ever tested.

**Acceptance for the first ship:** MOP reaches `replay_pass^1 = 1.0` on ≥ 2 unseen value sets within
`--rounds 3`, with a non-empty `accept_states` and `fast_forward_time` bound; Dream Theater keeps
`replay_pass^3 = 1.0` **and** gains a bound `watch_time` (i.e. its dwell column is no longer dropped).

## J.2 Generator-specific metrics

| metric | definition | source | today |
|---|---|---|---|
| `draft_acceptance_rate` | applied ÷ (applied + rejected + degraded) `DraftOutcome`s | `GenerateOutcome.outcomes` | `hint_acceptance_rate` = **0** (r2, r3) |
| `rejection_reasons` | histogram over `DraftOutcome.reason` classes | same | 3 classes, all addressing bugs |
| `repairs_used` | LLM repair turns per compile (0–2) | `GenerateOutcome` | n/a |
| `used_fallback_rate` | compiles where < 50 % of `main` materialised | same | n/a |
| `excluded_run_rate` | runs the agent excluded ÷ achieved runs; and **whether excluding them changed the replay result** | draft + replay | n/a (run 12 was un-excludable) |
| `interrupt_precision` | interrupts that a human labels genuine dismissals ÷ emitted | `Workflow.interrupts` | MOP **3/8** by inspection (5 at support 1) |
| `phantom_interrupt_seconds` | wall-clock spent on interrupt edges whose done state never held | `RunRecord.edges` (`outcome == "recovered"` + `duration_ms`) | MOP **~63 s of ~104 s per replay** |
| `accept_states_nonempty` | already specified in `eval-framework.md` §2.2 stage 5 | `bool(wf.accept_states)` | MOP **false**, DT true |
| `suspicious_pass_rate` | passes with an empty accept set or < 50 % of recorded wall-clock (§E.3) | replay records | unmeasured; DT round 1 is one |
| `param_precision` vs the planner | bound params ∩ `canonical_names` ÷ bound params; and **recall** ÷ `canonical_names` | `wf.params` vs `RoundContext.canonical_names` | MOP recall **3/4** (`fast_forward_time` missing), DT **1/2** |
| `false_param_rate` | on the 21-form sweep, where the correct answer is ~zero params (`generator-agent.md` §C.7 #2) | `evals/sweep.py` | unmeasured |
| `regression_count` | value sets that passed in round r−1 and fail in round r (§I.3) | `RoundContext.rounds[].replay` | unmeasured |
| `tokens_per_accepted_artifact` | Σ all rounds ÷ artifacts passing the gate | `RoundContext.total_usage()` | MOP **∞** (2.68 M tokens, 0 artifacts) |

`draft_acceptance_rate` is the health signal `generator-agent.md` §C.7 #4 wanted and MOP could not provide,
because 0/5 is uninterpretable when every rejection is an addressing bug. With `StepRef` addressing, a
rejection is a *semantic* refusal, and ASI's 15.6 % admission rate becomes a meaningful comparison point.

## J.3 The offline ablation — the eval that can live in CI

Every stored `<name>.trajectories/` bundle already contains everything `gather` needs. So:

```
netgent eval generator --bundle trajectories/mop --draft cached
```

replays the *compile* with zero browser and zero model (drafts cached from a previous live run) and reports
every metric above except the replay ones. Two committed fixtures:

1. **`mop`** — a bundle whose compile must produce a positional `t3`, a bound `fast_forward_time`, ≤ 4
   interrupts, and a non-empty accept set. This is the regression test for all five root causes at once.
2. **`empty-draft`** — applying an *empty* `WorkflowDraft` must produce a workflow byte-identical to
   `ctx.fallback`. This is `generator-agent.md` M1's gate, restated for the new schema, and it is what proves
   the "worst case = today's output" claim rather than asserting it.

`generator-agent.md` §E.1 could not find the "two broken fixtures"; these are them, and they are cheap because
the bundles already exist on disk.

---

# K. Prior art — only what `generator-agent.md` does not already cover

Everything on Workflow Use's builder, Skyvern's parameter path, ReUseIt, AWM, ASI, SkillWeaver, Stagehand's
cache, and the PBD lineage is in `generator-agent.md` §B and is not repeated. Verified live 2026-09-02/03.

## K.1 Workflow Use — one correction, one warning

`browser-use/workflow-use` HEAD is still **`5d2d19f` (2026-08-27)**, the commit §B.1 pins; the five newer
commits are dependency bumps. `builder/service.py` confirms §B.1.3 and sharpens it: `build_workflow()` is
**one LLM call with no retry, no repair and no validation** — it returns `llm_response.completion` directly,
and `_parse_llm_output_to_workflow()` is dead code on the structured-output path.

**New and worth recording:** the builder prompt (`builder/prompts.py`, rule 2) instructs the model to
*pre-emptively downgrade* deterministic steps to `"type": "agent"` when the task involves "selecting from a
list or set of options that changes frequently (e.g. restaurants, products, or **search results**)", with the
canonical example `"Select the restaurant named {{restaurant_name}} from the search results"`. That is NetGent's
P1, and Workflow Use's answer is **to pay an LLM every run for it** — chosen by the LLM at authoring time, with
no criterion and nothing measuring the resulting agentic ratio. *Avoid.* One idea worth taking: the action
vocabulary in their prompt is generated by reflection over the runtime registry, so it cannot drift from the
executor — NetGent should render `GENERATOR_SYSTEM`'s action list from the pydantic union for the same reason.

## K.2 Skyvern's cached-script subsystem and `script_reviewer_v3` — **the closest industrial analogue, entirely uncovered**

§B.3 read Skyvern's parameter path. It did not read the two subsystems that matter most here. HEAD `b1a5c66`
(2026-09-03).

- **`run_with: code` admission rule** (`script_generations/CLAUDE.md`): *"ALL top-level blocks must have a
  `script_block` entry and a non-null `run_signature`. Without these, the system falls back to
  `run_with: agent`."* `script_block_extractor.py` computes that signature by AST — it wraps and compiles the
  block and returns every **free name not resolvable in the script's own scope**, so a generated unit is
  admitted only if it is closed over what it can see. *Take:* a structural precondition checked before any
  execution, with an explicit **per-unit fallback** — precisely §B.4's per-region materialisation,
  independently arrived at. Their **partial caching** (only blocks that actually executed get cached;
  `conditional` blocks never) is the per-transition notion of "verified by replay" NetGent's all-or-nothing
  gate lacks, and `cached_script_deploy_service.py`'s `_CachedScriptDeployUndoState` is ASI's
  `cp` → append → replay → `mv` back, productionised.
- **`script_reviewer_v3/`** (13 modules, behind a PostHog flag bucketed per `workflow_permanent_id`) is a live
  CEGIS repair loop with two halves: `midrun.py` fires from inside `ai_click`/`ai_input_text` the moment a
  cached selector misses; `postrun.py` does retrospective analysis. Four transferable pieces:
  - **`skills/interact.py`: "hypothesis → try → observe… a successful mutation IS the commit"**, with
    `_dom_hash()` = SHA of `document.body.innerHTML` recorded pre and post — a **zero-LLM state-change check**,
    the ASI `axtree_txt` inequality §B.8.1 recommends lifting, on a live DOM.
  - **`skills/validate.py`: dry-run before persist**, so a rejected edit never costs an artifact revision; it
    also blocks a `_FRAGILE_ID_PATTERNS` list (`#ember-\d+`, `#react-select-\d+`, `[data-reactid]`,
    `#dnn_\w+`) — **steal it for `browser/locators.py`**, where `is_volatile_selector` is narrower (§F, I2).
  - **`decision.py`: `demote_class_a`** — retrospective retraction of a mid-run "success" that later evidence
    contradicts: the SkillWeaver silenced-exceptions hole, tracked as a first-class outcome. Report a
    demotion rate.
  - **`script-reviewer.j2`** — the repair prompt, and the richest published artifact on letting an LLM edit a
    deterministic web program. Four rules worth lifting into NetGent's vocabulary: **rule 12** ("if different
    episodes show different values for the same parameter, any selector referencing that name is per-run and
    must be dynamic" — `_confirm_param`'s variance rule, restated as a constraint on the *editor*); **rule 9b**
    ("NEVER INVENT parameter names… this will crash at runtime with a KeyError"); a **three-tier determinism
    grade per call** (`selector=` free → `ai='fallback'` → `ai='proactive'`), i.e. an explicit per-action
    agentic-ratio dial; and **rule 8f `recoverable_marker_id`** — a marked non-deterministic call may be
    *upgraded* to a deterministic selector **only when a later execution episode supplies the evidence**, and a
    hard validator rejects any rewrite touching an unmarked call. That last one is a mechanised ratchet from
    agentic to deterministic driven by execution evidence, and it is the single most transferable idea here for
    NetGent's round-N loop.
- **`copilot/build_test_outcome.py` / `review_gate.py`** — `BuildTestOutcomeVerdict ∈ {progress_observed,
  repairable_failure, authoring_rejected, not_authoritative}` over 24 reason codes, several of which name
  NetGent's open problems exactly: **`suspicious_success`**, `outcome_not_demonstrated`,
  `synthesized_parameter_binding_ambiguous`, `unchanged_after_recorded_outcome`, `required_input_unbound`.
  And `BlockCoverage ∈ {current_source, different_source, never_run, unknown}` — **per unit, has the current
  source ever executed?** That is `accept_states: []`-shipped-and-nobody-noticed solved by bookkeeping rather
  than by a better oracle. Both are adopted in §E.3.

*Caveat:* `script_reviewer_v3` is flag-gated and mid-rollout (`cohort.py`: "call sites … are wired in PR 3"), so
some of it may not be live.

## K.3 Stagehand — a negative result

HEAD `e2c8946` (2026-09-02). **There is no workflow, codegen, or recorder→program feature in the OSS repo**
(`packages/` = docs, evals, extension, integrations, protocol, three SDKs; the only `workflow` hits are CI
YAML). §B.4's account of the cache still holds. **Director** (browserbase.com/blog/introducing-director,
2025-06-18) is a separate hosted product — NL prompt → a Stagehand script — with **no published claim of
execution validation**; no 2026 source found. Their DIY codegen recipe conditions an LLM on *the script so far
plus the current page HTML* and appends lines for human review: append-only, no recording, no execution
feedback. The one structural idea worth noting is prefix-conditioned incremental emission; NetGent's draft is
one-shot-plus-repair, which is the better trade when the whole evidence fits (§G.3).

## K.4 Induction repos are dead; three 2026 papers on *verifying* induced skills are new

Last pushes: **ASI 2025-04-24**, **SkillWeaver 2025-04-14**, **AWM 2025-12-22** (final commit literally
`upload rule-based awm workflows`, confirming §B.6.1 #4 from the other side), **WebXSkill** a single
`init` commit (2026-04-13). None is a maintained reference.

- **SkillGen: Verified Inference-Time Agent Skill Synthesis** — arXiv:2605.10999 (2026-05-09). Contrastive
  induction over successful **and failed** trajectories, and — the part that matters — it **models a skill as
  an intervention** and verifies it by running the same instances with and without the skill, scoring
  **repairs minus regressions**. Strictly stronger than ASI's "does it run": it charges the skill for the
  baseline successes it breaks. **Adopted as §I.3's third exit clause.** No code released.
- **Evidence Over Plans: Online Trajectory Verification for Skill Distillation** (SPARK) — arXiv:2605.09192.
  The **Posterior Distillation Index**, "a trajectory-level metric that quantifies how well a distilled skill
  is grounded in the task-environment evidence", used *online* during skill formation rather than as a
  post-hoc gate. It is the nearest published thing to a numeric version of NetGent's per-choice
  re-derivability check (which is a boolean). Worth reading before fixing §J's metric set.
- **SkillGenBench** — arXiv:2605.18693. Not read. Flagged because it may contradict §B.8.2's "nobody publishes
  precision for the induction decision" claim, which §J leans on.

## K.5 Execution-guided synthesis and CEGIS — the formal frame this design sits in, absent from every repo doc

The design in §A/§B has a name in the program-synthesis literature and citing it is free rigour.

- **Execution-Guided Neural Program Synthesis**, Chen, Liu & Song, ICLR 2019 — *"executing a partial program
  can result in intermediate states; thus, synthesizing the rest of the program can be conditioned on these
  intermediate states."* NetGent's analogue: the draft is conditioned on the **recorded** per-step state — the
  URL, the ladder with its match counts and indices, the media readings — not on the task text alone.
  Related: **ExeDec** (arXiv:2307.13883), **Execution-Guided Line-by-Line Code Generation** (arXiv:2506.10948),
  **SolidCoder** (arXiv:2604.19825), **RLEF** (arXiv:2410.02089).
- **CEGIS with an LLM as the synthesizer:** `pmorvalho/LLM-CEGIS-Repair` (AAAI 2025) — fault localisation
  removes the buggy statements, the LLM fills the holes, a failing test's counterexample is fed back;
  **Property-Guided LLM Program Synthesis for Planning** (arXiv:2605.16142) — *"LLM as the synthesizer in a
  CEGIS-style loop with a property checker as the verifier, handing the LLM a concrete counterexample of where
  and how the program went wrong."* One survey line worth quoting: *"CEGIS underpins much of classical program
  synthesis, yet it has seen little use with LLMs."*
- **This names both loops in NetGent.** The *round* loop is CEGIS at the artifact level: `replay_check` is the
  verifier, the failing value set at `t3` is the counterexample, `triage.py` is the fault localiser. The
  `draft → materialize → repair` loop (§A.1) is CEGIS at the compile level, with `materialize`'s rejection
  reasons as counterexamples. The framing also predicts MOP's failure: **a counterexample must be specific
  enough to localise** ("column 4 is not a main-path column" localises to nothing), and **the sketch must
  forbid the repair from touching verified regions** — Skyvern's rule 8f, independently.

## K.6 Positional / ordinal targets — RPA has a 20-year answer, and it validates ours

Covered already: CoScripter's ordinal exclusion, Helena's `row[i]`, Skyvern's prohibition, Workflow Use's
prose `position_hint`. New:

- **UiPath ships a first-class ordinal (`idx`) and lints it.** Workflow Analyzer rule **UI-REL-001 "Large Idx
  in Selectors"** fires when `idx` exceeds a threshold: *"IDX is the index of the current element in a
  container with multiple similar elements, and this might change when a new element appears in the same
  container … this attribute should be avoided."* The prescribed alternatives are ancestor information,
  relative elements, or the **Anchor Base** activity — find a stable anchor, then locate the target *relative
  to it*.
- **This is exactly what shipped in `generator-agent.md` §D.3**: `#dismissible > div > div a#video-title` +
  `nth(0)` is a container-relative descendant path with a small ordinal. Twenty years of deployed RPA practice
  says ordinals are acceptable **when the index is relative to a named container and the index is small** — a
  citable rule, and a stronger one than "code supplies the ordinal". **Adopt as two additions to M6:**
  require the rung's kind to be `structural` (already), and cap `nth` at a small bound (**`nth ≤ 4`**, with a
  warning above 0), preferring the most specific container.
- **Multi-Click: Cross-Tab Web Automation via Action Generalization**, Zhang, Li, Arab & Oney, **UIST '25**,
  DOI 10.1145/3746059.3747780 — generalizes one demonstrated input event to multiple targets on the premise of
  "multiple instantiations of the same template". **Could not be read** (ACM DL 403, author mirror 404). It is
  the newest HCI work on exactly "generalize a demonstrated action to sibling targets" and should be obtained
  through UCSB's ACM subscription before any novelty claim is made. Same for **MIWA** (UIST '23,
  10.1145/3586183.3606720), mentioned once in `reuseit.md` and never read.
- **Negative result, worth stating in a paper:** across everything searched, **no system stores "the first
  search result" as a typed ordinal intent bound to a container**. The five options in the wild are prose for
  an LLM to re-read (Skyvern, Workflow Use), a document-position selector that is discouraged or banned
  (UiPath `idx`, Skyvern `_POSITIONAL_RE`), a value-keyed row filter (Skyvern `filter(has_text=…)`), a
  relation-column index derived from value containment (Helena), or a grammar ordinal the recorder is
  forbidden to infer (CoScripter). NetGent's *"typed positional intent on a container-relative rung, requested
  by the LLM, range-checked against the recorded match counts, gated by replay"* appears to be unoccupied
  ground — **subject to reading Multi-Click.**

## K.7 Patch vs whole artifact — the evidence, and why it points at §B's design

Not covered anywhere in the repo docs, and it is the empirical question under §B.1.

- **Aider is the only public suite that isolates edit format.** *"Plain text edit formats worked best"* —
  `whole` (return the entire file) was "the most reliable and effective edit format across all GPT-3.5 and
  GPT-4 models"; GPT-3.5-0613 scored 39 % on `whole` and **~19 % on `diff`**; *"using the new functions API for
  edits performed worse than the whole file method, for all the models."* Their unified-diff work adds three
  measured lessons: **no line numbers** (*"GPT is terrible at working with source code line numbers"*);
  **high-level edits** (whole replaced functions, not surgical lines) — omitting this caused a **30–50 %
  increase in editing errors**; **flexible patch application** — omitting it, **9×** more errors. Third-party
  agreement: arXiv:2510.13859 finds *"the whole code format … tends to be more stable overall"* in multi-turn.
- **What transfers, and what does not.** Aider measures *free-form text that must be textually applied*; a
  typed semantic patch cannot fail to apply. So Aider does **not** condemn the old `GeneralizationPlan`. What
  it *does* support is three things this design already does: emit the **whole** artifact rather than surgical
  edits; keep the items **coarse** ("this target is positional", not "change this selector then this nth");
  and **never** address by counting (§G.1's "every reference is printed on the line you are reading").
- **The Structured Output Benchmark** (arXiv:2604.25359, 2026-04-28; 21 models) is the result that matters
  most: **all 21 models exceed 84 % JSON *validity*, yet the best *value* accuracy is 83.0 % on text** — a
  15–25-point gap between "produces valid JSON" and "produces correct JSON", widening on nested schemas, with
  Phi-4 (14 B) beating GPT-5 on value accuracy. Practitioner consensus (JSONSchemaBench, arXiv:2501.10868):
  constrained decoding has solved syntactic validity at all three major providers; semantic correctness is not
  solved, and *"overly large schemas with 50+ fields degrade quality"*.
  **This is the strongest external argument for §B.3's whole point:** schema-validity buys nothing about
  correctness, so *every leaf must be independently re-derivable from the recording*. It is also a live risk
  for `WorkflowDraft` — mitigation: keep every model small (none exceeds 8 fields), keep the nesting to two
  levels except in `main`, and rely on the repair turn.
- **Skyvern ships both and lets the agent choose:** `script_reviewer_v3/skills/persist.py` has
  `persist_block_edit` (a **libcst structural patch**) *and* `persist_script_rewrite` (verbatim whole-file
  replacement), both compile-checked ("defense-in-depth"), both preceded by the dry-run validators.

## K.8 Two 2026 papers that may be direct competitors — read before publishing

- **Agentic Compilation: Mitigating the LLM Rerun Crisis for Minimized-Inference-Cost Web Automation** —
  arXiv:2604.09718v2. Web-specific, and the name collides with NetGent's framing. **Not fetched.**
- **Compiled AI: Deterministic Code Generation for LLM-Based Workflow Automation** — arXiv:2604.05150.
  Confines the LLM to a one-time compilation phase, constrains it to fill *narrow business-logic functions
  inside pre-validated templates*, and passes the artifacts through a multi-stage validation pipeline before
  deploying them as static code: "zero-token deterministic execution". **This is NetGent's thesis as an
  architecture paper, in a non-web domain**, and the "LLM fills holes in pre-validated templates, never
  authors the skeleton" pattern is §B's contract. Abstract only; **whether its validation includes execution
  is unconfirmed.**
- Also flagged, not fetched: **From Agent Loops to Deterministic Graphs** (arXiv:2605.06365);
  **Deterministic Replay for AI Agent Systems** (arXiv:2607.16200, `agrepl` — MITM interception, replay
  fidelity F = 1.0, −98.3 % median per-step latency; the right citation for "replay is a legitimate acceptance
  oracle" and for a hermetic sweep harness).

---

# Build order

Each milestone is independently shippable and testable; the first three need no model and no browser.

| # | milestone | LLM? | browser? | files | gate |
|---|---|---|---|---|---|
| **G0** | `StepKey` on `ColumnReport` + `Episode` + `RoundRecord.key_index` (§C.2) | no | no | `generator/merge.py`, `triage.py`, `rounds.py`, `tests/unit/test_triage.py` | re-merge the stored MOP bundle three times (3, 5, 8 runs) and assert the video-click column's key is identical in all three, while its index goes 4/5 → 6 → 7 |
| **G1** | `draft.py` (the schema) + `materialize.py` (M1–M14) + `evidence.py` (§G.2), exercised by a **hand-written** `WorkflowDraft` fixture against `trajectories/mop/` | no | no | `generator/{draft,materialize,evidence,models}.py`, `tests/unit/test_materialize.py` | (a) an **empty** draft materialises byte-identical to `ctx.fallback`; (b) a hand-written draft produces a positional `t3`, ≤ 4 interrupts, a non-empty accept set |
| **G2** | `ParamDerivation` + `resolve_params` arithmetic (§D.4) and the media-jump validator (§D.3) | no | no | `schema/control.py`, `schema/workflow.py`, `generator/materialize.py`, `tests/unit/test_params.py` | MOP's recorded media readings yield `divide_by ≈ 10` from ≥3 pairs in ≥2 runs; `fast_forward_time=35` resolves to 4 presses |
| **G3** | The interrupt invariants I1–I6 + the fragile-id blocklist + `Interrupt.resolve_timeout_ms` (§F) | no | no/yes | `generator/materialize.py`, `browser/locators.py`, `schema/control.py`, `executor/engine.py` | on the MOP bundle, `YouTube Home`, the Blinding Lights link and the search-submit button are all refused by I3; `No thanks` and `Skip ad` survive |
| **G4** | The agent: `context.py`, `prompt.py`, `graph.py`, `agent.py`, `__init__.py` — `gather → draft → materialize → repair` | **yes** | no | `generator/{context,prompt,graph,agent,__init__}.py`, `tests/unit/test_generator_graph.py` (FakeLLM, no browser) | a `FakeLLM`-scripted draft drives the graph end to end; `draft_acceptance_rate` and `repairs_used` land in `RoundRecord` |
| **G5** | Wire into the loop: `generate` node after `merge`; delete `hints.py`; strip `generalization_hints` from `NextRoundPlan`; add the replay gate to the single-run path; add the regression clause (§I) | yes | yes | `agent/orchestrator.py`, `agent/planner/{models,prompt,graph}.py`, `agent/generator/hints.py` (delete), `agent/triage.py` (`varying_gesture`), `tests/integration/test_rounds.py` | MOP passes `--parallel 5 --rounds 3`; Dream Theater still passes **and** binds `watch_time` |
| **G6** | `netgent eval generator` + the two committed fixtures (§J.3) | no | no | `src/netgent/evals/generator.py`, `src/netgent/cli/eval.py`, `evals/bench/…` | runs in CI; `used_fallback_rate` and `draft_acceptance_rate` printed per commit |

**Do G0 and G1 first and alone.** They are falsifiable in a day against a bundle already on disk, they need
neither a key nor a browser, and if a hand-written draft cannot produce a correct MOP artifact from the stored
recordings then the problem is in the *evidence*, not in the prompt — and no amount of §G will fix it.

Explorer follow-ups, independent of the above and cheap: the overshoot bound in the seek prompt (§D.5 iii),
and rendering the action vocabulary from the pydantic union (§K.1).

---

# L. Unverified / could not confirm

**About this design**

1. **The media-jump arithmetic is derived, not measured.** §D.2's formula matches run 1's prose ("0:19 → 0:39,
   two verified +10 s seeks") and the `media`/`t` fields exist on every step, but I did not compute `seek_k`
   over the MOP bundle. G2's gate is exactly that computation; **run it before committing to ±40 %.** If the
   readings turn out too sparse (a step with no `media` breaks a pair), the fallback is a constant
   `divide_by` claimed by the agent and checked only against the overshoot band, which is weaker.
2. **`_positional_target`'s `match_indices` are `null` on some steps** (every press step in the MOP bundle
   records `match_indices: [null, null]`). M6 requires a non-null index; whether the *click* steps that matter
   have non-null indices in the MOP bundle was not checked step by step — the Dream Theater run proves it
   happens on YouTube result links, and nothing more.
3. **`kind: "page"` params (dynamic `ParamSource` extraction) have never been emitted by any generator.** M9
   specifies them; the machinery exists (`schema/control.py`, `tests/integration/test_dynamic_params.py`) and
   is untested from this direction. Defer past G5.
4. **The 50 % `used_fallback` floor and `max_repairs = 2` are stipulated, not tuned.**
5. **`nth ≤ 4`** (§K.6) is inferred from UiPath's UI-REL-001 having *a* threshold; I did not find the numeric
   threshold UiPath uses.
6. **The `Interrupt.resolve_timeout_ms` change assumes** the executor applies the state's `timeout_ms` when
   awaiting an interrupt's done state. That is the natural reading of `engine.py`'s sweep but was not traced.

**About the model seam**

7. **Whether `init_chat_model(...).with_structured_output()` on Anthropic uses forced `tool_choice`** — and
   therefore whether `claude-fable-5-1` 400s on it — was **not** verified against the installed LangChain
   version. §H's refusal of Fable rests on it. Check with one call before ruling Fable in or out.
8. **How to reach `output_config.effort` through `init_chat_model`** is unknown to me; §H's "effort: high" may
   require `model_kwargs` or may not be reachable at all in the current seam.
9. **Prompt-caching breakpoints are not exposed by `agent/llm.py`.** The explorer gets provider-side caching
   (`cache_read_tokens` is non-zero in MOP's `usage.json`), but placing an explicit breakpoint after the
   evidence block is unimplemented and its benefit is estimated, not measured.

**About the prior art (§K)**

10. **Multi-Click (UIST '25)** could not be read — ACM DL 403, author mirror 404. It is the one paper that
    might already occupy §K.6's "unoccupied ground". **Obtain it before making a novelty claim.** Same for
    **MIWA** (UIST '23).
11. **Four 2026 arXiv entries were not fetched:** `2604.09718` (Agentic Compilation — web-specific, name
    collision, **highest priority**), `2605.06365` (From Agent Loops to Deterministic Graphs),
    `2605.18693` (SkillGenBench), and `2604.05150` was read from a search snippet only.
12. **SkillGen (2605.10999) and SPARK (2605.09192)** are abstract-level reads; no code confirmed released for
    either. §I.3's regression clause is defensible on its own merits regardless.
13. **Skyvern's `script_reviewer_v3` is flag-gated and mid-rollout**, so §K.2's account may describe code that
    is not fully live. The file reads are direct and current (HEAD `b1a5c66`).
14. **Aider's per-model "percent using correct edit format" numbers** are on leaderboard tables that were not
    fetched; §K.7 quotes only the benchmark-notes pages.
15. **Director's 2026 state** and whether Director-emitted Stagehand scripts are execution-validated: no source
    found either way.

**Judgement calls, not facts**

16. **"The agent gets the last word over the merge"** (§I.1) is a judgement grounded in one task family
    (§1.5's 21-of-33 drop). It is the right call on that evidence; it is one site and one task.
17. **Excluding runs** (M3) is the most dangerous power in the draft. The budget (⌊N/3⌋, ≥3 remaining) is
    stipulated, and the real guard is that the replay gate still has to pass on unseen values. Watch
    `excluded_run_rate` in §J.
18. **§1's numbers are one run**, one site, one model (`claude-code:sonnet`), 13 explorations. Everything here
    is designed against it and against the Dream Theater contrast; nothing here establishes a rate.

---

# M. What shipped (2026-09-02, branch `v2/generator-agent`)

G0–G6 of the build order, in five commits, measured against the stored MOP bundle
(`tests/fixtures/mop`, the trimmed real run) and one live compile of that bundle with `claude-code:sonnet`
(`evals/results/generator/mop/`). Where this doc left a choice open, the simpler one was taken; the
deviations from the text above are listed so the doc stays honest.

| item | as specified | as shipped |
|---|---|---|
| `LocatorRef.rung` | "0 = the chain the explorer used" | indexes `locator_candidates` verbatim; the explorer's own chain is marked `*` in the evidence (the ladder is durability-ordered, so the used chain is rung 1 on MOP's video click) |
| `DraftNode` | a pydantic discriminated union | a plain `Union`: the claude-code route's `--json-schema` validator (ajv strict) rejects the OpenAPI `discriminator` keyword; each node's `kind` Literal disambiguates |
| a user param's witness | `text`/`value`/`url`/`seconds` | plus `press_count` and `media_jump` — `fast_forward_time` is never waited on directly, so its witness is the measured per-press seek (the model chose exactly this, unprompted) |
| `DraftRepeat.body` | any nodes | one edge; dwells bind with `value_param` on the wait edge, never a fold |
| `kind="page"` params | dynamic `ParamSource` | rejected with a reason (§L.3: never emitted by any generator yet) |
| M4 corroboration | same `_sig` shape | plus a guard: a dismissal-shaped click that some kept run never performed is refused on the main path and promoted to an interrupt candidate (the first live draft put the ad-skip on the main path, corroborated by 6/7 runs) |
| `Interrupt.resolve_timeout_ms` | executor applies it to the done state | the executor overrides the target state's `timeout_ms` for resolve edges only |
| §I.3 exit | ≥ 2 unseen + non-empty accept + no regression | ≥ 2 unseen + no regression; a missing postcondition is reported (`not-validated`) but does not fail the gate — the replay stays the only gate |
| §I.4 single-run replay gate | ship in the same change | shipped after: `--parallel 1` goes explore → verify → generate → **replay** — the artifact is replayed with zero LLM on its recorded value set, twice when params are declared (one exploration has no unseen set, so the metamorphic check degenerates to determinism); a failure keeps the artifact on disk, prints the replay lines and exits non-zero (`tests/integration/test_orchestrator.py`: a page whose Go button is gone on the second visit fails at `t2` with `selector_visible` unmet) |
| §E.2 milestones, §E.3 coverage / `suspicious_success`, §H prompt caching / per-node effort | follow-ups | not done |
| §D.5 (iii) the explorer's overshoot bound | two lines in the seek prompt | **reverted**: "stop at the FIRST press whose verified total meets N" read as "stop after the first press" — on the live run, runs 1–3 pressed once and were judged NOT achieved; the original wording (8/13 achieved on MOP) stays, and the materializer's overshoot band absorbs the count noise |

**Measured on the bundle** (`tests/unit/test_materialize.py`, `tests/unit/test_step_key.py`): the video-click
column's key is `click:get_by_role|link#0` at 3, 5 and 8 runs while its index goes 4/5 → 6 → 7; the hand-written
draft yields `t4` = `#dismissible > div > div a#video-title` + `nth(0)`, one `Repeat(count="${fast_forward_presses}")`
with `derive = fast_forward_time / 10 (ceil)` (the median measured seek over ≥ 20 press pairs is ≈ 10 s;
`fast_forward_time=35` resolves to 4 presses), the three run-12 false positives refused by I3, `No thanks` (7) and
`Skip ad` (2) the only interrupts, `accept = [url_matches ^/watch, media_playing(min 120 s)]`; an empty `main`
returns the merge's artifact byte-for-byte. **Measured with the model** (`netgent eval generator tests/fixtures/mop
--model claude-code:sonnet`): 25 items, 20 applied / 0 rejected / 5 degraded, 0 repairs, spine run 4, run 12 excluded
at `r12.s17.0`, `param_recall` 4/4, positional `t4`, one interrupt, validated — ~31 k input tokens, one call
(§G.3's estimate was ~16 k; the ladder lines and the eight runs' reasoning clauses are the difference).

**Live, end to end** (`netgent generate … --model claude-code:sonnet --allow press --max-steps 35`, defaults
`--parallel 5 --rounds 3`; `evals/results/closed-loop/mop-generator-agent*/`):

- The first live compile **passed the gate in round 1 and was vacuous**: `run-60s.json` shows all five initial
  dwells and all six presses executed against the 0:15 pre-roll (`video PLAYING at 0:0x / 0:15`); the 4:33 content
  appeared only at `t7`, because the accept state was the only one carrying `media_playing`. The state sequence was
  right and the goal was not. Two code fixes followed: every timed phase's state is gated on the content the
  recordings show playing (an invariant of `materialize`, reported as a degraded `main[i].gate`), and replay value
  sets take the runs' declared values so the agent's own params are varied — which surfaced the second bug,
  `repeat.count '30s'`, now absorbed by one unit coercion (`schema/units.py`).
- The re-run (`mop-generator-agent-2/`) **passed in round 1**: 4/5 runs achieved, draft 21/24 applied (the three
  degraded items are the code-added gates), one repair, 13 transitions, 3 interrupts, `accept_states=['s7']`;
  replay `ok` on the defaults and two unseen sets with `fast_forward_time` 30 / 40 / 45 s, watches 15/30/20 and
  20/10/25, same `s1…s7` signature, zero LLM. A direct `netgent run … fast_forward_time=60s initial_watch_time=5
  post_ff_watch_time=5` (`run-60s/record.json`): the ad-skip interrupt fired three times at `s4`, `t5` waited
  38.7 s for the 4:33 content, the six presses ran on it (`0:09 → 1:14`), final position `1:23`.
- What the loop still does not check: the judge's exact-seconds strictness makes the explorer's private retries the
  expensive part (4 of 5 runs retried); and `fast_forward_presses` per-run counts are only band-checked (run 2
  recorded 1 press for 20 s), which the median-seek rule tolerates by design.
