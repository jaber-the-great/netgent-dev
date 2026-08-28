# Verification & completion-checking literature (2000–2026) — for NetGent v2's verifier

*Scope: **academic papers only** (open-source repos are the sibling survey, `agent-verification.md`).
Every number below was read from the paper's arXiv abstract/HTML, ACL Anthology, OpenReview or
publisher page during this review. Anything I could not read in a paper's own text is in §7
("claims I could not verify") rather than asserted here.*

## Summary (10 lines)

1. **Self-reported `done(success=True)` is the weakest signal available.** StressWeb measures a
   **5.3×** claimed-to-actual success ratio under semantic perturbation; AgentRewardBench shows judges
   are fooled by exactly this ("misleading agent reasoning" is a named failure class).
2. **But programmatic oracles are *also* wrong — in the other direction.** Rule-based eval
   underreports real success by **16.7 pts** (WebArena) and **18.5 pts** (VisualWebArena); recall **55.9%**.
   NetGent's `_form_succeeded` marker check is a rule-based oracle and will have the same false-negative bias.
3. **No LLM judge exceeds ~70% precision on agent trajectories** (best: GPT-4o **69.8%**,
   AgentRewardBench). WebJudge reaches **~85% human agreement / 3.8 pt SR gap** on Online-Mind2Web, but
   only **73.7%** precision on AgentRewardBench. Judges are a *ranking/triage* tool, not an authority.
4. **State-diff oracles beat both.** τ-bench compares the final database to an annotated goal state —
   deterministic, no LLM. WorkArena's `validate()` queries the DB; WebArena's `program_html` locates
   page content. This is the family NetGent should compile into.
5. **Verification is what makes induced skills survive.** Voyager's ablation: removing self-verification
   costs **73%** of discovered items — the single most important feedback component. SKILL.nb's gated
   execution retains **91.7%** of successes across three re-executions (**+15.5 pts** over next best).
6. **Guards derived from *failed* traces are the highest-leverage artifact**: ReUseIt 24.2% → **70.1%**
   by attaching pre/post condition checks + fallbacks to workflow steps. This is NetGent's state-condition idea, measured.
7. **Intrinsic self-correction does not work; external signal does.** GPT-4 GSM8K **95.5% → 89.0%**
   after two self-correction rounds; **→ 97.5%** with an oracle label. CRITIC, Reflexion and Self-Debug
   all get their lift from *tool/environment* feedback, not introspection.
8. **Step-level beats outcome-level supervision** where you can afford it: PRM **78.2%** vs ORM **72.4%**
   vs majority **69.6%** on MATH; GUI-Shepherd **+5.1 pts** as a verifier on AndroidWorld.
9. **Feedback form matters more than feedback presence.** Self-repair gains are "often modest… sometimes
   not present"; they grow substantially only when feedback quality is raised (Olausson, ICLR 2024).
   Magentic-One's structured Progress Ledger is worth **31%** of GAIA performance in ablation.
10. **The 25-year-old oracle literature already named our problem**: Barr et al. TSE 2015 — specified /
    derived / implicit / no-oracle. NetGent is trying to move web-agent verification from *implicit*
    (`done`) to *specified* (conditions on states). AgentLTL and WebTestPilot are the 2026 versions.

---

## How to read the "relevance" verdicts

NetGent's pipeline is `explore` (one LangGraph LLM agent → `AgentTrajectory`) → `generate`
(pure code → an NFA `Workflow`: states carry trigger conditions, transitions carry one atomic action) →
`validate` (`validate_workflow()`: fresh `BrowserSession` per param set, `Executor` replay, first failing
edge reported, **zero LLM**). The only completion signal at explore time is the explorer's own
`Decision.done` + `Decision.success` boolean (`agent/explorer/decision.py:170-172`). The one
page-observed oracle in the repo today is `evals/sweep.py::_form_succeeded`, which checks three
walker-read sources (dialogs raised this attempt, marker text the agent's observations *saw*, marker
text still visible in the frame) and deliberately ignores the agent's self-report.

So a paper is relevant when it changes (a) what evidence closes an exploration episode, (b) what the
compiler can turn into a *checkable* state condition, (c) what the zero-LLM replay should assert, or
(d) what the failed-replay report should hand back to the explorer.

---

# 1. Web/GUI-agent evaluators and judges (2023–2026)

## 1.1 The auto-evaluators everyone cites

### WebVoyager — He et al., ACL 2024 · [arXiv:2401.13919](https://arxiv.org/abs/2401.13919)

**Mechanism.** An LMM agent on 15 live websites, **643 tasks**. Its lasting contribution is the
**GPT-4V auto-eval protocol**: the judge is given the task, the agent's final textual response, and the
last *k* screenshots, and returns success/failure.

**Numbers.** Agent SR **59.1%**. Auto-eval agreement with human annotators scales with evidence:
k=1 screenshot **75.3%** (κ=0.51) → k=2 **79.7%** (κ=0.59) → k=3 **81.3%** (κ=0.62) → **full
trajectory 85.3%** (κ=0.70), which matches inter-human Fleiss' κ=0.7. Failure taxonomy over 300 failed
tasks: navigation stuck 44.4%, visual grounding 24.8%, **hallucination 21.8%**, prompt misalignment 9.0%.

**Relevance to NetGent's verifier.** The κ-vs-k curve is the single most actionable design fact in this
whole survey: **judge agreement is a function of how much of the trajectory you show it**, and a
one-screenshot judge is 10 points worse than a full-trajectory judge. If we ever add a trajectory
judge, feed it the whole `AgentTrajectory`, not the last observation. Also: 21.8% of failures are
hallucination — i.e. the agent's own narration is wrong — which is precisely what `done` reports.

### An Illusion of Progress? / Online-Mind2Web / **WebJudge** — Xue et al., COLM 2025 · [arXiv:2504.01382](https://arxiv.org/abs/2504.01382)

**Mechanism.** 300 realistic tasks over 136 live websites. **WebJudge** is a three-stage judge:
(1) *key-point identification* — extract from the task description the checkable sub-goals;
(2) *key-screenshot identification* — select only the screenshots relevant to those key points;
(3) *outcome judgement* over that filtered evidence. The filtering step is the trick: it stops the
judge drowning in a 40-step trajectory.

**Numbers.** WebJudge (GPT-4o) **~85% agreement** with human judgement and an **average success-rate
gap of 3.8 pts**; with o4-mini **85.7%** agreement, same 3.8 pt gap; a distilled **WebJudge-7B** hits
**87%** agreement / 3.9 pt gap with **two API calls per trajectory**. Cross-checked on
AgentRewardBench, WebJudge scores **73.7% precision** and a **5.9%** SR gap vs rule-based methods'
9.8%. Agents on Online-Mind2Web: Operator **61.3%**, Claude CU 3.7 **56.3%**, SeeAct **30.7%**,
Browser Use **30.0%**, Agent-E **28.0%**, Claude CU 3.5 **29.0%**. The headline indictment: a *trivial
search agent* scores **51%** on WebVoyager but **22%** on Online-Mind2Web.

**Relevance to NetGent's verifier.** Key-point extraction is the closest published thing to what
NetGent's compiler should do: **turn the natural-language task into a small set of checkable
sub-goals, then check each against page evidence.** Our advantage is that we don't need screenshots —
our key points can compile into `selector_visible` / `url_matches` / `title_contains` triggers, which
are *free and deterministic* to evaluate at replay. Also note the 85% agreement is a ceiling for a
strong judge on a curated benchmark; treat 85% as optimistic for our sites.

### AgentRewardBench — Lù et al., 2025 · [arXiv:2504.08942](https://arxiv.org/abs/2504.08942)

**Mechanism.** The reference measurement of *how good automatic evaluation of web-agent trajectories
actually is*: **1,302 trajectories** from 4 LLMs over **5 benchmarks**, each expert-annotated by 6
annotators on three questions — *was the action sequence successful? did the agent perform unnecessary
actions with side effects? did it loop without progress?* (**89.3%** inter-annotator agreement on
success labels for GPT-4o trajectories). **12 LLM judges** are then scored against those labels.

**Numbers.** Best judge precision: **GPT-4o 69.8%**, Claude 3.7 Sonnet **68.8%**, Qwen2.5-VL **64.3%**;
prior methods AER-C **67.7%**, AER-V **67.6%**, NNetNav **52.5%**. **No judge exceeds 70% precision.**
Recall is high (GPT-4o **83.1%**, Qwen2.5-VL **89.8%**, Claude **81.6%**, NNetNav 82.4%, AER-C 71.9%) —
i.e. judges are *permissive*: they say yes too often. Rule-based evaluation is the mirror image:
recall **55.9%**, and it underreports success by **16.7 pts on WebArena** (42.3% expert vs 25.6%
rule-based, GPT-4o), **18.5 pts on VisualWebArena** (35.9% vs 17.4%), **6.2 pts on WorkArena** (56.2%
vs 50.0%) and **13.8 pts on WorkArena++** (18.4% vs 4.6%). On AssistantBench the rule-based check has
**25.0%** precision vs GPT-4o's 77.8%. **Side-effect detection is a disaster**: precision 14.0%
(Claude), 9.0% (Qwen2.5-VL), 7.7% (GPT-4o). Named judge failure modes: grounding mismatch, **misleading
agent reasoning** (judges believe the agent's false completion claims), missed instruction details
(cart-not-purchase), misunderstood final-action intent. Ablation: **more input distracts** — screenshots
alone beat screenshots + a11y tree.

**Relevance to NetGent's verifier.** This is the paper that sets the authority level. Two operational
rules fall straight out: (i) an LLM judge may **never** be the sole gate for accepting a workflow —
at ~70% precision, 3 in 10 accepted workflows are wrong; (ii) our rule-based `_form_succeeded` markers
have a *known, quantified* false-negative bias of the same order (rule-based recall 55.9%), so a
"not verified" verdict in the sweep should trigger a retry (it does) and should **not** be logged as
agent failure. The right architecture is the one this paper implies but doesn't build: **rules decide
`yes`, a judge only ever escalates `no`.**

### Autonomous Evaluation and Refinement of Digital Agents — Pan et al., COLM 2024 · [arXiv:2404.06474](https://arxiv.org/abs/2404.06474)

**Mechanism.** Two domain-general evaluator designs: an **end-to-end VLM evaluator** (instruction +
action sequence + screenshots → reasoning → success/fail) and a **modular captioner-then-reason**
evaluator (fine-tuned QWen-VL captions each screenshot; Mixtral or GPT-4 reasons over the text). Those
evaluators are then used two ways: **inference-time guidance** (Reflexion-style retry driven by the
evaluator) and **filtered behaviour cloning** (keep only evaluator-approved trajectories for training).

**Numbers.** Evaluator agreement with oracle: WebArena — captioner+GPT-4 **82.1%**, GPT-4V **80.6%**,
captioner+Mixtral **74.4%**; Android-in-the-Wild — captioner+Mixtral **92.9%**, GPT-4V **90.6%**,
captioner+GPT-4 **89.8%**. Refinement: from a 14.4% WebArena baseline, 3 reflexion rounds give
**+16%** (Mixtral evaluator), **+23%** (GPT-4V), up to **+29%** relative (captioner+GPT-4). iOS device
control: CogAgent 8/52 → 11/52 (self-training) → **14/52** with evaluator-filtered BC (**~75%**
relative). Aside worth keeping: **~36% of the *human* demonstrations contained actual failures.**

**Relevance to NetGent's verifier.** The strongest published evidence that a *separate* evaluator pays
for itself twice — once as a retry trigger (our sweep already does this with a rule oracle) and once
as a **trajectory filter before compilation**. NetGent compiles a trajectory into an NFA; compiling a
silently-failed trajectory produces a permanently broken workflow, so a filter at the `explore →
generate` boundary is the highest-value place to spend an LLM call. The 36% figure also warns against
assuming any single exploration run is clean.

### Agent-as-a-Judge — Zhuge et al., 2024 · [arXiv:2410.10934](https://arxiv.org/abs/2410.10934)

**Mechanism.** Instead of one LLM judging a final answer, an *agentic* judge with tools (read the
workspace, locate files, trace requirement→artifact) evaluates each of a task's hierarchical
requirements. Benchmark: **DevAI**, 55 AI-development tasks with **365 hierarchical requirements**.

**Numbers.** Alignment with human consensus (black-box): OpenHands **90.44%** vs LLM-as-a-Judge
**60.38%**; GPT-Pilot **83.88%** vs 65.30%; MetaGPT **88.52%** vs 84.15%. Gray-box: **92.07% / 86.61% /
90.16%**. Judge shift from human consensus: Agent-as-a-Judge **0.27% / 8.20% / 3.26%** vs LLM-as-a-Judge
up to **31.42%**. Cost: **$30.58** and **118.43 min** vs **~$1,297.50** and **86.5 h** of human
evaluation — **97.71%** cheaper, **97.64%** faster. Individual human raters disagree pairwise
**~10–30%**; consensus reduces individual error to **~6.01%**.

**Relevance to NetGent's verifier.** Two transferable ideas. (1) **Decompose the goal into requirements
and judge each separately** — a 30-point alignment gain over monolithic judging, and it maps exactly
onto per-state conditions in our NFA. (2) **Give the judge tools.** Our judge doesn't need vision: it
needs `snapshot()`. A verifier that can re-query the DOM is a gray-box judge, and gray-box beat
black-box in every DevAI row.

## 1.2 Programmatic / oracle-function benchmarks (the family NetGent belongs to)

### WebArena — Zhou et al., ICLR 2024 · [arXiv:2307.13854](https://arxiv.org/abs/2307.13854)

**Mechanism.** 812 tasks, **execution-based reward**, two evaluator families. For information-seeking:
`exact_match` ("only a predicted answer identical with reference receives score of one"), `must_include`
("any predicted answer containing the reference receives score of one"), and `fuzzy_match` (GPT-4 judges
semantic equivalence, e.g. "2h58min" ≡ "2 hour 58 minutes"). For navigation/config tasks: `program_html`
— a **locator** (DB query, API call, or JS element selection) retrieves the critical content, then
keyword verification runs `exact_match`/`must_include` over it.

**Numbers.** GPT-4+CoT **11.70%**, best reported agent **14.41%**, human **78.24%**. Fuzzy-match
sanity check: GPT-4 got **100%** on 900 date and 900 duration examples; 40 manually-checked examples
gave **97.5%** agreement.

**Relevance to NetGent's verifier.** `program_html` *is* the design NetGent should generate:
locator + expected content, evaluated with no model in the loop. Note that WebArena's authors already
concede this class of oracle causes false negatives — AgentRewardBench then measured it at 16.7 pts.
So: emit program_html-style checks, but never treat a failed one as proof of agent failure without a
second look.

### VisualWebArena — Koh et al., ACL 2024 · [arXiv:2401.13649](https://arxiv.org/abs/2401.13649)

**Mechanism.** **910 tasks** (25.2% with input images) across Classifieds/Shopping/Reddit. Adds two
*visual* oracle primitives to WebArena's set: `eval_vqa` ("queries a VLM capable of performing visual
question answering… with an image and a question") and `eval_fuzzy_image_match` (structural similarity
index, SSIM, against a ground-truth image), plus `must_exclude` for negative constraints.

**Numbers.** GPT-4V+SoM **16.37%**, Gemini-Pro **6.04%**, LLaVA-7B **2.75%**, **human 88.70%**.

**Relevance to NetGent's verifier.** `must_exclude` is the primitive our trigger set is missing: today
NetGent can say `selector_visible` / `selector_hidden` but has no "this text must NOT appear" check.
An error-banner-absent condition is cheap and catches the most common silent form failure. The SSIM
oracle is a reasonable escape hatch for canvas/chart pages where the DOM says nothing.

### WorkArena / BrowserGym — Drouin et al., 2024 · [arXiv:2403.07718](https://arxiv.org/abs/2403.07718)

**Mechanism.** 33 ServiceNow task templates, **19,912 unique instances** (lists 12/6,900; forms
5/5,000; KB 1/1,000; service catalogs 9/3,550; dashboards 4/1,862; menus 2/1,600). Every task ships a
`validate()`: list tasks use **client-side validation** that the resulting list satisfies the expected
conditions; form and catalog tasks **query the database** for entries/orders the agent created;
dashboard tasks check the agent's response contains the right numbers and labels. Crucially, every task
also ships an **oracle function** — "hand-crafted solutions that automatically complete the tasks using
Playwright" — used to prove feasibility, produce ground truth, and detect benchmark rot.

**Numbers.** GPT-4o **42.7%** (WorkArena) / 66.1% (MiniWoB) / 23.5% (WebArena); Llama3-70b 17.9% /
62.6% / 11.0%; GPT-3.5 6.1% / 38.9% / 6.7%. List tasks: **0%** across all models.

**Relevance to NetGent's verifier.** The **Playwright oracle solution shipped alongside every task** is
the idea to steal. A NetGent workflow *is* a Playwright oracle: if replay succeeds and the state
conditions hold, the task is demonstrably still feasible. That makes `validate` a benchmark-rot detector
as well as a correctness check — run it on a schedule and it tells you when a site changed, for free.

### WebCanvas / Mind2Web-Live — Pan et al., 2024 · [arXiv:2406.12373](https://arxiv.org/abs/2406.12373)

**Mechanism.** Evaluation for *live* sites via **key nodes**: "indispensable steps… regardless of the
path taken to accomplish a task, these steps are required." **542 tasks, 2,439 intermediate evaluation
states.** Three evaluation targets (URL, element path, element value) × three match functions (exact;
include — URL and value only; semantic via LLM — URL and value only). Metrics: *step score* (1 per key
node reached), *completion rate* (fraction of key nodes), *task success rate* (all key nodes),
*efficiency* = trajectory length / step score.

**Numbers.** Mind2Web-Live test (104 tasks): GPT-4 **48.8% completion / 23.1% task SR** / 2.47
efficiency; GPT-3.5 40.2% / 16.5% / 3.03. Human-labelled reward raised GPT-4 completion to 52.3%.

**Relevance to NetGent's verifier.** Key nodes are literally NetGent states with conditions, and the
URL / element-path / element-value × exact / include / semantic matrix is a ready-made **type system
for our triggers**. The completion-rate metric is what our `ValidationReport` should surface instead of
a bare boolean: `edges_ok` already counts it — expose it as a rate and we get partial credit for free.

### TheAgentCompany — Xu et al., 2024–2025 · [arXiv:2412.14161](https://arxiv.org/abs/2412.14161)

**Mechanism.** **175 tasks** in a simulated software company (SWE 69, PM 28, HR 29, admin 15, DS 14,
finance 12, …), graded by **checkpoints** — intermediate milestones with point values covering action
completion, data accuracy, and colleague collaboration. Score = `0.5·(Result/Total) + 0.5·S_full`,
i.e. half partial credit, half a full-completion bonus.

**Numbers.** Full completion: Gemini-2.5-Pro **30.3%**, Claude-3.7-Sonnet 26.3%, Claude-3.5-Sonnet
24.0%, Gemini-2.0-Flash 11.4%, GPT-4o 8.6%. Partial score: 39.3% / 36.4% / 34.4%.

**Relevance to NetGent's verifier.** The scoring formula is worth copying verbatim into eval reporting:
a binary `validated` flag throws away the information that tells you *where* a workflow broke.
`0.5·edges_ok/edges + 0.5·success` would make the A/B sweeps far more sensitive.

### τ-bench — Yao et al., ICLR 2025 · [arXiv:2406.12045](https://arxiv.org/abs/2406.12045)

**Mechanism.** The cleanest oracle in the field: "the reward of a task episode r = r_action × r_output
∈ {0,1} is based on (1) whether the final database is identical to the unique ground truth outcome
database, and (2) whether the agent's responses contain all necessary information." **Zero LLM
judging on the action side.** Introduces **pass^k** = 𝔼_task[C(c,k)/C(n,k)] — the probability that
*all* k independent trials succeed (vs pass@k = at least one).

**Numbers.** GPT-4o τ-retail **pass^1 61.2%**, **pass^8 <25%**; τ-airline **pass^1 35.2%** and
substantially lower at k=8.

**Relevance to NetGent's verifier.** `pass^k` is the metric NetGent's whole thesis is about: a
compiled zero-LLM workflow should have pass^k ≈ pass^1, and an LLM agent doesn't. **Report pass^k for
both arms in every eval** — it's the number that shows determinism paying off, and it's currently
missing from `ValidationReport` (which runs one replay per param set). Run k≥5 replays per param set.

### GAIA — Mialon et al., 2023 · [arXiv:2311.12983](https://arxiv.org/abs/2311.12983)

**Mechanism.** 466 questions (Level 1: 146, Level 2: 245, Level 3: 75) with a single short factual
answer each, scored by **quasi exact match** "up to some normalization tied to the 'type' of the
ground truth." The authors explicitly reject model-based evaluation: "model-based evaluations… are by
construction dependent of stronger models hence cannot evaluate new state-of-the-art models."

**Numbers.** GPT-4+plugins vs human: L1 **30.3% / 93.9%**, L2 **9.7% / 91.8%**, L3 **0% / 87.3%**.

**Relevance to NetGent's verifier.** The rejection argument applies directly to us. If NetGent's
verifier is an LLM judge, NetGent's measured quality is capped by the judge's model and *changes when
the judge model changes* — which destroys longitudinal eval comparability across our A/B sweeps. Our
oracles must be page-observed and model-free wherever possible; the LLM is a fallback, not the ruler.

### AssistantBench — Yoran et al., 2024 · [arXiv:2407.15711](https://arxiv.org/abs/2407.15711)

**Mechanism.** 214 realistic, time-consuming open-web tasks, automatically evaluable.

**Numbers.** No model exceeds **26 points** accuracy; SOTA web agents score near zero. Closed-book LMs
score well on accuracy but have **low precision and hallucinate facts**.

**Relevance to NetGent's verifier.** The precision/accuracy split is the important framing: a system
that answers everything looks accurate and is untrustworthy. NetGent's equivalent is a workflow that
always reports success. Track **abstention** — a workflow that says "I could not verify" is worth more
than one that says "done".

### ST-WebAgentBench — Levy et al., ICLR 2026 · [arXiv:2410.06703](https://arxiv.org/abs/2410.06703)

**Mechanism.** **222 tasks** paired with explicit **ST policies** — "concise rules that encode
constraints" across six dimensions — and scored by **Completion under Policy (CuP)**, which "credits
only completions that respect all applicable policies," plus a Risk Ratio.

**Numbers.** For three open-source agents, "average CuP is less than two-thirds of their nominal
completion rate."

**Relevance to NetGent's verifier.** CuP is the right shape for a NetGent workflow contract: success is
not "the last state was reached" but "the last state was reached **and** no forbidden state was entered."
Our NFA already has the machinery — a policy is just a `must_exclude`-style trigger evaluated on every
state, not only the terminal one. Cheap to add, and it converts the replay from an end-check into a
monitor (see §4).

### BrowserGym ecosystem — Le Sellier De Chezelles et al., 2024–2025 · [arXiv:2412.05467](https://arxiv.org/abs/2412.05467)

**Mechanism.** One interface over MiniWoB++ (125 templates), WebArena (812), VisualWebArena (910),
WorkArena L1/L2/L3, WebLINX (31,586), AssistantBench (214), plus AgentLab and a **ReproducibilityAgent**
that re-executes action sequences to detect prompt/environment drift, and reproducibility journals
recording software versions, commit hashes, OS, timestamps.

**Numbers.** Claude-3.5 Sonnet / GPT-4o: MiniWoB 69.8% / 63.8%; WorkArena L1 56.4% / 45.5%; L2 39.1% /
8.5%; WebArena 36.2% / 31.4%; VisualWebArena 21.0% / 26.7% — all with **±1.3–3.2% standard error**.
**Documented evaluation caveats**: localisation differences (time zone, language, geography) change
agent behaviour; ads and dynamic content break determinism; "API-based LLMs silently changing";
**agent collisions** where concurrent runs corrupt shared DB state ("if two agents add an item to their
cart concurrently, they may unintentionally update each other's cart"), forcing near-sequential
execution (2–4 parallel); and a scoring artefact — **6.9% on AssistantBench vs 27% on external
leaderboards**, attributed to the harness being "more adapted for action-oriented tasks."

**Relevance to NetGent's verifier.** The most practically useful section in the survey for our eval
harness. Three imports: (i) always report **standard error across seeds** — our sweep results are
single-run today; (ii) a **ReproducibilityAgent** is exactly `validate_workflow` — say so, and log the
journal fields they log; (iii) their AssistantBench artefact is a warning that *the harness itself* can
be the thing under test. When a NetGent A/B shows a delta, rule out the harness before the change.

### HAL / Holistic Agent Leaderboard — Kapoor et al., 2025 · [arXiv:2510.11977](https://arxiv.org/abs/2510.11977) · and Log analysis is necessary… — Kirgis et al., 2026 · [arXiv:2605.08545](https://arxiv.org/abs/2605.08545)

**Mechanism.** HAL runs **21,730 agent rollouts** across 9 models × 9 benchmarks (~$40,000, 2.5B tokens
of logs released) and adds **LLM-aided log inspection**, which surfaced behaviours no outcome metric
would show: agents "searching for the benchmark on HuggingFace instead of solving a task," and
"misusing credit cards in flight booking tasks." The companion position paper argues pass/fail alone
threatens validity three ways — shortcuts/artefacts inflate or deflate scores, benchmark scores fail to
predict real utility because of scaffold limits, and **capability scores conceal dangerous actions**.

**Numbers.** HAL: 21,730 rollouts, 9 models, 9 benchmarks. Kirgis et al.: pass^5 was
**under-elicited by nearly 50%** on τ-bench Airline.

**Relevance to NetGent's verifier.** Direct instruction for us: **the trajectory record is evidence, not
exhaust.** NetGent already writes `--trajectory DIR` with screenshots and records; the finding is that
periodic *log inspection* (even LLM-aided, offline, non-authoritative) catches classes of failure that
`validated: true` never will — e.g. a workflow that "succeeds" by navigating to a cached success page.
Also: the pass^5 under-elicitation result says our replay budget matters; one replay per param set
under-measures.

## 1.3 Verifiers used as training/search signal

### WebRL — Qi et al., ICLR 2025 · [arXiv:2411.02337](https://arxiv.org/abs/2411.02337)

**Mechanism.** Self-evolving curriculum RL. The **ORM** is a binary classifier over (instruction,
action history, final HTML) emitting YES/NO, compared as token probabilities → reward ∈ {0,1}.
**Curriculum from failure**: failed tasks seed new instructions by in-breadth evolution, filtered to
critic scores in **[0.05, 0.75]** (too-easy and too-hard dropped), ~500 new validated instructions per
phase; GPT-4o filters infeasible ones. A **replay buffer** keeps only trajectories with perplexity in
[1/0.95, 1/0.5] under the previous actor — avoiding "over-familiar data and data that remains too
challenging." KL-constrained policy update against the previous phase.

**Numbers.** **ORM accuracy ~80%** on WebArena-Lite test data and rollouts, vs ~71% for GPT-4-Turbo
variants. WebArena-Lite SR: Llama-3.1-8B **4.8% → 42.4%**; GLM-4-9B **6.1% → 43.0%**; vs GPT-4-Turbo
17.6%, GPT-4o 13.9%, AutoWebGLM 18.2%.

**Relevance to NetGent's verifier.** Two things. (1) An **HTML-state ORM at ~80% accuracy** is a
realistic ceiling for a learned "did this work" classifier on final page state — better than a
prompted judge's 69.8% precision, and it's exactly the input NetGent's `snapshot()` already produces.
(2) **Curriculum from failure** is the feedback contract we want: a failed replay should not just be
logged, it should generate the *next* exploration task (see §6).

### Tree Search for Language Model Agents — Koh et al., 2024 · [arXiv:2407.01476](https://arxiv.org/abs/2407.01476)

**Mechanism.** Best-first tree search **in the real environment** (not a simulator), guided by an
LM value function scoring how promising each state is — a verifier used as a search heuristic rather
than a gate. Complementary to any base agent.

**Numbers.** VisualWebArena **+39.7% relative**, absolute **26.4%**; WebArena **+28.0% relative**,
absolute **19.2%**.

**Relevance to NetGent's verifier.** The same value function that ranks candidate next-states can score
"is this state closer to the goal," which is what a NetGent *state condition* asserts statically. Search
in the live environment is too expensive for us (irreversible actions), but it is the strongest
evidence that **a per-state score, not just a terminal check, is where the gains are.**

### WebDreamer — Gu et al., 2024–2025 · [arXiv:2411.06559](https://arxiv.org/abs/2411.06559)

**Mechanism.** Uses the LLM as a **world model**: simulate the outcome of each candidate action and
score it before committing — avoiding real-environment backtracking, which is impossible for
irreversible web actions.

**Numbers.** Competitive with tree search on VisualWebArena while being **4–5× more efficient**;
effective on Online-Mind2Web and Mind2Web-Live; a Dreamer-7B performs comparably to GPT-4o.

**Relevance to NetGent's verifier.** The irreversibility argument is ours too — NetGent explores live
forms and cannot undo a submit. If we ever want lookahead, simulate-then-commit is the affordable
version. Lower priority than the oracle work, but the 4–5× efficiency number makes it viable.

### Agent Q — Putta et al., 2024 · [arXiv:2408.07199](https://arxiv.org/abs/2408.07199)

**Mechanism.** MCTS + **AI self-critique providing step-level feedback** + off-policy DPO on both
successful and failed trajectories.

**Numbers.** OpenTable (real site) with Llama-3 70B: **18.6% → 81.7%** after one day of training
(**+340% relative**), **→ 95.4%** with online search. On WebShop it beats behaviour cloning, RFT, and
average human performance when equipped with online search.

**Relevance to NetGent's verifier.** Notable mostly for the shape: **step-level critique signal >
outcome signal** when the trajectory is long, and failed trajectories are training data rather than
waste. NetGent discards failed exploration runs today; ReUseIt (§6) shows what to do with them instead.

### PAE — Zhou et al., 2024 · [arXiv:2412.13194](https://arxiv.org/abs/2412.13194)

**Mechanism.** Proposer (context-aware task proposal from a URL or user demos) → Agent (attempts) →
**autonomous VLM-based success evaluator** whose verdict is the RL reward. No human instructions.

**Numbers.** Not stated in the abstract page I could read (see §7).

**Relevance to NetGent's verifier.** The architecture is NetGent's `generate` loop with the evaluator
promoted to first class: propose task → explore → **evaluate** → keep. Worth reading in full for the
proposer design if we ever auto-generate exploration tasks per site.

### NNetNav — Murty et al., 2024–2025 · [arXiv:2410.02907](https://arxiv.org/abs/2410.02907)

**Mechanism.** Unsupervised demonstration synthesis by **retroactively labelling** action sequences
from an exploration policy — you explore first and write the instruction afterwards — with hierarchical
task decomposition used to **prune** trajectories lacking meaningful sub-task annotations.

**Numbers.** 10,000 self-generated demonstrations; Llama-3.1-8B fine-tuned reaches **16% on WebArena**
(+15 pts over zero-shot) and **35% on WebVoyager** (+31 pts). Note: as a *judge*, NNetNav scores only
**52.5% precision** on AgentRewardBench — the weakest of the twelve tested.

**Relevance to NetGent's verifier.** The pruning criterion is the transferable part: *a trajectory
that cannot be described as a coherent sub-task is not worth keeping*. That's a cheap, structural
filter NetGent could apply before compiling — no judge required. The 52.5% precision result is the
warning attached: NNetNav's relabeller makes good training data and a bad oracle.

### Explorer — Pahuja et al., ACL Findings 2025 · [arXiv:2502.11357](https://arxiv.org/abs/2502.11357) · [ACL](https://aclanthology.org/2025.findings-acl.326/)

**Mechanism.** Exploration-driven synthesis of web trajectories at scale, with filtering to
*successful* trajectories only.

**Numbers.** **94K+ successful multimodal trajectories**, 49K unique URLs, 720K screenshots, 33M web
elements, at **$0.28 per successful trajectory**. Trained agent evaluated on Mind2Web-Live,
Multimodal-Mind2Web, MiniWoB++.

**Relevance to NetGent's verifier.** The economics are the point: **$0.28 per verified-successful
trajectory** is the benchmark cost to beat for NetGent's compile step, and the fact that a 94K-scale
pipeline is built entirely around "keep only what verified" reinforces that the filter is the product.

## 1.4 Process reward / step verifiers for GUI agents (2025–2026)

### GUI-Shepherd — Chen et al., 2025 · [arXiv:2509.23738](https://arxiv.org/abs/2509.23738)

**Mechanism.** A Process Reward Model for long-horizon GUI tasks giving **dense step-by-step feedback**,
usable both as a training reward and as an **inference-time verifier**. Trained on **52,000
interactions** with human annotations plus GPT-4o-generated rationales.

**Numbers.** AndroidWorld: **+7.7 pts** SR via multi-turn online PPO, **+5.1 pts** used purely as a
verifier. AndroidControl: **+2.2 pts** as reward provider, **+4.3 pts** as verifier. Reported to
outperform outcome-focused reward models across settings.

**Relevance to NetGent's verifier.** The +5.1 pts "as a verifier, no training" number is the one that
matters for us: a step-level checker bolted onto an unchanged agent still buys ~5 points. NetGent's
per-transition guard is the zero-LLM version of this — the paper says the signal is real; we get it
for free at replay time.

### GUI-Critic-R1 — Wanyan et al., 2025 · [arXiv:2506.04614](https://arxiv.org/abs/2506.04614)

**Mechanism.** A **pre-operative** critic: reason about the likely outcome and correctness of an
action *before* executing it, motivated explicitly by irreversibility ("deletions or payments").
Trained with **S-GRPO** (Suggestion-aware Group Relative Policy Optimization) using a suggestion reward,
so the critic must produce an actionable fix, not just a verdict.

**Numbers.** GUI-Critic-Test: mobile GUI-I **69.20% critic accuracy / 52.43% suggestion accuracy**;
mobile GUI-S 58.77% / 47.37%; **web GUI-W 63.08% / 39.48%**. Vs same-backbone Qwen2.5-VL-7B: **+14.32
pts** critic accuracy on GUI-I, +9.29 pts suggestion. Vs GPT-4o on GUI-I: +3.19 pts critic, **+11.89
pts** suggestion. Downstream on AndroidWorld with a Qwen2.5-VL-72B agent: **22.4% → 27.6%** SR, 31.8%
efficiency advantage rate.

**Relevance to NetGent's verifier.** Note the web number: **63.08% critic accuracy** — a purpose-built,
RL-trained critic on web GUIs is barely better than a coin-flip-plus. This is the strongest single
argument in the survey against building an LLM step-verifier for NetGent and for compiling deterministic
pre-conditions instead. The *suggestion* framing is worth keeping though: our failed-edge report should
say what to do, not just what broke (§6).

### AgentPRM — Xi et al., 2025 · [arXiv:2511.08325](https://arxiv.org/abs/2511.08325)

**Mechanism.** PRM for multi-turn agents scoring each decision by **promise and progress** — proximity
to the goal and progress made — rather than binary step correctness, with TD-based estimation plus GAE
for label generation.

**Numbers.** "**over 8× more compute-efficient** than baselines"; robust improvement under test-time
compute scaling. (Benchmark-level SR deltas not in the accessible text — §7.)

**Relevance to NetGent's verifier.** The conceptual correction is useful: for a web workflow, most steps
aren't "right" or "wrong," they're "closer" or "not closer." NetGent's states are a *discrete* version
of progress — reaching state *k* of *n* is measurable progress with no model at all. Our `edges_ok`
count is already a progress signal; we should treat it as one.

---

# 2. LLM-as-a-judge foundations and failure modes

### Judging LLM-as-a-Judge (MT-Bench / Chatbot Arena) — Zheng et al., NeurIPS 2023 D&B · [arXiv:2306.05685](https://arxiv.org/abs/2306.05685)

**Mechanism.** The paper that established the practice and, in the same breath, its limits: it
"examine[s] the usage and limitations of LLM-as-a-judge, including **position, verbosity, and
self-enhancement biases**, as well as limited reasoning ability," validated against MT-Bench (**3K
expert votes**) and Chatbot Arena (**30K** human-preference conversations).

**Numbers.** GPT-4 achieves "**over 80% agreement**" with both controlled and crowdsourced human
preferences — "the same level of agreement between humans."

**Relevance to NetGent's verifier.** The 80%-equals-human framing is what everyone quotes to justify
LLM judges; note the domain — *open-ended chat preference*, where the human ceiling is itself ~80%.
On agent trajectories the same technique lands at 69.8% precision (AgentRewardBench). Do not transfer
the chat number to our setting.

### Judging the Judges: position bias — Shi et al., AACL-IJCNLP 2025 · [arXiv:2406.07791](https://arxiv.org/abs/2406.07791)

**Mechanism.** Three metrics — **repetition stability, position consistency, preference fairness** —
applied to **15 LLM judges** over MTBench and DevBench: 22 tasks, ~40 solution-generating models,
**>150,000 evaluation instances**. Decomposes bias into judge-level, candidate-level and task-level
factors.

**Numbers.** "Position bias is not due to random chance and varies significantly across judges and
tasks"; prompt-component length weakly influences bias, while **solution quality gaps strongly affect
it** — judges are most position-biased precisely when the candidates are close.

**Relevance to NetGent's verifier.** If we ever A/B two candidate workflows with an LLM judge (e.g.
"which compiled NFA is better"), position bias will be worst exactly in the close calls we care about.
Use paired, order-randomised evaluation or, better, a deterministic replay metric.

### LLM Evaluators Recognize and Favor Their Own Generations — Panickssery, Bowman & Feng, NeurIPS 2024 · [arXiv:2404.13076](https://arxiv.org/abs/2404.13076)

**Mechanism.** Tests whether self-preference is causally driven by self-recognition; fine-tunes models
to vary self-recognition ability and measures the effect on self-preference.

**Numbers.** "GPT-4 and Llama 2 have **non-trivial accuracy** at distinguishing themselves from other
LLMs and humans," and there is "a **linear correlation** between self-recognition capability and the
strength of self-preference bias." (Exact percentages weren't in the abstract page — §7.)

**Relevance to NetGent's verifier.** Concrete rule: **never let the same model that drove exploration
judge its own trajectory.** NetGent uses one cheap model (`anthropic/claude-haiku-4-5-20251001`) for
exploration; if a judge is added, it must be a different model, or the verdict inherits a measured bias.

### Large Language Models Cannot Self-Correct Reasoning Yet — Huang et al., ICLR 2024 · [arXiv:2310.01798](https://arxiv.org/abs/2310.01798)

**Mechanism.** Isolates **intrinsic** self-correction (no external feedback, no oracle label) from the
oracle-assisted variety that prior work conflated with it.

**Numbers.** Intrinsic, GPT-3.5 (initial → round 1 → round 2): GSM8K **75.9 → 75.1 → 74.7**;
CommonSenseQA **75.8 → 38.1 → 41.8**; HotpotQA 26.0 → 25.0 → 25.0. GPT-4: GSM8K **95.5 → 91.5 → 89.0**;
CommonSenseQA 82.0 → 79.5 → 80.0; HotpotQA 49.0 → 49.0 → 43.0. With **oracle labels** the direction
flips: GPT-3.5 GSM8K 75.9 → **84.3**, CommonSenseQA 75.8 → **89.7**; GPT-4 GSM8K 95.5 → **97.5**,
HotpotQA 49.0 → **59.0**. Diagnosis: "74.7% of the time, GPT-3.5 retains its initial answer. Among the
remaining instances, the model is more likely to modify a correct answer to an incorrect one."

**Relevance to NetGent's verifier.** This is the empirical basis for NetGent's architecture being right:
**the verifier must be external to the explorer.** An explorer asked "are you sure?" gets worse, not
better. The oracle-label columns say the payoff comes entirely from a *real* signal — which for us is
a page-observed condition or a replay result, both of which we can produce.

### CRITIC — Gou et al., ICLR 2024 · [arXiv:2305.11738](https://arxiv.org/abs/2305.11738)

**Mechanism.** Verify-then-correct through **tools**: the model interacts with a search engine, code
interpreter, or toxicity API to critique its own output, then revises using that grounded feedback.

**Numbers.** Consistent gains on free-form QA, math program synthesis and toxicity reduction; the
paper's headline conclusion is "the **crucial importance of external feedback** in promoting the
ongoing self-improvement of LLMs."

**Relevance to NetGent's verifier.** The browser is our tool. `session.snapshot()` after an action is
precisely a CRITIC-style tool call, and it's already how `_form_succeeded` works. The paper is the
citation for why that design (page reads, not self-report) is the correct one.

### LLM Critics Help Catch LLM Bugs (CriticGPT) — McAleese et al., 2024 · [arXiv:2407.00215](https://arxiv.org/abs/2407.00215)

**Mechanism.** RLHF-trained critic models that write natural-language critiques of code to help human
evaluators; the critics found errors in ChatGPT training data previously rated flawless.

**Numbers.** Model critiques preferred over human critiques in **63%** of cases on code with naturally
occurring LLM errors. **Human-machine teams** "catch similar numbers of bugs to LLM critics while
**hallucinating less** than LLMs alone." Critics "hallucinated bugs that could mislead humans."

**Relevance to NetGent's verifier.** The human+critic > critic-alone result is the template for our
authority level: an LLM verdict should **surface evidence to a deterministic checker** (or a human in
the eval loop), not decide alone. Mirrors AgentRewardBench's precision ceiling from a different angle.

### Shrinking the Generation-Verification Gap with Weak Verifiers (Weaver) — Saad-Falcon et al., NeurIPS 2025 · [arXiv:2506.18203](https://arxiv.org/abs/2506.18203)

**Mechanism.** Combine many weak, imperfect verifiers into one strong verifier using **weak
supervision** to estimate each verifier's accuracy without labels, normalising inconsistent output
formats with dataset statistics and filtering low-quality verifiers.

**Numbers.** With Llama 3.3 70B as generator and an ensemble of ≤70B judges/reward models as
verifiers: **87.7% average**, vs GPT-4o **69.0%** and o3-mini **86.7%**. Also distils the ensemble into
a **400M cross-encoder**.

**Relevance to NetGent's verifier.** Directly applicable and cheap: NetGent already has *three*
independent weak verifiers in `_form_succeeded` (dialog raised, marker seen in observed text, marker
present in a fresh snapshot). Weaver's finding is that **weighted** ensembles substantially beat
unweighted ones because the verifiers differ in accuracy — so measure each of our three signals'
precision separately and weight them, rather than OR-ing them as we do now.

### Variation in Verification — Zhou et al., ICLR 2026 · [arXiv:2509.17995](https://arxiv.org/abs/2509.17995)

**Mechanism.** Systematic study of generative verifiers (CoT then binary verdict) across three axes —
problem difficulty, generator capability, verifier capability — over **12 benchmarks**, **14 open models
(2B–72B)** plus GPT-4o.

**Numbers.** "Easy problems allow verifiers to more reliably certify correct responses"; "**weak
generators produce errors that are easier to detect than strong generators**"; post-verification the
Gemma2-9B→27B performance gap **shrinks by 75.7%**; and there are regimes where "strong verifiers offer
limited advantage over weak ones."

**Relevance to NetGent's verifier.** Two consequences. (1) Verification gets *harder* as our explorer
gets better — today's cheap-model failures are loud (empty form, error banner); a stronger explorer's
failures will be subtle (right form, wrong field). Budget for that. (2) The 75.7% gap-shrink says
verification is a cheaper lever than upgrading the explorer model — good news for a compile-time budget.

---

# 3. Self-verification and reflection in agents

### Voyager — Wang et al., 2023 · [arXiv:2305.16291](https://arxiv.org/abs/2305.16291)

**Mechanism.** The canonical separate-verifier design. A **second GPT-4 instance acts as critic**: given
the agent's current state and the task, it reports whether the program achieved the task and, on
failure, "critique by suggesting how to complete the task." That verdict gates whether the skill enters
the library and whether the agent advances or retries.

**Numbers.** 3.3× more unique items, 2.3× longer distances, tech-tree milestones **15.3× faster** than
baselines. **Ablation: removing self-verification drops discovered items by 73%** — "the most important
among all the feedback types," ahead of environment feedback and execution errors.

**Relevance to NetGent's verifier.** The 73% number is the strongest single justification for building
NetGent's verifier at all, and the design is ours almost exactly: a separate critic that both (a) gates
skill-library admission — for us, gates whether a trajectory gets compiled into a workflow — and
(b) returns a *suggestion*, not just a verdict. Note that Voyager's critic reads structured game state,
not prose: our equivalent is the DOM snapshot, not the agent's narration.

### Reflexion — Shinn et al., NeurIPS 2023 · [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)

**Mechanism.** Verbal reinforcement: an evaluator produces a signal, a self-reflection model turns it
into text, and that text goes into an episodic memory buffer consulted on the next trial. No weight
updates.

**Numbers.** AlfWorld: ReAct plateaus ~78%; ReAct+Reflexion solves **130/134 (~97%)** over 12 trials
(+22 pts). HotpotQA: CoT ~60% → **~74%**; CoT(GT) 68% → 80%; ReAct ~39% → ~51%. HumanEval pass@1
**80.1% → 91.0%** (prior SOTA 65.8%); MBPP 80.1% → 77.1% (a *regression*). Rust-50 ablation: base 60%,
no test generation 52%, **no self-reflection 60%**, full 68%. **Crucially, where the reward comes
from**: AlfWorld uses the environment's binary signal plus heuristics (repeated action >3 cycles, >30
actions); HotpotQA uses "exact match answer grading using the environment"; programming uses
self-generated unit tests (≤6, AST-validated).

**Relevance to NetGent's verifier.** Read the reward column, not the headline: **every Reflexion domain
has an external oracle.** The MBPP regression and the flat no-self-reflection ablation row show the
lift is fragile without one. NetGent's loop-detection heuristics (`MAX_REPEAT`) are the same family as
their ">3 cycles" rule — cheap, model-free, and evidently worth keeping.

### Self-Refine — Madaan et al., NeurIPS 2023 · [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)

**Mechanism.** Same model generates → critiques → refines, iteratively, with no external signal and no
training.

**Numbers.** **~20% absolute** average improvement across **7 tasks** with GPT-3.5/ChatGPT/GPT-4.

**Relevance to NetGent's verifier.** The counterweight to Huang et al.: intrinsic refinement *does*
work for open-ended generation (writing, code readability) where "better" is a judgement call. It does
not work for tasks with a fact of the matter. "Did this form submit?" is the second kind. Do not
generalise Self-Refine's 20% to our setting.

### LATS — Zhou et al., 2023–2024 · [arXiv:2310.04406](https://arxiv.org/abs/2310.04406)

**Mechanism.** MCTS over language-agent trajectories with **LM-powered value functions and
self-reflections** as the search heuristic; unifies reasoning, acting and planning.

**Numbers.** HumanEval pass@1 **92.7%** (GPT-4); WebShop **75.9** average (GPT-3.5, gradient-free).

**Relevance to NetGent's verifier.** Same lesson as Koh et al.: the verifier is most valuable as a
*state score* consumed by search. NetGent doesn't search, so the transferable piece is narrower — but
if we ever add multi-run exploration (`--runs N`) with selection among candidate trajectories, an LM
value function is the documented way to pick.

### ExpeL — Zhao et al., AAAI 2024 · [arXiv:2308.10144](https://arxiv.org/abs/2308.10144)

**Mechanism.** Cross-task experiential learning: compare **success/failure pairs** and sets of successes
to extract natural-language insights, maintained by four operations — **ADD / UPVOTE / EDIT /
DOWNVOTE** — each insight carrying an importance score (starts at 2, incremented by UPVOTE/EDIT,
decremented by DOWNVOTE, removed at 0).

**Numbers.** HotpotQA: ReAct 28.0±1.4 → ExpeL **39.0±1.7** (Reflexion R3 40%). ALFWorld: ReAct 40.0±0.3
→ ExpeL **59.0±0.3**, beating Reflexion R3's 54.4% **without retries**. WebShop: 37% (insights-only).

**Relevance to NetGent's verifier.** The vote-with-decay bookkeeping is a good model for NetGent's
future guard library: a state condition that keeps holding gets upvoted; one that keeps failing on a
site gets downvoted out. It's cheap, auditable, and needs no model at replay time.

### RAP — Hao et al., EMNLP 2023 · [arXiv:2305.14992](https://arxiv.org/abs/2305.14992)

**Mechanism.** Repurposes the LLM as **both world model and reasoning agent**, with MCTS over the
reasoning space and a reward/self-evaluation at each step.

**Numbers.** RAP on LLaMA-33B beats GPT-4 CoT on plan generation by **33% relative**.

**Relevance to NetGent's verifier.** Background for why step-level self-evaluation helps at all; the
practical descendant for our domain is WebDreamer. Low direct priority.

### SCoRe — Kumar et al., 2024 · [arXiv:2409.12917](https://arxiv.org/abs/2409.12917)

**Mechanism.** Multi-turn online RL on **self-generated** data to train genuine self-correction,
after diagnosing why SFT approaches fail: "(1) a distribution mismatch between mistakes made by the
data-collection policy and the model's own responses, or (2) behavior collapse, where learning
implicitly prefers only a certain mode of correction behavior."

**Numbers.** **+15.6 pts** self-correction on MATH (Gemini 1.0 Pro); **+9.1 pts** on HumanEval
(Gemini 1.5 Flash).

**Relevance to NetGent's verifier.** Confirms self-correction is trainable but not promptable — out of
scope for NetGent (we don't train). Cite it to close the loop on "why not just prompt the explorer to
double-check itself": because the literature says that specific thing doesn't work (Huang et al.) and
the thing that does requires RL.

---

# 4. Specification → checkable oracles (the old literature, and its 2026 descendants)

### The Oracle Problem in Software Testing: A Survey — Barr, Harman, McMinn, Shahbaz & Yoo, **IEEE TSE 41(5):507–525, 2015** · DOI [10.1109/TSE.2014.2372785](https://doi.org/10.1109/TSE.2014.2372785) · [UCL Discovery](https://discovery.ucl.ac.uk/1471263/)

**Mechanism.** The canonical framing: "Given an input for a system, the challenge of distinguishing the
corresponding desired, correct behaviour from potentially incorrect behavior is called the **test oracle
problem**." Surveys oracle automation via modelling, specifications, contract-driven development, and
metamorphic testing, and notes that "without test oracle automation, the human has to determine whether
observed behaviour is correct."

**Relevance to NetGent's verifier.** The vocabulary alone is worth adopting in our docs. NetGent today
runs on an *implicit* oracle (the agent's `done`) plus a *derived* one (marker text). The whole v2
thesis — conditions on states — is a move to a **specified** oracle. Framing the verifier work this way
in the paper/design doc positions it against 25 years of SE literature rather than one year of agent
papers, which is the stronger claim.

### Metamorphic Testing: A Review of Challenges and Opportunities — Chen, Kuo, Liu, Poon, Towey, Tse & Zhou, **ACM Computing Surveys 51(1):4:1–4:27, 2018** · [DOI 10.1145/3143561](https://dl.acm.org/doi/10.1145/3143561)

**Mechanism.** When you can't state the correct output, state a **relation between outputs of related
inputs** ("necessary properties of the target function or algorithm in relation to multiple inputs and
their expected outputs"). Test generation and result verification in one.

**Relevance to NetGent's verifier.** The most under-exploited idea here for NetGent. We can't always
say "this booking is correct," but we can say **"the same workflow with two different `--param` values
must reach the same states and differ only in the extracted values."** That is a metamorphic relation
NetGent can check *for free* — we already run `validate_workflow` once per param set (`validate.py`
loops `param_sets`), we just don't compare across them. Cheapest new oracle in this document.

### QuickCheck — Claessen & Hughes, **ICFP 2000** · [DOI 10.1145/351240.351266](https://dl.acm.org/doi/10.1145/351240.351266)

**Mechanism.** Properties as executable functions, checked against automatically generated random
inputs; custom generators for structured data. ACM SIGPLAN Most Influential ICFP 2000 Paper (awarded
2010).

**Relevance to NetGent's verifier.** The property/generator split maps onto our `Param` schema: a
NetGent parameter *is* a generator, and a state condition *is* a property. Property-based replay —
generate N param sets, assert the state conditions hold for all — is the natural generalisation of
`validate_workflow(param_sets=...)` and would turn our single-shot validation into a fuzz test.

### Model-based GUI testing and GUI Ripping — Memon et al., 2001–2007 · [GUI Ripping, WCRE 2003 (PDF)](https://www.cs.umd.edu/~atif/pubs/MemonWCRE2003.pdf) · [Event-flow model, STVR 2007](https://onlinelibrary.wiley.com/doi/abs/10.1002/stvr.364)

**Mechanism.** **GUI Ripping** reverse-engineers a state-based model of an application by systematically
executing every possible action in every discovered state; the surrounding framework (coverage
evaluator, test-case generator using AI planning, **test oracle**, executor, regression tester; DART for
daily automated re-testing) generates tests *and* oracles from that model.

**Relevance to NetGent's verifier.** This is NetGent's ancestor, and the docs should say so: an
automatically-ripped state model whose states carry expected properties, replayed daily to detect
regressions. The 20-year-old lesson we should not re-learn: the oracle is generated *from the model*,
not from the executor's opinion of itself.

### AgentSpec — Wang, Poskitt & Sun, **ICSE 2026** · [arXiv:2503.18666](https://arxiv.org/abs/2503.18666)

**Mechanism.** A domain-specific language of **trigger → predicate → enforcement** rules, applied as
*runtime* enforcement around an LLM agent's actions (block, warn, substitute).

**Numbers.** Prevents **>90%** of unsafe executions for code agents and enforces **100%** compliance for
autonomous vehicles; eliminates all hazardous actions in embodied tasks; **millisecond-level** latency.
LLM-generated rules (OpenAI o1): **95.56% precision / 70.96% recall** for embodied agents; identifies
**87.26%** of risky code; prevents law-breaking in **5 of 8** AV scenarios.

**Relevance to NetGent's verifier.** *trigger → predicate → enforcement* is NetGent's schema with an
extra field. The 95.56%-precision/70.96%-recall split for LLM-generated rules is the number to plan
around: an LLM asked to write our state conditions will write mostly-correct but **incomplete** ones —
so rule synthesis is a good compile-time use of the model, and rule *completeness* must come from
observed trajectories, not from the model's imagination.

### AgentLTL — Elkoussy & Perez, 2026 · [arXiv:2607.02599](https://arxiv.org/abs/2607.02599)

**Mechanism.** A language derived from **First-Order LTL** expressing procedural rules over agent
traces, yielding "a deterministic, **judge-free** compliance score." One spec, two uses: *harnessing*
(score completed traces, or gate each tool call online by checking the prefix before execution) and
*finetuning* (the score as a dense reward). Motivation stated bluntly: "Tool-using LLM agents are
usually evaluated by final-answer correctness or LLM judges. Neither captures how an answer was
produced."

**Numbers.** Block-and-warn harnessing improves compliance on **5 of 7** models; finetuning with the
same reward gives **+38 pts accuracy** and **+17.5 pts compliance** on held-out patterns including
unseen tool-name aliases.

**Relevance to NetGent's verifier.** The closest formal match to NetGent's `control_sequence` /
`Branch` / `Repeat`. Our control program is already a bounded regular expression over actions — i.e.
a monitorable temporal property — so a **prefix-checking online monitor is implementable today** with
no new machinery: at each replay step, assert the trace so far is a prefix of the language the control
program accepts. That turns `validate` from an end-state check into a runtime monitor, which is what
ST-WebAgentBench's CuP also wants.

### WebTestPilot — Teoh et al., **PACMSE / TOSEM, April 2026** · [arXiv HTML](https://arxiv.org/html/2602.11724)

**Mechanism.** End-to-end web testing **against a natural-language specification** by inferring oracles:
(1) **symbolize** GUI elements into structured variables with type constraints (Cart, Product…);
(2) recognise data/causal/temporal **dependencies across states**; (3) compose assertions in a
Python-extended **DSL over those symbols**; (4) reason across states via page reidentification with a
structured session history. Explicitly designed so assertions are "constrained to grounded symbols
rather than free-form natural language reasoning" — an anti-hallucination measure.

**Numbers.** **96% precision / 96% recall** in bug detection, **99%** task completion, over 100 test
cases across 4 web applications; 8 real bugs found in industrial deployment. Baselines: LaVague 0.64
task completion, NaviQAte 0.54, PinATA 0.08 (**0.26 precision / 0.69 recall** on bugs).

**Relevance to NetGent's verifier.** The single most directly transferable paper in this document.
96/96 vs an LLM judge's 69.8% precision, achieved by exactly NetGent's move: **compile the NL intent
into symbol-grounded, checkable assertions instead of asking a model for a verdict.** Their symbolization
step is what our compiler is missing — we compile *actions* from the trajectory but not *expected
values*. Adding "expected value of this field after this transition" to the NFA is the concrete next step.

### From Business Requirements to Test Assertions — Ma & Eisty, 2026 · [arXiv:2607.10277](https://arxiv.org/abs/2607.10277)

**Mechanism.** Requirement-driven oracle pipeline on Defects4J Lang (10 real bugs): extract behavioural
change from buggy/fixed diffs → hand-translate into a business requirement → build a
requirement-derived gold oracle (REQ) → prompt 5 LLMs (DeepSeek-V3, Gemma-3n, Llama-3, Mistral-7B,
Qwen-3) for Java oracle code → score agreement with REQ and with the SUT.

**Numbers.** "LLMs achieve **non-trivial generalization but with substantial bug- and model-level
variance**." Generated oracles align **more closely with REQ than with the SUT**; correlations between
requirement technicality/ambiguity and oracle accuracy are weak with wide CIs; "no detectable linear
relationship exists between requirement properties and oracle accuracy."

**Relevance to NetGent's verifier.** Tempering result for the "compile the task string into checks"
plan: LLM-written oracles track *the stated requirement* better than *the actual system*. For NetGent
that means checks synthesised from the task string will over-fit the prompt and miss site reality —
so **synthesised conditions must be validated against an observed trajectory before being written into
the NFA**, which is what our `explore → generate` order already enforces. Keep it that way.

### LLM-Based Test Oracles: Source-of-Authority Taxonomy (SLR) — Mughal & Bilal, 2026 · [arXiv:2607.05031](https://arxiv.org/abs/2607.05031)

**Mechanism.** PRISMA-2020 systematic review screening **2,436 records → 54 included → 83 with
snowballing**, classifying oracles along three axes: **source of authority**, form, and adjudicating
mechanism.

**Numbers/claims.** "Just over half of the corpus reaches a verdict with **no specification at all**."
"A label such as LLM-as-a-judge names **how** a verdict is produced, not **why** it should be trusted."
"Oracle quality is most often judged by **resemblance to a known oracle rather than by whether injected
faults are caught**." Their prescription: "The first question to ask of any LLM oracle is therefore what
one would point to in defending its verdict."

**Relevance to NetGent's verifier.** Gives us the evaluation methodology for our own verifier, and it's
one we're currently not using: **don't measure our checks by agreement with a judge — measure them by
fault injection.** Break a workflow deliberately (wrong selector, wrong param, site-changed fixture) and
count how many breakages the state conditions catch. That is a defensible number and it's cheap to
produce with the existing eval harness.

---

# 5. Replayability / determinism as verification

### SKILL.nb — El Hattami, Chapados & Pal, 2026 · [arXiv:2606.08049](https://arxiv.org/abs/2606.08049)

**Mechanism.** Workflows stored as versioned, auditable notebooks interleaving NL guidance,
multi-language executable cells, **validation gates**, fallback paths and multimodal evidence
(outputs, screenshots, error traces). **Selective formalization**: execution evidence decides which
steps become code and which stay NL-guided; the choice is revisable. Explicitly frames "lifecycle
reliability" — artifacts that succeed once fail later under environment drift.

**Numbers.** WebArena-Verified single-round **53.7%** (+3.9 pts over baseline). **Re-execution retention
91.7%** of initially successful tasks across three re-executions — **+15.5 pts over the next best
method**. Bounded repair recovers **72.9%** of subsequent failures with post-repair regressions limited
to **4.2%** (vs **15.0–17.0%** for baselines). Cross-version transfer (frozen GitLab 15.7 state reused):
**−1.7 pts** on GitLab 16.11, **+0.6 pts** on GitLab 18.9.

**Relevance to NetGent's verifier.** The closest published system to NetGent's product, and its metric
— **re-execution retention** — is the one our `validate` node should report. 91.7% is the number to
beat. Two design confirmations: gates belong *inside* the artifact (our state conditions), and repair
must be **bounded** or it regresses (their 4.2% vs baselines' 15–17% is the argument for our replay
being zero-LLM and our repair being explicit rather than improvisational).

### ReUseIt — IUI 2026 · [arXiv:2510.14308](https://arxiv.org/abs/2510.14308) · [ACM](https://dl.acm.org/doi/10.1145/3742413.3789083)

**Mechanism.** Synthesizes reusable workflows from an agent's **successful *and* failed** attempts, and
attaches **execution guards** = (a) *condition checks*, pre/post conditions around each action — e.g.
before navigating, verify "all required form fields are complete and correct"; after typing a
user-specified value, "the field should display exactly that value" — plus (b) *fallback actions*
extracted from successful runs (retry with an alternative element or navigation path). **Guards from
failed traces**: error messages describing what the agent couldn't do become the condition that should
have been checked. **Fallbacks from successful traces**: what worked becomes the retry strategy.

**Numbers.** 15 Skyvern-benchmark tasks with auto-generated variations across sites and params.
Task-only **24.2%** → ReUseIt workflow **70.1%** (**+45.9 pts**); **+21.5 pts** over Task + Magentic-UI
Plan; **+28.7 pts** over Task + Success-Traces (replay of low-level actions).

**Relevance to NetGent's verifier.** The most quantitatively persuasive validation of NetGent's core
design decision. Two numbers matter most: **+28.7 pts over raw success-trace replay** — guards, not the
action sequence, are what makes a replayed workflow work; and **guards derived from failures** are the
mechanism. NetGent currently throws failed exploration runs away. The single highest-ROI change
suggested by this survey is: keep the failed runs, and mine the failed edge into a state condition.

### Ringer — Barman, Chasins, Bodík & Gulwani, **OOPSLA 2016** · [DOI 10.1145/2983990.2984020](https://dl.acm.org/doi/10.1145/2983990.2984020) · [PDF](https://schasins.com/assets/papers/ringer.pdf)

**Mechanism.** Record-and-replay web automation by demonstration that reproduces user-level
interactions rather than script-level DOM calls. Evaluated in four configurations — *user-timing* (wait
as long as the user did), *no-wait* (dispatch ASAP), and **2run-trigger / 3run-trigger** versions that
**infer synchronization triggers from two or three recorded traces** — each run 10 times.

**Numbers.** Replays **25 interactions correctly vs CoScripter's 6**; "replayed **4×** more benchmarks
than a state-of-the-art replay tool." CoScripter failures are analysed as keypress-event handling and
page-load synchronization problems.

**Relevance to NetGent's verifier.** The trigger-inference design is NetGent's `--runs N` in 2016 form:
**record the same task multiple times and infer the wait conditions from what's common across runs.**
That is a *pure-code* way to synthesise state conditions with no LLM at all, and it fits our
`explore(N runs) → generate` pipeline exactly. Also the historical proof that synchronization, not
element identification, is the dominant replay failure mode — which matches the flaky-test data below.

### Rousillon — Chasins, Mueller & Bodík, **UIST 2018** · [DOI 10.1145/3242587.3242661](https://dl.acm.org/doi/pdf/10.1145/3242587.3242661) · and CoScripter — Leshed, Haber, Matthews & Lau, **CHI 2008** · [DOI 10.1145/1357054.1357323](https://dl.acm.org/doi/10.1145/1357054.1357323)

**Mechanism.** Rousillon: PBD for hierarchical, distributed web data — the user demonstrates collecting
the first row of a "universal table" and the system generalises to all rows. CoScripter: records browser
actions as **pseudo-natural-language scripts** ("go to http://google.com", "type coscripter into the
search box"), shared in an enterprise wiki; deployed >10 months with 50+ voluntary users.

**Relevance to NetGent's verifier.** The PBD lineage NetGent sits in, and specifically the source of
the *human-readable artifact* requirement: CoScripter's scripts were readable, which is why people
trusted and edited them. NetGent's YAML has the same property; keep the state conditions readable for
the same reason. Rousillon's loop generalisation is the ancestor of our `Repeat`.

### Similo — Nass, Alégroth, Feldt, Leotta & Ricca, 2022 · [arXiv:2208.00677](https://arxiv.org/abs/2208.00677)

**Mechanism.** Locate a web element by a **weighted similarity score over many locator parameters**
rather than one brittle selector.

**Numbers.** **72 failures out of 598** target elements vs **146** for the state-of-the-art baseline,
across the 40 most popular websites.

**Relevance to NetGent's verifier.** 12% residual failure rate for the best similarity-based locator is
the realistic floor for NetGent's `resolution.py` locator chains. Two implications: (i) a failed replay
edge is *not* strong evidence the site changed — ~1 in 8 is locator noise; (ii) that's exactly why the
verdict needs a second, independent signal (the state condition) before we declare breakage.

### An Empirical Analysis of Flaky Tests — Luo, Hariri, Eloussi & Marinov, **FSE 2014** · [DOI 10.1145/2635868.2635920](https://dl.acm.org/doi/10.1145/2635868.2635920) · [PDF](https://mir.cs.illinois.edu/lamyaa/publications/fse14.pdf)

**Mechanism.** Classified the root cause of every flaky-test fix in **201 commits across 51 Apache
projects**, producing the 10-category taxonomy still used today (Async Wait, Concurrency, Test Order
Dependency, Resource Leak, Network, Time, IO, Randomness, Floating Point, Unordered Collections).

**Numbers.** **Async Wait 45%**, **Concurrency 20%**, **Test Order Dependency 12%** — three categories
cover **77%** of the 161 classified commits.

**Relevance to NetGent's verifier.** Directly predicts NetGent's failure distribution: nearly half of
non-deterministic replay failures will be **waiting for the wrong thing**, not wrong selectors. That
argues the highest-value trigger types are the *temporal* ones (`selector_visible` with a proper poll,
`selector_hidden` for spinners) — which `browser/triggers.py` already polls — and that
**order-dependency (12%)** is a real risk for our sweep, which reuses one agent and one session across
forms. It also says a single failed replay should be **retried before being reported**: 77% of flakiness
is the kind that passes on a second run.

---

# 6. Feedback contracts: what the verifier hands back

### Magentic-One — Fourney et al., 2024 · [arXiv:2411.04468](https://arxiv.org/abs/2411.04468)

**Mechanism.** An Orchestrator with two ledgers. **Task Ledger** (outer loop): facts, educated guesses,
plan. **Progress Ledger** (inner loop), re-derived each turn as five explicit questions — *"Is the
request fully satisfied (i.e., task complete)? Is the team looping or repeating itself? Is forward
progress being made? Which agent should speak next? What instruction or question should be asked of this
team member?"* A **stall counter** increments on loops/no-progress; when it exceeds a threshold (≤2),
the inner loop breaks and control returns to the outer loop to revise the plan.

**Numbers.** GAIA **32.33% ± 5.3** (GPT-4o) → **38.00% ± 5.5** (GPT-4o + o1); AssistantBench EM
**11.0% ± 4.6** → 13.3% ± 4.9; WebArena **32.8% ± 3.2**. **Ablation on GAIA validation: removing the
Orchestrator ledgers costs 31%** (removing FileSurfer 39%, Coder 21%, ComputerTerminal 21%). Top failure
causes: *persistent-inefficient-actions* (repeating failed strategies), **insufficient-verification-steps
(tasks marked complete without validation)**, underutilized-resource-options. o1 refused 26% of GitLab
tasks and 12% of shopping tasks.

**Relevance to NetGent's verifier.** The best-documented **feedback contract** in the literature, and
the ablation puts a price on it: 31% of GAIA performance. The five questions are directly portable to
NetGent's explorer state — we already track step history as flat strings; making "is forward progress
being made?" and "are we looping?" *explicit, per-step, structured* fields is a small change with a
measured payoff. And their #2 failure mode — **"tasks marked complete without thorough validation"** —
is exactly `done(success=True)`.

### WebRL's curriculum from failure — [arXiv:2411.02337](https://arxiv.org/abs/2411.02337) (mechanism detailed in §1.3)

**Relevance to NetGent's verifier.** The routing rule: a failed replay is a *task generator*. When
`validate_workflow` reports `failed_edge`, the natural next action is not "report broken" but
"re-explore starting from the last good state, with the failed edge as the task." NetGent's NFA makes
that easy in a way WebRL's flat trajectories don't — we know exactly which state to resume from.

### Is Self-Repair a Silver Bullet for Code Generation? — Olausson, Inala, Wang, Gao & Solar-Lezama, **ICLR 2024** · [arXiv:2306.09896](https://arxiv.org/abs/2306.09896)

**Mechanism.** Analyses Code Llama, GPT-3.5 and GPT-4 self-repair on HumanEval and APPS, **charging the
cost of repair against the budget**, then isolates the bottleneck by artificially raising feedback
quality (stronger model's feedback; then human feedback).

**Numbers/claims.** "When the cost of carrying out repair is taken into account, performance gains are
**often modest, vary a lot between subsets of the data, and are sometimes not present at all**." "Using
a stronger model to artificially boost the quality of the feedback, we observe **substantially larger
performance gains**." With human feedback, "even for the strongest models, self-repair still **lags far
behind** what can be achieved with human-level debugging."

**Relevance to NetGent's verifier.** The cleanest answer to "what form of feedback helps": **the
bottleneck is feedback quality, not the repair step.** For NetGent this argues for spending effort on
making the failed-edge report *precise* (which transition, which selector, which condition failed, what
the page actually showed) rather than on adding retry loops. It also says to **charge the retry budget**:
our sweep's `retries=2` with a growing step budget should be reported as cost, not hidden.

### Teaching Large Language Models to Self-Debug — Chen, Lin, Schärli & Zhou, 2023 · [arXiv:2304.05128](https://arxiv.org/abs/2304.05128)

**Mechanism.** Few-shot self-debugging via **rubber-duck explanation** of the predicted program, with or
without execution/unit-test feedback.

**Numbers.** Spider (**no unit tests available**): +2–3%, and **+9%** on the hardest problems, from code
explanation alone. TransCoder and MBPP (**unit tests available**): **up to +12%**.

**Relevance to NetGent's verifier.** The 3% vs 12% split is the binary-vs-grounded feedback comparison
we wanted: explanation-only feedback buys a few points; **executable feedback roughly quadruples it.**
NetGent's replay *is* the unit test. This is the citation for prioritising "replay and report the real
failure" over "ask the model to reflect."

### Let's Verify Step by Step — Lightman et al., 2023 · [arXiv:2305.20050](https://arxiv.org/abs/2305.20050)

**Mechanism.** Head-to-head process supervision (feedback on every intermediate step) vs outcome
supervision (feedback on the final result), plus active learning to choose which solutions to label.
Releases **PRM800K** (800,000 step-level human labels).

**Numbers.** MATH at N=1860 samples: **PRM 78.2%**, ORM 72.4%, majority vote 69.6%. Active learning is
**~2.6× more data efficient** than uniform labelling. Out-of-distribution (best-of-100), PRM/ORM/majority:
AP Calculus **86.7 / 68.9 / 80.0**; AP Chemistry **80.0 / 68.9 / 71.7**; AP Physics **86.7 / 77.8 / 82.2**;
AMC10/12 **53.2 / 49.1 / 32.8**; aggregate **72.9 / 63.8 / 61.3**.

**Relevance to NetGent's verifier.** The reference number for "step-level beats end-level": **+5.8 pts
in-distribution, +9.1 pts OOD.** NetGent gets step-level supervision structurally — every transition has
a guard — without labelling 800K steps. This is the theoretical backing for putting conditions on
*every* state rather than only the terminal one.

### Plan-and-Solve prompting — Wang et al., **ACL 2023** · [arXiv:2305.04091](https://arxiv.org/abs/2305.04091)

**Mechanism.** Zero-shot: devise a plan splitting the task into subtasks, then execute the plan; PS+
adds detailed instructions targeting calculation errors.

**Numbers.** Across ten datasets PS "consistently outperform[s] Zero-shot-CoT by a large margin" and
matches 8-shot CoT on math reasoning. (Per-dataset figures weren't in the accessible text — §7.)

**Relevance to NetGent's verifier.** Marginal for verification specifically; relevant only as the origin
of the "explicit plan then check against the plan" pattern that Magentic-One's Task Ledger and
WebJudge's key points both instantiate. The verification-usable form is: **write down the sub-goals
first, then check each** — which is the design NetGent should implement.

---

# 7. Ranked findings, judge-authority evidence, and unverified claims

## (a) The 10 findings that should shape NetGent's verifier

| # | Finding | Number | Source | Where it lands |
|---|---|---|---|---|
| 1 | Guards derived from **failed** runs are what make replayed workflows work — more than the action sequence itself | 24.2% → **70.1%**; **+28.7 pts** over replaying success traces alone | ReUseIt, [2510.14308](https://arxiv.org/abs/2510.14308) | **spec→checks** + **feedback routing**: stop discarding failed exploration runs; mine the failed edge into a state condition |
| 2 | A separate verifier gating artifact admission is the highest-value component in a skill-learning loop | removing it costs **73%** of discovered items | Voyager, [2305.16291](https://arxiv.org/abs/2305.16291) | **trajectory judge**: gate `explore → generate`; don't compile an unverified trajectory |
| 3 | LLM judges cap at **~70% precision** on agent trajectories and are permissive (recall 79–90%) | GPT-4o **69.8%** P / 83.1% R; side-effect precision **7.7–14.0%** | AgentRewardBench, [2504.08942](https://arxiv.org/abs/2504.08942) | **authority level**: a judge may escalate a `no`, never certify a `yes` |
| 4 | Symbol-grounded assertions compiled from the NL spec beat judges by ~26 points of precision | **96% P / 96% R** vs judges' 69.8% P | WebTestPilot, [2602.11724](https://arxiv.org/html/2602.11724) | **spec→checks**: add expected *values* (not just actions) to the NFA; ground every assertion in a page symbol |
| 5 | Re-execution retention, not first-run success, is the metric for a durable workflow | **91.7%** retained over 3 re-executions (+15.5 pts); bounded repair 72.9% recovery, 4.2% regression | SKILL.nb, [2606.08049](https://arxiv.org/abs/2606.08049) | **workflow replay check**: report retention + `pass^k`, not a boolean `validated` |
| 6 | Rule-based oracles have a large, measured **false-negative** bias | underreports SR by **16.7 pts** (WebArena) / **18.5 pts** (VWA); recall **55.9%** | AgentRewardBench | **workflow replay check**: a failed marker check must trigger retry/escalation, not a failure verdict |
| 7 | Self-reported completion is systematically overconfident, and worse under drift | claimed:actual **5.3×** under semantic perturbation; agents claim success while true SR falls 54.3% → 26.2% | StressWeb, [2604.16385](https://arxiv.org/abs/2604.16385) | **authority level**: `done(success=True)` stays evidence, never a verdict — as `_form_succeeded` already assumes |
| 8 | Step-level supervision beats outcome-level, and the gap widens out of distribution | PRM **78.2%** vs ORM 72.4% vs majority 69.6%; OOD aggregate **72.9 / 63.8 / 61.3**; GUI-Shepherd **+5.1 pts** as verifier alone | Lightman [2305.20050](https://arxiv.org/abs/2305.20050); GUI-Shepherd [2509.23738](https://arxiv.org/abs/2509.23738) | **spec→checks**: conditions on *every* state, not just the terminal one |
| 9 | Intrinsic self-correction degrades performance; external signal reverses it | GPT-4 GSM8K **95.5 → 89.0** intrinsic vs **→ 97.5** with oracle; explanation feedback +2–3% vs execution feedback +12% | Huang [2310.01798](https://arxiv.org/abs/2310.01798); Chen [2304.05128](https://arxiv.org/abs/2304.05128) | **feedback routing**: never ask the explorer to re-check itself; hand it a replay/page fact |
| 10 | A structured progress ledger is worth ~a third of end-to-end performance; and ~half of replay flakiness is waiting | ledger ablation **−31%** on GAIA; **Async Wait 45%**, Concurrency 20%, Order 12% (77% total) | Magentic-One [2411.04468](https://arxiv.org/abs/2411.04468); Luo FSE 2014 | **feedback routing** + **replay check**: make loop/progress explicit per step; retry once before declaring breakage |

**Two runners-up worth acting on cheaply.** (i) *Metamorphic replay*: `validate_workflow` already loops
param sets — assert that different params traverse the **same state sequence** and differ only in
extracted values (Chen et al., CSUR 2018). (ii) *Weighted weak verifiers*: `_form_succeeded` OR-s three
independent signals; Weaver shows weighted ensembles beat unweighted because verifier accuracies differ
(**87.7%** vs GPT-4o's 69.0%) — measure each signal's precision and weight it.

## (b) Evidence on LLM-judge precision → the authority level to set

| Setting | Judge | Precision / agreement | Source |
|---|---|---|---|
| Web-agent trajectories, 5 benchmarks, expert labels | GPT-4o (best of 12) | **69.8% precision**, 83.1% recall | AgentRewardBench |
| same | Claude 3.7 Sonnet | 68.8% P, 81.6% R | AgentRewardBench |
| same | Qwen2.5-VL | 64.3% P, 89.8% R | AgentRewardBench |
| same | AER-C / AER-V / NNetNav | 67.7% / 67.6% / **52.5%** P | AgentRewardBench |
| same — **side effects** | Claude / Qwen / GPT-4o | **14.0% / 9.0% / 7.7%** P | AgentRewardBench |
| same — rule-based baseline | programmatic | 55.9% recall; −16.7/−18.5 pts SR | AgentRewardBench |
| Live-web tasks, human-labelled | WebJudge (GPT-4o) | **~85% agreement**, 3.8 pt SR gap; 73.7% P on ARB | Online-Mind2Web |
| same | WebJudge-7B | 87% agreement, 3.9 pt gap, 2 API calls | Online-Mind2Web |
| Live-web tasks | WebVoyager GPT-4V, full trajectory | **85.3%** agreement (κ=0.70); 81.3% at k=3, 75.3% at k=1 | WebVoyager |
| WebArena trajectories | captioner+GPT-4 / GPT-4V / captioner+Mixtral | **82.1% / 80.6% / 74.4%** oracle agreement | AutoEval |
| Android-in-the-Wild | captioner+Mixtral / GPT-4V | **92.9% / 90.6%** | AutoEval |
| Final HTML state, trained classifier | WebRL ORM | **~80% accuracy** (vs ~71% GPT-4-Turbo) | WebRL |
| Web GUI step critique, RL-trained | GUI-Critic-R1 | **63.08%** critic accuracy (web split) | GUI-Critic-R1 |
| Requirements → hierarchical checks, tool-using judge | Agent-as-a-Judge | **83.9–92.1%** alignment vs LLM-judge 60.4–84.2% | Agent-as-a-Judge |
| Symbol-grounded compiled assertions | WebTestPilot | **96% P / 96% R** | WebTestPilot |
| Chat preference (for contrast — *do not transfer*) | GPT-4 | >80% agreement, = human-human | MT-Bench |

**Authority level this implies.** Three tiers, in decreasing authority:

1. **Deterministic, page-observed checks** (state conditions, `program_html`-style locators, τ-bench-style
   state diffs, replay success). These *decide*. Evidence: 96/96 (WebTestPilot), τ-bench's LLM-free
   action reward, GAIA's explicit rejection of model-based eval ("cannot evaluate new state-of-the-art
   models") — which for us also protects longitudinal A/B comparability.
2. **Trained/structured verifiers over page state** (an HTML-state ORM ~80%, key-point judges ~85%
   agreement). These *escalate and rank*: good enough to filter trajectories before compilation
   (AutoEval's filtered BC: +75% relative), not good enough to certify.
3. **Prompted LLM judgement and the agent's own `done`** (≤69.8% precision; 5.3× overclaim). These are
   **inputs, never verdicts**. Where they disagree with tier 1, tier 1 wins, and the disagreement is
   logged as an eval signal.

Concretely for NetGent: keep `done(success=True)` as a *hint that closes the episode*; make workflow
acceptance conditional on tier 1 (replay + conditions hold across k runs and ≥2 param sets); allow a
tier-2 judge to *reject* a trajectory before compilation but never to *accept* one. And measure our own
checks by **fault injection** (Mughal & Bilal's prescription), not by agreement with a judge.

## (c) Claims I could not verify

- **PAE's quantitative results.** The arXiv abstract page for [2412.13194](https://arxiv.org/abs/2412.13194)
  gave the full mechanism but no numbers; I could not read the evaluator's accuracy or the WebVoyager/
  WebArena deltas, so none are quoted above.
- **AgentPRM's benchmark-level success rates.** Only the "**>8× more compute-efficient**" figure was in
  the accessible text of [2511.08325](https://arxiv.org/abs/2511.08325); the per-benchmark comparison
  against ORMs is unverified.
- **Panickssery et al.'s exact self-recognition accuracies and correlation coefficient.** The abstract
  states "non-trivial accuracy" and "a linear correlation" without figures on the page I read; I did not
  reach the NeurIPS camera-ready.
- **Plan-and-Solve's per-dataset numbers and error-type breakdown** (GSM8K/SVAMP/AQuA; calculation vs
  missing-step vs semantic error percentages) — not present on the ACL/arXiv abstract page I fetched.
- **Ringer's full benchmark size and per-configuration replay rates.** The PDF did not parse; the
  "25 vs 6 interactions" and "4× more benchmarks than a state-of-the-art replay tool" figures come from
  secondary descriptions of the paper, not from the paper text I read directly. **Treat as
  provisional and re-check against the OOPSLA PDF before citing in a submission.**
- **Rousillon's and CoScripter's replay-validity numbers.** I verified venue/authors/mechanism only;
  neither paper's evaluation numbers were read, so none are quoted.
- **Healenium's evaluation.** No peer-reviewed evaluation of Healenium specifically was located; the
  self-healing numbers quoted above are Similo's (arXiv:2208.00677), which is a different system. The
  "Parasoft Selenic healed all locator failures in five mutants of Spring-PetClinic" line surfaced in
  search results but I did not read the source paper — **excluded from the findings table.**
- **TheAgentCompany's per-checkpoint reliability.** The paper gives the scoring formula and per-model
  scores; I found no measurement of checkpoint-grading reliability vs human judgement.
- **ST-WebAgentBench's exact CuP and Risk Ratio values per agent.** Only the qualitative "average CuP is
  less than two-thirds of their nominal completion rate" was readable.
- **WAREX's magnitude of degradation.** The abstract says "significant drops" across WebArena,
  WebVoyager and REAL without figures on the page I read ([2510.03285](https://arxiv.org/abs/2510.03285)).
- **HAL's failure-attribution split** (harness/benchmark artefacts vs genuine agent error). The rollout
  counts and the qualitative log findings are verified; the attribution percentages are not.
- **"Agents that flake"** — the prompt named this as a possible title; I found no paper by that name.
  The nearest verified sources on agent run-to-run reliability are τ-bench's `pass^k`, SKILL.nb's
  re-execution retention, StressWeb, WAREX, and BrowserGym's variance discussion, all cited above.
- **A dedicated "ProgressRM" paper.** Not found under that name. The verified 2025–2026 GUI
  process-reward line is GUI-Shepherd, GUI-Critic-R1 and AgentPRM (whose mechanism is "step-wise promise
  and progress" — likely what the name referred to).
- **Metamorphic testing / QuickCheck / Barr et al. / Memon / Luo et al. abstracts** were read from
  publisher and repository pages rather than arXiv; venue, year and DOI are verified, and the quoted
  sentences are from those pages. Memon's oracle papers specifically were characterised from the GUI
  Ripping (WCRE 2003) and event-flow (STVR 2007) pages plus secondary summaries — the 2001 TSE oracle
  paper itself was not read.
