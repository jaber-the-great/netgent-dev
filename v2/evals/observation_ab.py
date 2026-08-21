"""A/B the observation backends (DOM walk vs accessibility tree) on live sites — no LLM.

For each site and backend: interactive element count, % with a non-empty name, % whose
durable locator resolves to exactly one element, observation size (chars / ~tokens),
snapshot wall-clock, iframe + shadow coverage, and the symmetric difference of elements
(by frame + bbox) so "what does one backend see that the other doesn't" is reported, not
asserted.

    uv run python evals/observation_ab.py [--out evals/results/observation_ab.md] [--sites name,...]
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from netgent.agent.explore_agent.observation import _locator_for, format_observation
from netgent.browser.session import BrowserSession

SITES = {
    "youtube": "https://www.youtube.com/",
    "twitch": "https://www.twitch.tv/",
    "reddit": "https://www.reddit.com/",
    "forms": "https://browser-use.github.io/stress-tests/forms-comparison.html",
    "challenge": "https://browser-use.github.io/stress-tests/challenge.html",
    "todomvc-spa": "https://demo.playwright.dev/todomvc",
}
BACKENDS = ("dom", "ax")


def _key(e) -> tuple:
    # Same element across backends: same frame, tag, and (coarse) position/size. x is
    # excluded so a 1-2px iframe border difference does not split a match.
    return (tuple(e.frame_path), e.tag, round(e.bbox.y / 6), round(e.bbox.h / 6), round(e.bbox.w / 6))


async def measure_site(url: str, repeats: int = 3) -> dict[str, dict]:
    """Both backends on the SAME loaded page (so coverage differences are the backend's, not
    the feed's): open once, snapshot with each backend in turn."""
    async with BrowserSession(headless=True, observation="dom") as s:
        await s.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            await s.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001 — live sites may never go idle
            pass
        await s.page.wait_for_timeout(1500)
        return {backend: await measure(s, backend, repeats) for backend in BACKENDS}


async def measure(s: BrowserSession, backend: str, repeats: int = 3) -> dict:
    s.observation = backend
    url = s.page.url
    times = []
    snap = None
    for _ in range(repeats):
        t = time.perf_counter()
        snap = await s.snapshot()
        times.append(time.perf_counter() - t)
    assert snap is not None
    elements = snap.elements
    named = sum(1 for e in elements if e.name)
    role_loc = unique = resolved_any = 0
    details = []
    for e in elements:
        try:
            chain = _locator_for(e)
        except ValueError:
            continue
        is_role = any(step.fn == "get_by_role" for step in chain)
        role_loc += int(is_role)
        try:
            n = await s._resolve(chain).count()
        except Exception:  # noqa: BLE001
            n = -1
        resolved_any += int(n >= 1)
        unique += int(n == 1)
        details.append(
            {"name": e.name, "tag": e.tag, "role": e.role, "frame": e.frame_path, "n": n,
             "key": json.dumps(_key(e))}
        )
    obs = format_observation(snap)
    return {
        "backend": backend,
        "url": url,
        "elements": len(elements),
        "named_pct": round(100 * named / len(elements), 1) if elements else 0.0,
        "role_locator_pct": round(100 * role_loc / len(elements), 1) if elements else 0.0,
        "unique_pct": round(100 * unique / len(elements), 1) if elements else 0.0,
        "resolves_pct": round(100 * resolved_any / len(elements), 1) if elements else 0.0,
        "obs_chars": len(obs),
        "obs_tokens_est": len(obs) // 4,
        "texts": len(snap.texts),
        "snapshot_s": round(statistics.median(times), 3),
        "frames": len(s.page.frames),
        "in_iframe": sum(1 for e in elements if e.frame_path),
        "iframes_with_elements": len({tuple(e.frame_path) for e in elements if e.frame_path}),
        "keys": sorted({json.dumps(_key(e)) for e in elements}),
        "details": details,
    }


def table(rows: list[dict]) -> str:
    cols = [
        ("site", "site"), ("backend", "backend"), ("elements", "elements"), ("named %", "named_pct"),
        ("role loc %", "role_locator_pct"), ("unique %", "unique_pct"), ("resolves %", "resolves_pct"),
        ("obs chars", "obs_chars"), ("~tokens", "obs_tokens_est"), ("texts", "texts"),
        ("snapshot s", "snapshot_s"), ("frames", "frames"), ("in iframes", "in_iframe"),
        ("iframes w/ elems", "iframes_with_elements"),
    ]
    out = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(k, "")) for _, k in cols) + " |")
    return "\n".join(out)


async def main(sites: list[str]) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    diffs: list[str] = []
    for name in sites:
        url = SITES[name]
        try:
            per = await measure_site(url)
        except Exception as exc:  # noqa: BLE001 — report the failure as rows
            per = {b: {"backend": b, "url": url, "error": str(exc)[:200], "keys": [], "details": []} for b in BACKENDS}
        for backend in BACKENDS:
            r = per[backend]
            r["site"] = name
            rows.append(r)
            print(table([r]).splitlines()[-1], flush=True)
        a, b = set(per["dom"]["keys"]), set(per["ax"]["keys"])
        diffs.append(
            f"- **{name}**: {len(a & b)} elements seen by both (by frame+bbox), "
            f"{len(a - b)} only by dom, {len(b - a)} only by ax."
        )
        # name a few of each side's exclusives for the doc
        ex_dom = _exclusives(per["dom"], a - b)
        ex_ax = _exclusives(per["ax"], b - a)
        if ex_dom:
            diffs.append(f"  - dom-only e.g.: {ex_dom}")
        if ex_ax:
            diffs.append(f"  - ax-only e.g.: {ex_ax}")

    return rows, diffs


def write_report(rows: list[dict], diffs: list[str], out: Path) -> None:
    md = [
        "# Observation backend A/B — DOM walk vs accessibility tree",
        "",
        f"Generated by `evals/observation_ab.py` on {time.strftime('%Y-%m-%d')}. Headless Chromium, 1280px viewport, "
        "median of 3 snapshots. `unique %` = durable locator resolves to exactly one element; "
        "`role loc %` = locator is a get_by_role chain. Tokens are chars/4.",
        "",
        table(rows),
        "",
        "## Coverage differences (elements matched across backends by frame + bounding box)",
        "",
        *diffs,
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md))
    slim = [{k: v for k, v in r.items() if k not in ("keys", "details")} for r in rows]
    out.with_suffix(".json").write_text(json.dumps(slim, indent=2))
    print(f"\nwrote {out}")


def _exclusives(r: dict, keys: set[str]) -> str:
    """A few elements (tag + name) of this backend whose frame+bbox key the other lacks."""
    return ", ".join(repr(n)[:40] for n in _sample_names(r, keys))


def _sample_names(r: dict, keys: set[str]) -> list[str]:
    out = []
    for d in r.get("details", []):
        if d.get("key") in keys and d["name"]:
            out.append(f"{d['tag']} {d['name']}")
        if len(out) >= 6:
            break
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("evals/results/observation_ab.md"))
    ap.add_argument("--sites", default=",".join(SITES))
    args = ap.parse_args()
    write_report(*asyncio.run(main(args.sites.split(","))), args.out)
