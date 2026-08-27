# Decision: anchored states + scoped ε-interrupts (2026-08-27)

**Status:** implemented (`2c57466`, `7c6a21f`, `1c2c949`). Decided by Manni in-session;
to be reviewed with Eugene/Arpit alongside the deferred question in §4.

## 1. States must carry an anchor

The compiler now anchors every state (where expressible) on **the next edge's target
element**: `s_k` gets `selector_visible(<locator of t_{k+1}'s action>)` in addition to any
URL condition. The executor's per-edge contract is unchanged (dispatch → await target
conditions); recognition simply stopped being vacuous — 3/24 guarded states became 9/17 on
the same task.

- Rationale: an unguarded state recognizes in 0 ms, so edges fired into races; every fixed
  sleep the agent inserted was "a trigger that couldn't be expressed"
  (browser-layer-design.md §3). Recognition timeout is now a meaningful per-edge drift
  signal (the healing ladder's entry point).
- Known conflation, accepted for now: the anchor is a *proceed*-condition, not an
  *identity*-condition. Identity anchors (page-distinctive elements, distinctness-checked)
  remain open — see OVERVIEW §7.1.3.
- Conservative translation: only single-step `locator(css)` and `get_by_role(role, name=…)`
  chains become anchors (`role=…[name="…" i]` — Playwright selector syntax, which the
  trigger engine already evaluates). Anything else keeps an open gate, never a wrong guard.

## 2. Pop-ups are scoped, bounded interrupts (ε-sweep)

`Interrupt {state, resolve[], scope[], max_fires}` on the Workflow. The interrupt state's
conditions are its anchor; `resolve` is a chain of ordinary one-atomic-action transitions
validated to start at that state; the executor sweeps in-scope anchors **between**
control-program nodes, resolves on a hit, verifies the pop-up went away, re-verifies the
interrupted state, and resumes the program.

This implements M3's "pop-ups are states reached by ε-transitions; resolution is an
ordinary transition back", operationalized as the run-side spec's "sweep in-scope ε-edges".
Three commitments keep it inside the formalism:

1. **`max_fires` is mandatory** (default 3) — the executed run stays statically bounded:
   `|program| + Σ max_fires × |resolve|`. Same red line as `Repeat.max_iterations`.
2. **`scope` is explicit and non-empty** — in-scope ε-edges, never global-by-omission.
   The compiler scopes an interrupt to the states of the page it was observed on.
3. **Dwells ≥ 3 s compile to `Repeat(wait 1 s × N)` self-loops**, so sweeps run between
   atomic actions — an interrupt never splits one. (Letter-of-M3 note: `wait(t)` stays in
   the atomic action set; slicing is a compilation choice, not a schema change.)

Interruption steps are classified out of the trajectory by reasoning-text heuristic
(ads/pop-ups/cookies/consent — deliberately not bare "skip"); upgrading this to an explicit
`is_interruption` flag on `AgentDecision` is planned once the explore agent is free.

Formal reading: the executed language is the word interleaved with in-scope bounded
interrupt resolutions — `t1 · I? · t2 · I? · …`, still a bounded regular expression.
M2/M3's "the word fully determines the run" is relaxed to this; recorded here as the
justification the design-review requires.

## 3. Consequences

- A replay that gets **no** ad walks the word untouched; an ad striking **mid-dwell** is
  skipped mid-dwell. The linear-word failure (youtube-session t15, 2026-08-25) is closed.
- Traffic attribution: an interrupt's traffic lands on its own resolution edges (named
  ε-state), not smeared into a `wait` edge.
- Recognition failures moved earlier and got typed: a missing next-element fails the
  *prior* edge's recognition with the unmet condition named (see
  tests/integration/test_validation_agent.py).

## 4. Deferred: reactive (word-free) execution

Proposal on hold (Manni, 2026-08-27): drop the word; executor tracks its graph node and
fires whichever in-scope trigger activates. Would need: sibling-guard exclusivity checked
at compile time, per-edge fire caps, accept_states becoming load-bearing, and a T3
reconnection story for observationally-identical states. Overturns M2/M3 decision #4
("no determinization needed") — requires its own record and an Eugene/Arpit conversation.
Nothing implemented today forecloses it: anchors, interrupts, and bounded repeats are all
reused unchanged by a reactive executor; only the word's authority changes.
