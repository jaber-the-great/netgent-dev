# Evals

Offline benchmark runs for netgent. Kept separate from `tests/` on purpose: `tests/` is
deterministic and gates CI; evals are run by hand and never gate CI (the tests-vs-evals split
every surveyed browser-agent project converged on — see `docs/browser-agents.md`).

## Layout

- `datasets/<name>/` — a dataset: `*.workflow.yaml` artifacts plus the static fixtures they drive.
- `results/<name>/` — raw per-task results from a replay-benchmark run: `summary.json`, and one
  trajectory bundle per task (`<task>/record.json` + `<task>/screenshots/`). Committing `summary.json`
  and the per-task `record.json` keeps reported numbers verifiable; screenshots are gitignored.
- `results/observation/`, `results/som/`, `results/stress/`, `results/matrix/` — outputs of the
  other `netgent eval` subcommands (markdown + json, plus annotated PNGs for `som` and per-run
  `result.json` / `trajectory.json` for `stress`).

## Running — `netgent eval <subcommand>`

Every number in `docs/research/` is reproducible from one command. All subcommands print a
compact table, write markdown + json under `evals/results/<eval>/` (override with `--out`), and
exit non-zero only on runner errors (never on a low score — except `dataset`, the CI-style check).

```bash
netgent eval dataset evals/datasets/forms          # replay benchmark → evals/results/forms/ (zero LLM)
netgent eval dataset evals/datasets/forms --headed # watch it
netgent trajectory evals/results/forms/vanilla/record.json --html view.html

netgent eval observation                           # DOM vs AX vs hybrid on the same page load (no LLM)
netgent eval observation --sites forms --sites mine=file:///tmp/page.html --backends dom,ax
                                                   # → evals/results/observation/observation_ab.{md,json}
netgent eval som                                   # Set-of-Marks geometry check + annotated PNGs (no LLM)
netgent eval som --sites fixed+modal --sites reddit
                                                   # → evals/results/som/som_check.{md,json}, <site>.png
netgent eval stress challenge --backend hybrid --runs 3 --tag=-M   # LLM (Haiku); needs ANTHROPIC_API_KEY
netgent eval stress sweep --backend ax --runs 3 --tag=-M
                                                   # → evals/results/stress/<kind>-<backend><tag>-r<i>/result.json
netgent eval matrix --tags -M                      # ax / hybrid / hybrid_on_stuck table with cost per step
                                                   # → evals/results/matrix/matrix.md
```

The runners live in `src/netgent/evals/` (importable, no `sys.exit`); `evals/*.py` are shims that
forward to the CLI. `netgent eval <sub> --help` says what each measures.

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
