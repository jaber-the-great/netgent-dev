"""`netgent infer-params` — derive workflow parameters from prompt variations."""

from typing import Annotated

import typer


def infer_params(
    variations: Annotated[list[str], typer.Argument(help="Two or more variations of the task prompt.")],
) -> None:
    """Diff the prompt variations; the parts that differ become ${p1}, ${p2}, ... parameters."""
    from netgent.agent.variations import infer_params as _infer

    try:
        result = _infer(variations)
    except ValueError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(1) from exc

    typer.secho("template:", bold=True)
    typer.echo(f"  {result.template}")
    typer.secho("\nparams:", bold=True)
    for p in result.params:
        typer.echo(f"  {p.name}: {result.samples[p.name]}")
    typer.echo("\n(paste `params:` into the workflow; ${name} placeholders are already in the template)")
