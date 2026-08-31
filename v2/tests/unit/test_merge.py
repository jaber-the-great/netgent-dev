"""The typed-key merge: N same-task trajectories → one generalized workflow, pure code.

Covers the four dispositions (Param, Interrupt, Branch, reject) plus trigger intersection,
the parameterized dwell, target generalization, and the single-achieved-run degradation."""

import pytest

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.merge import GeneralizedTrajectory, RunInput, merge_trajectories


def _step(n, kind, url, action, reasoning="", dialogs=None, error=None):
    return AgentStep(n=n, kind=kind, reasoning=reasoning, url=url, action=action,
                     dialogs=dialogs or [], error=error)


def _goto(url):
    return {"type": "goto", "url": url}


def _fill(sel, text):
    return {"type": "fill", "locator": [{"fn": "locator", "args": [sel]}], "text": text}


def _click(sel):
    return {"type": "click", "locator": [{"fn": "locator", "args": [sel]}]}


def _click_role(role, name):
    return {"type": "click", "locator": [{"fn": "get_by_role", "args": [role], "kwargs": {"name": name}}]}


def _press(sel, keys="Enter"):
    return {"type": "press", "keys": keys, "locator": [{"fn": "locator", "args": [sel]}]}


def _wait(seconds):
    return {"type": "wait", "seconds": seconds}


def _traj(task, steps):
    return AgentTrajectory(task=task, success=True, steps=steps)


def _search_run(query, extra=()):
    steps = [
        _step(0, "goto", "https://site.test/", _goto("https://site.test/")),
        _step(1, "fill", "https://site.test/", _fill("#q", query)),
        _step(2, "press", "https://site.test/results", _press("#q")),
        *extra,
    ]
    return _traj(f"search for {query}", steps)


def test_param_inference_from_varying_values():
    """Disposition 1: a value that varies at an aligned column and matches each run's planned
    value becomes ${param} with the planner's name; run 1's value is the default."""
    runs = [
        RunInput(run=1, trajectory=_search_run("cat videos"), values={"query": "cat videos"}),
        RunInput(run=2, trajectory=_search_run("dog videos"), values={"query": "dog videos"}),
    ]
    out = merge_trajectories(runs, name="s")
    wf = out.workflow
    (fill_edge,) = [t for t in wf.transitions if t.action.type == "fill"]
    assert fill_edge.action.text == "${query}"
    (p,) = wf.params
    assert p.name == "query" and p.default == "cat videos"
    assert out.generalized.params[0].values_by_run == {1: "cat videos", 2: "dog videos"}
    assert any(c.disposition == "param" and c.param == "query" for c in out.generalized.columns)


def test_constant_values_are_not_confirmed_as_params():
    """A planner-proposed name whose values never vary is a value, not a parameter."""
    runs = [
        RunInput(run=1, trajectory=_search_run("cat videos"), values={"query": "cat videos"}),
        RunInput(run=2, trajectory=_search_run("cat videos"), values={"query": "cat videos"}),
    ]
    wf = merge_trajectories(runs, name="s").workflow
    assert wf.params == []
    (fill_edge,) = [t for t in wf.transitions if t.action.type == "fill"]
    assert fill_edge.action.text == "cat videos"  # literal kept


def test_trigger_intersection_url_condition_only_when_every_run_agrees():
    """A url_matches survives only when every run landed on the same base at that column."""
    run1 = _traj("t", [
        _step(0, "goto", "https://site.test/a", _goto("https://site.test/a")),
        _step(1, "click", "https://site.test/next", _click("#go")),
    ])
    run2 = _traj("t", [
        _step(0, "goto", "https://site.test/a", _goto("https://site.test/a")),
        _step(1, "click", "https://site.test/other", _click("#go")),  # different landing page
    ])
    wf = merge_trajectories([RunInput(run=1, trajectory=run1), RunInput(run=2, trajectory=run2)], name="t").workflow
    s1, s2 = wf.state("s1"), wf.state("s2")
    assert any(c.type == "url_matches" for c in s1.conditions)  # both runs agreed on /a
    assert not any(c.type == "url_matches" for c in s2.conditions)  # divergent landing: dropped
    assert wf.accept_states == []  # final state has no intersected condition -> legacy success


def test_trigger_intersection_keeps_shared_anchor_and_accept_state():
    runs = [
        RunInput(run=1, trajectory=_search_run("a b"), values={"query": "a b"}),
        RunInput(run=2, trajectory=_search_run("c d"), values={"query": "c d"}),
    ]
    wf = merge_trajectories(runs, name="s").workflow
    # s1 (after goto): anchored on the fill target that held in both runs
    assert any(c.type == "selector_visible" and c.selector == "#q" for c in wf.state("s1").conditions)
    # final state: both runs ended on /results -> url condition -> accept state
    (cond,) = wf.state("s3").conditions
    assert cond.type == "url_matches" and "results" in cond.pattern
    assert wf.accept_states == ["s3"]


def test_interrupt_candidate_from_cross_run_presence():
    """Disposition 2: a dismissal-shaped click present in one run only leaves the main word
    and becomes a scoped, bounded interrupt."""
    dismiss = _step(9, "click", "https://site.test/results", _click("#overlay-close"),
                    reasoning="close the promo overlay")
    runs = [
        RunInput(run=1, trajectory=_search_run("x y")),
        RunInput(run=2, trajectory=_search_run("x y", extra=()), values={}),
    ]
    # insert the overlay click mid-run for run 2 only
    runs[1].trajectory.steps.insert(2, dismiss)
    out = merge_trajectories(runs, name="s")
    wf = out.workflow
    (intr,) = wf.interrupts
    anchor = wf.state(intr.state)
    assert anchor.conditions[0].selector == "#overlay-close"
    assert intr.max_fires == 3
    assert [t.id for t in wf.transitions if t.id.startswith("t") and not t.id.startswith("ti")] == ["t1", "t2", "t3"]
    assert any(c.disposition == "interrupt" for c in out.generalized.columns)
    assert out.generalized.interrupts[0]["selector"] == "#overlay-close"


def test_branch_from_downstream_divergence():
    """Disposition 3: runs that genuinely fork (distinct targets, extra steps) become a
    Branch with one arm per continuation, guarded by each arm's first target."""
    common_head = [
        _step(0, "goto", "https://site.test/", _goto("https://site.test/")),
    ]
    common_tail = [
        _step(5, "click", "https://site.test/done", _click("#finish")),
    ]
    run1 = _traj("t", common_head + [
        _step(1, "click", "https://site.test/", _click("#tab-basic")),
        _step(2, "fill", "https://site.test/", _fill("#name", "Ada")),
    ] + common_tail)
    run2 = _traj("t", common_head + [
        _step(1, "click", "https://site.test/", _click("#tab-pro")),
    ] + common_tail)
    out = merge_trajectories([RunInput(run=1, trajectory=run1), RunInput(run=2, trajectory=run2)], name="t")
    wf = out.workflow
    branches = [n for n in wf.control if n.kind == "branch"]
    (br,) = branches
    assert len(br.arms) == 2 and br.else_ is None  # no arm matched = new territory, never a skip
    guard_selectors = {wf.state(arm.when).conditions[0].selector for arm in br.arms}
    assert guard_selectors == {"#tab-basic", "#tab-pro"}
    # both arms converge on the same state, and the word continues to #finish from there
    arm_last_edges = [arm.then[-1].edge for arm in br.arms]
    targets = {wf.transition(e).target for e in arm_last_edges}
    assert len(targets) == 1
    assert out.generalized.branches[0]["runs_by_arm"] == [[1], [2]]


def test_reject_unresolved_divergence_keeps_spine_and_warns():
    """Disposition 4: divergence with no distinguishing guard is rejected with a warning
    naming the column; run 1's step is kept so the artifact stays replayable."""
    run1 = _search_run("x y", extra=(
        _step(3, "fill", "https://site.test/results", _fill("#extra", "only run 1")),
    ))
    run2 = _search_run("x y")
    warnings: list[str] = []
    out = merge_trajectories(
        [RunInput(run=1, trajectory=run1), RunInput(run=2, trajectory=run2)], name="s", warnings=warnings
    )
    assert any("kept run 1" in w for w in warnings)
    assert any(c.disposition == "kept-spine" for c in out.generalized.columns)
    (extra_edge,) = [t for t in out.workflow.transitions if t.action.type == "fill" and "extra" in str(t.action)]
    assert extra_edge.action.text == "only run 1"


def test_gap_scroll_and_wait_are_dropped_quietly():
    scroll = _step(9, "scroll", "https://site.test/results", {"type": "scroll", "down": True, "pages": 1.0})
    run1 = _search_run("x y")
    run2 = _search_run("x y")
    run2.steps.insert(2, scroll)
    out = merge_trajectories([RunInput(run=1, trajectory=run1), RunInput(run=2, trajectory=run2)], name="s")
    assert not any(t.action.type == "scroll" for t in out.workflow.transitions)
    assert any(c.disposition == "dropped" and c.action_type == "scroll" for c in out.generalized.columns)


def test_parameterized_dwell_compiles_to_repeat_count():
    """A wait whose duration varies with a planned value becomes Repeat(count="${name}") of
    1 s slices behind a noop edge — interrupt sweeps still run between slices."""
    def run(seconds):
        return _traj("watch", [
            _step(0, "goto", "https://site.test/watch", _goto("https://site.test/watch")),
            _step(1, "wait", "https://site.test/watch", _wait(seconds)),
        ])
    runs = [
        RunInput(run=1, trajectory=run(5.0), values={"watch_time": "5"}),
        RunInput(run=2, trajectory=run(10.0), values={"watch_time": "10"}),
    ]
    wf = merge_trajectories(runs, name="w").workflow
    (rep,) = [n for n in wf.control if n.kind == "repeat"]
    assert rep.count == "${watch_time}" and rep.max_iterations >= 30
    (noop_edge,) = [t for t in wf.transitions if t.action.type == "noop"]
    (dwell_edge,) = [t for t in wf.transitions if t.action.type == "wait"]
    assert dwell_edge.source == dwell_edge.target and dwell_edge.action.seconds == 1.0
    assert noop_edge.target == dwell_edge.source
    (p,) = wf.params
    assert p.name == "watch_time" and p.default == "5"


def test_parameterized_dwell_tolerates_units_in_planner_values():
    """Planners write durations in natural language ("10 seconds"); the seconds match
    extracts the number, and the stored param values are bare numbers (they feed
    Repeat.count, which counts 1 s slices)."""
    def run(seconds):
        return _traj("watch", [
            _step(0, "goto", "https://site.test/watch", _goto("https://site.test/watch")),
            _step(1, "wait", "https://site.test/watch", _wait(seconds)),
        ])
    runs = [
        RunInput(run=1, trajectory=run(5.0), values={"watch_time": "5 seconds"}),
        RunInput(run=2, trajectory=run(10.0), values={"watch_time": "10 seconds"}),
    ]
    wf = merge_trajectories(runs, name="w").workflow
    (rep,) = [n for n in wf.control if n.kind == "repeat"]
    assert rep.count == "${watch_time}"
    (p,) = wf.params
    assert p.default == "5"  # bare number, so resolve_params -> a coercible count


def test_target_generalization_role_name_contains_value():
    """A click column whose role-name targets each contain that run's value becomes
    get_by_role(role, name="${param}") + nth(0) — the first match naming the value."""
    def run(query, title):
        return _search_run(query, extra=(
            _step(3, "click", "https://site.test/results", _click_role("link", title)),
        ))
    runs = [
        RunInput(run=1, trajectory=run("lofi hip hop", "lofi hip hop radio 24/7"),
                 values={"query": "lofi hip hop"}),
        RunInput(run=2, trajectory=run("cat video", "funny CAT VIDEO compilation"),
                 values={"query": "cat video"}),
    ]
    out = merge_trajectories(runs, name="s")
    (click_edge,) = [t for t in out.workflow.transitions if t.action.type == "click"]
    chain = click_edge.action.locator
    assert chain[-2].fn == "get_by_role" and chain[-2].kwargs["name"] == "${query}"
    assert chain[-1].fn == "nth" and chain[-1].args == [0]
    assert any(c.disposition == "param-target" for c in out.generalized.columns)


def test_target_varies_without_matching_value_is_rejected_with_warning():
    def run(title):
        return _search_run("same query", extra=(
            _step(3, "click", "https://site.test/results", _click_role("link", title)),
        ))
    warnings: list[str] = []
    runs = [
        RunInput(run=1, trajectory=run("first title"), values={"query": "same query"}),
        RunInput(run=2, trajectory=run("second title"), values={"query": "same query"}),
    ]
    out = merge_trajectories(runs, name="s", warnings=warnings)
    (click_edge,) = [t for t in out.workflow.transitions if t.action.type == "click"]
    assert click_edge.action.locator[-1].kwargs["name"] == "first title"  # spine kept
    assert any("targets differ" in w for w in warnings)
    assert any(c.disposition == "target-varies" for c in out.generalized.columns)


def test_single_achieved_run_degrades_to_single_run_compile():
    runs = [
        RunInput(run=1, trajectory=_search_run("cat videos"), values={"query": "cat videos"}),
        RunInput(run=2, trajectory=_traj("failed", [
            _step(0, "goto", "https://site.test/", _goto("https://site.test/")),
        ]), values={"query": "dog videos"}, achieved=False),
    ]
    warnings: list[str] = []
    out = merge_trajectories(runs, name="s", warnings=warnings)
    assert any("only one achieved run" in w for w in warnings)
    (fill_edge,) = [t for t in out.workflow.transitions if t.action.type == "fill"]
    assert fill_edge.action.text == "${query}"  # literal sweep still binds the declared value
    assert out.generalized.achieved_runs == [1]


def test_no_achieved_runs_raises():
    with pytest.raises(ValueError, match="no achieved runs"):
        merge_trajectories([RunInput(run=1, trajectory=_traj("t", []), achieved=False)], name="x")


def test_generalized_round_trips_as_json():
    runs = [
        RunInput(run=1, trajectory=_search_run("a b"), values={"query": "a b"}),
        RunInput(run=2, trajectory=_search_run("c d"), values={"query": "c d"}),
    ]
    out = merge_trajectories(runs, name="s")
    data = out.generalized.model_dump_json()
    back = GeneralizedTrajectory.model_validate_json(data)
    assert back.params[0].name == "query" and back.runs == 2
