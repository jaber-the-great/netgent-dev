"""End-to-end stress tests with the cheap model: the 21-form sweep and the challenge game (LLM).

`challenge`: one BrowserAgent run on browser-use's challenge game; the score the page itself
shows, the completed/missed card ids, steps, errors, LLM usage.
`sweep`: `sweep_forms` on the 21-form stress page; per-form verified pass/fail with step logs.
Each run writes `<out>/<kind>-<backend><tag>-r<i>/result.json` (+ trajectory for challenge).

`backend` names the observation backend. This branch has the DOM walk; the accessibility-tree
and hybrid backends (`ax`, `hybrid`, `hybrid_on_stuck`) arrive with the observation branch and
share this runner and result layout.
"""

import json
import time
from pathlib import Path

CHALLENGE_URL = "https://browser-use.github.io/stress-tests/challenge.html"
FORMS_URL = "https://browser-use.github.io/stress-tests/forms-comparison.html"
DEFAULT_MODEL = "anthropic/claude-haiku-4-5-20251001"
BACKENDS = ("dom",)
DEFAULT_MAX_STEPS = {"challenge": 60, "sweep": 30}

# The exact prompt used for the acceptance runs (documented in
# docs/research/accessibility-tree-observation.md §6).
CHALLENGE_TASK = (
    "Complete every task on this page, working top to bottom. Each task is a card whose "
    "instruction is in the page text (e.g. 'Click the button to start', 'Select one of the "
    "radio buttons'). The header shows 'Score: N / 17' and N goes up by one each time a task "
    "registers; a card's own text (slider value, keys pressed, upload status) also tells you "
    "whether it registered. There are exactly 15 cards (the page's '/ 17' is a typo — the "
    "score can never reach 17, so do not hunt for missing points). Do exactly what each "
    "instruction says using click, fill, select, hover, press, upload, or scroll-inside-a-box; "
    "attempt each card once, in order, and do not go back. If a card is impossible for you "
    "(e.g. reading letters off a canvas image), skip it and move on. Scroll down only when "
    "every card in view is done or skipped. Finish with done (success=true if you attempted "
    "all 15 cards) when the last card (the contenteditable one) is done."
)


def _session(backend: str):
    """A BrowserSession for `backend`; the DOM walk is the only backend on this branch."""
    from netgent.browser.session import BrowserSession

    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}")
    return BrowserSession(headless=True)


async def run_challenge(backend: str, max_steps: int, out_dir: Path, model: str = DEFAULT_MODEL) -> dict:
    from netgent.agent import BrowserAgent, make_llm

    llm = make_llm(model)
    t0 = time.perf_counter()
    async with _session(backend) as s:
        agent = BrowserAgent(llm, max_steps=max_steps, run_dir=out_dir)
        traj = await agent.run(s, CHALLENGE_TASK, CHALLENGE_URL)
        score = await s.page.locator(".score").inner_text()
        done_ids = await s.page.eval_on_selector_all(".task.completed", "els => els.map(e => e.id)")
        all_ids = await s.page.eval_on_selector_all(".task", "els => els.map(e => e.id)")
    usage = getattr(llm, "usage", None)
    return {
        "kind": "challenge",
        "backend": backend,
        "model": model,
        "max_steps": max_steps,
        "score": int(score),
        "completed": done_ids,
        "missed": [i for i in all_ids if i not in done_ids],
        "steps": len(traj.steps),
        "agent_success": traj.success,
        "stopped_reason": traj.stopped_reason,
        "errors": [f"{st.n}. {st.kind}: {st.error}" for st in traj.steps if st.error],
        "wall_s": round(time.perf_counter() - t0, 1),
        "usage": usage if isinstance(usage, dict) else None,
        "per_step": list(getattr(llm, "calls", []) or []),  # per-call input/output/cache tokens
    }


async def run_sweep(backend: str, max_steps: int, out_dir: Path, model: str = DEFAULT_MODEL) -> dict:
    from netgent.agent import make_llm
    from netgent.evals.sweep import sweep_forms

    del out_dir  # the sweep keeps its own per-form results inside the result
    llm = make_llm(model)
    t0 = time.perf_counter()
    async with _session(backend) as s:
        await s.page.goto(FORMS_URL, wait_until="networkidle")
        result = await sweep_forms(s, llm, max_steps_per_form=max_steps, retries=1)
    usage = getattr(llm, "usage", None)
    return {
        "kind": "sweep",
        "backend": backend,
        "model": model,
        "max_steps_per_form": max_steps,
        "total": result.total,
        "submitted": result.submitted,
        "forms": [f.model_dump() for f in result.forms],
        "wall_s": round(time.perf_counter() - t0, 1),
        "usage": usage if isinstance(usage, dict) else None,
        "per_step": list(getattr(llm, "calls", []) or []),  # per-call input/output/cache tokens
    }


async def run(
    kind: str,
    backend: str,
    *,
    runs: int = 1,
    max_steps: int | None = None,
    model: str = DEFAULT_MODEL,
    tag: str = "",
    out_dir: Path = Path("evals/results/stress"),
    progress=None,
) -> list[dict]:
    """Run `runs` repetitions; each result is written to <out_dir>/<kind>-<backend><tag>-r<i>/."""
    from netgent.core.settings import get_settings

    get_settings().sync_provider_keys()  # publish .env keys to the SDKs
    steps = max_steps or DEFAULT_MAX_STEPS[kind]
    results = []
    for i in range(runs):
        d = out_dir / f"{kind}-{backend}{tag}-r{i}"
        r = await (run_challenge if kind == "challenge" else run_sweep)(backend, steps, d, model)
        d.mkdir(parents=True, exist_ok=True)
        (d / "result.json").write_text(json.dumps(r, indent=2) + "\n")
        results.append(r)
        if progress:
            progress(f"[run {i}] {kind} {backend}: metric={metric(r)} usage={r.get('usage')}")
    return results


def metric(r: dict) -> int:
    return r["score"] if r["kind"] == "challenge" else r["submitted"]


def summary_table(results: list[dict]) -> str:
    if not results:
        return "(no results)"
    kind, backend = results[0]["kind"], results[0]["backend"]
    denom = "15" if kind == "challenge" else str(results[0].get("total", 21))
    lines = [
        "| run | result | LLM calls | input tokens | output tokens | cache read | in/step | out/step | wall |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results):
        u = r.get("usage") or {}
        calls = u.get("calls") or 0
        lines.append(
            f"| {i} | {metric(r)}/{denom} | {calls} | {u.get('input_tokens', 0):,} | "
            f"{u.get('output_tokens', 0):,} | {u.get('cache_read_tokens', 0):,} | "
            f"{u.get('input_tokens', 0) / calls if calls else 0:,.0f} | "
            f"{u.get('output_tokens', 0) / calls if calls else 0:,.0f} | {r['wall_s']}s |"
        )
    mean = sum(metric(r) for r in results) / len(results)
    lines.append(f"\n**{kind} / {backend}: mean {mean:.2f}/{denom} over {len(results)} run(s)**")
    return "\n".join(lines)
