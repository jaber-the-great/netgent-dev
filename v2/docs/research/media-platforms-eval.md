# Media-platforms eval — does the YouTube media-watch pipeline generalize?

**Date:** 2026-09-02. **Branch:** `pr8-plus-scaffold` (PR #8 media-observation work + scaffold).
**Setup:** single-run pipeline per site (`netgent generate … --max-steps 30 --allow press
--model claude-code:sonnet`), then zero-LLM replay of any compiled artifact. One retry per
failed exploration. Raw logs/trajectories/probes under `/tmp/media-eval/<site>/`. Note the
orchestrator itself re-explores once when the judge rejects a run, so one CLI invocation can
contain two explorations; "attempt" below means one CLI invocation.

## Scoreboard

| Site | Explore | Verify | Compile | Zero-LLM replay | Root cause class |
|---|---|---|---|---|---|
| Vimeo | ✗ (both attempts) | never ran | — | — | explorer decision + site-specific |
| Twitch | ✗ (both attempts) | NOT achieved (high conf.) | — | — | site-specific (stream never attaches) |
| Dailymotion | ✓ 16 steps | achieved (medium conf.) | 16 t / 15 s | **✓ pass** (fidelity caveat: replay dwelled on a 15 s pre-roll ad) | — |
| SoundCloud | ✗ (both attempts) | NOT achieved (medium conf.) | — | — | observation (detached audio → no MEDIA line) |
| Internet Archive | ✓ 13 steps | achieved (high conf.) | 14 t / 13 s | **✗ fails at first edge** (s1 `selector_visible` unmet) | compiler/anchor (truncated name → exact-match trigger) |

Bottom line: the pipeline fully generalizes to exactly one of five sites (Dailymotion).
Archive is one compiler bug away from passing. SoundCloud is one observation gap away from a
plausible pass. Vimeo is an explorer-policy failure. Twitch is blocked by the site itself.

---

## Vimeo — exploration failed twice, nothing compiled

- **Attempt 1:** 9 steps (goto + 8), stopped: explorer declared itself stuck. **Attempt 2:**
  8 steps, same outcome. The judge never ran (the orchestrator aborts when the explorer itself
  reports failure).
- **MEDIA line:** present — three `MEDIA: video PLAYING at 0:00 [muted]` lines from the
  homepage's autoplaying marketing videos (noise, not the task's player).
- **Iframe/shadow:** none on attempt 1; attempt 2 accidentally opened two video-preview modals
  whose players are Vimeo-player **iframes** (`|IFRAME 1|`/`|IFRAME 2|` headers appeared).
- **Pop-ups:** no dialogs; the self-inflicted preview modals could not be closed (Escape
  pressed on the wrong target; no close button in the observation).
- **What actually happened:** the logged-out vimeo.com homepage is a SaaS landing page with
  **zero `<input>` elements** (probe confirmed). Search lives behind the "Watch" nav link or at
  `vimeo.com/search?q=…` (probe: loads fine, 24 video links). The explorer fixated on an
  unnamed header link `[52]`, clicked it three times across scrolls, and never once tried the
  visible `a "Watch"` element `[62]`. With `goto` not in the allowed action set, it also could
  not navigate to `/search` directly.
- **Root cause:** **explorer decision** (fixation on one unnamed element, no
  try-something-different pressure after repeated no-ops), aggravated by **CLI/config** (`goto`
  not allowed, so URL-level recovery was impossible) and **site-specific** UI (search hidden
  from logged-out visitors).

## Twitch — exploration failed twice, nothing compiled

- **Attempt 1:** hit `max_steps=30`. Reached `/monstercat` via search (cookie/consent popup
  dismissed at step 1, an overlay dismissed at step 5), then spent **25 consecutive steps**
  (click / space / `k` / overlay hunting) against `MEDIA: video PAUSED at 0:00`. The `m` press
  at step 24 landed — reading became `PAUSED at 0:00 [muted]` — so mute worked; play never did.
- **Attempt 2:** first internal exploration claimed success in 13 steps; the judge rejected it,
  correctly — *"the video player never entered a PLAYING state … the monstercat channel was
  OFFLINE per the page text"* — and the automatic re-exploration gave up at step 10.
- **Iframe/shadow:** none — Twitch's player is a plain in-page `<video>`.
- **Probe finding (the real cause):** loading `/monstercat` read-only shows LIVE badges in the
  DOM but the `<video>` has **`src=""` and `readyState=0`** — the player never attached a
  stream. Twitch's player fails stream initialization in this automation environment (most
  likely its client-integrity/bot check; Patchright stealth passes DOM-level detection but not
  stream delivery), then falls back to "Monstercat is offline." placeholder text. No amount of
  clicking can play a video with no source.
- **Root cause:** **site-specific** (stream delivery blocked in the automated browser).
  Secondary **observation** gap: the MEDIA line renders "no source ever loaded" identically to
  "paused at 0:00", which is what let the explorer burn 25 steps toggling play on a dead
  element. Reporting `readyState`/has-src would have turned this into a 5-step honest failure.

## Dailymotion — full pass (with a replay-fidelity caveat)

- **Exploration:** 16 steps, success. Cookie consent dismissed (step 2). One detour: clicking
  the results-page "Videos" filter bounced to the homepage; the explorer recovered by
  re-searching (steps 7–10). No ad appeared, so no skip-button branch was ever observed.
- **MEDIA / frames:** the player is inside an **iframe** (`|IFRAME 2| Dailymotion video
  player`, plus Google ad iframes). MEDIA lines tracked it throughout; the in-iframe Mute click
  landed (step 13→14: `PLAYING … [muted]`, Mute button `[checked]`). Final:
  `video PLAYING at 0:19 / 104:51 [muted]`. No shadow DOM.
- **Verifier:** achieved, medium confidence; no unmet points.
- **Compile:** 16 transitions / 15 states; repeats `t2_dwell×2` and `t14_dwell×14`
  (the watch dwell); **no interrupts** (nothing to learn them from) and **no `media_playing`
  gates** — trigger types are only `selector_visible` + `url_matches`.
- **Replay: pass.** All edges ok, trigger latencies 0–637 ms. Per-edge media: `PAUSED at 0:00`
  through search → `PLAYING` after the result click → `[muted]` after the mute edge → dwell.
- **Caveat:** the replay's media readings show `PLAYING 0:00–0:11 / 0:15 [muted]` — a
  **15-second pre-roll ad**, not the 104:51 video from exploration. The workflow "passed"
  because no anchor checks media duration/identity, and the watch dwell counted ad time as
  watch time. Two latent breaks: a skippable ad would stall the run (no skip interrupt was
  compiled), and the network trace records ad traffic labeled as video-watching. This is the
  interrupt-coverage gap: single-run exploration can't learn pop-ups/ads it never saw.

## SoundCloud — exploration failed twice, nothing compiled

- **Attempt 1:** hit `max_steps=30`. **The MEDIA line never appeared once in 31 steps** —
  `media: None` on every record. The explorer actually got the track playing (it read
  "1:01 / 2:00:00" from timeline *text*) but had no cheap way to confirm play or mute state, so
  it spent the budget clicking candidate mute buttons and re-verifying via text.
- **Attempt 2:** first internal exploration (20 steps) was rejected by the judge — *"no
  evidence the track actually started … no MEDIA TIMELINE showing position advancing"* — and
  the re-exploration died on the stuck-detector (3 no-change steps: the "Play current" button
  label never visibly changed after clicks).
- **Pop-ups:** cookie banner (dismissed) plus a **sign-in modal iframe** that shrugged off
  several Escape presses and cost ~5 steps in attempt 1.
- **Probe finding:** after clicking play on a track page, the DOM contains **0 `<audio>` and 0
  `<video>` elements**. SoundCloud drives playback through a detached `new Audio()` (never
  inserted into the DOM), so the snapshot walker — which only visits DOM-attached nodes —
  cannot see it. `observeMedia` is fine; the element simply never crosses its path.
- **Root cause:** **observation (walker/serializer)** — invisible-to-the-walker media breaks
  the explorer's act→observe feedback loop for play and mute. Site-specific overlay friction
  was secondary. This class covers any Web-Audio/detached-element player.

## Internet Archive — explored and compiled cleanly, replay fails on edge 1

- **Exploration:** 13 steps, success, no retry needed. Plain HTML5 `<video>`, **no iframe, no
  shadow DOM**. Play landed (step 9→10 `PAUSED`→`PLAYING`), mute landed (step 10→11
  `[muted]`, "sound is off. click for sound." overlay in the observation). Final:
  `video PLAYING at 0:19 / 90:07 [muted]`. No pop-ups.
- **Verifier:** achieved, high confidence.
- **Compile:** 14 transitions / 13 states; repeats `t5_dwell×2`, `t12_dwell×14`; **one
  `media_playing` gate** on s11 (`playing: true, min_duration_s: 120`) — the media-observation
  work is reaching artifacts.
- **Replay: fail at the first edge.** `t1: goto` succeeds, then `state 's1' not recognized
  within 10000ms; unmet conditions: ['selector_visible']`. The run never reaches the
  media-gated states.
- **Root cause (probe-confirmed): compiler/anchor.** s1's anchor is
  `role=link[name="Web icon An illustration of a" i]` — an accessible name **truncated by the
  serializer** mid-phrase. The trigger compiles to Playwright *selector-engine* syntax, where
  `[name="…" i]` is an **exact** (case-insensitive) match → **0 matches** on the live page. The
  corresponding *action* locator `get_by_role("link", name=…)` uses **substring** matching →
  1 match, which is why the same element worked during exploration. The trigger and the action
  disagree on name semantics, and any truncated name makes the trigger unsatisfiable. Fully
  deterministic; a replay re-run is pointless. Generic: it will break every compiled anchor
  whose accessible name exceeds the serializer's cap.

---

## Generic vs. site-specific

**Generic (would bite on other sites):**

1. **Trigger/action name-semantics mismatch on truncated accessible names** (Archive). Exact
   `[name="…" i]` triggers vs. substring `get_by_role` actions — any long aria-label breaks
   replay at anchor time.
2. **Detached/JS-managed media invisible to the DOM walker** (SoundCloud) — no MEDIA line, no
   feedback loop for play/mute/seek on Web-Audio-style players.
3. **MEDIA line can't say "no source loaded"** (Twitch) — `readyState 0, src=""` reads the
   same as an ordinary pause, so explorers burn whole budgets toggling dead players.
4. **Explorer fixation with no recovery policy** (Vimeo) — repeated no-op actions on the same
   element without escalating to alternate nav or direct URLs (`goto` isn't even allowed by
   default).
5. **Single-run interrupt blindness** (Dailymotion, latent) — an ad/pop-up not seen during
   exploration produces no interrupt; the replay either stalls on it or silently records its
   traffic as task traffic.

**Site-specific:** Twitch's stream-delivery/integrity block (browser-profile problem, not a
pipeline problem); Vimeo hiding search from logged-out visitors; SoundCloud's sign-in overlay;
Dailymotion's ad variability between runs.

## Three highest-value fixes, ranked by sites unblocked

1. **Make compiled `selector_visible` anchors use the same name semantics as action locators
   (substring/regex on the — untruncated — accessible name), or stop truncating names fed to
   the generator.** Immediately unblocks Archive's replay, and de-risks every future compile:
   it's a determinism bug in the artifact itself, the product's core guarantee. Cheapest fix
   of the three.
2. **Enumerate live `HTMLMediaElement`s via CDP (attached or not) and extend the MEDIA line
   with load state (`readyState`/has-source).** Unblocks SoundCloud (restores the act→observe
   loop for play/mute) and converts Twitch's 25-step play-toggling spiral into a fast, honest
   "stream never loaded" failure; benefits every audio-first platform.
3. **Explorer stuck-recovery policy: after N no-change repeats on the same element, forbid it
   and escalate — try alternate nav links, then a direct URL (add `goto` to the default allow
   set for exploration).** Unblocks Vimeo (the `/search?q=` URL works today) and shortens
   every fixation loop observed in this eval.

Twitch stays blocked until the browser profile passes Twitch's stream-integrity checks — an
investigation for the stealth/profile layer, not the pipeline.

---

## After fixes 1 and 2 (2026-09-02, branch `pr8-plus-scaffold-1`, commits `277cec5` + `fba7fc7`)

Same protocol as above (single-run `generate --max-steps 30 --allow press --model claude-code:sonnet`,
then zero-LLM `run`; one retry per failed exploration). Raw material under `/tmp/fix-eval/<site>/`.

| Site | Explore | Verify | Compile | Zero-LLM replay | MEDIA lines observed |
|---|---|---|---|---|---|
| Internet Archive | ✓ 10 steps | achieved (high) | 12 t / 11 s, 2 `media_playing` gates | ✗ at **t6** (was t1): t1–t5 ok, s1 recognized in 24 ms | `video PLAYING at 0:32 / 90:07 [muted]` |
| SoundCloud, attempt 1 | ✗ 11 steps (stuck) | — | — | — | none (playback never started: 3 clicks on an inert "Play current") |
| SoundCloud, attempt 2 | ✗ 29 steps (gave up: mute control not found) | — | — | — | **`audio (detached) PLAYING at 0:09 / 120:00`** from step 15, advancing to `3:05` at step 29; readings on 15 of 30 steps (was 0 of 31) |
| Twitch | ✗ 13 + 13 steps (two internal explorations, both ended by the explorer's own `done`) | NOT achieved (high) | — | — | `video NOT LOADED (no source)` from step 4; `video (detached) PAUSED at 0:21 / 0:30 [muted]` (the offline promo loop) |

- **Fix 1 (anchors carry the action's locator chain):** Archive's first edge, the one that failed
  before, now recognizes in 24 ms; edges t1–t5 all pass (latencies 0–155 ms, 7.1 s for the
  results-page wait). The replay fails at t6 in both of two runs: s6 is anchored on the player's
  `link "Click for sound"`, whose box is 30×0 px on this page (present, `display:block`, never
  visible over 40 s of polling). The explorer's click on it at step 6 landed only through the
  dispatcher's JS-click fallback, so "its element is visible" was never true even during
  exploration. Same shape at s8 (`link "Click to mute"`). New generic gap, distinct from the
  name-semantics bug: **an anchor derived from a click that needed the JS fallback (a
  Playwright-invisible target) is unsatisfiable**; the walker lists 30×0 elements (it drops only
  0×0) while Playwright's visibility needs both dimensions > 0.
- **Fix 2 (CDP media enumeration + load state):** SoundCloud's detached `new Audio()` is read
  (attempt 2, 15 readings, position advancing 0:09 → 3:05 across steps); the explorer used it
  ("confirmed PLAYING via MEDIA line"). The remaining failure is explorer-side: it could not
  find the volume/mute control in the sticky player bar and scroll-thrashed for 12 steps.
  Twitch's dead player reads `NOT LOADED (no source)`; each exploration stopped at 13 steps by
  the explorer's own decision citing that line (before: 30-step budget exhausted, then 13 + 10).
- **Cost of the media read** (SoundCloud, 12 frames): 100 ms while a player is playing (cached
  re-resolve), 1.2 s when nothing is playing (one `Runtime.queryObjects` heap walk per target —
  a full GC); 7.7 s before the walk was rationed to each target's top document.
- **Regression:** forms sweep `netgent eval stress sweep --model claude-code:haiku`: **19/21** (the
  baseline; the two unverified forms are the known broken fixtures, forms 8 and 12), 167 LLM calls,
  1919 s wall.
