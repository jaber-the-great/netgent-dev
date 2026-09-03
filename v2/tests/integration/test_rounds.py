"""The closed loop end to end on local fixtures with a scripted LLM (M4 acceptance, now through the
generator agent): a results list whose "first item" differs between two queries → round 1's
generator gets no draft (the merge's title-keyed artifact is the fallback) → the replay fails at
the title-keyed click (the Metallica gap) → triage names it positional → plan_next (scripted)
proposes one more variation → round 2 re-merges all three runs and the generator's scripted
draft points the click at the STRUCTURAL rung + nth(0); materialize re-derives it from every
run's recorded ladder, and the replay passes on both unseen value sets. Zero LLM at replay by
construction: FakeLLM raises once its script is exhausted."""

import asyncio
import json
import re

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.generator.draft import (
    DraftCondition,
    DraftEdge,
    DraftParam,
    LocatorRef,
    ParamWitness,
    WorkflowDraft,
)
from netgent.agent.orchestrator import GenerateRequest, orchestrate, select_replay_sets
from netgent.agent.planner import NextRoundPlan, TaskVariation, VariationPlan
from netgent.agent.rounds import RoundContext
from netgent.agent.verifier import Verdict

HOME = """<!doctype html><html><head><title>Tube</title></head><body>
<form action="/results" method="get"><input id="q" name="q" placeholder="search"></form>
</body></html>"""

# The results depend on the query: "kittens" lists cat videos, anything else dog videos —
# so a title-keyed locator captured on run 1 cannot replay for run 2's query.
RESULTS = """<!doctype html><html><head><title>Results</title></head><body>
<h1>Results</h1>
<ul id="results"></ul>
<script>
  const q = new URLSearchParams(location.search).get('q') || '';
  const items = q === 'kittens' ? ['Cat video A', 'Cat video B'] : ['Dog video A', 'Dog video B'];
  const ul = document.getElementById('results');
  items.forEach((t, i) => { const li = document.createElement('li'); const a = document.createElement('a');
    a.href = '/watch-' + (i === 0 ? 'first' : 'second'); a.textContent = t; li.appendChild(a); ul.appendChild(li); });
</script>
</body></html>"""

WATCH = """<!doctype html><html><head><title>Now playing</title></head><body>
<h1>Now playing</h1><p>the first result is playing</p><button id="pause">Pause</button>
</body></html>"""


def _run_script(query):
    return [
        AgentDecision(reasoning="type the query", kind="fill", index=0, text=query),
        AgentDecision(reasoning="submit", kind="press", index=0, keys="Enter"),
        AgentDecision(reasoning="open the first result", kind="click", index=0),
        AgentDecision(reasoning="the first result is playing", done=True, success=True),
    ]


def _task(query):
    return f"search for {query} and play the first result"


def _round1_plan():
    return VariationPlan(variations=[
        TaskVariation(task_text=_task("kittens"), values={"query": "kittens"}),
        TaskVariation(task_text=_task("puppies"), values={"query": "puppies"}),
    ])


def _next_plan():
    return NextRoundPlan(
        next_variations=[TaskVariation(task_text=_task("parrots"), values={"query": "parrots"})],
        notes=["run 2's replay failed at the title-keyed click; the task says 'the first result'"],
    )


def _positional_draft(content: list[dict]) -> WorkflowDraft:
    """The round-2 draft, as the agent would write it from the rendered evidence: the click's
    structural rung is read off its ladder line (`N:structural(2@0)`), never assumed."""
    text = content[0]["text"]
    line = next(ln for ln in text.splitlines() if ln.startswith("r1.s3.0"))
    rung = int(re.search(r"(\d+):structural\(", line).group(1))
    queries = {1: "kittens", 2: "puppies", 3: "parrots"}
    return WorkflowDraft(
        spine=1, kept_runs=[1, 2, 3],
        params=[DraftParam(name="query", witnesses=[
            ParamWitness(step=f"r{k}.s1.0", field="text", literal=q) for k, q in queries.items()])],
        main=[
            DraftEdge(step="r1.s0.0", corroborated_by=["r2.s0.0", "r3.s0.0"]),
            DraftEdge(step="r1.s1.0", value_param="query", corroborated_by=["r2.s1.0", "r3.s1.0"]),
            DraftEdge(step="r1.s2.0", corroborated_by=["r2.s2.0", "r3.s2.0"]),
            DraftEdge(step="r1.s3.0", target=LocatorRef(step="r1.s3.0", rung=rung, nth=0),
                      corroborated_by=["r2.s3.0", "r3.s3.0"], why="'the first result' is a position"),
        ],
        accept=[DraftCondition(type="url_matches", witness="r1.s3.0", why="the task ends on the watch page")],
    )


def test_round_two_turns_the_first_result_click_positional_and_passes(serve, tmp_path):
    srv = serve({"/": HOME, "/results": RESULTS, "/watch-first": WATCH, "/watch-second": WATCH})
    ok = Verdict(achieved=True, confidence="high")
    # judge() is consumed in order: round-1 plan, run 1's verdict, run 2's verdict, plan_next, run 3's verdict;
    # the generator's drafts separately: none in round 1 (the merge's artifact), the positional one in round 2.
    llm = FakeLLM(_run_script("kittens") + _run_script("puppies") + _run_script("parrots"),
                  verdicts=[_round1_plan(), ok, ok, _next_plan(), ok], drafts=[None, _positional_draft])
    events: list[tuple[str, str]] = []
    req = GenerateRequest(task=_task("kittens"), url=srv.url("/"), name="tube", out=tmp_path / "tube.yaml",
                          runs=2, max_rounds=3, allow_kinds=["press"])
    result = asyncio.run(orchestrate(req, llm, lambda s, t: events.append((s, t))))

    assert result.error is None, result.error
    assert result.rounds == 2
    ctx: RoundContext = result.context
    r1, r2 = ctx.rounds
    # round 1: no draft arrived → the merge's title-keyed artifact; the Dog replay failed at it; triage saw why
    assert [r.run for r in r1.runs] == [1, 2] and all(r.achieved for r in r1.runs)
    assert r1.used_fallback and r1.draft_outcomes == [] and r1.draft_acceptance_rate is None
    assert not r1.replay_passed and r1.unseen_passed == 0
    (failed,) = [r for r in r1.replay if not r.success]
    assert failed.values == {"query": "puppies"} and failed.failed_edge is not None
    (pos,) = [e for e in r1.episodes if e.kind == "positional_target"]
    assert pos.column == 3 and pos.key == "click:get_by_role|link#0" and pos.confirmed_by_replay
    assert pos.replay_values == {"query": "puppies"}
    assert r1.next_plan is not None and r1.exit == ""
    # round 2: one more run; the draft materialized (every item applied), the click positional, both unseen passed
    assert [r.run for r in r2.runs] == [3] and r2.runs[0].values == {"query": "parrots"}
    assert r2.generalized is not None and r2.generalized.achieved_runs == [1, 2, 3]
    assert not r2.used_fallback and r2.draft_acceptance_rate == 1.0 and r2.repairs_used == 0 and r2.validated
    (target,) = [o for o in r2.draft_outcomes if o.item == "main[3].target"]
    assert target.status == "applied" and "#results > li > a" in target.reason and target.transition == "t4"
    assert r2.key_index["click:get_by_role|link#0"] == 3
    assert r2.replay_passed and r2.unseen_passed == 2 and r2.exit == "passed"
    assert [r.values for r in r2.replay][0] == {"query": "kittens"}  # defaults first
    assert {tuple(r.values.items()) for r in r2.replay[1:]} == {(("query", "puppies"),), (("query", "parrots"),)}
    # the artifact: the click is the structural rung + nth(0); the query is a param; the watch page is the accept
    wf = result.workflow
    (click,) = [t for t in wf.transitions if t.action.type == "click"]
    assert [(st.fn, st.args) for st in click.action.locator] == [("locator", ["#results > li > a"]), ("nth", [0])]
    assert [p.name for p in wf.params] == ["query"]
    assert wf.accept_states == [click.target]
    (url,) = [c for c in wf.state(click.target).conditions if c.type == "url_matches"]  # one, not a duplicate
    assert url.pattern.endswith("/watch\\-first")
    assert result.replay.passed and len(result.replay.runs) == 3
    # the generator saw the evidence with references on every line, and the round-1 replay + episodes
    assert len(llm.drafted) == 2
    round2_prompt = llm.drafted[1][0]["text"]
    assert "r3.s3.0" in round2_prompt and "positional_target column 3" in round2_prompt
    assert "FAILED at t4" in round2_prompt and "round 1: no draft arrived" in round2_prompt
    # per-run usage is recorded even for a seam that does not count (FakeLLM: None), per run
    assert [r["run"] for r in result.run_reports] == [1, 2, 3] and all("usage" in r for r in result.run_reports)
    # the store: rounds persisted, context.json round-trips, usage.json per run, the draft per round
    store = tmp_path / "tube.trajectories"
    for k in (1, 2, 3):
        assert (store / f"run-{k}" / "trajectory.json").is_file() and (store / f"run-{k}" / "usage.json").is_file()
        var = json.loads((store / f"run-{k}" / "variation.json").read_text())
        assert var["round"] == (1 if k < 3 else 2) and var["scoped"] is False
    for r in (1, 2):
        assert (store / f"round-{r}" / "generalized.json").is_file()
        assert (store / f"round-{r}" / "episodes.json").is_file()
        assert (store / f"round-{r}" / "draft.json").is_file()
    draft2 = json.loads((store / "round-2" / "draft.json").read_text())
    assert draft2["draft"]["main"][3]["target"]["nth"] == 0 and "workflow" not in draft2
    assert (store / "round-1" / "next_plan.json").is_file() and not (store / "round-2" / "next_plan.json").exists()
    assert (store / "round-2" / "replay-1" / "record.json").is_file()
    back = RoundContext.model_validate_json((store / "context.json").read_text())
    assert back == ctx
    stages = [s for s, _ in events]
    assert stages.count("round") == 2 and "triage" in stages and "generate" in stages
    assert stages.index("merge") < stages.index("generate") < stages.index("replay")
    assert stages.index("triage") < stages.index("round", 1)  # triage before round 2 was announced


def test_round_budget_ends_the_loop_honestly(serve, tmp_path):
    """--rounds 1: the failed replay is reported, plan_next never runs, the artifact is kept."""
    srv = serve({"/": HOME, "/results": RESULTS, "/watch-first": WATCH, "/watch-second": WATCH})
    ok = Verdict(achieved=True, confidence="high")
    llm = FakeLLM(_run_script("kittens") + _run_script("puppies"), verdicts=[_round1_plan(), ok, ok])
    req = GenerateRequest(task=_task("kittens"), url=srv.url("/"), name="tube", out=tmp_path / "tube.yaml",
                          runs=2, max_rounds=1, allow_kinds=["press"])
    result = asyncio.run(orchestrate(req, llm))
    assert result.error and "after 1 round(s)" in result.error
    assert result.rounds == 1 and result.context.rounds[0].exit == "max_rounds"
    assert result.workflow is not None and (tmp_path / "tube.yaml").is_file()
    assert [e.kind for e in result.episodes] == ["positional_target"]
    assert len(llm.judged) == 3 and len(llm.drafted) == 1  # no plan_next call; one (empty) draft call


def test_select_replay_sets_prefers_failed_then_newest_unseen():
    from netgent.agent.generator.merge import GeneralizedTrajectory, ParamReport
    from netgent.schema.workflow import Param, State, Workflow

    wf = Workflow(name="w", start_state="init", states=[State(id="init")], transitions=[],
                  params=[Param(name="q", default="a")])
    gen = GeneralizedTrajectory(task="t", runs=4, achieved_runs=[1, 2, 3, 4], params=[
        ParamReport(name="q", default="a", values_by_run={1: "a", 2: "b", 3: "c", 4: "d"})])
    sets = select_replay_sets(wf, gen, [1, 2, 3, 4], previous_failed=[{"q": "b"}])
    assert sets == [{"q": "a"}, {"q": "b"}, {"q": "d"}]  # defaults, the failed set, the newest run
    assert select_replay_sets(wf, gen, [1], previous_failed=[]) == [{"q": "a"}, {"q": "a"}]  # determinism check


def test_select_replay_sets_never_asks_the_caller_for_a_derived_param():
    from netgent.agent.generator.merge import GeneralizedTrajectory, ParamReport
    from netgent.schema.control import ParamDerivation
    from netgent.schema.workflow import Param, State, Workflow

    wf = Workflow(name="w", start_state="init", states=[State(id="init")], transitions=[], params=[
        Param(name="fast_forward_time", default="30s"),
        Param(name="presses", required=False, derive=ParamDerivation(from_param="fast_forward_time", divide_by=10))])
    gen = GeneralizedTrajectory(task="t", runs=2, achieved_runs=[1, 2], params=[
        ParamReport(name="fast_forward_time", default="30s", values_by_run={1: "30s", 2: "45s"})])
    assert select_replay_sets(wf, gen, [1, 2], previous_failed=[]) == [
        {"fast_forward_time": "30s"}, {"fast_forward_time": "45s"}]
    # a param the AGENT bound but the merge did not: its per-run values come from the runs' declared values
    unmerged = GeneralizedTrajectory(task="t", runs=2, achieved_runs=[1, 2], params=[])
    assert select_replay_sets(wf, unmerged, [1, 2], previous_failed=[],
                              run_values={1: {"fast_forward_time": "30s"}, 2: {"fast_forward_time": "45s"}}) == [
        {"fast_forward_time": "30s"}, {"fast_forward_time": "45s"}]
    assert select_replay_sets(wf, unmerged, [1, 2], previous_failed=[]) == [
        {"fast_forward_time": "30s"}, {"fast_forward_time": "30s"}]  # the old behaviour: the knob never varied
    # a dwell count param (bare-number default) takes the NUMBER out of the planner's '30s' (the live re-run
    # died at repeat.count '30s'); fast_forward_time's default is '30s' itself, so its spelling is kept
    timed = Workflow(name="w", start_state="init", states=[State(id="init")], transitions=[], params=[
        Param(name="initial_watch_time", default="15"), Param(name="fast_forward_time", default="30s")])
    assert select_replay_sets(timed, unmerged, [1, 2], previous_failed=[], run_values={
        1: {"initial_watch_time": "15s", "fast_forward_time": "30s"},
        2: {"initial_watch_time": "30s", "fast_forward_time": "45s"}}) == [
        {"initial_watch_time": "15", "fast_forward_time": "30s"},
        {"initial_watch_time": "30", "fast_forward_time": "45s"}]
