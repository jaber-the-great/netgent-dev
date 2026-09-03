"""G1–G3 — the materializer against the stored MOP bundle (tests/fixtures/mop), no key, no browser
(docs/research/generator-agent-v2.md build order). A hand-written WorkflowDraft — a test fixture for
the resolver, not a workflow — must yield: the video click on the container-relative rung + nth(0);
the fast-forward presses folded into ONE Repeat whose count derives from fast_forward_time via the
media readings; the three run-12 false-positive interrupts refused by I3; a non-empty accept set.
An empty main falls back to the merge's artifact byte-for-byte."""

import json
from pathlib import Path

import pytest

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator.context import GeneratorContext
from netgent.agent.generator.draft import (
    CountSpec,
    DraftCondition,
    DraftEdge,
    DraftInterrupt,
    DraftParam,
    DraftRepeat,
    ExcludedRun,
    LocatorRef,
    ParamWitness,
    WorkflowDraft,
)
from netgent.agent.generator.evidence import seek_between
from netgent.agent.generator.materialize import materialize
from netgent.agent.generator.merge import RunInput, merge_trajectories
from netgent.agent.generator.models import acceptance_rate
from netgent.schema.workflow import resolve_params

FIX = Path(__file__).parent.parent / "fixtures" / "mop"
TASK = json.loads((FIX / "context.json").read_text())["task"]
KEPT = [1, 2, 4, 6, 7, 10, 11]  # run 12 restarted the whole flow from YouTube Home (r12.s17.0)


def mop_runs() -> list[RunInput]:
    out = []
    for k in range(1, 14):
        d = FIX / f"run-{k}"
        traj = AgentTrajectory.model_validate(json.loads((d / "trajectory.json").read_text()))
        var = json.loads((d / "variation.json").read_text())
        ver = json.loads((d / "verdict.json").read_text())
        out.append(RunInput(run=k, trajectory=traj, values=var["values"], achieved=ver["achieved"],
                            scoped=var.get("scoped", False)))
    return out


@pytest.fixture(scope="module")
def ctx() -> GeneratorContext:
    runs = mop_runs()
    merged = merge_trajectories(runs, name="mop")
    return GeneratorContext(task=TASK, url="https://www.youtube.com", name="mop", runs=tuple(runs),
                            generalized=merged.generalized, fallback=merged.workflow)


# The same real step in every kept run, by inspection of the recordings (the ladder lines).
SEARCH_FILL = {1: "r1.s1.0", 2: "r2.s1.0", 4: "r4.s1.0", 6: "r6.s1.0", 7: "r7.s1.0", 10: "r10.s1.0", 11: "r11.s1.0"}
SEARCH_SUBMIT = {1: "r1.s2.0", 2: "r2.s2.0", 4: "r4.s2.0", 6: "r6.s2.0", 7: "r7.s2.0", 10: "r10.s2.0", 11: "r11.s2.0"}
VIDEO_CLICK = {1: "r1.s4.0", 2: "r2.s4.0", 4: "r4.s4.0", 6: "r6.s4.0", 7: "r7.s4.0", 10: "r10.s4.0", 11: "r11.s4.0"}
FIRST_WATCH = {1: "r1.s9.0", 2: "r2.s7.0", 4: "r4.s8.0", 6: "r6.s7.0", 7: "r7.s7.0", 10: "r10.s7.0", 11: "r11.s8.0"}
PRESSES = {1: ["r1.s10.0", "r1.s11.0", "r1.s12.0", "r1.s13.0"], 2: ["r2.s9.0", "r2.s10.0", "r2.s11.0", "r2.s12.0"],
           4: ["r4.s9.0", "r4.s10.0", "r4.s11.0"], 6: ["r6.s8.0", "r6.s9.0", "r6.s10.0"],
           7: ["r7.s9.0", "r7.s10.0", "r7.s11.0", "r7.s12.0", "r7.s13.0"],
           10: ["r10.s9.0", "r10.s10.0", "r10.s11.0", "r10.s12.0"],
           11: ["r11.s9.0", "r11.s10.0", "r11.s11.0", "r11.s12.0"]}
SECOND_WATCH = {1: "r1.s14.0", 2: "r2.s13.0", 4: "r4.s12.0", 6: "r6.s11.0", 7: "r7.s14.0", 10: "r10.s13.0",
                11: "r11.s13.0"}


def _others(d: dict[int, str]) -> list[str]:
    return [v for k, v in d.items() if k != 1]


def mop_draft(**over) -> WorkflowDraft:
    draft = dict(
        spine=1, kept_runs=KEPT,
        excluded=[ExcludedRun(run=12, reason="restarted", evidence="r12.s17.0",
                              why="'I'll click YouTube Home to restart' — redid the whole flow")],
        params=[
            DraftParam(name="video_query", witnesses=[ParamWitness(step=SEARCH_FILL[k], field="text", literal=q)
                                                       for k, q in [(1, "Metallica - Master of Puppets"),
                                                                    (2, "Queen - Bohemian Rhapsody"),
                                                                    (4, "AC/DC - Thunderstruck")]]),
            DraftParam(name="initial_watch_time", witnesses=[
                ParamWitness(step=FIRST_WATCH[1], field="seconds", literal="15"),
                ParamWitness(step=FIRST_WATCH[2], field="seconds", literal="10")]),
            DraftParam(name="second_watch_time", witnesses=[
                ParamWitness(step=SECOND_WATCH[1], field="seconds", literal="20")]),
            DraftParam(name="fast_forward_time", witnesses=[
                ParamWitness(step="r1.s10.0", field="media_jump", literal="10")],
                why="the seek key adds 10s per press; fast_forward_time is the total"),
            DraftParam(name="fast_forward_presses", kind="derived", derived_from="fast_forward_time", divide_by=10,
                       rounding="ceil", why="one 'l' press = +10s, read off the media lines"),
        ],
        main=[
            DraftEdge(step="r1.s0.0",
                      corroborated_by=["r2.s0.0", "r4.s0.0", "r6.s0.0", "r7.s0.0", "r10.s0.0", "r11.s0.0"]),
            DraftEdge(step=SEARCH_FILL[1], value_param="video_query", corroborated_by=_others(SEARCH_FILL)),
            DraftEdge(step=SEARCH_SUBMIT[1], corroborated_by=_others(SEARCH_SUBMIT)),
            DraftEdge(step=VIDEO_CLICK[1], target=LocatorRef(step=VIDEO_CLICK[1], rung=2, nth=0),
                      corroborated_by=_others(VIDEO_CLICK), why="'the first video that pops up' is a position"),
            DraftEdge(step=FIRST_WATCH[1], value_param="initial_watch_time", corroborated_by=_others(FIRST_WATCH)),
            DraftRepeat(body=[DraftEdge(step="r1.s10.0")], count=CountSpec(param="fast_forward_presses"),
                        covers=[r for refs in PRESSES.values() for r in refs],
                        why="fast-forward for ${fast_forward_time}: each 'l' seeks +10s"),
            DraftEdge(step=SECOND_WATCH[1], value_param="second_watch_time", corroborated_by=_others(SECOND_WATCH)),
        ],
        interrupts=[
            DraftInterrupt(step="r1.s8.0",
                           also_seen=["r2.s8.0", "r4.s7.0", "r6.s6.0", "r7.s8.0", "r10.s8.0", "r11.s7.0"],
                           why="'No thanks' dismisses the Premium prompt — 'If at any point any pop-ups happen "
                               "dismiss them'"),
            DraftInterrupt(step="r1.s7.0", also_seen=["r10.s6.0"], why="'If an ad is shown skip the ad'"),
        ],
        accept=[DraftCondition(type="url_matches", witness=SECOND_WATCH[1], why="the task ends on the watch page"),
                DraftCondition(type="media_playing", witness=SECOND_WATCH[1],
                               why="'watch for 20s' — the content must be playing at the end")],
    )
    draft.update(over)
    return WorkflowDraft(**draft)


def test_the_measured_seek_step_is_ten_seconds_on_the_mop_recordings(ctx):
    seeks = []
    for r in ctx.achieved():
        steps = [s for s in r.trajectory.steps if s.action is not None and s.error is None]
        for a, b in zip(steps, steps[1:], strict=False):
            if a.action.type == "press" and a.action.keys == "l" and (v := seek_between(a, b)) is not None:
                seeks.append(v)
    assert len(seeks) >= 20
    import statistics
    assert 8.5 <= statistics.median(seeks) <= 11.5, seeks


def test_hand_written_draft_yields_a_positional_click_a_derived_fold_and_an_accept_state(ctx):
    out = materialize(mop_draft(), ctx)
    wf = out.workflow
    assert not out.used_fallback and out.validated, out.warnings
    rejected = [o for o in out.outcomes if o.status == "rejected"]
    assert rejected == [], [f"{o.item}: {o.reason}" for o in rejected]
    # the positional click: the container-relative rung + nth(0), the same in every kept run (M6)
    (click,) = [t for t in wf.transitions if t.action.type == "click" and not t.id.startswith("ti")
                and t.action.locator[-1].fn == "nth"]
    assert [(st.fn, st.args) for st in click.action.locator] == [
        ("locator", ["#dismissible > div > div a#video-title"]), ("nth", [0])]
    assert click.id == "t4"
    # the state before it anchors on that chain, not on a title
    (anchor,) = [c for c in wf.state(click.source).conditions if c.type == "selector_visible"]
    assert anchor.locator[-1].fn == "nth"
    # the fast-forward: ONE Repeat, count derived from fast_forward_time (M10/M11, §D)
    (rep,) = [n for n in wf.control if n.kind == "repeat" and n.body[0].edge.endswith("_rep")]
    assert rep.count == "${fast_forward_presses}" and rep.max_iterations == 15  # max(10, 3 × 5)
    (derived,) = [p for p in wf.params if p.derive is not None]
    assert derived.name == "fast_forward_presses" and derived.derive.from_param == "fast_forward_time"
    assert derived.derive.divide_by == 10 and derived.derive.rounding == "ceil" and not derived.required
    assert {p.name for p in wf.params} == {"video_query", "initial_watch_time", "second_watch_time",
                                           "fast_forward_time", "fast_forward_presses"}
    assert next(p for p in wf.params if p.name == "fast_forward_time").default == "30s"
    # the artifact's knob is the task's knob: 35 s → 4 presses, 30 s → 3
    assert resolve_params(wf, {"fast_forward_time": "35"}).control[rep_index(wf)].count == "4"
    assert resolve_params(wf, {}).control[rep_index(wf)].count == "3"
    # the query and the dwells are bound
    (fill,) = [t for t in wf.transitions if t.action.type == "fill"]
    assert fill.action.text == "${video_query}"
    dwells = [n for n in wf.control if n.kind == "repeat" and n.body[0].edge.endswith("_dwell")]
    assert [d.count for d in dwells] == ["${initial_watch_time}", "${second_watch_time}"]
    # interrupts: No thanks (support 7) and Skip ad (support 2), nothing else
    assert [i.id for i in wf.interrupts] == ["int1", "int2"]
    names = [wf.transition(i.resolve[0]).action.locator[-1].kwargs["name"] for i in wf.interrupts]
    assert names == ["No thanks", "Skip ad"]
    assert all(i.resolve_timeout_ms == 2000 for i in wf.interrupts)
    # accept: the final state carries url_matches ^watch + media_playing
    assert wf.accept_states == [wf.states[-1 - 2 * len(wf.interrupts)].id] or wf.accept_states
    final = wf.state(wf.accept_states[0])
    assert {c.type for c in final.conditions} >= {"url_matches", "media_playing"}
    (url,) = [c for c in final.conditions if c.type == "url_matches"]
    assert url.pattern == "^https://www\\.youtube\\.com/watch"
    (media,) = [c for c in final.conditions if c.type == "media_playing"]
    assert media.min_duration_s == 102.0  # the phase gate; the accept defers to it
    assert media.min_position_s == "${fast_forward_time}" and final.timeout_ms == 2000  # the goal gate (below)
    assert acceptance_rate(out.outcomes) == 1.0 or all(o.status in ("applied", "degraded") for o in out.outcomes)
    # provenance: every main node landed on a transition
    landed = {o.transition for o in out.outcomes if o.item.startswith("main[") and "." not in o.item}
    assert landed >= {"t1", "t2", "t3", "t4"}


def rep_index(wf) -> int:
    return next(i for i, n in enumerate(wf.control) if n.kind == "repeat" and n.body[0].edge.endswith("_rep"))


def test_the_three_run_12_false_positives_are_refused_by_i3(ctx):
    """YouTube Home (/watch → /), the Blinding Lights link (/results → /watch) and the search-submit
    button (/ → /results) all changed the base URL: navigations, not dismissals."""
    draft = mop_draft(kept_runs=[*KEPT, 12], excluded=[], interrupts=[
        DraftInterrupt(step="r12.s17.0", why="pop-up"),
        DraftInterrupt(step="r12.s20.0", why="pop-up"),
        DraftInterrupt(step="r12.s18.0", why="pop-up"),
        DraftInterrupt(step="r1.s8.0", also_seen=["r2.s8.0"], why="'No thanks'"),
    ])
    out = materialize(draft, ctx)
    reasons = {o.ref: o.reason for o in out.outcomes if o.item.startswith("interrupts[") and o.status == "rejected"}
    assert set(reasons) == {"r12.s17.0", "r12.s20.0", "r12.s18.0"}
    assert all("changed the page's base URL" in r for r in reasons.values()), reasons
    assert [i.id for i in out.workflow.interrupts] == ["int1"]


def test_interrupts_on_the_main_path_and_beyond_the_cap_are_refused(ctx):
    draft = mop_draft(interrupts=[
        DraftInterrupt(step="r1.s3.0", why="the search button again"),  # its target IS the main-path submit
        DraftInterrupt(step="r1.s8.0", also_seen=["r2.s8.0"], why="'No thanks'"),
        DraftInterrupt(step="r1.s7.0", why="skip ad"),  # support 1 — the task names ads, so I5 admits it
        DraftInterrupt(step="r2.s5.0", why="the play button"),  # a player control, support 1, no dismissal text
    ])
    out = materialize(draft, ctx)
    by_ref = {o.ref: o for o in out.outcomes if o.item.startswith("interrupts[")}
    assert by_ref["r1.s3.0"].status == "rejected" and "main path" in by_ref["r1.s3.0"].reason
    assert by_ref["r2.s5.0"].status == "rejected" and "one run only" in by_ref["r2.s5.0"].reason
    assert by_ref["r1.s7.0"].status == "applied" and by_ref["r1.s8.0"].status == "applied"


def test_positional_target_is_rejected_when_the_recordings_disagree(ctx):
    bad = mop_draft()
    bad.main[3].target = LocatorRef(step=VIDEO_CLICK[1], rung=2, nth=1)  # nobody acted on index 1
    out = materialize(bad, ctx)
    (t,) = [o for o in out.outcomes if o.item == "main[3].target"]
    assert t.status == "rejected" and "sat at index 0, not 1" in t.reason
    (click,) = [tr for tr in out.workflow.transitions if tr.id == "t4"]
    assert click.action.locator[-1].fn == "get_by_role"  # the recorded chain, unchanged
    role_rung = mop_draft()
    role_rung.main[3].target = LocatorRef(step=VIDEO_CLICK[1], rung=1, nth=0)
    (t,) = [o for o in materialize(role_rung, ctx).outcomes if o.item == "main[3].target"]
    assert t.status == "rejected" and "structural" in t.reason
    missing = mop_draft()
    missing.main[3].target = LocatorRef(step=VIDEO_CLICK[1], rung=7, nth=0)
    (t,) = [o for o in materialize(missing, ctx).outcomes if o.item == "main[3].target"]
    assert t.status == "rejected" and "was not recorded" in t.reason


def test_a_derived_param_whose_unit_the_readings_contradict_is_rejected_and_the_fold_unrolls(ctx):
    draft = mop_draft()
    draft.params[4].divide_by = 25
    out = materialize(draft, ctx)
    (fold,) = [o for o in out.outcomes if o.item == "main[5]"]
    assert fold.status == "rejected" and "median measured jump" in fold.reason and "not 25" in fold.reason
    assert not [n for n in out.workflow.control if n.kind == "repeat" and n.body[0].edge.endswith("_rep")]
    presses = [t for t in out.workflow.transitions if t.action.type == "press"]
    assert len(presses) == 4  # run 1's four presses, as today
    assert not [p for p in out.workflow.params if p.derive is not None]
    assert not out.used_fallback  # one rejected region, the rest of the draft stands


def test_params_need_verified_witnesses_with_provenance(ctx):
    draft = mop_draft()
    draft.params[0].witnesses = [ParamWitness(step=SEARCH_FILL[1], field="text", literal="Nirvana")]
    draft.params[1].witnesses = [ParamWitness(step=FIRST_WATCH[1], field="seconds", literal="99")]
    out = materialize(draft, ctx)
    rej = {o.item: o.reason for o in out.outcomes if o.status == "rejected"}
    assert "does not appear in the recorded text" in rej["params[0]"]
    assert "is not the recorded 15s" in rej["params[1]"]
    assert "not an accepted user param" in rej["main[1].value_param"]
    (fill,) = [t for t in out.workflow.transitions if t.action.type == "fill"]
    assert fill.action.text == "Metallica - Master of Puppets"  # the literal, unchanged
    assert {p.name for p in out.workflow.params} == {"second_watch_time", "fast_forward_time", "fast_forward_presses"}


def test_the_accept_state_asserts_the_seek_the_recordings_witnessed_within_the_settle_budget(ctx):
    """The goal gate: `url_matches ^/watch + media_playing(min_duration_s)` proves the video is playing,
    not that the seek happened (run-60s-mine: the playhead went 0:12 → 1:16 across six presses — that
    is the fact to check). The accept state's media_playing gains min_position_s = ${fast_forward_time}
    — the seek knob, what the presses alone must have produced; the dwells are NOT added, since the
    state is entered before the last dwell and dwell time is exactly what polling accrues — set only
    because every kept run's playhead on entering the accept state (103 / 136 / 105 / 79 / 154 / 113 /
    113 s) is past its own seek. The state's timeout drops to the 2 s settle budget: a one-press
    replay of a 60 s seek passed the first version of this gate after 56 s of polling."""
    out = materialize(mop_draft(), ctx)
    wf = out.workflow
    final = wf.state(wf.accept_states[0])
    (media,) = [c for c in final.conditions if c.type == "media_playing"]
    assert media.min_position_s == "${fast_forward_time}"
    assert final.timeout_ms == 2000
    assert final.id == wf.transition("t7").target  # entered by t7, before the second dwell's self-loop
    assert [p.name for p in wf.params if p.derive is not None] == ["fast_forward_presses"]  # no derived sum
    (gate,) = [o for o in out.outcomes if o.item == "accept.position"]
    assert gate.status == "degraded" and "run 1: 103s ≥ 30s" in gate.reason and "run 7: 154s ≥ 50s" in gate.reason
    assert not [w for w in out.warnings if "media position" in w]
    # zero-LLM resolution: the reference becomes the number the executor compares the playhead to,
    # with the same unit coercion a Repeat count gets
    def floor(values):
        st = resolve_params(wf, values).state(wf.accept_states[0])
        return next(c.min_position_s for c in st.conditions if c.type == "media_playing")
    assert floor({}) == "30s"
    assert floor({"fast_forward_time": "60s"}) == "60s"
    assert floor({"fast_forward_time": "1m"}) == "1m"
    # the other phase gates carry no position and keep their ad-tolerant timeouts: only the accept
    # state asserts the goal, and only it is recognized within the settle budget
    for st in wf.states:
        for c in st.conditions:
            if c.type == "media_playing" and st.id != final.id:
                assert c.min_position_s is None and st.timeout_ms >= 130_000


def _ctx_with_values(base: GeneratorContext, run: int, **values) -> GeneratorContext:
    runs = [r.model_copy(update={"values": {**r.values, **values}}) if r.run == run else r for r in base.runs]
    return GeneratorContext(task=base.task, url=base.url, name=base.name, runs=tuple(runs),
                            generalized=base.generalized, fallback=base.fallback)


def test_the_goal_gate_is_witnessed_never_asserted_from_the_task_text(ctx):
    """A run whose declared seek (500 s) its playhead on entering the accept state (103 s) contradicts
    leaves no witnessed seek knob: `not-validated (media position)`, no floor, the state's timeout
    untouched; the url/media accept still stands."""
    out = materialize(mop_draft(), _ctx_with_values(ctx, 1, fast_forward_time="500s"))
    final = out.workflow.state(out.workflow.accept_states[0])
    (media,) = [c for c in final.conditions if c.type == "media_playing"]
    assert media.min_position_s is None and final.timeout_ms >= 130_000
    assert not [o for o in out.outcomes if o.item == "accept.position"]
    assert any(w.startswith("not-validated (media position)") and "run 1: 103s" in w for w in out.warnings)
    assert out.validated  # the url/media accept stands; only the goal gate is missing
    # without a derived fold there is no seek knob to gate on
    draft = mop_draft()
    draft.params[4].divide_by = 25  # M10 rejects the derived count; the fold unrolls
    out = materialize(draft, ctx)
    final = out.workflow.state(out.workflow.accept_states[0])
    assert all(c.min_position_s is None for c in final.conditions if c.type == "media_playing")
    assert any("no seek knob" in w for w in out.warnings)
