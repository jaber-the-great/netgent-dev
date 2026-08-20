"""`netgent run` — execute a compiled workflow deterministically (zero LLM calls)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def run(
    workflow: Annotated[Path, typer.Argument(exists=True, help="Compiled workflow file (.json, .yaml, or .yml).")],
    save: Annotated[Path | None, typer.Option(help="Write the run record JSON to this path.")] = None,
    trajectory_dir: Annotated[
        Path | None,
        typer.Option("--trajectory", help="Write a trajectory bundle (record.json + per-edge screenshots) here."),
    ] = None,
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="Workflow param as name=value (repeatable).")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed", help="Run the browser headless.")] = True,
    stealth: Annotated[bool, typer.Option("--stealth/--no-stealth", help="Harden the browser fingerprint.")] = True,
) -> None:
    """Execute a compiled workflow (NFA) without LLM calls."""
    # Heavy imports stay inside the handler so `--help` stays fast.
    from pydantic import ValidationError

    from netgent.browser.session import BrowserSession
    from netgent.executor.engine import Executor
    from netgent.schema.workflow import load_workflow

    try:
        wf = load_workflow(workflow)
        values = dict(p.split("=", 1) for p in (param or []))
    except (ValidationError, ValueError) as exc:
        typer.secho(f"invalid workflow artifact: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc
    typer.secho(
        f"workflow: {wf.name} v{wf.version} ({len(wf.states)} states, {len(wf.transitions)} transitions)", bold=True
    )

    async def _run():
        async with BrowserSession(headless=headless, stealth=stealth) as session:
            # params are substituted at dispatch (statics upfront, dynamics from the live page)
            return await Executor(session, wf, run_dir=trajectory_dir, params=values).run()

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
    if trajectory_dir:
        typer.echo(f"trajectory bundle written to {trajectory_dir}/")
        typer.echo(f"  view: netgent trajectory {trajectory_dir}/record.json --html out.html")

    if not record.success:
        raise typer.Exit(1)
    typer.secho("workflow completed", fg="green", bold=True)
