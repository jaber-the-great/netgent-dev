"""Observation formatting + decision→action mapping (no browser)."""

import pytest

from netgent.agent.explore_agent.decision import AgentDecision
from netgent.agent.explore_agent.observation import to_action
from netgent.browser.dom import BBox, DomElement, DomSnapshot, SelectorCandidate, TextBlock, format_observation
from netgent.schema.actions import ClickAction


def _snap() -> DomSnapshot:
    return DomSnapshot(
        url="http://x/y",
        title="T",
        elements=[
            DomElement(
                tag="input", type="date", name="DOB", bbox=BBox(x=0, y=0, w=1, h=1),
                candidates=[SelectorCandidate(kind="css", value="#dob")],
            ),
            DomElement(
                tag="input", type="radio", role="radio", name="Email", checked=False, disabled=False,
                bbox=BBox(x=0, y=0, w=1, h=1),
                candidates=[SelectorCandidate(kind="role", role="radio", name="Email")],
            ),
            DomElement(
                tag="button", name="Old", disabled=True, bbox=BBox(x=0, y=0, w=1, h=1),
                candidates=[SelectorCandidate(kind="css", value="#b")],
            ),
            DomElement(
                tag="input", type="text", name="Zip", required=True, invalid=True,
                bbox=BBox(x=0, y=0, w=1, h=1), candidates=[SelectorCandidate(kind="css", value="#zip")],
            ),
        ],
        texts=[TextBlock(text="Please fill the form"), TextBlock(text="Success!", alert=True)],
    )


def test_observation_shows_type_state_and_text():
    obs = format_observation(_snap())
    assert "input[date] \"DOB\"" in obs
    assert "input[radio] \"Email\" [unchecked]" in obs
    assert "[disabled]" in obs
    assert "VISIBLE TEXT:" in obs
    assert "!ALERT Success!" in obs  # alert messages are flagged
    assert "[required]" in obs and "[invalid:" in obs  # blocks-submit hints surfaced


def test_click_always_maps_to_click_action():
    # The single click verb produces a ClickAction for everything; checkbox/radio toggle
    # vs select is handled at dispatch (keyed on the live element), tested in integration.
    snap = DomSnapshot(
        url="u", title="t",
        elements=[
            DomElement(tag="input", type="checkbox", name="TOS", checked=False, bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#cb")]),
            DomElement(tag="button", name="Go", bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#b")]),
        ],
    )
    assert isinstance(to_action(AgentDecision(reasoning="x", kind="click", index=0), snap), ClickAction)
    assert isinstance(to_action(AgentDecision(reasoning="x", kind="click", index=1), snap), ClickAction)


def test_bad_index_raises():
    with pytest.raises(ValueError, match="valid element index"):
        to_action(AgentDecision(reasoning="x", kind="click", index=99), _snap())


def test_action_type_guards_give_corrective_errors():
    snap = DomSnapshot(
        url="u", title="t",
        elements=[
            DomElement(tag="input", type="date", name="DOB", bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#d")]),
            DomElement(tag="select", name="Country", options=["usa", "uk"], bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#c")]),
            DomElement(tag="input", type="text", name="Zip", bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#z")]),
        ],
    )
    # select on a date input → tells the agent to fill instead (the exact stall we hit)
    with pytest.raises(ValueError, match="not a dropdown"):
        to_action(AgentDecision(reasoning="x", kind="select", index=0, value="2024-01-01"), snap)
    # fill on a real dropdown → tells the agent to select
    with pytest.raises(ValueError, match="use 'select'"):
        to_action(AgentDecision(reasoning="x", kind="fill", index=1, text="usa"), snap)
    # select value not among options → lists the valid options
    with pytest.raises(ValueError, match="not an option"):
        to_action(AgentDecision(reasoning="x", kind="select", index=1, value="france"), snap)
    # a valid select still works
    assert to_action(AgentDecision(reasoning="x", kind="select", index=1, value="uk"), snap).value == "uk"


def test_iframe_element_gets_frame_locator_prefix():
    from netgent.agent.explore_agent.observation import _locator_for

    el = DomElement(
        tag="input", type="text", name="Email", frame_path=["iframe#outer", "iframe:nth-of-type(1)"],
        bbox=BBox(x=0, y=0, w=1, h=1), candidates=[SelectorCandidate(kind="css", value="#email")],
    )
    chain = _locator_for(el)
    assert [s.fn for s in chain] == ["frame_locator", "frame_locator", "locator"]
    assert chain[0].args == ["iframe#outer"]


def test_upload_maps_to_upload_file_action():
    from netgent.schema.actions import UploadFileAction

    snap = DomSnapshot(
        url="u", title="t",
        elements=[DomElement(tag="input", type="file", name="doc", bbox=BBox(x=0, y=0, w=1, h=1),
                             candidates=[SelectorCandidate(kind="css", value="#f")])],
    )
    act = to_action(AgentDecision(reasoning="x", kind="upload", index=0), snap, upload_path="/tmp/s.txt")
    assert isinstance(act, UploadFileAction) and act.paths == ["/tmp/s.txt"]
    with pytest.raises(ValueError, match="no upload file configured"):
        to_action(AgentDecision(reasoning="x", kind="upload", index=0), snap)


def test_scroll_is_anchored_on_an_element_or_the_scoped_frame():
    """R5: a scroll names the element (or, in a frame-scoped observation, any element of that
    frame) whose scroll container should move; an unscoped, index-less scroll stays plain."""
    from netgent.schema.actions import ScrollAction

    in_frame = DomElement(
        tag="input", type="text", name="A", frame_path=["iframe#f"], bbox=BBox(x=0, y=0, w=1, h=1),
        candidates=[SelectorCandidate(kind="css", value="#a")],
    )
    top = DomElement(tag="button", name="B", bbox=BBox(x=0, y=0, w=1, h=1),
                     candidates=[SelectorCandidate(kind="css", value="#b")])
    scoped = DomSnapshot(url="u", title="t", elements=[in_frame], viewport_height=0)
    mixed = DomSnapshot(url="u", title="t", elements=[top, in_frame], viewport_height=0)

    act = to_action(AgentDecision(reasoning="x", kind="scroll", down=True), scoped)
    assert isinstance(act, ScrollAction) and [s.fn for s in act.locator] == ["frame_locator", "locator"]
    act = to_action(AgentDecision(reasoning="x", kind="scroll", index=1), mixed)
    assert act.locator[0].args == ["iframe#f"]
    act = to_action(AgentDecision(reasoning="x", kind="scroll"), mixed)
    assert act.locator is None


def test_closed_shadow_elements_get_a_marker_in_the_observation():
    snap = DomSnapshot(
        url="u", title="t",
        elements=[
            DomElement(tag="input", name="Secret", requires_closed_shadow=True, bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#ci")]),
            DomElement(tag="button", name="Plain", bbox=BBox(x=0, y=0, w=1, h=1),
                       candidates=[SelectorCandidate(kind="css", value="#b")]),
        ],
    )
    obs = format_observation(snap)
    assert "|SHADOW(closed)| input" in obs  # closed-root element is marked
    assert "|SHADOW(closed)| button" not in obs  # the plain one is not


def test_iframe_headers_group_elements_by_frame():
    """Addendum: elements are grouped under a |IFRAME n| header per frame; the top frame gets
    none; single-frame and scoped observations get zero header lines."""
    top = DomElement(tag="button", name="Top", bbox=BBox(x=0, y=0, w=1, h=1),
                     candidates=[SelectorCandidate(kind="css", value="#t")])
    a1 = DomElement(tag="input", name="A1", frame_path=['iframe[name="pay"]'], bbox=BBox(x=0, y=10, w=1, h=1),
                    candidates=[SelectorCandidate(kind="css", value="#a1")])
    a2 = DomElement(tag="button", name="A2", frame_path=['iframe[name="pay"]'], bbox=BBox(x=0, y=20, w=1, h=1),
                    candidates=[SelectorCandidate(kind="css", value="#a2")])
    b1 = DomElement(tag="input", name="B1", frame_path=["iframe#other"], bbox=BBox(x=0, y=30, w=1, h=1),
                    candidates=[SelectorCandidate(kind="css", value="#b1")])
    multi = DomSnapshot(url="u", title="t", elements=[top, a1, b1, a2], viewport_height=0)
    obs = format_observation(multi)
    assert '|IFRAME 1| iframe[name="pay"] (2 elements)' in obs
    assert "|IFRAME 2| iframe#other (1 element)" in obs
    # the two "pay" elements are contiguous (grouped), the top-frame one has no header
    lines = [ln for ln in obs.splitlines() if ln.startswith("  [") or ln.startswith("|IFRAME")]
    assert lines[0].strip().startswith("[0]")  # Top, no header
    assert lines[1].startswith("|IFRAME 1|") and "A1" in lines[2] and "A2" in lines[3]

    # single frame → no headers; scoped → no headers
    single = DomSnapshot(url="u", title="t", elements=[top], viewport_height=0)
    assert "|IFRAME" not in format_observation(single)
    scoped = DomSnapshot(url="u", title="t", elements=[a1, a2], viewport_height=0)
    assert "|IFRAME" not in format_observation(scoped)


def test_dialogs_render_once_and_survive_scoping():
    """A page's alert() is the only feedback some forms give; it must reach the observation
    (so the stuck detector sees a change) and survive scoped_to (sweeps work one frame)."""
    snap = DomSnapshot(url="u", title="t", elements=[], texts=[], dialogs=["alert: Form submitted successfully!"])
    obs = format_observation(snap)
    assert "DIALOGS" in obs and "alert: Form submitted successfully!" in obs
    assert snap.scoped_to(["iframe#f"]).dialogs == snap.dialogs
    assert "DIALOGS" not in format_observation(DomSnapshot(url="u", title="t"))
