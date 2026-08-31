"""Parameter binding: the compiler sweeps the caller's sample values out of value fields and
state conditions (never locators) and WARNS about what it could not bind."""

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.schema.actions import ClickAction, FillAction, GotoAction, LocatorStep


def _fill(n, text, url="https://site/"):
    return AgentStep(n=n, kind="fill", reasoning="", url=url,
                     action=FillAction(locator=[LocatorStep(fn="locator", args=["#q"])], text=text))


def test_sample_value_in_a_value_field_binds_case_insensitively():
    traj = AgentTrajectory(task="t", success=True, steps=[_fill(1, "Cat Videos")])
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="yt", params={"query": "cat videos"}, warnings=warnings)
    assert wf.transition("t1").action.text == "${query}"
    assert warnings == []


def test_locator_names_are_never_abstracted_but_url_conditions_are():
    link = ClickAction(locator=[LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": "Monstercat"})])
    steps = [
        AgentStep(n=1, kind="click", reasoning="", url="https://twitch/", action=link),
        AgentStep(n=2, kind="click", reasoning="", url="https://twitch/monstercat", action=link),
    ]
    wf = compile_trajectory(AgentTrajectory(task="t", success=True, steps=steps), name="tw",
                            params={"channel": "monstercat"})
    assert all(t.action.locator[0].kwargs["name"] == "Monstercat" for t in wf.transitions)
    assert any("${channel}" in c.pattern for s in wf.states for c in s.conditions if c.type == "url_matches")


def test_unbound_parameter_warns_instead_of_failing_silently():
    traj = AgentTrajectory(task="t", success=True, steps=[_fill(1, "something else")])
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="x", params={"query": "cat videos"}, warnings=warnings)
    assert wf.params[0].name == "query"
    assert warnings and "never bound" in warnings[0]


def test_sample_value_inside_a_goto_url_is_substituted_url_encoded():
    step = AgentStep(n=1, kind="goto", reasoning="", url="https://s/?q=cat+videos",
                     action=GotoAction(url="https://s/?q=cat+videos"))
    wf = compile_trajectory(AgentTrajectory(task="t", success=True, steps=[step]), name="g",
                            params={"query": "cat videos"})
    assert wf.transition("t1").action.url == "https://s/?q=${query}"
