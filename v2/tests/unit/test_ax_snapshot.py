"""The accessibility-tree parser: fixture aria snapshots → interactive elements, text, locators."""

from netgent.agent.explore_agent.observation import _locator_for
from netgent.browser.dom import ax_snapshot as ax
from netgent.browser.dom.snapshot import BBox, DomElement, SelectorCandidate

# A trimmed real `aria_snapshot(mode="ai", boxes=True)`: main frame with a scored header,
# radios in labels, a nameless date input, an iframe holding a slider, and a link with /url.
FIXTURE = """\
- generic [active] [ref=e1] [box=0,0,1280,3606]:
  - banner [ref=e2] [box=0,0,1280,109]:
    - heading "Browser Agent Evaluation Stress-Test" [level=1] [ref=e3] [box=16,29,1248,51]
    - generic [ref=e4] [box=1099,20,161,67]:
      - text: "Score:"
      - generic [ref=e5] [box=1181,28,20,51]: "0"
      - text: / 17
  - paragraph [ref=e7] [box=0,125,1280,26]: Please complete the following tasks.
  - generic [ref=e9] [box=240,177,800,145]:
    - link "simple-button" [ref=e11] [cursor=pointer] [box=235,162,79,30]:
      - /url: "#simple-button"
    - generic [ref=e12] [box=277,209,731,31]: Click the button to start
    - button "Start" [ref=e13] [cursor=pointer] [box=277,256,66,34]
  - generic [ref=e18] [box=272,438,736,26]:
    - generic [ref=e19] [cursor=pointer] [box=272,441,59,19]:
      - radio "Cat" [disabled] [ref=e20] [box=277,444,13,13]
      - text: Cat
    - generic [ref=e21] [cursor=pointer] [box=347,441,52,19]:
      - radio "AI" [checked] [ref=e22] [box=352,444,13,13]
      - text: AI
  - searchbox "Enter a search term" [ref=e46] [box=272,887,153,21]: abc
  - textbox [ref=e52] [box=272,1052,318,38]
  - combobox "Select a color:" [ref=e113] [box=387,3262,200,19]:
    - option "Choose a color" [selected] [box=0,0,0,0]
    - option "Red" [box=0,0,0,0]
  - button "Submit" [ref=e60] [box=0,0,10,10]
  - button "Submit" [ref=e61] [box=0,20,10,10]
  - alert [ref=e62] [box=0,40,100,10]: Saved!
  - iframe [ref=e77] [box=272,1946,352,152]:
    - generic [ref=f30e2] [box=25,20,300,48]:
      - slider [ref=f30e3] [box=27,22,300,15]: "1"
      - generic [ref=f30e4] [box=25,49,300,19]: "Value: 1"
"""


def test_parse_tree_roles_names_attrs():
    nodes = ax.parse_aria_snapshot(FIXTURE)
    root = nodes[0]
    assert root.role == "generic" and root.ref == "e1" and root.attrs["active"] is True
    banner = root.children[0]
    heading = banner.children[0]
    assert heading.role == "heading" and heading.name == "Browser Agent Evaluation Stress-Test"
    assert heading.attrs["level"] == "1" and heading.box == BBox(x=16, y=29, w=1248, h=51)
    link = root.children[2].children[0]
    assert link.role == "link" and link.name == "simple-button" and link.attrs["cursor"] == "pointer"
    assert link.children == []  # /url is a property, not a child


def test_collect_interactives_text_and_frames():
    interactives, texts, iframes = ax.collect(ax.parse_aria_snapshot(FIXTURE))
    by_ref = {it.node.ref: it for it in interactives}
    # interactive roles are collected; options inside a combobox are not separate targets
    assert {"e13", "e20", "e22", "e46", "e52", "e113", "e60", "e61", "f30e3", "e11"} <= set(by_ref)
    assert not any(it.node.role == "option" for it in interactives)
    # in-frame boxes are offset by the iframe's top-left into top-viewport coordinates
    slider = by_ref["f30e3"]
    assert slider.frame_refs == ["e77"] and slider.bbox.x == 272 + 27 and slider.bbox.y == 1946 + 22
    assert iframes == ["e77"]
    # inline fragments merge into one reader-facing block; alerts are flagged; y is kept
    blocks = {t.text: t for _, t in texts}
    assert "Score: 0 / 17" in blocks and blocks["Score: 0 / 17"].y == 20
    assert blocks["Saved!"].alert is True
    assert "Click the button to start" in blocks and "Value: 1" in blocks
    # control labels are not duplicated as text; the text beside a radio IS (it's page text)
    assert "Start" not in blocks


def test_build_elements_joins_dom_facts_and_disambiguates_duplicates():
    interactives, _, _ = ax.collect(ax.parse_aria_snapshot(FIXTURE))
    facts = {
        "e52": {"tag": "input", "type": "date", "css": "#date-picker", "required": True, "invalid": True},
        "e113": {"tag": "select", "css": "#color-select", "options": ["blue", "red"]},
        "e60": {"tag": "button", "css": "form > button:nth-of-type(1)"},
        "e61": {"tag": "button", "css": "form > button:nth-of-type(2)"},
        "e22": {"tag": "input", "type": "radio", "checked": True, "css": "input:nth-of-type(2)", "hasLabel": True},
    }
    elements = ax.build_elements(interactives, facts, {"e77": "iframe#slider-iframe-element"})
    by_name = {(e.tag, e.name): e for e in elements}

    date = next(e for e in elements if e.type == "date")
    assert date.required and date.invalid and date.name == ""  # nameless textbox → DOM facts carry it
    assert _locator_for(date)[0].args == ["#date-picker"]

    select = by_name[("select", "Select a color:")]
    assert select.options == ["blue", "red"]
    assert [s.fn for s in _locator_for(select)] == ["locator"]  # stable #id wins

    # duplicate role+name in the same frame → .nth(k); exact=True because names are accname
    submits = [e for e in elements if e.name == "Submit"]
    chains = [_locator_for(e) for e in submits]
    assert chains[0][0].kwargs == {"name": "Submit", "exact": True}
    assert chains[0][1].fn == "filter" and chains[0][1].kwargs == {"visible": True}  # hidden duplicates skipped
    assert chains[0][2].fn == "nth" and chains[0][2].args == [0] and chains[1][2].args == [1]

    radio = by_name[("input", "AI")]
    assert radio.checked is True and radio.type == "radio"
    # AX-only (no DOM facts): state from the tree, role locator still built
    cat = by_name[("input", "Cat")] if ("input", "Cat") in by_name else by_name[("radio", "Cat")]
    assert cat.disabled and cat.checked is False

    slider = next(e for e in elements if e.frame_path)
    assert slider.frame_path == ["iframe#slider-iframe-element"] and slider.value == "1"
    assert _locator_for(slider)[0].fn == "frame_locator"


def test_merge_extras_dedupes_by_frame_and_bbox_and_keeps_reading_order():
    def el(name, y, frame=()):
        return DomElement(
            tag="div", name=name, bbox=BBox(x=0, y=y, w=100, h=20), frame_path=list(frame),
            candidates=[SelectorCandidate(kind="css", value=f"#{name}")],
        )

    listed = [el("a", 10), el("c", 300)]
    extras = [el("a-dup", 11), el("b", 100), el("a-other-frame", 10, frame=("iframe#x",))]
    merged = ax.merge_extras(listed, extras)
    assert [e.name for e in merged] == ["a", "a-other-frame", "b", "c"]


def test_parse_is_tolerant_of_odd_lines():
    text = """\
- generic [ref=e1]:
  - button "Say \\"hi\\"" [ref=e2] [box=1,2,3,4]
  - text: plain words
  - weird line without a role pattern: 42
"""
    nodes = ax.parse_aria_snapshot(text)
    btn = nodes[0].children[0]
    assert btn.name == 'Say "hi"' and btn.box == BBox(x=1, y=2, w=3, h=4)
    assert nodes[0].children[1].text == "plain words"
    assert ax.parse_aria_snapshot("") == []
