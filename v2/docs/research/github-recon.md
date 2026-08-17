# GitHub Recon — NetGent's Own Repos + Comparable Systems

Researched 2026-08-05 (Opus subagent, 221 tool calls). Companion to [design-doc-review.md](design-doc-review.md).

## Part 1 — The project's own repos

| Repo | Role |
|---|---|
| [SNL-UCSB/netgent](https://github.com/SNL-UCSB/netgent) (public, 9★) | **NetGent V1** — the paper artifact (SeleniumBase + PyAutoGUI + LangGraph) |
| [EugeneVuong/netgent](https://github.com/EugeneVuong/netgent) | **V1.5/V2 prototype** — ground-up Playwright/async rewrite |
| [SNL-UCSB/netgent-workflow](https://github.com/SNL-UCSB/netgent-workflow) | Workflow registry (15 workflows, JSON + manifests + index.json) |
| SNL-UCSB/netgent-paper (private) | Paper draft (created 2026-07-21) |
| SNL-UCSB/appAgent (private) | Predecessor, archived into netgent 2025-09 |

Paper: **"NetGent: Agent-Based Automation of Network Application Workflows"**, arXiv 2509.00625 — Daneshamooz, Vuong, Koduru, Chandrasekaran, Gupta (UCSB). NeurIPS 2025.

### What V1 is
A **cache-first NFA interpreter**: users write NL `StatePrompt`s (abstract NFA); each compiles to a concrete state `(detectors, code)`; a pure-Python `ProgramController` matches the live page against cached detectors (conjunction of checks; two matches ⇒ `ValueError` since `allow_multiple_states=False`); hit → replay actions LLM-free; miss + LLM enabled → `state_synthesis` (LLM sees only URL + title — not DOM/screenshot, despite the paper's "Observe" description) → web agent → write new state back. **No runtime validation, no selector fallback, no healing, no compile-time state-distinctness check.** Whole-state regeneration is the only recovery, and it fires only when *zero* states match — a wrong-but-matching detector is undetectable.

Paper numbers: ESPN uncached 278k tokens/$0.098 per run vs. cached $0.15 one-time; localized regeneration ~95% overhead reduction (20k vs 375k tokens).

Instructive commit `0bb957a` (Twitch trigger collision): "Watching Stream" state checked only `<video>`, which also exists in the home-page autoplay preview → both states matched → hard crash. Fixed by hand-ANDing a channel-page CSS marker. **State identity as hand-tuned detector conjunctions fails at runtime, loudly at best.**

Repo is dormant since 2026-06-26; energy moved to EugeneVuong/netgent + the paper. Open issue #17 (dropdown clicks fail) is exactly the failure browser-use built menu-reopen healing for.

### What V1.5 (EugeneVuong/netgent) already has
- Playwright async, layered `src/{adapters,agents,core,engine,...}`, Pydantic `WorkflowSchema` (`extra="forbid"`), `{{param}}` resolution, static validation (`WorkflowRunner.validate()` — schema + action-registry + signature binding), tests + CI, browser/shell workflow types (ping/iperf/ndt first-class).
- **A working mid-run agent repair loop** (`src/agents/subagents/browser/execute/agent.py`): on action failure, capture `{state, action_index, completed prefix, error}`, hand the *live page* to a browser-use agent with "do not restart from the beginning," compile the recovered continuation, merge prefix + continuation. **This is ahead of Skyvern (TODO) and workflow-use (dead code).** Missing: cheap heal levels below the agent, and write-back/persistence of the fix.
- **`evolution.py`** — cross-attempt learning: accumulates success/error action counts across generation attempts and folds them into the prompt ("best known action sequence… actions that correlated with errors…"). Novel; none of the surveyed projects have it.
- **Two regressions**: (1) `gen_workflow()` emits a single `always_true` state with a flat action list — **the NFA is gone**, discarding the paper's central contribution; (2) `generate_selectors()` computes a sophisticated fallback ladder then `return selectors[0]` — everything else is discarded. Production consequence in netgent-workflow's Twitch workflow: `"selector": "button.cikFpu"` (styled-components hash), `"selector": "div"` (matches thousands, silently clicks the first), hardcoded `href="/hasanabi"`. Guaranteed to break, mostly *silently*.
- `check_url` is exact string equality — breaks on any tracking param.

## Part 2 — Comparable systems: key mechanisms

| Axis | Skyvern | Stagehand | browser-use | workflow-use | Healenium | Crawljax | NetGent now |
|---|---|---|---|---|---|---|---|
| Element identity | content hash of normalized subtree | absolute index XPath | **5-level hash cascade** | selector-strategy ladder | root→node path + LCS | XPath into stripped DOM | single CSS string |
| Ambiguity | >1 match ⇒ stop ✅ | first match | first match ⚠️ | first match ⚠️ | ==1 required ✅ | n/a | first match ⚠️ |
| Self-heal | Gen-2: LLM repairs generated code | **heal + write-back** ✅ | cascade, no write-back | dead code ⛔ | **persist + review + negative cache** ✅ | n/a | agent repair, no write-back |
| State identity | — | url+instruction | `PageFingerprint` | — | — | **pluggable normalizer pipeline + fuzzy hash** ✅ | detector conjunction |

- **Stagehand** ([browserbase/stagehand](https://github.com/browserbase/stagehand)) — the single highest-value mechanism found: `takeDeterministicAction()` → on failure, re-run inference from the action's own `description`, **freeze method/arguments, swap only the selector**, then `refreshCacheEntry()` **writes the heal back** — the cache converges instead of rotting. Also: `act(string)` (LLM) vs `act(Action)` (pure Playwright) as one verb with two determinism levels; cache keys on `variableKeys` not values, with normalized URLs. Traps: proceeds after selector-wait timeout; replays cached `extract` results (stale data reported as success).
- **browser-use** ([browser-use/browser-use](https://github.com/browser-use/browser-use)) — the healing cascade to copy: EXACT hash (parent tag path + sorted STATIC_ATTRIBUTES allow-list (~45 entries) + ax_name) → STABLE (dynamic class tokens filtered) → XPATH (shadow-transparent, iframe-bounded) → AX_NAME → ATTRIBUTE. Plus: recorded step-interval pacing on replay; redundant-retry elision; dropdown-reopen healing without consuming a retry; never replaying `extract` from cache; superb failure diagnostics. **They deleted their CSS-selector generator entirely** — semantic identity + fresh-snapshot index won. Gaps: no agent fallback in replay, no write-back, first-match-wins.
- **workflow-use** ([browser-use/workflow-use](https://github.com/browser-use/workflow-use)) — most directly comparable ("Deterministic, Self Healing Workflows"). Copy: the compile pipeline (CapturingController snapshots selector map before each action; deterministic converter preferred over LLM; `_validate_workflow_quality()` fails on residual agent steps; pattern-based variable identification with no LLM); the look-ahead readiness gate (resolve *next* step's selector after each step — cheap state assertion + settle wait); `target_text`-primary semantic identity with legacy-marked css/xpath. ⛔ Their headline self-healing is **70 lines of commented-out dead code** behind unreachable `if`s.
- **Healenium** ([healenium/healenium-web](https://github.com/healenium/healenium-web)) — the persistence/review story: learn-on-success (re-save element path on every successful find, not just heals); LCS-over-ancestor-path scoring with **score-cap 0.6**; the acceptance gate — **exactly one match AND not already claimed this run**; heals persisted to Postgres with before/after screenshots, human approve/reject, rejections become a **negative cache**; per-step healing opt-out.
- **Skyvern** ([Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern)) — Gen-2 "Code 2.0" is the closest analogue to NetGent V2's compile idea. Copy: cache key as Jinja template over params → domain → site-platform fallback (one artifact per ATS, not per customer); page-readiness gate before every cached action (1s delay + networkidle + loading-indicator + DOM-stable — shipped because replay outruns the page); per-block `disable_cache`; never caching conditionals; version-pinned entries; status lifecycle (draft/published/pinned) + reviewer. Avoid: compiling to Python source (they need `_llm_fix_broken_main_py` to repair their own codegen — NetGent's compile-to-data is the right call); Gen-1's `ORDER BY created_at DESC` cache poisoning; 597 KB `block.py`.
- **Crawljax** ([crawljax/crawljax](https://github.com/crawljax/crawljax)) — the reference answer for **state identity as pluggable policy**: a condition-gated normalizer pipeline (strip scripts/styles, mask dates/regexes, exclude XPath subtrees like ads/badges, optionally tags-only template skeleton), then exact equality on normalized DOM, then fuzzy (TLSH/Levenshtein/RTED/visual) near-duplicate detection with distance bookkeeping. URL plays **no part** in state identity. Plus `Invariant`s checked on every transition. Avoid: their O(n²) hash/equals-contract violation (use an LSH index) and their fallback-free XPath element re-identification. Academic grounding: Yandrapally et al. ICSE 2020 near-duplicate classes — **ND2 (same template, different data) is exactly NetGent's case**.

## Part 3 — Copy / avoid (prioritized)

**Copy:**
1. **7-level element-identity ladder** (browser-use L1–L5 + Healenium LCS-tree at score ≥0.6 + agent as L7 with frozen method/args) — and stop discarding `generate_selectors()`'s ladder; persist it all, cap runtime attempts by time budget.
2. **Ambiguity rule**: accept only exactly-one-match AND not-already-claimed. First-match-wins is NetGent's most dangerous current behavior (silent wrong clicks).
3. **Heal write-back + learn-on-success + negative cache + review artifacts** (Stagehand + Healenium). Alarm when an edge's heal_count crosses a threshold.
4. **Cache keys**: variableKeys not values; Jinja-template → domain → site-family; normalized URLs; version pins; config-signature namespace; status lifecycle.
5. **Layered state identity** (Crawljax): url_template + PageFingerprint → declarative normalizer policy per site → exact → fuzzy near-duplicate → new state. Store raw AND normalized DOM so policy changes don't invalidate the cache. Check state *distinctness at compile time* (fixes the Twitch collision class of bug).
6. **Runtime mechanics**: page-readiness gate; look-ahead next-step assertion; recorded-interval pacing (realistic timing is the *point* of this project); redundant-retry elision; never cache extraction; per-step `allow_healing`; structured strategy-attempt diagnostics; cacheStatus HIT/MISS telemetry (hit rate is the paper's headline metric).
7. Keep V1.5's **evolution.py** and the metaclass action/trigger registry.

**Avoid:**
1. CSS-selector generation as primary identity (two teams independently abandoned it).
2. First-match acceptance; advisory (log-and-pass) semantic assertions.
3. Healing as TODO/dead code — V1.5's repair loop is ahead of the field; finish it (write-back), don't let it decay.
4. Compiling to code instead of data.
5. Linear-script regression — **don't lose the NFA**; the paper's robustness/efficiency claims live in the multi-state structure.
6. Raw URLs in state keys; exact-equality `check_url`.
7. Defining the deterministic action set by string-name subtraction from browser-use (V1.5's `EXCLUDED_BROWSER_USE_ACTIONS` already exposed to upstream renames — define the set positively in the registry).
8. Silent unresolved `{{placeholders}}` — make them a hard `validate()` error.
9. Vendor heuristics in core (browser-use has literal Guidewire selectors in agent/service.py — the menu-reopen *idea* is great, put it in per-site recovery rules).

## Suggested V2 artifact shape

Per **edge**: `{version, state_id, edge_id, intent_nl, description, method, arg_template, element_identity: {element_hash, stable_hash, xpath, css_ladder[], ax_name, ancestor_path_with_attrs, frame_id}, precondition, postcondition, variable_keys[], allow_healing, heal_count, recorded_step_interval}`.

Per **state**: `{url_template, normalized_dom_hash, tlsh, element_count, raw_dom, normalized_dom, normalizer_policy_id, dist_to_nearest, nearest_state_id}`.

Thresholds with empirical grounding: tree-similarity accept ≥ **0.6** (Healenium), text fuzzy ≥ **0.8** (workflow-use).

## The five findings that matter most

1. **V1.5's agent-repair loop is ahead of the field** — workflow-use commented theirs out, Skyvern left theirs a TODO. It lacks the cheap deterministic levels below it and write-back/persistence after it.
2. **Stagehand's heal-with-write-back is the single best mechanism surveyed** — one LLM call repairs the cache permanently; everything else rots.
3. **Element identity is NetGent's weakest component and fails silently** (`selectors[0]` → `"div"`, `button.cikFpu` in shipped workflows).
4. **State identity must become a pluggable policy** (Crawljax normalizers + fuzzy hashing), enabling compile-time distinctness checks.
5. **Don't lose the NFA** — V2 should be V1's NFA on V1.5's platform, not V1.5's linear scripts with better selectors.
