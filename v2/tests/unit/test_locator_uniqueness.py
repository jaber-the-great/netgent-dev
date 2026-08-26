"""R1 — capture-time uniqueness: candidate ladder + nth fallback, with a fake session."""

import asyncio

from netgent.agent.explorer.observation import _locator_candidates, _locator_for, unique_locator_for
from netgent.browser.dom import BBox, DomElement, SelectorCandidate


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
    chains = _locator_candidates(el)
    assert [c[-1].fn for c in chains] == ["locator", "get_by_role", "get_by_test_id", "get_by_label"]
    assert all(c[0].fn == "frame_locator" and c[0].args == ["iframe#pay"] for c in chains)
    assert _locator_for(el) == chains[0]


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
