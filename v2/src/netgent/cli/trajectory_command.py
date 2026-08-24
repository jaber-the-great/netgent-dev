"""`netgent trajectory` — view a saved run record or exploration trajectory as a timeline / HTML."""

from pathlib import Path
from typing import Annotated

import typer


def trajectory(
    record: Annotated[Path, typer.Argument(exists=True, help="A run record.json or an exploration trajectory.json.")],
    html_out: Annotated[Path | None, typer.Option("--html", help="Write a self-contained HTML viewer here.")] = None,
) -> None:
    """Render a replay run (text timeline, or --html for a visual page) or an exploration trajectory."""
    from netgent.report import load_exploration, load_record, render_exploration_text, render_text, write_html
    from netgent.report.exploration import is_exploration

    data = load_exploration(record)
    if is_exploration(data):
        if html_out is not None:
            typer.secho("--html is for replay run records; exploration trajectories render as text", fg="red", err=True)
            raise typer.Exit(2)
        typer.echo(render_exploration_text(data))
        return
    rec = load_record(record)
    if html_out is not None:
        write_html(rec, html_out)
        typer.echo(f"wrote {html_out}")
        return
    typer.echo(render_text(rec))
