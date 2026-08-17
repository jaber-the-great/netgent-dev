# Related Work & Recommendations (Web Research)

Researched 2026-08-05 (Opus subagent, ~180 verified sources). Companion to [github-recon.md](github-recon.md).

## Executive summary — the four things that matter

1. **The architecture has been independently converged on 4× in 18 months** (WebXSkill, PreAct, ReUseIt, WALT) plus Skyvern in industry. Differentiate on *state identity* and *NFA structure* — none of them formalize either.
2. **State identity is the hardest open problem; 20 years of SE research says avoid global thresholds.** ICSE 2020 (Yandrapally/Stocco/Mesbah): best universal-threshold F1 ≈ 0.60; app-specific thresholds +34%; "universal thresholds may not be feasible." Never use SimHash on within-app page content (F1 0.17, worse than random).
3. **The repair loop = Ringer (OOPSLA 2016) + VON Similo LLM (STVR 2024)**: persist a rich node fingerprint, rank ALL candidates by weighted similarity, LLM only disambiguates a shortlist. Never send whole DOMs to the model.
4. **Key negative result: 81.7% of repaired web tests re-break within six months** (ASE 2025). Repair must prefer *robustness-raising* rewrites (CSS chain → role+name), not match restoration.

## NetGent V1 baseline

arXiv:2509.00625, NeurIPS 2025 MLForSys. V1 has no Discovery algorithm, no formal state identity, no closed-loop repair, no healing evaluation, no parameterization story — exactly V2's contribution surface. Caution: the abstract already claims "adapts quickly when interfaces change"; V2 must quantify it.

## Must-cite prior art

### LLM agents that compile/cache workflows
- **AWM — Agent Workflow Memory** (Wang/Mao/Fried/Neubig, ICML 2025) https://arxiv.org/abs/2409.07429 — textual workflows as in-context guidance; WebArena +51% rel, steps 7.9→5.9. Its limitations section ("agents struggle diverging from workflow guidelines when environments differ… future work: real-time state access") **is NetGent V2's motivation, written by the anchor paper**.
- **ASI — Inducing Programmatic Skills** (same authors, COLM 2025) https://arxiv.org/abs/2504.06821 — **programs beat prose head-to-head (+11.3% over AWM)**, attributed to execution-verified induction. The single strongest citation.
- **SkillWeaver** (OSU, 2025) https://arxiv.org/abs/2504.07079 — URL-only exploration → practiced, verified, parameterized Python APIs; strong-agent-synthesizes-for-weak-agent transfer (+54.3%) = the economic argument for compilation. Closest neighbor to the Discovery phase.
- **WebXSkill** (UNC/Microsoft, Apr 2026) https://arxiv.org/abs/2604.13318 — names the "grounding gap"; hybrid executable skill = parameterized program + step-level NL guidance, grounded/guided dual mode. Essentially the YAML NFA in prose — read before writing related work.
- **PreAct** (2026, ⚠️ unrefereed preprint, single author) https://arxiv.org/abs/2606.17929 · code: https://github.com/19PINE-AI/PreAct — **verified against the full PDF + repo (2026-08-06)**. Compiles successful CUA runs into directly-executed state-machine programs (states = exact XPath/resource-id verification predicates; transitions = actions; branching; `{{param}}`-style parameter lifting; LLM or embedding program selector — choice doesn't matter). 8.5–13× warm-run speedup; verify-before-store gate (re-run from clean state + independent evaluator) worth 1.75–2.6 tasks/benchmark. **Closest published neighbor — differentiate on**: (1) *no healing* — on any predicate/action failure the FULL agent takes over (repo confirms: "programs are either replayed unchanged or abandoned"); the "in-place patching/splicing" its representation *enables* is not implemented as a repair path; (2) *program-granular refinement only* — corpus mutates by UPSERT (full re-trace → recompile → verified wholesale replacement), no edge-level write-back; (3) *brittle exact element identity* — single concrete selectors, no fingerprints/ladders/ambiguity rule; its own audit finds the compiler lossy (~28% Android programs miss navigate_back; 100% of audited WebArena programs misuse inspect_screenshot); (4) *its state-machine-vs-flat-script advantage is not statistically significant* (L1: Δ=+0.67, p=0.125, n=5) — NetGent's healing-locality argument is a stronger justification for the state machine than PreAct's own; (5) *corpus doesn't transfer* — OOD it lands ~11 pts BELOW cold baseline; (6) *verify gate assumes resettable/idempotent environments* (L6) — benchmark-only as validated; (7) tiny scale: 15+6+12 tasks, 58 stored programs; no drift/longitudinal evaluation at all — the site changing is NetGent's entire experiment and PreAct never tests it.
- **ReUseIt** (UCSB + MSR, IUI 2026!) https://arxiv.org/abs/2510.14308 — synthesizes reusable workflows with **execution guards**; 24.2%→70.1%. Peer-reviewed match for the healing half — and it's UCSB-local.
- **WALT** (Salesforce, 2025) https://arxiv.org/abs/2510.01524 — reverse-engineers site functionality into deterministic parameterized tools.
- Also cite: **SteP** (COLM 2024, stack of policies = NFA sub-machine calls) https://arxiv.org/abs/2310.03720 · **SeeAct** (ICML 2024 — the 26% vs 51.1%-oracle grounding gap is the quantitative argument that grounding is the bottleneck; set-of-mark ineffective for web) https://arxiv.org/abs/2401.01614 · **Voyager** (TMLR 2024) · **Synapse** (ICLR 2024, LLM state abstraction) · **SSO** (skill pruning = YAML garbage collection) https://arxiv.org/abs/2402.03244 · **AutoGuide** (NeurIPS 2024 — IF-context-THEN-guidance = guards on transitions) https://arxiv.org/abs/2403.08978 · **Agent-Pro** (accept a rewrite only if verified better on held-out trajectories) · **API-Based Web Agents** (hybrid beats browsing +24 abs) https://arxiv.org/abs/2410.16464 · **Learn-by-interact** (backward construction: label the workflow by what the trace *did*) https://arxiv.org/abs/2501.10893.

### PBD lineage (reviewers WILL ask; cite proactively — the idea is ~20 years old)
- **Ringer** (OOPSLA 2016) https://schasins.com/assets/papers/ringer.pdf — **the healing design, published 2016**: save the entire node (hundreds of attributes), at replay score EVERY candidate, take argmax ("requires only that some unknown subset match"). Also **trigger inference** for waits from 2–3 successful traces (align server responses by hostname/path/type) — extra-relevant since NetGent records network traces anyway.
- **WebRobot** (PLDI 2022) https://arxiv.org/abs/2203.09993 — PBD synthesis of loopy web-RPA programs; speculate-and-validate against a *recorded DOM trace* (avoids destructive replay); its DSL (selector loops, value loops, pagination `while true do {P; Click(n)}`) is a peer-reviewed IR template.
- **Rousillon/Helena** (UIST 2018; helena-lang.org) — strongest prior art on the DSL-design side. **Skip Blocks** (OOPSLA 2017) — identity annotations enable skip-completed-work recovery, 7.9× speedup.
- **Koala** (CHI 2007) / **CoScripter** (CHI 2008) — sloppy programming + personal-variable store = parameterized workflows in 2007. **Sikuli** (UIST 2009) — screenshot-patch identity. **SemanticOn** (UIST 2022) — semantic conditions = pre-LLM guards. **Workflow-Guided Exploration** (ICLR 2018) — formal ancestor of AWM/ASI.

### Self-healing / selector repair
- **Similo → Similo++ (2025)** https://arxiv.org/html/2505.16424 — multi-property weighted matching; **use the GA-optimized weights**: Name 2.85, Visible Text 2.80 (Lev), Type 2.75, Neighbor Text 1.45, Location 1.20, Aria-Label 0.90 (Jaccard), Tag 0.80, ID 0.50. Similo++ 99.4% exact-match on 10,376 pairs. Benchmark lesson: evaluate on ~4-month version gaps, not multi-year.
- **VON Similo LLM** (STVR 2024) https://arxiv.org/abs/2310.02046 — **the strongest citation for deterministic-first, LLM-only-on-breakage**: Similo ranks, GPT-4 picks from shortlist; failures −44%. VON insight: normalize visually-overlapping DOM nodes into one visual group before scoring.
- **Explanation-consistency checking** (2023) https://arxiv.org/abs/2312.05778 — LLM must name the attributes that matched; a validator checks the claim; EditDistance+ChatGPT 88%. Also: simplest matcher + LLM beat sophisticated matchers + LLM.
- **VISTA** (FSE 2018) — visual template matching **plus local crawling** for workflow-level (not just locator) repair — the capability NetGent's NFA is uniquely positioned to have. **WATER** (2011) — differential old/new analysis; the stored NFA gives the differential for free. **UITestFix** (ASE 2023) — repair the whole state's guards jointly; resolved guards anchor the unresolved. **ERRATUM** (2021) — prune search space before matching. **Robula+** (2016) / **SIDEREAL** (2021) — robust XPath generation; SIDEREAL learns per-attribute fragility *per app*. **Multi-locator voting** (ICST 2015) — locator disagreement as a wrong-heal detector (catches false greens). **WEFix** (WWW 2024) — many "broken guards" are timing; wait synthesis fixed 120/122 flaky tests.
- **ReproBreak** (2026) https://github.com/rub-sq/ReproBreak — **the repair-loop benchmark**: 449 Dockerized reproducible locator breaks in Cypress/Playwright projects.
- Industrial: **Healenium** (score-cap 0.6, recovery-tries, selector-imitator re-serialization, review UI) · **Testim** (proactive drift detection on match-score trends) · **mabl** (heal locators, never expected values) · **Katalon 11** (LLM repair input bundle: page source + a11y tree + full screenshot + element screenshot — copy verbatim) · **testRigor** (store NL intent alongside every selector) · **Meticulous** (response mocking isolates DOM drift from data drift).

### State identity / exploration (the deepest literature)
- **ICSE 2020 near-duplicate study** https://people.ece.ubc.ca/amesbah/resources/papers/icse20.pdf — THE paper. Taxonomy: clone / Nd1 cosmetic / **Nd2 dynamic-data (same template, different data — NetGent's case)** / Nd3 duplication / distinct. SimHash catastrophically bad within-app; thresholds don't transfer; **Nd3 near-duplicates are generated by the crawler's own actions** (add-a-row loops) and model F1 decays 0.95→0.45 during a crawl.
- **FragGen** (TSE 2023) https://arxiv.org/abs/2110.14043 — fragment-based classification: "is this extra element a duplicate of something already on the page?" kills Nd3. **Transition identity = (fragment identity, XPath relative to the fragment)**.
- **APE** (ICSE 2019) https://helloqirun.github.io/papers/icse19_tianxiao.pdf — **the answer to "how do I pick state granularity"**: CEGAR-style bidirectional refinement — refine a state when one model action covers >α=3 GUI actions or transitions are non-deterministic; coarsen when a split exceeds β=8. Non-determinism = the spurious counterexample.
- **Enemy of the State** (USENIX Sec 2012) — page identity = **link/form vectors only, content-blind**; state-change detection = same request, different response; state merging via graph coloring on *negative* evidence.
- **DroidBot dual-key** — `state_str` (exact, text truncated at 50 chars) + `structure_str` (content-free layout skeleton): "have I seen this screen" vs "this KIND of screen." The most-copied dedup idiom.
- **Baek & Bae GUICC ladder** (ASE 2016) — package → route → layout → **executable-widget/affordance set** → text content; no single level works. **SwiftHand** (OOPSLA 2013) — state = set of enabled inputs, period. **EFG/EIG** (Memon 2007) — structural-event removal by transitive closure **is ε-elimination — the 20-year-old formalism for popups-as-ε**. **Stoat** — text changes don't create states; lists → empty/non-empty. **AutoDroid** (MobiCom 2024) — hash for identity, LLM summary for equivalence. **Crawljax** oracle-comparator pipeline + the broken hash/equals lesson (fuzzy identity can't hash; layer exact-key → prefilter → judge). **MinHash over element signatures** (not SimHash over text) for LSH prefiltering https://arxiv.org/abs/2001.01128.
- **WebCanvas** https://arxiv.org/abs/2406.12373 — **key nodes** (indispensable waypoints) with {URL, path, value} × {exact, include, semantic} matching = the spec for state guards, and the right replay metric.
- 2026 head-to-head https://arxiv.org/abs/2606.16650 — no single abstraction wins; model-based approaches want strict abstractions; LLM context should be functionality-rich, not per-step state dumps.

### Who actually caches/replays (industry gap analysis)
- **Skyvern**: code cache (Jinja-keyed generated Python, per-block, progressive branch coverage, `script_reviewer_v3` LLM-rewrites the artifact with validation) + action cache (element content-hash rebinding; ambiguity = miss; **`intention` NL holes refilled by one cheap batched call** = parameterization trick).
- **Stagehand**: observe/act memoization; **cache key from variable KEYS not values** (secrets never reach the model); self-heal rewrites the entry; 48h validity.
- **browser-use**: best element rebinding (5-level cascade), replay of recorded pacing; no artifact rewrite. **workflow-use**: right shape (semantic target_text, selectorStrategies, compile-time LLM decides which steps stay agentic, lookahead pre-wait) but **self-heal is commented out**.
- **LaVague** (dead, Jan 2025): one-way compilation, no healing. **Agent-E**: no caching, deliberately; their paper's future-work paragraph describes NetGent V2 unbuilt — **quote it in the intro**. **Chrome Recorder**: 5 redundant selectors per step but can never invent a sixth. **Steward** (arXiv:2409.15441): URL-keyed semantic action cache, write-time LLM validation, 49% hit rate, −53.6% cost.
- **The gap**: redundancy and regeneration are disjoint across the field; almost nobody repairs the artifact. **V2's defensible claim: redundancy AND regeneration AND artifact repair, on a formal state machine with principled state identity. No one has all four.**

## Prioritized recommendations

### P0 — cheap, architecture-changing
- **R1. `locator.ariaSnapshot()` as the state fingerprint** (https://playwright.dev/docs/aria-snapshots): already YAML, semantic, **subset-matching by default** (right guard semantics), regex names for dynamic content, and every node doubles as a `getByRole` repair candidate. Collapses state identity + oracle + repair-candidate-generation into one artifact. Nobody else has noticed this.
- **R2. DroidBot dual-key dedup**: structure_key (tag/role/id/aria-label skeleton, text stripped, repeated siblings collapsed) + exact_key. Threshold-free kill of Nd1/Nd2.
- **R3. State identity is intensional — a guard conjunction** (route + affordance list + requires/forbids + per-state compare_level), not a DOM snapshot. For an NFA, "state = available affordances" is semantically correct (Doupé, SwiftHand).
- **R4. Every guard = intent (NL) + fingerprint (Similo++ properties) + ranked locators (Testing Library priority) + anchors + screenshot crop + `healable:` flag** — structured fields so repair mutates ONE field.
- **R5. Stagehand's variable-keys-not-values** cache key + Skyvern's intention-typed holes.
- **R6. Soft assertions + state/transition IDs in failure messages** → one run yields the complete broken-guard list.

### P1 — Discovery
- **R7.** Normalize → dedup → classify; **let the LLM write the per-state normalizer** (mask rules) after exploration.
- **R8.** Give the LLM the Cl/Nd1/Nd2/Nd3/Di **vocabulary**, not a similarity score; hash first, LLM only on miss.
- **R9.** Design against Nd3 explicitly: "list with n items" ≡ "list with n+1 items"; FragGen's same-page-duplicate check.
- **R10.** Transition identity = fragment-relative, not absolute; equivalent widgets explored once.
- **R11.** **Offline consolidation pass** (the structural advantage over online crawlers): APE refinement (α=3, β=8) + Doupé negative-evidence coloring + **ASI validate-by-re-execution** (every guard fires on its state and nowhere else).
- **R12.** Formalize popups-as-ε via EIG structural-event classification — free credibility.
- **R13.** LLM decides at compile time which steps stay agentic (calendars, changing option lists). 90% deterministic + 10% honest agent steps beats 100% deterministic that breaks weekly.
- **R14.** AutoScraper's step-back loop for guard authoring; validate each guard against every other captured page.
- **R15.** Backward construction: label workflows by what the trace demonstrably did.

### P2 — Repair
- **R16. Four-tier ladder**: T0 try other ranked locators (free) → T1 Similo++ weighted scoring over pruned candidates, whole-state jointly (UITestFix) → T2 LLM picks from top-5..10 with Katalon input bundle + explanation-consistency verification → **T3 bounded local re-exploration to SPLICE A NEW STATE (VISTA) — the headline repair contribution only an NFA can make.**
- **R17.** Gate every heal: min_confidence + max_candidates in YAML; heal selectors never expected values; log old/new/confidence/screenshot; fail the run on heal-rate spikes; human review to commit; re-serialize healed nodes to readable selectors.
- **R18.** **Multi-locator disagreement as a wrong-heal alarm** even when the primary resolves — catches false greens.
- **R19.** Prefer robustness-raising repairs (score selectors; a repair must not lower the score) — the 81.7% re-break stat demands it.
- **R20.** Commit a repair only after replay verifies no regression.
- **R21.** Predictive: per-attribute stability per app (SIDEREAL) + match-score trend monitoring (Testim) → re-explore before red.
- **R22. Failure taxonomy → repair dispatch built into the runner**: 0 matches → ladder; >1 → add scope/filter never nth; found-but-not-actionable → *prior transition* wrong; detached → re-query in retry; passes-at-longer-timeout → timing only (WEFix); aria-subset mismatch → genuine state change → T3.
- **R23.** **Ringer trigger inference for waits** — NetGent already records network traces; sleeps corrupt the measurement. Plus workflow-use's lookahead pre-wait. Emit explicit guards for Playwright's no-check actions (press/focus/dispatchEvent/setInputFiles/blur).
- **R24.** Meticulous-style response mocking to isolate DOM drift from data drift — doubly free since traces are the product.

### P3 — Evaluation
- **R25.** Primary: **WorkArena/++** (task families × seeds = native parameterized replay) + **REAL/AgiSDK** (deterministic, URL-configurable) + **WebArena** (comparability with AWM/ASI/SkillWeaver). Integrate via **BrowserGym** — don't build a harness.
- **R26.** WebCanvas key-node scoring as the replay metric ("still works" vs "drifted").
- **R27.** Healing claim: **OpenApps** (>50-pt swings across cosmetic variants = fragility baseline) + **StressWeb** (controlled perturbations); repair loop on **ReproBreak**; ~4-month version gaps.
- **R28.** EvoClawBench's PreSkill/PostSkill protocol (explore run vs replay run vs direct).
- **R29.** Report: LLM calls/run, cost/run, steps, cache-hit rate, heal rate, **heal precision** (nobody reports it — weakest spot in the field).
- **R30.** **The metric nobody else can report: traffic-trace fidelity/stability across replays.** Lead with it.
- No benchmark exists for parameterized workflow reuse on the web — **shipping one is a contribution opportunity.**

### Avoid
Global-threshold state similarity · SimHash within-app · hashable fuzzy identity · re-deriving AWM/Voyager/ASI induction · building a bench harness · emitting nth/force/sleeps/absolute XPaths/class chains/spatial `:near()` · set-of-mark for repair grounding · "the LLM will figure out if it's a new state" (Humanoid: better action prior ≠ better abstraction) · Mind2Web/WebLINX for the core claim (offline traces) · silent healing.

### Read in full before writing the V2 design
Papers: **APE** (ICSE 2019) · **ND study** (ICSE 2020) · **Ringer** (OOPSLA 2016).
Repos: **workflow-use** · **skyvern/webeye/actions/caching.py** · **APE**.
