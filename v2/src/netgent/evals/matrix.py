"""Assemble the backend comparison matrix from stress result JSONs.

Cost per step uses Anthropic Haiku 4.5 list prices ($1 / M input, $5 / M output); image tokens
are estimated per sent screenshot (1280×800 ≈ 1,365) and reported separately — the API's
input_tokens already includes them, so `text tokens` = input − images × per-image.
"""

import json
from pathlib import Path
from statistics import mean

IN_PRICE, OUT_PRICE = 1.0 / 1e6, 5.0 / 1e6
BACKENDS = ("dom", "ax", "hybrid", "hybrid_on_stuck")
KINDS = ("challenge", "sweep")


def load(results_dir: Path, kind: str, backend: str, tag: str) -> list[dict]:
    out = []
    for d in sorted(results_dir.glob(f"{kind}-{backend}{tag}-r*")):
        p = d / "result.json"
        if p.exists():
            out.append(json.loads(p.read_text()))
    return out


def row(kind: str, backend: str, runs: list[dict], img_tokens: int) -> str | None:
    if not runs:
        return None
    metric = [r["score"] if kind == "challenge" else r["submitted"] for r in runs]
    calls = [r["usage"]["calls"] for r in runs]
    inp = [r["usage"]["input_tokens"] for r in runs]
    outp = [r["usage"]["output_tokens"] for r in runs]
    imgs = [r["usage"].get("images", 0) for r in runs]
    wall = [r["wall_s"] for r in runs]
    img_tok = [i * img_tokens for i in imgs]
    text_tok = [a - b for a, b in zip(inp, img_tok, strict=True)]
    cost = [i * IN_PRICE + o * OUT_PRICE for i, o in zip(inp, outp, strict=True)]
    cost_step = [c / n for c, n in zip(cost, calls, strict=True)]
    denom = "15" if kind == "challenge" else str(runs[0].get("total", 21))
    return (
        f"| {kind} | {backend} | **{mean(metric):.1f}**/{denom} ({', '.join(map(str, metric))}) | "
        f"{mean(calls):.0f} | {mean(text_tok):,.0f} | {mean(img_tok):,.0f} ({mean(imgs):.0f} imgs) | "
        f"{mean(outp):,.0f} | {mean(wall):.0f}s | ${mean(cost):.3f} | {mean(cost_step) * 100:.2f}¢ |"
    )


HEAD = (
    "| task | backend | result mean (per run) | LLM calls | text tokens | image tokens | output tokens | wall | "
    "cost/run | cost/step |\n|---|---|---|---|---|---|---|---|---|---|"
)


def build(results_dir: Path, tags: list[str], image_tokens: int = 1365) -> str:
    lines = [HEAD]
    for tag in tags:
        for kind in KINDS:
            for b in BACKENDS:
                r = row(kind, b, load(results_dir, kind, b, tag), image_tokens)
                if r:
                    lines.append(r)
    if len(lines) == 1:
        lines.append("| (no results found) ||||||||||")
    return "\n".join(lines)
