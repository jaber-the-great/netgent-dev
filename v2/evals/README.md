# Evals

Offline benchmark runs for netgent. Kept separate from `tests/` on purpose: `tests/` is
deterministic and gates CI; evals are run by hand and never gate CI (the tests-vs-evals split
every surveyed browser-agent project converged on — see `docs/browser-agents.md`).

## Layout

- `datasets/<name>/` — a dataset: `*.workflow.yaml` artifacts plus the static fixtures they drive.
- `results/<name>/` — raw per-task results from a run: `summary.json`, and one trajectory bundle
  per task (`<task>/record.json` + `<task>/screenshots/`). Committing `summary.json` and the
  per-task `record.json` keeps reported numbers verifiable; screenshots are gitignored (heavy,
  regenerable).

## Running

```bash
netgent eval evals/datasets/forms            # → evals/results/forms/
netgent eval evals/datasets/forms --headed   # watch it
netgent trajectory evals/results/forms/vanilla/record.json --html view.html
```

Success for a task = the compiled workflow reached its accepting state (`record.success`), i.e.
the form's success sentinel (`the secret is: dumbledore`) became visible. No LLM, no live network:
the harness serves each dataset directory over a local HTTP server and substitutes `{base}` in the
workflow URLs.

## Datasets

- **forms** — form-filling stress cases adapted from the shapes in
  [browser-use/stress-tests](https://github.com/browser-use/stress-tests): a vanilla HTML form
  (with a red-herring cancel button), a **shadow-DOM** form (Playwright pierces open shadow roots),
  and a **multi-step/progressive** form (each step is its own NFA state). All three currently pass.

## Roadmap

This is the deterministic-replay eval (does a compiled NFA replay?). The LLM-judged, compile-from-spec
eval (does `generate` produce a correct NFA from a natural-language spec?) arrives with the `agent/`
pipeline; this harness is its runnable skeleton.
