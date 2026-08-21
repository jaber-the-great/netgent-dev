"""`netgent generate` — the compile step, run by the orchestrator:
explore (LLM agent) → generate (trajectory → NFA) → validate (zero-LLM replay)."""

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
    show_graph: Annotated[
        bool, typer.Option("--graph", help="Print the pipeline's LangGraph (Mermaid) and exit.")
    ] = False,
) -> None:
    """Explore the task with the agent, compile its trajectory into a workflow, validate it."""
    if show_graph:
        from netgent.agent.orchestrator import orchestration_graph_mermaid

        typer.echo(orchestration_graph_mermaid())
        return

    try:
        from netgent.agent import make_llm
        from netgent.agent.orchestrator import GenerateRequest, orchestrate
    except ImportError as exc:
        typer.secho(f"generate needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings

    req = GenerateRequest(
        task=task,
        url=url,
        name=name or (out.stem if out.stem != "workflow" else "workflow"),
        params=dict(p.split("=", 1) for p in (param or [])),
        max_steps=max_steps,
        headless=headless,
        out=out,
        trajectory_dir=trajectory_dir,
        validate_replay=validate,
    )
    llm = make_llm(model or get_settings().generator_model)

    colors = {"explore": None, "generate": "cyan", "validate": "magenta"}

    def listen(stage: str, text: str) -> None:
        fg = "red" if "FAILED" in text or "failed" in text else colors[stage]
        typer.secho(f"[{stage}] {text}", fg=fg)

    result = asyncio.run(orchestrate(req, llm, listen))

    if result.workflow is not None:
        typer.echo(f"\nworkflow written to {out}")
        typer.echo(f"replay: netgent run {out}" + "".join(f' --param "{p.name}=..."' for p in result.workflow.params))
    if result.error:
        typer.secho(f"✗ {result.error}", bold=True, fg="red", err=True)
        raise typer.Exit(1)
    if result.report is not None:
        typer.secho("✓ validated: every edge replayed with zero LLM calls", bold=True, fg="green")
