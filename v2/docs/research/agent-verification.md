# Agent verification — deciding whether the trajectory achieved the task and the NFA is right

**Question.** NetGent compiles at `explore → generate → validate`
([`orchestrator.py:85-138`](../../src/netgent/agent/orchestrator.py)). The only completion signal
at compile time is the explorer's own `done(success=True)`
([`explorer/decision.py:170-173`](../../src/netgent/agent/explorer/decision.py),
consumed at [`explorer/graph.py:177-187`](../../src/netgent/agent/explorer/graph.py) and gating the
pipeline at [`orchestrator.py:111-114`](../../src/netgent/agent/orchestrator.py)). We want a
**verification stage** that (1) decides from the user's task whether the trajectory actually achieved
it, (2) decides whether the compiled NFA is right, and (3) when it is not, tells `explore`/`generate`
precisely *what* is wrong, in a typed contract they can act on.

**Status.** Written 2026-08-27 against sources fetched the same day. Source claims cite a pinned
commit + line; paper claims cite arXiv id + the number as printed. This doc **builds on**
[`browser-agent-architectures.md`](browser-agent-architectures.md) — that doc settled *how many
agents and which roles* (§4.1: judges are "a good router and a bad gate"; §5.4: an advisory critic;
§5.5: zero-LLM triage). It is **not** re-derived here. This doc covers the axis that one does not:
**what is checkable, where the checks come from, and how a verdict routes back into the pipeline.**

---

## Summary (10 lines)

1. Every production system that verifies at all runs **deterministic checks first and an LLM second**, and the LLM's verdict is *evidence consumed by a deterministic gate*, never the gate — Skyvern states it in a docstring (`completion_verification.py:1-9`), browser-use in one (`service.py:1622-1628`).
2. The numbers say why: **no LLM judge exceeds 70% precision** across 1302 trajectories / 5 benchmarks / 12 judges — "30% of trajectories are erroneously marked as successful" — and judges **overestimate** success while rule-based oracles **underestimate** it (arXiv:2504.08942 §4.3, §5, Table 1).
3. All four judge failure modes AgentRewardBench found are *sycophancy toward the agent's own reasoning* (§6). **Design consequence: our judge must not see `AgentStep.reasoning/evaluation/memory`.** That is a cheap, evidence-backed change nobody in the survey has made.
4. Judge accuracy is bought by **making the criteria explicit before the run**, not by a better prompt: 30% of AutoEval's GPT-4V judge errors were "ambiguities in task specification and success criteria" (arXiv:2404.06474 §4.3). WebJudge's whole contribution is extracting **key points** from the task first (arXiv:2504.01382 §3), reaching 82.0% precision where the plain judges sit at 61–70%.
5. Stagehand already ships this shape: `generateRubric(taskSpec)` → **cached per task** → `verify(trajectory)` → per-criterion verdicts + an explicit **`evidenceInsufficient`** list, with a batch gate on unverifiable criteria (`verifierAdapter.ts:58-122,129-164`; `verifierGate.ts:1-10`).
6. "The replay ran cleanly" is a **known-broken** success oracle. SkillWeaver marked malfunctioning APIs verified because they "silenced all exceptions" (arXiv:2504.07079 §D.2.1); ASI truncates trailing actions "to avoid spurious successes" (arXiv:2504.06821 §2.3); Skyvern's judge prompt says it outright: *"a run can 'complete' without achieving the outcome."*
7. NetGent's `ValidationReport` is exactly that broken oracle today: `success` = every edge fired ([`validate.py:44-52`](../../src/netgent/agent/validator/validate.py) → [`engine.py:47,54-57`](../../src/netgent/executor/engine.py)), which is why a workflow that searched `"YouTube"` instead of `${query}` replays green (`browser-agent-prompting.md:120`).
8. The fix is already half-built and costs no new formalism: **`Workflow.accept_states` exists** ([`workflow.py:91`](../../src/netgent/schema/workflow.py)) and `Executor._reached_accept_state()` already evaluates it ([`engine.py:54-62`](../../src/netgent/executor/engine.py)); `compile_trajectory` simply never populates it. Task expectations stated in our Trigger vocabulary become that terminal state's conditions — so verification and the artifact are **the same object**.
9. `sweep.py::_form_succeeded` ([`sweep.py:66-89`](../../src/netgent/evals/sweep.py)) is already the right primitive (dialogs ∪ `texts_seen` ∪ live frame text, "never the agent's self-report"). Generalising it from a fixed marker list to task-derived expectations is the whole first slice.
10. **Build order:** (1) zero-LLM `verify` node gating `generate` on page evidence; (2) `plan_checks` (LLM, one call) → typed `Expectation`s; (3) expectations → `accept_states` in the compiler; (4) advisory judge, logged beside page truth; (5) `triage` routing. Measure on the 21-form sweep, where **ember and shadow-dom are broken fixtures** the verifier must reject even when the agent claims success (`browser-agent-date-inputs.md:24`).

---

## 1. What NetGent verifies today, precisely

| Signal | Where | What it proves | What it does not |
|---|---|---|---|
| `AgentDecision.done + success` | [`decision.py:170-173`](../../src/netgent/agent/explorer/decision.py), consumed [`graph.py:177-187`](../../src/netgent/agent/explorer/graph.py) | the model *believes* it finished | nothing about the page. It gates the entire pipeline ([`orchestrator.py:111-114`](../../src/netgent/agent/orchestrator.py)) |
| `pre-done` prompt rule | [`prompt.py:56-57`](../../src/netgent/agent/explorer/prompt.py) — *"Before done=true with success=true, re-check every TASK requirement against RECENT STEPS"* | reduces overclaiming | self-report either way |
| stuck detection | [`graph.py:118-130`](../../src/netgent/agent/explorer/graph.py), `MAX_REPEAT = 3` | the screen stopped changing | says nothing about the goal; a *successful* end state is also unchanging |
| `texts_seen` + settle watcher | [`graph.py:34,37-61,131-136`](../../src/netgent/agent/explorer/graph.py) → [`browser_agent.py:107-116,241-242`](../../src/netgent/agent/explorer/browser_agent.py) | every distinct text the walker *saw*, including transient banners hidden 3 s later | is not compared to anything at compile time — **only `sweep.py` reads it** |
| `AgentStep.dialogs` | [`browser_agent.py:86-89`](../../src/netgent/agent/explorer/browser_agent.py) | the page's own `alert()` feedback | compiled into a `dialog_matches` guard ([`compiler.py:105-106`](../../src/netgent/agent/generator/compiler.py)), never checked against the task |
| `ValidationReport` | [`validate.py:13-26,29-56`](../../src/netgent/agent/validator/validate.py) | **every edge fired and every target state's guard held**, zero LLM | *nothing about the goal*: with `accept_states` empty, `Executor` returns `True` for "the program ran without a failed edge" ([`engine.py:54-57`](../../src/netgent/executor/engine.py)) |
| `ConditionCheck{type, met}` / `EdgeOutcome` | [`records.py:13,20-25,27-40`](../../src/netgent/schema/records.py) | *which conjunct* failed on *which edge* | already enough to classify failures deterministically; nothing consumes it |
| `sweep._form_succeeded` | [`sweep.py:66-89`](../../src/netgent/evals/sweep.py) | **the only page-derived success oracle in the repo** — dialogs since a mark ∪ `texts_seen` ∪ live frame text, against `DEFAULT_MARKERS` | markers are a fixed 5-tuple, not derived from the task; lives in `evals/`, not in the pipeline |

Two structural facts matter for the design:

- **Trigger vocabulary.** This branch: `url_matches`, `title_contains`, `selector_visible`,
  `selector_hidden`, `dialog_matches` ([`triggers.py:12-65`](../../src/netgent/schema/triggers.py)).
  `eugene/v2-discovery` adds `element_visible` (durable locator chain), `text_visible` (case-insensitive
  substring) and `video_playing` (`currentTime` advances between two polls), plus
  `agent/evidence.py`, which already captures `PageEvidence{url, title, texts, video_present,
  video_playing, probes}` per step. **`text_visible` is the single most important trigger for
  verification** and it is one branch away.
- **`accept_states` is wired end to end except for the compiler.** Schema
  ([`workflow.py:91,127-129`](../../src/netgent/schema/workflow.py)), executor
  ([`engine.py:47,54-62`](../../src/netgent/executor/engine.py) — success iff some accept state's
  conditions *all* hold at program end). `compile_trajectory` never emits one
  ([`compiler.py:117-125`](../../src/netgent/agent/generator/compiler.py)).

---

## 2. The survey table

Pinned: browser-use `6ed72e1fb3693b9f990bafae4da004e0c991bd2a` (2026-08-27); Skyvern
`d081a5324bda5bdf58c640f1c59b2c40975e64c1` (2026-08-26); Stagehand
`4d88741a0e2283942f67ae7005a52d6f7e703698` (2026-08-27); workflow-use
`891267bb614c0b0821adbb0f7fffc0ebbf045a38` (2026-07-29, the pin used by
[`browser-agent-architectures.md`](browser-agent-architectures.md); HEAD is `5d2d19f`); Magentic-One
prompts from autogen `027ecf0a379bcc1d09956d46d12d44a3ad9cee14`; magentic-ui
`d3c9d13c39288257286a66daabf7c5b5fb72ee69`; WebArena `dce04686a56253aefba7b18a4fa0937cf1dc987b`;
WebVoyager `5a7896738c10bfb8b9edccce6bb0e0411f8ae569`; Agent-E `f218c3cb4b2b3e33ed08ea12da5514ab1e89cdd7`.

| System | What the verifier sees | When it runs | Output | Authority | Measured accuracy | Citation |
|---|---|---|---|---|---|---|
| **browser-use `judge`** | `task`, `final_result`, `history.agent_steps()` (**incl. the agent's own reasoning**), last ≤10 screenshots, optional `ground_truth` | once, after `done` (`use_judge=True` by default) | `JudgementResult{reasoning, verdict: bool, failure_reason, impossible_task, reached_captcha}` | **advisory** — *"does NOT override `last_result.success`… telemetry sends both values so the eval platform can compare agent vs judge"* | none published | `agent/judge.py:44-52,106-190,201-216`; `views.py:288-304`; `service.py:184-186,254-255,1587-1620,1622-1628,2270-2272` |
| **browser-use `AgentBrain`** | current browser state + screenshot | **every step** | `evaluation_previous_goal` ending "Verdict: Success/Failure/Uncertain" | self-report; feeds the next step | — | `system_prompts/system_prompt.md:187,210-214,236` |
| **browser-use `pre_done_verification`** | the agent's own results + page/screenshot | before emitting `done(success=true)` | forces `success=false` on any unmet/uncertain/unverifiable requirement | self-report, but *"Partial results with `success=false` are more valuable than overclaiming"* | — | `system_prompt.md:139-153` |
| **browser-use CI eval** | `task`, agent output, debug info, **`judge_context` = per-task success criteria written in the task file** | post-hoc, in CI | `JudgeResponse{success, explanation}` | gates CI | — | `tests/ci/evaluate_tasks.py:36-37,56,157-174` |
| **Skyvern `check-user-goal`** | parsed page elements, screenshots (unless `without_screenshots`), `navigation_goal`, `navigation_payload`, `action_history`, `complete_criterion`, `new_elements_ids`, `local_datetime` | per step, inside the navigate loop | `{page_info, thoughts, user_goal_achieved: bool}` | decides `COMPLETE` for that block | — | `forge/prompts/skyvern/check-user-goal.j2:1-63` |
| **Skyvern `check-user-goal-with-termination`** | same | same | `{page_info, thoughts, status ∈ complete\|terminate\|continue, failure_categories[{category, confidence_float, reasoning}]}` | also decides *give up* | — | `check-user-goal-with-termination.j2:11-12` |
| **Skyvern `task_v2_check_completion`** | user goal, task history, live open-tab list, screenshot | after each mini-task | `{require_extraction, information_extracted, required_subgoals[{subgoal, satisfied, evidence}], user_goal_achieved, should_terminate, termination_reason, failure_categories}` | drives the planner loop | — | `task_v2_check_completion.j2:11-20,28-42` |
| **Skyvern `ValidationBlock`** | `complete_criterion`, `terminate_criterion`, `error_code_mapping`, prior block outputs, optionally *no page at all* | as an explicit workflow block | pass/fail + user-defined error code | **blocks the workflow** | — | `client/types/validation_block.py:36-53` |
| **Skyvern evidence router** | **criterion text + workflow data ONLY** — *"never accepts the DOM, the screenshots, the current URL, or action history"* | before a ValidationBlock, to decide what evidence it needs | `{evidence_kind ∈ data_only\|page_state\|mixed, confidence, rationale}` | advisory + **conservative**: only `data_only` above a confidence floor may skip page evidence; a lexical short-circuit blocks page-state keywords from ever reaching the LLM | — | `forge/validation_evidence_router.py:1-18,104-155,215-228,237-363`; `prompts/skyvern/validation-evidence-router.j2:1-21` |
| **Skyvern copilot completion-verifier** | list of completion **criteria** + the **evidence the run produced** (extraction/validation block outputs, observed end-state URL/title) | after a workflow test run | `CriterionVerdict{criterion_id, state, reason_code ∈ evidence_confirms\|no_evidence\|evidence_contradicts\|unknown, evidence_ref, missing_evidence, self_emitted_judgment_not_independent}` | **advisory by construction** — *"The deterministic gate consumes the typed result; this module never decides the gate"*; abstains when there is no evidence | — | `sdk/copilot/completion_verification.py:1-9,50-53,98-116`; `prompts/skyvern/workflow-copilot-completion-verification.j2:1-21` |
| **Skyvern `failure_classifier`** | failure text + exception type/name | on any terminate/exception/max-steps | 17 categories with `confidence_float`, marked `evidence_source: keyword_only` when only a keyword matched | routes repair | — | `forge/failure_classifier.py:21-46,84-90` |
| **Stagehand eval verifier** | `Trajectory` + a **rubric** (`items[{criterion, description, maxPoints}]`) generated from the `TaskSpec` and **cached per task** | rubric before, verify after | `EvaluationResult{outcomeSuccess, processScore, perCriterion[], findings[], evidenceInsufficient[], firstPointOfFailure{stepIndex, errorCode}, taskValidity{isAmbiguous, isInvalid, …}}` | **gates the eval**; `EVAL_SUCCESS_MODE ∈ outcome\|process\|both` (process threshold 0.8) | — | `packages/evals/framework/verifierAdapter.ts:58-122,129-164,206-270,316-331`; `adHocRubric.ts:16-27` |
| **Stagehand verifier gate** | per-arm counts of `criterionCount` / `evidenceInsufficient` / `verifierError` | per bench batch | `ArmVerifiability{gradedRuns, ungradedRuns, unverifiableCriteria, totalCriteria}` | gates the batch on `EVAL_MAX_UNVERIFIABLE_CRITERIA`; runs the verifier failed to grade fall back to self-report and *"must never hide inside a gated batch"* | — | `verifierGate.ts:1-10,29-60,64-80` |
| **workflow-use `StepVerifier`** | the executed step + pre-step page state + live DOM | **after every step** | `VerificationOutcome{result ∈ SUCCESS\|FAILURE\|UNCERTAIN\|SKIPPED, checks_run/passed/failed, confidence, details}` | fails the step; `HYBRID` = deterministic first, AI fallback | — | `workflow/step_verifier.py:16-30,83-178,182-300` |
| **workflow-use per-step-type checks** | — | — | `navigation → check_url_matches, check_page_loaded`; `click → check_page_state_changed, check_click_outcome`; `input → check_input_value, check_no_validation_errors`; `select_change → check_option_selected`; `scroll → check_scroll_position`; `extract → check_data_extracted` | **deterministic, minted from the step type — never asked of a model** | — | `step_verifier.py:202-297` |
| **Magentic-One progress ledger** | task, team, full conversation | **every orchestrator turn** | `LedgerEntry{is_request_satisfied, is_in_loop, is_progress_being_made, next_speaker, instruction_or_question}`, each `{reason, answer}` | **decides the whole loop**: 3 stalls → rewrite facts + plan and re-enter the outer loop | removing the ledgers: **−31% on GAIA** *(carried from [`browser-agent-architectures.md`](browser-agent-architectures.md) §4.1; not re-verified here)* | autogen `.../_magentic_one/_prompts.py:59-100,103-118`; final answer `:139-149`; re-plan `:121-136` |
| **magentic-ui bash verifier** | filesystem state **diff** (pre and/or post) for the paths a destructive command touched | after a destructive command | a rendered evidence block appended to the tool output | pure evidence — *"so the model can self-correct on no-op cases"*; `PRE_AND_POST` for `rm`, `POST_ONLY` for `mv/cp/chmod` | — | magentic-ui `teams/omniagent/_verifier.py:1-31` |
| **WebVoyager auto-eval** | task, **result screenshots**, the agent's textual `ANSWER` | post-hoc | `SUCCESS` / `NOT SUCCESS` + reasoning | benchmark oracle | **85.3% agreement with human judgment** *(number carried from [`browser-agent-architectures.md`](browser-agent-architectures.md) §4.1; the prompt below is verified at `5a78967`)* | `evaluation/auto_eval.py:10-24` |
| **WebArena programmatic evaluators** | last action's `answer`, `page.url`, and DOM read back via JS locators / re-navigation | post-hoc | float score, **multiplied across evaluators** (a conjunction) | **the benchmark's oracle** | precision **83.8%**, recall **55.9%**, F1 **67.1** vs expert annotation | `evaluation_harness/evaluators.py:71-170,173-241,244-333,336-352,356-374`; arXiv:2504.08942 Table 1 |
| **Online-Mind2Web `WebJudge`** | task → **key points**; per-screenshot relevance score → **key screenshots**; then task + key points + key screenshots + action history | post-hoc, 3 LLM stages (2 with WebJudge-7B) | `Thoughts:` + `Status: success\|failure` | benchmark oracle | ~**85%** human agreement (GPT-4o **83.6%**, o4-mini **85.7%**, SR gap **3.8%**); on AgentRewardBench **precision 73.7 / 75.7 / 82.0%** (GPT-4o / 7B / o4-mini) | arXiv:2504.01382 §3, §4, §5; prompts in App. |
| **AgentRewardBench "simplified" judge** | goal + `{s₁,(r₁,a₁),…,sₙ}` with **either** the final a11y tree **or** the final screenshot (decoupled) | post-hoc | success + side-effect + repetition, one completion | benchmark study | best **P 69.8** (GPT-4o, a11y) / 68.8 (Claude 3.7 S.) / 61.5 (GPT-4o Mini) | arXiv:2504.08942 §4.1, Table 1 |
| **AutoEval (Pan et al. 2024)** | screenshots (end-to-end GPT-4V) **or** captions of them + text (modular Captioner+LM) | post-hoc; also as a Reflexion reward | binary success | drives refinement | **74.4–92.9%** agreement with oracle metrics (WebArena ≤82.1%, AitW 92.9%); vs human: Captioner+Mixtral **92.9%**, GPT-4V **90.6%**; **+29%** relative WebArena SR via Reflexion | arXiv:2404.06474 §4.1-4.3 |
| **PAE evaluator** | **final three screenshots + the agent's final answer** only | post-hoc | 0/1 sparse reward | the RL reward | step-based evaluation rejected as *"too noisy"*, code-based as impractical without hidden state | arXiv:2412.13194 §4.3 |
| **WebRL ORM** | trajectory | post-hoc | "YES"/"NO" binary reward | curriculum + RL signal | **~80%** accuracy vs ~70% for GPT-4-Turbo / Captioner+GPT-4-Turbo / GPT-4V baselines | arXiv:2411.02337 §3.8 |
| **NNetNav labeler + ORM** | trajectory prefix at fixed timesteps | **during** exploration (prunes) | inferred sub-task instruction + reward; prune if 0 | prunes the episode | judge **P 52.5 / R 82.4** on AgentRewardBench | arXiv:2410.02907 §3.2; arXiv:2504.08942 Table 1 |
| **TheAgentCompany** | environment state (workspace, intranet, simulated colleagues) + agent trajectory | post-hoc, per **checkpoint** | partial score per checkpoint + `S_full` binary (+50% completion bonus) | benchmark oracle | *"In most cases, these evaluators are deterministic and written as simple Python functions"*; LLM only for unstructured deliverables | arXiv:2412.14161 §3, §4.1 |
| **WebCanvas / Mind2Web-Live** | **key nodes** = indispensable milestones; matched on URL / Element Path / Element Value × Exact / Include / Semantic Match | post-hoc, per key node | step score + task score | benchmark oracle | **only 46 of 104** tasks have the final key node as a *sufficient* condition — final-state-only evaluation is inadequate | arXiv:2406.12373 §2.2-2.3, §6.2 |
| **τ-bench** | **the database state** at episode end vs the annotated goal state | post-hoc | reward ∈ {0,1}; `pass^k` over k i.i.d. trials | the oracle; fully deterministic | gpt-4o >60% `pass^1` but **`pass^8` < 25%** in retail | arXiv:2406.12045 §2, §3.3, §5 |
| **Agent-as-a-Judge** | project artifacts + *interaction with the environment after the agent finishes* | post-hoc | per-requirement judgments | study | **90%** alignment with human consensus vs **70%** for LLM-as-a-Judge; human–human disagreement **10–30%** | arXiv:2410.10934 §1, §4 |
| **Agent-E planner** | the navigator's replies to explicit confirmation questions | interleaved, *as plan steps* | prose confirmations | drives `##TERMINATE##` | *"Very Important: Add verification as part of the plan, after each step and specifically before terminating… Do not assume the helper has performed the task correctly."* | `ae/core/prompts.py:26,60,172-173` |
| **Notte** | — | at exit | `AgentResponse{success, answer}` | self-report only | — | `notte-agent/.../common/types.py:22-23` |
| **SkillWeaver** | action log + final screenshot | after each practice attempt; plus API unit tests | `{step_by_step_reasoning, success}` (structured output); API "verified" if it runs without exception | admits the skill to the library | **cautionary**: *"malfunctioning APIs could be marked as verified simply because they silenced all exceptions"* | arXiv:2504.07079 §A.5, §D.2.1 |
| **ASI** | executes the induced program on a rewritten trajectory prefix | at induction | pass/fail by execution | admits the skill | trailing primitive actions are **truncated** *"to avoid spurious successes"*; +23.5% / +11.3% SR | arXiv:2504.06821 §2.3 |
| **AWM (online)** | trajectory | post-hoc | binary, via Pan et al. (2024)'s evaluator | filters which trajectories become workflows | +51.1% relative SR on WebArena | arXiv:2409.07429 §2.3 |
| **NetGent `sweep`** | dialogs since a mark ∪ `texts_seen` ∪ live frame text vs `DEFAULT_MARKERS` | after each form attempt | `bool` (`submitted`), recorded **beside** `agent_success` | **authoritative** — retries until verified | — | [`sweep.py:66-89,112-137`](../../src/netgent/evals/sweep.py) |
| **NetGent `validate`** | a fresh zero-LLM replay through the production `Executor` | after `generate` | `ValidationReport{replays[{success, edges_ok, failed_edge, error}]}` | **authoritative** | 100% precise about *"every edge fired and every guard held"*; **says nothing about the goal** | [`validate.py:13-56`](../../src/netgent/agent/validator/validate.py) |

---

## 3. What the judges actually see — the prompts, verbatim

Four prompts are worth reading in full because they encode four different theories of evidence.

### 3.1 browser-use — maximum context, explicit distrust, zero authority

`judge.py:44-52` takes `(task, final_result, agent_steps, screenshot_paths, max_images=10,
ground_truth=None, use_vision=True)`; screenshots are the **last** ≤10 (`judge.py:76`). The system
prompt's operative lines (`judge.py:169-176`):

> - **evaluate for action** - For each key step of the trace, double check whether the action that the agent tried to performed actually happened. If the required action did not actually occur, the verdict should be false.
> - **screenshot is not entire content** - The agent has the entire DOM content, but the screenshot is only part of the content. If the agent extracts information from the page, but you do not see it in the screenshot, you can assume this information is there.
> - **IMPORTANT**: be very picky about the user's request …
> - **IMPORTANT**: be initially doubtful of the agent's self reported success, be sure to verify that its methods are valid and fulfill the user's desires to a tee.

and among the automatic-false conditions (`judge.py:145`): *"The agent calls done action before
completing all key points of the task."* When `ground_truth` is supplied it *"takes ABSOLUTE
precedence over all other evaluation criteria"* (`judge.py:96-104`) — i.e. browser-use already knows
that a judge with a **stated criterion** is a different instrument from a judge without one.

The authority rule is a docstring (`service.py:1622-1628`):

> The judge verdict is attached to the action result but does NOT override `last_result.success` — that stays as the agent's self-report. Telemetry sends both values so the eval platform can compare agent vs judge.

Note the shape: **log both, decide neither.** That is the correct first move for NetGent too (§6.4).

### 3.2 Skyvern's copilot verifier — the best-stated theory of evidence in the survey

`workflow-copilot-completion-verification.j2:6-13`, verbatim:

> - satisfied=true ONLY when the produced evidence directly demonstrates the criterion's end state (an extraction/validation output value, or the observed end-state URL/title). When in doubt, satisfied=false.
> - **Judge OUTCOMES, not steps. The fact that a block ran, a label was executed, or a navigation happened is NEVER sufficient on its own — a run can "complete" without achieving the outcome.**
> - If the evidence does not contain anything that shows the outcome, set satisfied=false and reason_code=no_evidence. Do not infer the outcome from the presence of a step or from the criterion text itself.
> - If the evidence shows the outcome did NOT happen …, set satisfied=false and reason_code=evidence_contradicts.
> - If you cannot tell from the evidence, set satisfied=false and reason_code=unknown.
> - For an implicit constraint (e.g. "added exactly once"), check the end-state value (e.g. a cart quantity), not whether an add step ran.
> - evidence_ref: when satisfied=true, use an exact evidence label shown above … Never return a literal URL.

The bolded line is a one-sentence statement of NetGent's `validate` gap. Three further properties are
worth stealing wholesale:

1. **A four-valued reason code**, not a boolean: `evidence_confirms | no_evidence |
   evidence_contradicts | unknown` (`completion_verification.py:50`). "I have no evidence" and "the
   evidence refutes it" route differently.
2. **`evidence_ref` is mandatory on a positive verdict** — the judge must *point at* the record that
   satisfied the criterion. A judge that cannot cite cannot confirm.
3. **`self_emitted_judgment_not_independent`** (`completion_verification.py:112,207-211`): a flag for
   "this evidence is the agent's own claim". A criterion satisfied only by self-emitted judgment is
   rejected unless an independent corroborator exists.

### 3.3 Skyvern's evidence router — deciding *what kind* of evidence a criterion needs

`validation_evidence_router.py:1-18` is a small classifier that decides whether a criterion is
`data_only`, `page_state`, or `mixed` — and it is deliberately **blind**:

> The router never accepts the DOM, the screenshots, the current URL, or action history as input — page-derived signals would bias classification.
> Only `DATA_ONLY` with confidence at or above the configured floor bypasses page evidence. Every other result (`MIXED`, `PAGE_STATE`, low confidence, parse error, handler exception, lexical short-circuit) keeps the existing page-aware path.
> A lexical short-circuit blocks page-state keywords from ever reaching the router …

The lexical short-circuit (`:104-155,215-228`) is a frozen phrase set — `"page shows"`, `"url contains"`,
`"visible"`, `"error banner"`, `"file downloaded"`, `"button disabled"`, `"modal appears"` … — with
exclusion-clause stripping so `"Do NOT use the page"` does not trigger it. **Every uncertainty maps
to more evidence, never less.** That is the correct default for a verifier and directly informs §6.1:
*derive checks deterministically where a rule can, ask the model only for the residue.*

### 3.4 WebJudge — key points first

WebJudge (arXiv:2504.01382 §3) is three stages. Stage 1, in full:

> You are an expert tasked with analyzing a given task to identify the key points explicitly stated in the task description.
> **Objective**: Carefully analyze the task description and extract the critical elements explicitly mentioned in the task for achieving its goal.
> 1. Read the task description carefully.
> 2. Identify and extract **key points** directly stated in the task description.
>  - A **key point** is a critical element, condition, or step explicitly mentioned in the task description.
>  - **Do not infer or add any unstated elements.**
>  - Words such as "best," "highest," "cheapest," "latest," … must go through the sort function (e.g., the key point should be "Filter by highest").
> **Respond with**: - **Key Points**: A numbered list of the explicit key points for completing this task, one per line, without explanations or additional details.

Stage 3 then judges `(task, key points, action history, key screenshots + why each was kept)` with
criteria that are *mostly assertions about page state* — *"The filtered results must be displayed
correctly. If filters were not properly applied (i.e., missing selection, missing confirmation, or
no visible effect in results), the task is not considered successful"* and *"Some tasks require a
submission action or a display of results to be considered successful."*

Two things follow. First, "do not infer or add any unstated elements" is exactly the guard our
`plan_checks` needs — an invented expectation is a false failure, which is worse than a missed one
because it re-runs exploration for nothing. Second, extracting key points is what moves precision
from 61–70% (plain judges, arXiv:2504.08942 Table 1) to 73.7–82.0% (WebJudge on the *same*
1302-trajectory benchmark).

### 3.5 WebVoyager — the precedence rule NetGent already follows

`auto_eval.py:10-24`, the last two rules:

> -- NOTE that the screenshot is authentic, but the response provided by LLM is generated at the end of web browsing, and there may be discrepancies between the text and the screenshots.
> -- Note the difference: 1) **Result response may contradict the screenshot, then the content of the screenshot prevails**, 2) The content in the Result response is not mentioned on the screenshot, choose to believe the content.

This is `sweep.py:66-89`'s docstring — *"All three are the walker's own reads of the page, never the
agent's self-report"* — restated as a judge instruction. NetGent got there first; the useful addition
is clause 2: silence in the page evidence is **not** refutation.

### 3.6 Magentic-One's ledger — the one verifier with real authority, and why

`_prompts.py:59-100` asks five questions per turn, each `{reason, answer}`:

> - Is the request fully satisfied? (True if complete, or False if the original request has yet to be SUCCESSFULLY and FULLY addressed)
> - Are we in a loop where we are repeating the same requests and / or getting the same responses as before? …
> - Are we making forward progress? …
> - Who should speak next? …
> - What instruction or question would you give this team member? …

`is_request_satisfied=False` does not fail anything — it **re-plans**: stalls increment, and at the
cap the orchestrator rewrites the fact sheet and asks *"briefly explain what went wrong on this last
run (the root cause of the failure), and then come up with a new plan … that especially avoids
repeating the same mistakes"* (`:121-136`). The −31% ablation is for *this* use — the judge as a
**router**, exactly as [`browser-agent-architectures.md`](browser-agent-architectures.md) §4.1
concluded. Nobody's measured ablation supports a judge as an *acceptance gate*.

---

## 4. Deterministic vs LLM-judgeable — and how wrong the LLM is

### 4.1 The partition

**Deterministic and page-derived** (computable by our browser layer, no model, and expressible as a
`Trigger` today or one branch away):

| Evidence | How we get it | Trigger |
|---|---|---|
| final / intermediate URL | `page.url` | `url_matches` |
| page title | `page.title()` | `title_contains` |
| a marker string was **ever visible** | `traj.texts_seen` ([`graph.py:131-136`](../../src/netgent/agent/explorer/graph.py)) — survives banners hidden after 3 s | `text_visible` *(discovery branch)* |
| a marker string is visible **now** | `session.snapshot().texts`, frame-scoped | `text_visible` |
| an element is visible / hidden, in-frame | `condition_report` ([`session.py:127-128`](../../src/netgent/browser/session.py)) | `selector_visible` / `selector_hidden` / `element_visible` |
| a JS dialog with a given message fired **since the last action** | `dialogs_since_last_action()` ([`browser_agent.py:86-89`](../../src/netgent/agent/explorer/browser_agent.py)) | `dialog_matches` |
| every dialog this session | `dialogs_seen()` ([`session.py:90-94`](../../src/netgent/browser/session.py)) | — (verification-time) |
| a field's value equals X | `input_value` probe (`ParamSource.kind = "input_value"`, [`control.py:79-93`](../../src/netgent/schema/control.py)) | — (a `value_equals` trigger would be new) |
| a `<video>` is actually advancing | two `currentTime` polls | `video_playing` *(discovery branch)* |
| a dwell of ≥ N s happened | `WaitAction` duration in the trajectory | — (record, not trigger) |
| which conjunct of which state failed on replay | `EdgeRecord.conditions` ([`records.py:27-40`](../../src/netgent/schema/records.py)) | — |
| network: a request to X returned 2xx | capture hooks in `browser/factory.py` | — (the product is traffic; this is free evidence we do not yet use) |

**Only an LLM can judge**: whether the *meaning* of the page satisfies the task —
*"book the cheapest flight"* (is this the cheapest? was a sort applied?), *"summarise the reviews"*
(is this a summary?), *"the top-rated adventure movie"* (top-rated by what?), and whether a
*rephrasing* of a marker still means success (`"Your message was sent"` vs `"Thanks!"`). WebJudge's
criteria 1–4 are all attempts to force this class back into checkable form ("the filter must be
*applied*, not merely *typed*"), which is a good sign that the class is smaller than it looks.

**The residue that is neither**: side effects (did the agent also buy something?), repetition cycles,
and destructive actions. AgentRewardBench annotates all three separately (§3.1) precisely because
success alone hides them; judges are *terrible* at side effects — precision **6.5–8.8%** across the
GPT-4o-mini ablation (Table 2). Do not ask a judge about side effects; use the action log.

### 4.2 The numbers, and their direction

| Claim | Number | Source |
|---|---|---|
| Best LLM judge precision, 1302 trajectories / 5 benchmarks / 12 judges | **GPT-4o 69.8**, Claude 3.7 Sonnet **68.8**, GPT-4o Mini **61.5**, AER-C **67.7**, AER-V **67.6**, NNetNav **52.5** | arXiv:2504.08942 Table 1 |
| The headline | *"no judge achieves above 70% precision, which means that 30% of trajectories are erroneously marked as successful"* | ibid. §4.3 |
| Recall of the same judges | **71.5–86.1%** — judges say *yes* too often, not too rarely | ibid. Table 1 |
| Official rule-based evaluators | precision **83.8**, recall **55.9**, F1 **67.1** | ibid. Table 1 |
| Direction of the two biases | LLM judges **overestimate** success for nearly every agent; rule-based **consistently underestimates** it (GPT-4o expert-vs-rule gap: **16.7 pts** on WebArena, **18.5 pts** on VisualWebArena) | ibid. §5 |
| Input representation ablation (GPT-4o Mini) | screenshot only **P 64.5 / R 78.3**; a11y tree only **P 61.5 / R 86.1**; **both P 62.1 / R 81.7** — *"more information distracts rather than assists"*; neither **P 60.7 / R 73.9** | ibid. Table 2 |
| Inter-annotator agreement (human ceiling) on success | **89.3%** | ibid. §3.3 |
| WebJudge on the same 1302 trajectories | precision **73.7%** (GPT-4o), **75.7%** (WebJudge-7B), **82.0%** (o4-mini) | arXiv:2504.01382 §5 |
| WebJudge vs human on Online-Mind2Web (300 tasks / 136 sites) | avg agreement **83.6%** (GPT-4o), **85.7%** (o4-mini), success-rate gap **3.8%**; rule-based gap **9.8%**, prior LLM-judge gap **8.1%** | ibid. §4, §5 |
| AutoEval agreement with oracle metrics | **74.4–92.9%** (WebArena ≤ **82.1%**, AitW **92.9%**) | arXiv:2404.06474 §4.1 |
| AutoEval error taxonomy on WebArena | perception loss 10% (modular) / 5% (GPT-4V); **reasoning errors 50%** (GPT-4V/GPT-4), 70% (Mixtral); **task-spec & success-criteria ambiguity 30%** (GPT-4V/GPT-4) | ibid. §4.3 |
| …and | *"the model provides the correct final evaluation, but incorrect reasoning, in about 10% of correct evaluations"* | ibid. §4.3 |
| Agent-as-a-Judge (env-interacting) vs LLM-as-a-Judge | **90%** vs **70%** alignment with human consensus; human–human disagreement **10–30%** | arXiv:2410.10934 §1, §4 |
| WebRL's trained ORM | **~80%** vs ~70% for prompted GPT-4-Turbo / Captioner+GPT-4-Turbo / GPT-4V | arXiv:2411.02337 §3.8 |
| Consistency, not accuracy, is the real gap | gpt-4o >60% `pass^1` in τ-retail but **`pass^8` < 25%** | arXiv:2406.12045 §5 |
| Final-state-only oracles are insufficient | **46 of 104** Mind2Web-Live tasks have the final key node as a sufficient condition | arXiv:2406.12373 §6.2 |

### 4.3 *How* judges fail — all four modes are sycophancy

AgentRewardBench §6 names four categories; every one is the judge deferring to the agent:

1. **Grounding mismatch** — the agent's reasoning describes a page state that is not real; a judge
   without the screenshot accepts it. ("*Based on the layout of the page, the second row, second
   column item is the [energy Drink]*" — it wasn't.)
2. **Misleading agent reasoning** — after failing to apply a filter, the agent *states* it succeeded;
   the judge writes *"The agent successfully […] applied the filter…"*
3. **Missed instruction details** — the task said *buy*; the agent *found*; the judge wrote
   *"successfully identified and purchased"*.
4. **Misunderstanding action intents** — the agent completes every step then reports the task
   infeasible; the judge ignores the misused action.

The paper's conclusion: *"they will easily agree with the agent's reasoning even when it is wrong."*

> **Design consequence for NetGent.** Our judge must be shown `AgentStep.kind`, `target`, `url`,
> `error`, `dialogs`, `texts_seen`, and screenshots — and **must not** be shown
> `AgentStep.reasoning`, `evaluation`, `memory`, or `next_goal`
> ([`browser_agent.py:100-104`](../../src/netgent/agent/explorer/browser_agent.py)). Those fields
> exist as compile-time provenance and the compiler already ignores them; the judge should too.
> browser-use's judge does the opposite (`agent_steps()` includes the reasoning chain, `judge.py:69`)
> and mitigates it with prose (*"be initially doubtful of the agent's self reported success"*).
> Withholding beats instructing. Skyvern encodes the same idea as a *field*:
> `self_emitted_judgment_not_independent` (`completion_verification.py:112`).

A second consequence from Table 2: **give the judge one representation, not two.** Screenshot-only
had the best precision; adding the a11y tree *lowered* it. For NetGent, "screenshots + the
deterministic evidence bundle" — not "screenshots + the full observation text".

---

## 5. Spec → checks: turning the task into conditions *before* running

Every system that beats the ~70% ceiling does the same thing: it converts the task into a small,
explicit, enumerable set of expectations **before** judging, and often before running.

| System | When the checks are made | Form | Who writes them | Notes |
|---|---|---|---|---|
| WebArena | task authoring time | `eval_types: [string_match \| url_match \| program_html]` with `exact_match` / `must_include` / `fuzzy_match`, `reference_url` + `url_note: "GOLD in PRED"`, and `program_html[{url, locator (JS), required_contents}]` | human | scores **multiply** — a strict conjunction (`evaluators.py:336-352`) — the same semantics as our `State.conditions` |
| Online-Mind2Web | at judge time, from the task text | numbered **key points**, *"Do not infer or add any unstated elements"* | LLM, one call | +4–20 pts precision over plain judges |
| TheAgentCompany | task authoring time | **checkpoints** in English → a Python evaluator each; categories: *Action Completion*, *Data Accuracy*, *Collaboration*; each with a point value | human | *"In most cases, these evaluators are deterministic and written as simple Python functions"*; LLM only for unstructured deliverables |
| WebCanvas | annotation time, via a recording plugin | **key nodes** = indispensable milestones; evaluation function = ⟨target ∈ URL / Element Path / Element Value⟩ × ⟨match ∈ Exact / Include / Semantic⟩ | human | *"we preferred to use URL state as identifiers for key nodes rather than element interaction … Only element class methods are considered for key nodes that cannot be represented by URLs"* — **exactly our trigger preference order** |
| Stagehand | before the run, **cached per task** | `Rubric{items[{criterion, description, maxPoints}]}` from `generateRubric(taskSpec)`, or `precomputedRubric`, or `adHocRubric(...criteria)` | LLM (cached) or human | caching makes the criteria *stable across runs* — a rubric that varies per run cannot be compared across arms |
| Skyvern | at plan time | `complete_criterion`: *"a short, checkable statement of what is true on the page once this mini goal is done (e.g. 'the confirmation number is displayed', 'the results table for X is visible'). The inner agent stops as soon as this holds instead of running to its step limit."* (`task_v2.j2:92`) | LLM planner | also `terminate_criterion`, `data_extraction_goal` + `data_schema`, `error_code_mapping` (`validation_block.py:36-53`) |
| Skyvern (safety) | — | criteria proposed by a *planner reading a page* are marked `complete_criterion_is_untrusted` and fenced in `BEGIN_UNTRUSTED_WEB_PAGE_DATA` (`check-user-goal.j2:1,36-43`) | — | a page-derived criterion can never override the user goal |
| browser-use CI | task authoring time | `judge_context: list[str]` of success criteria, defaulting to `['The agent must solve the task']` | human | `evaluate_tasks.py:56,157` |
| τ-bench | annotation time | ground-truth **database write actions** | human | the strongest oracle in the survey and the least transferable to the open web |
| ReUseIt | after failures | *"Condition Check: Before or after performing {Action}, ensure {Condition} is satisfied"*, attached to a step as a **unit** | LLM, from failure text | see [`reuseit.md`](reuseit.md) §3.3 |
| **NetGent today** | — | `DEFAULT_MARKERS = ("dumbledore", "success", "submitted", "thank you", "completed")` | hard-coded | [`sweep.py:19`](../../src/netgent/evals/sweep.py) — task-independent, `evals/`-only |

Three transferable rules:

1. **Prefer the URL, fall back to the element** (WebCanvas). Our compiler already does this
   ([`compiler.py:89-99`](../../src/netgent/agent/generator/compiler.py)); expectations should too.
2. **Cache the checks per task** (Stagehand). A rubric regenerated per run makes `--runs N`
   incomparable across runs — and NetGent's whole product is comparability across replays.
3. **Fence anything page-derived as untrusted** (Skyvern). If we ever let the explorer *propose* an
   expectation from what it saw, it must not be able to weaken one derived from the user's task.

**How partial completion is scored.** TheAgentCompany awards per-checkpoint points and gives a
binary `S_full` *plus* a 50% bonus for full completion; WebCanvas reports a "completion rate" over
key nodes alongside the task score; Stagehand reports `outcomeSuccess` (bool) and `processScore`
(float) with `EVAL_SUCCESS_MODE ∈ outcome | process | both` and a 0.8 process threshold
(`verifierAdapter.ts:316-331`). NetGent should report **both and gate on `outcome`**: an artifact is
either right or not, but a partial score is what makes A/B arms comparable and what tells `triage`
*which* expectation to re-explore for.

---

## 6. A verifier for NetGent

Constraints, restated so nothing below violates them: LLM only at compile time; the artifact is a
zero-LLM NFA; states carry conditions (a conjunction); one atomic action per transition;
`generate` and `validate` stay pure code
([`CLAUDE.md`](../../../CLAUDE.md) hard rules 1–3, `OVERVIEW.md` §7.2 decisions 6–7).

Proposed package: **`v2/src/netgent/agent/verifier/`** — a fourth agent alongside
`explorer/ generator/ validator/`, holding `spec.py` (types + deterministic derivation),
`check.py` (zero-LLM evaluation), `judge.py` (the advisory LLM seam), `triage.py` (zero-LLM
classification). `schema/` gains nothing except one trigger (§6.3).

### 6.1 (a) Spec → checks, before exploring

```python
# v2/src/netgent/agent/verifier/spec.py
from typing import Literal
from pydantic import BaseModel, Field
from netgent.schema.triggers import Trigger

Scope = Literal["terminal", "milestone"]

class Expectation(BaseModel):
    """One key point of the task, stated so a machine can look for it.

    `check` is our own Trigger vocabulary, so an expectation is simultaneously (a) what
    the verifier looks for after exploration and (b) a condition of the compiled artifact's
    terminal state. `check=None` means "no deterministic form exists" — the judge may speak
    to it, and it is COUNTED as unverifiable (Stagehand `evidenceInsufficient`), never
    silently assumed satisfied.
    """
    id: str                       # "e0", "e1" — stable; verdicts and episodes cite it
    text: str                     # the key point, in the user's own words
    scope: Scope = "terminal"
    check: Trigger | None = None
    param: str | None = None      # the ${name} this expectation is about, if any
    required: bool = True
    origin: Literal["param", "quoted", "task_verb", "model"] = "model"  # provenance

class TaskSpec(BaseModel):
    task: str
    params: dict[str, str] = Field(default_factory=dict)
    expectations: list[Expectation] = Field(default_factory=list)

    def terminal_checks(self) -> list[Trigger]:
        return [e.check for e in self.expectations
                if e.scope == "terminal" and e.required and e.check is not None]
```

**Derivation is deterministic first, model second** — Skyvern's router discipline
(`validation_evidence_router.py:1-18`) applied to *authoring* rather than routing:

```python
# v2/src/netgent/agent/verifier/spec.py (continued)
def derive_deterministic(task: str, params: dict[str, str]) -> list[Expectation]:
    """Expectations no model is needed for. These are the high-confidence core."""
    out: list[Expectation] = []
    # 1. Every declared -p sample must show up in what the page said or where we ended up.
    #    This ALONE rejects the YouTube case: the explorer typed "YouTube", not ${query}.
    for name, value in params.items():
        out.append(Expectation(
            id=f"e{len(out)}", text=f"the page reflects {name} = {value!r}",
            check={"type": "text_visible", "text": value},
            param=name, origin="param",
        ))
    # 2. Quoted strings in the task are the user's own literal success markers.
    for quoted in re.findall(r"[\"'“](.{2,60}?)[\"'”]", task):
        out.append(Expectation(id=f"e{len(out)}", text=f'the page shows "{quoted}"',
                               check={"type": "text_visible", "text": quoted}, origin="quoted"))
    # 3. A bare URL in the task is a url_matches expectation.
    for url in re.findall(r"https?://\S+", task):
        out.append(Expectation(id=f"e{len(out)}", text=f"we end up on {url}",
                               check={"type": "url_matches", "pattern": re.escape(_base(url))},
                               origin="task_verb"))
    return out
```

Then **one** LLM call (`plan_checks`) for the residue, prompted with WebJudge's constraint verbatim
(*"A key point is a critical element, condition, or step explicitly mentioned in the task
description. Do not infer or add any unstated elements."*) plus Skyvern's *"a short, checkable
statement of what is true on the page once this is done"*, and told the closed `Trigger` vocabulary.
Code then **validates every proposed check**:

- it must parse as a `Trigger` (pydantic does this for free);
- a `text_visible` whose `text` appears neither in the task nor in a param value is **downgraded to
  `check=None`** — the model may name a key point it cannot ground, but it may not invent a marker;
- a `selector_visible` is rejected outright: selectors are minted from actions
  ([`compiler.py:32-63`](../../src/netgent/agent/generator/compiler.py)), never from a model
  ([`browser-agent-architectures.md`](browser-agent-architectures.md) §4.3 item 3, §5.1);
- the result is **cached** keyed on `(task, sorted(params))` under the trajectory dir, so `--runs N`
  and A/B arms compare against identical expectations (Stagehand `RubricCache`,
  `verifierAdapter.ts:78-92`).

Degradation is total: no API key, `--no-verify`, or a failed call ⇒ `derive_deterministic()` only.
The pipeline never *gains* an LLM dependency it did not have.

### 6.2 (b) Trajectory verification at `done`

```python
# v2/src/netgent/agent/verifier/check.py
class ExpectationStatus(BaseModel):
    id: str
    state: Literal["met", "unmet", "no_evidence"]
    source: Literal["page", "judge"]          # deliberately NO "agent"
    evidence: str | None = None               # the exact text / url / dialog that satisfied it
    contradicted_at_step: int | None = None   # AgentStep.n whose observation refutes it

class Verdict(BaseModel):
    achieved: bool                            # every REQUIRED expectation met by PAGE evidence
    statuses: list[ExpectationStatus]
    unverifiable: list[str]                   # expectation ids with no deterministic check
    agent_claim: bool                         # traj.success — RECORDED, never consulted
    judge: JudgeNote | None = None            # advisory only

async def verify_trajectory(
    session: BrowserSession, traj: AgentTrajectory, spec: TaskSpec,
) -> Verdict:
    """Deterministic pass. Zero LLM. The generalisation of sweep._form_succeeded."""
    statuses = []
    for e in spec.expectations:
        if e.check is None:
            statuses.append(ExpectationStatus(id=e.id, state="no_evidence", source="page"))
            continue
        hit = (
            _in_texts_seen(traj.texts_seen, e.check)      # transient banners: sweep.py:83-84
            or _in_dialogs(session.dialogs_seen(), e.check)  # sweep.py:80-82
            or await _holds_now(session, e.check)          # session.condition_report, sweep.py:85-89
        )
        statuses.append(ExpectationStatus(
            id=e.id, state="met" if hit else "unmet", source="page", evidence=hit or None,
            contradicted_at_step=None if hit else _last_step_before_end(traj),
        ))
    required = [s for s, e in zip(statuses, spec.expectations) if e.required]
    return Verdict(
        achieved=bool(required) and all(s.state == "met" for s in required),
        statuses=statuses,
        unverifiable=[e.id for e in spec.expectations if e.check is None],
        agent_claim=traj.success,
    )
```

Note the asymmetries, each borrowed and each load-bearing:

- **`achieved` requires at least one required expectation.** An empty spec must not vacuously pass —
  SkillWeaver's failure mode in one line (arXiv:2504.07079 §D.2.1).
- **`agent_claim` is stored, not read.** browser-use's *"telemetry sends both values so the eval
  platform can compare agent vs judge"* (`service.py:1622-1628`), and `sweep.py:130-131`'s existing
  `submitted` / `agent_success` pair, which is already the corpus we need.
- **`no_evidence` ≠ `unmet`.** Four-valued reasoning collapsed to three, following
  `completion_verification.py:50`; it is what makes `triage` able to distinguish "the site changed"
  from "we cannot check this at all".
- The three page sources are `sweep.py:80-89` verbatim, generalised from `DEFAULT_MARKERS` to
  `spec.expectations` and from a frame filter to a `Trigger`.

**Then the judge — as evidence.** `verifier/judge.py`, one call, `NETGENT_SECONDARY_MODEL`, default
**off** (`--judge/--no-judge`):

```python
class JudgeVerdict(BaseModel):
    id: str
    reason_code: Literal["evidence_confirms", "no_evidence", "evidence_contradicts", "unknown"]
    evidence_ref: str | None = None      # REQUIRED when reason_code == evidence_confirms
    contradicted_at_step: int | None = None

class JudgeNote(BaseModel):
    verdicts: list[JudgeVerdict]
    impossible_task: bool = False        # browser-use JudgementResult; routes to END
    reached_captcha: bool = False
    reasoning: str = ""
```

Inputs: `spec.expectations`, and an **evidence bundle** — per step `(n, kind, target, url, error,
dialogs)`, `texts_seen`, and the last ≤10 screenshots. **Not** `reasoning`/`evaluation`/`memory`
(§4.3), and **not** the observation text alongside the screenshots (Table 2: two representations
scored worse than one).

Combination rule — the judge may **demote, never promote**:

| deterministic | judge | final |
|---|---|---|
| `met` | anything | **`met`** (page evidence wins — WebVoyager's precedence rule) |
| `unmet` | anything | **`unmet`** |
| `no_evidence` | `evidence_confirms` **with** an `evidence_ref` | `met`, `source="judge"`, id stays in `unverifiable` |
| `no_evidence` | `evidence_contradicts` | `unmet`, `source="judge"` |
| `no_evidence` | `no_evidence` / `unknown` / confirm **without** a ref | `no_evidence` (abstain) |

`achieved` is computed from `source="page"` statuses alone until the agreement measurement in §6.5
says otherwise. This is Skyvern's line — *"The deterministic gate consumes the typed result; this
module never decides the gate"* (`completion_verification.py:1-9`) — and it is the only stance the
~70%-precision number supports.

### 6.3 (c) Workflow verification — closing the replay gap

**What `validate` proves today.** A fresh browser, params resolved, every transition dispatched
through the production `Executor`, every target state's conjunction checked with the recorded
`ConditionCheck`s, zero LLM ([`validate.py:29-56`](../../src/netgent/agent/validator/validate.py)).
That is a genuinely strong property — stronger than any judge — and it is the thesis.

**What it does not prove.** With `accept_states` empty, `Executor.run()` sets `success = True` for
"the program ran without a failed edge" ([`engine.py:47,54-57`](../../src/netgent/executor/engine.py)).
So a workflow that types the literal `"YouTube"` into the search box because the compiler never bound
`${query}` (`browser-agent-prompting.md:120`: *"YouTube run typed 'YouTube', 0 `${query}` in the
artifact"*) replays perfectly green, forever, at every parameter value. Three independent systems
name this exact hazard:

- Skyvern's verifier prompt: *"a run can 'complete' without achieving the outcome."*
- SkillWeaver: *"our criteria for a function to be 'verified' was to have it be called without
  producing an exception … malfunctioning APIs could be marked as verified simply because they
  silenced all exceptions … This represents a measure for evaluation having unintended
  consequences."* (arXiv:2504.07079 §D.2.1)
- ASI: trailing primitive actions are truncated before verification, because otherwise *"executing it
  will always return the correct message to the user, regardless of whether the previous skill calls
  are valid"* (arXiv:2504.06821 §2.3).

**The fix, in the formalism, using fields that already exist.** `compile_trajectory` gains a
`spec: TaskSpec | None` argument and, when given one, appends the terminal expectations' triggers to
the last state and names it as the accept state:

```python
# v2/src/netgent/agent/generator/compiler.py — inside compile_trajectory, after the loop
accept: list[str] = []
if spec is not None and spec.terminal_checks():
    terminal = states[-1]
    # The state after the last action is the goal state; its conditions become the
    # conjunction of "the URL/dialog the trajectory landed on" AND "the task's key points".
    # Executor._reached_accept_state() (engine.py:54-62) already evaluates exactly this.
    states[-1] = terminal.model_copy(update={
        "conditions": [*terminal.conditions, *spec.terminal_checks()]
    })
    accept = [terminal.id]

wf = Workflow(..., accept_states=accept, ...)
```

Consequences, all of which fall out for free:

- **`${param}` binding is now proved by replay.** `_bind_params` rewrites `${name}` into state
  conditions as well as actions ([`compiler.py:201-206`](../../src/netgent/agent/generator/compiler.py)),
  and `resolve_params` substitutes them before the replay
  ([`workflow.py:152-181`](../../src/netgent/schema/workflow.py)). So the accept condition
  `text_visible: "${query}"` resolves to the *replay's* query value. The YouTube workflow fails
  validation honestly, at the right place, with the right message.
- **`--runs N` becomes meaningful.** Replaying the same workflow at several param sets and requiring
  the accept state each time is `pass^k` over the artifact (arXiv:2406.12045 §3.3), which is the
  metric a reproducible-traffic product actually needs — `pass^1` hides exactly the flakiness NetGent
  exists to eliminate.
- **`ReplayResult` gains the detail `triage` needs**: `accept_met: list[ConditionCheck]` (the same
  type `EdgeRecord` already uses, [`records.py:20-25`](../../src/netgent/schema/records.py)), so a
  failure names *which conjunct* of the goal did not hold.
- **The ASI truncation warning applies to us**: because `accept_states` are evaluated *after* the
  whole control program ([`engine.py:47`](../../src/netgent/executor/engine.py)), a trailing
  `goto`/`go_back` recorded by the explorer can navigate *away* from the goal state and fail a
  correct workflow, or *back* to a page that shows the marker for the wrong reason. The compiler
  should drop trailing navigations after the last state-changing action before minting the accept
  state, and say so in `warnings`.
- **Milestones for partial credit.** `Milestone{id, state, segment_edges}` already exists
  ([`control.py:112-118`](../../src/netgent/schema/control.py)) and is documented as
  reporting/heal-scope only. `scope="milestone"` expectations map onto it, giving WebCanvas-style
  key-node scoring and TheAgentCompany-style partial credit with no new schema.

**A caveat worth stating.** Adding goal conditions to the terminal state makes validation *stricter*,
and stricter oracles under-report: rule-based evaluators recall only **55.9%** (arXiv:2504.08942
Table 1). A brittle marker will fail correct workflows. Two mitigations: only `required=True`
expectations become accept conditions; and `triage` classifies "accept state unmet, every edge ok,
marker never seen in any run" as **over-strict guard** and drops the conjunct before failing the
artifact ([`browser-agent-architectures.md`](browser-agent-architectures.md) §5.5).

### 6.4 (d) The feedback contract

```python
# v2/src/netgent/agent/verifier/triage.py
FailureKind = Literal[
    "expectation_unmet",    # the goal was not achieved (verify or validate said so)
    "param_unbound",        # a ${name} never reached the artifact
    "flow_drift",           # the page moved on us: guard timed out, action fine
    "ui_drift",             # locator resolved to 0 elements
    "ambiguity",            # locator resolved to >1 (decision #8: ambiguity is a miss)
    "over_strict_guard",    # some conjuncts held; the unmet ones look incidental
    "flaky",                # passed on retry
    "unverifiable",         # no deterministic check exists for a required expectation
    "unpassable",           # judge impossible_task / captcha / Skyvern-style terminate
]

class FailureEpisode(BaseModel):
    kind: FailureKind
    expectation_id: str | None = None    # which key point (verify)
    transition_id: str | None = None     # which edge (validate)
    source: str | None = None            # the state to re-explore from
    unmet_conditions: list[str] = []     # ConditionCheck.type values that failed
    page_url: str | None = None
    step_n: int | None = None            # the trajectory step that contradicts it
    detail: str = ""
    attempt: int = 0

    def as_task_hint(self) -> str:
        """The one line handed back to `explore`. Prose ONLY here, at the seam into a prompt."""
```

Routing (all zero-LLM; the classification is a `match` over `EdgeOutcome` + `ConditionCheck` +
`Verdict.statuses`, both of which the executor and verifier already produce):

| Kind | Detected by | Route | What the receiver is told |
|---|---|---|---|
| `expectation_unmet` (at verify) | `Verdict.achieved == False` | → `explore` | task + *"A previous attempt did not achieve: `<expectation.text>`. The page never showed `<check>`."* |
| `expectation_unmet` (at validate) | `accept_met` has an unmet conjunct, all edges ok | → `explore` from `source` | same, plus the replay's URL |
| `param_unbound` | `compile_trajectory` `warnings` already emit this ([`compiler.py:208-213`](../../src/netgent/agent/generator/compiler.py)) | → `generate` (re-bind) once, then → `explore` | *"you must set `param` on the step that types `${name}`"* — the existing prompt contract ([`orchestrator.py:96-106`](../../src/netgent/agent/orchestrator.py)) |
| `flow_drift` | `trigger_timeout`, no conditions met, action ok | → `explore` from `source` | the failing edge and what it expected |
| `ui_drift` | `action_error`, 0 matches | → `explore`; record the dead locator | — |
| `ambiguity` | `action_error`, >1 match | **END** | decision #8 |
| `over_strict_guard` | `trigger_timeout`, *some* conditions met | → `generate` (drop the conjunct), re-validate once | — |
| `flaky` | passes only on the retry replay | report; `validated` stays **false** | Playwright Test's classification; [`browser-agent-architectures.md`](browser-agent-architectures.md) §5.3 |
| `unverifiable` | `Verdict.unverifiable` non-empty for a required expectation | report loudly; **never** silently pass | Stagehand `verifierGate.ts:1-10` |
| `unpassable` | `JudgeNote.impossible_task` / `reached_captcha` | **END** | the one place a judge may end the run, and only to *stop* work |

Graph, extending [`build_orchestration_graph`](../../src/netgent/agent/orchestrator.py):

```
START → plan_checks → explore → verify ─┬─ achieved ──► generate → validate → triage ─┬─ ok ──► END
        (LLM ×0|1)    (LLM ×N)  (0 LLM) │                (0 LLM)    (0 LLM)   (0 LLM) │
                          ▲             └─ not achieved ──────────────────────────────┤
                          └───────────── retry, bounded by req.max_attempts ──────────┘
```

```python
async def verify(state: OrchestrationState) -> Command[Literal["generate", "explore", "__end__"]]:
    verdict = await verify_trajectory(session, state["trajectory"], state["spec"])
    if judge_enabled:                       # advisory; may only demote, and only where source="page"
        verdict = attach_judge(verdict, await judge_trajectory(...))
    emit("verify", f"{sum(s.state=='met' for s in verdict.statuses)}/{len(verdict.statuses)} "
                   f"expectations met (agent claimed {verdict.agent_claim})")
    if verdict.achieved:
        return Command(update={"verdict": verdict}, goto="generate")
    episodes = triage_verdict(verdict, attempt=state.get("attempt", 0))
    if any(e.kind == "unpassable" for e in episodes) or state.get("attempt", 0) >= req.max_attempts:
        return Command(update={"verdict": verdict, "episodes": episodes,
                               "error": "exploration did not achieve the task"}, goto=END)
    return Command(update={"verdict": verdict, "episodes": episodes,
                           "attempt": state.get("attempt", 0) + 1}, goto="explore")
```

`explore` reads `state["episodes"]` and appends `e.as_task_hint()` to the task — the same
"failure-seeded next attempt" that WebRL's curriculum and Magentic-One's plan-update prompt both use
(`_prompts.py:133-136`), reduced to its cheapest form. **`max_attempts` defaults to 1** (one retry),
because unbounded retry against a real site is a cost and a politeness problem, not a correctness one.

**`--runs N` and `pass^k`.** With `runs > 1` the pipeline fans out explorations
([`browser-agent-architectures.md`](browser-agent-architectures.md) §5.3), each producing its own
`Verdict` against the **same cached** `TaskSpec`. Report:

- `verify_pass^k` = fraction of runs where every required expectation was met by page evidence;
- `replay_pass^k` over the param sets in `validate`;
- and, separately, `agent_claim` agreement — the corpus that eventually licenses (or refuses) any
  judge authority. Report `pass^k`, not `pass@k`: NetGent's product is *reproducible* traffic, so
  "at least one run worked" is the wrong statistic (arXiv:2406.12045 §3.3).

### 6.5 (e) What to build first, and how to measure it

**Slice 1 — the zero-LLM verify node (highest confidence gain per line).** Move
`sweep._form_succeeded` into `verifier/check.py` as `verify_trajectory`, generalised from
`DEFAULT_MARKERS` to `Expectation.check`, with `derive_deterministic()` as the only spec source (no
LLM at all). Wire it into `orchestrator` between `explore` and `generate`, replacing
`if not traj.success` ([`orchestrator.py:111-114`](../../src/netgent/agent/orchestrator.py)) with
`if not verdict.achieved` — and *log* `agent_claim` beside it.

Why first: it needs no new model call, no new schema, and no prompt change; it immediately catches
the class of failure NetGent has actually shipped (the un-parameterised YouTube workflow); and it is
measurable the same afternoon on the existing sweep, where `_form_succeeded` is already ground truth.

**Slice 2 —** `text_visible` merged from `eugene/v2-discovery`
(`schema/triggers.py`, `TextVisible`), plus `browser/triggers.py` support. Without it, half the
expectations have `check=None`.

**Slice 3 —** `plan_checks`: the LLM key-point call, cached, validated into `Trigger`s, degrading to
slice 1 when absent.

**Slice 4 —** `accept_states` in `compile_trajectory` + `accept_met` in `ReplayResult` (§6.3).

**Slice 5 —** the advisory judge, then `triage` routing. Both are worthless before slices 1–4 give
them something deterministic to defer to.

**Measurement.** Three corpora already exist and already carry page-derived truth:

1. **The 21-form sweep** ([`stress.py:102-127`](../../src/netgent/evals/stress.py), `sweep_forms`).
   `FormResult` already records `submitted` (page truth) beside `agent_success` (claim)
   ([`sweep.py:31-38`](../../src/netgent/evals/sweep.py)). Report the verifier's verdict as a third
   column and compute precision / recall against `submitted`.
   **The acceptance test is the two broken fixtures — `ember` and `shadow-dom`
   (`browser-agent-date-inputs.md:24`: sweep 19/21, *"the ceiling, Ember and Shadow DOM being broken
   fixtures"*). A verifier that marks either as achieved is a false positive and the slice is not
   done.** This is a real, standing adversarial pair: agent-claims-success-on-an-unsubmittable-form is
   precisely the case §4.3's four judge failure modes produce.
2. **The challenge game** ([`stress.py:64-99`](../../src/netgent/evals/stress.py)). The page's own
   `.score`, `.task.completed` ids and `missed` list are an oracle, and `agent_success` is already
   recorded next to them. Per-card expectations turn this into a checkpoint-graded corpus
   (TheAgentCompany's shape) that measures *partial* scoring, not just the binary.
3. **`netgent generate` on `examples/cat-video.yaml` / `twitch-live.yaml`** with a wrong param, to
   confirm slice 4 fails the replay it should fail.

Report per slice: **false-positive rate** (verdict `achieved` where the page says otherwise — the
number that matters, since judges' error is one-directional), false-negative rate, `unverifiable`
count per task (Stagehand's arm metric), and agent-vs-verifier disagreement in both directions. Add
judge-vs-page agreement once slice 5 exists, and hold the judge advisory until that agreement is
measured on **our** corpus — not on the field's.

**Explicitly do not build:** an LLM that gates the artifact (§4.2); an LLM that mints selectors
(§6.1); per-step LLM verification (PAE found step-level evaluation *"too noisy"*, arXiv:2412.13194
§4.3, and our per-step signal is already deterministic — `error`, `dialogs`, `texts_seen`, observation
equality); a similarity threshold anywhere (`OVERVIEW.md` §7.1 item 3).

---

## 7. Provenance and unverified claims

**Verified by reading source this session** (fetched 2026-08-27, pinned):
browser-use `6ed72e1fb3693b9f990bafae4da004e0c991bd2a` — `browser_use/agent/judge.py` (225 lines,
read in full), `agent/views.py`, `agent/service.py`, `agent/system_prompts/system_prompt.md`,
`tests/ci/evaluate_tasks.py`.
Skyvern `d081a5324bda5bdf58c640f1c59b2c40975e64c1` — `forge/prompts/skyvern/check-user-goal.j2`,
`check-user-goal-with-termination.j2`, `task_v2_check_completion.j2`, `validation-evidence-router.j2`,
`workflow-copilot-completion-verification.j2`, `task_v2.j2`, `extract-action.j2`,
`forge/validation_evidence_router.py`, `forge/failure_classifier.py`,
`forge/sdk/copilot/completion_verification.py`, `verification_evidence.py`,
`outcome_verification_trace.py`, `forge/sdk/browser_action_policy.py`, `client/types/validation_block.py`.
Stagehand `4d88741a0e2283942f67ae7005a52d6f7e703698` — `packages/evals/framework/verifierAdapter.ts`,
`verifierGate.ts`, `adHocRubric.ts`.
workflow-use `891267bb614c0b0821adbb0f7fffc0ebbf045a38` — `workflow/step_verifier.py`.
autogen `027ecf0a379bcc1d09956d46d12d44a3ad9cee14` —
`.../teams/_group_chat/_magentic_one/_prompts.py` (read in full).
magentic-ui `d3c9d13c39288257286a66daabf7c5b5fb72ee69` — `teams/omniagent/_verifier.py`.
WebArena `dce04686a56253aefba7b18a4fa0937cf1dc987b` — `evaluation_harness/evaluators.py`.
WebVoyager `5a7896738c10bfb8b9edccce6bb0e0411f8ae569` — `evaluation/auto_eval.py`.
Agent-E `f218c3cb4b2b3e33ed08ea12da5514ab1e89cdd7` — `ae/core/prompts.py`.
Notte `main` (unpinned) — `packages/notte-agent/src/notte_agent/common/types.py`.

**Verified by reading the arXiv HTML this session:** 2504.08942v2 (AgentRewardBench — Tables 1 & 2,
§3.1, §3.3, §4.2, §4.3, §5, §6 read in full), 2504.01382v3 (Online-Mind2Web / WebJudge — §3, §4, §5
and the three appendix prompts), 2404.06474v3 (AutoEval — §4.1, §4.3), 2412.14161v3
(TheAgentCompany — §3, §4.1), 2406.12045v1 (τ-bench — §2, §3.3, §5), 2410.10934v2 (Agent-as-a-Judge),
2411.02337v3 (WebRL §3.8), 2410.02907v2 (NNetNav), 2412.13194v1 (PAE §4.3), 2406.12373v3
(WebCanvas §2.2-2.3, §6.2), 2504.07079v1 (SkillWeaver §A.5, §D.2.1), 2409.07429v1 (AWM §2.3),
2504.06821v2 (ASI §2.3).

**Verified against this repo** at `06aecd8` (branch `eugene/v2-scaffold`), plus
`eugene/v2-discovery` for `schema/triggers.py` and `agent/evidence.py`. Every `file:line` above was
read; the discovery-branch line numbers are from `git show eugene/v2-discovery:<path>` and will move
on merge.

**Carried from [`browser-agent-architectures.md`](browser-agent-architectures.md), not re-verified
this session:**
- WebVoyager's **85.3%** human agreement (arXiv:2401.13919 abstract). The *prompt* is verified at
  `5a78967`; the number is not.
- Magentic-One's **−31%** ledger ablation and **21–39%** worker ablations (arXiv:2411.04468 Fig. 3).
- SteP's 14.9% → 33.5%, WebPilot 95.6% vs SteP 96.0% on MiniWoB++, MAST's 14 failure modes.
- ReUseIt's 24.2% → 70.1% (see [`reuseit.md`](reuseit.md)).

**Unverified / weaker evidence:**
- **The judge-input claim in §4.3 is a design inference, not a measured result.** AgentRewardBench
  §6 shows judges deferring to agent reasoning; it does **not** run an ablation withholding that
  reasoning. Predicting that withholding raises precision is *our* hypothesis, and §6.5 is written to
  measure it rather than assume it. Table 2's a11y-vs-screenshot ablation is the closest published
  evidence that *removing* input can help, and it is about representations, not about self-report.
- **No accuracy number exists for any of the production judges surveyed** (browser-use, Skyvern,
  Stagehand, workflow-use). Every number in §4.2 comes from a benchmark paper, on *benchmark*
  trajectories, none of them NetGent's. The ~70% ceiling is a strong prior, not a measurement of what
  a judge would do on the 21-form sweep.
- **`text_visible` semantics across the merge.** The discovery branch defines it as a
  case-insensitive substring over visible elements; whether `traj.texts_seen` and a live
  `condition_report` agree on "visible" in every frame/shadow case is untested. Slice 2 must add a
  unit test that the same `Trigger` evaluated against `texts_seen` and against a live snapshot cannot
  disagree for a text that is currently on screen.
- **The over-strictness cost of §6.3 is not quantified.** The 55.9% rule-based recall figure is
  WebArena's hand-written oracles, not ours; how often a task-derived `text_visible` fails a correct
  NetGent workflow is exactly what slice 4's measurement is for.
- **Skyvern's `VALIDATION_EVIDENCE_ROUTER_MODE` default and confidence floor** live in
  `skyvern/config.py`, which was not read; §3.3 describes the mechanism (`off`/`shadow`/`enforce`,
  `min_confidence`), not the shipped setting.
- **workflow-use is pinned to an older commit** (`891267b`, 2026-07-29) than its HEAD (`5d2d19f`,
  2026-08-27), for continuity with
  [`browser-agent-architectures.md`](browser-agent-architectures.md). Its verifier may have changed.
