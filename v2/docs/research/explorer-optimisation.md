# Explorer optimisation — measured A/B record (2026-08-26)

What was changed in `agent/explorer/`, `agent/llm.py` and `browser/dom/serializer.py` on branch
`v2/explorer` (off `eugene/v2-scaffold` @ `b7b2349`), why (the four research documents in this
folder: [prompting](browser-agent-prompting.md), [memory](browser-agent-memory.md),
[tool calling](browser-agent-tool-calling.md), [papers](web-agent-papers.md) §5), and — the
point of this file — **what each change measured**. Every arm is a real run of
`netgent eval stress` with `anthropic/claude-haiku-4-5-20251001`, 3 repetitions, from an
isolated `git worktree` of the arm's commit so later edits could not leak into a running arm.

Five negative results are recorded here on purpose — each a recommendation of the research docs
(or of the convergent design they describe) that the A/B refuted: off-screen magnitude markers,
an explicit "nothing changed" line, `go_back` in the default kind set, the observation diff and
working-memory fields as defaults, and action batching as a default. Each was reverted or made
opt-in before the next stage, and the winning configuration is what the branch ships.

## 1. Method

| | |
|---|---|
| Evals | `netgent eval stress challenge` (browser-use's 15-card challenge game; score the page reports) and `netgent eval stress sweep` (21 forms on `forms-comparison.html`; forms verified by a success marker the page shows, never the agent's self-report) |
| Model | `anthropic/claude-haiku-4-5-20251001`, temperature 0 |
| Repetitions | 3 per arm; per-run results are listed, not just means (n=3 is noisy) |
| Isolation | one `git worktree` per arm under `/tmp/netgent-<arm>`, own `uv` venv; results in `/tmp/<arm>/stress/<kind>-dom-r<i>/result.json` (raw JSON incl. per-step tokens from `LangChainLLM.calls`) |
| Wall time | arms ran concurrently on one machine (2–3 browser+LLM runs at a time); wall seconds are indicative only. Scores, steps and tokens are unaffected by concurrency. |
| Tokens | `input_tokens` is the provider's total (cache reads/writes included); `in/step` = input tokens ÷ LLM calls |

Arms (commits on `v2/explorer`):

| arm | commit | what it adds |
|---|---|---|
| baseline | `b7b2349` | the base commit |
| stage1 | `36a3fcd` | viewport scrollback + per-element off-screen markers + page magnitudes; prompt rewrite; system/human message split with `cache_control`; declared `${param}` binding |
| stage1b | `1300085` | stage1 minus the off-screen markers and page magnitudes (count-based POSITION) |
| stage2 | `96cf289` | typed `StepRecord` memory, fold-at-`note()` compaction, `evaluation/memory/next_goal`, observation diff with an explicit "nothing changed" line |
| stage3-first | `6867be7` | `done: bool`, coercion + retry ladders, opt-in hover/press/goto, value-aware diff (still with a "no change" claim) |
| stage3b | `e58fadc` | inline child text merged into the parent block; **no** explicit "nothing changed" claims anywhere |
| stage3c | `c31036f` | bounded action batch, run with `NETGENT_MAX_ACTIONS=4` (default stays 1) |
| final | `ea498c9` | stage3c + `go_back` opt-in (the challenge arms above never used `go_back`, so their numbers hold for this commit) |
| shipped defaults | (next commit) | the final code with `NETGENT_OBS_DIFF` and `NETGENT_MEMORY_FIELDS` **off** by default and batch 1 — i.e. exactly the *final, flags-off* arm below |

## 2. Results

### 2.1 Challenge (15 cards, `--max-steps 60`)

| arm | result | mean | steps | LLM calls | input tok/run | in/step | out/step | cache read | wall s |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 4/4/5 | **4.33**/15 | 14 | 12 | 43,654 | 3,638 | 99 | 0 | 21 |
| stage1 | 1/4/5 | **3.33**/15 | 44 | 42 | 211,305 | 5,031 | 105 | 0 | 64 |
| stage1b | 4/3/5 | **4.00**/15 | 28 | 26 | 122,066 | 4,635 | 100 | 0 | 44 |
| stage2 | 1/1/1 | **1.00**/15 | 5 | 3 | 14,039 | 4,680 | 134 | 0 | 13 |
| stage3-first | 1/1/1 | **1.00**/15 | 7 | 5 | 22,973 | 4,923 | 192 | 0 | 14 |
| stage3b | 5/5/5 | **5.00**/15 | 17 | 15 | 78,918 | 5,381 | 225 | 0 | 41 |
| stage3b, `NETGENT_OBS_DIFF=0 NETGENT_MEMORY_FIELDS=0` | 5/5/5 | **5.00**/15 | 34 | 32 | 165,000 | 5,100 | 137 | 0 | — |
| stage3c (batch 4) | 9/5/7 | **7.00**/15 | 41 | 36 | 222,599 | 6,183 | 236 | 0 | 113 |

Where each arm stopped (from the trajectories):

- **baseline** — every run died on the search card: `press` with `keys="Return"` (Playwright:
  *Unknown key*), then an index-less `press Enter` that changed nothing, three times → the
  `MAX_REPEAT=3` stuck stop at 11–16 steps.
- **stage1** — the agent no longer got stuck early, but 35 of 58 steps in run 0 were scrolls
  whose reasoning quoted the new markers verbatim (*"scroll down to see the slider task (index 19)
  which is 1.2 pages below"*, *"the observation shows we're 2.0 pages above the top"*). Run 0 then
  used `goto` to "start fresh", which reset the page's score to 1. This is AgentOccam's *aimless
  and repetitive scrolling* finding reproduced on our own agent — by a change the prompting doc
  recommended (S2/S3). **Reverted in stage1b**; `goto` became opt-in in stage 3.
- **stage1b** — back at baseline parity (4/3/5 vs 4/4/5) but still spending 2× the steps.
- **stage2 / stage3-first** — collapsed to score 1 in 5 steps: after clicking Start (score 0→1)
  the observation said `CHANGED SINCE LAST STEP: nothing changed on screen`, so the model re-clicked
  until the stuck stop. Root cause was two-fold: the walker only kept an element's *direct* text, so
  `Score: <span>1</span> / 17` rendered as `Score: / 17` and the digit was deduplicated away; and
  the memory doc's "soft no-progress nudge" (recommendation #6) turned that blindness into "the
  click did not register". The card's completion state is CSS-only (a border colour), so no DOM
  text change exists at all for that card.
- **stage3b** — inline child text is merged into the parent block (`Score: 1 / 17` is one text
  and its change surfaces under `NEW TEXT SINCE LAST STEP`), and no explicit "nothing changed"
  claim is made anywhere. 5/5/5: the search card now passes (`Return`→`Enter` coercion, `press`
  with an index targets the field), the date/time, checkbox and slider cards pass; every run then
  stalls on the **hover** card (the page does not register Playwright's hover) and the run ends at
  the stuck stop. The remaining cards (canvas captcha, iframe slider, scroll-inside-box, arrow keys,
  upload, details, dropdowns, contenteditable) were never reached.
- **stage3b with the diff and memory fields switched off** (the ablation arm) — also 5/5/5, stalling
  on the same hover card, at ~280 fewer input and ~90 fewer output tokens per step. On this
  benchmark the `*` markers / new-text section and `evaluation`/`memory`/`next_goal` buy nothing
  measurable; they cost ≈5% input and ≈40% output tokens per step. (Haiku fills `memory`, leaves
  `evaluation` empty on most steps.)
- **stage3c (batch 4)** — 9/5/7. Batching lets the agent get past the hover card in two of three
  runs (a `hover` + `press` / `click` batch on the same card registers where a lone hover does not) and
  then complete the search, date/time, slider, iframe slider, arrow-key and upload cards; misses are
  hover, canvas captcha, scroll-inside-a-box, details, dropdowns, contenteditable. Each batch item is
  one transition (41 steps from 36 calls). Run 1 hit the 60-step budget.

### 2.2 Sweep (21 forms, `--max-steps 30` per form, 1 retry)

| arm | result | mean | steps | LLM calls | input tok/run | in/step | out/step | cache read | wall s |
|---|---|---|---|---|---|---|---|---|---|
| baseline | 16/17/17 | **16.67**/21 | 160 | 203 | 605,723 | 2,984 | 102 | 0 | 428 |
| stage1 | 17/16/17 | **16.67**/21 | 146 | 190 | 724,916 | 3,809 | 103 | 0 | 358 |
| stage3b (killed after r1) | 17/9 | 13.0/21 | — | 240 | 1,098,000 | 4,570 | 195 | 0 | 622 |
| final, diff + memory fields on, batch 1 | 17/16/16 | **16.33**/21 | 260 | 307 | 1,417,784 | 4,613 | 214 | 0 | 858 |
| final, diff + memory fields on, batch 4 | 15/16/17 | **16.00**/21 | 318 | 340 | 1,847,757 | 5,435 | 219 | 0 | 925 |
| **final, diff + memory fields off, batch 1 (shipped defaults)** | 17/17/17 | **17.00**/21 | 163 | 212 | 817,318 | 3,861 | 107 | 0 | 383 |

Forms not verified: baseline r0 `[1, 2, 5, 7, 11]`, r1 `[5, 7, 11, 13]`, r2 `[5, 7, 11, 13]`;
stage1 r0 `[1, 5, 7, 11]`, r1 `[1, 2, 7, 11, 13]`, r2 `[5, 7, 11, 13]`; stage3b r0 `[1, 2, 7, 11]`,
r1 `[1, 2, 7, 11, 13–20]`. Forms 7 and 11 fail in every arm — the ceiling for this model, not the
prompt. Final arms: diff+memory r0 `[1, 2, 7, 11]`, r1 `[1, 2, 7, 11, 13]`, r2 `[1, 2, 5, 7, 11]`; batch 4
r0 `[1, 2, 5, 7, 11, 13]`, r1 `[1, 2, 7, 11, 13]`, r2 `[1, 2, 7, 11]`; flags-off r0–r2 `[1, 2, 7, 11]`
(the three final arms ran concurrently, so their wall times are comparable with each other but
not with the baseline).

**stage3b's sweep was the third negative result.** With `go_back` in the default kind set (the
convergent core, kept by AgentOccam) Haiku used it **41 times** across the sweep — *"I'll use
go_back to reveal form 14"*, *"try a different approach"* — against **0** uses in the baseline and
stage-1 arms, whose prompt listed the same kind. In run 1 a `go_back` navigated the sweep page to
`about:blank` and every later form failed (9/21). The sweep was stopped after run 1 (run 2 was at
form 11, on track) and `go_back` joined hover/press/goto behind `--allow` (commit `ea498c9`).
The input-token doubling (2,984 → 4,570 per step) is the longer prompt, the three full history
blocks and the diff/new-text lines, with no cache on Haiku — the final arms below measure how much
of it the diff and memory fields are responsible for.

**The final sweep answers that: most of it, and they lower the score.** With the diff and the
memory fields on, the sweep needs 307 calls / 1.42 M input tokens for 16.33; with both off it
needs 212 calls / 0.82 M for **17.00** — the best result of any arm, on the same commit. The extra
steps are the model acting on `*`-marked / NEW-TEXT lines and re-planning around its own
`memory` text; the 9 forms (`1, 2, 7, 11`) that fail are the same in every run of the flags-off arm.
**Batch 4 also loses on the sweep** (16.00, 340 calls): batched fills against a form that
re-renders after the first fill abort mid-batch, and the model re-issues them one by one — the
per-item guards work, but they cost the calls batching was meant to save. It wins on the
challenge (7.00 vs 5.00), where a `hover`+`press`/`click` batch on one card is what gets the
page to register.

**Shipped defaults follow the measurement:** observation diff off (`NETGENT_OBS_DIFF=1` to
enable), memory fields off (`NETGENT_MEMORY_FIELDS=1`), `max_actions_per_step=1`
(`--max-actions 4` for challenge-like tasks). The features stay in the code, tested, as opt-ins.

### 2.3 Observation size (zero-LLM, `netgent eval observation`, first page load)

| site | elements | base chars (~tok) | final chars (~tok) | Δ |
|---|---|---|---|---|
| forms (21 iframe forms) | 222 | 5,545 (1,386) | 5,863 (1,465) | +5.7% |
| challenge | 39 | 3,050 (762) | 3,586 (896) | +17.6% |
| todomvc-spa | 4 | 341 (85) | 395 (98) | +15.8% |
| youtube (home) | 14 | 706 (176) | 613 (153) | −13.2% |

Element coverage, naming and locator uniqueness are identical between base and final (the walker's
element rules did not change). The growth on a first load is the always-present POSITION line,
the `format=` hints and the merged inline text blocks (longer, fewer); on YouTube the alert-first
dedup against element names removes more than that adds. Per-step growth during a run is larger
(the scrollback slice, `*` markers and the change/new-text lines): challenge in/step 3,638 → 5,381.

### 2.4 Prompt caching

`cache read` is **0 in every Anthropic arm**. The message split (static system+task first, marked
`cache_control: ephemeral`; history + observation last) is in place and correct, but Claude Haiku
4.5's minimum cacheable prefix is **4096 tokens** (1024 on Sonnet-class models), and our prefix
(≈1,350-token system prompt + task + the ~450-token tool schema) is ≈2,000. The layout pays only
on a Sonnet/Opus explorer, or if the prefix grows past 4k. `usage["cache_read_tokens"]` /
`cache_creation_tokens` are recorded per call so this is checkable, not assumed.

## 3. Per-axis outcome

| axis | shipped | measured effect | rejected (measured) |
|---|---|---|---|
| **observation** | one viewport of scrollback kept (the YouTube Skip band, `-vh ≤ y < -60`, verified by a fixture test and on the live watch page: 14 vs 30 elements dropped after one scroll); alerts first, element-name text deduped; `format=` hints on date/time inputs; password values never printed; inline child text merged; single-char state texts kept | challenge 4.33 → 5.00 (with stage 3); sweep 16.67 → 17.00; in/step +29% on the sweep (2,984 → 3,861) and +40% on the challenge, mostly the longer prompt with no cache on Haiku | per-element `(↓ N pages below)` markers and page-magnitude POSITION (scroll thrash, −1.0 on the challenge); any explicit "nothing changed" line (retry loops, −3.3); `*[index]` markers + `NEW TEXT SINCE LAST STEP` as a default (sweep −0.67 at +45% calls; kept as `NETGENT_OBS_DIFF=1`) |
| **memory** | `StepRecord` (kind, target name, outcome, error); fold-at-`note()` compaction so a sweep's cross-form memory survives the window; folds/notes always rendered, last 10 acted records, last 3 as blocks | sweep 17/17/17 with the same three forms failing every run (the baseline lost different forms per run) | `evaluation` / `memory` / `next_goal` as a default: +107 output tokens/step, no gain on the challenge, and with the diff −0.67 on the sweep (kept as `NETGENT_MEMORY_FIELDS=1`); writing the loop's no-progress verdict into the record |
| **action space / tool calling** | `done: bool` enforced alone; kind aliases, `[3]`/float index repair, Playwright key-name normalisation, index dropped on page-level kinds, `press` with an index; in-place parse retry with the validator's errors; `hover`/`press`/`goto`/`go_back` opt-in per task (prompt and schema narrowed together); bounded batch behind `max_actions_per_step` (default 1) | the search card that killed every baseline run passes; `goto` can no longer reset a page, `go_back` can no longer blank it; batch 4: challenge 5.00 → 7.00 | batch 4 as a default (sweep 16.00, +60% calls); `go_back` as a default (41 uses, one `about:blank`) |
| **prompt** | kind list fixed (`upload` present, `done` not a kind), observation legend, grounding, overlays/ads, dwell, dropdowns, positive scroll rule, PARAMETERS; ≈1,014 → ≈1,350 tokens | see observation row (confounded with it) | the "listed and actionable off-screen" markers the legend described |
| **parameters** | `AgentDecision.param` → `AgentStep.param` → compiler binds `${name}` structurally; literal sweep only on value fields / state conditions; warnings for unbound or mismatched params | YouTube run: `param=query` declared on the fill, `text: ${query}` in the artifact, no warnings, zero-LLM replay validated (8 edges) | substring abstraction inside locator names |

## 4. The YouTube case (Stage 4)

`netgent generate "Search YouTube for the query, open the first video result, skip the ad if
one plays, and watch the video for 10 seconds." --url https://www.youtube.com -p "query=lofi hip
hop" --trajectory /tmp/yt --max-steps 20 --model anthropic/claude-haiku-4-5-20251001`:

```
1. fill   — search box ← 'lofi hip hop'          (param=query)
2. click  — Search button
3. scroll — (results page)
4. click  — first result "Best of lofi hip hop 2021 …"
5. click  — Play
6. click  — Skip   ("An ad is currently playing (Factor75 …) with 'Skip' button visible")
7. wait   — 10 s
8. done   — success
[generate] compiled 8 transitions, 9 states; param query (default: 'lofi hip hop')
[validate] replay ok (8 edges) — ✓ validated: every edge replayed with zero LLM calls
```

The Skip button was observed and clicked on the watch page. Whether it would also survive a
scroll cannot be forced on the live site (ads are not deterministic and YouTube's player chrome
auto-hides at `opacity: 0`, which the walker rightly drops), so the geometry is pinned by
`tests/integration/test_batch_and_scrollback.py::test_skip_button_stays_observed_after_scrolling_one_page`:
a control 300 px above the viewport after one page of scroll is listed under the new policy and
dropped under `NETGENT_OBS_SCROLLBACK=0`.

## 5. A/B switches kept in the code

| env var | arm |
|---|---|
| `NETGENT_OBS_SCROLLBACK=0` | the old 60 px cut |
| `NETGENT_OBS_DIFF=1` | `*` markers / change line / new-text section (default off) |
| `NETGENT_MEMORY_FIELDS=1` | `evaluation` / `memory` / `next_goal` in the schema (default off) |
| `NETGENT_MAX_ACTIONS=N` | batch size for `eval stress` (agent/CLI: `max_actions_per_step`, `--max-actions`) |
| `NETGENT_IFRAME_HEADERS=0` | (pre-existing) no `|IFRAME n|` headers |

## 6. Not done, and why

- **Sticky/fixed elements always in view (prompting doc S7)** — moot: `getBoundingClientRect` is
  viewport-relative, so a fixed element is never above the cut.
- **Soft escalating stuck nudge (memory doc #6)** — measured harmful in two arms; the hard
  `MAX_REPEAT` stop stays.
- **JS-evaluate action** — decided against (tool-calling doc §6.4).
- **Second cross-run memory store / LLM summariser / raw-HTML observations / screenshots** — the
  memory doc's own "do not build" list.
- **Task-conditioned element re-ranking, state-conditioned prompt fragments (SteP), `simulate`
  node, pass^k validation** — pipeline-level items from the papers doc, outside this brief.
