# Accessibility-tree observation for the explore agent — a controlled A/B

**Branch:** `v2/accessibility-tree` (from `eugene/v2-scaffold`). **Flag:** `NETGENT_OBSERVATION=dom|ax`
(default `dom`), also `--observation` on `netgent agent` / `netgent generate`.

**Question.** Does switching the explore agent's *observation* from our injected DOM walk to the
browser's accessibility tree make exploration more robust and cheaper, without losing what the
DOM walk gives us (iframe/shadow coverage, form state, viewport paging, durable locators)?

**Answer in one paragraph.** Yes for robustness of *element identity* — the accessibility backend
names controls the DOM heuristic cannot (radios/checkboxes labelled by following text, icon
buttons), and its role+name locators resolve to exactly one element far more often (Reddit: 88 %
vs 29 %; Twitch 80 % vs 54 %). Cost is a wash (observation size within ±5 %; the ax snapshot is
slower on huge pages because DOM facts are fetched per element). End-to-end on the stress tests
the two backends are within noise of each other with Haiku once the agent-loop gaps the challenge
exposed were fixed *for both*. Recommendation: **switch the default to `ax` (the hybrid), keep
`dom` as the fallback the session already performs automatically**, with the caveats in §8.

---

## 1. Prior art — what working systems actually do (sources read, paths cited)

All paths are relative to the clone roots under `/tmp/ax-refs/` at the time of reading
(2026-08-21): `pw` = microsoft/playwright @ `9642f57`, `agent-browser` = vercel-labs/agent-browser,
`stagehand` = browserbase/stagehand @ `a21633d`, `browser-use` = browser-use/browser-use,
`skyvern` = Skyvern-AI/skyvern @ `888348d`. (`magnitudedev/magnitude` has pivoted to a coding agent;
its browser stack no longer exists in the repo, so it is not compared.)

### 1.1 microsoft/playwright-mcp — Playwright's aria snapshot in `ai` mode + `aria-ref`

The MCP server's source lives in the Playwright monorepo (`playwright-mcp/src/README.md`).
`browser_snapshot` (`pw/packages/playwright-core/src/tools/backend/snapshot.ts:35-56`, capture in
`tools/backend/tab.ts:419-452`) calls `page.ariaSnapshot({ mode: 'ai', depth, boxes })`.

* **Walk.** A raw DOM walk inside the injected script, not the platform AX tree:
  `generateAriaTree` in `pw/packages/injected/src/ariaSnapshot.ts:76` → `visit` (`:89-160`).
  Roles come from `roleUtils.getAriaRole` (`pw/packages/injected/src/roleUtils.ts:281`, implicit
  roles at `:242`); the accessible name from `roleUtils.getElementAccessibleName` (`:538-547`), a
  full accname implementation (labels `:1225-1233`, name-from-content `:1035-1067`). **This is the
  same code `getByRole(name=…)` matches against** — the decisive property for us (§2).
* **Refs.** `computeAriaRef` (`ariaSnapshot.ts:220-233`): a ref is minted for every node that is
  `box.visible && receivesPointerEvents` — *not* a curated interactive-role list; headings and
  generics get refs too. The ref is cached on the element (`element._ariaRef`) and reused across
  snapshots while role+name are unchanged. `[cursor=pointer]` is an orthogonal annotation
  (`pw/packages/isomorphic/ariaSnapshot.ts:54-56`).
* **Iframes.** Not descended in the injected script: `toAriaNode` turns `IFRAME/FRAME` into a
  childless `iframe` node (`ariaSnapshot.ts:236-252`). Stitching is server-side in
  `ariaSnapshotJSONForFrame` (`pw/packages/playwright-core/src/server/page.ts:1143-1170`), which
  recurses with the selector ``aria-ref=${ref} >> internal:control=enter-frame >> body,frameset``
  — uniformly for same- and cross-origin frames. Child refs are prefixed by the frame sequence
  number (`injectedScript.ts:327`, `frames.ts:133-135`): `e12` in the main frame, `f3e12` in frame 3.
* **Ref → locator.** The `aria-ref` selector engine (`injectedScript.ts:737-743`) looks the ref up
  in the last snapshot's map and checks `isConnected`; the frame prefix is resolved server-side by
  `FrameSelectors._jumpToAriaRefFrameIfNeeded` (`frameSelectors.ts:109-121`). Tools consume refs in
  `Tab.targetLocators` (`tools/backend/tab.ts:497-521`): `page.locator('aria-ref=e12')`, then
  `locator.normalize()` → `Frame.resolveSelector` (`frames.ts:1312-1339`) turns the ref into an
  idiomatic locator (`getByRole('button', { name: 'Submit' })`, with
  `>> internal:control=enter-frame` hops for iframes) — refs are the model-facing handle, role
  locators the code-facing artifact. Stale refs: `isConnected`, map replaced per snapshot, and the
  main frame is **re-numbered on cross-document navigation** (`frames.ts:274-278`) so old
  `f<seq>e<n>` refs cannot alias new elements.
* **Shadow DOM.** Open roots are pierced explicitly (`ariaSnapshot.ts:172-184`, slots via
  `assignedNodes()`); accname mirrors this (`roleUtils.ts:1049-1062`). Closed roots are invisible.
* **Duplicates.** No dedup; same role+name are distinct refs. **No viewport filtering** anywhere.
* **Distillation** (`ariaSnapshotDistiller.ts:256-263`): merge string children, drop nameless
  images, drop names already visible as content, unwrap single-child generics — refs of removed
  nodes still resolve.

### 1.2 vercel-labs/agent-browser — raw CDP `Accessibility.getFullAXTree`, role/name/nth fallback

Pure Rust + CDP, no Playwright. `take_snapshot` (`agent-browser/cli/src/native/snapshot.rs:216`)
calls `Accessibility.getFullAXTree` (`:308-314`), builds an index tree from `childIds`
(`build_tree`, `:928`), drops `ignored` and `InlineTextBox` nodes (`:946-951`), coalesces adjacent
`StaticText` (`:1004-1032`) and renders Playwright-style lines `- role "name" [ref=e3]`.

* **Refs** are sequential for `INTERACTIVE_ROLES` (`:11-29`), for named `CONTENT_ROLES` (`:31-41`),
  and for DOM "cursor-interactive" nodes (`:370-376`). Each `RefEntry` stores
  `{backend_node_id, role, name, nth, frame_id}` (`element.rs:9`).
* **Ref → action.** `resolve_element_center` (`element.rs:299`): `DOM.scrollIntoViewIfNeeded` +
  `DOM.getBoxModel` on the cached backendNodeId; **if stale, re-query the AX tree by
  role+name+nth** (`find_node_id_by_role_name`, `element.rs:629`) — the same data source as the
  snapshot so matching stays consistent. `nth` is only persisted for keys with count > 1
  (`RoleNameTracker`, `snapshot.rs:175-214`).
* **`-i`** prunes at render time (nodes without refs are skipped, children still render,
  `:1109-1115`); **`-d`** is an indent cutoff (`:1094-1098`); **`-c`** is a post-filter keeping only
  lines with `ref=` or a value plus their ancestors (`:1196-1233`); **`-s`** scopes through
  `DOM.describeNode{depth:-1}` collecting backendNodeIds incl. `shadowRoots`/`contentDocument`
  (`:1332-1352`).
* **Iframes.** One level only (`:497`): for each `Iframe` node, `DOM.describeNode` →
  `contentDocument.frameId` (`resolve_iframe_frame_id`, `:589`) then recurse; same-origin frames via
  `{frameId}` on the page session, OOPIFs via their own session from `Target.attachedToTarget`
  (`element.rs:614-628`, `actions.rs:1445-1458`). Child output is textually spliced (`:520-572`).
* **Shadow DOM.** No explicit piercing; works only because Chrome's AX tree includes shadow content.
* Notable extra: a hit-test "is the click point covered by `<div#consent-banner>`" check
  (`check_node_interception`, `element.rs:402`).

### 1.3 browserbase/stagehand — CDP AX tree per frame fused with `DOM.getDocument` → XPaths

"Hybrid snapshot" (`stagehand/packages/extension/understudy/a11y/snapshot/capture.ts:41-58`): three
artifacts — an indented outline `[<encodedId>] role: name`, `encodedId → absolute cross-frame XPath`,
`encodedId → url`.

* **AX:** `a11yForFrame` (`a11yTree.ts:15-102`) calls `Accessibility.getFullAXTree` **with
  `frameId`**, falling back to an unscoped call when the frame is an OOPIF (`:26-40`).
* **DOM:** one `DOM.getDocument({depth:-1, pierce:true})` per *session* (`domTree.ts:233-323`),
  with an adaptive-depth retry around Chrome's CBOR stack overflow (`:118-148`). Join key =
  `backendNodeId` (AX `backendDOMNodeId` ↔ DOM `backendNodeId`). Ids are
  `${frameOrdinal}-${backendNodeId}` (`capture.ts:364`).
* **Pruning** (`a11yTree.ts:152-212`): keep named nodes / nodes with children / non-structural;
  structural `generic|none|inlinetextbox` with one child collapse into it; surviving generics take
  their DOM tag as role; `combobox` on `<select>` → `select`; `StaticText` equal to the parent name
  is dropped (`:247-263`). **Scrollables** are marked from the DOM node's `isScrollable`
  (`:122-134`); file inputs (`button` in Chrome AX) are re-labelled `input, file`.
* **Iframes:** frame topology from the page's own registry fed by `Target.setAutoAttach`
  (`understudy/cdp.ts:191-192`, `page.ts:403-451`); `DOM.getFrameOwner` on the *parent* session
  (`sessions.ts:21-31`); XPath prefixes concatenate `…/iframe[1]/html[1]/body[1]/…`
  (`capture.ts:717-776`), and `deepLocator.ts:214-245` splits them back into a FrameLocator chain.
* **Shadow DOM:** `pierce:true`; shadow hops are encoded as `//` in the XPath (`domTree.ts:292-299`)
  and resolved by a composed-tree walker (`dom/locatorScripts/xpathResolver.ts:118-168`).
* **Act:** XPath → objectId in the frame's isolated world → `DOM.scrollIntoViewIfNeeded` →
  `DOM.getBoxModel` → synthetic mouse events (`locator.ts:296-364`). No dedup of duplicate names
  (ids are unique), no hidden/offscreen check at snapshot time.

### 1.4 browser-use/browser-use — CDP `DOM.getDocument` + `Accessibility.getFullAXTree` + `DOMSnapshot`

`DomService._get_all_trees` (`browser-use/browser_use/dom/service.py:395-700`) issues in parallel:
`DOMSnapshot.captureSnapshot` (computed styles, paint order, rects), `DOM.getDocument{depth:-1,
pierce:true}`, `Accessibility.getFullAXTree` **per frame** (`_get_ax_tree_for_all_frames`,
`:357-397`), and `Page.getLayoutMetrics`; plus a `getEventListeners` pass through
`Runtime.evaluate{includeCommandLineAPI:true}` (`:465-510`).

* **Merge** by `backendNodeId` (`:737-757`); role/name straight from AX `role.value`/`name.value`
  (`:196-220`); AX properties kept (`views.py:300-310`), the LLM sees `checked, selected, expanded,
  pressed, disabled, invalid, required, …` (`views.py:18-82`).
* **Interactivity** (`serializer/clickable_elements.py:5-246`): JS click listener → iframes >100px →
  label/span wrapping a control → search-ish class/id → AX `focusable/editable/settable`, presence of
  `checked/expanded/pressed/selected`, `required/autocomplete` → tag set
  `{button,input,select,textarea,a,details,summary,option,optgroup}` → `onclick/…/tabindex` → roles →
  icon-sized elements with `aria-label` → `cursor: pointer`.
* **Visibility/occlusion:** CSS + frame-chain viewport intersection ±1000px (`service.py:250-355`);
  paint-order occlusion with an exact rect union per document (`serializer/paint_order.py:145-225`);
  ≥99 % bbox containment in a propagating parent excludes children (`serializer.py:768-918`).
* **Iframes:** same-origin via `pierce` with a running `total_frame_offset` (`:930-940`); OOPIFs
  behind `cross_origin_iframes` (default off!) via `Target.getTargets` and a full recursive DOM/AX
  round per child target (`:975-1064`). Shadow roots from `pierce` (`:948-970`).
* **Index → action:** the index *is* the `backendNodeId` when free (`serializer.py:633-655`);
  click = `DOM.scrollIntoViewIfNeeded` → `DOM.getContentQuads/getBoxModel` → `elementFromPoint`
  occlusion check → `Input.dispatchMouseEvent`, JS `click()` fallback
  (`browser/watchdogs/default_action_watchdog.py:767-950`).
* **Performance:** list→set for `isClickable` gave 5,925 ms → 2 ms at 20k elements
  (`enhanced_snapshot.py:97-101`); guardrails `max_iframes=100`, `max_iframe_depth=5`, only 10
  computed styles requested.

### 1.5 Skyvern — injected DOM walk, stamped ids, no accessible names

`skyvern/webeye/scraper/domUtils.js:2361` `buildTreeFromBody` per Playwright frame
(`scraper.py:704-764`, same-origin only; cross-origin frames are placeholders). Interactivity is
a long, site-specific ladder (`isInteractable`, `:1251-1475`) plus a `:hover`-stylesheet cursor
map (`getHoverStylesMap`, `:3175`). Identity is a **stamped attribute** `unique_id` (`:2176`) with
the frame index in the first char; actions resolve `frame.locator('[unique_id="…"]')`
(`actions/handler.py:9333`). Shadow DOM: open roots walked as a second child list (`:2505`),
xpath `null` inside them. No accname: direct text + `::before/::after` content (`:1691`, `:1822`).
Notable: `MutationObserver`-driven incremental scraping for dropdowns (`:3403`), structural
hashing of elements for re-identification (`scraper.py:229`).

### 1.6 Comparison

| | Tree source | Names | Ref → target | Cross-origin iframes | Shadow DOM | Viewport/occlusion |
|---|---|---|---|---|---|---|
| playwright-mcp | injected walk (`ai` mode) | Playwright accname (= `getByRole`) | `aria-ref` → role locator | yes, server-stitched `f<seq>e<n>` | open, explicit | none |
| agent-browser | CDP `getFullAXTree` | Chrome AX | backendNodeId, re-query by role/name/nth | yes (1 level), per-session | incidental | none at snapshot |
| stagehand | CDP AX + `DOM.getDocument` | Chrome AX | xpath with `//` shadow hops + FrameLocator chain | yes (sessions registry) | pierce + composed walker | none at snapshot |
| browser-use | CDP DOM + AX + DOMSnapshot | Chrome AX (+DOM attrs) | backendNodeId → CDP click | opt-in, full recursion | pierce | paint-order + bbox |
| Skyvern | injected walk | none (text + pseudo) | stamped `unique_id` | placeholders | open (no xpath) | hit-test at act |
| **NetGent `dom`** (today) | injected walk per Playwright frame | heuristic (aria-label/label/placeholder/name/innerText) | role/test-id/label/css candidates | yes (per-frame evaluate) | open | bbox paging |
| **NetGent `ax`** (this branch) | Playwright `aria_snapshot(mode="ai", boxes=True)` + DOM facts via `aria-ref` | Playwright accname (= `get_by_role`) | role+name `exact` (+`nth`) → test-id → label → css | yes (Playwright stitching) | open | bbox paging |

**What the evidence says.** Every production system that replays actions later (stagehand,
agent-browser, playwright-mcp) reconciles the *observation* with the *locator engine it will act
with*: agent-browser re-queries the same AX tree; stagehand hands back XPaths it built itself;
playwright-mcp's refs normalize to `getByRole` through the same accname code that produced the
name. Every system that needs form state, types, or scroll containers (stagehand, browser-use)
goes to the DOM for it — the AX tree does not carry `required`/validity/`<select>` options/input
type, and Chrome reports file inputs as `button`. Cross-origin iframes are the thing most get
partially wrong (browser-use off by default, agent-browser one level, Skyvern placeholders);
Playwright's frame manager handles OOPIFs for us already. Hence the hybrid below.

## 2. Design choice: Playwright aria snapshot (AI mode) + DOM facts, not raw CDP

Two candidates were evaluated on this repo's own browser (Patchright 1.62 = Playwright 1.62):

* **(ii) CDP `Accessibility.getFullAXTree` per frame.** Would need frame ids per Playwright frame
  (not exposed; requires `Page.getFrameTree` matching or stamping), a separate session per OOPIF,
  `DOM.getBoxModel` per node for paging, and — crucially — it yields *Chrome's* accessible names,
  which differ from Playwright's accname in edge cases (hidden content, `title`, placeholder,
  whitespace), so `get_by_role(name=…, exact=True)` could miss. Patchright also deliberately avoids
  `Runtime.enable`-style CDP traffic for stealth.
* **(i) `page.locator("body").aria_snapshot(mode="ai", boxes=True)`** — chosen. One call returns
  every frame (27 on the forms page, 0.31 s, same- and cross-origin — verified with a two-origin
  fixture), pierces open shadow roots (a textbox inside a shadow root inside a cross-origin frame
  came back as `ref=f1e7` and resolved), includes `[box=x,y,w,h]` per node for viewport paging (frame-
  local; we offset by the ancestor iframe's box), `[checked]/[disabled]/[expanded]/[active]/
  [cursor=pointer]`, values, and a `[ref=…]` that `page.locator("aria-ref=f1e7")` resolves across
  frames. Names are computed by the same engine `get_by_role` uses, so `exact=True` round-trips.

**What the AX tree lacks and where we get it** (`browser/dom/ax_snapshot.py`):

| Need | Source |
|---|---|
| input `type` (date/time/file/range), `required`, native `validity`, `<select>` option values, current value, stable `#id`/`data-testid`, label association, CSS-path fallback | `locator("aria-ref=…").evaluate(ELEMENT_FACTS_JS)` per interactive node, gathered concurrently (205 nodes in 0.28 s on the forms page — equal to the DOM walk) |
| iframe chain selector (`frame_locator` steps) | `FRAME_SELECTOR_JS` evaluated on the iframe node's `aria-ref` |
| elements interactive by structure only: `tabindex`, `onclick`, `contenteditable`, `<summary>`, scrollable boxes, elements with direct `addEventListener` mouse/keyboard listeners | the DOM walk in `extrasOnly` mode (`DOM_SNAPSHOT_JS`), merged by frame + bbox (`merge_extras`) |
| `role+name` uniqueness | counted per (frame, role, name) in the tree; duplicates get `.nth(k)` |
| page text | AX text nodes; consecutive inline fragments merged into one block (`Score: 0 / 17`), `alert`/`status` flagged, `y` kept for paging |

The LLM-facing format (`format_observation`) is byte-for-byte the same renderer for both backends;
only the `DomSnapshot` producer differs. The session falls back to the DOM walk if the ax path
raises (logged), so observation can never abort a step.

## 3. Gap fixes the challenge exposed — applied to BOTH backends (general, formalism-preserving)

| Gap (challenge card) | Fix | Where |
|---|---|---|
| "Scroll to the bottom of this legal text" — inner scroll container not observable, `scroll` only page-level | scrollable boxes listed as `div (scrollable) "…" value="scrolled 37%"`; `ScrollAction.locator` (optional) → hover + wheel inside it. Still the one `scroll` atomic action, now with an optional target. | `snapshot.py` (`isScrollable`), `schema/actions.py`, `session.py` |
| "Hover over this element" — plain `div` with a `mouseenter` listener, no role/cursor | CDP `getEventListeners` probe (browser-use's technique) marks elements with direct mouse/keyboard listeners interactive — restricted to named, non-page-sized elements without interactive descendants (YouTube hangs listeners on `<html>`/`<ytd-app>`) | `session._listener_probe`, `snapshot.py` |
| "Expand this details section" — `<summary>` is not a button in either tree | `<summary>` added to the interactive tag set (no ARIA role; CSS fallback anchored at the nearest stable-id ancestor) | `snapshot.py` |
| "Score: 0 / 17" rendered as three fragments | inline-children text merge (DOM walk) / inline-run merge (AX) | both |
| 40+ text blocks, the observation showed the first 25 → lower cards' instructions invisible | text blocks carry `y` and are paged with the viewport like elements | `observation.py` |
| Haiku emits `press "Return"`, `press "ArrowRight ArrowRight ArrowRight"` | key aliases (`Return→Enter`, …) and space-separated sequences | `session.normalize_keys`, dispatch |
| the model repeats an action whose effect it cannot see (click-to-focus, a counter bump) | step history now carries outcomes: `-> page now shows: 'Score: 4 / 17'` / `-> done, but nothing visible changed`; one explicit warning before the stuck detector ends the run (`MAX_REPEAT` → warn, `2×` → stop) | `graph.py` |
| canvas CAPTCHA | **not fixed** — needs vision; out of scope for an observation-layer change (both backends skip it) | — |

No new atomic action was needed. `scroll` gained an optional `locator`; `press` accepts a sequence.

## 4. Observation A/B — measurements (no LLM)

`uv run python evals/observation_ab.py` → `evals/results/observation_ab.md` (+ `.json`).

RESULTS_TABLE

## 5. Form sweep — 21 forms, Haiku, both backends

`uv run python evals/stress_ab.py sweep --backend dom|ax` (`sweep_forms`, `max_steps_per_form=30`,
`retries=1`, one agent with continuous memory, verified by the form's own success marker).

SWEEP_RESULTS

## 6. Challenge game — browser-use/stress-tests/challenge.html, Haiku, both backends

How the page signals progress (read from its source): 15 task cards (the header says `/ 17`);
each card calls `completeTask(card)` from its own listener (click, `change`, `input ≥ 90` for sliders,
`keypress Enter` with value `squash`, `mouseenter` held 1 s, `scroll` to the container bottom enabling
the button, three `ArrowRight` keydowns on a `tabindex=0` div, `change` on a file input, `toggle` on
`<details>`, `change` on both selects (`red` + `ball`, the second is a Select2 widget over a hidden
`<select>`), `input` on a contenteditable equal to `banana`, and `input` on the canvas text field
equal to `CAPTCHA123`). Completion: the `.score` span counts completed cards; `.task.completed`
classes list them. One `netgent agent`-style run per backend (`BrowserAgent.run`, `max_steps=60`),
score read from the page afterwards.

Exact prompt (`evals/stress_ab.py::CHALLENGE_TASK`):

> CHALLENGE_PROMPT

CHALLENGE_RESULTS

## 7. `netgent generate` — YouTube and Twitch with the ax backend

GENERATE_RESULTS

## 8. Recommendation and honest limitations

RECOMMENDATION
