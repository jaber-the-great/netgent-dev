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


# ── M0: the structural (positional) rung and the probed ladder ──────────────────────────


def _list_link(**kw) -> DomElement:
    base = dict(
        tag="a", role=None, name="Cat video A", type=None, bbox=BBox(x=40, y=120, w=200, h=20),
        candidates=[
            SelectorCandidate(kind="role", role="link", name="Cat video A"),
            SelectorCandidate(kind="css", value="#results > li:nth-of-type(1) > a"),
            SelectorCandidate(kind="structural", value="#results > li > a"),
        ],
    )
    base.update(kw)
    return DomElement(**base)


def test_structural_rung_is_last_and_kinds_are_named():
    """The positional rung (a css path anchored at the repeated container) closes the ladder
    and is labelled, so a compile can find it without re-deriving it from the selector text."""
    from netgent.browser.locators import ladder

    rungs = ladder(_list_link())
    assert [k for k, _ in rungs] == ["role", "css", "structural"]
    assert rungs[-1][1][-1].args == ["#results > li > a"]
    assert locator_candidates(_list_link()) == [c for _, c in rungs]


def test_probe_ladder_counts_every_rung_and_indexes_the_structural_one():
    from netgent.browser.locators import probe_ladder

    session = FakeSession(
        {"get_by_role:link": 1, "locator:#results > li:nth-of-type(1) > a": 1, "locator:#results > li > a": 3},
        index=0,
    )
    probe = asyncio.run(probe_ladder(session, _list_link()))
    assert probe.kinds == ["role", "css", "structural"]
    assert probe.counts == [1, 1, 3]
    assert probe.indices == [None, None, 0]  # only the structural rung was ambiguous
    assert probe.rung("structural") == 2 and probe.rung("id") is None
    # the unique winner is unchanged: the role rung, with the probe reused (no extra counts)
    counted_before = len(session.counted)
    chain = asyncio.run(unique_locator_for(session, _list_link(), probe))
    assert [s.fn for s in chain] == ["get_by_role"] and len(session.counted) == counted_before


def test_probe_ladder_marks_unresolvable_rungs_and_indexes_the_first_ambiguous():
    from netgent.browser.locators import probe_ladder

    class Raising(FakeSession):
        async def count(self, chain):
            if chain[-1].args[0] == "#results > li > a":
                raise RuntimeError("bad selector")
            return await super().count(chain)

    session = Raising({"get_by_role:link": 2, "locator:#results > li:nth-of-type(1) > a": 2}, index=1)
    el = _list_link()
    probe = asyncio.run(probe_ladder(session, el))
    assert probe.counts == [2, 2, -1]
    assert probe.indices == [1, None, None]  # first ambiguous rung only; the broken rung stays unknown
    chain = asyncio.run(unique_locator_for(session, el, probe))
    assert [(s.fn, s.args) for s in chain][-1] == ("nth", [1])  # disambiguated from the probe's index
