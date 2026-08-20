"""Trajectory -> workflow compilation: actions become transitions, URLs become
state conditions, and sample values become ${name} parameters."""

import pytest

from netgent.agent.browser_agent import AgentStep, AgentTrajectory
from netgent.agent.compiler import compile_trajectory


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
