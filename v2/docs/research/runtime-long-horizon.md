# Runtime Context & Progress Management in Open-Source LLM Browser Agents

*Research note for NetGent v2 (UCSB). Scope: the observe→decide→act step loop, 50–200+ steps. Compile-time planning, NFA/workflow induction, and benchmark design are deliberately out of scope.*

---

## Question

When a browser agent's task takes 50–200+ steps, the agent's own trajectory becomes the dominant context-management problem. Concretely, at step N:

1. **What is actually in the prompt?** Full history, last-k steps, a running summary, or a structured state object?
2. **How is progress tracked** across many steps — a plan object, a todo list, milestone flags, a self-evaluation of the previous action?
3. **How is being STUCK detected and escaped** — loop detection, repeated-action hashing, failure counters?
4. **What are the step budgets, and what happens when they run out?**
5. **Is there explicit context compaction/summarization** when history grows?

The answers below come from reading current source (clone SHAs and dates given per system) plus 2025–2026 papers on runtime context management.

**Repos read (all shallow-cloned and read locally):**

| System | Commit | Date |
|---|---|---|
| browser-use/browser-use | `85ddbfedf609166b2d2c76c3d80506649fee82a9` | 2026-08-19 |
| Skyvern-AI/skyvern | `a54dc39058a1ebb6ac93731ea7a0240c24c1dfc1` | 2026-08-19 |
| EmergenceAI/Agent-E | `f218c3cb4b2b3e33ed08ea12da5514ab1e89cdd7` | 2025-05-12 |
| magnitudedev/magnitude | `c3ace06488737be5383087d965d0e4e629f4f00b` | 2026-08-19 |
| nanobrowser/nanobrowser | `24a14b76e14a9c30fd84878ca7985049d1e7d064` | 2026-08-18 |

---

## Per-system findings

### 1. browser-use

The most mechanism-dense of the five. Its runtime loop has *five* separate, independently-configurable context/progress subsystems, several of which are recent additions.

#### What is in the prompt at step N

**Not an accumulating chat log.** `MessageHistory` (`browser_use/agent/message_manager/views.py`) holds exactly three slots:

```python
class MessageHistory(BaseModel):
    system_message: BaseMessage | None = None
    state_message: BaseMessage | None = None
    context_messages: list[BaseMessage] = Field(default_factory=list)
```

Every step, `MessageManager.create_state_messages()` (`message_manager/service.py:424`) builds one fresh `UserMessage` and **replaces** the previous `state_message` via `_set_message_with_type(state_message, 'state')`. So the LLM sees: system prompt + one rebuilt user message + any ephemeral nudges. The DOM and screenshot of step N−1 are simply gone.

That single user message is assembled by `AgentMessagePrompt.get_user_message()` (`agent/prompts.py:404`) in this order:

```
<user_request>          the original task (always present, verbatim)
<agent_history>         compacted_memory + list of HistoryItem records
<agent_state>           <file_system>, <todo_contents>, <plan>, <sensitive_data>, <available_file_paths>
<browser_state>         current URL, tabs, indexed interactive elements
<read_state>            one-shot extract/read_file output (this step only)
<page_specific_actions>
<step_info>             "Step{N} maximum:{max_steps}" + today's date  ← deliberately last, for prefix caching
```

Only the **current** screenshot is attached. `create_state_messages` builds `screenshots = []` and appends at most `browser_state_summary.screenshot` — there is no image history.

`<agent_history>` is a list of `HistoryItem` (`message_manager/views.py:15`), each rendering to:

```
<step_N>
{evaluation_previous_goal}
{memory}
{next_goal}
Result
{action_results}
```

`max_history_items` defaults to `None` (`agent/service.py:181`) → **all steps included**, but each is a ~4-line text record, not raw page state. When a limit is set, `agent_history_description` (`message_manager/service.py:153`) keeps *item 0 + a `<sys>[... K previous steps omitted...]` marker + the most recent (limit−1) items* — first-and-last-k, never a plain sliding window.

`action_results` is not the raw tool output. `_update_agent_history_description` (`message_manager/service.py:304`) prefers `action_result.long_term_memory` (a short agent-authored note) over `extracted_content`; content flagged `include_extracted_content_only_once` goes to `<read_state>` for exactly one step and then disappears. Errors are middle-truncated to 200 chars (`error[:100] + '......' + error[-100:]`); both `read_state_description` and `action_results` are hard-capped at 60,000 chars.

#### Progress tracking

Three mechanisms stacked:

**(a) The `AgentBrain` triad**, emitted every step (`agent/views.py:381`, `AgentOutput` at `:388`):

```python
class AgentBrain(BaseModel):
    thinking: str | None
    evaluation_previous_goal: str   # "Clicked submit button with index 15 but the form was not submitted. Verdict: Failure"
    memory: str                     # "Visited 2 of 5 target websites. Collected pricing from Amazon ($39.99)..."
    next_goal: str
```

`model_json_schema` forces `['evaluation_previous_goal', 'memory', 'next_goal', 'action']` as required. The system prompt's `<memory_examples>` block explicitly trains counters and failure notes ("Captcha appeared twice on this site. Will try alternative approach", "Previous click on search button failed - page did not change").

**(b) A first-class plan object** (newer than the triad). `AgentOutput` also carries optional `current_plan_item: int | None` and `plan_update: list[str] | None` (`agent/views.py:395-396`). `Agent._update_plan_from_model_output()` (`agent/service.py:1411`) maintains server-side `list[PlanItem]` state with statuses, and `_render_plan_description()` (`:1445`) renders it into `<plan>`:

```
[x] 0: Navigate to arxiv.org/list/cs.AI/recent
[>] 1: Collect metadata for papers 1-10
[ ] 2: Collect metadata for papers 11-20
```

Advancing `current_plan_item` from i→j auto-marks everything in between `done`. The `<planning>` section of `system_prompt.md` gates plan creation on complexity ("Simple task (1-3 actions): Act directly. Do NOT output `plan_update`") and warns "Completing all plan items does NOT mean the task is done."

**(c) A real file system with `todo.md`.** `FileSystem` is initialized with `default_files = ['todo.md']` (`browser_use/filesystem/file_system.py:382`). `get_todo_contents()` (`:889`) returns it **in full, never truncated**, injected as `<todo_contents>`; all *other* files get a start/end preview capped at 400 chars by `describe()` (`:816`). The prompt says: "Use `replace_file` tool to update markers in `todo.md` as first action whenever you complete an item… DO NOT use the file system if the task is less than 10 steps!"

#### Stuck detection

`ActionLoopDetector` (`agent/views.py:157-245`), on by default (`loop_detection_enabled: bool = True`, `views.py:91`). Two independent signals over a rolling window of 20:

- **Action repetition.** `compute_action_hash()` (`:151`) hashes a *normalized* action, not the raw params (`_normalize_action_for_hash`, `:110`): search queries are lowercased/tokenized/sorted; clicks hash by element type + text **ignoring the index**; navigation hashes by domain only. So near-duplicate clicks collide by design. `wait`, `done`, `go_back` are exempt (`_LOOP_EXEMPT_ACTIONS`, `service.py:1509`) — `wait` would otherwise hash identically and trip instantly.
- **Page stagnation.** `PageFingerprint` (`views.py:95`) = `(url, element_count, sha256(dom_text)[:16])`; identical consecutive fingerprints increment `consecutive_stagnant_pages`.

`get_nudge_message()` escalates at **5 / 8 / 12** repetitions and at **5** stagnant pages. Critically, this is *advisory*: the class docstring says "This is a soft detection system — it generates context messages for the LLM but never blocks actions." The 12-threshold message even says "If you are making progress with each repetition, keep going" — deliberately tuned not to break legitimate pagination loops.

Two more stall responses in `service.py`, both firing before the LLM call at `:1147-1151`:
- `_inject_replan_nudge()` (`:1457`) at `planning_replan_on_stall = 3` consecutive failures → "REPLAN SUGGESTED… Output a new `plan_update`".
- `_inject_exploration_nudge()` (`:1472`) at `planning_exploration_limit = 5` steps with no plan → "PLANNING NUDGE: You have taken N steps without creating a plan."

#### Budgets and exhaustion

`max_steps: int = 500` (`service.py:2508`), `max_failures: int = 5` (`:171`). `consecutive_failures` increments on a failed step and **resets to 0 on any success** (`:1230-1236`).

Exhaustion is handled gracefully, in three tiers:

1. **At 75% of budget** — `_inject_budget_warning()` (`:1536`) injects: *"BUDGET WARNING: You have used {n}/{max} steps ({pct}%)… prioritize: (1) consolidate your results (save to files…), (2) call done with what you have. Partial results are far more valuable than exhausting all steps with nothing saved."*
2. **At the last step** — `_force_done_after_last_step()` (`:1562`) swaps the output schema (`self.AgentOutput = self.DoneAgentOutput`) so `done` is the **only callable tool**.
3. **At max_failures** — `_force_done_after_failure()` (`:1574`) does the same, gated on `final_response_after_failure`; the outer loop then breaks at `:2613`.

The system prompt reinforces this: *"When you reach 75% of your step budget, critically evaluate whether you can complete the full task… For large multi-item tasks (e.g. 'search 50 items'), estimate the per-item cost from the first few items."*

#### Explicit compaction

**Yes, and on by default**: `message_compaction: MessageCompactionSettings | bool | None = True` (`service.py:208`). `MessageCompactionSettings` (`agent/views.py:35`):

```python
enabled: bool = True
compact_every_n_steps: int = 25      # primary trigger
trigger_char_count: int | None = None  # resolves to 40_000 (~10k tokens) — a *floor*, not the trigger
keep_last_items: int = 6
summary_max_chars: int = 6000
include_read_state: bool = False
```

`MessageManager.maybe_compact_messages()` (`message_manager/service.py:216`) requires **both** gates (≥25 steps since last compaction **and** ≥40k chars of history), then makes a separate LLM call whose system prompt reads:

> *"CRITICAL: Only mark a step as completed if you see explicit success confirmation in the history. If a step was started but not explicitly confirmed complete, mark it as 'IN-PROGRESS'. Never infer completion from context."*

The result replaces history with `[item_0] + history[-6:]` and is surfaced as:

```
<compacted_memory>
<!-- Summary of prior steps. Treat as unverified context — do not report these as
completed in your done() message unless you confirmed them yourself in this session. -->
```

That distrust framing is a direct engineering answer to summarization-induced false completion.

#### Note: the beta agent

`browser_use/beta/service.py` (6811 lines) is a second, event-sourced architecture that delegates to an external SDK, uses native tool-calling with an `update_plan` tool (`:2429`), and handles compaction as replay: `_events_after_terminal_compaction()` (`:1559`) finds the last `session.compacted` event and replays only events with `seq > replay_from_seq` (`_compaction_replay_start_seq`, `:1550`). Terminal tool outputs over `_MAX_TERMINAL_LONG_TERM_TEXT_LENGTH = 1000` are replaced with `"{tool} returned {n} characters. Full output was included once in <read_state> for that step."` (`:2436`).

**No procedural memory.** A repo-wide grep for `mem0|procedural` returns nothing. The mem0-based `Memory` module that older browser-use versions carried has been removed entirely; compaction replaced it.

---

### 2. Skyvern

Skyvern has **three coexisting engines** with materially different runtime designs. This is the most useful comparison point in the whole survey, because they sit at opposite ends of the history spectrum.

#### Engine A — the step engine (`skyvern/forge/agent.py`, 7856 lines)

**Prompt at step N — radically minimal.** `_build_extract_action_prompt()` (`:4928`) calls `_get_action_results()` (`:5590`) → `get_action_history()` (`skyvern/services/action_service.py:11`), whose default window is:

```python
PROMPT_ACTION_HISTORY_WINDOW: int = 1   # skyvern/config.py:208
```

```python
window_steps = steps[-1 - history_window : -1]
```

**One prior step.** And not even the full step: each entry is projected down to `{action_type, element_id, status, reasoning, option, download}` + `{success, exception_type, exception_message, download_triggered, ...}`. Multi-result actions keep only `results[-1]` ("some actions (like chain_click) might have multiple results. Only the last one can represent the real result").

The `extract-action.j2` prompt gets: user goal, complete criterion, user details (navigation payload), then a `BEGIN_UNTRUSTED_WEB_PAGE_DATA` fenced block with current URL, clickable elements, the 1-step action history, browser dialog messages, and open tabs. State lives in **the page and the database**, not the prompt.

**Progress tracking is per-step self-evaluation only.** The output schema requires:

```
"user_goal_stage": str,     // reasoning whether user goal has been achieved
"user_goal_achieved": bool,
"action_plan": str,         // plan of actions this turn, and their order
"actions": [ {reasoning, confidence_float, action_type, id, ...} ]
```

`action_plan` is *within-turn* — it is not persisted or re-fed. Separately, `check_user_goal_complete()` (`:4094`) runs a **dedicated verification LLM call every step**, which can return `CompleteAction(verified=True)` or (under an experiment flag) `TerminateAction`.

**Stuck detection is prompt-level, not code-level.** The system prompt carries: *"Consider the action history from the last step and the screenshot together, if actions from the last step don't yield positive impact, try other actions or other action combinations"* and, for dialogs, *"do NOT retry the same INPUT_TEXT with the same text on the same field."* I found no action-hashing or repetition counter in the step engine.

**Budgets — very tight.**
```python
MAX_STEPS_PER_RUN: int = 10        # config.py:155
MAX_RETRIES_PER_STEP: int = 5      # config.py:185
LONG_RUNNING_TASK_WARNING_RATIO: float = 0.95   # config.py:184
```
Resolution order (`agent.py:1611`): request override → task → organization → global default. A failed step is not discarded — it is re-executed as a **new `Step` row with `retry_index + 1`** (`:6718-6796`), and exceeding `max_retries_per_step` raises `ReachMaxRetriesError`. At `step.order == int(max_steps * 0.95 - 1)` a "Long running task warning" is logged (`:7441`). There is **no in-prompt wrap-up warning** in the step engine — running out of steps just fails the task.

**No compaction** — with a 1-step window, there is nothing to compact.

For the CUA-style path (`YutoriNavigatorLLMCaller`, `:3560`) Skyvern *does* keep a persistent `message_history` across steps, initialized only at `step.order == 0 and step.retry_index == 0` so retries don't replay, and calls `add_stop_and_summarize()` on the last step instead of a normal tool result.

#### Engine B — Task V2 (`skyvern/services/task_v2_service.py`, 2852 lines)

An outer planner loop that emits mini-goals, each executed by a step-engine block.

```python
DEFAULT_MAX_ITERATIONS = 50                       # :105
MAX_STEPS_PER_TASK_V2: int = 25                   # config.py:156
NAVIGATE_TERMINAL_OUTPUT_MAX_CHARS = 2000         # :109
```

The 2000-char cap is explicitly justified: *"task_history is re-fed to the planner every iteration, so an unbounded reasoning blob would grow context."* Structured outputs over 20k chars are dropped rather than truncated (`NAVIGATE_STRUCTURED_OUTPUT_MAX_CHARS`, `:112`).

**Prompt at planning iteration i** (`task_v2.j2`): user goal, then an untrusted block with current URL, open tabs, clickable elements, the **full `task_history`** (a list of `{type, task, status, reason, extracted_data}` records — one per mini-goal, not per step), and `prior_required_subgoals`.

**Progress tracking — the strongest explicit milestone mechanism I found in any of these repos.** The planner must emit:

```
"required_subgoals": [{
    "subgoal": str,
    "satisfied": bool,   // "A navigate/visit that merely reached the relevant page
                         //  WITHOUT capturing the data does NOT satisfy it."
    "evidence": str
}],
"user_goal_achieved": bool,  // "True ONLY if EVERY entry in required_subgoals is satisfied"
```

This checklist is **carried forward** across iterations (`carry_subgoals` lever, `planner_levers.py:31`), and the prompt instructs: *"Refine the required_subgoals leg-checklist… instead of re-deriving it from scratch. Carry forward the parts already marked satisfied (keep their evidence)… only re-mark a part satisfied=false if new evidence shows it regressed."*

**Budget-aware wrap-up.** `_converge_iterations_remaining()` (`:672`) computes a window of `max(1, max_iterations * converge_pct // 100)`, with `DEFAULT_CONVERGE_PCT = 20` (`planner_levers.py:9`) — i.e. the last ~10 of 50 iterations. Inside that window the prompt gains:

> **WRAP-UP MODE** — only {N} planning iteration(s) remain… Work ONLY the required_subgoals still marked satisfied=false… Do NOT start new legs, broaden scope, explore optional/secondary info, or re-verify already-satisfied parts.

**Stuck escape.** Notable prompt engineering: *"When a mini goal's reason says it reached the maximum steps, it did NOT fail because it was impossible — it was either too broad or the agent spent steps operating the page inefficiently. Do not re-issue it unchanged. Re-plan a MORE SPECIFIC variant: name the exact action and the exact value to enter, and switch to a more direct interaction when the previous one was expensive (e.g. type a date into the field instead of clicking through a calendar)."* And an explicit anti-livelock rule for close-tabs tasks: *"If you have already attempted a close-tabs task and the open tabs still do not match, do not keep retrying it."*

There is even a named failure mode encoded in the prompt: planning "summarize the findings" tasks *"loops forever, because extract keeps returning page data instead of the synthesis, and it is the single most common way these runs exhaust their step budget."*

#### Engine C — Task V3 (`skyvern/forge/taskv3/`, 1594 lines)

The newest engine and the architectural opposite of the step engine. Module docstring:

> *"A single persistent LLM conversation drives browser tools via native tool-calling… Perception is a tool the model chooses to call — nothing about the page is injected automatically — which is what distinguishes this from the step engine's scrape-every-step loop."*

**Prompt at step N: the entire transcript, re-sent every turn** (`llm_caller.message_history = list(messages)`, `loop.py:333`).

**Compaction: in-place snapshot elision.** `_compact_transcript()` (`loop.py:219`) runs *before every* LLM call. `ToolSpec` carries a `compactable: bool` flag ("a large perception result safe to elide from the transcript once superseded"); successful perception results record their index in `snapshot_indices` at append time. Compaction keeps the newest result *per tool name* and rewrites older ones to `"[superseded observe output elided to bound context]"`. Two protections are called out in the docstring:

- The most-recent round (after the last assistant message) is never touched, because compaction runs *before* the model has read it.
- Only *successful* snapshots are candidates, so an error result can never shadow the real page view.

Only content is shrunk, never removed — "every `tool_call` keeps a matching result and the transcript stays valid."

**Budgets — five simultaneous ceilings** (`engine.py:36-53`):

```python
DEFAULT_MAX_TURNS = 80
DEFAULT_MAX_TOOL_CALLS = 300
DEFAULT_DEADLINE_SECONDS = 1800
DEFAULT_MAX_TOKENS = 1_500_000   # "Backstop against a spiral re-reading the page every turn"
MIN_ACTION_STEPS = 20            # floors a step-engine-tuned cap so v3 isn't starved
MAX_TURNS_PER_ACTION_STEP = 6
MAX_TOOL_CALLS_PER_ACTION_STEP = 25
```

A "step" here is *an action round* — a turn that ran ≥1 page-mutating (`billable`) tool. Perception-only turns don't consume the step budget. When `max_action_steps` is hit, billable tools are refused but **perception and `finish` still pass through**, so the agent gets one last observe-and-report turn. Unexecuted calls in a batch are answered with `"skipped: {reason}"` (`_append_skipped_tool_results`, `:145`) so the transcript stays valid.

**Stuck handling — three distinct mechanisms:**
- `NO_TOOL_CALL_NUDGE` (`:141`): if a turn returns prose instead of a tool call, inject *"You did not call a tool. Call a browser tool to make progress, or call finish(…). Emit a tool call now."* Tracked separately as `no_tool_call_turns`.
- **Batch abort on error** (`:463`): a failed tool call skips the rest of that turn's batch, because "a failed call can leave the page in a state the rest of this batch was not planned against."
- **Anti-inspection-spiral prompt rule** (`engine.py` `SYSTEM_PROMPT`): *"Inspecting the page does NOT progress the task — only type/select_option/click do. If your recent turns were mostly observe/get_html with little typing or clicking, you are stuck inspecting: stop, and fill every field you can from the latest observe snapshot."*
- **Settle-gated completion**: `make_finish_tool()` (`:158`) takes a `settle_probe`; `finish(completed)` on an unsettled page is deferred up to `max_settle_deferrals = 2` — "delayed loads otherwise produce stochastic false completions."

---

### 3. Agent-E

Note: last commit 2025-05-12; effectively dormant. Its value here is architectural, not as current practice.

#### Structure: planner/executor with a summarizing boundary

`AutogenWrapper` (`ae/core/autogen_wrapper.py:43`):

```python
def __init__(self, save_chat_logs_to_files=True,
             planner_max_chat_round: int = 50,
             browser_nav_max_chat_round: int = 10):
```

- **Outer chat** (`a_initiate_chat`, `:368`): `user` proxy ↔ `planner_agent`, `max_turns=50`. `clear_history=True` is present but **commented out** (`:371`), so the planner accumulates the full sequence of (next_step → helper summary) exchanges.
- **Inner chat** (`register_nested_chats`, `:147`): `browser_nav_executor` ↔ `browser_nav_agent`, `max_turns=10`, triggered per planner step.

The boundary is the interesting part. `my_custom_summary_method()` (`:121`) returns **only `recipient.last_message(sender)["content"]`** to the planner — the entire inner tool-calling loop (DOM dumps, click results, retries) is discarded, and only the final `##TERMINATE TASK##` summary crosses back, with the current URL appended. `reflection_message()` (`:135`) does the reverse: it takes only `next_step` from the planner's JSON and appends `get_url()`.

This is enforced in the prompt: *"Helper is stateless and treats each step as a new task. Helper will not remember previous pages or actions. So, you will provide all necessary information as part of each step."* And: *"Helper cannot go back to previous pages. If you need the helper to return to a previous page, you must explicitly add the URL."*

#### Prompt at step N

- **Planner**: full accumulating outer conversation (task, every `next_step` it issued, every helper summary + URL), plus static user LTM. Output schema: `{"plan", "next_step", "terminate", "final_response"}` — `plan` is "optional and needs to be present only when a task starts and when the plan needs to be revised."
- **Browser nav agent**: fresh chat containing one subtask string + URL, then whatever DOM it fetches on demand via `get_dom_with_content_type` (`all_fields` vs `text_only`).

#### Change observation — Agent-E's most distinctive mechanism

A `MutationObserver` is installed on the page (`ae/utils/dom_mutation_observer.py`, `add_mutation_observer`) tracking `childList` and `characterData` mutations, filtering out `SCRIPT/NOSCRIPT/STYLE` and the agent's own overlay. Skills subscribe around their action and fold the diff into the tool result. From `ae/core/skills/click_using_selector.py:45-58`:

```python
dom_changes_detected = None
def detect_dom_changes(changes: str):
    nonlocal dom_changes_detected
    dom_changes_detected = changes
subscribe(detect_dom_changes)
await do_click(...)
unsubscribe(detect_dom_changes)

if dom_changes_detected:
    return (f"Success: {result['summary_message']}.\n As a consequence of this action, "
            f"new elements have appeared in view: {dom_changes_detected}. This means that "
            f"the action to click {selector} is not yet executed and needs further interaction. "
            f"Get all_fields DOM to complete the interaction.")
```

Same pattern in `press_key_combination.py:43-63`. So the *effect* of each action — not the whole new page — is what enters context. This is the hand-written ancestor of what VeriGUI (below) later learned end-to-end.

#### Stuck detection

`ae/utils/detect_llm_loops.py`, `is_agent_stuck_in_loop()`. Over the last 6 messages: if every `assistant` message's `tool_calls[0]["function"]` is identical **and** every `tool` response content is identical → return True. Wired as the browser executor's `is_termination_msg` (`autogen_wrapper.py:290-297`), so a detected loop **hard-terminates the inner chat** and hands control back to the planner. This is strictly binary (exact equality, no normalization, no fuzzy hashing) and terminates rather than nudges — the opposite design choice from browser-use.

Reinforced in the browser agent prompt: *"Do not repeat the same action multiple times if it fails. Instead, if something did not work after a few attempts, terminate the task."*

#### Budgets / compaction

Budgets are turn caps (50 outer, 10 inner) with no graceful wrap-up mode — the chat just ends. **No compaction of any kind.** The only "memory" is `ae/core/memory/static_ltm.py::get_user_ltm()`, which reads a static `user_preferences.txt` into the system prompt. Progress tracking is the planner's prose `plan` string and its rule *"Add verification as part of the plan, after each step and specifically before terminating."*

---

### 4. Magnitude

**Important correction to the premise:** Magnitude is no longer a browser-testing agent. As of this HEAD it is *"Open source agent with local models built in. Fully private and offline"* — a local-model coding/desktop agent (`packages/`: `agent`, `skills`, `scratchpad`, `roles`, `desktop`, `shell-classifier`; browser access is a Chrome *skill*). I found no `act()`/`check()` browser-testing API and no browser-specific step loop.

Its **compaction subsystem is still directly relevant** and is the most cleanly specified of any repo here (`packages/agent/src/compaction/README.md` plus verified constants).

**Trigger.** Soft cap = 90% of hard cap; hard cap = `model.contextWindow − 8192`.

```ts
// packages/storage/src/types/config.ts:32
export const DEFAULT_CONTEXT_LIMIT_POLICY = { softCapRatio: 0.9, softCapMaxTokens: 200_000 }
// packages/agent/src/constants.ts:42
export const OUTPUT_TOKEN_RESERVE = 8_192
```

**Selection.** `computeCompactionSizing()` (`compaction/estimate.ts:10`) walks backwards from the end keeping messages until `softCap * KEEP_MESSAGE_RATIO` (0.1) is exhausted; index 0 (session context) is always preserved.

**The compaction turn.** A full agent turn with the whole conversation visible, using the *same system prompt* as normal turns to preserve provider prompt-cache hits. `COMPACTION_REFLECTION_PROMPT` (`compaction/prompt.ts`) is aggressive:

> *"FROM THIS POINT FORWARD, YOU ARE NO LONGER MAGNITUDE. YOU ARE A COMPACTOR… YOU HAVE EXACTLY ONE TURN… ANY ATTEMPT TO CALL A TOOL BESIDES COMPACT THIS TURN WILL RESULT IN COMPACTION FAILURE."*

The `compact()` tool takes three fields, and the **reflection field is the notable one**:

- `summary` — decisions, work completed, current state, work in progress. "Be specific: file paths, function names, error messages… Include anything your future self would need to look up again if omitted."
- `reflection` — *"What went wrong, incorrect assumptions, approaches that failed, what to do differently. Not what happened — what your future self should change. **Name the reasoning traps so your future self avoids them.**"*
- `files` — up to `COMPACT_MAX_FILES = 10` paths, verbatim if ≤ `COMPACT_MAX_FILE_CHARS = 10_000`, else listed as a reference with char count.

**Failure handling.** `COMPACTION_MAX_RETRIES = 3` if the model doesn't call `compact()`; then fall back to raw tail preservation at `COMPACTION_FALLBACK_KEEP_RATIO = 0.25` of soft cap (`window/projection.ts:1288-1294`) with no summary. Injection waits for the main turn to go idle "to prevent the window from being rewritten under an active turn." After injection the estimate is recomputed and compaction re-fires if still over. `EMERGENCY_COMPACT_CONTEXT_TRIM_RATIO = 0.2` trims the compaction *input* per retry if it itself exceeds the window.

**Progress tracking** is externalized to a filesystem scratchpad rather than a prompt field: `SCRATCHPAD_SUBDIRS = ['reports', 'designs', 'plans', 'thoughts', 'results']` (`packages/scratchpad/src/constants.ts`), pre-created per session. `MAX_TOOL_CALLS_PER_TURN = 10`. I found no todo-list or plan-object mechanism in the agent loop.

---

### 5. nanobrowser — the two-level loop with a fixed planner interval

Included as the "other notable newer agent." It is a browser-use v0.1-lineage Chrome extension (its own comments say "in browser-use, it uses an empty string" / "in python version, all action results are reset to empty"), but it kept the **multi-agent** structure browser-use dropped: Planner / Navigator / Validator.

**Budgets** (`chrome-extension/src/background/agent/types.ts:24-33`):
```ts
maxSteps: 100,  maxActionsPerStep: 10,  maxFailures: 3,  planningInterval: 3
```

**The planner runs every 3 steps**, plus whenever the navigator claims completion (`executor.ts:157`):
```ts
if (this.planner && (context.nSteps % context.options.planningInterval === 0 || navigatorDone)) {
```
Navigator-claimed completion is never trusted directly — *"Navigator indicates completion - will be validated by next planner run"* (`:172`). The planner's schema (`prompts/templates/planner.ts`) is `{observation, done, challenges, next_steps, final_answer, reasoning, web_task}`; its output is injected as an `<plan>…</plan>` AI message (`messages/service.ts:199`).

**Context management — the ephemeral-observation pattern, explicit.** In `agents/navigator.ts`:
```ts
await this.addStateMessageToMemory();        // :173  — DOM + screenshot in
const modelOutput = await this.invoke(...);
this.removeLastStateMessageFromMemory();     // :200  — DOM + screenshot out
this.addModelOutputToMemory(modelOutput);    // :201  — decision stays
```
So the accumulating history is decisions + short `Action result:` / `Action error:` messages (errors reduced to their **last line only**, `:295-303`), while the bulky page state exists for exactly one call.

**Compaction: none.** `cutMessages()` (`messages/service.ts:370`) is pure emergency truncation against `maxInputTokens = 128000`: strip images from the last message; if still over, slice a proportional number of characters off the *tail* of the last message; if that would remove >99%, throw. No summarization anywhere.

**Stuck detection:** only `consecutiveFailures >= maxFailures (3)` → `MaxFailuresReachedError` (`executor.ts:267, 309, 329`). No loop or repetition detection. Step exhaustion emits `TASK_FAIL` with `MaxStepsReachedError` (`:188-192`) — no wrap-up mode, no forced summary.

---

### 6. 2025–2026 papers on runtime context management

Grouped by the mechanism they bear on.

#### Compaction / folding (the most active area, and the best-evidenced)

**AgentFold** (arXiv:2510.24699, Tongyi Lab / Alibaba, Oct 2025) is the closest thing to a formal spec of what NetGent v2 would want. Context `C_t` is exactly four parts: **user question Q** (invariant anchor), **tools T**, **multi-scale state summaries S** (an ordered sequence of blocks `s_{x,y}` each covering steps x→y), and **the latest interaction I_{t-1}** (full explanation + action + observation — one step only). Each turn the model emits four things: `thinking`, a **folding directive** `{"range": [k, t-1], "summary": σ_t}`, an `explanation`, and an `action`. The range selects the scale:
- `k = t−1` → **granular condensation**: fold only the last interaction into a fine-grained summary.
- `k < t−1` → **deep consolidation**: fuse the last interaction *with a chain of prior summaries* into one coarse block — i.e. retroactively collapse a finished sub-task.

Numbers worth quoting: at 100 tool calls, context is **~7,000 tokens vs ~91,000 for a ReAct baseline** (13× smaller), scaling tested to 256 and 500 turns. AgentFold-30B-A3B: 36.2% BrowseComp, 47.3% BrowseComp-ZH, beating DeepSeek-V3.1-671B and o4-mini with plain SFT.

**ReSum** (arXiv:2509.13313, Xixi Wu et al., Sep 2025; v3 Mar 2026): plug-and-play periodic summarization when context nears capacity, no architecture change. Training-free: **+4.5%** over ReAct. With ReSum-GRPO (advantage broadcasting across segmented trajectories to fix credit assignment across summary boundaries): **+8.2%** more.

**Context-Folding** (arXiv:2510.11967, Sun et al., Oct 2025): explicit `branch`/`return` tools — procedurally branch into a sub-trajectory, then fold it on completion, collapsing intermediates and keeping an outcome summary. Trained with FoldGRPO using process rewards for decomposition. **Matches or beats ReAct with an active context 10× smaller**, and beats summarization-based management.

**ACM: Agentic Context Management** (arXiv:2607.23809, Li/Ming/Chu (CMU) + Shao/Jin (Meta), Jul 2026): the agent itself decides when to compress, via two tools — `manage_context` (compress everything since the last compression into a summary, archive the raw messages externally under a summary ID) and `query_memory` (retrieve from a given summary ID with a query). **Lossless** (raw content is archived, never discarded), **agent-initiated** (not threshold-triggered), **proactive** (before the limit). Qwen3.5-9B post-trained: BrowseComp-Plus 57.0→72.7%, DeepSearchQA 36.7→42.5%, SWE-Bench Verified 48.9→53.0%; peak tokens −20%.

The design axis these four lay out is worth naming explicitly, because the repos sit on it too: **who decides to compact** (external threshold → browser-use, Magnitude, ReSum) vs **the policy itself** (AgentFold, Context-Folding, ACM), and **whether the raw data is recoverable** (ACM: yes, via `query_memory`; everyone else: no).

#### Progress state as a first-class object

**PABU: Progress-Aware Belief Update** (arXiv:2602.09138, Jiang/Ge/Cai/Song, Feb 2026). Replaces the trajectory with a belief `[q, p_n, 𝒜_att, 𝒜_available, 𝒪_saved]`:
- `q` — user query, retained throughout
- `p_n` — **current progress estimate** (a task-specific milestone)
- `𝒜_att` — **actions already attempted under the same progress value**
- `𝒜_available` — actions from the current observation
- `𝒪_saved` — observations kept by a *learned* retention policy

Each step the model autoregressively predicts retention → progress update → action. The `𝒜_att` mechanism is elegant for our purposes: when progress does **not** advance (`p_{n+1} = p_n`), the executed action is appended to the attempted set, which is exactly a principled, learned version of browser-use's action-hash loop detector. Results on AgentGym (8 environments): **81.0% completion vs 65.4% prior SOTA, and 9.5 vs 13.0 average steps (−26.9%)**. Ablation: progress prediction and selective retention are *both* necessary.

#### Action-effect verification and stuck escape

**"Don't Act Blindly" / VeriGUI** (arXiv:2604.05477, Zhang et al., Baidu, Apr 2026). A **Thinking–Verification–Action–Expectation (TVAE)** cycle: each step the model emits a predicted `Expected Effect E_t`, and at step t+1 must emit a binary verification `V_t ∈ {SUCCESS, NO_CHANGE}` comparing the actual screen against `E_{t-1}`. *"The expected effect predicted at step t becomes the verification hypothesis at step t+1. This temporal dependency enforces causal consistency across steps, ensuring that errors cannot be ignored."* On `NO_CHANGE`, structured `[Diagnose]` and `[Recovery]` tags force an *alternative* action rather than a repeat.

Training exploits **failure idempotency** — incorrect GUI actions usually leave the screen unchanged — to synthesize failure trajectories (30% of SFT data, optimal 70:30 success:failure). GRPO rewards are asymmetric to punish self-deception: correct verification +1.0, missed failure −0.5, **hallucinated success −2.0**.

The headline evidence for loop mechanisms: **baseline models repeat failed actions in 72.3% of failures; Loop Rate drops from 30% (baseline) to 24.3% (3B) and 15.6% (7B)**. Recovery Success Rate 51.1% (3B) / 52.5% (7B) on AndroidControl-High; without synthetic failures in SFT, verification capability never develops (RSR stays ~30%).

This is the formalized, trained version of Agent-E's mutation-observer feedback and browser-use's `evaluation_previous_goal`.

#### Where long-horizon runs actually break

**Odysseys** (arXiv:2604.24964, Jang/Koh/Fried/Salakhutdinov, CMU, Apr 2026): 200 long-horizon live-web tasks, rubric-scored (6.1 rubric items/task, 1,225 criteria), tiered easy (≤5 steps, ≤3 domains) / medium / hard. Best model: **44.5% perfect success**; "Trajectory Efficiency" (rubric score per step) is **1.15% even for frontier agents**; ~30 min wall-clock per run.

The failure modes map directly onto the mechanisms above:
- **Opus 4.6 hit step limits on 39% of tasks with empty outputs** — over-investing in research, never transitioning to deliverable production. This is precisely the failure browser-use's 75% budget warning + forced-`done` and Skyvern V2's WRAP-UP MODE are built to prevent, and it is the strongest evidence in the survey that budget-aware behavior change matters.
- **GPT-5.4: "inaction despite correct high-level reasoning"** — detailed plans, then termination after few browser interactions.
- Both stall on high-fanout tasks, completing subsets rather than full cross-site synthesis.

**"When Web Agents Finish but Still Fail"** (arXiv:2606.20724, Sogani/Rui/Vaidyanathan/Agarwal/Yan/Venkataraman, Jun 2026): trace-level analysis over 1,679 verified records identifies three modes hidden by final-answer scoring — **context-bound search loops**, **premature termination on partial answers**, and **synthesis collapse**. Completion rate rose 50.7→96.0% while binary accuracy stayed "far below completion": a large completion–correctness gap. Diagnostic, not prescriptive — no runtime mitigation is evaluated.

#### Runtime observation shaping

**WebChallenger** (arXiv:2606.10423, Hwang/Zhang/Padwal, Jun 2026): 56.3% WebArena, 48.7% VisualWebArena, 51.0% Online-Mind2Web, 70.9% WorkArena with open-weight models, no fine-tuning. Per step the agent sees a **task-focused page summary** from a three-stage pipeline (section summaries → LLM selects relevant sections → extract task-pertinent details → synthesize), appended to a compact interaction history `h_t`. `PageMem` caches per-section summaries across revisits. Stuck escape is an **end-task verification workflow**: selecting `end-task` triggers an LLM check over instruction + full history that can reject the termination and demand alternative actions. Averages ~1,850 tokens/prompt.

#### The important counterpoint

**"Are Online Skill and Memory Modules Always Worth Their Tokens? A Budget-Constrained Study of Web Agents"** (arXiv:2606.15017, Hajimiri, Aminbeidokhti, Dolz, Ben Ayed, Laradji, Gella, Gontier, Jun 2026). Compares runtime skill/memory augmentation against baselines **at matched total token budgets**. Finding: under equitable budgets, simpler baselines often perform comparably — the modules' gains are partly just "more tokens spent." Conclusion: evaluate whether runtime augmentation earns its token cost rather than assuming it helps.

This is the right frame for reading everything above. Note that AgentFold and Context-Folding survive it cleanly (they *reduce* tokens 10–13× while improving accuracy); undifferentiated "add a memory module" designs are the ones at risk.

**AWM (Agent Workflow Memory**, arXiv:2409.07429, ICML 2025): included for completeness since it was named in the brief, but it is mostly compile-time. Its *runtime*-relevant half is **online induction** — inducing workflows from self-generated trajectories judged correct by an evaluator, with no annotated examples. +24.6% relative on Mind2Web, +51.1% on WebArena, with **fewer steps** on successful WebArena tasks; online AWM gains 8.9–14.0 absolute points as train/test distribution gaps widen.

---

## Synthesis: the runtime toolkit

Eight distinct mechanisms, ranked by how many of the six systems implement them and by the strength of the evidence that they help. "Prevalence" counts browser-use, Skyvern (any engine), Agent-E, Magnitude, nanobrowser, and the paper literature as a seventh voice.

---

### 1. Ephemeral observation, persistent decision trace
**Prevalence: 6/6 — universal, and the single most important design decision.**

The page (DOM tree, screenshot, accessibility tree) is *never* accumulated. Exactly one page state is in context at a time; what persists across steps is a compact record of what the agent decided and what resulted.

| System | Implementation |
|---|---|
| browser-use | `MessageHistory` has one `state_message` slot, replaced each step; only the current screenshot is attached |
| nanobrowser | `addStateMessageToMemory()` → invoke → `removeLastStateMessageFromMemory()` (`navigator.ts:173-201`) |
| Skyvern step engine | `PROMPT_ACTION_HISTORY_WINDOW = 1`; only the current scrape is in-prompt |
| Skyvern V3 | `_compact_transcript()` keeps the newest `observe`/`get_html` per tool, elides all older ones in place |
| Agent-E | Inner chat is discarded at the boundary; helper is "stateless"; DOM fetched on demand |
| Magnitude | Tail-keep at 10% of soft cap; large file content only via explicit `compact(files)` |

Papers: AgentFold's `I_{t-1}` (exactly one full interaction) → **~7k vs ~91k tokens at 100 turns**. PABU's learned `𝒪_saved` retention. WebChallenger's synthesized task-focused summary replacing the raw page.

**For NetGent v2:** if you build only one thing from this document, build this. Everything else is refinement on top of it.

---

### 2. Step/turn budgets plus a consecutive-failure counter
**Prevalence: 6/6 — universal, but the *values* vary by 50×, which is itself informative.**

| System | Step budget | Failure budget | Retry semantics |
|---|---|---|---|
| browser-use | `max_steps=500` | `max_failures=5`, resets to 0 on success | Failure counted, step advances |
| Skyvern step engine | `MAX_STEPS_PER_RUN=10` | `MAX_RETRIES_PER_STEP=5` | Failed step **re-executed** as new `Step` row with `retry_index+1` |
| Skyvern Task V2 | `DEFAULT_MAX_ITERATIONS=50` planner iterations × 25 steps/block | — | Failed mini-goal re-planned, not re-issued |
| Skyvern V3 | 5 simultaneous: turns 80, tool calls 300, action steps (≥20), tokens 1.5M, deadline 1800s | LLM-call retries only (`max_call_retries=2`) | Only the *LLM call* is retried (side-effect-free); never the browser action |
| Agent-E | 50 planner rounds / 10 executor rounds | — | — |
| nanobrowser | `maxSteps=100` | `maxFailures=3` | — |

Two design lessons worth carrying:
- **Skyvern V3's multi-budget approach** is more robust than a single step counter, because different runaway modes have different signatures (a perception spiral burns turns and tokens without burning action steps). Its comment is explicit: the token cap exists so "a runaway trips this as `budget_exhausted` instead of surfacing as a provider context-window error."
- **Only retry what is side-effect-free.** V3 retries the LLM call but never the browser action, "unlike a whole-task retry, which would re-execute prior clicks/types."

---

### 3. Structured per-step self-evaluation of the previous action
**Prevalence: 5/6 systems. Best-evidenced single mechanism in the literature.**

The agent is *forced by schema* to judge whether its last action worked, before choosing the next one.

- browser-use: `evaluation_previous_goal` (required field) — "Clearly state success, failure, or uncertain," with `Verdict: Success/Failure` examples.
- Skyvern step engine: `user_goal_stage` + `user_goal_achieved`, plus a *separate* verification LLM call every step (`check_user_goal_complete`).
- nanobrowser: planner's `observation` + `challenges`, run every 3 steps and on every claimed completion.
- Agent-E: mechanized rather than prompted — the mutation observer returns *"As a consequence of this action, new elements have appeared in view: {diff}. This means that the action is not yet executed and needs further interaction."*
- Skyvern V3: settle-probe gating on `finish(completed)`, deferring up to twice so the model re-verifies against a loaded page.

**Evidence: strongest in the survey.** VeriGUI's TVAE cycle makes the prediction explicit (`E_t` at step t is the verification hypothesis at t+1) and shows baselines repeat failed actions in **72.3% of failures**, with loop rate falling 30% → 15.6% once verification is trained in — plus the asymmetric reward (hallucinated success −2.0) needed to prevent the model from lying to itself.

**For NetGent v2:** the "expected effect → verify next step" formulation is a better fit for an NFA than free-text `evaluation_previous_goal`, because a predicted post-condition is exactly an edge's expected target state. This is the most direct bridge between the runtime loop and your compile-time formalism.

---

### 4. An explicit progress object, separate from the transcript
**Prevalence: 5/6. Rising fast; the newest additions to browser-use and Skyvern are both here.**

A structured artifact that survives history truncation and compaction, because it lives *outside* the message list.

| Form | System |
|---|---|
| Server-side plan with per-item status (`[x] [>] [ ] [-]`) | browser-use `PlanItem` list, driven by `plan_update` / `current_plan_item` |
| Carried-forward subgoal checklist with evidence | Skyvern V2 `required_subgoals: [{subgoal, satisfied, evidence}]` |
| `todo.md` in a real file system, injected untruncated | browser-use `<todo_contents>` |
| Scratchpad directories (`plans/`, `thoughts/`, `results/`) | Magnitude |
| `<plan>` message re-issued every planner interval | nanobrowser |
| Prose `plan` in planner JSON, revised on demand | Agent-E |
| Learned scalar progress `p_n` | PABU |

Three details that matter more than the mechanism itself:

1. **Skyvern's "satisfied" definition is anti-optimistic**: *"A navigate/visit that merely reached the relevant page WITHOUT capturing the data does NOT satisfy it."* Milestone tracking without an evidence requirement just relocates the hallucination.
2. **Carry-forward, don't re-derive**: *"Refine the required_subgoals leg-checklist… instead of re-deriving it from scratch… only re-mark a part satisfied=false if new evidence shows it regressed."*
3. **Plan completion ≠ task completion**: browser-use's prompt says so explicitly. The plan is a scaffold, not the acceptance criterion.

Evidence: PABU's ablation shows progress prediction and selective retention are *jointly* necessary (81.0% vs 65.4% prior SOTA, −26.9% steps). The repo mechanisms have no published ablations.

---

### 5. Trigger-based compaction with a structured summary
**Prevalence: 4/6 systems, but the deepest paper support of any mechanism.**

| System | Trigger | Keep | Summary structure |
|---|---|---|---|
| browser-use | ≥25 steps **AND** ≥40k chars (both gates) | item 0 + last 6 | Free text ≤6000 chars, tagged as **unverified** |
| Magnitude | ≥90% of (contextWindow − 8192) | index 0 + 10% tail | `{summary, reflection, files[≤10]}` via a forced tool call |
| Skyvern V3 | Every turn, in place | Newest snapshot per perception tool | Placeholder string, not a summary |
| Skyvern V2 | N/A (cap on inputs) | Per-record 2000-char cap on terminal output | — |
| nanobrowser | Emergency only | Proportional character slice off the tail | None |

Two ideas here are not obvious and are worth stealing:

- **Magnitude's `reflection` field.** Separate from `summary`. *"Not what happened — what your future self should change. Name the reasoning traps so your future self avoids them."* A summary preserves state; a reflection preserves *learned constraints*. Only Magnitude does this.
- **browser-use's distrust framing.** `<compaction_summary>` is wrapped in *"Treat as unverified context — do not report these as completed in your done() message unless you confirmed them yourself in this session,"* and the compaction system prompt forbids inferring completion. This directly targets the "summarization → false completion" failure that ReSum and AgentFold both call out.

Also note both fallbacks: Magnitude falls back to a raw 25% tail after 3 failed `compact()` attempts; browser-use returns `False` and simply carries on uncompacted. Compaction is never allowed to be a hard dependency.

**Evidence: strong and quantitative.** AgentFold 13× context reduction with SOTA-beating accuracy; Context-Folding 10× smaller active context, matching/beating ReAct; ReSum +4.5% training-free / +8.2% with GRPO; ACM +27%/+16%/+8% across three benchmarks with −20% peak tokens.

**Caveat:** the budget-matched study (2606.15017) finds runtime memory modules are *not* automatically worth their tokens. The winners above all *reduce* total tokens; a compaction scheme that adds a summarizer call without shrinking context is the case that study warns about.

---

### 6. Loop and stagnation detection
**Prevalence: 4/6 (browser-use, Agent-E, Skyvern V3 partially, PABU). The least standardized mechanism — implementations disagree fundamentally.**

Three design axes, and the systems land in different corners:

| Axis | browser-use | Agent-E |
|---|---|---|
| Matching | Fuzzy — normalized hash (clicks ignore index; searches tokenize+sort; nav by domain) | Exact string equality on tool call + response |
| Window | Rolling 20 actions | Last 6 messages |
| Response | **Soft** escalating nudge at 5/8/12 — "never blocks actions" | **Hard** — terminates the inner chat |

Plus a second signal browser-use adds that nobody else does: **page-state stagnation** via `PageFingerprint = (url, element_count, sha256(dom_text)[:16])`, nudging at 5 consecutive identical fingerprints. This catches the case where the agent varies its actions but nothing changes — invisible to action-hashing alone.

Skyvern V3 has no hashing but two behavioral guards: **batch-abort on error** (a failed call skips the rest of the turn's batch so the model re-plans from the error rather than acting on a stale assumption) and a prompt-level anti-inspection-spiral rule.

PABU's `𝒜_att` is the principled version: *actions attempted while progress has not advanced*. It fires on the right condition — repetition is only a problem when it isn't producing progress — which is exactly what browser-use's 12-threshold nudge hedges about in prose ("If you are making progress with each repetition, keep going").

**Evidence: indirect but real.** VeriGUI measures baseline loop rates at 30% and cuts them to 15.6%; the trace-diagnostics paper names "context-bound search loops" as one of three persistent failure modes. No repo has published an ablation of its own detector.

**For NetGent v2:** browser-use's normalized hashing is the piece to copy — index-invariant click hashing in particular, since raw-param hashing misses the common case of re-clicking the same button at a shifted index. But gate the nudge on *progress not advancing* (PABU) rather than on repetition count alone.

---

### 7. Budget-aware behavior change ("wrap-up mode")
**Prevalence: 3/6, all recent. Highest-value-per-line mechanism in this document.**

Distinct from mechanism #2: not *stopping* at the budget, but *changing strategy* as it approaches.

- **browser-use, at 75%**: injects a warning naming steps used/remaining and ordering priorities — "(1) consolidate your results (save to files…), (2) call done with what you have. Partial results are far more valuable than exhausting all steps with nothing saved." Then at the last step, `AgentOutput` is swapped for `DoneAgentOutput` so `done` is the *only* available tool.
- **Skyvern Task V2, in the last 20% of iterations** (`DEFAULT_CONVERGE_PCT = 20`): WRAP-UP MODE — "Work ONLY the required_subgoals still marked satisfied=false… Do NOT start new legs, broaden scope, explore optional/secondary info, or re-verify already-satisfied parts."
- **Skyvern CUA path, at the last step**: `add_stop_and_summarize()` instead of a normal tool result.

The system prompt even asks for arithmetic: *"For large multi-item tasks (e.g. 'search 50 items'), estimate the per-item cost from the first few items. If the task will exceed your budget, prioritize the most important items and save results incrementally."*

**Evidence: the clearest failure-mode match in the survey.** Odysseys found **Opus 4.6 hit step limits with empty outputs on 39% of tasks** — over-investing in research and never producing a deliverable. Two of the three failure modes in the trace-diagnostics paper (premature termination on partial answers, synthesis collapse) are the same coin. Restricting the tool schema at the last step, rather than merely asking for a summary, is the version most likely to actually fire.

Agent-E, nanobrowser, and the Skyvern step engine have **nothing** here — they just fail at the cap.

---

### 8. Two-level loop: cheap inner actor, periodic outer planner/verifier
**Prevalence: 4/6. Converging on "periodic, not every step," with browser-use as the notable defector.**

| System | Outer cadence | What crosses the boundary |
|---|---|---|
| nanobrowser | Every 3 steps (`planningInterval`) + on any claimed completion | `<plan>` message; navigator completion is re-validated |
| Agent-E | Every subtask | Only the last message from the nested chat (`summary_method`); everything inside is discarded |
| Skyvern V2 | Every mini-goal (≤50 iterations) | `task_history` record + refined `required_subgoals` |
| Skyvern step engine | Every step (`check_user_goal_complete`) | Complete/Terminate verdict |
| browser-use | **None** — single loop with in-band `plan_update` | — |

The boundary is where the compression happens. Agent-E is the extreme case: a 10-turn inner tool-calling loop, with DOM dumps and retries, collapses to one summary string plus a URL. That is architectural compaction — you get it for free without a summarizer call, because the sub-agent's context is simply thrown away.

Note the trajectory: browser-use **removed** its planner-interval and multi-agent structure and replaced it with in-band `plan_update`/`current_plan_item` fields on the single actor. nanobrowser, forked from the older design, kept it. This is a genuine open question, not settled practice — but browser-use's move suggests that a structured plan field on one agent may capture most of the benefit at a fraction of the token cost, which is exactly what the budget-matched study (2606.15017) would predict.

---

### Cross-cutting observation for NetGent v2

The five current systems have independently converged on the same core: **one page state in context, a compact typed record per step, an out-of-band progress object, and a budget that changes behavior before it terminates.** They diverge most on loop detection (soft-nudge vs hard-terminate, fuzzy vs exact) and on whether to keep a second planner agent.

The 2026 literature's contribution is to make three of these *learned* rather than hand-tuned: which observations to keep (PABU's retention policy), when and at what scale to fold (AgentFold's directive), and whether the last action actually worked (VeriGUI's verification head). For an NFA-based system, the VeriGUI framing is the most directly transferable — a predicted post-condition per action *is* an edge's expected target state, which means runtime verification and compile-time structure can share one representation rather than two.

---

## Verification notes

### Confirmed by reading source in this session

Every file path, class name, function name, constant, and default value below was read directly from a local clone. Line numbers refer to the SHAs in the table at the top.

**browser-use** — `MessageHistory`/`HistoryItem`/`MessageManagerState` (`message_manager/views.py`); `agent_history_description` (`:153`), `prepare_step_state` (`:199`), `maybe_compact_messages` (`:216`), `_update_agent_history_description` (`:304`), `create_state_messages` (`:424`) in `message_manager/service.py`; `MessageCompactionSettings` (`views.py:35`), planning/loop settings (`views.py:76-91`), `PageFingerprint` (`:95`), `_normalize_action_for_hash` (`:110`), `compute_action_hash` (`:151`), `ActionLoopDetector` (`:157`), `AgentState` (`:248`), `AgentBrain` (`:381`), `AgentOutput` (`:388`); `_maybe_compact_messages` (`service.py:1156`), nudge call sites (`:1147-1151`), `consecutive_failures` handling (`:1230-1236`), `_update_plan_from_model_output` (`:1411`), `_render_plan_description` (`:1445`), `_inject_replan_nudge` (`:1457`), `_inject_exploration_nudge` (`:1472`), `_inject_loop_detection_nudge` (`:1488`), `_update_loop_detector_actions` (`:1502`), `_inject_budget_warning` (`:1536`), `_force_done_after_last_step` (`:1562`), `_force_done_after_failure` (`:1574`), run loop (`:2603`), ctor defaults (`:165-208`); `AgentMessagePrompt` (`prompts.py:104`), `_get_agent_state_description` (`:337`), `_get_step_meta_description` (`:365`), `get_user_message` (`:404`); `system_prompt.md` `<input>`/`<agent_history>`/`<file_system>`/`<planning>`/`<task_completion_rules>`/output format; `FileSystem.describe` (`:816`) and `get_todo_contents` (`:889`); beta `_compaction_replay_start_seq` (`:1550`) / `_events_after_terminal_compaction` (`:1559`) / `_terminal_tool_memory` (`:2436`).

**Skyvern** — `config.py` constants (`:155,156,178,184,185,208`); `get_action_history` (`services/action_service.py:11`); `agent.py` `execute_step` (`:1510`), `agent_step` (`:2291`), Yutori CUA path (`:3560`), `check_user_goal_complete` (`:4094`), `_build_extract_action_prompt` (`:4928`), `_get_action_results` (`:5590`), retry logic (`:6718-6796`), long-running warning (`:7441`); `prompts/skyvern/extract-action.j2` full schema; `task_v2_service.py` `:105,109,112,655,672,993-1006,1270`; `prompts/skyvern/task_v2.j2` `required_subgoals` (`:81`) and WRAP-UP MODE (`:136`); `planner_levers.py:9,31,40`; `taskv3/loop.py` docstring, `ToolSpec` (`:50`), `NO_TOOL_CALL_NUDGE` (`:141`), `make_finish_tool` (`:158`), `_compact_transcript` (`:219`), `run_agent_tool_loop` (`:255`), budget checks and batch-abort (`:320-470`); `taskv3/engine.py:36-53` constants and `SYSTEM_PROMPT`.

**Agent-E** — `detect_llm_loops.py::is_agent_stuck_in_loop` (read in full); `prompts.py` PLANNER_AGENT_PROMPT and BROWSER_AGENT_PROMPT; `autogen_wrapper.py:43` (round defaults), `:121` (`my_custom_summary_method`), `:135` (`reflection_message`), `:147-160` (`register_nested_chats`), `:276,290-307` (agent construction + loop-detection wiring), `:368-374` (planner chat, `clear_history` commented out); `dom_mutation_observer.py::add_mutation_observer`; `skills/click_using_selector.py:45-58` and `skills/press_key_combination.py:43-63`; `memory/static_ltm.py` (read in full); `agents/browser_nav_agent.py:28-73`.

**Magnitude** — `compaction/README.md` (read in full); `constants.ts:42-70` (all seven constants); `compaction/estimate.ts::computeCompactionSizing`; `compaction/prompt.ts::COMPACTION_REFLECTION_PROMPT`; `storage/src/types/config.ts:32-64` (`softCapRatio: 0.9`, `softCapMaxTokens: 200_000`, `computeContextLimits`); `window/projection.ts:1288-1294` (fallback tail); `scratchpad/src/constants.ts`.

**nanobrowser** — `types.ts:11-33` (all defaults); `executor.ts:133-192, 233-267, 309, 329`; `messages/service.ts:14` (`maxInputTokens`), `:199` (`addPlan`), `:211` (`addStateMessage`), `:244` (`removeLastStateMessage`), `:370` (`cutMessages`, read in full); `agents/navigator.ts:173-201, 275-327`; `prompts/templates/planner.ts` output schema.

### Negative results confirmed by search, not just absence of notice

- **browser-use has no procedural memory.** `grep -rn 'mem0\|procedural'` across the entire repo (`.py`, `.toml`, `.md`) returns **zero** hits. The mem0-based `Memory` module of older versions is gone; `maybe_compact_messages` occupies that role now.
- **Skyvern's step engine has no action-hash or repetition counter.** Searched for `repeated`, `same action`, loop/stuck terms across `forge/agent.py`; only prompt-level guidance exists.
- **nanobrowser has no summarization.** `cutMessages()` is the only history-shrinking path and is pure truncation.
- **Agent-E has no compaction.** Its only cross-step compression is the nested-chat `summary_method` boundary.
- **Magnitude has no todo/plan mechanism** in the agent loop; `grep -rln 'todo\|Todo' packages/agent/src/prompts/` returns nothing.

### Corrections to premises in the brief

- **Magnitude is not currently a browser agent.** At `c3ace06` it is a local-model coding/desktop agent (README: "Open source agent with local models built in. Fully private and offline"); browser access is a Chrome *skill*. I found no `act()`/`check()` browser-testing API. I substituted **nanobrowser** as the additional browser-native system and reported Magnitude for its compaction subsystem only. Its compaction findings are real and verified — but they are not browser-agent findings.
- **browser-use's "planner interval" no longer exists.** Older versions had a separate planner LLM on an interval; the current code has no such thing. Its replacement is the in-band `plan_update`/`current_plan_item` fields on the single actor plus `enable_planning` settings. nanobrowser, forked from the older design, still has `planningInterval: 3`. I have **not** verified the exact removal commit (shallow clones, no history).

### Secondhand — read via abstract/HTML fetch, not full PDF

All paper claims below come from arXiv abstracts or HTML full-text rendered through a summarizing fetch, **not** from reading the PDFs end to end. Treat specific numbers as reported-not-verified.

- **Solid, structural detail obtained** (HTML full text, field names quoted): **AgentFold** (2510.24699) — context components, folding directive format, 7k vs 91k at 100 turns; **ACM** (2607.23809) — tool names, lossless archival, three benchmark deltas; **PABU** (2602.09138) — five belief components, three-stage autoregressive update, 81.0% vs 65.4%; **VeriGUI / "Don't Act Blindly"** (2604.05477) — TVAE cycle, reward asymmetry, 72.3% baseline repeat rate, loop rate 30%→15.6%; **Odysseys** (2604.24964) — tiering, 44.5% best, 39% empty-output step-limit finding; **WebChallenger** (2606.10423) — three-stage observation pipeline, PageMem, end-task verification.
- **Abstract-level only**: **ReSum** (2509.13313) — +4.5% / +8.2% figures are from the abstract; I did not verify the summarization trigger threshold or summary schema in the paper body. **Context-Folding** (2510.11967) — "10× smaller active context" is from the abstract; branch/return tool signatures not verified. **"When Web Agents Finish but Still Fail"** (2606.20724) — three failure modes from the abstract; the fetch explicitly notes no runtime mitigations are proposed. **AWM** (2409.07429) — numbers from a search summary plus abstract; I did not read the paper or the `zorazrw/agent-workflow-memory` repo.

### Flagged as unverified or low confidence

- **"Are Online Skill and Memory Modules Always Worth Their Tokens?"** (2606.15017): the fetch returned a PDF whose summary is directional ("not always worth their tokens," "simpler baselines often perform comparably") but gives **no specific numbers, benchmarks, or module names**. I am reporting the *thesis* only. If this counterpoint matters to a design decision, read the PDF — it is the single most consequential claim in the paper section and I have the weakest evidence for it.
- **"Signal-Driven Observation for Long-Horizon Web Agents"** (2606.06708): the fetch returned only generic description ("signals identify which page elements warrant inclusion") with **no concrete numbers, benchmarks, or mechanism detail**. I mention it in the WebChallenger vicinity but draw no conclusions from it. Treat as a pointer, not a finding.
- **FoldAct** (2512.22733) and **Recursive Language Models** (2512.24601) appeared in search results only. **Not fetched, not read, not cited above.**
- The AgentFold-vs-ReSum/ACON/ACE comparison ("prompting-only context-management techniques" vs a trained folding policy) came from a search-result synthesis, not from either paper's text. **ACON and ACE were never fetched** and I make no claims about them.
- Claims in mechanism §6 about "action deduplication using hashing of tool-argument pairs" and "progress detection when agent state hasn't changed in k steps" as *general practice* came from a search-result synthesis. The specific implementations I attribute to browser-use and Agent-E are code-verified; the framing of them as a broader field pattern is inference.

### Not investigated

Per instruction, I did no sub-agent delegation and stayed within these five repos plus the papers. Systems named in the field but **not examined**: Stagehand/Browserbase, Notte, lmnr-ai/Index, OpenAI CUA sample app, steel-browser, WebVoyager. Skyvern's `script_reviewer_v3`, self-heal, and cached-script paths were noticed but not read — they are compile-time/replay concerns, outside the brief. browser-use's `beta/service.py` was sampled (compaction-replay and plan-tool paths) rather than read in full; its 6811 lines likely contain additional runtime mechanisms I did not surface.

---

## Addendum: where NetGent's own BrowserAgent stands (2026-08-19)

Mapping `v2/src/netgent/agent/browser_agent.py` (+ `observation.py`, `sweep.py`) against the eight mechanisms above:

| # | Mechanism | NetGent today | Gap / next move |
|---|---|---|---|
| 1 | Ephemeral observation, persistent decision trace | ✅ Already the design: one fresh snapshot per step; history is one text line per step (`kind(index) reasoning -> FAILED: …`) | Aligned with the universal pattern |
| 2 | Step budget + failure counter | ◐ `max_steps` cap (25; per-run override). No consecutive-failure counter — a run can fail different actions every step to the cap | Add `max_failures`-style counter (browser-use: 5, reset on success) |
| 3 | Structured self-evaluation of previous action | ✖ Only free-text `reasoning`; failures fed back as history lines | Add an `evaluation_previous_goal`-style required field — or better, the VeriGUI framing: predict the post-condition, verify next step. A predicted post-condition **is** an NFA edge's target-state trigger, so runtime verification and the compiled artifact share one representation |
| 4 | Explicit progress object outside the transcript | ✖ None — at step 40 the agent knows the current screen + last 10 lines | Highest-value gap for long exploration runs: a small plan/todo object injected untruncated each step |
| 5 | Trigger-based compaction | ✖ (not needed yet: `decide()` sends only the last 10 history lines) | Becomes relevant only if history window widens; keep the last-k window instead |
| 6 | Loop/stagnation detection | ◐ Observation-equality stagnation (3 no-change steps → stuck) — this is the page-fingerprint idea, arguably the stronger half | Add normalized action-hashing for the complementary case (agent varies pages but repeats the same failing action); gate on progress, per PABU |
| 7 | Budget-aware wrap-up mode | ✖ Hits the cap and stops | Cheap win: at ~75% budget inject a wrap-up nudge; at the last step restrict the decision schema to done/stop |
| 8 | Two-level loop with a compression boundary | ◐ The form sweep is exactly this: deterministic outer orchestrator, scoped inner runs, verified outcomes, one shared memory | The NFA executor is the end-state of this idea: the "outer loop" compiled to zero-LLM |

NetGent's structural answer to long horizons remains the compile step itself — replaying the long part as a zero-LLM NFA sidesteps context exhaustion entirely (mechanism 1 taken to its limit). The table above is about the *exploration* agent, whose horizons will grow as `generate` matures. Priority order if hardening it: #4 (progress object), #3 (post-condition verification — doubles as compile-time trigger discovery), #7 (wrap-up mode), #2/#6 (failure counter + action hashing).
