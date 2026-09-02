# NetGent V2 — Docs Index

Working notes derived from three design meetings (Eugene Vuong ↔ Manni Moghimi, UCSB SNL; advisor: Arpit) and the "NetGent V2 Design Doc" PDF (10 pp.).

- [meetings-summary.md](meetings-summary.md) — per-meeting breakdown (participants, decisions, action items, risks) plus the narrative arc across the series.
- [design-doc-review.md](design-doc-review.md) — full structured review of the design doc PDF: inventory, architecture, decision table, gap analysis, critique, and 13 prioritized recommended edits.
- [github-recon.md](github-recon.md) — deep dive into the project's own repos (V1, V1.5, workflow registry) and comparable OSS (Skyvern, Stagehand, browser-use, workflow-use, Healenium, Crawljax): mechanisms to copy/avoid, suggested V2 artifact schema.
- [proposed-ai-agent.md](proposed-ai-agent.md) — the forward-looking proposal: a state-machine-based agent that replays deterministically, self-heals via a T0–T3 ladder with write-back, and self-improves via an offline loop; includes architecture, LLM-usage budget table, evaluation plan, and a 6-phase roadmap.
- [related-work.md](related-work.md) — literature survey (~180 sources): must-cite papers (AWM/ASI, Ringer, APE, ICSE'20 near-duplicate study, Similo++/VISTA), the field-gap positioning, and 30 prioritized recommendations (R1–R30) spanning state identity, Discovery, repair, and evaluation/benchmarks.

## Later research (Aug 2026) — the explorer, browser layer, and pipeline

- [browser-agent-architectures.md](browser-agent-architectures.md) — how browser agents split roles (planner/executor/judge/triage) and what our explore → generate → validate pipeline should borrow.
- [langgraph-agent-structure.md](langgraph-agent-structure.md) — how LangGraph agents are actually structured (functions + compiled graph vs classes), resource injection, memory, config; refactor sketch for the explorer.
- [langgraph-multi-agent.md](langgraph-multi-agent.md) — LangGraph's current multi-agent patterns (subagents/handoffs/skills/router/custom workflow) vs our orchestrator; `Send` fan-out for `--runs N`.
- [web-agent-papers.md](web-agent-papers.md) — literature review (~59 papers): observation, memory, action space, skill induction; ranked top-10 actionable findings.
- [browser-agent-memory.md](browser-agent-memory.md) — history windows, working-memory fields, observation diffs, compaction, cross-run memory.
- [browser-agent-tool-calling.md](browser-agent-tool-calling.md) — single vs batched actions, element addressing, compound actions, structured output vs tool calling.
- [browser-agent-prompting.md](browser-agent-prompting.md) — observation formats and token costs, viewport policy, system-prompt structure, parameter conveyance.
- [explorer-optimisation.md](explorer-optimisation.md) — what was implemented from the four above, with the A/B numbers (kept vs reverted).
- [browser-agent-date-inputs.md](browser-agent-date-inputs.md) — date inputs and pickers: format signals, dispatch strategies, measured on the two failing sweep forms (implemented).
- [trajectory-memory.md](trajectory-memory.md) — inducing one generalized workflow from N trajectories (ReUseIt corrected: no real merge; failures +8.7, fallbacks +20); the typed-key merge proposal and the runs-independence policy.
- [generator-agent.md](generator-agent.md) — should the generator be an LLM agent? Survey of Workflow Use / Skyvern / ReUseIt / AWM parameter decisions; design: LLM emits a typed GeneralizationPlan, code re-derives and validates every edit, replay is the gate.
- [generalization-papers.md](generalization-papers.md) — the literature on turning demonstrations into generalized procedures (SMARTedit/Ringer/Rousillon → AWM/ASI/NSI/Skill-DisCo): version-space merge, branch induction, positional locators, replay-on-held-out as the gate; a six-stage algorithm for our generator.
- [agent-verification.md](agent-verification.md) — how agents verify task completion: judges vs deterministic oracles, feedback contracts; the NetGent verifier design.
- [verification-papers.md](verification-papers.md) — the verification/judging literature, old and new (test oracles, LLM-as-judge limits, self-verification, replay determinism).
- [eval-framework.md](eval-framework.md) — how the field structures evals and tracks regressions over commits (WebArena, AgentLab, τ-bench pass^k, WebJudge, AgentRewardBench, browser-use/Skyvern/Stagehand harnesses, Harbor/Inspect, SWE-bench, error bars); the `netgent eval bench` spec: versioned task suites with page-derived postconditions, per-stage metrics, replay pass^k on held-out value sets, budget-normalized closed-loop metrics.
- [stealth-after-patchright.md](stealth-after-patchright.md) — what Patchright covers, measured residuals, `BrowserProfile` verdict (implemented).
- [iframes-shadow-dom.md](iframes-shadow-dom.md) — iframe/shadow-DOM handling R1–R8 (implemented; closed roots read over CDP).
- [discovery-prior-art.md](discovery-prior-art.md), [reuseit.md](reuseit.md), [design-doc-and-meetings.md](design-doc-and-meetings.md) — discovery/exploration prior art, the ReUseIt paper, and the design doc + meeting transcripts.
- [runtime-long-horizon.md](runtime-long-horizon.md), [long-horizon-agents.md](long-horizon-agents.md) — long-horizon handling at run time and in agents.
- [repo-layout-viewers.md](repo-layout-viewers.md) — where evals/trajectory viewers live in other repos (informed `evals/` and `report/`).

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
