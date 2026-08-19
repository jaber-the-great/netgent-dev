"""`netgent forms-sweep` — complete AND verify every form on a page, one at a time."""

import asyncio
from typing import Annotated

import typer


def forms_sweep(
    url: Annotated[str, typer.Argument(help="Page whose forms should all be filled + submitted.")],
    model: Annotated[str | None, typer.Option(help="LLM as provider/model.")] = None,
    steps_per_form: Annotated[int, typer.Option(help="Step budget per form.")] = 30,
    headless: Annotated[bool, typer.Option("--headless/--headed")] = True,
) -> None:
    """Enumerate the forms, drive the agent through each one, and verify each submission."""
    try:
        from netgent.agent import make_llm
        from netgent.agent.sweep import sweep_forms
        from netgent.browser.session import BrowserSession
    except ImportError as exc:
        typer.secho(f"needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings

    resolved_model = model or get_settings().generator_model

    async def _run():
        async with BrowserSession(headless=headless, stealth=True) as session:
            await session.page.goto(url, wait_until="networkidle")
            return await sweep_forms(session, make_llm(resolved_model), max_steps_per_form=steps_per_form)

    result = asyncio.run(_run())
    for f in result.forms:
        ok = f.submitted
        note = "" if ok == f.agent_success else f"  (agent claimed {'success' if f.agent_success else 'failure'})"
        typer.secho(f" {'✓' if ok else '✗'} form {f.form + 1} ({f.steps} steps){note}", fg="green" if ok else "red")
    typer.secho(
        f"\n{result.submitted}/{result.total} forms verified submitted",
        bold=True,
        fg="green" if result.submitted == result.total else "yellow",
    )
    if result.submitted < result.total:
        raise typer.Exit(1)
