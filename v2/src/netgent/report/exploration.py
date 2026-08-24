"""Render an exploration trajectory (the agent's trajectory.json) as a text timeline.

Reads the JSON as plain data on purpose: the trajectory model lives in `agent/`, which pulls in
the browser layer, and a viewer should stay light. The file shape is `AgentTrajectory`:
{task, success, stopped_reason, steps: [{n, kind, reasoning, url, error?, action?}]}.
"""

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
