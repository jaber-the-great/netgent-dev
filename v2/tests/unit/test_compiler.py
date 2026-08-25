"""Trajectory -> workflow compilation: actions become transitions, URLs become
state conditions, and sample values become ${name} parameters."""

import pytest

from netgent.agent.explore_agent.browser_agent import AgentStep, AgentTrajectory
from netgent.agent.workflow_generator_agent.compiler import compile_trajectory


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
    # step 2 stayed on the same page -> unconditioned state; step 3 moved -> url condition
    assert wf.state("s2").conditions == []
    (cond,) = wf.state("s3").conditions
    assert cond.pattern == "https://youtube\\.com/results"  # query stripped, regex-escaped


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
    from netgent.agent.explore_agent.browser_agent import AgentStep, AgentTrajectory
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
            # nth-disambiguated chains are not expressible as a CSS trigger; top-frame
            # elements and uploads are deliberately not anchored → no derived condition
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
    assert [c.type for c in by_id["s4"].conditions] == ["url_matches"]  # next: top-frame click
    assert by_id["s5"].conditions == []  # next: upload
    assert by_id["s6"].conditions == []  # last state


def test_compiler_folds_a_frame_nth_step_into_the_frame_path():
    from netgent.agent.explore_agent.browser_agent import AgentStep, AgentTrajectory
    from netgent.agent.workflow_generator_agent.compiler import _element_condition
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
