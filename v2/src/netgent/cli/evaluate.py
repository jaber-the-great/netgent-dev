"""`netgent eval` — run an offline benchmark task set from evals/datasets/."""

from pathlib import Path
from typing import Annotated

import typer


def evaluate(
    dataset: Annotated[Path, typer.Argument(exists=True, help="Path to a task-set JSONL under evals/datasets/.")],
    model: Annotated[str | None, typer.Option(help="LLM model to run the agent with.")] = None,
    out: Annotated[
        Path | None, typer.Option(help="Results directory (default: evals/results/<dataset>-<model>-<date>/).")
    ] = None,
) -> None:
    """Run a task set from evals/datasets/ and write raw results to evals/results/."""
    typer.secho(
        "`netgent eval` is not implemented yet: see evals/README.md for the intended layout", fg="red", err=True
    )
    raise typer.Exit(1)
