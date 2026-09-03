"""Triage — one round's evidence (verdicts, the merge's trail, the replay report) → typed Episodes.

The evidence is the trimmed real 3-run Dream Theater bundle (tests/fixtures/dream_theater):
replay 1 (run 1's values) passed; replay 2 (run 2's Metallica values) FAILED@t4 at the
title-keyed "click the first video result" — the known open gap."""

import json
from pathlib import Path

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator.merge import RunInput, merge_trajectories
from netgent.agent.replay import ReplayReport, ReplayRun, replay_run_from_record
from netgent.agent.triage import Episode, triage
from netgent.agent.verifier import Verdict
from netgent.schema.records import RunRecord

FIX = Path(__file__).parent.parent / "fixtures" / "dream_theater"


def _runs() -> tuple[list[RunInput], dict[int, Verdict]]:
    runs, verdicts = [], {}
    for k in (1, 2, 3):
        d = FIX / f"run-{k}"
        traj = AgentTrajectory.model_validate(json.loads((d / "trajectory.json").read_text()))
        var = json.loads((d / "variation.json").read_text())
        ver = json.loads((d / "verdict.json").read_text())
        runs.append(RunInput(run=k, trajectory=traj, values=var["values"], achieved=ver["achieved"]))
        verdicts[k] = Verdict.model_validate(ver["verdict"])
    return runs, verdicts


def _values(gen, rid: int) -> dict[str, str]:
    return {p.name: p.values_by_run[rid] for p in gen.params}


def _replay(gen) -> ReplayReport:
    runs = []
    for i, rid in ((1, 1), (2, 2)):
        record = RunRecord.model_validate(json.loads((FIX / f"replay-{i}" / "record.json").read_text()))
        runs.append(replay_run_from_record(_values(gen, rid), record))
    return ReplayReport(runs=runs, passed=False)


def test_replay_run_from_record_names_the_failed_edge_and_unmet_conjuncts():
    runs, _ = _runs()
    gen = merge_trajectories(runs, name="dt").generalized
    report = _replay(gen)
    ok, failed = report.runs
    assert ok.success and ok.failed_edge is None and "FAILED" not in " ".join(ok.signature)
    assert not failed.success and failed.failed_edge == "t4" and failed.outcome == "action_error"
    assert failed.signature[-1] == "FAILED@t4" and failed.unmet == ["url_matches", "selector_visible"]
    assert failed.values["search_query"] == "Metallica - Master of Puppets"


def test_merge_records_the_evidence_triage_needs():
    runs, _ = _runs()
    gen = merge_trajectories(runs, name="dt").generalized
    (click,) = [c for c in gen.columns if c.disposition == "target-varies" and c.action_type == "click"]
    assert click.transition == "t4" and sorted(click.targets_by_run) == [1, 2, 3]
    assert all(t.startswith("role=link") for t in click.targets_by_run.values())
    # the initial watch: run 2's 5 s ad-wait no longer outbids its 25 s watch (value-aware alignment)
    (watch,) = [c for c in gen.columns if c.param == "initial_watch_seconds"]
    assert watch.disposition == "param" and watch.field == "seconds"
    assert watch.values_by_run == {1: "20.0", 2: "25.0", 3: "15.0"}
    assert sorted(p.name for p in gen.params) == [
        "final_watch_seconds", "initial_watch_seconds", "pause_seconds", "search_query", "second_watch_seconds"]
    off_path = [c for c in gen.columns if c.disposition in ("dropped", "interrupt")]
    assert all(c.transition is None for c in off_path)
    assert not [c for c in gen.columns if c.disposition == "value-diverges"]


def _perturbed(runs: list[RunInput]) -> list[RunInput]:
    """Run 2 planned a 40 s initial watch but waited 25 s: its dwell binds to nothing."""
    out = [r.model_copy(deep=True) for r in runs]
    out[1].values["initial_watch_seconds"] = "40s"
    return out


def test_unbound_value_episode_when_a_dwell_matches_no_planned_value():
    runs, verdicts = _runs()
    gen = merge_trajectories(_perturbed(runs), name="dt").generalized
    (col,) = [c for c in gen.columns if c.disposition == "value-diverges"]
    assert col.action_type == "wait" and col.field == "seconds"
    episodes = triage(generalized=gen, replay=None, runs=_perturbed(runs), verdicts=verdicts)
    (unbound,) = [e for e in episodes if e.kind == "unbound_value"]
    # with nothing to bind run 2's 25 s watch to, its 5 s ad-wait pairs with the others again
    assert unbound.column == col.index and unbound.observed == {1: "20.0", 2: "5.0", 3: "15.0"}
    assert unbound.planned["initial_watch_seconds"] == {1: "20s", 2: "40s", 3: "15s"}


def test_varying_gesture_names_the_seek_block_whose_counts_differ():
    """Three / two / four `l` presses for planned 30s / 20s / 40s fast-forwards: one episode over
    the press block (spanning the stray scroll column), an observation for the generator's prompt."""
    runs, verdicts = _runs()
    gen = merge_trajectories(runs, name="dt").generalized
    episodes = triage(generalized=gen, replay=None, runs=runs, verdicts=verdicts)
    (vg,) = [e for e in episodes if e.kind == "varying_gesture"]
    assert vg.action_type == "press" and vg.observed == {1: "3", 2: "2", 3: "4"}
    assert vg.planned["fast_forward_seconds"] == {1: "30s", 2: "20s", 3: "40s"}
    assert vg.key.startswith("press:") and "differing counts" in vg.detail


def test_triage_on_the_dream_theater_round():
    runs, verdicts = _runs()
    gen = merge_trajectories(runs, name="dt").generalized
    episodes = triage(generalized=gen, replay=_replay(gen), runs=runs, verdicts=verdicts)
    kinds = [e.kind for e in episodes]

    (pos,) = [e for e in episodes if e.kind == "positional_target"]
    assert pos.source == "merge" and pos.action_type == "click" and pos.confirmed_by_replay
    assert pos.transition == "t4" and pos.replay_values["search_query"] == "Metallica - Master of Puppets"
    assert pos.unmet == ["url_matches", "selector_visible"] and sorted(pos.observed) == [1, 2, 3]
    assert "search_query" in pos.planned and pos.planned["search_query"][2] == "Metallica - Master of Puppets"

    assert "unbound_value" not in kinds  # every dwell bound to a planned duration
    assert kinds.count("conditional_step") >= 2  # the k<N dismissal-shaped columns
    assert "flow_drift" not in kinds  # the failed edge's column already carries the positional episode
    assert "unpassable" not in kinds
    (judge,) = [e for e in episodes if e.kind == "judge_unmet"]
    assert judge.runs == [2] and judge.unmet and "skip" in judge.unmet[0].lower()  # run 2's ad-skip caveat
    assert all("positional_target column" in e.as_line() for e in [pos])  # renders for the planner


def test_judge_caveat_is_dropped_when_a_passing_replay_contradicts_it():
    runs, verdicts = _runs()
    gen = merge_trajectories(runs, name="dt").generalized
    passing = ReplayReport(passed=True, runs=[
        ReplayRun(values=_values(gen, 1), success=True, signature=["s1"]),
        ReplayRun(values=_values(gen, 2), success=True, signature=["s1"]),  # run 2's values replayed fine
    ])
    episodes = triage(generalized=gen, replay=passing, runs=runs, verdicts=verdicts)
    assert not [e for e in episodes if e.kind == "judge_unmet"]
    (pos,) = [e for e in episodes if e.kind == "positional_target"]
    assert not pos.confirmed_by_replay  # merge evidence stands on its own, unconfirmed


def test_flow_drift_is_emitted_for_a_failed_edge_with_no_more_specific_episode():
    runs, verdicts = _runs()
    gen = merge_trajectories(runs, name="dt").generalized
    drifted = ReplayReport(passed=False, runs=[ReplayRun(
        values=_values(gen, 1), success=False, signature=["s1", "FAILED@t2"], failed_edge="t2",
        outcome="trigger_timeout", unmet=["selector_visible"], error="state 's2' not recognized",
    )])
    episodes = triage(generalized=gen, replay=drifted, runs=runs, verdicts=verdicts)
    (drift,) = [e for e in episodes if e.kind == "flow_drift"]
    assert drift.source == "replay" and drift.transition == "t2" and drift.unmet == ["selector_visible"]
    assert drift.column == next(c.index for c in gen.columns if c.transition == "t2") and drift.action_type == "fill"


def test_no_achieved_run_is_one_unpassable_episode():
    runs, verdicts = _runs()
    failed = [r.model_copy(update={"achieved": False}) for r in runs]
    gen = merge_trajectories(runs, name="dt").generalized  # the trail from the runs as they were
    episodes = triage(generalized=gen, replay=None, runs=failed,
                      verdicts={k: Verdict(achieved=False, unmet=["never played"]) for k in (1, 2, 3)})
    (ep,) = episodes
    assert ep.kind == "unpassable" and ep.runs == [1, 2, 3] and ep.unmet == ["never played"]


def test_episode_round_trips_as_json():
    ep = Episode(kind="unbound_value", source="merge", column=10, field="seconds", observed={1: "20.0"})
    assert Episode.model_validate_json(ep.model_dump_json()) == ep
