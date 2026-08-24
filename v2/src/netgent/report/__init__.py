"""Render things humans read: a replay run record or an exploration trajectory, as a text
timeline or a self-contained HTML page (`netgent trajectory`).

Imports only `schema` and the standard library — no Playwright, no LLM SDKs — so viewing a
record is instant and works on a machine without a browser installed. Rendering lives here,
not in `cli/` (tests and other code import it as a library) and not in `core/` (the foundation
layer imports nothing else; this depends on `schema`). See docs/research/repo-layout-viewers.md.
"""

from netgent.report.exploration import (
    load_exploration,
    render_exploration_html,
    render_exploration_text,
    write_exploration_html,
)
from netgent.report.run import load_record, render_html, render_text, write_html

__all__ = [
    "load_exploration",
    "load_record",
    "render_exploration_html",
    "render_exploration_text",
    "render_html",
    "render_text",
    "write_exploration_html",
    "write_html",
]
