"""`netgent eval` — run an offline benchmark dataset of workflow artifacts."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def evaluate(
    dataset: Annotated[Path, typer.Argument(exists=True, help="Dataset dir with *.workflow.yaml + fixtures.")],
    out: Annotated[
        Path | None, typer.Option(help="Results directory (default: evals/results/<dataset>/).")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed", help="Run the browser headless.")] = True,
) -> None:
    """Run every workflow in a dataset against its fixtures; write results + trajectories."""
    from netgent.evalharness import run_dataset

    results_dir = out or (Path("evals/results") / dataset.name)
    summary = asyncio.run(run_dataset(dataset, results_dir, headless=headless))

    for t in summary.tasks:
        color = "green" if t.passed else "red"
        dur = f" ({t.duration_ms:.0f}ms, {t.edges} edges)" if t.duration_ms is not None else ""
        typer.secho(f" {'✓' if t.passed else '✗'} {t.task}{dur}", fg=color)
        if t.error:
            typer.secho(f"   {t.error}", fg="red")

    typer.secho(
        f"\n{summary.passed}/{summary.total} passed ({summary.success_rate:.0%}) — results in {results_dir}/",
        bold=True,
    )
    if summary.passed < summary.total:
        raise typer.Exit(1)
