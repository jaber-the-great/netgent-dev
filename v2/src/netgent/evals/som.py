"""Set-of-Marks geometry check — is the overlay CORRECT on real (and hard) pages? No LLM.

For each site it renders the marks, saves the annotated PNG, and reports per page:

  listed / in view / marks   elements listed, in the viewport, and drawn
  identity %                 (hit + covered) / marks — the drawn number sits on the element
  hit / covered / miss       elementFromPoint at the box centre (composed tree, per frame) lands on
                             the element | on a larger overlay (drawn hollow — correct) | elsewhere
  label overlaps             labels that had to fall back onto an occupied slot
  unmarked in view           in-viewport listed elements with no mark (should be 0)
  render ms                  Pillow render time

Built-in fixtures cover the hard cases: a fixed header + modal backdrop, an RTL page, a canvas
page, and a mobile viewport.
"""

import io
import json
import time
from pathlib import Path

from netgent.agent.explore_agent.marks import layout_marks, marks_for, render_set_of_marks
from netgent.agent.explore_agent.observation import shown_elements
from netgent.browser.session import BrowserSession
from netgent.evals.observation import SITES as LIVE

FIXED_AND_MODAL = """<!doctype html><html><head><meta charset=utf-8><title>Fixed+Modal</title>
<style>
  header{position:fixed;top:0;left:0;right:0;height:60px;background:#123;color:#fff;z-index:10}
  .modal{position:fixed;inset:20% 25%;background:#fff;border:3px solid #333;z-index:100;padding:20px}
  .backdrop{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:90}
  main{margin-top:80px}
</style></head><body>
<header><button id=home>Home</button> <button id=acct>Account</button></header>
<main>
  <button id=below1>Behind the modal 1</button><br><br>
  <button id=below2>Behind the modal 2</button>
  <div style="transform:scale(1.5) rotate(3deg);margin:40px"><button id=xf>Transformed</button></div>
</main>
<div class=backdrop></div>
<div class=modal><h2>Confirm</h2><button id=ok>OK</button> <button id=cancel>Cancel</button></div>
</body></html>"""

RTL = """<!doctype html><html dir=rtl lang=ar><head><meta charset=utf-8><title>RTL</title></head>
<body style="font-size:20px">
  <button id=a>حفظ الملف</button>
  <input id=e placeholder="البريد الإلكتروني" style="width:300px">
  <button id=b>إرسال 🚀</button>
  <div style="overflow-x:auto;width:300px;white-space:nowrap">
    <button id=c>عنصر داخل حاوية أفقية طويلة جدا جدا جدا</button>
  </div>
</body></html>"""

CANVAS = """<!doctype html><html><head><meta charset=utf-8><title>Canvas</title></head><body>
<canvas id=c width=300 height=100></canvas>
<input id=t placeholder="type the code"><button id=go>Go</button>
<script>const x=document.getElementById('c').getContext('2d');
x.font='30px Arial';x.fillText('AX7Q9',20,60);</script>
</body></html>"""

FIXTURES: dict[str, tuple[str | None, str | None, tuple[int, int] | None]] = {
    # name: (url, inline html, viewport)
    "fixed+modal": (None, FIXED_AND_MODAL, None),
    "rtl": (None, RTL, None),
    "canvas": (None, CANVAS, None),
    "forms-mobile": (LIVE["forms"], None, (390, 844)),
}


Job = tuple[str, str | None, str | None, tuple[int, int] | None]


def resolve_jobs(spec: list[str] | None) -> list[Job]:
    """Site names (live or fixture) or `name=url` → job tuples; None → all live + all fixtures."""
    if not spec:
        return [(n, u, None, None) for n, u in LIVE.items()] + [(n, *v) for n, v in FIXTURES.items()]
    jobs = []
    for item in spec:
        if "=" in item:
            name, url = item.split("=", 1)
            jobs.append((name.strip(), url.strip(), None, None))
        elif item in LIVE:
            jobs.append((item, LIVE[item], None, None))
        elif item in FIXTURES:
            jobs.append((item, *FIXTURES[item]))
        else:
            raise ValueError(f"unknown site {item!r}; use {sorted(LIVE)} / {sorted(FIXTURES)} or name=url")
    return jobs


async def check(session: BrowserSession, name: str, out_dir: Path) -> dict:
    snap = await session.snapshot()
    _, shown, _ = shown_elements(snap)
    vw, vh = await session.viewport_size()
    marks = marks_for(shown, vw, vh)
    png = await session.capture_viewport_png()
    drawn = {m.index for m in marks}
    hits = await session.mark_hits([(i, el) for i, el in shown if i in drawn])
    t = time.perf_counter()
    annotated = render_set_of_marks(png, marks, vw, vh, covered={i for i, r in hits.items() if r != "hit"})
    render_ms = round((time.perf_counter() - t) * 1000, 1)
    (out_dir / f"{name}.png").write_bytes(annotated)
    n_hit = sum(1 for v in hits.values() if v == "hit")
    n_cov = sum(1 for v in hits.values() if v == "covered")
    n_miss = sum(1 for v in hits.values() if v == "miss")

    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(io.BytesIO(png))
    sc = im.width / vw if vw else 1.0
    try:
        font = ImageFont.truetype("Arial.ttf", 13)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    d = ImageDraw.Draw(im)
    layout = layout_marks(marks, sc, im.width, im.height, lambda s: int(d.textlength(s, font=font)))
    overlaps = sum(1 for pl in layout if pl.collided)

    def _visible(el):
        return not (el.bbox.x + el.bbox.w < 0 or el.bbox.x > vw or el.bbox.y + el.bbox.h < 0 or el.bbox.y > vh)

    in_view = [i for i, el in shown if _visible(el)]
    return {
        "site": name,
        "viewport": f"{vw}x{vh}",
        "listed": len(shown),
        "in_viewport": len(in_view),
        "marks": len(marks),
        "identity_pct": round(100 * (n_hit + n_cov) / len(drawn), 1) if drawn else 0.0,
        "hit": n_hit,
        "covered": n_cov,
        "miss": n_miss,
        "label_overlaps": overlaps,
        "unmarked_in_view": len([i for i in in_view if i not in drawn]),
        "render_ms": render_ms,
    }


async def run_site(name: str, url: str | None, html: str | None, out_dir: Path, viewport=None) -> dict:
    try:
        async with BrowserSession(headless=True, observation="hybrid") as s:
            if viewport:
                await s.page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
            if html is not None:
                await s.page.set_content(html)
                await s.page.wait_for_timeout(200)
            else:
                await s.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    await s.page.wait_for_load_state("networkidle", timeout=12_000)
                except Exception:  # noqa: BLE001
                    pass
                await s.page.wait_for_timeout(1200 if not url.startswith("file:") else 200)
            return await check(s, name, out_dir)
    except Exception as exc:  # noqa: BLE001
        return {"site": name, "error": str(exc)[:160]}


COLUMNS = [
    ("site", "site"), ("viewport", "viewport"), ("listed", "listed"), ("in view", "in_viewport"),
    ("marks", "marks"), ("identity %", "identity_pct"), ("hit", "hit"), ("covered", "covered"),
    ("miss", "miss"), ("label overlaps", "label_overlaps"), ("unmarked in view", "unmarked_in_view"),
    ("render ms", "render_ms"),
]


def table(rows: list[dict]) -> str:
    lines = ["| " + " | ".join(c for c, _ in COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")) for _, k in COLUMNS) + " |")
    return "\n".join(lines)


async def run(jobs, out_dir: Path, progress=None) -> tuple[list[dict], str]:
    """Render + check every job; annotated PNGs go to out_dir (must exist — see `write`/the CLI).
    Returns (rows, markdown)."""
    rows = []
    for name, url, html, vp in jobs:
        r = await run_site(name, url, html, out_dir, viewport=vp)
        rows.append(r)
        if progress:
            progress(table([r]).splitlines()[-1])
    md = [
        "# Set-of-Marks geometry check",
        "",
        "`netgent eval som`, headless Chromium. For each drawn mark, elementFromPoint at the box center "
        "(in the element's own frame, composed-tree/shadow aware): `hit` = lands on the element; "
        "`covered` = a larger element sits on top (modal/backdrop/fixed header) and the mark is drawn "
        "hollow — the correct outcome; `miss` = a geometry error. `identity %` = (hit + covered) / marks. "
        f"Annotated PNGs in `{out_dir}/`.",
        "",
        table(rows),
        "",
    ]
    return rows, "\n".join(md)


def write(rows: list[dict], md: str, out_dir: Path, stem: str = "som_check") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.md").write_text(md)
    (out_dir / f"{stem}.json").write_text(json.dumps(rows, indent=2))
    return out_dir / f"{stem}.md"
