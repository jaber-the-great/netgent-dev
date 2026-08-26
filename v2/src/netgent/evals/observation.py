"""Observation-backend metrics on live or local pages — no LLM.

For each site, ONE page load is snapshotted with every requested backend in turn (so coverage
differences are the backend's, not the feed's). Per backend: interactive element count, % with
a non-empty name, % with a get_by_role locator, % whose durable locator resolves to exactly one
element, observation size (chars / ~tokens), snapshot wall-clock, iframe coverage.

This branch has the DOM walk; the accessibility-tree/hybrid backends arrive with the observation
branch and share this runner and its result layout.

    rows, md = asyncio.run(run(sites={"forms": URL}, backends=("dom",)))
"""

import json
import statistics
import time
from pathlib import Path

from netgent.agent.explorer.observation import _locator_for
from netgent.browser.dom import format_observation
from netgent.browser.session import BrowserSession

SITES = {
    "youtube": "https://www.youtube.com/",
    "twitch": "https://www.twitch.tv/",
    "reddit": "https://www.reddit.com/",
    "forms": "https://browser-use.github.io/stress-tests/forms-comparison.html",
    "challenge": "https://browser-use.github.io/stress-tests/challenge.html",
    "todomvc-spa": "https://demo.playwright.dev/todomvc",
}
ALL_BACKENDS = ("dom",)


def resolve_sites(spec: list[str] | None) -> dict[str, str]:
    """`["youtube", "mine=file:///x.html"]` → {name: url}; None → every known site."""
    if not spec:
        return dict(SITES)
    out: dict[str, str] = {}
    for item in spec:
        if "=" in item:
            name, url = item.split("=", 1)
            out[name.strip()] = url.strip()
        elif item in SITES:
            out[item] = SITES[item]
        else:
            raise ValueError(f"unknown site {item!r}; use one of {sorted(SITES)} or name=url")
    return out


def _key(e) -> tuple:
    # Same element across backends: same frame, tag, and (coarse) position/size. x is excluded
    # so a 1-2px iframe border difference does not split a match.
    return (tuple(e.frame_path), e.tag, round(e.bbox.y / 6), round(e.bbox.h / 6), round(e.bbox.w / 6))


async def measure_site(url: str, backends: tuple[str, ...], repeats: int = 3) -> dict[str, dict]:
    """All backends on the SAME loaded page: open once, snapshot with each backend in turn."""
    for b in backends:
        if b not in ALL_BACKENDS:
            raise ValueError(f"backend {b!r} is not available on this branch; use one of {ALL_BACKENDS}")
    async with BrowserSession(headless=True) as s:
        await s.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            await s.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001 — live sites may never go idle
            pass
        await s.page.wait_for_timeout(1500 if not url.startswith("file:") else 200)
        return {backend: await measure(s, backend, repeats) for backend in backends}


async def measure(s: BrowserSession, backend: str, repeats: int = 3) -> dict:
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
        role_loc += int(any(step.fn == "get_by_role" for step in chain))
        try:
            n = await s.resolve(chain).count()
        except Exception:  # noqa: BLE001
            n = -1
        resolved_any += int(n >= 1)
        unique += int(n == 1)
        details.append(
            {"name": e.name, "tag": e.tag, "role": e.role, "frame": e.frame_path, "n": n,
             "key": json.dumps(_key(e))}
        )
    obs = format_observation(snap)
    n_el = len(elements)
    return {
        "backend": backend,
        "url": url,
        "elements": n_el,
        "named_pct": round(100 * named / n_el, 1) if n_el else 0.0,
        "role_locator_pct": round(100 * role_loc / n_el, 1) if n_el else 0.0,
        "unique_pct": round(100 * unique / n_el, 1) if n_el else 0.0,
        "resolves_pct": round(100 * resolved_any / n_el, 1) if n_el else 0.0,
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


COLUMNS = [
    ("site", "site"), ("backend", "backend"), ("elements", "elements"), ("named %", "named_pct"),
    ("role loc %", "role_locator_pct"), ("unique %", "unique_pct"), ("resolves %", "resolves_pct"),
    ("obs chars", "obs_chars"), ("~tokens", "obs_tokens_est"), ("texts", "texts"),
    ("snapshot s", "snapshot_s"), ("frames", "frames"), ("in iframes", "in_iframe"),
    ("iframes w/ elems", "iframes_with_elements"),
]


def table(rows: list[dict]) -> str:
    out = ["| " + " | ".join(c for c, _ in COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(k, "")) for _, k in COLUMNS) + " |")
    return "\n".join(out)


async def run(
    sites: dict[str, str], backends: tuple[str, ...] = ALL_BACKENDS, progress=None
) -> tuple[list[dict], str]:
    """Measure every site with every backend. Returns (rows, markdown report)."""
    rows: list[dict] = []
    for name, url in sites.items():
        try:
            per = await measure_site(url, backends)
        except Exception as exc:  # noqa: BLE001 — report the failure as rows
            per = {b: {"backend": b, "url": url, "error": str(exc)[:200], "keys": [], "details": []} for b in backends}
        for backend in backends:
            r = per[backend]
            r["site"] = name
            rows.append(r)
            if progress:
                progress(table([r]).splitlines()[-1])
    md = [
        "# Observation backend metrics",
        "",
        f"Generated by `netgent eval observation` on {time.strftime('%Y-%m-%d')}. Headless Chromium, "
        "median of 3 snapshots per backend on ONE page load. `unique %` = durable locator resolves to "
        "exactly one element; `role loc %` = locator is a get_by_role chain. Tokens are chars/4.",
        "",
        table(rows),
        "",
    ]
    return rows, "\n".join(md)


def write(rows: list[dict], md: str, out_dir: Path, stem: str = "observation_ab") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.md").write_text(md)
    slim = [{k: v for k, v in r.items() if k not in ("keys", "details")} for r in rows]
    (out_dir / f"{stem}.json").write_text(json.dumps(slim, indent=2))
    return out_dir / f"{stem}.md"
