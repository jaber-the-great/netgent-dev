# LangChain/LangGraph Eval Libraries — Survey and Recommendation

**Question.** NetGent v2 compiles workflows with a LangGraph pipeline (Planner → Discovery → Generator
→ Validator) and replays them with zero LLM calls ([`OVERVIEW.md`](../OVERVIEW.md) §3.1, decision #15).
What libraries exist for evaluating LangChain/LangGraph-based pipelines, and should NetGent use any of
them?

**Answer, in one line.** No — with one narrow exception: copy openevals' MIT-licensed judge *prompts*
into the repo and write the harness by hand. Every library surveyed is built around a hosted
dashboard, evaluates the wrong surface, or is 12 lines of list comparison wearing a dependency tree.

**Status.** Researched 2026-08-17 against live repos, PyPI, and vendor pricing pages, with every
behavioural claim reproduced locally in throwaway virtualenvs (`uv venv` + `uv pip install` at the
versions named below). Claims marked **[verified]** were executed, not read. Reproduction commands are
in [Appendix A](#appendix-a--reproducing-this-survey).

---

## 0. The two surfaces being evaluated

Everything below turns on which of NetGent's two eval surfaces a library can even reach.

| | **(a) Compile-pipeline evals** | **(b) End-to-end workflow evals** |
|---|---|---|
| Question | Does `netgent generate` produce a *correct NFA* from a spec? | Does the compiled NFA *replay successfully* on the live site? |
| What runs | The LangGraph pipeline, LLM present | `netgent run` — **zero LLM calls, no framework imported** |
| Artifact under test | A typed pydantic NFA (states, guards, edge action IR) | A replay: success/failure, HAR, timing, trace stability |
| Shape of the metric | Structural assertions + LLM judge on the emitted graph | Success rate over a task set + LLM judge on outcomes |
| Home | `tests/` (structural) + `evals/` (judged) | `netgent eval` + `evals/datasets/` |

**Surface (b) has no LangGraph run in it at all.** The import-boundary rule (decision #10: `core ←
browser ← executor ← agent`, only `agent` imports LLM SDKs) means the replay path never touches
LangChain. Every trace-shaped tool in this survey — agentevals' graph trajectories, Phoenix's OTel
spans, DeepEval's callback handler, MLflow's autolog — is **structurally inapplicable to surface (b)**,
which is the surface `evals/` exists for. This single fact eliminates most of the field before
maintenance or pricing is even considered.

A third point, easy to lose: NetGent's headline eval metric is **trace fidelity** — HAR/network-trace
stability across replays, "the one metric no competing system can report"
([`OVERVIEW.md`](../OVERVIEW.md) §1; `related-work.md` §P3). No LLM-eval library has any concept of a
network trace. That metric is custom no matter what is adopted.

---

## 1. First-party LangChain ecosystem

### 1.1 LangSmith SDK — `evaluate()`, datasets, experiments

`langsmith` 0.11.0 (2026-08-14) · MIT · [langchain-ai/langsmith-sdk](https://github.com/langchain-ai/langsmith-sdk)
1,022★ · 521 releases since 2023-06-26 · actively developed (pushed 2026-08-17).

**Already in the dependency tree.** `langchain-core` requires `langsmith<1.0.0,>=0.3.45` **[verified]**
— a hard dependency, not an extra. So `netgent[generate]` already installs it, and `LANGSMITH_API_KEY`
is already a documented slot in `v2/.env.example`. Marginal install cost of *using* it: zero.

**API shape:**

```python
from langsmith import evaluate
results = evaluate(target_fn, data=examples, evaluators=[my_scorer], upload_results=False)
```

**Does it work offline?** Yes — with caveats that matter. **[verified]** with no `LANGSMITH_API_KEY`,
`LANGSMITH_TRACING=false`, and `LANGSMITH_ENDPOINT=http://127.0.0.1:9` (a deliberately dead port); the
run completed with correct scores and exit 0, so the offline path genuinely makes no network calls.
But:

1. **`upload_results=False` is beta.** It emits `LangSmithBetaWarning: 'upload_results' parameter is in
   beta.` on every run (`langsmith/evaluation/_runner.py:396`).
2. **`data` must be `langsmith.schemas.Example` objects, not dicts.** Passing a plain
   `[{"inputs": …, "outputs": …}]` — the form the docs' cloud path accepts — crashes with
   `AttributeError: 'dict' object has no attribute 'modified_at'` at `_runner.py:1980`. Offline you
   must hand-construct `Example(id=uuid4(), dataset_id=…, created_at=…, modified_at=…, …)`.
3. **No on-disk artifact.** `ExperimentResults` is in-memory. Writing the committed per-task JSONL that
   decision #13 requires is code you write yourself, in full.
4. Minor maturity tell: the offline run prints `Starting evaluation of experiment: %s mealy-country-38`
   — an unformatted `%s` in the log line.

**Cloud coupling.** Not a hard gate, but the *value* of `evaluate()` is the hosted experiment
comparison UI. Used offline you pay the ceremony (Example objects, beta flag, no persistence) for none
of the payoff.

**Pricing / self-host** (langchain.com/pricing-langsmith, fetched 2026-08-17): Developer $0/seat,
**max 1 seat**, 5k base traces/mo then pay-as-you-go; Plus $39/seat/mo, 10k traces; Enterprise custom.
**Self-hosted and hybrid deployment are Enterprise-only** and require a `LANGSMITH_LICENSE_KEY`
obtained through sales. The server is closed-source. For a multi-person university lab the realistic
options are "1 free seat" or "$39/person/month" — the free tier's seat cap is the binding constraint,
not the trace cap.

### 1.2 openevals — prebuilt LLM-judge evaluators

`openevals` 0.2.0 (2026-04-07) · MIT · [langchain-ai/openevals](https://github.com/langchain-ai/openevals)
1,169★ · 60 releases since 2025-02-17 · ~1.16M downloads/mo.

**Maintenance: coasting.** The last 10 commits (through 2026-08-12) are *entirely* Dependabot bumps and
their merge commits — `chore(deps): Bump brace-expansion`, `Bump nltk`, `Fix Dependabot dependency
alerts` **[verified]**. 38 commits in the last 90 days, no feature work among them. It is maintained in
the security-patch sense, not the developing sense. Newest open issue (#212, 2026-08-04): *"Most
built-in judge prompts don't guard against presentation bias."*

**What it offers.** Three groups:

- **LLM-as-judge factory** — `create_llm_as_judge(prompt=…, model=…, feedback_key=…)`, with continuous
  or boolean scores, custom output schemas, few-shot examples, and multimodal attachments.
- **~30 prebuilt judge prompts** as plain Python string constants under `openevals/prompts/`:
  `CORRECTNESS_PROMPT`, `PLAN_ADHERENCE_PROMPT`, `TRAJECTORY_ACCURACY_PROMPT`, `TOOL_SELECTION_PROMPT`,
  `HALLUCINATION_PROMPT`, `TASK_COMPLETION_PROMPT`, plus RAG/safety/security/image/voice families.
- **Deterministic evaluators** — `exact_match`, `create_json_match_evaluator`, Levenshtein, embedding
  similarity, and Pyright/mypy code checkers.

**Offline?** Yes for the deterministic evaluators. **[verified]** with all `LANGSMITH_*`/`OPENAI_*` env
vars deleted: `create_json_match_evaluator` and `exact_match` return plain dicts
(`{'key': 'json_match:average', 'score': 0.5, 'comment': None, 'metadata': None}`), no network. The
LangSmith coupling in `openevals/utils.py` is `@traceable` + `get_current_run_tree()`, both inert when
tracing is off. The LLM judge obviously needs a model key, but nothing needs a *LangSmith* key.

**Two frictions specific to NetGent:**

- **`langchain-openai` is a mandatory dependency** (`openevals/pyproject.toml`), even though NetGent's
  default is `NETGENT_GENERATOR_MODEL=gemini/gemini-2.5-pro`.
- **Model-string namespace mismatch.** openevals routes through `init_chat_model`, which speaks
  `provider:model`, not litellm's `provider/model`. **[verified]** — passing NetGent's own config
  string `"gemini/gemini-2.5-pro"` resolves to *ChatVertexAI* and demands `langchain-google-vertexai`;
  `"google_genai:gemini-2.5-pro"` demands `langchain-google-genai`. So the eval layer would need its
  own model-string dialect and its own provider packages, diverging from `.env.example`.

Install footprint: 51 packages / 66 MB (pulls `openai`, `tiktoken`, `langgraph`, `langchain-openai`)
**[verified]**.

### 1.3 agentevals — trajectory evaluators for LangGraph agents

`agentevals` 0.0.9 · MIT · [langchain-ai/agentevals](https://github.com/langchain-ai/agentevals)
699★ · ~370k downloads/mo.

**Maintenance: dormant.** Last PyPI release **2025-07-24 — thirteen months ago**. Still 0.0.x. All 20
commits in the last 90 days are Dependabot **[verified]**. Sole dependency: `openevals>=0.0.20`.

**What it offers.**

*Agent trajectory match* — `create_trajectory_match_evaluator(trajectory_match_mode=…)` over OpenAI-format
message lists carrying `tool_calls`, in `strict` / `unordered` / `subset` / `superset` modes, with
per-tool arg-matching overrides. **[verified]** offline.

*Graph trajectory* — the headline feature and the reason it was on the shortlist:

```python
from agentevals.graph_trajectory.utils import extract_langgraph_trajectory_from_thread
from agentevals.graph_trajectory.strict import graph_trajectory_strict_match

t = extract_langgraph_trajectory_from_thread(app, {"configurable": {"thread_id": "1"}})
# t["outputs"]["steps"] == [['__start__', 'planner', 'discovery', 'generator', 'validator']]
graph_trajectory_strict_match(outputs=t["outputs"], reference_outputs=ref)
```

**[verified]** against a hand-built 4-node LangGraph shaped like NetGent's compile pipeline. Three
findings from doing so:

1. **It requires a checkpointer.** Without one, `extract_langgraph_trajectory_from_thread` raises
   `ValueError: No checkpointer set`, because it reads `graph.get_state_history(config)`. NetGent's
   compile pipeline is a batch job with no human-in-the-loop and no resume requirement — it would have
   to adopt a checkpointer *solely to make its trajectory extractable*.
2. **`graph_trajectory_strict_match` is a twelve-line list-of-lists equality check.** The entire scorer
   in `graph_trajectory/strict.py` is a length check plus a `zip` comparison. There is no partial
   credit, no edit distance, no subset mode (open feature request #49, 2025-06-03, unanswered).
3. **The issue backlog is stale, but the code is not broken.** Issue #40 (*"Graph trajectory extraction
   does not handle `Command`/`Send` API"*, opened 2025-05-20) has been open 15 months. I could **not**
   reproduce it on agentevals 0.0.9 + langgraph 1.2.x: both a `Send`-based fan-out (correctly extracted
   `['__start__','planner','discovery','discovery','discovery','generator']`) and a `Command(goto=…)`
   handoff chain extracted cleanly **[verified]**. Read that as an unattended tracker rather than a
   functional defect — which is itself the maintenance signal.

*Graph trajectory LLM-as-judge* — `create_graph_trajectory_llm_as_judge`, which formats
`<input>/<trajectory>/<result>` blocks into a rubric prompt asking whether the steps "make logical
sense" and are "relatively efficient." Useful shape; it is a prompt template, and the prompt is MIT.

---

## 2. Third-party frameworks

### 2.1 DeepEval (Confident AI)

`deepeval` 4.1.8 (2026-08-12) · Apache-2.0 · 17.6k★ · 516 releases · ~5.65M downloads/mo · genuinely
active (pushed same-day).

**LangGraph integration: real, but cloud-directed.** `deepeval/integrations/README.md` carries an
explicit matrix with a LangGraph row (mechanism: LangChain's `CallbackHandler()`). But the matrix's
"Bare" column is defined as *"calling the framework directly … produces a trace **in Confident AI**"*,
and the transport reference names `api.confident-ai.com/v1/traces` and `otel.confident-ai.com`. The
tracing integration exists to feed their SaaS.

**Local evaluation works without a Confident AI key** **[verified]** — `evaluate(test_cases=…,
metrics=[ToolCorrectnessMetric()])` scored correctly offline — but prints a Confident AI upsell banner
on every run.

**Three concrete costs for NetGent:**

- **It forces an OpenAI key for a metric that needs no LLM.** `ToolCorrectnessMetric()` is purely
  deterministic (set comparison over tool names), yet its **constructor** eagerly calls
  `initialize_model(None)` → `OpenAIModel()` → `DeepEvalError: OpenAI API key is not configured`
  **[verified]**, traceback through `deepeval/metrics/utils.py:713`. A Gemini-configured repo cannot
  run deepeval's deterministic metrics without also holding an OpenAI key.
- **It installs five pytest plugins as hard runtime dependencies** — `pytest`, `pytest-asyncio`,
  `pytest-repeat`, `pytest-rerunfailures`, `pytest-xdist`, plus `posthog` and `grpcio` **[verified]**;
  66 packages / 102 MB. NetGent's `tests/` is the deterministic CI gate (decision #13); having an
  *eval* dependency inject plugins that change pytest collection and retry semantics inverts that
  separation.
- **Telemetry is on by default** (PostHog → `us.i.posthog.com`), opt out via
  `DEEPEVAL_TELEMETRY_OPT_OUT=1`.

Agent-relevant metrics worth knowing exist: `task_completion`, `tool_correctness`, `plan_adherence`,
`plan_quality`, `step_efficiency`, `agent_loop_detection`, `goal_accuracy`, `dag` (decision-tree
scoring), `g_eval`.

### 2.2 Ragas

`ragas` 0.4.3 · Apache-2.0 · 15.3k★.

**Dormant, and it moved.** The repo has been transferred from `explodinggradients/ragas` to
**`vibrantlabsai/ragas`**. Last commit **2026-02-24**; last release **2026-01-13** — roughly six months
of silence at time of writing.

It does have `src/ragas/integrations/langgraph.py` and agent-shaped metrics (`_goal_accuracy.py`,
`_tool_call_accuracy.py`, `_tool_call_f1.py`). But the library's centre of gravity is RAG — faithfulness,
context precision/recall, answer relevance — and **NetGent has no retrieval surface at all**. Wrong
shape plus dormancy plus an org transfer mid-flight.

### 2.3 Arize Phoenix

`arize-phoenix` 20.2.1 (2026-08-14) · **Elastic License 2.0** · 11.1k★ · 683 releases · extremely active.

**Not OSI open source.** Verified from the repo's `LICENSE`: ELv2 forbids providing the software to
third parties as a hosted service and forbids circumventing its license-key functionality.
`arize-phoenix-evals` (3.4.0) is ELv2 as well. For a university lab running it internally this is
almost certainly fine, but it is a licensing-review item, not a non-event — and it is the only
copyleft-adjacent license in this survey.

**Self-hosting is free and easy**: `pip install arize-phoenix && phoenix serve` (or
`uvx arize-phoenix serve`), with Docker Compose / Kubernetes+Helm / AWS CloudFormation paths documented.
LangGraph tracing works via OpenTelemetry (`openinference-instrumentation-langchain` 0.1.70).

**Why it still doesn't fit.** Phoenix is an *observability platform* whose evals are a sub-package. Its
value is a live server collecting spans from a running application. NetGent's evals run offline, a
handful of times per paper deadline, and must produce git-committed files. Standing up an OTel
collector and a Phoenix server to score a batch job you run monthly is inverted effort.

### 2.4 promptfoo

`promptfoo` 0.122.0 (2026-08-04) · MIT · 24.3k★ · very active · TypeScript/npm.

**Zero LangChain/LangGraph integration.** `gh search code repo:promptfoo/promptfoo langgraph` → **0
results**; `langchain in:path` → **0 results** **[verified]**. Its Python integration is a black-box
provider contract — `def call_api(prompt, options, context) -> {"output": …}` — which sees only the
final output and has no visibility into intermediate steps or traces.

It is a good declarative prompt-comparison and red-teaming tool. It is not a LangGraph eval library,
and adopting it would put Node in the toolchain of a pure-Python repo.

### 2.5 Braintrust (and `autoevals`)

`braintrust` 0.34.0 (2026-08-17) · very active.

**Hard cloud gate.** `braintrust.Eval(...)` with no `BRAINTRUST_API_KEY` fails outright:
`ValueError: Could not login to Braintrust. You may need to set BRAINTRUST_API_KEY in your environment
or nearest .env.braintrust file.` **[verified]**. There is no offline mode. This is the clearest
lock-in of anything surveyed.

Pricing (braintrust.dev/pricing, fetched 2026-08-17): Starter free — $10 credits, 1 GB processed data
(then $4/GB), 10k scores (then $2.50/1k), **14-day retention**; Pro $249/mo; self-hosting is
Enterprise-only. No per-seat fees. The 14-day retention on the free tier is disqualifying on its own
for results that must remain verifiable alongside a paper.

**`autoevals` is the salvageable part.** MIT, 1,002★, pushed 2026-07-29, 131 releases. Its scorers run
standalone with no login **[verified]**: `Levenshtein().eval(output=…, expected=…)` → `Score(...)`.
Same category as openevals' deterministic evaluators. No LangGraph awareness.

### 2.6 MLflow LLM Evaluate

`mlflow` 3.15.1 (2026-08-03) · Apache-2.0 · 27.5k★ · very active. The only candidate that is both
fully OSI-licensed and fully self-hostable with no license key.

**It works offline** **[verified]**:

```python
os.environ["MLFLOW_TRACKING_URI"] = "sqlite:///mlflow.db"
res = mlflow.genai.evaluate(data=data, predict_fn=predict_fn, scorers=[my_scorer])
# → {'n_states_match/mean': np.float64(0.5)}
```

Four findings from running it:

1. **The file store is no longer allowed.** `file://…` (the old `./mlruns/`) now raises
   `MlflowException: The filesystem tracking backend … is in maintenance mode and will not receive
   further updates. Please migrate to a database backend` **[verified]**. A SQLite DB is mandatory
   (or the `MLFLOW_ALLOW_FILE_STORE=true` escape hatch). Results live in that DB and the MLflow UI —
   **not** as the committed per-task files decision #13 requires.
2. **The LangChain autolog window excludes NetGent's pin.** `mlflow.langchain.autolog()` documents
   compatibility as `1.0.0 <= langchain <= 1.3.14` **[verified from the docstring]**; NetGent's
   `pyproject.toml` requires `langchain>=1.3.15`. NetGent is, today, exactly one patch release outside
   the supported range.
3. **Heavy**: 89 packages / 507 MB **[verified]** — roughly 8× the openevals footprint.
4. Interesting meta-fact: `mlflow/genai/scorers/` ships adapters for **deepeval, phoenix, ragas, and
   trulens**. MLflow is positioning as the neutral layer above the others. If NetGent ever wanted a
   platform, this is the least lock-in-prone one — but "least lock-in-prone platform" is still a
   platform.

---

## 3. What comparable projects actually do

The prior survey ([`../browser-agents.md`](../browser-agents.md) §2) found hand-rolled eval harnesses
everywhere across 32 repos. **Verified, and the finding holds.**

*Method:* fetched the dependency manifests of browser-use, Skyvern, Notte, Agent-E, WebArena, HUD,
Webwright, SeeAct, and Bananalyzer and grepped for
`deepeval|ragas|phoenix|promptfoo|braintrust|mlflow|openevals|agentevals|langsmith|langchain|langgraph|arize|trulens|opik|langfuse`;
then ran GitHub code search for `openevals|agentevals|deepeval|ragas|promptfoo` scoped to browser-use,
Skyvern, Stagehand, Notte, nanobrowser, Lumen, steel-browser, and hud-python. Positive control:
`litellm` and `playwright` are found in Skyvern's manifest, so the greps are live.

**Result: 0 hits in every repo, for every library, in both passes — with exactly one exception.**

**Stagehand** carries `"braintrust": "^0.4.10"` in `packages/evals/package.json` plus a
`report:core → render-braintrust-core-report.ts` script. Consistent with what batch-1 recorded: runs
stream to Braintrust **only when `BRAINTRUST_API_KEY` is set**, and the default path is hand-rolled
`scoring.ts` (`exactMatch`, `passRate`, `errorMatch`). So even the one adopter uses it as an *optional
dashboard sink*, not as the scoring framework.

That is the state of the art among the projects NetGent is directly comparable to: **1 of 32 repos uses
1 of these 9 libraries, optionally, for reporting only.** Everyone else — including the two closest
institutional peers, SeeAct (OSU NLP) and WebArena (CMU) — writes the runner, the judge call, and the
results dump by hand.

---

## 4. Fit analysis

### 4.a Compile-pipeline evals — is agentevals the answer?

No, and the reason is a category error rather than a quality problem.

**The trajectory is not the artifact.** NetGent's compile pipeline is a four-node DAG with two
documented back-edges ([`OVERVIEW.md`](../OVERVIEW.md) §3.1). Its node sequence is *fixed by
construction*: `__start__ → planner → discovery → generator → validator`. `graph_trajectory_strict_match`
compares exactly that sequence — so the only bit of information it can return is **how many times a
back-edge fired**, which is an integer you get from `pipeline.py` incrementing a counter. Adopting
agentevals to learn it means adding a LangGraph checkpointer to a batch job that has no other use for
one.

**What a compile eval must actually assert** is a property of the *emitted NFA*, not of the run that
emitted it: state count and distinctness (the Twitch dual-match bug class, decision #8 / `github-recon.md`),
guard-conjunct well-formedness, every edge carrying exactly one atomic action from the closed set
(decision #2), no ambiguous locators (decision #8), locator chains that deserialize, no fixed sleeps
(`browser-layer-design.md` §3: *"every remaining fixed sleep is a bug report"*). These are pydantic-level
assertions over a JSON artifact. **agentevals has nothing for this.** `openevals.json.create_json_match_evaluator`
is the closest fit — recursive dict comparison against a reference NFA — but it is domain-blind: it
cannot know that a reordered locator fallback ladder is fine while a changed guard conjunct is not. The
domain rule is the entire content of the evaluator, and you write it either way.

**The one genuine fit** is narrower than the headline: agentevals' *tool-call* trajectory matchers
(`subset`/`superset`/`unordered`) map well onto the **Discovery agent's action log** — "did discovery
click the things it was supposed to click, in any order?" That is a real tool-call trajectory. The
catch is that NetGent's action IR is a pydantic discriminated union, not OpenAI-format messages with
`tool_calls`, so it needs an adapter — and behind the adapter, superset-match on names plus args is
~40 lines. Take the *idea* (name the four match modes explicitly; make `superset` the default so
extra exploration isn't punished); skip the dependency.

### 4.b End-to-end workflow evals — does anything beat the hand-rolled harness?

No, and here the argument is structural rather than a judgment call.

**Nothing LangGraph-shaped can reach this surface.** `netgent run` makes zero LLM calls and imports no
framework. There is no graph, no trace, no callback handler, no OTel span. agentevals, Phoenix,
DeepEval's callback integration, and MLflow autolog are all inapplicable by construction.

What is left is the generic part: a task set, a concurrent runner, an LLM judge, and per-task result
files. Scoring each:

- **`langsmith.evaluate(upload_results=False)`** supplies the runner and concurrency. It costs you
  hand-built `Example` objects, a beta warning, a LangChain-dialect model string that contradicts
  `.env.example`, and **no persistence**. The concurrency it provides is `asyncio.gather` with a
  semaphore.
- **openevals' judge factory** supplies `create_llm_as_judge`. It costs a mandatory `langchain-openai`
  and a second model-string dialect. The judge itself is one structured-output call — which NetGent
  already needs a seam for (decision #15: *"all model calls behind a single call-site seam"*). Routing
  the judge through a *different* client than the pipeline defeats that seam.
- **Every platform** (LangSmith, Braintrust, Confident AI, Phoenix, MLflow) stores results in a
  dashboard or a database. **Decision #13 requires committed raw per-task results** so reported numbers
  stay verifiable — the practice `browser-agents.md` §4 takeaway 5 singles out as the thing almost
  nobody does. Not one library writes that file. You write the artifact layer regardless, and once
  you've written it the runner above it is ~50 lines.
- **Trace fidelity**, the headline metric, is unsupported everywhere.

The hand-rolled harness every surveyed browser agent converged on isn't a shortcut they took for lack
of options. It's what the shape of the problem produces.

---

## 5. Comparison table

| Library | What it evaluates | LangGraph integration | Offline / cloud | Maturity (2026-08-17) | License | Verdict |
|---|---|---|---|---|---|---|
| **LangSmith SDK** `evaluate()` | Any target fn over a dataset; runner + concurrency + experiment diffing | Traces LangGraph natively (`@traceable`) | Offline via `upload_results=False` **[verified]**, but *beta*, needs `Example` objects, no on-disk output. Self-host = **Enterprise + license key**; free tier caps at **1 seat** | Very mature: 521 releases, active daily | MIT SDK / closed server | **Skip for scoring.** Already in the tree — keep as optional *tracing* only |
| **openevals** | LLM-as-judge + ~30 prebuilt prompts; deterministic json/exact/Levenshtein | Indirect (judges outputs, not graphs) | Fully offline **[verified]**; no LangSmith key needed | Coasting — last 10 commits all Dependabot; 0.2.0 Apr 2026 | MIT | **Partially adopt — vendor the prompts, not the package** |
| **agentevals** | Tool-call trajectory match (4 modes); graph-trajectory strict match + LLM judge | The only *native* one: `extract_langgraph_trajectory_from_thread` | Fully offline **[verified]**; **requires a checkpointer** | **Dormant** — last release 2025-07-24 (13 mo), still 0.0.x, backlog unattended 15 mo | MIT | **Skip.** Graph matcher is 12 lines; steals the wrong signal |
| **DeepEval** | 40+ metrics incl. `task_completion`, `plan_adherence`, `tool_correctness`, `g_eval` | Yes — LangChain `CallbackHandler()`, but traces target Confident AI | Local `evaluate()` works **[verified]**; needs `OPENAI_API_KEY` even for deterministic metrics **[verified]**; PostHog telemetry on by default | Very active (516 releases, daily) | Apache-2.0 | **Skip.** Injects 5 pytest plugins into a repo whose CI gate is pytest |
| **Ragas** | RAG metrics + `goal_accuracy` / `tool_call_accuracy` | `integrations/langgraph.py` exists | Offline-capable | **Dormant** — last commit 2026-02-24; org moved to `vibrantlabsai` | Apache-2.0 | **Skip.** Wrong shape (no retrieval surface) + dormant |
| **Arize Phoenix** | Observability platform; `phoenix-evals` sub-package | Yes — OTel via `openinference-instrumentation-langchain` | Self-host free (`phoenix serve`); needs a running server + collector | Very active (683 releases) | **Elastic-2.0** (not OSI) | **Skip.** A server for a job run monthly; ELv2 is a review item |
| **promptfoo** | Declarative prompt comparison + red-teaming | **None** — 0 code-search hits **[verified]**; Python provider is a black box | Fully local, CI-friendly | Very active, 24.3k★ | MIT | **Skip.** No LangGraph awareness; adds Node to a Python repo |
| **Braintrust** | Hosted experiment tracking + scoring | None specific | **Hard-fails with no API key [verified]**; free tier = 14-day retention; self-host Enterprise-only | Very active | SDK Apache-2.0 / closed platform | **Skip.** Only true lock-in in the survey |
| ↳ `autoevals` | Standalone scorers (Levenshtein, ExactMatch, LLM judges) | None | Fully offline, no login **[verified]** | Active (131 releases) | MIT | **Optional** — same niche as openevals' deterministic set |
| **MLflow** `genai.evaluate` | Scorers + judges over a dataset; adapters for deepeval/phoenix/ragas/trulens | `mlflow.langchain.autolog()` covers LangGraph — but pinned `langchain <= 1.3.14`, NetGent needs `>=1.3.15` **[verified]** | Fully offline, no license key — but **requires a SQLite backend** (file store now blocked **[verified]**); results in a DB, not files | Very active, 27.5k★ | Apache-2.0 | **Skip for now.** 507 MB + a DB for an offline batch job; results aren't git-committable |

---

## 6. Recommendation

### 6.1 The decision

**Skip all of them. Hand-roll `netgent eval`. Vendor openevals' judge prompts.**

This is the same conclusion `agent-frameworks.md` §5 reached about the orchestration layer, arrived at
independently: the pipeline is small and known-shape, the artifact is typed, and the generic machinery
these libraries sell (a runner, a judge call, a results table) is smaller than the integration cost of
any of them.

### 6.2 Per library, with the deciding evidence

| Library | Verdict | The one fact that decides it |
|---|---|---|
| **openevals** | **Partially adopt** — copy prompts, not the package | The prompts are MIT-licensed plain string constants. `PLAN_ADHERENCE_PROMPT` is *exactly* the Validation Agent's rubric. Taking the file costs nothing; taking the package costs a mandatory `langchain-openai` and a second model-string dialect that contradicts `.env.example` |
| **LangSmith** | **Keep as tracing; skip `evaluate()`** | Already a hard transitive dep of `langchain-core` **[verified]** — tracing is free and off by default. But `evaluate()`'s offline path is beta, needs hand-built `Example` objects, and persists nothing; its actual value is the hosted UI, which is 1 seat free or $39/seat |
| **agentevals** | **Skip** | Last release 13 months ago, still 0.0.x — and `graph_trajectory_strict_match` is a 12-line list comparison that would report a node sequence fixed by construction, in exchange for adding a checkpointer NetGent doesn't otherwise need |
| **DeepEval** | **Skip** | Installs `pytest-xdist`/`pytest-repeat`/`pytest-rerunfailures` as *runtime* deps **[verified]** into a repo whose CI gate is pytest (decision #13). Plus: `ToolCorrectnessMetric()` demands an OpenAI key to do set comparison **[verified]** |
| **Ragas** | **Skip** | Six months dormant + an org transfer, and its metric family assumes a retrieval surface NetGent doesn't have |
| **Phoenix** | **Skip** | Elastic-2.0, and it's a server-based observability platform. Evals that run offline a few times a semester don't justify an OTel collector |
| **promptfoo** | **Skip** | Zero LangGraph awareness **[verified]**; the Python provider sees only final output. Also Node |
| **Braintrust** | **Skip** | `Eval()` raises without an API key **[verified]**. Free-tier retention is 14 days — results referenced by a paper cannot live there |
| ↳ `autoevals` | **Optional** | Works offline with no login **[verified]**; MIT. Reach for it only if you want Levenshtein/embedding scorers without writing them |
| **MLflow** | **Skip now, revisit if the lab wants a platform** | The only fully-OSI, fully-self-hostable option — but 507 MB, a mandatory SQLite backend, results in a DB instead of committed files, and an autolog support window that excludes NetGent's pinned `langchain>=1.3.15` **[verified]** |

### 6.3 On the cloud-lock-in question

Decision #15 named "LangSmith logging" as a motivation for choosing LangChain+LangGraph. That motivation
survives this survey intact, because **tracing and evaluation are separable**:

- **Tracing** is opt-in per-environment (`LANGSMITH_TRACING`, off by default), costs nothing when off,
  and is genuinely useful for debugging a compile run. `LANGSMITH_API_KEY` is already a slot in
  `.env.example`. Keep it.
- **Evaluation** is where the gravity starts. Once datasets live in LangSmith, the task set stops being
  a git-versioned JSONL under `evals/datasets/` and becomes a row in someone's cloud tenant — which
  breaks decision #13's verifiability property and ties the paper's numbers to a seat someone has to
  keep paying for. Self-hosting out is Enterprise-only with a sales-issued license key.

For a university lab the practical exposure isn't the trace quota, it's the **1-seat cap on the free
tier**. A four-person project on the free tier means one person owns all the data. That is a bad
place for a paper's evaluation record to live.

### 6.4 What to build instead

`netgent eval` needs roughly 200 lines, all of which you'd write anyway as the artifact layer under any
library:

```
src/netgent/eval/
  dataset.py    # load evals/datasets/*.jsonl -> list[EvalTask] (pydantic)
  runner.py     # asyncio.gather + Semaphore over tasks; N runs per task
  judge.py      # ONE call through the agent/ model seam (decision #15), pydantic-schema'd verdict
  scoring.py    # success rate, pass@k, self-report-vs-judge alignment, trace-fidelity stats
  report.py     # write evals/results/<dataset>-<model>-<date>/{per_task.jsonl,summary.json}
```

Four methodology points, all from the existing survey rather than from this one
([`../browser-agents.md`](../browser-agents.md) §4):

1. **Few tasks × many runs** beats one pass over a big set — variance is the binding constraint
   (Notte's WebVoyager30 ×8).
2. **Unit-test `scoring.py`** in `tests/`. A silent grader bug corrupts every number reported
   (takeaway 2, from WebShop).
3. **Commit raw per-task results.** The practice that distinguishes Skyvern's credible 85.8% from
   Browserable's unsupported 90.4% (takeaway 5).
4. **Report judge-vs-self-report alignment**, not just success rate — Notte measured browser-use
   over-claiming at 1.14–1.53×.

And two NetGent-specific ones from this analysis:

5. **Compile-pipeline evals assert on the artifact, not the trajectory.** Structural NFA checks
   (distinctness, one-atomic-action-per-edge, no ambiguous locators, no fixed sleeps) belong in
   `tests/` as pure pydantic assertions; only the "is this graph *sensible*" judgment needs an LLM and
   belongs in `evals/`.
6. **Name the match mode for Discovery action logs** — take agentevals' `strict`/`unordered`/`subset`/
   `superset` vocabulary and default to `superset`, so extra exploration isn't scored as failure.

### 6.5 What would change this

Revisit if any of these become true:

- **agentevals ships a 0.1.0 with a non-Dependabot changelog** and adds partial-credit graph matching
  (issue #49). Right now it's 13 months cold at 0.0.x.
- **NetGent adopts agentic edges** (open decision in [`OVERVIEW.md`](../OVERVIEW.md) §7.3). If some
  edges stay LLM-driven at *run* time, surface (b) acquires a real trajectory and the trajectory
  matchers become applicable.
- **The lab standardizes on an experiment tracker** across projects. Then MLflow — Apache-2.0, no
  license key, self-hosted — is the one to pick, and `mlflow.genai`'s adapters for
  deepeval/phoenix/ragas make it the least lock-in-prone entry point.
- **LangSmith self-hosting stops being Enterprise-gated**, or the free tier's 1-seat cap lifts.

---

## Appendix A — Reproducing this survey

```bash
mkdir -p /tmp/ng-evals && cd /tmp/ng-evals

# repo + release metadata
for r in langchain-ai/openevals langchain-ai/agentevals langchain-ai/langsmith-sdk \
         confident-ai/deepeval explodinggradients/ragas Arize-ai/phoenix \
         promptfoo/promptfoo braintrustdata/braintrust-sdk mlflow/mlflow; do
  gh api "repos/$r" --jq '{full_name, stars:.stargazers_count, pushed_at, archived, license:.license.spdx_id}'
done
# note: explodinggradients/ragas 301-redirects to vibrantlabsai/ragas
gh api "repos/langchain-ai/agentevals/commits?per_page=10" \
  --jq '.[] | "\(.commit.author.date[0:10]) \(.commit.message|split("\n")[0])"'   # all Dependabot
gh api repos/langchain-ai/agentevals/issues/40 --jq '{title, created_at, state}'  # open 15 months

# PyPI release cadence + downloads
for p in openevals agentevals langsmith deepeval ragas arize-phoenix braintrust mlflow; do
  curl -s "https://pypi.org/pypi/$p/json" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['info']['version'])"
  curl -s "https://pypistats.org/api/packages/$p/recent"
done

# behavioural checks (each in its own venv)
uv venv .venv-oe --python 3.12 && uv pip install -p .venv-oe openevals agentevals langsmith
uv venv .venv-mlf --python 3.12 && uv pip install -p .venv-mlf mlflow
uv venv .venv-bt  --python 3.12 && uv pip install -p .venv-bt  braintrust autoevals
uv venv .venv-de  --python 3.12 && uv pip install -p .venv-de  deepeval

#  1. openevals/agentevals offline, no keys        -> plain dicts, no network
#  2. langsmith evaluate(upload_results=False) with LANGSMITH_ENDPOINT=http://127.0.0.1:9
#                                                  -> exit 0; requires schemas.Example, not dicts
#  3. agentevals extract_langgraph_trajectory_from_thread on a 4-node graph
#       without a checkpointer                     -> ValueError: No checkpointer set
#       with Send fan-out / Command(goto=)         -> both extract correctly (issue #40 not reproducible)
#  4. openevals create_llm_as_judge(model="gemini/gemini-2.5-pro")
#                                                  -> resolves to ChatVertexAI, wants langchain-google-vertexai
#  5. mlflow.genai.evaluate with file:// store     -> MlflowException, file store blocked; sqlite:// works
#  6. braintrust.Eval() with no BRAINTRUST_API_KEY -> ValueError: Could not login to Braintrust
#  7. deepeval ToolCorrectnessMetric() ctor        -> DeepEvalError: OpenAI API key is not configured
#  8. pip metadata: langchain-core requires langsmith<1.0.0,>=0.3.45 (already in netgent[generate])

# adoption check across the surveyed browser agents (expect: zero hits)
for r in browser-use/browser-use Skyvern-AI/skyvern nottelabs/notte EmergenceAI/Agent-E \
         hud-evals/hud-python microsoft/Webwright reworkd/bananalyzer; do
  gh api "repos/$r/contents/pyproject.toml" -H "Accept: application/vnd.github.raw" \
    | grep -iE "deepeval|ragas|phoenix|promptfoo|braintrust|mlflow|openevals|agentevals|langsmith"
done
gh api "repos/browserbase/stagehand/contents/packages/evals/package.json" \
  -H "Accept: application/vnd.github.raw" | grep -i braintrust   # the sole exception
```

## Appendix B — Source cross-references

- [`../OVERVIEW.md`](../OVERVIEW.md) §3.1 (compile pipeline), §7.2 decisions #10, #13, #15, §7.3 (agentic edges, open)
- [`../browser-agents.md`](../browser-agents.md) §2 (eval patterns across 32 repos), §4 (takeaways 1–5)
- [`agent-frameworks.md`](agent-frameworks.md) §5 (custom pipeline recommendation; same reasoning applied to orchestration)
- [`browser-agents-batch-1.md`](browser-agents-batch-1.md) §Stagehand/Evals (the Braintrust exception)
- [`../../evals/README.md`](../../evals/README.md) (the `datasets/` + `results/` contract this must satisfy)
