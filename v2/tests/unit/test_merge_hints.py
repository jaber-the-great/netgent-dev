"""M3 — the generator consumes plan_next's typed hints ONLY where the recordings prove them
(generator-agent.md §C.4): positional → the structural rung + nth(i) from every run's ladder;
text_contains_param → the role-name rewrite; repeat_fold → contiguous identical presses as
one counted Repeat bound to the planned values; a rejected hint leaves the draft unchanged and
is recorded (generalized.hints) with its reason. Plus the seconds tolerance and the press-key
alignment fix."""

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.generator.hints import GeneralizationHint, RepeatFold, acceptance_rate
from netgent.agent.generator.merge import RunInput, merge_trajectories
from netgent.schema.actions import LocatorStep

SITE = "https://site.test"
STRUCT = "#results > li > a"


def _step(n, kind, url, action, **kw):
    return AgentStep(n=n, kind=kind, reasoning=kw.pop("reasoning", ""), url=url, action=action, **kw)


def _goto():
    return _step(0, "goto", f"{SITE}/", {"type": "goto", "url": f"{SITE}/"})


def _fill(text):
    return _step(1, "fill", f"{SITE}/", {"type": "fill", "locator": [{"fn": "locator", "args": ["#q"]}], "text": text})


def _press(keys="Enter", n=2, url=f"{SITE}/results", sel="#q"):
    return _step(n, "press", url, {"type": "press", "keys": keys, "locator": [{"fn": "locator", "args": [sel]}]})


def _wait(seconds, n=9):
    return _step(n, "wait", f"{SITE}/watch", {"type": "wait", "seconds": seconds})


def _click_first(title, *, index=0, count=3, structural=STRUCT, ladder=True, n=3):
    """The recorded click on a list item: the title-keyed role chain won; the ladder (M0)
    carries the structural rung with the acted element's position."""
    action = {"type": "click", "locator": [{"fn": "get_by_role", "args": ["link"], "kwargs": {"name": title}}]}
    step = _step(n, "click", f"{SITE}/watch", action)
    if ladder:
        step.locator_candidates = [
            [LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": title})],
            [LocatorStep(fn="locator", args=[f"#results > li:nth-of-type({index + 1}) > a"])],
            [LocatorStep(fn="locator", args=[structural])],
        ]
        step.candidate_kinds = ["role", "css", "structural"]
        step.match_counts = [1, 1, count]
        step.match_indices = [None, None, index]
        step.element = {"tag": "a", "role": None, "name": title, "type": None, "frame_path": []}
    return step


def _run(query, title, **click_kw):
    return AgentTrajectory(task=f"search {query} and open the first result", success=True,
                           steps=[_goto(), _fill(query), _press(), _click_first(title, **click_kw)])


def _inputs(a=("kittens", "Cat video A"), b=("puppies", "Dog video A"), a_kw=None, b_kw=None):
    return [
        RunInput(run=1, trajectory=_run(*a, **(a_kw or {})), values={"query": a[0]}),
        RunInput(run=2, trajectory=_run(*b, **(b_kw or {})), values={"query": b[0]}),
    ]


def _fold_repeat(wf):
    """The folded gesture's Repeat (its body is the `_rep` self-loop), or None."""
    return next((n for n in (wf.control or []) if n.kind == "repeat" and n.body[0].edge.endswith("_rep")), None)


# ── positional ────────────────────────────────────────────────────────────────────────────


def test_positional_hint_switches_the_column_to_the_structural_rung_and_nth():
    hint = GeneralizationHint(column=3, intent="positional", why="'the first result'")
    warnings: list[str] = []
    out = merge_trajectories(_inputs(), name="s", warnings=warnings, hints=[hint])
    (click,) = [t for t in out.workflow.transitions if t.action.type == "click"]
    assert [(st.fn, st.args) for st in click.action.locator] == [("locator", [STRUCT]), ("nth", [0])]
    (col,) = [c for c in out.generalized.columns if c.action_type == "click"]
    assert col.disposition == "positional" and col.transition == click.id
    (outcome,) = out.generalized.hints
    assert outcome.status == "applied" and outcome.transition == click.id and STRUCT in outcome.reason
    assert acceptance_rate(out.generalized.hints) == 1.0
    # the state before the click anchors on the positional target — expressible as `css >> nth=0`
    (anchor,) = [c for c in out.workflow.state(click.source).conditions if c.type == "selector_visible"]
    # The anchor carries the chain itself (media-platforms fix), not a rendered selector.
    assert anchor.selector is None
    assert [(st.fn, st.args) for st in anchor.locator] == [("locator", [STRUCT]), ("nth", [0])]
    assert not any("targets differ" in w for w in warnings)


def test_positional_hint_is_rejected_when_the_positions_disagree():
    hint = GeneralizationHint(column=3, intent="positional")
    warnings: list[str] = []
    out = merge_trajectories(_inputs(b_kw={"index": 1}), name="s", warnings=warnings, hints=[hint])
    (click,) = [t for t in out.workflow.transitions if t.action.type == "click"]
    assert click.action.locator[-1].fn == "get_by_role" and click.action.locator[-1].kwargs["name"] == "Cat video A"
    (col,) = [c for c in out.generalized.columns if c.action_type == "click"]
    assert col.disposition == "target-varies"  # the draft is unchanged
    (outcome,) = out.generalized.hints
    assert outcome.status == "rejected" and "different positions" in outcome.reason and "run 2: 1" in outcome.reason
    assert any("hint positional at column 3 rejected" in w for w in warnings)


def test_positional_hint_is_rejected_without_a_recorded_ladder_or_with_differing_rungs():
    no_ladder = merge_trajectories(_inputs(b_kw={"ladder": False}), name="s",
                                   hints=[GeneralizationHint(column=3, intent="positional")])
    (o,) = no_ladder.generalized.hints
    assert o.status == "rejected" and "no structural rung" in o.reason and "run 2" in o.reason
    other_rung = merge_trajectories(_inputs(b_kw={"structural": "#other > li > a"}), name="s",
                                    hints=[GeneralizationHint(column=3, intent="positional")])
    (o,) = other_rung.generalized.hints
    assert o.status == "rejected" and "differs across runs" in o.reason
    few = merge_trajectories(_inputs(b_kw={"count": 0}), name="s",
                             hints=[GeneralizationHint(column=3, intent="positional")])
    (o,) = few.generalized.hints
    assert o.status == "rejected" and "fewer than index" in o.reason


def test_positional_hint_on_a_non_click_or_off_path_column_is_rejected():
    out = merge_trajectories(_inputs(), name="s", hints=[
        GeneralizationHint(column=1, intent="positional"),  # the fill
        GeneralizationHint(column=7, intent="positional"),  # no such column
    ])
    assert [(o.hint.column, o.status) for o in out.generalized.hints] == [(1, "rejected"), (7, "rejected")]
    assert "is a fill" in out.generalized.hints[0].reason
    assert "not a main-path column" in out.generalized.hints[1].reason


# ── text_contains_param / instance ─────────────────────────────────────────────────────────


def test_text_contains_param_hint_applies_the_role_name_rewrite_for_the_named_param():
    runs = _inputs(a=("kittens", "Kittens playing 4K"), b=("puppies", "cute PUPPIES compilation"))
    hint = GeneralizationHint(column=3, intent="text_contains_param", param_name="query")
    out = merge_trajectories(runs, name="s", hints=[hint])
    (click,) = [t for t in out.workflow.transitions if t.action.type == "click"]
    assert click.action.locator[-2].kwargs["name"] == "${query}" and click.action.locator[-1].fn == "nth"
    (o,) = out.generalized.hints
    assert o.status == "applied" and "${query}" in o.reason
    rejected = merge_trajectories(_inputs(), name="s", hints=[hint])  # titles do not contain the queries
    (o,) = rejected.generalized.hints
    assert o.status == "rejected" and "contains" in o.reason
    unnamed = merge_trajectories(runs, name="s", hints=[GeneralizationHint(column=3, intent="text_contains_param")])
    (o,) = unnamed.generalized.hints
    assert o.status == "rejected" and "needs param_name" in o.reason


def test_instance_hint_is_a_recorded_no_op():
    out = merge_trajectories(_inputs(), name="s", hints=[GeneralizationHint(column=3, intent="instance")])
    (o,) = out.generalized.hints
    assert o.status == "applied" and "kept" in o.reason
    (col,) = [c for c in out.generalized.columns if c.action_type == "click"]
    assert col.disposition == "target-varies"


# ── repeat_fold ────────────────────────────────────────────────────────────────────────────


def _seek_run(presses, watch=10.0):
    steps = [_goto(), _fill("q"), _press()]
    n = 3
    for _ in range(presses):
        steps.append(_press("l", n=n, url=f"{SITE}/watch", sel="video"))
        n += 1
    steps.append(_wait(watch, n=n))
    return AgentTrajectory(task="seek", success=True, steps=steps)


def test_repeat_fold_binds_the_press_count_to_the_planned_values_exactly():
    runs = [RunInput(run=1, trajectory=_seek_run(3), values={"presses": "3", "watch": "10"}),
            RunInput(run=2, trajectory=_seek_run(2), values={"presses": "2", "watch": "10"})]
    hint = GeneralizationHint(column=3, repeat_fold=RepeatFold(kind="press", count_param="presses"))
    out = merge_trajectories(runs, name="s", hints=[hint])
    wf = out.workflow
    rep = _fold_repeat(wf)
    assert rep is not None and rep.count == "${presses}" and rep.max_iterations >= 9
    (loop,) = [t for t in wf.transitions if t.id.endswith("_rep")]
    assert loop.source == loop.target and loop.action.type == "press" and loop.action.keys == "l"
    (noop,) = [t for t in wf.transitions if t.action.type == "noop"]
    assert noop.target == loop.source
    (p,) = wf.params
    assert p.name == "presses" and p.default == "3"
    assert out.generalized.params[0].values_by_run == {1: "3", 2: "2"}
    folded = [c for c in out.generalized.columns if c.disposition == "folded"]
    assert [c.index for c in folded] == [3, 4, 5] and all(c.param == "presses" for c in folded)
    (o,) = out.generalized.hints
    assert o.status == "applied" and o.transition == noop.id and "columns 3, 4, 5" in o.reason
    assert not any(t.action.type == "press" and t.action.keys == "l" and not t.id.endswith("_rep")
                   for t in wf.transitions)


def test_repeat_fold_binds_by_a_constant_factor_and_names_the_count_param():
    """Three `l` presses for "fast forward 30s", two for "20s": the counts are the planned
    seconds ÷ 10 in every run, so the artifact's param is the COUNT with the factor recorded."""
    runs = [RunInput(run=1, trajectory=_seek_run(3), values={"fast_forward_seconds": "30s"}),
            RunInput(run=2, trajectory=_seek_run(2), values={"fast_forward_seconds": "20s"})]
    hint = GeneralizationHint(column=4, repeat_fold=RepeatFold(kind="press", count_param="fast_forward_seconds"))
    out = merge_trajectories(runs, name="s", hints=[hint])  # column 4 sits INSIDE the block: it extends both ways
    rep = _fold_repeat(out.workflow)
    assert rep is not None and rep.count == "${fast_forward_seconds_count}"
    (p,) = out.workflow.params
    assert p.name == "fast_forward_seconds_count" and p.default == "3"
    assert "each press ≈ 10 of fast_forward_seconds" in p.description and "run 2: '20s'" in p.description
    assert out.generalized.hints[0].status == "applied"


def test_repeat_fold_is_rejected_when_the_counts_do_not_explain_the_planned_values():
    runs = [RunInput(run=1, trajectory=_seek_run(3), values={"fast_forward_seconds": "30s"}),
            RunInput(run=2, trajectory=_seek_run(2), values={"fast_forward_seconds": "25s"})]
    hint = GeneralizationHint(column=3, repeat_fold=RepeatFold(kind="press", count_param="fast_forward_seconds"))
    warnings: list[str] = []
    out = merge_trajectories(runs, name="s", warnings=warnings, hints=[hint])
    (o,) = out.generalized.hints
    assert o.status == "rejected" and "constant factor" in o.reason
    assert _fold_repeat(out.workflow) is None
    assert any("repeat_fold at column 3 rejected" in w for w in warnings)
    # the block compiled column by column, as without the hint (two shared presses, one run-1-only)
    assert sorted(c.disposition for c in out.generalized.columns[3:6]) == ["aligned", "aligned", "dropped"]


def test_repeat_fold_without_a_param_needs_equal_counts():
    same = [RunInput(run=1, trajectory=_seek_run(2)), RunInput(run=2, trajectory=_seek_run(2))]
    out = merge_trajectories(same, name="s", hints=[GeneralizationHint(column=3, repeat_fold=RepeatFold(kind="press"))])
    rep = _fold_repeat(out.workflow)
    assert rep is not None and rep.count == 2 and out.workflow.params == []
    assert out.generalized.hints[0].status == "applied"
    differ = [RunInput(run=1, trajectory=_seek_run(3)), RunInput(run=2, trajectory=_seek_run(2))]
    out = merge_trajectories(differ, name="s",
                             hints=[GeneralizationHint(column=3, repeat_fold=RepeatFold(kind="press"))])
    assert out.generalized.hints[0].status == "rejected" and "no count_param" in out.generalized.hints[0].reason


def test_repeat_fold_rejects_a_column_that_is_not_the_named_kind():
    runs = [RunInput(run=1, trajectory=_seek_run(3)), RunInput(run=2, trajectory=_seek_run(2))]
    out = merge_trajectories(runs, name="s",
                             hints=[GeneralizationHint(column=1, repeat_fold=RepeatFold(kind="press"))])
    (o,) = out.generalized.hints
    assert o.status == "rejected" and "not a single-signature press column" in o.reason


# ── alignment and the seconds tolerance ────────────────────────────────────────────────────


def test_press_keys_never_substitute_for_each_other():
    """Run 2 mutes (`m`) where run 1 seeks (`l`): two gap columns, not one target-varies press."""
    run1 = AgentTrajectory(task="t", success=True, steps=[_goto(), _press("l", n=1, url=f"{SITE}/", sel="video")])
    run2 = AgentTrajectory(task="t", success=True, steps=[_goto(), _press("m", n=1, url=f"{SITE}/", sel="video")])
    out = merge_trajectories([RunInput(run=1, trajectory=run1), RunInput(run=2, trajectory=run2)], name="t")
    assert [c.disposition for c in out.generalized.columns] == ["aligned", "dropped", "dropped"]


def test_wait_seconds_within_tolerance_of_the_planned_value_bind_approximately():
    def run(seconds):
        return AgentTrajectory(task="w", success=True, steps=[_goto(), _wait(seconds, n=1)])
    warnings: list[str] = []
    out = merge_trajectories([
        RunInput(run=1, trajectory=run(18.0), values={"watch": "20s"}),
        RunInput(run=2, trajectory=run(9.0), values={"watch": "10s"}),
    ], name="w", warnings=warnings)
    (rep,) = [n for n in out.workflow.control if n.kind == "repeat"]
    assert rep.count == "${watch}" and out.generalized.params[0].values_by_run == {1: "20", 2: "10"}
    assert any("approximately" in w for w in warnings)
    far = merge_trajectories([
        RunInput(run=1, trajectory=run(20.0), values={"watch": "20s"}),
        RunInput(run=2, trajectory=run(5.0), values={"watch": "25s"}),  # an ad-wait, not the watch
    ], name="w")
    (col,) = [c for c in far.generalized.columns if c.action_type == "wait"]
    assert col.disposition == "value-diverges" and col.values_by_run == {1: "20.0", 2: "5.0"}
