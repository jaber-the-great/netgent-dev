# Web-agent literature review (2023–2026) — DOM/text observation, for NetGent v2

*Scope: academic papers only (repos are covered by the sibling surveys). Every number below was
read from the paper's arXiv abstract or HTML full text during this review; anything I could not
find in the paper text is listed in §6 rather than asserted.*

## Summary (10 lines)

1. **Trimming the action space pays more than trimming the observation.** AgentOccam's biggest
   single jump on WebArena is removing `hover`/`press`/`scroll`/tab/`goto`: 16.5% → 28.2%.
2. **Text/DOM beats vision for grounding.** SeeAct: textual-choice grounding 39.1% step SR vs
   20.3% for Set-of-Mark image annotation; oracle grounding 61.9% — grounding, not planning, is the bottleneck.
3. **"Smaller observation is better" is model-dependent, and 2026 evidence flips it for strong models**:
   a11y-tree helps weak models (Llama-3.1-70b 18.2% vs 3.6% on HTML) and *hurts* strong ones
   (GPT-5.1 55.8% a11y → 73.3% HTML).
4. **Goal-conditioned trimming is nearly free**: FocusAgent cuts AxTree >50% at parity; ACON cuts peak
   tokens 26–54% and *raises* small-model success up to 46%.
5. **Long histories collapse agents**: 40–50% → <10% success as context grows 25k→150k tokens; the
   dominant failure modes are action loops and goal drift — exactly what NetGent's `MAX_REPEAT` guards.
6. **Induced workflows are the strongest cheap win**: AWM 23.5% → 35.5% on WebArena with *fewer*
   steps (7.9 → 5.9); ReUseIt 24.2% → 70.1% by adding execution guards.
7. **Verification-in-the-loop is what makes induced skills usable** (ASI +23.5% and −10.7–15.3% steps;
   SkillWeaver +31.8% relative) — NetGent's `validate` node is the same idea, earlier.
8. **Self-reported `done` is not trustworthy**: rule-based eval under-reports by 16.7–18.5 pts; the best
   LLM judge reaches only ~69.8% precision; WebJudge gets ~85% human agreement / 3.8% SR gap.
9. **Structured output costs reasoning** — put free-form reasoning *before* the constrained fields.
10. **Closest prior art to NetGent's product**: SKILL.nb (gated, selectively-formalized workflows;
    91.7% of successes survive re-execution) and ReUseIt (guards from failed runs). Both validate
    "conditions on states, one action per transition".

---

## How to read the "relevance" verdicts

NetGent's explorer is: one structured-output LLM call per step → one atomic action on a numbered
element; observation = URL/title/position + ≤60 near-viewport interactive elements (+ iframe headers,
+ dialogs); memory = a flat `list[str]` of `"{n}. {kind}({index}) {reasoning} -> outcome"`; the whole
agent runs at *compile time only* and its trajectory is compiled into a zero-LLM NFA. So a paper is
relevant when it changes (a) the observation string, (b) a prompt rule, (c) what the flat history
should carry, (d) the closed action set, or (e) an orchestrator node (`explore` / `synthesize` /
`validate`).

---

# 1. Observation & prompt design

### WebArena — Zhou et al., ICLR 2024 · [arXiv:2307.13854](https://arxiv.org/abs/2307.13854)

**Mechanism.** 6 self-hosted, fully functional sites (e-commerce, forum, GitLab, CMS, map) with 812
long-horizon tasks and *functional*, execution-based reward rather than string match. The
environment can render pages as raw HTML DOM, screenshot, or accessibility tree; the baseline agent
uses "accessibility tree with element IDs". The action space is three groups: element ops
(`click`, `hover`, `type`, `press`, `scroll`), tab ops (`tab_focus`, `new_tab`, `tab_close`), URL ops
(`goto`, `go_back`, `go_forward`), plus `noop`.

**Numbers.** GPT-4 + CoT **11.70%**, GPT-3.5 + CoT **8.75%**, best reported agent in the paper
**14.41%**, human **78.24%**. On unachievable tasks GPT-4 mislabels **54.9%** of *feasible* tasks as
impossible when given the UA hint; removing the hint moves it 11.70% → 14.41% while UA recognition
drops to 44.44%.

**Relevance to NetGent.** This is the canonical action set our `schema/actions.py` mirrors — and the
UA result is a direct warning about our `done(success=false)` escape hatch: a "give up" affordance is
cheap for the model to over-use.

### Mind2Web / MindAct — Deng et al., NeurIPS 2023 Spotlight · [arXiv:2306.06070](https://arxiv.org/abs/2306.06070)

**Mechanism.** 2,000+ tasks over 137 real websites / 31 domains. Because raw HTML does not fit in a
context window, MindAct is two-stage: a fine-tuned **DeBERTa-base cross-encoder ranks DOM elements**
against the task + prior actions, the top-k survive, and the LLM then answers a **multiple-choice
question with 5 options per group** (iterated until one option wins) instead of generating a selector.

**Numbers.** Ranker **Recall@50 = 88.9% / 85.3% / 85.7%** (cross-task / cross-website / cross-domain).
Flan-T5-XL: 52.0% step SR, 5.2% task SR (cross-task); GPT-4 (50-task subset) 36.2% step SR / 2.0% task
SR; GPT-3.5 ~17–20% step SR, failing mostly by picking "None".

**Relevance to NetGent.** Our `format_observation(limit=60)` is an *un-ranked* candidate generator —
positional (near-viewport), not task-conditioned. Recall@50 ≈ 89% for a **DeBERTa-base**-sized ranker
is the strongest evidence that a cheap task-conditioned re-rank in front of the 60-element cap is
affordable and would raise the ceiling on long pages.

### SeeAct — Zheng et al., ICML 2024 · [arXiv:2401.01614](https://arxiv.org/abs/2401.01614)

**Mechanism.** Splits GPT-4V's job into *action generation* (free-form textual plan) then *grounding*
(turn the plan into an element + operation). Three grounding variants are compared: (a) generate
element attributes and match them back, (b) pick from **textual choices** (the MindAct-style
multiple-choice list), (c) **image annotation** — Set-of-Mark bounding boxes drawn on the screenshot.

**Numbers (step SR, cross-task / cross-website / cross-domain):** element attributes 16.1 / 12.1 /
19.0; **textual choices 39.1 / 32.7 / 42.0**; image annotation 20.3 / 13.9 / 23.7; **oracle grounding
61.9 / 65.0 / 62.1**. Online on live sites: SeeAct-Choice **37.8%** whole-task SR vs SeeAct-Oracle
**51.1%**. Full offline SeeAct-Choice: 46.4% element acc / 73.4% op F1 / 40.2% step SR (cross-task).

**Relevance to NetGent.** This is the paper that justifies our whole design: **a numbered textual
element list beats drawing marks on a screenshot by ~19 step-SR points**, and the gap to oracle
grounding (~22 pts) says most remaining loss is "which element", not "what to do". Every point spent
improving element naming/dedup in `serializer.py` is spent on the actual bottleneck.

### VisualWebArena — Koh et al., ACL 2024 · [arXiv:2401.13649](https://arxiv.org/abs/2401.13649)

**Mechanism.** 910 visually-grounded tasks on Classifieds / Shopping / Reddit, with the observation
configurable as accessibility tree, caption-augmented a11y tree, screenshot, or **screenshot + SoM**.

**Numbers.** GPT-4V: a11y+captions+screenshot **15.05%**, screenshot+captions+**SoM 16.37%** (SoM helps
most on Classifieds 12.38 → 17.14 and Reddit 8.12 → 9.83). Gemini-Pro: caption-augmented 3.85%,
multimodal 6.04%, multimodal+SoM **5.71%** (SoM *hurts*). Human baseline **88.7%** on 230 sampled tasks.

**Relevance to NetGent.** SoM's benefit is small and model-dependent even on a benchmark *designed* to
need vision. For form-filling / navigation traffic generation, the vision path is not worth its cost.

### WebVoyager — He et al., ACL 2024 · [arXiv:2401.13919](https://arxiv.org/abs/2401.13919)

**Mechanism.** End-to-end GPT-4V agent on 15 *live* websites, screenshot + SoM-style interactive-element
overlay, plus a GPT-4V **auto-evaluator** that judges trajectories from screenshots.

**Numbers.** **59.1%** task success overall, beating GPT-4 (All Tools) and its own text-only variant;
the auto-evaluator agrees with humans **85.3%** of the time.

**Relevance to NetGent.** The 85.3% judge-agreement is the number to beat for our `validate` node —
and note it's measured on *live* sites, i.e. the regime we actually generate traffic in. See also
§3 (AgentRewardBench) for why 85% is less impressive than it sounds.

### Set-of-Mark — Yang et al., 2023 · [arXiv:2310.11441](https://arxiv.org/abs/2310.11441)

**Mechanism.** Segment the image (SEEM/SAM), overlay alphanumeric marks on regions, let GPT-4V
reference marks by number — the visual analogue of our `[index]` list.

**Numbers.** Reported as beating a fully-finetuned referring-expression model on RefCOCOg zero-shot;
the abstract gives no web-agent numbers (see §6).

**Relevance to NetGent.** Cite only as the origin of index-based grounding. The *web* verdicts come
from SeeAct (SoM loses by ~19 pts) and VisualWebArena (SoM helps GPT-4V by ~1.3 pts, hurts Gemini).

### AgentOccam — Yang et al., ICLR 2025 · [arXiv:2410.13825](https://arxiv.org/abs/2410.13825)

**Mechanism.** *The* observation/action-space-simplification paper. No in-context examples, no search,
no new roles — only: (i) **remove actions** the LLM handles badly (`noop`, `tab_focus`/`new_tab`/
`tab_close`, `go_forward`, `goto`, `hover`, `press`, `scroll`); (ii) **add planning actions**
(`branch`, `prune`, `note`, `stop`, `go_home`); (iii) **observation opt** — merge `StaticText` into the
interactive element sharing its label, convert tables/lists to Markdown to kill repetitive structural
tokens; (iv) **selective history replay** — keep only ancestor/sibling/descendant "pivotal nodes" and
drop history steps outside the current sub-plan.

**Numbers (WebArena, GPT-4-Turbo, cumulative ablation):** vanilla **16.5%** → ↓actions **28.2%** →
+X-scrolling 30.7% → +obs opt 32.7% → +history 35.5% → **AgentOccam 43.1%**. Reported as +9.8 absolute
(+29.4%) over the prior SOTA and +26.6 points (+161%) over the plain agent. Efficiency: average
observation tokens/step **2210.2 → 2930.9** and steps/task **6.2 → 9.0** (per-site obs tokens swing
both ways: Map 1883 → 1056, Shopping-Admin 2460 → 4921).

**Relevance to NetGent — highest of any paper here.** Two concrete reads: (1) the **+11.7-point jump
comes from deleting actions**, and NetGent's explorer decision space still contains `hover`, `press`,
`goto`, `go_back`, `scroll` — worth an A/B where the *explorer* can't emit them even though the
*workflow schema* still can; (2) their obs-opt (merge StaticText into the labelled interactive element,
Markdown-ise tables) is directly implementable in `browser/dom/serializer.py`. Also note honestly:
AgentOccam's **total** observation tokens went *up*, because planning/history text replaced the tokens
saved — "simplify the observation" ≠ "shrink the prompt".

### WorkArena + BrowserGym — Drouin et al., ICML 2024 · [arXiv:2403.07718](https://arxiv.org/abs/2403.07718)

**Mechanism.** 33 ServiceNow knowledge-work tasks (forms, lists, dashboards, filters) inside BrowserGym,
a Gym API over Playwright. Observations are AxTree or HTML, both augmented with element IDs, bounding
boxes, and visibility/clickability flags. Action space: `bid`-based (click/type/select/drag),
coordinate-based, high-level primitives, or arbitrary Playwright Python.

**Numbers.** GPT-4o **42.7%**, Llama3 **17.9%**, GPT-3.5 **6.1%**. They chose AxTree over HTML because
**HTML pages run 40,000–500,000 tokens**.

**Relevance to NetGent.** WorkArena is the closest public benchmark to our form-sweep eval
(`evals/sweep.py`), and the augmented-AxTree element schema (bid + bbox + visible/clickable) is nearly
identical to our `DomSnapshot` element model — good external validation, and a ready target if we ever
want a public number.

### The BrowserGym Ecosystem — Le Sellier De Chezelles et al., TMLR 2025 · [arXiv:2412.05467](https://arxiv.org/abs/2412.05467)

**Mechanism.** Unifies 6 benchmarks behind one API + AgentLab for running/analysing agents; first
large-scale like-for-like comparison of frontier models.

**Numbers (Claude-3.5-Sonnet).** MiniWoB 69.8 ± 1.8, WorkArena-L1 56.4 ± 2.7, L2 39.1 ± 3.2, L3
0.4 ± 0.4, WebArena 36.2 ± 1.7, VisualWebArena 21.0 ± 1.3, WebLINX 13.7 ± 0.6, AssistantBench
5.2 ± 1.5. GPT-4o leads only on VisualWebArena (26.7 ± 1.5).

**Relevance to NetGent.** WorkArena-L3 at **0.4%** is the sobering datapoint: nobody solves genuinely
long multi-app workflows zero-shot. It is the empirical argument for NetGent's premise — compile once
with an LLM, then replay deterministically, rather than paying an LLM to re-solve L3 every time.

### LCoW — Lee et al., ICLR 2025 · [arXiv:2503.10689](https://arxiv.org/abs/2503.10689)

**Mechanism.** Decouple *understanding* from *deciding*: train a small **contextualisation module**
(Phi-3-mini for WebShop; Llama-3.1-8B for Work/WebArena) that rewrites the raw observation into a
compact annotated form, then hand that to any decision agent. Trained by iterative self-training:
sample K candidate contextualisations, score each by the **sum of action-matching scores across several
LLM agents**, SFT on the best; if all score zero, retry with the ground-truth action as a hint.

**Numbers.** WebShop (500 tasks) raw → iter-3: GPT-4o 34.8 → 50.6, Gemini-1.5-flash 43.6 → 62.8,
Claude-3.5-Sonnet 26.6 → 59.8, Llama-3.1-70B (unseen) 34.2 → 59.6. WorkArena (165 tasks, 1 iteration):
GPT-4o 38.2 → 44.2, Gemini-1.5-flash 11.5 → 41.2, Claude-3.5-Sonnet 44.8 → 55.8, **Llama-3.1-8B
1.2 → 37.0**. Averages: +15.6% (closed models) and +23.7% (open models) on WorkArena.

**Relevance to NetGent.** We won't train a module. But the **evaluation trick is free**: score a candidate
observation format by whether several LLMs pick the *ground-truth* action from it. That's a drop-in
objective for `netgent eval observation` — currently our A/B (e.g. `NETGENT_IFRAME_HEADERS=0`) has no
such metric. Also: the Llama-3.1-8B 1.2 → 37.0 result says observation quality dominates model quality
at the cheap end — exactly where our `anthropic/claude-haiku-4-5` explorer sits.

### AutoWebGLM — Lai et al., KDD 2024 · [arXiv:2404.03648](https://arxiv.org/abs/2404.03648)

**Mechanism.** An **HTML Pruner** that iteratively keeps operable components, text and attributes plus
their ancestors/descendants within a depth bound and deletes the rest, feeding a 6B ChatGLM3 agent
trained with curriculum SFT + rejection sampling + RL. Closed action space of 10:
`click`, `hover`, `select`, `type_string`, `scroll_page`, `go`, `jump_to`, `switch_tab`, `user_input`, `finish`.

**Numbers.** AutoWebBench 64.8% (EN cross-task) vs GPT-4 38.6%; Mind2Web 59.5% vs GPT-4 30.9%;
MiniWoB++ 89.3% vs GPT-4 32.1%; WebArena 18.2% vs GPT-4 14.4%.

**Relevance to NetGent.** Their 10-action set is almost exactly ours (we add `upload_file`/`wait`, they
add `user_input`). Worth noting they keep `hover` and `scroll_page` where AgentOccam deletes both —
the disagreement is real and is why an A/B on *our* traffic is warranted rather than copying either.

### Agent-E — Abuelsaad et al., 2024 · [arXiv:2407.13032](https://arxiv.org/abs/2407.13032)

**Mechanism.** Hierarchical planner + browser-navigator, with **DOM distillation** offering three
observation modes the agent picks between (`text_only`, `input_fields`, `all_fields`) and **change
observation** (report what changed after an action rather than re-dumping the page).

**Numbers.** WebVoyager **73.2%**, vs text-only WILBUR 52.6% (+20 pts) and multimodal WebVoyager 57.1%
(+16 pts). Efficiency (they claim first to report it): successful tasks average **150 s**, failed
**220 s**, range 68–286 s per site; **25 LLM calls/task** (6.4 planner + 18.6 navigator), range 14.5–53.8.

**Relevance to NetGent.** "Change observation" maps onto something we already half-have: our
observation-diff stuck detector compares whole observation strings. Reporting the *diff* to the model
(instead of only using it internally to detect no-progress) is a cheap prompt change. Their per-task
LLM-call budget (~25) is also a sane sanity bound for our `max_steps=25` default.

### FocusAgent — Kerboua et al., 2025 · [arXiv:2510.03204](https://arxiv.org/abs/2510.03204)

**Mechanism.** A **lightweight LLM retriever** picks the most relevant *lines* of the AxTree given the
task goal; the main agent only ever sees those lines.

**Numbers.** **>50% reduction in observation size at parity** with the full-observation baseline on
WorkArena and WebArena; a FocusAgent variant also **cuts prompt-injection attack success** (banner and
pop-up attacks) with no loss on attack-free tasks.

**Relevance to NetGent.** The cleanest published support for a task-conditioned filter in front of our
60-element cap. The injection result matters more than it looks: NetGent generates traffic on *live*
third-party pages, where ad/banner text lands in our observation verbatim.

### ACON — Kang et al., ICML 2026 · [arXiv:2510.00615](https://arxiv.org/abs/2510.00615)

**Mechanism.** Compress *both* observations and history; the compression **guidelines are optimised in
natural-language space** by analysing failures (compressed run failed where uncompressed succeeded →
rewrite the guideline), then distilled into a small compressor. No fine-tuning of the agent.

**Numbers.** **26–54% lower peak tokens**; up to **+46%** task success for small-LM agents; beats prior
compression baselines on AppWorld, OfficeBench and Multi-objective QA.

**Relevance to NetGent.** Our history is an unbounded `list[str]` on `BrowserAgent`, *shared across runs*
in a sweep — the exact failure mode ACON targets. Their "failure-driven guideline" loop is also a
model for how we could tune `SYSTEM_PROMPT` mechanically instead of by hand.

### UIFormer — Ran et al., 2025 · [arXiv:2512.13438](https://arxiv.org/abs/2512.13438)

**Mechanism.** Instead of hand-written heuristics, *search* for the UI→text transformation program: a
DSL of UI-specific transforms plus LLM-driven iterative refinement under **correctness and efficiency
rewards**.

**Numbers.** **48.7–55.8% token reduction** with maintained-or-improved success, across 3 UI navigation
benchmarks (Android + Web) and 5 LLMs; deployed at WeChat.

**Relevance to NetGent.** Direct commentary on `serializer.py`: our format is a hand-tuned heuristic
program. Their headline is that a searched program beats hand tuning by ~50% tokens at parity — a
plausible future eval, not a near-term change.

### Read More, Think More — Enomoto et al., 2026 · [arXiv:2604.01535](https://arxiv.org/abs/2604.01535)

**Mechanism.** Re-runs the "reduce the observation" assumption across model tiers and thinking budgets.
Representations: a11y tree (~6,720 input tokens), full HTML with CSS layout (~56,653), a11y+screenshot
(~7,446).

**Numbers (WorkArena L1, a11y → HTML).** Claude Sonnet 4.6 52.4 → **67.0** (+14.6); GPT-5.1 (high)
55.8 → **73.3** (+17.5); Gemini-2.5-flash (budget 16384) 45.5 → 56.7 (+11.2). *Reversed* for weak models:
GPT-oss-20b (high) 46.4 → **27.6** (−18.8); Llama-3.1-70b 18.2 → **3.6** (−14.6). Raising the thinking
budget widens HTML's advantage (GPT-5.1 low→high: +8.8 → +17.5; Gemini 128→16384: +6.0 → +11.2).
Error analysis: strong models exploit CSS/layout for grounding; weak models hallucinate more on long input.

**Relevance to NetGent.** This is the paper that should stop us from over-fitting the observation format.
Our explorer runs a *cheap* model by design (`anthropic/claude-haiku-4-5-20251001`), which sits on the
"compact wins" side — so the current compact format is right *for the default model*, and the
`--model` flag should probably select the observation profile too, not just the model string.

### Revisiting Observation Reduction (lightweight framework) — Enomoto et al., 2026 · [arXiv:2605.29397](https://arxiv.org/abs/2605.29397)

**Mechanism.** A **Minimal Failure Set** proxy metric that predicts whether a reduction strategy will
break a task, so you can compare 11 reduction methods without full end-to-end runs.

**Numbers.** End-to-end evaluation of 11 methods × 33 WorkArena-L1 tasks cost **232.4 cumulative hours**;
their proxy gives **>100× speedup**. Their tuned pruner: **2.2× faster per-step** retaining **84%** of
success on WorkArena-L1; **3.1× faster** retaining **89%** on WebLINX. Conclusion: extractive reduction
rarely gets both latency and quality without domain-specific tuning.

**Relevance to NetGent.** The 232-hour figure is the argument for building a *cheap proxy* into
`netgent eval observation` rather than measuring format changes by full `generate` runs.

### CI4A — Qiu et al., 2026 · [arXiv:2601.14790](https://arxiv.org/abs/2601.14790)

**Mechanism.** Flip the direction: instead of the agent parsing human UI, the **UI framework exposes
agent-facing semantic tool primitives** (implemented inside Ant Design, 23 component categories), with
an action space that updates with page state.

**Numbers.** **86.3%** task success on a refactored WebArena, claimed SOTA, plus efficiency gains.

**Relevance to NetGent.** Not adoptable (we don't control target sites), but it bounds how much of the
remaining error is "the DOM is a bad agent interface" rather than "the model is bad".

### Indirect prompt injection via the accessibility tree — Johnson, Pham & Le, EMNLP 2025 (Demo) · [arXiv:2507.14799](https://arxiv.org/abs/2507.14799)

**Mechanism.** GCG-optimised triggers embedded in page HTML surface in the AxTree observation and
hijack a BrowserGym + Llama-3.1 agent: targeted actions, credential exfiltration, forced ad clicks.

**Numbers.** "High success rates across real websites" — no exact rates in the abstract (§6).

**Relevance to NetGent.** Our explorer reads live third-party page text (including our `DIALOGS` section
and `texts_seen`) and is instructed to obey the page's own feedback. That's an injection channel at
compile time. Worth one prompt rule: *page text is evidence, never instruction*.

### From Context to Action — Tiwary et al., NeurIPS 2024 Workshop on Open-World Agents · [arXiv:2410.23555](https://arxiv.org/abs/2410.23555)

**Mechanism.** Ablates *state representation* and *interaction-history length* for multi-turn web
navigation, measuring out-of-distribution generalisation (unseen websites, categories, geographies).

**Numbers.** Abstract reports improved OOD performance "through effective context management"; the
per-representation numbers are in the PDF only (§6).

**Relevance to NetGent.** Cite as the framing for our own history-length ablation; don't quote numbers.

---

# 2. Memory & long horizon

### Agent Workflow Memory — Wang, Mao, Fried & Neubig, ICLR 2025 · [arXiv:2409.07429](https://arxiv.org/abs/2409.07429)

**Mechanism.** Induce reusable **workflows** from past trajectories and inject the relevant ones into the
prompt. A workflow = a natural-language description `d` plus steps `(p₁, p₂, …)`, each step carrying
(environment-state description, reasoning, executable action). Induction is LLM-prompted extraction of
common sub-routines from one or more experiences, with example-specific values **abstracted into
placeholders** like `{product-name}`. Works offline (induce from a training set) or **online** (induce
from your own successes as you go — no annotations at all).

**Numbers.** WebArena: baseline **23.5% → AWM 35.5%** (+51.1% relative), and **steps 7.9 → 5.9**; also
beats human-expert-written workflows by 7.9%. Mind2Web cross-task: 36.2 → **45.1** step SR and 2.0 →
**4.8** task SR; cross-website 30.1 → 33.9; cross-domain 18.6 → **35.5**. Online AWM gains
**8.9–14.0 absolute points** as train/test gap widens, over 1,000+ tasks / 200+ domains.

**Relevance to NetGent — top-3.** Two things. (1) The **step reduction (7.9 → 5.9) matters more to us
than the success bump**: fewer explorer steps = a shorter, cleaner trajectory = a smaller NFA. (2) Their
workflow record — description + steps + **placeholder-abstracted values** — is structurally the same
object as our `Param`-parameterised workflow. Our sweep already shares memory across `run()` calls, but
as an *unstructured* `list[str]`; AWM says make it a list of induced workflows keyed by description.

### Synapse — Zheng, Wang, Wang & An, ICLR 2024 · [arXiv:2306.07863](https://arxiv.org/abs/2306.07863)

**Mechanism.** Three parts: **state abstraction** (strip task-irrelevant page content so more exemplars
fit), **trajectory-as-exemplar prompting** (the exemplar is a whole state-action sequence, not a single
step), and an **exemplar memory** retrieved by embedding similarity for unseen tasks.

**Numbers.** MiniWoB++ **99.2%** mean success over 64 tasks (+10% relative over prior SOTA) using
demonstrations from only 48 tasks; first ICL method to solve `book-flight`. Mind2Web: **+56% relative**
mean step success over the previous best prompting method.

**Relevance to NetGent.** The "exemplar is a trajectory, not a step" claim is directly usable: when a
sweep moves to form 3 of 21, the right memory injection is *the whole successful trajectory for form 2*,
not our current one-line-per-step log. That's a change to `BrowserAgent.note()` / `history`.

### Reflexion — Shinn et al., NeurIPS 2023 · [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)

**Mechanism.** After a failed episode, the model writes a **verbal self-reflection** into an episodic
memory buffer that is prepended on the next attempt — reinforcement without gradient updates.

**Numbers.** HumanEval pass@1 **91%** vs GPT-4's 80%; also evaluated on ALFWorld and HotpotQA (numbers
not in the abstract — §6).

**Relevance to NetGent.** Only applicable across our `--runs N`: run 2 should start with run 1's failure
note. Today `agent.history` carries raw step logs across runs, not a distilled reflection.

### ExpeL — Zhao et al., AAAI 2024 · [arXiv:2308.10144](https://arxiv.org/abs/2308.10144)

**Mechanism.** Gather experiences on training tasks, then distil **natural-language insights** with four
operations over an evolving insight list — **ADD / UPVOTE / DOWNVOTE / EDIT**. Insights start with
importance 2, gain/lose on agreement, and are deleted at 0. At inference, retrieve the top-k most
similar successful trajectories (k=6 HotpotQA, k=2 ALFWorld, k=2 WebShop) plus the insight list.

**Numbers.** HotpotQA ReAct 28.0 ± 1.4 → ExpeL **39.0 ± 1.7**; ALFWorld 40.0 ± 0.3 → **59.0 ± 0.3**;
WebShop mean reward 0.665 → **0.701**; FEVER transfer 63 ± 0.4 → **70 ± 0.7**.

**Relevance to NetGent.** The vote-weighted insight list is the right data structure for the "site rules"
we currently hard-code in `SYSTEM_PROMPT` (date formats MM/DD/YYYY→DD/MM/YYYY, "click Skip first",
"a div with a name is a rich-text editor"). Those are hand-written ExpeL insights; they could be
*induced per site* during a sweep and stored beside the workflow.

### LASER — Ma et al., 2023/2024 · [arXiv:2309.08172](https://arxiv.org/abs/2309.08172)

**Mechanism.** Model the task as **transitions between a small set of predefined high-level states**
(for WebShop: 4 states), each with its own instruction and its own **permitted action set**, and allow
explicit **backtracking** to a previous state instead of forward-only rollout. State-specific
instructions replace in-context exemplars.

**Numbers.** WebShop: LASER **50.0% SR / 75.6 reward** vs ReAct 34.0 / 59.7, ASH 30.2 / 56.7, human expert
59.6 / 82.1. Transfer to live amazon.com (100 instructions): **62.0% SR / 85.4 reward** vs human 65.0 / 88.2.

**Relevance to NetGent — conceptually the closest paper in §2.** LASER *is* an NFA over page states with
per-state legal actions, hand-specified. NetGent's premise is that the compiler should **induce** that
automaton from exploration rather than have a human write it. Their +16-point gain over ReAct is the
best available evidence that state-conditioned action restriction beats a flat ReAct loop — i.e. that
our `Trigger`-guarded transitions are worth their complexity.

### Tree Search for Language Model Agents — Koh, McAleer, Fried & Salakhutdinov, 2024 · [arXiv:2407.01476](https://arxiv.org/abs/2407.01476)

**Mechanism.** Inference-time **best-first tree search** over web states with a value function, using
environment backtracking to explore multiple branches.

**Numbers.** VisualWebArena **18.9% → 26.4%** (+39.7% relative) with GPT-4o; WebArena **15.0% → 19.2%**
(+28.0% relative); performance scales with test-time compute.

**Relevance to NetGent.** Search *at compile time* is legitimate for us — the zero-LLM rule binds the
replayer, not the explorer. But backtracking on live third-party sites is often impossible (side effects,
no undo), which is precisely the objection WebDreamer raises next.

### WebDreamer — Gu et al., NAACL 2025 · [arXiv:2411.06559](https://arxiv.org/abs/2411.06559)

**Mechanism.** Use the LLM itself as a **world model**: simulate "what would the page look like if I
clicked X" in natural language, score the imagined outcomes, execute only the best. No real
backtracking, so it works on irreversible live sites.

**Numbers.** VisualWebArena: reactive 17.6% → WebDreamer (GPT-4o) **23.6%** vs tree search 26.2%;
Dreamer-7B 21.9%. Online-Mind2Web: reactive 26.0% → **37.0%** (Dreamer-7B 35.0%). Mind2Web-Live:
20.2% → **25.0%** (Dreamer-7B 24.0%). Efficiency: **~180 s vs ~750 s** per task for tree search
(the "4–5× more efficient" claim), with comparable step counts.

**Relevance to NetGent.** The strongest single-run improvement here (+11 points on Online-Mind2Web) costs
one extra LLM call per step and **no environment backtracking** — compatible with our `observe → decide
→ act` graph as an optional `simulate` node between `decide` and `act`. This is the highest-value
optional pipeline node in the whole review.

### WebRL — Qi et al., ICLR 2025 · [arXiv:2411.02337](https://arxiv.org/abs/2411.02337)

**Mechanism.** Self-evolving **online curriculum RL**: failed tasks are recycled into new, easier tasks
for the next round; an ORM supplies the reward; a KL-constrained policy update plus experience replay
keeps training stable.

**Numbers (WebArena-Lite).** Llama-3.1-8B **4.8% → 42.4%**; GLM-4-9B **6.1% → 43.0%**. Reference points:
GPT-4-Turbo 17.6%, GPT-4o 13.9%, AutoWebGLM 18.2%.

**Relevance to NetGent.** We don't train. The transferable idea is the **failure→curriculum** loop: when
`generate --runs N` has a run fail, the next run should get an easier, decomposed version of the same
task rather than an identical retry.

### OpenWebVoyager — He et al., 2024 · [arXiv:2410.19609](https://arxiv.org/abs/2410.19609)

**Mechanism.** Imitation-learn from GPT-4o trajectories, then loop: explore live web → filter with a
GPT-4o judge → SFT on the survivors → repeat.

**Numbers.** Base Idefics2-8b-instruct; IL from **1,165 trajectories / 7,253 turns**; each cycle ~480
queries yielding 152–207 successful trajectories. WebVoyager test (643 queries): IL 19.9% → **25.8%**
after 3 iterations. Mind2Web cross-task: 6.3 → **19.6%**; cross-website 6.6 → 10.4%.

**Relevance to NetGent.** A calibration point for exploration yield: ~**32–43% of exploration attempts
survive judging**. Our `--runs N` should assume a similar survival rate when budgeting runs, and the
synthesiser should be built to work from a *subset* of runs succeeding.

### AgentTrek — Xu et al., ICLR 2025 Spotlight · [arXiv:2412.09605](https://arxiv.org/abs/2412.09605)

**Mechanism.** Harvest **tutorial-like text from the web**, convert each tutorial into a task spec, replay
it with a VLM agent in a real browser, and keep only trajectories a judge accepts.

**Numbers.** **$0.55 per high-quality trajectory** with no human annotators; SOTA on WebArena and on
ScreenSpot-Web / Multimodal-Mind2Web (per-benchmark rates not in the abstract — §6).

**Relevance to NetGent.** The tutorial-as-task-spec trick is a way to auto-generate the natural-language
task strings that `netgent generate` takes as input — relevant if we ever want to scale dataset
generation beyond hand-written task prompts.

### Agent S — Agashe et al., ICLR 2025 · [arXiv:2410.08164](https://arxiv.org/abs/2410.08164)

**Mechanism.** Experience-augmented hierarchical planning for OS-level GUI agents: retrieve external web
knowledge *and* internal narrative/episodic memory at both the plan and the subtask level, behind an
Agent-Computer Interface.

**Numbers.** OSWorld **+9.37 absolute points (+83.6% relative)** over the baseline; generalises to
WindowsAgentArena.

**Relevance to NetGent.** The two-level memory split (narrative = "how tasks of this shape usually go";
episodic = "the exact steps that worked") is the right shape for our sweep memory: one narrative entry
per site, one episodic entry per completed form.

### AgentFold — Ye et al., 2025 · [arXiv:2510.24699](https://arxiv.org/abs/2510.24699)

**Mechanism.** **Proactive context folding**: at each step choose between a fine-grained condensation
(keep details of the last step) and a deep consolidation (abstract a whole multi-step subtask away) —
as opposed to ReAct's unbounded accumulation or fixed-window summarisation's irreversible loss.

**Numbers.** BrowseComp **36.2%**, BrowseComp-ZH **47.3%** (AgentFold-30B-A3B, SFT only), claimed to
match/beat DeepSeek-V3.1-671B and o4-mini.

**Relevance to NetGent.** A concrete policy for our flat history: when a sub-goal completes (a form
submitted, a dialog confirmed), replace its N step-lines with one consolidated line. Cheap to implement
in `graph.py::act` where we already append the history line.

### Evaluating Long-Context Reasoning in LLM-Based WebAgents — Chung et al., NeurIPS 2025 LAW Workshop · [arXiv:2512.04307](https://arxiv.org/abs/2512.04307)

**Mechanism.** Chains of sequentially dependent subtasks that force retrieval from earlier interaction
history, sweeping context from **25k to 150k tokens**.

**Numbers.** Success falls from **40–50% baseline to <10%** at long context, for Claude-3.7, GPT-4.1,
Llama 4 and o4-mini alike. The two dominant failures: **stuck in loops** and **losing track of the
original objective**. An implicit-RAG summariser gives only modest improvement.

**Relevance to NetGent.** Direct empirical backing for two things we already do (`MAX_REPEAT=3` loop
detection; a hard `max_steps` budget) and one we don't (bounding the history). It also says the fix is
*not* "summarise the history" — that only helped modestly.

---

# 3. Action space & tool calling

### WebShop — Yao, Chen, Yang & Narasimhan, NeurIPS 2022 · [arXiv:2207.01206](https://arxiv.org/abs/2207.01206)

**Mechanism.** 1.18M real products, 12,087 crowd-sourced instructions; a deliberately **tiny action
grammar**: `search[query]` and `click[button]`, where the legal `click` targets are whatever the current
page shows — i.e. the action space is *state-dependent by construction*.

**Numbers.** Best model **29%** task success vs rule heuristic 9.6% vs human expert **59%**; 1,600+ human
demonstrations; non-trivial sim-to-real transfer to amazon.com and ebay.com.

**Relevance to NetGent.** The ancestor of "actions are indices into the current observation" — the same
contract as our `AgentDecision.index`. It also shows how far a 2-verb action space can go.

### WebGPT — Nakano et al., 2021/2022 · [arXiv:2112.09332](https://arxiv.org/abs/2112.09332)

**Mechanism.** Fine-tune GPT-3 in a **text-only browsing environment** with a fixed command grammar
(search, click link, quote, scroll, …), behaviour-cloned from human demonstrations then improved by
rejection sampling against a preference reward model; references must be collected while browsing.

**Numbers.** Answers preferred to human demonstrators **56%** of the time and to the top Reddit answer
**69%** of the time (ELI5).

**Relevance to NetGent.** Historical anchor for text-only browsing + a closed command grammar. Its
"collect evidence while acting" idea is what our `texts_seen` accumulation does for post-hoc verification.

### SteP — Sodhi, Branavan, Artzi & McDonald, COLM 2024 · [arXiv:2310.03720](https://arxiv.org/abs/2310.03720)

**Mechanism.** Rather than one mega-prompt handling every state (which causes "behaviour leakage"),
decompose the policy into sub-policies and let the agent **push/pop policies onto a stack** — an MDP
whose state includes the chain of policy calls, so the hierarchy is dynamic rather than fixed.

**Numbers.** WebArena **14.9% → 33.5%** over GPT-4 SOTA; competitive on MiniWoB++ (96.0% per WebPilot's
comparison table) with far less data; also evaluated on a CRM environment.

**Relevance to NetGent.** Our `SYSTEM_PROMPT` is exactly the "one large prompt for all behaviours" that
SteP argues against — it currently mixes ad-skipping, date formats, iframe semantics, scroll discipline,
CAPTCHA policy and upload handling. Splitting it into state-conditioned fragments (only show the
form-filling rules when a form is on screen) is a low-risk, high-expected-value prompt change.

### WebPilot — Zhang et al., AAAI 2025 · [arXiv:2408.15978](https://arxiv.org/abs/2408.15978)

**Mechanism.** Multi-agent MCTS with global (decompose into subtasks, refine as the world changes) and
local (MCTS within a subtask, handling partial observability) phases.

**Numbers.** WebArena **37.2%** with GPT-4o (CMS 24.7, Map 33.9, Shopping 36.9, Reddit 65.1, GitLab 39.4);
**29.1%** with GPT-3.5; MiniWoB++ **95.6%** (vs SteP 96.0). +93% relative over the concurrent tree-search
method at 19.2%; +11.0 absolute over SteP's 33.5%.

**Relevance to NetGent.** Reference point for what heavy compile-time search buys (~+4 pts over SteP for
a lot of machinery). Given our compile-once amortisation, "expensive but better" is more defensible for
us than for a runtime agent — but WebDreamer's cost/benefit is better.

### Go-Browse — Gandhi & Neubig, ICLR 2026 · [arXiv:2506.03533](https://arxiv.org/abs/2506.03533)

**Mechanism.** Data collection as **graph search over the website**: keep a graph of discovered pages,
re-enter promising nodes across episodes instead of restarting from the homepage, and propose feasible
tasks from each node.

**Numbers.** **10K successful trajectories / 40K interaction steps over 100 URLs**; fine-tuned 7B model
scores **21.7%** on WebArena — +2.4 points over GPT-4o-mini and +2.9 over the best sub-10B model.

**Relevance to NetGent.** `netgent generate --runs N` currently runs N **independent** explorations from
the same start URL — Go-Browse's core claim is that this wastes most of the budget. A shared frontier of
visited states across runs is the natural upgrade, and it also directly serves the synthesiser: the graph
of states *is* the NFA skeleton we are trying to build.

### AgentBench — Liu et al., ICLR 2024 · [arXiv:2308.03688](https://arxiv.org/abs/2308.03688)

**Mechanism.** 8 environments (incl. web browsing and web shopping) evaluating LLMs specifically *as*
agents over multiple turns.

**Numbers.** Large commercial-vs-open gap for ≤70B models; the named obstacles are **long-term reasoning,
decision-making and instruction following**; training on multi-round alignment data helps, code training
has ambivalent effects.

**Relevance to NetGent.** "Instruction following" being a top-3 named failure is the empirical case for
our structured-output decision object (invalid output can't crash the run) and for the `_coerce_index`
validator that repairs `"[3]"` → `3`.

### AgentBoard — Ma et al., NeurIPS 2024 Oral · [arXiv:2401.13178](https://arxiv.org/abs/2401.13178)

**Mechanism.** Replaces binary success with a **progress rate** built from subgoal completion / continuous
matching, over 9 task types and **1,013 environments**.

**Numbers.** GPT-4: **70.0% average progress rate** but only **47.9% success**. Open-weight models (except
Llama3-70b, Deepseek-67b) **stop progressing after about 6 steps**. Agents rarely recover from mistakes;
grounding (action-format accuracy), world modelling and self-reflection are the discriminating abilities.

**Relevance to NetGent.** Two things. (1) Progress-rate is the metric our sweep eval should report —
"filled 17 of 21 forms" is the number we care about, not a binary. (2) "~6 steps then stall" for
mid-tier models is a hard constraint on `max_steps=25` with a Haiku-class explorer: we should expect
long tasks to need decomposition, not a bigger budget.

### τ-bench — Yao, Shinn, Razavi & Narasimhan, 2024 · [arXiv:2406.12045](https://arxiv.org/abs/2406.12045)

**Mechanism.** Tool-agent-user interaction under written domain policies, scored by comparing the final
**database state**; introduces **pass^k** — the probability that *all k* independent trials succeed.

**Numbers.** GPT-4o pass@1 **<50%**; **pass^8 < 25%** in the retail domain — i.e. agents are drastically
inconsistent across identical repeated trials.

**Relevance to NetGent — under-appreciated.** pass^k is the right metric for a *dataset generator*: if
a compiled workflow must replay identically thousands of times, single-run success is the wrong number.
Our `validate` node should be run k times and report pass^k, not pass@1. This is a concrete change to
`agent/validator/`.

### Let Me Speak Freely? — Tam et al., EMNLP 2024 Industry · [arXiv:2408.02442](https://arxiv.org/abs/2408.02442)

**Mechanism.** Compares free-form generation against JSON/XML-constrained generation (format-restricted
prompting and constrained decoding) across reasoning and classification tasks.

**Numbers.** A "significant decline in LLM reasoning abilities under format restrictions", with stricter
constraints causing larger degradation; classification is largely unaffected. Exact per-task deltas are
in the PDF (§6).

**Relevance to NetGent.** We make **one structured-output call per step** and ask for reasoning *inside*
the schema. The mitigation this literature supports is exactly our field order — `reasoning` is declared
first in `AgentDecision`, so it is generated before `kind`/`index`. Worth a comment in `decision.py`
citing this so nobody "tidies" the field order later. See also **JSONSchemaBench**
([arXiv:2501.10868](https://arxiv.org/abs/2501.10868)) for coverage/efficiency of constrained-decoding backends.

### Where LLM Agents Fail and How They Can Learn From Failures — Zhu et al., 2025 · [arXiv:2509.25370](https://arxiv.org/abs/2509.25370)

**Mechanism.** An **AgentErrorTaxonomy** across memory / reflection / planning / action / system, an
annotated failure-trajectory dataset (**AgentErrorBench**, from ALFWorld, GAIA, WebShop), and
**AgentDebug**, which isolates the *root-cause* step and feeds back targeted corrective feedback rather
than a generic "you failed".

**Numbers.** **+24%** all-correct accuracy and **+17%** step accuracy over the strongest baseline at
root-cause identification; **up to +26% relative** task success from iterative recovery. Framing result:
one root-cause error cascades and is hard to reverse once started.

**Relevance to NetGent.** Our `graph.py::act` already echoes failures into history (`-> FAILED: {error}`)
— that's generic feedback. The paper's result says *root-cause attribution* is worth ~+26% relative,
which for a compile-time agent could be a `diagnose` node that runs once when the run ends unsuccessfully
and writes one corrective note for the next run.

### AgentRewardBench — Lù et al., 2025 · [arXiv:2504.08942](https://arxiv.org/abs/2504.08942)

**Mechanism.** **1,302 expert-annotated trajectories** across 5 benchmarks and 4 agent backbones, used to
measure how well 12 LLM judges (and rule-based evaluators) recognise success.

**Numbers.** Best judges: GPT-4o **69.8% precision**, Claude-3.7-Sonnet **68.8%** (both using the
simplified judge design over accessibility trees) — no judge wins everywhere. **Rule-based evaluation
under-reports success by 16.7 points on WebArena and 18.5 points on VisualWebArena** for GPT-4o, with
only **55.9% recall** on WebArena.

**Relevance to NetGent.** Sobering for our `validate` node in both directions: a strict rule-based
replay check will call working workflows broken (false negatives), and an LLM judge is only ~70%
precise. The design implication is to make the *replay itself* the oracle — which is exactly what
NetGent does by re-running the NFA zero-LLM — and to report pass^k rather than trusting one verdict.

### An Illusion of Progress? / Online-Mind2Web + WebJudge — Xue et al., COLM 2025 · [arXiv:2504.01382](https://arxiv.org/abs/2504.01382)

**Mechanism.** 300 realistic tasks over **136 live websites**, plus **WebJudge**, an LLM autoeval that
first identifies key screenshots/steps then judges against them.

**Numbers.** WebJudge (GPT-4o-mini) reaches **~85% agreement with humans** and only a **3.8% average
success-rate gap**, beating WebVoyager's and AgentTrek's autoevals. Agents: OpenAI Operator **61.3%**,
Claude Computer Use 3.7 **56.3%**, SeeAct / Browser Use / Agent-E all **28–30%**. Headline: a naive
search-based agent scores **51% on WebVoyager's tasks but only 22% on Online-Mind2Web** — most agents
released after early 2024 do not actually beat the original SeeAct.

**Relevance to NetGent.** The best available recipe for our `validate` judge (key-step identification
first, judge second) *and* a caution about benchmark shopping: our own evals should be live-site,
not fixture-only. Also note `texts_seen` in `AgentTrajectory` is already the key-evidence buffer
WebJudge would need.

### Skim — Wong, Hsieh, Nath & Netravali, 2026 · [arXiv:2605.16565](https://arxiv.org/abs/2605.16565)

**Mechanism.** Offline profiler learns URL patterns and task→trajectory mappings for a site; at runtime,
match the query to a template, **synthesise the destination URL directly**, extract with a small model,
and verify — falling back to the full agent only when the verifier objects.

**Numbers.** **1.9× median per-task cost reduction**, **33.4% lower latency**, **no accuracy loss**, over
three backbones (WebVoyager, AgentOccam, BrowserUse).

**Relevance to NetGent.** This is essentially NetGent's thesis published as a systems optimisation:
profile offline, replay cheaply, verify, fall back. The *verifier-with-fallback* structure is worth
copying into our executor's error path — but only as a compile-time repair trigger, never as a runtime
LLM call (that would break the zero-LLM rule).

---

# 4. Workflow / skill induction from exploration (closest to NetGent's product)

### SkillWeaver — Zheng et al., 2025 · [arXiv:2504.07079](https://arxiv.org/abs/2504.07079)

**Mechanism.** Autonomously explore a website and distil what worked into **Python functions containing
Playwright code**, each with a signature, docstring and a usage log. Three stages: **propose** skills
from observations/a11y tree → **synthesise** (practise the skill, convert the successful trajectory to
an API, static-analyse for common generation errors) → **hone** (LLM writes test cases for parameterised
APIs, executes them, debugs failures). ~160 exploration iterations per website.

**Numbers.** WebArena: baseline **12.3% → 29.8%** average across Gitlab/Map/Shopping/CMS/Reddit
(reported as **+31.8% relative**). Live sites (Online-Mind2Web tasks, 44 websites / 57 tasks):
**+39.8% relative**. Weak-to-strong transfer: GPT-4o-mini using GPT-4o-synthesised APIs goes
**9.2% → 14.1%** average, with per-domain gains of **40–133%** (the "54.3%" headline).

**Relevance to NetGent — closest published system to `netgent generate`.** Same shape (explore → induce
→ verify), different artifact: they emit **Playwright code**, we emit a **declarative NFA**. Their own
limitation section — weak models can't pick the right API or fill its parameters — is an argument for
our artifact choice: a parameterised NFA replayed by a deterministic executor has no "pick the right
API" step at all. The honing loop (auto-generate test cases per parameterised skill) is the direct
analogue of running `validate` with several `--param` values, which we should do.

### Agent Skill Induction (ASI) — Wang, Gandhi, Neubig & Fried, 2025 · [arXiv:2504.06821](https://arxiv.org/abs/2504.06821)

**Mechanism.** Induce, **verify**, and use **program-based skills on the fly**: generate an action
trajectory, induce a Python program that wraps primitive actions into a higher-level function, and only
admit the skill if it **executes correctly against test trajectories**.

**Numbers.** WebArena: **+23.5%** success over the static baseline and **+11.3%** over its own
*text-skill* counterpart (skills written as prose instead of programs); **−10.7 to −15.3% action steps**.
Skills transfer across websites, with adaptation when sites change.

**Relevance to NetGent — the single most important comparison in this document.** ASI's controlled
result is *programmatic skills beat text skills by 11.3 points, because programs can be verified*.
NetGent's YAML NFA is a third point on that axis: verifiable like a program, but declarative (no code
in artifacts, per our formalism). ASI is the empirical justification for the "verify before admitting"
gate that our `validate` node implements — and the step-reduction number (−10.7–15.3%) is what we should
expect from compiling repeated sub-sequences into a `control_sequence`.

### ReUseIt — Liu, Sra, Inala & Wang, ACM IUI 2026 · [arXiv:2510.14308](https://arxiv.org/abs/2510.14308)

**Mechanism.** Run task **variations multiple times**, then mine both the failures and the successes:
agent challenges observed at failed steps become **condition checks (execution guards)**, and successful
experiences become **fallback actions** for self-recovery. The result is a reusable, human-readable
workflow that keeps the user informed of progress and problems.

**Numbers.** **24.2% → 70.1%** success across fifteen tasks (reported elsewhere as +45.9 points);
9-participant user study showing higher success with less guidance than baselines.

**Relevance to NetGent — direct product analogue.** Their "condition checks at failed steps" are exactly
our **state triggers** (`url_matches`, `selector_visible`, …), and their "run variations multiple times"
is exactly `--runs N --variation name=value`. The gap: we currently synthesise from *successful* runs and
discard failures; ReUseIt's result says the **failed runs are where the guards come from**. That is the
highest-value change to `agent/generator/` in this review.

### Alloy — Li, Ning, Tian & Li, 2025 · [arXiv:2510.10049](https://arxiv.org/abs/2510.10049)

**Mechanism.** Generate reusable web-agent workflows from **user demonstration** instead of prompts,
rendering them as transparent, editable, visualised workflows that generalise across task variations.

**Numbers.** 12-participant study; demonstration-based workflows outperformed prompt-based agents and
manual workflows at capturing intent and procedural preferences (no automated success rates in the
abstract — §6).

**Relevance to NetGent.** Supports the "artifact must be human-inspectable and editable" property our
YAML has. Not a source of numbers.

### SKILL.nb — El Hattami, Chapados & Pal, 2026 · [arXiv:2606.08049](https://arxiv.org/abs/2606.08049)

**Mechanism.** **Selective formalisation**: execution evidence decides which workflow steps become
deterministic code and which stay natural-language-guided. Each step carries **validation gates**; a step
runs its code when its gates validate, and falls back locally when drift invalidates the executable form.

**Numbers.** WebArena-Verified **53.7%** single-round success (**+3.9 pts** over the strongest baseline);
across re-executions it **retains 91.7% of initially successful tasks (+15.5 pts** over the next best);
recovers **72.9%** of subsequent failures under bounded repair, with post-repair regressions of **4.2%**
vs 15.0–17.0% for baselines; leads Mind2Web cross-website/cross-domain; on a GitLab version migration the
frozen-vs-fresh gap is **−1.7 pts (16.11)** and **+0.6 pts (18.9)**.

**Relevance to NetGent — the most directly comparable numbers in the entire review.** *Replay retention*
(91.7% of successes survive re-execution) is precisely the metric NetGent's product needs and that
nobody else reports. Their gates ≈ our triggers; their selective formalisation is the choice we made
globally (everything is formalised, no NL fallback), which predicts we should beat 91.7% on retention
and lose on first-round coverage. **`netgent eval` should report exactly this number.**

### WebXSkill — Wang et al., 2026 · [arXiv:2604.13318](https://arxiv.org/abs/2604.13318)

**Mechanism.** Skills pair a **parameterised action program** with **step-level natural-language
guidance**; mined from synthetic trajectories, indexed in a **URL-keyed graph** for retrieval, deployed
in either grounded (auto-execute) or guided (step-by-step instruction) mode.

**Numbers.** **+9.8 points** task success on WebArena, **+12.9 points** on WebVoyager.

**Relevance to NetGent.** URL-keyed skill indexing is a clean retrieval key we could adopt for
cross-run memory in a sweep (our `history` has no index at all). The dual grounded/guided mode is the
same hedge SKILL.nb makes and that we deliberately don't.

### NNetNav — Murty, Zhu, Bahdanau & Manning, ACL 2025 · [arXiv:2410.02907](https://arxiv.org/abs/2410.02907)

**Mechanism.** Unsupervised: interact with websites, then **retroactively label** the exploration with
whatever instruction it happened to accomplish, and **prune** an episode as soon as its prefix can't be
labelled as a meaningful subtask — exploiting the hierarchy of tasks to keep search tractable.

**Numbers.** **10K synthetic demonstrations**; fine-tuned Llama-3.1-8B reaches **16% on WebArena
(+15 points over zero-shot)** and **35% on WebVoyager (+31 points)**, exceeding zero-shot GPT-4 and
setting the unsupervised SOTA.

**Relevance to NetGent.** Retroactive relabelling is the answer to "what do we do with an exploration run
that failed the given task but did something coherent?" — today `generate` throws it away. Their pruning
rule (kill an episode whose prefix isn't a describable subtask) is also a better stuck-detector than our
observation-equality heuristic.

### Explorer — Pahuja et al., ACL 2025 Findings · [arXiv:2502.11357](https://arxiv.org/abs/2502.11357)

**Mechanism.** Four-stage synthesis pipeline: **task proposer** (from a homepage) → **task refiner**
(revise during exploration) → **task summariser** (write the description that actually matches the
executed actions) → **task verifier** (LLM checks completion). Trajectory-first, description-second —
the opposite of task-first pipelines.

**Numbers.** **94K successful trajectories / 49K unique URLs / 720K screenshots / 33M web elements** at
**$0.28 per successful trajectory** (53.1% attempt success rate, ~2× cheaper than AgentTrek).
Mind2Web-Live: Explorer-7B **45.3% step SR / 19.3% task SR** vs Qwen2-VL-7B 14.5% and GPT-3.5 15.4%.
Multimodal-Mind2Web: **54.3%** step SR (beats AgentTrek-7B 53.2%). MiniWob++ zero-shot: Explorer-7B
**53.26%** (> GPT-4 53.04%), Explorer-4B 46.74%.

**Relevance to NetGent.** The **summariser** stage is the missing node in our pipeline: after a run, we
keep the *original* task string even when the agent actually accomplished something slightly different.
Rewriting the task to match the trajectory before synthesis would make the compiled workflow's `task`
field honest, and directly improves the `validate` step's job. The 53.1% attempt-success rate is another
calibration point for `--runs N`.

### InSTA — Trabucco, Sigurdsson, Piramuthu & Salakhutdinov, 2025 · [arXiv:2502.06776](https://arxiv.org/abs/2502.06776)

**Mechanism.** Three LLM stages replacing human annotation entirely: an LLM **proposes a realistic task**
for each website, an agent **attempts** it, an LLM **judges and filters** the trajectory.

**Numbers.** **150k sites** annotated; harmful-content filter **97%** accurate; the trajectory judge
agrees with humans **82.6%** of the time. A **Qwen3-1.7B** agent trained on the result reaches **56.9%**
success — **94.7% of Gemini 2.5 Flash's performance** — beating Qwen3-235B (235× larger) and
Llama 4 Maverick; zero-shot transfer demonstrated on WebVoyager.

**Relevance to NetGent.** The 82.6% judge agreement is the realistic ceiling for an LLM-only success
verdict — and it is *below* what a zero-LLM replay check gives us for free. Good ammunition for the
design rule that verification should be execution-based, not judgement-based.

### PAE (Proposer-Agent-Evaluator) — Zhou et al., ICML 2025 · [arXiv:2412.13194](https://arxiv.org/abs/2412.13194)

**Mechanism.** A **context-aware task proposer** invents tasks from website context, the agent attempts
them, and a **VLM evaluator** supplies the reward for RL — autonomous skill discovery with no
human-written task set.

**Numbers.** LLaVa-7B: WebVoyager 14.9% (SFT) → **22.3%** (PAE), WebArena-Easy 18.0% → **24.6%**; the
paper reports averages of **+7.4** and **+10.8** absolute points respectively. Against open-source SOTA,
**22.6% → 33.0%** on WebVoyager despite a much smaller base model. Evaluator misalignment with humans:
**1.7% system-level, 8.6% instance-level**.

**Relevance to NetGent.** The proposer is how we'd generate task strings at scale for dataset production;
the evaluator's **8.6% instance-level misalignment** is another datapoint that per-trajectory LLM
verdicts are noisy even when the aggregate looks fine — argues for aggregating over `--runs N` rather
than trusting a single `done(success=true)`.

### WebSynthesis — Gao, Ye, Wang & Sang, ACL 2026 · [arXiv:2507.04370](https://arxiv.org/abs/2507.04370)

**Mechanism.** Train a **world model** (Qwen2.5-7B-Instruct) to predict the next observation (DOM /
accessibility tree) from (observation, action), then run **MCTS inside the world model** — reversible,
cheap planning — and use the resulting trajectories for behaviour cloning. Two-stage curriculum: UI
understanding, then UI behaviour cloning.

**Numbers.** WebArena Pass@3: WebSynthesis **20.15%** vs OS-Genesis-7B **18.66%** (7.4k *real*
trajectories) vs AgentTrek-7B **11.94%** (20k tutorial trajectories) — using ~**4k synthetic**
trajectories. Training mix: ~2k dense captioning, ~6k element functionality, ~7k state-transition
prediction, ~4k valuable/rollback trajectories.

**Relevance to NetGent.** Their **state-transition prediction** training data (observation + action →
next observation) is exactly the supervision our trajectories already contain — every `AgentStep` has
pre/post URL and the observation was rendered on both sides. If we ever want a NetGent-specific model,
the data is a by-product of `--trajectory DIR`.

### A Survey of WebAgents — Ning et al., KDD 2025 · [arXiv:2503.23350](https://arxiv.org/abs/2503.23350)

Survey covering architectures, training and trustworthiness for LFM-based web agents. Useful as a
citation net; the taxonomy details are not in the abstract (§6).

---

# 5. Top 10 actionable findings for the NetGent explorer

Ranked by expected impact on our compile-time agent, each mapped to one concrete change.

| # | Finding (source, number) | Concrete change | Where |
|---|---|---|---|
| 1 | **Deleting actions beat every other single change**: WebArena 16.5% → 28.2% from removing `hover`/`press`/`scroll`/tab/`goto` alone (AgentOccam, [2410.13825](https://arxiv.org/abs/2410.13825)) | Restrict the **explorer's** `AgentActionKind` to `click, fill, select, upload, wait, done` (+`scroll` only when the observation says "↓ N more below"); keep the full set in `schema/actions.py` for the workflow artifact. A/B on the form sweep. | action-space — `agent/explorer/decision.py` |
| 2 | **Guards must be mined from *failed* runs**: 24.2% → 70.1% when failure-derived condition checks are added (ReUseIt, [2510.14308](https://arxiv.org/abs/2510.14308)) | Stop discarding unsuccessful runs in `generate`. Feed failed trajectories to the synthesiser as a *source of triggers*: a step that failed until condition C held becomes a `Trigger` on the target state. | pipeline node — `agent/generator/` + `orchestrator.py` |
| 3 | **Replay retention is the metric our product needs, and it's ~91.7% for the best gated system** (SKILL.nb, [2606.08049](https://arxiv.org/abs/2606.08049)); **pass^8 < 25% for tool agents** (τ-bench, [2406.12045](https://arxiv.org/abs/2406.12045)) | Make `validate` run the compiled NFA **k times** (k≥3, varying `--param`) and report **pass^k / retention**, not a single boolean. | pipeline node — `agent/validator/` + `netgent eval` |
| 4 | **Induced workflows cut steps as well as raising success**: 23.5 → 35.5% and **7.9 → 5.9 steps**, with values abstracted to `{placeholders}` (AWM, [2409.07429](https://arxiv.org/abs/2409.07429)); ASI −10.7–15.3% steps (**verified** programs beat prose skills by 11.3 pts, [2504.06821](https://arxiv.org/abs/2504.06821)) | Replace `BrowserAgent.history: list[str]` with a structured memory holding induced workflows (`description`, `steps`, placeholder params) built from *completed* sub-tasks in a sweep, injected on later runs. | memory field — `agent/explorer/browser_agent.py` |
| 5 | **Observation format should follow the model tier**: a11y → HTML is +17.5 pts for GPT-5.1 but −18.8 for GPT-oss-20b (Read More Think More, [2604.01535](https://arxiv.org/abs/2604.01535)); goal-conditioned trimming is free (FocusAgent >50%, [2510.03204](https://arxiv.org/abs/2510.03204)) | Two changes: (a) tie the serializer's verbosity profile to the configured explorer model, not a constant `limit=60`; (b) add a goal-conditioned line filter in front of the cap. | observation format — `browser/dom/serializer.py` |
| 6 | **Textual choices beat image marks by ~19 step-SR points; oracle grounding is +22 over the best real grounding** (SeeAct, [2401.01614](https://arxiv.org/abs/2401.01614)); a **DeBERTa-base** ranker hits **Recall@50 = 88.9%** (Mind2Web, [2306.06070](https://arxiv.org/abs/2306.06070)) | Keep text-only (confirmed), and spend the effort on element *identity*: task-conditioned re-rank before the 60-element cut, and better labels (merge `StaticText` into its labelled control, per AgentOccam's obs-opt). | observation format — `browser/dom/serializer.py`, `observer.py` |
| 7 | **Long context collapses agents**: 40–50% → <10% from 25k→150k tokens, failing by loops and goal drift ([2512.04307](https://arxiv.org/abs/2512.04307)); folding/compression recovers up to +46% for small models (AgentFold [2510.24699](https://arxiv.org/abs/2510.24699), ACON [2510.00615](https://arxiv.org/abs/2510.00615)) | Bound `history`: fold a completed sub-goal's N lines into one consolidated line (form submitted / dialog confirmed), and hard-cap total history tokens. Our cross-run sweep history is the biggest offender. | memory field — `agent/explorer/graph.py::act` |
| 8 | **One mega-prompt causes behaviour leakage**; state-conditioned sub-policies took WebArena 14.9 → 33.5% (SteP, [2310.03720](https://arxiv.org/abs/2310.03720)) | Split `SYSTEM_PROMPT` into a small core plus **conditionally-injected fragments** (form rules only when inputs are listed; ad/skip rules only when a media element is present; upload rules only when `input[file]` is listed). | prompt rule — `agent/explorer/prompt.py` |
| 9 | **Simulating the next state beats reacting, cheaply**: Online-Mind2Web 26.0 → 37.0%, ~180 s vs ~750 s for tree search (WebDreamer, [2411.06559](https://arxiv.org/abs/2411.06559)); root-cause feedback is worth up to +26% relative (AgentDebug, [2509.25370](https://arxiv.org/abs/2509.25370)) | Optional `simulate` node between `decide` and `act` (predict the post-action observation, re-decide on mismatch) — legitimate because it's compile-time only; plus a `diagnose` node on unsuccessful runs that writes one root-cause note for the next run. | pipeline node — `agent/explorer/graph.py` |
| 10 | **Independent restarts waste exploration budget**: graph-structured re-entry gave 10K trajectories over 100 URLs and beat GPT-4o-mini at 7B (Go-Browse, [2506.03533](https://arxiv.org/abs/2506.03533)); retroactive relabelling salvages "failed" episodes (NNetNav, [2410.02907](https://arxiv.org/abs/2410.02907)); a **task summariser** makes the description match what was actually done (Explorer, [2502.11357](https://arxiv.org/abs/2502.11357)) | Give `--runs N` a shared state frontier instead of N cold starts, and add a post-run **summariser** that rewrites the task to match the trajectory before synthesis. The frontier graph doubles as the NFA skeleton. | pipeline node — `agent/orchestrator.py` |

**Runner-up (not in the table but cheap):** put a one-line comment in `decision.py` recording that
`reasoning` must stay the **first** field, because format restriction degrades reasoning and free-form
tokens generated *before* the constrained fields are the standard mitigation
(Let Me Speak Freely, [2408.02442](https://arxiv.org/abs/2408.02442)).

---

# 6. Claims I could NOT verify from the paper text

Listed so nobody cites these as if they were read.

1. **Set-of-Mark web-agent numbers** ([2310.11441](https://arxiv.org/abs/2310.11441)) — the abstract gives
   only a RefCOCOg zero-shot claim. Every web-specific SoM verdict here comes from SeeAct and
   VisualWebArena, not from the SoM paper.
2. **WebArena observation-format ablation** — I could not find a table in the paper (abs, v4 HTML, or
   ar5iv) comparing success rates for accessibility tree vs raw HTML vs screenshot. WebArena *supports*
   all three; the baselines are a11y-tree only. Any "WebArena showed a11y beats HTML" claim is not
   supported by the paper text.
3. **BrowserGym axtree-vs-pruned_html results** ([2412.05467](https://arxiv.org/abs/2412.05467)) — the
   ecosystem paper reports per-model/per-benchmark success but, in the HTML I read, **no systematic
   observation-modality ablation**. The axtree-vs-HTML *token-size* argument comes from WorkArena
   ([2403.07718](https://arxiv.org/abs/2403.07718): HTML 40k–500k tokens); the *success-rate* comparison
   comes from Read More, Think More ([2604.01535](https://arxiv.org/abs/2604.01535)).
4. **Agent-E DOM-distillation ablation** ([2407.13032](https://arxiv.org/abs/2407.13032)) — the paper
   describes `text_only` / `input_fields` / `all_fields` and change-observation but, in the v1 HTML I
   read, gives **no isolated ablation numbers** for either. The 73.2% WebVoyager figure is verified;
   attributing a share of it to DOM distillation is not.
5. **WebVoyager text-only ablation magnitude** ([2401.13919](https://arxiv.org/abs/2401.13919)) — the
   abstract says WebVoyager beats "GPT-4 (All Tools) and text-only" but gives no text-only number. Do
   not quote a text-only delta.
6. **AgentTrek per-benchmark success rates** ([2412.09605](https://arxiv.org/abs/2412.09605)) — only
   "$0.55/trajectory" and "SOTA on WebArena / ScreenSpot-Web / Multimodal Mind2Web" were verifiable.
7. **Reflexion's ALFWorld and HotpotQA numbers** ([2303.11366](https://arxiv.org/abs/2303.11366)) — only
   HumanEval 91% vs 80% is in the abstract. (ExpeL's table gives *its own* ReAct/Reflexion re-runs:
   Reflexion R3 = 40.3% HotpotQA / 54.4% ALFWorld — those are ExpeL's numbers, not Reflexion's.)
8. **"Let Me Speak Freely" per-task degradation percentages** ([2408.02442](https://arxiv.org/abs/2408.02442))
   — the direction ("significant decline", "stricter → worse") is verified; exact deltas are in the PDF
   body, which I did not read.
9. **Indirect-prompt-injection attack success rates** ([2507.14799](https://arxiv.org/abs/2507.14799)) —
   "high success rates" only; no percentages in the abstract.
10. **Alloy quantitative results** ([2510.10049](https://arxiv.org/abs/2510.10049)) — 12 participants and
    a qualitative "outperformed" claim; no success rates.
11. **From Context to Action per-representation numbers** ([2410.23555](https://arxiv.org/abs/2410.23555))
    — abstract only; the HTML/a11y/screenshot × history-length table is in the PDF.
12. **A Survey of WebAgents taxonomy details** ([2503.23350](https://arxiv.org/abs/2503.23350)) — abstract
    only.
13. **SkillWeaver's total skill count / per-API pass rate** ([2504.07079](https://arxiv.org/abs/2504.07079))
    — "160 exploration iterations per website" is verified; the number of skills retained and their
    reliability are not reported in the text I read. Also note the paper's "54.3%" headline and the
    per-domain "40–133%" transfer range are different framings of the weak-to-strong result; I verified
    the 9.2% → 14.1% average but not the exact derivation of 54.3%.
14. **AgentOccam's "+9.8 absolute over previous SOTA"** — verified as an abstract claim, but I did not
    verify *which* prior system that 33.3%-equivalent baseline is, nor reconcile it against SteP's 33.5%.
15. **SKILL.nb, WebXSkill, CI4A, UIFormer, Read More Think More, Revisiting Observation Reduction,
    Skim, ACON** are 2026 (or late-2025) preprints/venue-accepted papers read from abstract + HTML in
    August 2026; none have the citation track record of the 2023–2025 entries. Treat their numbers as
    single-source.
16. **SeeAct's "51.1%"** is the *oracle-grounding* online figure; the deployable SeeAct-Choice number is
    **37.8%**. The abstract's phrasing ("51.1% ... when textual plans were manually grounded") is easy to
    mis-cite as an achieved system result.

---

## Bibliography (arXiv IDs, one line each)

Observation & prompt: [2307.13854](https://arxiv.org/abs/2307.13854) WebArena ·
[2306.06070](https://arxiv.org/abs/2306.06070) Mind2Web/MindAct ·
[2401.01614](https://arxiv.org/abs/2401.01614) SeeAct ·
[2401.13649](https://arxiv.org/abs/2401.13649) VisualWebArena ·
[2401.13919](https://arxiv.org/abs/2401.13919) WebVoyager ·
[2310.11441](https://arxiv.org/abs/2310.11441) Set-of-Mark ·
[2410.13825](https://arxiv.org/abs/2410.13825) AgentOccam ·
[2403.07718](https://arxiv.org/abs/2403.07718) WorkArena/BrowserGym ·
[2412.05467](https://arxiv.org/abs/2412.05467) BrowserGym Ecosystem ·
[2503.10689](https://arxiv.org/abs/2503.10689) LCoW ·
[2404.03648](https://arxiv.org/abs/2404.03648) AutoWebGLM ·
[2407.13032](https://arxiv.org/abs/2407.13032) Agent-E ·
[2510.03204](https://arxiv.org/abs/2510.03204) FocusAgent ·
[2510.00615](https://arxiv.org/abs/2510.00615) ACON ·
[2512.13438](https://arxiv.org/abs/2512.13438) UIFormer ·
[2604.01535](https://arxiv.org/abs/2604.01535) Read More Think More ·
[2605.29397](https://arxiv.org/abs/2605.29397) Revisiting Observation Reduction ·
[2601.14790](https://arxiv.org/abs/2601.14790) CI4A ·
[2507.14799](https://arxiv.org/abs/2507.14799) IPI via a11y tree ·
[2410.23555](https://arxiv.org/abs/2410.23555) From Context to Action

Memory & long horizon: [2409.07429](https://arxiv.org/abs/2409.07429) AWM ·
[2306.07863](https://arxiv.org/abs/2306.07863) Synapse ·
[2303.11366](https://arxiv.org/abs/2303.11366) Reflexion ·
[2308.10144](https://arxiv.org/abs/2308.10144) ExpeL ·
[2309.08172](https://arxiv.org/abs/2309.08172) LASER ·
[2407.01476](https://arxiv.org/abs/2407.01476) Tree Search ·
[2411.06559](https://arxiv.org/abs/2411.06559) WebDreamer ·
[2411.02337](https://arxiv.org/abs/2411.02337) WebRL ·
[2410.19609](https://arxiv.org/abs/2410.19609) OpenWebVoyager ·
[2412.09605](https://arxiv.org/abs/2412.09605) AgentTrek ·
[2410.08164](https://arxiv.org/abs/2410.08164) Agent S ·
[2510.24699](https://arxiv.org/abs/2510.24699) AgentFold ·
[2512.04307](https://arxiv.org/abs/2512.04307) Long-context WebAgents

Action space & tool calling: [2207.01206](https://arxiv.org/abs/2207.01206) WebShop ·
[2112.09332](https://arxiv.org/abs/2112.09332) WebGPT ·
[2310.03720](https://arxiv.org/abs/2310.03720) SteP ·
[2408.15978](https://arxiv.org/abs/2408.15978) WebPilot ·
[2506.03533](https://arxiv.org/abs/2506.03533) Go-Browse ·
[2308.03688](https://arxiv.org/abs/2308.03688) AgentBench ·
[2401.13178](https://arxiv.org/abs/2401.13178) AgentBoard ·
[2406.12045](https://arxiv.org/abs/2406.12045) τ-bench ·
[2408.02442](https://arxiv.org/abs/2408.02442) Let Me Speak Freely ·
[2501.10868](https://arxiv.org/abs/2501.10868) JSONSchemaBench ·
[2509.25370](https://arxiv.org/abs/2509.25370) AgentDebug ·
[2504.08942](https://arxiv.org/abs/2504.08942) AgentRewardBench ·
[2504.01382](https://arxiv.org/abs/2504.01382) Online-Mind2Web/WebJudge ·
[2605.16565](https://arxiv.org/abs/2605.16565) Skim

Workflow/skill induction: [2504.07079](https://arxiv.org/abs/2504.07079) SkillWeaver ·
[2504.06821](https://arxiv.org/abs/2504.06821) ASI ·
[2510.14308](https://arxiv.org/abs/2510.14308) ReUseIt ·
[2510.10049](https://arxiv.org/abs/2510.10049) Alloy ·
[2606.08049](https://arxiv.org/abs/2606.08049) SKILL.nb ·
[2604.13318](https://arxiv.org/abs/2604.13318) WebXSkill ·
[2410.02907](https://arxiv.org/abs/2410.02907) NNetNav ·
[2502.11357](https://arxiv.org/abs/2502.11357) Explorer ·
[2502.06776](https://arxiv.org/abs/2502.06776) InSTA ·
[2412.13194](https://arxiv.org/abs/2412.13194) PAE ·
[2507.04370](https://arxiv.org/abs/2507.04370) WebSynthesis ·
[2503.23350](https://arxiv.org/abs/2503.23350) Survey of WebAgents
