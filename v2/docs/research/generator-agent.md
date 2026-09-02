# The generator as an agent — an LLM that emits a typed *generalization plan*, and code that applies it

Research doc for NetGent v2 (UCSB SNL). Written 2026-09-02; revised the same day, after the design shipped
on `v2/closed-loop-rounds` and ran end-to-end (Part D). Research only: no code was changed for this doc.

---

## Summary (10 lines)

1. NetGent's generator is 100 % pure code today, and four measured failures follow from that: a title-keyed
   click that never replays, params only learnable from N runs, a regex-over-prose interrupt classifier, and
   three `press` steps that are really one "fast-forward 30 s".
2. All four are *intent* questions ("position, not title"; "the duration is a parameter"; "this click is an
   ad-skip"; "these three presses are one gesture"). Intent is in the task text and the step reasoning — data
   an LLM reads and a regex cannot.
3. Everyone who solves them uses an LLM. Nobody makes the LLM's answer checkable: Workflow Use has the LLM
   write the workflow; ReUseIt/Magentic-UI have it write prose with `<angle-bracket>` placeholders; AWM has it
   write `{placeholder}` text. None of these artifacts can be type-checked, and none report parameter precision.
4. The systems that verify by **execution** win — ASI's pass rate drops 31.4 % → 15.6 % and it still beats AWM
   by 11.3 pts; WebXSkill's largest ablation is verification. But SkillWeaver's authors document their own gate
   passing code that merely silenced its exceptions, which is exactly NetGent's empty-`accept_states` hole.
5. Proposal: the LLM never writes YAML. It reads the typed trajectory and emits a **patch of typed edits**
   (`locator_intent`, `param_binding`, `fold_repeat`, `role`, `accept`); code applies what it can re-derive.
6. Every edit is *checkable against the recording*: a binding must match a literal actually present in that
   step's field; a positional locator must be a rung of the candidate ladder the browser layer already computed;
   a fold must cover contiguous identical actions.
7. The cheap trick holds: `locator_candidates()` already computes a *ladder* per element and throws all but
   one away, and it does contain a container-relative rung. The LLM's job is **choosing a rung**, not writing
   a selector; code supplies the ordinal (§D.3).
8. Placement: `explore → verify → compile/merge (code) → **generalize (LLM patch)** → apply+validate (code) →
   replay check (the gate)`. Code runs first so the LLM is only asked about what code could not dispose of.
9. On conflict, cross-run evidence beats a single-run reading for *structure*; the LLM wins on
   *locator intent* (the one place the merge is measurably wrong today), and the replay check gates both.
10. **Measured (Part D).** On the Dream Theater task, round 1's replay failed 2 of 3 value sets at `t4` on the
    title-keyed click; triage emitted `positional_target`, the planner hinted `positional`, code applied it to
    the rung `#dismissible > div > div a#video-title` + `nth(0)`, and round 2 passed all three including two
    unseen queries. Still open: no repeat fold fires (triage has no episode for a varying-count gesture), and
    `accept_states` is empty, so the gate checks the state *sequence*, not the goal.

---

## 0. Scope, and what this doc does not repeat

This doc answers one question: **should the step that turns trajectories into a workflow be an agent, and if
so what exactly does it emit?**

It assumes and does not repeat:

- `docs/research/reuseit.md` — ReUseIt (arXiv:2510.14308) read in full, with its four published prompts, the
  70.1 %/50.1 % ablation and the concept map to NetGent. §6.3 there lists seven ideas worth adopting.
- `docs/research/trajectory-memory.md` — the typed-key merge rationale (Part C), the AWM induction prompt
  (§B.2.1), ASI's verification rule (§B.2.4), the PBD lineage and SMARTedit's version-space argument (§B.2.6),
  and the independence policy (§C.4).
- `docs/research/discovery-prior-art.md` — eighteen systems compared, and design recommendations D1–D10;
  D3 ("consolidate by state-keyed graph merge, not by asking an LLM to merge prose") and D6 (the locator
  ladder) are the two this doc revisits with a different answer.
- `docs/research/browser-agent-architectures.md` §3.2/§3.3/§3.5 — Workflow Use's step verifier, Skyvern's
  block vocabulary, Stagehand's cache.

New here: the survey of how each system decides *which literal is a parameter*, the positional-intent problem,
and a concrete typed design for a NetGent generalizer agent.

**Source discipline.** Everything about NetGent is cited by file and line, with the branch named — the code is
spread over three branches and it matters which. Everything external is cited by URL. Claims I could not verify
are in §E.

Branches read (2026-09-02):

| Branch | HEAD | What lives there |
|---|---|---|
| `eugene/v2-scaffold` | `8c7217b` | `generator/compiler.py` (single-run compile, now **including** the media gate and `MediaPlaying`), the schema, `browser/locators.py`, `evals/` |
| `v2/multi-trajectory-parallel` | `a90e675` | `generator/merge.py`, `planner/` variations, the multi-run orchestrator, `agent/replay.py`, `agent/store.py` |
| `v2/closed-loop-rounds` | — | `agent/triage.py`, `agent/generator/hints.py`, `plan_next`, the rounds loop, the M0 ladder on `AgentStep` — **the implementation of Part C**; see Part D |

Every `compiler.py` / `locators.py` / `workflow.py` line number below is against `eugene/v2-scaffold` @
`8c7217b` (`git show HEAD:…`), because the working tree was mid-merge when this was written (§E.2);
`triage.py` / `hints.py` / `planner/models.py` line numbers are against `v2/closed-loop-rounds`.

---

# Part A — the measured problem

## A.1 What the generator is today

**One run → one NFA** (`generator/compiler.py`, `eugene/v2-scaffold`, 287 lines, zero LLM):

- Keeps only successful action steps: `s.action is not None and s.error is None` (L197).
- Each step becomes one `Transition`; the state it lands in is recognized by the query-stripped URL when the
  URL changed (L218), plus — for the *next* step's target — a `selector_visible` carrying that edge's own
  **locator chain** (L224; `_anchor`, L78-97: the chain itself is the condition, so role/name matching,
  `exact`, frame steps and `nth` hold exactly as the action resolves them), plus a `dialog_matches` when the
  step raised a JS dialog (L231).
- Dwells ≥ 3 s become `Repeat` of 1 s `wait` slices so interrupt sweeps run between them (L53-54, L242-245).
- Interruption steps leave the main word and become scoped ε-`Interrupt`s (L260-282), classified by a
  **conjunction of two regexes over prose**: the step's reasoning must match
  `\b(ads?|advert\w+|pop-?ups?|cookies?|consent|banners?|dismiss\w*|no thanks)\b` (L40-43) **and** its target
  selector must match `skip|dismiss|consent|cookie|no.?thanks|close|reject|accept|got.?it` (L48-51). The
  comment at L45-47 records why both are needed: reasoning alone flagged a seek-slider click as an interrupt.
- Parameters are a **caller-declared literal sweep**: `-p name=sample` values are substituted case-insensitively
  (and URL-encoded) into action `text`/`value`/`url` fields and into state condition patterns — and
  **never inside locators** (`_bind_params`, L305-347; the docstring at L192-194 says "never inside locators,
  where substring matches over-abstracted names"). A sample that binds nowhere produces a warning, not a
  failure (L341).

**N runs → one NFA** (`generator/merge.py`, `v2/multi-trajectory-parallel`, 808 lines, zero LLM). The typed-key
merge of `trajectory-memory.md` §C.1:

- Align on `_sig(step) = (action type, durable target key)` with value fields excluded (L134-147), by
  Needleman-Wunsch against the running column list (L198-229), scored by locator *shape* agreement and by
  *URL effect* (L150-195) — both discriminators were added after a real 3-run YouTube merge mis-paired a
  play-button click with video-title links (commit `e8932d9`).
- Conditions by version-space intersection: a trigger survives only if every achieved run witnessed it.
- Four dispositions for divergence (L436-484): **param** (a value that varies and matches a planner-proposed
  value in every run, L268-284), **interrupt** (a dismissal-shaped step present in *k < N* runs, L353-361),
  **branch** (a genuine fork where each continuation's first target distinguishes it, `_try_branch`),
  **reject** (drop the minority step with a warning; keep run 1's version of a full-support column).
- One special case of locator generalization exists: `_generalize_target` (L293-330) rewrites a column whose
  per-run role-*names* each contain that run's param value into `get_by_role(role, name="${param}") + nth(0)`.
  It requires ≥ 2 runs, values ≥ 3 chars, and a single shared role.
- Params are never *invented*: `_confirm_param` only confirms a name the **planner** already proposed
  (`planner/prompt.py::VARIATIONS_SYSTEM`, L18-31) and only when the values actually vary across runs
  (L280-281: "constant across runs: not a parameter, just a value").

**The pipeline** (`agent/orchestrator.py`, same branch): `plan → explore_run ×N (verify per run, one private
retry) → merge → replay`. The replay node (L418-442) is the gate: `agent/replay.py::replay_check` replays the
compiled workflow once per value set and requires the same state signature from each (`state_signature`,
L33-46, excludes interrupt edges and collapses self-loops). This is already ASI's admission rule in miniature
— **the artifact is admitted by executing it, not by a judge's opinion**.

## A.2 The four pain points, with their measurements

### P1 — positional intent compiled as an instance key

The task says *"click the first video result"*. The explorer clicks it; `browser/locators.py::locator_candidates`
(`eugene/v2-scaffold` @ `8c7217b`, L29-73) ranks candidate chains **`#id` → `get_by_role` with a real
accessible name → test-id → label → any css path**, and `unique_locator_for` (L81-108) takes the first unique
one. On YouTube that
is the role+name rung: `get_by_role("link", name="<the video's title>")`. The title is an *instance*; the
intent was a *position*.

Measured, verbatim from commit `e8932d9` (2026-08-31):

> After the fixes the stored 3-run YouTube memory re-merges (offline, zero LLM) to:
> `goto -> fill ${video_query} -> click search -> click video (target-varies, run-1 kept) -> 5s dwell`;
> replay set 1 walks s1..s5 to the real watch page; **set 2 fails honestly at the value-dependent click
> (titles do not contain the query — the known open gap).**

So this is not a hypothesis: it is the current, documented open gap, and it is exactly the class the merge
cannot close. `_generalize_target` only fires when the run values appear *inside* the role names; when the user
asked for position, they never do. The merge's honest fallback is `target-varies → keep run 1's selector`
(L521-526) — a locator that by construction cannot replay for another query.

Why pure code cannot fix it: nothing in the typed trajectory distinguishes "I clicked this because it is first"
from "I clicked this because it is titled X". Both produce the same `ClickAction`. The distinguishing evidence
is the task text and the step's `reasoning` — text.

### P2 — parameters that a human reads off the task, from ONE run

Task: *"search for X, watch 20 s, fast-forward 30 s, pause 10 s"*. Every one of `X`, `20`, `30`, `10` is a
parameter; a person knows this from the sentence alone.

Today two mechanisms exist and neither gets there from one run:

- `compile_trajectory` binds only what the **caller already named** with `-p name=sample`, by literal sweep
  (L244-287). The caller has to know the answer.
- `merge_trajectories` **infers** the binding, but only from *variance across runs*: `_confirm_param` requires
  `len({v.lower() for v in declared.values()}) >= 2` (L280-281). At N=1 the merge degrades to
  `compile_trajectory` with a warning (L384-388: *"only one achieved run: single-run compile; params bound by
  literal sweep, unconfirmed"*).

The planner already proposes names from the task text (`VARIATIONS_SYSTEM`, L18-31, asks for snake_case names
and requires every value to appear verbatim in its variation's `task_text`). What is missing is a step that
*confirms a proposal against one trajectory* instead of against N. A literal sweep can confirm `X` (it was
typed). It cannot confirm `20`/`30`/`10`, because those live in a `WaitAction.seconds` float and in the
*count* of repeated `press` steps — and because a bare `10` matched literally would substitute everywhere
(hence `_MIN_VALUE_LEN = 2`, L56).

### P3 — interrupts classified by regex over prose

`is_interruption_step` (L172-181) is two regexes ANDed. The comments record both failure directions:

- reasoning alone over-fires — *"maybe it restarted after the ad" flagged a seek-slider click as an interrupt
  (v3 run, 2026-08-27)"* (L45-47);
- the word "skip" had to be excluded from the reasoning regex because *"fast-forward reasoning says 'skip ahead
  10 seconds'"* (L37).

`trajectory-memory.md` §C.1.3 already argues cross-run presence is the better signal, and `merge.py` implements
that (`_dismissal_step`, L353-361, relaxes to target **OR** reasoning because the presence gap carries the
other half). That works at N ≥ 2. At N = 1 the classifier is still two regexes over English written by an LLM —
i.e. an LLM already wrote the evidence, and we are parsing it with a regex instead of asking a model to read it.

### P4 — three `press` steps that are one gesture

The explorer is *instructed* to fast-forward one key at a time and to count verified jumps
(`explorer/prompt.py`, `origin/v2-media-observation`, L78-85):

> Seeking / fast-forwarding by N seconds: send the seek key (one press per step) and VERIFY each press landed
> before counting it. … Track the running total of VERIFIED jumps in your reasoning ("jumps so far: 10+10 = 20
> of 30") and keep pressing until it reaches N.

So a "+30 s" fast-forward is recorded as three `PressAction` steps whose `reasoning` literally contains the
running total. The compiler emits three independent transitions. The merge aligns them individually
(`_sig` for press is `("press", keys, locator)` — all three are identical, so alignment across runs is
degenerate) and can never fold them, because folding requires knowing that the *count* is the semantic unit.
`Repeat(count="${param}")` already exists and is already used for dwells (`_make_emit`, L542-556) — the
representation is there; the recognition is not.

The cost of not folding was measured on the same media branch (commit `724cf03`):

> its watch/seek states were anchored on "video element visible", which an ad playing in the same element
> satisfies — so the replay spent its dwells on a Sleep Number ad and **its three +10s seeks no-op'd**, while
> every edge recorded ok.

### A.3 What these four have in common

| | signal that decides it | where that signal lives today | can code read it? |
|---|---|---|---|
| P1 positional vs instance | the task says "first"; the reasoning says "the top result" | `traj.task`, `AgentStep.reasoning` | no |
| P2 param from one run | the task names the value; the step used it | `traj.task`, planner `values`, action fields | partly (literal sweep); not for numbers/counts |
| P3 interrupt vs main | the reasoning explains *why* the click was made | `AgentStep.reasoning` | badly (regex) |
| P4 fold N presses | the reasoning carries the running total and the target | `AgentStep.reasoning`, `AgentStep.media` | no |

Every row's signal is natural language that an LLM produced during exploration and that we currently either
discard or grep. **That is the case for the generator being an agent** — not "LLMs are good at workflows", but
"the deciding evidence is text, and we already have it".

The case *against* letting that agent write the artifact is equally concrete and is the whole of Part B.

---

# Part B — how everyone else turns a recording into a parameterized procedure

All source fetched live 2026-09-02. Commits pinned per section.

## B.0 The one-line answer

Most of the best-known systems in this space **do not bind a single value**. ReUseIt has no parameter
mechanism; Magentic-UI's plan learner never mentions parameters and its `adapt_plan` is dead code; Stagehand
has no inverse (value → placeholder) pass at all; AWM's abstraction is one prompt sentence and its *released*
workflow files contain zero placeholders. Workflow Use does parameterize — mostly with a regex table, while
treating its own LLM's suggestions as advisory. Skyvern parameterizes best of all, and **deleted its LLM
field-namer** to do it. Nobody publishes a precision number for parameter selection; that is stated
affirmatively, with the search that establishes it, in §B.8.2.

## B.1 Workflow Use — the LLM writes the workflow (`browser-use/workflow-use` @ `5d2d19f`, 2026-08-27)

The repo has grown a second front door since `discovery-prior-art.md` §3 was written (@ `891267b`, 2026-07-29):

| path | input | converter | wired to |
|---|---|---|---|
| `workflow_use/builder/` | Chrome-extension recording JSON | LLM (`WORKFLOW_BUILDER_PROMPT_TEMPLATE`, 61 lines) | `cli.py build-workflow` |
| `workflow_use/healing/` | a browser-use `AgentHistoryList` from one live run | LLM (`healing/prompts/workflow_creation_prompt.md`, 241 lines) | `cli.py generate-workflow` |
| `workflow_use/healing/deterministic_converter.py` | same | **zero-LLM** direct action mapping (912 lines) | opt-in |

Everything now runs on `ChatBrowserUse(model='bu-latest')` — browser-use's own gateway; the
`--agent-model`/`--workflow-model` CLI options are accepted, echoed, and ignored (`cli.py` L2306-2308 vs
L2334-2335).

### B.1.1 How the LLM is asked to choose variables

The builder prompt gives almost no guidance — one sentence
(https://raw.githubusercontent.com/browser-use/workflow-use/main/workflows/workflow_use/builder/prompts.py):

```
   - Always aim to include at least one input in "input_schema" unless the workflow is explicitly static
     (e.g., always navigates to a fixed URL with no user-driven variability). Base inputs on the user goal,
     event parameters (e.g., search queries, form inputs), or potential reusable values. For example, if the
     workflow searches for a term, include an input like {"name": "search_term", "type": "string",
     "required": true}.
   - Only use an empty "input_schema" if no dynamic inputs are relevant after careful analysis. Justify this
     choice in the "workflow_analysis".
```

Note the prior: *"always aim to include at least one input"*. That is a bias toward over-parameterizing,
justified by a chain-of-thought field (`workflow_analysis`) that must be emitted **first** — rule 0.

The newer healing prompt carries the real taxonomy, and it is the closest published statement of the
parameter-decision rule
(https://raw.githubusercontent.com/browser-use/workflow-use/main/workflows/workflow_use/healing/prompts/workflow_creation_prompt.md):

```
4. **Variable Identification**:
   - Analyze ALL values entered/selected during the workflow
   - Identify which values are:
     - **SHOULD BE VARIABLES**: User-specific data (names, emails, search terms, dates, amounts, selections)
     - **SHOULD BE HARDCODED**: Navigation targets, UI element labels, constant values
   - For each variable, specify:
     - Variable name (descriptive, snake_case)
     - Type (string/number/bool)
     - Format requirements (if applicable, e.g., "MM/DD/YYYY", "email format")
     - Whether it's required or optional
```

and a category list under the input schema:

```
- Consider these common variable categories:
  - **Personal Information**: Names, emails, phone numbers, addresses
  - **Search/Filter Criteria**: Search terms, date ranges, categories
  - **Form Data**: Any user-entered text, numbers, or selections
  - **Business Data**: Amounts, quantities, IDs, references
  - **Dates/Times**: Any temporal data (specify exact format in "format" field)
```

**The over-parameterization guard is one line: "SHOULD BE HARDCODED: Navigation targets, UI element labels,
constant values."** That is the entire published answer to "don't turn the site name and the Submit button
into parameters."

### B.1.2 Positional intent: the one system that has a field for it

This is the finding most directly relevant to NetGent's P1. `SelectorWorkflowSteps`
(https://raw.githubusercontent.com/browser-use/workflow-use/main/workflows/workflow_use/schema/views.py L30-60)
deprecates CSS/XPath and replaces them with **text plus disambiguation hints**:

```python
	# PRIMARY: Text-based semantic targeting (non-brittle)
	target_text: Optional[str] = Field(
		None,
		description='Visible or accessible text to identify the element. Use hierarchical context for
		disambiguation (e.g., "Submit (in Personal Information)", "Edit (item 2 of 3)"). If None, relies on
		selectorStrategies fallback.',
	)

	# OPTIONAL: Context hints for disambiguation (stored as text, not selectors)
	container_hint: Optional[str] = ...
	position_hint: Optional[str] = ...
	interaction_type: Optional[str] = ...
```

So ordinal intent **is** expressible — as English inside a string (`"Edit (item 2 of 3)"`, `position_hint`)
that a runtime `SemanticWorkflowExecutor` resolves against a refreshed text→element map. And the prompt makes
the key move NetGent's compiler currently forbids: **a variable may appear inside the target**:

```
    - Example (variable in target_text): {"type": "click", "target_text": "{repo_name}",
      "container_hint": "Repositories", "description": "Click repository - works for ANY repo name!"}
    - **PRO TIP**: Using variables in `target_text` allows the same workflow to work with different search
      terms, product names, button labels, etc. WITHOUT needing agent steps!
```

`compile_trajectory`'s docstring says the opposite — *"never inside locators, where substring matches
over-abstracted names"* (`compiler.py` L192-194) — and `merge._generalize_target` (L293-330) is the narrow,
cross-run-evidenced exception. Workflow Use grants the LLM the general power; NetGent grants code the narrow
one. §C proposes the middle: the LLM may request it, code must verify it.

### B.1.3 What validates the LLM's output

- **Structured output, then a hard pydantic validate, then nothing.** `llm.ainvoke(..., output_format=WorkflowDefinitionSchema)`
  → `output_format.model_validate(completion_data)` inside `ChatBrowserUse`
  (https://raw.githubusercontent.com/browser-use/browser-use/main/browser_use/llm/browser_use/chat.py L168-169,
  L246). Retries cover **transport only** (`RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}`,
  `max_retries=5`); a `ValidationError` propagates uncaught. Neither `BuilderService.build_workflow` nor
  `HealingService.create_workflow_definition` re-prompts.
- **One semantic invariant in the schema** — the workflow must end in an extract step
  (`validate_ends_with_extract`, `schema/views.py` L233-249). That is the only structural rule the type system
  enforces.
- **An LLM reviewer, off by default.** `enable_ai_validation: bool = False` (`healing/service.py` L47). When
  on, `WorkflowValidator` returns `WorkflowIssue{severity, step_index, issue_type, description, suggestion}`
  plus an optional `corrected_workflow`, over a fixed taxonomy that includes `agent_step`, `invalid_variable`,
  `hardcoded_value`, `generic_target_text`. Its prompt is a static checklist; it is static review, never replay.
- **A zero-LLM lint that only prints** (`_validate_workflow_quality`, L254-274).
- **No replay test anywhere.** The closest artifact,
  `workflows/examples/scripts/deterministic/run_complete_test.py`, claims in its docstring to test "that it can
  be run" but its pass criterion is structural: `agent_count == 0 and len(semantic_steps) > 0`.
- **CI is lint-only**; the ~20 files under `workflows/tests/` are not run
  (https://raw.githubusercontent.com/browser-use/workflow-use/main/.github/workflows/lint.yml — the test job is
  commented out with *"Tests implementation (disabled for now)"*).

### B.1.4 What replay does with the parameters

`_resolve_placeholders` (`workflow/service.py` L508-523) is **Python `str.format()` with single braces**, and
it swallows misses:

```python
			try:
				# Only attempt to format if placeholder syntax is likely present
				if '{' in data and '}' in data:
					formatted_data = data.format(**self.context)
					return formatted_data
				return data  # No placeholders, return as is
			except KeyError:
				# A key in the placeholder was not found in the context.
				# Return the original string as per previous behavior.
				return data
```

An unbound `{query}` therefore replays as the literal string `{query}`. NetGent's `resolve_params`
(`schema/workflow.py` L176-205) raises `ValueError(f"missing required param {p.name!r}")` instead — the right
call, and worth keeping.

**Deterministic-step failure has no fallback**: `_execute_step` logs *"Attempting fallback with agent"* and
then `raise`s on the next line; the whole `_fallback_to_agent` method (L421-493) is commented out, and the
README's two self-healing items are unchecked roadmap boxes:

```markdown
- [ ] Improve LLM fallback when step fails (currently really bad)
- [ ] Self healing, if it fails automatically agent kicks in and updates the workflow file
```

The real robustness lives in `SemanticWorkflowExecutor` (3229 lines): `max_retries=3`,
`max_global_failures=5`, `max_verification_failures=3`, and each retry **re-resolves the element from a
refreshed text→element map** rather than re-firing the same selector. `enable_step_verification=False` —
*"Disabled by default until fully stable"*.

### B.1.5 The zero-LLM variable pass — and the LLM pass that is only advisory

Two separate parameter mechanisms ship, and **the deterministic one is authoritative while the LLM one is not**:

- `workflow/variable_identifier.py` (default **on**, `enable_pattern_variable_identification=True`) is a
  three-stage regex/keyword classifier with no LLM. Verbatim
  (https://raw.githubusercontent.com/browser-use/workflow-use/main/workflows/workflow_use/workflow/variable_identifier.py L60-118):

```python
	PATTERNS = {
		VariableType.EMAIL: r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
		VariableType.PHONE: r'^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$',
		VariableType.URL: r'^https?://[^\s]+$',
		VariableType.ZIP_CODE: r'^\d{5}(-\d{4})?$',
		VariableType.SSN: r'^\d{3}-?\d{2}-?\d{4}$',
		VariableType.CREDIT_CARD: r'^\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}$',
		VariableType.DATE: r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$|^\d{4}[/-]\d{1,2}[/-]\d{1,2}$',
		VariableType.NUMBER: r'^\d+(\.\d+)?$',
	}
	VARIABLE_KEYWORDS = {'email': …, 'phone': …, 'address': …, 'name': …, 'password': …, 'ssn': …,
	                     'zip': …, 'card': …, 'date': …, 'amount': …, 'quantity': …, 'price': …}
	# Values that should NOT be parameterized (common static values)
	STATIC_VALUES = {'', ' ', 'true', 'false', 'yes', 'no', 'on', 'off', '1', '0', 'submit', 'cancel', 'ok'}
```

- `healing/variable_extractor.py` holds a *second*, LLM prompt with a cleaner taxonomy — and its result is
  thrown away. `healing/service.py` L335-336, verbatim: `# Note: We don't auto-apply these suggestions, just
  log them`.

There is also a human escape hatch: `MANUAL_MARKER_PATTERN = re.compile(r'VAR:([a-z_][a-z0-9_]*):(\S+)')` —
type `VAR:name:value` into a recording and it becomes `{name}` plus an `input_schema` entry.

**Read that ordering carefully.** The team that has shipped this longest trusts a regex table over its own
LLM for the parameter decision, and gates the LLM reviewer off by default. That is a data point *for* the
"LLM proposes, code disposes" split and *against* "LLM writes the artifact" — from inside the project that
does the latter.

### B.1.6 browser-use's `variable_detector.py` — a different signal entirely

Three corrections to the common description of this file
(https://raw.githubusercontent.com/browser-use/browser-use/main/browser_use/agent/variable_detector.py, 276 lines):

1. **There is no LLM and no prompt in it.** `import re` and two model imports; everything else is attribute
   lookups and regexes.
2. **It does not read the task string.** It walks an `AgentHistoryList` *after* a run, and inspects only two
   action parameter fields: `fields_to_check = ['text', 'query']` (L62-63).
3. **It has no notion of secrets.** The `x_…` / `<secret>` sensitive-data machinery is an unconnected
   subsystem in `tools/registry/service.py::_replace_sensitive_data` and `agent/prompts.py`. `variable_detector`
   will happily promote a password-shaped string to a plain `DetectedVariable`.

Its two strategies, in order:

```python
	# Check 'type' attribute first (HTML5 input types)
	input_type = attributes.get('type', '').lower()
	if input_type == 'email':   return ('email', 'email')
	elif input_type == 'tel':   return ('phone', 'phone')
	elif input_type == 'date':  return ('date', 'date')
	elif input_type == 'number':return ('number', 'number')
	elif input_type == 'url':   return ('url', 'url')

	# Combine semantic attributes for keyword matching
	semantic_attrs = [attributes.get('id',''), attributes.get('name',''),
	                  attributes.get('placeholder',''), attributes.get('aria-label','')]
	combined_text = ' '.join(semantic_attrs).lower()
	…
	if 'first' in combined_text and 'name' in combined_text: return ('first_name', None)
```

…then a value-shape fallback (email regex, ≥10 digits → phone, `^\d{4}-\d{2}-\d{2}$` → date, capitalized
letters-only 2–30 chars → name).

**The signal is the element, not the task.** `input[type=email]` is a parameter *because the page says it is
a field for a user-specific value*. NetGent's `DomElement` already carries exactly this — `tag`, `type`,
`role`, `name`, `format`, `required` (`browser/dom/models.py` L31-52) — and the compiler ignores all of it.
That is a free, zero-LLM signal we are not using, and §C.4 folds it in as a *check on* the LLM's proposals
rather than as the proposer.

Reuse is by **exact string replacement over a deep-copied history**
(`agent/service.py::_substitute_variables_in_history`, L4078-4096 → `_substitute_in_dict`, L4140-4160):
`if value in replacements: data[key] = replacements[value]`. There is no templating and no artifact.

## B.2 ReUseIt and Magentic-UI — the LLM writes prose, and neither parameterizes

`docs/research/reuseit.md` covers ReUseIt in full. Three findings from a fresh read of arXiv:2510.14308v2 and
of `microsoft/magentic-ui` change the picture, and one of them is a correction.

### B.2.1 ReUseIt has no parameter mechanism — generalization is bought by sampling

Searching v2 for a parameter formalism returns nothing: no slots, no binding, no substitution. The workflow's
only syntax is the Appendix C.4 output format (`Action:` / `Condition Check:` / `Fallback Action:` lines).
Generalization comes from two other places:

- **Task-variation sampling** — the attribute/category/website taxonomy of Appendix C.1, ×5 runs each
  (≈ 20 runs per family, 15–53 min of synthesis).
- **A prohibition on literals in the *guards* only** — the Important Constraint, quoted in `reuseit.md` §7 #8.

And the *structure* is told to keep literals. The plan-learning prompt ReUseIt borrows says, verbatim:

> Include details about the actions performed, buttons clicked, urls visited if they are useful. For instance,
> if the plan was trying to find the github stars of autogen and arrived at the link
> https://github.com/microsoft/autogen then mention that link. Or if the web surfer clicked a specific button
> to create an issue, mention that button.

So the artifact is **literal-bearing prose with value-agnostic guards bolted on**. The `<departure city>`
angle brackets that appear in the paper's figures are the authors' notation for describing a task family; no
prompt asks for them and nothing resolves them. (`reuseit.md` §3.3 transcribes Figure 7 from the PDF showing
those brackets and already flags this: *"Note what a 'parameter' actually is: an `<angle-bracket>` placeholder
inside prose. Nothing types, validates, or resolves it."* The fresh read confirms the stronger statement:
there is no parameter concept in the system at all.)

**Consequence for us:** ReUseIt's 24.2 % → 70.1 % headline is *not* evidence that LLM parameterization works.
It is evidence that **LLM-written guards** work. The clean number is the guard delta over the bare learned
plan: **48.6 % → 70.1 %**, and the fallback ablation at fixed retry budget, **50.1 % → 70.1 %**.

### B.2.2 The Magentic-UI plan learner has been deleted from `main`

The footnote URL ReUseIt cites —
`https://github.com/microsoft/magentic-ui/blob/main/src/magentic_ui/learning/learner.py` — **returns HTTP 404
as of 2026-09-02**. The full `main` tree at `d3c9d13` (447 entries, untruncated) has no `learning/` package;
`search_code repo:microsoft/magentic-ui learn_plan` returns `total_count: 0`. It was present at tag `v0.1.6`
(2025-11-29) and gone by `v0.2.1` (2026-05-21). `trajectory-memory.md` §A.1 already noted the 404 against
HEAD `d3c9d13`; this pins the removal window.

At `v0.1.6` the mechanism is:

- **The prompt never mentions parameters, variables, placeholders, or generalization.** The word
  "parameterized" appears only in the function docstring — *"use structured outputs to create a draft of
  parameterized plan"* (`learning/learner.py` L32) — and nothing implements it. The only abstraction
  instruction is negative and narrow: *"Again, DO NOT memorize the final answer in the plan."*
- **Schema:** `Plan{task: str|None, steps: Sequence[PlanStep]}`, `PlanStep{title, details, agent_name}`
  (`types.py` L29, L62). No parameters, no conditions. (`SentinelPlanStep.condition` exists for "tell me when"
  monitoring and `learn_plan_from_messages` can never emit it — `response_format=Plan` types `steps` as
  `Sequence[PlanStep]`.)
- **Validation:** `response_format=Plan` (provider structured outputs) → bare `json.loads` →
  `Plan.model_validate`. **No retry, no repair.** By contrast the *live* orchestrator's planner has a
  3-retry loop that feeds the validation error back as a `UserMessage` (`_orchestrator.py` L434-510) — the
  learning path gets none of it.
- **Storage keyed on the raw task string.** The memory controller is configured `generalize_task=False`,
  `revise_generalized_task=False`, `generate_topics=False`, `max_memos_to_retrieve=1`
  (`learning/memory_provider.py` L147-193). AutoGen ships a task-generalization step; Magentic-UI turns it off.
- **Reuse is verbatim re-instantiation.** `retrieve_relevant_plans: Literal["never","hint","reuse"] = "never"`
  (off by default). In `"reuse"`, `self._config.plan = Plan.from_list_of_dicts_or_str(most_relevant_plan)` —
  no LLM re-grounding, no value substitution. `adapt_plan(client, plan, task)` exists, its whole prompt is
  *"Adapt the following plan to the new task."*, and it is **never called**.
- **Human gates:** saving is a manual "Learn Plan" button on the Final Answer block; and with
  `cooperative_planning=True` (default) a recalled plan is shown to the user for edit/accept before execution.

**The lesson for a NetGent generator agent** is the negative space. The two systems most often described as
"an LLM turns a trajectory into a reusable parameterized workflow" do not bind a single value. What they
actually contribute is (a) *guards* and (b) *structure*, and only the guards are measured.

## B.3 Skyvern — the system that moved the parameter decision *away* from the LLM

`Skyvern-AI/skyvern` @ `1126ec9` (HEAD of `main`, 2026-09-02). This is the most instructive section in the
survey, because Skyvern started where the user's proposal starts (an LLM names the parameters) and has since
replaced that with deterministic code, for a documented reason.

### B.3.1 Parameters are typed, and referenced by Jinja2

`ParameterType` distinguishes **where a value comes from**, which is the distinction NetGent's `Param` /
`ParamSource` also draws (`schema/control.py` L79-109):

```python
class ParameterType(StrEnum):
    WORKFLOW = "workflow"          # user input
    CONTEXT = "context"            # wraps another parameter
    AWS_SECRET = "aws_secret"
    BITWARDEN_LOGIN_CREDENTIAL = "bitwarden_login_credential"
    …
    OUTPUT = "output"              # a block's result
    CREDENTIAL = "credential"
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/forge/sdk/workflow/models/parameter.py#L25-L36)

with a value-type sub-tag (`STRING/INTEGER/FLOAT/BOOLEAN/JSON/FILE_URL/CREDENTIAL_ID`, L228-235) and a
`RESERVED_PARAMETER_KEYS` list (`current_item`, `current_index`, `current_date`, `workflow_run_id`, …, L11-22)
that a synthesized name may not claim. Blocks reference them as `{{ param_key }}` through a real sandboxed
Jinja2 (`SandboxedEnvironment`, `StrictUndefined`).

Their human-facing heuristic is one line
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/fern/workflows/what-is-a-parameter.mdx):

```
  * Ask yourself: does this vary run-by-run? If the answer is yes, there might be value in creating a
    parameter for it
```

### B.3.2 The parameter decision is structural; only the *name* is the LLM's

When converting a browser recording into blocks, the branch is on **action kind**, not on the value:

```python
        if action.kind == ActionKind.INPUT_TEXT:
            prompt_name = "recording-action-block-prompt-input-text"
            if (… is_secret_field(…) and action.input_value):
                action = action.model_copy(update={"input_value": ""})
        else:
            prompt_name = "recording-action-block-prompt"
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/services/browser_recording/service.py#L590-L606)

The two prompts differ by exactly one requirement — the input-text one mandates a hole:

```
The templated prompt should have one jinja variable in it. Come up with a good name for the variable that is
lower case, no spaces, underscores permitted.

Example: "Enter {{ address }} into the address field."
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/forge/prompts/skyvern/recording-action-block-prompt-input-text.j2)

**So: a click can never mint a parameter. A fill always does. The LLM's entire contribution is the name.**
There is even a deterministic name fallback that keys on the *field's* identity, never the value:

```python
def deterministic_input_text_parameter_key(action: ActionInputText) -> str:
    target = action.target
    for candidate in (target.id, *(target.texts or []), target.sky_id):
        …
    return "input_value"
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/services/browser_recording/service.py#L187-L196)

and a value-dedup identity that collapses two occurrences into one parameter only if **both** the value and
the field identity match (`code_block_synthesis.py` L1657-1672).

### B.3.3 The LLM field-namer was deleted after a named incident

`generate-workflow-parameters.j2` still exists in the tree and has **zero references** anywhere in the repo.
It was replaced by a three-rule deterministic picker whose module docstring names the bug
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/core/script_generations/deterministic_field_naming.py#L9-L31):

```
The picker implements three rules in priority order for every INPUT_TEXT,
UPLOAD_FILE, and SELECT_OPTION action observed during a workflow run. See
SKY-8965 for the motivating smoke-test repro (phantom
`preprint_search_term` on a single-block search workflow whose navigation
goal embedded the search term as a literal).

Rule precedence:
    1. Jinja-reference rule  — the unrendered `navigation_goal` template
       contains `{{ key }}` where `key` is in the valid-keys set …
    2. Upstream-schema rule  — the action's value equals a literal value
       associated with an upstream block's `data_schema.properties` key.
    3. Intention-derived rule — deterministic snake_case sanitization of
       the action's `intention` text. Last-resort synthesis …
```

Two lines from that file are worth pinning to the wall:

```python
        goal_template: Unrendered `navigation_goal` string for the task this
            action belongs to. Must NOT be the rendered form — otherwise the
            jinja-reference rule cannot tell a real parameter from a literal.
```
```python
    # Rule 1: jinja reference to a declared or schema key.
    # Only fires when exactly ONE valid key is referenced in the goal — otherwise
    # we can't disambiguate which INPUT_TEXT action targets which key and would
    # collapse multiple fields onto the same name (CORR-1 from debate review).
```

and the guard that survives the migration, whose error message is the single best summary of the risk the
user's proposal takes on:

```python
            f"Generated script references undeclared workflow parameters: {invalid_list}. "
            f"Valid keys are: {valid_list}. This usually means the synthesis LLM invented a "
            f"field name for a value that was a literal in the navigation goal. See SKY-8965."
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/core/script_generations/parameter_reference_guard.py#L54-L62)

**This is the counter-argument to "make the generator an agent", stated by the team that tried it.** §C's
answer is not to dismiss it but to adopt its structure: an LLM's parameter claim is admitted only if code can
re-derive it from the recording.

### B.3.4 Value-containment witnesses — the mechanism to steal

Where Skyvern *does* let a value drive a selector, it demands a **witness** that survives recomputation:

```python
class ScoutedInputCorrespondence(TypedDict):
    input_key: str
    matched_literal: str
    parameter_value: str
    surface: str
    transform: str
    position: int
    equivalent_inputs: NotRequired[list[ScoutedEquivalentInput]]
```
```python
    # Grounded value-containment witnesses computed at the update_workflow confluence; drive
    # generator-owned templated locators. Empty/absent => literal replay.
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/forge/sdk/copilot/runtime.py#L242-L249, L296-L298)

Three properties matter:

1. **"Empty/absent ⇒ literal replay."** No witness, no generalization. The conservative default is the
   un-generalized artifact — exactly `merge.py`'s `target-varies → keep run 1's selector`, but with a path to
   *earn* the generalization.
2. **A closed transform set.** Only three value transforms are admissible:
   ```python
   def _witness_observed_forms(value: str) -> list[tuple[str, str]]:
       forms = [("identity", value)]
       iso = _month_name_to_iso(value)                    # "March" -> "03"
       …
       year_month = _iso_date_to_year_month(value)        # "2026-03-14" -> "2026-03"
   ```
   NetGent's equivalent today is `_run_value_forms(value) = (value, quote_plus(value))` (`merge.py` L244-245)
   plus `_number_in` for durations (L248-251). Same idea, one rung shorter.
3. **Self-validation.** `_input_templated_holes_are_self_validating` recomputes every witness from the stored
   `input_key` + `transform` and rejects the hole if the recomputed form is not the recorded `matched_literal`
   (`code_block_synthesis.py` L1027-1040). **A provenance record that cannot be re-derived is discarded.**
   That is precisely the shape §C.4 proposes for `param_bindings`.

Guards on back-substituting a parameter value into recorded prose:

```python
# Minimum length for a parameter value to be eligible for substitution in click prompts.
# Short values (e.g. "1", "No", "CA") cause too many false-positive replacements.
MIN_PARAM_VALUE_LENGTH_FOR_PROMPT_SUB = 4
MAX_PARAM_VALUE_LENGTH_FOR_PROMPT_SUB = 500
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/core/script_generations/generate_script.py#L417-L423)

NetGent has the same constant at a lower value — `_MIN_VALUE_LEN = 2` (`merge.py` L56). Skyvern's independent
arrival at 4, with an explicit false-positive rationale, is a reason to revisit ours.

### B.3.5 Positional intent: Skyvern *forbids* it

This is the sharpest disagreement with the user's `locator_intent: positional(n)` proposal, and it is
deliberate:

```python
_POSITIONAL_RE = re.compile(
    r":nth-of-type\(|:nth-child\(|:nth-last-of-type\(|:nth-last-child\(|>>\s*nth=|:first-child|:last-child"
)
```
```python
def _is_positional_selector(selector: str) -> bool:
    """True when the captured selector's match depends on document position, not element identity.

    Stable anchors (id, [name=...], [data-testid=...], [aria-label=...], a non-indexed CSS path) are
    preferred verbatim; only a positional/index selector is worth trading for an ARIA role/name anchor.
    """
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/forge/sdk/copilot/code_block_synthesis.py#L382-L384, L621-L627)

A positional selector may not be templated, may not anchor a dynamic row, and may not be re-emitted by the
repair path (*"do not re-emit the bare selector or a positional nth selector"*, `copilot/agent.py` L972-977).
What Skyvern emits **instead** for "the row for X" is a value-keyed filter, admitted only under strict
uniqueness:

```python
        return f"page.locator({_py_str(selector)}).filter(has_text={_PERIOD_DATE_PATTERN_HELPER_VAR}({transformed}))"
```
with `row_match_count == 1`, `selected_row_match_count == 1`, and a list of 2–100 rows
(`code_block_synthesis.py` L1069-1089, L901-919). `selected_index` **is** recorded and range-checked — and
used only as provenance. It is never emitted as a locator.

And at the agentic layer, ordinal intent stays prose. Their canonical example:

```yaml
    - block_type: navigation
      label: search_and_open
      navigation_goal: "Search for {{ query }} and click the first result"
      parameter_keys: [query]
```
(https://github.com/Skyvern-AI/skyvern/blob/1126ec96fdadb5e7ff222c9582fa32f9af955cdf/skyvern/forge/prompts/skyvern/workflow_knowledge_base.txt#L149-L164)

**`{{ query }}` is a parameter; "the first result" is a sentence for an LLM to re-read every run.** That is a
coherent design for a product that runs an LLM at replay. It is not available to NetGent.

## B.4 Stagehand — a cache with forward-only variables

`browserbase/stagehand` @ `e2c8946` (HEAD of `main`, 2026-09-02); v4 is current.

- **What is cached is one flat `Action{selector, description, method, arguments}`** — a single selector
  string, in practice an absolute XPath (`packages/protocol/schemas.ts` L1017-1043;
  `packages/extension/services/observeService.ts` L135-140), e.g.
  `xpath=/html[1]/body[1]/shadow-demo[1]//div[1]/button[1]`.
- **Replay is genuinely zero-LLM**: `act()` is overloaded on `string | Action`, and an `Action` short-circuits
  before any snapshot (`actService.ts` L92-102). *"Replays cached actions deterministically — no LLM
  involved. Any failure throws so the cache intercept falls back to the full inference pipeline, which
  doubles as the self-heal path for stale cached selectors."* (L232-245)
- **A stale selector is not detected — it is discovered by failing.** There is no guard, no state condition.
  The docs say it plainly: *"If the page content or structure changes, the action won't get a cache `HIT` and
  Stagehand calls the LLM."* `docs/research/browser-agent-architectures.md` §3.5 already called this out;
  it remains the gap NetGent's state conditions fill.
- **Variables exist, and the artifact stores the placeholder.** `%name%` substitution applies to `arguments`
  **only**, never the instruction (`actService.ts` L473-486). A unit test pins the crucial behaviour: the
  action *executes* with `"user@example.com"` and *records* `arguments: ["%accountEmail%"]`
  (`packages/extension/tests/act.test.ts` L135-157). `observe()` takes a `variables` option whose only effect
  is to expose the names to the model *"so observe() returns %variableName% placeholders in suggested action
  arguments instead of literal values"* (`schemas.ts` L1253-1256).
- **There is no inverse pass.** Nothing scans a recorded value and proposes a placeholder. Pass no
  `variables` and Stagehand records `arguments: ["94105"]` forever. Zero false positives, zero recall.
- **No ordinal concept.** The XPath's `[n]` steps are DOM sibling indices emitted by `nodeToAbsoluteXPath` —
  positional by accident, and nothing distinguishes "this happened to be third" from "I mean the third".
- **Correction to a claim in circulation:** the v3 docs said cache keys are built from variable *keys* not
  values, so two runs with different values share an entry. The v4 docs reverse this — *"Do not assume two
  runs with different values share a cache entry. The variables you pass travel to the cache service with the
  rest of the request, so a different value may produce different key data and miss."*
  (`packages/docs/v4/best-practices/caching.mdx` L412-417).

## B.5 The PBD lineage — where this problem was actually solved

Three decades of programming-by-demonstration answered the two questions in this doc's title with
mechanisms, not prompts. Everything here was read from full PDFs and from shipped source, fetched 2026-09-02.

### B.5.1 CoScripter / Koala — a literal is a parameter iff it is already in the user's dictionary

Koala (CHI 2007, https://acypher.com/Publications/koala-chi07.pdf) records scripts as pseudo-natural-language
and interprets each line as a bag of words scored against annotated page controls. Its parameterization rule
is startlingly simple and is stated in the paper, in IBM's shipped help, and in the extension source:

> During script recording, if the user fills in a form with a value that appears in the database, that step is
> automatically generalized to refer to the named attribute, rather than the current user's literal value.
> For example, a script step might be generalized to: `enter your home street address (e.g., 100 Main Street)
> into the "Address:" textbox`.
> — Koala, CHI 2007

The implementation is a reverse dictionary lookup with **exact, case-sensitive, trimmed** equality:

```js
	// Takes this.literal and tries to find a database key that has it as a value; if so, sets this up as a variable.
	variabilize : function(database) {
		if (this.literal != null) {
			…
			var dbEntry = database.inverseLookupEntry(this.literal);
			if ( dbEntry ) {
				this.dbkey = dbEntry.ident.string;	//e.g. "work email"
```
```js
	// returns the first entry that has the given value (the match must be exact, including capitalization)
	inverseLookupEntry : function(value) { … if (value == entryValue) { return entry } … }
```
(https://raw.githubusercontent.com/jeffnichols-ibm/coscripter-extension/master/platform/modules/coscripter-command.js,
`…/coscripter-database.js`)

**The user's act of putting a value in the personal DB *is* the parameter declaration.** Zero false positives
on values they never registered; zero recall on values they did not. And a missing key is a hard stop, never
a silent fall-back to the author's literal — `hasNeededVars()` → false → the step turns red with
`No 'full name' in your personal DB`. NetGent's `resolve_params` raises on a missing required param; same
discipline.

**Ordinals are first-class in the language, and the recorder is forbidden from inferring one.** The grammar:

```js
new Tokendef(ParserConstants.ORDINAL, /first|second|third|…|[0-9]*[0-9]th/gi),
```
```
click the third button
click the third "Submit" button
click the # your "counter" "Submit" button
```
and the help page: *"CoScripter also understands a few special words, such as "first", "second", "third", and
"thirty-fourth", as referring to the nth such control on the page."*

But the recorder only emits an ordinal **as a disambiguator**, when the label matched more than one element
(`coscripter-command-generator.js`: `if (targetMatches && targetMatches.length > 1) { … ordinal.setVarOrVal(i+1) }`).
And this comment is the single best design rule in the whole survey:

```js
	variabilize : function(database) {
		this.targetLabel.variabilize(database);
		//if (this.ordinal) this.ordinal.variabilize(database); It's a  bad idea to variablilize the ordinal. For instance, if any db entry has a value of 2, "second" will be replaced by a variable
		// It's ok for the user to write a command that uses a variable for the ordinal, but we shouldn't record one.
	},
```

**The authoring grammar may express more than the recorder is allowed to infer.** §C.4 adopts this as a rule:
the `GeneralizationPlan` schema can express positional intent, and code must never *derive* it without an
explicit request plus a resolution check.

### B.5.2 Ringer / Rousillon / Helena — the one-demonstration answer

Sarah Chasins' line (Ringer OOPSLA '16, Rousillon UIST '18, Skip Blocks OOPSLA '17, dissertation
UCB/EECS-2019-139) is the closest prior art to what NetGent is trying to do, and it answers all four of our
pain points with algorithms.

**(a) Selectors: stop synthesizing at record time.** Ringer's reformulation, from the dissertation (Figs.
2.13/2.14, p. 24), is the transferable idea:

```
Classical:     given W and t ∈ W,  synthesize  s . s(W) = t
Reformulated:  given W, t ∈ W, and the replay-time page W',
               synthesize  s . |attr(s(W')) ∩ attr(t)| maximized
```

> The solution was to discard the classical node selector synthesis problem and replace it with a new problem
> formulation, a deferred synthesis approach. … At record time, Helena records all available attributes of the
> target node … The end result is a map from 300 or more attributes to their associated values. At replay time,
> Helena scores all webpage nodes according to how many attributes they have in common with the record-time
> target node.

Two measured results that bear directly on NetGent's locator ladder:

- **Uniform weights beat learned weights.** *"Surprisingly, we found that the algorithm that weighted all
  attributes equally achieved the best performance. This result indicates that past changes to a website are
  not good predictors of future changes and supports our claim that using a fixed set of features is
  fragile."* Day 1: uniform 94 %, SVM 86 %, regression 53 % (Ringer §5.3, §8.4).
- **83 % of nodes still identified after 37 days, +22 pp over the next best approach** (§1.3).

And Ringer names NetGent's P1 exactly, in 2016
(https://schasins.com/assets/papers/ringer.pdf §5.4, p. 755):

> How do the iMacros and ATA-QV node addressing techniques identify the price node? Both techniques first
> filter for nodes with the original node's text, which is the price observed during recording — the stale
> data! If the price has changed, there is no such node, and the tools fail.

**(b) One demonstration is enough, because the *structure* supplies the second example.** Rousillon requires
the user to demonstrate only the first row:

> Our custom relation extractor is closely related to the relation extractors […] with one key difference: it
> is designed to excel in the case of having only one row of data. We found that prior relation extractor
> techniques often required at least two rows of data as input. … The key insight is to fingerprint the
> structure of the input cells' deepest common ancestor (DCA), then find a sibling of the DCA that shares the
> structure fingerprint. … Using the sibling node as a second row of labeled cells, we can apply the same
> techniques that drive prior relation extractors.

**(c) The parameter decision is a value-containment test, done once, at compile time** — and it is the direct
ancestor of what §C proposes:

> We use parameterization-by-value, a metaprogramming technique for turning a term that operates on a concrete
> value into a function that can be called on other values. Essentially, `(pbv term value) → (lambda(x) term′)`
> … We execute parameterization-by-value for DOM nodes, typed strings, and URLs. For each Helena statement in a
> newly inserted loop, we check whether the target node appears in the loop's associated relation. If yes, we
> identify the index i of the target node n in the relation row. We then replace the Helena statement's slice
> of Ringer events E with `(pbv E n)(row[i])` … We repeat this process for typed strings, for each type
> statement in a loop (**checking whether the typed string includes the text of any relation node**), and for
> URLs, for each load statement in the loop.
> — Rousillon UIST '18, §Generalizer/"Parameterization"

Three kinds, three rules:

| kind | parameter iff | bound to |
|---|---|---|
| DOM node | the target node appears in the loop's relation | `row[i]` — **by column index** |
| typed string | the typed string *includes* the text of some relation node | a concat over `row[i]` |
| URL | same containment test | `row[i]` |

Note "includes", not "equals": typing `"Herbert Simon email"` yields `concat(author_name, " email")` — the
WWW '15 predecessor spells this out. And note the endgame: **value-matching happens once, at compile time, to
*detect* the parameter; after that the binding is positional forever (`row[i]`), and the runtime element
lookup is a similarity argmax in which the recorded text carries weight 1 of ~300.**

**(d) The acknowledged cost of one demonstration is ambiguity, and the answer is an editable program:**

> Rousillon uses a single demonstration as input to the PBD process, so inputs can be ambiguous. For instance,
> say a user scrapes a table in which some rows are user-generated posts and some rows are ads. The user may
> want to scrape all rows or only rows that have the same type as the demonstrated row. A single-row
> demonstration is insufficient to distinguish between these two cases. Thus it is critical that users have
> the option to edit output programs.

For NetGent, the equivalent of "an editable program" is the replay check plus the warnings trail — we cannot
ask a user mid-compile, but we can refuse to emit what we cannot verify.

### B.5.3 Version-space algebra (SMARTedit) — the contrast

Covered in `trajectory-memory.md` §B.2.6 and not repeated. The one line that matters here: a version space is
the set of hypotheses consistent with **all** examples, narrowed monotonically; 1–2 demonstrations suffice
under a strong prior; the failure mode is the late anomalous example, and the proposed fix is *active
learning* — ask for the example that would disambiguate, rather than raising N uniformly.

`merge.py` is NetGent's version space. Its hypothesis space is `schema/triggers.py` ∪ the four dispositions.
It is monotone and sound. Its weakness is exactly SMARTedit's: with N = 1 the version space has not been
narrowed at all, so every hypothesis consistent with one run survives, and code has no basis to prefer
"positional" over "title-keyed". **That is the precise hole an LLM can fill — not by being a better
generalizer, but by being a reader of the intent that the demonstration does not encode.**

## B.6 LLM procedure induction — AWM, ASI, SkillWeaver, and the 2026 wave

`trajectory-memory.md` §B.2 covers AWM's induction prompt, ASI's three-check rule and SkillWeaver's honing
loop. What follows is what a fresh read adds, focused on *parameterization* and *what gates admission*.

### B.6.1 AWM — the abstraction instruction is one sentence, and the shipped artifacts have no placeholders

The entire parameterization mechanism is the last sentence of the induction prompt:

```
Each workflow should be a commonly-reused sub-routine of the tasks. Do not generate similar or overlapping
workflows. Each workflow should have at least two steps. Represent the non-fixed elements (input text,
button strings) with descriptive variable names as shown in the example.
```
(https://raw.githubusercontent.com/zorazrw/agent-workflow-memory/main/mind2web/prompt/instruction_abstract.txt)

Four things a fresh read establishes that are worth recording:

1. **There are two prompt variants, and the default is the one WITHOUT the abstraction sentence.**
   `instruction_action.txt` is `instruction_abstract.txt` minus that sentence, and both
   `mind2web/offline_induction.py` and `online_induction.py` default to the `_action` pair.
2. **No code abstracts anything.** The only post-processing is `filter_workflows()` in
   `mind2web/utils/data.py`, which drops blocks mentioning the one-shot's `delta` example. Segmentation of the
   LLM's free text into individual workflows is **splitting on blank lines** — confirmed by the paper: *"These
   workflows are segmented (based on double-line breaks in the model output) and stored separately."*
3. **The placeholder convention is taught only by the one-shot, and it does not hold.** The paper's own
   Appendix A.2 shows induced workflows mixing `{RepositoryName}`, `<forum_link_id>`, `FROM_LOCATION` and bare
   `'main_category_id'` — the last being a *string literal passed to `hover()`*, not a binding. Nothing
   resolves any of them.
4. **The released artifacts contain no placeholders at all.** The five files under `webarena/workflow/` have
   zero `{` characters and all begin with `## Concrete Examples` — they are output of the **rule** path
   (`induce_rule.py`). The neural path writes `workflow/{website}_neural.txt`, which is not in the repo, and
   `mind2web/` ships no induced workflows at all.

And AWM's own ablation says the abstraction barely matters *for them*: on WebArena, rule induction 35.6 SR
vs LM induction 35.5 (LM wins only on steps, 5.9 vs 6.3); on Mind2Web LM wins by 2.8 step-SR, attributed to
"abstract representation of example-specific contexts". Their element ids are stable WebArena a11y ids — as
`trajectory-memory.md` §B.2.1 already notes, *"On live sites it is the whole game."*

AWM also states its own hazard, which is the single strongest argument for a replay gate:

> AWM online induces workflows from model-predicted trajectories that are not always correct, thus can lead to
> incorrect workflows that degrade model performance. — §3.2.2

### B.6.2 ASI — verification is the product, and it rejects most of what the LLM proposes

ASI's admission rule, verbatim (https://arxiv.org/html/2504.06821v2 §2.3):

```
Specifically, we check τ_f from three dimensions:
(1) Correctness: if executing τ_f successfully solves the task q as judged by the neural model evaluator V_L;
(2) Skill Usage: if the trajectory contains at least one call to at least one new skill in D; and
(3) Skill Validity: if all skill-calling actions cause environment changes.
```

It is really implemented, with rollback: `induce_actions.py::write_actions` copies the library to `.tmp`,
appends the new skills, `write_tests` replays each rewritten trajectory in a real browser via
`run_demo.py --headless`, and any failure does `mv tmp back`. Dimension (3) is a **zero-LLM DOM diff** —
`results/calc_valid_steps.py::is_state_change_step` compares `step_info.obs["axtree_txt"]` against the
previous step's. The static pre-check is thin: `ast.parse`, ≥ 2 calls per `def`, name novelty.

The numbers that matter for our design:

| | AWM | ASI |
|---|---|---|
| induction acceptance rate | 31.4 % of turns add a skill | **15.6 %** |
| WebArena SR (Claude 3.5 Sonnet) | 36.3 | **40.4** |
| steps | 5.9 | **5.0** |

Per-site attempted → accepted (Table 8): shopping 21→8, admin 38→15, reddit 24→11, map 13→10, gitlab 25→11 —
**40–75 % of LLM-proposed skills are rejected by an execution test.** And the format-vs-verification ablation
isolates the cause (Table 3, shopping): `(unverified, text) 32.6 → (verified, program) 36.4 → (verified,
text) 39.0`. The paper's reading: *"inducing skills with execution-based verification … improves end success
rate by 4.2 points, indicating the importance of higher-quality induction via verification."*

**Verification, not the program format, is what pays.** That is the empirical licence for §C's design: let the
LLM propose freely, reject most of it in code, and measure the rejection rate as a first-class metric.

One caution worth recording, because it is exactly the failure mode a NetGent generalizer would inherit: ASI's
*published few-shot exemplar* contains three parameterization bugs — `Examples:` passing a list to a
two-positional-arg function, an `Args:` entry (`view_all_id`) that is not in the signature, and a body calling
`page.get_by_label(...)` outside the closed action set the same prompt declares
(https://raw.githubusercontent.com/zorazrw/agent-skill-induction/main/asi/induce/prompt/shopping.md).
Nothing in the pipeline checks docstring↔signature agreement. If the exemplar is wrong, the induced skills
imitate it.

### B.6.3 SkillWeaver — the only published *rules about what a good parameter is*, machine-enforced

This is the closest analogue to what NetGent needs and the best-engineered gate in the survey.

The induction prompt states parameter-quality rules
(https://raw.githubusercontent.com/OSU-NLP-Group/SkillWeaver/main/skillweaver/templates/kb_procedural_update_base.md):

```
- Do not use `dict` as a type for any parameter.
- Avoid using `*_id` or `*_url` parameters, because these are not human-readable. For example:
  - `item_name` is preferred over `item_id`
  …
  - We will check your code for such parameters!
…
- Do not ``overfit" your function name to a specific set of task parameters. Instead, try to generalize your parameters.
…
- Do not overfit to selectors that include numbers in them (e.g. number of notifications, etc. should be replaced by a regex)
```

and — unlike everyone else — **the code actually checks**
(https://raw.githubusercontent.com/OSU-NLP-Group/SkillWeaver/main/skillweaver/knowledge_base/code_verification.py):

```python
    for p in fn.args.args:
        if p.arg.endswith("_id"):
            violations.append(
                f"{fn.name}, argument {p.arg}: Parameter names should not end with `_id`. This is too "
                "'under-the-hood' - prefer to use information that is readily available to the human user."
            )
```

plus: no `try`, no `while`, docstring required, non-empty body, `page.goto(` required, `.locator(`/
`.query_selector(` rejected in favour of accessibility-tree selectors, and a real
`subprocess.run(["pyright", "--outputjson", file])` type check. Parameter types are a closed whitelist that
doubles as JSON-schema generation — `str`, `int`, `float`, `bool`, `list[...]`, nothing else.

The honing loop generates *practice arguments* and executes:

```
You are a 'web agent' who is learning how to use a website. You have an untested automation called {name}
with the signature:
…
Because this is untested, you want to test it right now. Generate some reasonable parameters based on the page.
For example, find_cheapest_flight(page, from: str, to: str) => {{"from": "New York City", "to": "Los Angeles"}}.
```
(https://raw.githubusercontent.com/OSU-NLP-Group/SkillWeaver/main/skillweaver/templates/generate_practice_args.md)

**That is exactly NetGent's `replay_check` with a different value set** — and it is the strongest external
precedent for §C.7's primary metric.

**And the authors say plainly that their own gate is gameable.** This is the most important paragraph in the
survey for our design (https://arxiv.org/html/2504.07079v1, Appendix D.2.1):

> Because our criteria for a function to be "verified" was to have it be called without producing an
> exception, we found that occasionally, malfunctioning APIs could be marked as verified simply because they
> **silenced all exceptions** that could have occurred. This represents a measure for evaluation having
> unintended consequences. … instead of improving the function's signature or adding a check to ensure the
> function was called correctly, the LLM adds "if" statements to simply avoid any of the atomic actions from
> producing an error. While this does reduce the number of exceptions, it does not improve the robustness of
> the API.

§4.3 also names parameter choice as a top-2 *use*-time failure mode — *"We identify two primary categories of
failures: (1) failure to identify the appropriate API and (2) **generating wrong parameters**."* — with a
worked example and no rate.

**NetGent has the same hole today, and Part D measures it.** `Workflow.accept_states` defaults to empty, and
the schema says what empty means: *"Empty = legacy behavior (success = every edge ok)"* (`schema/workflow.py`
L90-91). A replay in which every edge dispatched without error but nothing was achieved is recorded as a
success. That is exactly the SkillWeaver failure mode; commit `724cf03` measured it on YouTube — *"the replay
spent its dwells on a Sleep Number ad and its three +10s seeks no-op'd, **while every edge recorded ok**"* —
and the Dream Theater artifact of §D.4 shipped with `accept_states: []`. §C.4 therefore requires a positive
postcondition on the gate, and §C.7 promotes `accept` out of the deferred milestone.

### B.6.4 Voyager, ICAL — for completeness

- **Voyager** (arXiv:2305.16291): the artifact is a Mineflayer async JS function, and the induced skills are
  **never parameterized**. The prompt mandates it (`voyager/prompts/action_template.txt` L30: *"Write an async
  function taking the bot as the only argument"*), and of the 172 skills shipped under
  `skill_library/trial1/skill/code/`, 15 of 15 sampled take `bot` only — `collectFiveCactusBlocks(bot)`,
  `cookSevenMutton(bot)`, `killFourSheep(bot)`, `smeltFiveRawIron(bot)`. **The quantities are baked into the
  function name and body.** The sharp part: the hand-written primitives Voyager *calls* are parameterized
  (`mineBlock(bot, name, count)`, `craftItem(bot, name, count)`), so the LLM consumes a parameterized API and
  emits a strictly less abstract one. Admission is an LLM critic returning strict JSON, notable because it
  reads **environment state** (inventory, biome, nearby blocks) rather than the agent's narration — the same
  reason NetGent's verifier is fed page evidence and *"never carries the explorer's reasoning"*
  (`verifier/models.py` L33). Removing self-verification costs **−73 % discovered items**, the largest single
  ablation drop in the paper.
- **ICAL** (arXiv:2406.14596v6, latest version 2025-09-18): the artifact is a stored **in-context example** —
  a corrected action sequence plus NL annotations — and it is **not parameterized**; the induced records bind
  literals (`"CounterTop_2"`, `"Mug_1"`) even though ICAL's own *action API* is typed
  (`InteractionObject(object_class, object_instance, parent_object, grounding_phrase)`). Generalization happens
  at retrieval-and-regeneration time (ada-002 + CLIP, top-k = 5), never by argument substitution. Admission =
  execution plus human NL feedback; examples still failing after N feedback rounds are **not stored**. TEACh
  unseen-val 35.8 SR / 54.2 GC vs HELPER's hand-written 34.5 / 36.7 (the "+17.5 %" is 54.2 − 36.7); ablation
  w/o human-in-the-loop 29.9 / 41.0 against 35.1 / 49.3 full. The web-domain abstraction prompt
  (`agent/prompts/prompt_add_knowledge.txt`) is referenced by the code and **absent from the repo** — 404.

### B.6.5 The 2026 wave — one paper is our formalism

Three papers from 2026 bear on this directly. All were fetched live; **none has released code**, so treat
them as design input, not as verified mechanism.

- **Skill-DisCo** (arXiv:2606.26669, 2026-06-25) is NetGent's formalism, arrived at independently:

  > We study this problem in FSM-defined scenarios, where successful traces can be viewed as paths in an
  > unknown transition graph, and formulate procedural skills as reusable **parameterized control-flow
  > subgraphs**. … A PFSM abstracts concrete states and actions into parameterized states and operators, so
  > traces with different objects, states, or lengths can instantiate the same execution pattern. … a skill is
  > not merely a textual routine or an LLM-generated script, but a structurally grounded abstraction of shared
  > execution logic.

  Its synthesis prompt asks for a **typed JSON contract** with `{param}` placeholders inside a
  `canonical_action_sequence` and explicit `preconditions`/`postconditions`/`side_effects` — the closest
  published thing to the `GeneralizationPlan` of §C.3. Verification is on a held-out set (runtime correctness,
  postcondition satisfaction, action savings), with ≤ R re-synthesis retries and then discard. Reported
  skill-call **execution error rate** drops from 75.3 % (ASI-offline) to 0.0 % on ALFWorld and 33.9 % → 21.5 %
  on WebArena, with library size 110 → 5 and 146 → 20. Note the residual: **one in five accepted skill
  invocations still errors on WebArena.**
- **MIND-Skill** (arXiv:2605.08670) is the only system that *optimizes for abstraction level*, with a
  five-axis rubric (GT-Independence, Actionability, Transferability, Completeness, Conciseness) and a
  reconstruction loss (a frozen agent replays the skill; a judge compares against the source trajectory).
  Ablation: removing the rubric loss costs 71.4 → 64.3 on AppWorld Normal.
- **W2S / RWSA** (arXiv:2606.06893) is one of the few to measure the *artifact* directly, by replay-based
  behavioural fidelity against reference skills: **0.503** vs Anthropic Skill Creator's 0.455. Even the winner
  reproduces about half the reference behaviour. (Its linked repo is empty.)
- **WebXSkill** (arXiv:2604.13318v2, `github.com/aiming-lab/WebXSkill`) is the closest published match to
  NetGent's *artifact*: *"executable skills, each pairing a **parameterized action program** with step-level
  natural-language guidance"*, where a skill carries *"name, description, **typed parameters**, and per-step
  guidance"* with `{{param}}` placeholders, indexed in a URL-keyed graph. It is also the only paper that
  **third-party-measures** another system's library (Table 7 — per-skill execution SR / utilization):
  SkillWeaver 84.1 / 8.2, WALT 67.2 / 22.0, WebXSkill 77.1 / 12.9, WebXSkill† 85.0 / 27.8. Its ablation says
  what ASI's does: *w/o skill verification* is the largest single drop (69.5 → **55.2**), ahead of *w/o skill
  graph* (59.1) and *w/o step guidance* (60.4).
- **WALT** (arXiv:2510.01524) generates tools with **validated input schemas** in a demonstrate → generate →
  validate loop, and defines the most directly transferable per-artifact objective in the survey: minimize
  `FailRate(u, I_test) + StepCount(u) + AgenticRatio(u)`, where **AgenticRatio is the fraction of steps
  requiring LLM-dependent reasoning — an explicit determinism term.** NetGent's AgenticRatio is 0 by
  construction; it is worth reporting as such, next to the cost column.
- **SGDR** (arXiv:2606.04391) mines text–code pairs by sliding-window segmentation and draws the distinction
  §C.3 needs: `submit_driving_directions_form(start_field_id, dest_field_id, go_button_id, start_location,
  destination)` separates **structural webpage arguments** from **task-specific content arguments**. Its
  validation is a **counterfactual replay** — substitute the skill call back into the original trajectory,
  re-execute, keep only if still judged successful.

## B.7 The parameter-decision signal table

What each system actually uses to decide "this literal is a parameter". ✓ = primary mechanism; · = present but
secondary; ✗ = not used.

| signal | Workflow&nbsp;Use | browser-use `variable_detector` | Skyvern | Stagehand | ReUseIt / Magentic-UI | AWM | Rousillon/Helena | CoScripter | **NetGent today** |
|---|---|---|---|---|---|---|---|---|---|
| value was **typed into an input** | ✓ (LLM) + · (regex on `value`) | ✓ | **✓ decisive** (`kind == INPUT_TEXT`) | ✗ | ✗ | · | ✓ (`type` statements) | ✓ (`EnterCommand`) | · (sweep hits `text`/`value`) |
| the **element's semantics** (`type=email`, aria-label "phone") | · (`VARIABLE_KEYWORDS`) | **✓ decisive** | · (`is_secret_field`) | ✗ | ✗ | ✗ | ✗ | ✗ | **✗ — available and unused** |
| value appears in the **task text** | · ("base inputs on the user goal") | ✗ | ✓ **as an unrendered `{{key}}` only** | ✗ | ✗ (variations instead) | · (prompt context) | ✗ | ✗ | ✓ via the planner's `values` |
| value **varies across runs** | ✗ (single run) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ (one demo) | ✗ | **✓ decisive** (`_confirm_param`) |
| value matches a **declared parameter** (containment) | ✗ | ✗ | ✓ witnesses + prompt back-substitution | ✗ | ✗ | ✗ | **✓ decisive** (`includes the text of any relation node`) | ✓ exact match vs personal DB | ✓ (`_generalize_target`, role names) |
| value appears in a **URL** | · | · (`URL` regex) | · | ✗ | ✗ | ✗ | ✓ (`load` statements) | ✗ | ✓ (`sub_literal` over `url`, URL-encoded too) |
| value is a **number / duration / date** | · (`DATE`,`NUMBER` regex) | · | ✓ closed transform set (3) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ for `seconds` (`_number_in`) |
| **user-provided vs page-provided** | ✗ | ✗ | ✓ `ParameterType` | ✓ (`variables` are user's) | ✗ | ✗ | ✓ (relation cell = page) | ✓ (personal DB = user) | ✓ `Param.source` (`ParamSource`) |
| **positional** intent ("first") | · prose in `target_text`/`position_hint` | ✗ | **✗ forbidden** | ✗ | ✗ prose | ✗ | ✓ `row[i]` after detection | ✓ ordinal token, **never inferred** | ✗ |
| author **declares** it | ✓ (`VAR:name:value`) | ✗ | ✓ (copilot writes `{{key}}`) | **✓ only mechanism** | ✗ | ✗ | ✗ | **✓ only mechanism** (the DB) | ✓ (`-p name=sample`) |

### How each avoids over-parameterizing

| system | guard |
|---|---|
| Skyvern | (1) structural gate — clicks/hovers/waits can never mint a parameter; (2) Rule 1 reads the **unrendered** goal so a baked-in literal is not mistaken for a parameter; (3) `MIN=4` / `MAX=500` length band, because *"Short values (e.g. `"1"`, `"No"`, `"CA"`) cause too many false-positive replacements"*; (4) declared-key closure with a raising guard; (5) **ambiguity refusal** — Rule 1 fires only when exactly one valid key is referenced. In every case the fallback is "don't parameterize". |
| Workflow Use | one prompt line: *"SHOULD BE HARDCODED: Navigation targets, UI element labels, constant values"*, plus `STATIC_VALUES = {'', ' ', 'true','false','yes','no','on','off','1','0','submit','cancel','ok'}` in the regex pass. |
| CoScripter | the personal DB is the registry — nothing outside it is ever a parameter; **and the ordinal is explicitly excluded from `variabilize`.** |
| Rousillon | the value must be *contained in a relation cell's text* — i.e. it must correspond to page-extracted data, not to an arbitrary literal. |
| SkillWeaver | `_id`/`_url` parameter names rejected in code; closed type whitelist; pyright. |
| Stagehand | nothing is ever parameterized automatically. |
| **NetGent today** | `_MIN_VALUE_LEN = 2`; the name must come from the planner; the values must actually vary; locators are never swept. |

## B.8 Trust and verification — and the number that decides the design

### B.8.1 The ladder, by system

| | schema-constrained output | post-hoc code validation | execution/replay before accepting | LLM judge | human approval |
|---|---|---|---|---|---|
| Workflow Use | ✓ pydantic, **no retry** | ✓ lint that only prints | ✗ | ✓ **off by default** | ✗ |
| ReUseIt | ✗ (prose) | ✗ | ✗ | ✓ at run time, per guard | ✓ (guidance write-back) |
| Magentic-UI | ✓ `response_format=Plan` + `model_validate`, **no retry** | ✗ | ✗ | ✗ | ✓ manual "Learn Plan"; co-planning accept |
| AWM | ✗ (free text, split on blank lines) | · (`filter_workflows`) | ✗ | ✓ AutoEval on the *trajectory* | ✓ only in the rule path (`--auto` bypasses) |
| ASI | ✗ (markdown fences) | · (`ast.parse`, ≥2 calls, name novelty) | **✓ replay + `mv` rollback** | ✓ as check (1) | ✗ (the `input()` result is discarded) |
| SkillWeaver | ✓ typed whitelist → JSON schema | **✓ strongest** (AST rules + naming rules + pyright) | ✓ practice args, live run | ✓ success check | ✗ |
| Voyager | ✓ strict JSON critic | · (errors fed back) | ✓ runs in the env | ✓ critic over **env state** | ✗ |
| Skyvern | ✓ typed params + Jinja closure guard | **✓ deterministic picker + reference guard** | · (cached script is itself a replay) | · | ✓ copilot asks rather than inventing |
| **NetGent (proposed §C)** | ✓ pydantic plan | ✓ every edit re-derived from the recording | **✓ `replay_check` is the gate** | · (verifier stays advisory) | ✗ |

Three mechanisms worth lifting wholesale: **ASI's library rollback** (`cp` → append → replay → `mv` back);
**ASI's zero-LLM state-change check** (`axtree_txt` inequality — NetGent's executor can do this with the DOM
snapshot it already takes); and **SkillWeaver's parameter-name lint**, which is pure code and needs no model.

### B.8.2 Precision numbers for LLM parameter extraction: there are none

I looked for them specifically. **No system in this survey publishes precision, recall, F1, or accuracy for
"did the LLM pick the right parameters / the right abstraction" against a gold standard.** In the AWM and ASI
papers, `precision`, `recall`, ` F1`, `placeholder`, `gold workflow`, `correct parameter` all return zero
hits. Workflow Use publishes **no accuracy number of any kind** anywhere in its repo — only unsourced
cost/latency estimates ("10-30× slower", "$0.10-0.30") and the maturity disclaimer *"this project is in very
early development so we don't recommend using this in production."* ReUseIt reports success rate only, and
has no parameter mechanism to measure.

The zero-hit result was confirmed independently across five papers — AWM, ASI, ICAL v6, SkillWeaver v1 and
Voyager v2 — for `precision`, `recall`, `F1`, `human evaluation`, `annotator` and `abstraction quality`.

What is measured instead: end-task success rate (universal), steps saved, reuse rate, and — the most useful
proxy — **induction acceptance rate**: ASI 15.6 % vs AWM 31.4 %. AWM's own "workflow quality analysis"
(Table 10: ~7.4 workflows/site, function overlap 0.08–0.20, utility rate 0.91–0.94, Mind2Web coverage 0.40)
measures *use*, not correctness.

Six systems measure the **artifact** at all, and every one measures "does it run" or "does it replay", never
"is this the right parameterization":

| system | artifact-level metric | value |
|---|---|---|
| WebXSkill | per-skill execution SR / utilization | 77.1 / 12.9 — and it measures **SkillWeaver at 84.1 / 8.2** |
| Skill-DisCo | skill-call execution error rate | 75.3 % → 0.0 % (ALFWorld); 33.9 % → **21.5 %** (WebArena) |
| W2S | replay fidelity vs reference skills | **0.503** vs 0.455 |
| WALT | `FailRate + StepCount + AgenticRatio` per tool | optimized, not reported as a headline |
| ASI | verification pass rate | **15.6 %** of turns (AWM 31.4 %) |
| ReUseIt | 9-participant comprehension/steerability study | qualitative — the only human evaluation of induced artifacts in this set |

Two consequences. First, **even honed libraries carry roughly one broken entry in five** (WebXSkill's 77–85 %
per-skill SR; Skill-DisCo's 21.5 % residual). Second, the abstraction *boundary* matters more than the code:
Skill-DisCo's A1 ablation (one skill per trace, no cross-trace consolidation) produces a **larger** library
(43 vs 5) and drops SR **99.3 → 53.0**. Over-fragmentation is a worse failure than under-generalization —
an argument for NetGent's merge staying the structural authority (§C.5).

**If NetGent measures parameter precision, it will be reporting a number nobody else has.** That is a
publishable contribution on its own, and §C.8 makes it the eval.

### B.8.3 The finding that settles "who grades the generalization"

arXiv:2605.23899 ("From Raw Experience to Skill Consumption") tests directly whether an LLM can tell a good
induced skill from a bad one, with measured downstream utility Δ as ground truth:

> Without any evaluation criteria, overall LLM selection accuracy is 46.4%, indistinguishable from random.
> … more strikingly, accuracy **decreases** as δ grows. On pairs with δ ≥ 5%, the judge picks the higher-Δ
> skill only **15.8%** of the time, a clear inversion of actual utility. In other words, the skill that reads
> better is often the one that performs worse.
>
> **Finding (Extraction).** Neither skill format nor textual plausibility predicts utility: directly asking an
> LLM to judge the skill text performs no better than chance.

A *validated* rubric — mined from high-gap skill pairs, not written a priori — raises judge accuracy to
73.8 %; a plausibility rubric written a priori **hurts** (−0.59 pp, worse in 6 of 9 cells).

**Design consequence, and it is not optional.** Do not add "an LLM judge of whether the generalization is
good". It is a coin flip in general and *anti-correlated on exactly the cases where the choice matters*. The
grader must be `replay_check`. The verifier stays where it is — advisory, judging whether the *task* was
achieved from page evidence — and never gets a vote on the generalization. This also matches
`trajectory-memory.md` §C.3 rule 6 (*"Never gate admission on the LLM judge alone"*) and AgentRewardBench's
~70 % judge precision.

### B.8.4 One caveat on everybody's headline numbers

arXiv:2606.15017 ("Are Online Skill and Memory Modules Always Worth Their Tokens?") compares AWM, ASI and
ReasoningBank against a **token-matched** vanilla baseline that spends the same budget on extra actor steps:

> Across four WebArena domains and three models … the vanilla baseline matches or surpasses all three
> augmentation methods in aggregate success rate while often using fewer total tokens. … their apparent gains
> often vanish against a budget-matched actor.

Vanilla wins on every model tested (Gemini 3 Flash 44.78 vs AWM 39.34 / ASI 41.02; GPT-5.4-mini 32.67 vs
27.02 / 29.00; Qwen 3.6-27B 42.14 vs 38.01 / 40.15).

This does **not** undercut NetGent — it strengthens the case. Every method that paper penalizes pays its
memory cost *at inference time, every run*. NetGent pays it once, at compile time, and replays at $0. The
right response is to report the cost column, which is the one nobody else prints (`trajectory-memory.md`
§C.6).

---

# Part C — design: NetGent's generalizer agent

## C.0 The contract, in one paragraph

The LLM **never writes the artifact**. After exploration and compilation, it reads the typed trajectory and
the *draft* workflow that pure code already produced, and emits one structured object — a
**`GeneralizationPlan`**: a list of typed *edits* keyed by recorded step. Pure code validates every edit
against the recording, applies the ones that survive, drops the rest with a named warning, and hands the
result to the replay gate. A rejected edit leaves the draft unchanged, so **the worst case of a wrong LLM is
today's output**. Nothing the LLM emits is ever a selector string, a regex, a YAML fragment, or code: the plan
is a set of *choices among options code already computed*.

This is Skyvern's post-SKY-8965 shape (§B.3.3), ASI's admission rule (§B.6.2), CoScripter's recorder/authoring
asymmetry (§B.5.1) and Rousillon's compile-time containment test (§B.5.2), assembled onto NetGent's formalism.

Three rules the survey earns and this design adopts:

1. **No witness, no generalization** (Skyvern, `runtime.py`: *"Empty/absent ⇒ literal replay."*). Every edit
   carries the literal it claims, and code re-derives that literal from the recording or discards the edit.
2. **The recorder may infer less than the language can express** (CoScripter: *"It's ok for the user to write a
   command that uses a variable for the ordinal, but we shouldn't record one."*). Positional intent is
   expressible in the plan and never *derived* by code.
3. **Replay is the grader, never a judge** (ASI; arXiv:2605.23899's 46.4 %/15.8 % result) — **and "every edge
   returned ok" is not a grade.** SkillWeaver's authors document their own gate being satisfied by code that
   merely silenced its exceptions (§B.6.3); NetGent's equivalent is an empty `accept_states`, and Part D
   measures a shipped artifact with exactly that. The gate needs a positive postcondition. The verifier stays
   advisory and gets no vote on the generalization.

## C.1 Where it sits

```
runs = 1:   explore → verify → compile (code) → generalize (LLM) → apply+validate (code) → replay×2 → END
runs = N:   plan → explore ×N → verify ×N → merge (code) → generalize (LLM) → apply+validate → replay×2 → END
```

Two deliberate choices:

- **Code runs first.** The generalizer sees the draft workflow *and the merge's column dispositions*, so at
  N ≥ 2 it is only asked about what code could not dispose of. This keeps the prompt small, keeps the LLM out
  of decisions where cross-run evidence already exists, and makes the edit-acceptance rate interpretable.
- **The replay gate moves to both paths.** Today only the multi-run path has one (`orchestrator.py` L418-442).
  The single-run path must get it too, because at N = 1 replay is the *only* verifier of an LLM binding
  (§C.5). This is the one non-trivial orchestrator change.

`generalize` is one node in the existing `StateGraph`, one LLM call, structured output through the `LLM`
protocol in `agent/llm.py` — same seam as the planner and verifier. It imports nothing new.

## C.2 Inputs

| input | source | why the LLM needs it |
|---|---|---|
| task text | `traj.task` / `req.task` | "the first video result", "watch 20 s" — the intent is only here |
| planner values | `VariationPlan.variations[i].values` (N > 1) | proposed names to confirm rather than invent |
| per-step record | `AgentStep` | action type, the resolved action's value fields, `url`, `dialogs`, `error` |
| per-step **reasoning** | `AgentStep.reasoning` + `evaluation`/`memory`/`next_goal` | P3 and P4 live here ("jumps so far: 10+10 = 20 of 30") |
| per-step **media** | `AgentStep.media`, `AgentStep.t` (media branch) | distinguishes an ad from the content; witnesses a `media_playing` accept |
| page texts | `traj.texts_seen`, `traj.final_observation` | tells a *page-provided* value from a *user-provided* one |
| **locator candidate ladder** | ⚠️ **not recorded today** | the whole positional mechanism (§C.2.1) |
| the draft workflow | `compile_trajectory` / `merge_trajectories` output | so edits reference real transitions |
| merge column report | `GeneralizedTrajectory.columns` (N > 1) | tells the LLM which columns code already settled |
| verifier verdict | `Verdict{achieved, unmet, evidence}` | a "not achieved" run should not be generalized at all |

### C.2.1 The prerequisite: record the candidate ladder

`browser/locators.py::locator_candidates(el)` (`eugene/v2-scaffold` @ `8c7217b`, L29-73) already returns
**every durable chain for an element, most durable first** — `#id` → `get_by_role(role, name=…)` → test-id →
label → *any css path*. `unique_locator_for` (L81-108) picks the first that resolves uniquely and, when
everything is ambiguous, appends `nth(match_index)` chosen by bounding box. `capture_locator` (L111-144)
cross-checks against Playwright's own generator. (`is_volatile_selector` / `_VOLATILE_ID`, L17-26, keep
machine-generated ids off the ladder — a per-mount `#skip-button\:2` could never match a future overlay.)

**Then the alternatives were thrown away** — `AgentStep` kept only the chosen `action` and a prose
`locator_check` note. **This shipped** on `v2/closed-loop-rounds` as `locator_candidates`, `candidate_kinds`
and `element` (`explorer/models.py` L83-89); §D.3 reports what the ladder turned out to contain.

That css rung is the structure-keyed locator — on a results list it is something like
`ytd-video-renderer:nth-of-type(1) a#video-title`, which encodes *position*, while the role rung encodes the
*title*. **Both already exist at capture time. The generalizer's job on P1 is to pick the other rung.** That
reframes the hardest part of the design from "the LLM writes a robust selector" (which Skyvern rejects, §B.3.5,
and Ringer's data says is fragile, §B.5.2) into "the LLM chooses among chains code computed and verified" —
a bounded, checkable choice.

So, three fields on `AgentStep`, all populated by the browser layer, all compile-time provenance:

```python
    locator_candidates: list[Locator] = []   # the ladder from locator_candidates(el), in durability order
    candidate_kinds: list[str] = []          # id | role | test_id | label | css | structural, per rung
    element: dict = {}                       # tag, type, role, name, format, required, frame_path — from DomElement
```

`candidate_kinds` is what makes a positional edit checkable **offline, with no browser**: a rung tagged
`structural` is a container-relative path, which is a legitimate positional anchor once code appends the
ordinal. (§C.4 V5 as first drafted asked for a `match_counts` list instead — how many elements each rung
resolved to at capture time. The shipped design uses the kind tag; see §E.4.)

`element` also unlocks a zero-LLM signal we are not using: browser-use decides a value is a parameter from
`input[type=email]` and from `aria-label` keywords (§B.1.6), and NetGent's `DomElement` carries `tag`, `type`,
`role`, `name`, `format`, `required` (`browser/dom/models.py` L31-52). This becomes a *check on* the LLM's
`kind: user` claim, not a proposer.

## C.3 The output schema — `GeneralizationPlan`

A patch, not a workflow. Sketch (final field names are an implementation detail; the shape is the design):

```python
StepId = str  # "n.item", the AgentStep's own coordinates — stable, and maps 1:1 to a draft transition

class StepRole(BaseModel):
    step: StepId
    role: Literal["main", "interrupt", "noise"]
    why: str                      # one clause of evidence from the task or the step's reasoning

class ParamBinding(BaseModel):
    step: StepId
    field: Literal["text", "value", "url", "seconds"]   # NEVER a locator; see LocatorIntent
    name: str                     # snake_case; ^[a-z][a-z0-9_]*$
    kind: Literal["user", "page"] # user = supplied by the caller; page = extracted at run time (ParamSource)
    literal: str                  # the EXACT substring of that field this binding claims
    alt_value: str                # a second plausible value, for the replay gate only — never stored
    why: str

class LocatorIntent(BaseModel):
    step: StepId
    kind: Literal["instance", "positional", "text_param"]
    candidate: int | None = None  # index into AgentStep.locator_candidates — the rung to use
    index: int | None = None      # the ordinal, for kind="positional"
    param: str | None = None      # for kind="text_param": the param whose value the name must contain
    why: str

class RepeatFold(BaseModel):
    steps: list[StepId]           # ≥2, contiguous, identical action signature
    name: str | None = None       # the param carrying the iteration count
    per_iteration: str = ""       # "+10 s per press" — description only, never replayed
    alt_count: int | None = None  # for the replay gate
    why: str

class Expectation(BaseModel):
    trigger: Trigger              # the EXISTING discriminated union — no new vocabulary
    why: str

class GeneralizationPlan(BaseModel):
    roles: list[StepRole] = []
    params: list[ParamBinding] = []
    locators: list[LocatorIntent] = []
    repeats: list[RepeatFold] = []
    accept: list[Expectation] = []
    notes: list[str] = []         # what it considered and rejected — for the evidence trail
```

Design notes:

- **`literal` is the contract.** It is what makes a binding falsifiable, and it is the direct analogue of
  Skyvern's `ScoutedInputCorrespondence.matched_literal` and of Rousillon's containment test. A binding
  without a re-derivable literal is not a proposal, it is a hallucination.
- **`alt_value` / `alt_count` are the practice arguments.** SkillWeaver's `generate_practice_args.md` asks the
  model for plausible test values for exactly this reason (§B.6.3). They never enter the artifact; they exist
  so the replay gate has a *different* value to try at N = 1.
- **`kind` is `user | page`, not `user | page | positional`.** Positional intent is not a value binding — it
  belongs to the locator, and conflating them is how "first" would become a `${param}` that substitutes a
  literal `1` into an action field. This is CoScripter's ordinal exclusion, in the type system.
- **`accept` reuses `Trigger` verbatim.** The LLM may not invent a condition vocabulary; it may only select
  from `url_matches | title_contains | selector_visible | selector_hidden | dialog_matches | media_playing`.
- **`why` on every edit.** Not decoration: it is the warnings trail when an edit is rejected, and the material
  for the validated rubric that §B.8.3 says is the only kind of judge that helps.
- **What is deliberately absent:** no free-text selector, no regex, no `max_iterations`, no `scope`, no state
  ids, no transition ids, no timeouts. Every one of those is computed by code from the recording.

## C.4 How code validates and applies it

Ten rules. Each rejection appends a warning naming the edit and its `why`; **no rejection fails the compile.**

| # | rule | precedent |
|---|---|---|
| **V1** | *Literal witness.* For each `ParamBinding`, `literal` must be recoverable from the named field of the named step's recorded action under a **closed** set of forms: `identity`, `quote_plus`, and — for `seconds` — `_number_in` numeric equality. Anything else is rejected. | Skyvern `_input_templated_holes_are_self_validating`; Rousillon "includes the text of any relation node" |
| **V2** | *Provenance.* `kind: user` requires the literal (or its number) to appear in the task text or in a planner `value`. `kind: page` requires it to appear in `texts_seen`/the step observation **and not** in the task, and it must compile to a **dynamic** `Param` with a `ParamSource`, never a static one. A `kind: user` claim on a value the page supplied is downgraded to `page` with a warning. | Skyvern `ParameterType`; NetGent `ParamSource` already exists |
| **V3** | *Shape band.* Reject a string literal shorter than **3** characters or longer than 500, or in a stop-list (`submit`, `search`, `ok`, `yes`, `no`, `next`, `continue`, `login`, the page's own button labels from `element.name`, the site host). Numeric `seconds` bindings are exempt — they compare, not substitute. | Skyvern `MIN=4`/`MAX=500` *"Short values … cause too many false-positive replacements"*; Workflow Use `STATIC_VALUES`; NetGent's `_MIN_VALUE_LEN=2` is too low |
| **V4** | *Locators are never swept.* The literal sweep still touches only action value fields and state condition patterns. A `${param}` reaches a locator **only** through `LocatorIntent(kind="text_param")`. | `compiler.py` L192-194, unchanged |
| **V5** | *Locator resolution.* `instance` → no-op. `positional` → `candidate` must index the recorded ladder and that rung must be container-relative (`candidate_kinds[candidate] == "structural"` in the shipped design; this rule was first drafted against a `match_counts` list that was not built — §E.4). `text_param` → the recorded `get_by_role` name must contain the param's literal case-insensitively, and the emitted chain is `[…frames…, get_by_role(role, name="${p}"), nth(0)]`. Any check that fails → keep the recorded chain. **All three checks run against recorded data; no browser.** | `merge._generalize_target` L293-330 generalized to N=1; CoScripter's ordinal-as-disambiguator |
| **V6** | *Role edits.* `noise` is refused for a step whose action changed the base URL, and for the last step. `interrupt` requires `action.type == "click"` **and** an expressible target selector; code then builds the anchor state (`selector_visible`), the done state (`selector_hidden`), the resolve edge and the `scope` from the base URL, and sets `max_fires = 3`. | `compiler.py` L260-282 unchanged; the LLM supplies only the classification |
| **V7** | *Repeat folds.* `steps` must be contiguous in the trajectory, all with the same `_sig`, length ≥ 2. If `name` is set, the param's default is the **iteration count**, and `per_iteration` is recorded in `Param.description` (see the open question below). `max_iterations` is set by code to `max(3 × count, 10)`. | `merge._make_emit` dwell path L542-556 |
| **V8** | *Accept must be witnessed.* `url_matches` must match the recorded final URL; `selector_visible`/`selector_hidden` must name a selector present in the final observation; `title_contains` must be a substring of the observed title; `media_playing` requires a matching final `media` reading. Unwitnessed → dropped. | Voyager's env-state critic; NetGent's `MediaPlaying` gate |
| **V9** | *Param closure.* Every `${name}` reaching the artifact must have a `Param`; every `Param` must be referenced by ≥1 action or condition. Violations are **errors**, not warnings — the plan is re-applied without the offending binding. | Skyvern's `parameter_reference_guard`; NetGent's "never bound" warning promoted |
| **V10** | *No schema escape.* Edits may reference only existing step ids; names must match `^[a-z][a-z0-9_]*$` and avoid a reserved set; nothing in the plan is ever interpolated into a selector, a regex, or executed. Selectors come only from the recorded ladder; the resulting `Workflow` is re-validated by pydantic (`validate_locator_chain`, `_validate_graph`). | Skyvern `RESERVED_PARAMETER_KEYS`; `schema/actions.py` L15-86 |

**Then the gate.** `replay_check` runs the workflow twice: once with the defaults, once with every param set
to its `alt_value` (and every folded repeat to its `alt_count`). Both must succeed *and* produce the same state
signature — `state_signature` already excludes interrupt edges and collapses self-loop repeats, so a different
dwell length is not a difference (`replay.py` L33-46). A failure is reported honestly and the artifact is
marked not-validated; it does **not** silently fall back.

**V11 — the gate needs a positive postcondition.** `Workflow.accept_states` defaults to empty, and empty means
*"success = every edge ok"* (`schema/workflow.py` L90-91). That is the oracle SkillWeaver's authors document
being gamed (§B.6.3), the one commit `724cf03` measured failing on YouTube, and the one the Dream Theater
artifact shipped with (§D.4). So: **a generalized workflow with no `accept_states` does not pass the gate.** At
least one witnessed `Expectation` must survive V8 and become an accept state, or the compile reports
`not-validated (no postcondition)`. This is ASI's "Skill Validity" DOM-diff, ReUseIt's execution guards and
Skill-DisCo's postcondition satisfaction converging on one answer — and NetGent already has the primitive in
`browser/triggers.py`, so it costs nothing and stays zero-LLM at replay.

## C.5 Composition with the multi-run merge

The merge runs first and its report is an *input*. Precedence, by column disposition:

| merge disposition | who wins | rationale |
|---|---|---|
| `aligned` (code had no opinion) | **LLM** may add `role`, `repeat`, `locator_intent` | nothing to conflict with |
| `param` (values varied AND matched a planner value) | **merge** — given to the LLM as a fact, not re-decidable | N runs of evidence beats one reading |
| `param-target` (`_generalize_target` fired) | **merge** | cross-run evidence that the *name tracks the value* is strictly better than a single-run guess at position |
| `value-diverges` (values vary, no name matched) | **LLM supplies the name**, merge keeps the variance evidence | the merge had the evidence and lacked only a name — exactly the LLM's job |
| **`target-varies`** (targets differ, kept run 1's) | **LLM** | the one column class where code is *measurably wrong today* (commit `e8932d9`: *"replay set 2 fails honestly at the value-dependent click … the known open gap"*) |
| `interrupt` | **union** | ε-interrupts are off the main word by construction; a false positive costs a bounded sweep, not a broken replay |
| `dropped` (minority step, structural intersection) | **merge** — an LLM `role: main` on a dropped column is refused | measured: keeping run-1-only steps made replay time out (`e8932d9`) |
| `branch` | **merge** — the LLM may not create or dissolve a `Branch` | presence-based forks need cross-run presence, which one run cannot supply |

**The merge as verifier of the LLM's bindings.** At N ≥ 2, an LLM `ParamBinding` on a column whose values did
**not** vary is dropped with a warning: we have the evidence and the LLM's reading lost (`_confirm_param`
L280-281: *"constant across runs: not a parameter, just a value"*). So at N ≥ 2 the LLM adds coverage almost
entirely on **locators, folds and roles** — the three places code has no evidence — and adds nothing on value
params, which is exactly right, because that is where code is already correct.

**At N = 1 there is no merge evidence, so the replay gate is the only verifier.** That is why `alt_value` is
mandatory on every binding. It is also why the single-run path needs the replay node.

Ordering alternative considered and rejected: *LLM first, on the raw run-1 trajectory, then merge verifies.*
It costs a bigger prompt, makes the edit-acceptance rate uninterpretable (the merge would silently overrule
most edits), and gains nothing — the planner already proposes params from the task text before any run
(`VARIATIONS_SYSTEM`), so there is no bootstrapping need. Keep **planner = params from intent, before the runs;
generalizer = params, positions and folds from behaviour, after them.**

## C.6 The YouTube example, walked through

Task: *"search YouTube for lofi hip hop, watch 20 s, fast-forward 30 s, pause 10 s"*. Trajectory (the real
shape, from the runs behind `e8932d9` and `724cf03`):

```
 1 goto  https://www.youtube.com
 2 click get_by_role("button", name="Accept all")     "dismiss the cookie consent so the page is usable"
 3 fill  #search-input           "lofi hip hop"        "type the query the task gave"
 4 press Enter                                        "submit the search"
 5 click get_by_role("link", name="lofi hip hop radio — beats to relax/study to")
                                                      "open the first video result"
 6 click locator(".ytp-ad-skip-button")               "an ad is playing; skip it — it doesn't count as watch time"
 7 wait  20 s                                         "watch for the required 20 seconds"
 8 press "l"                                          "seek +10 s; jumps so far: 10 of 30"
 9 press "l"                                          "jumps so far: 10+10 = 20 of 30"
10 press "l"                                          "jumps so far: 10+10+10 = 30 of 30"
11 press "k"                                          "pause the video"
12 wait  10 s                                         "hold paused for 10 seconds"
```

**Today's compile:** 10 main transitions (2 and 6 become ε-interrupts *if* both regexes fire); step 5's locator
is the title; steps 7 and 12 become `Repeat`s of 1 s slices with **fixed** counts 20 and 10; steps 8-10 are
three separate transitions. Replay with a different query fails at step 5 — measured.

**The plan the generalizer would emit:**

```yaml
roles:
  - step: "2.0"  role: interrupt   why: "a cookie consent wall; the task never mentions it"
  - step: "6.0"  role: interrupt   why: "reasoning says an ad is playing and must be skipped — conditional, not part of the flow"
params:
  - step: "3.0"  field: text     name: video_query  kind: user  literal: "lofi hip hop"
                 alt_value: "jazz piano"   why: "the task names it as the thing to search for"
  - step: "7.0"  field: seconds  name: watch_time   kind: user  literal: "20"
                 alt_value: "8"            why: "task: 'watch 20 s'"
  - step: "12.0" field: seconds  name: pause_time   kind: user  literal: "10"
                 alt_value: "4"            why: "task: 'pause 10 s'"
locators:
  - step: "5.0"  kind: positional  candidate: 2  index: 0
                 why: "the task says 'the first video result'; the recorded name is this run's title, not the intent"
repeats:
  - steps: ["8.0","9.0","10.0"]  name: fast_forward_presses  per_iteration: "each press seeks +10 s"
                 alt_count: 2    why: "the reasoning counts 10+10+10 = 30 of 30; the task asks for a 30 s fast-forward"
accept:
  - trigger: {type: media_playing, playing: false}
                 why: "the task ends with the video paused"
```

**What the validator does with it, edit by edit:**

- **roles.** Step 2 is a click whose selector matches `accept`; step 6's matches `skip`. V6 passes for both;
  code builds `Interrupt(state=i1, resolve=[ti1], scope=[states on youtube.com], max_fires=3)` exactly as
  `compiler.py` L260-282. Both would also have fired today's regexes — the LLM agrees with code here, which is
  the boring, good case. The value is that it no longer *depends* on the regex: the "skip ahead 10 seconds"
  collision that forced `skip` out of `_INTERRUPTION_RE` (L37) stops being a problem, because steps 8-10 are
  classified `main` on their reasoning, not on a keyword.
- **`video_query`.** V1: `"lofi hip hop"` is `FillAction.text` verbatim ✓. V2: it appears in the task ✓ →
  `kind: user`, static `Param`. V3: 12 chars, not in the stop-list ✓. Applied by the existing literal sweep —
  which also rewrites the `url_matches` pattern of the results state, since `quote_plus` is already one of the
  swept forms (`_bind_params` L248-256).
- **`watch_time` / `pause_time`.** V1 on `seconds`: `_number_in("20") == 20.0 == action.seconds` ✓. Compiled by
  the existing dwell path to `Repeat(count="${watch_time}", max_iterations=60)` of 1 s slices — the machinery
  `merge._make_emit` L542-556 already has, now reachable from one run.
- **`locators[0]` — the load-bearing edit.** Candidate 2 must be a rung of step 5's recorded ladder. On a
  results list that rung is the css path (`locator_candidates` step 5, *"any css path"*, `locators.py`
  L67-70) — structure-keyed, not title-keyed. Code checks the rung exists and is container-relative, then
  appends `nth(index)`. **If the check fails the edit is dropped and run 1's selector is kept — i.e. exactly
  today's artifact, plus a warning naming why.** That degradation property is the reason this design is safe
  to ship. **Measured (§D.2): the rung is `#dismissible > div > div a#video-title`, and code applied it with
  `nth(0)`** — so the ordinal comes from code, not from the ladder, which is a narrower claim than this
  section originally made.
- **`repeats[0]`.** V7: steps 8-10 are contiguous, share `_sig = ("press", "l", <chain>)`, count 3 ✓. Compiled
  to one transition plus `Repeat(body=[that edge], count="${fast_forward_presses}", max_iterations=9)`, with
  `Param(name="fast_forward_presses", default="3", description="each press seeks +10 s (task: 30 s)")`.
  Steps 11 and 12 follow unchanged.
- **`accept[0]`.** V8: witnessed only if step 12's `media` reading says PAUSED. On the media branch it does;
  without that branch the edit is dropped. Applied, it sets `accept_states` on the final state — which is what
  makes "the run ended paused" a checkable success condition rather than "every edge returned ok".

**The gate.** Value set A = `{video_query: "lofi hip hop", watch_time: "20", pause_time: "10",
fast_forward_presses: "3"}`. Value set B = `{"jazz piano", "8", "4", "2"}`. Both must succeed with the same
state signature; the collapsed self-loops mean the different dwell lengths and the different press count do
not change it (`replay.py` L43-45). **Set B is exactly the replay that fails today.** If it passes, P1, P2 and
P4 are closed on this family; if it fails, the failure names the edge.

## C.7 What to build first, and how to measure

### Build order

| # | milestone | LLM? | what it proves |
|---|---|---|---|
| **M0** | Record `locator_candidates`, `match_counts` and `element` on `AgentStep` (§C.2.1) | **no** | Falsifiable in a day: does a *structure-keyed* rung actually exist in the ladder for the YouTube video click? If not, nothing downstream is buildable and the fix is in `locator_candidates`, not in a prompt. **Do this first, alone.** |
| **M1** | `GeneralizationPlan` schema + validator + applier, exercised by a hand-written plan fixture against the stored 3-run YouTube bundle | **no** | The apply path is sound. Gate: applying an **empty** plan must produce a byte-identical workflow to today's. `merge_trajectories` already re-merges stored trajectories offline with zero LLM, so this whole milestone runs with no browser and no model. |
| **M2** | The `generalize` node: one LLM call, structured output, four edit kinds — `locators`, `params`, `repeats`, **`accept`** | yes | The measurable hypothesis. `accept` is *not* deferred: without a witnessed postcondition the gate is the known-broken "every edge ok" oracle (V11), which Part D measures shipping. `roles` is deferred — the merge and the regexes already handle interrupts acceptably. |
| **M3** | Replay gate on the single-run path, driven by `alt_value`, requiring a non-empty `accept_states` | no | Closes the N=1 verification hole **and** the vacuous-success hole |
| **M4** | `roles` edits | yes | Only after M2's acceptance rate is understood |

**Status as of 2026-09-02:** M0, M1 and a rounds-shaped M2 have shipped on `v2/closed-loop-rounds` and been
run end-to-end; M3 has not. See Part D for what each milestone actually produced and what it did not.

### Metrics

1. **Metamorphic replay (primary).** A workflow compiled from the YouTube family must replay with a
   *different query* **and** a *different duration*, reach a witnessed accept state, and produce the same
   state signature. Baseline before the closed loop: **fails** — measured in `e8932d9`, and again in round 1
   of §D.2. Report `pass^k` over k replays, the retention metric of `trajectory-memory.md` §C.6, and report
   **vacuous passes separately**: runs where every edge returned ok but no accept state held. That count is
   unmeasurable today because `accept_states` is empty; making it measurable is M3.
2. **False-param rate on the 21-form sweep (the negative control).** `netgent eval stress sweep` walks 21
   forms with the task *"Fill in THIS form completely with plausible values and submit it"*
   (`evals/sweep.py::FORM_TASK`). **No value in that task comes from the user** — the agent invents them all —
   so the correct number of parameters is ~zero. Every param the generalizer proposes there is a false
   positive, and `false-param rate = proposed / 21` is a clean, cheap precision measurement.
   This is the number §B.8.2 says nobody publishes.
3. **Recall, on a small positive control.** 10–20 hand-labelled tasks with known parameters (the YouTube
   family, a search-and-filter family, a login family, a date-form family). Report precision and recall per
   `kind` (`user` vs `page`) with honest error bars. Together with (2) this is the first published
   precision/recall for LLM parameter selection in web-workflow induction.
4. **Edit acceptance rate, per edit kind.** The fraction of proposed edits that survive V1-V10. ASI's 15.6 %
   is the comparison point. Near 100 % means the validator is too weak; near 0 % means the prompt or the
   inputs are wrong. This number is the health check on the whole design and costs nothing to collect.
5. **Regression: the known-broken fixtures must still be rejected.** The generalizer must not paper over a
   genuinely broken workflow by relaxing a locator until it matches *something*. (See §E.1 — I could not locate
   these fixtures in the tree; if they are informal, M1 should make them formal, as two committed trajectory
   bundles whose compile must not pass the gate.)
6. **Cost.** One LLM call per compile; report tokens and dollars alongside the existing explore/verify usage
   line (`orchestrator.py` L147-153), and **$0 at replay** — the column §B.8.4 says nobody else prints.
7. **Offline ablation.** Apply-plan vs empty-plan over the stored bundles in `<name>.trajectories/`. Zero
   browser, zero model (plans cached from M2 runs), fully repeatable — which makes this the eval that can run
   in CI as a fixture test rather than as a flaky live-site eval.

## C.8 The three designs, compared

| | **LLM writes the workflow** (Workflow Use, Magentic-UI) | **LLM emits a typed generalization plan; code applies it** (proposed) | **Pure code from N runs** (NetGent today) |
|---|---|---|---|
| what the LLM emits | the whole artifact (steps, selectors, `input_schema`) | a patch of typed edits over a code-built draft | nothing |
| generalizes from **one** run | ✓ | ✓ | ✗ (`_confirm_param` needs variance) |
| expresses **positional** intent | prose in `target_text`/`position_hint`, resolved by a semantic executor at run time | ✓ as a choice of rung from the recorded ladder, resolved and checked at compile time | ✗ |
| folds N presses into one gesture | possible, unchecked | ✓ `RepeatFold`, checked for contiguity + identical signature | ✗ |
| classifies interrupts | LLM prose | ✓ typed `role`, code builds the ε-`Interrupt` | regex ∧ regex (N=1); cross-run presence (N≥2) |
| **failure mode when the LLM is wrong** | a broken artifact that parses — the error surfaces at replay, on a live site | the edit is **rejected in code**; the draft is unchanged; a warning names it | n/a |
| worst case | worse than no generalization | **equal to no generalization** | over-specific artifact |
| artifact checkable | pydantic shape only; `str.format` silently no-ops on a missing key | pydantic + 10 semantic rules + graph validation + replay | same, minus the plan rules |
| who grades the generalization | nobody (Workflow Use's AI validator is off by default; no accuracy number exists) | `replay_check`, with two value sets | `replay_check` |
| zero-LLM replay | ✗ (`agent`/`extract` steps; Magentic-UI is an LLM every step) | ✓ | ✓ |
| cost at compile | 1 LLM call | 1 LLM call | 0 |
| cost at replay | per-step inference (ReUseIt/Magentic-UI) or $0 with agent steps removed | **$0** | **$0** |
| evidence needed | 1 run | 1 run (N runs strictly better) | N runs |
| prior art | Workflow Use, Magentic-UI, AWM | ASI, SkillWeaver, Skyvern (post-SKY-8965), Rousillon, CoScripter | SMARTedit / version spaces |
| published precision for its parameter choices | **none** | to be measured (§C.7 #2/#3) | n/a |

The row that decides it is *failure mode*. Workflow Use's failure mode is an artifact that looks right and
breaks on a live site; ours is a warning and an unchanged draft. That asymmetry is why the plan is a patch and
not a rewrite.

## C.9 Open questions this design does not settle

1. **`Repeat.count` cannot express "30 seconds at 10 s per press".** The param must be the iteration count
   (`fast_forward_presses = 3`) with the unit in `Param.description`, or the schema needs arithmetic (a
   `per_iteration` field on `Repeat`, or a computed `Param`). The first is honest and needs no schema change;
   recommend it for v1 and revisit.
2. **`_MIN_VALUE_LEN` should probably rise from 2 to 3 or 4.** Skyvern arrived independently at 4 with an
   explicit false-positive rationale (§B.3.4). Changing it affects the existing merge, so it needs its own
   measurement on the sweep.
3. **Positional selectors are what Skyvern forbids** (§B.3.5). We are choosing the opposite for a reason —
   they run an LLM at replay and we do not, so prose is not available to us — but the risk they cite is real:
   a positional locator survives a title change and breaks on a layout change. The mitigation is that the
   choice is *requested and checked*, never derived (rule 2 of §C.0), and that the replay gate catches it.
   §D.2 is one confirmation on one site; it says nothing yet about layout drift over time, which is exactly
   what Ringer's 37-day study measured and we have not.
4. **`kind: page` bindings imply dynamic `Param` + `ParamSource` extraction with a `guard`** — machinery that
   exists in the schema (`control.py` L79-109) and is exercised by `tests/integration/test_dynamic_params.py`,
   but that the generator has never emitted. Defer past M2.
5. **What the generalizer should do with a `not achieved` verdict.** Today a failed verify ends the pipeline.
   Arguably it should never generalize a run the verifier rejected — but ReUseIt's central claim is that
   failures locate the guards (`reuseit.md` §6.3 #1). That is a separate design, not this one.

---

# Part D — Measured: the closed loop on the Dream Theater task (2026-09-02)

Between the survey above and this revision, the design shipped. Branch `v2/closed-loop-rounds` (being merged
into `eugene/v2-scaffold` at the time of writing — see §E.2), run artifacts committed under
`v2/evals/results/closed-loop/dream-theater-2026-09-02/`. Everything in this part is read from those files and
from the branch's source; nothing here is inferred.

## D.1 What shipped, and how it differs from §C.3

The implementation kept the contract of §C.0 exactly and made the vocabulary **narrower** than the
`GeneralizationPlan` sketch — which is the right direction.

| §C.3 sketch | shipped as | note |
|---|---|---|
| `GeneralizationPlan` | `NextRoundPlan` (`agent/planner/models.py` L119-138) | also carries `next_variations` and `scoped_subtasks`: the plan says what to *explore* next as well as what to *generalize* |
| per-step edits keyed by `StepId` | `GeneralizationHint` keyed by **merge column index** (`agent/generator/hints.py` L32-46) | better: a column is the unit the merge already reasons about, and it exists at N ≥ 2 |
| `LocatorIntent{instance, positional, text_param}` | `HintIntent = Literal["positional", "text_contains_param", "instance"]` (`hints.py` L15) | one-for-one |
| `RepeatFold{steps, name, per_iteration}` | `RepeatFold{kind: press\|click, count_param}` (`hints.py` L18-29) | the block is *derived* from the column, not listed by the LLM — strictly safer |
| `ParamBinding` | not a hint kind | the merge already confirms value params from cross-run variance; the LLM was not given a job code does correctly (§C.5) |
| `StepRole` | `Episode(kind="conditional_step")` on the triage side | classification moved to code |
| `Expectation` / `accept` | **not implemented** | the gap §D.4 measures |
| rejections as warnings | `HintOutcome{hint, status: applied\|rejected, reason, transition}` + `acceptance_rate()` (`hints.py` L49-62) | the edit-acceptance metric of §C.7 #4 is a first-class number |

`hints.py`'s own docstring states the contract in the doc's terms: *"A hint is a typed CHOICE among options
the recordings already contain, never a selector, a regex, an action or artifact content … Code re-derives
every hint from the recordings before applying it … a rejected hint leaves the draft unchanged."*

Two components §C did not anticipate and that turn out to be load-bearing:

- **`agent/triage.py`** (218 lines, zero LLM) turns one round's evidence into typed `Episode`s in a closed
  vocabulary — `positional_target`, `unbound_value`, `conditional_step`, `flow_drift`, `unpassable`,
  `judge_unmet`. Its authority rule is §B.8.3 in code: *"replay and merge signals are authoritative; the
  judge's are advisory and are dropped when a replay with that run's values passed"* (L17-18), implemented at
  L205-212 — a judge caveat survives only if no passing replay with that run's own value set contradicts it.
- **The M0 ladder shipped** as three fields on `AgentStep` (`explorer/models.py` L83-89):
  `locator_candidates: list[list[LocatorStep]]`, `candidate_kinds: list[str]`, `element: dict`. `triage._list_like`
  (L95-113) reads `"structural" in step.candidate_kinds` as its primary signal, with a listy-role and an
  `nth`-in-selector regex as fallbacks for records made before M0.

## D.2 The run

Task: *"Go to youtube.com, search for Dream Theater - Under a glass moon and play the first video that pops
up…"*, `--runs 3 --rounds 3`, model `claude-code:sonnet`. Canonical param names proposed by the planner:
`search_query, watch_time_1, fast_forward_time, watch_time_2, pause_time, play_time_2`.

**Round 1** (`round-1/`). All three runs achieved (run 3 needed a second attempt). The merge confirmed four
params — `search_query, watch_time_1, pause_time, play_time_2` — and dispositioned the columns
`{aligned: 5, param: 4, dropped: 12, target-varies: 1, interrupt: 2}`. Column 5 is the video click:

```json
{"index": 5, "disposition": "target-varies", "support": 3, "action_type": "click",
 "targets_by_run": {"1": "role=link[name=\"Under a Glass Moon 7 minutes, 4 seconds\" i]",
                    "2": "role=link[name=\"Master of Puppets (Remastered) 8 minutes, 36 seconds\" i]",
                    "3": "role=link[name=\"Pink Floyd - Comfortably numb 6 minutes, 55 seconds\" i]"},
 "transition": "t4"}
```

The replay gate then failed exactly as §A.2 P1 predicts:

```
replay {... 'search_query': 'Dream Theater - Under a glass moon' ...}: ok states=10 last=['s9','s10']
replay {... 'search_query': 'Pink Floyd - Comfortably Numb' ...}: FAILED at t4 (action_error; unmet ['url_matches','selector_visible'])
replay {... 'search_query': 'Metallica - Master of Puppets' ...}: FAILED at t4 (action_error; unmet ['url_matches','selector_visible'])
replay_passed=False unseen_passed=0
```

Triage emitted four episodes — `positional_target` on column 5 at `t4`, **replay-confirmed**; two
`conditional_step`; one `judge_unmet` — and `plan_next` returned three hints, two fresh variations and one
scoped sub-task. Its hint for column 5, verbatim from `round-2/generalized.json`:

```json
{"column": 5, "intent": "positional", "param_name": null, "repeat_fold": null,
 "why": "task text says 'play the first video that pops up'; replay FAILED at t4 for runs 2 and 3 because
         run 1's literal title selector was kept instead of a position-based match — episode explicitly flags
         this as list-like/positional"}
```

**Round 2.** The generator applied it, and — this is the part that matters — applied it *because code found a
rung to apply it to*:

```json
{"status": "applied", "transition": "t4",
 "reason": "structural rung '#dismissible > div > div a#video-title' + nth(0)"}
```

Column 5's disposition became `positional`, with the note *"switched to the structural rung + nth(0): the same
position in every run"*. The gate then passed:

```
replay {... 'Dream Theater - Under a glass moon' ...}: ok states=10 last=['s9','s10']
replay {... 'Pink Floyd - Comfortably Numb' ...}:      ok states=10 last=['s9','s10']
replay {... 'Metallica - Master of Puppets' ...}:      ok states=10 last=['s9','s10']
replay_passed=True unseen_passed=2
```

**Two of the three value sets had never been explored** — the artifact was compiled from run 1's trajectory and
replays for queries whose first result has a different title. That is P1 closed, end to end, zero LLM at replay.

## D.3 What this resolves, and what it costs

**§E.3's load-bearing unknown is resolved in the affirmative.** The previous revision flagged as unverified
whether `locator_candidates()` actually yields a *structure-keyed* rung for a YouTube result link. It does:
`#dismissible > div > div a#video-title`. Note what makes it work — it is a **descendant CSS path**, not an
`nth-of-type` chain, and the positional part comes from the appended `nth(0)`. So the mechanism is not "the
ladder happens to contain an ordinal selector"; it is "the ladder contains a *container-relative* rung, and
code adds the ordinal". That is a narrower and more robust claim than §C.2.1 made, and it is the one to carry
forward.

**Hint acceptance rate was 1/3** (`acceptance_rate` over `round-2/generalized.json.hints`). The two rejections
are both `"column 7 is not a main-path column of this merge"` / `"column 9 is not a main-path column"` — the
planner emitted `instance` hints for columns triage had reported as `conditional_step`, i.e. columns the merge
had already turned into interrupts and removed from the main word. Compare ASI's 15.6 %: our rejections are not
the validator catching hallucinated generalizations, they are the planner addressing columns that no longer
exist. **That is a fixable interface bug, not evidence about LLM quality**, and it means the acceptance rate is
not yet the health signal §C.7 #4 wanted it to be. Two candidate fixes: have triage omit `conditional_step`
episodes for columns the merge already compiled to an `Interrupt`, or have `normalize_next_round_plan` drop
hints whose column is not main-path (it already validates the column *exists*, `planner/models.py` L86-93).

## D.4 The two things still open — and what the evidence says the cause is

**(a) `fast_forward_time` never became a param, and no fold fired.** The user's report of this is confirmed,
but the cause is not where §C.4 V7 assumed. The fold machinery is present and capable: `merge.py` (L567-599 on
that branch) extends a `repeat_fold` hint's column into a block over adjacent same-signature columns and even
steps over scroll-only gap columns (*"a run scrolled to the player mid-gesture, and scrolls are dropped
whatever their support"*). It never ran because **no `repeat_fold` hint was ever proposed** — all three round-1
hints carry `"repeat_fold": null`. The planner says why, in its own note:

> `fast_forward_time` and `watch_time_2` never surfaced as confirmed param columns (all the candidate columns
> 11,14-19 were dropped as inconsistent press/wait actions present in only 1-2/3 runs) — the fast-forward
> gesture (repeated key presses vs. a single wait) was not stable across runs.

So the chain is: the explorer presses a different number of times each run → the press columns get support
1–2 of 3 → the merge drops them by the structural-intersection rule (correctly, and with a warning per column)
→ the next round's planner sees eleven `dropped` warnings and no signal that any of them are one gesture →
it proposes no fold. Round 2 confirms the upstream half independently: runs 4 and 5 were judged **not
achieved** on exactly this — *"only a single 'l' keypress occurred"*, *"only four 'l' key presses"*.

**The gap is in triage's vocabulary, not in the generator.** `dropped` conflates two different things: a step
the other runs genuinely did not need, and a *gesture whose repetition count varies with a parameter*. The
second is code-detectable — a maximal run of adjacent columns sharing one signature, present in **every** run
at count ≥ 1, whose per-run counts differ — and it deserves its own episode kind (say `varying_gesture`),
carrying the per-run counts so `plan_next` can propose the `repeat_fold` that already exists. That is a pure-code
addition to `triage.py` and it is the highest-value next change this doc can name.

Second-order: the explorer's own unreliability at the gesture is a separate defect and should not be papered
over by the generator. `explorer/prompt.py`'s seek section already instructs it to verify each press against
the next MEDIA reading and to count verified jumps; runs 4 and 5 show it not doing so.

**(b) `accept_states` is empty, so the gate checks the state *sequence*, not the goal.** Verified:
`dream-theater.workflow.yaml` L328 is `accept_states: []`. `replay_passed=True` in round 2 therefore means
"every edge dispatched ok and all three runs walked the same ten states" — it does **not** mean the video was
searched, played, fast-forwarded, paused and resumed for the requested durations. This is precisely
SkillWeaver's D.2.1 failure mode (§B.6.3) and it is why §C.4 V11 exists. The run supplies its own illustration:
run 3's judge caveat was that the video was not muted for ~12 s after the ad skip, and `triage` correctly kept
it as a `judge_unmet` episode *because no passing replay contradicted it* — a passing replay cannot contradict
a goal the artifact never encodes.

Given the fold gap, this matters more than it looks: `fast_forward_time` is not a param, so **no replay ever
varies the fast-forward**, and no accept state asserts the video advanced. A workflow that silently skipped the
fast-forward entirely would still report `replay_passed=True`.

## D.5 Revised recommendations

| # | change | why, from this run |
|---|---|---|
| 1 | **Add a `varying_gesture` episode to `triage.py`** — adjacent same-signature columns present in every run with differing per-run counts — and let `plan_next` propose the `repeat_fold` that already exists | the fold machinery works and was never invoked; `dropped` hides the pattern (§D.4a) |
| 2 | **Implement `accept` (V11).** No `accept_states` ⇒ not validated | measured shipping empty; the gate is currently the oracle §B.6.3 documents being gamed (§D.4b) |
| 3 | **Do not hint columns that are not main-path** — filter in triage or in `normalize_next_round_plan` | 2 of 3 rejections in round 2 were this, which corrupts the acceptance-rate metric (§D.3) |
| 4 | Keep §C.5's precedence table as written | round 1 → 2 is one clean confirmation of the `target-varies` row: code was measurably wrong, the LLM was right, and code still had the last word on whether the fix could be applied |
| 5 | Fix the explorer's seek verification before blaming the generator for `fast_forward_time` | runs 4 and 5 under-pressed and were judged not achieved (§D.4a) |

---

# E. Unverified, uncertain, or could not confirm

**About NetGent's own code**

1. **The "two broken fixtures".** I could not find them. `git grep -i broken` over `evals/` and `tests/` on
   every local branch returns only unrelated hits, and `evals/datasets/forms/` holds three fixtures
   (`vanilla`, `shadow`, `progressive`) which `evals/README.md` says *"All three currently pass."* §C.7 #5
   therefore states the *requirement* (a generalizer must not rescue a genuinely broken workflow) without
   citing the fixtures. If they exist informally, M1 should commit them as two trajectory bundles whose
   compile must fail the replay gate.
2. **Branch state, updated 2026-09-02.** `eugene/v2-scaffold` @ `8c7217b` now carries the merge, the media
   gate and `MediaPlaying`; the closed loop (`agent/triage.py`, `agent/generator/hints.py`, `plan_next`, the
   rounds loop) is on **`v2/closed-loop-rounds`** and was **mid-merge into `eugene/v2-scaffold` when this was
   written** — `.git/MERGE_HEAD` present, four conflicted paths including
   `v2/src/netgent/agent/generator/compiler.py`. Line citations for `compiler.py`, `locators.py` and
   `workflow.py` in this doc are against `eugene/v2-scaffold` @ `8c7217b` (i.e. `git show HEAD:…`), **not**
   against the conflicted working tree. Citations for `triage.py`, `hints.py` and `planner/models.py` are
   against `v2/closed-loop-rounds`. Once the merge lands, both sets move.
3. **RESOLVED (was: the load-bearing empirical claim of §C.6 is untested).** `locator_candidates()` does yield
   a structure-keyed rung for a YouTube result link — `#dismissible > div > div a#video-title`, applied with
   `nth(0)`. Evidence and the corrected framing are in §D.3. The remaining nuance: it is a *container-relative
   descendant path*, not an `nth-of-type` chain, so the ordinal is supplied by code, not found in the ladder.
   Whether that holds on sites other than YouTube is untested.
4. **`AgentStep` field names in §C.2.1 shipped, but not as proposed.** `v2/closed-loop-rounds` has
   `locator_candidates`, `candidate_kinds` and `element` (`explorer/models.py` L83-89); there is **no
   `match_counts`** field as §C.2.1 sketched. `triage._list_like` keys on `"structural" in step.candidate_kinds`
   instead. The V5 check as written in §C.4 ("`match_counts[candidate] >= index+1`") therefore does not
   correspond to shipped code — the shipped validation is inside the merge's positional path, which I did not
   read line-by-line.
5. **Whether a folded `press` repeat should be a self-loop edge** (so `state_signature` collapses it, as it
   does for dwells) is a design assertion, not something I tested. If it is not a self-loop, a different
   `alt_count` changes the signature and the metamorphic check would fail spuriously.

**About the external survey**

6. **The 2026 preprints are single-source and mostly code-less.** Skill-DisCo (2606.26669), MIND-Skill
   (2605.08670), W2S/RWSA (2606.06893, linked repo empty), "From Raw Experience to Skill Consumption"
   (2605.23899) and the budget-matched study (2606.15017) were fetched live by a research agent and I did not
   independently re-fetch them. The 46.4 %/15.8 %/73.8 % judge-accuracy result in §B.8.3 is doing real work in
   this design; **re-verify it before building on it.** No code is released for any of the five.
7. **ReUseIt Figure 7.** `reuseit.md` §3.3 transcribes it from the PDF showing `<departure city>` brackets; a
   fresh read of the arXiv HTML found only alt text and reports there is no parameter concept in the system at
   all. Both readings agree on the substance (nothing types, validates or resolves those brackets); the
   discrepancy is figure-text extraction, not fact.
8. **AWM's paper §A.1 prompt differs from the repo prompt** (the paper omits the two WebArena-only rules). I
   quote the repo files as authoritative but did not resolve which was used for the reported numbers.
9. **Skyvern is mid-migration.** The deterministic field picker's Phase 1 warns where Phase 2 will raise, so
   the behaviour in §B.3.3 will change. `generate-workflow-parameters.j2` is present-but-unreferenced; do not
   cite it as live. The producer that assigns `AuthoringParameterBindingMatchBasis` values was not located, so
   the precise rule behind e.g. `unique_ephemeral_value` is unknown.
10. **Stagehand's v3 documentation is stale** and contradicts v4 on whether cache keys use variable keys or
    values. §B.4 quotes v4. Any earlier NetGent doc citing the v3 claim should be corrected.
11. **Workflow Use HEAD moves fast** (`5d2d19f`, 2026-08-27 — a month past the `891267b` pinned in
    `discovery-prior-art.md`). Two reported internal inconsistencies (`keypress` vs the schema's `key_press`;
    an `input_schema` `description` field the validation prompt demands but the model does not declare) come
    from the survey agent and I did not re-verify them myself. `healing/deterministic_converter.py` (912
    lines) was not read.
12. **CoScripter's CHI 2008 paper could not be obtained** — ACM DL 403, the Cornell copy 404s, and Unpaywall
    confirms `"oa_status":"closed"`. Everything attributed to CoScripter in §B.5.1 comes from the Koala CHI
    2007 PDF, the GROUP '07 poster, IBM's shipped help pages, and the extension source. Nothing is quoted from
    CHI 2008.
13. **Two named systems were never fetched:** *Reasoning Primitive Induction* (arXiv:2606.02994) and *SAGE*
    (arXiv:2512.17102). Treat as unconfirmed. Also explicitly *not* examined: Cradle, Agent-Pro, LearnAct,
    Optimus-1/2, Agent Symbolic Learning, WebGauntlet — unexamined, not absent.
14. **The additions in §B.6.5 (WebXSkill, WALT, SGDR), the Voyager/ICAL corrections in §B.6.4 and the
    artifact-metric table in §B.8.2** come from a verification pass I did not independently repeat. WebXSkill
    has released code (`github.com/aiming-lab/WebXSkill`); WALT, SGDR, Skill-DisCo, MIND-Skill and W2S have
    not. WebXSkill's Table 7 measures SkillWeaver third-party — useful, but one lab's measurement of another's
    system.
15. **§B.5.3 (version spaces) is not re-verified today.** It rests on `trajectory-memory.md` §B.2.6, which
    cites Lau/Wolfman/Domingos/Weld, *Machine Learning* 53 (2003). A dedicated re-check was still running when
    this doc was written; the claims used here (monotone narrowing, 1–2 demos under a strong prior, the late
    anomalous example, active learning as the fix) are the ones that doc already verified.

**Judgement calls, not facts**

16. **"Edit acceptance near 100 % means the validator is too weak"** (§C.7 #4) is a heuristic borrowed from
    ASI's 15.6 %, not a measured threshold for our setting.
17. **Raising `_MIN_VALUE_LEN` from 2 to 3–4** (§C.9 #2) is inferred from Skyvern's independent choice of 4;
    its effect on the existing merge is unmeasured and it should not be changed without running the sweep.
18. **The precedence table in §C.5** encodes a judgement — cross-run evidence beats a single-run reading for
    *structure*, the LLM wins on `target-varies` — now grounded in two measured cases (`e8932d9` and the
    round-1 → round-2 transition of §D.2). Two cases on one site and one task family is enough to justify
    keeping it; it is not enough to call it settled.
19. **§D is one run, one task, one site, one model** (`claude-code:sonnet`, YouTube, 3 runs × 2 rounds). The
    positional fix is a single confirmation. Nothing here establishes a rate for anything, and §C.7's metrics
    (false-param rate on the 21-form sweep, precision/recall on a labelled set) remain unmeasured.
