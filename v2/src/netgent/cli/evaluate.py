"""`netgent eval` — the reproducible evals behind docs/research/ (a Typer sub-app).

Every subcommand is a thin wrapper over `netgent.evals.*`: it prints a compact summary table,
writes markdown + json under `evals/results/<eval>/` (override with --out), and exits non-zero only on runner errors —
never on a low score. The one exception is `dataset`, the CI-style replay check.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

eval_app = typer.Typer(no_args_is_help=True, help="Reproducible evals (dataset, observation, stress, matrix).")

RESULTS = Path("evals/results")


@eval_app.command("dataset")
def dataset(
    dataset: Annotated[Path, typer.Argument(exists=True, help="Dataset dir with *.workflow.yaml + fixtures.")],
    out: Annotated[Path | None, typer.Option(help="Results directory (default: evals/results/<dataset>/).")] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed", help="Run the browser headless.")] = True,
) -> None:
    """Replay benchmark: run every compiled workflow in a dataset against its local fixtures (zero LLM).

    Success = the workflow reached its accepting state. Writes summary.json and one record per task.
    Exits 1 when any task fails (this is the CI-style check; the other evals never exit on scores).
    """
    from netgent.evals.dataset import run_dataset

    results_dir = out or (RESULTS / dataset.name)
    summary = asyncio.run(run_dataset(dataset, results_dir, headless=headless))
    for t in summary.tasks:
        dur = f" ({t.duration_ms:.0f}ms, {t.edges} edges)" if t.duration_ms is not None else ""
        typer.secho(f" {'✓' if t.passed else '✗'} {t.task}{dur}", fg="green" if t.passed else "red")
        if t.error:
            typer.secho(f"   {t.error}", fg="red")
    typer.secho(
        f"\n{summary.passed}/{summary.total} passed ({summary.success_rate:.0%}) — results in {results_dir}/", bold=True
    )
    if summary.passed < summary.total:
        raise typer.Exit(1)


@eval_app.command("observation")
def observation(
    sites: Annotated[
        list[str] | None,
        typer.Option("--sites", help="Site names (youtube, twitch, reddit, forms, challenge, todomvc-spa) or name=url"),
    ] = None,
    backends: Annotated[str, typer.Option(help="Comma-separated observation backends (this branch: dom).")] = "dom",
    out: Annotated[Path | None, typer.Option(help="Output dir (default: evals/results/observation/).")] = None,
) -> None:
    """Observation metrics (no LLM) on live or local pages, per backend on the SAME page load.

    Measures: interactive elements, % named, % with a get_by_role locator, % whose durable
    locator resolves to exactly one element, observation chars/tokens, snapshot time, iframe coverage.
    """
    from netgent.evals import observation as mod

    try:
        site_map = mod.resolve_sites(sites)
        bk = tuple(b.strip() for b in backends.split(",") if b.strip())
        rows, md = asyncio.run(mod.run(site_map, bk, progress=typer.echo))
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    path = mod.write(rows, md, out or RESULTS / "observation")
    typer.echo("\n" + mod.table(rows))
    typer.secho(f"\nwrote {path} (+ .json)", bold=True)


@eval_app.command("interact")
def interact(
    sites: Annotated[
        list[str] | None,
        typer.Option("--sites", help="Site names (default: forms) or name=url"),
    ] = None,
    out: Annotated[Path | None, typer.Option(help="Output dir (default: evals/results/interact/).")] = None,
) -> None:
    """Interactability (no LLM): dispatch every observed element's canonical action and verify.

    A deterministic action-layer regression check — fill/select/check/upload/click each
    element through the real dispatcher and read the effect back. Submit buttons and
    top-frame links are skipped by design.
    """
    from netgent.evals import interact as mod

    try:
        site_map = mod.resolve_sites(sites or ["forms"])
        rows, md = asyncio.run(mod.run(site_map, progress=typer.echo))
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    path = mod.write(rows, md, out or RESULTS / "interact")
    typer.echo("\n" + md)
    typer.secho(f"\nwrote {path} (+ .json)", bold=True)
    if any(r["fail"] for r in rows):
        raise typer.Exit(1)


@eval_app.command("stress")
def stress(
    kind: Annotated[str, typer.Argument(help="sweep (21 forms) or challenge (the challenge game).")],
    backend: Annotated[str, typer.Option(help="Observation backend (this branch: dom).")] = "dom",
    runs: Annotated[int, typer.Option(help="Repetitions (results are noisy; the docs use 3).")] = 1,
    max_steps: Annotated[int | None, typer.Option(help="Step budget (challenge: 60; sweep: 30 per form).")] = None,
    model: Annotated[str, typer.Option(help="LLM as provider:model.")] = "anthropic:claude-haiku-4-5-20251001",
    tag: Annotated[str, typer.Option(help="Suffix for the result dir, e.g. '-M' (use --tag=-M).")] = "",
    out: Annotated[Path | None, typer.Option(help="Results root (default: evals/results/stress/).")] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed", help="Run the browser headless.")] = True,
) -> None:
    """Stress tests with the cheap model (LLM): the 21-form sweep or the 15-card challenge game.

    Writes <out>/<kind>-<backend><tag>-r<i>/result.json per run (plus trajectory.json for the
    challenge). Prints per-run result, LLM calls, tokens, wall time, and the mean.
    """
    from netgent.evals import stress as mod

    if kind not in ("sweep", "challenge"):
        typer.secho("kind must be 'sweep' or 'challenge'", fg="red", err=True)
        raise typer.Exit(2)
    if backend not in mod.BACKENDS:
        typer.secho(f"backend must be one of {mod.BACKENDS}", fg="red", err=True)
        raise typer.Exit(2)
    results = asyncio.run(
        mod.run(kind, backend, runs=runs, max_steps=max_steps, model=model, tag=tag,
                out_dir=out or RESULTS / "stress", progress=typer.echo, headless=headless)
    )
    typer.echo("\n" + mod.summary_table(results))


@eval_app.command("matrix")
def matrix(
    tags: Annotated[
        list[str] | None, typer.Option("--tags", help="Result-dir tags to include (default: '-M').")
    ] = None,
    results: Annotated[Path | None, typer.Option(help="Stress results root (default: evals/results/stress/).")] = None,
    out: Annotated[Path | None, typer.Option(help="Output dir (default: evals/results/matrix/).")] = None,
    image_tokens: Annotated[int, typer.Option(help="Estimated tokens per screenshot (1280x800 ≈ 1365).")] = 1365,
) -> None:
    """Assemble the backend comparison table from stress result JSONs.

    Columns: result mean (per run), LLM calls, text tokens, image tokens, output tokens, wall,
    cost per run and per step (Haiku 4.5 list prices).
    """
    from netgent.evals import matrix as mod

    md = mod.build(results or RESULTS / "stress", tags or ["-M"], image_tokens)
    out_dir = out or RESULTS / "matrix"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "matrix.md").write_text("# Backend matrix\n\n" + md + "\n")
    typer.echo(md)
    typer.secho(f"\nwrote {out_dir / 'matrix.md'}", bold=True)
