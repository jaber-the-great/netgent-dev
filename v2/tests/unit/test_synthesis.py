"""Synthesis: several fake trajectories -> one workflow with a core path, guarded
optional steps (ε-branches), evidence-based conditions, and minimization. No browser."""

import pytest

from netgent.agent.browser_agent import AgentStep, AgentTrajectory
from netgent.agent.evidence import ElementProbe, PageEvidence
from netgent.agent.synthesis import Exploration, abstract_params, synthesize
from netgent.schema.control import Branch, EdgeStep

HOME = "https://site.test/"
WATCH = "https://site.test/watch?v=1"
SEARCH = [{"fn": "get_by_role", "args": ["searchbox"], "kwargs": {"name": "Search"}}]
PROCEED = [{"fn": "get_by_role", "args": ["button"], "kwargs": {"name": "Proceed"}}]


def ev(url, texts=(), probe=None, visible=True, video=False, playing=False):
    probes = [ElementProbe(locator=probe, visible=visible)] if probe else []
    return PageEvidence(
        url=url, title="t", texts=list(texts), video_present=video, video_playing=playing, probes=probes
    )


def step(n, action, url, evidence=None, error=None):
    return AgentStep(n=n, kind=action["type"], reasoning="", url=url, action=None if error else action,
                     error=error, evidence=evidence)


def run(with_popup: bool, channel="monstercat", extra_scroll=False, success=True):
    steps = [step(0, {"type": "goto", "url": HOME}, HOME,
                  ev(HOME, ["Welcome"], probe=PROCEED if with_popup else SEARCH))]
    n = 1
    if with_popup:
        steps.append(step(n, {"type": "click", "locator": PROCEED}, HOME, ev(HOME, ["Welcome"], probe=SEARCH)))
        n += 1
    link = [{"fn": "get_by_role", "args": ["link"], "kwargs": {"name": channel}}]
    steps.append(step(n, {"type": "fill", "locator": SEARCH, "text": channel}, HOME,
                      ev(HOME, ["Welcome"], probe=link)))
    n += 1
    if extra_scroll:
        steps.append(step(n, {"type": "scroll", "down": True, "pages": 1.0}, HOME, ev(HOME, ["Welcome"], probe=link)))
        n += 1
    steps.append(step(n, {"type": "click", "locator": link}, WATCH,
                      ev(WATCH, ["Now playing", channel], video=True, playing=True)))
    n += 1
    steps.append(step(n, {"type": "wait", "seconds": 10}, WATCH,
                      ev(WATCH, ["Now playing", channel], video=True, playing=True)))
    steps.append(AgentStep(n=n + 1, kind="done", reasoning="", url=WATCH))
    return Exploration(AgentTrajectory(task="watch", success=success, steps=steps), {"channel": channel})


def test_single_run_is_linear_with_evidence_conditions():
    wf = synthesize([run(False)], name="w").workflow
    assert wf.control_sequence == ["t1", "t2", "t3", "t4"]
    assert wf.control is None
    # s1 (after goto): url + the next edge's target is visible
    assert [c.type for c in wf.state("s1").conditions] == ["url_matches", "element_visible"]
    # the watch state is verified by the player running, not just the URL
    assert [c.type for c in wf.state("s3").conditions] == ["url_matches", "video_playing"]
    assert wf.accept_states == ["s4"]
    assert [c.type for c in wf.state("s4").conditions] == ["video_playing"]
    # params abstracted: sample value -> ${channel}, default kept
    assert wf.transition("t2").action.text == "${channel}"
    assert wf.params[0].default == "monstercat"


def test_optional_popup_becomes_guarded_branch_with_epsilon_arm():
    result = synthesize([run(True), run(False)], name="w")
    wf = result.workflow
    assert wf.control is not None
    branch = wf.control[1]
    assert isinstance(wf.control[0], EdgeStep) and isinstance(branch, Branch)
    assert branch.probe_ms > 0
    # arm: guarded by the popup button's visibility; ε into the popup state, then the click
    (arm,) = branch.arms
    guard = wf.state(arm.when)
    assert guard.conditions[0].type == "element_visible"
    assert guard.conditions[0].locator == wf.transition("t1b1_1").action.locator
    assert [wf.transition(n.edge).action.type for n in arm.then] == ["noop", "click"]
    # else: ε straight to the join state; both paths converge on s1j
    assert [wf.transition(n.edge).action.type for n in branch.else_] == ["noop"]
    assert wf.transition("t1_eps").target == wf.transition("t1b1_1").target == "s1j"
    # the join state carries the evidence condition (search box visible in both runs)
    assert [c.type for c in wf.state("s1j").conditions] == ["element_visible", "text_visible"]
    # the next core edge fires from the join state
    assert wf.transition("t2").source == "s1j"
    assert any("guarded branch" in n for n in result.notes)


def test_variation_runs_align_after_param_abstraction():
    wf = synthesize([run(False, "monstercat"), run(False, "bobross")], name="w").workflow
    assert len(wf.transitions) == 4  # identical core after ${channel} abstraction
    assert wf.transition("t3").action.locator[0].kwargs["name"] == "${channel}"
    # a text that is param-bound is never a condition; a shared new text is
    texts = [c.text for c in wf.state("s3").conditions if c.type == "text_visible"]
    assert texts == ["Now playing"]


def test_scroll_that_changed_nothing_is_minimized_away():
    result = synthesize([run(False, extra_scroll=True)], name="w")
    assert [t.action.type for t in result.workflow.transitions] == ["goto", "fill", "click", "wait"]
    assert any("dropped scroll" in n for n in result.notes)


def test_click_then_fill_same_field_drops_the_click():
    steps = [
        step(0, {"type": "goto", "url": HOME}, HOME),
        step(1, {"type": "click", "locator": SEARCH}, HOME),
        step(2, {"type": "fill", "locator": SEARCH, "text": "a"}, HOME),
        step(3, {"type": "click", "locator": SEARCH}, HOME),
        step(4, {"type": "fill", "locator": SEARCH, "text": "a"}, HOME),
        step(5, {"type": "press", "keys": "Enter"}, HOME + "results"),
    ]
    traj = AgentTrajectory(task="t", success=True, steps=steps)
    wf = synthesize([Exploration(traj)], name="w").workflow
    assert [t.action.type for t in wf.transitions] == ["goto", "fill", "press"]


def test_failed_runs_are_excluded_and_noted():
    result = synthesize([run(False), run(True, success=False)], name="w")
    assert result.workflow.control is None  # the popup run didn't count
    assert any("did not reach done" in n for n in result.notes)
    with pytest.raises(ValueError, match="no successful exploration"):
        synthesize([run(False, success=False)], name="w")


def test_abstract_params_literal_and_encoded_case_insensitive():
    out = abstract_params({"a": "Cat+Videos and cat videos", "b": ["x"]}, {"q": "cat videos"})
    assert out == {"a": "${q} and ${q}", "b": ["x"]}
