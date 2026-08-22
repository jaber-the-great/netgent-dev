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
| a sweep crashed at form 14: Submit navigated the frame and the next `observe()` evaluated into a dying document (`Execution context was destroyed`) | `snapshot()` recognizes navigation errors, waits for `domcontentloaded` (bounded 5 s) and retries up to 3×; a detached frame is skipped, other errors still raise | `session.snapshot`, `tests/integration/test_snapshot_during_navigation.py` |
| canvas CAPTCHA | **not fixed** — needs vision; out of scope for an observation-layer change (both backends skip it) | — |

No new atomic action was needed. `scroll` gained an optional `locator`; `press` accepts a sequence.

## 4. Observation A/B — measurements (no LLM)

`uv run python evals/observation_ab.py` → `evals/results/observation_ab.md` (+ `.json`).

| site | backend | elements | named % | role loc % | unique % | resolves % | obs chars | ~tokens | texts | snapshot s | frames | in iframes | iframes w/ elems |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| youtube | dom | 14 | 85.7 | 35.7 | 42.9 | 100.0 | 761 | 190 | 6 | 0.083 | 3 | 0 | 0 |
| youtube | ax | 13 | 100.0 | 38.5 | 46.2 | 100.0 | 781 | 195 | 3 | 0.106 | 3 | 0 | 0 |
| twitch | dom | 115 | 86.1 | 86.1 | 48.7 | 87.8 | 3078 | 769 | 76 | 0.14 | 5 | 4 | 1 |
| twitch | ax | 106 | 68.9 | 68.9 | 79.2 | 99.1 | 2978 | 744 | 17 | 0.282 | 5 | 3 | 1 |
| reddit | dom | 98 | 89.8 | 73.5 | 51.0 | 88.8 | 2938 | 734 | 45 | 0.417 | 5 | 1 | 1 |
| reddit | ax | 96 | 87.5 | 72.9 | 87.5 | 92.7 | 2877 | 719 | 17 | 0.313 | 5 | 1 | 1 |
| forms | dom | 207 | 90.3 | 27.5 | 100.0 | 100.0 | 5111 | 1277 | 243 | 0.263 | 27 | 181 | 23 |
| forms | ax | 222 | 84.2 | 30.2 | 99.5 | 99.5 | 5351 | 1337 | 148 | 0.649 | 27 | 197 | 23 |
| challenge | dom | 42 | 71.4 | 2.4 | 64.3 | 100.0 | 3001 | 750 | 42 | 0.018 | 2 | 1 | 1 |
| challenge | ax | 41 | 85.4 | 22.0 | 63.4 | 100.0 | 3503 | 875 | 38 | 0.141 | 2 | 1 | 1 |
| todomvc-spa | dom | 4 | 100.0 | 100.0 | 75.0 | 100.0 | 341 | 85 | 5 | 0.017 | 1 | 0 | 0 |
| todomvc-spa | ax | 4 | 100.0 | 100.0 | 100.0 | 100.0 | 372 | 93 | 5 | 0.014 | 1 | 0 | 0 |

Both backends measured on the **same loaded page** (one session, snapshot with `dom` then `ax`).
YouTube serves a signed-out shell headless (13–14 elements); Reddit showed its login interstitial
in this session (≈100 elements; an earlier separate-session run had 537/488 with the same
shape of result: unique 28.7 % dom vs 88.3 % ax).

Reading the table:

* **Durable-locator uniqueness** (`unique %`) is the headline: Reddit 51 → 87.5 %, Twitch 48.7 →
  79.2 %, todomvc 75 → 100 %. The DOM walk's names are heuristics (`aria-label` → label →
  placeholder → `name` attr → innerText), so on modern sites its `get_by_role(name=…)` chain
  either matches nothing (`resolves %` 88 % on Twitch/Reddit vs 99/93 % for ax) or several
  elements (substring matching without `exact`). The ax names are Playwright's own accname, so
  they match exactly, and duplicates get `.nth(k)`.
* **Observation size is the same** (±5 % chars/tokens) because the renderer is shared and the
  element sets largely coincide (coverage diffs below). The fear that "the aria tree is 3× larger"
  was about the raw YAML; after filtering to interactive nodes + merged text it is not.
* **Snapshot time**: ax is 1.3–2.5× slower on big pages (Twitch 0.28 s vs 0.14 s, forms 0.65 s vs
  0.26 s) because DOM facts are fetched per element through `aria-ref`; Reddit's 488-element page
  took 1.0 s in the separate-session run. Still far below one LLM call (2–5 s).
* **Iframe coverage is identical** (27 frames / 23 with elements on the forms page for both); the
  ax backend lists 16 more elements there — the hidden file inputs that Playwright names from
  their custom-file labels (`input "Upload Profile Picture * Choose file Browse"`), which the DOM
  walk drops as invisible (0×0 box).
* **`named %`** is lower for ax on Twitch/forms: icon links/thumbnails whose accessible name is
  genuinely empty. The display-name fallback (DOM `title`/`placeholder`/`alt`/label/innerText) was
  added after this table was generated; the locator for such elements is the stable `#id` or a
  CSS path in both backends.

Coverage differences (same page, matched by frame + tag + coarse bbox):

- **youtube**: 12 elements seen by both (by frame+bbox), 1 only by dom, 0 only by ax.
- **twitch**: 61 elements seen by both (by frame+bbox), 5 only by dom, 0 only by ax.
  - dom-only e.g.: 'button Leave feedback for this Ad', 'button [595/730] 🔴 DUOING TO CHAMPION W, 'button WARDOGS BETA | SEAL TEAM SEXY | , 'button Leave feedback for this Ad', 'button PRODUCER WARS! GAMERHOOD S5 EP. , 'button EARLY AND DUEL - SHORT SHORT - I
- **reddit**: 85 elements seen by both (by frame+bbox), 3 only by dom, 1 only by ax.
  - dom-only e.g.: 'shreddit-progress-bar Media time', 'faceplate-tracker Continue with Phone N, 'faceplate-tracker Continue with Email'
  - ax-only e.g.: 'shreddit-progress-bar Media time'
- **forms**: 191 elements seen by both (by frame+bbox), 3 only by dom, 17 only by ax.
  - dom-only e.g.: 'button PLAY THE BROWSER-USE CHALLENGE G, 'input Email Address', 'input Upload Document'
  - ax-only e.g.: 'input Upload Profile Picture * Choose f, 'input Email', 'input Phone', 'input Mail', 'input Choose File', 'input Email Address *'
- **challenge**: 37 elements seen by both (by frame+bbox), 0 only by dom, 0 only by ax.
- **todomvc-spa**: 4 elements seen by both (by frame+bbox), 0 only by dom, 0 only by ax.


## 5. Form sweep — 21 forms, Haiku, both backends

`uv run python evals/stress_ab.py sweep --backend dom|ax` (`sweep_forms`, `max_steps_per_form=30`,
`retries=1`, one agent with continuous memory, verified by the form's own success marker).

`uv run python evals/stress_ab.py sweep --backend dom|ax` — `sweep_forms`, one agent (continuous
memory) walked through all 21 forms, each attempted up to 2× (`retries=1`), `max_steps_per_form=30`,
verified by the form's own `dumbledore` success marker (not the agent's self-report). Haiku.

Final code (v3, with the navigation guard of §3):

| backend | forms submitted (of 21) | LLM calls | input tokens | output tokens | wall |
|---|---|---|---|---|---|
| dom | **11/21** | 346 | 1,025,717 | 36,266 | 860s |
| ax | **5/21** | 407 | 1,231,313 | 41,813 | 1113s |

Per-form (v3): dom OK = [3, 4, 6, 8, 10, 12, 14, 17, 18, 19, 20]; ax OK = [3, 4, 6, 16, 19].

**This is a model+widget number, not an observation-quality number, and it is noisy.** Across
three runs on final code the counts were dom 8 / 8 / 11 and ax 4 / 1 / 5. The 1/21 outlier
(sweep-ax-v2) was a real bug, now fixed: the agent issued a `goto` during one form, the whole
page left `forms-comparison.html` for `about:blank`, and every later form saw an empty scoped
observation and flailed — one stray navigation poisoned the rest of the sweep. The §3 guard
(re-assert the base URL before each form; FORM_TASK forbids `goto`/`go_back`) removed the cascade
(no wandered forms in v3).

The remaining gap between backends is dominated by the page's deliberately hostile widgets and by
model behaviour, not by what the observation shows:

* The recurring failure in BOTH backends is *fill every field → click Submit → nothing happens →
  scroll-thrash until the stuck detector fires*. The form's client-side validation silently
  rejects a field the model believes it filled (a custom date picker, a Select2 whose hidden
  `<select>` never received the value, a contenteditable email host that times out on `.fill`).
  These are widget/model problems; the observation lists the field and a resolving locator in
  both backends (§4 `forms` row: dom unique 100 %, ax 99.5 %).
* Where the counts diverge run-to-run, it is because the ax names for custom controls (e.g. a
  radio exposed with `role=button`, a Select2 combobox duplicated as two nodes) sometimes lead
  the model down a different path than the DOM walk's heuristic names — not because a control is
  missing. Neither backend clears this page; browser-use's own agent does not either.

The observation-layer fixes the sweep *did* surface and that are now general (contenteditable
host de-duplication, hidden file inputs behind a styled label/button, `data-placeholder` names)
are in §3 and covered by tests; they moved specific forms (10, 16) from "field not observable" to
"observed and fillable".


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

> Complete every task on this page, working top to bottom. Each task is a card whose instruction is in the page text (e.g. 'Click the button to start', 'Select one of the radio buttons'). The header shows 'Score: N / 17' and N goes up by one each time a task registers; a card's own text (slider value, keys pressed, upload status) also tells you whether it registered. There are exactly 15 cards (the page's '/ 17' is a typo — the score can never reach 17, so do not hunt for missing points). Do exactly what each instruction says using click, fill, select, hover, press, upload, or scroll-inside-a-box; attempt each card once, in order, and do not go back. If a card is impossible for you (e.g. reading letters off a canvas image), skip it and move on. Scroll down only when every card in view is done or skipped. Finish with done (success=true if you attempted all 15 cards) when the last card (the contenteditable one) is done.

Results (`max_steps=60`, one run each, final code; earlier runs are in git history of `evals/results/stress/`):

| backend | score (of 15 possible) | steps used | LLM calls | input tokens | output tokens | observation chars | stopped |
|---|---|---|---|---|---|---|---|
| dom | **13** | 38 | 36 | 127,698 | 3,868 | 80,740 | stuck: 6 steps with no change on screen |
| ax | **13** | 28 | 27 | 98,633 | 2,956 | 73,753 | All 15 cards have been completed: Task 1-13 were completed i |

Cards missed — dom: slider-drag, canvas-captcha; ax: canvas-captcha, iframe-slider.

* `canvas-captcha` is unreachable for both: the text lives only in pixels. A vision input would
  be an agent change, not an observation-backend one (see §8).
* The other misses are model variance, not observation gaps: the dom run *clicked* the main
  slider instead of filling it; the ax run simply skipped the iframe slider card (it was listed as
  `[24] input[range] value="1"` with the iframe frame path) — both runs filled the *other* slider
  correctly by `fill "100"`.
* The dom run then spent 8 steps scrolling up and down "looking for the 4 missing tasks"
  (13/17) until the stuck detector stopped it; the ax run declared `done` at step 27. With the
  page's own `/ 17` contradicting the 15 cards, this is prompt/model behaviour, not observation.
* Before the gap fixes of §3 the same prompt scored **8/15 with both backends** (stuck at the
  arrow-key card: click-to-focus repeated 3× with no visible change, then `press "Return"` /
  `"ArrowRight ArrowRight ArrowRight"` rejected). With the fixes both reach 13/15 — the fixes,
  not the tree source, are what moved the number; the tree source decides how *durable* the
  compiled locators are.


## 7. `netgent generate` — YouTube and Twitch with the ax backend

Commands (Haiku, `--observation dom|ax`, `--trajectory` kept under `evals/results/stress/generate/`):

```
netgent generate "Search YouTube for cat videos and play the first result" --url https://www.youtube.com \
  -p "query=cat videos" --model anthropic/claude-haiku-4-5-20251001 --observation ax --out cat-video-ax.yaml
netgent generate "Search Twitch for the channel monstercat, open it, wait ONCE with seconds=10 to watch the stream, then declare done." \
  --url https://www.twitch.tv -p channel=monstercat --model anthropic/claude-haiku-4-5-20251001 --observation ax --out twitch-live-ax.yaml
```

| site | backend | validated (zero-LLM replay) | compiled edges | LLM calls | input tokens | output tokens | observation chars |
|---|---|---|---|---|---|---|---|
| youtube | dom | ✓ | 17 | 20 | 58,650 | 1,905 | 30,100 |
| youtube | ax | ✓ | 7 | 8 | 26,865 | 789 | 16,351 |
| twitch | dom | ✓ | 5 | 5 | 17,202 | 528 | 14,487 |
| twitch | ax | ✓ | 8 | 9 | 31,346 | 900 | 26,871 |

All four validated. YouTube with the ax backend took 8 steps/26.9k tokens vs 20 steps/58.7k for
dom on the same task (the dom run wandered before finding the search box; one run each, so treat
the gap as indicative). Twitch was the reverse (9 vs 5 steps): the ax run hit a click intercepted
by a consent overlay once and recovered. The compiled YouTube workflow (ax) is a pure
`get_by_role` chain except the video link, e.g. `get_by_role("combobox", name="Search", exact=True)`
→ `get_by_role("button", name="Search", exact=True)` → link by name → `press k` (the play button
was covered by an ad overlay at explore time, so the agent used the keyboard shortcut — and that
is what was compiled and replayed).


## 8. Recommendation and honest limitations

**Switch the default to `ax`.** The hybrid accessibility backend is strictly better on the one
axis that matters for a *compiler* whose output is `get_by_role` chains: element identity. Its
names are the browser's own accessible names, so a compiled `get_by_role(name=…, exact=True)`
resolves to exactly one element far more often than the DOM heuristic's guess (Reddit 51 → 87 %,
Twitch 49 → 79 %, todomvc 75 → 100 %), and where names repeat it disambiguates with `.nth(k)`.
It names controls the heuristic cannot (radios/checkboxes labelled by following text, icon
buttons, `<select>` by its label). Observation size and token cost are within ±5 % of the DOM
walk; snapshot latency is higher on large pages (per-element `aria-ref` fact fetches) but still
a fraction of one LLM call. Iframe (same- and cross-origin) and open-shadow coverage match the
DOM walk because both lean on Playwright's frame stitching.

Keep `dom` as the fallback the session already performs automatically when the aria snapshot
raises, and keep the flag: `ax` depends on Playwright's `aria_snapshot(mode="ai")` (a semi-internal
API) and on `getEventListeners` via CDP, so a Playwright upgrade or a hostile page could regress it.
Flip the default in `Settings.observation` when the team is ready; this branch leaves it at `dom`
so nothing changes without a decision.

The end-to-end numbers (challenge, sweep) are **within noise between backends** — because at
Haiku's level the bottleneck is the model's planning (hallucinated "already submitted", scroll
hunting, custom-widget confusion), not the observation's element identity. The ax backend's
advantage is latent until the compiled artifact is *replayed*: a role+name locator survives a
page redesign that shifts DOM structure, where a css-path fallback does not. That is the whole
point for NetGent — the observation feeds a compiler, and the compiler's job is durable locators.

### Honest limitations

* **Poor ARIA hygiene.** The ax backend is only as good as the page's roles/names. A `<div onclick>`
  with no role and no text is invisible to the aria tree; we recover the common cases (cursor
  pointer with text, direct event listeners, `<summary>`, scrollables) via the DOM `extrasOnly`
  merge, but a genuinely unlabelled custom widget still has only a css-path locator, same as the
  DOM walk. The 21-form sweep is deliberately adversarial (Select2, MUI, contenteditable rich-text,
  RTL Arabic labels) and neither backend clears it — custom radios rendered as `<button>` that
  don't toggle on a plain click, and submits silently blocked by client-side validation, are model
  and widget problems, not observation problems.
* **Localized / duplicate names.** `get_by_role(name=…, exact=True)` is language- and
  whitespace-sensitive: an Arabic or emoji-laden name round-trips fine (it is the browser's own
  string) but is opaque to the model, and two truly identical controls are only separable by
  `.nth(k)`, which is positional and brittle if the page reorders them between explore and replay.
* **Canvas / pixel-only content.** Text drawn on a `<canvas>` (the challenge CAPTCHA) is in neither
  tree. That needs a vision input — an agent change, not an observation-backend one.
* **Cost on huge pages.** Per-element fact fetches make the ax snapshot ~2× slower than the DOM
  walk on 200+ element pages (still < 1 s). Batching the facts into one `evaluate` over all refs
  would remove this; left as future work.
* **Semi-internal API.** `aria_snapshot(mode="ai", boxes=True)` is not a stability-guaranteed
  surface. The parser is defensive and the session falls back to the DOM walk on any error, but a
  Playwright upgrade could change the YAML shape; the fixture-based parser tests would catch it.



---

# Hybrid text+vision — the same `ax` text observation plus a Set-of-Marks screenshot

**Flag:** `NETGENT_OBSERVATION=hybrid` (screenshot every step) or `hybrid_on_stuck` (screenshot
only once the agent has stalled); `--observation hybrid` on `netgent agent` / `generate`.
Action space unchanged: the model still answers with an element index that resolves to a
durable locator; the image is perception only. No coordinate actions were added (they would not
compile to replayable locators).

## H1. Prior art — what the vision-capable agents actually send (source read, paths cited)

Clones under `/tmp/ax-refs/` (browser-use 0.13.8, stagehand @ `a21633d`, skyvern @ `888348d`,
WebVoyager @ `5a78967`).

* **browser-use** — the LLM screenshot is a **clean, unannotated PNG**; the text list carries the
  indices. `AgentMessagePrompt.get_user_message` appends `ContentPartImageParam(data:image/png;
  base64…)` after the `<browser_state>` text (`browser_use/agent/prompts.py:444-474`). Two
  Set-of-Marks painters exist but neither reaches the model: a Pillow painter
  (`browser_use/browser/python_highlights.py:341-460`, labels = selector-map keys, DPR from
  `Page.getLayoutMetrics` `:474-489`, label above small boxes / inside big ones `:182-188`) is
  referenced nowhere else; the live-DOM overlay `add_highlights` (`browser/session.py:3165-3320`,
  `<div id="browser-use-debug-highlights">`, `z-index 2147483647`, `pointer-events:none`) is gated by
  `dom_highlight_elements=False` "only for debugging" (`browser/profile.py:687-690`) and is removed
  *before* the screenshot (`watchdogs/screenshot_watchdog.py:55-62`). `use_vision` defaults True,
  tri-state with `'auto'` (`agent/views.py:62`, `message_manager/service.py:461-478`); only the
  current step's screenshot is kept (`:450,474-475`); optional LANCZOS resize to `(1400, 850)` for
  Claude (`agent/service.py:244-249`). Indices are primary; x/y clicks are an opt-in fallback for a
  model allow-list, rescaled by the resize ratio (`agent/service.py:326-332`, `tools/service.py:610-627`).
  Notable: its system prompt still promises "bounding boxes around interactive elements" that the
  default configuration never draws (`system_prompts/system_prompt.md:21,65-67`).
* **Stagehand** — `observe()`/`act()` are **text-only** (the hybrid a11y outline, no image):
  `packages/extension/inference.ts:174-247`, `prompt.ts:179-185`. The only multimodal path is
  `extract({screenshot:true})` — a viewport PNG appended as a second content block
  (`services/extractService.ts:96-144`, `prompt.ts:102-105`), cache-bypassed because "cache keys
  contain DOM state, not screenshot pixels" (`:67-69`). No Set-of-Marks anywhere; the only overlays
  are a cosmetic cursor (`dom/locatorScripts/cursorOverlay.ts`) and privacy masks
  (`understudy/screenshotUtils.ts:188-215`). Screenshots can be taken in CSS pixels (`scale:"css"` →
  `1/devicePixelRatio`, `screenshotUtils.ts:41-59`) and the viewport is pinned with
  `Emulation.setDeviceMetricsOverride` (`page.ts:1404-1424`). `DOM.getNodeForLocation` maps a
  coordinate *into* the tree (`a11y/snapshot/coordinateResolver.ts:11,71`) — coordinates flow in, not
  images out. No CUA loop in the tree.
* **Skyvern** (phase-1 reading) — split, scrolled screenshots are paired with the `unique_id`-stamped
  HTML tree; `drawBoundingBoxes` is marked DEPRECATED (`webeye/scraper/domUtils.js:2712`,
  `scraper.py:265-268`): it too moved to clean screenshots + text ids.
* **WebVoyager** (the original web SoM) — one injected `markPage()` (`utils.py:46-175`): selects by
  tag/`onclick`/`cursor:pointer` (`:52-93`), keeps only rects whose centre `elementFromPoint` is the
  element or a descendant and clamps them to the viewport (`:58-76`), appends `position:fixed`
  `<div>`s with a dashed outline, `pointer-events:none`, `z-index 2147483647` and a numeric
  `<span>` at the top-left corner (`:131-165`), sends screenshot + `[3]: <button> "Search";` list
  (`:179-209`), and **removes the overlay divs before acting** (`run.py:384-389`). Same-document
  only: no iframe descent, no shadow DOM; indices are recomputed every step.
* **Magnitude** — its browser stack no longer exists in the repo (pivoted to a coding agent); not
  compared.

**What converged.** (1) Nobody ships a painted SoM to the model by default any more — browser-use
and Skyvern both deprecated theirs and send a clean screenshot with the indices in the text;
WebVoyager is the one that does paint, and it removes the marks before acting. (2) Everyone who
paints hit-tests with `elementFromPoint` at the box centre (WebVoyager) and scales by DPR
(browser-use). (3) Live-DOM overlays are treated as hazardous (removed before screenshot/action,
`pointer-events:none`, debug-only). Our renderer therefore paints on a PIL copy — never the page —
and verifies identity per mark with a composed-tree `elementFromPoint`.

## H2. What was built

* `agent/explore_agent/marks.py` — `marks_for` (viewport clip; only the elements the text list
  shows, from the shared `shown_elements()`), `layout_marks` (DPR scale, min 12px box for tiny
  targets, 9 candidate label slots chosen to avoid already-placed labels, largest boxes first so
  small ones win the front), `render_set_of_marks` (PIL overlay on a copy of the clean viewport PNG;
  per-index colour; **covered** marks drawn dotted with a dimmed label so the image and the text
  list keep the same index set while signalling "behind something").
* `BrowserSession.capture_viewport_png / viewport_size / mark_hits` — `mark_hits` resolves each
  shown element by its durable locator (nothing is stamped on the page), then ONE
  `elementFromPoint` evaluate per frame classifies the box centre as `hit` (the element, or its
  label/child/ancestor walking the **flat tree** through `assignedSlot`/shadow hosts), `covered`
  (a larger element on top: modal, backdrop, fixed header) or `miss`.
* `agent/llm.py` — `decide(..., image=)` builds one `HumanMessage` with a text block and an
  `image_url` data-URL block; `FakeLLM` ignores the image; `usage.images` counts sends.
* `graph.py` — `hybrid` renders every step; `hybrid_on_stuck` only once `no_progress ≥ 1`.
* Two locator fixes the identity check exposed (they affect *actions*, not just marks):
  `get_by_role/get_by_label` chains now end in `filter(visible=True)` (YouTube's collapsed drawer
  holds a DOM-first, zero-size twin of "Guide"/"Settings"), and `#id` anchors require the id to be
  unique in its root (YouTube reuses `id="button"`). Elements with no addressable candidate are no
  longer listed. A `fill` on `input[date|time]` normalises `mm/dd/yyyy` / 12-hour values — the
  vision model reads the picker's *displayed* format off the screenshot.

## H3. Set-of-Marks geometry check (`evals/som_check.py`)

| site | viewport | listed | in view | marks | identity % | hit | covered | miss | label overlaps | unmarked in view | render ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| youtube | 1280x800 | 12 | 12 | 12 | 100.0 | 12 | 0 | 0 | 0 | 0 | 51.0 |
| twitch | 1280x800 | 60 | 45 | 45 | 97.8 | 41 | 3 | 1 | 0 | 0 | 53.3 |
| reddit | 1280x800 | 60 | 52 | 52 | 98.1 | 46 | 5 | 1 | 0 | 0 | 41.5 |
| forms | 1280x800 | 60 | 27 | 27 | 100.0 | 26 | 1 | 0 | 0 | 0 | 22.6 |
| challenge | 1280x800 | 41 | 14 | 14 | 92.9 | 13 | 0 | 1 | 0 | 0 | 24.9 |
| fixed+modal | 1280x800 | 7 | 6 | 6 | 100.0 | 2 | 4 | 0 | 0 | 0 | 47.8 |
| rtl | 1280x800 | 4 | 4 | 4 | 100.0 | 4 | 0 | 0 | 0 | 0 | 12.0 |
| canvas | 1280x800 | 2 | 2 | 2 | 100.0 | 2 | 0 | 0 | 0 | 0 | 15.9 |
| forms-mobile | 390x844 | 60 | 13 | 13 | 92.3 | 12 | 0 | 1 | 0 | 0 | 8.8 |

`identity %` = (hit + covered) / marks. `covered` is the correct outcome for an element under an
overlay: on `fixed+modal` the four buttons behind the backdrop are drawn hollow and the two modal
buttons solid (100 %); on Reddit the login interstitial covers 5. The two residual misses are a
link badge that overhangs its card (challenge) and one mobile-layout control (forms-mobile).
Before the flat-tree walk Reddit scored 45 % (every shadow-DOM control "missed" because
`document.elementFromPoint` returns the shadow host); before the unique-id rule YouTube's
"Guide" resolved to its hidden twin. Render cost: 10–60 ms; the per-step identity check is one
evaluate per frame.

Image cost (`evals/results/observation_ab_vision.md`): a 1280×800 viewport PNG is 28–660 KB and
≈1,365 Anthropic image tokens regardless of content (tokens scale with pixel area, ≈ w·h/750) —
i.e. +1.4k tokens on top of a 200–1,400-token text observation, per step.

## H4. Matrix — ax vs hybrid vs hybrid_on_stuck (Haiku, same prompts and budgets as §5–§7)

Same harness, prompts and budgets as §5–§7 (`evals/stress_ab.py … --runs 3`, Haiku 4.5, challenge
`max_steps=60`, sweep `max_steps_per_form=30`, `retries=1`). 3 runs per cell; mean with per-run
values. Token columns are the API's reported usage; `image tokens` = images × 1,365 (1280×800) and
is already included in the per-step cost. Prices: Haiku list ($1/M in, $5/M out).

| task | backend | result mean (per run) | LLM calls | text tokens | image tokens | output tokens | wall | cost/run | cost/step |
|---|---|---|---|---|---|---|---|---|---|
| challenge | ax | **13.3**/15 (13, 13, 14) | 32 | 118,478 | 0 (0 imgs) | 3,520 | 64s | $0.136 | $0.43¢ |
| challenge | hybrid | **15.0**/15 (15, 15, 15) | 33 | 124,013 | 45,500 (33 imgs) | 3,600 | 82s | $0.188 | $0.56¢ |
| challenge | hybrid_on_stuck | **12.7**/15 (15, 10, 13) | 31 | 114,889 | 10,920 (8 imgs) | 3,276 | 61s | $0.142 | $0.46¢ |
| sweep | ax | **5.3**/21 (5, 6, 5) | 388 | 1,195,296 | 0 (0 imgs) | 39,613 | 1219s | $1.393 | $0.36¢ |
| sweep | hybrid | **3.3**/21 (4, 3, 3) | 402 | 1,232,036 | 548,275 (402 imgs) | 41,737 | 1336s | $1.989 | $0.50¢ |
| sweep | hybrid_on_stuck | **5.0**/21 (5, 5, 5) | 392 | 1,194,828 | 261,625 (192 imgs) | 40,520 | 1273s | $1.659 | $0.42¢ |

Per-step wall clock: ax ≈2.0 s, hybrid ≈2.5 s (screenshot + identity check + larger request),
hybrid_on_stuck ≈2.1 s. `challenge` = cards cleared of 15 (the page's own counter says /17);
`sweep` = forms verified submitted of 21.

Reading it:

* **Challenge — hybrid 15/15 ×3 vs ax 13.3.** The two cards ax misses are exactly the ones that
  need pixels or spatial confirmation: `canvas-captcha` (text only in a `<canvas>`, read off the
  screenshot and typed via `fill` — every hybrid run) and the iframe slider that the text-only
  agent intermittently skipped. +38 % tokens per step, +28 % wall.
* **Sweep — no vision benefit (ax 5.3, hybrid_on_stuck 5.0, hybrid 3.3).** All three are inside the
  run-to-run band measured for ax alone in §5 (4–11). The forms fail on silent validation and
  custom widgets a picture does not explain, and the picture adds a failure of its own: the model
  read `mm/dd/yyyy` off the date picker and sent it (six times, then stuck) until the dispatch
  normaliser was added. +43 % tokens per step for hybrid, +17 % for on-stuck.
* **hybrid_on_stuck** sends an image on ~25 % of steps (8 of 31 on the challenge, 192 of 392 in the
  sweep — "stuck" is frequent on the forms) and is the most variable cell (15/10/13): the image
  arrives after the agent has already committed to a wrong reading.


### Generate + validate (YouTube, Twitch) — ax vs hybrid, same session window

| site | backend | validated | edges | LLM calls | text tokens | image tokens | output tokens |
|---|---|---|---|---|---|---|---|
| youtube | ax | ✓ | 6 | 6 | 17,436 | 0 (0 imgs) | 608 |
| youtube | hybrid | ✓ | 7 | 9 | 32,856 | 12,285 (9 imgs) | 893 |
| twitch | ax | ✓ | 9 | 14 | 53,844 | 0 (0 imgs) | 1,637 |
| twitch | hybrid | ✓ | 7 | 7 | 22,924 | 9,555 (7 imgs) | 703 |

All four validated with zero-LLM replay. Two earlier attempts (both backends) failed replay at the
same edge — the compiled `get_by_role("link", name="…NEW Funny ${query} 2026…", exact=True)`: the
compiler had parameterised the sample value inside an accessible name and `exact=True` (added by
the ax backend) then rejected the replay value's different casing. Fixed in the compiler (a name
carrying `${param}` drops `exact`); it affected every backend equally and is covered by a unit test.
The hybrid runs cost more input tokens per call (the screenshot) but did not take fewer steps here.


## H5. Recommendation

**Default: `ax`. Offer `hybrid` as an opt-in for tasks that need pixels.** The evidence splits
cleanly by what the task demands:

* Where perception is the bottleneck, vision is decisive. The challenge game went from 13.3/15
  (ax, 3 runs, never the canvas card) to **15/15 on every hybrid run** — the CAPTCHA text is read
  off the screenshot and typed through the ordinary `fill` action, and the slider/iframe cards
  that ax skipped intermittently were never skipped with the picture in front of the model.
* Where the bottleneck is widget semantics and validation (the 21-form sweep), the picture does
  not help and slightly hurts: ax 5.3, hybrid_on_stuck 5.0, hybrid 3.3 out of 21
  (3 runs each, all within the run-to-run noise we measured earlier for ax alone). The sweep's
  failures are silent client-side validation and custom widgets that a screenshot does not
  explain; and vision introduces a new failure of its own — the model trusts the *displayed*
  format (`mm/dd/yyyy`) over the programmatic one, which we now normalise at dispatch.
* Cost: a 1280×800 screenshot is ≈1,365 image tokens per step on top of a 2–4k text observation
  — **+40–45 % input tokens per step** (challenge 0.43¢ → 0.56¢ per step; sweep ≈ +50 %), plus
  ~25 % wall time (screenshot + identity check). `hybrid_on_stuck` sends an image on roughly a
  quarter of the steps and costs ≈ +10 %, but its results are the most variable of the three
  (challenge 15/10/13): the image arrives only after the agent has already committed to a wrong
  reading, and a single late picture rarely undoes that.
* `generate` validated for both backends on YouTube and Twitch; step counts are within noise.

So: keep `ax` (text-only hybrid AX+DOM) as the default observation for the compile-time agent —
it delivers the locator-durability win of §4 at no image cost — and expose `hybrid` for workloads
with pixel-only information (canvas, image captchas, charts, icon-only toolbars). Do not make
`hybrid_on_stuck` the default: it buys little and adds variance. The Set-of-Marks renderer is
correct enough to be the *only* way we ever attach pictures (identity ≥92 % on every page checked,
100 % on five, 0 unmarked, 0 label overlaps; never touches the live DOM), so switching a task to
`hybrid` is a one-flag decision with no change to the action space or the compiled artifacts.

