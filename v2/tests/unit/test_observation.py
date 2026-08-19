"""Observation formatting + decision→action mapping (no browser)."""

import pytest

from netgent.agent.decision import AgentDecision
from netgent.agent.observation import format_observation, to_action
from netgent.browser.dom.snapshot import BBox, DomElement, DomSnapshot, SelectorCandidate, TextBlock
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
    from netgent.agent.observation import _locator_for

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
