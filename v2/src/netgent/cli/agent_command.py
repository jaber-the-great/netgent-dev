"""`netgent agent` — run the LLM browser agent on a task (needs the `generate` extra + a key)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


def agent(
    task: Annotated[str, typer.Argument(help="What the agent should do, in plain language.")],
    url: Annotated[str | None, typer.Option(help="Starting URL.")] = None,
    model: Annotated[str, typer.Option(help="LLM as provider/model.")] = "gemini/gemini-2.5-flash",
    max_steps: Annotated[int, typer.Option(help="Step budget.")] = 25,
    trajectory_dir: Annotated[
        Path | None, typer.Option("--trajectory", help="Write the agent trajectory here.")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed")] = True,
) -> None:
    """Drive a stealth browser to complete a task, one atomic action per step."""
    try:
        from netgent.agent import BrowserAgent, make_llm
        from netgent.browser.session import BrowserSession
    except ImportError as exc:
        typer.secho(f"the agent needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    async def _run():
        llm = make_llm(model)
        async with BrowserSession(headless=headless, stealth=True) as session:
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
