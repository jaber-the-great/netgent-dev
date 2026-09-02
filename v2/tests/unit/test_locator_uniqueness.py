"""R1 — capture-time uniqueness: candidate ladder + nth fallback, with a fake session."""

import asyncio

from netgent.browser.dom import BBox, DomElement, SelectorCandidate
from netgent.browser.locators import durable_locator, locator_candidates, unique_locator_for


def _el(**kw) -> DomElement:
    base = dict(tag="input", type="email", name="Email", bbox=BBox(x=10, y=300, w=100, h=20))
    base.update(kw)
    return DomElement(**base)


class FakeSession:
    """count() answers from a table keyed on the chain's last step; match_index is fixed."""

    def __init__(self, counts: dict[str, int], index: int = 1):
        self._counts = counts
        self._index = index
        self.counted: list[str] = []

    async def count(self, chain):
        key = chain[-1].fn + ":" + str(chain[-1].args[0])
        self.counted.append(key)
        return self._counts.get(key, 0)

    async def match_index(self, chain, x, y):
        return self._index


def test_candidates_are_ordered_id_role_testid_label_css():
    el = _el(
        frame_path=["iframe#pay"],
        candidates=[
            SelectorCandidate(kind="role", role="textbox", name="Email"),
            SelectorCandidate(kind="test_id", value="email"),
            SelectorCandidate(kind="label", value="Email"),
            SelectorCandidate(kind="css", value="#email"),
        ],
    )
    chains = locator_candidates(el)
    assert [c[-1].fn for c in chains] == ["locator", "get_by_role", "get_by_test_id", "get_by_label"]
    assert all(c[0].fn == "frame_locator" and c[0].args == ["iframe#pay"] for c in chains)
    assert durable_locator(el) == chains[0]


def test_ambiguous_id_falls_through_to_a_unique_candidate():
    el = _el(candidates=[
        SelectorCandidate(kind="css", value="#email"),
        SelectorCandidate(kind="test_id", value="email-2"),
    ])
    session = FakeSession({"locator:#email": 2, "get_by_test_id:email-2": 1})
    chain = asyncio.run(unique_locator_for(session, el))
    assert [s.fn for s in chain] == ["get_by_test_id"]


def test_all_ambiguous_appends_nth_to_the_most_durable_chain():
    el = _el(candidates=[
        SelectorCandidate(kind="css", value="#email"),
        SelectorCandidate(kind="role", role="textbox", name="Email"),
    ])
    session = FakeSession({"locator:#email": 2, "get_by_role:textbox": 2}, index=1)
    chain = asyncio.run(unique_locator_for(session, el))
    assert [(s.fn, s.args) for s in chain] == [("locator", ["#email"]), ("nth", [1])]


def test_nothing_resolves_returns_the_unverified_chain():
    el = _el(candidates=[SelectorCandidate(kind="css", value="#gone")])
    chain = asyncio.run(unique_locator_for(FakeSession({}), el))
    assert [(s.fn, s.args) for s in chain] == [("locator", ["#gone"])]


def test_machine_generated_ids_never_lead_the_ladder():
    """A per-mount id (`#skip-button\\:2`, React's `:r1:`, trailing counters) must not win
    bucket 1: it changes every session, so a chain built on it can never replay — the
    YouTube ad-skip interrupt anchored on one and never fired again (2026-09-01)."""
    from netgent.browser.locators import is_volatile_selector

    for vid in (r"#skip-button\:2", "#:r1:", "#player-1234567", "#deadbeefcafe01", "#item-3", "#email2"):
        el = _el(candidates=[
            SelectorCandidate(kind="css", value=vid),
            SelectorCandidate(kind="role", role="button", name="Skip"),
        ], tag="button", type=None)
        chains = locator_candidates(el)
        assert chains[0][-1].fn == "get_by_role", vid  # role leads; the volatile id is css-fallback only
        assert is_volatile_selector(vid), vid
    assert not is_volatile_selector("#email")
    assert not is_volatile_selector("#main-content")
