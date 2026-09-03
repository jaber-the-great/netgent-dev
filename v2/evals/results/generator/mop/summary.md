# generator eval — tests/fixtures/mop

source: model claude-code:sonnet usage {'calls': 1, 'input_tokens': 30896, 'output_tokens': 29402, 'cache_read_tokens': 0, 'cache_creation_tokens': 30894, 'observation_chars': 54258, 'history_chars': 10}

| metric | value |
|---|---|
| draft_acceptance_rate | 80% (20 applied / 0 rejected / 5 degraded) |
| repairs_used | 0 |
| used_fallback | False |
| validated (witnessed accept) | True |
| transitions / interrupts | 12 / 1 |
| params | fast_forward_presses, fast_forward_time, initial_watch_time, second_watch_time, video_query |
| derived params | fast_forward_presses |
| param_recall vs planner | 100% |
| positional clicks | t4 |

## not applied

- `main[3].corroborated_by` (r10.s4.0) — degraded: a click on ('get_by_title', None) is not the spine step's shape
- `main[4].corroborated_by` (r1.s7.0) — degraded: a click on ('get_by_role', 'button') is not the spine step's shape
- `main[4].corroborated_by` (r2.s6.0) — degraded: a click on ('get_by_role', 'button') is not the spine step's shape
- `main[4].corroborated_by` (r10.s6.0) — degraded: a click on ('get_by_role', 'button') is not the spine step's shape
- `params[fast_forward_time]` — degraded: declared but referenced by no edge, target or count — dropped

## the agent's notes

- Runs 3, 5, and 13 recorded 0 steps (NOT achieved) and provide no step references, so they cannot be cited as ExcludedRun evidence per the schema; they are simply omitted from kept_runs. Run 3 drifted to a different video ('Come As You Are'), and runs 5/13 got stuck repeating a press on the same element 6 times — consistent with the fast-forward phase being fragile when the seek key stops landing.
- Runs 8 and 9 are 'scoped' with 0 steps (no exploration recorded) and are excluded from consideration entirely; kept only as evidence of declared values, per the harness's own note.
- Run 12 (achieved, 32 steps) was excluded: after 5 fast-forward presses it drifted via autoplay to a different video, then clicked 'YouTube Home' (r12.s17.0) and redid goto/search/click three more times before finally completing. This is a restart-and-retry pattern, not a single clean pass.
- The search-submission phase varies a lot across runs: some double-click the search button (runs 1, 4), some press Escape to close the suggestions dropdown (runs 2, 6, 12), some just wait (runs 7, 11), one presses Enter (run 10). None of these variants is common to all kept runs, so none was included on the main path beyond the single required search-button click; they are UI-settling noise, not task-required actions.
- Run 6 did not show an explicit 'Skip ad'/'Skip ads' button; instead the first load was a short muted preview and the agent clicked a 'Watch full video' thumbnail (r6.s5.0) to reach the real video. This was treated as a run-specific workaround, not corroboration for the skip-ad edge nor a genuine interrupt, and left off the main path.
- Run 2 and run 12 each needed an extra 'click Play' step (e.g. r2.s5.0) to actually start playback after the video-title click. Only run 2 (of the kept runs) needed this, so per the single-run-noise rule it was left off the main path.
- The video-selection click's locator ladder differs in *identity* across runs (different video titles/roles), but the structural rung consistently matched many candidates with the acted element always at index 0 in every run — this strongly supports treating 'first video result' as a positional selection (structural rung, nth=0) rather than a name-parameterized role rung.
- fast_forward_time has no direct 'seconds' witness anywhere in the recordings because it is never waited on directly — it is only realized through repeated 'l' presses. Per the derived-parameter convention, it is witnessed instead via the recorded seek+10s deltas on press steps (media_jump field), which also anchors the derived fast_forward_presses parameter (divide_by=10, ceil).
- Actual press counts per run only loosely track ceil(fast_forward_time/10): runs 4, 6, 7, 11 match exactly, runs 1 and 10 pressed one extra time, and run 2 pressed one fewer time than the ceiling — attributed to agents miscounting mid-task. The Repeat's `covers` list includes every press step actually recorded in each kept run (not just a fixed 3), so code can validate the derived count against the full recorded evidence.
