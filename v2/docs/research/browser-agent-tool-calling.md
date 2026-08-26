# Browser-agent tool calling — action lists, element addressing, and the closed action set

How DOM/text-observing browser agents shape the LLM's per-step output: one action or a list,
how elements are addressed and validated, which compound actions exist, what structured-output
mechanism carries it, and what any of it measurably buys. Read against NetGent's explorer
(`v2/src/netgent/agent/explorer/`), which today asks for **exactly one atomic action per step**
via one `with_structured_output` call. Sources are pinned to commits and read from raw source;
provenance and unverified claims are in §8.

## Summary (10 lines)

1. **Single-action is not the outlier it looks like.** Notte, AgentOccam (WebArena SOTA at
   publication), WebVoyager, LaVague-per-call and Stagehand's `act` are all one-action; browser-use,
   Skyvern, BrowserGym-multiaction and OpenAI CUA batch. Nobody batches *unbounded*.
2. **Everyone who batches uses the same two guards**: a static "this action changes the page"
   flag, and a runtime post-action page-change check. Both abort the rest of the list.
3. **A failed item aborts the remainder everywhere** (browser-use `break`; Skyvern marks the step
   failed and returns). Nobody executes past a failure into a stale DOM.
4. **Compound actions are real and narrow**: `fill_form` (Playwright MCP, Stagehand, Notte,
   Agent-E `bulk_enter_text`) and type-and-submit (`browser_type{submit}`, WebVoyager `Type`,
   LaVague `setValueAndEnter`, Notte `press_enter`). Both decompose to one atomic action per field.
5. **Index/ref addressing beats everything else, measurably**: SeeAct grounding via textual
   choices 39.1/32.7/42.0 step-SR vs image annotation 20.3/13.9/23.7 and attributes 16.1/12.1/19.0.
6. **Shrinking the action set is the single largest measured win in the literature**: AgentOccam
   Vanilla 16.5% → 25.9% on WebArena from removing actions alone (+9.4pts, +57%); the whole
   pipeline reaches 43.1%.
7. **Nobody in this survey uses one-tool-per-action-kind for a DOM agent.** browser-use and
   LangChain both force *one* tool whose schema carries the action union. Anthropic's computer-use
   toolset (17 named member tools, no `action` field) is the counter-example — and it's vision.
8. **We are already on native tool calling** and didn't know it: all three of our providers default
   `with_structured_output(..., method="function_calling")` at the pinned versions.
9. **Recommendation:** keep one atomic action as the unit; add a bounded `actions: list[…]`
   (max 4) with browser-use's two guards, recording one `AgentStep` — hence one NFA transition —
   per *executed* item. Add no compound actions to `schema/actions.py`.
10. Harden `llm.py` with Notte's retry ladder and `decision.py` with Skyvern's coercion ladder.

---

## 1. Where NetGent stands today (read from source)

| Aspect | NetGent | File |
|---|---|---|
| Output shape | **one** `AgentDecision`, one `kind`, one `index` | `agent/explorer/decision.py:18-43` |
| Kinds | `click, fill, select, upload, hover, press, goto, scroll, go_back, wait, done` (11) | `decision.py:12-15` |
| Addressing | `index: int \| None` into `snapshot.interactive()` | `decision.py:24` |
| Index validation | bounds-checked at map time; raises `ValueError` | `agent/explorer/actions.py:44-48` |
| Coercion | `_coerce_index` strips non-digits from a string index ("[3]" → 3) | `decision.py:26-33` |
| Type checks | `fill` on `<select>` rejected; `select` on non-`<select>` rejected; option value must be in `el.options` | `actions.py:64-79` |
| Structured output | one `with_structured_output(AgentDecision, include_raw=True)` call/step | `agent/llm.py:36,44-53` |
| Failure handling | parse failure → history note + re-observe, costs a step, never crashes | `agent/explorer/graph.py:99-104` |
| Dispatch failure | `ExecutionError`/`ValueError` → `step.error`, echoed into history | `graph.py:134-148` |
| Exit | `done` only, with `success: bool` | `decision.py:19-20`, `graph.py:107-116` |
| Artifact action set | `goto, click, fill, press, select, scroll, upload_file, go_back, wait, hover, noop` | `schema/actions.py:188-203` |
| Compile | one `AgentStep` with `action is not None and error is None` → one `Transition` | `agent/generator/compiler.py:78,111` |

Two properties of the compiler constrain everything below: a transition's **source state
conditions come from that step's post-action URL, the *next* step's in-iframe element, and the
dialogs raised by *that* action** (`compiler.py:86-101`). So any batching change must produce
per-item post-action URL and per-item dialog capture, or the compiled NFA loses its state anchors.

**On JS eval.** The brief refers to an evaluate-tool discussion in
`docs/research/browser-agent-architectures.md`; **there is none** — `grep -rn "evaluate("` across
`docs/research/*.md` returns only Playwright-layer mechanics and LangSmith `evaluate()`. The
decision is recorded here for the first time, and §6.4 gives the outside evidence for it.

---

## 2. Survey table

Columns are the six questions from the brief. "list" = the LLM may emit several actions per call.

| System | Actions per LLM call | Element addressing | Structured-output mechanism | `done` | Compounds |
|---|---|---|---|---|---|
| **browser-use** `28670f72` | **list**, `max_actions_per_step=5`, hard-truncated | `index: int` (`ge=1`) into selector map | one forced tool `AgentOutput`; `action: list[ActionModel]` where `ActionModel` is a `RootModel` union | `done(text, success, files_to_display)`, single-action only | `fill_form`? no — but `extract`, `find_elements`, `search_page`, `evaluate` |
| **Skyvern** `d081a532` | **list**, unbounded, ordered `action_order` | `id: str` (from scraped page) + `skyvern_element_hash` | JSON in prompt (`extract-action.j2`), hand-parsed | `COMPLETE` / `TERMINATE`, both `DecisiveAction` with `errors[]` | `INPUT_TEXT` auto-Tab, `PASTE_TEXT` (grid block) |
| **Stagehand v3** `a8d73fda` | **one tool call/step**, AI-SDK loop | `act` takes an NL phrase → `observe` → XPath `selector` + `method` + `arguments` | native tool calling (`ai` SDK `tool()` + zod) | `handleDoneToolCall` | **`fillForm{fields[]}`** — the canonical bounded list |
| **Playwright MCP** `16cf228d` | **one tool call**, host may batch | `target: string` ref `/^(f\d+)?e\d+$/` or a selector | MCP tools (zod schemas) | n/a (host agent's) | **`browser_fill_form{fields[]}`**, `browser_type{submit}` |
| **agent-browser** `fbd046c2` | one CLI command; `batch` runs a list | `@eN` refs from `snapshot` | MCP tools / CLI argv | n/a | `batch --bail`, `set_checked` |
| **Agent-E** `f218c3cb` | one skill call (AutoGen) | CSS `[mmid='114']` | AutoGen function calling over `Annotated` sigs | terminate via AutoGen | **`enter_text_and_click`**, **`bulk_enter_text`** |
| **Notte** `1802f008` | **one**: `action: ActionUnion` | `id: str` **or** `selector` (validator requires one) | litellm JSON schema + repair + retry ladder | `CompletionAction` | **`form_fill{value: dict[fixed keys]}`**, `press_enter` on fill |
| **LaVague** `9024bb83` | **list** (YAML `actions:`) | full XPath, must be in "Authorized Xpaths" | YAML in a markdown fence, hand-parsed | `failNoElement` / `failAmbiguous` | **`setValueAndEnter`** |
| **BrowserGym** `9e779f08` | `multiaction: bool = True`, python-call grammar | `bid: str` | function-call grammar string, or `to_tool_description()` | `send_msg_to_user` / `report_infeasible` | none (`check`/`uncheck` deliberately removed) |
| **WebVoyager** (2401.13919) | **one** | `Click [Numerical_Label]` | free-text grammar | `ANSWER; [Content]` | **`Type`** = focus+clear+type+**Enter** |
| **SeeAct** (2401.01614) | one `(e, o, v)` triple | index into a 17-option candidate list | free text → parse | n/a (Mind2Web) | Hover and Press-Enter folded **into Click** |
| **AgentOccam** (2410.13825) | **one** ("Only issue one single action") | `click [id]` | free-text grammar | `stop [answer]` | dropdown = single `click` on the option id |
| **OpenAI CUA** | **list** — `computer_call.actions[]` batched | coordinates | provider tool | model stops emitting `computer_call` | — |
| **Anthropic computer-use** `computer_toolset_20260801` | one tool_use block/turn | coordinates | **17 named member tools, no `action` field** | — | — |
| **NetGent** | **one** | `index: int` | `with_structured_output` (→ forced tool call) | `done{success}` | none |

---

## 3. Per-system detail worth carrying

### 3.1 browser-use — the multi-action reference implementation

`AgentOutput` (`browser_use/agent/views.py:388-399`) is a single pydantic model:

```python
class AgentOutput(BaseModel):
    thinking / evaluation_previous_goal / memory / next_goal / current_plan_item / plan_update
    action: list[ActionModel] = Field(..., json_schema_extra={'min_items': 1})
```

`ActionModel` is built per step by `create_action_model` (`tools/registry/service.py:517-575`):
one single-field pydantic model per registered action, then a `RootModel` union — so the JSON
schema forces exactly one action name per list element. The union is **filtered by page URL**
(`domains` glob) before the schema is built, so the model never sees an action it can't use here.

The whole thing is delivered as **one forced tool call**, not N tools
(`llm/anthropic/chat.py:419-448`):

```python
tool_name = output_format.__name__               # 'AgentOutput'
tool = ToolParam(name=tool_name, input_schema=SchemaOptimizer.create_optimized_json_schema(...))
tool_choice = ToolChoiceToolParam(type='tool', name=tool_name)   # forced
```

**Truncation, not rejection**, when the model overruns: `agent/service.py:1956-1958` does
`parsed.action = parsed.action[: self.settings.max_actions_per_step]` (default 5,
`agent/views.py:71`). No retry, no error to the model.

**`multi_act` (`agent/service.py:2732-2848`) is the part to copy.** Its docstring names the two
layers verbatim:

> 1. Static flag: actions tagged with `terminates_sequence=True` (navigate, search, go_back, switch)
>    automatically abort remaining queued actions.
> 2. Runtime detection: after every action, the current URL and focused target are compared
>    to pre-action values. Any change aborts the remaining queue.

Concretely, per item:
- `done` past index 0 → `break` with "Done action is allowed only as a single action" (`:2764-2768`).
- `wait_between_actions` sleep before every item after the first (`:2771-2773`).
- capture `pre_action_url` and `pre_action_focus`, act, then `if results[-1].is_done or results[-1].error or i == total-1: break` (`:2809`).
- `registered_action.terminates_sequence` → `break` (`:2818-2823`).
- `post_action_url != pre_action_url or post_action_focus != pre_action_focus` → `break` (`:2825-2831`).
- an exception → append an error `ActionResult` and `return results` immediately, **preserving
  partial results** so the model knows which prefix ran (`:2834-2848`).

Note: `cached_selector_map` is still computed at `:2751` and **never read** at this SHA — the
DOM-hash staleness guard was replaced by the URL/focus comparison. Worth knowing before copying it.

**Index validation is soft.** `ClickElementActionIndexOnly.index: int = Field(ge=1)`
(`tools/views.py:77-80`) is the only schema constraint; at execution
`browser_session.get_element_by_index(params.index)` returning `None` produces a *successful*
`ActionResult` whose text is `f'Element index {params.index} not available - page may have
changed. Try refreshing browser state.'` (`tools/service.py:714-717`, repeated at `:787, :1680,
:1708`). A hallucinated index costs a step and a nudge, never a crash — same philosophy as our
`graph.py:99-104`, but at the action layer rather than the parse layer. Index 0 is asserted away
(`:710`) because 0 means "no interactive elements".

**Prompt-level batching policy** (`agent/system_prompts/system_prompt.md:155-181`) is where the
real guidance lives, and it is a taxonomy we can lift wholesale:

> - **Page-changing (always last):** `navigate`, `search`, `go_back`, `switch`, `evaluate` …
>   Note: `evaluate` runs arbitrary JS that can modify the DOM, so it is never safe to chain
>   other actions after it.
> - **Potentially page-changing:** `click` (on links/buttons that navigate) — monitored at runtime …
> - **Safe to chain:** `input`, `scroll`, `find_text`, `extract`, `search_page`, `find_elements`,
>   file operations …
> **Recommended combinations:** `input`+`input`+`input`+`click`; `input`+`input`;
> `scroll`+`scroll`; `click`+`click` (only when clicks do not navigate)
> Do not try multiple different paths in one step. Always have one clear goal per step.
> Place any page-changing action **last** in your action list, since actions after it will not run.

**The read-only action family** is the other thing browser-use has that we don't: `extract`
(LLM over page markdown, with `output_schema`, `already_collected` for pagination,
`start_from_char` for truncation — `tools/views.py:8-27`), `search_page` (grep, "Zero LLM cost,
instant"), `find_elements` (CSS query returning tag/text/attrs, "Zero LLM cost, instant"),
`find_text` (scroll-to-text), `dropdown_options` (enumerate a native/ARIA dropdown before
choosing), `send_keys`, `switch`/`close_tab`, `screenshot`, `save_pdf`, file read/write/replace,
and `evaluate` (arbitrary JS).

### 3.2 Skyvern — the widest closed set, per-action confidence, and a firewall over it

`ActionType` (`skyvern/webeye/actions/action_types.py:4-49`) has **28 members**; `is_web_action()`
names the 8 element-targeted ones (CLICK, INPUT_TEXT, PASTE_TEXT, UPLOAD_FILE, DOWNLOAD_FILE,
SELECT_OPTION, CHECKBOX, HOVER). Two comments in `actions.py` are the action-space-minimality
argument in the wild:

- `CheckboxAction` (`actions.py:414-421`): *"This action causes more harm than it does good. It
  frequently mis-behaves, or gets stuck in click loops. Treating checkbox actions as click actions
  seem to perform way more reliably. Developers who tried this and failed: 2"* — i.e. Skyvern
  reached our `to_action` `case "click"` comment independently.
- `DOWNLOAD_FILE` (`action_types.py:10-11`): *"not used in the current implementation. Click
  actions are used instead."*

**The prompt asks for a LIST**, `extract-action.j2:20`: `"actions": array // An array of actions.`
preceded by `"action_plan": str // …the order you're going to take them in`. Every element carries
metadata we don't have:

| Field | `extract-action.j2` | Purpose |
|---|---|---|
| `reasoning` | `:22` | why this type and this element id |
| `user_detail_query` / `user_detail_answer` | `:23-24` | a Jeopardy-style Q/A pair; the query is **user-data-agnostic**, so the same action replays under a different user context |
| `confidence_float` | `:25` | 0.0-1.0 per action |
| `click_context.single_option_click` | `:48` | "is this the only way forward, or a user-dependent choice?" |
| `click_context.desired_state` | `:49` | level-triggered toggle intent — `true`/`false`/`null` |
| `context.{field,is_required,is_search_bar,is_location_input,is_date_related,date_format,is_text_captcha}` | `:54-60` | routes into per-widget handlers |

The `user_detail_query`/`user_detail_answer` split is the most transferable idea: it is exactly
NetGent's `-p name=sample` → `${name}` parameterisation, asked of the model at action time instead
of recovered by string substitution in `compiler.py:122+`.

**`parse_actions` (`parse_actions.py:360-447`) never fails the whole list.** Per element:
non-dict entries are collected and logged once (a planner refusal repaired into the array arrives
as prose); `UnsupportedActionType` / `ValidationError` / `Exception` each log and **drop that
action**, keeping the rest. `action_order = idx` is stamped.

**`parse_action`'s coercion ladder (`:73-356`) is a checklist for our `decision.py`:**
- `id` **or** `element_id` accepted (`:81-83`).
- `element_id` is `Annotated[str, Field(coerce_numbers_to_str=True)]` (`actions.py:151-152`) — an
  int id is coerced, not rejected.
- `action["action_type"].upper()` — *"handles the case where the LLM returns a lowercase action
  type"* (`:126`).
- legacy aliases mapped: `PRESS_ENTER → KEYPRESS`, `EXTRACT_INFORMATION → EXTRACT` (`:119-124`).
- unknown type → `UnsupportedActionType` (caught upstream, action dropped).
- missing `action_type` → `NullAction` (`:115-116`).
- **`element_id` is force-cleared for non-web actions** — *"LLM sometimes hallucinates and returns
  element id for non-web actions such as WAIT, TERMINATE, COMPLETE"* (`:130-134`).
- `KEYPRESS`: key must be in `{Enter, Tab, Escape, ArrowDown, ArrowUp}` or a single alnum char,
  else **downgrade to `NullAction`** rather than raise (`:245-251`); `repeat = max(1, int(...) or 1)`.
- `SCROLL`: `direction.lower()`, not in `("up","down")` → default `"down"` with a warning (`:263-266`).
- `CLOSE_PAGE`: non-integer `tab_index` → close the current tab (`:275-286`).
- `EXTRACT` without a configured extraction goal → `NullAction` (`:293-295`).
- `SELECT_OPTION` requires an `option` object with at least one of label/value/index (`:185-198`).

**Mid-list execution (`skyvern/forge/agent.py:3073-3345`)** is richer than browser-use's:
- a **linked list keyed by `element_id`** is built first (`:3075-3091`), so when the same element
  appears twice the second occurrence is reachable as `node.next`.
- `refresh_working_page` signal → reload and `break` the rest (`:3101-3134`).
- `allow_stale_refresh=action_idx > 0` is passed to the handler with the comment *"Only actions
  after the first can be stale: an earlier action in this same batch may have remounted/reflowed
  this one's target away from the shared pre-batch scrape"* (`:3208-3211`) — the single most
  important sentence for batching against a **shared pre-batch snapshot**, which is exactly what
  NetGent would be doing.
- lookahead: for `INPUT_TEXT`, if the next action is a `KEYPRESS` or targets the same element,
  set `skip_auto_complete_tab = True` (`:3187-3196`) — the auto-Tab that normally closes an
  autocomplete would steal focus from the next batched action.
- outcome routing (`:3268-3343`): success + `skip_remaining_actions` → `break`; a failed
  `DecisiveAction` → log, don't stop, don't retry; failure with `not stop_execution_on_failure` →
  log, continue; otherwise if `action_node.next` exists → `continue` (a later action on the same
  element may still work); else mark the **whole step failed and return**, which triggers a step
  retry from a fresh scrape.

**`browser_action_policy.py` is a security firewall over the closed set**, and its taxonomy is
worth stealing for the batching policy because it is the same partition: `_ACTION_CLASSES`
(`:177-207`) maps each `ActionType` to `BENIGN` (null, wait, hover, scroll, move, go_back,
close_page, switch_tab) / `READ` (extract) / `TERMINAL` (terminate, complete) / `MUTATING` (click,
input_text, paste_text, upload_file, select_option, checkbox, keypress, solve_captcha,
verification_code) / `NAVIGATION` (goto_url, new_tab, reload_page, go_forward) / `EGRESS`
(download_file) / `UNRESOLVABLE` (drag, left_mouse) / **`UNSUPPORTED` (`EXECUTE_JS`)**. A
production browser agent classifies arbitrary JS as *categorically unsupported* by its own policy
engine — independent support for NetGent's no-JS-eval decision (§6.4).

### 3.3 Stagehand v3 — `act` is observe→pick→Playwright method, and `fillForm` is the bounded list

`observe(instruction)` returns `Action[]` (`packages/docs/v3/references/observe.mdx:139-155`):

```typescript
interface Action {
  selector: string;        // XPath
  description: string;
  method?: string;         // "click" | "fill" | "type" | ...
  arguments?: string[];
}
```

`act()` accepts either an NL string (→ internal observe) or an `Action` straight from `observe`,
so **`observe → validate → act` is a supported, documented workflow** — with `%variableName%`
placeholders left in `arguments` precisely so the caller can inspect an action before running it
(`observe.mdx:87-93`, "Validate Then Act" tab). That is NetGent's compile-then-replay split
expressed as an API.

`method` resolves through a fixed map — `METHOD_HANDLER_MAP`
(`packages/extension/handlers/handlerUtils/actHandlerUtils.ts:114-131`):

```
scrollIntoView, scrollByPixelOffset, scrollTo, scroll, "mouse.wheel",
fill, type, press, click, doubleClick, dragAndDrop,
nextChunk, prevChunk, selectOptionFromDropdown, selectOption, hover
```

This is a closed whitelist of Playwright method names — structurally identical to our
`ALLOWED_LOCATOR_FNS` (`schema/actions.py:15-29`), applied to verbs instead of locators.

The **DOM-mode agent tool list** is (`packages/docs/v3/references/agent.mdx:258`):
`act, fillForm, ariaTree, extract, goto, scroll, keys, navback, screenshot, think, wait, search`
— 12 native AI-SDK tools. Hybrid mode adds coordinate tools (`click, type, dragAndDrop,
clickAndHold, fillFormVision`). Two are directly relevant:

**`fillForm`** (v3.7.5 `packages/core/lib/v3/agent/tools/fillform.ts`):

```typescript
description: 'FORM FILL - MULTI-FIELD INPUT TOOL\nFill 2+ form inputs/textareas at once. …'
inputSchema: z.object({ fields: z.array(z.object({ action: z.string() })).min(1) })
execute: async ({ fields }) => {
  const observeResults = await v3.observe(`Return observation results for the following actions: ${fields.map(f => f.action).join(", ")}`)
  for (const res of observeResults) {
    const actResult = await v3.act(res, actOptions)
    replayableActions.push(...(actResult.actions as Action[]))
  }
  v3.recordAgentReplayStep({ type: "fillForm", fields, observeResults, actions: replayableActions })
}
```

**This is the exact shape NetGent should copy**: one LLM tool call carrying N field intents →
one grounding pass → N individual acts → **N replayable `Action`s recorded**. The compound exists
in the *agent's* vocabulary and is absent from the *artifact's*.

**`keys`** (`tools/keys.ts`) merges type-into-focus and press-a-key behind `method: "press" | "type"`
plus `repeat` — and documents the trade-off: *"Unlike the type tool which clicks then types into
coordinates, this sends keystrokes directly to wherever focus currently is… Preferred when: input
is already focused, text needs to flow across multiple fields (e.g., verification codes)"*.

`scroll` (`tools/scroll.ts`) is `{direction: "up"|"down", percentage?: 1..200}` defaulting to 80% —
a percentage-of-viewport model, like our `pages: float`.

### 3.4 Playwright MCP — snapshot refs, the reference `fill_form`, and `type{submit}`

The implementation now lives in the Playwright monorepo
(`packages/playwright-core/src/tools/backend/`, per `playwright-mcp/src/README.md`).

**Addressing.** Every element-taking tool extends `elementSchema` (`snapshot.ts:30-33`):

```typescript
export const elementSchema = z.object({
  element: z.string().optional().describe('Human-readable element description used to obtain permission to interact with the element'),
  target:  z.string().describe('Exact target element reference from the page snapshot, or a unique element selector'),
});
```

`element` exists **only for the permission prompt** — the human/host sees "Click the Sign in
button", not `e12`. Resolution (`tab.ts:497-519`):

```typescript
if (!param.target.match(/^(f\d+)?e\d+$/)) { /* treat as a selector; page.$ must match */ }
else {
  let locator = this.page.locator(`aria-ref=${param.target}`);
  if (param.element) locator = locator.describe(param.element);
  ... catch { throw new Error(`Ref ${param.target} not found in the current page snapshot. Try capturing new snapshot.`) }
}
```

Refs are **frame-qualified** (`f2e12`) and **snapshot-scoped**: a stale ref is a hard error naming
the remedy. `targetLocators()` resolves a *batch* of params in one `Promise.all` — the plumbing
`browser_fill_form` needs.

**`browser_fill_form` (`form.ts:22-55`)** is the cleanest statement of "a list whose items are
still atomic actions":

```typescript
inputSchema: z.object({ fields: z.array(elementSchema.extend({
  name:  z.string().describe('Human-readable field name'),
  type:  z.enum(['textbox','checkbox','radio','combobox','slider']),
  value: z.string().describe('Value to fill in the field. If the field is a checkbox, the value should be `true` or `false`. If the field is a combobox, the value should be the text of the option.'),
})) })

handle: for (const field of params.fields) {
  const { locator, selector } = await tab.targetLocator({ element: field.name, target: field.target });
  if (type === 'textbox' || 'slider') { await locator.fill(secret.value); response.addAction({name:'fill', selector, text}) }
  else if (type === 'checkbox' || 'radio') { await locator.setChecked(value === 'true'); response.addAction({name: value==='true'?'check':'uncheck', selector}) }
  else if (type === 'combobox') { await locator.selectOption({label: value}); response.addAction({name:'select', selector, options:[value]}) }
}
```

One tool call → N `response.addAction(...)` records. **The recorded trace is atomic even though
the tool call was compound.** Note also that the field `type` enum, not the DOM, decides
fill-vs-check-vs-select — the model classifies the widget, which is what our `to_action` type
checks (`actions.py:64-79`) do from the snapshot instead.

**`browser_type{submit}` (`keyboard.ts:78-118`)** is type-and-submit, and it too decomposes:

```typescript
response.addAction({ name: 'fill', selector, text });   await locator.fill(secret.value);
if (params.submit) { response.addAction({ name:'press', selector, key:'Enter', modifiers:0 }); await locator.press('Enter'); }
```

Other tools worth noting: `browser_press_key` special-cases `Enter` into
`tab.waitForCompletion(...)`; `browser_select_option{values: array}` takes multiple values;
`browser_find{text|regex}` searches the a11y snapshot and returns matching nodes "which is cheaper
than capturing the whole snapshot when you only need to locate an element and its ref";
`browser_wait_for{time|text|textGone}`; `browser_evaluate{function}` and
`browser_run_code_unsafe{code}` — the latter self-describes as *"Unsafe: executes arbitrary
JavaScript in the Playwright server process and is RCE-equivalent."*

### 3.5 Vercel `agent-browser` — `@eN` refs and out-of-band batching

`snapshot` returns an a11y tree where *"Elements are annotated with refs like `[ref=e12]` that
other tools accept as `@e12` selectors. Use this before interacting with a page."*
(`packages/@agent-browser/eve/extension/tools/snapshot.ts`). Tools are one-verb, `selector`-typed:
`click{doubleClick,newTab,selector}`, `fill{clear,selector,text}`, `select_option{selector,value}`,
`set_checked{checked,selector}`, `press_key`, `hover`, `scroll`, `upload`, `drag`, `wait_for`,
`find`, `get`, `read`, `navigate`, `tabs`, `evaluate`, `console`, `network_requests`, `close`.
`set_checked{checked: bool}` is Skyvern's `desired_state` as a first-class verb — level-triggered,
so a replay is idempotent.

Batching is **out of band, not in the model's schema** (`README.md:237-254`):

```bash
agent-browser batch "open https://example.com" "snapshot -i" "screenshot"
agent-browser batch --bail "open https://example.com" "click @e1" "screenshot"
echo '[["open","https://example.com"],["snapshot","-i"],["click","@e1"]]' | agent-browser batch --json
```

`--bail` is browser-use's abort-on-failure as a CLI flag. Security controls are declared per
*action category*: `--confirm-actions eval,download`, `--action-policy ./policy.json`,
`--allowed-domains`, `--content-boundaries`, `--max-output`. Same partition as Skyvern's
`ActionClass`. Snapshot has a documented CDP-race retry (`snapshot.ts:11-27`) — one delayed retry
on `"CDP error"`, relevant to our `session.snapshot()`.

### 3.6 Agent-E — the two compound skills, and why they exist

Skills are AutoGen tool functions with `Annotated` params (`ae/core/skills/skill_registry.py`):
`click(selector, wait_before_execution)`, `entertext(EnterTextEntry{query_selector, text})`,
**`bulk_enter_text(entries: List[{query_selector, text}])`**,
**`enter_text_and_click(text_selector, text_to_enter, click_selector, wait_before_click_execution)`**,
`get_dom_with_content_type(content_type: 'text_only'|'input_fields')`, `get_url`, `open_url`,
`press_key_combination`, `get_user_input`, `pdf_text_extractor`.

`bulk_enter_text` is a plain `for entry in entries: await entertext(...)` loop returning a
per-entry result list (`enter_text_using_selector.py:225-262`) — again, compound in the tool,
atomic in execution and in the result record. Addressing is `[mmid='114']` — an injected
attribute, so the CSS selector *is* an index in disguise.

`get_user_input` is the `ask_human` action the brief asks about: Agent-E is the only surveyed
DOM agent that exposes one as a first-class skill.

### 3.7 Notte — single action, discriminated union, semantic `form_fill`

`_AgentCompletion` (`packages/notte-core/src/notte_core/agent_types.py:70-72`) is
`{state: AgentState, action: ActionUnion}` — **singular**. The union is built by a metaclass
registry (`actions.py:77-90, 156-165, 1033-1078`) split into `BrowserAction` (page-level) and
`InteractionAction` (element-level).

Addressing (`actions.py:1024-1030`, validator at `:1052+`): `id: str = ""` **or**
`selector: str | NodeSelectors`, with a model validator that raises
*"…need to provide either an action id or a selector"* if both are missing.
`InteractionAction` also carries `press_enter: bool | None` — type-and-submit as a flag on `fill`.

**`FormFillAction` (`actions.py:197-283`) is a *semantically keyed* compound**, not a positional
list. `value` is `dict[Literal["title","first_name","middle_name","last_name","full_name","email",
"company","address1","address2","address3","city","state","postal_code","country","phone",
"cc_name","cc_number","cc_exp_month","cc_exp_year","cc_exp","cc_cvv","username","password",
"current_password","new_password","totp"], str]` — the browser-autofill vocabulary. Its docstring
is a warning about exactly the failure mode a compound invites:

> The `form_fill` action requires field keys that match the page's actual field mapping.
> Do not guess keys from labels or HTML alone; use live observation or generated workflow
> code to confirm the field mapping first. … CRITICAL: If this action fails once, use the
> regular form fill instead.

Its validator strips nulls with the note *"Gemini fills all expanded properties with null for
unused fields"* and normalises `password → current_password` "for LLM compatibility" — two more
coercions worth having.

Also present: `MultiFactorFillAction` ("Only use it when filling in an OTP"), `FallbackFillAction`
("Only use if explicitly asked, or you failed to input with the normal fill action"), `CheckAction`
(level-triggered `value: bool`), `SelectDropdownOptionAction`, `UploadFileAction`,
`DownloadFileAction`, `CaptchaSolveAction`, `HelpAction`, `CompletionAction`, `ScrapeAction`,
`EmailReadAction` / `SmsReadAction` / `EmailVerificationReadAction`, `EvaluateJsAction`.

**Notte's structured-output ladder (`packages/notte-llm/src/notte_llm/engine.py:358-508`) is the
single most copyable thing in this document for `llm.py`:**

1. Provider-specific schema repair before the call: `fix_schema_for_gemini` (strip `$ref`/`$defs`,
   `additionalProperties`), `fix_schema_for_openai` (strict-mode subset), pass the pydantic model
   straight through for Anthropic, and **fall back to plain `json_object` for Anthropic-via-
   OpenRouter** because *"Bedrock doesn't support oneOf at all; Anthropic direct limits anyOf to
   16 parameters"* (`:374-380`). Our `AgentDecision` is flat, so we dodge this — but a
   discriminated union per action kind would walk straight into it.
2. `InvalidJsonResponseForStructuredOutput` or a 404 `ModelNotFoundError` → downgrade strict →
   `json_object` and **`tries += 1` so the downgrade doesn't consume a retry slot** (`:405-424`).
3. Strip ` ```json ` fences and known prefixes; if the content still doesn't start with `{`, append
   a user message saying so and loop (`:436-450`).
4. `ValidationError` → if any error is `json_invalid`, try `json_repair.repair_json` (`:491-507`).
5. Otherwise append a user message containing **`e.errors()` verbatim** plus targeted advice
   ("Trailing characters after the closing }", "Unescaped double quotes inside string values…
   MUST be escaped") and retry (`:462-483`).
6. After `nb_retries_structured_output + 1` attempts, raise `LLMParsingError` with the raw content.

### 3.8 LaVague — a YAML action list against an authorised XPath set

`NavigationEngine` prompts for a YAML list (`lavague-core/lavague/core/navigation.py:45-58`
declares the JSON schema `{actions: [{action: {name, args}}]}`). The driver's capability prompt
(`lavague-drivers-selenium/.../base.py:748-812`) enumerates six actions:

```
click(xpath) | setValue(xpath, value) | dropdownSelect(xpath, value)
setValueAndEnter(xpath, value)  -- "Like setValue, except then it presses ENTER.
                                   Use this tool can submit the form when there's no submit button."
hover(xpath) | scroll(xpath, value: UP|DOWN)
```

Addressing is full XPath, constrained by an explicit `Authorized Xpaths` set in the prompt and
*"You can only use one of the Xpaths included in the HTML. Do not derive new Xpaths."* — the
prompt-level analogue of our index bounds check. Dispatch (`base.py:324-352`) is a `match` over
the action name with `case _: raise ValueError(f"Unknown action: {action_name}")`, plus two
**failure actions the model can emit** — `failNoElement` → `NoElementException`, `failAmbiguous`
→ `AmbiguousException`. A `wait_for_idle()` runs after every item.

`hover`'s description is the frame-scroll trick we implemented independently: *"It can also be
used before scrolling to ensure the focus is in the correct container before performing the
scroll action"* — cf. our `ScrollAction.locator` (`schema/actions.py:137-150`).

### 3.9 BrowserGym — the action space as a configurable object, with the multi-action caveat in print

`HighLevelActionSet(subsets=[...], multiaction=True, strict=False)`
(`browsergym/core/src/browsergym/core/action/highlevel.py:300-330`) composes named subsets
(`:45-125`): `chat`, `infeas`, `bid`, `coord`, `nav`, `tab`, plus MiniWoB presets. The `bid` subset
is our set almost exactly — and it contains this comment (`:50-52`):

```python
"bid": [ scroll, fill,
    # These are not really needed and might pollute the action space, doing more harm than good
    # check,
    # uncheck,
    select_option, click, dblclick, hover, press, focus, clear, drag_and_drop, upload_file ],
```

The generated description tells the model, verbatim (`:468-474`):

> Multiple actions can be provided at once, but will be executed sequentially without any
> feedback from the page. **More than 2-3 actions usually leads to failure or unexpected behavior.**

versus, when `multiaction=False`: *"Only a single action can be provided at once."* Parsing
(`:502-518`) is a pyparsing grammar over python-call syntax; `strict=True` requires the whole
response to parse, `strict=False` searches for calls and skips prose between them;
`len(function_calls) > 1 and not self.multiaction` → `ValueError("Received a multi-action, only
single-actions are allowed.")`; an unknown name → `NameError(f"Invalid action type '{...}'.")`.
`to_tool_description(api="openai"|"anthropic")` (`:532-588`) emits **one tool per action** from the
python signature — a working reference if we ever want that shape.

### 3.10 The benchmark agents — where the action-space evidence comes from

**WebArena** (arXiv:2307.13854 §2.4, Figure 4) defines the 12-action baseline every later paper
ablates: `noop, click(elem), hover(elem), type(elem,text), press(key_comb), scroll(dir),
tab_focus(index), new_tab, tab_close, go_back, go_forward, goto(URL)`. On addressing:

> An element can be selected by its on-screen coordinates, (x,y), or by a unique element ID that
> is prepended to each element. … **With element IDs, the element selection is transformed into an
> n-way classification problem, thereby eliminating any disambiguation efforts required from the
> agent or the underlying implementation.**

Best GPT-4 agent: **14.41%** end-to-end SR (human 78.24%).

**WebVoyager** (arXiv:2401.13919 §3.4, App. C) is 7 actions with an explicit efficiency rationale:

- `Click [Numerical_Label]`
- `Type [Numerical_Label]; [Content]` — *"This is a composite action that involves selecting a text
  box, deleting any existing content within it, and then inputting new content. **To minimize
  interaction frequency, an automatic ENTER key press follows the input completion.**"*
- `Scroll [Numerical_Label or WINDOW]; [up or down]` — element-anchored scrolling for inner scrollers
- `Wait` · `GoBack` — *"We consider the forward action unnecessary because it can be achieved by
  repeating previous actions."*
- `Google` (jump to search engine) · `ANSWER; [Content]`

**SeeAct / Mind2Web** (arXiv:2401.01614): the action triple is `(e, o, v)` — element, operation,
value. Mind2Web *"supports three primary operations: Click, Type, and Select, **with Hover and
Press Enter operations integrated into Click to avoid ambiguity**"* (§3.1). Its Table 3 is the
addressing evidence (GPT-4V, 30 tasks/split, step SR %):

| Grounding | Cross-Task | Cross-Website | Cross-Domain |
|---|---|---|---|
| Element **Attributes** (model describes the element) | 16.1 | 12.1 | 19.0 |
| Image **Annotation** (SoM boxes + labels) | 20.3 | 13.9 | 23.7 |
| **Textual Choices** (index into 17 candidates) | **39.1** | **32.7** | **42.0** |
| Human **Oracle** | 61.9 | 65.0 | 62.1 |

> Element grounding via textual choice demonstrates the best performance under all metrics across
> all settings … on complex images with rich semantic and spatial relationships like webpage
> screenshots, severe hallucination is observed from GPT-4V. Specifically, it often fails to
> correctly map its generated element description (which is often correct according to oracle
> grounding) to the right bounding box and index label in the image.

**AgentOccam** (arXiv:2410.13825): §4.1 is an action-space-only intervention; the prompt says
*"You are ONLY allowed to use the following action commands. Strictly adheres to the given format.
**Only issue one single action.**"* (App. G.1). Removals and their stated reasons:

- `noop` — *"a distraction to the agent in most cases"*
- tab ops — *"only needed in limited cases of multi-site tasks"*
- `go_forward`, `goto` — *"utility is greatly constrained by the agent's poor memory of the
  relationship between a page's URL and its content"*
- `hover`, `press` — *"require LLMs to have embodied thinking of the current scenario, especially
  regarding the mouse position or keyboard operations, which it has not acquired during training"*
- `scroll` — replaced by loading the full page; *"agents tend to engage in aimless and repetitive
  scrolling when an essential link is not visible at the top of the page, wasting steps"*
- **dropdowns collapsed**: *"instead of selecting the menu and then an option, a single click
  command with the ID of the desired option now suffices"*

Additions: `note[content]`, `stop[answer]`, `go_home`, and the planning pair `branch[id][intent]` /
`prune[id][reason]`.

---

## 4. Measured effects

### 4.1 Action-space size — AgentOccam Table 17 (WebArena, GPT-4-Turbo, 812 tasks)

| Configuration | Overall SR % | Δ |
|---|---|---|
| Vanilla (WebArena replication) | 16.5 | — |
| **↓ Actions** (remove noop/hover/press/tabs/go_forward/goto; add note/stop/go_home) | **25.9** | **+9.4 (+57%)** |
| + X Scrolling (drop `scroll`, load full page) | 31.7 | +5.8 |
| + Obs Opt. (merge/markdownify the a11y tree) | 37.1 | +5.4 |
| + History (pivotal-node replay) | 38.2 | +1.1 |
| AgentOccam (+ branch/prune planning) | 43.1 | +4.9 |

Per-site for **↓Actions** alone: Shopping 16.6→23.5, Shopping Admin 15.9→23.6, GitLab 10.0→24.4,
Map 22.9→34.9, Reddit 21.7→33.0; Multisite **regresses** 16.7→12.5 (tab ops were removed).

Table 3, action counts across all tasks, Vanilla → ↓Actions:
`click` 2328 → **7119**, `type` 1024 → **2531**, `hover` 126 → 0, `press` 7 → 0, `goto` 511 → 0,
`new_tab` 20 → 0, `go_back` 71 → 52, `scroll` 132 → 370, plus `note` 194 / `stop` 512 / `go_home` 36.
Removing 6 verbs roughly **tripled productive `click`s and 2.5×'d `type`s** — the steps weren't
being spent elsewhere, they were being wasted.

### 4.2 Element addressing

SeeAct Table 3 above: **textual-choice indexing beats set-of-mark image annotation by
18.8/18.8/18.3 absolute points** on the same model and the same tasks. Grounding is also the
dominant residual error: oracle grounding is 61.9/65.0/62.1, so *"the best grounding strategy
still has a 20-30% gap with oracle grounding."* NetGent's `index` addressing is on the winning
side of the only controlled comparison in this survey.

### 4.3 Multi-action

**No controlled ablation exists in any surveyed source.** What exists:

- BrowserGym ships the caveat in the model-facing prompt: *"More than 2-3 actions usually leads to
  failure or unexpected behavior"* (`highlevel.py:471`) — a maintainer's empirical claim, not a
  measurement.
- browser-use's default is `max_actions_per_step = 5` (`agent/views.py:71`) and it truncates
  silently past that; its prompt's whole "Recommended combinations" list is
  `input+input+input+click`, `input+input`, `scroll+scroll`, `click+click`.
- OpenAI's computer-use docs state the rationale for batching directly: *"later turns can batch
  actions into the same `computer_call`"*, which *"improves efficiency by allowing the model to
  plan multiple steps before awaiting visual feedback."* [unverified — vendor doc claim, no number]
- browser-use's headline 89.1% on WebVoyager is disputed as non-reproducible by third parties.
  [unverified — search-result claim, not traced to a primary experiment; do not cite it]

The honest statement: **batching's benefit is fewer LLM calls, and it is asserted rather than
measured.** For NetGent that benefit is real and quantifiable in our own `netgent eval stress`
usage counters (`agent/llm.py:39`), which is where it should be measured.

### 4.4 Tool count vs accuracy

Two verified primary sources, both about *large* tool catalogues:

- **RAG-MCP** (arXiv:2505.03275, Gan & Sun, 6 May 2025): retrieval-gated tool selection
  *"more than triples tool selection accuracy (43.13% vs 13.62% baseline)"* and cuts prompt tokens
  by over 50%.
- **"How Many Tools Should an LLM Agent See? A Chance-Corrected Answer"** (arXiv:2605.24660,
  Repantis et al., 23 May 2026, rev. 7 Jun 2026): on BFCL (370 tools) an adaptive shortlist hits
  90.3% coverage showing ~7 tools on average vs 90.8% with a fixed 50; Claude Sonnet 4.6 selection
  accuracy 93.1% (adaptive) vs 87.1% (fixed 5).

**These do not apply at 11 actions.** They constrain the *growth* question: they are evidence
against adding a long tail of niche actions, not evidence for or against the current set. Blog
figures circulating as "accuracy degrades past 10-15 tools" and "740 tools → 0-20%" are secondary
and were not traced to a primary source. [unverified — do not cite]

### 4.5 Where the closed set converges

Counting the surveyed DOM agents, every one has: click, fill/type, select, scroll, goto, back,
wait, and a done/terminate pair. Divergence is entirely in the tail: hover (kept by us, Skyvern,
Stagehand, Playwright MCP; **removed by AgentOccam, folded into click by Mind2Web**), press/keys
(same split), upload (us, browser-use, Skyvern, Notte, agent-browser, Playwright MCP), tabs (not
us), extract/scrape (not us), JS eval (browser-use, Notte, agent-browser, Playwright MCP; Skyvern
classifies it `UNSUPPORTED`). Our 11 sit in the convergent core plus `hover` and `press`.

---

## 5. Recommendation for NetGent

### 5.1 Keep one atomic action as the unit; add a bounded list as an optimisation

**Recommendation: adopt a bounded `actions: list[AgentAction]` with `max_length=4`, defaulting
to 1 in the prompt's guidance and gated behind a flag until the eval says it pays.**

The formalism is untouched because the mapping is one-to-one on *executed* items: each list item
becomes one `AgentStep`, and `compiler.py:111` already makes one `Transition` per `AgentStep`.
This is precisely Playwright MCP's `browser_fill_form` (one call → N `response.addAction`) and
Stagehand's `fillForm` (one call → N `recordAgentReplayStep` actions). No compound reaches
`schema/actions.py`; the artifact is byte-identical to what a single-action run would produce.

The upside is concrete for our workload: `evals/sweep.py` sweeps forms, and a 12-field form is
12 LLM calls today. `input+input+input+click` is browser-use's #1 recommended combination and our
dominant pattern.

The risk is equally concrete and named in Skyvern's source: *"an earlier action in this same batch
may have remounted/reflowed this one's target away from the shared pre-batch scrape"*
(`agent.py:3209-3211`). Our snapshot is taken once per `observe` node and the locator is verified
once in `_verified_locator` (`graph.py:161-176`) — both would be stale for items 2..k.

**Sketch — `decision.py`:**

```python
AgentActionKind = Literal["click","fill","select","upload","hover","press","goto","scroll","go_back","wait"]

# Which kinds change the page and therefore end a batch. Mirrors browser-use's
# terminates_sequence (tools/registry/views.py:22-25) and Skyvern's ActionClass NAVIGATION.
TERMINATES_BATCH: frozenset[AgentActionKind] = frozenset({"goto", "go_back", "wait"})

class AgentAction(BaseModel):
    """One atomic action. Exactly what becomes one NFA transition."""
    kind: AgentActionKind
    index: int | None = Field(default=None, description="Element index from the observation.")
    text: str | None = None        # fill
    value: str | None = None       # select
    url: str | None = None         # goto
    keys: str | None = None        # press
    down: bool | None = None       # scroll
    pages: float | None = None     # scroll
    seconds: float | None = None   # wait
    # ... _coerce_index and the hardening from §5.5 live here

class AgentDecision(BaseModel):
    """One step. `done` is the only exit."""
    reasoning: str
    done: bool = False
    success: bool = False          # meaningful only when done
    actions: list[AgentAction] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "AgentDecision":
        if self.done and self.actions:
            raise ValueError("done must be returned alone, with no actions")
        if not self.done and not self.actions:
            raise ValueError("return at least one action, or done=true")
        return self
```

`done` moves out of the `kind` enum into its own boolean, which enforces browser-use's
*"You are ONLY ALLOWED to call `done` as a single action"* (`system_prompt.md:131`) in the schema
rather than at runtime (`agent/service.py:2764-2768`). §5.7 argues why.

**Sketch — `graph.py::act`, the two guards + per-item recording:**

```python
async def act(state: AgentState) -> Command[Literal["observe"]]:
    n, decision, snapshot = state["n"], state["decision"], state["snapshot"]
    steps: list[AgentStep] = []
    for i, item in enumerate(decision.actions):
        if i > 0:
            await session.page.wait_for_timeout(WAIT_BETWEEN_ACTIONS_MS)
            # Guard A (runtime): the previous item navigated -> the snapshot's indices are
            # meaningless now. Skyvern agent.py:3209; browser-use service.py:2825-2831.
            if session.page.url != steps[-1].url:
                history.append(f"{n}. page changed after action {i} — {len(decision.actions)-i} queued action(s) skipped")
                break
            # Guard B (staleness): this item's element must still look like what we snapshotted.
            # Skyvern's skyvern_element_hash, applied per item instead of per step.
            if not await _element_still_matches(session, snapshot, item.index):
                history.append(f"{n}. element {item.index} changed after action {i} — remaining actions skipped")
                break
        error, action = None, None
        try:
            upload = agent.upload_path() if item.kind == "upload" else None
            # Verify the locator HERE, not up front: items 2..k are resolved against the live page.
            locator_for, note = await _verified_locator(session, snapshot, item.index)
            action = to_action(item, snapshot, upload_path=upload, locator_for=locator_for)
            ... requires_closed_shadow carry-over, unchanged ...
            await session.dispatch(action)
        except (ExecutionError, ValueError) as exc:
            error = str(exc)
        # One AgentStep per EXECUTED item -> one Transition. Sub-numbered so `n` stays the LLM step.
        step = AgentStep(n=n, kind=item.kind, reasoning=decision.reasoning, url=session.page.url, error=error)
        if error is None:
            step.action, step.locator_check = action, note
            step.dialogs = session.dialogs_since_last_action()   # per item — compiler.py:99 needs this
        steps.append(step)
        history.append(f"{n}.{i} {item.kind}({item.index}){' -> FAILED: ' + error if error else ''}")
        if error is not None:
            break                                    # abort the remainder (universal)
        if item.kind in TERMINATES_BATCH:
            break                                    # Guard A (static)
    await agent.capture_screenshot(session, steps[-1])
    return Command(update={"steps": steps}, goto="observe")
```

Four notes on this sketch:

1. **`dialogs_since_last_action()` must be drained per item.** `ActionDispatcher.dispatch` already
   calls `self._dialogs.mark_action()` at `browser/actions.py:264`, so the per-item semantics are
   free — but only if we read it after each dispatch. Otherwise `compiler.py:99-101` attributes
   item 1's confirmation dialog to item 4's transition, which is a wrong state condition, silently.
2. **`_verified_locator` moves inside the loop.** It is one `capture_locator` round-trip per item;
   at k≤4 that's cheap, and it is the only way items 2..k get a chain verified against the page
   they will actually run on (R1/R4 provenance stays honest).
3. **`click` is deliberately *not* in `TERMINATES_BATCH`.** browser-use classifies it "potentially
   page-changing — monitored at runtime" and relies on Guard A. That's right: our dominant win
   (`fill × n` then `click Submit`) requires the submit click to be *last*, not forbidden.
4. **`wait` is in `TERMINATES_BATCH`.** For NetGent `wait` is not idle time — it's the dwell where
   the traffic we are collecting happens (`schema/actions.py:167-169`). Nothing may be queued
   behind it against a pre-dwell snapshot.

**Prompt change** (`prompt.py`), lifted from browser-use `system_prompt.md:164-181`:

```
Return one to four actions to run in order. Prefer ONE unless several act on the same page
and you already know all their values.
- Safe to batch: fill, select, hover, press, scroll, upload — they do not leave the page.
- Put click LAST in a batch. If it navigates, the remaining actions are skipped automatically.
- goto, go_back and wait always end the batch; put them alone or last.
- If the page changes mid-batch, the rest are dropped and you get a fresh observation. That is
  normal — reissue whatever did not run.
- Do not batch two different plans. One goal per step.
```

**Roll-out.** Gate on `BrowserAgent(max_actions_per_step: int = 1)`; `1` reproduces today's
semantics exactly (the loop runs once and `TERMINATES_BATCH` never fires). Then run
`netgent eval stress` / `eval matrix` at 1 vs 4 and compare `llm.usage["calls"]`, wall clock, and
compiled-workflow validation pass rate. **Ship the default change only if the pass rate is
unchanged.** This is the one place where we can produce the ablation the literature is missing.

### 5.2 Compound actions: add none to the closed set; add at most one to the agent's vocabulary

`schema/actions.py` must not grow a `fill_form` or a `fill{submit}`. The whole point of the
artifact is that one transition = one atomic action; a `submit: bool` on `FillAction` would make
one transition mean two, and the validator's replay would no longer be a faithful re-execution.

The bounded action list from §5.1 already delivers everything the surveyed compounds deliver:

| Compound in the wild | NetGent equivalent |
|---|---|
| Playwright MCP `browser_fill_form{fields[]}` | `actions: [fill, fill, fill, …]` |
| Stagehand `fillForm{fields[]}` | same |
| Agent-E `bulk_enter_text(entries)` | same |
| Playwright MCP `browser_type{submit}` | `actions: [fill, press{keys:"Enter"}]` |
| WebVoyager `Type` (auto-Enter) | same |
| LaVague `setValueAndEnter` | same |
| Notte `fill{press_enter}` | same |
| Agent-E `enter_text_and_click` | `actions: [fill, click]` |
| agent-browser `set_checked{checked}` | `click` (dispatch already reads live state, `browser/actions.py:73-81`) |

Two that the list does *not* cover, and my read on each:

- **`dropdown_options(index)`** (browser-use `tools/service.py:1675`) — enumerate a dropdown's
  options before choosing. **Not needed.** `DomElement.options` is already in the snapshot
  (`browser/dom/models.py:40`) and rendered by the serializer, and `to_action` validates the chosen
  value against it (`actions.py:77-78`). We solved this at observation time, which is strictly better.
- **`extract` / `scrape`** — **out of scope, deliberately.** NetGent's product is network traffic,
  not scraped data; adding an LLM extraction verb would put a model call inside a path that must
  stay zero-LLM at replay, and `executor/` already covers page-extracted parameters with guards.
  If a *compile-time-only* read verb is ever wanted, browser-use's `search_page` (regex grep over
  page text, "Zero LLM cost, instant") is the one to copy, not `extract`.

**AgentOccam's dropdown collapse is worth a second look, though.** *"instead of selecting the menu
and then an option, a single click command with the ID of the desired option now suffices"* — for
custom (non-`<select>`) dropdowns we already do the two-step inside `_select`
(`browser/actions.py:186-198`: click open, click the option by role/text). That means we have
AgentOccam's ergonomics *and* a single artifact action. Keep it. It's a good decision that
predates knowing why.

### 5.3 Index vs ref addressing: keep the index, borrow the ref's failure mode

Keep `index: int`. It has the only supporting measurement in the literature (SeeAct §4.2), it is
what browser-use, WebArena, WebVoyager and AgentOccam use, and it is what makes element choice
"an n-way classification problem" (WebArena §2.4).

Two things to borrow:

1. **Playwright MCP's error text**, not its ref format. Our bounds failure is
   `f"{decision.kind} needs a valid element index, got {decision.index}"` (`actions.py:47`) —
   accurate but it doesn't tell the model what to do. Playwright MCP throws
   `Ref {target} not found in the current page snapshot. Try capturing new snapshot.`
   and browser-use returns `Element index {n} not available - page may have changed. Try refreshing
   browser state.` Both name the remedy. Ours should say the range and the remedy:
   `f"index {decision.index} is not in this observation (valid: 0-{len(elems)-1}); act on a listed element or scroll for more"`.
2. **Skyvern's `skyvern_element_hash`** as the per-item batch staleness check (`_element_still_matches`
   in §5.1). We have no element identity today. The cheap version is a tuple over fields the
   snapshot already carries: `(el.tag, el.role, el.name, el.type, tuple(el.frame_path))` plus the
   first selector candidate — recompute for that index against a fresh cheap probe, or simply
   re-resolve the captured chain and check `count() == 1`. The latter is one round-trip and reuses
   `capture_locator`, so it costs nothing new.

`agent-browser`'s `@eN` and Playwright MCP's `f2e12` are both just indices with a sigil and frame
prefix. The sigil buys one thing we lack: it makes `"3"` unambiguously an element reference rather
than a string that might be a value. Our `_coerce_index` exists because the model echoes `"[3]"`.
Not worth a format change; worth keeping the coercion.

### 5.4 Native tool calling: we are already on it; do not split into N tools

**Verified locally at the pinned versions** (`langchain 1.3.15`, `langchain-core 1.5.5`,
`langchain-anthropic 1.5.6`, `langchain-openai 1.5.1`, `langchain-google-genai 4.3.4`):

```
ChatAnthropic.with_structured_output(schema, *, include_raw=False, method: Literal['function_calling','json_schema'] = 'function_calling', **kwargs)
ChatOpenAI.with_structured_output(schema=None, *, method: Literal['function_calling','json_mode','json_schema'] = 'function_calling', include_raw=False, strict=None, **kwargs)
ChatGoogleGenerativeAI.with_structured_output(schema, method: Optional[Literal['function_calling','json_mode']] = 'function_calling', *, include_raw=False, **kwargs)
```

All three default to `function_calling`. `agent/llm.py:36` is therefore already emitting **one
forced tool named `AgentDecision`** — the identical mechanism to browser-use's
`ToolChoiceToolParam(type='tool', name='AgentOutput')` (`llm/anthropic/chat.py:437-439`). The
question "structured output or native tool calling?" is a false dichotomy here; the real question
is **one tool or eleven**.

**Recommendation: stay at one tool.** Reasons, in order of weight:

1. **No surveyed DOM agent uses one-tool-per-action.** browser-use, Notte and LaVague all put the
   union inside one schema. Stagehand's 12 tools are *primitives at different levels* (`act`,
   `extract`, `ariaTree`, `think`) — not one tool per Playwright verb; its verbs live in
   `METHOD_HANDLER_MAP` behind `act`. Anthropic's 17-member computer toolset is the real
   counter-example, and it's vision/coordinate, where the tools genuinely differ in shape.
2. **Multi-action becomes hard.** Native tool calling gives you N *parallel* tool calls with no
   ordering contract and no way to bound the list in the schema. `actions: list[AgentAction] =
   Field(max_length=4)` is a schema-level guarantee; "the model happened to emit 3 tool_use blocks"
   is not. browser-use has to truncate in Python (`agent/service.py:1957`) precisely because it
   can't express the bound; we can.
3. **`reasoning` is a top-level field.** One tool keeps `reasoning` (and `success`) alongside the
   actions in a single validated object. With N tools it becomes prose outside the tool call, which
   is exactly the parsing surface `graph.py:99-104` exists to avoid.
4. **Schema-compat risk grows.** Notte's `engine.py:374-380` had to special-case Anthropic-via-
   OpenRouter because *"Bedrock doesn't support oneOf at all; Anthropic direct limits anyOf to 16
   parameters"*. Our current `AgentDecision` is a **flat** model with a `Literal` kind — no `anyOf`,
   no `$ref`. Keep it that way: prefer the flat `AgentAction` above over a discriminated union of
   11 pydantic classes, even though the union is prettier. The union is what breaks on Gemini and
   Bedrock, and `to_action`'s `match decision.kind` already gives us the same dispatch safety.
5. The tool-count evidence (§4.4) is about 370-3251 tools. It says nothing at 11. Don't cite it
   either way.

**Where native tool calling *would* pay** is a different agent: a compile-time *validator* or
*triage* agent that mixes read verbs (`search_page`, `find_elements`, `ariaTree`) with the browser
verbs. There, one tool per capability is right, `bind_tools` is the mechanism, and BrowserGym's
`to_tool_description(api=...)` (`highlevel.py:532-588`) is the reference for generating it from
signatures. For the explorer's inner loop, one tool.

The one LangChain knob worth flipping is `method`. `ChatAnthropic(..., method="json_schema")` uses
Claude's dedicated structured-output feature rather than forced tool calling; `ChatOpenAI(...,
method="json_schema", strict=True)` likewise. Worth A/B-ing in `eval stress` against parse-failure
rate, since a parse failure currently costs a whole step (`graph.py:104`).

### 5.5 Validation and coercion

**In `decision.py` / `AgentAction`** — the Skyvern ladder (§3.2), ordered by expected yield:

```python
@field_validator("kind", mode="before")
@classmethod
def _normalize_kind(cls, v: object) -> object:
    # Skyvern: action["action_type"].upper() + legacy aliases (parse_actions.py:119-126)
    if not isinstance(v, str):
        return v
    k = v.strip().lower().replace(" ", "_").replace("-", "_")
    return {
        "type": "fill", "input": "fill", "input_text": "fill", "enter_text": "fill",
        "type_text": "fill", "select_option": "select", "upload_file": "upload",
        "press_key": "press", "keypress": "press", "navigate": "goto", "back": "go_back",
        "check": "click", "uncheck": "click",        # Mind2Web/Skyvern: toggles ARE clicks
    }.get(k, k)

@field_validator("index", mode="before")
@classmethod
def _coerce_index(cls, value: object) -> object:
    # unchanged for str; add: floats ("3.0" from Gemini), and reject negatives early
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value)
        return int(digits) if digits else None
    return value

@model_validator(mode="after")
def _drop_index_on_pageless_kinds(self) -> "AgentAction":
    # Skyvern parse_actions.py:130-134 — "LLM sometimes hallucinates and returns element id
    # for non-web actions such as WAIT, TERMINATE, COMPLETE". scroll keeps its index (it
    # anchors the frame), goto/go_back/press/wait do not.
    if self.kind in ("goto", "go_back", "wait", "press") and self.index is not None:
        object.__setattr__(self, "index", None)
    return self
```

Plus two soft-repairs at the `to_action` boundary rather than hard raises, where a raise costs a
whole step for something we can fix:

- **`scroll` with a bad direction** → default `down` with a note, per Skyvern
  (`parse_actions.py:263-266`). Ours already defaults (`actions.py:85`); keep, but log it into
  `history` so the model learns.
- **`select` whose `value` isn't an option** — today raises (`actions.py:77-78`). Try a
  case-insensitive / whitespace-normalised match against `el.options` first; only raise if that
  fails. Skyvern accepts label *or* value *or* index for the same reason
  (`parse_actions.py:185-198`), and our dispatcher already falls back value→label
  (`browser/actions.py:181-185`).

**Keep raising** for the genuinely ambiguous cases we already handle well: `fill` on a `<select>`
and `select` on a non-`<select>` (`actions.py:64-76`). Those error strings already name the
remedy, which is the right pattern.

**In `llm.py`** — adopt Notte's ladder (§3.7), in this order:

1. Currently a `None` `parsed` raises `ValueError` (`llm.py:51-52`) which `graph.py:101` catches
   and turns into a lost step. **Retry in-place first** (2 attempts) before spending the step,
   appending the validation error to the message list the way Notte does (`engine.py:474-483`).
   `include_raw=True` already gives us `result["parsing_error"]`, which is the pydantic
   `ValidationError` — feed `e.errors()` back verbatim, it is far more actionable than `str(exc)`.
2. On a provider schema rejection, downgrade `method="json_schema"` → `"function_calling"` (or
   `"json_mode"`) **without consuming a retry slot** (`engine.py:410,422`).
3. Only then fall through to today's behaviour (history note + re-observe), which stays as the
   final backstop.

`json_repair` (Notte `engine.py:491-507`) is probably unnecessary for us — it earns its keep when
the model free-writes JSON, and we're on forced tool calling where the provider guarantees
well-formed JSON. Revisit only if `eval stress` shows `json_invalid` errors.

### 5.6 Things worth stealing that aren't about lists

- **`confidence_float` per action** (Skyvern `extract-action.j2:25`, `actions.py:143`). The
  generator currently compiles every successful step identically. A per-action confidence would
  let `compiler.py` mark low-confidence transitions for the validator to scrutinise, and would give
  multi-run synthesis a tiebreak when two runs disagree on a step. **Cheap: one float field.**
- **`user_detail_query` / `user_detail_answer`** (`extract-action.j2:23-24`). Today parameterisation
  is post-hoc string substitution of the `-p` sample value across the compiled workflow
  (`compiler.py:122+`), which will mis-fire whenever a sample value coincides with page text. Asking
  the model, per fill, "what is this field for, generically?" plus "what did you put there?" gives
  the compiler a *declared* parameter binding instead of an inferred one. **This is the highest-value
  idea in this document that is not about action lists.**
- **`click_context.desired_state`** (`extract-action.j2:49`) — level-triggered toggle intent.
  Our dispatcher already reads live state and computes the target
  (`browser/actions.py:73-81`), so a replayed checkbox click is idempotent *by accident of the
  dispatcher*. Recording the intent would make it idempotent *by artifact*, which is strictly
  better for a determinism engine. Costs one optional `bool` on `ClickAction` and does not break
  the one-action-per-transition rule.
- **Playwright MCP's `element` companion field** (`snapshot.ts:31`) — a human-readable description
  alongside the ref, used only for the permission prompt and `locator.describe()`. For us it would
  make trajectories and compile-time provenance readable ("click the Submit button") without
  affecting dispatch. Nearly free; good for `netgent trajectory`.
- **BrowserGym's `report_infeasible(reason)`** and LaVague's `failNoElement`/`failAmbiguous` — we
  fold all of this into `done(success=False)`. That's fine, but a structured reason (rather than
  free prose in `stopped_reason`) would make sweep triage mechanical.

### 5.7 `done` semantics

Current: `done` is a `kind` in the same enum as the browser verbs, with `success: bool` and the
reason in `reasoning` (`decision.py:12-20`, `graph.py:107-116`).

Three changes, in priority order:

1. **Move `done` out of the action enum** (as in §5.1). Today nothing structurally prevents
   `kind="done"` with an `index`, and if we add lists nothing prevents `done` at position 2 —
   which is the exact bug browser-use guards against at runtime
   (`agent/service.py:2764-2768`) and in the prompt (*"You are ONLY ALLOWED to call `done` as a
   single action"*). A `done: bool` with a `model_validator` makes it a schema error.
2. **Keep `success=False` as the give-up channel and keep it prominent.** Our prompt's CAPTCHA rule
   (`prompt.py:64-66`) matches Skyvern's `TerminateAction`, and browser-use's pre-done checklist
   is worth borrowing nearly verbatim (`system_prompt.md:150-152`):
   > **If ANY requirement is unmet, uncertain, or unverifiable — set `success` to `false`.**
   > Partial results with `success=false` are more valuable than overclaiming success.
   For NetGent this is load-bearing in a way it isn't for browser-use: a false `success=True`
   compiles a workflow that doesn't do the task, and `validator/` will replay it happily because
   the replay *is* faithful — it's the trajectory that was wrong.
3. **Do not add a structured-output payload to `done`.** browser-use's `StructuredOutputAction[T]`
   (`tools/views.py:114-119`) and Skyvern's `CompleteAction.data_extraction_goal` exist because
   their product is extracted data. Ours is traffic. `success: bool` plus `reasoning` is the whole
   contract, and `texts_seen` (`browser_agent.py:53-56`) already covers post-hoc verification of
   transient success banners.

One thing **not** to adopt: AgentOccam's `note`/`branch`/`prune` planning actions. They gave
+4.9pts on WebArena, but they are *planner state*, and our formalism says no code and no planner
state in artifacts. A planning action would either have to be filtered out at compile time (making
it dead weight in the action space) or leak into the NFA. If long-horizon planning becomes the
bottleneck, it belongs in `orchestrator.py` as a separate graph node, not in the action set.

---

## 6. What NOT to do

**6.1 Don't allow an unbounded action list.** Skyvern's is unbounded and it pays for it with the
most complex mid-list recovery machinery in the survey (linked lists by `element_id`, stale-refresh
flags, lookahead for auto-Tab suppression, four distinct failure branches). browser-use bounds at 5
and truncates. BrowserGym warns at 2-3. Bound at 4 in the schema.

**6.2 Don't add coordinate addressing.** browser-use gates it behind
`set_coordinate_clicking(enabled)` for specific models only (`tools/service.py:2144-2160`), Skyvern
classifies `DRAG`/`LEFT_MOUSE` as `UNRESOLVABLE` in its policy engine
(`browser_action_policy.py:205-206`), and SeeAct measures image-annotation grounding at roughly
half the accuracy of textual choices. Coordinates also cannot be compiled into a durable locator
chain, which makes them incompatible with `schema/actions.py` outright.

**6.3 Don't add tab actions.** AgentOccam removed them and its **Multisite** score *fell*
(16.7 → 12.5) while every other site rose — so tabs do matter for genuinely multi-site tasks. But
they were removed because *"they are only needed in limited cases"*, and NetGent's workflows are
single-site captures. Adding `switch_tab` costs an action slot, a `frame_path`-style addressing
extension, and a `BrowserSession` concept we don't have. Revisit only when a real workflow needs it.

**6.4 Don't add a JS-eval action.** This decision now has outside support worth recording:
- Skyvern's policy engine classifies `EXECUTE_JS` as `ActionClass.UNSUPPORTED`
  (`browser_action_policy.py:207`) — the one action type its firewall refuses categorically.
- Playwright MCP's equivalent self-describes as *"Unsafe: executes arbitrary JavaScript in the
  Playwright server process and is RCE-equivalent"* (`browser_run_code_unsafe`).
- agent-browser puts `eval` in the `--confirm-actions` category list by default in its own docs.
- browser-use's prompt has to carve out an exception because the model reaches for it wrongly:
  *"Shadow DOM elements with [index] markers can be clicked directly with click(index) — do NOT use
  evaluate() to click them."*
- browser-use also classifies `evaluate` as always-page-changing and forbids chaining after it:
  *"evaluate runs arbitrary JS that can modify the DOM, so it is never safe to chain other actions
  after it."*

For NetGent the argument is stronger still and independent of safety: **a JS action cannot be
compiled.** `schema/actions.py:1-5` states the rule — *"never generated code, never `exec`"* — and
`ALLOWED_LOCATOR_FNS` is *"the security boundary for replay"*. An `evaluate` transition would put a
string of JS into a YAML artifact, and there is no whitelist that makes that safe or deterministic.
Note that our *dispatcher* does use `evaluate` internally (`browser/actions.py:61-66, 81, 141-155,
233-235`) — that is fine and different: it is fixed, audited code inside the executor, not
model-authored code inside an artifact.

**6.5 Don't split `click` into `click`/`check`/`uncheck`/`select_radio`.** Three independent data
points: Skyvern's `CheckboxAction` comment (*"causes more harm than it does good… Treating checkbox
actions as click actions seem to perform way more reliably"*), BrowserGym's commented-out
`check`/`uncheck` (*"not really needed and might pollute the action space, doing more harm than
good"*), and Mind2Web folding Hover and Press-Enter into Click *"to avoid ambiguity"*. Our
`to_action` comment at `actions.py:56-58` says the same thing; it is now corroborated three times.

**6.6 Don't move to a discriminated union of 11 action models in the LLM schema.** Prettier in
Python, `anyOf`/`oneOf` in JSON Schema, and that is where Gemini's schema restrictions and
Bedrock's lack of `oneOf` bite (Notte `engine.py:374-395`, browser-use `SchemaOptimizer` flattening
all `$ref`/`$defs`). Keep `AgentAction` flat with a `Literal` kind and optional fields.

---

## 7. One-line answers to the brief

| Question | Answer |
|---|---|
| Single action vs list per call? | Split ~50/50; nobody unbounded. **Recommend: bounded list, `max_length=4`, default-1 guidance, gated behind `max_actions_per_step`.** |
| Invalid/failed item in a list? | Universally: abort the remainder, keep the prefix, tell the model which items didn't run. Skyvern additionally retries the whole step from a fresh scrape. |
| Element addressing? | Index/ref wins measurably (SeeAct: 39.1 vs 20.3 vs 16.1). **Keep `index: int`.** |
| Addressing validation? | browser-use: soft (`ge=1` + "not available" message). Playwright MCP: hard (ref must match `/^(f\d+)?e\d+$/` and resolve). Skyvern: hash + soft. **Keep hard bounds check; improve the message; add a per-item staleness probe for batches.** |
| Full vocabulary? | Convergent core = click, fill, select, scroll, goto, back, wait, done. We have that + hover, press, upload, noop. |
| Which compounds exist? | `fill_form` (4 systems), type-and-submit (5 systems), `bulk_enter_text`, `enter_text_and_click`, `set_checked`. **All decompose to atomic actions in every implementation.** |
| Add compounds to our set? | **No.** The bounded list subsumes all of them without touching `schema/actions.py`. |
| Structured output mechanism? | We're already on native forced tool calling (LangChain defaults to `function_calling` for all three providers). One tool, not eleven. |
| Model-error handling? | Skyvern's coercion ladder for `decision.py`; Notte's retry/downgrade ladder for `llm.py`. Both sketched in §5.5. |
| `done` semantics? | Move out of the action enum to `done: bool` + `success: bool`, enforced alone by a `model_validator`. No payload. |
| `extract` / `ask_human`? | `extract` out of scope (traffic, not data; zero-LLM replay). `ask_human` exists only in Agent-E; not needed for autonomous compile-time exploration. |
| Measured effects? | Action-space reduction +9.4pts (AgentOccam); textual-choice grounding +18.8pts (SeeAct); multi-action **unmeasured anywhere** — measure it ourselves in `eval stress`. |

---

## 8. Provenance and verification notes

All repository claims were read from raw source at the pinned commit on 2026-08-26, not from
memory or documentation. Commits: browser-use `28670f720f`, Skyvern `d081a5324b`, Stagehand
`341433acac` (docs/extension) and tag `stagehand-server-v3/v3.7.5` = `a8d73fda75` (v3 agent tools),
playwright-mcp `16cf228d7b`, microsoft/playwright `main` (MCP tool implementations live there per
`playwright-mcp/src/README.md`), vercel-labs/agent-browser `fbd046c23a`, Notte `1802f0080b`,
Agent-E `f218c3cb4b`, LaVague `9024bb832c`, BrowserGym `9e779f087d`.

**Verified by direct execution in this repo's venv:** the `with_structured_output` signatures and
`method="function_calling"` defaults for `ChatAnthropic` / `ChatOpenAI` / `ChatGoogleGenerativeAI`
(§5.4), via `inspect.signature` at `langchain 1.3.15` / `langchain-core 1.5.5`.

**Papers**, quoted from the arXiv HTML rendering: AgentOccam (2410.13825v2, Tables 3/7/8/17,
§4.1, App. G.1), WebArena (2307.13854v4, §2.4/Fig. 4), SeeAct (2401.01614v2, §3.1, Table 3),
WebVoyager (2401.13919v4, §3.4, App. C), RAG-MCP (2505.03275), "How Many Tools Should an LLM Agent
See?" (2605.24660).

**Marked unverified / handle with care:**
- The rendering of AgentOccam's Table 8 loses strikethrough formatting, so it appears to list the
  removed actions as present. The prose at App. A and §4.1 is authoritative and is what is quoted
  here; the table alone would mislead.
- **Anthropic and OpenAI computer-use details come from vendor documentation**, fetched
  2026-08-26, not from source. The claim that `computer_toolset_20260801` expands to 17 named
  member tools "with no `action` field" is a direct doc quotation; the claim that OpenAI CUA
  batches `actions[]` per `computer_call` is likewise a doc quotation with no accompanying
  benchmark.
- **No measured benefit of multi-action exists in any source read here.** BrowserGym's
  "more than 2-3 actions usually leads to failure" is a maintainer's in-prompt assertion.
  browser-use's `max_actions_per_step=5` is a default, not a tuned result.
- browser-use's reported 89.1% on WebVoyager appeared only in secondary sources, alongside
  third-party reproduction failures. **Not cited as evidence anywhere above.**
- Blog-level figures on tool-count degradation ("accuracy drops past 10-15 tools", "740 tools →
  0-20%", the BiasBusters positional numbers) surfaced in search but were **not traced to primary
  sources and are not relied on.** Only RAG-MCP and 2605.24660 are cited, and both concern
  catalogues 30-300× larger than ours.
- `browser_use/agent/service.py:2751` computes `cached_selector_map` and never uses it at this
  SHA (verified by `grep -n cached_selector_map`). Mentioned so nobody copies a dead guard.
- The brief refers to an "evaluate-tool discussion" in `browser-agent-architectures.md`. There is
  none; §6.4 is the first written record of the reasoning.
