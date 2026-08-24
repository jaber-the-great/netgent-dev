"""Render an exploration trajectory (the agent's trajectory.json) as a text timeline.

Reads the JSON as plain data on purpose: the trajectory model lives in `agent/`, which pulls in
the browser layer, and a viewer should stay light. The file shape is `AgentTrajectory`:
{task, success, stopped_reason, steps: [{n, kind, reasoning, url, error?, action?}]}.
"""

import base64
import html
import json
from pathlib import Path


def load_exploration(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def is_exploration(data: dict) -> bool:
    """An exploration trajectory has `steps`; a replay run record has `edges`."""
    return "steps" in data and "edges" not in data


def render_exploration_text(data: dict) -> str:
    status = "SUCCESS" if data.get("success") else "FAILED"
    steps = data.get("steps", [])
    lines = [f"exploration — {status} ({len(steps)} steps): {data.get('task', '')}"]
    for s in steps:
        sym = "✗" if s.get("error") else ("■" if s.get("kind") == "done" else "✓")
        action = s.get("action") or {}
        detail = f" [{action['type']}]" if action.get("type") else ""
        lines.append(f"  {sym} {s.get('n')}. {s.get('kind')}{detail} — {s.get('reasoning', '')}")
        if s.get("error"):
            lines.append(f"      error: {s['error']}")
        if s.get("url"):
            lines.append(f"      {s['url']}")
    if data.get("stopped_reason"):
        lines.append(f"stopped: {data['stopped_reason']}")
    return "\n".join(lines)


def _inline_image(base_dir: Path, rel: str) -> str:
    """A data: URI for a screenshot next to the trajectory (self-contained page); '' if missing."""
    path = Path(base_dir) / rel
    if not path.is_file():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def render_exploration_html(data: dict, base_dir: Path) -> str:
    """One self-contained HTML page: a card per step with its reasoning, action, URL, error and
    screenshot (inlined as base64 from `base_dir`, the directory the trajectory.json lives in)."""
    cards = []
    for s in data.get("steps", []):
        kind = s.get("kind", "")
        action = s.get("action") or {}
        cls = "fail" if s.get("error") else ("done" if kind == "done" else "ok")
        act = f'<code>{html.escape(json.dumps(action))}</code>' if action else ""
        err = f'<div class="err">{html.escape(s["error"])}</div>' if s.get("error") else ""
        src = _inline_image(base_dir, s["screenshot"]) if s.get("screenshot") else ""
        shot = f'<img src="{src}" loading="lazy">' if src else ""
        cards.append(f"""
      <div class="step {cls}">
        <div class="hd"><b>{s.get("n")}. {html.escape(kind)}</b> {act}</div>
        <div class="why">{html.escape(s.get("reasoning", ""))}</div>
        <div class="url">{html.escape(s.get("url", ""))}</div>
        {err}{shot}
      </div>""")
    status = "SUCCESS" if data.get("success") else "FAILED"
    stopped = html.escape(data.get("stopped_reason", ""))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>exploration trajectory</title>
<style>
 body {{ font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 2rem auto; max-width: 900px; color: #1c1c1c; }}
 h1 {{ font-size: 1.3rem; }} .meta {{ color: #666; margin-bottom: 1.5rem; }}
 .status.SUCCESS {{ color: #128a2b; }} .status.FAILED {{ color: #c0271a; }}
 .step {{ border: 1px solid #e2e2e2; border-left: 4px solid #128a2b; border-radius: 8px; }}
 .step {{ padding: .8rem 1rem; margin: .8rem 0; }}
 .step.fail {{ border-left-color: #c0271a; }} .step.done {{ border-left-color: #2b5fd1; }}
 .hd code {{ background: #f2f2f2; padding: .1rem .4rem; border-radius: 4px; font-size: .82em; }}
 .why {{ margin: .3rem 0; }} .url {{ color: #556; font-size: .82em; word-break: break-all; }}
 .err {{ color: #c0271a; font-family: monospace; font-size: .82em; margin-top: .4rem; }}
 img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 6px; margin-top: .6rem; }}
</style></head><body>
 <h1>exploration <small>{html.escape(data.get("task", ""))}</small></h1>
 <div class="meta"><span class="status {status}">{status}</span> · {len(data.get("steps", []))} steps · {stopped}</div>
 {"".join(cards)}
</body></html>
"""


def write_exploration_html(data: dict, base_dir: Path, out: Path) -> None:
    Path(out).write_text(render_exploration_html(data, base_dir))
