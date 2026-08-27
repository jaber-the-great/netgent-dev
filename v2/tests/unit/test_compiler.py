"""Trajectory -> workflow compilation: actions become transitions, URLs become
state conditions, and sample values become ${name} parameters."""

import pytest

from netgent.agent.explorer.browser_agent import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory


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
    assert anchor.type == "selector_visible" and anchor.selector == "input#q"
    # step 3 moved -> url condition; final state has no next edge -> no anchor
    (cond,) = wf.state("s3").conditions
    assert cond.pattern == "https://youtube\\.com/results"  # query stripped, regex-escaped


def test_states_anchor_on_next_edges_target_element():
    wf = compile_trajectory(_traj(), name="yt")
    # s1 (after goto): url condition AND the anchor for t2's fill target
    url_cond, anchor = wf.state("s1").conditions
    assert url_cond.type == "url_matches"
    assert anchor.type == "selector_visible" and anchor.selector == "input#q"


def test_get_by_role_locator_becomes_role_selector_anchor():
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
    assert anchor.selector == 'role=button[name="Search" i]'


def test_untranslatable_locators_get_no_anchor():
    traj = AgentTrajectory(
        task="t",
        success=True,
        steps=[
            AgentStep(n=1, kind="goto", reasoning="open", url="https://x.com/",
                      action={"type": "goto", "url": "https://x.com"}),
            # multi-step chain: conservatively no anchor (open gate, never a wrong guard)
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
    assert all(c.type == "url_matches" for c in wf.state("s1").conditions)  # no anchor added
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


def test_compiler_anchors_states_on_the_next_steps_element_with_frame_path():
    """R2: a state is guarded by the visibility of the element the next transition acts on,
    evaluated in that element's iframe (frame_locator steps → frame_path)."""
    from netgent.agent.explorer.browser_agent import AgentStep, AgentTrajectory
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
            # nth-disambiguated chains are not expressible as a CSS trigger; uploads are
            # deliberately not anchored → no derived condition. Top-frame single-step
            # targets ARE anchored (selector_visible, no frame_path).
            AgentStep(n=3, kind="click", reasoning="", url="http://shop/done",
                      action=ClickAction(locator=[frame, LocatorStep(fn="locator", args=["#dup"]),
                                                  LocatorStep(fn="nth", args=[1])])),
            AgentStep(n=4, kind="click", reasoning="", url="http://shop/done",
                      action=ClickAction(locator=[LocatorStep(fn="locator", args=["#top-level"])])),
            AgentStep(n=5, kind="upload", reasoning="", url="http://shop/done",
                      action=UploadFileAction(locator=[frame, LocatorStep(fn="locator", args=["#file"])],
                                              paths=["/tmp/x"])),
        ],
    )
    wf = compile_trajectory(traj, name="pay")
    by_id = {s.id: s for s in wf.states}
    # s1 (after goto): next step fills #card inside the frame
    s1 = [c.model_dump() for c in by_id["s1"].conditions]
    assert {"type": "selector_visible", "selector": "#card", "frame_path": ['iframe[name="payframe"]']} in s1
    assert s1[0]["type"] == "url_matches"
    # s2 (after fill): next step clicks #pay inside the frame
    assert [c.model_dump() for c in by_id["s2"].conditions] == [
        {"type": "selector_visible", "selector": "#pay", "frame_path": ['iframe[name="payframe"]']}
    ]
    assert by_id["s3"].conditions == []  # next: nth chain
    # next: top-frame click — anchored by _target_selector (merged behavior), frame-free
    s4 = [c.model_dump() for c in by_id["s4"].conditions]
    assert [c["type"] for c in s4] == ["url_matches", "selector_visible"]
    assert s4[1]["selector"] == "#top-level" and not s4[1].get("frame_path")
    assert by_id["s5"].conditions == []  # next: upload
    assert by_id["s6"].conditions == []  # last state


def test_compiler_folds_a_frame_nth_step_into_the_frame_path():
    from netgent.agent.explorer.browser_agent import AgentStep, AgentTrajectory
    from netgent.agent.generator.compiler import _element_condition
    from netgent.schema.actions import ClickAction, GotoAction, LocatorStep

    chain = [LocatorStep(fn="frame_locator", args=["iframe.two"]), LocatorStep(fn="nth", args=[1]),
             LocatorStep(fn="locator", args=["#go"])]
    assert _element_condition(ClickAction(locator=chain))["frame_path"] == ["iframe.two >> nth=1"]
    traj = AgentTrajectory(task="t", steps=[
        AgentStep(n=0, kind="goto", reasoning="", url="http://x/", action=GotoAction(url="http://x/")),
        AgentStep(n=1, kind="click", reasoning="", url="http://x/", action=ClickAction(locator=chain)),
    ])
    wf = compile_trajectory(traj, name="n")
    assert wf.states[1].conditions[1].frame_path == ["iframe.two >> nth=1"]


def test_step_dialog_becomes_a_dialog_matches_condition():
    """An alert-only form leaves URL and DOM unchanged: the dialog the submit raised is the
    only recognizable feedback, so the compiled post-submit state anchors on it."""
    from netgent.agent.explorer.browser_agent import AgentStep, AgentTrajectory
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
    assert anchor_cond.type == "selector_visible" and anchor_cond.selector == "#skip-ad"
    assert intr.max_fires == 3 and intr.resolve == ["ti1"]
    assert set(intr.scope) <= {s.id for s in wf.states}
    # resolution edge verifies the pop-up went away
    (done_cond,) = wf.state(wf.transition("ti1").target).conditions
    assert done_cond.type == "selector_hidden"


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
