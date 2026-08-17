# NetGent v2 Browser Layer — Design Conclusion

Synthesis of three source-level deep dives into nine Playwright-adjacent browser layers, conducted
2026-08-17. Full findings with file:line citations:

- [browser-layer-A.md](research/browser-layer-A.md) — Notte (`notte-browser`), Agent-E, LaVague
- [browser-layer-B.md](research/browser-layer-B.md) — BrowserGym, AgentLab, WebArena
- [browser-layer-C.md](research/browser-layer-C.md) — Skyvern (`webeye/`), browser-use, Playwright native capture

## The three findings that shape everything

1. **NetGent's two core needs have no prior art.** None of the nine repos captures network traffic
   as a product (one sets `record_har_path` — nobody), and none has a condition-based wait
   primitive — every one synchronizes with fixed sleeps + `domcontentloaded`, failures swallowed.
   Triggers and capture are where NetGent invents; everything else is assembly from proven parts.
2. **Element identity is the load-bearing decision.** WebArena's ordinal IDs are non-replayable by
   construction; BrowserGym's `bid`s reset on navigation and require mutating the live page; only
   Skyvern's content hash (`sha256` of the element minus volatile fields) survives across runs.
   A compiled NFA needs: durable locator chain + element fingerprint, resolved at compile time,
   verified at run time, with ambiguity being a **compile-time error**.
3. **Capture is a construction-time contract.** Playwright's HAR/video/tracing are `new_context()`
   options that cannot be enabled later. Skyvern has a live bug proving the failure mode: its
   cdp-connect path logs a `har_path` that was never passed to `new_context`, so the HAR silently
   doesn't exist. One code path must build contexts, and a declared-but-absent capture must abort
   the run.

## Package structure

```
src/netgent/
├── core/                      # pure types — imports nothing but pydantic/stdlib
│   ├── actions.py             # the action IR (see below)
│   ├── triggers.py            # trigger predicates as structured, composable objects
│   ├── states.py              # states + NFA / compiled-workflow model
│   └── records.py             # per-edge run record + run manifest schema
├── browser/                   # imports core; NEVER imports an LLM SDK (enforce with a lint rule)
│   ├── pw.py                  # the single Playwright import chokepoint
│   ├── factory.py             # builds browser+context; owns the capture contract (CaptureBundle)
│   ├── session.py             # run lifecycle: owns factory output, executor, trigger engine
│   ├── executor.py            # action dispatch: registry + setup/handler/teardown per action type
│   ├── resolution.py          # locator-chain resolution + fingerprint verification (+ drift errors)
│   ├── triggers.py            # trigger evaluation engine (per-frame, records which conjunct fired)
│   ├── observation/           # DOM walking/serialization — compile-time heavy, run-time minimal
│   └── capture/               # CapturePlugin list: har.py, tracing.py, websocket.py, (pcap.py)
├── synthesis/                 # the LLM side; only package that knows a model exists (later)
└── sessions/                  # auth: login NFAs, storage-state minting + freshness probes (later)
```

Import rule (the property that makes `run` trustworthy): `core` imports nothing, `browser` imports
`core`, `synthesis` imports both. The browser layer must be importable and runnable with no model
provider configured — enforced by a test, not a convention.

## Decisions, with their evidence

### 1. Action IR: pydantic discriminated union, replayed by reflection — never `exec`

- Actions are pydantic models with a `Literal` type discriminator, auto-registered via
  `__init_subclass__`, unioned for parsing (Notte's pattern). JSON round-trip of the compiled NFA
  and a validating loader come free; one source of truth for the schema — the compile-time prompt
  schema is *derived* from these models (LaVague's three out-of-sync definitions is the anti-pattern).
- Locators are stored as **structured chains**, executed by whitelist reflection — WebArena's
  `parse_playwright_code`/`locate()` design, the single most transplantable piece found:

  ```json
  {"type": "click",
   "locator": [{"fn": "get_by_role", "args": ["button"], "kwargs": {"name": "Submit"}}],
   "fingerprint": {"role": "button", "name": "Submit", "tag": "button", "hash": "sha256:…"},
   "timeout_ms": 5000}
  ```

  BrowserGym re-inlines and `exec`s ~700 lines of action-library source per step — the
  counterexample. The compiler emits JSON; the runtime walks it; the whitelist is the security
  boundary.
- Keep WebArena's `is_equivalent` (NFA self-loop detection, replay diffing) and `action2str`
  (logs, dataset labels). Every action carries its own timeout; validate `timeout=0 → default`
  (Playwright treats 0 as infinite).

### 2. Element identity: resolve at compile time, verify at run time

- **Compile time (LLM present):** inject marks freely, show the model everything. Then resolve each
  chosen element into (a) an ordered candidate-selector list — role-based, test-id, attribute, css
  path, in that order; first `count()==1` wins at replay (Notte's `locate_element`) — and (b) a
  Skyvern-style content fingerprint. If the fingerprint is ambiguous on the page, disambiguate or
  refuse to emit the transition **while the LLM is still available**.
- **Run time (no LLM):** no injection, no marking, no page mutation — mutation contaminates both
  DOM and the network trace NetGent is recording. Resolve the chain, verify the fingerprint, act.
  Mismatch → typed `ElementDriftError` naming the NFA edge, never a silent mis-click.
- Per-snapshot sequential IDs (`B1`, `mmid`, `bid`) never appear in the compiled artifact.
  Frame paths are encoded in the stored locator so replay traverses iframes deterministically;
  OOPIF-safe scoping per browser-use (`(frame_identity, backend_node_id)` collisions are real).

### 3. Triggers: the novel piece — composable predicates, built on mutation quiescence

No repo has this; the design assembles the best fragments:

- Foundation: LaVague's `JS_WAIT_DOM_IDLE` — MutationObserver quiescence with a stability threshold
  and hard ceiling, resolving converged-vs-timed-out (not `networkidle`, which is slow, wrong for
  streaming pages, and in one repo accidentally a 10ms no-op).
- A trigger is a structured conjunction: URL predicate ∧ selector visible/enabled ∧ DOM-quiescent
  ∧ network-quiet-for-N-ms (NetGent is uniquely positioned for the network conjunct — it's already
  listening). Each conjunct has a timeout and a defined not-satisfied outcome.
- Evaluate per-frame (BrowserGym's `_wait_dom_loaded` iterates `page.frames`), and **record which
  conjunct fired and its latency** — that's what makes a flaky trigger debuggable.
- Every fixed sleep remaining in the codebase is a bug report: it means a trigger couldn't be
  expressed. Readiness timeouts are returned as status, never swallowed (Skyvern's
  `wait_for_page_ready` — built for exactly the cached/no-LLM path — and browser-use's
  `_navigate_and_wait` with adaptive same/cross-domain timeouts are the models).

### 4. Capture: construction-time contract, plugin list, HAR + supplements

- `factory.py` is the only place a context is created. It returns `(context, CaptureBundle)` where
  the bundle holds the paths the context was *actually* constructed with; at run start, every
  declared capture is asserted live or the run aborts.
- Defaults: `record_har_path="<run>/har.zip"` (zip flips Playwright to content-addressed `attach`
  mode), `record_har_content="attach"`, `record_har_mode="full"`; `context.tracing` (screenshots +
  snapshots) as the debugging artifact. No URL filters on dataset runs.
- **HAR is application-layer only — the spec must say so.** No WebSocket frames (Playwright
  #17838/#30315), no TCP/TLS/DNS. Supplements, in order: `page.on("websocket")` frame sidecar
  (JSONL, pure Playwright); `SSLKEYLOGFILE` + tshark sidecar when packet-level ground truth is
  needed (the only path to pcap realism); CDP `Network.responseReceivedExtraInfo` only if timing
  breakdown demands it (`Network.enable` costs ~127ms per `goto` — measured in Skyvern; capture
  overhead distorts the dataset, so record observation overhead in the manifest).
- Capture components follow browser-use's watchdog *shape* — config-declared, independently
  failing, per-component timeouts — but as an explicit `list[CapturePlugin]` with
  `on_context_created / on_transition_start / on_transition_end / on_run_end` hooks, not a
  reflective event bus.
- **Barrier before write**: every async capture task is tracked and drained under a deadline before
  artifacts are written (browser-use loses HAR bodies to fire-and-forget tasks); assume the process
  dies at the worst moment — artifacts are atomically written or repairable.
- **Align everything to NFA edges**: executor setup/teardown slots stamp monotonic
  `edge_id`/timestamps so HAR entries are attributable to the transition that caused them. That
  attribution *is* the dataset's value.

### 5. Provenance and replay-and-diff

- Every run directory carries a manifest: `nfa_hash, spec_hash, netgent_version+git_hash,
  playwright_version, chromium_build, os, python_version, date, capture_drain_status` (AgentLab's
  reproducibility journal, adapted). Replay against a changed `nfa_hash` refuses unless forced.
- Per-edge record: serialized action, resolved locator + fingerprint, trigger conjunct + latency,
  `t_start/t_end`, URL before/after, outcome/error. A crashed run is still legible
  (BrowserGym's lazy filesystem-derived `ExpResult` reader).
- **"Run the same NFA twice, diff the traces" is a first-class command**: per edge — trigger fired?
  latency? same fingerprint? HAR similarity (request count, URL multiset, status distribution).
  With no LLM at run time, every divergence is environment non-determinism — the exact quantity
  NetGent must measure and minimize.
- Free hermetic mode: `context.route_from_har(har, not_found="abort")` replays a recorded run with
  no network and hard-fails on any un-recorded request — the cheapest site-drift detector, unused
  by every repo surveyed.

### 6. Determinism hygiene (hazards found in the wild)

- No randomized viewport (Notte jitters ±50px for stealth — changes what the DOM walker sees).
  Any variation for traffic realism is a seeded, recorded run parameter.
- All timing constants live in the compiled NFA's timing profile, not scattered magic numbers.
- Inject nothing into pages during `run` beyond what observation strictly requires; compile-time
  injection is fine, run-time injection contaminates the trace.

### 7. Testing

- `tests/fixtures/` of local pages (BrowserGym-style, served via `pytest-httpserver` per
  browser-use's `tests/ci/browser/` — copy its conftest nearly verbatim, including the stalled-
  subresource trick for testing readiness semantics and timing assertions as regression checks).
  Fixture coverage: nested iframes, shadow DOM, delayed/async content, SPA route changes,
  obstructed elements, and pages firing known request patterns so **HAR assertions are exact**.
- Pure-unit tests for serializer/fingerprint/action-IR that never start a browser.
- Live-site tests exist only for the compiler (`generate`), quarantined and allowed to be flaky.
  `run` is testable offline end-to-end — by design.

## What changed from the pre-research recommendation

The earlier sketch (`driver.py` + `executor.py` + `dom/` + `triggers.py` + `instrumentation.py`)
survives in outline but was wrong or incomplete in four places:

1. **`resolution.py` was missing entirely** — element identity (locator chains + fingerprints +
   drift errors) turned out to be the central design problem, not a detail of the executor.
2. **`instrumentation.py` as one file was naive** — capture is a plugin subsystem with a
   construction-time contract, drain barriers, and edge alignment; it gets a package.
3. **`driver.py` split into `pw.py` (import chokepoint) + `factory.py` (context/capture owner)** —
   the chokepoint is what makes unit-testing possible; the factory is what makes capture reliable.
   Collapsing lifecycle layers is the documented failure mode (Agent-E's singleton, LaVague's
   monolith).
4. **`dom/` demoted to `observation/` with an asymmetric role** — heavyweight observation is
   compile-time only; run time resolves one target element per transition and observes almost
   nothing. The earlier sketch implicitly assumed a symmetric pipeline.
```
