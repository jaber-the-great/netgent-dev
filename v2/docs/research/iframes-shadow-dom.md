# Iframes and shadow DOM: how browser agents observe and act across boundaries

*Source-verified survey, 2026-08-25. Repos read at the SHAs cited inline; all NetGent claims
re-measured against real Chromium (see [Verification notes](#verification-notes)).*

## Question

NetGent v2 compiles a browser workflow into an NFA whose transitions carry **durable, declarative
Playwright locator chains** — a list of `{fn, args, kwargs}` steps drawn from a fixed whitelist
(`get_by_role`, `get_by_text`, `get_by_label`, `get_by_placeholder`, `get_by_test_id`,
`get_by_title`, `get_by_alt_text`, `locator`, `frame_locator`, `filter`, `nth`) and replayed by
reflection with **zero LLM** (`v2/src/netgent/schema/actions.py:15-44`). Everything downstream of
compile time is a pure function of that artifact.

Two DOM features break the assumption that a page is one tree you can name a node in:

1. **Iframes** partition the page into browsing contexts. Cross-origin ones are, under Chromium's
   site isolation, *separate processes and separate CDP targets*. In-page JavaScript cannot read
   across the boundary at all.
2. **Shadow roots** partition a document into encapsulated subtrees. `open` roots are reachable
   from page JS; `closed` roots are, by design, reachable only by the component that created them.

So: what do the tools that do this for a living actually do — when **observing** (build a picture
of the page for a model) and, harder, when **acting** (click / fill / select / press / upload /
scroll)? What survives serialization into an artifact that must replay weeks later? And where does
NetGent actually stand today?

The short version: **NetGent's frame story is already among the best of the systems surveyed**
(chained `frame_locator`, verified working through two cross-origin hops, into shadow-hosted
iframes, and into shadow roots inside cross-origin iframes). The gaps are elsewhere — closed shadow
roots, ambiguous shadow-pierced `#id` selectors, frame-blind triggers and parameter extraction,
frame-blind scrolling, and an `x`/`y` coordinate space that only half exists.

---

## The mechanics

### Frames in Chromium

A page is a tree of **frames** (browsing contexts). Chromium's *site isolation* puts cross-site
frames in their own renderer process — an **out-of-process iframe (OOPIF)**. Over CDP an OOPIF is a
separate **target** with its own session, reached by `Target.setAutoAttach {autoAttach: true,
waitForDebuggerOnStart: true, flatten: true}` [Playwright `chromium/crPage.ts:539`,
`crBrowser.ts:84,89`]. Playwright creates a `FrameSession` per attached iframe target, keyed by
targetId (targetId == frameId), and `_sessionForFrame` walks up parent frames until it finds one —
so same-process frames share their ancestor's session and OOPIFs get their own
[`crPage.ts:144-153, 733-753`].

Consequences that matter:

- **`page.frames` is origin-blind.** Playwright learns frames from `Page.frameAttached` /
  `frameNavigated`, not from the DOM, so a cross-origin child, an `about:blank` child and a
  `srcdoc` child all appear as ordinary `Frame` objects. Verified: a 3-level page with one
  cross-origin, one `srcdoc` and one `about:blank` iframe yields 4 frames reporting
  `http://…`, `about:srcdoc`, `about:blank`. `frame_element()` resolves all of them — including
  when the host `<iframe>` lives inside a **closed** shadow root, because it goes through CDP
  rather than the DOM [Playwright `tests/page/frame-frame-element.spec.ts:59-77`].
- **`page.frame({url})` is useless for `about:blank` / `srcdoc` / sandboxed frames** — several
  frames report the same URL. Use `frame_locator` or `frame_element()`.
- **Injected page JS can never cross an origin boundary.** `iframe.contentDocument` throws. Every
  serious tool therefore drives the walk *per frame from outside* (Playwright/CDP) rather than
  recursing in JS.
- **Coordinates:** CDP `DOM.getContentQuads` already returns **main-frame** coordinates for
  same-process frames, so Playwright adds a `{0,0}` offset there; for OOPIFs it adds the frame
  element's own box [`crPage.ts:1104-1132, 1147-1160`]. A CSS `transform` anywhere on the iframe
  ancestor chain degrades this to `'transformed'` and Playwright **skips the hit-point pre-check**
  entirely, relying on the post-dispatch event interceptor [`dom.ts:933-941`].
- **Detach is normal, not exceptional.** Ad and analytics iframes attach and detach constantly. A
  detached frame raises `Frame was detached` / `Execution context was destroyed` and is removed
  from `page.frames` (verified). browser-use lost *entire* observations to this until they added
  `return_exceptions=True` to their per-frame AX gather [browser-use issue #4778,
  `dom/service.py:384-397`].

### Shadow roots

`element.attachShadow({mode})` creates a root. The **only** difference between `open` and `closed`
is that the `shadowRoot` *IDL getter* returns `null` for closed roots — the DOM internal slot
"element's shadow root" is populated either way. That single fact explains almost everything below:

- Every tool whose traversal reads `element.shadowRoot` sees open roots and is blind to closed ones.
  That is Playwright's selector engines, Puppeteer's `pierce/`, Cypress, WebdriverIO's `>>>`,
  Skyvern's `domUtils.js`, nanobrowser's `buildDomTree.js`.
- Every tool that reads the *internal slot* through a lower-level channel sees both. That is CDP's
  DOM domain (`pierce: true` returns nodes with `shadowRootType: 'closed'` — confirmed empirically:
  present with `pierce=true`, absent with `pierce=false`), the WebDriver classic
  `Get Element Shadow Root` endpoint (the spec says "let shadow root be element's shadow root" and
  the word *closed* appears nowhere; WPT parametrises the test over `["open","closed"]`), and
  WebDriver BiDi node serialization.
- **Slots** matter for accessible names. Playwright's role/accname engine follows
  `assignedNodes()` and treats unslotted light children as aria-hidden
  [`roleUtils.ts:344-346, 1021, 1046-1064`]. Its *text* engine does not — it walks light children
  then appends shadow text [`selectorUtils.ts:78-91`]. Skyvern handles neither.
- **Declarative shadow DOM** (`<template shadowrootmode="closed">`) never calls `attachShadow`, so
  every monkey-patch workaround silently misses it. Only the CDP/WebDriver paths see it.

### What pierces what

Verified against Chromium via Playwright 1.62.0 / Patchright 1.62.1 unless marked *[src]*.

| Engine / mechanism | Open shadow | Closed shadow | Same-origin iframe | Cross-origin iframe |
|---|---|---|---|---|
| Playwright CSS (`locator("…")`) | **yes** — incl. `>`, `+`, `~`, `:has()`, `:nth-match()` *[src `selectorEvaluator.ts:265-374`]* | no | no — needs `frame_locator` | no — needs `frame_locator` |
| Playwright `css:light=` / `:light()` | no (by design) | no | no | no |
| Playwright `get_by_role` / `text=` / testid | **yes** | no | no | no |
| Playwright XPath | **no** (`document.evaluate` cannot cross) | no | no | no |
| Playwright `frame_locator(...)` chain | n/a | n/a | **yes** | **yes** (verified 2 hops) |
| `>>>` in Playwright | **not a selector** — silently matches 0 | no | no | no |
| **Patchright** locator (CDP `DOM.describeNode{pierce}` + `resolveNode`) | yes | **yes** | via `frame_locator` | via `frame_locator` |
| Puppeteer `pierce/` and `>>>` / `>>>>` | yes | no | no | no |
| WebDriver classic `Get Element Shadow Root` | yes | **yes** *[spec + WPT]* | via `switch_to.frame` | via `switch_to.frame` |
| CDP `DOM.getDocument(pierce=true)` | yes | **yes** (`shadowRootType:'closed'`) | yes (`contentDocument`) | **no** — needs a per-target session |
| CDP `Accessibility.getFullAXTree` | yes | yes | per-frame `frameId` | per-target session |
| CDP `Page.captureScreenshot` | yes | **yes** | yes | **yes** (composited) |
| CDP `Input.dispatchMouseEvent(x,y)` | yes | **yes** | yes | **yes** (compositor hit-test) |
| In-page JS (`contentDocument`, `el.shadowRoot`) | yes | no | yes | **no** (SecurityError) |
| Chrome extension content script (`all_frames`) + `chrome.dom.openOrClosedShadowRoot` | yes | **yes** | yes | **yes** (one script per frame) |

Two rows carry most of the design pressure. **Coordinates and screenshots cross every boundary in
one call** — which is why vision agents sidestep this entire document. And **a coordinate is not a
durable locator**, which is why NetGent cannot.

### Three ways to act

1. **Locator / selector** (Playwright, Stagehand, Skyvern, NetGent). Re-resolved every attempt,
   survives re-render, serializes cleanly. Blind wherever its engine is blind.
2. **Node handle** (browser-use, agent-browser, nanobrowser): CDP `backendNodeId` +
   `sessionId` → `DOM.scrollIntoViewIfNeeded` → `getContentQuads` → `Input.dispatchMouseEvent` on
   *that session*. Crosses everything CDP crosses, but a `backendNodeId` is meaningless outside the
   session that minted it, so nothing here serializes.
3. **Coordinates** (lumen, magnitude): `Input.dispatchMouseEvent{x,y}`. Crosses *everything* —
   verified: a coordinate click landed inside a closed shadow root whose element
   `page.locator()` could not find, and inside an OOPIF. Keyboard follows, because a real click
   moves focus into the frame and page-level `Input.dispatchKeyEvent` goes to the focused element
   (verified). But nothing survives a layout change.

---

## Per-project findings

Tags: **[V]** = verified by reading source at the cited path/line; **[2H]** = secondhand (issue,
release note, or documented Chromium behaviour); **[M]** = measured by me in this session.

### Playwright — `microsoft/playwright` @ `036533f7` (2026-08-25, v1.63.0-next)

**Frames are string surgery, resolved server-side.** `frameLocator()` concatenates
`<frameSel> >> internal:control=enter-frame >> <childSel>` [V `client/locator.ts:447-451`];
`FrameSelectors._resolveChainedSelector` then walks the chunks — query in the current frame, assert
the result is an `IFRAME`/`FRAME`, switch context via `delegate.getContentFrame(element)`
[V `server/frameSelectors.ts:152-180`, `isomorphic/selectorParser.ts:94-145`]. Confirmed: a chained
locator stringifies to `#outer >> internal:control=enter-frame >> #inner >> … >> internal:role=button` [M].

**Every retry re-resolves the whole chain, frame steps included.**
`Frame._retryWithProgressIfNotConnected` calls `selectors.callOnSelectorHandle` from scratch each
iteration [V `server/frames.ts:1201-1252`]. Measured: a `frame_locator("#d2").locator("#ki")` chain
built *before* the frame re-navigated still filled correctly *after* [M]. This is the single most
important property for NetGent — our stored chains are self-healing across frame churn for free.
The cost is O(frames) CDP round-trips per retry.

**Actionability across frames.** `_checkFrameIsHitTarget` walks up `parentFrame()` collecting each
`frameElement()` box plus `describeIFrameStyle` (border/padding, or `'transformed'`), then top-down
asserts each parent's hit target *is* the child's frame element [V `server/dom.ts:927-961`].
`expectHitTarget` builds the shadow-root chain **bottom-up** — "Go from the bottom to the top to make
it work with closed shadow roots" [V `injectedScript.ts:996-1010`]. Note the asymmetry: Playwright can
hit-test *into* a closed root it already has a handle for, but cannot *find* one.

**Keyboard is structurally frame-decoupled.** Focus is in-page `element.focus()` in the target
frame's utility world [V `dom.ts:772-774`]; keys are `Input.dispatchKeyEvent` on the **page-level**
session [V `crPage.ts:99`, `crInput.ts:61,78`]. Nothing re-asserts the focused frame in between.
In practice it works — measured: click an input in a cross-origin frame, then `page.keyboard.type`,
and the text lands in the frame; focus the outer input and it lands outside [M] — but any focus
steal between the two sends keys to the wrong frame.

`setInputFiles` is OOPIF-safe (`DOM.setFileInputFiles` on the owning frame's session,
[V `dom.ts:726-764`]); `selectOption` is pure in-page JS and therefore transparent to both
boundaries [V `dom.ts:577-602`]. Documented limits: *"Closed-mode shadow roots are not supported"*
and *"Locating by XPath does not pierce shadow roots"* [V `docs/src/locators.md:702-704`].
Composite locators cannot contain frame steps [V `frameSelectors.ts:128-135`].

**`Locator.normalize()` is the sleeper feature.** `Frame.resolveSelector` resolves the locator,
generates a selector for the element via `generateSelectorSimple`, then walks up
`parentFrame()` generating one selector per `<iframe>` element and joins them with
`>> internal:control=enter-frame >>` [V `server/frames.ts:1312-1339`; generator
`injected/selectorGenerator.ts:78-117`, which climbs via `parentElementOrShadowHost` and therefore
handles shadow DOM]. It exists in the Playwright we already ship (1.62.0) [M]. Measured on a
shadow-DOM button inside a cross-origin iframe, it returns
`iframe[name="payframe"] >> internal:control=enter-frame >> internal:testid=[data-testid="deepbtn"s]`
— exactly the shape of a NetGent locator chain [M]. This is Playwright handing us a
frame-aware, shadow-aware, role/testid-preferring selector generator for free.

### Patchright — `Kaliiiiiiiiii-Vinyzu/patchright` @ `2290f121` (2026-08-19, tracks PW 1.62.1)

**Patchright reaches closed shadow roots, and NetGent already uses Patchright by default.** No
`attachShadow` override. It replaces the query-resolution loop: per selector part, per scope,
`DOM.describeNode {objectId, depth:-1, pierce:true}` → recursively collect
`shadowRoot.shadowRootType === "closed"` backendNodeIds (skipping `IFRAME` subtrees) →
`DOM.resolveNode` → use the handle as the scope for a normal `injected.querySelectorAll`
[V `driver_patches/frameSelectorsPatch.ts:150-280`]. XPath inside a closed root is emulated by
serializing `innerHTML`, re-parsing with `DOMParser`, and mapping the result index back
[V `XPathSelectorEnginePatch.ts:17-53`].

Measured end-to-end on a `{mode:'closed'}` root served over HTTP: `page.locator("#ci").count()` = 1
and `get_by_role("button", name="Closed Submit").count()` = 1 under Patchright, **0** under plain
Playwright; `fill`, `click`, `press`, `type` and a role-click all succeeded, and the effect landed
inside the closed root [M]. One earlier run saw an intermittent `fill` timeout at 3 s — the per-part
CDP walk is slower than the injected-script path, so budget bigger timeouts.

**Two Patchright behaviours that bite our snapshot.** (a) `page.evaluate` / `frame.evaluate` default
to `isolated_context=True` — a real isolated world that shares the DOM but *not* the JS global.
Measured: an `add_init_script` hook installed on `window` is `undefined` from the default
`evaluate`, and visible only with `isolated_context=False` [M]. That kwarg does not exist on plain
Playwright, so any code depending on it must be feature-gated. (b) Patchright injects init scripts
by **rewriting HTML responses through Playwright routes**, so `add_init_script` does nothing for
`set_content` / `data:` URLs [V README "Init Script Shenanigans"; M — the hook was missing after
`set_content` and present after `goto`]. Stagehand documents the same constraint from the other
side: *"Closed roots require a navigated page."*

### browser-use — @ `9a2db2d2` (2026-08-24, v0.13.8)

Pure CDP (`cdp-use`); Playwright was removed in v0.6.0 [V `pyproject.toml:42`]. Observation is four
parallel CDP calls per target — `DOMSnapshot.captureSnapshot`, `DOM.getDocument(depth=-1,
pierce=True)`, per-frame `Accessibility.getFullAXTree(frameId=…)`, `Page.getLayoutMetrics`
[V `dom/service.py:571-621`]. **Closed roots are pierced and surfaced to the model** as literal
`Open Shadow` / `Closed Shadow` markers [V `dom/serializer/serializer.py:1029-1080`].

OOPIFs are detected *by absence* — `nodeName == 'IFRAME' and contentDocument is None`, under the
comment `# TODO: hacky way to disable cross origin iframes for now` [V `dom/service.py:962-964`] —
then the whole four-call capture recurses on the child target with a threaded frame offset
[V `:1047-1067`]. The offset accumulator is worth stealing: an `HTML` node with a `frameId`
**subtracts** its `scrollRects`, an `IFRAME` node **adds** its `bounds.x/y` [V `:876-897`].

Acting picks the session with a five-tier fallback (`node.session_id` → `frame_id` → `target_id` →
focus → main) because "backend_node_id is only valid in the session where the DOM was captured"
[V `session.py:3954-4010`], then `scrollIntoViewIfNeeded` → largest viewport-intersecting quad →
occlusion probe → `Input.dispatchMouseEvent`. The occlusion probe uses
`document.elementFromPoint` + `Node.contains()`, neither of which crosses a shadow boundary — so
**shadow-DOM elements systematically read as occluded and fall through to a JS `.click()`**
[V `default_action_watchdog.py:598-670, 880-895`], losing trusted events.

Their durable-selector story is the cautionary tale. `EnhancedDOMTreeNode.xpath` *documents* that it
stops at shadow boundaries but the code `continue`s straight through them, producing an XPath
`document.evaluate` can never resolve; and `frame_id` is `None` for ordinary elements inside an
iframe [V `dom/views.py:492-514`, `service.py:857`]. Filed as #3820 "urgent deal-breaker", **still
unfixed** [2H]. Every substantive iframe/shadow issue in the tracker is closed — #295 nested
iframes, #443 payment iframes with no bounding box, #1998 shadow clicks reporting success while
nothing happened, #2336 three-deep *open* roots missed, #2715 self-referencing iframe hang,
#3382 could not return to the main frame after filling a Stripe iframe [2H].

### Stagehand — `browserbase/stagehand` @ `d49d643c` (2026-08-25, v4)

Three eras, and the current one matters: v2 (`lib/`) was a Playwright wrapper with **no iframe
descent and no shadow DOM at all** (`frameLocator` appears nowhere in v2.2.0); v3 replaced Playwright
with their own CDP driver (`understudy/`); v4 runs it as a Chrome extension [V].

Their cross-boundary representation is the most directly transferable idea in this survey: **one
flat XPath string with two separators**. A normal step is `/`; a **shadow hop is `//`**; an iframe
is just another step whose child document continues the same string:

```
/html/body/shadow-host//section/iframe/html/body/main/section[1]/form/div/div[1]/input
```
[V `packages/core/examples/deep-locator.ts:12`, `shadow-root.ts:10`]

At act time `resolveDeepXPathTarget` splits the steps on `IFRAME_STEP_RE = /^i?frame(?:\[\d+])?$/i`,
emits one `frameLocator()` per hop, and keeps the tail as an in-frame xpath
[V `understudy/deepLocator.ts:240-270`]. The shadow hops survive into the tail, where a *hand-written
composed-tree XPath engine in page JS* evaluates them [V `dom/locatorScripts/xpathResolver.ts:32-66,
240-329`].

Overloading `//` is also their biggest open bug: issue #2693 (OPEN) reports that once any shadow root
exists, their engine replaces `document.evaluate` page-wide and `//div[2]`, `[last()]` change meaning
— clicking the wrong element with **no error** [2H]. #2324 (OPEN): a trailing `iframe[n]` is
mis-flushed into a frame hop, breaking cross-origin clicks [2H].

Cross-origin is handled by *forcing* it: they launch with `--site-per-process` so every cross-origin
iframe is an OOPIF, then `Target.setAutoAttach{flatten:true}` and adopt each child session
[V `launch/local.ts:15`, `understudy/cdp.ts:136-138`]. Frame↔element bridging is CDP
`DOM.getFrameOwner` on the parent's session, whose `backendNodeId` gives the host `<iframe>`'s XPath
prefix [V `capture.ts:742-803`]. Closed roots: v3 monkey-patched `attachShadow` *and* shipped
`rerenderMissingShadowHosts()`, which **clones and replaces** live custom elements to re-run the
constructor under the hook [V `dom/rerenderMissingShadows.runtime.ts:20-27`] — aggressive and
destructive. v4 deleted the patch in favour of `chrome.dom.openOrClosedShadowRoot` plus a
**capability flag** `__stagehandLocatorWorld = {kind: "extension"|"cdp-fallback", closedShadowRoots}`
[V `content-script.ts:38-49`]. There is **no JS-click fallback**: clicks are
`DOM.scrollIntoViewIfNeeded` → `getBoxModel` → `Input.dispatchMouseEvent`, trusted events only, and
the only recovery is LLM self-heal [V `understudy/locator.ts:385-449`, `handlers/actHandler.ts:334-419`].
`press` is frame-blind — it ignores the locator and keys the main session [V `actHandlerUtils.ts:279-292`].

### Skyvern — `Skyvern-AI/skyvern` @ `10fd44bc` (2026-08-24)

Python drives one `evaluate` per frame; the injected `domUtils.js` **never** touches
`contentDocument` (zero hits) [V]. Each frame's walk stamps a `unique_id` attribute **into the live
DOM** — `element.setAttribute("unique_id", element_id)` [V `domUtils.js:2182-2184`] — and that id is
the only handle the LLM ever sees. Resolution reconstructs the frame chain by chasing each frame
node's own stamped id up to `"main.frame"`, doing `frame_locator("[unique_id='…']")` per hop and then
`locator("[unique_id='…']")` for the element [V `webeye/utils/dom.py:111-166`]. Open shadow roots come
free from Playwright's CSS piercing; there is no shadow branch in the resolver. Their `domUtils.js`
reads `element.shadowRoot` (open only), has **no `assignedNodes` handling**, and carries
`// FIXME: xpath won't work when the element is in shadow DOM` [V `domUtils.js:2626-2630`].

Their click fallback ladder is the most elaborate surveyed: Playwright `click` → label `for=`/child
input at `position={0,0}` → click the blocking element → `bounding_box` + `page.mouse.click(x,y)`
("bypasses actionability while still dispatching a real mouse event") → `evaluate(el => el.click())`
gated on a mutation observer so a no-op is not mistaken for success
[V `handler.py:8832, 9096-9103, 9214-9219`].

**The stamping trick judged for our use case.** It is an excellent *runtime* index and a terrible
*artifact* value: the id is minted by a global mutation counter seeded by walk order and frame index
[V `domUtils.js:1898-1928`], so it is non-deterministic across sessions; it dies on reload; it is a
fingerprinting surface; and a `cloneNode` re-render duplicates it — their own code warns that "a
non-strict click would land on the first match" [V `taskv3/tools.py:359-361`]. Skyvern knows this,
and their answer is the part worth copying: cross-session identity is a **content hash**
(`hash_element` = SHA-256 of the element dict with `id`, `rect`, `frame_index` removed), and cached
replay resolves hash → element ids, aborting unless there is **exactly one** match
[V `scraper.py:177-188`, `actions/caching.py:79-145`].

### playwright-mcp / agent-browser — aria-refs, and why they cannot be stored

playwright-mcp's source now lives inside the Playwright monorepo [V `src/README.md:3`]. Refs are
minted in `computeAriaRef` as an element expando `_ariaRef`, invalidated whenever role or accessible
name changes, from a module-level counter [V `injected/ariaSnapshot.ts:38, 220-233`]; the frame half is
`refPrefix = 'f' + this._frameSeq` [V `injectedScript.ts:327`], giving `e12` / `f3e12`. Resolution is a
one-line engine — look the ref up in `_lastAriaSnapshotForQuery`, return it only if `isConnected`
[V `injectedScript.ts:737-742`]. So a ref is **a cursor into one snapshot of one frame**: dead if not
from the newest snapshot, dead if role/name changed, dead if the frame re-navigated (Playwright
re-numbers the main frame on cross-document navigation precisely so stale refs cannot alias
[V `frames.ts:274-278`]). The stale-ref strategy is the error string *"Try capturing new snapshot"*
[V `tools/backend/tab.ts:498-518`]. Acting on a cross-frame ref does **not** use chained `frameLocator`:
the server parses `f(\d+)e\d+` and jumps to the `Frame` with that `seq`
[V `server/frameSelectors.ts:109-121`]. The aria walk pierces open shadow roots and follows
`assignedNodes()` [V `ariaSnapshot.ts:172-185`]; closed roots are simply absent.

Vercel's **agent-browser** (@ `8d5b08dd`, v0.35.0) is a native Rust CDP client, not a Playwright
wrapper. Its refs are flat `e{N}` with the frame stored *beside* the ref in
`RefEntry {backend_node_id, role, name, nth, selector, frame_id}` [V `native/element.rs:8-16`], and
resolution is materially stronger than aria-ref: try the cached `backendNodeId`, and on failure
**re-query the AX tree by role + name + nth** [V `element.rs:299-372`]. That is a self-healing,
semantically-keyed reference — the right idea, though it still only expands **one** level of iframe
nesting [V `snapshot.rs:505-509`] and has no ref→durable-locator conversion at all.

The lesson for NetGent is sharp: **do not store refs; convert them at capture time.**
playwright-mcp already does exactly this on every action — `tab.targetLocator` returns
`{locator, resolved, selector}` and persists the *resolved* one [V `tools/backend/snapshot.ts:75-81`],
and exposes it as `browser_generate_locator`. Their own test asserts
`page.locator('aria-ref=f4e2').normalize()` →
`locator('iframe[name="2frames"]').contentFrame().locator('iframe[name="dos"]').contentFrame().getByText("Hi, I'm frame")`
[V `tests/page/page-aria-snapshot-ai.spec.ts:130-133`].

### Vision / coordinate agents — lumen, magnitude

Both are genuinely coordinate-only: lumen's entire action union is `click{x,y}`, `scroll{x,y,…}`,
`hover{x,y}` with no selector variant [V `lumen/src/types.ts:42-56`]; magnitude takes `{x,y}` for
every action [V `harness.ts:184-201`]. Transport is `Input.dispatchMouseEvent` (lumen) or
`page.mouse.click` (magnitude, the same thing one layer up). Magnitude's abandoned alternative shows
the mechanic is deliberate: a commented-out `elementFromPoint` + synthetic `MouseEvent` block annotated
*"We can't set isTrusted, the browser forces it to false"* [V `harness.ts:243-271`]. Verified
independently: a coordinate click landed inside a closed shadow root that `page.locator()` could not
see, and inside an OOPIF; page-level `dispatchKeyEvent` then reached the focused in-frame input; and a
single `Page.captureScreenshot` composited both [M, sub-agent].

What they lose is exactly what NetGent needs. lumen's `ActionCache` keys coordinate actions on a
`screenshotHash` whose `similarity()` is a stub doing exact SHA-256 equality
[V `loop/action-cache.ts:82-91`], so coordinate replay fires only on a byte-identical render — and
their durable `WorkflowMemory` stores **human-readable step descriptions, not coordinates**
[V `memory/workflow.ts:4-15`]. Neither supports file upload (zero `setInputFiles` hits), and magnitude
works around native `<select>` by replacing it in the DOM with clickable divs — main frame only
[V `web/scripts/shadowDOMInputAdapter.js:186-247`].

### Extension agents — nanobrowser

`all_frames: true` (but **no** `match_origin_as_fallback`, so `about:`/`srcdoc` frames are uncovered)
[V `chrome-extension/manifest.js:76-82`]. The payoff is architectural: Chrome injects a *separate*
content-script instance into every frame, each inside that frame's own origin, so the same-origin
policy never applies. Frames are addressed by
`chrome.scripting.executeScript({target: {tabId, frameIds: [id]}})`, enumerated via
`chrome.webNavigation.getAllFrames`, and only when the root frame fails to parse child iframes
[V `background/browser/dom/service.ts:138, 179, 243, 626`]. Highlights do manual
`parentIframe.getBoundingClientRect()` offset arithmetic [V `buildDomTree.js:181-204`].

Correcting a common belief: **nanobrowser does not use `chrome.dom.openOrClosedShadowRoot`** (zero
hits), and neither does current browser-use. nanobrowser force-opens at creation time —
`attachShadow(…{...options, mode: "open"})`, shipped inside its *anti-detection* bundle
[V `background/browser/page.ts:157-160`]. Stagehand v4 is the one that uses the extension API.

### Test-automation practice — Selenium, WebdriverIO, Cypress

**WebDriver classic already returns closed shadow roots**, with zero page tampering. The spec says
"let shadow root be element's shadow root" and never mentions mode; WPT parametrises
`find_element_from_shadow_root` over `["open","closed"]` [SPEC + WPT]. Selenium wired the endpoints
in 4.0.0-rc-1 (Java) / 4.1.0 (Python) [V `py/CHANGES:683`]. The cost is the rest of the model:
no CSS piercing anywhere (`grep -i pierc` over all bindings → nothing), so deep components need
`el.shadow_root.find_element(...).shadow_root` chains; and frames are a **mode switch**, not a
locator — a handle from frame A is `no such element` in frame B, because references are keyed to the
*current browsing context* [SPEC]. Cross-origin is a non-issue: *"WebDriver is not bound by the same
origin policy"* [SPEC].

`>>>` is a ghost: the 2014 spelling of `/deep/`, and the CSS spec's own Changes list reads *"Remove
the `>>>` (previously called `/deep/`) combinator."* Every `>>>` today is tool-level — WebdriverIO's is
an injected `query-selector-shadow-dom` walk gated on `if (el.shadowRoot)`, open only
[V `thirdParty/querySelectorShadowDom.ts:301`]; Puppeteer's is its own handler. In Playwright it is not
a selector at all and silently matches zero [M].

WebdriverIO's modern BiDi path is the most elegant closed-root handling seen: a `script.addPreloadScript`
preload wraps `attachShadow` but does **not** force open — it logs the host node, and BiDi's node
serialization carries `shadowRoot.sharedId` + `mode` regardless [V `session/shadowRoot.ts:54-55`,
`scripts/customElement.ts:30-40`]. It is disabled inside iframes and blind to declarative shadow DOM
[V `utils/index.ts:603-610`].

Cypress is open-only by construction, with a codified non-support test:
`cy.get('#in-shadow', {includeShadowDom: true}).should('not.exist')` for a closed root
[V `system-tests/.../shadow-dom.cy.js:7-10`]. Its cross-origin difficulty is architectural — it runs
*inside* the page, so the same-origin policy applies to **it**, hence `cy.origin()` and a per-origin
"spec bridge" iframe [V `cross-origin-testing.md:41`]. A CDP-based tool has none of these problems
because it is not a page. Their `getShadowElementFromPoint` recursion — re-hit-test the same viewport
coords against `ShadowRoot.elementFromPoint`, guarding on `nodeFromPoint === node` — is a portable
trick [V `dom/elements/shadow.ts:14-19`].

**The closed-root monkey-patch, done well and done badly.** Percy's is the safe shape: stash in a
`WeakMap`, leave `mode` untouched, expose only a probe function, and deliberately avoid a strong
`hosts[]` array [V `percy-cypress@464f728 index.js:16-37`]. Forcing `mode:'open'` breaks real sites —
h5player forces open and then *re-lies* with
`Object.defineProperty(this, 'shadowRoot', {get(){return null}})`, commented (translated) "so what
the outside perceives is still a closed shadow root, to prevent misjudgement or targeted detection"
[V `h5player@e5a7d2b hackAttachShadow.js:40-50`]. I reproduced the leak: a naive
`mode:'closed' → 'open'` override makes the site's own `host.shadowRoot === null` check return
`false` [M].

**Does `add_init_script` reach every frame?** Definitively yes, and this was the key engineering
question. CDP: *"Evaluates given script in every frame upon creation"* [V `protocol.d.ts:15554`].
OOPIFs are separate targets, so Playwright re-registers per session
[V `crPage.ts:252-254, 1055-1059`], and on `Target.attachedToTarget` it installs all init scripts with
`runImmediately: true` **before** sending `Runtime.runIfWaitingForDebugger` — auto-attach uses
`waitForDebuggerOnStart: true`, and CDP messages are ordered per session [V `crPage.ts:539, 571-574`].
Asserted in their own suite [V `tests/library/chromium/oopif.spec.ts:243-253`]. Measured: a
context-level `attachShadow` hook pierced a closed root inside a **cross-origin OOPIF** and inside a
**srcdoc** frame [M]. The gotcha: the live `addInitScript` path does *not* pass `runImmediately`, so
registering after a document has loaded does not retro-apply — register before `goto`.

### Puppeteer — @ `18d58ff5` (2026-08-25): the explicit alternative to `frame_locator`

Puppeteer's `>>>` (deep descendant) and `>>>>` (deep child) are real, parsed combinators —
`enum PCombinator {Descendent = '>>>', Child = '>>>>'}` [V `injected/PQuerySelector.ts:32-35`],
tokenized by `/\s*(>>>>?|[\s>+~])\s*/g` [V `common/PSelectorParser.ts:21`], and implemented as a lazy
`flatMap` over the element stream: `pierce` yields `root.shadowRoot ?? root`, `pierceAll` seeds a
worklist of TreeWalkers [V `injected/util.ts:48-75`]. `pierce/div` ≡ `& >>> div`. It reads
`element.shadowRoot` — **open roots only**, closed unreachable, and it never crosses an iframe
(`contentDocument` appears nowhere in `src/injected/`). **There is no `frameLocator`** (zero hits);
descent is manual `page.frames()` / `contentFrame()` and `NodeLocator` binds its frame at
construction and never rebinds [V `api/locators/locators.ts:1086-1098`].

The transferable part is `#getTopLeftCornerOfFrame`: walk `parentFrame()`, evaluate **in the parent
realm**, and accumulate `rect.left + paddingLeft + borderLeftWidth` per level
[V `api/ElementHandle.ts:1380-1415`], with `#intersectBoundingBoxesWithFrame` clipping at every
ancestor [V `:1164-1238`]. That is the correct version of the offset math NetGent does by hand.
Also note `isIntersectingViewport` runs its `IntersectionObserver` *inside the element's own frame*
[V `:1516-1539`] — "viewport" means the iframe's viewport, a subtle gap.

### Midscene, Index, Eko, Steel — the common failure shape

**Midscene** (@ `378cb4ce`) has **zero shadow-DOM support** (repo-wide grep for `shadowRoot` /
`attachShadow` → nothing) and its extractor enumerates iframes from a *top-document-scoped*
`querySelectorAll('iframe')`, so **nested iframes are never reached** [V `extractor/web-extractor.ts:408-435`].
Its locator layer is better: `SUB_XPATH_SEPARATOR = '|>>|'` builds a compound cross-iframe XPath,
hopping via `elementFromPoint` and `translatePointToIframeCoordinates` —
`(point.left - rect.left - clientLeft - paddingLeft) / zoom` [V `extractor/locator.ts:13, 73-90, 300-354`] —
and fails loudly on cross-origin. The maintainer's position on nested iframes is *"use a vision model
and the iframe structure doesn't matter"* [2H #1098].

**Index** (lmnr-ai) computes frame/shadow provenance in its injected script
(`elementData.context.iframe`, `.context.shadowDOM`) and then **throws it away** — `InteractiveElement`
has no `context` field and no `extra='allow'`, so pydantic drops it [V `browser/models.py:30-49`]. It
acts by pure coordinates, and its one DOM-identity action (`select_dropdown_option`) is commented
"works across frames too" while doing a plain top-document `querySelector`
[V `controller/default_actions.py:437-450`].

**Eko** (@ `c3de315a`) reads `.shadowRoot` only, drops cross-origin iframes with a `console.warn`
[V `build-dom-tree.ts:746-771`], has no `all_frames`, executes everything in the top frame's isolated
world, and clicks with untrusted `new MouseEvent(...)` [V `browser-labels.ts:855-865`].
**Steel-browser** is session infra with no observation layer; its one injected script handles shadow
DOM solely via `event.composedPath()` — open roots only — and it calls `Runtime.enable` on every page
target [V `instrumentation/target-manager.ts:172-176`].

**rebrowser-patches** answers a question NetGent inherits from Patchright: without `Runtime.enable`,
how do you get an execution context in *every* frame? Lazily, per frame —
`Page.createIsolatedWorld` for the utility world, an isolated-world `CustomEvent` → `Runtime.addBinding`
handshake for the main world [V `patches/playwright-core/src.patch:78-141`]. Patchright does the
equivalent by parsing the context id out of an `objectId` string [V `framesPatch.ts:222-293`]. The
operational consequence: **there is no push notification of context creation**, so the first
`evaluate()` in a freshly-created frame pays a 3-4 round-trip tax and can race a navigation into
`Frame was detached`. Assume per-frame `evaluate()` needs a retry, not a one-shot.

### Agent-E, LaVague, Notte — three attempts at a durable cross-boundary path

**Agent-E** (@ `f218c3cb`) stamps `mmid` on every element via `querySelectorAll('*')` and smuggles it
through Playwright's AX snapshot in `aria-keyshortcuts` [V `get_detailed_accessibility_tree.py:30, 44-45, 85`].
It has **no shadow and no iframe support** — `page.accessibility.snapshot()` does not descend into
iframes, and `iframe` is in `tags_to_ignore` so those nodes are stripped [V `:74`]. `mmid` is a
per-snapshot counter: not replayable.

**LaVague** (@ `9024bb83`, dead since 2025-01) built the flat iframe-crossing XPath dialect Stagehand
later shipped: `traverse` recurses into `child.contentWindow.document.body` and concatenates
`childXpath + '/html/body'`, producing `/html/body/div/iframe/html/body/a[2]`
[V `core/base_driver.py:559-590`]. It is not valid XPath, so `resolve_xpath` string-splits on the
literal token `"iframe"`, `switch_to.frame`s, and recurses inside a context manager that restores the
default frame [V `drivers/selenium/base.py:53-63, 297-309`]. Cross-origin is "handled" by
`--disable-web-security`. Shadow DOM was designed (`//` as the intended separator) and **never
implemented** — zero `shadowRoot` hits across 716 commits [V; 2H issue #583, open]. The killer: their
Playwright driver does `page.locator(f"xpath={xpath}")` with no frame handling, and `lavague-qa` codegen
serializes the raw string into `By.XPATH` — **the frame boundary does not survive codegen**
[V `qa/utils.py:94-99`].

**Notte** (@ `1802f008`) is the closest prior art to NetGent. `NodeSelectors` is a pydantic model with
`css_selector`, `xpath_selector`, `in_iframe`, `in_shadow_root`, and
**`iframe_parent_css_selectors: list[str]`** [V `notte_core/browser/dom_tree.py:54-62`], resolved by
looping `current_frame = current_frame.frame_locator(css_path)` [V `dom/locate.py:10-20`] — the same
design as NetGent's `frame_path` → `frame_locator` chain. Shadow crossing is a Playwright `>>` chain of
per-shadow-tree xpath segments [V `dom/locate.py:58-100`]. Three defects worth learning from:
`locate_element` returns `page.locator(playwright_selector)` **before** the `if selectors.in_iframe:`
branch, making the frame chain dead code for any node that has one [V `dom/locate.py:28-42`]; the
durable-looking `notte_selector` embeds Python's `hash()`, which is `PYTHONHASHSEED`-randomized and so
unstable across processes [V `dom/parsing.py:72, 119`]; and the ergonomic *string* form of a selector
routes through `from_unique_selector`, which hardcodes
`in_iframe=False, in_shadow_root=False, iframe_parent_css_selectors=[]` — **frame and shadow context is
destroyed by string serialization** [V `dom_tree.py:74-100`].

---

## Comparison table

| Project | Observes x-origin iframes | Observes closed shadow | Acts via | Durable cross-boundary reference? |
|---|---|---|---|---|
| **NetGent (today)** | **yes** (per-frame `evaluate` via CDP) | no | Playwright locator chain | **yes** — `frame_locator` chain in YAML |
| Playwright (raw) | yes (`frameLocator`) | no | locator | yes (`normalize()` → chain) |
| Patchright | yes | **yes** (CDP `describeNode` pierce) | locator | yes, but closed-root reach is Patchright-only |
| browser-use | yes (per-target recursion) | **yes** (CDP pierce) | backendNodeId + `Input.*` | no — XPath passes through shadow, `frame_id` is `None` |
| Stagehand v4 | yes (forced `--site-per-process`) | **yes** (`chrome.dom.openOrClosedShadowRoot`) | CDP `Input.*` | yes — flat XPath w/ `//` shadow hop (ambiguous; #2693) |
| Skyvern | yes (per-frame `evaluate`) | no | locator + 5-step fallback ladder | ephemeral stamp + **content hash** for replay |
| playwright-mcp | yes (`f<seq>e<n>` refs) | no | locator via frame `seq` | **no** (refs) — but ships `normalize()` conversion |
| agent-browser | one level only | via AX tree | backendNodeId, self-heals by role+name+nth | no |
| Notte | yes (`frame_locator` per css path) | no | locator | **yes** in dict form; destroyed in string form |
| LaVague | yes (`--disable-web-security`) | no | Selenium `switch_to.frame` | path exists; **lost in codegen** |
| Puppeteer | manual `frames()` | no | locator, manual frame offsets | no |
| Midscene / Index / Eko | 1 level / 1 level / same-origin only | no | coordinates | no |
| lumen / magnitude | n/a (pixels) | n/a (pixels) | `Input.dispatchMouseEvent(x,y)` | **no** (exact screenshot hash) |
| Selenium / WebDriver | yes (mode switch) | **yes** (spec endpoint) | context-scoped handle | no (handles are context-scoped) |
| Cypress | painful (`cy.origin`) | no | in-page | n/a |

---

## Where NetGent stands

I ran our own `BrowserSession.snapshot()`, `_locator_for` and `_resolve` against a hostile fixture
(top frame + shadow-in-cross-origin-iframe + iframe-in-open-shadow + a closed shadow root + a
2-deep nested cross-origin chain + two instances of the same shadow component). Raw output in
[Verification notes](#verification-notes).

### What already works — and is genuinely ahead of the field

- **Per-frame observation is the right architecture.** `snapshot()` iterates `self.page.frames` and
  evaluates `DOM_SNAPSHOT_JS` in each frame's own context
  (`browser/session.py:116-119`), and `DOM_SNAPSHOT_JS` deliberately does *not* descend iframes
  (`browser/dom/snapshot.py:100-102`). That is the same choice Skyvern and browser-use converged on
  after their in-page recursion died on `SecurityError` (browser-use #1700). Midscene, Index and Eko
  still recurse in JS and lose cross-origin content.
- **Measured passes:** an input inside an **open shadow root inside a cross-origin iframe** — observed
  *and* filled. An input inside an **iframe hosted by an open shadow root** — observed *and* filled
  (`frame_locator("iframe#fb")` resolves because Playwright's CSS engine pierces the host). An input
  **two cross-origin hops deep** — observed *and* filled via
  `frame_locator("iframe#nest") · frame_locator("iframe#inner") · locator("#d2")`. Only
  browser-use, Stagehand and Notte match that, and agent-browser expands only one level of nesting.
- **The chain is self-healing across frame churn.** Playwright re-resolves every step, frame steps
  included, on each retry (`server/frames.ts:1201-1252`). Measured: a chain built before an iframe
  re-navigated still filled after. We get for free what LaVague's codegen loses.
- **`scoped_to(frame_path)`** (`snapshot.py:215-228`) gives the sweep a per-iframe form scope — the
  right primitive for multi-form pages.

### What is fragile or missing

> **Implemented on `v2/frames-shadow` (2026-08-25).** All ten gaps below are addressed; each
> item is tagged with the R-recommendation and commit that closed it, and every fix ships with
> the fixture-based test the Recommendations section prescribes (`tests/integration/test_frames_shadow.py`
> for the browser fixtures, `tests/unit/test_normalized.py` / `test_locator_uniqueness.py` /
> `test_compiler.py` for the pure logic). Status per R-item:
>
> - **R1 — locator uniqueness at capture time** *(done)*. `observation.unique_locator_for` verifies
>   each candidate chain resolves to `count()==1` before storing it; an all-ambiguous element gets a
>   whitelisted `nth` step. Closes gaps #2 and #8-uniqueness. (fixture: two `<my-form>` instances)
> - **R2 — frame-aware triggers + `ParamSource`** *(done)*. `frame_path: list[str] = []` on
>   `SelectorVisible`/`SelectorHidden`/`ParamSource`, resolved through the same `frame_locator` chain;
>   `SelectorHidden` now requires a resolved element. Closes gap #1. (fixture: cross-origin payment iframe)
> - **R3 — don't swallow per-frame failures; type-check `_resolve`** *(done)*. `snapshot()` logs and
>   counts skipped frames (`DomSnapshot.frames_skipped`); `_resolve` and a schema `AfterValidator`
>   reject chains that don't end on a `Locator`. Closes gaps #7 and #8. (fixture: self-removing iframe)
> - **R4 — `Locator.normalize()` cross-check/fallback** *(done)*. `agent/explore_agent/normalized.py`
>   parses the `internal:` selector back into our whitelist (total, else `UnmappableSelector`);
>   `capture_locator` prefers Playwright's frame selectors when both agree. (fixture: the hostile page)
> - **R5 — frame-aware scroll** *(done)*. `ScrollAction.locator` moves the cursor over the target
>   before the wheel; `to_action` anchors on the scoped frame. Closes gap #4. (fixture: 3000px in a 400px iframe)
> - **R6 — coordinate space** *(done)*. `_frame_info` accumulates border+padding content-origin on
>   both axes (Puppeteer's `#getTopLeftCornerOfFrame`), memoized. Closes gap #5 and #9. (fixture: 8px border+padding)
> - **R7 — harden `FRAME_SELECTOR_JS`** *(done)*. Real tag name, quoted attributes, verified-unique
>   with `nth`, preferring test-id/name/title. Closes gap #6. (fixture: two sibling iframes + a legacy `<frame>`)
> - **R8 — closed shadow roots** *(done; re-done zero-footprint 2026-08-25)*. Observed from OUTSIDE
>   the page over CDP (`browser/dom/closed_shadow.py`): `DOMSnapshot.captureSnapshot` detects documents
>   with a closed tree, `DOM.describeNode(depth=-1, pierce=true)` — Patchright's own pierce — lists
>   the closed roots, `DOM.resolveNode` hands them into an isolated world we create with
>   `Page.createIsolatedWorld`, and `DOM_SNAPSHOT_JS` walks them there. No init script, no
>   prototype patch, no global; `DOM_SNAPSHOT_JS` is back in Playwright's isolated world.
>   `requires_closed_shadow` capability flag; Patchright acts natively. Closes gap #3. (fixtures:
>   closed root over HTTP / in a cross-origin iframe / declarative — now observed / no-trace probe)
> - **Observation** now prints `|IFRAME n|` headers grouping elements by frame and marks
>   `|SHADOW(closed)|` elements, so the model sees containment (browser-use / Playwright aria-snapshot shape).
> - **Not yet closed: #10** (`PressAction` without a locator still keys the focused frame) — left as-is;
>   the frame-aware press has no fixture in scope and the risk is a focus-steal race, not a silent
>   mis-recognition. Noted here as an honest remaining gap.

**1. Triggers and parameter extraction are frame-blind — a correctness bug in the NFA, not a gap.**
`_holds` uses `self.page.locator(trigger.selector)` (`session.py:238-240`) and `extract_value` uses
`self.page.locator(source.selector)` (`session.py:251`). Neither has a frame path. Measured:
`selector_visible("#si")` returned **False** for a plainly visible element inside a cross-origin
iframe. Worse, `SelectorHidden` returns **True** for anything not in the top frame — so a state can be
"recognized" for the wrong reason. Payment, login and consent widgets are exactly the iframes we need
to anchor on.

**2. The `#id`-first rule is unsafe under shadow DOM.** `_locator_for` prefers a bare `#id`
(`agent/explore_agent/observation.py:102-111`) with the comment that it "pierces open shadow DOM" —
true, and that is the problem: an id inside a web component is *not* document-unique. Two instances of
the same component both expose `#email`. Measured: `locator("#email")` resolved to 2 elements →
`Locator.fill: strict mode violation`. `_click` survives on `.first` (`session.py:175`) but `fill`,
`select_option`, `set_input_files` and `hover` are strict and will throw **at replay time, in a
compiled workflow**. `nth` is in the whitelist (`schema/actions.py:27`) but `_locator_for` never emits it.

**3. Closed shadow roots: we can act on them but cannot see them.** `DOM_SNAPSHOT_JS` gates on
`el.shadowRoot` (`snapshot.py:99`), so closed roots are dropped — measured FAIL. Meanwhile Patchright
is our default (`PATCHED_BROWSER = True` measured) and resolves closed-root elements natively:
`locator("#ci").count()` = 1, and `fill`/`click`/`press`/`type`/role-click all succeeded. So the
compiler can never emit a locator for content the replayer could happily drive.

**4. Scroll cannot reach inner frames or inner scrollers.** `ScrollAction` does
`page.mouse.wheel(0, pixels)` (`session.py:210-213`) at the current cursor, which defaults to (0,0).
Measured: at (0,0) the **top** frame scrolls (inner 0 / outer 500); with the cursor centred on the
iframe the **inner** frame scrolls (inner 500 / outer 0); over an inner scrollable `<div>` the div
scrolls. We never move the cursor, so we always scroll the top frame. `viewport` is also the top
frame's `innerHeight`.

**5. The coordinate space is half-normalized.** `snapshot()` adds `offset_y` to `bbox.y`
(`session.py:124`) but **never to `bbox.x`** — so `x` is frame-local for in-frame elements and
top-viewport for everything else, in one list. And the offset sums
`getBoundingClientRect().top`, the *border-box* top, omitting the iframe's border and padding.
Measured against `bounding_box()` ground truth: `dy = −8`, `dx = −8` for an 8px-bordered iframe, stable
across a top-frame scroll. Puppeteer adds `paddingTop + borderTopWidth` per level
(`api/ElementHandle.ts:1380-1415`); we should too. The drift mis-sorts `format_observation`'s
near-viewport paging (`observation.py:36-38`) for elements near a frame edge.

**6. `FRAME_SELECTOR_JS` has four correctness holes** (`snapshot.py:144-164`): (a) it hardcodes the
`iframe` tag in the id/name fast paths, so a legacy `<frame>` in a frameset yields `iframe#x`, which
never matches — Skyvern hit exactly this (#530); (b) `iframe[name="${CSS.escape(fr.name)}"]` misuses
`CSS.escape`, which escapes *identifiers*, not quoted attribute values; (c) the generic path caps at 6
ancestors and, on hitting the cap, returns an **unanchored** descendant path that can match several
iframes — and `frame_locator` is strict (measured: `strict mode violation: locator("iframe") resolved
to 2 elements`; `.nth(1)` disambiguates, but we never emit it); (d) for an iframe inside a shadow root,
`parentElement` is `null` at the boundary so the path is shadow-root-relative — it happens to resolve
because Playwright's CSS pierces, but only while the path stays document-unique.

**7. Per-frame failures are silent.** `snapshot()` swallows any exception and `continue`s
(`session.py:120-121`). A detaching ad iframe drops all of its elements with no signal to the agent or
the trajectory. This is browser-use #4778 verbatim; their fix was to keep going but *log* it.

**8. `_resolve` can hand back a non-`Locator`.** It rejects a chain ending on `Page`
(`session.py:161-162`) but not one ending on `FrameLocator`, which has no `.fill`/`.click` (measured
`hasattr(FrameLocator, "fill") == False`) — the failure surfaces as an `AttributeError` through
`dispatch`'s generic handler. Relatedly `filter` is whitelisted but `FrameLocator` has no `.filter`
(measured `False`), so a schema-legal chain can be unresolvable.

**9. Cost.** `_frame_info` does `frame_element()` + two `evaluate` calls **per ancestor, per frame**,
with no memoization — O(depth²) round trips (`session.py:96-102`). 11 ms for 2 frames measured; a page
with 30 ad iframes 3 deep is ~180 round trips per observation.

**10. `PressAction` without a locator** goes to `page.keyboard.press` (`session.py:207`) — to whatever
frame currently has focus, unasserted. Stagehand has the identical bug (`actHandlerUtils.ts:279-292`).

---

## Recommendations

Ordered by (correctness impact ÷ cost). Everything below keeps locator chains declarative,
whitelisted and replayable — no code in artifacts.

### P0 — correctness bugs that will fire in compiled workflows

**R1. Verify locator uniqueness at capture time; emit `nth` when it is not unique.** *(cost: S)*
In `_locator_for`, before returning a chain, resolve it and check `count()`. If > 1, either fall back
to the next candidate or append `LocatorStep(fn="nth", args=[i])` — `nth` is already whitelisted, so
the artifact format does not change. Drop the "`#id` first" rule to "`#id` first **iff** it resolves to
exactly one element", since Playwright's CSS pierces open shadow roots and component ids repeat.
Skyvern already refuses to proceed unless `count() == 1` (`dom.py:1620-1642`); we should do the same at
*compile* time so replay never sees a strict-mode violation.
*Fixture:* a page with two instances of the same `<my-form>` web component, each with `#email`/`#go`
inside an open shadow root; assert the compiled chain resolves to exactly 1 and `fill` succeeds.

**R2. Give triggers and `ParamSource` a frame path.** *(cost: M — schema change)*
Add `frame_path: list[str] = []` to `SelectorVisible`, `SelectorHidden` and `ParamSource`, and resolve
it in `_holds`/`extract_value` by the same `frame_locator` chain `_resolve` already builds. Keep the
default empty so existing artifacts are unaffected. Additionally make `SelectorHidden` distinguish
*"resolved and hidden"* from *"never resolved"* — today a typo'd selector satisfies the trigger.
*Fixture:* a cross-origin payment iframe whose success banner appears inside the frame; assert a state
anchored on it is recognized, and that `SelectorHidden` on a nonexistent selector does **not** silently
hold.

**R3. Don't swallow per-frame failures; and type-check `_resolve`.** *(cost: XS)*
Log the frame URL and exception in `snapshot()`'s `except` and record a `frames_skipped` count on
`DomSnapshot` so the trajectory shows it. In `_resolve`, raise `LocatorResolutionError` when the chain
ends on anything that is not a `Locator`, and validate at schema level that `frame_locator`/`nth` are
the only steps legal on a `FrameLocator` receiver (i.e. `filter` may not follow `frame_locator`).
*Fixture:* a page whose iframe removes itself 100 ms after load; assert the snapshot reports one skipped
frame instead of silently shrinking.

### P1 — reach and robustness

**R4. Use `Locator.normalize()` as the capture-time locator generator and validator.** *(cost: M)*
This is the highest-leverage item in the survey. Playwright's `Frame.resolveSelector` already generates
a role/testid/text-preferring selector for an element **and** walks up `parentFrame()` emitting one
selector per `<iframe>`, joined by `internal:control=enter-frame` (`server/frames.ts:1312-1339`). It is
shadow-aware (it climbs via `parentElementOrShadowHost`) and it is in the Playwright we already ship
(1.62.0, measured). Measured output for a shadow-DOM button inside a cross-origin iframe:
`iframe[name="payframe"] >> internal:control=enter-frame >> internal:testid=[data-testid="deepbtn"s]`.
Use it two ways: (a) as a **cross-check** on `_locator_for` — if our chain and Playwright's disagree on
the resolved element, prefer Playwright's frame selector for the `frame_locator` steps (it uses
`iframe[name=…]`, which is far more stable than our `nth-of-type` path); (b) as a **fallback** when
`_locator_for` raises. Parse `internal:role=button[name="X"i]` / `internal:testid=…` back into our
whitelisted steps — do **not** store the internal string, which would smuggle a non-whitelisted engine
into the artifact. Keep the parse total: anything we cannot map to a whitelisted step is a compile-time
failure, recorded, not papered over.
*Fixture:* the hostile page above; assert every element's `_locator_for` chain and its `normalize()`
chain resolve to the same element handle.

**R5. Make scroll frame-aware.** *(cost: S)*
Extend `ScrollAction` with an optional `locator: Locator | None`. When present, move the mouse to that
element's `bounding_box()` centre before `mouse.wheel` — measured: the wheel then scrolls the frame or
inner scroller under the cursor, which is exactly the behaviour lumen and magnitude rely on. When
absent, keep today's top-frame behaviour. Also use the *scoped* frame's `innerHeight` for the page
conversion when the sweep is scoped to a frame.
*Fixture:* a 3000px-tall document inside a 400px cross-origin iframe with a button at the bottom;
assert scroll reaches it and that the top frame does not move.

**R6. Fix the coordinate space.** *(cost: S)*
In `_frame_info`, accumulate `rect.top + borderTopWidth + paddingTop` **and** `rect.left +
borderLeftWidth + paddingLeft` (Puppeteer's `#getTopLeftCornerOfFrame`), return both, and apply the x
offset in `snapshot()` alongside the y offset (`session.py:124`). Measured error today: exactly the
iframe's 8px border in both axes, and `x` is not offset at all.
*Fixture:* an element inside an iframe with `border: 8px; padding: 5px`; assert
`abs(snapshot.bbox.{x,y} − bounding_box().{x,y}) <= 1`.

**R7. Harden `FRAME_SELECTOR_JS`.** *(cost: S)*
Use the real tag (`fr.tagName.toLowerCase()`) instead of a hardcoded `iframe`; build attribute
selectors with proper quoting rather than `CSS.escape` on the value; and — the important one — verify
each generated frame selector is unique in its parent document before returning it, appending an `nth`
step when it is not. Memoize `_frame_info` per parent frame to kill the O(depth²) round trips.
*Fixture:* a page with two sibling `<iframe>` elements sharing a class and no id, plus one legacy
`<frame>` in a frameset; assert both resolve without a strict-mode violation.

### P2 — new capability

**R8. Closed shadow roots: observe from outside the page over CDP, act through Patchright, and
record a capability flag.** *(cost: M–L)*

> **Implemented mechanism (2026-08-25) — supersedes the registry design below.** The first
> implementation followed this section: a WeakMap registry wrapping `Element.prototype.attachShadow`,
> installed in the main world via CDP `Page.addScriptToEvaluateOnNewDocument`, probed by
> `DOM_SNAPSHOT_JS` under `isolated_context=False`. It did not leak `host.shadowRoot`, but it *was* a
> prototype lie — measured on Chrome 151 from the page's main world:
> `Element.prototype.attachShadow.toString()` returned our source instead of
> `function attachShadow() { [native code] }`, `.name` was `""` instead of `"attachShadow"`, and
> `'__ngClosedRoot' in window` was `true` (it appears in `Object.getOwnPropertyNames(window)`). That is
> exactly the class CreepJS's lies section scores (`Function.prototype.toString` on natives), and
> `stealth-after-patchright.md` says we must not ship it. The hook is gone; nothing of ours runs in the
> main world any more.
>
> What replaced it, per snapshot (`v2/src/netgent/browser/dom/closed_shadow.py`):
> 1. **One CDP session per target.** The page's session covers the top frame and every same-process
>    child; each OOPIF gets `context.new_cdp_session(frame)`. Playwright refuses that call for a
>    same-process frame ("This frame does not have a separate CDP session, it is a part of the parent
>    frame's session") — measured — which is how the two are told apart. Cross-origin frames therefore
>    keep working (a same-site cross-origin iframe is same-process and rides the page session; a
>    cross-site one, e.g. `localhost` vs `127.0.0.1`, is an OOPIF with its own session — both measured).
> 2. **Detect** with `DOMSnapshot.captureSnapshot({computedStyles: []})`: a flat dump of every local
>    document whose `shadowRootType` column says whether the document holds any closed tree (the
>    ShadowRoot node itself is not listed — children hang off the host, tagged with the tree type).
>    1–5 ms measured; most documents stop here.
> 3. **Enumerate** with `DOM.describeNode(backendNodeId=<document>, depth=-1, pierce=true)` — the call
>    Patchright's `_customFindElementsByParsed` uses to act — collecting every `shadowRootType:
>    "closed"` root's `backendNodeId`, nested ones included. Declarative closed roots
>    (`<template shadowrootmode="closed">`) are listed too, so they are now observed (the registry
>    could not see them: no `attachShadow` call) — fixture r8c flipped from "absent" to "observed,
>    flagged, clicked".
> 4. **Walk** in a world of our own: `Page.createIsolatedWorld(frameId)` → `executionContextId`
>    (cached per frame; a navigation destroys it and `Cannot find context with specified id` triggers
>    re-creation), `DOM.resolveNode(backendNodeId, executionContextId)` per root, then
>    `Runtime.callFunctionOn(DOM_SNAPSHOT_JS, arguments=roots, returnByValue)`. The walker maps
>    `root.host → root` and descends at the host's position, so element order is identical to the
>    registry's. Isolated worlds share the DOM but not the JS global — the page cannot see them.
> 5. **Join** to Playwright's frame loop by an exact key: the frame's selector path, computed on the
>    CDP side with `DOM.getFrameOwner` + `FRAME_SELECTOR_JS` in each ancestor's world, is the same
>    string `_frame_info` produces with Playwright for the same frame (measured equal for `iframe#cf`,
>    `iframe#oop`, `html > body > iframe:nth-of-type(4)`). `snapshot()` uses the CDP walk for frames
>    with that key and the ordinary `frame.evaluate` (isolated world) for all others.
>
> Cost: 25 ms for three closed-root documents (one OOPIF) on the fixtures. On pages without closed
> roots the only addition is detection: `captureSnapshot` ≈ 5 ms on browser-use's challenge page
> (2 documents) and 45–90 ms on its forms-comparison page (27 documents, ≈1.5 ms/document); the
> per-frame `new_cdp_session` probe is 0.3 ms / 6–25 ms respectively. `netgent eval observation`
> on both pages reports identical element counts and metrics before and after (207 / 39 elements,
> same named/unique/resolves %). Regression probe:
> `tests/integration/test_browser_profile.py::test_closed_shadow_observation_leaves_no_page_visible_trace`
> (native `attachShadow` source and name, no `__` global on `window`, page's `shadowRoot === null`
> intact, closed-root elements still observed and flagged).
The asymmetry today is backwards — we can act but not see. Three verified facts make the fix concrete:
(i) `context.add_init_script` reaches **every** frame including cross-origin OOPIFs and `srcdoc`
(measured, and Playwright installs init scripts per FrameSession with `runImmediately: true` before
`Runtime.runIfWaitingForDebugger`, `crPage.ts:571-574`); (ii) a `WeakMap` registry that leaves `mode`
untouched does **not** leak — measured, the site's own `host.shadowRoot === null` check still returns
`true`, and no enumerable `window` key is added, whereas the naive `closed → open` rewrite flips that
check to `false`; (iii) Patchright already acts on closed-root elements natively via CDP
`DOM.describeNode{pierce:true}` + `DOM.resolveNode`, with no page tampering at all.

So: register the Percy-shaped registry at context level *before* `goto`, have `DOM_SNAPSHOT_JS` probe
`__ngClosedRoot(host)` per element and walk what it returns, and stamp
`requires_closed_shadow: true` on any locator captured from inside one — Stagehand v4's capability-flag
pattern, so the synthesizer can refuse to emit a chain a plain-Playwright replayer could not drive.

Two Patchright-specific constraints, both measured: `evaluate` defaults to `isolated_context=True`,
which shares the DOM but **not** the JS global, so the probe needs `isolated_context=False` — a
Patchright-only kwarg that must be feature-gated on `PATCHED_BROWSER`; and Patchright injects init
scripts by rewriting HTML responses, so this does nothing for `set_content`/`data:` URLs. Do **not**
force `mode: 'open'` (breaks sites that branch on `shadowRoot === null`) and do **not** copy Stagehand
v3's `rerenderMissingShadowHosts`, which clones and replaces live custom elements. Declarative shadow
DOM (`<template shadowrootmode>`) never calls `attachShadow` and stays invisible — accept that, or add
a CDP `DOM.getDocument(pierce=true)` pass per target later.
*Fixtures:* (a) a `{mode:'closed'}` root served over HTTP — assert observed, acted on, flagged, and that
the page's own `shadowRoot === null` check is unchanged; (b) the same inside a cross-origin iframe;
(c) a `<template shadowrootmode="closed">` page — assert we report it as *unobservable* rather than
claiming success.

**Explicitly not recommended.** Stamping ids into the DOM (Skyvern): great runtime index, unusable in
an artifact — non-deterministic across sessions, duplicated by `cloneNode`, and a fingerprinting
surface. Coordinate actions (lumen, magnitude): they cross every boundary, but a coordinate is not a
locator, and lumen's own durable memory stores prose rather than pixels. Storing an aria-ref or a
`backendNodeId`: dead outside the snapshot that minted it. Overloading one separator for both
boundaries (Stagehand's `//`): their open issue #2693 is precisely that cost.

---

## Verification notes

**Environment.** macOS 15.5 / Chromium via `playwright 1.62.0` and `patchright 1.62.1` (the venv at
`v2/.venv`), `PATCHED_BROWSER = True`. Cross-origin fixtures were two or three `http.server` instances
on distinct loopback ports (different ports = different origins). Probe scripts live in `/tmp/ngexp/`
and touch no repo file.

**Measured directly by me (marked [M] above).** CSS `#id` pierces open shadow roots and returns 2
matches across two component instances; `fill` on it raises `strict mode violation`. `div#h1 > input`
and `div#h1 input` both cross an open shadow boundary. `get_by_role` / `get_by_text` /
`get_by_placeholder` pierce open roots. `>>>` is not a Playwright selector (0 matches, no error).
Closed roots: `count()` = 0 under Playwright, **1 under Patchright**, where `fill`/`click`/`press`/
`type` and a role-click all succeed and the effect lands inside the root (one earlier run showed an
intermittent `fill` timeout at 3 s). A context-level `attachShadow` `WeakMap` registry reached a closed
root inside a **cross-origin OOPIF** and inside a **srcdoc** frame; the non-leaking variant leaves the
site's `shadowRoot === null` check intact while the naive `closed → open` rewrite flips it.
`page.frames` reports `about:srcdoc` and `about:blank` for those frames and `frame_element()` resolves
both. Chained `frame_locator` works through two cross-origin hops and into a shadow root inside the
innermost frame; a chained locator stringifies to `… >> internal:control=enter-frame >> …`. A chain
re-resolves correctly after its frame re-navigates; a detached frame raises `Frame was detached` and
leaves `page.frames`. `frame_locator("iframe")` with two matches is a strict-mode violation; `.nth(1)`
fixes it. `mouse.wheel` scrolls whatever is under the cursor — inner frame when centred on it, top
frame at (0,0), an inner `<div>` when over one. `locator.click` auto-scrolls the *inner* frame to reach
an element. `Locator.normalize()` exists in 1.62.0 and produces frame + shadow-aware chains.
`FrameLocator` has neither `.filter` nor `.fill`.

**NetGent audit run.** On the hostile fixture: 5 frames, 9 elements. PASS — shadow-in-cross-origin-iframe
observed and filled; iframe-in-open-shadow observed and filled; depth-2 cross-origin observed and
filled. FAIL — closed shadow not observed; duplicate-shadow `#email` chain raised a strict-mode
violation on `fill`; `selector_visible("#si")` returned `False` for a visible in-frame element;
`ScrollAction` moved no frame. Coordinate error measured separately against `bounding_box()` ground
truth: `dx = −8`, `dy = −8` for an 8px-bordered iframe, stable across a top-frame scroll.
`snapshot()` took 11 ms with 2 frames.

**Secondhand and not re-verified.** All issue numbers and states (browser-use, Stagehand, Skyvern,
playwright-mcp, Midscene, LaVague) come from sub-agents' `gh search` results. Chromium-internal
behaviours — `DOM.scrollIntoViewIfNeeded` propagating to ancestor scrollers, `about:srcdoc` as the
literal URL — are documented behaviour, not measured here. The CDP claim that
`DOM.getDocument(pierce=true)` exposes closed roots but **not** OOPIF content was measured by a
sub-agent, not by me. Repo SHAs are as cited per section; several repos moved between the layout named
in the original brief and their current HEAD (playwright-mcp's source now lives in the Playwright
monorepo; Stagehand's `lib/` layout is v2 and its current driver is `understudy/`; Skyvern's
`SkyvernFrame` moved to `webeye/utils/page.py`).
