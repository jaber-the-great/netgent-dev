"""Per-round report of a closed-loop run from its context.json (zero LLM, read-only)."""
import json, sys
from pathlib import Path
root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/dt-run/dream-theater.trajectories")
ctx = json.loads((root / "context.json").read_text())
print(f"task: {ctx['task'][:80]}…  runs/round={ctx['runs_per_round']} max_rounds={ctx['max_rounds']}")
print("canonical names:", ctx["canonical_names"])
for rd in ctx["rounds"]:
    print(f"\n=== ROUND {rd['round']} (exit={rd['exit'] or 'continue'}) ===")
    for v in rd["variations"]:
        print("  variation:", {k: v["values"][k] for k in v["values"]})
    for r in rd["runs"]:
        u = r.get("usage") or {}
        print(f"  run {r['run']}{' scoped' if r['scoped'] else ''}: achieved={r['achieved']} attempts={r['attempts']} "
              f"steps={r['steps']} calls={u.get('calls')} in={u.get('input_tokens')} out={u.get('output_tokens')}"
              + (f" unmet={r['unmet'][0][:90]!r}" if r["unmet"] else ""))
    g = rd.get("generalized")
    if g:
        print("  params:", [(p["name"], p["default"]) for p in g["params"]])
        disp = {}
        for c in g["columns"]:
            disp[c["disposition"]] = disp.get(c["disposition"], 0) + 1
        print("  columns:", disp)
        for c in g["columns"]:
            if c["disposition"] in ("target-varies", "value-diverges", "positional", "folded"):
                print(f"    col {c['index']} {c['disposition']} {c['action_type']} {c.get('target') or ''!s:.60} "
                      f"{c.get('values_by_run') or ''} -> {c.get('transition')}")
        for w in g["warnings"]:
            print("  warning:", w[:150])
        for h in g["hints"]:
            hh = h["hint"]
            print(f"  hint col {hh['column']} {hh['intent']}{' fold' if hh.get('repeat_fold') else ''}: "
                  f"{h['status']} — {h['reason'][:120]}")
    for rr in rd["replay"]:
        print(f"  replay {rr['values']}: {'ok' if rr['success'] else 'FAILED'}"
              + (f" at {rr['failed_edge']} ({rr['outcome']}; unmet {rr['unmet']})" if rr.get("failed_edge") else "")
              + f" states={len(rr['signature'])} last={rr['signature'][-2:]}")
    print(f"  replay_passed={rd['replay_passed']} unseen_passed={rd['unseen_passed']}")
    for e in rd["episodes"]:
        print(f"  episode: {e['kind']} col={e.get('column')} {e.get('transition') or ''} "
              f"{'replay-confirmed' if e.get('confirmed_by_replay') else ''} {e.get('detail','')[:100]}")
    np = rd.get("next_plan")
    if np:
        print("  next_plan:", [v["values"] for v in np["next_variations"]],
              "scoped:", [s["task_text"][:50] for s in np["scoped_subtasks"]],
              "hints:", [(h["column"], h["intent"], h.get("repeat_fold")) for h in np["generalization_hints"]])
        for n in np["notes"]:
            print("    note:", n[:150])
    print("  usage:", {k: (v or {}).get("calls") for k, v in rd["usage"].items()})
