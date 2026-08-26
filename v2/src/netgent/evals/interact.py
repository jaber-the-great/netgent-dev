"""Zero-LLM interactability eval: can the ACTION layer operate every observed element?

For each element the snapshot reports, dispatch its canonical action through the real
dispatcher (fill / select / check / upload / click) and verify the effect by reading the
element back. No model, no decisions — a deterministic measurement of observation +
resolution + fallback-ladder coverage, so action-layer regressions are caught for cents in
~2 minutes instead of an LLM sweep. Submit buttons are skipped on purpose (pressing them
ends the form and would serialize the run); links in the TOP frame are skipped (navigation
would tear down the page under test).
"""

import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from netgent.browser import BrowserSession
from netgent.evals.observation import SITES, resolve_sites  # noqa: F401 — same site registry
from netgent.schema.actions import ClickAction, FillAction, SelectAction, UploadFileAction

FILL_BY_TYPE = {"date": "1990-05-15", "email": "eval@example.com", "tel": "5551234567", "number": "42"}


async def _try_element(session: BrowserSession, element, sample: str) -> tuple[str, str]:
    """(verdict ok|FAIL|skip, detail) for one element's canonical action."""
    from netgent.agent.explorer.observation import unique_locator_for

    chain = await unique_locator_for(session, element)
    locator = session.resolve(chain).first
    kind = (element.type or "").lower()
    try:
        if element.tag == "select":
            options = element.options or []
            if not options:
                return "skip", "no options"
            await session.dispatch(SelectAction(locator=chain, value=options[0], timeout_ms=4000))
            got = await locator.evaluate("el => el.value", timeout=3000)
            return ("ok", got) if got == options[0] else ("FAIL", f"value={got!r}")
        if kind in ("radio", "checkbox"):
            await session.dispatch(ClickAction(locator=chain, timeout_ms=4000))
            checked = await locator.evaluate("el => el.checked", timeout=3000)
            return ("ok", "checked") if checked else ("FAIL", "not checked after click")
        if kind == "file":
            await session.dispatch(UploadFileAction(locator=chain, paths=[sample], timeout_ms=5000))
            n = await locator.evaluate("el => el.files ? el.files.length : -1", timeout=3000)
            return ("ok", "file set") if n == 1 else ("FAIL", f"files={n}")
        if element.tag in ("input", "textarea") or (element.role == "textbox" and element.tag == "div"):
            text = FILL_BY_TYPE.get(kind, "hello")
            await session.dispatch(FillAction(locator=chain, text=text, timeout_ms=5000))
            got = await locator.evaluate(
                "el => el.isContentEditable ? el.textContent : String(el.value)", timeout=3000
            )
            return ("ok", got[:16]) if got.strip() else ("FAIL", "empty after fill")
        if kind == "submit" or "submit" in (element.name or "").lower():
            return "skip", "submit button (would end the form)"
        if element.tag in ("button", "a", "label") or element.role in ("button", "combobox"):
            await session.dispatch(ClickAction(locator=chain, timeout_ms=4000))
            return "ok", "clicked"
        return "skip", f"unclassified {element.tag}[{kind or element.role}]"
    except Exception as exc:  # noqa: BLE001 — the failure IS the measurement
        return "FAIL", str(exc).splitlines()[0][:90]


def _sample_file(tmp_dir: str) -> str:
    path = Path(tmp_dir) / "netgent-interact-sample.txt"
    path.write_text("netgent interact eval\n")
    return str(path)


async def run(
    sites: dict[str, str], progress: Callable[[str], None] = lambda s: None, tmp_dir: str = "/tmp"
) -> tuple[list[dict], str]:
    sample = _sample_file(tmp_dir)
    rows: list[dict] = []
    lines: list[str] = []
    for name, url in sites.items():
        async with BrowserSession(headless=True) as session:
            await session.page.goto(url, wait_until="networkidle")
            await session.page.wait_for_timeout(1500)
            start = time.perf_counter()
            snapshot = await session.snapshot()
            verdicts: Counter = Counter()
            fails: list[str] = []
            for element in snapshot.elements:
                if element.tag == "a" and not element.frame_path:
                    continue  # top-frame navigation links would tear down the page under test
                verdict, detail = await _try_element(session, element, sample)
                verdicts[verdict] += 1
                if verdict == "FAIL":
                    frame = element.frame_path[-1][:40] if element.frame_path else "(top)"
                    fails.append(f"{frame} {element.tag}[{element.type or element.role}] "
                                 f"{element.name!r}: {detail}")
            wall = time.perf_counter() - start
            rows.append({"site": name, "ok": verdicts["ok"], "fail": verdicts["FAIL"],
                         "skip": verdicts["skip"], "attempted": sum(verdicts.values()),
                         "wall_s": round(wall, 1), "fails": fails})
            progress(f"{name}: {verdicts['ok']} ok, {verdicts['FAIL']} FAIL, "
                     f"{verdicts['skip']} skipped ({wall:.0f}s)")
            lines.extend(f"  FAIL {f}" for f in fails)
    return rows, table(rows) + ("\n" + "\n".join(lines) if lines else "")


def table(rows: list[dict]) -> str:
    head = "| site | ok | FAIL | skipped | attempted | wall s |\n|---|---:|---:|---:|---:|---:|"
    body = "\n".join(
        f"| {r['site']} | {r['ok']} | {r['fail']} | {r['skip']} | {r['attempted']} | {r['wall_s']} |"
        for r in rows
    )
    return head + "\n" + body


def write(rows: list[dict], md: str, out_dir: Path, stem: str = "interact") -> Path:
    import json

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.json").write_text(json.dumps(rows, indent=2) + "\n")
    path = out_dir / f"{stem}.md"
    path.write_text(md + "\n")
    return path
