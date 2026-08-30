"""Parameter conveyance: the explorer declares `param` on the step that used a sample value;
the compiler binds ${name} structurally, falls back to the literal sweep for value fields and
state conditions only, and WARNS about what it could not bind
(docs/research/browser-agent-prompting.md §7.3)."""

from netgent.agent.explorer.decision import AgentDecision
from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.compiler import compile_trajectory
from netgent.schema.actions import ClickAction, FillAction, GotoAction, LocatorStep


def _fill(n, text, param=None, url="https://site/"):
    return AgentStep(n=n, kind="fill", reasoning="", url=url, param=param,
                     action=FillAction(locator=[LocatorStep(fn="locator", args=["#q"])], text=text))


def test_decision_carries_param_and_defaults_to_none():
    assert AgentDecision(reasoning="r", kind="fill", index=1, text="x").param is None
    assert AgentDecision(reasoning="r", kind="fill", index=1, text="x", param="query").param == "query"


def test_declared_param_binds_even_when_the_model_typed_something_else():
    """The measured YouTube case: the explorer typed 'YouTube' instead of the sample → the old
    literal sweep produced 0 ${query}. With `param` declared, the placeholder is bound and
    the mismatch becomes a warning instead of a silent zero."""
    traj = AgentTrajectory(task="t", success=True, steps=[_fill(1, "YouTube", param="query")])
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="yt", params={"query": "cat videos"}, warnings=warnings)
    assert wf.transition("t1").action.text == "${query}"
    assert len(warnings) == 1 and "typed 'YouTube'" in warnings[0] and "'cat videos'" in warnings[0]


def test_declared_param_with_matching_value_binds_silently():
    traj = AgentTrajectory(task="t", success=True, steps=[_fill(1, "Cat Videos", param="query")])
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="yt", params={"query": "cat videos"}, warnings=warnings)
    assert wf.transition("t1").action.text == "${query}"
    assert warnings == []


def test_undeclared_step_falls_back_to_the_literal_sweep_on_value_fields():
    traj = AgentTrajectory(task="t", success=True, steps=[_fill(1, "cat videos")])
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="yt", params={"query": "cat videos"}, warnings=warnings)
    assert wf.transition("t1").action.text == "${query}"
    assert warnings == []


def test_locator_names_are_abstracted_only_on_a_declared_step_and_only_whole_value():
    link = ClickAction(locator=[LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": "Monstercat"})])
    catalog = ClickAction(locator=[LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": "Catalog"})])
    steps = [
        AgentStep(n=1, kind="click", reasoning="", url="https://twitch/", action=link, param="channel"),
        AgentStep(n=2, kind="click", reasoning="", url="https://twitch/monstercat", action=catalog),
        AgentStep(n=3, kind="click", reasoning="", url="https://twitch/monstercat", action=link),  # undeclared
    ]
    warnings: list[str] = []
    wf = compile_trajectory(AgentTrajectory(task="t", success=True, steps=steps), name="tw",
                            params={"channel": "monstercat", "cat": "cat"}, warnings=warnings)
    assert wf.transition("t1").action.locator[0].kwargs["name"] == "${channel}"  # declared, whole value
    assert wf.transition("t2").action.locator[0].kwargs["name"] == "Catalog"  # never by substring
    assert wf.transition("t3").action.locator[0].kwargs["name"] == "Monstercat"  # undeclared: untouched
    # the url_matches pattern (a value field) still gets the fallback sweep
    assert any("${channel}" in c.pattern for s in wf.states for c in s.conditions if c.type == "url_matches")
    assert any("'cat' was never bound" in w for w in warnings)


def test_unbound_parameter_warns_instead_of_failing_silently():
    traj = AgentTrajectory(task="t", success=True, steps=[_fill(1, "something else")])
    warnings: list[str] = []
    wf = compile_trajectory(traj, name="x", params={"query": "cat videos"}, warnings=warnings)
    assert wf.params[0].name == "query"
    assert warnings and "never bound" in warnings[0]


def test_declared_goto_param_substitutes_inside_the_url():
    step = AgentStep(n=1, kind="goto", reasoning="", url="https://s/?q=cat+videos", param="query",
                     action=GotoAction(url="https://s/?q=cat+videos"))
    wf = compile_trajectory(AgentTrajectory(task="t", success=True, steps=[step]), name="g",
                            params={"query": "cat videos"})
    assert wf.transition("t1").action.url == "https://s/?q=${query}"


def test_declared_param_on_a_valueless_action_is_reported():
    step = AgentStep(n=1, kind="click", reasoning="", url="https://s/", param="query",
                     action=ClickAction(locator=[LocatorStep(fn="locator", args=["#go"])]))
    warnings: list[str] = []
    compile_trajectory(AgentTrajectory(task="t", success=True, steps=[step]), name="g",
                       params={"query": "cat videos"}, warnings=warnings)
    assert any("carrying no value" in w for w in warnings) and any("never bound" in w for w in warnings)
