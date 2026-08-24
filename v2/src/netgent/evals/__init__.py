"""Reproducible evals behind `netgent eval` — every number in docs/research/ comes from here.

Each module exposes an importable runner returning plain data (rows / dicts) and never exits
the process; the CLI (`cli/evaluate.py`) is a thin wrapper that prints a summary and writes
markdown + json under `evals/results/<eval>/`.

- `dataset` — the replay benchmark: compiled workflows against local fixtures, zero LLM
  (the CI-style check; the only runner whose CLI exits non-zero on a low score).
- `observation` — observation-backend metrics on live or local pages: element counts, names,
  locator uniqueness, observation size, snapshot time (no LLM).
- `stress` — the browser-use stress tests with the cheap model: the 21-form sweep and the
  challenge game, N runs per backend (LLM).
- `matrix` — assemble the backend comparison table from stress result JSONs.

"""
