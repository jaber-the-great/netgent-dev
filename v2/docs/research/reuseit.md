# ReUseIt — Synthesizing Reusable AI Agent Workflows for Web Automation

Reference doc for the NetGent v2 team (UCSB SNL). Written 2026-08-21 from a full read of
arXiv:2510.14308v2 (HTML + PDF, including all five appendices), cross-checked against the
Magentic-UI source the system is built on.

---

## 1. Citation and summary

| | |
|---|---|
| **Title** | ReUseIt: Synthesizing Reusable AI Agent Workflows for Web Automation |
| **Authors** | Yimeng Liu (UC Santa Barbara)\*, Misha Sra (UC Santa Barbara), Jeevana Priya Inala (Microsoft Research), Chenglong Wang (Microsoft Research). \*Work done during an internship at Microsoft Research. |
| **Venue** | IUI '26 — 31st International Conference on Intelligent User Interfaces, March 23–26, 2026, Paphos, Cyprus. ACM. DOI [10.1145/3742413.3789083](https://doi.org/10.1145/3742413.3789083). ACM ISBN 979-8-4007-1984-4/2026/03. CC-BY 4.0. ACM reference says 23 pages; the arXiv PDF is 16. |
| **arXiv** | [2510.14308](https://arxiv.org/abs/2510.14308) [cs.HC]. v1 2025-10-16, **v2 2026-01-24** (the camera-ready; this doc reads v2). |
| **Code / artifact** | **None found.** No repository, project page, or artifact link appears in the paper, on the arXiv abs page, or in a GitHub search. The only code the paper points at is Microsoft's [magentic-ui](https://github.com/microsoft/magentic-ui), which ReUseIt builds on. Everything about ReUseIt itself in this doc is **paper-only** unless marked otherwise. |
| **Related work most relevant to us** | Agent Workflow Memory (AWM), Wang et al. 2024, arXiv:2409.07429 — workflow induction from past traces; Magentic-UI, Mozannar et al. 2025, arXiv:2507.22358 — the host framework; Web Bench (Skyvern) — the benchmark tasks. |

**Summary.** LLM web agents can do a task once but cannot do it *again* reliably, so users end up
re-steering the agent on every run. ReUseIt attacks this by turning an agent's own trial-and-error
into a reusable artifact. Given one task description, it first auto-generates three *variation* tasks
(different values, different tab/category, different website) and runs the original plus each variation
five times each — roughly 20 runs, deliberately harvesting both failures and successes. Failed runs are
mined by an LLM into **condition checks** ("Before/After doing <action>, ensure <condition> is met");
successful runs are mined into **fallback actions** ("Retry <action> by <UI interaction>") and into the
**workflow structure**, a high-level step list produced by Magentic-UI's plan learner. Each step plus
its checks and fallbacks is a **unit**; concatenated units are the ReUseIt Workflow. At execution time
the workflow is still a natural-language prompt: at each guarded action the system screenshots the page,
asks an LLM "is this condition met, yes/no", retries via the fallback up to three times if not, and if
that fails, escalates to the user with a structured failure explanation whose reply is parsed back into
new checks/fallbacks. Success rate across fifteen Web Bench tasks goes from 24.2% (bare prompt) to 70.1%.

---

## 2. Motivation and the failure modes it targets

The paper's own evidence, in order:

- **Third-party baselines (§1).** "the state-of-the-art web agents achieved 66.0% (Anthropic Sonnet 3.7
  CUA) and 59.8% (OpenAI CUA) accuracy to execute common web tasks", citing Skyvern's Web Bench.
  Related work adds: "only about 30% of multi-step web tasks can be completed successfully by advanced
  agents like Operator, and many other agents achieve far lower success rates on average, often below
  20% on realistic web automation benchmarks."
- **Their own reuse measurement (§1).** With Magentic-UI: repeating *the same* task (5 runs each) succeeded
  **28.0%** of the time; generalizing to *related* tasks succeeded **22.5%**. This is the number that
  motivates the paper — not "agents fail", but "agents fail to *repeat*".
- **Preliminary evaluation (§3.1).** Six tasks (flight search, housing, pet adoption, product price,
  publication search, news), 20 executions per task family, human-judged. Across tasks:
  Task-Only **27.9% ± 6.3%**, Task + Success-Traces **61.4% ± 16.1%**, Task + Magentic-UI Plan
  **68.1% ± 15.1%**. Reading: a prior trace or plan helps a lot, but "a gap remains before users can
  fully hand off web interaction tasks to agents."
- **Formative study (§3.2).** Six participants (1F/5M, mean age 26.33, SD 1.11), all daily LLM users,
  each diagnosed three failed agent runs from screen recordings plus the Magentic-UI plan. Time to *find*
  the issue: 867–973 s. Time to *write guidance*: 858–997 s — "around half of the task time" spent just
  locating the bug.

**The failure taxonomy participants found** (§3.2) is the paper's real contribution to problem framing,
and it matches NetGent's own experience of brittle replay:

1. **Filters not applied** — agent proceeds without applying all requested filters.
2. **Navigation challenges** — stuck on pop-up banners, drop-downs triggered by clicking a text field.
3. **Random clicks/scroll** — poor awareness of page layout, scroll position, visible elements.
4. **Ambiguity about intent** — "first/top/most recent" underspecified.
5. **Partial actions** — failed to finish clicking Search, or set only some required parameters.

Figure 2 gives two concrete instances: on Booking.com the agent "mistakenly used the '+' next to
children to add adults"; on Google Flights it "mistakenly selected 'round trip' from the drop-down menu
despite the user asking for 'one-way' flights." The authors' term for these is **low-level but critical
mistakes** — the user knows *what* the agent should do and still cannot tell it *how*.

**And user repair barely works.** The follow-up experiment on user-fixed Magentic-UI plans
(Task + Magentic-UI Plan User) reached **73.5%** across tasks vs. 68.1% unfixed — "improved the SR by
around 5.4%" (percentage points) for ~15 minutes of expert effort per task. Two participants questioned
whether they would invest that effort at all. This is the gap ReUseIt claims: automate the repair.

Three named gaps (§3.3): substantial time needed to understand issues; significant effort to fix low-level
but critical mistakes; users wanted their guidance to be effectively reused.

---

## 3. System design

Two design goals: **DG1** automatically mitigate low-level but critical agent issues (§4.1);
**DG2** surface issues to help users identify where and why agents fail, and fold their feedback back in (§4.2).

### 3.1 What is recorded, what the LLM does, what is deterministic

Almost nothing is deterministic. The honest accounting:

| Stage | Mechanism |
|---|---|
| Variation task generation | LLM, prompt in Appendix C.1 |
| Task execution (×20) | Magentic-UI web surfer; GPT-4o for webpage parsing and action reasoning; Playwright dispatches |
| Recording | For **failed** runs: the *agent messages* (natural-language descriptions of each action: "navigated to a webpage, clicked a button, entered a value"). For **successful** runs: the same messages **plus** a high-level plan from Magentic-UI's plan-learning module |
| Condition check synthesis | LLM, Appendix C.2 |
| Fallback action synthesis | LLM, Appendix C.3 |
| Workflow assembly | LLM, Appendix C.4 (an LLM inserts the guards into the step list) |
| Execution-time condition evaluation | LLM (GPT-4o) Q&A over a screenshot, per guarded action |
| Failure explanation + guidance tips | LLM |
| User-guidance write-back | LLM |

Only the loop control (retry ≤ 3, then escalate) and the Playwright dispatch are code. **There is no
deterministic compilation step anywhere in ReUseIt** — the "workflow" is a natural-language document
that an LLM re-reads on every run. This is the single largest difference from NetGent.

*Verified against code:* the plan learner the paper borrows is
`learn_plan_from_messages` in `src/magentic_ui/learning/learner.py`. The footnote URL points at `main`,
where the file no longer exists (checked at HEAD `d3c9d13`); it is present at tag `v0.1.0`. It sends the
conversation plus a fixed instruction to the model with `response_format=Plan`, where
`Plan = {task: str, steps: [PlanStep{title, details, agent_name}]}`. So the "workflow structure" ReUseIt
inherits is **a list of prose step titles and details** — the docstring calls it a "parameterized plan",
but there is no parameter object in the schema and no substitution machinery; parameterization is
whatever `<angle-bracket>` placeholders the LLM happens to write into `details`. Sibling function
`adapt_plan` re-prompts an LLM to rewrite a plan for a new task. The prompt also instructs
"DO NOT memorize the final answer in the plan," and asks for the fewest steps possible.

### 3.2 Multiple task executions and task variations (§4.1, Appendix C.1)

Variations "exercise different levels of agent generalizability." Exact definitions from the C.1 prompt:

- **Attribute Variation** — "Modify specific input values (e.g., dates, quantities, names, locations, or
  other form fields) that would be entered on the same webpage."
- **Category Variation** — "Modify a high-level option that requires switching a tab, toggle, or category
  within the same website (e.g., changing ''One-way'' to ''Round-trip'' on a flight search site)."
- **Website Variation** — "Change the target website to a different one while keeping the underlying task
  objective unchanged (e.g., switching from Expedia.com to Google Flights for searching flight tickets)."

The prompt's METHOD is: "Analyze the input task and identify its variable components (e.g., form values,
categories, websites). Based on this analysis, generate three distinct task variations, each corresponding
to a different type of variation, while preserving the original task's objective and intent." Output is a
fixed four-line format (Original / Attribute / Category / Website), with "The original task must be
reproduced verbatim."

Run count: **n = 5 for the original and n = 5 for each variation** — "as this can lead to at least one
successful execution for workflow synthesis based on our experiments." Roughly 20 runs per task family.

### 3.3 Execution guard synthesis (§4.1, Figure 5, Appendices C.2–C.4)

The generative move, stated twice in the paper and worth internalizing:

> "Failed executions can help expose common agent challenges that are then converted into pre- and
> post-condition checks around each action. […] Successful executions, in turn, yield fallback actions, the
> recovery strategies for steps where failures commonly occur, and workflow structure, the sequence of major
> steps to which the derived condition checks and fallback actions are attached."

**Condition checks** come from failure text. The synthesis prompt tells the LLM to look for the cues
"failed to," "didn't," "couldn't", diagnose the underlying reason (inactive buttons, missing input fields),
and emit `Condition Check: Before or after performing {Action}, ensure {Condition} is satisfied.`
§4.1 gives the schematic form as `"Before/After doing <action>, ensure <condition> is met."`

**Fallback actions** come from success text. The prompt compares the failed step against the successful
runs' messages ("I clicked, I navigated to, or I typed <UI element>") and emits
`Fallback Action: Retry {Action} by performing {Fallback Action}.`

Both prompts carry the same **Important Constraint**, which is the paper's generalization mechanism and
the piece most worth stealing:

> "do not include any concrete or literal values from the original action (e.g., specific text strings,
> numbers, dates, names, or URLs). Conditions must be written using generic, value-agnostic wording that
> captures the underlying requirement (e.g., element state, page readiness, input availability) rather than
> the specific instance that caused the failure. The purpose of each condition is to prevent the same class
> of failure across different inputs or contexts, not to guard against a single, fixed value."

**The unit.** The paper's only formal-ish definition:

> "The action details of a step and the corresponding condition checks and fallback actions form a **unit**,
> which is concatenated with the rest of the steps/units to obtain the synthesized ReUseIt Workflow."

**Assembly (C.4).** A fourth LLM call inserts checks/fallbacks into the plan's steps. The output grammar
is explicit — four legal step shapes:

```
no check:        Action: Perform {Action}
pre only:        Condition Check → Fallback Action → Action
post only:       Action → Condition Check → Fallback Action
pre and post:    Condition Check → Fallback Action → Action → Condition Check → Fallback Action
```

**Figure 5** (the synthesis pipeline) reads left→right: Task Variations → Multiple Task Executions
(step-by-step traces tagged Failed/Successful) → Execution Guard Synthesis (two lanes: *Agent Challenges*
→ *Pre-/Post-Condition Checks*; *Successful Experience* → *Fallback Actions*) → ReUseIt Workflow (Step 1..n).
Its examples are concrete: challenge "The departure city was pre-filled to Seattle, but the user asked for
LA." → check "Before entering the departure city, confirm the text field is empty and active."
Success "I clicked the '+' next to Adults two times to add three adults." → fallback "Retry clicking the
'+' next to Adults enough times to add the correct number of adults." The caption ends: "Note that specific
values are turned into generic framing in the workflow to support task generalizability."

**Figure 7** shows a real synthesized workflow (flight search, with user edits in blue). Verbatim:

```
Step 3: Enter Departure Location (<departure city>)
  Condition checks:  If the input field is not empty, you need to clear it.
  Fallback actions:  Retry clicking 'x' to clear the field.
  Details:           Type <departure city> as the departure city in the designated field and select
                     "<departure city> All Airports" from popped up drop-down menu.
  Condition checks:  Confirm you have the correct <departure city> before continue.
  Fallback actions:  Retry entering <departure city> if the field does not retain the value.
...
Step 6: Select Number of Travelers (<number of passengers>)
  Details:           Open the traveler selection menu and use + button to select <passenger count> as the
                     number of travelers. You must make sure to use the + button next to adult or children
                     as instructed by the user to add travelers.
  Condition checks:  Confirm you have the correct <number of passengers> before continue.
  Fallback actions:  If the traveler count is not retained, reopen the menu and re-select the correct
                     configuration. Make sure to continue clicking the + button until the correct number
                     of travelers has been added.
```

Note what a "parameter" actually is: an `<angle-bracket>` placeholder inside prose. Nothing types,
validates, or resolves it — the executing LLM interprets it.

**Parallel vs. sequential (Remarks, §4.1).** Their implementation runs all executions in parallel and
synthesizes from both pools at once. The sequential alternative — get one success within ~3 runs, take
the structure from it, then add guards from further runs — is noted as viable for easy tasks; parallel was
chosen "to accommodate tasks with multiple difficulty levels."

### 3.4 Execution guards at run time (§4.2, Figure 6)

Figure 6 is a three-column flowchart — Condition Check → Agent Self-Recovery → User Notification:

1. **Condition check.** At any action carrying a check, screenshot the page before/after, pair the
   screenshot with the check text, ask the LLM for a **Yes/No answer plus an explanation**. Yes → step i+1.
2. **Self-recovery.** No → "it self-recovers by re-executing the failed step **up to three times** according
   to the fallback actions", re-evaluating the condition after the retries. Recovered → step i+1.
3. **User notification.** Retries exhausted → the *challenge identification and explanation prompt* produces
   three things: (1) where the failure occurred; (2) why the agent failed; (3) what agent behaviors caused
   the failure — grounding (1) in which condition check failed, (2) in which conditions were unmet, and
   (3) in a summary of agent messages and screenshots. Then the *actionable guidance prompt* summarizes the
   fallback actions at the failed step into suggestions for the user. Figure 6's message template:
   "The agent failed to complete <action> at Step i." / "The agent didn't complete <action> because
   <condition> was not met. It attempted to self-recover by retrying …, but these retries still failed
   because …" / "You can guide the agent to complete <action> by doing …"
4. **Write-back.** The *user guidance integration prompt* "asks the LLM to parse user guidance into condition
   checks or fallback actions." Routing rule: "You need to make sure <condition> is met before/after <action>"
   → condition checks; "You can click <UI element> to perform <action>" → fallback actions. "By iteratively
   incorporating user guidance, the automatically synthesized workflow 'learns' with human input over time."

**Gap worth flagging: four of the eight prompts are not published.** Appendix C contains only C.1 variation
generation, C.2 condition-check synthesis, C.3 fallback synthesis, C.4 workflow assembly. The execution-time
*condition check prompt*, the *challenge identification and explanation prompt*, the *actionable guidance
prompt*, and the *user guidance integration prompt* are named in §4.2 and never given. With no code release,
the entire DG2 half of the system is not reproducible.

### 3.5 Implementation and cost (§4.3)

Magentic-UI as the agent framework, chosen for its live visual overlays (rectangle on target element, dot
on cursor click) so users can watch. Magentic-UI's web surfer for browsing; the same tool definitions
(*verified in code*: `agents/web_surfer/_tool_definitions.py` at v0.1.0 defines 24 tools — `visit_url`,
`web_search`, `history_back`, `refresh_page`, `page_up`, `page_down`, `scroll_up/down`, `click`,
`click_full`, `input_text`, `scroll_element_up/down`, `hover`, `keypress`, `answer_question`,
`summarize_page`, `sleep`, `stop_action`, `select_option`, `create_tab`, `switch_tab`, `close_tab`,
`upload_file`). **GPT-4o for everything** — web surfer parsing/reasoning, workflow synthesis, condition
checks, user notification. Playwright executes.

Cost (Table 2, user-study tasks): per-task execution 0:46 ± 0:20 to 2:38 ± 0:41; **workflow synthesis
~15:20 to ~52:40 wall-clock** (≈ 20 × per-task time; parallelizable). No token counts, no dollar figures,
no per-step latency overhead for the guards — anywhere in the paper.

---

## 4. Evaluation

### 4.1 Benchmark (§5)

- **Tasks:** fifteen randomly sampled from the **Skyvern Web Bench** (Archive, Asus, Cars, Bandcamp, BBC,
  Fda, Forbes, Gettyimages, Groupon, Restaurantguru, Scribd, Smithsonianmag, Sportskeeda, Ticketmaster,
  Tvguide). Each task family = original + 3 variations × 5 runs. **Exception:** Archive got 2 variations
  and Cars 1, "where the missing variations failed in all executions due to captcha errors."
- **Baselines:** Task-Only; Task + Success-Traces; Task + Magentic-UI Plan.
- **Metric:** average success rate. **Judge:** GPT-4o LLM-as-a-judge (WebVoyager protocol) over the task
  description, the final three screenshots, and the agent's answer. Audited on 45 judgments (15%) against
  one human rater: **Accuracy 0.778, Precision 0.852, Recall 0.793, F1 0.821, Cohen's κ = 0.528**.

**Headline (§5.2):**

| Condition | Success rate (mean ± std) | 95% CI across tasks |
|---|---|---|
| Task-Only | 24.2% ± 13.2% | [16.9, 31.5] |
| Task + Success-Traces | 41.4% ± 14.8% | [33.2, 49.6] |
| Task + Magentic-UI Plan | 48.6% ± 12.9% | [41.4, 55.7] |
| **Task + ReUseIt Workflow** | **70.1% ± 16.4%** | [61.0, 79.2] |

Deltas as the paper states them (percentage points, written as "%"): +21.5 over Magentic-UI Plan,
+28.7 over Success-Traces, +45.9 over Task-Only. Per-task range 45.0% (Forbes) to 90.0% (Asus, Bandcamp,
Smithsonianmag). Success-Traces helped on the original task "but less effective on the variation tasks
compared to Magentic-UI Plan" — the low-level trace overfits.

**Ablation (§5.3).** `ReUseIt Workflow w/o Fallback Actions`: when a check fails, the agent must invent its
own recovery and retry, still up to three times. Across tasks **50.1% ± 10.3%** vs **70.1% ± 16.4%** — a
20-point drop. Fallbacks win or tie on all 15 tasks (Forbes ties at 45.0%). Their explanation: "agents were
likely to repeat errors they made in their first attempts when trying to fix errors, which highlights that
both condition checks and fallback actions are necessary." This is the paper's most informative number,
because it holds the retry budget fixed and isolates *guided* vs *unguided* recovery.

### 4.2 User study (§6)

- **Participants:** nine from a large company (4F/5M, mean age 27.78, SD 2.68; S2-P1..P9). Four were in the
  formative study, on different tasks. All daily LLM users. $30 gift card.
- **Tasks:** the six formative tasks, each family = 1 original + 2 variations, run under Task-Only,
  Task + Magentic-UI Plan, and Task + ReUseIt Workflow respectively.
- **Protocol:** ~10 min onboarding; ~30 min examining two task families / six agent executions **from slide
  decks** containing the task description, screen recording, the user notification message, and the workflow;
  think-aloud analysis; optional written guidance or workflow edits; questionnaire; ~20 min semi-structured
  interview. Thematic analysis on interviews; a follow-up re-run experiment on the user-updated workflows.
- **Follow-up experiment (S2-RQ1):** Task + ReUseIt Workflow **86.5% ± 9.9%**; Task + ReUseIt Workflow User
  **87.0% ± 7.1%**. For Product Price Tracking and Publication Search *no user edited the workflow at all* —
  they were satisfied — so those cells are empty and the "User" mean is over the remaining tasks only.
- **Questionnaire (S2-RQ2/3):** aggregated over three questions per condition on a −2..+2 scale —
  ReUseIt Workflow 66.7% positive / 3.7% negative, mean **0.96**; Magentic-UI Plan 40.7% / 37.0%, mean
  **0.07**; Task-Only 14.8% / 48.1%, mean **−0.52**.
- **Guidance volume:** 9 pieces for ReUseIt vs 17 each for Magentic-UI Plan and Task-Only. Word counts
  43.41 ± 50.02 / 43.24 ± 48.18 / 56.11 ± 44.59. So the *count* of interventions halved; the *length* of each
  did not change materially between ReUseIt and Magentic-UI Plan.
- **Qualitative (§6.3):** condition checks let users anticipate *where* failure would happen without watching
  everything (S2-P3); notifications explained *why* (S2-P4, S2-P3); guidance became "confirming what I saw and
  then translating it into updating those steps" (S2-P5) rather than guessing; explicit conditions and
  fallbacks raised stated trust and willingness to reuse (S2-P2, S2-P4). Counterpoint on baselines (S2-P2):
  the agent "just said I was successful, but sometimes it's just not really successful."

### 4.3 Limitations the authors state (§7.3)

1. **Reusability vs. generalizability tradeoff.** Guards are verbose because current agents need them:
   "agents following fewer restrictions (e.g., Magentic-UI Plan) had more random actions, which downgraded
   their reliability to reasonably generalize." Verbose workflows increase the user's burden when the agent
   *does* fail. They expect this to relax as agents improve.
2. **Linear intervention only.** The user is asked for help at the failing step; there is no way to rewind to
   an earlier step whose precondition was actually the problem. They point at LangGraph and AGDebugger for
   checkpoint/rewind/fork, and at DAG workflows with parallel branches as future work.

The Discussion (§7.1) also concedes that "the LLM judge tend[s] to produce false negatives in our experiments"
and proposes cross-validating agent claims against DOM state changes, screenshots, and console logs.

---

## 5. Critical reading

**Genuinely new.**
- *Asymmetric mining of failures and successes.* Prior workflow induction (AWM) learns from what worked.
  ReUseIt's claim — failures tell you **where to put a guard**, successes tell you **what the guard's escape
  hatch is** — is a clean idea and, per the ablation, the guards without the escape hatch buy only half the gain.
- *The value-agnostic abstraction constraint.* Making "strip every literal from the derived condition" an
  explicit prompt rule is the cheapest generalization mechanism in the paper and directly targets what makes
  recorded traces brittle.
- *Guards as a dual-purpose artifact.* The same condition checks that drive self-recovery are the user's map
  of where the agent is likely to break. That is the actual HCI contribution and it is supported by the study.
- *The attribute / category / website variation taxonomy* — a small, reusable framing for what "similar task"
  means, tied to increasing levels of UI divergence.

**Repackaged.** Workflow induction from traces is AWM. Verify-after-acting is the verifier component of GUI
agents, which the paper itself cites. Bounded retry, escalate-to-human is already in Magentic-UI. Pre/post
conditions on steps are Hoare-triple-shaped, and the PbD line (WebRobot, DiLogics, MIWA) has been synthesizing
generalized web scripts for years — the difference is that ReUseIt's artifact never becomes a program.

**Threats to validity.**
- *The headline compares against the weakest baseline.* 24.2% → 70.1% is vs. a bare prompt. Vs. the strongest
  baseline it is 48.6% → 70.1%. Both are real; only the second is the interesting one.
- *Not compute-matched.* ReUseIt spends ~20 exploration runs building its artifact and gets up to 3 extra
  retries plus per-step screenshot Q&A at execution time. Task-Only, Success-Traces, and Magentic-UI Plan get
  none of that loop. So the comparison conflates a better artifact with a bigger inference budget. The
  ablation is the one arm that controls for this, and it still shows +20 points — that is the number to cite.
- *Judge quality.* κ = 0.528 is moderate; accuracy 0.778 on a 15% audit. With per-task n = 20 and true rates
  in the 40–90% band, a judge that wrong is a meaningful error bar the reported std does not include.
- *Confidence intervals are not usable.* Appendix D reports intervals like Bandcamp Task-Only
  40.0 [−214.1, 294.1] and Cars Success-Traces 30.0 [−97.1, 157.1] — normal-approximation CIs over 2–3
  per-task means. **No inferential statistics (t-tests, ANOVA, bootstrap) appear anywhere in the paper.**
- *Selection bias in the benchmark.* Variations that failed in *all* runs due to captcha were dropped
  (Archive → 2 variations, Cars → 1). The hardest cases are silently excluded from the denominator.
- *Single model, single framework.* GPT-4o and Magentic-UI throughout. Nothing shows the effect survives a
  different backbone or a stronger/weaker agent — which matters a lot given limitation (1), where the authors
  argue the guards exist *because* current agents are sloppy.
- *The user study is a vignette study.* Participants watched slide decks of recordings; nobody drove a live
  agent. Willingness and trust are self-reported at one sitting. n = 9, 4 of them repeat participants, all
  daily-LLM-using employees of one large company. The "less guidance" finding (9 vs 17 pieces) is a raw count
  over a small sample with no test.
- *No cost accounting.* Wall-clock synthesis time is reported; tokens, dollars, and the per-step latency of
  screenshot-based condition checks are not. For a system that adds one or two VLM calls to *every* guarded
  action, this is the missing column.

**What breaks at scale.**
1. **Synthesis cost is superlinear in what you want covered.** ~53 minutes and ~20 agent runs for *one* flight
   search family. A library of hundreds of workflows, re-synthesized whenever a site changes, is not viable at
   that price — and the paper's own §7.2 fix (a RAG library of retrievable units) is speculative.
2. **The artifact is prose, so it degrades silently.** Nothing type-checks a condition, verifies that a
   `<placeholder>` is bound, or detects that two guards contradict. Site drift produces a stale sentence, not
   a failed parse. There is no way to diff two versions of a workflow meaningfully.
3. **Guards accumulate monotonically.** Every failure adds a check; every user reply adds more. Nothing prunes
   them. Over time the workflow grows toward the model's context limit and toward the verbosity the authors
   themselves flag as a burden.
4. **Screenshot Q&A is the reliability floor.** Every guard is a VLM yes/no on a screenshot — the same class of
   model that made the mistake being checked. The authors observe false negatives from their judge; the same
   applies to the guards, and a false "No" burns three retries and escalates to a human for nothing.
5. **Linear escalation is wrong for real failures.** As the authors admit, the failing step is often not the
   faulty one. Without rewind, a bad step 3 gets "fixed" by piling guards onto step 7.

---

## 6. Mapping to NetGent v2

### 6.1 Concept table

| ReUseIt | NetGent v2 | Notes |
|---|---|---|
| **unit** = step details + condition checks + fallback actions | **transition** (one atomic action) + **target state** conditions (+ a guarded `Branch` arm for recovery) | NetGent splits what ReUseIt fuses. The unit is prose; the transition is a typed pydantic object with a whitelisted locator chain (`schema/actions.py`). |
| **workflow structure** (Magentic-UI plan: prose step list) | **control program** — `control_sequence` of `EdgeStep`, plus `Branch` / `Repeat` / `Call` (`schema/control.py`) | Theirs is a numbered list an LLM re-reads; ours is statically enumerable with a bounded edge count before running. |
| **pre-condition check** | source state's **triggers** must hold before the edge fires (`url_matches`, `selector_visible`, `selector_hidden`, `title_contains`) | Structurally identical intent. Theirs: a VLM answers yes/no on a screenshot. Ours: a predicate evaluated by code. |
| **post-condition check** | target state's **triggers** | Same. NetGent already *requires* this shape; ReUseIt has to synthesize it. |
| **fallback action** ("Retry X by doing Y") | a `Branch` arm keyed on the observed state, or the (unspecified) healing/repair ladder | **Not implemented.** The repair spec is still an open item (`OVERVIEW.md` §7). This is the mapping with the most to learn from. |
| **task variations** (attribute / category / website) | `-p name=value` sample values → `${name}` params; `Param` / `ParamSource` / `guard` in `schema/control.py` | `netgent generate -p` exists in `cli/generate.py`; `--runs N` and `--variation` are described in `CLAUDE.md` but **are not implemented** on this branch. |
| ε-transitions / pop-ups | ReUseIt has **no notion of them** — pop-ups appear only as a failure symptom that becomes a condition check | NetGent models each pop-up as a state reached by a `noop` ε-transition. Strictly stronger. |
| **user notification** (where/why/what + guidance tips) | `ValidationReport` → `ReplayResult{success, edges_ok, failed_edge, error}` from `validation_agent/validate.py` | Ours localizes to a transition id deterministically; theirs explains in prose but needs an LLM to do it. |
| **user guidance integration** (LLM parses feedback into checks or fallbacks) | nothing yet | NetGent has no feedback write-back path at all. |
| Magentic-UI web surfer: **24 tools** (verified in code) | **11 atomic actions** — goto, click, fill, press, select, scroll, upload_file, go_back, wait, hover, noop | Ours is smaller and closed by design; theirs includes non-atomic ops (`web_search`, `answer_question`, `summarize_page`) that cannot be replayed deterministically. |
| workflow-unit library + RAG retrieval (§7.2, future work) | `Call` sub-workflow node (schema-only; executor does not resolve a library yet) | Same idea, both unbuilt. |

### 6.2 Where ReUseIt runs an LLM at execution time and NetGent does not

ReUseIt is **LLM-at-replay in at least four places**, every run:

1. The web surfer's action reasoning — GPT-4o decides each click/type from the page, *every step, every run*.
   The workflow is context, not control.
2. Every condition check — a screenshot + text → VLM yes/no + explanation, before and/or after each guarded action.
3. Every escalation — challenge identification/explanation and actionable guidance.
4. Every write-back — parsing user feedback into checks or fallbacks.

NetGent's contract is the inverse: the LLM runs **only** at compile time (`agent/`, LangChain/LangGraph imported
lazily); `executor/` and `browser/` may not import a model at all, enforced by
`tests/unit/test_import_boundaries.py`. `netgent run workflow.yaml` and `validate_workflow()` do zero LLM calls.
Concretely: ReUseIt's flight-search workflow costs a GPT-4o session *per replay*; NetGent's costs one at compile
and $0 thereafter. That is the axis on which NetGent should be measured against this paper — and it is the axis
ReUseIt never reports, since it publishes no token or dollar figures.

The corollary is that ReUseIt's numbers are **not** a ceiling for NetGent, nor directly comparable: 70.1% is the
success rate of an *LLM agent with a good prompt*, not of a deterministic replay. A fair head-to-head would need
NetGent's replay success on the same fifteen Web Bench tasks, plus cost per run for both.

### 6.3 Seven ideas worth adopting

1. **Compile from failed runs, not just successful ones.** *Why:* the paper's central insight — a step that
   failed in exploration is exactly where a state condition is load-bearing. Today `compile_trajectory` filters
   to `s.action is not None and s.error is None` and throws the failures away. *Cost:* the trajectory record must
   keep failed steps with their errors (it already has `error`); the compiler needs a failure→condition rule;
   a multi-run merge stage that doesn't exist yet.
2. **Never emit an unconditioned state where exploration failed.** *Why:* `compile_trajectory` currently gives
   same-page steps `conditions=[]`, so a fill that silently no-ops replays "successfully". ReUseIt's post-condition
   discipline ("After entering a user-specified value in a text field, the field should display exactly that value")
   maps directly onto a `selector_visible` / value-check trigger. *Cost:* small compiler change plus a new
   value-equality trigger type; risk of over-tight triggers that break on cosmetic drift.
3. **Adopt the value-agnostic constraint verbatim for trigger synthesis.** *Why:* `_base_url` + `re.escape(base)`
   already bakes literals into `url_matches` patterns — the exact brittleness ReUseIt's Important Constraint
   forbids. Their prompt text is directly reusable. *Cost:* a compile-time rule, plus a real risk in the other
   direction — a trigger too generic matches the wrong state, which for an NFA is worse than a miss.
4. **Implement `--runs N` / `--variation` with their three-way taxonomy.** *Why:* it gives `--variation` a
   principled meaning (attribute = same page different values; category = tab/toggle switch; website = layout
   change) and it is precisely how you'd discover which parts of a NetGent workflow must become `Param`s vs. which
   must become `Branch` arms. The C.1 prompt is reusable as-is. *Cost:* N× exploration wall-clock (theirs:
   15–53 min per family) and N× compile-time tokens; needs the merge stage from (1).
5. **Guided recovery, not blind retry — as a typed `Branch`, not prose.** *Why:* the ablation (50.1% → 70.1%)
   is the cleanest evidence in the paper, and its mechanism ("agents were likely to repeat errors they made in
   their first attempts") is exactly why a naive re-fire of a failed edge is worthless. *Cost:* the fallback must
   be a concrete atomic action or an alternate edge — never a sentence — or it violates the zero-LLM-at-replay
   rule. This is a design constraint on the still-unwritten repair spec, not a free adoption.
6. **Give `ValidationReport` the where/why/what-behaviors structure.** *Why:* participants rated the structured
   notification as the single most useful artifact for understanding failures, and NetGent already has the *where*
   for free (`failed_edge`) — better than ReUseIt, which must infer it. Add: which trigger failed, what the page
   actually showed, which exploration run last saw this edge succeed. *Cost:* extend `ReplayResult`; the *why*
   narrative can be templated with zero LLM, or generated by an LLM at compile time only.
7. **Typed human feedback write-back.** *Why:* their §4.2 routing rule ("You need to make sure <condition>…"
   → a check; "You can click <UI element>…" → a fallback) is the right shape, and NetGent has no feedback path.
   *Cost:* a compile-time-only LLM parse that must emit a validated `Trigger` or `Transition` — schema validation
   is what keeps it from becoming prose in the artifact, and preserves rule 1 (workflows are generated, never
   hand-written). Also inherit their unfixed problem: guards accumulate and nothing prunes them.

**One thing to deliberately *not* adopt:** the prose artifact. Everything ReUseIt gets from
`<placeholder>`-in-a-sentence, NetGent already gets from `Param` + `ParamSource` + `guard` with a regex the
resolved value must match. Their §7.3 limitation ("verbose workflows … increase the user's burden") is a direct
consequence of a representation that cannot be checked; it is not a problem NetGent needs to inherit.

**One thing to steal from their evaluation:** report a cost column. ReUseIt doesn't, and it is the number where
NetGent wins by construction.

---

## 7. Quotes worth keeping

1. *"increasing the success rates from 24.2% to 70.1% across fifteen tasks."* — Abstract
2. *"In our benchmark evaluation of six common tasks, the average success rate of repeating the same tasks (five times each task) was 28.0% and generalization to related tasks (five times each task) was 22.5%, using the Magentic-UI agent framework."* — §1
3. *"Failed executions can help expose common agent challenges that are then converted into pre- and post-condition checks around each action."* — §4.1
4. *"Successful executions, in turn, yield fallback actions, the recovery strategies for steps where failures commonly occur, and workflow structure, the sequence of major steps to which the derived condition checks and fallback actions are attached."* — §4.1
5. *"The action details of a step and the corresponding condition checks and fallback actions form a unit, which is concatenated with the rest of the steps/units to obtain the synthesized ReUseIt Workflow."* — §4.1
6. *"the LLM extracts the error pattern and convert it into a pre- or post-condition check for this action in the form of 'Before/After doing <action>, ensure <condition> is met.'"* — §4.1
7. *"We set the number of task executions as five for both the original and variation tasks, as this can lead to at least one successful execution for workflow synthesis based on our experiments."* — §4.1
8. *"do not include any concrete or literal values from the original action (e.g., specific text strings, numbers, dates, names, or URLs). Conditions must be written using generic, value-agnostic wording that captures the underlying requirement (e.g., element state, page readiness, input availability) rather than the specific instance that caused the failure."* — Appendix C.2 (near-identical text in C.3)
9. *"If the condition is met, the agent moves on to the next action; if not, it self-recovers by re-executing the failed step up to three times according to the fallback actions."* — §4.2
10. *"This prompt asks the LLM to parse user guidance into condition checks or fallback actions."* — §4.2
11. *"agents were likely to repeat errors they made in their first attempts when trying to fix errors, which highlights that both condition checks and fallback actions are necessary for improving agents' reliability."* — §5.3
12. *"If you know where the model's gonna fail from the condition checks [in ReUseIt Workflow], you don't have to watch the agent very carefully and examine everything."* — S2-P3, §6.3
13. *"our experiments show that agents following fewer restrictions (e.g., Magentic-UI Plan) had more random actions, which downgraded their reliability to reasonably generalize."* — §7.3
14. *"each unit in the synthesized workflow can be treated as a reusable building block … maintain a library of workflow units, each consisting of an action, its condition checks, and fallback actions, and create new workflows by retrieving the relevant units and assembling them."* — §7.2

---

### Provenance of claims in this doc

- **Paper-only** (no code, no artifact to check against): everything in §3 about ReUseIt itself, all numbers in
  §4, all prompt text. Four of the eight prompts named in §4.2 are not published at all.
- **Verified against code** (microsoft/magentic-ui @ `v0.1.0`, checked 2026-08-21): the plan-learning module
  `learn_plan_from_messages` and the `Plan`/`PlanStep` schema (`src/magentic_ui/learning/learner.py`,
  `src/magentic_ui/types.py`); the web surfer's 24 tool definitions
  (`src/magentic_ui/agents/web_surfer/_tool_definitions.py`). The paper's footnote URLs point at `main`, where
  `learning/learner.py` no longer exists.
- **Verified against this repo** (`v2/src/netgent/`, branch `eugene/v2-scaffold`): the action/trigger/control
  schemas, `compile_trajectory`'s filtering of failed steps and empty-conditions behaviour, `validate_workflow`'s
  `ReplayResult` fields, and the absence of `--runs` / `--variation` in `cli/generate.py`.
