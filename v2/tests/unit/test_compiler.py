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


def test_parameterized_role_name_drops_exact_match():
    """An accessible name containing the sample value becomes ${param}; exact=True would then
    fail on replay when the site renders the value in another case ("Cat Videos" vs "cat videos")."""
    from netgent.agent.explore_agent.browser_agent import AgentStep, AgentTrajectory
    from netgent.agent.workflow_generator_agent.compiler import compile_trajectory
    from netgent.schema.actions import ClickAction, LocatorStep

    traj = AgentTrajectory(task="t", success=True)
    traj.steps.append(AgentStep(n=1, kind="click", reasoning="", url="https://x/", action=ClickAction(locator=[
        LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": "NEW Funny Cat Videos 2026", "exact": True}),
        LocatorStep(fn="filter", kwargs={"visible": True}),
    ])))
    wf = compile_trajectory(traj, name="w", params={"query": "cat videos"})
    step = wf.transitions[0].action.locator[0]
    assert step.kwargs["name"] == "NEW Funny ${query} 2026"
    assert step.kwargs["exact"] is False
