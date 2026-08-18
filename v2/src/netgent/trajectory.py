"""Render a run trajectory (RunRecord) for viewing — text timeline or a self-contained HTML page.

Imports only the record schema (no Playwright), so `netgent trajectory` stays fast and works
without the browser installed.
"""

import html
import json
from pathlib import Path

from netgent.schema.records import RunRecord

_SYMBOL = {"ok": "✓", "trigger_timeout": "✗", "action_error": "✗"}


def load_record(path: Path) -> RunRecord:
    return RunRecord.model_validate_json(Path(path).read_text())


def render_text(record: RunRecord) -> str:
    status = "SUCCESS" if record.success else "FAILED"
    lines = [f"{record.workflow_name} v{record.workflow_version} — {status} ({len(record.edges)} edges)"]
    for i, e in enumerate(record.edges, 1):
        sym = _SYMBOL.get(e.outcome, "?")
        latency = f", recognized {e.target} in {e.trigger_latency_ms:.0f}ms" if e.trigger_latency_ms is not None else ""
        lines.append(f" {i}. {sym} {e.transition_id}: {e.action_type} ({e.source} → {e.target}){latency}")
        for c in e.conditions:
            lines.append(f"      {'●' if c.met else '○'} {c.type}")
        if e.url_after:
            lines.append(f"      url: {e.url_after}")
        if e.error:
            lines.append(f"      error: {e.error}")
    return "\n".join(lines)


def render_html(record: RunRecord) -> str:
    """A single self-contained HTML page: one card per edge, screenshots inline if present."""
    cards = []
    for i, e in enumerate(record.edges, 1):
        ok = e.outcome == "ok"
        conds = "".join(
            f'<span class="c {"met" if c.met else "unmet"}">{"●" if c.met else "○"} {html.escape(c.type)}</span>'
            for c in e.conditions
        )
        latency = f'<span class="lat">{e.trigger_latency_ms:.0f}ms</span>' if e.trigger_latency_ms is not None else ""
        shot = f'<img src="{html.escape(e.screenshot)}" loading="lazy">' if e.screenshot else ""
        err = f'<div class="err">{html.escape(e.error)}</div>' if e.error else ""
        cards.append(f"""
      <div class="edge {'ok' if ok else 'fail'}">
        <div class="hd"><b>{i}. {html.escape(e.transition_id)}</b>
          <code>{html.escape(e.action_type)}</code>
          {html.escape(e.source)} &rarr; {html.escape(e.target)} {latency}</div>
        <div class="conds">{conds}</div>
        <div class="url">{html.escape(e.url_after or "")}</div>
        {err}{shot}
      </div>""")
    status = "SUCCESS" if record.success else "FAILED"
    dur = f"{record.duration_ms:.0f}ms" if record.duration_ms is not None else "?"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(record.workflow_name)} trajectory</title>
<style>
 body {{ font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 900px; color: #1c1c1c; }}
 h1 {{ font-size: 1.3rem; }} .meta {{ color: #666; margin-bottom: 1.5rem; }}
 .status.SUCCESS {{ color: #128a2b; }} .status.FAILED {{ color: #c0271a; }}
 .edge {{ border: 1px solid #e2e2e2; border-left: 4px solid #128a2b; border-radius: 8px; padding: .8rem 1rem }}
 .edge {{ margin: .8rem 0; }}
 .edge.fail {{ border-left-color: #c0271a; }}
 .hd code {{ background: #f2f2f2; padding: .1rem .4rem; border-radius: 4px; }}
 .lat {{ color: #888; font-size: .85em; }}
 .conds {{ margin: .4rem 0; }} .c {{ font-size: .82em; margin-right: .8rem; }}
 .c.met {{ color: #128a2b; }} .c.unmet {{ color: #c0271a; }}
 .url {{ color: #556; font-size: .82em; word-break: break-all; }}
 .err {{ color: #c0271a; font-family: monospace; font-size: .82em; margin-top: .4rem; }}
 img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 6px; margin-top: .6rem; }}
</style></head><body>
 <h1>{html.escape(record.workflow_name)} <small>v{html.escape(record.workflow_version)}</small></h1>
 <div class="meta"><span class="status {status}">{status}</span> · {len(record.edges)} edges · {dur}</div>
 {"".join(cards)}
</body></html>
"""


def write_html(record: RunRecord, out: Path) -> None:
    Path(out).write_text(render_html(record))


# Re-export for scripts that just want the raw dict.
def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())
