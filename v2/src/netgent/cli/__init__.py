"""netgent CLI package (entry point: `netgent`), structured like Skyvern's Typer CLI."""

__all__ = ["cli_app", "main"]

from netgent.cli.commands import cli_app


def main() -> None:
    cli_app()
