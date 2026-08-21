"""`netgent generate` — the compile step: explore → synthesize → validate.

The agent explores the task N times (fresh sessions; optionally with alternate sample
values for the declared params), synthesis consolidates the runs into ONE workflow (core
path, guarded optional steps, evidence-based conditions), and a zero-LLM validation replay
decides whether the artifact is written as `validated: true`. LLM at generate time only."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer


def _kv(items: list[str] | None) -> list[tuple[str, str]]:
    out = []
    for item in items or []:
        if "=" not in item:
            raise typer.BadParameter(f"expected name=value, got {item!r}")
        k, v = item.split("=", 1)
        out.append((k, v))
    return out


def generate(
    task: Annotated[str, typer.Argument(help="What the workflow should do, in plain language.")],
    url: Annotated[str | None, typer.Option(help="Starting URL for exploration.")] = None,
    name: Annotated[str | None, typer.Option(help="Workflow name (default: derived from --out or 'workflow').")] = None,
    out: Annotated[Path, typer.Option(help="Where to write the compiled workflow (.yaml or .json).")] = Path(
        "workflow.yaml"
    ),
    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param", "-p", help="name=sample_value used during exploration; becomes a ${name} param (repeatable)."
        ),
    ] = None,
    variation: Annotated[
        list[str] | None,
        typer.Option(
            "--variation",
            help="name=value: one extra exploration with this alternate sample for a --param (repeatable).",
        ),
    ] = None,
    runs: Annotated[int, typer.Option(min=1, help="Explorations with the default params (fresh session each).")] = 1,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Replay the synthesized workflow with zero LLM calls.")
    ] = True,
    model: Annotated[str | None, typer.Option(help="LLM as provider/model (default: NETGENT_GENERATOR_MODEL).")] = None,
    max_steps: Annotated[int, typer.Option(help="Exploration step budget per run.")] = 25,
    trajectory_dir: Annotated[
        Path | None, typer.Option("--trajectory", help="Write every exploration/validation trajectory under here.")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed")] = True,
) -> None:
    """Explore the task (N runs), synthesize ONE workflow, validate it with zero LLM calls."""
    try:
        from netgent.agent import BrowserAgent, make_llm
        from netgent.agent.synthesis import Exploration, synthesize
        from netgent.agent.validate import validate_workflow
        from netgent.browser.session import BrowserSession
    except ImportError as exc:
        typer.secho(f"generate needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings
    from netgent.schema.provenance import Provenance
    from netgent.schema.workflow import dump_workflow

    params = dict(_kv(param))
    variations: list[dict[str, str]] = []
    for k, v in _kv(variation):
        if k not in params:
            raise typer.BadParameter(f"--variation {k}={v}: {k!r} is not a declared --param")
        variations.append({**params, k: v})
    resolved_model = model or get_settings().generator_model
    wf_name = name or (out.stem if out.stem != "workflow" else "workflow")

    # Plan of explorations: `runs` with the defaults, then one per variation.
    plan: list[tuple[str, dict[str, str]]] = [(f"run-{i + 1}", params) for i in range(runs)]
    plan += [(f"run-{runs + i + 1}-" + "-".join(f"{k}={v}" for k, v in p.items() if p[k] != params[k]), p)
             for i, p in enumerate(variations)]

    def task_for(values: dict[str, str]) -> str:
        text = task
        for k, v in values.items():  # the task is phrased with the default samples; swap in the variation's
            text = text.replace(params[k], v)
        return text

    async def _explore(label: str, values: dict[str, str]):
        llm = make_llm(resolved_model)
        run_dir = trajectory_dir / label if trajectory_dir is not None else None
        async with BrowserSession(headless=headless, stealth=True) as session:
            traj = await BrowserAgent(llm, max_steps=max_steps, run_dir=run_dir).run(session, task_for(values), url)
        return Exploration(traj, values)

    explorations = []
    for label, values in plan:
        typer.secho(f"\n[{label}] exploring: {task_for(values)}", bold=True)
        x = asyncio.run(_explore(label, values))
        for s in x.trajectory.steps:
            typer.secho(f" {s.n}. {s.kind} — {s.reasoning}", fg="red" if s.error else "green")
        typer.secho(
            f" {'✓ done' if x.trajectory.success else '✗ ' + (x.trajectory.stopped_reason or 'not completed')}",
            fg="green" if x.trajectory.success else "red",
        )
        explorations.append(x)

    try:
        synthesis = synthesize(explorations, name=wf_name, declared_params=params)
    except ValueError as exc:
        typer.secho(f"✗ synthesis failed: {exc}", fg="red", err=True)
        raise typer.Exit(1) from exc
    wf = synthesis.workflow
    typer.secho(
        f"\n✓ synthesized {len(wf.transitions)} transitions, {len(wf.states)} states"
        + (" (with guarded branches)" if wf.control is not None else ""),
        bold=True, fg="green",
    )
    for note in synthesis.notes:
        typer.echo(f"  · {note}")

    successful = sum(1 for x in explorations if x.trajectory.success)
    prov = Provenance(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        generator=resolved_model,
        runs=len(explorations),
        successful_runs=successful,
        variations=[{k: v for k, v in p.items() if p[k] != params[k]} for p in variations],
        notes=synthesis.notes,
    )

    if validate:
        param_sets = [params] + variations
        typer.secho(f"\nvalidating: {len(param_sets)} zero-LLM replay(s)", bold=True)
        outcome = asyncio.run(
            validate_workflow(wf, param_sets, headless=headless, run_dir=trajectory_dir)
        )
        wf = outcome.workflow
        for r in outcome.first_round:
            _print_result(r, prefix="first attempt")
        if outcome.relaxed:
            typer.secho(f"  relaxed {', '.join(outcome.relaxed)}; re-validated:", fg="yellow")
        for r in outcome.results:
            _print_result(r)
        prov.validated = outcome.validated
        prov.validation = outcome.first_round + outcome.results
        prov.relaxed = outcome.relaxed
    else:
        typer.secho("\nvalidation skipped (--no-validate): artifact is UNVALIDATED", fg="yellow", bold=True)

    wf = wf.model_copy(update={"provenance": prov})
    dump_workflow(wf, out)
    for p in wf.params:
        typer.echo(f"  param {p.name} (default: {p.default!r})")
    typer.echo(f"workflow written to {out}")
    typer.echo(f"replay: netgent run {out}" + ("".join(f' --param "{p.name}=..."' for p in wf.params)))
    if validate and not prov.validated:
        typer.secho(
            "\n✗ NOT VALIDATED — the artifact was written with provenance.validated: false. "
            "Do not rely on it for replay until the failure above is fixed.",
            fg="red", bold=True, err=True,
        )
        raise typer.Exit(1)
    if validate:
        typer.secho("✓ validated: every edge replayed with zero LLM calls", fg="green", bold=True)


def _print_result(r, prefix: str = "replay") -> None:
    shown = ", ".join(f"{k}={v}" for k, v in r.params.items()) or "(no params)"
    if r.success:
        typer.secho(f"  ✓ {prefix} {shown}: {r.edges_ok} edges ok", fg="green")
    else:
        where = f" at {r.failed_edge} → {r.failed_state}" if r.failed_state else ""
        unmet = f" unmet={r.unmet}" if r.unmet else ""
        typer.secho(f"  ✗ {prefix} {shown}:{where}{unmet} {r.error or ''}", fg="red")
