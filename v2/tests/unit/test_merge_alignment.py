"""Merge alignment rules measured on the YouTube 3-run merge: a press IS its key (`l` and `m`
never substitute for each other), and a dwell within ±25 % (≥ 2 s) of the planned duration still
binds. (The typed-hint tests that used to live beside these went with hints.py: generalization
is the generator agent's job now — tests/unit/test_materialize.py.)"""

from netgent.agent.explorer.models import AgentStep, AgentTrajectory
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
