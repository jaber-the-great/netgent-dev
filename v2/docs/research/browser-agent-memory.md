# Browser-agent memory — what a DOM-mode agent keeps between steps, and what NetGent's explorer should keep

**Question.** For agents that read the page as DOM / text / accessibility-tree (not pure-vision,
coordinate-clicking agents): what per-step state survives into the next prompt, how is it
serialised, what explicit working-memory fields exist, is there observation diffing, how is a long
horizon handled, and what crosses run boundaries? Then: which of it should NetGent's
[`explorer/`](../../src/netgent/agent/explorer/) adopt, given that our LLM runs **only at compile
time** and the trajectory must compile to atomic actions?

**Status.** Written 2026-08-26 against sources fetched and read the same day. Every source claim
cites a pinned commit and file:line. Every paper number is quoted as printed, with the table
extracted from the source HTML where possible (§7 says which). Companion docs:
[`browser-agent-architectures.md`](browser-agent-architectures.md) covers *role decomposition*;
[`runtime-long-horizon.md`](runtime-long-horizon.md) covered an earlier snapshot of this same
question (2026-08-19) — this doc supersedes its per-system findings and adds the memory-schema and
diffing axes it did not cover.

---

## Summary (10 lines)

1. **Nobody in DOM-mode keeps old observations.** browser-use, Skyvern, Notte and Agent-E all send exactly one page representation — the current one — and keep only a *decision trace* of prior steps. Notte makes this explicit: past `Observation` entries are matched and dropped when rebuilding the conversation (`notte_agent/agent.py:336-338`).
2. The trace is a **list of typed records**, not strings. browser-use's `HistoryItem` carries `evaluation_previous_goal / memory / next_goal / action_results / error` and renders itself (`agent/message_manager/views.py:15-63`); Skyvern's is a dict of `{action_type, element_id, reasoning, …}` + `{success, exception_message, …}` (`services/action_service.py:32-63`). NetGent's is a bare `f"{n}. {kind}({index}) {reasoning}{outcome}"` string (`explorer/graph.py:148`).
3. **How much trace** splits the field hard: Skyvern's default is **one** prior step (`PROMPT_ACTION_HISTORY_WINDOW: int = 1`, `config.py:208`); browser-use's default is **all** of them (`max_history_items = None`, `views.py:76`) with LLM compaction at step 25 / 40k chars; Notte keeps all and trims oldest-first on a token budget.
4. **Three working-memory fields recur verbatim** across independent codebases: `evaluation_previous_goal`, `memory`, `next_goal` (browser-use `AgentBrain`, `views.py:381-386`; Notte `AgentState`, `agent_types.py:18-26`; Skyvern's `user_goal_stage` / `action_plan`). NetGent has none of them.
5. **Observation diffing is standard and cheap.** browser-use marks elements new since last step with `*[` by diffing backend-node-id sets (`dom/serializer/serializer.py:756-762`); Agent-E attaches live `MutationObserver` output to each action's *return value* (`utils/dom_mutation_observer.py:30-65`); Playwright MCP re-renders tab headers only when `changed`.
6. **The one measured number on history format** (arXiv:2604.01535, WorkArena L1, Table 5): no history 6,720 input tok; last-4 full 26,184; last-9 full 39,011; **last-9 diff-only 13,670** — and diff scores equal-or-better than full for gpt-5.1(low) (+4.2 vs +1.8) and o3-mini(high) (+6.4 vs +3.6) over no-history. History helps every model; diff buys ~⅓ the tokens.
7. **Long horizon = summarise-and-truncate, not sliding window.** browser-use replaces old items with one `<compacted_memory>` block, keeping item 0 + last 6 (`message_manager/service.py:216-302`); Magentic-UI's OmniAgent uses a five-heading structured handoff summary (`teams/omniagent/_compaction.py:23-65`); Lumen folds sub-goals into a persistent list that survives compaction.
8. **Cross-run memory is exactly what NetGent's artifact already is.** Stagehand's cache, Lumen's on-disk `ActionCache`, AWM's induced workflows (+51.1% rel. on WebArena, arXiv:2409.07429) and SkillWeaver's synthesised APIs (+31.8% rel. WebArena; +54.3% cross-agent, arXiv:2504.07079) are all "compile the trajectory into something replayable" — our NFA is the strongest form. Do not rebuild it inside the explorer.
9. **Recommendation:** replace the history string with a typed `StepRecord`; add `evaluation` / `memory` / `next_goal` to `AgentDecision`; add an **element-diff line + new-alert-text line** to the observation; render full fields for the last 3 records and compact lines for older ones; add task-boundary compaction so a 21-form sweep stops silently losing its past at `history[-10:]`.
10. **Cost:** measured today ≈ **2,120 input tokens/step** (40 elements). The full proposal lands ≈ **2,300** (+8%) input and +50–90 output tokens/step. The diff line is the only item with an evidence-backed accuracy payoff; everything else is cheap insurance.

---

## 1. Where NetGent stands today

Read [`explorer/graph.py`](../../src/netgent/agent/explorer/graph.py) once and the whole memory
design is on two screens. There are four stores.

| Store | Lives in | Contents | Shown to the LLM? |
|---|---|---|---|
| `BrowserAgent.history` | the agent object, **persists across `run()` calls** (`browser_agent.py:69`) | `list[str]`, one line per acted step | **yes**, last 10 (`llm.py:42`) |
| `AgentState["steps"]` | LangGraph state, `Annotated[..., operator.add]` (`graph.py:40`) | `list[AgentStep]` — the compilable trajectory | no |
| `AgentState["prev_observation"]` | LangGraph state | the previous observation **string**, used only for equality (`graph.py:72-74`) | no |
| `AgentState["texts_seen"]` | LangGraph state, capped at 400 (`graph.py:82-92`) | every distinct visible text seen | **no** — post-run only, read by `evals/sweep.py` |

The prompt is assembled in one f-string:

```python
# src/netgent/agent/llm.py:42-43
hist = "\n".join(history[-10:]) if history else "(none yet)"
prompt = f"{system}\n\nTASK: {task}\n\nRECENT STEPS:\n{hist}\n\nOBSERVATION:\n{observation}\n\nNext action:"
```

and the history line is written in one place:

```python
# src/netgent/agent/explorer/graph.py:145-148
outcome = f" -> FAILED: {error}" if error else ""
if error is None and isinstance(action, WaitAction):
    outcome = f" -> DONE WAITING: you already watched/waited {action.seconds:g}s. Do NOT wait again."
history.append(f"{n}. {decision.kind}({decision.index}) {decision.reasoning}{outcome}")
```

**Measured size** (run 2026-08-26; `SYSTEM_PROMPT` measured directly, observation measured by
calling `format_observation` on synthetic `DomSnapshot`s of realistic shape — real element names and
values are longer, so treat these as a *lower bound*):

| Component | chars | ~tokens |
|---|---|---|
| `SYSTEM_PROMPT` | 4,057 | 1,014 |
| observation, 10 elements + 25 text lines | 2,087 | 521 |
| observation, 25 elements + 25 text lines | 2,725 | 681 |
| observation, 40 elements + 25 text lines | 3,367 | 841 |
| observation, 60 elements + 25 text lines | 4,215 | 1,053 |
| history, 10 lines (mean 94 chars/line) | 938 | 234 |
| **total prompt @ 40 elements** | **8,482** | **≈2,120** |

So the history is **11% of the prompt** and the system prompt is 48%. There is a lot of headroom.

**What is structurally missing**, judged against every system below:

- The history is **lossy in a specific way**: it records what the model *said it would do*, not what
  the page *did*. A click that resolves, dispatches, and changes nothing records as a clean success.
  Our only counter-signal is `no_progress` (`graph.py:72-78`), which is invisible to the LLM — it
  only ends the run at `MAX_REPEAT = 3`.
- `prev_observation` is compared but never *differenced*. The information needed for a diff line is
  already in state and thrown away.
- `texts_seen` is accumulated for the sweep's success check but never shown, even though the code
  comment (`graph.py:79-81`) explains exactly why transient banners matter to the model too.
- `history[-10:]` is a hard truncation with no summary. In a 21-form sweep — the case
  `BrowserAgent.history` was explicitly built for (`browser_agent.py:67-69`) and that `note()`
  marks up (`browser_agent.py:71-73`) — the cross-task memory is gone after 10 lines.
- `AgentDecision` (`decision.py:18-43`) has `reasoning` only. No progress field, no goal field, no
  self-evaluation of the previous step.

---

## 2. The survey table

Columns are the brief's six axes. "Trace" = what is kept about prior steps.

| System (commit / version) | (1) kept vs dropped | (2) serialisation | (3) working-memory fields | (4) diffing | (5) long horizon | (6) cross-run |
|---|---|---|---|---|---|---|
| **browser-use** `28670f7` | current DOM + **current screenshot only**; all prior observations & screenshots dropped | ONE user message rebuilt each step: `<user_request><agent_history><agent_state><browser_state><read_state>`; history items rendered by `HistoryItem.to_string()` | `evaluation_previous_goal`, `memory`, `next_goal`, `thinking`, `current_plan_item`, `plan_update` | `*[` prefix on elements new since last step (backend-node-id set diff) | `max_history_items` (default `None` = all) → first item + `[… N omitted …]` + last N-1; LLM compaction every 25 steps above 40k chars → `<compacted_memory>` + item 0 + last 6 | `todo.md` + a real `FileSystem`; no cross-*run* store |
| **Skyvern** `d081a53` | current element tree only; **prior step's actions+results, window = 1** | JSON blob `action_history` inside a fenced `BEGIN_UNTRUSTED_WEB_PAGE_DATA` block | `user_goal_stage`, `user_goal_achieved`, `action_plan` (per step); `task_history_information`, `required_subgoals[]`, `thoughts` (TaskV2 planner) | none per-step; `hash_element` / `structural_identity` used for *cached-action* matching, not for the prompt | TaskV2 outer planner: `task_history` list of `{type, task, status, reason, extracted_data}`, capped at 2,000 chars per navigate output; `DEFAULT_MAX_ITERATIONS = 50`; WRAP-UP MODE prompt at low iterations | DB-backed cached action plan replayed when element hashes still match (`webeye/actions/caching.py`) |
| **Notte (falco)** `1802f00` | conversation **rebuilt from the trajectory every step**; `Observation` entries explicitly skipped; only the current one is added | real message list (litellm): system, task, then per step assistant(JSON completion) + user(action result), then current observation | `previous_goal_status` (`success`/`failure`/`unknown`), `previous_goal_eval`, `page_summary`, `relevant_interactions[]`, `memory`, `next_goal` | none | `Conversation(autosize=True)`: token-count each message, keep system + first user, drop oldest until under 80% of context | none in-repo |
| **Stagehand** `341433a` (v4) | `act`/`observe`/`extract` are **stateless single-shot**; no agent loop in the v4 reference at all | n/a — one prompt per primitive | none | none | n/a | **the whole point**: `observe()` → `ObserveResult` cached → `act(result)` with zero inference; v4 adds a managed server-side cache keyed on instruction + page content, model-independent |
| **Agent-E** `f218c3c` | planner keeps the conversation; **the browser helper is stateless per subtask** ("Helper is stateless and treats each step as a new task", `prompts.py:18`) | AutoGen message list between planner and nav agent | planner emits `plan` / `next_step` / `terminate` / `final_response` | **live `MutationObserver`**: each skill subscribes, and its return string appends "As a consequence of this action, new elements have appeared in view: …" | planner re-plans; `is_agent_stuck_in_loop` terminates on 3 identical (tool-call, tool-response) pairs | `user_preferences.txt` static long-term memory |
| **LaVague** `9024bb8` (archived, 2025-01) | screenshot + a growing instruction list | `ShortTermMemory.previous_instructions`: a bulleted string, failures prefixed `[FAILED]` (`core/memory.py:52-64`) | `current_state.internal_state.{user_inputs, agent_outputs}`, `last_engine` | none | none — unbounded string | prompt cache integration only |
| **Playwright MCP** `16cf228` / pw@main | full aria snapshot per tool response; `snapshot.mode: 'full' \| 'none'` | MCP tool result with `### Page`, `### Snapshot`, `### Result` sections; snapshot usually **written to a file** and returned as a link (`response.ts:307-317`) | none — the driving coding agent owns all memory | tab headers re-rendered only when `changed` (`response.ts:295-300`) | `outputMaxSize` budget deletes oldest output files (`response.ts:239-268`); the host agent's own compaction does the rest | none |
| **vercel-labs/agent-browser** `fbd046c` | snapshot printed to stdout; `@eN` refs **stale the moment the page changes** | CLI text in the coding agent's transcript; claimed ~200–400 tokens/snapshot vs ~3,000–5,000 for raw HTML | none | none (`snapshot -i -c` compacts, does not diff) | host agent's compaction | none |
| **Lumen** `b1ad26a` *(vision-first — out of primary scope)* | screenshots older than `keepRecent=2` replaced by placeholders | wire message list + a never-compressed `semantic` step list | `writeState` persistent JSON; `addFold()` sub-goal summaries injected as `COMPLETED SUB-GOALS:` | none (no DOM) | tier-1 screenshot compression, tier-2 LLM summary at 80% utilisation replacing the whole wire history with one `summary` anchor | on-disk `ActionCache` keyed `sha256(url:instructionHash)` + screenshot-similarity guard; `WorkflowMemory` (explicitly "AWM-inspired") |
| **Magentic-One / Magentic-UI** autogen@main, `d3c9d13` | orchestrator sees the group transcript | Task Ledger (facts + plan) rebuilt on stall; Progress Ledger = a 5-field JSON re-asked **every turn** | `is_request_satisfied`, `is_in_loop`, `is_progress_being_made`, `next_speaker`, `instruction_or_question` — each `{reason, answer}` | none | Magentic-UI OmniAgent: `COMPACTION_PROMPT` with fixed headings `## Task / Actions Completed / Current State / Remaining Work / User Preferences & Constraints` | none |

---

## 3. Per-system detail worth carrying

### 3.1 browser-use — the reference implementation of "one rebuilt message"

The message list handed to the model is **never appended to**. `MessageHistory` holds exactly a
system message, one state message, and zero or more per-step context messages
(`agent/message_manager/views.py:66-83`), and `_set_message_with_type` *replaces* the state slot
each step (`message_manager/service.py:556-568`). The whole trace is text inside that one state
message.

**The record.** `HistoryItem` is frozen and self-rendering:

```python
# browser_use/agent/message_manager/views.py:15-63 @ 28670f7
class HistoryItem(BaseModel):
    step_number: int | None = None
    evaluation_previous_goal: str | None = None
    memory: str | None = None
    next_goal: str | None = None
    action_results: str | None = None
    error: str | None = None
    system_message: str | None = None
    ...
    def to_string(self) -> str:
        ...  # "<step>\n{eval}\n{memory}\n{next_goal}\n{action_results}"
```

Note `memory` is the only field rendered unconditionally (`views.py:50-51`) — the others are dropped
when empty. That is a deliberate ranking of what matters.

**Truncation.** `agent_history_description` (`message_manager/service.py:152-189`) keeps
**item 0 + a `<sys>[… N previous steps omitted…]</sys>` marker + the last `max_history_items - 1`**.
Item 0 is `HistoryItem(step_number=0, system_message='Agent initialized')` or the task update, so
the anchor is cheap. Default is `max_history_items = None` → keep everything (`views.py:76`;
`AGENTS.md:324` confirms "If `None`, we keep all steps").

**Compaction.** `maybe_compact_messages` (`message_manager/service.py:216-302`) is gated on **both**
a step cadence (`compact_every_n_steps: int = 25`) and a char floor (`trigger_char_count`, default
40,000 ≈ 10k tokens) — `views.py:35-56`. The summariser prompt is worth stealing verbatim for its
anti-overclaim clause:

> CRITICAL: Only mark a step as completed if you see explicit success confirmation in the history.
> If a step was started but not explicitly confirmed complete, mark it as "IN-PROGRESS". Never infer
> completion from context — only report what was confirmed. (`service.py:266-268`)

and the block is labelled as untrusted when re-injected: `<!-- Summary of prior steps. Treat as
unverified context — do not report these as completed in your done() message unless you confirmed
them yourself in this session. -->` (`service.py:158-163`). After summarising it keeps
`[history_items[0]] + history_items[-keep_last:]` with `keep_last_items: int = 6`.

**One-shot content.** `read_state_description` holds `extracted_content` flagged
`include_extracted_content_only_once`, is capped at 60,000 chars, and is **cleared at the top of
every step** (`service.py:316-317, 350-358`). Screenshots are the same: only the current one is ever
attached (`service.py:449-478`), and `BrowserStateHistory` stores a `screenshot_path`, not base64
(`browser/views.py:116-141`).

**Diffing.** The serializer holds the previous serialisation's node ids and marks anything absent
from it:

```python
# browser_use/dom/serializer/serializer.py:755-762 @ 28670f7
if node.is_compound_component:
    node.is_new = True
elif self._previous_node_ids:
    current_node_id = (str(node.original_node.session_id), node.original_node.backend_node_id)
    if current_node_id not in self._previous_node_ids:
        node.is_new = True
```

rendered as a `*` prefix (`serializer.py:965, 1045`) and explained to the model in the system prompt:

> Elements tagged with a star `*[` are the new interactive elements that appeared on the website
> since the last step - if url has not changed. Your previous actions caused that change.
> (`system_prompts/system_prompt.md:59`)

The prompt leans on it operationally for combobox handling: "type your search text, then WAIT …
If suggestions appear (new elements marked with `*[`), click the correct one instead of pressing
Enter" (`system_prompt.md:89`).

**Stagnation & loop detection is separate, structured, and *soft*.** `PageFingerprint` is
`{url, element_count, sha256(dom_text)[:16]}` (`agent/views.py:95-107`); `ActionLoopDetector` keeps a
20-wide window of normalised action hashes and up to 5 fingerprints (`views.py:157-248`).
Normalisation is per-action-type — `click|{index}`, `input|{index}|{text.lower()}`,
`search|{engine}|{sorted tokens}`, `navigate|{full url}` (`views.py:110-148`) — and `wait`, `done`,
`go_back` are exempt (`service.py:1510`). It never blocks; it injects an escalating nudge at 5 / 8 /
12 repeats and at 5 consecutive identical fingerprints (`views.py:211-248`, `service.py:1490-1500`).
Compare NetGent's `MAX_REPEAT = 3` hard stop on exact observation-string equality: strictly harsher,
strictly less informative to the model.

Other injected context messages, all as separate `context_messages` rather than baked into history:
replan nudge after `planning_replan_on_stall = 3` consecutive failures (`service.py:1458-1472`),
planning nudge after `planning_exploration_limit = 5` steps with no plan (`1474-1488`), a **budget
warning at 75% of the step budget** (`1536-1560`), and a forced-done message on the last step
(`1562-1571`).

**Flash mode is a built-in ablation lever**: `AgentOutputFlashMode` deletes `thinking`,
`evaluation_previous_goal`, `next_goal`, `current_plan_item`, `plan_update` and requires only
`memory` + `action` (`views.py:457-485`). No published accuracy delta for it — see §7.

### 3.2 Skyvern — one step of history, and prompt caching instead of memory

The whole of Skyvern's per-step memory is this:

```python
# skyvern/config.py:208 @ d081a53
PROMPT_ACTION_HISTORY_WINDOW: int = 1
```

`get_action_history` (`services/action_service.py:11-63`) takes `steps[-1 - history_window : -1]`
(excluding the freshly-created current step, optionally appending it), and projects each action down
to `{action_type, element_id, status, reasoning, option, download}` and each result to
`{success, exception_type, exception_message, download_triggered, upload_file_triggered,
needs_followup, followup_message}` — **only the last result per action**, because chained clicks
produce a run of failures followed by the real outcome (`action_service.py:45-47`). The rest of the
step object never reaches the model.

The window widens only for completion *verification*, and the comment says why:

```python
# skyvern/forge/agent.py:4506-4512 @ d081a53
if task.include_action_history_in_verification or unwrapped_goals.big_goal_context is not None:
    # Evidence must be complete: the default 1-step window drops earlier actions of a
    # multi-step goal, making every-action verification unsatisfiable on 3+-step heals.
    full_run_window = task.max_steps_per_run or settings.MAX_STEPS_PER_RUN
    actions_and_results_str = await self._get_action_results(task, current_step=step, history_window=full_run_window)
```

**Working memory is in the output schema, not the history.** `extract-action.j2:17-19` asks for
`user_goal_stage` (prose: has the goal been achieved), `user_goal_achieved` (bool), and `action_plan`
("a quick summary of the actions you're going to take, and what order … and how that moves you
towards your overall goal"). None of these are fed back next step — they exist to force the model to
reason before emitting actions. `slim_output in ('safe','terse')` strips them entirely
(`extract-action.j2:16`), another ablation switch with no published number.

**Instead of history, Skyvern buys context back with caching.** `_build_extract_action_prompt`
renders `{template}-static` and `{template}-dynamic` separately, keys a cache variant off the
feature flags, and creates a Vertex explicit cache for Gemini keys (`agent.py:5724-5750`).
`stable_prefix_ordering` reorders the untrusted block so `action_history` comes *before* `elements`
in one variant and after in the other (`extract-action.j2:102-148`) — i.e. the prompt layout is
optimised for prefix caching, not for recency. Hard ceiling: `PROMPT_HARD_CEILING_TOKENS = 180_000`
(`utils/prompt_engine.py:57`) with a per-template drop chain below it.

**Dialogs are a one-shot channel**, exactly like NetGent's: `recent_dialog_messages_str` is rendered
once and then `context.clear_recent_dialog_messages()` (`agent.py:5784-5785`), with prompt text
telling the model that a validation-error dialog means *change the value, do not retry the same
INPUT_TEXT* (`extract-action.j2:72`).

**The long horizon lives one level up.** TaskV2 (`services/task_v2_service.py`) runs an outer planner
over a `task_history: list[dict]` of `{type, task, status, reason?, extracted_data?}`
(`task_v2_service.py:806, 948, 1235-1271`), capped because it is re-fed every iteration:

```python
# skyvern/services/task_v2_service.py:107-112 @ d081a53
# Cap a navigate block's recovered terminal output: task_history is re-fed to the
# planner every iteration, so an unbounded reasoning blob would grow context.
NAVIGATE_TERMINAL_OUTPUT_MAX_CHARS = 2000
NAVIGATE_STRUCTURED_OUTPUT_MAX_CHARS = 10 * NAVIGATE_TERMINAL_OUTPUT_MAX_CHARS
```

The planner's memory fields are worth copying for shape: `task_history_information` (what has been
collected, what is missing), `required_subgoals: [{subgoal, satisfied, evidence}]` **carried forward
between planning steps** ("Refine the … leg-checklist provided … instead of re-deriving it from
scratch", `task_v2.j2:130-133`), and a WRAP-UP MODE block injected when `iterations_remaining` is low
(`task_v2.j2:134-140`). `DEFAULT_MAX_ITERATIONS = 50`.

**Cross-run:** `webeye/actions/caching.py` replays a stored action plan for a task with the same URL
and navigation goal, walking forward while each remaining cached action's `element_hash` still
exists on the current page, and falling back to no-cache mode on the first miss. `hash_element` is
sha256 over the cleaned element JSON (`webeye/scraper/scraper.py:230-235`); `structural_identity`
(`scraper.py:238-258`) is the position-independent variant used to re-find a remounted control — and
its docstring states the failure policy NetGent should share: "a control whose only distinguishing
signal is volatile has no stable identity and must fail closed rather than be guessed at."

### 3.3 Notte (falco) — the cleanest statement of "ephemeral observation, persistent trace"

Notte rebuilds the whole conversation from the trajectory on every step:

```python
# packages/notte-agent/src/notte_agent/agent.py:320-348 @ 1802f00
for step in self.trajectory:
    match step:
        case AgentCompletion():
            conv.add_assistant_message(step.model_dump_json(exclude_none=True, context=dict(hide_interactions=True)))
        case ExecutionResult():
            conv.add_user_message(content=self.perception.perceive_action_result(step, include_ids=False, include_data=True))
        # observation or screenshot
        case _:
            # TODO: add partial info for previous?
            pass

last_obs = self.trajectory.last_observation
if last_obs is not None and last_obs is not Observation.empty():
    perceived_content = self.perception.perceive(obs=last_obs, progress=self.progress)
    ...
```

Two details worth stealing. First, `hide_interactions=True` on the replayed assistant message: the
*element ids* the model chose are stripped from history, because they are meaningless against a new
observation — the same reason NetGent's prompt says "Element indices are valid only for the current
observation" (`prompt.py:41`). Notte enforces it structurally instead of asking.

Second, the observation carries a *disclaimer* that turns the model into its own memory manager:

```python
# packages/notte-agent/src/notte_agent/falco/perception.py:15-17
DISCLAIMER = """You will see the following only once. If you need to remember it and you dont know
it yet, write it down in the memory."""
```

`AgentState` (`packages/notte-core/src/notte_core/agent_types.py:18-26`) is the browser-use field set
plus two: `page_summary` and `relevant_interactions: list[{id, reason}]` — a shortlist of element ids
the model thinks matter next, which is a cheap self-issued attention hint.

Trimming is token-budgeted, not count-budgeted: `Conversation(autosize=True)` counts tokens per
message with litellm, always keeps the system message and the **first user message (the task)**, and
pops oldest-first until under `conservative_max_tokens = 0.8 × max_tokens`
(`common/conversation.py:82-120`). Default `max_history_tokens` is `None` → the provider's full
context length (`notte-core/common/config.py:394`, resolved in `conversation.py:58-60`).

The observation itself carries progress inline: `* Current step: {progress.current_step}/{progress.max_steps}`
(`falco/perception.py:35`).

### 3.4 Stagehand v4 — no agent memory, because the cache *is* the memory

Worth stating precisely because the brief asked about "Stagehand v3 DOM mode": at
`341433acac46a305ad6c2f9a0445e907675f4fb4` the workspace is **version 4.0.0**, and the v4 docs tree
(`packages/docs/v4/`) contains `basics/{act,extract,observe,webmcp}` and
`reference/{clipboard,context,locator,page,response,stagehand,webmcp}` — **no `agent`**. The
`agent()` API is documented only under `packages/docs/v2/`. The v4 story is primitives + an external
loop (`packages/docs/v4/integrations/deep-agents.mdx`).

The primitives are stateless: `buildActSystemPrompt` / `buildObserveSystemPrompt` /
`buildExtractSystemPrompt` (`packages/extension/prompt.ts:37-196`) take an instruction and a tree,
and nothing else. There is no history parameter anywhere in that file.

Memory is the cache, in two generations:

- **v2/v3 pattern, still documented**: `observe()` returns a JSON-ified Playwright action
  (`{description, method, selector, arguments}`); pass it to `act()` and there is "NO LLM INFERENCE"
  (`packages/docs/v2/best-practices/caching.mdx:8-43`), with a file-backed `getCache`/`setCache`
  example.
- **v4**: a managed server-side cache. "Browserbase builds the cache key from the instruction, page
  content, and the options you pass. It deliberately leaves out model configuration, so switching
  models does not invalidate your cache. On a cache hit, the server returns the response directly
  with no LLM inference and no token cost."
  (`packages/docs/v4/best-practices/caching.mdx:14`), enabled per-instance with `cache: true` or
  per-call with `{ cache: false }`, and requiring a Browserbase browser (`caching.mdx:16-18`).

This is NetGent's thesis with a weaker artifact: an instruction→action map instead of an NFA.

### 3.5 Agent-E — the only system that measures the page's reaction and returns it *with the action*

Agent-E's planner/executor split is a memory decision. The prompt states it outright:

> Helper is stateless and treats each step as a new task. Helper will not remember previous pages or
> actions. So, you will provide all necessary information as part of each step.
> (`ae/core/prompts.py:18`)

so all memory lives in the planner's AutoGen conversation, and the planner's structured output is
`{plan, next_step, terminate, final_response}` with `plan` re-emitted only "when a task starts and
when the plan needs to be revised" (`prompts.py:10`).

The interesting mechanism is **change observation as part of the action's return value**. A
`MutationObserver` is installed per page and reports added nodes and character-data changes with
their text (`ae/utils/dom_mutation_observer.py:30-65`); each skill subscribes for the duration of its
own action and folds the result into its return string:

```python
# ae/core/skills/enter_text_using_selector.py:158-159 @ f218c3c
if dom_changes_detected:
    return f"{result['detailed_message']}.\n As a consequence of this action, new elements have appeared in view: {dom_changes_detected}. This means that the action of entering text {text_to_enter} is not yet executed and needs further interaction. Get all_fields DOM to complete the interaction."
```

and the browser agent's system prompt tells it to expect exactly that: "Individual function will
reply with action success and if any changes were observed as a consequence. Adjust your approach
based on this feedback." (`prompts.py:75`).

Loop detection is a hard terminate on three consecutive identical (assistant tool-call,
tool-response) pairs over a 6-message window (`ae/utils/detect_llm_loops.py:20-45`). Long-term memory
is a static `user_preferences.txt` (`ae/core/memory/static_ltm.py`).

Caveat: the pinned commit is 2025-05-12 — the repo is not actively developed.

### 3.6 LaVague — NetGent's current design, in an archived repo

`ShortTermMemory` (`lavague-core/lavague/core/memory.py`) is a growing string:

```python
# lavague-core/lavague/core/memory.py:52-64 @ 9024bb8 (2025-01-21)
def update_state(self, instruction, last_engine, success, output):
    if not success:
        instruction = "[FAILED] " + instruction
    if output:
        self.current_state["internal_state"]["agent_outputs"].append(output)
    if self.previous_instructions == "[NONE]":
        self.previous_instructions = f"""\n- {instruction}"""
    else:
        self.previous_instructions += f"""\n- {instruction}"""
    self.last_engine = last_engine
```

rendered into the world-model prompt as a `Previous instructions:` bullet list plus a YAML
`Current state:` block (`lavague-core/lavague/core/world_model.py:16-38`). No cap, no summary, no
structure. The few-shot examples teach the model to *read* the `[FAILED]` markers — one shows two
identical failed clicks followed by the reasoning "Previous instructions have been unsuccessful. A
new approach should be used" (`world_model.py:35`).

This is almost exactly NetGent's `history.append(f"… {reasoning}{outcome}")`. It is the design the
maintained systems moved away from.

### 3.7 Playwright MCP and vercel agent-browser — when the *coding agent* is the memory

Neither tool has agent memory; they are stateless servers whose output lands in a host agent's
transcript. Two mechanisms matter anyway.

**Playwright MCP** (`microsoft/playwright-mcp@16cf228`; source lives in the Playwright monorepo,
`packages/playwright-core/src/tools/backend/`). `Response._build()` assembles `### Error`,
`### Result`, `### Ran Playwright code`, `### Open tabs`, `### Page`, `### Modal state`,
`### Snapshot`, `### Events` sections (`response.ts:270-333`). Three details:

- Tab headers are re-rendered only when something changed:
  `if (this._includeSnapshot !== 'none' || tabHeaders.some(header => header.changed))`
  (`response.ts:296`).
- The aria snapshot is normally **written to a file and returned as a printable link**
  (`snapshotToFile`, `response.ts:292, 308-312`) so the transcript accumulates links, not trees.
- An `outputMaxSize` budget deletes oldest output files to stay under it (`response.ts:239-268`).
- `snapshot.mode` is `'full' | 'none'` in the public config (`mcp/config.d.ts:225-236`).

**vercel-labs/agent-browser** `fbd046c` takes the token argument furthest: "Accessibility-tree
snapshots with compact `@eN` refs let agents interact with pages in ~200-400 tokens instead of
parsing raw HTML" (`skill-data/core/SKILL.md:9`), against a stated "Full DOM/HTML → AI parses → CSS
selector → Action (~3000-5000 tokens)" baseline (`references/snapshot-refs.md:19-27`). *(Both figures
are the project's own claims; not independently measured — see §7.)* Its ref discipline is the same
one NetGent enforces: "Refs (`@e1`, `@e2`, …) are assigned fresh on every snapshot. They become
**stale the moment the page changes** … Always re-snapshot before your next ref interaction."
(`SKILL.md:22`). There is no diff mode.

### 3.8 Lumen — out of scope, but three transferable mechanisms

Vision-first (screenshot → model → action, no DOM), so it fails the brief's scope filter. Its
plumbing is still the best-factored example of the mechanisms this doc recommends.

- **Two histories, one compressible.** `wire` (what goes to the model) and `semantic` — the latter
  labelled "Semantic history (never compressed)" (`src/loop/history.ts:69-77`). NetGent already has
  this shape: `AgentState["steps"]` is the semantic one.
- **Agent-controlled folding.** `addFold(summary)` pushes a completed sub-goal summary that
  "Persists across compaction", and immediately compresses screenshots to `keepRecent=1`;
  `getFoldedContext()` injects them into the system prompt as `COMPLETED SUB-GOALS:` numbered list
  (`history.ts:97-108`). Tier-2 compaction then replaces the entire wire history with a single
  `summary` message (`history.ts:130-149`) — the folds survive because they live outside it.
- **Three-layer stuck detection** (`src/loop/repeat-detector.ts:12-69`): exact normalised-action
  hash in a 20-window at thresholds 5/8/12; **action-category dominance** ("catches scroll/noop
  interleaving") that only fires for non-`productive` categories; and URL-level stall on
  origin+pathname (normalised to ignore tracking params) at 10 / 15 / 20 steps.
- **Action cache** (`src/loop/action-cache.ts`): key is `sha256(url:instructionHash)[:16]`, with a
  `stepKey` variant that deliberately omits the action type to solve the chicken-and-egg lookup
  problem, plus a `SIMILARITY_THRESHOLD = 0.92` screenshot-hash guard for coordinate actions and a
  `viewportMismatch` check.
- `src/memory/workflow.ts:16-20` is labelled "AWM-inspired workflow memory" and stores
  `{name, trigger, steps[], domain, successCount}` matched by trigger-keyword substring + domain
  bonus.

Its README reports a 25-task WebVoyager subset, 3 trials, LLM-as-judge: Lumen 25/25 at 104K avg
tokens vs Stagehand 19/25 at 200K, browser-use 25/25 tokens "N/A". *Self-reported, small n; treat as
directional only.*

### 3.9 Magentic-One / Magentic-UI — the ledger, and a compaction prompt worth copying

The Magentic-One orchestrator (`microsoft/autogen@main`,
`.../teams/_group_chat/_magentic_one/_prompts.py`) keeps two ledgers. The **Task Ledger** is a
pre-survey of facts in four fixed headings (`GIVEN OR VERIFIED FACTS`, `FACTS TO LOOK UP`,
`FACTS TO DERIVE`, `EDUCATED GUESSES`, lines 6-27) plus a bullet plan, rebuilt on stall. The
**Progress Ledger** is re-asked *every turn* and validated against a pydantic schema (lines 59-118):

```
is_request_satisfied / is_in_loop / is_progress_being_made / next_speaker / instruction_or_question
```

each as `{reason: str, answer: bool|str}`. Two of those five are stuck-detection questions asked of
the model rather than computed — and the loop question is phrased to catch NetGent's exact failure
mode: "Loops can span multiple turns, and can include repeated actions like scrolling up or down more
than a handful of times." The architectures doc records the ablation: removing the ledgers costs
−31% on GAIA (arXiv:2411.04468).

Magentic-UI at `d3c9d13` has restructured — its current web surfer is FaRA, a Qwen3-VL
computer-use agent (`src/magentic_ui/agents/web_surfer/fara/`), i.e. out of scope. But
`src/magentic_ui/teams/omniagent/_compaction.py:23-65` is the best-written compaction prompt found in
this survey: fixed headings `## Task`, `## Actions Completed`, `## Current State`,
`## Remaining Work`, `## User Preferences & Constraints`, with instructions like "Position in any
iteration (e.g., 'processed files A–M, next is notes.txt')" and the closer "Be exhaustive on
specifics and terse on prose. Prefer bullet lists over paragraphs. The next LLM has zero memory —
anything you omit is lost."

### 3.10 Cross-run memory: AWM, SkillWeaver, Go-Browse

- **AWM** (arXiv:2409.07429, repo `8c0ff8c`) induces reusable workflows from trajectories and
  prepends them to the prompt. Reported: **+24.6% relative** success on Mind2Web, **+51.1%
  relative** on WebArena "plus reduced steps for successfully completed tasks", and online AWM
  beating baselines by **8.9–14.0 absolute points** as the train/test gap widens. The induced
  artifact is literally `<think>/<action>` blocks in a text file (`webarena/workflow/gitlab.txt`),
  built by an LLM over trajectories that were first filtered by a rule pass that drops malformed
  actions and all `scroll`/`noop` steps (`webarena/induce_prompt.py:25-44`).
- **SkillWeaver** (arXiv:2504.07079, repo `f2a63d6`) synthesises skills as *Python APIs*, practises
  them, and distils practice into robust functions. Reported: **+31.8% relative** on WebArena,
  **+39.8% relative** on real websites, and APIs from a stronger agent lifting a weaker one by
  **up to 54.3%**. Its knowledge base is loaded by path (`--knowledge-base-path-prefix`) and can be
  converted into a browser-use `Controller` to extend an existing agent's action space.
- **Go-Browse** (arXiv:2506.03533) frames exploration as graph search over pages so information is
  reused *across* episodes; it collected 10K trajectories / 40K steps over 100 URLs and a fine-tuned
  7B model scores 21.7% on WebArena.

All three are "compile the trajectory into something reusable" — the family NetGent belongs to, and
the reason not to duplicate it inside the explorer.

---

## 4. Papers with numbers on the memory question itself

**arXiv:2604.01535 — "Read More, Think More: Revisiting Observation Reduction for Web Agents"**
(Enomoto, Obara, Zhang, Oyamada; submitted 2026-04-02). The only paper found that directly ablates
*observation history format*. WorkArena L1, success rate %, input-token counts given for
gpt-5.1(high). Table 5, extracted from the paper HTML:

| model | hist0 | hist4 | hist9 full | hist9 **diff** |
|---|---|---|---|---|
| *#input tokens* | *6,720* | *26,184* | *39,011* | ***13,670*** |
| gpt-5.1 (high) | 55.8 | 58.8 (+3.0) | 58.8 (+3.0) | 58.8 (+3.0) |
| gpt-5.1 (low) | 49.1 | 53.0 (+3.9) | 50.9 (+1.8) | **53.3 (+4.2)** |
| o3-mini (high) | 39.7 | 43.0 (+3.3) | 43.3 (+3.6) | **46.1 (+6.4)** |
| gemini-2.5-flash (budget=16384) | 45.5 | 48.2 (+2.7) | 50.0 (+4.5) | 48.2 (+2.7) |
| gemini-2.5-flash (budget=128) | 28.5 | 39.4 (+10.9) | 39.4 (+10.9) | 33.3 (+4.8) |
| gpt-oss-120b (high) | 46.7 | 49.1 (+2.4) | 48.5 (+1.8) | 46.4 (−0.3) |
| gpt-oss-20b (high) | 46.4 | 46.7 (+0.3) | 48.8 (+2.4) | 49.1 (+2.7) |

Paper's own reading: "adding observation history improves performance for most models and settings";
"for gpt-5.1 (low) and o3-mini, the diff format achieves performance comparable to or better than
the full format. Since the diff format reduces input token count to approximately one-third, it
constitutes an efficient alternative to full history." Their mechanism claim is measured too: they
find a **lower action-repetition rate correlates with higher success** (Figure 3) — history helps by
stopping the agent redoing the last action.

Table 1 of the same paper is the reason NetGent should *not* switch to raw HTML: a11y 6,720 tokens
vs HTML 56,653 tokens, and while Claude Sonnet 4.6 gains +14.6 and gpt-5.1(high) +17.5 from HTML,
every open-source model loses (gpt-oss-20b(high) −18.8, Llama-3.1-70B −14.6) — and so does
o3-mini(high), −7.6. The stated rule is "compact observations (accessibility trees) are preferable
for lower-capability models" — which is the tier `anthropic/claude-haiku-4-5-20251001` sits in.

**arXiv:2306.07863 — Synapse.** Three components: *state abstraction* (filter task-irrelevant page
content so more exemplars fit), *trajectory-as-exemplar prompting* (whole abstracted trajectories,
not plans or multi-choice), *exemplar memory* (embed and retrieve by similarity). 99.2% average on
64 MiniWoB++ tasks from demonstrations of only 48 (+10% relative); +56% relative step success rate on
Mind2Web.

**arXiv:2503.10689 — LCoW** (ICLR 2025). Trains a *separate contextualisation module* that rewrites a
complex page into a comprehensible form before the decision LLM sees it — decoupling page
understanding from decision-making. +15.6 average points for closed models and +23.7 for open models
on WorkArena. Relevant to NetGent because `format_observation` *is* our contextualiser, and it is
pure code — LCoW's result says that seam is worth investing in.

**arXiv:2510.12635 — MemAct / "Memory as Action"** (v3 2026-05-07). Treats context editing
(deletion, insertion) as learnable policy actions with RL. Reported **51% average context-length
reduction** with a 14B model matching one "16× larger". Directionally: giving the agent explicit
control over its own memory beats fixed truncation. The cheap non-RL version of this is browser-use's
`memory` field and Lumen's `addFold`.

**arXiv:2411.06559 — WebDreamer**; **arXiv:2411.02337 — WebRL**; **arXiv:2410.19609 —
OpenWebVoyager.** Included for completeness and *not* load-bearing here: WebDreamer is model-based
planning (simulate candidate actions before committing; competitive with tree search at 4–5× the
efficiency); WebRL (Llama-3.1-8B 4.8%→42.4%, GLM-4-9B 6.1%→43% on WebArena-Lite vs GPT-4-Turbo
17.6%) and OpenWebVoyager are *training*-loop papers whose "memory" is a replay buffer / trajectory
dataset, not prompt state. NetGent does not train a policy.

---

## 5. Patterns, with the numbers

**5.1 One page representation, always the current one.** Universal in DOM mode. The evidence that
this is right and not just cheap: RMTM Table 5 shows the *history* adding +2 to +11 points, but every
system that tested full-observation history (hist9 full, 39,011 tokens) found the diff variant
(13,670) equal or better. Observations are large and stale; decisions are small and durable.

**5.2 The trace is typed, and one field dominates.** browser-use renders `memory` unconditionally
and the other two only when non-empty (`agent/message_manager/views.py:45-55`). Notte and Skyvern independently converged
on the same three-ish fields. Nobody keeps free prose.

**5.3 Self-evaluation of the previous step is a *separate field*, not part of the action.** browser-use
demands a verdict word — its examples end "Verdict: Success" / "Verdict: Failure"
(`system_prompt.md:208-215`) — and warns "Never assume an action succeeded just because it appears to
be executed in your last step in `<agent_history>`" (`system_prompt.md:187`). Notte types it as
`Literal["success","failure","unknown"]`. This is the field NetGent most conspicuously lacks: our
`-> FAILED` marker fires only on *dispatch* errors, never on a dispatched-but-inert action.

**5.4 Stuck detection is computed, soft, and escalating — not a hard stop on string equality.**
browser-use: 20-wide normalised-action window, nudges at 5/8/12, page fingerprint stagnation at 5,
never blocks (`views.py:157-248`). Lumen: same thresholds plus category dominance plus URL stall.
Agent-E: hard terminate but only on 3 *identical tool-call+response pairs*. Magentic-One: asks the
model. NetGent stops the run at 3 identical observations and tells the model nothing beforehand.

**5.5 Compaction is triggered by two gates and produces a fixed-heading summary.** browser-use:
step cadence **and** char floor, `keep_last_items = 6`, item 0 preserved as anchor, summary marked
untrusted. Magentic-UI: five fixed headings. Lumen: 80% context utilisation. Nobody uses a pure
sliding window without a summary — which is what `history[-10:]` is.

**5.6 One-shot channels exist and are cleared.** browser-use `read_state` (cleared each step,
60k cap), Skyvern `recent_dialog_messages` (cleared after render), NetGent `snapshot.dialogs`
(rendered once by `serializer.py:95-100`). We already do this correctly.

**5.7 Cross-run memory is the artifact.** Stagehand cache ⊂ Lumen ActionCache ⊂ AWM workflows ⊂
SkillWeaver APIs ⊂ NetGent's NFA. Ours is the only one with an explicit state machine, triggers, and
zero-LLM replay. Nothing in this survey argues for adding a second, weaker cross-run store inside the
explorer.

---

## 6. Recommendation for NetGent's explorer

### 6.1 What to adopt, ranked

| # | Change | Precedent | Evidence | Cost / step | Priority |
|---|---|---|---|---|---|
| 1 | **Observation diff**: mark elements new since last step, plus a one-line change summary | browser-use `is_new`/`*[`; Agent-E MutationObserver | RMTM Table 5: diff ≈ full at ⅓ the tokens; lower repetition rate ↔ higher success (Fig. 3) | +10–40 in | **high** |
| 2 | **Typed `StepRecord`** replacing the history string | browser-use `HistoryItem`; Skyvern `action_history` dicts | none direct; enables 3, 5, 6 | 0 | **high** |
| 3 | `evaluation` + `memory` + `next_goal` on `AgentDecision` | browser-use `AgentBrain`; Notte `AgentState` | none published (§7) | +100–120 in, +50–90 out | **high** |
| 4 | **New-alert-text line** (`texts_seen` diff) in the observation | browser-use `read_state`; Notte DISCLAIMER | none; but directly fixes the transient-banner problem our own comment describes | +10–30 in | **high** |
| 5 | **Task-boundary compaction** of `BrowserAgent.history` on `note()` | browser-use `compacted_memory`; Lumen `addFold`; Magentic-UI headings | none | ~0 (saves tokens in sweeps) | medium |
| 6 | **Soft escalating stuck nudge** before the hard `MAX_REPEAT` stop | browser-use `ActionLoopDetector`; Lumen 3-layer | Magentic-One ledger ablation −31% (indirect) | +20–40 in when firing | medium |
| 7 | Step-budget line in the observation (`step n/N`) + a wrap-up nudge at 75% | Notte `perception.py:35`; browser-use `_inject_budget_warning` | none | +10 in | low |
| 8 | Cross-`--runs` site notes | Lumen SiteKB; browser-use `todo.md` | none | — | **do not build** (see 6.6) |

### 6.2 Concrete proposals

**(a) `StepRecord` — replace the history string.** New model, next to `AgentStep` in
`explorer/browser_agent.py`:

```python
class StepRecord(BaseModel):
    """One acted step, as the agent remembers it. Compile-time only: the generator reads
    AgentStep, never this. Rendered into the prompt by `to_line()` / `to_block()`."""
    n: int
    kind: str
    index: int | None = None
    target: str = ""              # el.name or tag[type] — survives index invalidation (Notte hide_interactions)
    reasoning: str = ""
    outcome: Literal["ok", "failed", "no_change"] = "ok"
    error: str | None = None
    # the model's own words, from AgentDecision (below); empty when not supplied
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""
    note: str | None = None       # a BrowserAgent.note() marker, e.g. "moving on to form 3 of 21"

    def to_line(self) -> str:     # compact form, older steps
        tail = f" -> {self.outcome.upper()}" + (f": {self.error}" if self.error else "")
        return f"{self.n}. {self.kind}({self.target or self.index}) {self.reasoning}{tail}"

    def to_block(self) -> str:    # full form, last 3 steps
        parts = [f"<step {self.n}>"]
        if self.evaluation: parts.append(f"Eval: {self.evaluation}")
        if self.memory:     parts.append(f"Memory: {self.memory}")
        if self.next_goal:  parts.append(f"Next goal: {self.next_goal}")
        parts.append(self.to_line())
        return "\n".join(parts)
```

Note `target`: browser-use keeps the raw index, Notte strips it (`hide_interactions=True`) precisely
because indices are invalid against a new observation. Keeping a *name* instead of (or beside) the
index is strictly better — the model can recognise "Submit application" across renumberings, and our
prompt already warns indices are per-observation (`prompt.py:41`).

`BrowserAgent.history` becomes `list[StepRecord]`; `note()` appends
`StepRecord(n=..., kind="note", note=text)`. `LLM.decide` takes `list[StepRecord]` and renders
last-3 as blocks + older as lines — this is the only place the format lives.

**(b) `AgentDecision` gains three fields.** Safe by construction: `to_action`
(`explorer/actions.py:33-112`) matches on `kind` and reads only the action-shaped fields, and the
generator (`generator/compiler.py`) reads only `step.url`, `step.dialogs`, `step.action`. Nothing new
can leak into the artifact.

```python
evaluation: str = Field(default="", description=
    "One sentence on whether your PREVIOUS action achieved its goal, ending in "
    "'Verdict: Success', 'Verdict: Failure', or 'Verdict: Unclear'. Judge from the "
    "observation — an action that dispatched without error may still have done nothing.")
memory: str = Field(default="", description=
    "1-2 sentences of progress you must not lose: counts, values entered, what is left.")
next_goal: str = Field(default="", description="The immediate goal this action serves.")
```

Two design notes. First, **defaults are empty strings, not required** — a cheap model that omits
them still validates, and `to_block()` skips empty fields exactly as browser-use does
(`agent/message_manager/views.py:45-55`). Second, `evaluation` is worth more than `next_goal` for us: it is the field that
catches the dispatched-but-inert action, which is the single failure mode our history cannot
represent. If output tokens ever matter, drop `next_goal` first (browser-use's flash mode drops
`next_goal` and `evaluation_previous_goal` and keeps `memory` — for our purpose the ranking should be
`evaluation` > `memory` > `next_goal`).

Mirror the three onto `AgentStep` as compile-time provenance, beside `locator_check`. They make the
trajectory JSON far more readable when debugging a bad compile, and cost nothing at run time.

**(c) Observation diff.** Two pieces, both in the browser layer so the zero-LLM boundary holds.

*Element diff.* `format_observation` grows an optional `previous: set[str] | None` parameter of
element keys. A key must survive renumbering — reuse the durable-locator ingredients:
`f"{frame_path}|{tag}|{type}|{name}"` is enough for a first pass and is pure (no CDP backend-node-ids
like browser-use uses, which we do not carry on `DomElement`). Render:

```
POSITION: middle of page.
CHANGED SINCE LAST STEP: 3 new, 1 gone, URL unchanged.
INTERACTIVE ELEMENTS (near viewport):
  [12] input[text] "Coupon code" [required]
 *[13] button "Apply coupon"          <- new since your last action
 *[14] div (alert) "Code accepted"
```

with one prompt paragraph modelled on `system_prompt.md:59`. When nothing changed, emit
`CHANGED SINCE LAST STEP: nothing changed on screen.` — that single line is also the soft version of
recommendation 6, and it says to the model exactly what `no_progress` currently only says to the
loop.

*Text diff.* `texts_seen` already accumulates every text ever observed (`graph.py:82-92`) and is
never shown. Add the complement — texts present now that were **not** in the previous snapshot,
alerts first:

```
NEW TEXT SINCE LAST STEP:
  !ALERT Thanks — your response has been recorded.
```

This is the cheapest possible fix for the transient-success-banner problem that the comments at `graph.py:79-81` and
`browser_agent.py:48-50` both describe: today the banner appears in one observation
and vanishes, and if the model happened to act on that step it never learns the submit worked.

Where the state lives: `AgentState` gains `prev_element_keys: set[str] | None` and
`prev_texts: set[str] | None`, set in `observe` alongside `prev_observation`. `prev_observation`
stays for the equality check (cheap, and it catches changes the key set misses).

**(d) Task-boundary compaction.** `BrowserAgent.note()` is called at each task boundary in a sweep.
Make it fold:

```python
def note(self, text: str) -> None:
    """Append a marker AND compact everything before it into one line."""
    done = [r for r in self.history if r.kind != "note"]
    if len(done) > 4:
        ok = sum(1 for r in done if r.outcome == "ok")
        summary = f"(earlier: {len(done)} steps, {ok} ok, {len(done)-ok} failed; last goal: {done[-1].next_goal or done[-1].reasoning})"
        self.history = [StepRecord(n=0, kind="note", note=summary)]
    self.history.append(StepRecord(n=0, kind="note", note=text))
```

Zero-LLM (unlike browser-use's summariser) because our boundaries are known — we do not need a model
to find them. This removes the current silent failure where `history[-10:]` erases everything a sweep
learned two forms ago. If a richer summary is ever wanted, browser-use's prompt
(`message_manager/service.py:262-270`) and Magentic-UI's headings
(`teams/omniagent/_compaction.py:23-65`) are the two to copy — with browser-use's anti-overclaim
clause, which matters doubly for us because a false "submitted successfully" in memory would corrupt
the trajectory the generator compiles.

**(e) What NOT to change.** Keep `MAX_REPEAT = 3` as the hard stop — a compile-time explorer should
die fast and cheap, unlike a user-facing agent that must keep trying. Keep the single-string prompt
in `llm.py` rather than moving to a message list: we are stateless per call, structured output is
already working, and a message list buys nothing until we want provider prompt caching (Skyvern's
static/dynamic split, `agent.py:5724-5752`, is the pattern if we ever do — our 1,014-token system
prompt is a natural cacheable prefix). Keep observations at accessibility-tree granularity: RMTM
Table 1 says HTML *hurts* every model in Haiku's capability tier.

### 6.3 What lives where

| Field | `AgentState` (LangGraph, per run) | `BrowserAgent` (per agent, across runs) |
|---|---|---|
| `n`, `snapshot`, `observation`, `decision` | ✅ (as today) | — |
| `prev_observation`, `no_progress` | ✅ (as today) | — |
| **`prev_element_keys`, `prev_texts`** | ✅ **new** | — |
| `texts_seen` | ✅ (as today, still post-run evidence) | — |
| `steps: Annotated[list[AgentStep], operator.add]` | ✅ — the compilable trajectory | — |
| **`records: Annotated[list[StepRecord], operator.add]`** | ✅ **new** — this run's memory | — |
| `history: list[StepRecord]` | — | ✅ **typed** — cross-run memory, mutated in place by `act` as today |
| `success`, `stopped_reason` | ✅ | — |

The rule that keeps this clean: **`AgentState` holds the current run; `BrowserAgent` holds what
survives a run.** The `records` reducer gives us a per-run copy for the trajectory file without
having to slice the shared list. Nothing unserialisable is added, so the graph stays
checkpointer-compatible-in-principle (as `graph.py:9-11` notes, none is attached today, and
`snapshot` remains the one object that would need excluding).

### 6.4 Token impact

Baseline measured today (§1), 40 elements, 10 history lines: **≈2,120 input tokens/step**, output
≈ one small JSON object (~40–70 tokens).

| Item | Δ input tokens/step | Δ output tokens/step |
|---|---|---|
| element-diff markers + `CHANGED SINCE LAST STEP:` line | +10 … +40 | 0 |
| `NEW TEXT SINCE LAST STEP` (0–3 lines) | +10 … +30 | 0 |
| last-3 records as blocks (eval + memory + next_goal ≈ 45 tok each), older 7 as lines | +100 … +135 | 0 |
| prompt paragraph explaining `*` and the change line | +45 (fixed, in `SYSTEM_PROMPT`) | 0 |
| `evaluation` + `memory` + `next_goal` in the structured output | 0 | +50 … +90 |
| task-boundary compaction | **−100 … −200** in sweeps | 0 |
| **net, single-task run** | **+165 … +250 (≈ +8–12%)** | **+50 … +90** |
| **net, 21-form sweep** | **roughly flat** | +50 … +90 |

At 25 steps that is ≈ 53k → ≈ 58k input tokens per exploration. Against the cost basis this repo
already uses for its own eval matrix (Haiku 4.5 at $1/M input, $5/M output — `evals/matrix.py:3`),
that is a few cents per exploration, and `--runs N` multiplies it linearly. The RMTM result says the
diff line alone should pay for the whole increase in fewer wasted steps: their hist0→diff deltas are
+2.7 to +6.4 points, and a step saved is ~2,120 tokens.

If cost does bite, the cut order is: `next_goal` → full blocks for last-3 (go back to lines for all)
→ `memory`. Never cut the diff line; it is the only item with an external measurement behind it.

### 6.5 How to measure it here

`netgent eval stress` already reports `calls / input_tokens / output_tokens / images / wall` per run
(`evals/stress.py:140-147`) and `LangChainLLM.usage` already accumulates `observation_chars`
(`llm.py:39, 46`). Two additions make the A/B mechanical:

- Env flags in the same style as the existing `NETGENT_IFRAME_HEADERS=0` A/B switch
  (`browser/dom/serializer.py:46`): `NETGENT_OBS_DIFF=0` and `NETGENT_MEMORY_FIELDS=0`. That keeps
  the ablation in the codebase rather than in a branch, exactly as the iframe-header measurement was
  done.
- Add `history_chars` beside `observation_chars` in `LLM.usage`, so the matrix can show the memory's
  share directly.

Then run `netgent eval stress` on the forms corpus at 2×2 (diff on/off × memory-fields on/off),
reporting steps-to-success and tokens. The primary metric should be **steps to a compilable
trajectory**, not just success — a shorter trajectory compiles to a smaller NFA.

### 6.6 What NOT to build

- **A second cross-run memory store (site notes, skill library, action cache).** The compiled
  workflow *is* that artifact, and it is stronger than every cache in §3.10. Worse, biasing run 2
  with run 1's notes would **correlate the runs** — and the whole point of `--runs N` is independent
  trajectories the generator can intersect. Deliberately keep the runs blind to each other.
- **An LLM summariser in the explorer loop.** Our horizons are bounded (`max_steps: int = 25`) and
  our task boundaries are known (`note()`), so zero-LLM folding covers the same ground. Every LLM
  call in the loop is a compile-time cost multiplied by `--runs N`.
- **A message-list conversation.** Notte's `Conversation` exists to support token-budgeted trimming
  over a real chat history; we rebuild one string per step and have no chat history to trim.
- **Raw-HTML observations.** RMTM Table 1: −18.8 points for gpt-oss-20b(high), −7.6 for o3-mini(high),
  at 8× the tokens.
- **Screenshots in the decision prompt.** Nothing in the DOM-mode survey needs them, RMTM Table 1
  shows a11y+screenshots gaining only +1.2 to +6.7 for a +726-token cost, and our trajectory already
  captures them for humans (`capture_screenshot`, `browser_agent.py:83-92`).

---

## 7. Provenance and verification notes

**Verified by reading source at a pinned commit** (cloned and read 2026-08-26):

- browser-use `28670f720f63cc5f525a2acd6d6072867689ab68` — `agent/message_manager/{service.py,views.py,utils.py}`, `agent/views.py`, `agent/prompts.py`, `agent/service.py`, `agent/system_prompts/system_prompt.md`, `dom/serializer/serializer.py`, `browser/views.py`, `filesystem/file_system.py`, `AGENTS.md`.
- Skyvern `d081a5324bda5bdf58c640f1c59b2c40975e64c1` — `config.py`, `services/action_service.py`, `services/task_v2_service.py`, `forge/agent.py`, `forge/prompts/skyvern/{extract-action.j2,task_v2.j2}`, `webeye/scraper/scraper.py`, `webeye/actions/caching.py`, `utils/prompt_engine.py`.
- Notte `1802f0080b5f15bf028c029026824b7f533dc7dc` — `packages/notte-agent/src/notte_agent/{agent.py,common/conversation.py,falco/perception.py}`, `packages/notte-core/src/notte_core/{agent_types.py,common/config.py}`.
- Stagehand `341433acac46a305ad6c2f9a0445e907675f4fb4` (workspace version 4.0.0) — `package.json`, `packages/extension/prompt.ts`, `packages/docs/v2/best-practices/caching.mdx`, `packages/docs/v4/best-practices/caching.mdx`, directory listings of `packages/docs/v4/{basics,reference}` (used for the "no `agent()` in v4 docs" claim).
- Agent-E `f218c3cb4b2b3e33ed08ea12da5514ab1e89cdd7` (2025-05-12, unmaintained) — `ae/core/prompts.py`, `ae/utils/dom_mutation_observer.py`, `ae/utils/detect_llm_loops.py`, `ae/core/skills/enter_text_using_selector.py`, `ae/core/memory/static_ltm.py`.
- LaVague `9024bb832c40291cd012916757f27ef60469b22d` (2025-01-21, archived) — `lavague-core/lavague/core/{memory.py,world_model.py,agents.py}`.
- Magentic-UI `d3c9d13c39288257286a66daabf7c5b5fb72ee69` (2026-07-23) — `src/magentic_ui/teams/omniagent/_compaction.py`, directory listings of `src/magentic_ui/agents/web_surfer/fara/`.
- playwright-mcp `16cf228d7b02c07f800ec3423f471ec2a42d22a9` (v0.0.79) — `src/README.md`, `package.json`.
- vercel-labs/agent-browser `fbd046c23a2c1156891bda294aaaee715c23b3f1` — `skill-data/core/SKILL.md`, `skill-data/core/references/snapshot-refs.md`.
- Lumen `b1ad26a0784645ac3a97d402db99cd5d17f86334` (2026-03-29) — `README.md`, `src/loop/{history.ts,repeat-detector.ts,action-cache.ts}`, `src/memory/workflow.ts`.
- AWM `8c0ff8cd11d648c8fceb99e4e42f37e3b75381b1` — `README.md`, `webarena/induce_prompt.py`, `webarena/workflow/gitlab.txt`.
- SkillWeaver `f2a63d65d0f6ff46ac30e817cede8797f8f25b97` — `README.md`.

**Unpinned (read from `@main`, pin before citing in a paper):**
`microsoft/autogen` — `python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_prompts.py`;
`microsoft/playwright` — `packages/playwright-core/src/tools/backend/response.ts`,
`packages/playwright-core/src/tools/mcp/config.d.ts`. (playwright-mcp's `src/` now contains only a
pointer README: "Playwright MCP source code is located in the Playwright monorepo".)

**NetGent measurements** were produced in this session on `eugene/v2-scaffold` @ `4d11d19`:
`SYSTEM_PROMPT` length read directly from `explorer/prompt.py`; observation sizes produced by calling
`format_observation` on synthetic `DomSnapshot` objects (6 repeating element shapes: text inputs with
and without `[required]`, a button, a `select` with 3 options, a link, a checkbox; 25 text blocks of
~58 chars). Real pages have longer names, values and URLs, so **these are lower bounds**; history
line length is the mean of 4 hand-written realistic lines (78/81/92/124 chars). Nothing was measured
against a live browser — an `netgent eval observation` run on the real corpus would replace these
with measured numbers.

**Paper numbers** are quoted as printed. arXiv:2604.01535 Tables 1 and 5 were extracted
programmatically from `https://arxiv.org/html/2604.01535v1` (row text parsed out of the HTML table
markup), not from a summariser. arXiv:2409.07429 (AWM), 2504.07079 (SkillWeaver), 2506.03533
(Go-Browse), 2306.07863 (Synapse), 2503.10689 (LCoW), 2510.12635 (MemAct), 2411.06559 (WebDreamer),
2411.02337 (WebRL), 2410.19609 (OpenWebVoyager) were read via abstract-page fetch only — the numbers
are as reported in the abstract/landing page, **not** re-derived from the tables. The
Magentic-One −31% ledger ablation is carried over from
[`browser-agent-architectures.md`](browser-agent-architectures.md) §3.4 (arXiv:2411.04468) and was
not re-verified here.

**Explicitly unverified / marked claims:**

- **No published ablation was found** for browser-use's `memory` / `evaluation_previous_goal` /
  `next_goal` fields, for `max_history_items`, for flash mode, or for Skyvern's
  `PROMPT_ACTION_HISTORY_WINDOW = 1`. These are load-bearing defaults in production systems with no
  public numbers behind them. Recommendation 3 rests on convergent design across four independent
  codebases plus the RMTM history result — not on a measured delta for those specific fields.
- vercel-labs/agent-browser's "~200-400 tokens" vs "~3000-5000 tokens" figures are the project's own
  README/SKILL claims; not independently measured.
- Lumen's WebVoyager table is self-reported on a 25-task subset with an LLM judge; directional only.
- The claim "Stagehand v4 has no built-in agent loop" is inferred from the v4 docs tree containing no
  `agent` page and `packages/sdk-ts/src/` containing no agent/history/cache module — a server-side
  agent behind the Browserbase API would not be visible in this repo.
- The token deltas in §6.4 are estimates from character counts of the proposed renderings, not
  measured LLM tokenisations.

**Not investigated:** WebVoyager/SeeAct/AutoWebGLM per-step memory (pure-vision or set-of-marks, out
of scope); browser-use's cloud/beta `service.py` variant; Skyvern's CUA engines; the FaRA web surfer;
Notte's `notte-skills` package; any retrieval-augmented memory (vector store over past trajectories),
which is a separate axis from per-step working memory and would be worth its own pass if the
generator ever needs cross-site priors.
