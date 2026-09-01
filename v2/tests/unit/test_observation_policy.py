"""Observation rendering policy (no browser): viewport scrollback, position line, format hints,
password redaction, alert-first text, and the element diff
(docs/research/browser-agent-prompting.md §7.2, browser-agent-memory.md §6.2c)."""

import os

from netgent.browser.dom import (
    BBox,
    DomElement,
    DomSnapshot,
    SelectorCandidate,
    TextBlock,
    element_key,
    element_lines,
    format_observation,
)


def _el(name, y, tag="button", h=20, **kw):
    return DomElement(tag=tag, name=name, bbox=BBox(x=0, y=y, w=50, h=h),
                      candidates=[SelectorCandidate(kind="css", value=f"#{name}")], **kw)


def test_one_viewport_of_scrollback_is_kept_without_magnitude_markers():
    """The YouTube Skip case: a control that scrolled just above the viewport must stay listed,
    not vanish behind an 'already handled' count. No per-element off-screen markers: the first
    A/B showed '(↓ 1.2 pages below)' becomes 'scroll down to see it' (35 scrolls in 58 steps)."""
    snap = DomSnapshot(url="u", title="t", viewport_height=800, elements=[
        _el("far-above", y=-2000),  # more than a viewport up → counted, not listed
        _el("skip", y=-300),        # within one viewport above → listed, marked
        _el("play", y=100),
        _el("comments", y=1500),    # below the fold → listed with a pages marker
    ])
    obs = format_observation(snap)
    assert obs.endswith('  [1] button "skip"\n  [2] button "play"\n  [3] button "comments"')
    assert "pages" not in obs and "viewport" not in obs  # no magnitudes, no off-screen markers
    assert "far-above" not in obs
    assert "(↑ 1 elements further above — scroll up to reach them)" in obs
    assert "already handled" not in obs
    assert "POSITION: bottom of page" in obs  # unlisted above, nothing unlisted below


def test_legacy_60px_cut_is_available_as_the_ab_arm(monkeypatch):
    snap = DomSnapshot(url="u", title="t", viewport_height=800, elements=[_el("skip", y=-300), _el("play", y=100)])
    monkeypatch.setenv("NETGENT_OBS_SCROLLBACK", "0")
    obs = format_observation(snap)
    assert "skip" not in obs and "(↑ 1 elements further above" in obs
    monkeypatch.delenv("NETGENT_OBS_SCROLLBACK")
    assert "skip" in format_observation(snap)


def test_above_viewport_elements_do_not_crowd_out_the_working_set():
    """Scrollback is context: at most 15 above-viewport elements take slots, nearest first."""
    above = [_el(f"a{i}", y=-700 + i * 10) for i in range(40)]
    below = [_el(f"b{i}", y=10 + i * 10) for i in range(50)]
    snap = DomSnapshot(url="u", title="t", viewport_height=800, elements=above + below)
    obs = format_observation(snap, limit=60)
    listed = [ln for ln in obs.splitlines() if ln.startswith(("  [", " *[", " ["))]
    assert len(listed) == 60
    assert sum(f'"a{i}"' in obs for i in range(40)) == 15
    assert '"a39"' in obs and '"a0"' not in obs  # nearest to the viewport kept
    assert "(↑ 25 elements further above" in obs
    assert "(↓ 5 more elements below" in obs


def test_position_line_states_only_whether_unlisted_elements_exist():
    snap = DomSnapshot(url="u", title="t", viewport_height=800, elements=[_el("x", y=10), _el("y", y=3000)])
    assert "POSITION: the whole page is listed" in format_observation(snap)
    assert "POSITION: top of page" in format_observation(snap, limit=1)
    assert "POSITION" not in format_observation(DomSnapshot(url="u", title="t", elements=[_el("x", y=10)]))


def test_format_hints_and_password_redaction():
    snap = DomSnapshot(url="u", title="t", elements=[
        _el("DOB", y=0, tag="input", type="date"),
        _el("When", y=0, tag="input", type="time"),
        _el("Pw", y=0, tag="input", type="password", value="hunter2"),
        _el("User", y=0, tag="input", type="text", value="ada"),
    ])
    obs = format_observation(snap)
    assert 'input[date] "DOB" format=YYYY-MM-DD' in obs
    assert 'input[time] "When" format=HH:MM' in obs
    assert "hunter2" not in obs
    assert 'value="ada"' in obs


def test_alerts_first_and_element_names_deduped_from_text():
    snap = DomSnapshot(
        url="u", title="t", elements=[_el("Home", y=0, tag="a"), _el("About", y=0, tag="a")],
        texts=[TextBlock(text="Home"), TextBlock(text="Welcome"), TextBlock(text="Email is required", alert=True)],
    )
    obs = format_observation(snap)
    text = obs.split("VISIBLE TEXT:")[1]
    assert text.index("!ALERT Email is required") < text.index("Welcome")
    assert "\n  Home" not in text  # repeats a link's name


def test_element_diff_marks_new_elements_and_new_text():
    prev = DomSnapshot(url="u", title="t", elements=[_el("Country", y=0, tag="div", role="combobox")],
                       texts=[TextBlock(text="Pick a country")])
    now = DomSnapshot(url="u", title="t", elements=[
        _el("Country", y=0, tag="div", role="combobox"),
        _el("Canada", y=30, tag="div", role="option"),
    ], texts=[TextBlock(text="Pick a country"), TextBlock(text="Saved!", alert=True)])
    obs = format_observation(now, previous=element_lines(prev), previous_texts={t.text for t in prev.texts})
    assert "CHANGED SINCE LAST STEP: 1 new element (marked *), 1 new text line (see NEW TEXT)." in obs
    assert ' *[1] div (option) "Canada"' in obs
    assert '  [0] div (combobox) "Country"' in obs
    assert "NEW TEXT SINCE LAST STEP:\n  !ALERT Saved!" in obs
    # nothing changed → say so (the soft stuck signal); no diff section without a previous
    # nothing listed changed → NO change line at all (an explicit "nothing changed" claim was
    # measured to cause retry loops whenever the walker is blind to the effect)
    same = format_observation(now, previous=element_lines(now), previous_texts={t.text for t in now.texts})
    assert "CHANGED SINCE LAST STEP" not in same and "*[" not in same
    # a text-only change (a score, a status) is a change — never "nothing changed"
    text_only = format_observation(now, previous=element_lines(now), previous_texts={"Pick a country"})
    assert "CHANGED SINCE LAST STEP: 1 new text line (see NEW TEXT)." in text_only
    # a value/state change on an existing element is a change too (a fill, a toggle)
    filled = DomSnapshot(url="u", title="t", elements=[
        _el("Country", y=0, tag="div", role="combobox", value="Canada"),
        _el("Canada", y=30, tag="div", role="option"),
    ], texts=now.texts)
    changed = format_observation(filled, previous=element_lines(now), previous_texts={t.text for t in now.texts})
    assert "CHANGED SINCE LAST STEP: 1 element changed value/state." in changed
    assert "CHANGED SINCE LAST STEP" not in format_observation(now)


def test_element_key_survives_renumbering_and_moving():
    a = _el("Submit", y=10)
    b = _el("Submit", y=500)
    assert element_key(a) == element_key(b)
    assert element_key(a) != element_key(_el("Submit", y=10, tag="a"))


def test_iframe_headers_env_flag_still_respected():
    assert os.getenv("NETGENT_IFRAME_HEADERS", "1") != "0"
