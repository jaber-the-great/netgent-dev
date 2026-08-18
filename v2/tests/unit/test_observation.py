"""Observation formatting + decision→action mapping (no browser)."""

import pytest

from netgent.agent.decision import AgentDecision
from netgent.agent.observation import format_observation, to_action
from netgent.browser.dom.snapshot import BBox, DomElement, DomSnapshot, SelectorCandidate, TextBlock
from netgent.schema.actions import SetCheckedAction


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


def test_check_and_uncheck_map_to_set_checked():
    snap = _snap()
    checked = to_action(AgentDecision(reasoning="x", kind="check", index=1), snap)
    assert isinstance(checked, SetCheckedAction) and checked.checked is True
    unchecked = to_action(AgentDecision(reasoning="x", kind="uncheck", index=1), snap)
    assert isinstance(unchecked, SetCheckedAction) and unchecked.checked is False


def test_bad_index_raises():
    with pytest.raises(ValueError, match="valid element index"):
        to_action(AgentDecision(reasoning="x", kind="click", index=99), _snap())


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
