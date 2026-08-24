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

## Running — `netgent eval` (a command group)

Every number in `docs/research/` should be reproducible from one of these; each writes
markdown + json under `evals/results/<eval>/` (override with `--out`) and, except `dataset`,
exits non-zero only on runner errors — never on a low score.

```bash
netgent eval dataset evals/datasets/forms            # zero-LLM replay benchmark → evals/results/forms/
netgent eval dataset evals/datasets/forms --headed   # watch it
netgent trajectory evals/results/forms/vanilla/record.json --html view.html

netgent eval observation --sites youtube twitch      # observation metrics, no LLM → results/observation/
netgent eval observation --sites mine=file:///tmp/page.html --backends dom

netgent eval stress challenge --backend dom --runs 3 --tag=-M   # the 15-card challenge game (LLM)
netgent eval stress sweep --backend dom --runs 3 --tag=-M       # the 21-form sweep (LLM)

netgent eval matrix --tags -M                        # comparison table from stress results → results/matrix/
```

| command | measures | writes |
|---|---|---|
| `dataset <dir>` | compiled workflows replayed against local fixtures, zero LLM (exits 1 on any failure — the CI check) | `results/<dataset>/summary.json` + per-task records |
| `observation` | per backend on the SAME page load: elements, named %, get_by_role %, locator uniqueness, chars/tokens, snapshot time, iframe coverage | `results/observation/observation_ab.{md,json}` |
| `stress sweep\|challenge` | browser-use stress tests with the cheap model, N runs; per-run result, LLM calls, tokens, wall | `results/stress/<kind>-<backend><tag>-r<i>/result.json` |
| `matrix` | mean (per run), text vs image tokens, cost/run and cost/step across backends | `results/matrix/matrix.md` |

`--backend` names the observation backend; this branch ships the DOM walk (`dom`). The
accessibility-tree and hybrid backends (`ax`, `hybrid`, `hybrid_on_stuck`) and `netgent eval som`
(the Set-of-Marks geometry check) live on `v2/accessibility-tree` and share this layout.

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
