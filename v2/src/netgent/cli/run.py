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
    bare: Annotated[
        bool, typer.Option("--bare", help="Bundled Chromium instead of real Chrome (control arm for experiments).")
    ] = False,
) -> None:
    """Execute a compiled workflow (NFA) without LLM calls."""
    # Heavy imports stay inside the handler so `--help` stays fast.
    from pydantic import ValidationError

    from netgent.browser.profile import BrowserProfile
    from netgent.browser.session import BrowserSession
    from netgent.executor.engine import Executor
    from netgent.schema.workflow import load_workflow, resolve_params

    try:
        wf = load_workflow(workflow)
        values = dict(p.split("=", 1) for p in (param or []))
        # Statics substitute upfront (so ${name} in state conditions resolves too);
        # dynamics stay as ${name} in actions and resolve from the live page at dispatch.
        wf = resolve_params(wf, values)
    except (ValidationError, ValueError) as exc:
        typer.secho(f"invalid workflow artifact: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc
    typer.secho(
        f"workflow: {wf.name} v{wf.version} ({len(wf.states)} states, {len(wf.transitions)} transitions)", bold=True
    )

    async def _run():
        async with BrowserSession(headless=headless, profile=BrowserProfile.bare() if bare else None) as session:
            # params are substituted at dispatch (statics upfront, dynamics from the live page)
            return await Executor(session, wf, run_dir=trajectory_dir, params=values).run()

    record = asyncio.run(_run())

    for edge in record.edges:
        ok = edge.outcome == "ok"
        recovered = edge.outcome == "recovered"
        color = "green" if ok else ("yellow" if recovered else "red")
        symbol = "✓" if ok else ("↻" if recovered else "✗")
        latency = f" ({edge.trigger_latency_ms:.0f}ms to recognize {edge.target})" if ok else ""
        note = " (did not settle — anchor re-checked)" if recovered else ""
        typer.secho(f" {symbol} {edge.transition_id}: {edge.action_type}{latency}{note}", fg=color)
        if edge.error and not recovered:
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
