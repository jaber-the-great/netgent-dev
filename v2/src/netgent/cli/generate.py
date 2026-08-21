"""`netgent generate` — the compile step: agent explores the task, the trajectory
compiles into a replayable workflow (NFA). LLM at generate time, zero LLM at run time."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def generate(
    task: Annotated[str, typer.Argument(help="What the workflow should do, in plain language.")],
    url: Annotated[str | None, typer.Option(help="Starting URL for exploration.")] = None,
    name: Annotated[str | None, typer.Option(help="Workflow name (default: derived from --out or 'workflow').")] = None,
    out: Annotated[Path, typer.Option(help="Where to write the compiled workflow (.yaml or .json).")] = Path(
        "workflow.yaml"
    ),
    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param", "-p", help="name=sample_value used during exploration; becomes a ${name} param (repeatable)."
        ),
    ] = None,
    model: Annotated[str | None, typer.Option(help="LLM as provider/model (default: NETGENT_GENERATOR_MODEL).")] = None,
    max_steps: Annotated[int, typer.Option(help="Exploration step budget.")] = 25,
    trajectory_dir: Annotated[
        Path | None, typer.Option("--trajectory", help="Also write the exploration trajectory here.")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed")] = True,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Replay the compiled workflow with zero LLM calls.")
    ] = True,
) -> None:
    """Run the agent on the task, then compile its trajectory into a workflow artifact."""
    try:
        from netgent.agent import BrowserAgent, make_llm
        from netgent.agent.workflow_generator_agent.compiler import compile_trajectory
        from netgent.browser.session import BrowserSession
    except ImportError as exc:
        typer.secho(f"generate needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings
    from netgent.schema.workflow import dump_workflow

    params = dict(p.split("=", 1) for p in (param or []))
    resolved_model = model or get_settings().generator_model
    wf_name = name or (out.stem if out.stem != "workflow" else "workflow")

    async def _run():
        llm = make_llm(resolved_model)
        async with BrowserSession(headless=headless, stealth=True) as session:
            return await BrowserAgent(llm, max_steps=max_steps, run_dir=trajectory_dir).run(session, task, url)

    typer.secho(f"exploring: {task}", bold=True)
    traj = asyncio.run(_run())
    for s in traj.steps:
        typer.secho(f" {s.n}. {s.kind} — {s.reasoning}", fg="red" if s.error else "green")
    if not traj.success:
        typer.secho(f"✗ exploration failed: {traj.stopped_reason or 'not completed'}", fg="red", err=True)
        raise typer.Exit(1)

    wf = compile_trajectory(traj, name=wf_name, params=params)
    dump_workflow(wf, out)
    typer.secho(f"\n✓ compiled {len(wf.transitions)} transitions, {len(wf.states)} states", bold=True, fg="green")
    for p in wf.params:
        typer.echo(f"  param {p.name} (default: {p.default!r})")
    typer.echo(f"workflow written to {out}")
    typer.echo(f"replay: netgent run {out}" + ("".join(f' --param "{p.name}=..."' for p in wf.params)))

    if validate:  # the validation agent: a fresh zero-LLM replay proves the artifact
        from netgent.agent.validation_agent import validate_workflow

        typer.secho("\nvalidating: zero-LLM replay with defaults", bold=True)
        report = asyncio.run(validate_workflow(wf, headless=headless))
        for r in report.replays:
            if r.success:
                typer.secho(f"  ✓ replay ok ({r.edges_ok} edges)", fg="green")
            else:
                typer.secho(f"  ✗ replay failed at {r.failed_edge}: {r.error}", fg="red")
        if report.validated:
            typer.secho("✓ validated: every edge replayed with zero LLM calls", bold=True, fg="green")
        else:
            typer.secho("✗ NOT validated — artifact written but did not replay cleanly", bold=True, fg="red", err=True)
            raise typer.Exit(1)
