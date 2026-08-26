# Alternatives to ReUseIt — prior art for NetGent v2's discovery step

Source-verified survey for the NetGent v2 team (UCSB SNL). Written 2026-08-21.
Companion to `reuseit.md` (the closest prior art) and `long-horizon-agents.md` §3 (the proposed
discovery algorithm). Every system below was read as **source** unless explicitly marked
*paper-only*; repositories were shallow-cloned on 2026-08-21 and are cited by file, symbol,
and the commit that was read.

---

## Question

NetGent v2 compiles a natural-language task into a deterministic NFA (states carry trigger
conjunctions; transitions carry exactly one atomic action; pop-ups are ε-transitions; the LLM
runs only at compile time). The unspecified piece is **discovery**: how to explore a site so that
the synthesized workflow survives pop-ups, layout drift, parameter variation, and scenario
variation — and how failed runs become recovery branches rather than dead trajectories.

ReUseIt answers this with ~20 LLM runs per task family, mining failures into prose condition
checks and successes into prose fallback actions. It has no code release and its artifact is
never compiled. So: **what else turns exploration or demonstration into a reusable artifact, and
what of it is actually implemented?**

The three questions asked of every system:

1. Is exploration **systematic** (site graph, BFS, variation taxonomy, curriculum) or incidental?
2. How are **multiple runs consolidated** — and are **failures** used at all?
3. Is the artifact **verified**, and does it run **without an LLM**?

---

## Per-system findings

### 0. ReUseIt (baseline) — arXiv 2510.14308, IUI '26

Recapped from `reuseit.md`. N=5 runs of the original task plus 5 of each of three LLM-generated
variations (attribute / category / website) ≈ 20 runs. Failed runs → pre/post **condition checks**;
successful runs → **fallback actions** + the step structure (from Magentic-UI's plan learner).
Guards are evaluated at run time by a VLM over a screenshot; ≤3 fallback retries; then escalate to a
human whose reply is parsed back into more checks/fallbacks.

- **Consolidation:** an LLM reads both pools at once and writes one prose document (Appendix C.4).
- **Validation:** none of the artifact. Evaluation is end-task success rate (24.2% → 70.1%).
- **LLM at replay:** yes, everywhere — the agent itself, every guard, every escalation.
- **Status:** *paper-only.* No repository; four of eight prompts unpublished.
- **The number that matters:** the ablation, 50.1% (checks only) → 70.1% (checks + fallbacks),
  holds the retry budget fixed. Guided recovery is worth ~20 points; unguided retry is worth little.

---

### 1. Agent Workflow Memory (AWM) — `zorazrw/agent-workflow-memory` @ `8c0ff8c` (2025-12-22)

**What it is.** Wang et al. 2024 (arXiv:2409.07429). Induce reusable "workflows" from past
trajectories and inject them into the agent's prompt. Two settings: **offline** (from annotated
training examples, `mind2web/offline_induction.py`) and **online** (from the agent's own past runs,
`webarena/induce_prompt.py`).

**Exploration strategy.** None. AWM does not explore; it consumes trajectories produced by a
benchmark task list. `webarena/pipeline.py` is the whole online loop: for each task id →
`run.py` → `autoeval.evaluate_trajectory` → `induce_prompt.py`, rewriting the workflow file in place.

**Recording.** `extract_think_and_action()` scrapes the BrowserGym `experiment.log` into
`(think, action)` pairs; `remove_invalid_steps()` drops malformed `click()`/`fill()` and (in
`induce_prompt.py`) all `scroll`/`noop`.

**Consolidation.** Two variants, both worth stealing conceptually:
- *Neural* (`induce_prompt.py`): dedup by `intent_template_id`, sample ≤`num_samples` per template,
  then one GPT-4o call over the concatenated examples with `prompt/instruction.txt` — "find the
  repetitive subset of actions across multiple tasks… Represent the non-fixed elements with
  descriptive variable names… Keep the values of invariant elements".
- *Rule-based* (`induce_rule.py`): dedup by template id, **then dedup by abstract trajectory** —
  `get_abstract_trajectory()` joins `action_name(first_arg)` per step into a single string key.
  Optional human y/n gate. Output is the raw trajectory text.

**Failure use.** **None.** Both scripts filter to successes only (`criteria="gt"` → `cum_reward`;
`criteria="autoeval"` → `record[0]["rm"]` from the LLM judge). This is precisely the asymmetry
ReUseIt adds.

**Validation.** None of the artifact. `webarena/autoeval/` judges *task* success, which is the
induction filter, not an artifact check.

**LLM at replay.** Yes, totally. `webarena/agents/legacy/agent.py:116-117`:
`sys_msg += '\n\n' + open(self.flags.workflow_path).read()`. The "workflow" is a string appended to
the system prompt. Retrieval for Mind2Web is FAISS over workflow name+docstring
(`mind2web/workflow/retrieve.py`).

**Verified:** yes, all of the above read in source. The checked-in `webarena/workflow/*.txt` are
rule-induced concrete exemplars (query + `<think>/<action>` blocks), not abstracted summaries — a
useful reality check on what "induced workflow" means here.

---

### 2. SkillWeaver — `OSU-NLP-Group/SkillWeaver` @ `f2a63d6` (2025-04-14)

**What it is.** Zheng et al. 2025 (arXiv:2504.07079). A web agent that explores a site and distills
what worked into **typed Python APIs** — the strongest "artifact is code, not prose" system in this
survey. Reported +31.8% relative on WebArena, +39.8% on live sites.

**Exploration strategy.** Systematic and *scheduled*. `skillweaver/explore.py::_run_explore_iteration`
alternates two task kinds per iteration under `_should_perform_test()`
(`"explore:X,test:Y"` or `"test_probability:p"`):
- `_choose_explore_task` — an LLM proposes a new skill from the AX tree + screenshot
  ("You propose tasks that would make good 'tools' for external users of a website").
- `_choose_test_task` — **practice an existing untested skill**, sampled softmax over
  `KnowledgeBase.rate_practice_utility(fn) = count_interactions(fn) − version`, i.e. prefer skills
  that touch many elements and have been rewritten least. Test-case *arguments* are generated by an
  LLM from the live page (`_generate_test_case_arguments`).
- Drift control: return to `base_url` when the agent leaves the host/path prefix or every
  `return_home_every_n_iterations`.

**Recording.** Playwright tracing per iteration (`trace.zip`), states+actions, and a pretty-printed
`trajectory_pretty.txt`. Everything under `logs/.../iter_N/`.

**Consolidation.** `KnowledgeBase.update()` is an LLM rewrite of a single Python module, but with
two disciplines NetGent should copy: (a) the prompt context is **filtered to verified code only** —
`if self.is_tested(f["name"]) or …` — so untested skills can't contaminate new ones; (b) the output
must pass `knowledge_base/code_verification.py::check_code`, retried up to **10 times** with the
violation list fed back. `check_code` rejects: any `try` block ("You must check for errors
proactively"), any `while` loop, non-`async` defs, missing docstring, missing `await page.goto(...)`,
`page.click(selector)` instead of `locator.click()`, and `.locator(`/`.query_selector(` (AX-tree
selectors only). Plus static type checking (`type_checking.py`).

**Failure use.** Two channels. (1) A task that fails its LLM success check
(`knowledge_base/check_success.py::check_success_simple`, VLM over trajectory + final screenshot)
simply does not update the KB. (2) **Locator-level recovery is recorded and folded back**:
`environment/patches.py` wraps Playwright locator errors, presents the AX tree as a multiple-choice
question, asks the model for the intended element **and a replacement locator expression**, up to 5
attempts; the resulting `RecoveryResult` list annotates the function source
(`agent.py::annotate_source_with_recoveries`, "We found a bug in one of the APIs…") for the next KB
rewrite. A test-task run that needed recovery is **not** counted as a passing test
(`_successfully_executes_function_without_errors` requires `recovery_results` empty).

**Validation.** Real, and the best-designed here: a skill is only "tested" after it executes
end-to-end with its own generated arguments, no exception, no recovery. `increment_test_count`.

**LLM at replay.** Split. The **skill** is plain Playwright code and runs zero-LLM; but the caller
(`attempt_task.py`) is an LLM codegen loop that writes an `act()` function per step, and the
locator-recovery path is an LLM. There is no "run this skill deterministically end-to-end" mode.

**Verified:** yes.

---

### 3. browser-use / workflow-use — `browser-use/workflow-use` @ `891267b` (2026-07-29)

**What it is.** Two front doors to one artifact: a Chrome-extension **recording** of a human demo,
or `HealingService.generate_workflow_from_prompt()` — run a browser-use Agent on a prompt, then
convert its history into a typed JSON/YAML workflow. **The repo has moved a long way past the
"builder + healing, no validation" description**: at this commit there is a per-step deterministic
verifier, a priority-ordered selector ladder, pattern-based variable extraction, and an optional
LLM validation pass.

**Exploration strategy.** Single run. No variations, no repeats, no site graph. The one clever
touch is prompt engineering for *recordability*: the agent's task is augmented with
"For EVERY action you take, you MUST include this structured tag… `[ELEMENT: "exact visible text"]`"
(`healing/service.py:797-812`), so the recording carries semantic anchors.

**Recording.** A `CapturingController(Controller).act()` override snapshots browser-use's
`selector_map` **before** each action and keeps text / tag / attributes per element index — with
explicit heuristics for bad anchors (`is_poor_text`: empty, ≤2 chars, "link"/"button"/"click"/"here",
or an 8-char alphanumeric that looks like an id).

**Consolidation.** None across runs — one run in, one workflow out. Within a run there are two
converters: the LLM `BuilderService` (`builder/prompts.py::WORKFLOW_BUILDER_PROMPT_TEMPLATE`, which
also decides which steps must stay *agentic*) and a 912-line `DeterministicWorkflowConverter`
(`use_deterministic_conversion`, default **False**).

**Failure use.** None at compile time. At run time `WorkflowService._execute_step` raises on a failed
deterministic step; the agent-fallback path exists but is **commented out** (`workflow/service.py:691-696`),
leaving only the semantic-execution fallback (no `cssSelector` but `target_text` present →
`SemanticWorkflowExecutor`).

**Validation.** `healing/validator.py::WorkflowValidator` — an LLM reads the workflow JSON (plus
optional browser logs from a failed run) and returns typed `WorkflowIssue{severity, step_index,
issue_type, description, suggestion}` plus an optional corrected workflow. Gated by
`enable_ai_validation`, default **False**. It is static review, not replay.

**LLM at replay.** Mostly no, sometimes yes: deterministic steps dispatch through the controller;
`extract` steps call an LLM; `agent` steps run a full browser-use Agent; `SemanticWorkflowExecutor`
uses a page-extraction LLM.

**Two mechanisms worth lifting wholesale:**
- `workflow/step_verifier.py::StepVerifier._get_verification_checks` — a **per-action-type table of
  post-conditions, computed with no LLM**: navigation → `check_url_matches` + `check_page_loaded`;
  click → `check_page_state_changed` (against a pre-step snapshot); input → `check_input_value` +
  `check_no_validation_errors`; select → `check_option_selected`; scroll → `check_scroll_position`;
  extract → `check_data_extracted`. Methods are `DETERMINISTIC | AI_ASSISTED | HYBRID`
  (deterministic first, AI only as fallback), results are `SUCCESS | FAILURE | UNCERTAIN | SKIPPED`.
- `healing/selector_generator.py` — 8 priority-ordered strategies per element (exact text = 1 …
  XPath = 8, absolute XPath last), capped by `max_total_strategies=2` in the current wiring;
  `workflow/element_finder.py::find_element_with_strategies` walks them in order and records a
  `StrategyAttempt` per try.
- `workflow/variable_identifier.py` — three-stage parameter detection (regex patterns @0.95
  confidence → context → heuristics @0.5), **no LLM, `$0 cost`** per its own comment.

**Verified:** yes.

---

### 4. Skyvern — `Skyvern-AI/skyvern` @ `888348d` (2026-08-21)

**What it is.** A production agent platform. Two pieces matter here: **Task v2** (the planner that
decomposes a goal into blocks and persists them as a workflow) and **script generation / caching**
(turning workflow *runs* into a deterministic Python script that later runs replace the agent with).
This is the closest industrial analogue to NetGent's compile step, and the only system in this
survey that consolidates *multiple runs* into one deterministic artifact by construction.

**Exploration strategy.** Goal-directed planning, not exploration. `forge/prompts/skyvern/task_v2.j2`
asks each planning iteration for `required_subgoals: [{subgoal, satisfied, evidence}]` — an explicit,
carried-forward decomposition ("Required subgoals carried forward from the previous planning step")
with `user_goal_achieved` allowed true only if every entry is satisfied. Under the
`planner_mini_goal_improvements` flag each mini-goal also carries a `complete_criterion`: "a short,
checkable statement of what is true on the page once this mini goal is done… The inner agent stops as
soon as this holds instead of running to its step limit." That is a per-milestone rubric authored by
the planner — the same shape as the completion rubrics in `long-horizon-agents.md` §3 Phase 0.

**Recording.** Every action of every block is persisted (tasks, actions, workflow_run_blocks);
`core/script_generations/transform_workflow_run.py` batches them into codegen input.

**Consolidation — the interesting part.** `core/script_generations/CLAUDE.md` (in-repo design doc)
documents **progressive caching**: script code is generated per *block that executed this run*;
conditional blocks are never cached (they re-evaluate live), but cacheable blocks inside branches are
cached when they execute — "Run 1 takes branch A → caches blocks from A; Run 2 takes branch B →
caches blocks from B (preserves A's cache)". A workflow only runs `run_with: code` when **all**
top-level blocks have a `script_block` row and a non-null `run_signature`; otherwise it falls back to
`run_with: agent`. That is exactly NetGent's "N runs discover the branch set" problem, solved by
accumulation rather than by a merge pass.

**Failure use.** `services/script_reviewer_v3/` — a budgeted LLM agent that reviews **fallback
episodes** (the moments where the deterministic script had to call AI) and persists edits as new
script versions. It runs `midrun` (live page, "hypothesis → try → observe"; skills can read DOM around
a selector and attempt click/fill, where "a successful mutation IS the commit") and `postrun` (DB +
artifacts). Skill families: `interact | investigate | investigate_artifacts | validate | persist |
terminal`. Budgets are explicit (`budget.py`: max cycles, tokens, cost USD, wall seconds, invocations
per run). So: replay failures are the training signal for the next artifact version.

**Validation.** `core/script_generations/script_validators.py` — AST-based checks shared by the
generator and reviewer (e.g. `validate_missing_selectors`, `iter_interaction_calls` distinguishing
kwargs from string literals), plus `parameter_reference_guard.py::HallucinatedParameterError`.
Static, on generated code.

**LLM at replay.** **Only on failure** — the design NetGent should study hardest. The cached script
is Playwright code, but `skyvern_page.py::element_fallback` (line 3516) delegates to
`real_skyvern_page_ai.py::ai_element_fallback(navigation_goal, max_steps=5)`, "Drive an AI agent from
the current page state toward `navigation_goal`". `fill_from_mapping` caps this at
`max_ai_fallbacks = 10` per call. Other `ai_*` hooks exist by design (`ai_extract`, `ai_validate`,
`ai_act`, `ai_classify`).

**Verified:** yes (prompts, codegen, validators, reviewer read in source; the caching semantics are
from the repo's own `CLAUDE.md`, which is a design doc rather than executable proof).

---

### 5. Stagehand — `browserbase/stagehand` @ `a21633d` (2026-08-21)

**What it is.** An act/observe/extract SDK with a server-backed cache. The pattern is *replay first,
LLM only on miss*.

**Exploration / recording / consolidation.** None. The cache is per-call.

**The mechanism.** `packages/extension/services/cacheService.ts::withCache` keys a request on
`{method, sessionId, url, cdpTree, data}` — **the CDP accessibility tree is part of the key**, with a
server-side similarity `threshold` and a `hitCount`. On a hit, `actService.ts::replayCachedActions`
runs the cached actions through `takeDeterministicAction` with `context: {…, selfHeal: false}` and
throws on the first failure; the wrapper catches, marks `missReason: "replay_failed"`, and reruns the
full inference pipeline — the comment says it plainly: "Any failure throws so the cache intercept falls
back to the full inference pipeline, which doubles as the self-heal path for stale cached selectors."

**Failure use.** Only implicit (a stale entry is replaced by whatever the fresh inference produces).

**LLM at replay.** No on a hit, yes on a miss. Agent-level fallback is a documented user pattern
(`packages/docs/v2/best-practices/agent-fallbacks.mdx`: `act()` → on throw → `agent.execute({maxSteps: 10})`).

**Note:** the `AgentReplayStep` type named in the brief **does not exist at this commit** (no match for
`ReplayStep` in the repo). The CHANGELOG confirms cached-action replay covers "agent & act", so the
concept survives under different naming.

**Verified:** yes.

---

### 6. Lumen — `omxyz/lumen` @ `b1ad26a` (2026-03-29)

**What it is.** Jina's vision-first browser agent, ~2 kLOC of readable TypeScript. It contains, in
miniature, three of the mechanisms this survey keeps rediscovering.

- `src/memory/workflow.ts::WorkflowMemory` — self-described "AWM-inspired". `Workflow{name, trigger,
  steps: string[], domain, successCount}`. `extract()` compresses a successful run's semantic history
  into ≤15 prose steps ("Click at (x, y)", "Type …"), derives `trigger` from ≤4 non-stopword
  instruction tokens; `match()` scores by trigger substring length + domain bonus + `min(successCount, 5)`;
  `add()` merges by `(domain, trigger)` and **keeps the shorter step list** — a one-line consolidation
  policy: prefer the cheaper demonstration. `toPromptHint()` injects it as "SUGGESTED WORKFLOW … adapt
  as needed".
- `src/loop/action-cache.ts::ActionCache` — `stepKey(url, instructionHash)` (deliberately excluding
  action type: "Solves the chicken-and-egg problem… Self-healing handles the case where the cached
  action is wrong"). Coordinate actions additionally store a `screenshotHash`; `viewportMismatch()`
  compares cached vs current viewport. Replay path (`loop/perception.ts:110-160`): cache hit → execute
  via router → **if `!outcome.ok`, return null and fall through to the model**. Honest caveat in the
  source: `similarity()` is a stub returning 1.0 on exact hash equality — so the perceptual guard is
  currently all-or-nothing, and the viewport check is logged as "informational only".
- `src/loop/action-verifier.ts::ActionVerifier` — "BacktrackAgent-inspired post-action verifier…
  No API calls — purely based on CDP state inspection", switching on action type (click / type / goto).

**Failure use / validation / consolidation across runs:** none beyond `successCount`.

**LLM at replay:** yes on a cache miss; no on a hit.

**Verified:** yes.

---

### 7. Magentic-UI plan learning — `microsoft/magentic-ui`, tag `v0.1.0` (HEAD `d3c9d13`, 2026-07-23)

The substrate ReUseIt builds on. `src/magentic_ui/learning/learner.py::learn_plan_from_messages`
sends the conversation plus a fixed instruction to the model with `response_format=Plan`, where
`Plan = {task, steps: [PlanStep{title, details, agent_name}]}`; the prompt asks for "the most
efficient and direct plan… the less number of steps, the better" and to "Include details about the
actions performed, buttons clicked, urls visited if they are useful". Sibling `adapt_plan` re-prompts
for a new task. Storage/retrieval is AutoGen's `task_centric_memory.MemoryController`
(`learning/memory_provider.py`), surfaced through `backend/web/routes/plans.py` (`POST /plans/learn_plan`)
and the frontend's `LearnPlanButton` / `relevant_plans` views.

**Note the drift:** `src/magentic_ui/learning/` **no longer exists at HEAD** — verified by
`git ls-tree` at `v0.1.0` vs the HEAD tree. Anything citing Magentic-UI plan learning (including
ReUseIt's footnote) must pin the tag.

- Exploration: none. Recording: chat messages. Consolidation: one LLM call per saved plan.
  Failure use: none. Validation: none. LLM at replay: yes (the plan is prompt context).
- **Verified:** yes.

---

### 8. NNetNav — `MurtyShikhar/NNetNav` @ `9d64248` (2025-04-16)

Exploration first, labels afterwards. `src/nnetnav_utils.py`:

- **Exploration** is an LLM policy with no goal, bounded by `early_stop(trajectory, max_steps,
  thresholds)` — max steps, *k* consecutive parse failures, *k* repeated equivalent actions (with a
  special case for `TYPE`). This is the cheapest loop-detector in the survey and directly usable.
- **Recording:** per-step `(init_observation, action, final_observation)` triples pushed through a
  **changelog model** (`TrajectoryLabeler.get_changelogs`) that describes what the action changed —
  i.e. *state diffs are first-class*, exactly what NetGent needs to draft target-state guards.
- **Retroactive labeling:** `label_all_endpoints` labels **every prefix** of a trajectory (every 4
  steps) with an instruction, turning one exploration run into many (instruction, trajectory) pairs.
- **Pruning:** `LanguagePruning.__call__` labels, scores with a reward model, and prunes when
  `reward < best_reward − 1` (default `best_reward=5`).
- Consolidation: none — the artifact is an SFT dataset (`stanfordnlp/nnetnav-live`, `-wa`) and a
  fine-tuned Llama-8B. Failure use: pruned away. Validation: the reward model. LLM at replay: yes
  (the artifact *is* a model).
- **Verified:** yes.

---

### 9. Explorer — `OSU-NLP-Group/Explorer` @ `209bc48` (2026-02-17), ACL 2025 Findings

94K multimodal trajectories, 49K URLs, ~28¢ per successful trajectory. The pipeline is documented as
pseudocode in `traj_gen/README.md` and implemented in `traj_gen/`: a **captcha agent** screens step 0;
a **task proposal agent** invents the intent from the first page; a **task refiner agent**
(`task_refiner_agent.py`) *rewrites the goal at every step* given the AX tree, screenshot and action
history — so the task is fitted to what the agent could actually do; a **summarizer** produces the
final user intent; a **VLM verifier** (`trajectory_verifier.py`) judges intent vs action history + all
screenshots + last-page markdown.

- Exploration: broad but shallow (one pass per URL, no site graph, no state dedup).
  Consolidation: none. Failure use: unverified trajectories are dropped. Artifact: SFT data → weights.
  LLM at replay: yes.
- **Verified:** yes (code + in-repo pseudocode).

---

### 10. Go-Browse — `ApGa/Go-Browse` @ `8742490` (2025-10-08)

**The systematic exploration algorithm this survey is otherwise missing.** Outer loop = graph search
over pages; inner loop = exhaust one page.

- `webexp/explore/core/graph.py::Graph` — nodes keyed by **URL**, `unexplored_nodes` FIFO
  (`get_next_node` returns `[0]`, with a literal `#TODO: Can add user-defined priortization here`),
  plus `allowlist_patterns` / `denylist_patterns` to bound the crawl.
- `webexp/explore/core/node.py::Node{url, tasks, exploration_tasks, children, description, prefixes,
  visited}` — `prefixes: list[Trace]` records *how the node was reached*.
- Per node (`algorithms/web_explore.py::web_explore_loop`): **page explorers** propose on-page tasks;
  **nav explorers** propose tasks that discover neighbours; `filter_to_feasible_tasks_for_node`
  *attempts* each proposal and keeps only those a strong model + VLM judge can complete
  (capped by `max_feasible_{page,nav}_explorer_tasks_per_node`); then `sample_task_solving_trajectories_for_node`
  samples `num_trajs_per_task` trajectories from other models.
- **Reset semantics:** `core/episode.py::reset_env_to_node` = `env.reset()` then `goto('<node.url>')`,
  plus an optional whole-environment `full_reset_url` POST (`webarena-reset/`). Cheap — and the reason
  it works is that WebArena state is URL-addressable. NetGent's flows (logged-in, cart-filled, player
  started) are **not**, which is exactly why `long-horizon-agents.md` §3 P3 proposes
  checkpoint-by-*replay* instead.
- Consolidation: none (the artifact is ~10K successful + ~17K unsuccessful trajectories → a fine-tuned
  Qwen-7B, 21.7% on WebArena). Failure use: **unsuccessful trajectories are kept and released** — the
  only dataset here that ships its failures. Validation: VLM judge. LLM at replay: yes.
- **Verified:** yes.

---

### 11. PAE (Proposer-Agent-Evaluator) — `amazon-science/PAE` @ `f40715b` (2024-12-30), ICML 2025

Autonomous skill discovery as RL. `scripts/propose_tasks_from_names_webvoyager.py` prompts Claude for
tasks given only a website name (+ optional demos) with constraints that are a ready-made spec for
NetGent's variation generator: diverse difficulty, "minimum completion steps from 3 to 7",
"objective and unambiguous", not dependent on current time/location, "able to be evaluated OBJECTIVELY…
by looking at the last three screenshots and the answer", "Humans should have a 100% success rate",
"completed without having to sign in". Evaluation is `environment/webgym/utils_eval.py::auto_eval_by_claude3`
(WebVoyager protocol) or the WebArena string/URL/HTML evaluators. The reward trains the policy.

- Exploration: proposer-driven, no site graph. Consolidation: RL, not merging. Failure use: negative
  reward. Artifact: weights. LLM at replay: yes.
- **Verified:** yes.

---

### 12. WebRL — `THUDM/WebRL` @ `fa8439e` (2025-06-06)

Self-evolving **curriculum** — the one system that turns failures into *the next round's exploration*.
`scripts/gen_task.py`: read the file of **failed instructions**, group by website, sample ~10 as seeds,
and prompt GPT-4o to "draw inspiration from the #Given Task# to create new tasks… same domain… similar
difficulty… Use variable names that match those in the provided task examples, such as place names,
usernames, and product names. Avoid inventing entirely new variable names." Generated tasks are then
filtered by an ORM/critic (`VLMDoubleCritic`) keeping only those whose predicted value falls **inside a
threshold band** — not too easy, not impossible. A separate `FILTER_POMPT` encodes per-site feasibility
rules.

- Exploration: curriculum over task space, not over the site graph. Consolidation: RL. Validation: ORM.
  Artifact: weights. LLM at replay: yes.
- **Verified:** yes.

---

### 13. Synapse — `ltzheng/Synapse` @ `08c3a25` (2026-01-07), ICLR 2024

Trajectory-as-exemplar prompting. Memory is built from a **fixed, human-curated** `EXEMPLAR_LIST`
(51 MiniWoB task names in `synapse/memory/miniwob/build_memory.py`), embedded with
`text-embedding-ada-002` into FAISS; `retrieve_exemplar_name` takes top-k and majority-votes the
exemplar name. Contributions are state abstraction + exemplar retrieval, not discovery.

- Exploration: none (this is the honest answer). Consolidation: none. Failure use: none.
  Validation: none. LLM at replay: yes (exemplars are prompt).
- **Verified:** yes.

---

### 14. Agent S / S2 — `simular-ai/Agent-S` @ `bffdb59` (2026-07-31)

`gui_agents/s2/core/knowledge.py::KnowledgeBase` keeps two prose stores: **narrative** (task-level)
and **episodic** (subtask-level), each an LLM summary (`summarize_narrative`, `summarize_episode`,
described as "reflection for the next round trial"), retrieved by embedding similarity and fused with
live web-search results (`knowledge_fusion`). Notably, `finalize_task()` saves **unconditionally** —
there is no success filter, so failed trajectories enter memory as reflections. Keys are the raw
task/subtask header strings; `save_episodic_memory` skips if the key already exists (no merge).

- Exploration: none. Consolidation: none (append-only, keyed by string). Failure use: implicit
  (reflection). Validation: none. LLM at replay: yes.
- **Verified:** yes.

---

### 15. Learn-by-interact (Su et al. 2025, arXiv:2501.10893) — *paper-only*

Synthesizes trajectories from documentation, then **backward construction**: derive the instruction by
summarizing/abstracting what the interaction actually did — the same move as NNetNav's retroactive
labeling and the one `long-horizon-agents.md` §3 Phase 2 already adopts. Reported up to +12.2% ICL /
+19.5% training across SWE-bench, WebArena, OSWorld, Spider2-V; backward construction alone worth up
to +14.0%. **No public repository found** (GitHub search returned nothing); everything here is
secondhand from the abstract and OpenReview listing.

---

### 16. Healenium — `healenium/healenium-web` @ `c1e4f83` (2026-03-03)

The QA world's answer to selector drift, and the only **zero-LLM healing** implementation here.

- At capture time, `SelfHealingEngine.saveElements()` stores, per locator, the element's **DOM node
  path** (`getNodePath` → `List<List<Node>>`) plus the action and current URL, into the healenium
  backend.
- On a `NoSuchElementException`, `service/HealingService.findNewLocations(paths, destination, context, engine)`
  scores candidate nodes in the *current* tree with `treecomparing.LCSPathDistance` +
  `HeuristicNodeDistance` via `PathFinder.getSortedNodes(..., 1000, scoreCap)`, then converts the best
  node to XPath/CSS and re-finds it, requiring a unique match
  (`getElementBySelectorType`, `replaceHealedElementLocator`).
- Defaults (`README.md`): `score-cap = 0.5` ("healing will be performed for new healed locators where
  probability of match with target one is >=50%"), `recovery-tries = 1`, `heal-enabled = true`,
  plus a `@DisableHealing` annotation and `backlight-healing` (draws a red border and screenshots the
  healed element).

- Exploration: n/a. Consolidation: healed locators are persisted server-side for later runs.
  Failure use: the failure *is* the trigger. Validation: uniqueness + score cap. LLM at replay: **no**.
- **Verified:** yes (code + README defaults).

---

### 17. Playwright Test — scenario matrix, retries, flakiness classification

Not a workflow synthesizer, but it already ships the scenario/perturbation vocabulary NetGent needs,
and its *tri-state* result is a better validation contract than NetGent's boolean.

- `retries` in `playwright.config.ts`; `testInfo.retry` at runtime; `test.describe.configure({retries: 2})`
  for a subset. With retries on, results are classified **passed / flaky / failed** — "flaky" = failed
  first, passed on retry.
- Per-project emulation via `use`: `viewport`, `locale`, `timezoneId`, `geolocation`, `colorScheme`,
  `permissions`, `offline`, `javaScriptEnabled`, `isMobile`, `userAgent`, plus the `devices` registry;
  overridable per file with `test.use()`.
- **Verified:** from the official docs pages (`/docs/test-retries`, `/docs/emulation`). I did **not**
  re-verify the `trace: 'on-first-retry'` option name on those pages — treat that specific string as
  unverified here.

---

### 18. Perturbation / failure-injection for web agents

- **WAREX** (arXiv:2510.03285) — *paper-only, no repo found.* A **split-TLS intercepting proxy**
  between agent and site: it terminates the client's TLS with an interception cert, opens its own
  connection to the origin, and applies "Web Failure Logic" in between. An *Injection Script* specifies
  a failure **Type** (network delay, 4xx, 5xx, JS failure, popup/overlay) and **Frequency** rules
  (exact URL, regex, k-th occurrence, first k, every k-th, random). Applied to WebArena, WebVoyager and
  REAL; reports "significant drops in task success rates". This is the cleanest published design for a
  NetGent perturbation harness — and it needs no agent or benchmark modification.
- **StressWeb** (arXiv:2604.16385) — *paper-only, abstract read.* Clean reference environments +
  structured perturbations in three families — **shifting layouts, altered interaction semantics,
  execution disruptions** — scored by deterministic multi-checkpoint evaluators. The clean/perturbed
  paired design is the right evaluation shape; the abstract does not enumerate individual perturbations
  and no repo is stated.
- **PopupAttack** — `SALT-NLP/PopupAttack`, *repo verified*. Adversarial pop-ups integrated into
  OSWorld and VisualWebArena: 86% average attack success rate, −47% task success. **Important nuance
  for NetGent:** the injection is *perception-level* — `VisualWebArena/browser_env/attack_utils.py::draw_som_for_attack_webarena`
  draws the pop-up onto the **screenshot** with PIL, and the config
  (`attack_config/intent_click_tag_OK_adv_text.json`: `{bottom, notice, attack_string, prefix, adv_text}`)
  parameterizes the rendered banner. A DOM-replaying executor like NetGent's would be unaffected by
  *this* attack; a real DOM overlay is the case NetGent must model, and that is what WAREX injects.
- **AgentHijack** (arXiv:2605.25707), *secondhand from search results only* — "computer use agent
  robustness to common environment corruptions", i.e. corruption rather than adversarial robustness.
  Not read; listed for follow-up.
- **testRigor / commercial self-healing suites** — *unverified, secondhand.* Vendors advertise
  AI-based locator healing; no source available. Healenium is the open, inspectable member of this
  family and should be the reference.

---

## Comparison table

| System | Exploration strategy | What is recorded | Multi-run consolidation | Failure use | Validation of artifact | LLM at replay? | Artifact | Verified |
|---|---|---|---|---|---|---|---|---|
| **ReUseIt** | 5 runs × (original + 3 LLM variations) — attribute/category/website | agent messages; + plan for successes | one LLM call over both pools | **yes** — failures → condition checks | none | **yes** (agent + every guard) | prose workflow | paper-only |
| **AWM** | none (benchmark task list) | think/action pairs from logs | template-id dedup + abstract-trajectory dedup; one LLM induction call | no (successes only) | none | yes (workflow = system-prompt text) | prose/pseudo-code workflows | code |
| **SkillWeaver** | explore/practice schedule, utility-ranked; return-home drift control | trajectory + Playwright trace | one LLM rewrite of a Python module, context filtered to *tested* skills | yes — locator recoveries annotate source for rewrite | **yes** — execute with generated args, no exception, no recovery | skill: no; caller: yes | typed Python APIs | code |
| **workflow-use** | single run (recording or prompt) | selector_map snapshot per action + `[ELEMENT:"…"]` tags | none | no (agent fallback commented out) | LLM static review (default off) + per-step deterministic verifier at run time | mostly no; extract/agent/semantic steps yes | typed JSON/YAML steps | code |
| **Skyvern** | planner with `required_subgoals` + `complete_criterion` | all blocks/tasks/actions in DB | **yes** — progressive per-block/per-branch script caching across runs | **yes** — script-reviewer agent turns fallback episodes into new script versions | AST validators + param guard | **only on failure** (`ai_element_fallback`, max_steps 5) | generated Python script | code |
| **Stagehand** | none | actions per act() call | none (per-call cache) | implicit (stale entry replaced) | none | no on hit, yes on miss | cached action list, keyed on CDP a11y tree | code |
| **Lumen** | none | semantic step history | `add()` merges by (domain, trigger), keeps shorter | no | no | no on hit, yes on miss | prose workflow + action cache | code |
| **Magentic-UI** | none | chat messages | one LLM call per saved plan | no | none | yes | prose plan | code (tag v0.1.0) |
| **NNetNav** | undirected policy + `early_stop` (max steps / k parse fails / k repeats) | (s, a, s′) changelogs | none (dataset) | pruned by reward model | reward model | yes (artifact = weights) | SFT dataset | code |
| **Explorer** | one pass per URL; goal refined each step | screenshots + a11y + actions | none | dropped by verifier | VLM verifier | yes | SFT dataset | code |
| **Go-Browse** | **site graph BFS** + per-node task proposal + feasibility filter | trajectories + reach `prefixes` per node | none | **failures kept and released** | strong-model + VLM judge | yes | dataset → weights | code |
| **PAE** | proposer from site name/demos | trajectories | RL | negative reward | VLM evaluator | yes | policy weights | code |
| **WebRL** | **failure-seeded curriculum**, critic-band filtered | trajectories | RL | **yes — failures seed next tasks** | ORM critic | yes | policy weights | code |
| **Synapse** | none (curated exemplars) | human trajectories | none | no | none | yes | prompt exemplars + FAISS | code |
| **Agent S2** | none | narrative + episodic summaries | append-only by string key | implicit (reflection, saved unconditionally) | none | yes | prose memory | code |
| **Learn-by-interact** | doc-driven synthesis + backward construction | trajectories | none stated | not stated | filtering | yes | data → ICL/weights | paper-only |
| **Healenium** | n/a | DOM node path per locator | healed locators persisted for later runs | failure is the trigger | uniqueness + `score-cap 0.5` | **no** | healed selectors | code |
| **Playwright Test** | project matrix (viewport/locale/tz/offline/devices) | traces, retries | n/a | retry → **flaky** classification | n/a | **no** | test suite | docs |
| **WAREX** | n/a (proxy) | n/a | n/a | injects failures | n/a | n/a | injection scripts | paper-only |
| **NetGent v2 (today)** | 1 run (`--runs`/`--variation` documented, **not implemented**) | trajectory steps incl. `error` | none | **none** — `compile_trajectory` filters `s.error is None` | **yes — zero-LLM replay** (`validate_workflow`) | **no, by construction** | typed NFA (pydantic) | this repo |

---

## Alternatives to ReUseIt — ranked by relevance to NetGent

1. **Skyvern script generation + caching + script-reviewer** — the only production system that
   consolidates *many runs* into *one deterministic artifact*, discovers branches progressively, and
   feeds replay failures back into the artifact. Everything NetGent wants, minus the formalism.
2. **workflow-use** — the closest artifact shape (typed steps, priority selector ladder, per-step
   deterministic post-conditions, pattern-based parameters). Read `step_verifier.py` before writing
   NetGent's condition synthesizer.
3. **SkillWeaver** — the discipline model: an artifact is not in the library until it has *executed*
   with generated arguments and produced no exception and no recovery.
4. **Go-Browse** — the systematic exploration algorithm (graph over pages, propose → feasibility-filter →
   sample), which ReUseIt has no analogue of and NetGent's discovery step needs.
5. **Stagehand cache** — the state-identity question answered concretely: key the artifact on the
   accessibility tree with a similarity threshold, replay, and treat failure as a cache miss.
6. **Healenium** — proof that useful healing can be purely structural, i.e. legal under NetGent's
   zero-LLM-at-replay rule.
7. **AWM** — the canonical trace→workflow induction, plus the cheapest dedup key in the field
   (`get_abstract_trajectory`). Its ceiling is that the artifact is prompt text and failures are discarded.
8. **Lumen** — a 200-line reference implementation of workflow memory + action cache + deterministic
   post-action verification; fastest thing to read end-to-end.
9. **WebRL** — failure-seeded curriculum: the right way to spend run N+1 after run N failed.
10. **NNetNav** — per-step state changelogs and retroactive prefix labeling; also the cheapest
    loop/stall detector (`early_stop`).
11. **WAREX / StressWeb / PopupAttack** — the perturbation vocabulary and injection mechanism for
    scenario coverage.
12. **Explorer / PAE** — task-proposal prompt engineering worth copying verbatim for `--variation`.
13. **Magentic-UI plan learning** — only as ReUseIt's substrate; pin `v0.1.0` or it is gone.
14. **Synapse / Agent S2 / Learn-by-interact** — retrieval-and-prompt memory; conceptually upstream,
    operationally not applicable to a compiled artifact.

---

## Design recommendations for NetGent's discovery step

Each maps to the NFA formalism, with cost and the evidence behind it.

### D1 — Mint a target-state condition from the *action type*, always (no LLM, no extra runs)
`compile_trajectory` currently gives same-page steps `conditions=[]`, so a `fill` that silently no-ops
replays "successfully". Add a rule table from action → target-state triggers, exactly as
workflow-use's `StepVerifier._get_verification_checks` and Lumen's `ActionVerifier.verify` do
independently: `goto` → `url_matches` + load; `click` → *something changed* (URL, or a
`selector_visible`/`selector_hidden` pair drawn from the observed DOM diff); `fill` → the field holds
the value; `select` → the option is selected; `press`/`scroll` → observed diff.
**Schema impact:** one new trigger type (`value_equals` over an input) — the current four
(`url_matches`, `title_contains`, `selector_visible`, `selector_hidden`) cannot express "the field
contains X". **Cost:** ~1 day; no extra exploration. **Evidence:** two independent implementations
converge on this table; ReUseIt spends ~20 LLM runs to derive weaker versions of the same checks.

### D2 — Implement `--runs N` / `--variation` as a *scenario matrix*, not just repeats
Adopt ReUseIt's attribute/category/website taxonomy for *task* variation (its Appendix C.1 prompt is
reusable, and PAE's proposer constraints — 3–7 steps, objectively checkable, no login — are a better
feasibility filter), **and** add an orthogonal *environment* axis that ReUseIt has no notion of:
fresh vs warmed profile (`storage_state`), viewport, `locale`/`timezoneId`, `colorScheme`, offline/throttle.
`BrowserSession.__init__` today takes only `headless` and `stealth`; give it a `ScenarioProfile` whose
fields mirror Playwright's per-project `use` keys so the vocabulary is one everyone already knows.
**Cost:** N× wall-clock (ReUseIt: 15–53 min per family) + a small session refactor. **Evidence:**
Playwright's emulation keys; Lumen's `viewportMismatch` (a cached coordinate action is invalid across
viewports); WAREX/StressWeb's finding that clean benchmarks overestimate robustness.

### D3 — Consolidate by **state-keyed graph merge**, not by asking an LLM to merge prose
Merge runs in pure code: canonicalize each run into (state guard conjunction → edge) pairs; union the
states by guard equality after value-abstraction; an edge observed in *every* run joins the core
`control_sequence`; an edge observed in *some* runs becomes a `Branch` arm keyed on the state whose
guard distinguishes them (cookie wall present/absent, logged-in/out). Use AWM's
`get_abstract_trajectory` (action name + first argument, joined) as the cheap pre-dedup key.
**Cost:** the merge pass is the single largest new component (~1–2 weeks) but it is *pure code*, which
is the whole point. **Evidence:** Skyvern's progressive branch caching does exactly this by
accumulation (run 1 caches branch A, run 2 branch B) and gates `run_with: code` on full coverage —
NetGent can do it as one offline pass instead, and can *know* when coverage is incomplete.

### D4 — Failures are where guards and ε-transitions come from
Stop discarding them: `compile_trajectory`'s `s.error is None` filter throws away the most informative
steps. Two concrete rules, both zero-LLM:
- A step that failed in run *i* and succeeded in run *j* after an extra dismiss/accept action ⇒ mint a
  **pop-up state** (guard = the overlay's `selector_visible`) reached by a `noop` **ε-transition**, a
  dismiss edge back, and a `Branch` arm that runs it only when the guard holds.
- A step that failed in run *i* at the same state where run *j* succeeded ⇒ the state's guard is
  **under-specified**; tighten it with a conjunct from the diff between the two observations.
**Cost:** trajectory records already carry `error`; needs the D3 merge to compare runs.
**Evidence:** ReUseIt's central claim (failures locate the guard; successes supply the escape hatch)
and its ablation; PopupAttack's 86% ASR shows the interruption class is dominant — with the caveat that
its injection is drawn on the screenshot, so a *DOM* overlay is the case NetGent must actually model.

### D5 — Checkpoint by **replay**, not by `goto` (and know why)
`long-horizon-agents.md` §3 P3 is right, and Go-Browse is the counter-example that proves it:
`reset_env_to_node` = `env.reset(); goto(url)` works there because WebArena state is URL-addressable.
NetGent's traffic workflows (logged-in, cart-filled, player started) are not, so exploring an
alternative from state S means replaying the already-frozen prefix deterministically. Free bonus: every
checkpoint is a regression test of the prefix — a prefix that will not replay is a compile-time bug
found at compile time. **Cost:** wall-clock only, zero tokens. **Evidence:** Go-Browse (what works when
state is URL-addressable), Skyvern's `run_signature` (a block is only reusable if it can be invoked
standalone).

### D6 — Locator robustness: a priority ladder at compile time, structural healing at replay
(a) Emit *ranked alternatives* per transition rather than one `LocatorStep` chain — workflow-use's
`SelectorGenerator` orders 8 strategies (exact text = 1 … absolute XPath = 8) and `element_finder`
walks them recording a `StrategyAttempt` per try. (b) Store the element's DOM **node path** in the
artifact and, on replay failure, heal Healenium-style: best-match node by `LCSPathDistance` +
`HeuristicNodeDistance` with a `score-cap` (their default 0.5), requiring a unique re-find. Both are
zero-LLM, so rule 2 survives. Log every heal as a **drift signal** rather than silently succeeding.
**Cost:** schema addition (`alternatives`, `node_path`) + a tree-distance implementation (~1 week).
**Risk:** healing to the wrong element; the score cap and uniqueness check are the mitigations, and the
run record must show it happened.

### D7 — Recovery is a typed `Branch` arm, never a retry and never a sentence
ReUseIt's ablation (50.1% → 70.1% at fixed retry budget) says the *content* of the recovery is what
matters, and their explanation — "agents were likely to repeat errors they made in their first
attempts" — is exactly why re-firing a failed edge is worthless. So: a recovery is an alternate
edge (or short edge sequence) selected by the observed state's guard. Bound it. The field has
converged on a small number: ReUseIt 3 retries, SkillWeaver 5 locator attempts, Skyvern
`ai_element_fallback(max_steps=5)` with `max_ai_fallbacks=10` per call. Use 3, and make exhaustion a
hard failure with a named edge, not a silent skip (`Branch` with no `else_` already behaves this way).
**Cost:** design work on the repair spec; no new schema (`Branch`/`BranchArm` exist).

### D8 — Validation must sweep the matrix and report **flaky**, not just pass/fail
Extend `validate_workflow(param_sets)` to `param_sets × scenarios` (D2) and change the contract:
a workflow that passes 2 of 3 replays is **flaky**, not validated — Playwright's tri-state
(passed / flaky / failed) is the right vocabulary and NetGent's `ValidationReport.validated`
(`all(r.success)`) currently collapses it. Then add one adversarial arm: replay with a synthetic DOM
overlay injected before a chosen edge (WAREX's popup/overlay injection, applied locally via
`page.add_style_tag`/`add_script_tag` rather than a TLS proxy) and assert the ε-branch from D4 fires.
**Cost:** small in the validator; the injection harness is ~1 day for the overlay case, more if network
faults are wanted. **Evidence:** WAREX (mechanism + frequency rules), StressWeb (clean/perturbed paired
design with multi-checkpoint evaluators), Playwright (result taxonomy).

### D9 — Add a compile-time *rejection* validator, not just a schema
SkillWeaver's `check_code` is instructive: the LLM's output is rejected for blanket `try/except`,
`while` loops, missing docstrings, `page.click(selector)` instead of `locator.click()`, CSS selectors
instead of AX-tree selectors — with the violation list fed back for up to 10 retries. NetGent's pydantic
models already do the typing; add the *semantic* rules as `model_validator`s: no state with empty
conditions immediately after a state-changing action (D1); no `url_matches` pattern containing an
un-parameterized sample value (ReUseIt's value-agnostic constraint, which
`_base_url` + `re.escape(base)` currently violates); every `Branch` arm's `when` state must have a
guard that is *distinguishable* from its siblings. **Cost:** ~2 days. **Evidence:** SkillWeaver;
ReUseIt Appendix C.2's Important Constraint.

### D10 — Seed the next exploration round from the failures of the last
When validation fails at edge *e*, do not re-run the identical task: generate the next round's
variations *from the failure* — same page, different value; the branch that was not taken. That is
WebRL's `gen_task.py` loop (failed instructions → seed prompt → new tasks → critic-band filter), and it
is strictly cheaper than ReUseIt's fixed 20-run budget because runs are spent where the artifact is
weak. NetGent's critic is free and non-probabilistic: the replay itself. **Cost:** bookkeeping in the
orchestrator + N× wall-clock. **Evidence:** WebRL; SkillWeaver's `rate_practice_utility` (practice what
is least verified) is the same idea applied to a skill library.

**One thing to deliberately not adopt:** the escape hatch. Skyvern, Stagehand and Lumen all keep an
LLM on the replay path for failure cases, and it is the right call for their products. NetGent's
product is *zero-LLM replay*; the same failures must be resolved into `Branch` arms at compile time or
be reported as drift. The cost column is where NetGent wins by construction — and it is the column
ReUseIt never reports.

---

## Verification notes

**Confirmed by reading source** (shallow clones taken 2026-08-21; commit shown):

| Repo | Commit | What I read |
|---|---|---|
| `zorazrw/agent-workflow-memory` | `8c0ff8c` (2025-12-22) | `webarena/{induce_prompt,induce_rule,pipeline}.py`, `prompt/instruction.txt`, `workflow/shopping.txt`, `agents/legacy/agent.py`, `mind2web/{offline,online}_induction.py`, `mind2web/workflow/retrieve.py` |
| `OSU-NLP-Group/SkillWeaver` | `f2a63d6` (2025-04-14) | `explore.py`, `knowledge_base/{knowledge_base,code_verification,check_success}.py`, `environment/patches.py`, `agent.py` |
| `browser-use/workflow-use` | `891267b` (2026-07-29) | `healing/{service,validator,selector_generator}.py`, `workflow/{service,step_verifier,element_finder,variable_identifier}.py`, `builder/prompts.py`, `schema/views.py` |
| `Skyvern-AI/skyvern` | `888348d` (2026-08-21) | `forge/prompts/skyvern/task_v2.j2`, `core/script_generations/{CLAUDE.md,generate_script.py,script_validators.py,skyvern_page.py,skyvern_page_ai.py,real_skyvern_page_ai.py}`, `services/script_reviewer_v3/{cohort,postrun,skills/*}.py` |
| `browserbase/stagehand` | `a21633d` (2026-08-21) | `packages/extension/services/{cacheService,actService}.ts`, `packages/docs/v2/best-practices/agent-fallbacks.mdx`, CHANGELOG |
| `omxyz/lumen` | `b1ad26a` (2026-03-29) | `src/memory/workflow.ts`, `src/loop/{action-cache,action-verifier,perception}.ts`, README |
| `microsoft/magentic-ui` | HEAD `d3c9d13` (2026-07-23) + tag `v0.1.0` | `learning/{learner,memory_provider}.py`, `backend/web/routes/plans.py` at the tag; confirmed `learning/` absent at HEAD |
| `MurtyShikhar/NNetNav` | `9d64248` (2025-04-16) | `src/nnetnav_utils.py` (`early_stop`, `TrajectoryLabeler`, `LanguagePruning`), README |
| `OSU-NLP-Group/Explorer` | `209bc48` (2026-02-17) | `traj_gen/README.md` (pseudocode), `trajectory_verifier.py`, `task_refiner_agent.py` |
| `ApGa/Go-Browse` | `8742490` (2025-10-08) | `webexp/explore/core/{graph,node,trace,episode}.py`, `webexp/explore/algorithms/web_explore.py` |
| `amazon-science/PAE` | `f40715b` (2024-12-30) | `scripts/propose_tasks_from_names_webvoyager.py`, `environment/webgym/utils_eval.py` |
| `THUDM/WebRL` | `fa8439e` (2025-06-06) | `scripts/gen_task.py` (seed prompt, ORM band filter, FILTER_POMPT) |
| `ltzheng/Synapse` | `08c3a25` (2026-01-07) | `synapse/memory/miniwob/build_memory.py` |
| `simular-ai/Agent-S` | `bffdb59` (2026-07-31) | `gui_agents/s2/core/knowledge.py` |
| `healenium/healenium-web` | `c1e4f83` (2026-03-03) | `SelfHealingEngine.java`, `service/HealingService.java`, README defaults |
| `SALT-NLP/PopupAttack` | (cloned 2026-08-21) | `VisualWebArena/browser_env/attack_utils.py`, `attack_config/*.json`, README |
| `netgent-dev` v2 (this repo) | `eugene/v2-scaffold` | `schema/{workflow,control,triggers,actions}.py`, `agent/generator/compiler.py`, `agent/validator/validate.py`, `browser/session.py` |

**Confirmed from official docs, not source:** Playwright `retries` / `testInfo.retry` /
`test.describe.configure({retries})` / passed-flaky-failed classification (`playwright.dev/docs/test-retries`);
Playwright emulation keys `viewport, locale, timezoneId, geolocation, colorScheme, permissions, offline,
javaScriptEnabled, isMobile, userAgent` + `devices` (`playwright.dev/docs/emulation`).

**Paper-only / secondhand — flagged, not verified in code:**
- **ReUseIt** — no repository exists; all of §0 is from the paper (see `reuseit.md` for the full read).
- **Learn-by-interact** (arXiv:2501.10893) — abstract and OpenReview listing only; GitHub search found
  no repository.
- **WAREX** (arXiv:2510.03285) — abstract + search-result summary of the proxy design; no repo found.
  The injection-type and frequency-rule lists are as reported, not as read.
- **StressWeb** (arXiv:2604.16385) — abstract only; the three perturbation families are the abstract's
  own wording, individual perturbations are not enumerated there.
- **AgentHijack** (arXiv:2605.25707) — search-result snippet only; not read.
- **testRigor and other commercial self-healing suites** — no source; claims are vendor-side.
- **Stagehand `AgentReplayStep`** — the identifier named in the brief does **not** exist at
  `a21633d`; the equivalent behaviour lives in `cacheService.withCache` + `actService.replayCachedActions`.
- **Skyvern progressive/branch caching semantics** — taken from the repository's own
  `core/script_generations/CLAUDE.md` design doc plus the codegen/validator sources; I did not trace the
  full `generate_script_if_needed` / `blocks_to_update` control flow in `forge/sdk/workflow/service.py`.
- **workflow-use** — the brief's "no validation step" was true of earlier versions; at `891267b` an
  LLM `WorkflowValidator` exists (default off) and a deterministic `StepVerifier` runs at execution time.
