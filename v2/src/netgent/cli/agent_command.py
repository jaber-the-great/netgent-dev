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
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Extra kinds to offer the explorer: hover, press, goto, go_back (repeatable)."),
    ] = None,
    max_actions: Annotated[
        int, typer.Option(help="Atomic actions one decision may batch (1-4; each is still one transition).")
    ] = 1,
) -> None:
    """Drive a browser to complete a task, one atomic action per step."""
    try:
        from netgent.agent import BrowserAgent, make_llm
        from netgent.browser.session import BrowserSession
    except ImportError as exc:
        typer.secho(f"the agent needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings

    resolved_model = model or get_settings().generator_model

    from netgent.agent.explorer.decision import DEFAULT_KINDS

    kinds = DEFAULT_KINDS | {k.strip() for item in (allow or []) for k in item.split(",") if k.strip()}

    async def _run():
        llm = make_llm(resolved_model)
        async with BrowserSession(headless=headless) as session:
            agent = BrowserAgent(
                llm, max_steps=max_steps, run_dir=trajectory_dir, allowed_kinds=kinds, max_actions_per_step=max_actions
            )
            return await agent.run(session, task, url)

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
