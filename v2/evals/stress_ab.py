"""End-to-end A/B of the observation backends with the cheap model (Haiku).

    uv run python evals/stress_ab.py challenge --backend ax [--max-steps 60] [--runs 1]
    uv run python evals/stress_ab.py sweep --backend dom [--max-steps 30]

`challenge`: one BrowserAgent run on browser-use's challenge game; reports the score the
page itself shows, the list of completed task ids, steps, and the errors seen.
`sweep`: `sweep_forms` on the 21-form stress page; reports per-form verified pass/fail.
Results are written under evals/results/stress/<kind>-<backend>[-N].json (+ trajectories).
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from netgent.agent import BrowserAgent, make_llm
from netgent.agent.explore_agent.sweep import sweep_forms
from netgent.browser.session import BrowserSession
from netgent.core.settings import get_settings

CHALLENGE_URL = "https://browser-use.github.io/stress-tests/challenge.html"
FORMS_URL = "https://browser-use.github.io/stress-tests/forms-comparison.html"
MODEL = "anthropic/claude-haiku-4-5-20251001"

# The exact prompt used for the acceptance run (documented in
# docs/research/accessibility-tree-observation.md).
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


async def run_challenge(backend: str, max_steps: int, out_dir: Path) -> dict:
    llm = make_llm(MODEL)
    t0 = time.perf_counter()
    async with BrowserSession(headless=True, observation=backend) as s:
        agent = BrowserAgent(llm, max_steps=max_steps, run_dir=out_dir)
        traj = await agent.run(s, CHALLENGE_TASK, CHALLENGE_URL)
        score = await s.page.locator(".score").inner_text()
        done_ids = await s.page.eval_on_selector_all(".task.completed", "els => els.map(e => e.id)")
        all_ids = await s.page.eval_on_selector_all(".task", "els => els.map(e => e.id)")
    usage = getattr(llm, "usage", None)
    return {
        "kind": "challenge",
        "backend": backend,
        "model": MODEL,
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
    }


async def run_sweep(backend: str, max_steps: int, out_dir: Path) -> dict:
    llm = make_llm(MODEL)
    t0 = time.perf_counter()
    async with BrowserSession(headless=True, observation=backend) as s:
        await s.page.goto(FORMS_URL, wait_until="networkidle")
        result = await sweep_forms(s, llm, max_steps_per_form=max_steps, retries=1)
    usage = getattr(llm, "usage", None)
    return {
        "kind": "sweep",
        "backend": backend,
        "model": MODEL,
        "max_steps_per_form": max_steps,
        "total": result.total,
        "submitted": result.submitted,
        "forms": [f.model_dump() for f in result.forms],
        "wall_s": round(time.perf_counter() - t0, 1),
        "usage": usage if isinstance(usage, dict) else None,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["challenge", "sweep"])
    ap.add_argument("--backend", choices=["dom", "ax", "hybrid", "hybrid_on_stuck"], required=True)
    ap.add_argument("--max-steps", type=int, default=None)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    get_settings().sync_provider_keys()  # publish .env keys to the SDKs
    out_dir = Path("evals/results/stress") / f"{args.kind}-{args.backend}{args.tag}"
    if args.kind == "challenge":
        result = await run_challenge(args.backend, args.max_steps or 60, out_dir)
    else:
        result = await run_sweep(args.backend, args.max_steps or 30, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "forms"}, indent=2))
    if "forms" in result:
        for f in result["forms"]:
            print(f"  form {f['form']:2d} {'OK ' if f['submitted'] else 'FAIL'} steps={f['steps']} {f['frame_path']}")


if __name__ == "__main__":
    asyncio.run(main())
