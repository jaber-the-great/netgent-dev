"""Set-of-Marks (SoM): draw numbered boxes on a clean viewport screenshot so a vision model
sees the SAME numbered elements the text observation lists.

Design (prior art in docs/research/accessibility-tree-observation.md §"Hybrid text+vision"):

* **Never touch the live DOM.** browser-use / WebVoyager inject a `<div>`/canvas overlay into
  the page and screenshot that; the overlay is then observable, clickable, and can shift layout,
  and it must be torn down before the next action. We instead draw with Pillow onto a *copy* of a
  clean screenshot — the page never changes, so perception can never contaminate the action space.
* **Indices are the text indices.** `agent.explore_agent.observation.shown_elements` is the single
  source of truth for which elements/numbers are on screen; the renderer draws exactly those.
* **Geometry is already frame-correct.** `DomElement.bbox` is normalized to TOP-viewport
  coordinates by `BrowserSession` (nested + cross-origin iframe offsets accumulated), so a mark at
  `(bbox.x, bbox.y)` lands on the right pixel for in-iframe elements too. We scale by the image
  DPR (`image_width / viewport_css_width`) for retina, clip to the viewport, expand a minimum box
  for tiny targets, and pick a label corner that avoids the other labels already placed.
* **Consistent colour per index** (hash of the index) so the model can match a text row to its box
  even where boxes crowd.

Occlusion/identity (is the box center actually the intended element, not something covering it)
is verified in the browser via `BrowserSession.mark_hits` (`elementFromPoint` per frame); the
renderer can be handed the already-filtered set, and `evals/som_check.py` reports the rate.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from netgent.browser.dom.snapshot import BBox, DomElement

# Palette: high-contrast, distinguishable; index picks one deterministically.
_PALETTE = [
    (230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180),
    (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 190), (0, 128, 128),
    (170, 110, 40), (128, 0, 0), (0, 0, 128), (128, 128, 0), (255, 100, 0),
]
MIN_BOX = 12  # tiny targets (a 3px radio) get a readable box this big, centered on them
LABEL_H = 16
LABEL_PAD = 3


def color_for(index: int) -> tuple[int, int, int]:
    return _PALETTE[index % len(_PALETTE)]


@dataclass
class Mark:
    index: int
    bbox: BBox  # top-viewport CSS pixels


def marks_for(shown: list[tuple[int, DomElement]], viewport_w: int, viewport_h: int) -> list[Mark]:
    """Marks for the on-screen shown elements whose box intersects the viewport.

    Elements paged into the text list but scrolled out of the viewport (y beyond the fold) are
    NOT drawn — the text already says "(↓ N below)", and drawing them would put a number on
    empty pixels."""
    out: list[Mark] = []
    for idx, el in shown:
        b = el.bbox
        if b.x + b.w < 0 or b.x > viewport_w or b.y + b.h < 0 or b.y > viewport_h:
            continue  # fully outside the viewport
        out.append(Mark(index=idx, bbox=b))
    return out


def _label_positions(
    box: tuple[int, int, int, int], w: int, img_w: int, img_h: int
) -> list[tuple[int, int, int, int]]:
    """Candidate label rectangles for a box, best first: the four outside corners then inside
    top-left. Returns (x0,y0,x1,y1) tuples clamped to the image."""
    x0, y0, x1, y1 = box
    lw = w
    cands = [
        (x0, y0 - LABEL_H, x0 + lw, y0),           # above-left (outside)
        (x1 - lw, y0 - LABEL_H, x1, y0),           # above-right
        (x0, y1, x0 + lw, y1 + LABEL_H),           # below-left
        (x0, y0, x0 + lw, y0 + LABEL_H),           # inside top-left (fallback)
    ]
    result = []
    for cx0, cy0, cx1, cy1 in cands:
        cx0 = max(0, min(cx0, img_w - lw))
        cy0 = max(0, min(cy0, img_h - LABEL_H))
        result.append((cx0, cy0, cx0 + lw, cy0 + LABEL_H))
    return result


def _overlaps(a, b) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def render_set_of_marks(png: bytes, marks: list[Mark], viewport_w: int, viewport_h: int) -> bytes:
    """Draw numbered boxes onto a copy of `png` (a viewport screenshot). Pure Pillow; the input
    image is never mutated in place and the live page is never touched."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(png)).convert("RGBA")
    # DPR: a retina screenshot is 2× the CSS viewport. Scale CSS-pixel bboxes to image pixels.
    scale = img.width / viewport_w if viewport_w else 1.0
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.truetype("Arial.ttf", 13)
    except Exception:  # noqa: BLE001 — no TTF on the box: bitmap default still legible
        font = ImageFont.load_default()

    placed_labels: list[tuple[int, int, int, int]] = []
    # Draw boxes first (so labels sit on top), largest first so small boxes/labels win the front.
    for m in sorted(marks, key=lambda m: -(m.bbox.w * m.bbox.h)):
        b = m.bbox
        x0, y0 = b.x * scale, b.y * scale
        x1, y1 = (b.x + b.w) * scale, (b.y + b.h) * scale
        # expand a minimum box around tiny targets, centered
        if (x1 - x0) < MIN_BOX * scale:
            cx = (x0 + x1) / 2
            x0, x1 = cx - MIN_BOX * scale / 2, cx + MIN_BOX * scale / 2
        if (y1 - y0) < MIN_BOX * scale:
            cy = (y0 + y1) / 2
            y0, y1 = cy - MIN_BOX * scale / 2, cy + MIN_BOX * scale / 2
        x0 = max(0, min(x0, img.width - 1))
        x1 = max(0, min(x1, img.width - 1))
        y0 = max(0, min(y0, img.height - 1))
        y1 = max(0, min(y1, img.height - 1))
        color = color_for(m.index)
        draw.rectangle([x0, y0, x1, y1], outline=(*color, 255), width=2)

    for m in sorted(marks, key=lambda m: -(m.bbox.w * m.bbox.h)):
        b = m.bbox
        x0, y0 = b.x * scale, b.y * scale
        x1, y1 = (b.x + b.w) * scale, (b.y + b.h) * scale
        color = color_for(m.index)
        label = str(m.index)
        tw = int(draw.textlength(label, font=font)) + 2 * LABEL_PAD
        boxpx = (int(x0), int(y0), int(x1), int(y1))
        for lx0, ly0, lx1, ly1 in _label_positions(boxpx, tw, img.width, img.height):
            if not any(_overlaps((lx0, ly0, lx1, ly1), p) for p in placed_labels):
                placed_labels.append((lx0, ly0, lx1, ly1))
                draw.rectangle([lx0, ly0, lx1, ly1], fill=(*color, 235))
                draw.text((lx0 + LABEL_PAD, ly0 + 1), label, fill=(255, 255, 255, 255), font=font)
                break
        else:  # every candidate collided — place at the first anyway (density fallback)
            lx0, ly0, lx1, ly1 = _label_positions(boxpx, tw, img.width, img.height)[0]
            placed_labels.append((lx0, ly0, lx1, ly1))
            draw.rectangle([lx0, ly0, lx1, ly1], fill=(*color, 235))
            draw.text((lx0 + LABEL_PAD, ly0 + 1), label, fill=(255, 255, 255, 255), font=font)

    out = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
