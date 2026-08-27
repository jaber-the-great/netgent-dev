# Date inputs: how browser agents read, format, and commit them

**Question.** Two forms in the browser-use 21-form sweep fail on every run for a date reason:
`src/angularjs.html` (a `type=text` input carrying `uib-datepicker-popup="MM/dd/yyyy"`) and
`src/jquery-bootstrap.html` (bootstrap-datepicker, `type=text`, no placeholder). Our prompt says
"dates as YYYY-MM-DD"; the explorer (Haiku 4.5) writes `1990-05-15` and never recovers. What do
other systems expose in the observation, what do they tell the model, and how do they *write* a
date — and what is the smallest change that fixes both forms without breaking the other 19?

**Status.** Written 2026-08-27. Every source-code claim cites a pinned commit and line range,
fetched the same day; every library claim cites that library's own source or docs. Every claim
about *our* two forms is a measurement from a probe run against the live pages on this machine
(§2, §5) — five probes, 16 end-to-end submits, listed in §9. Companion docs:
[`browser-agent-prompting.md`](browser-agent-prompting.md) (observation format, system-prompt
structure), [`browser-agent-tool-calling.md`](browser-agent-tool-calling.md) (action space),
[`browser-layer-design.md`](../browser-layer-design.md) (the dispatch ladders).

---

> **Status (2026-08-27): (a) + (c) implemented on `eugene/v2-scaffold`.** Walker emits `format=`
> / `picker=` from the closed signal list (incl. the `.input-group.date` ancestor) and folds
> `ng-invalid` / `is-invalid` / `aria-invalid` into `[invalid]`; `_fill` gained the gated
> per-key rung (Escape, explicit blur, verify after the commit); prompt rule (b) rewritten.
> Measured: sweep **19/21** (was 17/21 — the ceiling, Ember and Shadow DOM being broken fixtures),
> challenge 5/15 unchanged, 202 tests. Regression tests: `tests/integration/test_date_inputs.py`.

## Summary (10 lines)

1. **The two forms fail for two *different* reasons, and only one of them is a format problem.** `angularjs.html` is pure format: `05/15/1990` passes, `1990-05-15` fails under every dispatch strategy. `jquery-bootstrap.html` is pure *dispatch*: `locator.fill()` fails with **both** formats — the value is silently wiped on the next blur — while per-keystroke typing passes with both (measured, §2).
2. On `angularjs.html` our observation never shows `[invalid]` after the bad fill: native `validity.valid` stays **true** (the text is non-empty), and only AngularJS knows it is garbage (`ng-invalid-parse`). So the prompt's existing "if a date field stays `[invalid]`, retry MM/DD/YYYY" rule (`prompt.py:24-26`, `sweep.py:22-23`) **can never fire there**.
3. On `jquery-bootstrap.html` the mechanism is exact and citable: bootstrap-datepicker 1.9.0 binds only `keyup`/`keydown`/`paste` (`_buildEvents`, bootstrap-datepicker.js:341-348). Playwright's `fill` writes `.value` and dispatches `input`+`change` only, so `this.dates` stays empty; `hide()` then runs `forceParse` → `setValue()` → writes `getFormattedDate()` of an empty date list → **`""`** (`:484-495`, `:599-604`).
4. **browser-use has already solved exactly this, in two places**, in a burst of commits on 2025-10-29/30 driven by this same suite (PR #3471, which also switched CI to `InteractionTasks_v8`): a synthetic `format=` / `expected_format=` attribute in the serializer, keyed on `uib-datepicker-popup`, datepicker classes and `data-date-format` (`serializer.py:1144-1219`), and a `_requires_direct_value_assignment` → native-setter + focus/input/change/blur + `jQuery(...).datepicker('update')` write path (`default_action_watchdog.py:1617-1750`).
5. **Skyvern is the only system with a first-class date pathway**: an `is_date_related`/`date_format` context extracted per input action, an LLM `check-date-format` mini-agent (ISO-only, and only for native `type=date`), a 30-level date-picker click loop, and an error hint that tells the agent to click the calendar trigger.
6. Everyone else keeps dates inside `type`/`fill` plus one prompt sentence, or says nothing: Stagehand mirrors Playwright byte-for-byte and has zero datepicker awareness; Playwright MCP's `browser_fill_form` is a bare `locator.fill`; agent-browser, Notte, LaVague, OpenAI CUA and Anthropic computer-use docs say nothing about dates at all.
7. **No system reads a date format the way our walker would need to.** browser-use is the only one that synthesises a `format=` token, and even it misses `jquery-bootstrap.html`, because the only signal there sits on the **parent** `div.input-group.date`, not on the input (measured, §5).
8. Under Patchright our `page.evaluate` runs in an isolated world (measured: `typeof jQuery === 'undefined'` on a page whose datepicker is demonstrably live), so **plugin introspection is off the table** — attribute/class/ancestor reads are all we get. That constraint happens to match the deliverable's brief exactly.
9. **Recommendation:** (a) walker emits `format=` (and `picker=<lib>`) from a short, closed signal list including an ancestor check; (b) prompt retriggers on "value went empty / an error naming the field persists", not only on `[invalid]`; (c) `_fill` grows one gated rung — for a `type=text` input flagged `picker`, type per key, `Escape`, then blur, then verify. Never `Enter` (it commits *today's* date — measured `08/27/2026`).
10. Expected: (a) alone fixes `angularjs` only; (c) alone fixes `jquery-bootstrap` only (with a garbled-but-accepted date under ISO); **(a)+(c) fixes both with correct data → 21/21**. A `select_date` compound action is *not* warranted; it would smuggle a loop into a single transition.

---

## 1. What NetGent does today

| Layer | Code | Behaviour |
|---|---|---|
| Walker | [`dom/scripts/snapshot.js:162-196`](../../src/netgent/browser/dom/scripts/snapshot.js) | Per element: `tag`, `role`, `name`, `type`, `checked`, `disabled`, `required`, `invalid`, `options`, `value`, `bbox`, `candidates`. **No `placeholder`, `pattern`, `title`, `data-*`, `inputmode`, `maxlength` field.** |
| Name | `snapshot.js:55-74` | `accName` order: `aria-label` → `aria-labelledby` → `labels[0]` → **`placeholder`** → `data-placeholder` → `aria-placeholder` → `name` → `innerText` → `value`. A placeholder is therefore visible *only when the field has no label* — and then it is conflated with the field's identity. |
| Invalid | `snapshot.js:179` | `invalid: el.willValidate ? !el.validity.valid : false` — **native constraint validation only**. Framework validity (Angular `$error.parse`, jQuery `is-invalid`) is invisible. |
| Serializer | [`dom/serializer.py:75-92`](../../src/netgent/browser/dom/serializer.py) | `  [i] input[text] "Date of Birth" value="…" [required] [invalid: still needs a valid value]`. There is **no `format=` hint of any kind**, for native date inputs or otherwise. (The task brief assumed one exists; it does not — the ISO guidance lives only in the prompt.) |
| Prompt | [`explorer/prompt.py:24-26`](../../src/netgent/agent/explorer/prompt.py) | *"If a date you entered is rejected (an error like '… is required' persists after filling), the site expects a different format — retry with MM/DD/YYYY, then DD/MM/YYYY."* |
| Prompt | `prompt.py:51-52` | *"input[date] → fill with YYYY-MM-DD; input[time] → HH:MM; input[month] → YYYY-MM."* |
| Sweep task | [`evals/sweep.py:21-27`](../../src/netgent/evals/sweep.py) | *"dates as YYYY-MM-DD (if a date field stays [invalid], retry it as MM/DD/YYYY)"* |
| Error text | [`explorer/actions.py:73-76`](../../src/netgent/agent/explorer/actions.py) | The wrong-element error for `select` also says *"use 'fill' (dates as YYYY-MM-DD)"*. |
| Dispatch | [`browser/actions.py:90-160`](../../src/netgent/browser/actions.py) | `_fill` ladder: `fill()` → verify → `press_sequentially` → verify → native setter + `input`/`change`/`blur` → verify. `verify()` (`:108-123`) returns success when the read-back equals the text **or** is any non-empty *new* value. |
| Stuck | [`explorer/browser_agent.py:25`](../../src/netgent/agent/explorer/browser_agent.py), [`graph.py:73-78`](../../src/netgent/agent/explorer/graph.py) | `MAX_REPEAT = 3` identical observations → give up. |

Two consequences matter for what follows. First, `verify()` reads the value back **immediately**;
a picker that destroys the value on the *next* blur is invisible to it, so the ladder returns
"success" at rung 1 and never escalates. Second, the whole date story is carried by prose in the
prompt, keyed on a signal (`[invalid]`) that one of the two failing forms never produces.

---

## 2. The measured failure, mechanism by mechanism

All numbers below are from probes run on this machine on 2026-08-27 against the live pages
(§9 lists the scripts). Headless Patchright, `BrowserSession(headless=True)`, one fresh page
load per cell.

### 2.1 End-to-end: fill every other field deterministically, vary only the date

Success = the suite's own marker, `the secret is: dumbledore`, observed as visible text
(AngularJS) or an auto-accepted `alert` (jQuery/Bootstrap). 16 runs, zero LLM.

| form | write mode | text | field value at submit | passes |
|---|---|---|---|---|
| angularjs | `fill` | `1990-05-15` | `1990-05-15` | ✗ ("Date of Birth is required.") |
| angularjs | `fill` | `05/15/1990` | `05/15/1990` | **✓** |
| angularjs | `type` (per key) | `1990-05-15` | `1990-05-15` | ✗ |
| angularjs | `type` | `05/15/1990` | `05/15/1990` | **✓** |
| angularjs | `type`+`Tab` | `1990-05-15` | `1990-05-15` | ✗ |
| angularjs | `type`+`Tab` | `05/15/1990` | `05/15/1990` | **✓** |
| angularjs | `fill`→retype | `1990-05-15` | `1990-05-15` | ✗ |
| angularjs | `fill`→retype | `05/15/1990` | `05/15/1990` | **✓** |
| jquery-bootstrap | `fill` | `1990-05-15` | **`""`** | ✗ |
| jquery-bootstrap | `fill` | `05/15/1990` | **`""`** | ✗ |
| jquery-bootstrap | `type` | `1990-05-15` | `10/05/15` | **✓** (wrong date) |
| jquery-bootstrap | `type` | `05/15/1990` | `05/15/1990` | **✓** |
| jquery-bootstrap | `type`+`Tab` | `1990-05-15` | `10/05/15` | **✓** (wrong date) |
| jquery-bootstrap | `type`+`Tab` | `05/15/1990` | `05/15/1990` | **✓** |
| jquery-bootstrap | `fill`→retype | `1990-05-15` | `10/05/15` | **✓** (wrong date) |
| jquery-bootstrap | `fill`→retype | `05/15/1990` | `05/15/1990` | **✓** |

Read the two blocks separately:

- **`angularjs.html` is a format problem and nothing else.** The write mode is irrelevant; the
  string is everything. This corrects the brief's framing slightly: `05/15/1990` passes with a
  plain `fill`, so no dispatch change is needed here.
- **`jquery-bootstrap.html` is a dispatch problem and nothing else.** `fill` fails with *both*
  formats. Any keystroke path passes with both — but ISO produces the nonsense date `10/05/15`,
  which this form happens to accept because its submit handler only checks
  `!birthDate.val().trim()` (jquery-bootstrap.html:189). Correct data needs *both* fixes.

### 2.2 Value trajectory (why `fill` loses on jquery-bootstrap)

One fresh load per row; `v=` is `input.validity.valid`.

| form | strategy | after write | after commit key | after the next click elsewhere |
|---|---|---|---|---|
| angularjs | `fill` ISO | `'1990-05-15'` v=1 **ng-invalid-parse** | — | `'1990-05-15'` v=1 ng-invalid-parse |
| angularjs | `fill` US | `'05/15/1990'` v=1 | — | `'05/15/1990'` v=1 |
| jquery-bootstrap | `fill` ISO | `'1990-05-15'` v=1 | — | **`''` v=0** |
| jquery-bootstrap | `fill` US | `'05/15/1990'` v=1 | — | **`''` v=0** |
| jquery-bootstrap | `fill`+`Tab` US | `'05/15/1990'` v=1 | **`''` v=0** | `''` v=0 |
| jquery-bootstrap | `fill`+`Enter` US | `'05/15/1990'` v=1 | **`'08/27/2026'`** v=1 | `'08/27/2026'` v=1 |
| jquery-bootstrap | `type`+`Tab` ISO | `'1990-05-15'` v=1 | `'10/05/15'` v=1 | `'10/05/15'` v=1 |
| jquery-bootstrap | `type`+`Tab` US | `'05/15/1990'` v=1 | `'05/15/1990'` v=1 | `'05/15/1990'` v=1 |

Three things fall out of this table:

1. **The failure is delayed.** Right after the fill the field looks perfect — value present,
   `validity.valid = true`, no `[invalid]` marker. The wipe happens on the *next* action's
   mousedown. So the explorer sees: fill → looks fine → click a radio → date field is empty and
   `[invalid]` again → re-fill → … until `MAX_REPEAT = 3` ends the run. That is the observed loop.
2. **`Enter` is actively harmful.** With the picker open (focus opens it), `Enter` selects the
   highlighted cell, i.e. **today** — `08/27/2026`. Non-empty, `valid`, and wrong.
3. **`Tab` after a `fill` does not rescue anything** — the blur is exactly what triggers the wipe.
   Only a keystroke path populates the widget's internal state first.

### 2.3 Why, in the libraries' own source

**bootstrap-datepicker 1.9.0** (the version the form loads, cdnjs):

```js
// bootstrap-datepicker.js:341-348 — the ONLY input listeners
var events = {
    keyup:   $.proxy(function(e){ if ($.inArray(e.keyCode, [27,37,39,38,40,32,13,9]) === -1) this.update(); }, this),
    keydown: $.proxy(this.keydown, this),
    paste:   $.proxy(this.paste, this)
};
```
```js
// :484-495                                   // :599-604
hide: function(){                             setValue: function(){
  …                                             var formatted = this.getFormattedDate();
  if (this.o.forceParse && this.inputField.val())   this.inputField.val(formatted);
    this.setValue();                            return this;
  …                                           },
},
```

`forceParse` defaults to `true` and `format` to `"mm/dd/yyyy"`
([options docs](https://bootstrap-datepicker.readthedocs.io/en/latest/options.html); source
`:1691`). The docs state it plainly: *"when an invalid date is left in the input field by the
user, the picker will forcibly parse that value, and set the input's value to the new, valid
date, conforming to the given format."* There is **no `input` or `change` listener**. Playwright's
`fill` on a text input goes down the `needsinput` path and delivers the characters with CDP
`Input.insertText`, which — per Playwright's own docs — *"Dispatches only `input` event, does not
emit the `keydown`, `keyup` or `keypress` events"*
([`docs/src/api/class-keyboard.md:164-167`](https://github.com/microsoft/playwright/blob/32095ea/docs/src/api/class-keyboard.md)).
So `this.dates` is never populated, `getFormattedDate()` returns `""`, and the field is cleared.
Per-keystroke typing (`press_sequentially`, which sends *"a `keydown`, `keypress`/`input`, and
`keyup` event for each character"*, `class-locator.md`) fires `keyup` → `update()` → the value is
parsed and kept.

**angular-ui-bootstrap 2.5.0** (`uib-datepicker-popup`):

```js
// ui-bootstrap-tpls.js:2744         constant uibDatepickerPopupConfig
datepickerPopup: 'yyyy-MM-dd',
// :2793
dateFormat = $attrs.uibDatepickerPopup || datepickerPopupConfig.datepickerPopup;
// :2802, :2810  — throws if a format is neither given nor configured
throw new Error('uibDatepickerPopup must have a date format specified.');
// :3047-3068  parseDate → parseDateString(viewValue) → undefined when unparseable
return ngModelOptions.getOption('allowInvalid') ? viewValue : undefined;
```

An unparseable view value makes the `$parsers` chain yield `undefined`, so `ngModel` records a
**parse** error — which is why the class list we measured after the ISO fill contains
`ng-invalid ng-invalid-parse` while `input.validity.valid` is still `true`. The DOM value stays
put; only Angular knows it is dead. `form.$valid` is false, `submitForm` returns early
(angularjs.html:212-215), and the only page-visible evidence is the help block
*"Date of Birth is required."* (angularjs.html:111-112) — which is misleading, because the field
is not empty.

---

## 3. The cross-system table

| system (pinned) | observation exposes placeholder / pattern / format? | prompt rule for dates? | dispatch for `input[type=date]` | dispatch for text + picker | calendar-click fallback? |
|---|---|---|---|---|---|
| **browser-use** `28670f7` | **Yes, richest by far.** `DEFAULT_INCLUDE_ATTRIBUTES` carries `placeholder`, `aria-placeholder`, `pattern`, `min`/`max`/`step`, `maxlength`, `inputmode`, `autocomplete`, `list`, `data-mask`, `data-inputmask`, `data-date-format`, `data-datepicker`, plus two **synthetic** keys `format` and `expected_format` (`dom/views.py:18-60`). Synthesised in `serializer.py:1144-1219`: ISO `format=` for the 5 native types, `expected_format=`+`format=` from `uib-datepicker-popup`, `format=`/`placeholder=` from `data-date-format` or a `datepicker`/`datetimepicker`/`daterangepicker` class (defaulting to `mm/dd/yyyy`). Compound date sub-components are deliberately suppressed (`serializer.py:192-199`). | **None in the main prompt** — grep of `system_prompts/system_prompt.md` finds no date/format rule; the whole burden is on the serializer. The Anthropic-flash variant adds one line: *"When dealing with date pickers, calendars, or other complex widgets, interact with them step by step and verify each selection"* (`system_prompt_anthropic_flash.md:56`). | **Direct value assignment.** `_requires_direct_value_assignment` returns true for `date/time/datetime-local/month/week/color/range` (`default_action_watchdog.py:1645-1651`), then `_set_value_directly` uses the `HTMLInputElement.prototype` native setter and dispatches `focus`→`input`→`change`→`blur` (`:1669-1750`). Typing is skipped entirely (`:1837-1846`). | **Same direct-assignment path**, gated on the input's own `class` matching `datepicker`/`daterangepicker`/`datetimepicker`/`bootstrap-datepicker`, or on the presence of `data-datepicker` / `data-date-format` / **`data-provide`** (`:1652-1666`). Uniquely, the JS ends with `jQuery(this).trigger('change')` and, if `jQuery(this).data('datepicker')`, `jQuery(this).datepicker('update')` (`:1720-1726`) — the plugin-aware commit. | No dedicated one. Readback after every write; on mismatch the tool result appends *"⚠️ Note: the field's actual value '…' differs from typed text '…'. The page may have reformatted or autocompleted your input."* (`tools/service.py:835`), leaving recovery to the model. |
| **Skyvern** `d081a53` | **Yes.** `RESERVED_ATTRIBUTES` includes `pattern`, `placeholder`, `title`, `maxlength`, `name`, `type`, `value`, `required`, `aria-label`/`aria-required`/… (`webeye/scraper/scraper.py:111-139`); the enriched tree adds `aria-describedby`, `aria-invalid`, `aria-errormessage`, `errorText`, `validationMessage` (`:143-153`). No synthetic `format=`. | **Yes, as structured extraction rather than prose.** Every INPUT/SELECT action carries a `context` with `"is_date_related": bool` and `"date_format": str // …For example YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, DD.MM.YYYY, MM/DD/YYYY…"` (`prompts/skyvern/single-input-action.j2:26-27`, `parse-input-or-select-context.j2:13-14`). The dropdown prompt adds *"Date picker might be triggered, you goal is to set the correct start date and end date"* when `is_date_related` (`custom-select.j2:11-12`). | **A dedicated LLM mini-agent.** For `tag == input and type == "date"`, `check_date_format()` runs a secondary-model prompt whose goal is *"to check whether the format of the date matches the required format 'YYYY-MM-DD'"* and which returns `recommended_date` (`handler.py:7112-7131`, `:3324-3360`; `prompts/skyvern/check-date-format.j2:1,9-10`). The corrected value then goes through `input_fill`. Note it is **hard-coded to ISO** — the extracted `date_format` is not passed in. | Falls through to the generic input path: `input_clear` → `input_sequentially` (per-keystroke), with auto-completion / custom-dropdown handling on top. If the live node refuses text, the failure message is a hint: *"The element appears to be a non-input segment of a custom date widget. Look for a calendar icon, date picker trigger, or stepper button near this element and click that instead of typing into the segment"* (`exceptions.py:1201-1213`). | **Yes — the only system with one.** `sequentially_select_from_dropdown` raises its depth cap from `MAX_SELECT_DEPTH = 3` to `MAX_DATEPICKER_DEPTH = 30` when `is_date_related`, so the agent can click through month/year navigation (`handler.py:10354-10357`). If the target is an `<input>` it first tries *"Try to input the date directly"* via `input_sequentially` before falling back to clicking (`:10480-10495`). |
| **Stagehand** `341433a` | **No.** The a11y line is `[id] role: name` plus only `[selected]`/`[checked]` (`extension/understudy/a11y/snapshot/treeFormatUtils.ts:8-22`). No placeholder, no value, no required/invalid. | **None.** A repo-wide code search for `datepicker` returns zero hits; `act` reasoning is server-side and closed. | Mirrors Playwright exactly: `fillElementValue` has `inputTypesToSetValue = {color, date, datetime-local, month, range, time, week}` and applies the native setter (`extension/dom/locatorScripts/scripts.ts:217-236`). | `needsinput` → CDP `Input.insertText` (`understudy/locator.ts:426-533`). Its `type()` also uses `Input.insertText` unless a `delay` is passed, in which case it synthesises per-char `keyDown`/`keyUp` (`:543-560`). **Would hit the identical bootstrap-datepicker wipe.** | None. |
| **Playwright MCP** (in `microsoft/playwright` `32095ea`) | Snapshot is the aria snapshot; the `browser_fill_form` tool takes a field `type` of `textbox / checkbox / radio / combobox / slider` only (`packages/playwright-core/src/tools/backend/form.ts:32-34`). | None. | `await locator.fill(secret.value, …)` — i.e. Playwright's own native-setter path (`form.ts:42-45`). | The same bare `locator.fill`. No datepicker awareness anywhere. | None. |
| **Vercel agent-browser** `vercel-labs/agent-browser@fbd046c` | **Placeholder, yes**; format hints, no. The documented snapshot line is `@e1 [tag type="value"] "text content" placeholder="hint"` (`skill-data/core/references/snapshot-refs.md:141-158`; example at `SKILL.md:97-98`). | **None** — no mention of dates, formats, calendars or pickers in the 519-line `SKILL.md`. | Not distinguished. | Not distinguished, but the SKILL does encode the general escape hatch: *"**Fill / type doesn't work** Some custom input components intercept key events. Try: `agent-browser focus @e1` / `agent-browser keyboard inserttext "text"` … or `agent-browser keyboard type "text"` # raw keystrokes"* (`SKILL.md:411-417`). That is exactly the right ladder, stated generically rather than for dates. | None. |
| **Agent-E** `f218c3c` | Placeholder yes: the a11y-tree attribute list is `['name','aria-label','placeholder','mmid','id','for','data-testid']` (`ae/utils/get_detailed_accessibility_tree.py:72`). No pattern/format. | **Yes, and it is the closest prior art to what we need in prose:** *"When inputing information, remember to follow the format of the input field. For example, if the input field is a date field, you will enter the date in the correct format (e.g. YYYY-MM-DD), you may get clues from the placeholder text in the input field."* (`ae/core/prompts.py:73`). Today's date is injected into the system message (`agents/browser_nav_agent.py:51`). | Not distinguished. | Not distinguished. | None. |
| **Notte** `1802f00` | — | **None**; no date-format rule anywhere in the prompts. | `locator.fill(...)` (`notte-browser/controller.py:355`). | `locator.press_sequentially(value, delay=100)` is a first-class alternative rung (`controller.py:365`); the vault/autofill path always types with a randomised 50-150 ms delay (`form_filling.py:625`). **Would pass jquery-bootstrap by construction, and fail angularjs on format.** | None. |
| **LaVague** `9024bb8` (dead) | — | None. | — | — | None. |
| **Magentic-UI / FARA WebSurfer** `d3c9d13` | — | **Yes, and it is the opposite policy:** *"For calendar widgets, you usually need to left_click() on arrows to move between months and left_click() on dates to select them; type() is not typically used to input dates there."* (`agents/web_surfer/fara/_prompts.py:36`). | — | Always keyboard-typed, with a deliberate 100 ms per-keystroke delay for short strings: *"These masks have per-keystroke event handlers that need time to reformat the value and reposition the cursor"* — naming phone, credit card and **date** (`tools/playwright/playwright_controller_fara.py:586-596`). | **Yes, by prompt** (click through the calendar), not by code. |
| **OpenAI CUA** / **Anthropic computer-use** | Screenshot only. | **None** — both tool docs, fetched 2026-08-27, contain no guidance on date fields, date formats, or calendar widgets. | n/a (pixel typing) | n/a | n/a — implicitly always the calendar, since typing is the only primitive. |

### 3.1 The two shapes of the answer

Everything above collapses into two families.

**Format-first (browser-use, Skyvern, Agent-E).** Put the required format in front of the model —
in the observation (browser-use's synthetic `format=`), in the action schema (Skyvern's
`date_format` field), or in the prompt (Agent-E's "clues from the placeholder"). Cheap, no
dispatch change, and it is exactly the fix `angularjs.html` needs.

**Keystroke-first (Notte, Magentic-UI, Skyvern's `input_sequentially`, agent-browser's
troubleshooting ladder).** Assume the widget is keystroke-driven and type. Slower, but it is the
only thing that makes `jquery-bootstrap.html` work, and Magentic-UI states the reason in a
comment that could have been written about our exact failure.

browser-use is the only project doing **both**, and it added them in the same 48 hours
(`a720373` "Add date/time input format hints in DOMTreeSerializer", `f99efed` "More datapickers",
`acac902` "data-date-forma", `4f9ba96` "Expected date format + scroll container", `6a0b39c`
"Fix date serilizer", `5a4ebf7` "Date fix" on the serializer; `f1e3fbc` "More forms for
datepicker", `0badc5d` "Date setting update" on the watchdog — all 2025-10-29/30, under PR
[#3471](https://github.com/browser-use/browser-use/pull/3471), whose own summary says it
"strengthens … form input (date/time, contenteditable)" and "switches CI eval to v8" — v8 being
`InteractionTasks_v8.json` in the stress-tests repo). This is the same suite we are measuring on:
its date-bearing tasks are #4 "Date Time Input", #15 "jQuery Bootstrap Form", #16 "AngularJS Form"
and the rest of the form set.

**Note on browser-use's coverage of *our* two forms.** Their `uib-datepicker-popup` branch is
tailor-made for `angularjs.html` and would emit `format=MM/dd/yyyy`. Their bootstrap branch would
**miss** `jquery-bootstrap.html`: the class check reads the input's own `class`, which is
`"form-control"`, and the `data-provide` check (which *is* the bootstrap-datepicker declarative
hook) appears only in the dispatch predicate (`default_action_watchdog.py:1664`), not in the
serializer's hint synthesis (`serializer.py:1186-1219`). The dispatch side would still route it to
the native-setter + `jQuery(...).datepicker('update')` path only if one of those attributes or
classes is present — and none is (§5). So browser-use's own machinery, applied verbatim, fixes one
of our two forms, not both.

### 3.2 Published pass rates

None. The stress-tests repo publishes only the intended *outcome* — *"All forms will display
`the secret is: dumbledore` upon succesful submission to make evals easy to validate"* (README) —
and per-task ground truth is the string `"successfully"` (`InteractionTasks_v8.json`). There is no
per-form pass-rate table in the repo, in `browser-use/browser-use`, or in any issue I could find
(`gh search issues --repo browser-use/browser-use "datepicker"` returns nothing relevant).

---

## 4. Playwright's own contract

| API | Behaviour | Source |
|---|---|---|
| `locator.fill()` on `input[type=date/time/datetime-local/month/week/color/range]` | `value = value.trim(); input.focus(); input.value = value; if (input.value !== value) throw 'Malformed value';` then dispatches `input` + `change` and returns `done`. **ISO required**, enforced by the browser rejecting the assignment. | `packages/injected/src/injectedScript.ts:872-891` @ `32095ea` |
| `locator.fill()` on `input[type=text/email/password/search/tel/url/number]`, `textarea`, `[contenteditable]` | Returns `needsinput`; the driver then selects the text and inserts it — **no key events**. | `injectedScript.ts:892-898` |
| `keyboard.insertText` | *"Dispatches only `input` event, does not emit the `keydown`, `keyup` or `keypress` events."* | `docs/src/api/class-keyboard.md:164-167` |
| `locator.pressSequentially` | *"Focuses the element, and then sends a `keydown`, `keypress`/`input`, and `keyup` event for each character."* Tipped as *"You only need to press keys one by one if there is special keyboard handling on the page."* | `docs/src/api/class-locator.md` |
| `locator.fill()` public docs | Say nothing about date formats. The ISO requirement appears only as examples in the input guide: `page.get_by_label("Birth date").fill("2020-02-02")`, `…("Appointment time").fill("13:15")`, `…("Local time").fill("2020-03-02T05:15")`. | `docs/src/api/class-locator.md:1302-1332`; `docs/src/input.md:12-25` |

**Measured surprise: our `_fill` ladder is already more forgiving than raw Playwright on native
date inputs.** On `vanilla.html`'s `input[type=date]`:

| mode | text | resulting `.value` |
|---|---|---|
| `_fill` | `1990-05-15` | `1990-05-15` ✓ |
| `_fill` | `05/15/1990` | **`1990-05-15`** ✓ — rung 1 throws *Malformed value*, rung 2 (`press_sequentially`) types into Chromium's `en-US` segmented control, which reads `05`→month, `15`→day, `1990`→year |
| raw `press_sequentially` | `1990-05-15` | **`0515-12-09`** — `1990` overflows the month segment; garbage, and `validity.valid` is still `true` |
| raw `press_sequentially` | `05/15/1990` | `1990-05-15` ✓ |

So NetGent already tolerates US-order text in a native date input, and the real hazard on native
inputs is **ISO typed per key**. Any new typing rung must therefore be gated to `type=text`.

### 4.1 How each picker library parses typed text

| library | default format | when it parses | class/attr it leaves in the DOM | source |
|---|---|---|---|---|
| **bootstrap-datepicker** 1.9.0 | `mm/dd/yyyy` | `keyup` → `update()`; and on `hide()` if `forceParse` (default `true`) → `setValue()` rewrites the field | Nothing on the input in component mode; the *wrapper* is `.input-group.date` (`:105` looks for `.date` on the element). Declarative hook is `data-provide="datepicker"`. | `bootstrap-datepicker.js:341-348, 484-495, 599-604, 1691`; [options docs](https://bootstrap-datepicker.readthedocs.io/en/latest/options.html) |
| **jQuery UI datepicker** 1.13.2 | `dateFormat: "mm/dd/yy"` | `_doKeyUp` parses on every keyup; `_setDateFromField` on blur/close | **`hasDatepicker`** on the input (`markerClassName`) | `jquery-ui.js:7384, 7452, 8040-8055, 8816` |
| **angular-ui-bootstrap** `uib-datepicker-popup` 2.5.0 | `yyyy-MM-dd` (config), overridden by the attribute value | `$parsers` on every `input`; unparseable ⇒ model `undefined` ⇒ `ng-invalid-parse` | **the attribute itself carries the format**: `uib-datepicker-popup="MM/dd/yyyy"` | `ui-bootstrap-tpls.js:2744, 2793, 2802, 2810, 3047-3068` |
| **flatpickr** | `dateFormat: "Y-m-d"` | Typing is disabled unless `allowInput`; the input is set **`readonly`** otherwise | `.flatpickr-input` on the input; `readonly` attribute | `src/types/options.ts:359`; `src/index.ts:2628, 2652-2653` |
| **react-datepicker** | `dateFormat: "MM/dd/yyyy"` | `onChange` per keystroke through the React controlled input | wrapper `.react-datepicker-wrapper` / `.react-datepicker__input-container` | `src/index.tsx:323`; `docs/datepicker.md:21` |
| **MUI X DatePicker** | locale-derived; `en-US` → `MM/DD/YYYY` | **Sectioned field**: each section is a `spinbutton`; there is no single free-text value to type. Docs warn *"`04/11/2022` parses as April 11 in `en-US` but November 4 in `en-GB`"* and tell testers to *"click the field first, then fill each `spinbutton`"* | `MuiInputBase-input` etc.; a hidden input holds the formatted value with placeholders (`04/DD/YYYY`) | [MUI X base concepts](https://mui.com/x/react-date-pickers/base-concepts/) |
| **Ant Design DatePicker** | `format` default `YYYY-MM-DD` | dayjs parse on change | `.ant-picker-input` | [antd DatePicker API](https://ant.design/components/date-picker) |

The pattern: **US-order (`mm/dd/yyyy`) is the default for the two jQuery-era libraries and
react-datepicker; ISO is the default for uib's *config* (but overridden per-field by the
attribute), flatpickr and Ant Design; MUI is locale-derived.** "Always ISO" is wrong roughly half
the time, and "always US" is wrong the other half. The only reliable move is to read the
per-field signal when one exists, and fall back to the page locale when it doesn't.

---

## 5. The catalogue of format signals readable without executing page JS

This is the constraint that matters for us. Under Patchright, `page.evaluate` runs in an
**isolated world** — measured: on both forms, `typeof jQuery === 'undefined'` and
`window.angular === undefined`, even though bootstrap-datepicker demonstrably ran (it wiped the
field) and AngularJS demonstrably ran (it applied `ng-invalid-parse`). So
`jQuery(el).data('datepicker').o.format` — browser-use's trick at
`default_action_watchdog.py:1720-1726`, which runs via `Runtime.callFunctionOn` in the page world
— is **not available to our walker**. Attributes, classes, ancestors and text are all we get.

| # | signal | what it yields | measured: `angularjs #birthDate` | measured: `jquery-bootstrap #birth-date` |
|---|---|---|---|---|
| 1 | `type` ∈ {date,time,datetime-local,month,week} | exact ISO format, no ambiguity | ✗ (`type=text`) | ✗ (`type=text`) |
| 2 | `placeholder` | often literally `MM/DD/YYYY` | **absent** | **absent** |
| 3 | `pattern` | a regex the format must satisfy | **absent** | **absent** |
| 4 | `title` | tooltip, sometimes the format | **absent** | **absent** |
| 5 | `aria-describedby` → resolved text | help text, sometimes the format | **absent** (resolves to `""`) | **absent** |
| 6 | `data-date-format` / `data-format` | the format, verbatim | **absent** | **absent** |
| 7 | `data-provide="datepicker"` | bootstrap-datepicker declarative init ⇒ default `mm/dd/yyyy` | **absent** | **absent** (initialised imperatively at `$(document).ready`) |
| 8 | `uib-datepicker-popup="…"` | **the format, verbatim** | **PRESENT — `"MM/dd/yyyy"`** | ✗ |
| 9 | picker class **on the input** (`datepicker`, `datetimepicker`, `daterangepicker`, `hasDatepicker`, `flatpickr-input`, `ant-picker-input`) | which library ⇒ its documented default | **absent** (`form-control ng-pristine ng-untouched ng-isolate-scope ng-empty ng-valid-date ng-invalid ng-invalid-required`) | **absent** (`form-control`) |
| 10 | picker class **on an ancestor** (`.input-group.date`, `.react-datepicker__input-container`, `.ant-picker`) | which library ⇒ its documented default | ✗ (parent is plain `div.input-group`) | **PRESENT — parent is `div.input-group date`** |
| 11 | `inputmode` | numeric keypad hint, weak | absent | absent |
| 12 | `maxlength` | `10` ⇒ a 10-char format, weak | absent | absent |
| 13 | associated `<label>` text | the field's *identity*, never the format | `"Date of Birth *"` | `"Date of Birth *"` |
| 14 | sibling/adjacent calendar button | "there is a picker here" | present (`button > i.glyphicon-calendar`) | present (`span.input-group-text > i.fa-calendar`) |
| 15 | `<html lang>` / `navigator.language` | the **locale default order** | `en` / `en-US` ⇒ `MM/DD/YYYY` | `en` / `en-US` ⇒ `MM/DD/YYYY` |
| 16 | `readonly` | typing is refused ⇒ must click the calendar (flatpickr default) | absent | absent |
| 17 | native `validity` after a write | our `[invalid]` marker | `valid=true` — **no signal** | `valid=true`, then `false` **after blur** (value wiped) |
| 18 | framework classes after a write (`ng-invalid-parse`, `is-invalid`, `aria-invalid`) | "the framework rejected it" | **`ng-invalid-parse` — the only machine-readable signal on this form** | `is-invalid` (only after a submit attempt) |

**The headline result of this table:** across the eighteen signals, exactly **one** fires per form,
and it is a *different* one each time — attribute #8 on AngularJS, ancestor class #10 on
jQuery/Bootstrap. Neither form carries a placeholder, a pattern, a title, a `data-*` format, or a
picker class on the input itself. Any detector that only reads the element's own attributes (which
is what browser-use's serializer does) covers one form and misses the other.

Signal #18 is worth calling out separately: `ng-invalid-parse` is a *post-hoc* signal — it appears
only after a bad write — but it is precisely the thing our observation is missing on
`angularjs.html`, and it is a plain class read. Surfacing "the framework marked this field invalid"
alongside our native `[invalid]` would let the existing prompt rule fire on that form.

### 5.1 The rest of the sweep

A scan of all 21 forms on `forms-comparison.html` found **21 date-ish inputs**:

| shape | count | forms |
|---|---|---|
| native `input[type=date]` | 15 | vanilla, angular, react-hook-form, formik, svelte, ember, vue, material-ui, shadow-dom, progressive, hidden-labels, non-latin, rich-text, animated (`placeholder=" "`), iframe-inception-level3 |
| `type=text` + picker, **no** own-element signal | 1 | jquery-bootstrap (ancestor `.input-group.date` only) |
| `type=text` + format-bearing attribute | 1 | angularjs (`uib-datepicker-popup="MM/dd/yyyy"`) |
| `type=text` + `placeholder="MM/DD/YYYY"` | 1 | react-native-web (`class="rn-textinput"`, no `<label for>` — so our `accName` already surfaces the placeholder, *as the element's name*) |
| contenteditable + `data-placeholder` | 1 | contenteditable-form (`#birthDateField`, also `data-field`, `data-required`) |
| split `<select>` day/month/year + hidden input | 1 (3 selects) | i18n-form (`#birthDay`/`#birthMonth`/`#birthYear`, hidden `#birthDate`) |
| hidden mirror input | 1 | contenteditable-form `#birthDate` |

So 15 of the 21 are native and already pass; the format/dispatch problem is confined to the two
failing forms plus, latently, the react-native-web and contenteditable ones (which pass today).

---

## 6. Academic evidence

Short version: **the literature does not isolate date pickers as a failure category, and nobody
publishes a number for them.** What exists is adjacent.

- **Online-Mind2Web / "An Illusion of Progress? Assessing the Current State of Web Agents"**
  (arXiv:2504.01382, COLM 2025) §5.2 "Error Analysis and More Discussion", Figure 7 gives
  Operator's error distribution as **Filter & Sorting Errors 57.7 %**, **Navigation Errors 19.6 %**,
  plus Incomplete Steps / Misunderstanding / Others. Temporal constraints are named explicitly —
  the agent *"frequently fails to satisfy numerical and temporal constraints specified in the task
  instructions, either by overlooking or applying incorrect value ranges"* — but they are folded
  into the 57.7 % Filter & Sorting bucket, with no separate date-widget figure. Appendix F.1.4
  Fig. F.4 is a year-range example (`2001 to 2012` instead of `2004 to 2012`).
- **Invariant Labs, "What we've learned from analyzing hundreds of AI web agent traces"** gives a
  four-way taxonomy — Looping, Hallucinations, Environment Errors, Instruction Ignoring — with
  **no date category at all**; date-shaped failures land in "Ignoring Parts of Instructions". Their
  headline fixes are environment-level: OpenStreetMap 30 % → 46 %, ShoppingAdmin 24 % → 31 %.
- **WorkArena / BrowserGym.** There is no task family named `*date*`. Date-bearing tasks exist —
  the change-request scheduling family, e.g. *"Edit the schedule of the change requests by setting
  the start and end dates so that the change requests do not overlap"*
  (`src/browsergym/workarena/tasks/form.py:1517, 1565-1571`) — but the benchmark's own oracle
  fills every text field with a plain `input_field.fill(value)` and special-cases **only**
  autocomplete (`tasks/utils/form.py:5-30`). ServiceNow's `glide_date_time` fields are
  `type=text` with an on-blur validator, i.e. structurally the same trap as our
  jquery-bootstrap form — and WorkArena neither models it nor measures it.
- **AgentOccam** (arXiv:2410.13825) reports gains from *shrinking* the action/observation space;
  its error discussion attributes residual failures to simulator artefacts (Reddit rate limits,
  login expiry), not to widget mechanics.
- **WebVoyager** (arXiv:2401.13919) error analysis is dominated by visual grounding and
  hallucinated completion; no date category.

The one number I could find attributed to calendar widgets — a claim that models "click correct day
numbers in wrong months or target whitespace adjacent to date cells" in **UI-CUBE**
(arXiv:2511.17131) — **I could not verify**: the abstract contains no mention of calendars and the
PDF body did not extract. It is listed in §8 as unverified.

**The takeaway for us is the absence itself.** The benchmarks that dominate the literature are
built on either native inputs (Mind2Web/WebArena) or a single enterprise widget family
(WorkArena/ServiceNow). The browser-use stress suite is unusual precisely because it puts seven
different form stacks side by side, which is why it surfaces a class of bug the papers never
quantify. Our two failing forms are a finding, not a gap in our reading.

---

## 7. Recommendation for NetGent

Four changes, in dependency order. (a) and (c) are the ones that move the number; (b) is cheap
insurance; (d) is a decision *not* to add something.

### (a) Walker + serializer: a `format=` hint, and a `picker=` tag

Add two optional fields to `DomElement` (`dom/models.py`) — `format: str | None`,
`picker: str | None` — populated by the walker from the closed signal list in §5, and rendered by
the serializer as at most one extra token per element.

```js
// dom/scripts/snapshot.js — near INPUT_ROLE
const ISO_FORMAT = {date:'YYYY-MM-DD', time:'HH:MM', 'datetime-local':'YYYY-MM-DDTHH:MM',
                    month:'YYYY-MM', week:'YYYY-Www'};
// Library → its DOCUMENTED default input format (see docs/research/browser-agent-date-inputs.md §4.1).
// Only libraries whose default we can cite: guessing a format is worse than emitting none.
const PICKERS = [
  ['flatpickr',            (el) => el.classList.contains('flatpickr-input'),                 'YYYY-MM-DD'],
  ['jquery-ui-datepicker', (el) => el.classList.contains('hasDatepicker'),                   'MM/DD/YYYY'],
  ['react-datepicker',     (el) => !!el.closest('.react-datepicker__input-container'),       'MM/DD/YYYY'],
  ['ant-picker',           (el) => !!el.closest('.ant-picker'),                              'YYYY-MM-DD'],
  // bootstrap-datepicker: component mode leaves NOTHING on the input — the wrapper is
  // `.input-group.date` (bootstrap-datepicker.js:105) and the declarative hook is
  // data-provide="datepicker". Measured: this ancestor check is the ONLY signal on
  // stress-tests/src/jquery-bootstrap.html.
  ['bootstrap-datepicker', (el) => el.getAttribute('data-provide') === 'datepicker'
                                 || /(^|\s)(datepicker|datetimepicker|daterangepicker)(\s|$)/i.test(el.className)
                                 || !!el.closest('.input-group.date'),                       'MM/DD/YYYY'],
];
const dateHint = (el) => {
  if (el.tagName !== 'INPUT') return {format: null, picker: null};
  const t = (el.getAttribute('type') || 'text').toLowerCase();
  if (ISO_FORMAT[t]) return {format: ISO_FORMAT[t], picker: null};   // native: ISO, always
  if (t !== 'text' && t !== '') return {format: null, picker: null};
  // 1. an attribute that CARRIES the format wins outright.
  //    uib-datepicker-popup="MM/dd/yyyy" (angular-ui-bootstrap ui-bootstrap-tpls.js:2793) —
  //    measured: the only signal on stress-tests/src/angularjs.html.
  const explicit = el.getAttribute('uib-datepicker-popup')
                || el.getAttribute('data-date-format') || el.getAttribute('data-format');
  if (explicit) return {format: explicit.toUpperCase(), picker: 'attr'};
  // 2. a placeholder/pattern/title that LOOKS like a format.
  for (const a of ['placeholder', 'title', 'aria-placeholder', 'data-placeholder']) {
    const v = (el.getAttribute(a) || '').trim();
    if (/^[dmy][dmy\W]{5,}$/i.test(v)) return {format: v.toUpperCase(), picker: null};
  }
  // 3. a known library → its documented default, disambiguated by page locale where the
  //    library itself is locale-agnostic (US order for en-US; day-first otherwise).
  for (const [name, test, fmt] of PICKERS) {
    if (!test(el)) continue;
    const lang = (document.documentElement.lang || navigator.language || 'en-US').toLowerCase();
    const localeFmt = fmt === 'MM/DD/YYYY' && !lang.startsWith('en-us') && lang !== 'en'
      ? 'DD/MM/YYYY' : fmt;
    return {format: localeFmt, picker: name};
  }
  return {format: null, picker: null};
};
```

Serializer (`dom/serializer.py`, in the element loop next to `[required]`/`[invalid]`):

```python
if el.format:
    state += f" [format={el.format}" + (f" via {el.picker}]" if el.picker else "]")
```

Rendering on the two forms becomes:

```
  [2] input[text] "Date of Birth" [required] [invalid: still needs a valid value] [format=MM/DD/YYYY]
  [4] input[text] "Date of Birth" [required] [invalid: still needs a valid value] [format=MM/DD/YYYY via bootstrap-datepicker]
```

Design notes, and why this is deliberately narrower than browser-use's version:

- **Never guess from the label.** browser-use defaults *any* datepicker-classed text input to
  `mm/dd/yyyy` (`serializer.py:1206-1219`). We only emit a format when a signal in §5 fires; a
  field called "Date of Birth" with no signal gets nothing. Our prior A/B measurement
  (`browser-agent-prompting.md`) found decorative markers actively harmful, and a wrong `format=`
  is worse than none.
- **One token, appended to the existing state run.** No new line, no new section.
- **Also emit ISO for native types.** `input[date]` already carries its format in `[date]`, but
  making it explicit costs 18 characters and lets us delete two prompt sentences.
- **Optional, cheap, high value:** also surface the framework-invalid signal from §5 #18 —
  `el.classList.contains('ng-invalid') || el.getAttribute('aria-invalid') === 'true' ||
  el.classList.contains('is-invalid')` folded into the existing `invalid` field. On
  `angularjs.html` this is the *only* machine-readable evidence that the ISO date was rejected,
  and it makes the existing prompt rule fire.

### (b) Prompt: retrigger on "the value disappeared", not only on `[invalid]`

Replace `prompt.py:24-26` and align `sweep.py:22-23`:

```
Dates. A native input[date]/[time]/[month] takes the ISO form (YYYY-MM-DD, HH:MM, YYYY-MM).
A field shown with [format=…] wants EXACTLY that format — use it verbatim.
A date is rejected when ANY of these happens after you fill it: the field goes back to
[invalid]; its value= is empty or changed to something you did not type; or an error naming
that field ("... is required") is still on screen. When that happens the page parsed your
text and threw it away — do NOT retype the same string. Retry once in the page's own order
(MM/DD/YYYY on an English page, DD/MM/YYYY otherwise), then once in ISO. If both are refused,
click the calendar button next to the field and pick the date in the popup that opens.
```

The three trigger clauses map one-to-one onto the three mechanisms measured in §2:
`[invalid]` (jquery-bootstrap after blur), `value=` emptied or rewritten (jquery-bootstrap, and
any `forceParse` library), and a persistent error text (angularjs, where nothing else changes).
The current single `[invalid]` trigger covers only the first.

### (c) Dispatch: one gated rung in `_fill`

The measured fact this must encode: for a text input backed by a keystroke-driven picker,
`fill()` is not merely weaker than typing — it is *destructive*, and the destruction happens after
our read-back, so the existing ladder cannot detect it.

```python
# browser/actions.py — near _READBACK_JS
_PICKER_PROBE_JS = """el => {
  if (el.tagName !== 'INPUT') return false;
  const t = (el.getAttribute('type') || 'text').toLowerCase();
  if (t !== 'text' && t !== '') return false;           // NEVER native date/time: typing ISO
  return !!(el.getAttribute('uib-datepicker-popup')     // into input[type=date] yields garbage
         || el.getAttribute('data-date-format') || el.getAttribute('data-format')
         || el.getAttribute('data-provide') === 'datepicker'
         || /(^|\\s)(datepicker|datetimepicker|daterangepicker|hasDatepicker|flatpickr-input)(\\s|$)/i
              .test(el.className)
         || el.closest('.input-group.date, .react-datepicker__input-container, .ant-picker'));
}"""

async def _fill(self, locator, text, timeout_ms):
    first = locator.first
    ...
    # NEW rung 0, ahead of fill(): a picker-backed TEXT input.
    #
    # bootstrap-datepicker 1.9.0 binds only keyup/keydown/paste (_buildEvents :341-348), so
    # Playwright's fill — which delivers characters with Input.insertText and dispatches no key
    # events (docs/src/api/class-keyboard.md:164) — never populates the widget's date list. Its
    # hide() then runs forceParse -> setValue() -> writes getFormattedDate() of an EMPTY list,
    # i.e. "" (:484-495, :599-604). Measured on stress-tests/src/jquery-bootstrap.html: fill
    # leaves the right value, and the NEXT action's mousedown blanks the field.
    #
    # Escape (not Enter) closes the popup: Enter commits the highlighted cell, which is TODAY
    # (measured: 08/27/2026). Then blur explicitly, so forceParse runs INSIDE this action and
    # the read-back sees the value the widget actually kept.
    try:
        is_picker = await first.evaluate(_PICKER_PROBE_JS, timeout=2000)
    except Exception:  # noqa: BLE001 — probe is advisory
        is_picker = False
    if is_picker:
        await first.click(timeout=timeout_ms)
        await first.press("ControlOrMeta+a", timeout=timeout_ms)
        await first.press_sequentially(text, timeout=timeout_ms)
        await first.press("Escape", timeout=timeout_ms)
        await first.evaluate("el => el.blur()", timeout=2000)
        ok, current = await verify()          # post-commit: "" here means the widget rejected it
        if ok:
            return
        raise ActionDispatchError(
            f"fill did not stick: the date widget rejected {text!r} and left {current!r}"
        )
    # …existing fill → press_sequentially → native-setter ladder, unchanged…
```

Three properties worth stating explicitly:

- **Still one action per transition.** The rung is internal to `_fill`, exactly like the existing
  two escalations; the artifact still records a single `FillAction`. Nothing about the NFA changes.
- **Still zero-LLM.** The probe is a pure DOM read, run at replay too, so a replay on the same page
  takes the same rung. The alternative — baking a `commit: "blur"` flag onto `FillAction` at
  compile time — is also defensible (it makes the artifact self-describing and removes a live
  probe from the hot path) but it hard-codes a page property into the artifact and would need a
  schema change; I'd start with the live probe and promote it to a schema field only if replay
  determinism turns out to need it.
- **The error is now honest.** Today the value-was-wiped case silently "succeeds"; after this
  change it raises, the failure lands in `history` (`graph.py:148`), and the agent gets told.

### (d) A `select_date` compound action is **not** warranted

Only Skyvern has anything like one, and it is not an action — it is a *loop*:
`sequentially_select_from_dropdown` with `MAX_DATEPICKER_DEPTH = 30`
(`handler.py:10354-10357`), i.e. up to thirty LLM-driven click rounds through month/year
navigation, entered only after `input_sequentially` has been tried and failed (`:10480-10495`).
browser-use, Stagehand, Playwright MCP, agent-browser, Notte, Agent-E and Magentic-UI all keep
dates inside `type`/`fill` plus prompt guidance.

For NetGent the argument is stronger than "most systems don't". Our formalism says a transition
carries **exactly one atomic action**; "pick 15 May 1990 in a calendar" is inherently
`click(prev-month) × k → click(day-cell)`, which is a *path through the NFA*, not an edge. That is
precisely what the automaton is for, and it is what our `Repeat`/`Branch` control forms already
express. A `select_date` edge would hide an unbounded loop inside a single transition and make the
artifact unreplayable without re-deriving the loop bound. Keep it in `fill`; when a field is
genuinely calendar-only (flatpickr's default `readonly` input, §4.1), let the agent emit click
transitions — and surface `readonly` in the observation so it knows to.

### 7.1 Expected effect, per fix

Derived from the §2.1 matrix, which varies exactly one thing at a time.

| fix | `angularjs.html` | `jquery-bootstrap.html` | sweep |
|---|---|---|---|
| (a) `format=` hint only | **passes** — the agent now writes `05/15/1990`, which a plain `fill` accepts | still fails — `fill` wipes the value regardless of format | 20/21 |
| (b) prompt retrigger only | *may* pass — the "error text persists" clause fires, and the retry order starts at `MM/DD/YYYY`; costs 2-3 extra steps and depends on the model actually varying the string | still fails — every retry is another `fill` | 19-20/21 |
| (c) typing rung only | still fails — dispatch is not the problem there | **passes**, but with `10/05/15` (bootstrap-datepicker's lenient parse of `1990-05-15`): the form accepts it because it only checks non-empty, so the *sweep* goes green on a **wrong date** | 20/21 |
| **(a) + (c)** | **passes** | **passes with `05/15/1990`** | **21/21, correct data** |
| (a)+(b)+(c) | passes | passes | 21/21, plus recovery on unseen sites where no signal fires |

(c) alone passing with wrong data is the reason to ship (a) with it rather than after it: a green
sweep that writes 15 Oct 0015 as a date of birth is worse for a *dataset-generation* product than
a red one.

### 7.2 Regression surface

| at risk | why | mitigation |
|---|---|---|
| **15 native `input[type=date]`** across the sweep | Typing ISO per key into a segmented native control yields garbage that still reports `validity.valid = true` — measured `1990-05-15` → `0515-12-09` (§4) | `_PICKER_PROBE_JS` returns `false` for any `type` other than `text`/`""`. This is the single most important line in the probe. |
| **`react-native-web-form`** (`type=text`, `placeholder="MM/DD/YYYY"`, `class="rn-textinput"`) — passes today | If we routed it to per-key typing, RN Web's controlled input re-renders on every keystroke | The probe fires only on a **picker library**, never on a placeholder alone. The placeholder still produces a `format=` hint (observation-only, no dispatch change). |
| **`contenteditable-form` `#birthDateField`** (`data-placeholder`, `data-field`) — passes today | Contenteditable already reaches `press_sequentially` as the existing rung 2 | Probe is `tagName === 'INPUT'` only; contenteditable is untouched. |
| **`animated-form`** `input[type=date] placeholder=" "` | A one-space placeholder could be mistaken for a format string | The `/^[dmy][dmy\W]{5,}$/i` guard rejects it; and native types short-circuit to ISO before the placeholder branch is reached. |
| **`i18n-form`** split `<select>` day/month/year | Not an input at all | Untouched — `select` path. |
| The existing `_fill` docstring warns the typed rung once *"opened a datepicker popup and garbled the field"* | That is the `Enter`/left-open-popup failure | The new rung ends with `Escape` + explicit `blur()` before verifying, which is exactly the ordering that measured clean (§2.2). |
| `verify()`'s "any non-empty new value is success" rule | It is what let the wipe pass silently | Unchanged for the general case; the picker rung verifies **after** the commit, so a wipe is caught. |

---

## 8. Unverified / open

1. **UI-CUBE calendar claim.** A web-search summary attributed to UI-CUBE (arXiv:2511.17131) the
   finding that *"calendar interfaces prove particularly problematic, with models clicking correct
   day numbers in wrong months or targeting whitespace adjacent to date cells."* The abstract
   contains no mention of calendars and the PDF body would not extract for me. **Treat as
   unverified**; if the sentence matters, read the rendered PDF.
2. **browser-use's actual pass rate on these two forms.** I read their code, not their runs. Their
   `uib-datepicker-popup` branch clearly targets `angularjs.html`; whether their bootstrap path
   catches `jquery-bootstrap.html` in practice is a *prediction* from §3.1 (no attribute or class
   fires, and their serializer's bootstrap branch does not check `data-provide` or ancestors),
   not a measurement. Running their agent on the suite would settle it.
3. **Stagehand's server-side `act`.** `act` reasoning moved server-side and is closed; my claim
   that Stagehand has no date handling covers the open-source client and extension only. A
   server-side format hint would be invisible to me.
4. **Locale mapping.** I map `en-US`/`en` → `MM/DD/YYYY` and everything else → `DD/MM/YYYY` for
   locale-agnostic libraries. That is a coarse rule (it is wrong for `en-CA`, `ja`, `hu`, and for
   most of central Europe's dotted `DD.MM.YYYY`). It only ever applies as a *last* fallback, after
   an explicit attribute and a placeholder have both failed. `Intl.DateTimeFormat().formatToParts`
   would give the real order without page JS, and is worth considering if this fallback is ever
   observed to matter.
5. **Whether the framework-invalid signal (§5 #18) is safe to fold into `invalid`.** `ng-invalid`
   appears on pristine untouched fields too (measured: `ng-invalid ng-invalid-required` before any
   interaction), so folding it in naively would mark every empty Angular field `[invalid]` — which
   is arguably correct but changes the meaning of the marker sweep-wide. It needs its own A/B run
   before shipping; I did not measure it.
6. **The `MM/dd/yyyy` → `MM/DD/YYYY` normalisation** in the walker sketch upper-cases the attribute
   value so the model sees one consistent notation. Library format languages differ (`yyyy` vs
   `YYYY` vs `Y-m-d` in flatpickr); a flatpickr `dateFormat` string read from an attribute would
   need translating, not upper-casing. No form in this suite exercises that path.
7. **`InteractionTasks_v8.json` task-level ground truth** is only the string `"successfully"`; I
   found no per-form pass-rate publication in either repo. If browser-use publishes eval runs
   elsewhere (their cloud dashboards), those numbers were not reachable from the repos.

---

## 9. Method

Sources fetched 2026-08-27. Pinned commits: browser-use `28670f7`, Skyvern `d081a53`, Stagehand
`341433a`, Playwright `32095ea`, vercel-labs/agent-browser `fbd046c`, Agent-E `f218c3c`,
Notte `1802f00`, LaVague `9024bb8`, magentic-ui `d3c9d13`, browser-use/stress-tests `b3600b6`.
Library sources read at the versions the failing pages actually load
(bootstrap-datepicker 1.9.0 from cdnjs — the exact URL in `jquery-bootstrap.html:114`;
angular-ui-bootstrap 2.5.0; jQuery UI 1.13.2) plus flatpickr, react-datepicker, MUI X and
Ant Design at their current docs/`main`.

Measurements were taken with five throwaway probes driving this repo's own
`BrowserSession` (headless Patchright, `PATCHED_BROWSER = True`) against the live GitHub Pages,
written to `/tmp/ng-research/` and not committed:

| probe | what it measured | rows |
|---|---|---|
| `probe_dates.py` | every §5 signal on both date inputs; the observation our serializer renders; a first pass at the value trajectory | 2 forms |
| `probe2.py` | value trajectory per strategy, **one fresh page load per cell** (the first probe suffered cross-trial contamination from a picker left open — the numbers in §2.2 are probe 2's) | 20 |
| `probe3.py` | end-to-end: every other field filled deterministically, only the date strategy varied, success read from the suite's own `dumbledore` marker | 16 |
| `probe4.py` | inventory of all 21 date-ish inputs across `forms-comparison.html` and which signals each carries | 21 |
| `probe5.py` | regression check: `fill` vs per-key typing, ISO vs US, into a native `input[type=date]` | 4 |

Every "measured" claim in this document comes from one of those five. Claims about other systems
come from their source at the pinned commit; claims about libraries come from that library's
source or its own documentation; nothing here is from memory.
