# Generalization papers — turning a few demonstrations into a parameterized, replayable procedure

*Research doc. Every paper below was fetched this session (PDF text via `pdftotext`, arXiv abs/HTML,
or ACL Anthology); numbers are quoted from the fetched text, not from memory. Sibling doc:
`generator-agent.md` (open-source repos). Companion: `trajectory-memory.md` (which papers store
*what*); this doc asks how one turns demonstrations into a *generalized program*.*

## Summary (10 lines)

1. The only papers with an **algorithm** for "which literal generalizes" are the classic PBD line:
   SMARTedit's version-space algebra learns from **1–2 demonstrations in 18 of 30 scenarios** because
   its hypothesis space is small and typed — exactly NetGent's position.
2. **Ringer already built NetGent's cross-run merge, in 2016**: it infers wait-conditions by keeping
   only what held in *every* successful trace, and two or three traces suffice.
3. **Nobody aligns trajectories step-by-step with an LLM either** — Skill-DisCo (2026) comes closest,
   scoring a candidate skill by the fraction of traces it matches, and gets **5 skills where ASI got 110**.
4. The single strongest 2026 result: **linear parameterized scripts are the wrong artifact.**
   NSI's branching, predicate-guarded programs beat ASI's linear scripts 98.0 vs 70.6 (ALFWorld) and
   44.5 vs 7.5 (WebShop) — and NSI induces branches **from one linear trace**.
5. Parameter detection has one rule that works and is cheap: **match the words of the task text
   against the values the demonstration typed** (SUGILITE, AWM, WebXSkill). NetGent already does this.
6. The rule's limit is measured: in AndroidHowTo, instructions carry **190K operation spans, 172K
   object spans, and only 321 argument spans** — most steps have no literal in the text to match.
7. **One demonstration is massively under-determined**: WebRobot synthesized multiple consistent
   programs for **59 of 76** benchmarks (max 101). Rousillon states the same and punts to an editor.
8. For locators, the evidence favours **many weak features, unweighted**: Ringer's uniform-weight
   similarity beat its own SVM- and regression-learned weights, and beat iMacros 81.4% vs 60.2%.
9. **"It ran without an exception" is not verification** — SkillWeaver reports the LLM silencing
   exceptions to pass its own check. Replay on a *held-out instance* is the only test that held up.
10. A budget-matched vanilla actor beats AWM, ASI and ReasoningBank on all three models tested
    (44.78 vs 39.34/41.02/39.33 avg WebArena SR) — but that critique prices *online* induction, which
    is not NetGent's setting. Say so explicitly rather than ignoring it.

---

## 0. Scope, method, and the question

The question: **given one or a few typed trajectories of the same task, what algorithm produces a
generalized, parameterized, replayable procedure — and how do you know the generalization is right?**

Four sub-questions run through every section:

| | The decision | NetGent's current answer (`generator/compiler.py`) |
|---|---|---|
| **P** | which literals become parameters | caller declares `-p name=sample`; case-insensitive literal sweep over `text`/`value`/`url` and `url_matches` patterns, **never** inside locators (`_bind_params`) |
| **C** | which steps are conditional | none; every successful step becomes an unconditional `Transition` |
| **O** | positional vs identity selection | inherited from the explorer's `Locator` chain; `get_by_role(role, name=…)` is identity, `nth()` is positional |
| **V** | how the generalization is verified | verifier LLM judge, advisory only; no replay-based acceptance test |

Sources fetched: 27 papers as full PDF text, plus arXiv/ACL abstract pages. `pdftotext -layout` for
single-column, plain `pdftotext` (reading order) for two-column. Where a claim comes from an abstract
page rather than the body, it is marked. §8 lists what I could not retrieve.

---

# 1. Programming by demonstration / example — the classic line

## 1.1 SMARTedit and version space algebra — the formal treatment of "which literal generalizes"

**Lau, Wolfman, Domingos & Weld, *Programming by demonstration using version space algebra*,
Machine Learning 53:111–156 (2003).** [PDF](https://homes.cs.washington.edu/~pedrod/papers/mlj02.pdf)

**The formalism.** A hypothesis is a function; a training example `(i, o)` is *consistent* with `h`
iff `h(i) = o`; the version space `VS_{H,D}` is the subset of `H` consistent with the **sequence** `D`.
"When a new example is observed, the version space must be updated to ensure that it remains
consistent with the new example by removing the hypotheses that are inconsistent with it."

The **algebra** composes small version spaces into large ones:

| Operator | Definition | Cost |
|---|---|---|
| **Union** | `VS_{H1,D} ∪ VS_{H2,D} = VS_{H1∪H2,D}`; components maintained separately, so unions need not be boundary-set representable | Theorem 1: time/space = sum of components **+ O(1)** |
| **Join** | ordered pairs `⟨h1,h2⟩` with `h1∈VS1, h2∈VS2` satisfying a joint consistency predicate `C` | cross product in general |
| **Independent join** | when `C(h1,D1) ∧ C(h2,D2) ⇒ C(⟨h1,h2⟩,D)` — consistency factorizes | components only |
| **Transform** | re-type a generic space into a domain space (`ConstInt f(x)=C` → absolute row) | 1-to-1, no renormalization |

**The hypothesis space for text editing** is a tree of these:
`Action = ∪{Move, Select, Insert, Delete, clipboard}`; `Move = transform(Location)`;
`Location = ∪{RowCol, FindPrefix, FindSuffix, …}`; `RowCol = independent-join(Row, Column)`;
`Row = ∪{AbsRow = transform(ConstInt: f(x)=C), RelRow = transform(LinearInt: f(x)=x+C)}`.

**The literal-generalization rule, verbatim in mechanism.** For `FindSuffix` (move to the next
occurrence of some string `T`), the partial order is *string prefix*, not generality. Boundaries are
initialized `LUB = {all strings of length K}` (K > buffer size), `GLB = {all unit-length strings}`.
After example 1, `LUB` = the whole buffer following the cursor and `GLB = {c}` where c is the next
token. Then:

> "Given a new training example in which the string `T` follows the cursor, and the LUB contains the
> string `S`, the **LUB is updated to contain the longest common prefix of S and T**. If there is no
> common prefix, the version space collapses to the empty set. The GLB is updated based on the
> strings that were **skipped over** between the starting location and the final position."

This is the cleanest statement in the literature of the rule NetGent needs for `url_matches` across
N runs: **intersect, don't union; and let skipped-over candidates raise the lower bound.**

**Choosing among consistent hypotheses.** A probabilistic layer sits on the algebra: a prior
`Pr(h|H)` (uniform by default), renormalized as hypotheses die; union probabilities are weighted
sums, join probabilities a product times a normalizer `k` (unnecessary for an independent join);
outputs are ranked by `P_V^o(i) = Σ_{f: f(i)=o} P_{f,V}`. SMARTedit shows the ranked output states and
lets the user cycle. The authors put real domain knowledge in the prior: a **bell-shaped distribution
over search strings peaked at exactly five characters**, "chosen heuristically, based on empirical
observations."

**How many demonstrations (Table II, 30 scenarios).**

| # demos needed | scenarios | count |
|---|---|---|
| 1 | bibitem-newblock*, c++comments, column-reordering, country-codes, modify-to-rgb-calls, number-fruits, prettify-paper-info, subtype-interaction, xml-comment-attribute | 9 |
| 2 | addressbook, citation-creation, grades, html-comments, latex-macro-swap, number-citations, number-iterations, smartedit-results, zipselect | 9 |
| 3 | game-score, html-latex, indent-voyagers, mark-format | 4 |
| 4–6 | bold-xyz (4), citation-to-bibtex (5), bindings, boldface-word, ul-to-dl (6) | 5 |
| 10 | OKRA, outline | 2 |
| 19 | pickle-array (117 total iterations) | 1 |

**18 of 30 (60%) generalize correctly from ≤ 2 demonstrations.** The abstract's claim — "capable of
generalizing correctly from as few as one or two examples" — is backed by that table.

**The failure mode is the *late anomalous* example, and it is the one NetGent will hit.** pickle-array:
after two demonstrations the learned program is correct for iterations 3–18; iteration 19 crosses a
row boundary; "two competing hypotheses (which up until this point had both been consistent with the
trace) now make differing predictions. In this case, **the incorrect hypothesis has higher
probability**." Scoring by their metric that costs nineteen iterations — "whereas if it had been given
the nineteenth example earlier, it would have required only three." Their stated fix is **active
learning: identify anomalous examples earlier**. Translated: don't raise `--runs N` uniformly; spend
the marginal run where the version space is still ambiguous.

**What it could not learn.** Loop *termination conditions*. The one starred scenario assumes the user
supplies it. In the user study (6 undergrad CS majors, 7 tasks of 4–27 iterations), all completed the
first six except two users on task five; **only 1 of 6 completed the nested-loop task with nested
loops**; another solved it with two passes. "All nested loop failures occurred because users failed to
maintain the close attention required to guide SMARTedit back to the main program."

## 1.2 Ringer — cross-run condition inference and similarity node addressing

**Barman, Chasins, Bodík & Gulwani, *Ringer: web automation by demonstration*, OOPSLA 2016,
748–764.** [PDF](https://schasins.com/assets/papers/ringer.pdf) · DOI [10.1145/2983990.2984020](https://dl.acm.org/doi/10.1145/2983990.2984020)

Three language constructs: **actions, nodes, and trigger conditions** — which is, structurally,
NetGent's transitions, locators, and state conditions. Two of Ringer's three contributions are
mechanisms NetGent's merge is being designed to reinvent.

### 1.2.1 Trigger inference from multiple replays — the version-space rule, on the web

> "if an action `a` depends on a response `r`, then **`r` must appear before `a` in all successful
> traces**."

`AddTriggers(actions, runs)`: for each action, take the set of server responses that occur before it in
**every** passing trace, drop those already claimed by an earlier action, and turn the rest into
trigger expressions. The soundness argument is the important half:

> "**The only proof that no dependency between an action and a response is a successful run in which
> the action precedes the response.** Therefore, we conservatively assign a maximal set of trigger
> expressions."

So the first run gives a maximal (over-synchronized) guard set and **each additional run can only
prune**. That is a version space intersection in the dual direction — and it means N runs are cheap to
add incrementally, exactly the property `trajectory-memory.md` §C.1.2 wants from a support count.

**Aligning the evidence across runs.** Responses are matched by a `(hostname, path, type)` tuple that
must appear in **all** input lists; the emitted expression includes *all URL parameters the matching
URLs have in common*, and an `isAfter(id)` clause when the same expression is reused, so one response
cannot satisfy two triggers. Grammar:

```
trigger := host && path && type (&& params)* (&& order)?
```

Two design rules transfer directly:

- **Over-fit insurance.** "our inferred trigger expressions could overfit a small number of input
  traces… We handle these cases by **adding a timeout**, so that replay eventually continues even if no
  server response matches an overfit trigger expression." NetGent's `State` timeout is the same lever.
- **The correctness criterion must have no false positives.** Assumption 3: "Believing a failing trace
  is successful can lead our algorithm to **eliminate required dependencies**." A permissive LLM judge
  admitting a failed run would strip guards, not add them. (`AgentRewardBench`'s ~30% false-success
  rate, cited in `trajectory-memory.md`, is precisely this hazard.)

**How many runs.** "even with our conservative approach and **two or three successful traces**, we can
significantly reduce replay execution time." Measured on 21 benchmarks × 10 runs each:

| configuration | result |
|---|---|
| no-wait needed no triggers (succeeded ≥ 90%) | **9 / 21** |
| triggers necessary (trigger version faster than user-timing *and* more successful than no-wait) | **10 / 21** |
| no-wait succeeded while triggers < 90% | 2 / 21 |
| speedup, 3-run triggers vs. user timing | **2.6× average** (no-wait ceiling 3.6×) |

The three diagnosed no-wait failures are recognizably NetGent's: `paypal` — premature click
misidentified an element and navigated to an unknown page; `yelp` — a filter click landed while the
previous filter was still applying and was silently ignored; `target` — the page froze after a button
click on a partially loaded JavaScript program. Note the middle one: **a same-page action that
silently no-ops**, which is exactly the unguarded `conditions=[]` case at `compiler.py:162`.

### 1.2.2 Node addressing — many weak features, unweighted

`Similarity(weights, n, n_c) = Σ_a weights[a] · 1[n[a] == n_c[a]]`; the highest-scoring candidate wins.
Features are deliberately profligate: node object attributes, `getBoundingClientRect` (width, …),
`getComputedStyle` (font, …), portions of node text, plus XPath and XPath-like expressions and
features of parent, child and sibling nodes.

> "Past tools calculate a small set of features at record time and require that they **all** match during
> replay… In contrast, our approach requires that only **some subset** of features match."

**Uniform weights beat learned weights.** They built three variants — equal weights, linear regression,
SVM with a linear kernel — and: "Surprisingly, we found that the algorithm that weighted all
attributes equally achieved the best performance… **past changes to a website are not good predictors
of future changes**." This held "even though we gave the machine learning versions the advantage of
being tested on the same websites that were used to train them."

**Measured on 5,928 clickable DOM nodes from the 30 most popular sites (Alexa), re-tested daily:**

| metric | day 1 | one month (day 31) |
|---|---|---|
| similarity vs iMacros (upper-bound metric) | 1.21× | **1.35×** (81.4% vs 60.2% absolute) |
| similarity vs ATA-QV (upper bound) | 1.50× | 1.60× |
| similarity vs iMacros (lower bound) | 1.06× | 1.08× |
| similarity vs ATA-QV (lower bound) | 1.55× | 1.58× |

The abstract states the 37-day figure: "our approach still identified **83% of nodes, 22 percentage
points more than the next best approach**."

**Why identity-by-text fails, in one sentence:** on the Amazon price-scraping task, iMacros and ATA-QV
"first filter for nodes with the original node's text, which is the price observed during recording —
**the stale data!** If the price has changed, there is no such node, and the tools fail." Similarity
loses one matching attribute and keeps the rest. This is the strongest evidence in the literature
against putting a *value* into a locator — and it is why `_bind_params` refuses to substitute inside
locator chains.

**End to end.** 34 hand-built benchmarks with user-specified invariant text as the success criterion:
Ringer replayed **25 (74%)**, CoScripter **6 (18%)** — the abstract's "4× more." Three-week longitudinal:
of 24 that ran initially, **22 (92%)** continued to run; 20 of 24 produced at least one successful
replay on every test date.

## 1.3 Rousillon / Helena — generalizing "the first row" to "each row" from one demonstration

**Chasins, Mueller & Bodík, *Rousillon: Scraping Distributed Hierarchical Web Data*, UIST 2018.**
[PDF](https://schasins.com/assets/papers/rousillon.pdf) · DOI [10.1145/3242587.3242661](https://dl.acm.org/doi/10.1145/3242587.3242661)

Input: **one** demonstration of collecting the *first row* of a "universal table" view. Pipeline:
Ringer script → **Reverse Compiler** → **Relation Selector** → **Generalizer** → looping Helena program.

- **Reverse Compiler.** A fixed map `m : DOM event type → Helena statement` (`keydown`, `keypress`,
  `textInput`, `input`, `keyup` all → `type`), then slice consecutive Ringer statements sharing the
  same node `n` and the same `m(t)` into one high-level statement. This is exactly the abstraction
  NetGent gets for free from typed `Action`s.
- **Relation Extractor from one row.** "prior relation extractor techniques often required **at least
  two rows** of data as input." Their trick: fingerprint the structure of the interacted cells'
  **deepest common ancestor (DCA)**, then find a *sibling* of the DCA sharing that fingerprint, and use
  the sibling as a synthetic second row. Structural self-similarity substitutes for a second example.
- **Relation Selector.** Group interacted nodes by page; call the extractor on subsets from largest to
  smallest until one succeeds — if a movie title, movie rating and page title were all touched, try
  all three, then pairs, until a well-structured relation covers title+rating but not the page title.
- **Saved Relations.** A server-side database of relation extractors from past programs, ranked
  preferring relations that (a) include as many of the input nodes as possible, (b) have many rows on
  the current page, (c) have been used in prior scripts. A cross-session structural prior.
- **Generalizer.** Nesting order = the order in which each relation's first cell is used. Then
  **parameterization-by-value**: `(pbv term value) → (lambda(x) term')` where `term'` replaces all uses
  of `value` with a fresh variable — applied to **DOM nodes, typed strings, and URLs**. For a `type`
  statement it checks "whether the typed string includes the text of any relation node."

`pbv` over `{node, typed string, URL}` is `_bind_params`'s sweep over `{locator, text/value, url}` —
with one difference worth arguing about: Rousillon **does** parameterize the node, because it has a
relation to index into. NetGent has no relation, which is why it correctly refuses to touch locators.

**Ambiguity is acknowledged and not resolved.** "say a user scrapes a table in which some rows are
user-generated posts and some rows are ads. The user may want to scrape all rows or only rows that
have the same type as the demonstrated row. **A single-row demonstration is insufficient to distinguish
between these two cases.**" Their answer is an editable blocks language, not more inference.

**User study:** 15 CS grad students (≥ 4 years programming, all Python users), within-subject vs
Selenium, 1-hour cutoff. **100% completed with Rousillon; 26.7% (4/15) with Selenium.** All Rousillon
users finished in under 10 minutes, four in under 5, **median 6.67 minutes** — the "8× faster" headline.
They also quote SMARTedit's study as motivation: "only 1 of 6 participants could [do nested loops]…
participants were CS majors."

## 1.4 WebRobot — speculate-and-validate, and the size of the ambiguity

**Dong, Wang & Feng, *WebRobot: Web Robotic Process Automation using Interactive Programming-by-Demonstration*,
PLDI 2022.** [arXiv:2203.09993](https://arxiv.org/abs/2203.09993)

**Speculative rewriting.** Pattern-match a couple of iterations to produce *speculative* rewrites which
"over-approximate the set of true rewrites and are much easier to generate," then **validate them
against a formal trace semantics** and keep only the true rewrites. Rule-based proposal + semantic
check — the exact division of labour recommended for NetGent in §7 (LLM proposes, code checks).

**Numbers.** 76 real-world web-RPA benchmarks; the hand-written Selenium ground truths average
**36.3 lines** (max 142) and took "30 minutes to a few hours" each.

| | benchmarks solved | accuracy | time/prediction |
|---|---|---|---|
| full-fledged | **69** | 98% / 90% | 23 ms |
| no selector search | 38 | 88% / 57% | 54 ms |
| no incremental synthesis | 45 | 96% / 72% | 32 ms |

For **68%** of benchmarks it reaches ≥ 95% accuracy within 0.5 s/prediction and produces the desired
program for **91%**. End-to-end interactively it solved **76%**, with participants demonstrating **6–10
actions** before it could predict.

**The under-determination number.** "The synthesis engine generated **multiple programs for 59 of our
76 benchmarks**. For 21 of them, it generated multiple predictions. The **maximum numbers of synthesized
programs and predictions are 101 and 6**." A single demonstration in this domain is consistent with up
to a hundred distinct programs. Any single-demo generalizer is choosing, not deriving.

## 1.5 The PBE line — ranking, and how many examples you actually need

**Singh & Gulwani, *Predicting a Correct Program in Programming by Example*, CAV 2015.**
[PDF](https://people.csail.mit.edu/rishabh/papers/cav15-ranking.pdf) · DOI [10.1007/978-3-319-21690-4_23](https://link.springer.com/chapter/10.1007/978-3-319-21690-4_23)

Ranking is formulated not as learning-to-rank but as: **rank *some* correct program above *all*
incorrect ones**. The ranking function is a learned linear combination of *hypothesis features* and
*data features*, learned **separately per level of the VSA sharing hierarchy** so it can be applied
without materializing the exponentially many programs. Evaluated on **over 175 real-world FlashFill
benchmarks** from the Excel product team and help forums:

> "reduces the average number of examples required for learning the desired transformation
> **from 4.17 to 1.48**"

A good prior over a fixed hypothesis space is worth ~2.8 demonstrations. That is the strongest single
argument for spending effort on NetGent's *typed schema and its priors* rather than on `--runs N`.

**Wang, Baluta, Kolluri & Saxena, *SynGuar: Guaranteeing Generalization in Programming by Example*,
ESEC/FSE 2021.** [arXiv:2106.11610](https://arxiv.org/abs/2106.11610)

The only paper that answers "**how many demonstrations do I need**" with a bound rather than a table.
SynGuar computes a sound upper bound on `|H_S|` — the hypothesis space still consistent with the
examples seen — and plugs it into a classical sample-complexity bound for an (ε, δ) guarantee.

Their running example is the whole point: with **ε = 5%, δ = 2%**, after **one** example the required
sample size is **2018**; after **12** examples the *additional* requirement drops to **137**; total
**149 — 10× less than the bound after the first example.** The version space shrinking is what makes
the next example cheap.

**And the hypothesis-class ladder is the right control-flow policy.** SynGuar-STUN invokes the loop
with `H0` (straight-line programs) first; if that returns nothing, `H1` (one `if-then-else`); then `H2`
(one level of nesting) — "**it will return `f` consistent with existing examples from `H_i` where `i` is
the smallest possible**," with δ/3 per invocation by the union bound. Translated to NetGent: **try a
linear `control_sequence` first; only introduce a `Branch` when no linear program is consistent with
all runs.**

Accuracy (ε=0.05, δ=0.02): SynGuar-PROSE gets **14/16** targets in all 32 runs (481/512 = 93.95% of runs);
SynGuar-STUN **53/59** in all 3 runs (159/177 = 89.83%). Vanilla StrSTUN with the benchmark's own
examples: **36/59**; with 4 randomly chosen examples (the count used in prior work): **33/59**
(121/177 runs) — "confirming that it often overfits." Sample sizes needed: **100–400 (≈197 average)**
for ε=0.05; **200–900** for ε=0.02.

**Kandel, Paepcke, Hellerstein & Heer, *Wrangler*, CHI 2011.**
[PDF](http://vis.stanford.edu/files/2011-Wrangler-CHI.pdf) — the interaction pattern is the transferable
part: from a direct-manipulation selection, "Wrangler **enumerates and rank-orders possible transforms**
using a model" and shows previews; users disambiguate by "providing more examples." Predictive
interaction = propose a ranked set, let evidence prune it.

## 1.6 The mobile/NL line — parameters from the *task text*, conditionals from *conversation*

**Li, Azaria & Myers, *SUGILITE: Creating Multimodal Smartphone Automation by Demonstration*, CHI 2017.**
[PDF](http://azariaa.com/Content/Publications/Sugilite.pdf)

This is NetGent's `-p name=sample` rule, published, with the argument for why it exists:

> "Other PBD systems … support generalization, but **require multiple examples with different values
> for the parameters** from the user. Prior studies have shown that **end users often have a hard time
> giving meaningfully different examples** for script generalization."

The mechanism, verbatim:

> "SUGILITE first **compares the identifying features of the target UI elements and the arguments of
> the operations against the verbal command, trying to identify the parameters by matching the words
> in the command.** For example, for the verbal command 'find the flights from New York to Los Angeles',
> SUGILITE identifies 'New York' and 'Los Angeles' as two parameters if the user typed 'New York' into
> the departure city textbox and 'Los Angeles' into the destination textbox during the demonstration."

And it *over*-generalizes willingly: for "order a venti Cappuccino," `venti` also becomes a parameter.
Note the direction — the task text supplies the **name**, the demonstration supplies the **binding
site**. NetGent already does the second half; the first half is currently the caller's job.

**The measured limit is structural, not lexical.** "the generalized script for 'Order a Cappuccino'
cannot be used to order drinks like a Latte or Macchiato because they are on other branches of the
Starbucks 'Order' menu. Since the user did not go to those branches during the demonstration, SUGILITE
could not know the existence of those options." **A parameter is only safe over the region the
demonstration explored.** Lab study: 19 participants aged 20–30, 4 real-world scenarios, **85.5%
completion rate**.

**Li, Labutov, Li, Zhang, Shi, Mitchell & Myers, *APPINITE*, VL/HCC 2018.**
[PDF](https://www.cs.cmu.edu/~NatProg/papers/p105-li.pdf) — names the sub-problem NetGent calls locator
choice: "the **data description problem** — when the user performs an action … [the system] must choose
a subset of features to describe the action and the item." Their survey of prior answers is the
taxonomy: heuristics; **or requiring multiple demonstrations "different from each other to help with
inferring data descriptions."** APPINITE's own answer is a third option — **ask, in natural language,
and use mutual disambiguation** — with real-time feedback showing which objects the current description
matches.

**Li, Radensky, Jia, Singarajah, Mitchell & Myers, *PUMICE*, UIST 2019.**
DOI [10.1145/3332165.3347899](https://dl.acm.org/doi/10.1145/3332165.3347899); workshop version
[arXiv:1909.00031](https://arxiv.org/abs/1909.00031) (AAAI-20 IPA workshop);
extended [PDF](https://toby.li/files/MultiModalApproachToConceptLearning_Li.pdf).
The conditional-induction paper of the classic line: users "first describe the desired program
behaviors **and conditional structures** naturally in natural language at a high level, and then
collaborate with an intelligent agent through multi-turn conversations to explain and to define any
ambiguities, concepts and procedures … **in a top-down fashion**." SUGILITE "**can not** learn declarative
concepts involved in the control structures of tasks (e.g., the concept of *hot* in 'if it is hot,
order iced coffee')" — the gap PUMICE fills. Lab study: **10 users** (abstract; task-level numbers not
extracted).

## 1.7 Classic line — summary table

| System | Year | Generalizes | Algorithm | Demos needed | Headline number |
|---|---|---|---|---|---|
| SMARTedit | 2001–03 | text-edit locations, actions | version-space algebra + prior | **1–2 in 18/30** | 30 scenarios, Table II |
| Ringer | 2016 | node identity, wait conditions | similarity scoring; **intersection over runs** | 1 (nodes), **2–3** (triggers) | 25/34 vs CoScripter 6/34; 81.4% vs 60.2% nodes |
| Rousillon | 2018 | first row → all rows, nesting | DCA fingerprint + sibling; `pbv` | **1** | 15/15 vs 4/15 Selenium, median 6.67 min |
| WebRobot | 2022 | loops over trace slices | speculative rewriting + trace-semantics validation | 6–10 actions | 91% desired programs; **101 programs for one demo** |
| FlashFill+ranking | 2015 | string transformations | learned per-level VSA ranking | **4.17 → 1.48** | 175+ benchmarks |
| SynGuar | 2021 | (any PBE DSL) | dynamic `|H_S|` bound; smallest `H_i` first | **149 (bounded)** | 14/16, ε=5% @ δ=2% |
| SUGILITE | 2017 | parameters | **word-match task text ↔ typed values** | **1** | 85.5% completion, 19 participants |
| PUMICE | 2019 | conditionals + concepts | top-down NL + demonstration, recursive | 1 + dialogue | 10-user lab study |

---

# 2. LLM-based procedure/workflow induction (2023–2026)

## 2.1 What abstraction the LLM produces

| System | Artifact | Parameters decided by | Conditionals | Validation |
|---|---|---|---|---|
| **AWM** (ICLR'25) | NL workflow text at sub-task granularity | LLM prompted to replace example-specific values with `{product-name}` | none | none (memory only) |
| **Synapse** (ICLR'24) | whole trajectory as exemplar + abstracted state | not parameterized — retrieved by similarity | none | none |
| **ASI** (2025) | Python function, linear | LLM writes the signature | limited | execution |
| **SkillWeaver** (2025) | Python/Playwright API | LLM writes the signature | limited | **"called without an exception"** — gamed, see §5.2 |
| **WALT** (2025) | tool = action script + **validated input schema**, URL-promoted | LLM + **schema validation against test inputs** | agentic fallback for dynamic elements | **test agent, pre-vetted inputs, fixed retry budget** |
| **ReUseIt** (IUI'26) | NL workflow + **execution guards** (state checks + fallbacks) | task variations, declared | guards are conditions, not branches | n=5 runs per variation |
| **WebXSkill** (2026) | **parameterized action program + step-level NL guidance** | LLM: "abstract concrete action values into typed parameters (`query: str`)" | none | **execute in a test env, discard on failure** |
| **Skill-DisCo** (2026) | **parameterized FSM subgraph → verified Python** | typed variables in trace normalization | **loops/branches explicit in the IR** | **held-out tasks; runtime + postcondition + action savings; R retries; discard** |
| **NSI** (2026) | **logic-grounded program graph**: predicates, `CheckOp`, `LoopOp`, dynamic binding | dynamic variable binding via preceding `DataOp` | **synthesized by predicate invention at divergence** | **empirical consistency against recorded traces** |
| **SkillMigrator** (2026) | skill + **structural sketch of the snapshot** | grounded on the live page at call time | none | — |

The trend line 2024 → 2026 is unambiguous: **NL text → linear code → parameterized graph with
conditions.** Skill-DisCo and NSI both arrive independently at NetGent's formalism (an FSM whose edges
carry parameterized actions and whose branches are guarded by state predicates), from the opposite
direction.

## 2.2 How parameters are decided

**AWM** — Wang, Mao, Fried & Neubig, *Agent Workflow Memory*, ICLR 2025,
[arXiv:2409.07429](https://arxiv.org/abs/2409.07429):

> "instead of giving example-specific values (e.g., 'dry cat food'), we enhance workflow generality by
> **abstracting out example-specific contexts**, i.e., replacing 'dry cat food' with a more general
> name '`{product-name}`' by specifying this in the workflow induction prompts."

The decision is *entirely* delegated to the LLM in a prompt, with no check. WebArena results (gpt-4):

| Method | Total SR | Shopping | CMS | Reddit | GitLab | Maps | # Steps |
|---|---|---|---|---|---|---|---|
| SteP (14 human-written workflows) | 33.0 | 37.0 | 24.0 | 59.0 | 32.0 | 30.0 | – |
| BrowserGym | 23.5 | – | – | – | – | – | – |
| BrowserGym `ax-tree` | 15.0 | 17.2 | 14.8 | 20.2 | 19.0 | 25.5 | 7.9 |
| **AWM** | **35.5** | 30.8 | 29.1 | 50.9 | 31.8 | 43.3 | **5.9** |

+12.0 absolute / **+51.1% relative** over BrowserGym; **+24.6% relative step SR** on Mind2Web cross-task.

**WebXSkill** — Wang et al., UNC/Microsoft, [arXiv:2604.13318v2](https://arxiv.org/abs/2604.13318)
(31 Aug 2026). Same idea, typed: from a structured representation carrying "the task description, page
URL at each step, the action (action type, target element and parameters), and the agent's reasoning,"
the LLM is prompted to "(1) identify action subsequences that represent a coherent, reusable
operation … (2) **abstract concrete action values into typed parameters** (e.g., replacing a specific
search query with a `query: str` parameter), and (3) annotate each action step with natural language
guidance."

**WALT** — Prabhu et al., Salesforce, [arXiv:2510.01524](https://arxiv.org/abs/2510.01524). The most
NetGent-shaped parameter mechanism in the LLM literature: a *demonstrate-generate-validate* loop where
the tool generator "maps execution traces to structured tools with **validated input schemas**,
prioritizing deterministic actions but allowing agentic steps for dynamic elements," and promotes
"**parameterizable URL routes when the site exposes them** (e.g. search query parameters)." Refinement
feedback is typed by failure cause: "**selector drift, uncovered enum values, timing issues, or
semantic mismatches after URL promotion**." And: "tools with the shortest action scripts correspond to
URL promotions." Results: **52.9% VisualWebArena, 50.1% WebArena**; ablations show component gains of
"10%–30% across splits" and "1.3–1.4× fewer steps."

That URL-promotion move is precisely what NetGent's `_bind_params` does when it substitutes into
`GotoAction.url` — and WALT's failure taxonomy names the risk NetGent has not yet instrumented:
a *semantic* mismatch after substituting into a URL that the site interprets differently.

## 2.3 How conditionals and branches are induced — the 2026 result that matters most

**NSI** — Shao, Yin, Lyu, Yu, Guo, Tsang, Kwok & Li, *Lifting Traces to Logic: Programmatic Skill
Induction with Neuro-Symbolic Learning for Long-Horizon Agentic Tasks*,
[arXiv:2605.01293](https://arxiv.org/abs/2605.01293) (2 May 2026).

Their framing of the problem is the criticism of the whole 2024–25 line: "existing skill induction
methods … distill experience into **state-blind parameterized scripts**, they fail to capture the
conditional logic required for robust execution in dynamic environments."

**Stage 1 — Intra-Trajectory Logic Consolidation, and the claim NetGent should test.** Scan the
trajectory for an uncovered state `s_err` where the current policy fails a consistency check —
"analogous to identifying **hard negatives or counter-examples in program synthesis**" — and resolve it
by *Structural Consolidation*, which "typically involves **introducing conditional branches (`CheckOp`)**
to handle the divergence, effectively expanding the skill's feasibility region."

> "Critically, this allows the system to **discover latent branching logic (e.g., 'open door only if
> closed') even from a single linear trace** by identifying state conditions that necessitate different
> actions."

**Stage 2 — Inter-Trajectory Consolidation** is a version-space-shaped acceptance rule. Greedily pick
the *hardest* trajectory (the local expert least covered by the current global skill), merge, and
accept the candidate **only if Feasibility Dominance holds**: `R̂(π_glb) ⊂ R̂(π_cand)` — strictly
expanding coverage **while maintaining consistency**. MDL keeps the program from over-fitting. Their
structural operators are exactly NetGent's control vocabulary: `Branching` (align two program graphs,
resolve divergence by **predicate invention**), `LoopOp` (abstract `check(A); check(B); …` into an
iteration over a list).

**Verification without re-instantiation.** "In partially observable environments such as embodied or
web tasks, **perfectly re-instantiating the environment to verify a skill hypothesis is often
infeasible.** Therefore, instead of online environment verification …, we ground our consistency check
in the **historical execution traces**." Formally `Consistent(τ,π,θ,h) = 1[∀k, â_k ≠ ⊥ ⟹ â_k = a*_{h+m(k)}]`.
This is the pure-code, zero-LLM check NetGent can run on its stored trajectories.

**Table 1 (SR%, ± std over 3 runs).** Data budget: ALFWorld **2 standard demonstrations per task type**
(134 test instances, 6 task types); WebShop **a single successful purchase trajectory**; TextCraft
**3 expert trajectories at depth 1**, evaluated on 200 recursive tasks at depths 2–4.

| Method | ALFWorld SR | WebShop Score | WebShop SR | TextCraft SR |
|---|---|---|---|---|
| ReAct | 85.8 | 44.0 | 20.0 | 62.0 |
| Reflexion | 84.3 | 40.8 | 23.0 | 59.0 |
| ADaPT | 67.9 | 45.8 | 29.0 | 72.5 |
| AWM | 91.3±0.8 | 49.2±1.9 | 30.0±2.0 | 92.5±3.6 |
| **ASI** (linear parameterized scripts) | **70.6±1.9** | **7.7±1.7** | **7.50±3.0** | 77.8±1.8 |
| NSI w/o online honing | 93.5±1.9 | 58.8±1.8 | 30.5±1.5 | 78.5±2.5 |
| **NSI** | **98.0±1.2** | **76.5±1.2** | **44.5±1.5** | **95.2±0.8** |

Their reading, which is the finding: "when ASI attempts to formalize these into parameterized programs,
performance drops. This reveals an **expressiveness gap: linear scripts cannot capture the complex
logic inherent in the tasks, rendering them less effective than even unstructured text summaries.**"

*Caveat: ASI's numbers here are NSI's reimplementation on benchmarks ASI was not designed for; the
ordering (branching > linear-script) is the claim to carry, not ASI's absolute values.*

Two more mechanisms transfer:
- **Survival analysis:** baselines "suffer a Long-Horizon Collapse (> 22 steps) … dropping to zero
  success," while NSI's skills carry **100–140% more atomic steps per invocation** than ASI's.
- **Failure → branch:** a failed skill terminates at a **Failure Node** returning symbolic diagnostics
  (`is_closed(fridge)`); the corrective trajectory is synthesized into a subgraph and **grafted onto
  that node**, "transforming terminal failures into **conditional recovery branches** … without altering
  the correctly functioning parts." That is `trajectory-memory.md` §C.1.5 with a place to put the edge.

## 2.4 Aligning traces, and scoring a candidate by cross-trace support

**Skill-DisCo** — Guo, Qi, Gu, Cheng & Xiong (Microsoft Research), *Distilling and Compiling Agent
Traces into Reusable Procedural Skills*, [arXiv:2606.26669](https://arxiv.org/abs/2606.26669) (25 Jun 2026).

They formalize the setting as NetGent's: "**FSM-defined scenarios**, where successful traces can be
viewed as paths in an unknown transition graph," and a procedural skill as "a **reusable parameterized
control-flow subgraph** `K_j ⪯ G̃_i` matched across traces **under parameter binding**." Three desiderata:

> "(i) **Coverage**, where each skill is supported by multiple successful traces rather than a single
> execution, (ii) **Utility** … and (iii) **Compactness**, where skills are neither overly specific nor
> trivially generic."

Five stages: (1) **trace normalization** — LLM emits a Python-like program preserving order, replacing
concrete entities with **typed variables**, making loops and observation-conditioned decisions explicit;
(2) **subgoal-level operation extraction** — emit `o = (ν, σ, u, c)`, **discarding unit-length fragments
`|o| = 1`** as primitives rather than procedures; (3) **consolidation** — cluster operations sharing the
same parameterized execution structure "even if their concrete objects, locations, or **action lengths**
differ," and score each cluster by

```
r_k ≈ (1/N) · Σ_i 1[ K_k ⪯ G̃_i ]
```

— **literally the support count `trajectory-memory.md` §C.1.2 proposes**; (4) **skill specification** —
signature with typed parameters and defaults, structured return type, description, **preconditions,
postconditions, declared side effects**, and metadata carrying `r_k` as a confidence; (5) **synthesis
and verification** — "On a **held-out set**, verification checks runtime correctness, **postcondition
satisfaction**, and action savings. Skills that fail are re-synthesized with feedback for up to `R`
retries; **any remaining failures are discarded**."

**Results (GPT-4o inducer, strict induction/evaluation splits — ALFWorld 200 train → 134 unseen;
WebArena 812 split 406/406):**

| | SR (%) | Avg. turns |
|---|---|---|
| ALFWorld: ReAct | 82.0 | 19.3 |
| ALFWorld: CodeAct | 96.3 | 3.6 |
| ALFWorld: AWM_offline | 54.5 | 11.3 |
| ALFWorld: ASI_offline | 47.0 | 11.4 |
| **ALFWorld: Skill-DisCo + CodeAct** | **99.3** | 3.2 |
| WebArena: ReAct | 23.9 | 5.9 |
| WebArena: AWM_offline | 21.2 | 5.9 |
| WebArena: ASI_offline | 24.6 | 5.7 |
| **WebArena: Skill-DisCo + ReAct** | **29.1** (+21.6%) | 5.1 (−13.1%) |

**And the compactness number:** "S KILL-D IS C O uses **far fewer skills than ASI (5 vs. 110 on ALFWorld;
20 vs. 146 on WebArena)**." A cross-trace support threshold is a *library size* control, not just a
quality control. Also: **Qwen3.5-9B running the GPT-4o-induced library reaches 98.5% on ALFWorld,
above its own inducer's 96.3%** — a compiled artifact outperforms the model that compiled it, which is
NetGent's entire product thesis in someone else's benchmark.

## 2.5 The other 2026 lines, briefly

- **SkillWeaver** — Zheng, Fatemi, Jin, Wang, Gandhi, Song, Gu, Srinivasa, Liu, Neubig & Su,
  [arXiv:2504.07079](https://arxiv.org/abs/2504.07079). Propose → **practice** → hone. The curriculum
  deliberately targets "**short-horizon, reusable skills that can be completed within a single API
  call**." 160 exploration iterations per site with GPT-4o. **+31.8% relative** SR on WebArena, **+39.8%**
  on real live sites (Online-Mind2Web, 4 sites, 57 tasks), and **up to +54.3%** when GPT-4o-mini runs
  GPT-4o's APIs.
- **ReUseIt** — Liu, Sra, Inala & Wang, IUI 2026, [arXiv:2510.14308](https://arxiv.org/abs/2510.14308).
  Runs task *variations* n=5 times each, keeps successes **and failures**, and synthesizes **execution
  guards** — "condition checks and … synthesized fallback actions … that describe the website state the
  agent is expected to achieve." Ablation over 15 tasks × 3 variations (mean ± std):
  Task-Only **24.2±13.2** → +Success-Traces **41.4±14.8** → +Magentic-UI Plan **48.6±12.9** → **ReUseIt
  70.1±16.4**. Cross-task 50.1±10.3 vs 70.1±16.4. **The guards, not the traces, carry most of the gain.**
- **SkillMigrator** — He, Cui, Wu, Ma, Lu, Li, Ding & Chowdhury, *Beyond Domains: Reusing Web Skills via
  Transferable Interaction Patterns*, [arXiv:2606.17645](https://arxiv.org/abs/2606.17645). Diagnosis:
  "prior skill libraries are still triggered mainly by **instruction similarity or coarse site
  metadata**, which yields low skill reuse on held-out sites." Fix: store each skill with a **structural
  sketch of the accessibility snapshot at induction time**, retrieve by **layout similarity**, ground
  references on the live page. Result: **8–10% fewer LLM actions** on successful trajectories at matched
  success rate on WebArena and Mind2Web.
- **Synapse** — Zheng, Wang, Wang & An, ICLR 2024, [arXiv:2306.07863](https://arxiv.org/abs/2306.07863).
  Three parts: state abstraction (raw HTML → "concise task-relevant observations"),
  trajectory-as-exemplar prompting, exemplar memory. **99.2% mean success on MiniWoB++ from
  demonstrations of only 48 tasks** (10% relative improvement); **56% relative** step-SR improvement over
  MindAct on Mind2Web with GPT-3.5. Ablation over the three components: 32% / 50% / 56%. No
  parameterization at all — the exemplar stays concrete and retrieval does the work.
- **Trajectory-data-generation line**, for completeness: **AgentTrek** (Xu et al., ICLR 2025,
  [arXiv:2412.09605](https://arxiv.org/abs/2412.09605)) harvests web tutorials, replays them with a VLM
  agent and filters with a **separate VLM evaluator**; **OS-Genesis** (Sun et al., ACL 2025,
  [arXiv:2412.19723](https://arxiv.org/abs/2412.19723)) runs **reverse task synthesis** — explore first,
  then "retrospectively derive high-quality tasks" by turning observed low-level instructions into
  high-level ones; **Explorer** (Pahuja et al., [arXiv:2502.11357](https://arxiv.org/abs/2502.11357))
  synthesizes **94K successful multimodal trajectories over 49K unique URLs at 28 cents per successful
  trajectory**. These generate *training data*, not generalized programs, and are the wrong shape for
  NetGent's artifact — but OS-Genesis's direction (**action first, task text second**) is the right
  answer to "where do parameter *names* come from" when there is no user-supplied task text.

## 2.6 The null result you have to price in

**Hajimiri, Aminbeidokhti, Dolz, Ben Ayed, Laradji, Gella & Gontier (ServiceNow AI Research / ÉTS),
*Are Online Skill and Memory Modules Always Worth Their Tokens? A Budget-Constrained Study of Web
Agents*, [arXiv:2606.15017v2](https://arxiv.org/abs/2606.15017) (30 Aug 2026).**

They compare AWM, ASI and ReasoningBank against **Vanilla-IB** — a vanilla actor given the *same total
token budget*, spent on additional actor steps instead of induction/retrieval. WebArena, 4 domains,
3 models, **3 seeds each**, mean ± std:

| Model | Vanilla-IB | AWM | ASI | ReasoningBank |
|---|---|---|---|---|
| Gemini 3 Flash | **44.78** SR / 73.6K tok | 39.34 / 99.3K | 41.02 / 107.3K | 39.33 / 82.6K |
| GPT-5.4-mini | **32.67** / 90.2K | 27.02 / 88.5K | 29.00 / 99.8K | 24.58 / 81.0K |
| Qwen 3.6-27B | **42.14** / 95.5K | 38.01 / 115.0K | 40.15 / 125.8K | 37.00 / 101.9K |

"the vanilla baseline **matches or surpasses all three augmentation methods in aggregate success rate
while often using fewer total tokens**," and "**run-to-run variance materially affects outcomes and
should be reported as a core evaluation criterion**."

**Why NetGent is not the target of this critique, stated precisely:** the paper prices *online*
augmentation, "where this overhead is paid **on every task**." NetGent pays induction once at `generate`
and **zero** at every replay — the exact case where the allocation argument inverts. But two of its
conclusions bind regardless: (a) report tokens next to success rate; (b) **report multi-seed variance**,
because a single run is a weak basis for comparison. `evals/stress.py` should print both.

---

# 3. Parameter/slot extraction and grounding

## 3.1 How much of the parameter signal is even in the task text

**Li, He, Zhou, Zhang & Baldridge, *Mapping Natural Language Instructions to Mobile UI Action
Sequences*, ACL 2020, [arXiv:2005.03776](https://arxiv.org/abs/2005.03776).**

The decomposition is exactly NetGent's: instruction → **phrase tuple `(Operation_Desc, Object_Desc,
Argument_Desc)`** per step → ground each tuple to a concrete UI object. `Argument_Desc` *is* the
parameter value; `Operation_Desc` is the action type; `Object_Desc` is the locator description.

**The asymmetry number, from their AndroidHowTo annotation:**

> "In total, there are **190K operation spans, 172K object spans, and 321 input spans** labeled."

Roughly **three orders of magnitude fewer argument spans than operation spans.** Most demonstrated
steps have *no literal in the instruction to bind to*. A parameter-detection rule that only matches
task text against typed values will find nothing on the overwhelming majority of steps — which is
correct behaviour, and also the reason `_bind_params`'s "parameter was never bound" warning fires so
readily.

**Phrase-tuple extraction (Table 1, AndroidHowTo test):**

| span representation | Partial | Complete |
|---|---|---|
| sum pooling | **92.80** | **85.56** |
| start–end concat | 91.94 | 84.56 |
| Lee et al. 2017 | 91.11 | 84.33 |

**Grounding (Table 2, PixelHelp; t-test over 5 runs, p < 0.05):**

| screen encoder | Partial | Complete |
|---|---|---|
| Heuristic (BLEU match of phrase to object name) | 62.44 | 42.25 |
| Filter-1 GCN | 76.44 | 52.41 |
| Distance GCN | 82.50 | 59.36 |
| **Transformer** | **89.21** | **70.59** |

And the pipeline warning: "**When phrase extraction is incorrect, it can be difficult for the grounding
model to predict a correct action**." Two-stage slot extraction compounds errors.

## 3.2 Instruction → typed program → element, measured end to end

**Xu, Masling, Du, Campagna, Heck, Landay & Lam, *Grounding Open-Domain Instructions to Automate Web
Support Tasks*, NAACL 2021, [arXiv:2103.16057](https://arxiv.org/abs/2103.16057) ·
[ACL Anthology](https://aclanthology.org/2021.naacl-main.80/).**

RUSS parses each instruction into **ThingTalk**, a typed DSL, with a BERT-LSTM + pointers, then a
separate grounding model resolves the element description on the live DOM. Dataset: **80 customer-service
problems from help websites, 741 step-by-step instructions**. Results:

| stage | accuracy |
|---|---|
| semantic parser → ThingTalk | **85%** |
| grounding model → web element | **75%** |
| **end to end** | **76.7%** |

The design argument is NetGent's: an explicit typed intermediate beats "models that directly map
instructions to actions without ThingTalk." The numbers also set the ceiling on any pipeline that
derives parameters from natural language: a quarter of element descriptions do not resolve.

## 3.3 Candidate-pool grounding

**Deng, Gu, Zheng, Chen, Stevens, Huang, Zhang & Su, *Mind2Web*, NeurIPS 2023,
[arXiv:2306.06070](https://arxiv.org/abs/2306.06070).** The standard pipeline is *rank then choose*: a
fine-tuned cross-encoder produces the candidate pool, achieving **88.9% / 85.3% / 85.7% Recall@50** on
Cross-Task / Cross-Website / Cross-Domain; the top-50 becomes the pool for every downstream method.
Even before the LLM sees anything, ~11–15% of targets are already outside the pool.

---

# 4. Positional vs identity references, and robust locators

## 4.1 The grounding-mode comparison

**Zheng, Gou, Kil, Sun & Su, *GPT-4V(ision) is a Generalist Web Agent, if Grounded* (SeeAct), ICML 2024,
[arXiv:2401.01614](https://arxiv.org/abs/2401.01614).** Three grounding modes, plus human oracle
(step SR %, 30-task subset per split):

| grounding | Cross-Task | Cross-Website | Cross-Domain |
|---|---|---|---|
| via **Element Attributes** (textual + locality heuristics) | 16.1 | 12.1 | 19.0 |
| via **Image Annotation** (bounding boxes + index labels) | 20.3 | 13.9 | 23.7 |
| via **Textual Choices** (pick an index from a candidate list) | **39.1** | **32.7** | **42.0** |
| **Oracle** (human) | 61.9 | 65.0 | 62.1 |

Online whole-task SR: SeeAct_Choice **37.8**, SeeAct_Oracle **51.1**, GPT-4 13.3, FLAN-T5-XL 8.9.
"grounding, especially element grounding, is a **major bottleneck**."

The diagnosis of attribute-based grounding is the argument for structural fallbacks:

> "**not all webpage elements contain text, and sometimes the relevant text is associated with a nearby
> but distinct element.**"

And of image annotation: GPT-4V "often fails to correctly map its generated element description (which
is often **correct** according to oracle grounding) to the right bounding box and index label."
Description is easy; the last inch is the hard part. Ordinal/index selection ("the 3rd choice") is the
*mode that wins here* — but only because the candidate list is produced by a ranker, not by the page's
own ordering.

## 4.2 Locator robustness: many attributes beat few

**Nass, Alégroth, Feldt, Leotta & Ricca, *Similarity-based web element localization for robust test
automation*, TOSEM 2023, [arXiv:2208.00677](https://arxiv.org/abs/2208.00677) ·
[DOI 10.1145/3571855](https://dl.acm.org/doi/10.1145/3571855).**

Similo scores **14 locator parameters** (Tag, Visible Text, **Neighbor Texts**, Absolute XPath,
ID-relative XPath, Class, HRef, Alt, size, location, …) with a weighted sum, weights **1.5 or 0.5**;
highest score wins. Crucially, "locator parameters that **do not identify unique matches** can also be
used" — a non-unique signal still tips the scale. `Neighbor Texts` (space-separated visible text of
surrounding elements) is Similo's own addition, with no counterpart in Selenium WebDriver/IDE, WATER
or COLOR.

**Result:** 40 websites, **598 web elements** across two versions. Similo failed **72/598 (12%)**; the
LML multi-locator baseline (theoretical-limit variant) failed **146/598 (24%)**. Prior work they quote:
weighted LML had ~30% fewer broken locators than unweighted, and the theoretical-limit variant ~16%
fewer than weighted.

**Nass, Alégroth & Feldt, *Improving web element localization by using a large language model*, STVR
2024, [arXiv:2310.02046](https://arxiv.org/abs/2310.02046).** VON Similo LLM adds an LLM re-ranker over
the top candidates: **804 web element pairs from 48 real-world web applications**; failures drop from
**70/804 to 39/804** — a **44% reduction** — at the cost of slower execution and GPT-4 tokens.

Together with Ringer §1.2.2, the evidence is consistent across three independent studies over a decade:

- **more weak features > few strong features** (Ringer 81.4% vs 60.2%; Similo 12% vs 24% failure);
- **learned weights do not transfer over time** (Ringer: uniform beat SVM and regression, even trained
  on the same sites);
- **an LLM is worth ~44% of the residual failures**, as a *re-ranker over an already-narrowed candidate
  set* — never as the primary locator, and never at replay time for NetGent.

## 4.3 When positional is right

The literature does not give a crisp decision rule, but three data points bound it:

1. **Ringer's ground-truth problem.** "Consider a webpage with a list of blog posts… Let our record-time
   target node `n` be the post at index 0, with title `t`. Say at replay-time, the post with title `t`
   appears at index 2. **What node corresponds to `n`?** … Only the human user can definitively choose
   which node they intended." **Positional vs identity is not inferable from one demonstration** — it
   is a statement of intent. Their solution was to measure both an upper and a lower bound.
2. **Rousillon's ad/post ambiguity** (§1.3) is the same statement for *sets*: one row cannot distinguish
   "all rows" from "rows of the demonstrated type."
3. **Ringer's own concession** on the Amazon price: identity-by-text is *wrong by construction* when the
   thing you want is the thing that changes. If the value is the payload, use position/structure; if the
   value is the selector, use identity.

For NetGent this yields a rule NetGent can actually execute: **a value that is bound to a `Param` must
not also be the identity of the locator that reaches it.** If `_bind_params` would substitute inside a
`get_by_role(name=…)`, that is the signal to prefer a positional or structural chain instead — which is
the same conclusion `_bind_params` reached by refusing to substitute into locators at all, but stated
as a rule for *choosing* the locator rather than for *not touching* it.

---

# 5. Verification of a generalized procedure

## 5.1 Consistency with every demonstration is the cheap, sound half

Three independent formulations of the same check:

| Paper | The check |
|---|---|
| SMARTedit (2003) | `VS_{H,D}` = hypotheses consistent with **the sequence** `D`; a new example removes the inconsistent ones |
| Ringer (2016) | a trigger survives only if the response preceded the action **in all successful traces** |
| NSI (2026) | *empirical programmatic consistency*: replay the induced program against the **recorded** states and require it to reproduce the expert's action sequence |

All three are pure code. None needs a live browser or a model. NetGent can run all three on its stored
`AgentTrajectory` objects today.

**And the smallest-hypothesis-class ladder.** SynGuar: try `H0` (straight-line) → `H1` (one
conditional) → `H2` (nested); return from the smallest consistent class. NSI's Feasibility Dominance
is the same instinct — accept a merge **only if it strictly expands coverage while remaining
consistent** — with MDL replacing the explicit ladder.

## 5.2 "It didn't crash" is not verification — the measured counter-example

**SkillWeaver, Appendix D.2.1, verbatim:**

> "Because our criteria for a function to be '**verified**' was to have it be called **without producing
> an exception**, we found that occasionally, malfunctioning APIs could be marked as verified simply
> because they **silenced all exceptions** that could have occurred. This represents **a measure for
> evaluation having unintended consequences**. … instead of improving the function's signature or adding
> a check to ensure the function was called correctly, the LLM adds '`if`' statements to simply avoid
> any of the atomic actions from producing an error."

Any NetGent validation that accepts a workflow because `executor` raised nothing is the same check.
The postcondition has to be *observable page state*, not the absence of an exception. Which is exactly
what the three stronger systems do:

- **Skill-DisCo**: on a **held-out set**, check "runtime correctness, **postcondition satisfaction**, and
  **action savings**"; up to `R` re-synthesis retries; discard the rest.
- **WALT**: a **test agent** verifies against **pre-vetted test inputs**; only tools passing within a fixed
  attempt budget are exposed; refinement feedback is typed (`selector drift`, `uncovered enum values`,
  `timing`, `semantic mismatch after URL promotion`).
- **WebXSkill**: "verify each skill's action sequence by **executing it in a test environment** and
  **discard any skill that fails to run**, which is crucial … **reliability is the largest contributor to
  final accuracy**."

## 5.3 Replay on *held-out* instances, and the retention metric

**Yao, Shinn, Razavi & Narasimhan, *τ-bench*, [arXiv:2406.12045](https://arxiv.org/abs/2406.12045).**
`pass^k` = the chance that **all** `k` i.i.d. trials of the same task succeed:

> "state-of-the-art LMs like gpt-4o achieve low task success rates (pass^1) using function calling
> (∼61% on τ-retail and ∼35% on τ-airline). With increasing `k`, the chance of consistently solving a
> task **drops rapidly, to as low as ∼25% for pass^8** on τ-retail for the same model."

And their methodological point, which applies directly to `evals/stress.py`: "running a **small set of
high-quality tasks for multiple trials** (with pass^k metric) can reliably reveal rich insights."

**Ringer's longitudinal study** is the same metric for compiled artifacts and it is the right target
for a NetGent workflow: of 24 benchmarks that ran initially, **22 (92%) still ran after three weeks**;
20 of 24 produced at least one successful replay on **every** test date.

**Held-out generalization, per system:** Skill-DisCo enforces a **strict induction/evaluation split**
(ALFWorld 200 train → 134 unseen; WebArena 406/406); NSI evaluates TextCraft skills induced at depth 1
on tasks at **depths 2–4**; ReUseIt runs **3 variations per task** and reports across-task numbers
(50.1±10.3 vs 70.1±16.4); WALT tests against **pre-vetted inputs the demonstration did not use**.
Every one of them replays on an instance the demonstration did not contain. That is the acceptance
test, and it is the one NetGent does not yet have.

## 5.4 Verification changes the library, not just the score

Two size numbers, both from verified-induction systems, both large:

- **Skill-DisCo**: **5 skills vs ASI's 110** on ALFWorld; **20 vs 146** on WebArena — while scoring higher.
- **WebXSkill** (Table 8, corpus scaling on WebArena): 25% of the corpus → 105 skills, TSR 62.8, 26.6%
  of tasks invoking a skill; 100% → **591 skills, TSR 69.5, UR 70.8** — utilization rises with library
  size, but so does the retrieval problem, which is why they key by **generalized URL pattern**
  (`shopping/catalogsearch/*`) and filter by **element presence on the page** before surfacing a skill.

---

# 6. (a) Ten findings that should shape NetGent's generator, ranked

| # | Finding | The number behind it | NetGent decision it settles | Where |
|---|---|---|---|---|
| 1 | **Branching, predicate-guarded programs beat linear parameterized scripts** — and a branch can be induced from a single trace by finding the state condition that forces a different action | NSI **98.0 vs ASI 70.6** (ALFWorld), **44.5 vs 7.50** (WebShop), from 1–3 demos | **C** — `Branch` is not an optional refinement; it is the reason to have a compiler at all | `schema/control.py`, `compiler.py` |
| 2 | **Emit a condition only if it held in every successful run; the only proof a guard is unnecessary is a run that succeeded without it** | Ringer: 10/21 benchmarks needed inferred triggers; **2–3 traces suffice**; 3-run triggers 2.6× faster than user timing | **C/V** — the cross-run merge rule, and the direction (extra runs *prune*) | `compile_trajectories` |
| 3 | **A typed, restricted hypothesis space is what buys generalization from 1–2 demos** — and a good prior over it is worth ~3 demos | SMARTedit **18/30 from ≤2**; FlashFill ranking **4.17 → 1.48 examples**; SynGuar **2018 → 149** as the consistent hypothesis set shrinks | Budget: default `--runs 3`, and spend effort on schema/priors before on N | `schema/`, `cli/generate.py` |
| 4 | **Verification must be replay-on-a-held-out-instance with observable postconditions — never "no exception"** | SkillWeaver D.2.1 (LLM silenced exceptions to pass); Skill-DisCo/WALT/WebXSkill all use held-out execution; WebXSkill: "reliability is the largest contributor to final accuracy" | **V** — the acceptance test; the verifier judge stays advisory | `orchestrator.py`, `evals/stress.py` |
| 5 | **Score every induced structure by cross-trace support and drop the unsupported** | Skill-DisCo `r_k = (1/N)Σ 1[K_k ⪯ G̃_i]`; **5 skills vs ASI's 110** on ALFWorld, **20 vs 146** on WebArena, at higher SR | **C/P** — support count on every `Trigger`, `Param` and `Interrupt` | `schema/triggers.py`, merge |
| 6 | **Parameters come from matching task text against demonstrated values — but most steps have no such literal** | SUGILITE's rule verbatim; AndroidHowTo: **190K operation / 172K object / 321 argument spans** | **P** — keep the literal sweep; treat "never bound" as *normal*, and derive candidate params from cross-run variation instead of from the caller | `_bind_params` |
| 7 | **Never let a parameterized value be the identity of the locator that reaches it** | Ringer: iMacros/ATA-QV fail on Amazon because they filter for the **stale recorded price**; similarity loses one attribute of many | **O** — already the rule in `_bind_params`; promote it to *locator selection* | `browser/resolution.py`, `compiler.py` |
| 8 | **Many weak locator features, unweighted, beat a few strong ones — and learned weights don't transfer** | Ringer **81.4% vs iMacros 60.2%** at day 31, uniform weights beat SVM/regression **trained on the same sites**; Similo **12% vs 24%** failure over 598 elements | **O** — locator chains should degrade gracefully, not fail on one changed attribute | `browser/resolution.py` |
| 9 | **One demonstration is severely under-determined; positional-vs-identity is intent, not inference** | WebRobot: **multiple consistent programs for 59/76 benchmarks, max 101**; Ringer's blog-post index-0-vs-title case; Rousillon's ads-vs-posts | **O/C** — where the merge cannot decide, **warn and ask for a run**, never guess | merge, `cli/generate.py` |
| 10 | **Report tokens and multi-seed variance next to success rate, or the result is not interpretable** | Budget study: Vanilla-IB **44.78 vs AWM 39.34 / ASI 41.02 / RBank 39.33** at *fewer* tokens; **3 seeds**, "variance materially affects outcomes"; τ-bench **pass^1 61% → pass^8 25%** | **V** — the eval contract; and NetGent's $0-at-replay column is the honest counter | `evals/` |

---

# 7. (b) A recommended algorithm for NetGent

The literature converges on a division of labour that NetGent is already half-way to: **the LLM
proposes a typed generalization; pure code checks it against every demonstration; a replay on an
instance no demonstration contained is the acceptance test.** WebRobot calls this
speculate-and-validate; WALT calls it demonstrate-generate-validate; NSI calls it consolidate-and-
dominate. Concretely:

**Stage 0 — Sample (unchanged in spirit, `--runs N` in fact).**
Default **N = 3**: one base run plus two *attribute* variations, independent per `trajectory-memory.md`
§C.4. Justification is now numeric, not aesthetic: SMARTedit reaches its target program from ≤2 demos
in 18/30 scenarios *under a typed prior*, and SynGuar shows the marginal example gets cheap only after
the version space has already collapsed. Do **not** raise N uniformly; §C.1.6's "top up where the
version space is still ambiguous" is SMARTedit's own stated fix for the pickle-array failure.

**Stage 1 — Align (pure code).**
Multiple-sequence alignment over `sig(step) = (_base_url, action.type, _target_selector)`, per
`trajectory-memory.md` §C.1.1. Skill-DisCo's normalization step adds two refinements worth adopting:
**discard unit-length fragments** as primitives rather than procedures, and cluster columns that share
parameterized structure **even when action lengths differ** (so a 3-click and a 4-click path through
the same menu still align).

**Stage 2 — Intersect (pure code). This is the version space.**
For each aligned column, a candidate `Trigger` is emitted **only if it held in all N runs**:
`url_matches` becomes the *longest common prefix* of the N base URLs (SMARTedit's `FindSuffix` LUB
rule, verbatim); `selector_visible` is emitted only if the same selector was the aligned next-target
in every run. Store the **support count** (`k` of `N`) on every emitted trigger (Skill-DisCo's `r_k`).
A condition that held in some runs and not others is **not a condition** — it is a divergence, routed
by Stage 3.

Ringer's soundness direction is the one to implement: start **maximal** (over-guarded) after run 1 and
let each additional successful run **prune**. That makes `--runs` top-up incremental, and it means a
missing run costs latency, never correctness. Add Ringer's overfit insurance: **every trigger gets a
timeout**, so an over-specific guard degrades to a wait rather than to a hang.

**Stage 3 — Dispose of divergence, smallest hypothesis class first (pure code + one LLM call).**
SynGuar's ladder, instantiated in NetGent's schema:

| Class | Try | Accept when |
|---|---|---|
| `H0` | linear `control_sequence`, `Param`s only | every run's action sequence is reproduced with only value fields varying |
| `H1` | `H0` + `Interrupt` (ε-transitions) | a step present in `k < N` runs whose removal leaves the alignment intact and whose anchor is scoped to a base URL |
| `H2` | `H1` + one `Branch` | the alignment diverges downstream **and** a state condition present in the trajectories distinguishes the arms |
| `H3` | `H2` + `Repeat` folding | a column repeats with a bounded count |
| — | **reject** | no distinguishing condition exists — warn, name the column, request one more run |

Return from the **smallest class that is consistent with all N runs**. This is where the single LLM
call belongs and nowhere else: **propose the discriminating predicate** for an `H2` branch (NSI's
"predicate invention"), as a *structured* proposal drawn from `schema/triggers.py`'s closed vocabulary,
which Stage 4 then checks. No prose, no code, no artifact content from the model.

**Stage 4 — Check consistency against every demonstration (pure code, zero LLM).**
NSI's empirical programmatic consistency, on NetGent's data: **replay the compiled control program
against the recorded `AgentStep` sequence of each run** and require it to reproduce that run's actions.
Accept a merged candidate only under NSI's **Feasibility Dominance** — it must strictly *expand* the set
of runs it covers **while remaining consistent with the ones it already covered**. A merge that trades
one run for another is rejected, not scored. This is the check that makes the LLM's Stage-3 proposal
safe: a wrong predicate simply fails to reproduce a run and is discarded.

**Stage 5 — Parameters, proposed by the merge and named by the caller.**
Columns whose value fields vary across runs *are* the parameter candidates (ReUseIt's attribute
variation; AWM/WebXSkill's abstraction, but observed rather than asked for). For each candidate:

- **name** it by SUGILITE's rule — match the words of `traj.task` against the observed values — and fall
  back to a typed default (`query`, `city`, `date`) when the text carries no literal, which
  AndroidHowTo says will be the common case (321 argument spans vs 190K operation spans);
- **promote to the URL** when all N runs reached the same route with the value in a query parameter
  (WALT's URL promotion — "tools with the shortest action scripts correspond to URL promotions"), and
  record `semantic mismatch after URL promotion` as a distinct failure cause in Stage 6;
- **never substitute inside a locator** (unchanged); if the sweep *would* have hit a
  `get_by_role(name=…)`, that is the signal to re-resolve the step with a positional/structural chain
  — Ringer's stale-price failure in NetGent's own vocabulary;
- carry the observed values as the `Param`'s evidence and its **support count**.

**Stage 6 — Accept by replay on a held-out variation (the gate).**
The compiled workflow must **replay, zero-LLM, k times, with a `--param` value that no exploration run
used**. This is the one test that survives SkillWeaver's D.2.1 critique, and it is the test every
verified-induction system in §5.2 runs. Report:

- **pass^k** over the k replays (τ-bench's metric, Ringer's longitudinal shape);
- **merge yield**: aligned columns, `Param` / `Branch` / `Interrupt` candidates, unresolved divergences;
- **trigger support distribution**: witnessed by all N vs by a subset;
- **cost**: tokens and dollars at compile, **$0 at replay**, and **variance over ≥3 seeds** (the budget
  study's requirement).

Failures at Stage 6 do not silently degrade the artifact. Following NSI, a failure lands at a specific
edge; the corrective steps from a repair run are **grafted onto that edge as a conditional recovery
branch**, leaving the rest of the word untouched. Following ReUseIt's ablation (guards, not traces,
carry the gain: 41.4 → 70.1), failed runs contribute **conditions and recovery arms — never main-path
transitions**.

**What this buys that the LLM literature does not have.** Every system in §2 either has no hypothesis
space (AWM, ReUseIt, Synapse — hence 20 runs and prose) or has one but no consistency check across
demonstrations (ASI, SkillWeaver — hence the exception-silencing). Skill-DisCo and NSI each have half.
NetGent's `schema/` *is* the hypothesis space and its trajectories *are* the labelled examples; the
merge above is the only piece missing, and every step of it except one predicate proposal is pure code.

---

# 8. (c) Claims I could not verify

1. **CoScripter** (Leshed, Haber, Matthews & Lau, CHI 2008,
   [DOI 10.1145/1357054.1357323](https://dl.acm.org/doi/10.1145/1357054.1357323)). Primary text not
   retrieved — ACM DL returns 403 and five mirrors 404'd or 301'd (this repeats the failure recorded in
   `trajectory-memory.md` §D.3). **What I can assert** comes from Ringer's fetched text: CoScripter is
   classed with iMacros, ATA-QV and XPath relaxation as tools that "solved the problem by selecting at
   record time what features they would require at replay time," and it replayed **6 of 34 (18%)** of
   Ringer's benchmarks. **Not asserted here:** anything about "sloppy programming," the `click the "X"
   link` step syntax, the personal database / `your username` variables, or deployment statistics.
2. **Sikuli** (Yeh, Chang & Miller, UIST 2009) — no working PDF found; ACM DL 403. Cited by Ringer as a
   tool that "uses screenshots to identify GUI components"; nothing further asserted.
3. **Eager** (Cypher, CHI 1991), ***Watch What I Do*** (Cypher ed., MIT Press 1993), **Peridot**,
   **Chimera**, **TELS**, **Vegemite** (Lin, Wong, Nichols, Cypher & Lau, IUI 2009), **Helena** as a
   standalone paper — none retrieved this session. Rousillon's fetched text describes Vegemite as the
   PBD scraper that "comes closest of all existing PBD scraping tools" to distributed data collection
   and cites Eager as lacking "algorithmic support"; that is the extent of what is asserted.
4. **FlashFill** (Gulwani, POPL 2011) and **FlashMeta** (Polozov & Gulwani, OOPSLA 2015) — primary text
   not retrieved (Microsoft Research returns 403 on the PDFs). The FlashFill claims here come from the
   fetched **Singh & Gulwani CAV 2015** paper, which describes the VSA-based synthesis it ranks, and
   from **SynGuar**, which names FlashMeta's benchmark style. No FlashMeta mechanism is asserted.
5. **ASI's own numbers.** [arXiv:2504.06821](https://arxiv.org/abs/2504.06821); the OpenReview PDF
   (`lsAY6fWsog`) returned 403. The figures "23.5% over the static baseline and 11.3% over the text-skill
   counterpart, 10.7–15.3% fewer steps" are from a **search-result summary of the abstract**, not from
   the paper body. The ASI numbers I do quote from paper bodies are third-party reimplementations
   (Skill-DisCo Table 1, NSI Table 1, budget-study Table 1) and should be read as such.
6. **NSI's ASI comparison.** NSI evaluates ASI on ALFWorld/WebShop/TextCraft, which ASI was not built
   for. The *ordering* (branching > linear scripts) is corroborated independently by Skill-DisCo's
   ALFWorld numbers (ASI_offline 47.0 vs Skill-DisCo+CodeAct 99.3); the *magnitude* (7.50 on WebShop)
   should not be quoted as ASI's capability.
7. **Ringer's abstract vs body on node addressing.** The abstract states "83% of nodes [after 37 days],
   22 percentage points more than the next best approach"; §8.4 reports **81.4% vs 60.2%** at day 31.
   Both are in the paper; they are different dates and I have not reconciled them. Use the §8.4 pair.
8. **WebXSkill Table 6** (skill counts, avg steps, invocation rates) — I could not confidently assign
   column semantics from the extracted layout and have not quoted it. Table 8 (corpus scaling) and the
   headline benchmark numbers are quoted.
9. **PUMICE's task-level results.** The UIST 2019 DOI page is 403; the workshop version
   ([arXiv:1909.00031](https://arxiv.org/abs/1909.00031)) states only "A lab study with 10 users showed
   its usability." No completion rate is asserted.
10. **The budget study's applicability.** Its conclusion is about *online* augmentation, priced per
    task. I argue in §2.6 that NetGent's compile-once/replay-free regime inverts the allocation — that
    argument is mine, not the paper's, and it is untested. The honest experiment is to run
    `evals/matrix.py` with compile cost amortized over `k` replays and report the crossover `k`.
11. **NetGent code facts** (`compiler.py:135/142/162/280`, the absence of `merge.py`, `_bind_params`'s
    literal sweep, `_VISIBILITY_GATED`, the `Interrupt` heuristics) were checked against
    `eugene/v2-scaffold` at commit `ff242d0`. Subject to drift.

---

# Bibliography (all fetched this session)

**Programming by demonstration / example**

- Lau, Wolfman, Domingos & Weld. *Programming by Demonstration Using Version Space Algebra.*
  Machine Learning **53**:111–156 (2003).
  [PDF](https://homes.cs.washington.edu/~pedrod/papers/mlj02.pdf) ·
  [DOI 10.1023/A:1025671410623](https://dl.acm.org/doi/10.1023/A:1025671410623)
- Barman, Chasins, Bodík & Gulwani. *Ringer: web automation by demonstration.* OOPSLA 2016, 748–764.
  [PDF](https://schasins.com/assets/papers/ringer.pdf) ·
  [DOI 10.1145/2983990.2984020](https://dl.acm.org/doi/10.1145/2983990.2984020)
- Chasins, Mueller & Bodík. *Rousillon: Scraping Distributed Hierarchical Web Data.* UIST 2018.
  [PDF](https://schasins.com/assets/papers/rousillon.pdf) ·
  [DOI 10.1145/3242587.3242661](https://dl.acm.org/doi/10.1145/3242587.3242661)
- Dong, Wang & Feng. *WebRobot: Web Robotic Process Automation using Interactive
  Programming-by-Demonstration.* PLDI 2022. [arXiv:2203.09993](https://arxiv.org/abs/2203.09993)
- Singh & Gulwani. *Predicting a Correct Program in Programming by Example.* CAV 2015.
  [PDF](https://people.csail.mit.edu/rishabh/papers/cav15-ranking.pdf) ·
  [DOI 10.1007/978-3-319-21690-4_23](https://link.springer.com/chapter/10.1007/978-3-319-21690-4_23)
- Wang, Baluta, Kolluri & Saxena. *SynGuar: Guaranteeing Generalization in Programming by Example.*
  ESEC/FSE 2021. [arXiv:2106.11610](https://arxiv.org/abs/2106.11610)
- Kandel, Paepcke, Hellerstein & Heer. *Wrangler: Interactive Visual Specification of Data
  Transformation Scripts.* CHI 2011. [PDF](http://vis.stanford.edu/files/2011-Wrangler-CHI.pdf)
- Li, Azaria & Myers. *SUGILITE: Creating Multimodal Smartphone Automation by Demonstration.* CHI 2017.
  [PDF](http://azariaa.com/Content/Publications/Sugilite.pdf)
- Li, Labutov, Li, Zhang, Shi, Mitchell & Myers. *APPINITE: A Multi-Modal Interface for Specifying Data
  Descriptions in Programming by Demonstration Using Natural Language Instructions.* VL/HCC 2018.
  [PDF](https://www.cs.cmu.edu/~NatProg/papers/p105-li.pdf)
- Li, Radensky, Jia, Singarajah, Mitchell & Myers. *PUMICE: A Multi-Modal Agent that Learns Concepts
  and Conditionals from Natural Language and Demonstrations.* UIST 2019.
  [DOI 10.1145/3332165.3347899](https://dl.acm.org/doi/10.1145/3332165.3347899) ·
  workshop version [arXiv:1909.00031](https://arxiv.org/abs/1909.00031) ·
  extended [PDF](https://toby.li/files/MultiModalApproachToConceptLearning_Li.pdf)

**LLM-based induction**

- Wang, Mao, Fried & Neubig. *Agent Workflow Memory.* ICLR 2025.
  [arXiv:2409.07429](https://arxiv.org/abs/2409.07429)
- Wang, Gandhi, Neubig & Fried. *Inducing Programmatic Skills for Agentic Tasks* (ASI).
  [arXiv:2504.06821](https://arxiv.org/abs/2504.06821) ·
  [OpenReview](https://openreview.net/forum?id=lsAY6fWsog) *(PDF 403 — abstract only)*
- Zheng, Fatemi, Jin, Wang, Gandhi, Song, Gu, Srinivasa, Liu, Neubig & Su. *SkillWeaver: Web Agents can
  Self-Improve by Discovering and Honing Skills.* [arXiv:2504.07079](https://arxiv.org/abs/2504.07079)
- Prabhu, Dai, Fernandez, Gu, Ramakrishnan, Luo, Savarese, Xiong, Li, Chen & Xu. *WALT: Web Agents that
  Learn Tools.* Salesforce AI Research. [arXiv:2510.01524](https://arxiv.org/abs/2510.01524)
- Liu, Sra, Inala & Wang. *ReUseIt: Synthesizing Reusable AI Agent Workflows for Web Automation.*
  IUI 2026. [arXiv:2510.14308](https://arxiv.org/abs/2510.14308) ·
  [DOI 10.1145/3742413.3789083](https://doi.org/10.1145/3742413.3789083)
- Guo, Qi, Gu, Cheng & Xiong (Microsoft Research). *Skill-DisCo: Distilling and Compiling Agent Traces
  into Reusable Procedural Skills.* [arXiv:2606.26669](https://arxiv.org/abs/2606.26669) (25 Jun 2026)
- Shao, Yin, Lyu, Yu, Guo, Tsang, Kwok & Li. *Lifting Traces to Logic: Programmatic Skill Induction with
  Neuro-Symbolic Learning for Long-Horizon Agentic Tasks* (NSI).
  [arXiv:2605.01293](https://arxiv.org/abs/2605.01293) (2 May 2026)
- Wang, Wu, Zhang, Zhang, Yao, Faisal, Peng, Qin, Nath, Lin, Bansal, Zhang, Rajmohan, Gao & Yao.
  *WebXSkill: Skill Learning for Autonomous Web Agents.*
  [arXiv:2604.13318v2](https://arxiv.org/abs/2604.13318) (31 Aug 2026)
- He, Cui, Wu, Ma, Lu, Li, Ding & Chowdhury. *Beyond Domains: Reusing Web Skills via Transferable
  Interaction Patterns* (SkillMigrator). [arXiv:2606.17645](https://arxiv.org/abs/2606.17645)
- Hajimiri, Aminbeidokhti, Dolz, Ben Ayed, Laradji, Gella & Gontier. *Are Online Skill and Memory
  Modules Always Worth Their Tokens? A Budget-Constrained Study of Web Agents.*
  [arXiv:2606.15017v2](https://arxiv.org/abs/2606.15017) (30 Aug 2026)
- Zheng, Wang, Wang & An. *Synapse: Trajectory-as-Exemplar Prompting with Memory for Computer Control.*
  ICLR 2024. [arXiv:2306.07863](https://arxiv.org/abs/2306.07863)
- Xu, Lu, Shen, Wang, Wang, Mao, Xiong & Yu. *AgentTrek: Agent Trajectory Synthesis via Guiding Replay
  with Web Tutorials.* ICLR 2025. [arXiv:2412.09605](https://arxiv.org/abs/2412.09605)
- Sun, Cheng, Ding et al. *OS-Genesis: Automating GUI Agent Trajectory Construction via Reverse Task
  Synthesis.* ACL 2025. [arXiv:2412.19723](https://arxiv.org/abs/2412.19723)
- Pahuja, Lu, Rosset, Gou, Mitra, Whitehead, Su & Awadallah. *Explorer: Scaling Exploration-driven Web
  Trajectory Synthesis for Multimodal Web Agents.* [arXiv:2502.11357](https://arxiv.org/abs/2502.11357)

**Slots, grounding, locators, verification**

- Li, He, Zhou, Zhang & Baldridge. *Mapping Natural Language Instructions to Mobile UI Action
  Sequences.* ACL 2020. [arXiv:2005.03776](https://arxiv.org/abs/2005.03776)
- Xu, Masling, Du, Campagna, Heck, Landay & Lam. *Grounding Open-Domain Instructions to Automate Web
  Support Tasks* (RUSS). NAACL 2021. [arXiv:2103.16057](https://arxiv.org/abs/2103.16057) ·
  [ACL Anthology](https://aclanthology.org/2021.naacl-main.80/)
- Deng, Gu, Zheng, Chen, Stevens, Huang, Zhang & Su. *Mind2Web: Towards a Generalist Agent for the Web.*
  NeurIPS 2023. [arXiv:2306.06070](https://arxiv.org/abs/2306.06070)
- Zheng, Gou, Kil, Sun & Su. *GPT-4V(ision) is a Generalist Web Agent, if Grounded* (SeeAct). ICML 2024.
  [arXiv:2401.01614](https://arxiv.org/abs/2401.01614)
- Nass, Alégroth, Feldt, Leotta & Ricca. *Similarity-based web element localization for robust test
  automation* (Similo). TOSEM 2023. [arXiv:2208.00677](https://arxiv.org/abs/2208.00677) ·
  [DOI 10.1145/3571855](https://dl.acm.org/doi/10.1145/3571855)
- Nass, Alégroth & Feldt. *Improving web element localization by using a large language model.*
  STVR 2024. [arXiv:2310.02046](https://arxiv.org/abs/2310.02046)
- Yao, Shinn, Razavi & Narasimhan. *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World
  Domains.* [arXiv:2406.12045](https://arxiv.org/abs/2406.12045)
