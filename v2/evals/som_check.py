"""Set-of-Marks geometry checker — is the overlay CORRECT on real (and hard) pages?

For each site (incl. a fixed-header+modal fixture, an RTL page, a canvas page, and a mobile
viewport run) it renders the marks, saves the annotated PNG, and reports:

  listed        interactive elements in the observation
  marks         boxes actually drawn (in-viewport subset)
  identity %    marks whose box CENTER hits the intended element (elementFromPoint per frame)
  label-overlap % marks whose label rectangle overlaps another mark's label
  unmarked %    listed elements in the viewport with NO mark (should be ~0)
  render ms     Pillow render time

    uv run python evals/som_check.py [--out evals/results/som_check.md]

No LLM. `identity %` is the headline: it proves the drawn number sits on the element the text
list names, across iframes, shadow DOM, transforms, DPR, and occluding modals.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from netgent.agent.explore_agent.marks import LABEL_H, LABEL_PAD, marks_for, render_set_of_marks
from netgent.agent.explore_agent.observation import shown_elements
from netgent.browser.session import BrowserSession

# A fixed header that covers the top of the page + a modal overlay that occludes everything
# behind it — the classic SoM failure (marking covered elements).
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

LIVE = {
    "youtube": "https://www.youtube.com/",
    "twitch": "https://www.twitch.tv/",
    "reddit": "https://www.reddit.com/",
    "forms": "https://browser-use.github.io/stress-tests/forms-comparison.html",
    "challenge": "https://browser-use.github.io/stress-tests/challenge.html",
}


def _label_rect(m, scale):
    b = m.bbox
    x0 = int(b.x * scale)
    y0 = int(b.y * scale)
    return (x0, max(0, y0 - LABEL_H), x0 + 12 + 2 * LABEL_PAD, max(0, y0 - LABEL_H) + LABEL_H)


def _overlap(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


async def check(session: BrowserSession, name: str, out_dir: Path) -> dict:
    snap = await session.snapshot()
    _, shown, _ = shown_elements(snap)
    vw, vh = await session.viewport_size()
    marks = marks_for(shown, vw, vh)
    png = await session.capture_viewport_png()
    t = time.perf_counter()
    annotated = render_set_of_marks(png, marks, vw, vh)
    render_ms = round((time.perf_counter() - t) * 1000, 1)
    (out_dir / f"{name}.png").write_bytes(annotated)

    drawn = {m.index for m in marks}
    hits = await session.mark_hits([(i, el) for i, el in shown if i in drawn])
    identity = sum(1 for v in hits.values() if v)
    # label overlap: compare label rects at the image scale the renderer uses
    import io as _io

    from PIL import Image
    img_w = Image.open(_io.BytesIO(png)).width
    sc = img_w / vw if vw else 1.0
    rects = [_label_rect(m, sc) for m in marks]
    overlaps = sum(1 for i in range(len(rects)) for j in range(i + 1, len(rects)) if _overlap(rects[i], rects[j]))

    def _visible(el):
        return not (el.bbox.x + el.bbox.w < 0 or el.bbox.x > vw or el.bbox.y + el.bbox.h < 0 or el.bbox.y > vh)

    in_view = [i for i, el in shown if _visible(el)]
    unmarked = [i for i in in_view if i not in drawn]
    return {
        "site": name,
        "viewport": f"{vw}x{vh}",
        "listed": len(shown),
        "in_viewport": len(in_view),
        "marks": len(marks),
        "identity_pct": round(100 * identity / len(drawn), 1) if drawn else 0.0,
        "label_overlaps": overlaps,
        "unmarked_in_view": len(unmarked),
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
                await s.page.wait_for_timeout(1200)
            return await check(s, name, out_dir)
    except Exception as exc:  # noqa: BLE001
        return {"site": name, "error": str(exc)[:160]}


async def main(out: Path) -> "tuple[str, list]":
    out_dir = out.parent / "som"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    jobs = [(n, u, None, None) for n, u in LIVE.items()] + [
        ("fixed+modal", None, FIXED_AND_MODAL, None),
        ("rtl", None, RTL, None),
        ("canvas", None, CANVAS, None),
        ("forms-mobile", LIVE["forms"], None, (390, 844)),
    ]
    for name, url, html, vp in jobs:
        r = await run_site(name, url, html, out_dir, viewport=vp)
        rows.append(r)
        print(r, flush=True)

    cols = [("site", "site"), ("viewport", "viewport"), ("listed", "listed"), ("in view", "in_viewport"),
            ("marks", "marks"), ("identity %", "identity_pct"), ("label overlaps", "label_overlaps"),
            ("unmarked in view", "unmarked_in_view"), ("render ms", "render_ms")]
    lines = ["| " + " | ".join(c for c, _ in cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")) for _, k in cols) + " |")
    md = [
        "# Set-of-Marks geometry check",
        "",
        "`evals/som_check.py`, headless Chromium. `identity %` = drawn marks whose box center hits the "
        "intended element (elementFromPoint per frame, occlusion- and iframe-aware). Annotated PNGs "
        "in `evals/results/som/`.",
        "",
        "\n".join(lines),
        "",
    ]
    return "\n".join(md), rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("evals/results/som_check.md"))
    args = ap.parse_args()
    _md, _rows = asyncio.run(main(args.out))
    args.out.write_text(_md)
    args.out.with_suffix(".json").write_text(json.dumps(_rows, indent=2))
    print("wrote", args.out)
