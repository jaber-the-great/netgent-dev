# Evals

Offline, LLM-judged benchmark runs for netgent agents. Kept separate from `tests/` on purpose:
`tests/` is deterministic and gates CI; nothing here runs in CI.

- `datasets/` — task sets (JSONL), versioned. If a set is published externally, note provenance here.
- `results/` — committed raw per-task results per run (`<dataset>-<model>-<date>/`), so reported
  numbers stay verifiable.

See `docs/browser-agents.md` for the survey of how other browser-agent projects structure evals.
