"""Root Typer app; each command lives in its own module and is registered here."""

from importlib import metadata

import typer

from netgent.cli import (
    agent_command,
    doctor,
    evaluate,
    generate,
    run,
    schema_command,
    sweep_command,
    trajectory_command,
    variations_command,
)

cli_app = typer.Typer(
    help="Agent-based automation of network application workflows.",
    no_args_is_help=True,
)

cli_app.command("run")(run.run)
cli_app.command("generate")(generate.generate)
cli_app.command("eval")(evaluate.evaluate)
cli_app.command("doctor")(doctor.doctor)
cli_app.command("schema")(schema_command.schema)
cli_app.command("trajectory")(trajectory_command.trajectory)
cli_app.command("agent")(agent_command.agent)
cli_app.command("forms-sweep")(sweep_command.forms_sweep)
cli_app.command("infer-params")(variations_command.infer_params)


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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging (overrides NETGENT_LOG_LEVEL)."),
) -> None:
    from netgent.core.logger import configure_logging
    from netgent.core.settings import get_settings

    settings = get_settings()  # loads env + .env (typed)
    settings.sync_provider_keys()  # so the agent's LLM SDK picks up keys from .env
    configure_logging("debug" if verbose else settings.log_level)
