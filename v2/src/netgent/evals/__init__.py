"""Reproducible evals behind `netgent eval` — every number in docs/research/ comes from here.

Each module exposes an importable runner returning (rows, markdown) and never exits the
process; the CLI (`cli/evaluate.py`) is a thin wrapper that prints a summary and writes
markdown + json under `evals/results/<eval>/`. The legacy `evals/*.py` scripts are shims.

- `observation` — DOM walk vs accessibility tree vs hybrid: element counts, names, locator
  uniqueness, observation size, snapshot time, image cost (no LLM).
- `som` — Set-of-Marks geometry check: identity / covered / miss per mark, label collisions,
  annotated PNGs (no LLM).
- `stress` — the browser-use stress tests with the cheap model: 21-form sweep and the
  challenge game, N runs per backend (LLM).
- `matrix` — assemble the backend comparison table from stress result JSONs.
"""
