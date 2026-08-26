"""Serialize a `DomSnapshot` into the text the explore agent reads.

The browser layer owns the whole observe step — walk (`observer.py`) and render (here) — the
way browser-use's `dom/serializer`, Skyvern's `scraped_page.py` and Stagehand's
`treeFormatUtils` do. This is pure string formatting over the snapshot models: no model call,
no Playwright, so it stays inside the zero-LLM boundary and evals can render observations
without importing `agent/`. Element indices printed here are what the agent answers with;
`agent/explorer/observation.py::to_action` maps an index back to the element.
"""

import os

from netgent.browser.dom.models import DomSnapshot

__all__ = ["format_observation"]


def format_observation(snapshot: DomSnapshot, limit: int = 60, text_limit: int = 25) -> str:
    """Render the near-viewport slice of the page. Elements keep their original snapshot
    index (what the agent references); scrolling shifts which slice is shown."""
    lines = [f"URL: {snapshot.url}", f"TITLE: {snapshot.title}"]

    # Page the elements by top-viewport position so scroll reveals the next batch.
    vh = snapshot.viewport_height or 0
    indexed = list(enumerate(snapshot.interactive()))
    if vh:
        above = sum(1 for _, el in indexed if el.bbox.y < -60)
        visible = sorted((ie for ie in indexed if ie[1].bbox.y >= -60), key=lambda ie: ie[1].bbox.y)
    else:  # viewport unknown → show in document order, no paging
        above, visible = 0, indexed
    shown = visible[:limit]
    below = len(visible) - len(shown)
    # Group elements by the frame they live in and print a header per iframe, so the model
    # sees containment instead of a flat list that hides frame boundaries. Reference formats:
    # browser-use renders a non-clickable |IFRAME| line with the frame's elements indented
    # (dom/serializer/serializer.py:1030-1062); Playwright's aria snapshot merges the child
    # frame's tree under the iframe node (injected/ariaSnapshot.ts:229). Headers are not
    # indexed (the model never acts on them) and don't count toward the paging limit.
    distinct_frames: list[tuple[str, ...]] = []
    for _, el in shown:
        key = tuple(el.frame_path)
        if key not in distinct_frames:
            distinct_frames.append(key)
    # Zero extra lines when everything is in ONE frame (single-frame page, or scoped_to a form).
    # NETGENT_IFRAME_HEADERS=0 turns them off (for the A/B measurement in docs/research).
    use_headers = len(distinct_frames) > 1 and os.getenv("NETGENT_IFRAME_HEADERS", "1") != "0"
    if use_headers:
        shown = sorted(shown, key=lambda ie: (distinct_frames.index(tuple(ie[1].frame_path)), ie[1].bbox.y))
        frame_number = {k: n for n, k in enumerate((k for k in distinct_frames if k), start=1)}
    if vh:
        if not above and below:
            lines.append("POSITION: top of page. The elements below are the first ones — act on them.")
        elif above and not below:
            lines.append("POSITION: bottom of page. Nothing more below; do not scroll down further.")
        elif above and below:
            lines.append("POSITION: middle of page.")
    if above:
        lines.append(f"(↑ {above} elements above — already handled; scroll up only to revisit)")
    lines.append("INTERACTIVE ELEMENTS (near viewport):")

    current_frame: tuple[str, ...] | None = None
    for i, el in shown:
        key = tuple(el.frame_path)
        if use_headers and key != current_frame:
            current_frame = key
            if key:  # a non-top frame: emit a header before its elements (top frame gets none)
                label = " › ".join(key)
                count = sum(1 for _, e in shown if tuple(e.frame_path) == key)
                lines.append(f"|IFRAME {frame_number[key]}| {label[:80]} ({count} element{'s' if count != 1 else ''})")
        # Mark elements inside a CLOSED shadow root (browser-use's |SHADOW(closed)| prefix,
        # dom/serializer/serializer.py:1030-1062). Open roots get no marker — Playwright's
        # engines pierce them and the model gains nothing (Eugene addendum item 2).
        shadow = "|SHADOW(closed)| " if el.requires_closed_shadow else ""
        kind = shadow + el.tag
        if el.type:  # input[date], input[file], input[email] — the agent needs the type
            kind += f"[{el.type}]"
        elif el.role and el.role != el.tag:
            kind += f" ({el.role})"
        val = f' value="{el.value}"' if el.value else ""
        if el.options:
            val += f" options=[{', '.join(el.options)}]"
        name = f' "{el.name}"' if el.name else ""
        state = ""
        if el.checked is not None:
            state += " [checked]" if el.checked else " [unchecked]"
        if el.disabled:
            state += " [disabled]"
        if el.required:
            state += " [required]"
        if el.invalid:
            state += " [invalid: still needs a valid value]"
        lines.append(f"  [{i}] {kind}{name}{val}{state}")
    if below:
        lines.append(f"(↓ {below} more elements below — scroll down to reveal and reach them)")
    if snapshot.dialogs:
        # A dialog is the page's own message (often the success/error a plain form shows via
        # alert()). Shown once, at the step it happened; it was accepted so the page moved on.
        lines.append("DIALOGS (the page showed these; auto-accepted):")
        for d in snapshot.dialogs:
            lines.append(f"  !{d[:300]}")
    if snapshot.frames_skipped:
        lines.append(f"(⚠ {snapshot.frames_skipped} frame(s) could not be observed this step: "
                     + "; ".join(snapshot.skipped_frames[:3]) + ")")
    if snapshot.texts:
        lines.append("VISIBLE TEXT:")
        for t in snapshot.texts[:text_limit]:
            prefix = "  !ALERT " if t.alert else "  "
            lines.append(f"{prefix}{t.text}")
    return "\n".join(lines)
