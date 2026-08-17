"""Root Typer app; each command lives in its own module and is registered here."""

from importlib import metadata

import typer

from netgent.cli import doctor, evaluate, generate, run

cli_app = typer.Typer(
    help="Agent-based automation of network application workflows.",
    no_args_is_help=True,
)

cli_app.command("run")(run.run)
cli_app.command("generate")(generate.generate)
cli_app.command("eval")(evaluate.evaluate)
cli_app.command("doctor")(doctor.doctor)


def _version_callback(value: bool) -> None:
    if value:
        try:
            version = metadata.version("netgent")
        except metadata.PackageNotFoundError:
            version = "unknown (not installed)"
        typer.echo(f"netgent {version}")
        raise typer.Exit()


@cli_app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    pass
