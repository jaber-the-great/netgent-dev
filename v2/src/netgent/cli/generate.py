"""`netgent generate` — the compile step, run by the orchestrator:
explore (LLM agent) → verify (LLM judge, advisory) → generate (trajectory → NFA)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer


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
    model: Annotated[str | None, typer.Option(help="LLM as provider:model (default: NETGENT_GENERATOR_MODEL).")] = None,
    max_steps: Annotated[int, typer.Option(help="Exploration step budget.")] = 25,
    trajectory_dir: Annotated[
        Path | None, typer.Option("--trajectory", help="Also write the exploration trajectory here.")
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--headed")] = True,
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Extra kinds to offer the explorer: hover, press, goto, go_back (repeatable)."),
    ] = None,
    max_actions: Annotated[
        int, typer.Option(help="Atomic actions one decision may batch (1-4; each is still one transition).")
    ] = 1,
    judge: Annotated[
        bool, typer.Option("--judge/--no-judge", help="LLM judge of the exploration from page evidence (advisory).")
    ] = True,
    parallel: Annotated[
        int, typer.Option("--parallel", min=1, help="Explore N planned task variations at once (one browser "
                          "each) and merge them into one generalized workflow (params inferred; zero-LLM "
                          "replay check). --parallel 1 = a single exploration, compiled as-is.")
    ] = 5,
    variation: Annotated[
        list[str] | None,
        typer.Option("--variation", help="Pin one variation's value as name=value (repeatable; needs --parallel > 1)."),
    ] = None,
    rounds: Annotated[
        int, typer.Option("--rounds", min=1, help="Closed-loop round budget (--parallel > 1): after a failed replay "
                          "check, triage → plan_next → another round of explorations merged with everything so "
                          "far, until the replay passes on 2 unseen value sets. 1 = a single round.")
    ] = 3,
) -> None:
    """Explore the task with the agent, judge the run from page evidence, compile it into a workflow."""

    try:
        from netgent.agent import make_llm
        from netgent.agent.orchestrator import GenerateRequest, orchestrate
    except ImportError as exc:
        typer.secho(f"generate needs the 'generate' extra: pip install 'netgent[generate]'  ({exc})", fg="red")
        raise typer.Exit(1) from exc

    from netgent.core.settings import get_settings

    req = GenerateRequest(
        task=task,
        url=url,
        name=name or (out.stem if out.stem != "workflow" else "workflow"),
        params=dict(p.split("=", 1) for p in (param or [])),
        max_steps=max_steps,
        allow_kinds=[k.strip() for item in (allow or []) for k in item.split(",") if k.strip()],
        max_actions_per_step=max_actions,
        headless=headless,
        out=out,
        trajectory_dir=trajectory_dir,
        judge=judge,
        # One knob: N variations, all N explored concurrently (one browser each).
        runs=parallel,
        parallel=parallel,
        variation=dict(v.split("=", 1) for v in (variation or [])),
        max_rounds=rounds,
    )
    llm = make_llm(model or get_settings().generator_model)

    colors = {"plan": "magenta", "explore": None, "verify": "yellow", "merge": "blue",
              "generate": "cyan", "replay": "green", "triage": "yellow", "round": "magenta"}

    def listen(stage: str, text: str) -> None:
        fg = "red" if "FAILED" in text or "failed" in text else colors.get(stage)
        typer.secho(f"[{stage}] {text}", fg=fg)

    result = asyncio.run(orchestrate(req, llm, listen))

    if result.workflow is not None:
        typer.echo(f"\nworkflow written to {out}")
        typer.echo(f"replay: netgent run {out}" + "".join(f' --param "{p.name}=..."' for p in result.workflow.params))
    if result.error:
        typer.secho(f"✗ {result.error}", bold=True, fg="red", err=True)
        raise typer.Exit(1)
    if result.workflow is not None:
        typer.secho("✓ compiled", bold=True, fg="green")
