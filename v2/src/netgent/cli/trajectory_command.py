"""`netgent trajectory` — view a saved run record as a timeline or an HTML page."""

from pathlib import Path
from typing import Annotated

import typer


def trajectory(
    record: Annotated[Path, typer.Argument(exists=True, help="A saved run record.json.")],
    html_out: Annotated[Path | None, typer.Option("--html", help="Write a self-contained HTML viewer here.")] = None,
) -> None:
    """Render an agent-run trajectory (text timeline, or --html for a visual page)."""
    from netgent.trajectory import load_record, render_text, write_html

    rec = load_record(record)
    if html_out is not None:
        write_html(rec, html_out)
        typer.echo(f"wrote {html_out}")
        return
    typer.echo(render_text(rec))
