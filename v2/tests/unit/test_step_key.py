"""G0 — StepKey: a column's durable name (docs/research/generator-agent-v2.md §C.2), measured on
the stored MOP bundle (tests/fixtures/mop): the video-click column is numbered 4/5, then 6, then
7 as runs are added across rounds, while its key stays ``click:get_by_role|link#0``."""

import json
from pathlib import Path

from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator.merge import RunInput, StepKey, merge_trajectories
from netgent.agent.rounds import GeneralizedSummary, RoundRecord
from netgent.agent.triage import Episode, triage

FIX = Path(__file__).parent.parent / "fixtures" / "mop"


def mop_runs(ids: list[int]) -> list[RunInput]:
    out = []
    for k in ids:
        d = FIX / f"run-{k}"
        traj = AgentTrajectory.model_validate(json.loads((d / "trajectory.json").read_text()))
        var = json.loads((d / "variation.json").read_text())
        ver = json.loads((d / "verdict.json").read_text())
        out.append(RunInput(run=k, trajectory=traj, values=var["values"], achieved=ver["achieved"],
                            scoped=var.get("scoped", False)))
    return out


ROUNDS = {1: [1, 2, 3, 4, 5], 2: [1, 2, 3, 4, 5, 6, 7, 8], 3: list(range(1, 14))}


def test_the_video_click_keeps_its_key_while_its_column_index_drifts():
    keys, indices = {}, {}
    for r, ids in ROUNDS.items():
        gen = merge_trajectories(mop_runs(ids), name="mop").generalized
        cols = [c for c in gen.columns if c.action_type == "click" and c.disposition == "target-varies"]
        indices[r] = sorted(c.index for c in cols)
        keys[r] = {c.key for c in cols}
    assert indices == {1: [4, 5], 2: [6], 3: [7]}  # the measured drift (§1.2)
    assert keys[2] == keys[3] == {"click:get_by_role|link#0"}
    assert "click:get_by_role|link#0" in keys[1]  # round 1 had two candidates; the second is #1


def test_keys_are_unique_per_merge_and_off_path_columns_render_apart():
    gen = merge_trajectories(mop_runs(ROUNDS[3]), name="mop").generalized
    assert all(c.key for c in gen.columns)
    assert len({c.key for c in gen.columns}) == len(gen.columns)
    on = [c.key for c in gen.columns if c.transition]
    off = [c.key for c in gen.columns if not c.transition]
    assert all("#" in k for k in on) and all("~" in k for k in off)
    assert StepKey(action="click", shape="get_by_role|link", occurrence=2).render() == "click:get_by_role|link#2"


def test_episodes_and_round_records_carry_the_key():
    runs = mop_runs(ROUNDS[3])
    gen = merge_trajectories(runs, name="mop").generalized
    (pos,) = [e for e in triage(generalized=gen, replay=None, runs=runs) if e.kind == "positional_target"]
    assert pos.column == 7 and pos.key == "click:get_by_role|link#0"
    assert "(key click:get_by_role|link#0)" in pos.as_line()
    rec = RoundRecord(round=3, generalized=GeneralizedSummary.from_generalized(gen))
    assert rec.key_index["click:get_by_role|link#0"] == 7
    assert json.loads(rec.model_dump_json())["key_index"]["click:get_by_role|link#0"] == 7
    assert Episode.model_validate_json(pos.model_dump_json()) == pos
