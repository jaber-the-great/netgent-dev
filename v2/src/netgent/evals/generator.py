"""`netgent eval generator` — the offline compile eval (docs/research/generator-agent-v2.md §J.3).

A stored `<name>.trajectories/` bundle in (the per-run recordings, verdicts and variations that
every `netgent generate` leaves on disk), one compile out: merge (pure) → gather (pure) → draft
(a live model, or a cached draft.json for zero LLM) → materialize (pure). No browser. Reports the
generator metrics of §J.2 — draft_acceptance_rate, rejection reasons, repairs_used, used_fallback,
accept_states_nonempty, interrupts, param recall against the planner's names, positional clicks —
and writes the artifact, the draft and a summary under the results dir.

Importable functions returning rows/markdown; no sys.exit (the CLI wraps it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator.context import MAX_REPAIRS, GeneratorContext
from netgent.agent.generator.draft import WorkflowDraft
from netgent.agent.generator.materialize import materialize
from netgent.agent.generator.merge import RunInput, merge_trajectories
from netgent.agent.generator.models import GenerateOutcome, acceptance_rate
from netgent.schema.workflow import Workflow, dump_workflow


def load_bundle(bundle: Path) -> tuple[str, str | None, list[str], list[RunInput]]:
    """(task, url, canonical param names, runs) from a stored bundle."""
    task, url, names = "", None, []
    ctx_path = bundle / "context.json"
    if ctx_path.is_file():
        ctx = json.loads(ctx_path.read_text())
        task, url, names = ctx.get("task", ""), ctx.get("url"), list(ctx.get("canonical_names", []))
    runs: list[RunInput] = []
    for d in sorted((p for p in bundle.iterdir() if p.is_dir() and p.name.startswith("run-")),
                    key=lambda p: int(p.name.split("-")[1])):
        traj_path = d / "trajectory.json"
        if not traj_path.is_file():
            continue
        traj = AgentTrajectory.model_validate(json.loads(traj_path.read_text()))
        var = json.loads((d / "variation.json").read_text()) if (d / "variation.json").is_file() else {}
        ver = (json.loads((d / "verdict.json").read_text()) if (d / "verdict.json").is_file()
               else {"achieved": traj.success})
        runs.append(RunInput(run=int(d.name.split("-")[1]), trajectory=traj, values=var.get("values", {}),
                             achieved=bool(ver.get("achieved")), scoped=bool(var.get("scoped", False))))
    if not task and runs:
        task = runs[0].trajectory.task.split("\n\nPARAMETERS:")[0]
    if not names and runs:
        names = list(runs[0].values)
    return task, url, names, runs


def load_draft(path: Path) -> WorkflowDraft:
    """A cached draft: round-r/draft.json (GenerateOutcome minus the workflow) or a bare WorkflowDraft."""
    data = json.loads(path.read_text())
    return WorkflowDraft.model_validate(data["draft"] if "draft" in data and isinstance(data["draft"], dict) else data)


def metrics(outcome: GenerateOutcome, names: list[str]) -> dict[str, Any]:
    wf: Workflow = outcome.workflow
    bound = [p.name for p in wf.params]
    positional = [t.id for t in wf.transitions if t.action.type == "click"
                  and getattr(t.action, "locator", None) and t.action.locator[-1].fn == "nth"]
    reasons: dict[str, int] = {}
    for o in outcome.outcomes:
        if o.status == "rejected":
            key = o.reason.split(":")[0][:60]
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "draft_acceptance_rate": acceptance_rate(outcome.outcomes),
        "items": len(outcome.outcomes),
        "applied": sum(1 for o in outcome.outcomes if o.status == "applied"),
        "rejected": sum(1 for o in outcome.outcomes if o.status == "rejected"),
        "degraded": sum(1 for o in outcome.outcomes if o.status == "degraded"),
        "rejection_reasons": reasons,
        "repairs_used": outcome.repairs_used,
        "used_fallback": outcome.used_fallback,
        "validated": outcome.validated,
        "accept_states_nonempty": bool(wf.accept_states),
        "transitions": len(wf.transitions),
        "interrupts": len(wf.interrupts),
        "params": bound,
        "derived_params": [p.name for p in wf.params if p.derive is not None],
        "param_recall": (sum(1 for n in names if n in bound) / len(names)) if names else None,
        "positional_clicks": positional,
        "warnings": list(outcome.warnings),
    }


async def run_generator_eval(
    bundle: Path,
    out_dir: Path,
    *,
    model: str | None = None,
    draft_path: Path | None = None,
    max_repairs: int = MAX_REPAIRS,
    progress=None,
) -> tuple[dict[str, Any], str]:
    """One compile of a stored bundle; returns (summary, markdown). Zero LLM with `draft_path`."""
    task, url, names, runs = load_bundle(bundle)
    if not any(r.achieved and not r.scoped for r in runs):
        raise ValueError(f"{bundle}: no achieved run to compile")
    merged = merge_trajectories(runs, name=bundle.name.removesuffix(".trajectories") or "workflow")
    if progress:
        progress(f"merged {len(merged.generalized.achieved_runs)} achieved run(s): "
                 f"{len(merged.generalized.columns)} columns")
    if draft_path is not None:
        ctx = GeneratorContext(task=task, url=url, name=merged.workflow.name, runs=tuple(runs),
                               generalized=merged.generalized, fallback=merged.workflow)
        outcome = materialize(load_draft(draft_path), ctx)
        source = f"cached draft {draft_path}"
    else:
        from netgent.agent.generator.graph import generate
        from netgent.agent.llm import make_llm, usage_of

        llm = make_llm(model) if model else None
        outcome = await generate(task=task, runs=runs, generalized=merged.generalized, fallback=merged.workflow,
                                 llm=llm, url=url, name=merged.workflow.name, max_repairs=max_repairs)
        source = f"model {model}" + (f" usage {usage_of(llm)}" if usage_of(llm) else "")
    summary = {"bundle": str(bundle), "source": source, "task": task, "canonical_names": names,
               **metrics(outcome, names)}
    md = markdown(summary, outcome)
    write(out_dir, outcome, summary, md)
    return summary, md


def write(out_dir: Path, outcome: GenerateOutcome, summary: dict[str, Any], md: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_workflow(outcome.workflow, out_dir / "workflow.yaml")
    draft = outcome.model_dump(mode="json", exclude={"workflow"})
    (out_dir / "draft.json").write_text(json.dumps(draft, indent=2) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "summary.md").write_text(md)


def markdown(summary: dict[str, Any], outcome: GenerateOutcome) -> str:
    rate = summary["draft_acceptance_rate"]
    recall = "n/a" if summary["param_recall"] is None else f"{summary['param_recall']:.0%}"
    lines = [f"# generator eval — {summary['bundle']}", "", f"source: {summary['source']}", "",
             "| metric | value |", "|---|---|",
             f"| draft_acceptance_rate | {'n/a' if rate is None else f'{rate:.0%}'} "
             f"({summary['applied']} applied / {summary['rejected']} rejected / {summary['degraded']} degraded) |",
             f"| repairs_used | {summary['repairs_used']} |", f"| used_fallback | {summary['used_fallback']} |",
             f"| validated (witnessed accept) | {summary['validated']} |",
             f"| transitions / interrupts | {summary['transitions']} / {summary['interrupts']} |",
             f"| params | {', '.join(summary['params']) or '(none)'} |",
             f"| derived params | {', '.join(summary['derived_params']) or '(none)'} |",
             f"| param_recall vs planner | {recall} |",
             f"| positional clicks | {', '.join(summary['positional_clicks']) or '(none)'} |", ""]
    rejected = [o for o in outcome.outcomes if o.status != "applied"]
    if rejected:
        lines += ["## not applied", ""]
        lines += [f"- `{o.item}`{f' ({o.ref})' if o.ref else ''} — {o.status}: {o.reason}" for o in rejected]
        lines.append("")
    if outcome.warnings:
        lines += ["## warnings", "", *(f"- {w}" for w in outcome.warnings), ""]
    if outcome.draft is not None and outcome.draft.notes:
        lines += ["## the agent's notes", "", *(f"- {n}" for n in outcome.draft.notes), ""]
    return "\n".join(lines)


def table(summary: dict[str, Any]) -> str:
    rate = summary["draft_acceptance_rate"]
    return yaml.safe_dump({k: summary[k] for k in (
        "draft_acceptance_rate", "applied", "rejected", "degraded", "repairs_used", "used_fallback", "validated",
        "transitions", "interrupts", "params", "derived_params", "param_recall", "positional_clicks")} | {
        "draft_acceptance_rate": None if rate is None else round(rate, 2)}, sort_keys=False)
