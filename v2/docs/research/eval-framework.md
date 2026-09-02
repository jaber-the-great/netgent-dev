# Eval framework — measuring the compile pipeline across commits (`netgent eval bench`)

Research + spec for the one measurement framework the pipeline is missing. Written against the
pipeline as it stands on [`pr8-plus-scaffold`](../../src/netgent/agent/orchestrator.py)
(`plan → explore×N (parallel) → verify → merge → compile → replay_check`) and the closed-loop
`triage → plan_next → rounds` extension being built on `v2/closed-loop-rounds`.

> Source links below resolve on `eugene/v2-scaffold` **except** `agent/generator/merge.py`,
> `agent/replay.py` and `agent/store.py`, which exist only on `pr8-plus-scaffold`
> (`git show pr8-plus-scaffold:v2/src/netgent/agent/…`). Same for the `media_playing` trigger.

## Summary (10 lines)

1. The problem is not "we have no evals" — it is that every number we own scores **one stage** of a
   six-stage pipeline, so a change that helps explore and hurts merge reads as noise.
2. The field's answer is uniform: a **versioned task suite** whose success is decided by
   **programmatic evaluators over final page state**, not by a judge (WebArena, Skyvern, SWE-bench).
3. The product metric for NetGent is not exploration success — it is **replay pass^k on value sets
   the compiler never saw**, using τ-bench's combinatorial pass^k (`C(c,k)/C(n,k)`).
4. Judges stay advisory and get **scored against page truth** every run: precision/FP-rate is the
   number, because judge error is one-directional (AgentRewardBench: best judge ≈70% precision).
5. The closed loop is measured by making **budget an axis, not a footnote**: every quality number is
   reported at a fixed round budget, plus `tokens per accepted artifact`.
6. Regression = a **paired, per-task** difference whose CI excludes zero (Miller 2024, rec. 4), or
   any negative control flipping, or any golden artifact failing zero-LLM replay.
7. Two broken sweep fixtures (`ember`, `shadow-dom`) become **negative controls**: any stage that
   calls them achieved is a scored false positive, exactly as `agent-verification.md` §6.5 demands.
8. Mechanics reuse what exists: `TriggerEngine.holds` for postconditions, `replay_check` for the
   metamorphic gate, `generalized.json` for generalization metrics, `matrix.py` for the report.
9. Results are **committed JSON rows under `evals/results/bench/<commit>/`** — the practice that
   distinguishes credible from unsupported numbers, and the reason no hosted platform is adopted.
10. Smallest trustworthy slice this week: local-fixture tier, 3 tasks × 3 runs × 3 held-out value
    sets → one number, `replay pass^3`, plus the two negative controls.

---

## 0. What is actually broken

The team's statement — *"we could SEE success going up while iterating by hand; now we cannot measure
whether a change helps or hurts"* — is a precise description of a measurement gap, not a vague one.
Three things changed:

**(a) The unit of success moved.** When the pipeline was `explore → compile`, exploration success was
a fair proxy for product success. It is not any more. `merge_trajectories` can consume three achieved
trajectories and still emit a workflow that replays for exactly one value set — the live example in
`dream-theater.trajectories.example/generalized.json` has 22 aligned columns of which **7 aligned, 6
dropped, 4 param, 2 target-varies, 2 interrupt, 1 value-diverges**, and five warnings of the form
*"column 5: click targets differ across runs and match no planned value — kept run 1's selector;
replay with other values may not find it"*. Every one of those is a place where exploration succeeded
and the product degraded. Nothing we measure today sees it.

**(b) Nothing is scored per stage.** What exists:

| Existing eval | What it scores | Where |
|---|---|---|
| `netgent eval dataset` | zero-LLM replay of *committed* artifacts on local fixtures; `record.success` | [`evals/dataset.py:89`](../../src/netgent/evals/dataset.py) — the CI gate, [`ci.yml:55`](../../../.github/workflows/ci.yml) |
| `netgent eval observation` | observation-backend metrics, no LLM | [`evals/observation.py`](../../src/netgent/evals/observation.py) |
| `netgent eval interact` | action-layer dispatch/verify, no LLM | [`evals/interact.py`](../../src/netgent/evals/interact.py) |
| `netgent eval stress sweep\|challenge` | **explorer only**, page-verified, with per-run tokens | [`evals/stress.py`](../../src/netgent/evals/stress.py) |
| `netgent eval matrix` | cost table across arms | [`evals/matrix.py:54`](../../src/netgent/evals/matrix.py) |
| `NETGENT_JUDGE=1` | judge precision/recall vs page truth, printed | [`evals/stress.py:193-203`](../../src/netgent/evals/stress.py) |

The gap is exactly the middle of the pipeline: **plan, merge, compile, replay** have no eval at all,
and `dataset` measures *artifacts we hand-committed*, not artifacts the pipeline produced today.

**(c) The closed loop makes low scores invisible.** With `triage → plan_next → rounds`, an artifact
that needed 1 round yesterday and 4 rounds today reports the same success. Budget absorbs the
regression. This is the single most important thing the framework must not allow.

---

## 1. Survey — how the field structures evals and tracks regressions

Read from current sources (repository contents fetched 2026-09-02 unless noted).

### 1.1 Task suites with programmatic evaluators — WebArena / VisualWebArena

WebArena's 812 task configs are **one JSON object per task**, and the evaluator is selected by a list
of `eval_types`. Verbatim from
[`config_files/test.raw.json`](https://raw.githubusercontent.com/web-arena-x/webarena/main/config_files/test.raw.json)
(task 0) and [`config_files/examples/2.json`](https://raw.githubusercontent.com/web-arena-x/webarena/main/config_files/examples/2.json):

```json
{ "sites": ["shopping_admin"], "task_id": 0, "require_login": true,
  "storage_state": "./.auth/shopping_admin_state.json", "start_url": "__SHOPPING_ADMIN__",
  "intent_template": "What is the top-{{n}} best-selling product in {{year}}",
  "instantiation_dict": {"n": 1, "year": 2022},
  "intent": "What is the top-1 best-selling product in 2022",
  "require_reset": false,
  "eval": { "eval_types": ["string_match"],
            "reference_answers": {"exact_match": "Quest Lumaflex™ Band"},
            "reference_url": "", "program_html": [] },
  "intent_template_id": 279 }
```

```json
{ "eval": { "eval_types": ["url_match"],
            "reference_url": "https://russmaxdesign.github.io/exercise/#link-two",
            "program_html": [{"url": "", "required_contents": []}] },
  "reference_action_sequence": { "action_set_tag": "playwright",
    "action_sequence": ["page.get_by_role(\"navigation\").get_by_role(\"link\", name=\"Classification\").click()", "page.stop(\"Wilson and Reade\")"] } }
```

[`evaluation_harness/evaluators.py`](https://raw.githubusercontent.com/web-arena-x/webarena/main/evaluation_harness/evaluators.py)
implements exactly three: `StringEvaluator` (`exact_match` / `must_include` / `fuzzy_match`, the last
an LLM call), `URLEvaluator` ("GOLD in PRED" over base path + query params), `HTMLContentEvaluator`
(navigate to `program_html[i].url`, run a JS `locator`, check `required_contents`, with optional
`prep_actions`).

**Four things to steal.** (i) A task is a **file**, not code — `intent_template` +
`instantiation_dict` is exactly our `task` + `params`/`variations`. (ii) Success is a **list** of
evaluators ANDed together, so partial specs are expressible. (iii) `program_html` proves the pattern
of *"navigate somewhere else and check the state you left behind"* — which is what a postcondition on
a compiled NFA needs. (iv) `require_reset` is an explicit per-task field; we need the same for live
sites. **One thing to refuse:** `fuzzy_match` puts an LLM inside the oracle. AgentRewardBench (§1.4)
is the reason not to.

### 1.2 Experiment records and reproducibility — BrowserGym / AgentLab

[AgentLab's README](https://github.com/ServiceNow/AgentLab/blob/main/README.md) makes the *Study* the
unit: `make_study(benchmark=…, agent_args=[…], comment=…)`, materialized under `AGENTLAB_EXP_ROOT`,
one directory per (benchmark, agent, task, seed), each holding `ExpArgs` (the input config) and
`ExpResult` (screenshots, action trace, per-step records). The Study records *"benchmark version,
package version, commit hash, os version, and time stamp"*; `study.append_to_journal()` appends to a
shared `reproducibility_journal.csv`; a `ReproducibilityAgent` *"re-execute[s] the same action
sequence on the same task seeds"*; `agentlab-xray` is the trace viewer; and incomplete runs are
recovered with `Study.load(...)`, `study.find_incomplete(include_errors=True)`, `study.run()`.

The [BrowserGym paper](https://arxiv.org/html/2412.05467v1) names five variance sources verbatim:
*"Different versions of Playwright or any package in the software stack could influence the behavior
of the benchmark or the agent"*; *"even for a fixed version, a commercial LLM may be updated"*; live
websites where *"the experience may change depending on the country or region"*; stochastic agents
(*"LLMs are non-deterministic, but this is less concerning since it is independent and identically
distributed (IID) noise"*); and non-deterministic tasks. Results are reported with standard errors
(e.g. `69.8 ±1.8`).

**Take:** the per-run record must carry commit hash + package versions + model id + benchmark
version, and the runner must support *resume the incomplete ones* rather than *rerun everything* —
LLM runs cost money and a partial arm is the normal failure mode. **Refuse:** a separate viewer
binary; we already have `netgent trajectory … --html`.

### 1.3 Reliability over repeated trials — τ-bench pass^k

τ-bench's [`tau_bench/run.py:194-203`](https://github.com/sierra-research/tau-bench/blob/main/tau_bench/run.py)
is the whole definition:

```python
pass_hat_ks: dict[int, float] = {}
for k in range(1, num_trials + 1):
    sum_task_pass_hat_k = 0
    for c in c_per_task_id.values():
        sum_task_pass_hat_k += comb(c, k) / comb(num_trials, k)
    pass_hat_ks[k] = sum_task_pass_hat_k / len(c_per_task_id)
```

i.e. with `n = num_trials` and `c` successes for a task, `pass^k = mean_over_tasks C(c,k)/C(n,k)` —
the probability that **all k** of a random k-subset of trials succeeded. Not pass@k (any-of-k);
the opposite. The CLI pins `--seed 10`, `--temperature 0.0`, `--num-trials`, `--task-split`,
`--max-concurrency`.

**Take:** pass^k is the correct shape for NetGent's product claim, because a compiled workflow is
sold as *deterministic*: "it worked once in five" is a failure, not a partial success. Report the
whole `k = 1..n` curve; a flat curve means reliability, a curve that collapses at k=2 means we are
reporting luck.

### 1.4 Judges, and calibrating them — Online-Mind2Web, AgentRewardBench, browser-use

**WebJudge** ([Online-Mind2Web](https://github.com/OSU-NLP-Group/Online-Mind2Web), 300 tasks over
136 websites) is three steps: identify **key points** required by the task, select **key screenshots**
from the trajectory, then judge the outcome from task + key points + key screenshots + action history.
Reported agreement with human labels: 83.6% (GPT-4o), 85.7% (o4-mini, 3.8% success-rate gap vs human),
87% (WebJudge-7B). The v2 submission schema fields are `schema_version`, `task`, `task_id`,
`agent_final_answer`, `reference_length`, `action_history`.

**AgentRewardBench** ([arXiv:2504.08942](https://arxiv.org/abs/2504.08942)) is the calibration set:
1302 expert-annotated trajectories over 5 benchmarks and 4 LLMs, annotators answering **success /
side-effect / repetition-cycle** with 89.3% inter-annotator agreement on success. Two findings that
should govern our design: the best LLM judges reach only **≈70% precision** (GPT-4o 69.8%), and
**rule-based evaluators underreport** — WebArena success 16.7 pp lower, VisualWebArena 18.5 pp lower
than expert judgment.

That pair is the whole argument for our arrangement: page-derived truth is *conservative* (it misses
real successes) while judges are *permissive* (they invent them). NetGent already chose conservative
— [`sweep.py:72 _form_succeeded`](../../src/netgent/evals/sweep.py) — and should keep it, while
**measuring the judge against it** rather than replacing it.

**browser-use's [`benchmark`](https://github.com/browser-use/benchmark) repo** (BU Bench V1 = 100
tasks, V2 = 200 tasks, Stealth Bench V1 = 71 tasks) is the most instructive current harness:

- Task JSON fields are minimal: `task_id`, `confirmed_task`, `category`, `answer`.
- Task sets ship **encrypted** (`BU_Bench_V1.enc`, Fernet keyed by the suite name) and the README
  says plainly: *"The task set is stored in base64 encoding to prevent data contamination in LLM
  training"*, and *"`run_data/` traces include decrypted task text, ground truth, model outputs, and
  screenshots. They are gitignored for local verification only."*
- `run_eval.py` records exactly three cost columns per task — `steps`, `duration`, `cost` — and a
  run-level `total_steps`/`total_duration`/`total_cost`.
- `findings_judge.py` (BU Bench V2) is the most disciplined judge design in the survey, and its
  docstring states the separation we want: *"The judge emits one finding per rubric item (met /
  violated / not_assessable, each with evidence) and never emits a score. Valuation happens in code
  from the task's weights, so re-weighting a rubric never requires re-judging a run."* Its `score()`
  adds three mechanisms worth copying wholesale:
  - `not_assessable` **earns nothing** — *"it means the evidence was unreadable, which is not partial
    credit"*;
  - duplicate findings resolve **worst-wins** (`met=0 < not_assessable=1 < violated=2`), so *"a stray
    second 'met' can never overwrite a 'violated'"*;
  - a **canary tripwire**: every rubric carries a token absent from the task text, and any agent text
    reproducing it zeroes the score deterministically, independent of the LLM.
  - the structured-output enum is pinned to *this* task's item ids, so *"an id outside the rubric
    fails schema validation rather than scoring zero unnoticed."*

**Take:** the judge never sees the weights and never emits the number; code does the arithmetic from
a frozen rubric. That is the same rule as our "generator is pure code" — and it means a rubric change
never requires re-running a judge.

### 1.5 Harness shape — Skyvern, Stagehand

**Skyvern** keeps evals as committed data + scripts:
[`evaluation/datasets/webvoyager_tasks.jsonl`](https://github.com/Skyvern-AI/skyvern/tree/main/evaluation/datasets),
a `WebVoyagerTestCase` pydantic model (`group_id`, `id`, `url`, `question`, `answer`, `is_updated`,
`max_steps`), a `webvoyager_outdated_tasks.jsonl` for tasks the live web has broken, and
**per-site results committed as markdown** (`evaluation/results/webvoyager-Allrecipes.md`, …). The
`is_updated` / `outdated` split is the honest way to handle live-site rot, and the committed
per-site markdown is the same instinct as our `evals/results/`.

**Stagehand** ([`packages/evals`](https://github.com/browserbase/stagehand/tree/main/packages/evals))
adds the operational layer: tasks are **auto-discovered** from `tasks/bench/<category>/` with *"no
registration step"*; `evals.config.json` pins the defaults `{"env":"local","trials":3,
"concurrency":10}` and per-benchmark `limit: 25`; run targets are tiers/categories/tasks/benchmark
shorthands (`evals run b:webvoyager -l 10`); `--preview` *"prints the resolved plan and exit — no
browser, no LLM calls"*; and `scoring.ts` is three functions — `exactMatch`, `passRate`, `errorMatch`.
Braintrust is optional: *"Runs stream into Braintrust when `BRAINTRUST_API_KEY` is set; otherwise a
local summary prints to stdout."* This is the finding [`langchain-evals.md`](langchain-evals.md) §3
already recorded (1 of 32 surveyed repos uses a platform, optionally, for reporting only) — verified
again here and unchanged.

**Take:** trials default to 3 (matching our own A/B convention), concurrency is a first-class flag,
and `--preview` is cheap insurance against paying for a mis-specified sweep. `errorMatch` as a
*separate* score is worth copying: infra failure must not be counted as an agent failure.

### 1.6 Task-spec conventions — Inspect, Harbor, and the `eval-engineering` skill

[Inspect](https://inspect.aisi.org.uk/tasks.html) makes a Task *"a recipe for an evaluation consisting
minimally of a dataset, a solver, and a scorer"*, parameterized by function arguments overridable at
the CLI (`-T`), with `epochs` = *"epochs to run for each dataset sample"* — i.e. repetitions are part
of the task spec, not the invocation.

The installed **[`eval-engineering`](../../../.claude/skills/eval-engineering/SKILL.md)** skill is the
most directly applicable source, and several of its rules resolve open questions for us:

- **The Verifier definition** ([`references/verifier-design.md`](../../../.claude/skills/eval-engineering/references/verifier-design.md)):
  *"A Verifier decides success from evidence independent of the agent's claim. Start with one
  sentence: `Pass iff <observable successful outcome>`."* And: *"Prefer programmatic checks… Use tool-call
  records only when final state cannot prove a required action… Never trust an agent-written action
  list, a service success flag, or an Environment helper that already decides success."*
- **Judges are last, not first**: *"Use an LLM judge only after code has settled objective facts…
  Pin and record the judge model."* And *"A judge timeout, malformed response, missing evidence, or
  credential error is an infrastructure error, not an agent failure."*
- **The decision-boundary fixture table** — the single most useful artifact in the skill for us:

  | Fixture | Expected result |
  |---|---|
  | Known-good result | Pass |
  | Different but valid result | Pass |
  | Realistic wrong result | Fail |
  | Shortcut or reward hack | Fail |
  | Prohibited collateral change | Fail |
  | Missing or corrupt evidence | Infrastructure error |

- **Failure classification** ([`references/calibration.md`](../../../.claude/skills/eval-engineering/references/calibration.md)):
  every non-pass is labelled *Capability / Missing information / Harness / Environment / False
  rejection / False acceptance / Leakage / Infrastructure*, and *"First repair all non-agent causes
  and rerun affected trials."* Also: *"Pass rates and model ordering do not prove Task quality"*, and
  *"Do not make a Task harder to hide a defect."*
- **Harbor's layout** ([`references/harbor.md`](../../../.claude/skills/eval-engineering/references/harbor.md)):
  `task.toml` + `instruction.md` + `environment/` + `tests/test.sh` + optional `solution/solve.sh`,
  with `Task.md` (the human-reviewed spec, exact truth, scoring rules) *never* mounted into the
  agent's image, and `test.sh` obliged to *"write a valid reward … on every completed Verifier path"*
  and never to *"turn an infrastructure failure into a zero."*

**Take:** three rules, adopted verbatim below — *pass iff one observable outcome*; *the spec that
holds the answer is never visible to the thing being measured*; *infrastructure failure is a third
outcome, not a zero*. **Refuse:** Docker-per-task and the full Harbor package layout. Our environment
*is* a browser plus a local HTTP server ([`dataset.py:_StaticServer`](../../src/netgent/evals/dataset.py));
a Dockerfile per task buys nothing and costs the ability to run the suite from `uv run`.

### 1.7 Score-over-commits and eval-as-CI-gate — SWE-bench, LangSmith, statistics

**SWE-bench** is the reference for "one number tracked over commits". Its
[`harness/grading.py:309`](https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/grading.py)
reduces per-test results to a three-valued status:

```python
#   - If fail-to-pass (Resolution) = 1 and pass-to-pass (Maintenance) = 1 -> FULL
#   - If (fail-to-pass < 1 and > 0) and pass-to-pass = 1 -> PARTIAL
#   - Otherwise -> NO
```

The pairing of **FAIL_TO_PASS** (the new capability) with **PASS_TO_PASS** (nothing else broke) is
exactly the shape a pipeline regression suite needs. And its `SUITE_RAN` regex guard carries a comment
that is our bug class word-for-word: *"A runner that starts and immediately loses the browser still
prints its summary… an empty status map scores every F2P test as passing, so a zero count read as
evidence turns a suite that never ran into a resolved instance."* Our analogue is
[`compiler.py`'s same-page steps with `conditions=[]`](trajectory-memory.md) — a fill that silently
no-ops replays "successfully".

**LangSmith** supplies the vocabulary we should use even though we are not adopting the platform
(decision re-affirmed in [`langchain-evals.md`](langchain-evals.md) §6.1): **dataset** (collection of
examples), **example** (inputs + optional reference outputs + metadata), **experiment** (results of
evaluating one application *version* on a dataset), **evaluator** (human / code / LLM-as-judge /
pairwise), `num_repetitions` for repeated runs, and — the feature that names our need — a **pinned
baseline experiment**: "pin any experiment as your baseline… the baseline stays pinned to the top of
the Experiments view with performance deltas surfaced across every column"
([changelog](https://changelog.langchain.com/announcements/pin-a-baseline-experiment-in-langsmith),
[regression-testing blog](https://www.langchain.com/blog/regression-testing)). A flat markdown table
with a pinned baseline column reproduces this in ~40 lines.

**Statistics.** [Miller, *Adding Error Bars to Evals*, arXiv:2411.00640](https://arxiv.org/abs/2411.00640)
gives five recommendations; four bind here:

1. standard errors of the mean via the CLT: `SE = sqrt( Σ(sᵢ − s̄)² / (n−1) / n )`;
2. **clustered** standard errors when questions come in related groups (our 21 sweep forms on one
   page, or 3 variations of one task, are clusters — the paper notes cluster-adjusted SEs can be ~3×
   the naive value);
3. variance reduction by resampling answers — averaging K samples per question shrinks the
   conditional variance by K, with diminishing returns once `E[σᵢ²]/K ≪ Var(x)`;
4. **compare two models on question-level paired differences, not population summary statistics**:
   `SE_{A−B,paired} = sqrt( Σ(s_{A−B,i} − s̄_{A−B})² / (n−1) / n )`. Since per-task scores are
   positively correlated across arms, pairing is *"a 'free' reduction in estimator variance"*;
5. power analysis / minimum detectable effect, to decide whether a suite can test a hypothesis at all.

At n=3 runs × 3 tasks (our current scale) the MDE is enormous — this is worth saying out loud in the
spec rather than pretending a mean of three runs is a measurement.

### 1.8 What we take, and what we refuse

| Source | Adopt | Refuse |
|---|---|---|
| WebArena | task-as-file; `eval_types` list ANDed; navigate-and-check postconditions; `require_reset` | `fuzzy_match` (LLM inside the oracle) |
| VisualWebArena | pre-baked environment images; per-task reset tokens | Docker-per-task for our local fixtures |
| BrowserGym/AgentLab | commit hash + package + benchmark version in every record; resume-incomplete; per-seed dirs | a separate viewer binary |
| τ-bench | pass^k (`C(c,k)/C(n,k)`), pinned seed + temperature 0 | user-simulator machinery |
| Online-Mind2Web | key-points-first judging; judge-vs-human agreement as a reported number | judge as the primary oracle |
| AgentRewardBench | judge **precision** as the headline; a standing calibration set | nothing |
| browser-use benchmark | judge emits findings, code computes the score; `not_assessable` ≠ credit; worst-wins; canary; `steps/duration/cost` columns | encrypted task sets (our fixtures are local and public) |
| Skyvern | committed per-suite results; explicit `outdated` list for rotted live tasks | JSONL-only task specs (we need typed postconditions) |
| Stagehand | auto-discovered tasks; `trials: 3` default; `--preview`; `errorMatch` as its own score | Braintrust dependency |
| Inspect/Harbor | `epochs` in the spec; `Pass iff <one observable outcome>`; spec never visible to the measured thing; infra ≠ zero | container-per-task packaging |
| SWE-bench | FAIL_TO_PASS × PASS_TO_PASS pairing; "did the suite actually run" guard; status over commits | — |
| LangSmith | dataset/example/experiment/evaluator vocabulary; pinned baseline + deltas | the hosted platform ([`langchain-evals.md`](langchain-evals.md) §6.3) |
| Miller 2024 | paired per-task differences; clustered SEs; MDE honesty | — |

---

## 2. Spec — `netgent eval bench`

### 2.0 Command surface

```bash
netgent eval bench run   <suite> [--tier local|stable|live] [--runs N] [--k K]
                                 [--arm NAME] [--model provider:model] [--rounds R]
                                 [--only task-id ...] [--preview] [--resume] [--out DIR]
netgent eval bench replay [--golden evals/bench/golden]        # zero-LLM, the CI gate
netgent eval bench report [--commits SHA,SHA ...] [--arms a,b] [--baseline SHA]
```

Same conventions as the existing group ([`cli/evaluate.py`](../../src/netgent/cli/evaluate.py)):
importable functions in `netgent/evals/bench/`, no `sys.exit`, markdown + JSON under
`evals/results/bench/`, non-zero exit **only** from `replay` (the gate) and from runner errors.
`--preview` resolves the plan (tasks × runs × rounds, estimated LLM calls) and exits — Stagehand's
flag, and the cheapest guard against a mis-specified overnight sweep.

### 2.1 The task suite — `evals/bench/*.yaml`

One versioned file per suite. `suite_version` is bumped on **any** change to a task's text, params,
variations, or postconditions; every result row records it, so a score is never silently compared
across two different benchmarks.

```yaml
suite: core
suite_version: 1
tier: local                       # local | stable | live
defaults:
  model: anthropic:claude-haiku-4-5-20251001
  temperature: 0
  runs: 3                         # explorations per task (the merge's N)
  epochs: 3                       # pipeline repetitions per task (the pass^k n)
  max_steps: 25
  parallel: 3

tasks:
  - id: forms-vanilla
    task: "Fill in the signup form with the given values and submit it."
    url: "{base}/vanilla.html"          # {base} substituted by the local server, as dataset.py does
    params: {name: "Ada Lovelace", email: "ada@example.com", plan: "pro"}

    # Value sets the compiler never sees. Replay pass^k is measured on THESE.
    holdout:
      - {name: "Grace Hopper", email: "grace@example.com", plan: "basic"}
      - {name: "Alan Turing",  email: "alan@example.com",  plan: "pro"}

    # Success, page-derived. Our Trigger vocabulary; ANDed, WebArena-style.
    postconditions:
      - type: selector_visible
        selector: "text=the secret is: dumbledore"

    # What the merge SHOULD infer. Scored, not asserted — a miss is a number, not a crash.
    expect:
      params: [name, email, plan]
      interrupts: 0
      branches: 0
      accept_states: nonempty
      max_merge_warnings: 0

    budget: {max_tokens: 400000, max_wall_s: 300, max_rounds: 1}
    reset: none                    # none | storage_state | fixture   (WebArena's require_reset)

  # ── negative controls (agent-verification.md §6.5) ────────────────────────
  - id: sweep-form-7-ember
    tier: stable
    task: "Fill in this form completely with plausible values and submit it."
    url: "https://browser-use.github.io/stress-tests/forms-comparison.html"
    frame_filter: [ember]
    negative_control: true         # the fixture is BROKEN: success is impossible
    postconditions:
      - type: selector_visible
        selector: "text=dumbledore"
    expect: {achieved: false}      # any stage reporting achieved here is a scored false positive
```

**Tiers.**

| tier | environment | runs in | flake policy |
|---|---|---|---|
| `local` | `evals/bench/fixtures/**` served by `_StaticServer` | **CI, every commit** | zero tolerance — a failure is a bug |
| `stable` | public but static (browser-use stress pages, archive.org, a pinned TodoMVC) | nightly | 1 auto-retry; retries recorded |
| `live` | YouTube / Twitch / real sites | nightly, allowed to flake | failures classified before scoring; an `outdated:` list per Skyvern |

**Postcondition vocabulary and how it is checked.** Postconditions are `Trigger`s from
[`schema/triggers.py`](../../src/netgent/schema/triggers.py) — `url_matches`, `title_contains`,
`selector_visible`, `selector_hidden`, `dialog_matches`, `media_playing` — evaluated by
[`TriggerEngine.holds`](../../src/netgent/browser/triggers.py) (line 26), the same code the executor
uses. Reusing the executor's own trigger evaluation is the point: a postcondition the bench can check
is by construction a postcondition the compiler could emit.

`_form_succeeded` already discovered that end-of-run checking alone is insufficient (success banners
are transient). Generalize its three-way rule into `bench/postconditions.py`:

```
postcondition_met(trigger) :=
      TriggerEngine.holds(trigger) now                       # still visible
   or trigger matched a dialog raised since the run's mark   # dialogs are one-shot
   or trigger matched any observation the harness recorded   # texts_seen — transient banners
```

All three are the walker's own reads of the page, never the agent's self-report — the
[`sweep.py:72`](../../src/netgent/evals/sweep.py) docstring's rule, promoted to a shared module.

**Two dependencies, stated up front.** `media_playing` exists on `pr8-plus-scaffold` but **not** on
`eugene/v2-scaffold`; `text_visible` exists only on `eugene/v2-discovery`
([`agent-verification.md`](agent-verification.md) §6.5 slice 2). Until `text_visible` lands, text
postconditions are written as `selector_visible: "text=…"`, which Playwright supports but which
cannot express frame-scoped text. Both are prerequisites for the `live` tier, not for slice 1.

**Where the answer lives.** Harbor's rule applies: the suite file holds the truth (`postconditions`,
`expect`, `holdout`) and is **never** given to the explorer. The explorer receives `task` + `params`
and nothing else. This is not theoretical — the current `_variation_task` builds the explorer prompt
from the variation only, and the bench must not widen it.

### 2.2 Metrics per stage

Every metric below names the field that already records it. `[new]` marks the ones needing code.

#### Stage 1 — plan (`planner/graph.py`, `VariationPlan`)

| Metric | Definition | Source |
|---|---|---|
| `variation_validity` | fraction of planned variations whose values are usable (non-empty, distinct across runs, within the declared param names) | `store.save_variation(k, …)` → `run-k/variation.json` |
| `variation_diversity` | distinct value-tuples ÷ runs | same `[new: 3 lines]` |
| `plan_tokens` | tokens spent in the planner node | `LangChainLLM.usage` delta around the node `[new: per-node usage split]` |

Rationale: the merge can only infer a `Param` from a column whose values *actually varied*
([`merge.py`](../../src/netgent/agent/generator/merge.py) disposition 1). A planner emitting three
identical value sets silently caps generalization at zero, and today nothing would show it.

#### Stage 2 — explore

| Metric | Definition | Source |
|---|---|---|
| `explore_success` | `traj.success` per run | `AgentTrajectory.success` |
| `steps`, `steps_to_success` | `len(traj.steps)` | same |
| `stopped_reason` histogram | stuck / budget / done / error | `traj.stopped_reason` |
| `action_error_rate` | steps with `error` ÷ steps | `AgentStep.error` |
| `tokens`, `calls`, `in/step`, `out/step` | per run | `LangChainLLM.usage` + `.calls` (already in `stress.py` and `matrix.py`) |

These are exactly what `netgent eval stress` reports; `bench` reuses the columns so explorer A/B
numbers stay comparable with [`explorer-optimisation.md`](explorer-optimisation.md).

#### Stage 3 — verify (the judge, advisory)

Scored against page truth, per `agent-verification.md` §6.5. The headline is the **false-positive
rate**, because judge error is one-directional.

| Metric | Definition | Source |
|---|---|---|
| `judge_precision` | TP ÷ (TP+FP) where truth = `postcondition_met` | `sweep.py`'s existing computation, [`stress.py:193-203`](../../src/netgent/evals/stress.py), generalized |
| `judge_fp_rate` | FP ÷ judged — **the acceptance criterion** | same |
| `judge_recall` | TP ÷ (TP+FN); expected < 1 (page truth is conservative — AgentRewardBench §1.4) | same |
| `judge_unverifiable` | verdicts with no citable evidence (Stagehand's arm metric) | `Verdict.evidence == []` `[new]` |
| `agent_vs_judge_disagreement` | both directions | `traj.success` vs `verdict.achieved` |
| `negative_control_fp` | judge says achieved on `negative_control: true` | **hard gate: must be 0** |
| `retry_yield` | fraction of verifier-triggered re-explorations that then achieve | `verdict.json.attempts` (already stored) |

`retry_yield` is worth calling out: `verify_retries` costs a full extra exploration, and nothing today
tells us whether that money buys anything.

#### Stage 4 — merge / generalization

The richest under-measured stage. Everything below is already written to
`<name>.trajectories/generalized.json` by [`store.save_generalized`](../../src/netgent/agent/store.py);
the bench only has to *read and score* it.

| Metric | Definition | Source |
|---|---|---|
| `param_recall` | \|inferred ∩ `expect.params`\| ÷ \|`expect.params`\| | `GeneralizedTrajectory.params[].name` |
| `false_param_rate` | inferred params not in `expect.params` ÷ inferred | same |
| `param_default_correct` | defaults equal run 1's declared values | `ParamReport.default` vs `values_by_run` |
| `disposition_accuracy` | per-column disposition vs the suite's expected disposition, where declared | `ColumnReport.disposition` ∈ {aligned, param, param-target, interrupt, branch, dropped, value-diverges, target-varies} |
| `interrupt_precision` | inferred interrupts that are genuine dismissal controls ÷ inferred; `support` recorded | `GeneralizedTrajectory.interrupts[].support` |
| `branch_count` vs `expect.branches` | over/under-branching | `.branches` |
| `merge_warnings` | count, and count by class | `.warnings` |
| `dropped_columns` | columns present in *k<N* runs and dropped | `ColumnReport.disposition == "dropped"` |
| `achieved_runs` | how many of N reached the merge | `.achieved_runs` |

The live example already shows what these catch: 5 warnings, 6 dropped columns, and 2 of the 5
inferred interrupts at `support: 1` (a single run's `Mute (m)` and `Play (k)` clicks classified as
pop-up dismissals). None of that is visible in any number we report today; all of it degrades replay.

#### Stage 5 — compile (artifact quality)

Structural properties belong in `tests/` as pydantic assertions
([`langchain-evals.md`](langchain-evals.md) §6.4 point 5); the bench **records** them as columns so a
change in artifact shape is visible next to the score.

| Metric | Source |
|---|---|
| `states`, `transitions`, `interrupts`, `params` | `len(wf.states)` etc. |
| `accept_states_nonempty` | `bool(wf.accept_states)` — the §6.3 slice-4 gate |
| `unguarded_transition_rate` | transitions whose target state has `conditions == []` | `Workflow.states[].conditions` |
| `locator_ambiguity` | targets whose durable locator resolves to ≠1 element (reuse `observation.py`'s uniqueness check) | `[new: reuse existing code]` |
| `fixed_sleep_count` | `wait` actions not derived from a `${param}` | [`browser-layer-design.md`](../browser-layer-design.md) §3: *"every remaining fixed sleep is a bug report"* |

`unguarded_transition_rate` is the direct analogue of SWE-bench's `SUITE_RAN` guard: an unguarded
same-page transition is a fill that can silently no-op and still "replay successfully."

#### Stage 6 — replay (**the product metric**)

```
replay_pass^k  =  mean over tasks of  C(c, k) / C(n, k)
```

with `n` = epochs × |holdout| trials and `c` = trials where **the artifact compiled in this run**
replays the **held-out value set** to `record.success` AND its postconditions are met AND its state
signature agrees with the other trials'. Zero LLM: this is
[`replay_check`](../../src/netgent/agent/replay.py) with the holdout values substituted for the
metamorphic pair, plus the postcondition check.

| Metric | Definition | Source |
|---|---|---|
| `replay_pass^k`, k = 1..n | above, τ-bench formula | `ReplayRun.success`, `ReplayReport.passed` |
| `signature_agreement` | distinct state signatures ÷ trials (1 = perfect) | [`state_signature`](../../src/netgent/agent/replay.py) line 33 |
| `holdout_generalization_gap` | pass^1 on `params` minus pass^1 on `holdout` | — |
| `interrupt_fire_rate` | interrupt edges per replay (stochastic by design; a *rise* means the site changed) | `EdgeRecord.transition_id.startswith("ti")` |
| `trigger_latency_p95` | slowest state recognition | `EdgeRecord.trigger_latency_ms` (already recorded) |
| `replay_survival(d)` | **staleness**: pass^1 of a *stored golden artifact* replayed d days after it was compiled | `evals/bench/golden/` + result timestamps |

`holdout_generalization_gap` is the number that separates "the pipeline memorized one run" from "the
pipeline generalized". It is the reason `holdout` is a required field.

`replay_survival` is the only metric here that measures the *world* rather than the code; report it
as a curve per artifact age and never as a pipeline regression.

#### Stage 7 — closed loop (`triage → plan_next → rounds`)

| Metric | Definition | Source |
|---|---|---|
| `rounds_to_pass` | rounds until replay pass^k ≥ threshold; `∞` if budget exhausted | round loop `[new]` |
| `episodes_per_round` | explorations launched per round | `len(state["inputs"])` per round |
| `hint_acceptance_rate` | triage hints that the next round's trajectory actually acted on (a hint is "accepted" when its named selector/step appears in an achieved run) | `[new]` — compare `plan_next` output against next round's `AgentStep.action` targets |
| `marginal_round_yield` | Δ(replay pass^1) per additional round | derived |
| `tokens_per_accepted_artifact` | Σ tokens over all rounds ÷ artifacts passing replay pass^k | usage + replay |
| `wall_per_accepted_artifact` | same with seconds | `wall_s` |
| `contamination_divergence` | divergence count: columns where runs disagree (`dropped` + `value-diverges` + `target-varies`) ÷ columns; rises when a hint leaks a step sequence between runs | `ColumnReport.disposition`, per [`trajectory-memory.md`](trajectory-memory.md) §C |

**The anti-hiding rule.** Quality metrics are reported **at a fixed round budget**, and the report
prints a `pass^1 @ R=1 / @ R=2 / @ R=max` triple. A change that keeps the final number by spending
more rounds shows as a *left-shifted* curve — the regression is in `pass^1 @ R=1` and in
`tokens_per_accepted_artifact`, both of which are printed next to the headline. Comparing two commits
at different budgets is refused by the reporter, not left to the reader.

`contamination_divergence` is the guard on the independence policy: the orchestrator's `_site_hints`
is deliberately restricted to interrupt anchors *"never a step sequence, never an element to click for
the task, never a value"*. If `plan_next` widens that, divergence collapses (runs become copies) and
the merge's version-space intersection stops being evidence. A *falling* divergence count with a
*rising* score is the contamination signature.

### 2.3 Statistics

**Design.** Per arm: `epochs = 3` pipeline repetitions per task (Stagehand's default, our A/B
convention), `temperature = 0`, model pinned as `provider:model`, seed recorded where the provider
honours one. Suite, `suite_version`, commit SHA, `uv.lock` hash, Patchright version, and OS go in
every row (AgentLab's reproducibility set).

**Reporting.** Per-run values are always listed, never only the mean — this is already the house rule
(*"per-run results are listed, not just means (n=3 is noisy)"*,
[`explorer-optimisation.md`](explorer-optimisation.md) §1). Add:

- **mean ± SE** using the CLT formula, with **clustered** SEs where tasks share a page (the 21 sweep
  forms; the 3 holdout sets of one task are also a cluster);
- **pass^k for k = 1..n**, printed as a curve, not a scalar;
- **paired per-task differences** for any two arms, with the paired SE — Miller rec. 4, and the reason
  a 3-task suite can say anything at all;
- an explicit **MDE line** in every report: at 3 tasks × 3 epochs the smallest detectable difference
  is roughly a full task, and the report should print that rather than let a 0.33 delta look real.

**What counts as a regression** (ordered; the first two are gates, the third is a signal):

1. **Hard gate** — any golden artifact fails zero-LLM replay, or `accept_states` becomes empty, or a
   `negative_control` task is reported achieved by any stage. n=1 suffices: these are deterministic.
2. **Hard gate** — `replay_pass^1` on the local tier drops below the committed baseline on **any**
   task while no task improves (SWE-bench's PASS_TO_PASS discipline: the new capability must not break
   the old ones).
3. **Signal** — the paired difference in `replay_pass^k` has a 95% interval excluding zero at equal
   round budget. Below that bar it is reported as "not distinguishable at n=3", which is a true
   statement and a more useful one than a coloured arrow.

**Flakiness.** Every non-pass is classified with the skill's taxonomy — *Capability / Missing
information / Harness / Environment / False rejection / False acceptance / Leakage / Infrastructure*
— and only `Capability` counts against the score. Infra failures are recorded as a separate
`error_rate` column (Stagehand's `errorMatch`), never as zeros. Live-tier tasks that fail three
consecutive nights move to an `outdated:` list in the suite file (Skyvern's convention) and stop
counting until repaired.

**Cost normalization.** `tokens_per_accepted_artifact` and `usd_per_accepted_artifact` (Haiku list
prices, the arithmetic already in [`matrix.py:8`](../../src/netgent/evals/matrix.py)) are printed
beside every quality number. An arm that wins on quality and loses 3× on cost is a legitimate result;
it just has to be visible.

### 2.4 Mechanics

**Result layout** — committed, per decision #13:

```
evals/results/bench/<commit-sha>/
  meta.json                  # commit, suite, suite_version, model, temperature, uv.lock hash,
                             # patchright version, os, started_at, arm, tier, round budget
  <suite>/
    summary.json             # aggregate rows (the thing report/ reads)
    bench.md                 # human-readable table, the same shape as matrix.md
    <task-id>/
      epoch-1/
        run-1..N/            # per exploration: trajectory.json, variation.json, verdict.json
        generalized.json     # the merge's evidence trail
        workflow.yaml        # the compiled artifact
        replay-holdout-1/    # record.json (+ screenshots, gitignored)
        row.json             # ONE flat row: every metric of §2.2 for this epoch
```

`row.json` is the unit the reporter consumes; everything else is evidence. Screenshots stay gitignored
(heavy, regenerable) exactly as `evals/README.md` already specifies; `row.json`, `summary.json`,
`generalized.json`, `workflow.yaml` and `record.json` are committed.

**The report** — `netgent eval bench report --commits A,B --baseline A` extends
[`matrix.py`](../../src/netgent/evals/matrix.py) rather than replacing it: same loader shape, same
markdown-table output, with a pinned baseline column and per-column deltas (LangSmith's baseline
feature, reproduced flat):

```
| metric                  | A (baseline) | B         | Δ        | paired 95% CI |
|-------------------------|--------------|-----------|----------|---------------|
| replay pass^1           | 0.67 (2/3)   | 1.00 (3/3)| +0.33    | [-0.2, +0.9]  |
| replay pass^3           | 0.33         | 1.00      | +0.67    | [ 0.0, +1.0]  |
| holdout gap             | 0.33         | 0.00      | -0.33    | …             |
| param recall            | 0.75         | 1.00      | +0.25    | …             |
| false param rate        | 0.20         | 0.00      | -0.20    | …             |
| merge warnings          | 5            | 1         | -4       | —             |
| judge FP rate           | 0.08         | 0.08      |  0.00    | …             |
| tokens / accepted artifact | 1.4M      | 0.9M      | -36%     | —             |
| rounds to pass (median) | 2            | 1         | -1       | —             |
```

**CI vs nightly.**

| When | What | Cost |
|---|---|---|
| every commit (CI) | `netgent eval bench replay` — zero-LLM replay of **golden artifacts** on local fixtures + `negative_control` structural checks + `tests/unit` artifact assertions | seconds, $0 |
| every commit (CI) | existing `netgent eval dataset evals/datasets/forms` ([`ci.yml:55`](../../../.github/workflows/ci.yml)) folds into the above | seconds, $0 |
| nightly | `netgent eval bench run core --tier local` (LLM, full pipeline, 3 epochs) | ~minutes, cents |
| nightly | `--tier stable` (sweep/challenge pages) | ~1 h |
| nightly, allowed to flake | `--tier live` (YouTube/Twitch) | ~1 h |
| on demand | `--arm` A/B, per §2.4 below | — |

The CI job stays zero-LLM by construction, which keeps the `agent/`-imports-langchain boundary and
the "CI never depends on a model provider" property intact. Only the nightly job needs keys.

**Golden artifacts.** `evals/bench/golden/<task-id>.workflow.yaml` + its fixture: the artifact a
known-good pipeline run produced, frozen, with a `golden.json` recording the commit and date that
compiled it. Replayed on every commit with zero LLM. This is `netgent eval dataset` generalized from
one directory to a per-task set with postconditions, and it is what catches executor/browser
regressions that have nothing to do with the LLM. Refreshing a golden artifact is an explicit,
reviewed commit — never automatic, or the gate measures nothing.

**A/B worktrees.** Unchanged from [`explorer-optimisation.md`](explorer-optimisation.md) §1: one
`git worktree` per arm under `/tmp/netgent-<arm>`, own `uv` venv, `--out /tmp/<arm>`, arms run
concurrently (wall time indicative only; scores/steps/tokens unaffected). The bench adds two things:
`--arm NAME` stamps `meta.json` so `report` can join arms without directory-name parsing, and
`--resume` re-runs only the missing `row.json`s (AgentLab's `find_incomplete`), because a killed
LLM arm currently means paying for the whole thing again.

**Dashboards.** A flat committed `bench.md` per commit, plus `report` for cross-commit tables. No
platform: [`langchain-evals.md`](langchain-evals.md) §6.3's argument stands — a paper's numbers should
not live behind a 1-seat free tier, and the committed-rows requirement is satisfied by no hosted
product. LangSmith **tracing** stays available and off by default for debugging a compile run.

### 2.5 Build order

**Slice 0 — this week, one trustworthy number.** Local tier only, no new agents.

1. `evals/bench/core.yaml` with the three existing form fixtures
   (`vanilla`, `shadow`, `progressive` from `evals/datasets/forms/`), each with `params`, two
   `holdout` value sets, and one `selector_visible` postcondition (`text=the secret is: dumbledore`).
2. `evals/bench/postconditions.py` — `_form_succeeded` generalized to a `Trigger` list over
   `TriggerEngine.holds` + dialogs + `texts_seen`. ~40 lines, unit-tested against the six
   decision-boundary fixtures from the skill's table (known-good, valid-alternative, realistic-wrong,
   shortcut, collateral-change, corrupt-evidence).
3. `netgent eval bench run core --tier local --runs 3 --epochs 3`: drives the existing
   `orchestrate(GenerateRequest…)` per epoch, then replays the artifact once per `holdout` set with
   `replay_check`, and writes `row.json`.
4. Report **`replay_pass^k`, k=1..6**, `holdout_generalization_gap`, and per-run values.

That is a real product number by Friday: *given a task and a start URL, how often does the compiled
NFA replay a value set the compiler never saw*. Nothing in the repo answers it today.

**Slice 1 — the gate (days).** `evals/bench/golden/` + `netgent eval bench replay` wired into CI
alongside the existing `eval dataset` step; `accept_states_nonempty` and `unguarded_transition_rate`
as `tests/unit` assertions.

**Slice 2 — the two negative controls (days).** Add the Ember and Shadow-DOM sweep forms — the two
that fail in every arm (indices 7 and 11 in [`explorer-optimisation.md`](explorer-optimisation.md)
§2.2; named as the broken fixtures in [`browser-agent-date-inputs.md`](browser-agent-date-inputs.md),
*"the ceiling, Ember and Shadow DOM being broken fixtures"*)
as `negative_control: true` on the `stable` tier, and score `negative_control_fp` for the verifier
and for `traj.success`. This is `agent-verification.md` §6.5's stated acceptance test, run
automatically instead of by hand.

**Slice 3 — generalization metrics (days).** Read `generalized.json` into `row.json`:
`param_recall`, `false_param_rate`, `merge_warnings`, `dropped_columns`, interrupt `support`
distribution. Zero new model calls — the data is already on disk.

**Slice 4 — the reporter (days).** `netgent eval bench report --commits … --baseline …`, paired
differences + clustered SEs + the MDE line. Extend `matrix.py`'s loader.

**Slice 5 — the closed loop (when `v2/closed-loop-rounds` lands).** Add `rounds`, `--rounds R`,
and the seven §2.2 stage-7 columns. The only genuinely new instrumentation is
`hint_acceptance_rate`, which needs `plan_next` to emit its hints in a typed form the bench can join
against the next round's `AgentStep.action` targets — worth requesting *while* that node is being
written rather than retrofitting.

**Slice 6 — live tier.** Requires `text_visible` (merge from `eugene/v2-discovery`) and
`media_playing` (already on `pr8-plus-scaffold`) for YouTube/Twitch postconditions, plus the
`outdated:` list and the three-consecutive-nights rule.

**Explicitly not built:** a hosted eval platform; an LLM anywhere in the oracle; per-step LLM
verification (PAE found step-level evaluation *"too noisy"*, and our per-step signal is already
deterministic); a similarity threshold anywhere; Docker-per-task; a task set encrypted against
contamination (our fixtures are local HTML we wrote).

---

## 3. Provenance and unverified claims

**Verified by direct fetch of current sources (2026-09-02):** WebArena `test.raw.json` task 0 and
`config_files/examples/2.json` verbatim (812 tasks in `test.raw.json`); WebArena `evaluators.py`
class list (`StringEvaluator`, `URLEvaluator`, `HTMLContentEvaluator` — note there is **no**
`page_image_query` evaluator in that file, contrary to the brief's list); τ-bench
`tau_bench/run.py:194-203` pass^k code verbatim and its CLI defaults; browser-use `benchmark`
repo tree, README (BU Bench V1=100, V2=200, Stealth Bench V1=71 tasks; task fields `task_id`,
`confirmed_task`, `category`, `answer`), `findings_judge.py` docstring/`score()` verbatim,
`run_eval.py` `steps`/`duration`/`cost` columns; Skyvern `evaluation/` tree and
`WebVoyagerTestCase`; Stagehand `packages/evals` tree, README, `evals.config.json`, `scoring.ts`;
SWE-bench `grading.py` `get_resolution_status` and `SUITE_RAN` comment verbatim; Harbor/verifier/
calibration/patterns text from the installed `.claude/skills/eval-engineering/`; the NetGent files
and line numbers cited throughout, plus `pr8-plus-scaffold`'s `orchestrator.py`, `merge.py`,
`replay.py`, `store.py`, and the real `dream-theater.trajectories.example/generalized.json` on the
`v2/closed-loop-rounds` worktree.

**Reported via a summarizing fetch, not quoted from primary text — treat the numbers as
approximate until re-checked:**

- AgentRewardBench precision figures (GPT-4o 69.8%; WebArena −16.7 pp, VWA −18.5 pp; 89.3%
  inter-annotator agreement). The abstract confirms *"1302 trajectories across 5 benchmarks and 4
  LLMs"* and the underreporting claim; the specific percentages come from a summarized read of the
  paper HTML.
- Online-Mind2Web WebJudge agreement rates (83.6% / 85.7% / 87%) and the v2 submission field list.
- AgentLab README details (`AGENTLAB_EXP_ROOT`, `reproducibility_journal.csv`, `find_incomplete`) and
  the BrowserGym paper's five variance sources — quoted through a summarizer; wording is close but
  not guaranteed verbatim.
- LangSmith `num_repetitions` and the pinned-baseline feature: the docs page for repetitions 404'd;
  the parameter name and baseline behaviour come from the LangChain changelog/blog and search
  results, not from a fetched API reference.
- Inspect's `epochs` semantics — from the Inspect docs page, summarized.
- Miller (arXiv:2411.00640): the five recommendations and formulas were read from the HTML render;
  the LaTeX is transcribed and should be checked against the PDF before being reproduced in a paper.

**Unverified design assumptions in the spec (not facts about the world):**

- That `TriggerEngine.holds` can be driven from a bench harness without an `Executor` — plausible
  (it takes `page`, `resolver`, `dialogs`) but not attempted.
- That per-node token attribution is obtainable by diffing `LangChainLLM.usage` around each LangGraph
  node. With `parallel > 1` this is **wrong** — concurrent explorations share one LLM object — so
  Stage-1/Stage-2 token splits need either per-run LLM instances or a callback-scoped counter. Flagged
  rather than solved.
- That `hint_acceptance_rate` is computable by joining `plan_next` output against the next round's
  action targets. It depends entirely on hints being typed, which is a request to the closed-loop
  work, not an observation about it.
- The `holdout_generalization_gap` and `replay_survival(d)` metrics have no precedent in the surveyed
  systems; they are derived from NetGent's own contract (zero-LLM replay of a parameterized artifact)
  and should be treated as proposals.
- The mapping *sweep forms 7 and 11 ↔ the Ember and Shadow-DOM fixtures* is an inference from two
  docs (`explorer-optimisation.md` §2.2 names the indices; `browser-agent-date-inputs.md` names the
  fixtures); no file states the binding directly. Confirm before writing the ids into `core.yaml`.
- The claim that `contamination_divergence` falls under hint leakage is a hypothesis from
  [`trajectory-memory.md`](trajectory-memory.md) §C's reasoning, not a measured NetGent result.
