"""Inferring parameters from prompt variations (ReUseIt variation-task idea)."""

import pytest

from netgent.agent.variations import infer_params


def test_single_token_values_become_params():
    r = infer_params([
        "search for laptop on Amazon",
        "search for phone on eBay",
        "search for tablet on Walmart",
    ])
    assert r.template == "search for ${p1} on ${p2}"
    names = [p.name for p in r.params]
    assert names == ["p1", "p2"]
    assert r.samples["p1"] == ["laptop", "phone", "tablet"]
    assert r.samples["p2"] == ["Amazon", "eBay", "Walmart"]
    # the first variation's value is the default
    assert r.params[0].default == "laptop"


def test_multi_word_values():
    r = infer_params([
        "fly from New York to Los Angeles",
        "fly from Boston to Chicago",
    ])
    assert r.template == "fly from ${p1} to ${p2}"
    assert r.samples["p1"] == ["New York", "Boston"]
    assert r.samples["p2"] == ["Los Angeles", "Chicago"]


def test_no_variation_yields_no_params():
    r = infer_params(["click the submit button", "click the submit button"])
    assert r.template == "click the submit button"
    assert r.params == []


def test_needs_at_least_two():
    with pytest.raises(ValueError, match="at least two"):
        infer_params(["only one"])
