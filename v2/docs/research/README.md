# NetGent V2 — Docs Index

Working notes derived from three design meetings (Eugene Vuong ↔ Manni Moghimi, UCSB SNL; advisor: Arpit) and the "NetGent V2 Design Doc" PDF (10 pp.).

- [meetings-summary.md](meetings-summary.md) — per-meeting breakdown (participants, decisions, action items, risks) plus the narrative arc across the series.
- [design-doc-review.md](design-doc-review.md) — full structured review of the design doc PDF: inventory, architecture, decision table, gap analysis, critique, and 13 prioritized recommended edits.
- [github-recon.md](github-recon.md) — deep dive into the project's own repos (V1, V1.5, workflow registry) and comparable OSS (Skyvern, Stagehand, browser-use, workflow-use, Healenium, Crawljax): mechanisms to copy/avoid, suggested V2 artifact schema.
- [proposed-ai-agent.md](proposed-ai-agent.md) — the forward-looking proposal: a state-machine-based agent that replays deterministically, self-heals via a T0–T3 ladder with write-back, and self-improves via an offline loop; includes architecture, LLM-usage budget table, evaluation plan, and a 6-phase roadmap.
- [related-work.md](related-work.md) — literature survey (~180 sources): must-cite papers (AWM/ASI, Ringer, APE, ICSE'20 near-duplicate study, Similo++/VISTA), the field-gap positioning, and 30 prioritized recommendations (R1–R30) spanning state identity, Discovery, repair, and evaluation/benchmarks.

## One-paragraph project summary

NetGent V2 is a web-automation system where an LLM agent explores a site once and compiles the workflow into a deterministic, parameterized, replayable config (YAML), modeled as an NFA — so subsequent runs need no LLM in the loop. The V1→V2 differentiators are a validation/error agent and a healing/repair capability. Agent pipeline: Planner → Discovery fleet → Workflow Generator → Validation Agent → Workflow artifact.

## Where design and doc diverge (the headline)

The meetings converged on **Manni's formalism** — guards/anchors live in states, transitions carry a **single atomic action** (closed parameterized set, <15 ops), pop-ups are states reached via **ε-transitions**, and a planner emits a finite **control sequence** — and decided healing is **embedded inside execution** (consciously overriding Arpit's separate-bootstrapping rule). The design doc largely predates or omits this: it still presents Eugene's inverse model as live (with a strawman N×M argument *against* the adopted design), its only concrete artifact (the Verizon Fios YAML) encodes the superseded model, and the two critical sections — **Validation/Error Fixing** and **Metrics/Evaluation** — are empty headings. The repair path and the Discovery algorithm are the two unspecified halves of the system; both are named as the actual hard problems in the meetings.

## Top open items

1. Write the repair/healing spec (Meeting 3 has the design: discovery mode, local branching, transition rewrite, hook-matching reconnection — it's just not in the doc).
2. Declare Manni's formalism normative; mark Eugene's as superseded; rewrite the YAML artifact accordingly.
3. Extend the architecture diagram past the `Workflow` artifact (executor, breakage detection, repair, write-back).
4. Specify state identity (Manni's static-template-HTML criterion) and the Discovery algorithm + related-work survey.
5. Fill Metrics/Evaluation with both baselines: NetGent V1 **and** a plain-LLM browser agent.
