"""`--parallel N` end to end on a local fixture with a scripted LLM: plan variations →
explore ×N (fresh memory, verify per run) → typed merge (params inferred) → zero-LLM
metamorphic replay with BOTH value sets. The replay proves zero-LLM by construction:
FakeLLM raises once its script is exhausted."""

import asyncio
import json

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.orchestrator import GenerateRequest, orchestrate
from netgent.agent.planner import TaskVariation, VariationPlan
from netgent.agent.verifier import Verdict

FIXTURE = """<!doctype html><html><head><title>Hello</title></head><body>
<input id="name" placeholder="name">
<button id="go" onclick="document.getElementById('ok').style.display='block'">Go</button>
<div id="ok" style="display:none">welcome</div>
</body></html>"""


def _run_script(text):
    return [
        AgentDecision(reasoning="type the name", kind="fill", index=0, text=text),
        AgentDecision(reasoning="press go", kind="click", index=1),
        AgentDecision(reasoning="welcome is shown", done=True, success=True),
    ]


def _plan():
    return VariationPlan(variations=[
        TaskVariation(task_text="fill the name Ada and press go", values={"who": "Ada"}),
        TaskVariation(task_text="fill the name Bob and press go", values={"who": "Bob"}),
    ])


def test_multi_run_infers_params_and_replays_zero_llm(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    llm = FakeLLM(
        _run_script("Ada") + _run_script("Bob"),
        verdicts=[_plan(), Verdict(achieved=True, confidence="high"), Verdict(achieved=True, confidence="high")],
    )
    events: list[tuple[str, str]] = []
    req = GenerateRequest(
        task="fill the name Ada and press go",
        url=page.as_uri(),
        name="hello",
        out=tmp_path / "hello.yaml",
        runs=2,
    )
    result = asyncio.run(orchestrate(req, llm, lambda s, t: events.append((s, t))))

    assert result.error is None
    # the merge confirmed the planner's name from the varying fill values
    (p,) = result.workflow.params
    assert p.name == "who" and p.default == "Ada"
    (fill_edge,) = [t for t in result.workflow.transitions if t.action.type == "fill"]
    assert fill_edge.action.text == "${who}"
    # per-run verdicts recorded; both achieved
    assert [r["achieved"] for r in result.run_reports] == [True, True]
    assert [r["values"]["who"] for r in result.run_reports] == ["Ada", "Bob"]
    # the store: run folders, variation + verdict + trajectory per run, generalized.json
    store = tmp_path / "hello.trajectories"
    for k in (1, 2):
        assert (store / f"run-{k}" / "trajectory.json").is_file()
        assert json.loads((store / f"run-{k}" / "variation.json").read_text())["values"]
        assert json.loads((store / f"run-{k}" / "verdict.json").read_text())["achieved"] is True
    generalized = json.loads((store / "generalized.json").read_text())
    assert generalized["achieved_runs"] == [1, 2]
    assert generalized["params"][0]["name"] == "who"
    # the metamorphic replay: two value sets (Ada and Bob), zero LLM, same state sequence
    assert result.replay is not None and result.replay.passed
    assert [r.values for r in result.replay.runs] == [{"who": "Ada"}, {"who": "Bob"}]
    assert result.replay.runs[0].signature == result.replay.runs[1].signature
    assert {s for s, _ in events} >= {"plan", "explore", "verify", "merge", "generate", "replay"}
    assert (tmp_path / "hello.yaml").is_file()


def test_not_achieved_run_is_retried_once_with_a_private_suffix(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    llm = FakeLLM(
        _run_script("Ada") + _run_script("Bob") + _run_script("Bob"),  # run 2 retried once
        verdicts=[
            _plan(),
            Verdict(achieved=True, confidence="high"),
            Verdict(achieved=False, confidence="high", unmet=["no welcome visible"]),
            Verdict(achieved=True, confidence="high"),
        ],
    )
    req = GenerateRequest(
        task="fill the name Ada and press go", url=page.as_uri(), name="hello",
        out=tmp_path / "hello.yaml", runs=2,
    )
    result = asyncio.run(orchestrate(req, llm))

    assert result.error is None
    assert [r["attempts"] for r in result.run_reports] == [1, 2]
    # the first (failed) attempt of run 2 was stashed, not lost
    stash = tmp_path / "hello.trajectories" / "run-2" / "trajectory.failed-attempt-1.json"
    assert stash.is_file()
    # the retry suffix stayed inside run 2: run 1's trajectory task carries no unmet points
    run1 = json.loads((tmp_path / "hello.trajectories" / "run-1" / "trajectory.json").read_text())
    assert "NOT achieved" not in run1["task"]
    run2 = json.loads((tmp_path / "hello.trajectories" / "run-2" / "trajectory.json").read_text())
    assert "no welcome visible" in run2["task"]


def test_no_achieved_runs_stops_before_generate(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    fail = [AgentDecision(reasoning="a CAPTCHA blocks the task", done=True, success=False)]
    llm = FakeLLM(fail + fail, verdicts=[_plan()])
    req = GenerateRequest(task="impossible", url=page.as_uri(), name="never",
                          out=tmp_path / "never.yaml", runs=2)
    result = asyncio.run(orchestrate(req, llm))

    assert result.error and "no run achieved" in result.error
    assert result.workflow is None and not (tmp_path / "never.yaml").exists()
    # failed runs are stored anyway — they are memory
    for k in (1, 2):
        assert json.loads(
            (tmp_path / "never.trajectories" / f"run-{k}" / "verdict.json").read_text()
        )["achieved"] is False


def test_a_scripted_draft_flows_through_materialize_and_the_zero_llm_replay(tmp_path):
    """G4/G5: the generator agent's draft — pointers into the two recordings — is materialized
    (every pointer re-derived), replaces the merge's artifact, carries a witnessed accept state,
    and replays for both value sets with zero LLM."""
    from netgent.agent.generator.draft import DraftCondition, DraftEdge, DraftParam, ParamWitness, WorkflowDraft

    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    draft = WorkflowDraft(
        spine=1, kept_runs=[1, 2],
        params=[DraftParam(name="who", witnesses=[ParamWitness(step="r1.s1.0", field="text", literal="Ada"),
                                                  ParamWitness(step="r2.s1.0", field="text", literal="Bob")])],
        main=[DraftEdge(step="r1.s0.0", corroborated_by=["r2.s0.0"]),
              DraftEdge(step="r1.s1.0", value_param="who", corroborated_by=["r2.s1.0"]),
              DraftEdge(step="r1.s2.0", corroborated_by=["r2.s2.0"], why="the button shows the welcome")],
        accept=[DraftCondition(type="url_matches", witness="r1.s2.0", why="the task ends on the page")],
    )
    ok = Verdict(achieved=True, confidence="high")
    llm = FakeLLM(_run_script("Ada") + _run_script("Bob"), verdicts=[_plan(), ok, ok], drafts=[draft])
    req = GenerateRequest(task="fill the name Ada and press go", url=page.as_uri(), name="hello",
                          out=tmp_path / "hello.yaml", runs=2)
    result = asyncio.run(orchestrate(req, llm))

    assert result.error is None, result.error
    rd = result.context.rounds[0]
    assert not rd.used_fallback and rd.validated and rd.draft_acceptance_rate == 1.0 and rd.repairs_used == 0
    assert {o.item for o in rd.draft_outcomes} >= {"runs", "params[0]", "main[0]", "main[1]", "main[2]", "accept[0]"}
    wf = result.workflow
    (fill,) = [t for t in wf.transitions if t.action.type == "fill"]
    assert fill.action.text == "${who}" and [p.name for p in wf.params] == ["who"]
    assert wf.accept_states == ["s3"] and wf.state("s3").conditions[-1].type == "url_matches"
    assert result.replay.passed and [r.values for r in result.replay.runs] == [{"who": "Ada"}, {"who": "Bob"}]
    assert len(llm.drafted) == 1 and llm.drafted[0][0]["text"].startswith("TASK: fill the name Ada")
    stored = json.loads((tmp_path / "hello.trajectories" / "round-1" / "draft.json").read_text())
    assert stored["used_fallback"] is False and stored["draft"]["spine"] == 1
