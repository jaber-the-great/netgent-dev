"""`netgent generate` — full agent pipeline: state prompts -> compiled workflow (v1's Code Generation Mode)."""

from pathlib import Path
from typing import Annotated

import typer


def generate(
    prompts: Annotated[str, typer.Argument(help="State prompts JSON file or inline JSON string.")],
    api_keys: Annotated[
        Path | None, typer.Option("--api-keys", help="LLM API keys JSON file (or rely on env vars).")
    ] = None,
    credentials: Annotated[str | None, typer.Option(help="Credentials JSON file or inline JSON string.")] = None,
    out: Annotated[Path | None, typer.Option(help="Where to write the compiled workflow JSON.")] = None,
    headless: Annotated[bool, typer.Option("--headless", help="Run the browser headless.")] = False,
) -> None:
    """Run the agent pipeline to compile state prompts into executable workflow code."""
    typer.secho("`netgent generate` is not implemented yet: the v2 agent core has not landed", fg="red", err=True)
    raise typer.Exit(1)
