"""`netgent run` — execute a compiled workflow deterministically (zero LLM calls)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def run(
    workflow: Annotated[Path, typer.Argument(exists=True, help="Compiled workflow file (.json, .yaml, or .yml).")],
    save: Annotated[Path | None, typer.Option(help="Write the run record JSON to this path.")] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed", help="Run the browser headless.")] = True,
) -> None:
    """Execute a compiled workflow (NFA) without LLM calls."""
    # Heavy imports stay inside the handler so `--help` stays fast.
    from pydantic import ValidationError

    from netgent.browser.session import BrowserSession
    from netgent.core.workflow import load_workflow
    from netgent.executor.engine import Executor

    try:
        wf = load_workflow(workflow)
    except (ValidationError, ValueError) as exc:
        typer.secho(f"invalid workflow artifact: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc
    typer.secho(f"workflow: {wf.name} ({len(wf.states)} states, {len(wf.transitions)} transitions)", bold=True)

    async def _run():
        async with BrowserSession(headless=headless) as session:
            return await Executor(session, wf).run()

    record = asyncio.run(_run())

    for edge in record.edges:
        ok = edge.outcome == "ok"
        color = "green" if ok else "red"
        latency = f" ({edge.trigger_latency_ms:.0f}ms to recognize {edge.target})" if ok else ""
        typer.secho(f" {'✓' if ok else '✗'} {edge.transition_id}: {edge.action_type}{latency}", fg=color)
        if edge.error:
            typer.secho(f"   {edge.error}", fg="red")

    if save:
        save.write_text(record.model_dump_json(indent=2) + "\n")
        typer.echo(f"run record written to {save}")

    if not record.success:
        raise typer.Exit(1)
    typer.secho("workflow completed", fg="green", bold=True)
