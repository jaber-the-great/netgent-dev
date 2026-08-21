"""`netgent agent` — run the LLM browser agent on a task (needs the `generate` extra + a key)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def agent(
    task: Annotated[str, typer.Argument(help="What the agent should do, in plain language.")],
    url: Annotated[str | None, typer.Option(help="Starting URL.")] = None,
    model: Annotated[str | None, typer.Option(help="LLM as provider/model (default: NETGENT_GENERATOR_MODEL).")] = None,
    max_steps: Annotated[int, typer.Option(help="Step budget.")] = 25,
    trajectory_dir: Annotated[
        Path | None, typer.Option("--trajectory", help="Write the agent trajectory here.")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed")] = True,
    observation: Annotated[
        str | None, typer.Option(help="Observation backend: dom | ax (default: NETGENT_OBSERVATION).")
    ] = None,
    show_graph: Annotated[
        bool, typer.Option("--graph", help="Print the agent loop's LangGraph (Mermaid) and exit.")
    ] = False,
) -> None:
    """Drive a stealth browser to complete a task, one atomic action per step."""
    if show_graph:
        from netgent.agent.explore_agent.graph import agent_graph_mermaid

        typer.echo(agent_graph_mermaid())
        return
    try:
        from netgent.agent import BrowserAgent, make_llm
        from netgent.browser.session import BrowserSession
    except ImportError as exc:
        typer.secho(f"the agent needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings

    resolved_model = model or get_settings().generator_model

    async def _run():
        llm = make_llm(resolved_model)
        async with BrowserSession(headless=headless, stealth=True, observation=observation) as session:
            return await BrowserAgent(llm, max_steps=max_steps, run_dir=trajectory_dir).run(session, task, url)

    traj = asyncio.run(_run())
    for s in traj.steps:
        color = "red" if s.error else "green"
        typer.secho(f" {s.n}. {s.kind} — {s.reasoning}", fg=color)
        if s.error:
            typer.secho(f"    {s.error}", fg="red")
    typer.secho(
        f"\n{'✓ success' if traj.success else '✗ ' + (traj.stopped_reason or 'not completed')} "
        f"({len(traj.steps)} steps)",
        bold=True,
        fg="green" if traj.success else "red",
    )
    if not traj.success:
        raise typer.Exit(1)
