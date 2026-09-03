"""The orchestrator chains explore → verify → generate → replay on a local fixture with a scripted LLM.
The replay is the single-run gate: zero LLM by construction (FakeLLM raises once its script is spent)."""

import asyncio
import json

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.orchestrator import GenerateRequest, orchestrate

FIXTURE = """<!doctype html><html><head><title>Hello</title></head><body>
<input id="name" placeholder="name">
<button id="go" onclick="document.getElementById('ok').style.display='block'">Go</button>
<div id="ok" style="display:none">welcome</div>
</body></html>"""


def test_orchestrate_explores_verifies_and_generates(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    llm = FakeLLM(
        [
            AgentDecision(reasoning="type the name", kind="fill", index=0, text="Ada"),
            AgentDecision(reasoning="press go", kind="click", index=1),
            AgentDecision(reasoning="welcome is shown", done=True, success=True),
        ]
    )
    events: list[tuple[str, str]] = []
    req = GenerateRequest(
        task="fill the name and press go",
        url=page.as_uri(),
        name="hello",
        params={"who": "Ada"},
        out=tmp_path / "hello.yaml",
    )
    result = asyncio.run(orchestrate(req, llm, lambda stage, text: events.append((stage, text))))

    assert result.error is None
    assert result.trajectory is not None and result.trajectory.success
    assert result.workflow is not None and [t.id for t in result.workflow.transitions] == ["t1", "t2", "t3"]
    assert result.workflow.transition("t2").action.text == "${who}"  # sample value became a param
    # the explorer was TOLD the sample values (else it cannot use them and nothing abstracts)
    assert "${who} = 'Ada'" in result.trajectory.task and result.trajectory.task.startswith(req.task)
    assert (tmp_path / "hello.yaml").is_file()
    assert result.verdict is not None and result.verdict.achieved  # FakeLLM's default verdict
    assert [s for s, _ in events][0] == "explore"
    assert {s for s, _ in events} == {"explore", "verify", "generate", "replay"}
    # the single-run gate (generator-agent-v2.md §I.4): the artifact replayed on the recorded value set,
    # twice because a param is declared (the determinism half of the metamorphic check), zero LLM
    assert result.replay is not None and result.replay.passed
    assert [r.values for r in result.replay.runs] == [{"who": "Ada"}, {"who": "Ada"}]
    assert result.replay.runs[0].signature == result.replay.runs[1].signature == ["s1", "s2", "s3"]
    for k in (1, 2):
        record = json.loads((tmp_path / "hello.trajectories" / f"replay-{k}" / "record.json").read_text())
        assert record["success"] is True
    assert any(s == "replay" and t.startswith("ok {'who': 'Ada'}") for s, t in events)


def test_a_drifted_page_fails_the_single_run_replay_gate_and_keeps_the_artifact(serve, tmp_path):
    """The page the explorer saw is not the page the replay gets (the Go button is gone on the second
    visit): the compiled artifact is still written, the replay reports the failed edge and the
    unmet condition, and the pipeline ends with an error — what the CLI turns into a non-zero exit."""
    visits = {"n": 0}

    def page() -> str:
        visits["n"] += 1
        return FIXTURE if visits["n"] == 1 else FIXTURE.replace('<button id="go"', '<button id="go" hidden')

    srv = serve({"/": page})
    llm = FakeLLM([
        AgentDecision(reasoning="type the name", kind="fill", index=0, text="Ada"),
        AgentDecision(reasoning="press go", kind="click", index=1),
        AgentDecision(reasoning="welcome is shown", done=True, success=True),
    ])
    events: list[tuple[str, str]] = []
    out = tmp_path / "hello.yaml"
    req = GenerateRequest(task="fill the name and press go", url=srv.url("/"), name="hello", out=out, judge=False)
    result = asyncio.run(orchestrate(req, llm, lambda stage, text: events.append((stage, text))))

    assert out.is_file()  # the artifact is written before the gate, for inspection
    assert result.workflow is not None
    assert result.error and result.error.startswith("replay check failed")
    assert result.replay is not None and not result.replay.passed
    (run,) = result.replay.runs  # no params: one replay
    assert run.values == {} and not run.success
    assert run.signature == ["s1", "FAILED@t2"] and run.failed_edge == "t2" and run.outcome == "trigger_timeout"
    assert run.unmet == ["selector_visible"]  # the state anchored on the Go button never came
    assert visits["n"] == 2
    lines = [t for s, t in events if s == "replay"]
    assert any(t.startswith("FAILED {}") for t in lines) and lines[-1].startswith("replay check FAILED")


def test_orchestrate_stops_when_exploration_fails(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    llm = FakeLLM([AgentDecision(reasoning="a CAPTCHA blocks the task", done=True, success=False)])
    req = GenerateRequest(task="impossible", url=page.as_uri(), out=tmp_path / "never.yaml")
    result = asyncio.run(orchestrate(req, llm))

    assert result.error and "exploration failed" in result.error
    assert result.workflow is None and result.verdict is None  # verify/generate never ran
    assert not (tmp_path / "never.yaml").exists()


def test_verifier_reexplores_once_when_the_judge_says_not_achieved(tmp_path):
    """The judge (advisory) routes: NOT achieved → one more exploration with the unmet points in
    the task; achieved → generate. It sees page evidence, never the explorer's reasoning."""
    from netgent.agent.verifier import Verdict

    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    run = [
        AgentDecision(reasoning="type the name", kind="fill", index=0, text="Ada"),
        AgentDecision(reasoning="press go", kind="click", index=1),
        AgentDecision(reasoning="welcome is shown", done=True, success=True),
    ]
    llm = FakeLLM(run + run, verdicts=[
        Verdict(achieved=False, confidence="high", unmet=["no welcome message visible"]),
        Verdict(achieved=True, confidence="high", evidence=["Welcome, Ada"]),
    ])
    events: list[tuple[str, str]] = []
    req = GenerateRequest(task="fill the name and press go", url=page.as_uri(), name="hello",
                          params={"who": "Ada"}, out=tmp_path / "hello.yaml")
    result = asyncio.run(orchestrate(req, llm, lambda stage, text: events.append((stage, text))))

    assert result.error is None and result.workflow is not None
    assert result.verdict is not None and result.verdict.achieved
    assert [s for s, _ in events].count("verify") >= 2  # judged twice
    assert result.trajectory.task.endswith("before declaring done.")  # the retry carried the unmet points
    assert "no welcome message visible" in result.trajectory.task
    assert len(llm.judged) == 2
    text = llm.judged[0][0]["text"]
    assert "type the name" not in text and "TASK: fill the name and press go" in text  # evidence only
    assert any(c["type"] == "image_url" for c in llm.judged[0])  # screenshots reached the judge
