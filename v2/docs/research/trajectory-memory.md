# Trajectory memory — inducing one generalized workflow from N runs of the same task

Research doc for NetGent v2 (UCSB SNL), written 2026-08-31. Companion to
`reuseit.md` (which it extends and corrects) and `browser-agent-memory.md` (which covers the
*complement*: per-step memory inside one run). Everything here was fetched this session; nothing is
cited from memory. Provenance for every non-obvious claim is in §D.

---

## Summary (10 lines)

1. **The merge is the memory.** In every system that reuses trajectories, the artifact induced from
   N episodes *is* the cross-run memory. For NetGent that artifact already exists — the NFA — so
   `--runs N` → generator merge is not a new subsystem, it is the induction step we haven't built.
2. **Aggregating N trajectories of the *same* task beats one-per-trajectory**, measured: WISE-Flow's
   task-wise vs trajectory-wise induction, +0.031 similarity / +0.032 F_β; ReasoningBank's MaTTS
   parallel self-contrast, 49.7 → 55.1 SR at k=5 vs 52.4 for un-aggregated scaling.
3. **Nobody aligns the trajectories.** ReUseIt, AWM and ReasoningBank all hand *all* traces to one
   LLM call. There is no alignment algorithm anywhere in this literature. NetGent can do it in code,
   because our steps carry typed keys (base URL + durable locator + action kind) — this is our edge.
4. **ReUseIt's structure comes from one successful run only**; failures contribute *guard text* and
   nothing else, and divergence between runs never becomes a branch (verified in the paper's own §4.1
   and Appendix C.2–C.4, quoted in §A.3).
5. **Correction to our own notes:** ReUseIt's 24.2 → 70.1 is *not* the value of failure-mined guards.
   Guards without fallbacks score 50.1; success-only traces already score 41.4. Failure-mining is
   worth roughly **+8.7 pts**; the success-mined fallbacks are worth **+20.0**.
6. **Representation decides whether failures help.** Adding failed trajectories to trajectory-shaped
   memory *hurts* (AWM 44.4 → 42.2); to abstracted-strategy memory it helps (ReasoningBank 46.5 → 49.7).
7. **Success-only trajectory memory can be net negative under distribution shift**: AWM loses to
   *no memory at all* on WebArena's cross-site Multi subset (10.3 → 3.4) and overall on Claude-3.7
   (41.7 → 40.8).
8. **Under a strong structural prior, 1–2 demonstrations suffice** (SMARTedit/version-space algebra),
   and the failure mode is the *late anomalous run* — which is the argument for N=3 with incremental
   top-up rather than N=20.
9. **Proposal:** the merge should be **version-space intersection over triggers** plus
   alignment-driven classification of divergence into `Param` / `Branch` / `Interrupt` / reject —
   pure code, zero LLM. Separately, a per-site memory of *robustness hints only*.
10. **Independence policy:** the N runs of one `generate` share a frozen, task-independent site
    snapshot and nothing else. No run-to-run action copying, ever.

---

## 0. Scope, and what this doc does not repeat

| Document | Its question |
|---|---|
| `browser-agent-memory.md` | What the explorer keeps **between steps of one run** (the history window, folds, `StepRecord`). |
| `web-agent-papers.md` §2/§4 | A per-paper survey card for the memory and skill-induction literature. |
| `reuseit.md` | A full read of ReUseIt as a system. |
| **this doc** | **N trajectories of one task → one generalized, task-keyed artifact**, and what trajectory-derived memory the explorer carries across runs and invocations. |

Part A extends and corrects `reuseit.md`; it does not restate it. Part B goes deeper than
`web-agent-papers.md` on exactly one axis — the multi-episode induction step — and adds the systems
that document did not cover (ReasoningBank/MaTTS, WISE-Flow, MemGuard, AutoGuide, AutoManual, Memp,
Memento, AgentKB, Rememberer, RAP, AgentRR, the PBD lineage, Claude Skills).

---

# Part A — ReUseIt, extended and corrected

## A.1 Provenance re-check (2026-08-31)

Re-fetched `arxiv.org/abs/2510.14308`: still **v1 2025-10-16, v2 2026-01-24**, no v3. Comments field
verbatim: *"ACM IUI '26 | 31st International Conference on Intelligent User Interfaces"*. **No code,
no project page, no artifact link** on the abs page. `reuseit.md`'s "Code / artifact: none found" row
stands unchanged.

Appendices C.1–C.4 were extracted from the v2 PDF this session and are quoted at length below; the
four *execution-time* prompts named in §4.2 remain unpublished, so the DG2 half is still
irreproducible.

## A.2 What a stored "reusable workflow" actually contains

There is no schema. The artifact is a numbered prose list. Its grammar is fixed only by the C.4
output contract:

```
– Action: Concise description of the action.
– Condition Check: The condition to verify before or after the action.
– Fallback Action: The recovery action to take if the condition is not met.
```

with exactly four legal step shapes (no check / pre only / post only / pre and post). One step plus
its checks and fallbacks is a **unit**; the workflow is the concatenation of units.

Answering the brief's item (1) precisely:

| Asked | ReUseIt's answer |
|---|---|
| **step schema** | A prose `Action:` line inherited from Magentic-UI's plan learner (`PlanStep{title, details, agent_name}`). No typed fields. |
| **selectors** | **None.** Elements are referred to in English ("the '+' next to Adults"). Resolution is redone by a VLM on every replay. |
| **guards / pre-post conditions** | Prose sentences of the form `Before/After performing {Action}, ensure {Condition} is satisfied.` Evaluated at run time by a VLM yes/no over a screenshot. |
| **params** | `<angle-bracket>` placeholders inside prose. Nothing declares, types, validates or resolves them. |

The one mechanism worth stealing verbatim is the **Important Constraint** that appears identically in
C.2 and C.3:

> "When deriving condition checks from a failed action, do not include any concrete or literal values
> from the original action (e.g., specific text strings, numbers, dates, names, or URLs). Conditions
> must be written using generic, value-agnostic wording that captures the underlying requirement
> (e.g., element state, page readiness, input availability) rather than the specific instance that
> caused the failure."

## A.3 How N trajectories become one artifact — the merge, precisely

This is the brief's item (2) and the part `reuseit.md` left open. The answer, from §4.1 and the
prompt signatures:

**There is no alignment algorithm and no merge.** The pipeline is three independent LLM calls over
*pools* of traces, plus one insertion pass:

| Stage | Input (verbatim from the prompt's INPUT TO ANALYZE) | What it emits |
|---|---|---|
| Structure | successful attempts only, via Magentic-UI's `learn_plan_from_messages` | **one** `{WORKFLOW STRUCTURE}` — a linear prose step list |
| Guards (C.2) | `{FAILED EXECUTION MESSAGES}` — the whole pool at once | a flat list of `Condition Check:` rules |
| Fallbacks (C.3) | `{FAILED ACTION}` + `{SUCCESSFUL EXECUTION MESSAGES}` | one `Fallback Action:` per failed action |
| Assembly (C.4) | one structure + all checks + all fallbacks | the workflow |

Consequences, each of which matters for NetGent:

1. **The structure comes from a single run.** §4.1: *"For successful attempts, we likewise capture the
   agent's messages and additionally use Magentic-UI's plan learning module to synthesize a high-level
   plan consisting of the major steps. This plan serves as the workflow structure."* Nothing
   reconciles two successful runs that took different paths. If run 3 and run 7 both succeeded by
   different routes, one of them is silently discarded.
2. **Alignment is delegated to the model, in one clause.** C.3's METHOD: *"Compare the failed step
   with the actions described in the successful execution messages **of the same action**."* "The same
   action" is matched by an LLM over English descriptions. That is the entire cross-run alignment.
3. **Divergence never becomes a branch.** There is no `Branch`, no alternative arm, no disjunction
   anywhere in the C.4 grammar. All divergence collapses into either (a) a guard, or (b) a fallback
   sentence attached to a step of the single canonical structure.
4. **Failures contribute *only* guard text.** They never contribute structure, never contribute
   fallbacks, and are never re-run to confirm the guard fixes them. Answering the brief's question
   "what exactly is mined from a failed run": the *agent messages* (natural-language descriptions of
   each action), filtered by the cues `"failed to," "didn't," "couldn't"`, abstracted into a
   value-free condition. Screenshots, DOM, URLs and error objects are not used.
5. **Generalization is a prompt rule, not a data operation.** The abstraction that makes the workflow
   reusable is the Important Constraint (§A.2), applied per-item by the LLM — not an intersection
   over what the runs had in common.

**The variation taxonomy is the real merge input.** The paper's own worked task template is worth
quoting because it is a partition of a task's parameters:

> "search the `<flight type>` `<cabin type>` ticket from `<departure city>` to `<destination city>`
> on `<date>` for `<number of passengers>` on `<website>`" — attribute variations are `<cabin type>`,
> `<departure city>`, `<destination city>`, `<date>`, `<number of passengers>`; category variations
> are `<flight type>` (one-way/round-trip); website variations vary `<website>`.

So the three variation levels are exactly: *values on the same page* / *a tab-or-toggle switch on the
same site* / *a different layout*. That is a ready-made decision procedure for which NetGent construct
each variable becomes (§C.1.4).

**Run budget.** n=5 for the original and n=5 per variation ≈ 20 runs, justified only as *"this can
lead to at least one successful execution for workflow synthesis based on our experiments."* The
Remarks paragraph concedes a sequential alternative (get one success within ~3 runs, take the
structure, add guards from further runs) and says parallel was chosen to accommodate hard tasks.

## A.4 Retrieval — there is none

Brief item (3). ReUseIt has **no retrieval mechanism**. A workflow is bound to the task family it was
synthesized for, and the user applies it explicitly. The §7.2 future-work paragraph proposes a RAG
library of retrievable *units* ("maintain a library of workflow units, each consisting of an action,
its condition checks, and fallback actions, and create new workflows by retrieving the relevant units
and assembling them") — speculative, unbuilt, unevaluated. Contrast AWM, Voyager and ReasoningBank,
which all ship a retrieval key (§B.4).

## A.5 Execution — the fallback ladder, and who contributes what

Brief item (4). The ladder is three rungs, from §4.2 / Figure 6:

1. **Condition check** — screenshot before/after the guarded action, paired with the check text; VLM
   returns yes/no + explanation. Yes → next step.
2. **Self-recovery** — no → re-execute the failed step **up to three times** following the fallback
   actions, re-evaluating the condition after the retries.
3. **User notification** — retries exhausted → structured where/why/what-behaviors message; the
   user's reply is parsed back into new checks or fallbacks.

Decomposing the headline honestly:

| Arm | SR | Reading |
|---|---|---|
| Task-Only | 24.2 ± 13.2 | bare prompt, no artifact, no retry loop |
| Task + Success-Traces | 41.4 ± 14.8 | **success-only replay** — the right baseline for "does failure-mining help" |
| Task + Magentic-UI Plan | 48.6 ± 12.9 | strongest non-ReUseIt baseline |
| ReUseIt **w/o** Fallback Actions | 50.1 ± 10.3 | guards + 3 retries, agent invents its own recovery |
| Task + ReUseIt Workflow | 70.1 ± 16.4 | full system |

So: **failure-mined guards buy ≈ +8.7 pts over success-only traces (41.4 → 50.1); the success-mined
fallbacks buy +20.0 (50.1 → 70.1).** The ablation holds the retry budget fixed, so it is the one arm
that is compute-matched, and it points the opposite way from the popular reading of this paper.

> **Correction to our own docs.** `web-agent-papers.md` §5 finding #2 states "Guards must be mined
> from *failed* runs: 24.2% → 70.1% when failure-derived condition checks are added." That
> attribution is wrong — 24.2 → 70.1 is the whole system against a bare prompt, and it bundles a
> ~20-run synthesis budget plus a per-step VLM check plus 3 retries. The defensible claim is the
> decomposition above. `reuseit.md` §6.3 item 1 ("compile from failed runs, not just successful
> ones") survives, but should be re-costed: it is the *smaller* half of the gain.

## A.6 Verification of steps at replay

Brief item (5). Every guard is a **VLM yes/no over a screenshot**, from the same model class that made
the mistake being checked. The paper's own judge audit (GPT-4o, WebVoyager protocol, 45 judgments)
reports Accuracy 0.778, Precision 0.852, Recall 0.793, F1 0.821, **κ = 0.528**, and §7.1 concedes the
judge "tend[s] to produce false negatives." A false "No" burns three retries and escalates to a human
for nothing. AgentRewardBench (arXiv:2504.08942, 1,302 trajectories, 5 benchmarks, 4 agents)
independently measures the best judges — GPT-4o and Claude 3.7 Sonnet — at **≈70% precision**, i.e.
30% of trajectories marked successful are not; human inter-annotator agreement is 89.3%. This is the
reliability floor of the whole DG1 mechanism, and it is the number NetGent avoids by construction:
our replay check is a predicate evaluated by code.

## A.7 Limitations — theirs, and the ones they don't state

Stated (§7.3): (i) a reusability-vs-generalizability tradeoff — guards are verbose because current
agents need them, and verbosity is a user burden; (ii) linear intervention only — no rewind to an
earlier step whose precondition was the real problem.

Not stated, and load-bearing for us:

- **The artifact cannot be diffed, type-checked, or pruned.** Guards accumulate monotonically; nothing
  detects that two guards contradict or that a `<placeholder>` is unbound.
- **No cost accounting.** Wall-clock synthesis 15:20–52:40 per task family is reported; tokens,
  dollars, and the per-step latency of screenshot Q&A are not.
- **Selection bias.** Variations that failed in *all* runs due to captcha were dropped (Archive → 2
  variations, Cars → 1). The hardest cases leave the denominator.
- **Unusable intervals.** Appendix D prints normal-approximation CIs like Bandcamp Task-Only
  40.0 [−214.1, 294.1]. No inferential statistics appear anywhere in the paper.
- **Single model, single framework.** GPT-4o + Magentic-UI throughout.

## A.8 Corrections to `reuseit.md`

| In `reuseit.md` | Correct as of 2026-08-31 |
|---|---|
| §6.1 maps user notification to `ValidationReport` → `ReplayResult` from `validator/validate.py` | **`validator/` no longer exists.** The pipeline is explore → verify → generate (`agent/orchestrator.py`); the judge lives in `agent/verifier/`. The mapping target should be the verifier's `Verdict` plus the executor's per-edge failure. |
| §6.1 lists our triggers as `url_matches, selector_visible, selector_hidden, title_contains` | `schema/triggers.py` defines `UrlMatches`, `SelectorVisible`, `SelectorHidden`, **`DialogMatches`**. There is no `title_contains` in code (CLAUDE.md still lists it). |
| §6.3 item 1: "compile from failed runs… the paper's central insight" | True but mis-weighted; see §A.5. Failure-mining is the smaller half. |
| §5 "the merge" is left unspecified | There is no merge; see §A.3. |
| Retrieval is not discussed | There is none; see §A.4. |

## A.9 Mechanism map → NetGent, with a verdict

| ReUseIt mechanism | NetGent equivalent | Verdict | Why |
|---|---|---|---|
| Prose unit = step + checks + fallbacks | `Transition` (one atomic action) + target `State.conditions` + a `Branch` arm | **reject the form, keep the shape** | The Hoare-triple shape is right; prose is what makes their artifact undiffable and unprunable. We already have the typed version. |
| Workflow structure from **one** successful run | `control` / `control_sequence` | **reject** | Discarding the other successful runs throws away exactly the signal that tells us what is invariant. Replace with an alignment over all successes (§C.1). |
| Condition checks mined from failed-run *text* | `Trigger` on a `State` | **adapt** | Adopt the intent, change the evidence: mine from the failed step's *URL, DOM and error object*, which we have and they don't. Emit a `SelectorVisible`/`UrlMatches`/`DialogMatches`, never a sentence. |
| Important Constraint (strip every literal) | trigger synthesis rule | **copy, with a guard** | `compile_trajectory` bakes `re.escape(base)` into `url_matches` (`compiler.py:162`) — the exact brittleness the constraint forbids. But over-generic triggers are *worse* for an NFA than missing ones (a wrong state match), so pair it with the version-space rule in §C.1.2. |
| Fallback actions ("Retry X by doing Y") | a `Branch` arm keyed on the observed state | **adapt** | Their ablation (50.1 → 70.1) is the strongest evidence in the paper and it is about *guided* vs *blind* retry. But a fallback must compile to a concrete atomic action or an alternate edge — never a sentence — or it breaks the zero-LLM rule. |
| Bounded retry ≤3 then escalate | `Interrupt.max_fires` (default 3), `Repeat.max_iterations` | **already have it** | Ours is statically bounded and checkable; theirs is a loop counter. |
| Variation taxonomy (attribute / category / website) | `Param` / `Branch` / separate workflow | **copy the taxonomy, reuse C.1 verbatim** | It is a decision procedure for which construct a variable becomes. See §C.1.4. |
| ~20 runs per family | `--runs N` | **reject the number** | SMARTedit's result (§B.2.6) says a strong structural prior needs 1–2 examples. We have the prior. Default N=3, top up on unresolved divergence. |
| VLM yes/no guard at replay | trigger predicate in `browser/triggers.py` | **reject** | ~70% judge precision (AgentRewardBench) vs a code predicate. This is the axis NetGent wins on and should measure on. |
| Pop-ups as a failure symptom → a guard | `Interrupt {state, resolve, scope, max_fires}` | **we are strictly stronger** | They have no notion of ε-transitions. Ours is in `schema/control.py` and swept between control nodes. |
| User guidance write-back (LLM parses feedback into checks or fallbacks) | nothing yet | **adapt, compile-time only** | The routing rule is right; the output must validate as a `Trigger` or `Transition`, which is what keeps rule 1 ("workflows are generated, never hand-written") true. Inherit their unfixed problem too: nothing prunes accumulated guards — see MemGuard, §B.6. |
| No retrieval | `Call` + a workflow library | **build later** | Both unbuilt. AWM's `retrieve.py` is the reference implementation (§B.4). |

---

# Part B — trajectory-based memory: what is stored, keyed, retrieved, written

## B.0 The one question

> An agent runs task *T* N times under different parameter values and page conditions. From those N
> trajectories, induce one generalized, task-keyed artifact that transfers to future runs of *T*'s
> family.

Only four published systems do exactly this. Everything else in the literature induces from
trajectories of **different** tasks, which is a materially easier problem (you are looking for common
sub-routines, not for the invariant of a distribution).

| System | Induces from N episodes of the *same* task? | How |
|---|---|---|
| **ReUseIt** (2510.14308) | yes, ~20 | three pooled LLM calls, no alignment, structure from one run (§A.3) |
| **ReasoningBank / MaTTS** (2509.25140) | yes, k=5 parallel | one LLM call over all k trajectories with an explicit *self-contrast* instruction (§B.2.2) |
| **WISE-Flow** (2601.08158) | yes | three-pass analyse → draft → reflect-and-revise, over a partition into clean success / recovered success / failure (§B.2.3) |
| **SMARTedit / VSA** (Lau et al., MLJ 2003) | yes, 1–2 | version-space **intersection** — the only *algorithmic* multi-demo merge in this survey (§B.2.6) |
| AWM (2409.07429) | *no* — cross-task | but its rule-based path contains a reusable same-task dedup signature (§B.2.1) |

## B.1 Taxonomy table

| System | Stored what | Keyed by | Retrieval | Write policy | Measured gain | NetGent relevance |
|---|---|---|---|---|---|---|
| **AWM** 2409.07429 | workflow = name + one-line docstring + abstracted `<think>/<action>` steps with `{placeholder}` values | website (files are per-site) + docstring text | FAISS over `name\ndocstring`, ada-002, top-k=10 (`mind2web/workflow/retrieve.py`); WebArena injects the whole file | success-only, judged by `cum_reward` or LLM autoeval; dedup by intent-template then by abstract-trajectory signature | WebArena 23.5 → 35.5, steps 7.9 → 5.9; Mind2Web cross-domain 18.6 → 35.5 | **highest.** Its rule-path dedup signature is our alignment key (§C.1.1) |
| **ReasoningBank** 2509.25140 | memory item `{title, description, content}` — 1–3 sentences of distilled strategy | task query embedding | embedding top-k (≤10), items injected into the system instruction | **both successes and failures**, labelled by LLM-as-judge, plain append | WebArena overall 40.5 → 48.8 (flash); +MaTTS 51.8; success-only 46.5 → 49.7 with failures | **highest.** `PARALLEL_SI` is literally the same-query multi-trajectory induction prompt (§B.2.2) |
| **WISE-Flow** 2601.08158 | workflow backbone (description + ordered milestones) + prerequisite-augmented action blocks with conditional next-step transitions | task | embedding, at workflow *and* action level | contrastive over clean-success / recovered-success / failure; reflect-and-revise validates each step against the trajectories | task-wise vs trajectory-wise induction: Sim +0.031, F_β +0.032 | **highest.** Their representation is an NFA in all but name |
| **Synapse** 2306.07863 | whole abstracted trajectory as an exemplar | task description embedding | similarity search | success (demonstration) only | MiniWoB++ 99.2% over 64 tasks from 48 demos; Mind2Web +56% rel. step SR | medium — state abstraction is a compile-time idea for us |
| **ExpeL** 2308.10144 | insight list + trajectory pool | task embedding | all-mpnet-base-v2 + FAISS kNN, k=2–6 | ADD (importance 2) / EDIT / UPVOTE / DOWNVOTE, delete at 0 | HotpotQA 28.0 → 39.0; ALFWorld 40.0 → 59.0 | **high** — the right structure for per-site rules |
| **AutoGuide** 2403.08978 | guideline "When on *context*, if you want to *goal*, you should *action*" | **state / context**, in a dict | context identification then top-k (2–3) *within that context* | mined from **paired** trajectories with different returns, at the divergence timestep | ALFWorld 54.5 → 79.1; WebShop 30 → 46; WebArena 8.0 → 47.1 (subset, see §D) | **highest** — the case for keying by state, not task |
| **AutoManual** 2405.16247 | rules typed into 6 categories, each `{Type, Content, Example, Validation Logs}` | environment | injected | online `write_rule` / `update_rule` by a Builder agent; case-conditioned on "Imperfect Rules" vs "Imperfect Agents" | ALFWorld 97.4; MiniWoB++ 98.3; online +2.7, case-conditioning +3.6 | high — typed rules with validation logs ≈ triggers with support counts |
| **Memp** 2508.06433 | both trajectory-level and script-level procedural memory | task | random / query-similarity / AveFact | validation filter or reflexion-based in-place revision of the failing memory | TravelPlanner 71.93 → 79.94; ALFWorld 42.14 → 77.86 | high — "combine both granularities" and "correct in place" |
| **Memento** 2508.16153 | case `(s, a, r)`, r binary | state embedding (SimCSE) | non-parametric top-K cosine, or a learned Q-function | append; parametric variant trains a case-selection Q | GAIA val 87.88% top-1; **K=4 optimal**, degrades beyond | medium — the "swamping problem": small curated memory wins |
| **Rememberer** 2306.07929 | `(task, observation, action, Q)` records | λ·task-similarity + (1−λ)·**observation**-similarity | top-m as dynamic exemplars | both successes and failures; Q updated by off-policy Bellman, α=1/N | WebShop 0.36 → 0.39 SR; WikiHow 0.89 → 0.93 | medium — *"observation similarity proved more critical than task similarity"* |
| **RAP** 2402.03610 | task + plan + full trajectory | weighted mix of task, plan, and retrieval-key similarity | per action-plan generation, not per step | — | ALFWorld 52.2 → 85.8; WebShop 35.0 → 48.0 | low-medium |
| **AgentKB** 2507.06229 | `⟨problem pattern, goal, solution trajectory, context, relations⟩` | problem pattern + goal | two-stage: student retrieves workflow-level, teacher retrieves step-level after reading the failure | LLM-generated from logs, seeded by annotated failure cases | GAIA GPT-4.1 55.15 → 61.21; SWE-bench o3-mini 23.0 → 31.67 | medium — the two-stage read is a repair-time idea |
| **MemGuard** 2608.21867 | any record + descriptor `(reward, confidence, verifier label, verification time)` | — | descriptor-aware, not semantic-only | admission needs R≥0.70 ∧ c≥0.60; merge duplicates by structured signature; conflict resolution; archive stale under a fixed budget | vs ReasoningBank: WebArena 50.5 → 58.4; semantic-only retrieval ablation 50.1 | **high** — the only paper that treats *staleness* as a first-class problem |
| **Voyager** 2305.16291 | skill = executable code + description | **description embedding** (ada-002) | top-5, query = an LLM-written "general suggestion" + env feedback | admitted only after GPT-4 self-verification | w/o skill library, progress plateaus | medium — description-as-key is the durable idea |
| **SkillWeaver** 2504.07079 | API = signature + docstring (incl. **preconditions**) + Playwright code + usage log | website | API-selection module filters by precondition satisfaction | propose → practise → synthesize → hone (LLM-written unit tests); ~160 iterations/site | WebArena 25 → 29.8; live sites +39.8% rel; weak-to-strong up to 54.3% | **high** — closest published system to `netgent generate` |
| **ASI** 2504.06821 | verified Python skill **in the action space** | — | called as a first-class action | admitted only if (a) trajectory solves the task, (b) uses the new skill, (c) every skill call changes the environment observably | +23.5% over vanilla, **+11.3% over AWM's text skills**, steps −15.3% | **highest** — the empirical case for verified, non-prose artifacts |
| **Go-Browse** 2506.03533 | graph G=(V,E): V = unique **URLs**, E = trajectories; plus a frontier queue | **URL** | reset exploration to a discovered URL instead of the root | feasibility-checked (≤3 tries + VLM judge); keeps successes *and* failures (9,504 / 17,245) | Go-Browse-7B 21.7% WebArena | **high** — state-keyed exploration memory |
| **WebXSkill** 2604.13318 | parameterized action program + step-level NL guidance | **URL-keyed graph** | graph lookup | mined from synthetic trajectories | +9.8 pts WebArena, +12.9 WebVoyager | high — URL-keyed indexing |
| **AgentRR** 2505.17716 | two levels: exact action sequences, and generalized procedures; plus **check functions** | task | — | position paper, no numbers | — | conceptual — its check-function taxonomy (flow integrity, state preconditions, data constraints, safety invariants) is a good checklist for our triggers |
| **Claude Skills** (Claude Code docs) | `SKILL.md`: frontmatter + markdown body | `description` (+`when_to_use`), truncated at 1,536 chars in the listing; `paths` globs scope activation | model reads descriptions, loads the body only on use ("progressive disclosure") | `/verify` records what worked and **"edits the recorded file only when it steered a run wrong"**; the earlier fold-in-everything policy "caused frequent merge conflicts" | — | **high** — a shipped, correction-only write policy (§C.2) |

Out of scope, checked and excluded: **GUI-Odyssey** (arXiv:2406.08451) is a dataset — 8,334 cross-app
episodes, 15.3 steps average, 212 apps — and OdysseyAgent's "history resampler" is *within*-episode
screenshot attention, not cross-run memory. **Mobile-Agent-v3** (arXiv:2508.15144) has a Notetaker
that writes notes on successful steps only, but the paper does not describe task-level persistence;
AndroidWorld 73.3, OSWorld-Verified 37.7.

## B.2 The multi-episode induction step, system by system

### B.2.1 AWM — the induction prompt, the abstraction levers, and the dedup

**The induction prompt, verbatim** (`webarena/prompt/instruction.txt` @ `main`):

> Given a list of web navigation tasks, your task is to extract the common workflows to solve these
> tasks. Each given task contains a natural language instruction, and a series of actions to solve
> the task. You need to find the repetitive subset of actions across multiple tasks, and extract each
> of them out as a workflow.
> Each workflow should be a commonly-reused sub-routine of the tasks. **Do not generate similar or
> overlapping workflows. Each workflow should have at least two steps. Represent the non-fixed
> elements (input text, button strings) with descriptive variable names as shown in the example.**
> Keep the values of invariant elements, e.g., id of "Search" or "Customers", as they will share and
> stay invariant across tasks.
> Try to generate as many workflows that can cover all the tasks in the input list.

Three things to note. (a) The anti-redundancy rule is a *prompt instruction*, not an algorithm.
(b) "Keep the values of invariant elements" is the flip side of ReUseIt's Important Constraint — AWM
tells the model what to *keep* literal, ReUseIt tells it what to *strip*. (c) The induced artifact's
header is `# name` + a one-line docstring, and that docstring encodes a **precondition**:

```
# enter_flight_locations
Given that you are on the Delta flight booking page, this workflow enters the departure and
destination city/airport for your flight.
[link]  {link to enter departure city} -> CLICK
[textbox]  {textbox to input departure city} -> TYPE: {your-origin-city}
[link]  {best-popup-option} -> CLICK
```

**The abstraction lever is a knob with two settings**, and the repo ships both prompts:

| Prompt file | Element descriptor | Typed value | Example |
|---|---|---|---|
| `one_shot_action.txt` | **literal** | placeholder | `[textbox] Origin City or Airport -> TYPE: {your-origin-city}` |
| `one_shot_abstract.txt` | **placeholder** | placeholder | `[textbox] {textbox to input departure city} -> TYPE: {your-origin-city}` |

This is exactly NetGent's choice about how much of a locator to abstract, and AWM's own ablation says
the answer barely matters for *them* (text 45.4 vs code 45.1 step SR on Mind2Web) — because their
element ids are stable WebArena a11y ids. On live sites it is the whole game.

**Deduplication is two-stage and rule-based** (`webarena/induce_rule.py`):

1. Group by `intent_template_id`, sample one per group.
2. Compute an **abstract trajectory signature** — for each action, `f"{action}({first_arg})"`, all
   joined by `_`, with `send_msg_to_user` reduced to its bare name — and keep one workflow per
   distinct signature.

That signature is the closest thing in the literature to an alignment key, and it is the direct
ancestor of the key proposed in §C.1.1. Note also the pre-filter: malformed `click`/`fill` are
dropped and **all `scroll` and `noop` steps are removed** before induction.

**Retrieval** (`mind2web/workflow/retrieve.py`): FAISS over `text-embedding-ada-002` embeddings of
`f"{w['name']}\n{w['docstring']}"`, `similarity_search_with_score`, `top_k` default 10, with a
`random` baseline mode for ablation. WebArena instead injects the entire per-site workflow file.

**Quality metrics** (Table 10): ~7.4 workflows per website on WebArena, 7.3 on Mind2Web; **function
overlap 0.08 / 0.20**, computed by "counting the number of overlapping sub-trajectories (≤ 2 steps)
between each workflow pair for the same website"; utility rate 0.94 / 0.91; Mind2Web coverage only
0.40. Ablations: rule vs LM induction 35.6 vs 35.5 SR on WebArena (LM wins on steps, 5.9 vs 6.3) but
LM wins by 2.8 step-SR on Mind2Web, attributed to "abstract representation of example-specific
contexts."

**The failure mode AWM documents about itself**, and the one to take seriously: *"agents still
encounter some challenges in identifying places to diverge from the workflow guidelines"*, and
Appendix C reports that **combining offline and online workflows underperforms either alone** —
"offline workflows seem to impair the generative quality and utility efficacy of online workflows."
Memory contamination, measured, by the authors.

### B.2.2 ReasoningBank + MaTTS — the same-query self-contrast prompt

This is the closest published match to NetGent's `--runs N`. Code at
`github.com/google-research/reasoning-bank`. The relevant prompt is `PARALLEL_SI` in
`WebArena/prompts/memory_instruction.py`, quoted verbatim because it is the artifact the brief asks
for:

> You are an expert in web navigation. You will be given a user query and multiple trajectories
> showing how an agent attempted the task. Some trajectories may be successful, and others may have
> failed.
>
> **Guidelines** — Your goal is to **compare and contrast** these trajectories to identify the most
> useful and generalizable strategies as memory items. Use **self-contrast reasoning**:
> - Identify patterns and strategies that consistently led to success.
> - Identify mistakes or inefficiencies from failed trajectories and formulate preventative strategies.
> - Prefer strategies that generalize beyond specific pages or exact wording.
>
> **Important notes** — Think first: Why did some trajectories succeed while others failed? You can
> extract *at most 5* memory items from all trajectories combined. Do not repeat similar or
> overlapping items. Do not mention specific websites, queries, or string contents — focus on
> generalizable behaviors and reasoning patterns.

The single-trajectory prompts (`SUCCESSFUL_SI`, `FAILED_SI`) cap at 3 items each and carry the same
value-agnostic constraint: *"Prefer concrete, actionable procedures over abstract principles. Do not
embed specific product names, queries, or literal string contents from the task."* The `FAILED_SI`
variant asks the model to *"first reflect and think why the trajectory failed, and then summarize
what lessons you have learned or strategies to prevent the failure."*

The schema field worth copying is the description: **"one sentence summary describing when *or when
NOT* to use the memory item"** — a negative-applicability clause baked into the retrieval key. Nobody
else does this and it is the cheapest defence against the AWM contamination failure.

Numbers that matter here:

| | Shopping | Admin | Gitlab | Reddit | **Multi** | Overall |
|---|---|---|---|---|---|---|
| No Memory (Gemini-2.5-flash) | 39.0 | 44.5 | 33.9 | 55.7 | 10.3 | 40.5 |
| Synapse | 40.6 | 45.1 | 35.6 | 59.4 | 10.3 | 42.1 |
| AWM | 44.4 | 46.7 | 37.2 | 62.3 | **3.4** | 44.1 |
| ReasoningBank | 49.7 | 51.1 | 40.6 | 67.0 | 13.8 | 48.8 |
| + MaTTS (k=5, parallel) | 53.0 | 53.8 | 42.8 | 70.8 | 17.2 | 51.8 |

The Multi column is cross-site transfer. **AWM is worse than no memory at all** there — 10.3 → 3.4 on
flash, 6.9 → 3.4 on pro — and AWM is also below No Memory overall on Claude-3.7 (41.7 → 40.8). This
is the single most important negative result in the survey.

The MaTTS ablation on WebArena-Shopping (Gemini-2.5-flash):

- MaTTS parallel k=1 → k=5: **49.7 → 55.1**; vanilla TTS (same rollouts, memory induced per-trajectory
  with no aggregation) reaches only **52.4**; sequential 49.7 → 54.5 vs 51.9.
- **Without** memory, parallel scaling just fluctuates between 39.0 and 42.2.
- Pass@1 (average trajectory quality after curation) rises 49.7 → 53.0 for ReasoningBank, but only
  40.6 → 41.2 for Synapse and 44.4 → 45.5 for AWM: *"scaling actually reduces performance for weaker
  memories."*

Success-only vs with-failures, same subset:

| Memory | success-only | + failures |
|---|---|---|
| Synapse | 40.6 | 41.7 |
| **AWM** | 44.4 | **42.2** |
| ReasoningBank | 46.5 | **49.7** |
| (No memory) | 39.0 | — |

**The representation, not the data, decides whether failures help.** Pouring failed trajectories into
a trajectory-shaped memory poisons it; pouring them into an abstracted-strategy memory helps.

Robustness to judge noise, measured: their LLM-as-judge is 72.7% accurate against ground truth, and
simulating judge accuracy from 100% down to 50% moves SR only from 52.4 to ~47.6, with 70–90%
essentially flat. So a ~70%-precision judge (AgentRewardBench's figure) is good enough *for this
memory shape* — a useful calibration for our verifier.

Efficiency: steps drop up to 1.4 vs No Memory and 1.6 vs other memory baselines, and the reduction is
larger on *successful* cases (up to 2.1 steps, 26.9% relative) — i.e. the memory shortens the right
path rather than truncating the wrong one.

### B.2.3 WISE-Flow — the task-wise vs trajectory-wise ablation

arXiv:2601.08158 (Zhou, Wang, Yuan, Wang, Koelle, Zhu, Niu; 2026-01-14). The only paper that
*isolates* the question "should I induce one artifact per trajectory, or one per task from all its
trajectories?"

Their induction is a **three-pass procedure**: (i) *analysis* identifies the goal-consistent action
sequence and the key environment feedback explaining failures; (ii) *drafting* synthesizes a candidate
workflow with explicit steps and per-action prerequisites; (iii) *reflection and revision* "validates
each step, prerequisite, and branching condition against trajectories, removing or fixing unsupported
or non-executable recommendations." That third pass is a version-space consistency check performed by
an LLM.

Their contrast construction is the sharpest in the literature and is worth copying wholesale:
partition the trajectories for each task into **clean successes** (no tool-call errors), **recovered
successes** (errors, later recovered), and **failures**; then pair a clean success with a recovered
success or a failure. *"Contrastive comparisons isolate the minimal deviations that separate success
from failure and encode them as explicit ordering constraints and prerequisites in the workflow."*

Their workflow representation is an NFA in all but name: a **backbone** (short description + ordered
milestones, used for progress alignment) plus **action blocks**, each with explicit global and
scenario-specific **prerequisites** and **conditional next-step transitions grounded in environment
feedback**. Compare `schema/workflow.py`: `State.conditions` = prerequisites, `Transition` = action
block, `Branch` = conditional transitions, `Milestone` already exists in `schema/control.py`.

The ablation (ToolSandbox, same retrieval and evaluation for both arms):

| | Trajectory-wise | Task-wise | Δ |
|---|---|---|---|
| Similarity | 0.8824 | 0.9136 | +0.0312 |
| F_β | 0.9433 | 0.9755 | +0.0322 |
| SR | 94.23% | 97.54% | figure labels **+6.00 pp** (see §D) |

Their explanation is the mechanism NetGent should internalize: *"A workflow induced from a single
trajectory can include some unnecessary or even false steps in the trial, whereas task-wise induction
lets the LLM compare different attempts and summarize a more stable, task-relevant action pattern
into a consolidated workflow. This is more effective than presenting all trajectories to the agent
and asking it to perform the comparison during task execution."*

That last clause is a direct argument for NetGent's architecture: do the comparison **at compile
time**, put the result in the artifact, and the replayer never has to compare anything.

### B.2.4 ASI — verification is what makes induction worth doing

arXiv:2504.06821. Induces a Python skill from a trajectory and admits it only if three checks pass:
(a) the rewritten trajectory still solves the task, (b) it actually calls the new skill, (c) every
skill-calling action produces an observable environment change. Note the direction of the numbers:
ASI's induction **pass rate is 15.6% vs AWM's 31.4%** — verification rejects twice as much — and it
still wins by 11.3 points. Two further decompositions: putting programs in the *action space* rather
than text in memory is worth +3.7%, and converting already-verified programs back to text costs most
of the gain (+2.6% only). Step count drops 10.7–15.3%.

For NetGent this is the strongest external justification of two design choices already made: the
artifact is declarative-but-checkable (not prose), and admission should be gated on a replay, not on
a judge's opinion.

### B.2.5 SkillWeaver — practice as the multi-episode signal

arXiv:2504.07079. A skill is a signature + docstring (documenting **prerequisites**) + Playwright code
+ a **usage log** recording attempts, successes, failures and observed behaviours. The three stages
are propose → synthesize (practise the task, convert the successful trajectory to an API,
static-analyse) → **hone** (an LLM writes unit tests with generated parameter values, executes them,
debugs the failures). ~160 exploration iterations per website. The API-selection module filters by
precondition satisfaction before the agent sees the library.

The honing loop is the direct analogue of running a compiled NetGent workflow k times with different
`--param` values. Their weak-to-strong result (a weaker agent using a stronger agent's APIs gains up
to 54.3%) is the argument for compiling with a strong model and replaying with none.

They explicitly do **not** address skills breaking when the site changes — the docstring records
prerequisites and the usage log records surprises, and that is all.

### B.2.6 The PBD lineage — the only *algorithmic* multi-demonstration merge

**SMARTedit / version space algebra** (Lau, Wolfman, Domingos & Weld, *Machine Learning* 53, 2003).
The formalism: a version space `VS_{H,D}` is the set of hypotheses in `H` consistent with the
*sequence* `D` of examples; *"When a new example is observed, the version space must be updated to
ensure that it remains consistent with the new example by removing the hypotheses that are
inconsistent with it."* Complex program spaces are built by **composing** simpler version spaces
(join, union) — hence "algebra".

Three empirical findings that transfer directly:

1. **1–2 demonstrations suffice under a strong prior.** *"a program that generalizes correctly for
   each of these scenarios can be learned quickly in as few as one or two training examples."*
2. **Users won't give you more.** *"in our study, users did not want to demonstrate more than one or
   two iterations of the program."*
3. **The failure mode is the late anomalous example.** Their pickle-array scenario: after two
   iterations the learned program is correct for iterations 3–18, but iteration 19 crosses a row
   boundary; two hypotheses that had been jointly consistent now disagree, and *the wrong one has
   higher probability*. Their metric therefore scores it as needing nineteen iterations — "whereas if
   it had been given the nineteenth example earlier, it would have required only three." Their
   proposed fix is **active learning: identify anomalous examples earlier.**

That is the entire design brief for NetGent's `--runs N`: a small N is enough *if* the hypothesis
space is constrained, and the risk you are buying down with extra runs is specifically the rare
divergent condition (the cookie wall that appears one time in five). It also says the right knob is
not "raise N" but "add a run that is likely to be different" — i.e. `--variation`.

**Rousillon / Helena** (Chasins, Mueller & Bodík, UIST 2018): a web scraper written by demonstrating
how to collect *the first row* of a hierarchical dataset; novel relation-selection and generalization
algorithms lift that one demonstration to all rows; the result is editable in a block language. 15 CS
participants wrote hierarchical scrapers **8× faster** than by traditional programming.
**WebRobot** (PLDI 2022, arXiv:2203.09993): "speculative rewriting" — a speculate-and-validate
methodology inside rewrite-based program synthesis, learning RPA programs from demonstrations;
automates the majority of 76 web RPA benchmarks.

The lineage's collective lesson: **a typed, restricted hypothesis space is what buys you generalization
from few examples.** ReUseIt and AWM have no hypothesis space at all, so they need 20 runs and an LLM.
NetGent's `schema/` *is* a hypothesis space.

### B.2.7 Synapse — abstraction as the thing that makes an exemplar reusable

arXiv:2306.07863. Three parts: **state abstraction** (filter task-irrelevant page content, so more
exemplars fit in context), **trajectory-as-exemplar prompting** (the exemplar is a whole
state-action sequence, not a step or a plan), **exemplar memory** (embed, retrieve by similarity).
99.2% mean success across 64 MiniWoB++ tasks from demonstrations of only 48; +56% relative step SR on
Mind2Web. The transferable claim: the unit of memory is a trajectory, and abstraction is what makes
storing whole trajectories affordable. NetGent's `browser/dom/serializer.py` is our state abstractor
and it already runs on every step.

## B.3 State- and graph-shaped memory: keyed by *where*, not by *what*

- **AutoGuide** (2403.08978) is the cleanest statement of the idea. Guidelines are extracted by
  contrasting a high-return with a low-return trajectory **at the timestep where they diverge**, and
  they are stored in a dictionary **keyed by a natural-language context** ("On the Reddit main page"),
  retrieved by first identifying the current context and then taking top-k (2–3) *within* it. The
  reported gap over ExpeL — which injects all guidelines with no context filter — is large on every
  benchmark (ALFWorld 59.0 → 79.1; WebShop 35 → 46; WebArena 21.8 → 47.1). For an NFA, "keyed by
  context" is free: a guideline attaches to a `State`.
- **Go-Browse** (2506.03533) maintains `G = (V, E)` where V is unique **URLs** and E is trajectories,
  plus a frontier queue, and resets exploration to a discovered URL rather than the root. It keeps
  9,504 successful and 17,245 unsuccessful trajectories (39,339 vs 157,123 steps), ≤30 feasible tasks
  per URL over 100 URLs. The reusable idea is that **the page graph is the durable object and the
  trajectories are samples of its edges** — which is exactly NetGent's formalism.
- **WebXSkill** (2604.13318) indexes parameterized skills in a **URL-keyed graph**; +9.8 pts WebArena.
- **World models** are the other way to reuse trajectories: **WMA** (2410.13232) trains an
  observation-*transition* predictor by matching elements across consecutive observations with the
  Hungarian algorithm and describing only UPDATED/DELETED/ADDED elements in NL; WebArena GPT-4o 16.6%
  (+29.7% rel), 5.3× faster and 6.8× cheaper than tree search. **WebDreamer** (2411.06559) simulates
  in NL without any training. Both are inference-time; neither produces a durable artifact. Not for
  us — except that WMA's transition-diff abstraction is a good serializer idea, and it is the same
  observation as `browser-agent-memory.md` §4's diff-history result.

## B.4 What the retrieval key actually is

Ranked by how well the key matches what the artifact is *about*:

| Key | Systems | Verdict for NetGent |
|---|---|---|
| **State / URL / context** | AutoGuide, Go-Browse, WebXSkill, Rememberer (observation term dominates) | **Right for us.** We know the site and the state exactly; no embedding needed for site-scoped memory. |
| **Task description embedding** | AWM (`name\ndocstring`, ada-002, top-10), Synapse, ReasoningBank, ExpeL, Memento, Memp | Right for a *workflow library* (`Call`), where the query is a new task string. |
| **Skill description embedding** | Voyager (top-5, query = LLM-written "general suggestion" + env feedback) | Same as above; Voyager's trick of querying with a generated *intent* rather than the raw task is worth noting. |
| **Precondition satisfaction** | SkillWeaver (API selection filters by precondition), AgentRR (check functions) | This is a `Trigger` evaluation. Free for us, and strictly more reliable than similarity. |
| **Descriptor-aware (reward, confidence, verifier label, recency)** | MemGuard | The missing dimension everywhere else; see §B.6. |
| **File-path globs** | Claude Skills (`paths`) | The desktop analogue of URL-keying. |

Note the recurring shape: **name + one-line description is the key; the body is the payload, loaded
only on a hit.** AWM (`name\ndocstring`), Voyager (description embedding), ReasoningBank
(`title`/`description`), and Claude Skills (`description` + `when_to_use`, capped at 1,536 chars,
body loaded lazily) all converged on it independently.

## B.5 The ablation ledger — what actually moves the needle

Everything below is measured, with the arm that isolates the claim.

| Claim | Evidence |
|---|---|
| **Aggregating same-task trajectories beats one-per-trajectory** | WISE-Flow: Sim +0.0312, F_β +0.0322. ReasoningBank MaTTS at k=5: 55.1 (aggregated) vs 52.4 (vanilla TTS, same rollouts). |
| **Memory ON vs OFF is worth ~+8 points on WebArena** | ReasoningBank 40.5 → 48.8 (flash), 46.7 → 53.9 (pro), 41.7 → 46.3 (Claude-3.7). AWM 23.5 → 35.5 on its own setup. |
| **…but memory can be net negative under shift** | AWM on WebArena-Multi: 10.3 → 3.4 (flash), 6.9 → 3.4 (pro); overall on Claude-3.7 41.7 → 40.8. AWM's own Appendix C: offline+online combined underperforms either. |
| **Granularity: abstraction > raw trajectory** | ReasoningBank (distilled items) > Synapse (raw trajectories) > No Memory on every backbone. ASI (verified programs) > AWM (text workflows) by 11.3 pts. Memp: scripts generalize to new tasks, trajectories win on familiar ones — combine both. |
| **Verification at induction is worth more than induction volume** | ASI admits 15.6% vs AWM's 31.4% and wins by 11.3 pts. |
| **Failures help only if the representation abstracts** | Success-only → +failures: AWM 44.4 → 42.2 (worse); Synapse 40.6 → 41.7; ReasoningBank 46.5 → 49.7. |
| **Failure-derived guards, priced honestly** | ReUseIt success-traces 41.4 → guards-only 50.1 → guards+fallbacks 70.1. |
| **State-conditioned retrieval > flat injection** | AutoGuide vs ExpeL: ALFWorld 59.0 → 79.1, WebShop 35 → 46, WebArena 21.8 → 47.1. |
| **Retrieval count saturates and then hurts** | Memento K=4 optimal (F1 64.5), declines beyond — the CBR "swamping problem". Memp: performance plateaus with too many retrieved memories. |
| **Judge noise is tolerable for abstracted memory** | ReasoningBank: real judge 72.7% accurate; simulated 100%→50% moves SR 52.4 → ~47.6, flat across 70–90%. |
| **…but judges are systematically over-optimistic** | AgentRewardBench: best judges ~70% precision (30% of "successes" are not); rule-based on WebArena P 79.0 / R 55.9 (under-reports). PAE evaluator: 1.7% system-level, 8.6% instance-level misalignment. |
| **Governance (dedup, conflict resolution, archival) is worth as much as retrieval** | MemGuard vs ReasoningBank: WebArena 50.5 → 58.4. Ablations: w/o governance 52.0, w/o admission 52.8, semantic-only retrieval 50.1. |
| **Memory reduces steps as well as raising success** | AWM 7.9 → 5.9; ASI −10.7 to −15.3%; ReasoningBank up to −2.1 steps on successful cases (−26.9% relative). |
| **Few demonstrations suffice under a typed prior** | SMARTedit: correct programs from 1–2 examples across their scenario suite. |

## B.6 Failure modes: contamination, staleness, and who writes

**Contamination.** AWM's cross-site collapse and its own offline+online result are the same
phenomenon: a memory that encodes *the path* rather than *the invariant* is a liability the moment the
target moves. ReasoningBank's fix is representational (strategies, not steps, with a "when NOT to use"
clause in the key). AutoGuide's fix is retrieval-side (never show a guideline outside its context).

**Staleness.** Only **MemGuard** (arXiv:2608.21867, 2026-08-22) treats it directly. Every record
carries a descriptor `d_m = (R_m, c_m, ℓ_m, ν_m)` — trajectory reward, confidence, verifier label
(`verified_success` / `verified_fail` / `uncertain`), verification time — and that descriptor governs
admission (`R ≥ 0.70 ∧ c ≥ 0.60`), retrieval, **duplicate merging by structured signature**, conflict
resolution (by label, reward, confidence, recency, usage), summarization and archival under a fixed
active-memory budget. Ablating governance costs more than ablating admission (WebArena 58.4 → 52.0 vs
52.8), and a verifier-only baseline — one-time filtering, no persisted signals — loses in all 16
backbone×benchmark settings. Translation for us: *the verdict must be stored with the record, not
consumed at the door.*

**Write policy.** The spectrum, with evidence:

- *Success-only*: AWM, Synapse, Voyager. Simple; loses the guard signal; brittle under shift.
- *Judged, both outcomes*: ReasoningBank, Go-Browse, Memp. Best measured results; needs an abstracting
  representation.
- *Failure-mined for guards*: ReUseIt, AutoGuide, WISE-Flow, AutoManual (its "Corrected Error" /
  "Unsolved Error" rule types). Right shape for *conditions*.
- *Correction-only*: **Claude Code's `/verify`**, the only shipped instance found. It records what
  worked to `.claude/skills/verify/SKILL.md`, and — per the docs — *"Claude edits the recorded file
  only when it steered a run wrong, such as a command that failed or a missing step, so you can commit
  the file without per-session diffs."* The prior policy ("fold in anything a run learned") **"caused
  frequent merge conflicts."** For a memory file that lives in git next to a repo — which is exactly
  what a NetGent site-memory file would be — this is the policy with production evidence behind it.

## B.7 The independence question

If run *k* is seeded with memory from runs 1..*k*−1, the N runs are no longer independent samples.
What the literature says:

**The case that shared memory across parallel rollouts is good:** ReasoningBank's MaTTS. Parallel
scaling with shared memory reaches 55.1 at k=5 vs 42.2 without memory; *"high-quality memory steers
the scaled exploration toward more promising paths, while the rich experiences generated forge even
stronger memories."*

**The case that it destroys what we need:** their objective is success rate. NetGent's `--runs N`
exists to *sample the variation space* so the merge can tell invariant from incidental. Guidance that
makes run 3 walk run 1's path removes exactly the divergence the merge consumes. Three pieces of
supporting evidence:

- **Diversity has to be engineered, it is not free.** PAE's proposer prompt says, in caps, *"Your
  proposed tasks should be DIVERSE AND COVER A WIDE RANGE OF DIFFERENT POSSIBILITIES AND
  DIFFICULTY"*, and demands 25 tasks per domain at 3–7 steps. NNetNav buys diversity by
  **persona-conditioning** (16 personas per site) plus best-of-K sampling (K=3), and prunes >60% of
  episodes after 16 actions when the prefix isn't a describable subtask. Go-Browse buys it
  structurally, by resetting to frontier URLs rather than the root.
- **Over-specified memory transfers badly**: AWM's Multi-subset collapse (§B.2.2).
- **SMARTedit's anomalous-example problem** (§B.2.6) is precisely a coverage failure: the rare
  divergent iteration is the one that carries all the information, and it is the one guidance would
  suppress.

**The resolution the literature supports** is that the two goals want different memory *content*, not
different amounts. Memory that changes *nuisance* behaviour — "this site shows a consent wall",
"dates here are DD/MM/YYYY", "the search button is disabled until the field blurs" — reduces variance
without touching the task path, and is exactly what ReUseIt's Important Constraint and ReasoningBank's
"do not mention specific websites, queries, or string contents" are trying to produce. Memory that
encodes *which element to click next* is the AWM failure mode. That distinction is the policy in §C.4.

---

# Part C — proposal for NetGent

## C.1 The centrepiece: `--runs N` → the generator's merge → the NFA *is* the induced memory

Today `compile_trajectory` (`agent/generator/compiler.py`) takes exactly one trajectory, keeps only
`s.action is not None and s.error is None` (line 135), and throws every failed step away. `--runs N`
and `--variation` are described in `CLAUDE.md` but do not exist in `cli/generate.py`. The proposal is
a `compile_trajectories(trajs: list[AgentTrajectory], ...)` that subsumes the current function at
N=1 — and the whole point is that it is **pure code**, so the merge stays inside the "generator is
pure code" rule in `orchestrator.py`.

### C.1.1 The alignment key

Every `AgentStep` already carries what an alignment needs: `url`, `action` (a typed `Action` with a
durable `Locator` chain), `dialogs`, `error`. Define, per step:

```
sig(step) = (_base_url(step.url), step.action.type, _target_selector(step.action))
```

Both helpers already exist in `compiler.py`. This is AWM's `get_abstract_trajectory` signature
(`action(first_arg)` joined by `_`) with two upgrades: a durable Playwright locator instead of a
volatile numeric a11y id, and the page identity included. AWM had to dedup *whole* trajectories by
this signature; we can align *step-by-step* with it.

Merge = a multiple-sequence alignment over `sig` across the N successful trajectories (a standard
progressive alignment on N short sequences; typical trajectories are 5–25 steps, so cost is
irrelevant). Steps that align form a column; unaligned steps form a gap.

### C.1.2 Conditions by version-space intersection

This is the mechanism the literature does not have, and it falls out of the formalism for free.

Treat each candidate condition as a hypothesis and each run as a training example. For an aligned
column *c*, the current compiler would propose `url_matches(re.escape(base))` and
`selector_visible(next_target)`. Instead:

- **Emit a condition only if it held in every run at that column.** A `url_matches` pattern becomes
  the longest common prefix of the N base URLs (or is dropped if they share nothing meaningful); a
  `selector_visible` is emitted only if the same selector was the aligned next-target in all N runs.
- **A condition that held in some runs and not others is not a condition — it is a divergence**, and
  it is routed by §C.1.3.
- **Record support.** Each emitted `Trigger` carries how many of the N runs witnessed it. That is
  MemGuard's descriptor idea in typed form, and it makes a later `--runs` top-up incremental rather
  than a full recompile.

This is literally SMARTedit's version space: the hypothesis set is the conditions expressible in
`schema/triggers.py`, and each new run removes the inconsistent ones. It is also the deterministic
version of WISE-Flow's third pass ("validates each step, prerequisite and branching condition against
trajectories, removing unsupported recommendations") — they need an LLM because their artifact is
prose; we do not.

It also fixes a known bug directly. `compiler.py:162` gives same-page steps `conditions=[]`, so a fill
that silently no-ops replays "successfully". With N runs, a same-page column that produced an
observable change in all N (a new element, a dialog, a text) yields a real post-condition; one that
produced nothing is honestly reported as unguarded.

### C.1.3 Divergence has exactly four dispositions

| What the alignment shows | Compile to | Precedent |
|---|---|---|
| Same `sig`, **different value field** (`text`/`value`/`url`) across runs | a **`Param`** — with the observed values as evidence, and `guard` set from their common shape | AWM `{placeholder}`; ReUseIt attribute variation |
| Step present in *k < N* runs, its removal leaves the rest of the alignment intact, its target selector looks like a dismissal control, and the page it fires on is in scope | an **`Interrupt`** (`state` = anchor, `resolve` = the step, `scope` = the aligned states on that base URL, `max_fires` = 3) | our own `2026-08-27-anchored-states-and-interrupts.md` |
| Step present in *k < N* runs **and** the alignment diverges downstream | a **`Branch`** with one arm per observed continuation, `when` = the state whose conditions distinguish them | ReUseIt has no equivalent — this is where we exceed it |
| Divergence with no distinguishing state condition | **reject**: emit a compile warning naming the column, and (if `--runs` budget remains) request one more run | SMARTedit's active learning for anomalous examples |

The `Interrupt` case is worth dwelling on. Today `_is_interruption` (`compiler.py:142`) is a
conjunction of two *text* heuristics — reasoning text matching `ads?|pop-?ups?|cookies?|consent|…`
**and** target selector matching `skip|dismiss|close|…` — and the decision doc explicitly flags this as
provisional, to be upgraded to an `is_interruption` flag on `AgentDecision`. **Cross-run presence is a
better signal than either.** "A step that appears in 2 of 5 runs and whose omission does not disturb
the alignment" is close to the definition of an ε-transition. Keep the text heuristics as a
tie-breaker, not as the classifier.

### C.1.4 `--variation` gets a principled meaning

Adopt ReUseIt's Appendix C.1 taxonomy verbatim (the prompt is reusable as-is) and bind each level to a
NetGent construct:

| Variation | ReUseIt's definition | NetGent construct | Runs it justifies |
|---|---|---|---|
| **Attribute** — "modify specific input values … entered on the same webpage" | different values, same page | **`Param`** | the bulk of N: this is what makes the value columns vary so `_bind_params` can be *derived* rather than declared |
| **Category** — "modify a high-level option that requires switching a tab, toggle, or category within the same website" | different arm, same site | **`Branch`** | 1–2 runs; produces the second arm |
| **Website** — "change the target website … keeping the objective unchanged" | different layout | a **separate workflow** (+ a library entry for `Call`) | 0 by default — do not merge across sites |

The third row is a deliberate divergence from ReUseIt. They merge across websites into one prose
workflow; the measured consequence of doing that with a trajectory-shaped memory is AWM's Multi-subset
collapse (10.3 → 3.4). NetGent should compile one NFA per site and let the *library* carry the
cross-site relationship.

This also retires today's declare-then-sweep parameter binding. `_bind_params` requires the caller to
name `-p name=sample` up front and warns `"parameter 'x' was never bound"` (`compiler.py:280`) when
the literal sweep misses. With attribute variations, the varying columns are **observed**, so params
can be *proposed* by the merge and only *named* by the caller.

### C.1.5 Failed runs: what to keep, and where it goes

Keep the failed steps (they are already in `AgentStep` with `error` set; only the compiler filters
them). Their disposition:

- A step that **failed in run i and succeeded in run j after an extra preceding step** → the extra
  step's post-condition becomes a `Trigger` on the source state of the failing edge. This is ReUseIt's
  C.2 mechanism with DOM evidence instead of English error prose, and WISE-Flow's "minimal deviation
  that separates success from failure".
- A step that **failed in every run** → the column is dropped from the word and reported, not guessed
  at.
- A **run that failed entirely** → contributes conditions and interrupts only. Never structure. (Same
  rule as ReUseIt, for a different reason: our structure comes from the alignment of the *successes*,
  which is strictly better than their "pick one plan".)

Guard against the measured hazard: ReasoningBank's ablation shows failures poison a
*trajectory*-shaped memory. Ours is not trajectory-shaped — a failure contributes a `Trigger`, never a
`Transition` — so the mechanism that hurt AWM does not apply. Say so explicitly in the compiler
docstring so nobody "improves" it by mining fallback *actions* from failures.

### C.1.6 Budget

N=3 by default (1 base + 1 attribute variation + 1 category variation, or 3 attribute samples when no
category variation exists), with `--runs` top-up triggered by unresolved divergence columns. Rationale:
SMARTedit needs 1–2 under a typed prior and we have one; ReUseIt's 20 buys them a *prose* structure
they can't check; the marginal run should be spent where the version space is still ambiguous, not
uniformly. Report the wall-clock and token cost per compile — ReUseIt reports 15:20–52:40 of synthesis
per task family and no token figure at all, and cost is the axis NetGent wins by construction.

## C.2 Across invocations on the same site: a site-memory file

Separate object, separate rules. Not the workflow, not a trajectory store.

**Location and key.** `~/.netgent/sites/<etld+1>.md` (or repo-local, committed). Keyed by registrable
domain — an exact key, no embeddings. This is Go-Browse/WebXSkill's URL-keying and Claude Skills'
`paths` globbing; we know the site, so similarity search buys nothing.

**Shape.** Two sections.

1. **Robustness hints** — ReasoningBank's item schema, unchanged, because it is the smallest
   structure that carries a usable retrieval key and a negative-applicability clause:
   `{title, description ("one sentence summary describing when or when NOT to use"), content (1–3
   sentences)}`. Content is restricted by the Important Constraint (no literals) and by the topic
   whitelist in §C.3. These are injected into `explorer/prompt.py` as a short, capped block — the
   place where site rules are currently *hard-coded* (date formats, "click Skip first", "a div with a
   name is a rich-text editor"). Those hand-written lines are the hypothesis that this file is worth
   building; induce them per site instead.
2. **An interrupt catalogue** — typed, not prose: `{anchor selector, resolve action, observed on which
   base URLs, support count}`. These seed `Interrupt` candidates for the next compile on that site,
   so a cookie wall is recognized on run 1 of the next task rather than discovered again. This is the
   only *action-shaped* thing in the file, and it is safe precisely because ε-transitions are
   off the main word by construction (`2026-08-27-anchored-states-and-interrupts.md` §2).

**Write policy — correction-only, with a descriptor.** Write an entry only when a run *contradicted*
the current file or hit something the file did not cover; do not fold in everything a successful run
learned. This is Claude Code `/verify`'s shipped policy and the reason for it is documented: the
fold-in-everything version "caused frequent merge conflicts." Every entry carries MemGuard's
descriptor — `(outcome, confidence, verifier label, timestamp, support count)` — because MemGuard's
ablation shows governance is worth more than retrieval (WebArena 58.4 vs 52.0 w/o governance vs 50.1
with semantic-only retrieval). Merge duplicates by structured signature; archive under a fixed budget;
drop entries whose support has not been reconfirmed in the last *k* compiles.

**The compiled workflow library is the *other* memory**, and it is a different mechanism: `Call` +
`schema/control.py`'s library ref, keyed by task description, retrieved by embedding — the AWM shape
(`name\ndocstring`, ada-002, top-10). That is cross-*task* reuse at generate time (does a sub-workflow
for "log in to this site" already exist?), not explorer seeding. Both are worth having; do not conflate
them. Note the sizing datum: AWM maintains ~7.3–7.4 workflows per site with 0.08–0.20 function
overlap; Memento finds K=4 optimal and degrades beyond; Memp plateaus. A site library of ~5–10 entries
with a top-3 retrieval is the shape the evidence supports.

## C.3 Never

1. **Never carry an action sequence from run *i* into run *j* of the same `generate` invocation.** The
   whole value of `--runs N` is that the runs are samples; correlating them makes the merge's
   agreement meaningless. This is the one hard rule.
2. **Never put a site-memory hint into the *artifact*.** Hints are compile-time prompt material. The
   workflow contains only `State`/`Transition`/`Trigger`/`Param`/`Branch`/`Interrupt`. Rule 1 of
   `CLAUDE.md` and the zero-LLM-at-replay contract both depend on this.
3. **Never merge across websites.** Website variation produces a second workflow, not a second arm.
   Evidence: AWM's Multi-subset collapse.
4. **Never store literal task values in site memory.** ReUseIt's Important Constraint and
   ReasoningBank's "do not mention specific websites, queries, or string contents", applied to our
   file. A remembered sample value is a privacy problem and a generalization problem at once.
5. **Never let memory accumulate monotonically.** ReUseIt's unfixed flaw. Every entry has a descriptor,
   a budget, and an archival rule from day one.
6. **Never gate admission on the LLM judge alone.** AgentRewardBench: ~70% precision, 30% false
   successes. Our advantage is that a compiled workflow can be *replayed*; make replay the admission
   test (ASI's rule (a)), with the verifier advisory as it already is in `orchestrator.py`.

## C.4 The independence policy, stated

> Within one `netgent generate --runs N`, the N exploration runs are **conditionally independent given
> the site snapshot**. Each run gets a fresh `ExplorerMemory`. The only shared state is a read-only
> snapshot of the site-memory file taken **before** the batch begins, and that snapshot may contain
> **only robustness hints and interrupt anchors** — never a step sequence, never an element to click
> for the task, never a value. Write-back to site memory happens **after** the batch completes, from
> the merged result, so nothing derived from run *i* can influence run *j*. Across invocations, the
> snapshot may differ; that is intended, and the descriptor's timestamp records it.

Current-code status, so this is actionable:

- `explore()` takes `memory: ExplorerMemory | None = None` (`explorer/graph.py:347`) and the
  orchestrator never passes one, so today's orchestrated runs already get a fresh memory. Good.
- **`ExplorerAgent` holds one `ExplorerMemory` across `run()` calls** (`explorer/agent.py:46-47`,
  `explorer/memory.py:20-22`: *"Persists across explore() calls, so ONE memory can span several
  tasks"*). That is correct for a *sweep* (21 forms, one agent) and is a correlation hazard if
  `--runs N` is ever built on top of `ExplorerAgent`. Build `--runs N` on `explore()`.
- The verifier retry loop already appends `task_suffix` to the task on re-exploration
  (`orchestrator.py:114-115, 150-157`). That is a Reflexion-style channel and it is fine — those
  attempts are *repairs of one run*, not independent samples. If `--runs N` wraps this loop, each of
  the N must get its own attempt counter and its own suffix, and the suffixes must not cross.

**And measure it.** The A/B is not success rate. Run `--runs 5` with the site snapshot ON and OFF and
report the number of **distinct aligned columns** (divergence count) and the number of `Param` /
`Branch` / `Interrupt` candidates the merge finds. If the snapshot collapses divergence, it is
contaminating the sample regardless of what it does to success rate. `evals/stress.py` and
`evals/matrix.py` are the right homes; the methodology (worktree per arm, ×3) is already established
in the explorer A/B work.

## C.5 Top-10 findings for NetGent, ranked

| # | Finding (source, number) | Concrete change | Where |
|---|---|---|---|
| 1 | **Aggregating N same-task trajectories beats one-per-trajectory** (WISE-Flow: Sim +0.031, F_β +0.032; MaTTS: 55.1 vs 52.4 at k=5) | Build `compile_trajectories(list[AgentTrajectory])`; keep `compile_trajectory` as the N=1 case | `agent/generator/compiler.py` |
| 2 | **Nobody aligns trajectories; we can, in code** (ReUseIt has no alignment, §A.3; AWM's abstract-trajectory signature is the closest prior art) | Align on `(base_url, action.type, target_selector)` — both helpers already exist | `compiler.py` (`_base_url`, `_target_selector`) |
| 3 | **Version-space intersection is the correct condition rule** (SMARTedit: 1–2 demos suffice under a typed prior; WISE-Flow's pass (iii) is the LLM version) | Emit a `Trigger` only if it held in every run at that column; store a support count | `compiler.py`, `schema/triggers.py` |
| 4 | **Success-only trajectory memory can be net negative** (AWM WebArena-Multi 10.3 → 3.4; overall on Claude-3.7 41.7 → 40.8) | Never merge across websites; website variation → a second workflow + a library entry | `cli/generate.py`, `schema/control.py` `Call` |
| 5 | **Failure-mining is worth ~+8.7, not +45.9** (ReUseIt 41.4 → 50.1 → 70.1) | Keep failed steps and mine them for `Trigger`s only; do the *guided-recovery* work (`Branch` arms) too, because that is where the +20.0 is | `compiler.py`, healing spec |
| 6 | **Representation decides whether failures help** (AWM 44.4 → 42.2 with failures; ReasoningBank 46.5 → 49.7) | Document in the compiler that failures may produce conditions, never transitions | `compiler.py` docstring |
| 7 | **Verified induction beats voluminous induction** (ASI admits 15.6% vs AWM 31.4%, wins by 11.3 pts) | Admission = the compiled workflow replays, k times, with varying params (SkillWeaver's honing loop) | `evals/stress.py`, `netgent eval` |
| 8 | **State-keyed memory beats task-keyed memory for procedures** (AutoGuide vs ExpeL: WebArena 21.8 → 47.1) | Key site memory by eTLD+1 and interrupts by base URL; no embeddings for site-scoped memory | site-memory file |
| 9 | **Governance ≥ retrieval** (MemGuard 58.4 vs 52.0 w/o governance, 50.1 semantic-only) | Every site-memory entry carries `(outcome, confidence, verifier label, timestamp, support)`; fixed budget; archival | site-memory file |
| 10 | **Correction-only writes keep a committed memory file usable** (Claude Code `/verify`; fold-in-everything "caused frequent merge conflicts") | Write to site memory only on contradiction or uncovered surprise | site-memory writer |

## C.6 What to measure, and against what

ReUseIt reports success rate and wall-clock and no cost. SKILL.nb (arXiv:2606.08049, in
`web-agent-papers.md`) reports the metric our product actually needs — **replay retention**, 91.7% of
initially-successful tasks surviving re-execution. Report, per compile:

- **Retention**: pass^k of the compiled workflow over k replays with varying `--param`.
- **Merge yield**: aligned columns, `Param` / `Branch` / `Interrupt` candidates, unresolved divergences.
- **Trigger support distribution**: how many conditions were witnessed by all N vs by a subset.
- **Cost**: tokens and dollars at compile, and **$0 at replay** — the column nobody else prints.

---

# D. Unverified, uncertain, or could not confirm

1. **WISE-Flow's SR delta.** Figure 3's bars print 94.23% and 97.54% (a 3.31 pp gap) while the figure's
   own label reads "+6.00pp". Two-column PDF extraction may have mispaired a bar with its label. The
   similarity and F_β deltas (+0.0312, +0.0322) are internally consistent and are the ones I rely on.
2. **AutoGuide's WebArena numbers** (ReAct 8.0 → AutoGuide 47.1) come from an ar5iv-rendered summary. A
   47.1% WebArena success rate would be near state of the art for the period, so this is almost
   certainly a *subset* (their evaluation is described as domain-specific), not full WebArena. Treat
   the *ordering* (AutoGuide > ExpeL > ReAct) as the claim, not the absolute value.
3. **CoScripter** (Leshed et al., CHI 2008) — could not retrieve the paper text this session (404 on
   the PDF mirror, 403 on the ACM DL full-text page). It is named in §B.2.6 only as lineage; no
   specific claim about its "sloppy programming" step syntax or keyword-based element matching is
   asserted here. Worth a follow-up: it is the ancestor of "identify the element by its label, not its
   XPath", which is what our `get_by_role(role, name=…)` locators are.
4. **Rousillon's mechanism details** (relation selection, generalization algorithm, Ringer-derived
   element identification) come from search-result summaries, not from the PDF text — the PDF
   defeated extraction. The user-study figure (8× faster, 15 CS participants) and the
   one-demonstration framing are from those summaries. The VSA/SMARTedit claims, by contrast, are
   quoted from the paper's own text.
5. **Voyager's ablation numbers.** The "w/o skill library plateaus" claim is qualitative; the paper's
   quantitative ablation is over tech-tree milestones and item counts, and I did not extract a clean
   table. Do not cite a number for it.
6. **ExpeL's ablation table** (insights-only 36/50, retrieve-only 31/55, full 39/59) is from an
   ar5iv-rendered summary and the values are rounded; the headline numbers (28.0 → 39.0 HotpotQA,
   40.0 → 59.0 ALFWorld) match the abstract and are safe.
7. **AWM's Table 10 and Table 5–8 numbers** are from an ar5iv-rendered read, not from the PDF text
   layer. The *code*-derived claims in §B.2.1 (prompts, dedup signature, retrieval) are verbatim from
   `github.com/zorazrw/agent-workflow-memory` @ `main` and are the reliable ones.
8. **ReasoningBank's Figure 8** (SR vs simulated judge accuracy) values were read from a figure
   rendered into text; the 72.7% measured judge accuracy and the qualitative flatness across 70–90%
   are from the body text and are reliable.
9. **AgentRR** (arXiv:2505.17716) is a position paper. Its two-level abstraction and check-function
   taxonomy are described in prose; there are no evaluation numbers, and I found none.
10. **"Memp" and "AgentKB" details** come from ar5iv summaries; I did not read their code. The
    directional claims (script+trajectory combination, reflexion-based update, two-stage
    student/teacher retrieval) are stated in their abstracts or method sections.
11. **AgentFly.** The brief names "AgentFly"; arXiv:2508.16153 resolves to **Memento: Fine-tuning LLM
    Agents without Fine-tuning LLMs** (Zhou et al., v1 2025-08-22). I have reported it under that
    title. If a different "AgentFly" was meant, it was not located.
12. **NetGent facts asserted here** were checked against `eugene/v2-scaffold` at the time of writing:
    `compiler.py` line numbers, `explore()`'s `memory=None` default, `ExplorerAgent`'s single shared
    `ExplorerMemory`, the absence of `--runs`/`--variation` in `cli/generate.py`, the absence of
    `validator/`, and the trigger set in `schema/triggers.py`. All are subject to drift.

---

# Bibliography (fetched this session)

**ReUseIt** — Liu, Sra, Inala & Wang. *ReUseIt: Synthesizing Reusable AI Agent Workflows for Web
Automation.* ACM IUI '26. [arXiv:2510.14308](https://arxiv.org/abs/2510.14308) v2 (2026-01-24). No code.
DOI [10.1145/3742413.3789083](https://doi.org/10.1145/3742413.3789083).

**AWM** — Wang, Mao, Fried & Neubig. *Agent Workflow Memory.* ICLR 2025.
[arXiv:2409.07429](https://arxiv.org/abs/2409.07429). Code:
[zorazrw/agent-workflow-memory](https://github.com/zorazrw/agent-workflow-memory) — `webarena/induce_prompt.py`,
`webarena/induce_rule.py`, `webarena/prompt/{instruction,one_shot}.txt`,
`mind2web/prompt/{instruction,one_shot}_{abstract,action}.txt`, `mind2web/workflow/retrieve.py`.

**ReasoningBank / MaTTS** — *ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory.*
[arXiv:2509.25140](https://arxiv.org/abs/2509.25140). Code:
[google-research/reasoning-bank](https://github.com/google-research/reasoning-bank) —
`WebArena/prompts/memory_instruction.py`, `WebArena/memory_management.py`.

**WISE-Flow** — Zhou, Wang, Yuan, Wang, Koelle, Zhu & Niu. *WISE-Flow: Workflow-Induced Structured
Experience for Self-Evolving Conversational Service Agents.*
[arXiv:2601.08158](https://arxiv.org/abs/2601.08158) (2026-01-14).

**MemGuard** — Wang, Dong, Liang, Zhang et al. *MemGuard: Persisting Verifier Signals for LLM-Agent
Memory Governance.* [arXiv:2608.21867](https://arxiv.org/abs/2608.21867) v1 (2026-08-22).

**Falsifiable Commitment Planning** — Liu, Zhao & Yao. *Falsifiable Commitment Planning for
Self-Correcting Web Agents.* [arXiv:2607.24167](https://arxiv.org/abs/2607.24167) v1 (2026-07-27).

**Synapse** — Zheng, Wang, Wang & An. ICLR 2024. [arXiv:2306.07863](https://arxiv.org/abs/2306.07863).
**ExpeL** — Zhao et al. AAAI 2024. [arXiv:2308.10144](https://arxiv.org/abs/2308.10144).
**AutoGuide** — [arXiv:2403.08978](https://arxiv.org/abs/2403.08978).
**AutoManual** — [arXiv:2405.16247](https://arxiv.org/abs/2405.16247).
**Rememberer** — [arXiv:2306.07929](https://arxiv.org/abs/2306.07929).
**RAP** — [arXiv:2402.03610](https://arxiv.org/abs/2402.03610).
**Memp** — [arXiv:2508.06433](https://arxiv.org/abs/2508.06433).
**Memento** — Zhou et al. [arXiv:2508.16153](https://arxiv.org/abs/2508.16153).
**AgentKB** — [arXiv:2507.06229](https://arxiv.org/abs/2507.06229).
**AgentRR** — Feng et al. *Get Experience from Practice: LLM Agents with Record & Replay.*
[arXiv:2505.17716](https://arxiv.org/abs/2505.17716).
**Voyager** — Wang et al. [arXiv:2305.16291](https://arxiv.org/abs/2305.16291).
**SkillWeaver** — Zheng et al. [arXiv:2504.07079](https://arxiv.org/abs/2504.07079).
**ASI** — Wang, Gandhi, Neubig & Fried. [arXiv:2504.06821](https://arxiv.org/abs/2504.06821).
**Go-Browse** — Gandhi & Neubig. [arXiv:2506.03533](https://arxiv.org/abs/2506.03533).
**NNetNav** — Murty et al. ACL 2025. [arXiv:2410.02907](https://arxiv.org/abs/2410.02907).
**PAE** — Zhou et al. ICML 2025. [arXiv:2412.13194](https://arxiv.org/abs/2412.13194).
**WMA** — [arXiv:2410.13232](https://arxiv.org/abs/2410.13232).
**AgentRewardBench** — Lù et al. [arXiv:2504.08942](https://arxiv.org/abs/2504.08942).
**GUI-Odyssey** — [arXiv:2406.08451](https://arxiv.org/abs/2406.08451).
**Mobile-Agent-v3** — [arXiv:2508.15144](https://arxiv.org/abs/2508.15144).
**WebRobot** — Dong et al. PLDI 2022. [arXiv:2203.09993](https://arxiv.org/abs/2203.09993).
**SMARTedit / Version Space Algebra** — Lau, Wolfman, Domingos & Weld. *Programming by Demonstration
Using Version Space Algebra.* Machine Learning 53, 2003.
[PDF](https://homes.cs.washington.edu/~pedrod/papers/mlj02.pdf).
**Rousillon** — Chasins, Mueller & Bodík. UIST 2018.
[DOI 10.1145/3242587.3242661](https://dl.acm.org/doi/10.1145/3242587.3242661).
**Claude Skills / Agent Skills** — [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)
(frontmatter reference, progressive disclosure, `/verify` recorded recipes).
