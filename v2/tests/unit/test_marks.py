"""Set-of-Marks renderer: geometry, index labels, viewport clipping, tiny/edge/overlap cases."""

import io

from PIL import Image

from netgent.agent.explore_agent.marks import Mark, color_for, marks_for, render_set_of_marks
from netgent.browser.dom.snapshot import BBox, DomElement, SelectorCandidate


def _el(x, y, w, h):
    return DomElement(tag="button", name="b", bbox=BBox(x=x, y=y, w=w, h=h),
                      candidates=[SelectorCandidate(kind="css", value="#b")])


def test_marks_for_clips_to_viewport():
    shown = [
        (0, _el(10, 10, 40, 20)),     # in view
        (1, _el(-100, 10, 40, 20)),   # fully left of viewport
        (2, _el(10, 900, 40, 20)),    # below an 800px fold
        (3, _el(1270, 10, 40, 20)),   # straddles the right edge → kept (intersects)
    ]
    marks = marks_for(shown, 1280, 800)
    assert {m.index for m in marks} == {0, 3}


def test_render_produces_png_of_same_size_and_is_deterministic():
    png = _blank(200, 100)
    marks = [Mark(0, BBox(x=10, y=10, w=40, h=20)), Mark(1, BBox(x=100, y=50, w=3, h=3))]
    a = render_set_of_marks(png, marks, 200, 100)
    b = render_set_of_marks(png, marks, 200, 100)
    assert a == b  # deterministic
    img = Image.open(io.BytesIO(a))
    assert img.size == (200, 100)
    # something was drawn (not still blank white)
    drawn = img.convert("RGB").getcolors(maxcolors=100000)
    blank = Image.open(io.BytesIO(png)).convert("RGB").getcolors(maxcolors=100000)
    assert drawn != blank


def test_tiny_target_gets_a_minimum_box():
    # a 3x3 radio must be boxed big enough to see; the drawn box exceeds MIN_BOX
    png = _blank(100, 100)
    out = render_set_of_marks(png, [Mark(5, BBox(x=50, y=50, w=3, h=3))], 100, 100)
    painted = _painted_bbox(out, png)
    assert painted is not None
    w = painted[2] - painted[0]
    assert w >= 10, f"tiny target box too small: {w}px"


def test_dpr_scaling_places_marks_at_2x():
    # a retina screenshot is 2x the CSS viewport; a box at css x=50 lands near px=100
    png = _blank(200, 200)  # image 200px wide
    out = render_set_of_marks(png, [Mark(0, BBox(x=50, y=50, w=20, h=20))], 100, 100)  # css viewport 100
    painted = _painted_bbox(out, png)
    assert painted is not None and painted[0] >= 90, f"expected ~100px, got {painted}"


def test_color_is_consistent_per_index():
    assert color_for(3) == color_for(3) and color_for(3) != color_for(4)


def _blank(w, h) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _painted_bbox(out_png: bytes, base_png: bytes):
    """Bounding box of pixels that differ from the all-white base — where marks were drawn."""
    out = Image.open(io.BytesIO(out_png)).convert("RGB")
    base = Image.open(io.BytesIO(base_png)).convert("RGB")
    from PIL import ImageChops

    diff = ImageChops.difference(out, base)
    return diff.getbbox()
