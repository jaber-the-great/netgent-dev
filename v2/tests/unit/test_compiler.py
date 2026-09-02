"""Trajectory -> workflow compilation: actions become transitions, URLs become
state conditions, and sample values become ${name} parameters."""

import pytest

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.schema.actions import LocatorStep


def _css(sel):
    return [LocatorStep(fn="locator", args=[sel])]


def _traj() -> AgentTrajectory:
    return AgentTrajectory(
        task="search youtube for cat videos and play the first result",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://youtube.com/",
                      action={"type": "goto", "url": "https://youtube.com"}),
            AgentStep(n=2, kind="fill", reasoning="search", url="https://youtube.com/",
                      action={"type": "fill", "locator": [{"fn": "locator", "args": ["input#q"]}],
                              "text": "cat videos"}),
            AgentStep(n=3, kind="press", reasoning="submit",
                      url="https://youtube.com/results?search_query=cat+videos",
                      action={"type": "press", "keys": "Enter",
                              "locator": [{"fn": "locator", "args": ["input#q"]}]}),
            AgentStep(n=4, kind="fill", reasoning="failed step is skipped", url="https://youtube.com/results",
                      error="timeout"),
            AgentStep(n=5, kind="done", reasoning="done", url="https://youtube.com/watch?v=x"),
        ],
    )


def test_actions_become_transitions_and_urls_become_conditions():
    wf = compile_trajectory(_traj(), name="yt")
    assert [t.id for t in wf.transitions] == ["t1", "t2", "t3"]  # failed + done steps dropped
    assert wf.control_sequence == ["t1", "t2", "t3"]
    # step 2 stayed on the same page -> no url condition, but it IS anchored on the next
    # edge's target element (t3 presses Enter on input#q)
    (anchor,) = wf.state("s2").conditions
    assert anchor.type == "selector_visible" and anchor.locator == _css("input#q") and anchor.selector is None
    # step 3 moved -> url condition; final state has no next edge -> no anchor
    (cond,) = wf.state("s3").conditions
    assert cond.pattern == "https://youtube\\.com/results"  # query stripped, regex-escaped


def test_states_anchor_on_next_edges_target_element():
    wf = compile_trajectory(_traj(), name="yt")
    # s1 (after goto): url condition AND the anchor for t2's fill target
    url_cond, anchor = wf.state("s1").conditions
    assert url_cond.type == "url_matches"
    assert anchor.type == "selector_visible" and anchor.locator == _css("input#q")


def test_anchor_is_the_next_actions_own_locator_chain():
    """The anchor carries the chain itself, never a selector-string rendering: Playwright's
    public `role=` engine matches `[name="…" i]` EXACTLY while get_by_role matches by
    SUBSTRING, so an anchor rendered from a name Playwright's generator had shortened to a
    30-char prefix ("Web icon An illustration of a") matched nothing on replay while the
    click it guarded matched one element (archive.org, media-platforms-eval.md)."""
    traj = AgentTrajectory(
        task="t",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://x.com/",
                      action={"type": "goto", "url": "https://x.com"}),
            AgentStep(n=2, kind="click", reasoning="click", url="https://x.com/",
                      action={"type": "click",
                              "locator": [{"fn": "get_by_role", "args": ["button"],
                                           "kwargs": {"name": "Search"}}]}),
        ],
    )
    wf = compile_trajectory(traj, name="x")
    _, anchor = wf.state("s1").conditions
    assert anchor.type == "selector_visible" and anchor.selector is None
    assert anchor.locator == [LocatorStep(fn="get_by_role", args=["button"], kwargs={"name": "Search"})]
    assert anchor.locator == wf.transition("t2").action.locator  # byte-for-byte the action's chain


def test_multi_step_locators_anchor_on_the_same_chain():
    traj = AgentTrajectory(
        task="t",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://x.com/",
                      action={"type": "goto", "url": "https://x.com"}),
            # multi-step chain (nth-disambiguated): anchored on the chain as a whole — there
            # is no translation step that could get it wrong
            AgentStep(n=2, kind="click", reasoning="click", url="https://x.com/",
                      action={"type": "click",
                              "locator": [{"fn": "locator", "args": ["#a"]},
                                          {"fn": "nth", "args": [0]}]}),
            # locator-less action: nothing to anchor on
            AgentStep(n=3, kind="press", reasoning="key", url="https://x.com/",
                      action={"type": "press", "keys": "l"}),
        ],
    )
    wf = compile_trajectory(traj, name="x")
    _, anchor = wf.state("s1").conditions
    assert anchor.locator == [LocatorStep(fn="locator", args=["#a"]), LocatorStep(fn="nth", args=[0])]
    assert wf.state("s2").conditions == []  # next action has no locator


def test_sample_values_become_params():
    wf = compile_trajectory(_traj(), name="yt", params={"query": "cat videos"})
    assert wf.params[0].name == "query" and wf.params[0].default == "cat videos"
    assert wf.transition("t2").action.text == "${query}"  # literal form substituted
    # the URL-encoded form in a state condition substituted too
    (cond,) = wf.state("s3").conditions
    assert "${query}" not in cond.pattern  # query string was stripped from the condition


def test_empty_trajectory_rejected():
    with pytest.raises(ValueError, match="no successful action steps"):
        compile_trajectory(AgentTrajectory(task="t"), name="empty")


def test_compiler_anchors_states_on_the_next_steps_element_inside_its_frame():
    """R2: a state is guarded by the visibility of the element the next transition acts on,
    evaluated in that element's iframe — the chain's own frame_locator steps carry the frame."""
    from netgent.agent.explorer.models import AgentStep, AgentTrajectory
    from netgent.schema.actions import ClickAction, FillAction, GotoAction, LocatorStep, UploadFileAction

    frame = LocatorStep(fn="frame_locator", args=['iframe[name="payframe"]'])
    traj = AgentTrajectory(
        task="pay",
        success=True,
        steps=[
            AgentStep(n=0, kind="goto", reasoning="", url="http://shop/checkout",
                      action=GotoAction(url="http://shop/checkout")),
            AgentStep(n=1, kind="fill", reasoning="", url="http://shop/checkout",
                      action=FillAction(locator=[frame, LocatorStep(fn="locator", args=["#card"])], text="4242")),
            AgentStep(n=2, kind="click", reasoning="", url="http://shop/checkout",
                      action=ClickAction(locator=[frame, LocatorStep(fn="locator", args=["#pay"])])),
            AgentStep(n=3, kind="click", reasoning="", url="http://shop/done",
                      action=ClickAction(locator=[frame, LocatorStep(fn="locator", args=["#dup"]),
                                                  LocatorStep(fn="nth", args=[1])])),
            AgentStep(n=4, kind="click", reasoning="", url="http://shop/done",
                      action=ClickAction(locator=[LocatorStep(fn="locator", args=["#top-level"])])),
            # uploads are deliberately not anchored: set_input_files works on HIDDEN file
            # inputs, which custom upload widgets hide on purpose
            AgentStep(n=5, kind="upload", reasoning="", url="http://shop/done",
                      action=UploadFileAction(locator=[frame, LocatorStep(fn="locator", args=["#file"])],
                                              paths=["/tmp/x"])),
        ],
    )
    wf = compile_trajectory(traj, name="pay")
    by_id = {s.id: s for s in wf.states}

    def anchors(sid):
        return [c.locator for c in by_id[sid].conditions if c.type == "selector_visible"]

    # s1 (after goto): url, then the next step's fill target inside the frame
    assert [c.type for c in by_id["s1"].conditions] == ["url_matches", "selector_visible"]
    assert anchors("s1") == [[frame, LocatorStep(fn="locator", args=["#card"])]]
    # s2 (after fill): next step clicks #pay inside the frame
    assert anchors("s2") == [[frame, LocatorStep(fn="locator", args=["#pay"])]]
    # s3: next is the nth-disambiguated in-frame chain — anchored as is
    assert anchors("s3") == [[frame, LocatorStep(fn="locator", args=["#dup"]), LocatorStep(fn="nth", args=[1])]]
    # s4: next is a top-frame click — a frame-free chain
    assert anchors("s4") == [[LocatorStep(fn="locator", args=["#top-level"])]]
    assert anchors("s5") == []  # next: upload
    assert by_id["s6"].conditions == []  # last state
    # every anchor evaluates the exact chain its edge dispatches
    for sid, tid in (("s1", "t2"), ("s2", "t3"), ("s3", "t4"), ("s4", "t5")):
        assert anchors(sid) == [wf.transition(tid).action.locator]


def test_step_dialog_becomes_a_dialog_matches_condition():
    """An alert-only form leaves URL and DOM unchanged: the dialog the submit raised is the
    only recognizable feedback, so the compiled post-submit state anchors on it."""
    from netgent.agent.explorer.models import AgentStep, AgentTrajectory
    from netgent.agent.generator.compiler import compile_trajectory
    from netgent.schema.actions import ClickAction, LocatorStep

    click = ClickAction(locator=[LocatorStep(fn="locator", args=["#submit"])])
    steps = [
        AgentStep(n=1, kind="click", reasoning="submit", url="https://site.test/form",
                  action=click, dialogs=["alert: Form submitted successfully! The secret is: dumbledore"]),
    ]
    wf = compile_trajectory(AgentTrajectory(task="t", steps=steps, success=True, stopped_reason=""), name="w")
    final = wf.states[-1]
    dialog = [c for c in final.conditions if c.type == "dialog_matches"]
    assert len(dialog) == 1
    assert "dumbledore" in dialog[0].pattern


def _ad_traj() -> AgentTrajectory:
    """A watch-page trajectory with an ad-skip click and a 15 s dwell."""
    return AgentTrajectory(
        task="watch a video, skip ads",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://yt.com/watch?v=x",
                      action={"type": "goto", "url": "https://yt.com/watch?v=x"}),
            AgentStep(n=2, kind="click", reasoning="A skip ads button is visible; skip the ad.",
                      url="https://yt.com/watch?v=x",
                      action={"type": "click", "locator": [{"fn": "locator", "args": ["#skip-ad"]}]}),
            AgentStep(n=3, kind="wait", reasoning="watch for 15 seconds", url="https://yt.com/watch?v=x",
                      action={"type": "wait", "seconds": 15.0}),
            AgentStep(n=4, kind="press", reasoning="fast forward", url="https://yt.com/watch?v=x",
                      action={"type": "press", "keys": "l"}),
        ],
    )


def test_interruption_clicks_become_scoped_interrupts():
    wf = compile_trajectory(_ad_traj(), name="yt")
    # The ad-skip click left the main word...
    assert [t.id for t in wf.transitions if not t.id.startswith("ti")] != []
    assert all("skip-ad" not in str(t.action) for t in wf.transitions if t.source.startswith("s") or t.source == "init")
    # ...and became an interrupt anchored on the skip button, scoped to watch-page states.
    (intr,) = wf.interrupts
    (anchor_cond,) = wf.state(intr.state).conditions
    assert anchor_cond.type == "selector_visible" and anchor_cond.locator == _css("#skip-ad")
    assert intr.max_fires == 3 and intr.resolve == ["ti1"]
    assert set(intr.scope) <= {s.id for s in wf.states}
    # resolution edge verifies the pop-up went away — same chain, hidden
    (done_cond,) = wf.state(wf.transition("ti1").target).conditions
    assert done_cond.type == "selector_hidden" and done_cond.locator == _css("#skip-ad")


def test_dwells_compile_to_bounded_repeats():
    wf = compile_trajectory(_ad_traj(), name="yt")
    assert wf.control_sequence is None  # rich program in use
    repeats = [n for n in wf.control if n.kind == "repeat"]
    (rep,) = repeats
    assert rep.max_iterations == 14  # 15 s = 1 s edge + 14 repeated 1 s slices
    (body,) = rep.body
    dwell_edge = wf.transition(body.edge)
    assert dwell_edge.source == dwell_edge.target  # self-loop: sweeps run between slices
    assert dwell_edge.action.seconds == 1.0


def test_linear_no_interrupt_trajectories_keep_control_sequence():
    wf = compile_trajectory(_traj(), name="yt")
    assert wf.control_sequence == ["t1", "t2", "t3"]
    assert wf.control is None and wf.interrupts == []


def test_reasoning_mention_alone_does_not_make_an_interrupt():
    """'maybe it restarted after the ad' on a seek-slider click must stay in the main word."""
    traj = AgentTrajectory(
        task="t",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://yt.com/watch?v=x",
                      action={"type": "goto", "url": "https://yt.com/watch?v=x"}),
            AgentStep(n=2, kind="click", reasoning="video is at 0:03, maybe it restarted after the ad",
                      url="https://yt.com/watch?v=x",
                      action={"type": "click",
                              "locator": [{"fn": "get_by_role", "args": ["slider"],
                                           "kwargs": {"name": "Seek slider"}}]}),
        ],
    )
    wf = compile_trajectory(traj, name="x")
    assert wf.interrupts == []  # target is not a dismissal control → main word
    assert len(wf.transitions) == 2


def test_params_bind_on_trajectories_with_interrupts_and_dwells():
    """Regression: _bind_params zipped steps against ALL transitions (strict), but dwell
    twins (t{i}_dwell) and interrupt resolutions (ti{k}) have no originating step — the
    zip must pair steps with the word's primary edges t1..tN only."""
    steps = list(_ad_traj().steps)
    steps.insert(1, AgentStep(n=10, kind="fill", reasoning="search", url="https://yt.com/watch?v=x",
                              action={"type": "fill", "locator": [{"fn": "locator", "args": ["input#q"]}],
                                      "text": "cat videos"}))
    traj = AgentTrajectory(task="t", success=True, steps=steps)
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="yt", params={"query": "cat videos"}, warnings=warnings)
    assert wf.interrupts and any(t.id.endswith("_dwell") for t in wf.transitions)  # the crash shape
    (fill_edge,) = [t for t in wf.transitions if t.action.type == "fill"]
    assert fill_edge.action.text == "${query}"
    assert not warnings


def _media_traj() -> AgentTrajectory:
    """A watch/seek/pause run with per-step media readings (the l-presses-into-the-ad shape)."""
    video = [{"fn": "locator", "args": ["#movie_player video"]}]
    return AgentTrajectory(
        task="watch, fast-forward, pause",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://youtube.com/watch?v=x",
                      action={"type": "goto", "url": "https://youtube.com/watch?v=x"}),
            # reading BEFORE this press: the AD is playing (short duration) -> s1 stays ungated
            AgentStep(n=2, kind="press", reasoning="mute", url="https://youtube.com/watch?v=x",
                      media="video PLAYING at 0:03 / 1:30 [muted]",
                      action={"type": "press", "keys": "m", "locator": video}),
            # content playing before the dwell -> s2 (the dwell's source) is gated
            AgentStep(n=3, kind="wait", reasoning="watch", url="https://youtube.com/watch?v=x",
                      media="video PLAYING at 0:04 / 7:04 [muted]",
                      action={"type": "wait", "seconds": 20.0}),
            # content playing before the seek press -> s3 gated
            AgentStep(n=4, kind="press", reasoning="fast forward", url="https://youtube.com/watch?v=x",
                      media="video PLAYING at 0:24 / 7:04 [muted]",
                      action={"type": "press", "keys": "l", "locator": video}),
            # PAUSED before the pause dwell -> s4 NOT gated (a playing-gate would deadlock a pause)
            AgentStep(n=5, kind="wait", reasoning="hold the pause", url="https://youtube.com/watch?v=x",
                      media="video PAUSED at 0:34 / 7:04 [muted]",
                      action={"type": "wait", "seconds": 10.0}),
        ],
    )


def test_media_gates_playing_states_only_with_ad_proof_duration_threshold():
    wf = compile_trajectory(_media_traj(), name="media")
    threshold = min(round((7 * 60 + 4) / 2), 120)  # capped at 120s

    def gates(sid):
        return [c for c in wf.state(sid).conditions if c.type == "media_playing"]

    assert gates("s1") == []  # the ad was playing here — its 90s duration is below threshold
    (g2,) = gates("s2")
    (g3,) = gates("s3")
    assert g2.min_duration_s == g3.min_duration_s == float(threshold) and g2.playing
    assert gates("s4") == []  # paused phase: a playing-gate would deadlock the pause dwell
    # gated states may legitimately wait out an unskippable ad
    assert wf.state("s2").timeout_ms >= 130_000
    assert wf.state("s4").timeout_ms == 10_000


def test_media_gate_absent_without_readings_or_for_short_content():
    wf = compile_trajectory(_traj(), name="yt")  # no media readings anywhere
    assert all(c.type != "media_playing" for s in wf.states for c in s.conditions)
    short = _media_traj()
    for s in short.steps:
        if s.media:
            s.media = s.media.replace("7:04", "0:25").replace("1:30", "0:20")
    wf = compile_trajectory(short, name="short")  # 25s content: length can't tell it from an ad
    assert all(c.type != "media_playing" for s in wf.states for c in s.conditions)


def test_media_readings_parse_detached_players_and_ignore_unloaded_ones():
    from netgent.agent.generator.compiler import _media_readings

    class Step:
        media = "audio (detached) PLAYING at 0:07 / 3:12 [muted]; video NOT LOADED (no source); video PAUSED at 1:00"

    assert _media_readings(Step()) == [("PLAYING", 192), ("PAUSED", None)]
