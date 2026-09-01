"""Serialize a `DomSnapshot` into the text the explore agent reads.

The browser layer owns the whole observe step — walk (`observer.py`) and render (here) — the
way browser-use's `dom/serializer`, Skyvern's `scraped_page.py` and Stagehand's
`treeFormatUtils` do. This is pure string formatting over the snapshot models: no model call,
no Playwright, so it stays inside the zero-LLM boundary and evals can render observations
without importing `agent/`. Element indices printed here are what the agent answers with;
`agent/explorer/actions.py::to_action` maps an index back to the element.

Viewport policy (docs/research/browser-agent-prompting.md §6.3, §7.2 S2/S3): one viewport of
scrollback is KEPT and marked "(above viewport)" instead of being dropped — the old 60 px cut
was the strictest in the survey and hid a video player's controls (the Skip button) after a
single scroll. browser-use keeps ±1000 px; a viewport is the same idea in the page's own units.
Below-fold elements are listed (up to `limit`) like any other. Deliberately NO per-element
off-screen markers and no page magnitudes: the first A/B (docs/research/explorer-optimisation.md,
Stage 1) showed a "(↓ 1.2 pages below)" marker turns into "scroll down to see the slider task"
— 35 scrolls in a 58-step run. Every listed element is actionable without scrolling (Playwright
scrolls it into view), so the only position facts worth stating are the counts of elements that
are NOT listed.
"""

import os

from netgent.browser.dom.models import DomElement, DomSnapshot, TextBlock

__all__ = ["element_key", "element_lines", "format_observation"]

# Format hints for date/time inputs, copied from browser-use (dom/serializer/serializer.py:1157-1167):
# the model cannot miss the required format when it is on the element's own line.
_FORMAT_HINT = {
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "datetime-local": "YYYY-MM-DDTHH:MM",
    "month": "YYYY-MM",
    "week": "YYYY-W##",
}

# How many above-viewport elements may take slots from `limit` (nearest to the viewport first);
# the rest are counted in the "(↑ N elements further above)" line.
_MAX_ABOVE_SHOWN = 15


def element_key(el: DomElement) -> str:
    """A stable-enough identity for an element ACROSS steps, so a re-rendered page can be
    diffed against the previous one without per-snapshot indices (browser-use diffs CDP
    backend-node-ids; we carry none, so the durable-locator ingredients stand in). The bbox is
    deliberately excluded — an element that merely moved is not new."""
    cand = next((c.value or f"{c.role}:{c.name}" for c in el.candidates), "")
    return "|".join(["/".join(el.frame_path), el.tag, el.type or "", el.role or "", el.name, cand])


def element_lines(snapshot: DomSnapshot) -> dict[str, str]:
    """`element_key` → rendered line (index-free) for every element: what the next step's
    observation is diffed against, so a changed value / checked state counts as a change."""
    return {element_key(el): _render(el) for el in snapshot.interactive()}


def format_observation(
    snapshot: DomSnapshot,
    limit: int = 60,
    text_limit: int = 25,
    previous: dict[str, str] | None = None,
    previous_texts: set[str] | None = None,
) -> str:
    """Render the page slice around the viewport. Elements keep their original snapshot
    index (what the agent references); scrolling shifts which slice is shown.

    `previous` / `previous_texts`: `element_lines()` and text blocks from the PREVIOUS step's
    snapshot of the same page. When given, elements absent from `previous` are starred
    (`*[12]`), a one-line change summary counts new/changed/gone elements, new text and
    dialogs, and a "NEW TEXT SINCE LAST STEP" section is emitted (browser-use's `*[` markers;
    docs/research/browser-agent-memory.md §6.2c). Pass None on the first step and after a
    navigation, so a new page is not starred wholesale.
    """
    lines = [f"URL: {snapshot.url}", f"TITLE: {snapshot.title}"]
    # Playback ground truth (walker reads the <video>/<audio> properties): the on-screen
    # controls freeze while auto-hidden, so this line is the only reliable playing/paused
    # signal — and its ticking currentTime keeps a playing page from ever comparing equal
    # to its previous observation (stuck detection).
    for m in snapshot.media[:3]:
        state = "ENDED" if m.ended else ("PAUSED" if m.paused else "PLAYING")
        pos = _mmss(m.current) + (f" / {_mmss(m.duration)}" if m.duration is not None else "")
        lines.append(f"MEDIA: {m.tag} {state} at {pos}" + (" [muted]" if m.muted else ""))

    # Page the elements by top-viewport position so scroll reveals the next batch.
    vh = snapshot.viewport_height or 0
    indexed = list(enumerate(snapshot.interactive()))
    if vh:
        # NETGENT_OBS_SCROLLBACK=0 restores the pre-2026-08-26 60 px cut (the A/B arm).
        keep_above = -60 if os.getenv("NETGENT_OBS_SCROLLBACK", "1") == "0" else -vh
        kept = sorted((ie for ie in indexed if ie[1].bbox.y >= keep_above), key=lambda ie: ie[1].bbox.y)
        above_kept = [ie for ie in kept if ie[1].bbox.y + ie[1].bbox.h < 0]
        in_or_below = kept[len(above_kept):]
        # Above-viewport elements are context, not the working set: cap how many of them
        # take slots, keeping the ones nearest the viewport.
        above_kept = above_kept[-_MAX_ABOVE_SHOWN:] if len(above_kept) > _MAX_ABOVE_SHOWN else above_kept
        shown = above_kept + in_or_below[: max(0, limit - len(above_kept))]
        above = len(indexed) - len(in_or_below) - len(above_kept)
        below = len(in_or_below) - (len(shown) - len(above_kept))
    else:  # viewport unknown → show in document order, no paging
        above, shown = 0, indexed[:limit]
        below = len(indexed) - len(shown)
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
        # Only the counts of UNLISTED elements matter for a scroll decision.
        if not above and below:
            lines.append("POSITION: top of page. Every element up to the cut-off below is listed; act on them.")
        elif above and not below:
            lines.append("POSITION: bottom of page. Nothing more below; do not scroll down further.")
        elif above and below:
            lines.append("POSITION: middle of page.")
        else:
            lines.append("POSITION: the whole page is listed. Nothing is hidden above or below.")
    fresh_texts = [t for t in snapshot.texts if t.text not in previous_texts] if previous_texts is not None else []
    if previous is not None:
        current = element_lines(snapshot)
        new = sum(1 for k in current if k not in previous)
        changed = sum(1 for k, line in current.items() if k in previous and previous[k] != line)
        gone = sum(1 for k in previous if k not in current)
        parts = []
        if new:
            parts.append(f"{new} new element{'s' if new != 1 else ''} (marked *)")
        if changed:
            parts.append(f"{changed} element{'s' if changed != 1 else ''} changed value/state")
        if gone:
            parts.append(f"{gone} element{'s' if gone != 1 else ''} gone")
        if fresh_texts:
            parts.append(f"{len(fresh_texts)} new text line{'s' if len(fresh_texts) != 1 else ''} (see NEW TEXT)")
        if snapshot.dialogs:
            parts.append(f"{len(snapshot.dialogs)} dialog{'s' if len(snapshot.dialogs) != 1 else ''}")
        # Emitted only when something DID change. An explicit "nothing changed" claim was
        # measured to be harmful: whenever the observation is blind to an effect (a CSS-only
        # completion state, a deduplicated digit) it turns into "the click did not register"
        # and the agent repeats the action until the stuck stop (Stage 2/3 challenge A/B,
        # docs/research/explorer-optimisation.md).
        if parts:
            lines.append("CHANGED SINCE LAST STEP: " + ", ".join(parts) + ".")
    if above:
        lines.append(f"(↑ {above} elements further above — scroll up to reach them)")
    lines.append("INTERACTIVE ELEMENTS:")

    current_frame: tuple[str, ...] | None = None
    for i, el in shown:
        key = tuple(el.frame_path)
        if use_headers and key != current_frame:
            current_frame = key
            if key:  # a non-top frame: emit a header before its elements (top frame gets none)
                label = " › ".join(key)
                count = sum(1 for _, e in shown if tuple(e.frame_path) == key)
                lines.append(f"|IFRAME {frame_number[key]}| {label[:80]} ({count} element{'s' if count != 1 else ''})")
        star = "*" if previous is not None and element_key(el) not in previous else " "
        lines.append(f" {star}[{i}] {_render(el)}")
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
    if fresh_texts:
        # Transient banners ("Thanks — recorded") appear for one step and vanish; naming
        # them here is how the model learns the submit worked (memory doc §6.2c).
        lines.append("NEW TEXT SINCE LAST STEP:")
        for t in sorted(fresh_texts, key=lambda t: not t.alert)[:8]:
            lines.append(("  !ALERT " if t.alert else "  ") + t.text)
    texts = _visible_texts(snapshot, text_limit)
    if texts:
        lines.append("VISIBLE TEXT:")
        for t in texts:
            prefix = "  !ALERT " if t.alert else "  "
            lines.append(f"{prefix}{t.text}")
    return "\n".join(lines)


def _mmss(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m}:{s:02d}"


def _render(el: DomElement) -> str:
    """One element's line, without its index."""
    # Mark elements inside a CLOSED shadow root (browser-use's |SHADOW(closed)| prefix,
    # dom/serializer/serializer.py:1030-1062). Open roots get no marker — Playwright's
    # engines pierce them and the model gains nothing (Eugene addendum item 2).
    shadow = "|SHADOW(closed)| " if el.requires_closed_shadow else ""
    kind = shadow + el.tag
    if el.type:  # input[date], input[file], input[email] — the agent needs the type
        kind += f"[{el.type}]"
    elif el.role and el.role != el.tag:
        kind += f" ({el.role})"
    # Never echo a password: it would sit in the prompt where page text could exfiltrate
    # it (browser-use serializer.py:1220-1227 treats this as a security boundary).
    val = f' value="{el.value}"' if el.value and el.type != "password" else ""
    if el.options:
        val += f" options=[{', '.join(el.options)}]"
    name = f' "{el.name}"' if el.name else ""
    fmt = el.format or _FORMAT_HINT.get(el.type or "")
    if fmt:
        name += f" format={fmt}"
        if el.picker and el.picker != "attr":
            name += f" picker={el.picker}"
    state = ""
    if el.checked is not None:
        state += " [checked]" if el.checked else " [unchecked]"
    if el.disabled:
        state += " [disabled]"
    if el.required:
        state += " [required]"
    if el.invalid:
        state += " [invalid: still needs a valid value]"
    return f"{kind}{name}{val}{state}"


def _visible_texts(snapshot: DomSnapshot, text_limit: int) -> list[TextBlock]:
    """Alerts first (stable otherwise), and drop text that merely repeats an element's name —
    AgentOccam's `remove_redundant_statictext` / Stagehand's `removeRedundantStaticTextChildren`.
    On a nav-heavy page this stops 25 link labels crowding out the one error message."""
    names = {el.name for el in snapshot.interactive() if el.name}
    texts = [t for t in snapshot.texts if t.text not in names]
    return sorted(texts, key=lambda t: not t.alert)[:text_limit]
