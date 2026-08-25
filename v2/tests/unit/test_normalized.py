"""R4 — Playwright's normalized `internal:` selectors → our whitelisted chain, totally or not at all."""

import pytest

from netgent.agent.explore_agent.normalized import UnmappableSelector, chain_from_normalized, frame_steps, split_parts
from netgent.schema.actions import ClickAction

# Shapes measured from Locator.normalize() on Playwright 1.62 / Patchright 1.62.1.
CASES = {
    'iframe[name="payframe"] >> internal:control=enter-frame >> internal:role=textbox[name="Card holder"i]': [
        ("frame_locator", ['iframe[name="payframe"]'], {}),
        ("get_by_role", ["textbox"], {"name": "Card holder"}),
    ],
    'iframe[name="payframe"] >> internal:control=enter-frame >> internal:testid=[data-testid="deepbtn"s]': [
        ("frame_locator", ['iframe[name="payframe"]'], {}),
        ("get_by_test_id", ["deepbtn"], {}),
    ],
    'iframe[name="payframe"] >> internal:control=enter-frame >> internal:role=button[name="Same"i] >> nth=1': [
        ("frame_locator", ['iframe[name="payframe"]'], {}),
        ("get_by_role", ["button"], {"name": "Same"}),
        ("nth", [1], {}),
    ],
    'iframe >> nth=2 >> internal:control=enter-frame >> internal:role=textbox[name="Card number"i]': [
        ("frame_locator", ["iframe"], {}),
        ("nth", [2], {}),
        ("get_by_role", ["textbox"], {"name": "Card number"}),
    ],
    '#fb >> internal:control=enter-frame >> textarea[name="msg"]': [
        ("frame_locator", ["#fb"], {}),
        ("locator", ['textarea[name="msg"]'], {}),
    ],
    'internal:role=button[name="a \\"quoted\\" name"i]': [("get_by_role", ["button"], {"name": 'a "quoted" name'})],
    'internal:role=heading[name="P"s][level=2]': [
        ("get_by_role", ["heading"], {"name": "P", "exact": True, "level": 2})
    ],
    'internal:role=checkbox[checked=true][include-hidden=true]': [
        ("get_by_role", ["checkbox"], {"checked": True, "include_hidden": True})
    ],
    'internal:text="edit me"i': [("get_by_text", ["edit me"], {})],
    'internal:text="Sign in"s': [("get_by_text", ["Sign in"], {"exact": True})],
    'internal:label="Email"i': [("get_by_label", ["Email"], {})],
    'internal:attr=[placeholder="Search"i]': [("get_by_placeholder", ["Search"], {})],
    'internal:attr=[alt="Logo"s]': [("get_by_alt_text", ["Logo"], {"exact": True})],
    'internal:attr=[title="Tip"i]': [("get_by_title", ["Tip"], {})],
    'div >> internal:has-text="foo >> bar"i': [("locator", ["div"], {}), ("filter", [], {"has_text": "foo >> bar"})],
    'iframe[name="a"] >> internal:control=enter-frame >> iframe[name="b"] >> internal:control=enter-frame >> #d2': [
        ("frame_locator", ['iframe[name="a"]'], {}),
        ("frame_locator", ['iframe[name="b"]'], {}),
        ("locator", ["#d2"], {}),
    ],
}


@pytest.mark.parametrize("selector,expected", list(CASES.items()))
def test_normalized_selectors_map_to_whitelisted_steps(selector, expected):
    chain = chain_from_normalized(selector)
    assert [(s.fn, s.args, s.kwargs) for s in chain] == expected
    ClickAction(locator=chain)  # every mapped chain is a valid artifact chain


@pytest.mark.parametrize(
    "selector",
    [
        'internal:has=[internal:role=button]',  # nested selector
        'internal:chain=xyz',
        'xpath=//div[1]',
        'internal:has-text="Exact"s',  # exact has-text has no filter() form
        'internal:attr=[data-foo="x"i]',  # no get_by_* for arbitrary attributes
        'internal:text=/^re.*/i',  # regex
        'iframe[name="a"] >> internal:control=enter-frame',  # ends inside a frame
        'internal:control=enter-frame >> #x',  # frame with no selector
        'internal:role=button >> internal:control=enter-frame >> #x',  # non-css frame selector
        'internal:control=pierce-frames >> #x',
    ],
)
def test_unmappable_parts_fail_instead_of_being_stored_raw(selector):
    with pytest.raises(UnmappableSelector):
        chain_from_normalized(selector)


def test_split_is_quote_aware():
    assert split_parts('a >> internal:text="x >> y"i >> nth=0') == ["a", 'internal:text="x >> y"i', "nth=0"]


def test_frame_steps_prefix():
    chain = chain_from_normalized('iframe >> nth=2 >> internal:control=enter-frame >> #x >> nth=1')
    assert [s.fn for s in frame_steps(chain)] == ["frame_locator", "nth"]
