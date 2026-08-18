"""`netgent schema` — print or regenerate the JSON Schemas of the artifact formats."""

from pathlib import Path
from typing import Annotated

import typer


def schema(
    name: Annotated[str | None, typer.Argument(help="Schema to print: workflow | run-record. Omit to list.")] = None,
    write: Annotated[Path | None, typer.Option(help="Regenerate all schemas into this directory.")] = None,
) -> None:
    """Print an artifact JSON Schema, or regenerate the committed copies with --write."""
    from netgent.schema import SCHEMAS, render, write_all

    if write is not None:
        for path in write_all(write):
            typer.echo(f"wrote {path}")
        return
    if name is None:
        typer.echo("available schemas: " + ", ".join(SCHEMAS))
        raise typer.Exit()
    if name not in SCHEMAS:
        typer.secho(f"unknown schema {name!r} (available: {', '.join(SCHEMAS)})", fg="red", err=True)
        raise typer.Exit(1)
    typer.echo(render(name), nl=False)
