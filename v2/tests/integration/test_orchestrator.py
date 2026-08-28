"""The orchestrator chains explore → generate → validate on a local fixture with a scripted LLM."""

import asyncio

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.orchestrator import GenerateRequest, orchestrate

FIXTURE = """<!doctype html><html><head><title>Hello</title></head><body>
<input id="name" placeholder="name">
<button id="go" onclick="document.getElementById('ok').style.display='block'">Go</button>
<div id="ok" style="display:none">welcome</div>
</body></html>"""


def test_orchestrate_explores_generates_and_validates(tmp_path):
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
    assert result.validated, [(r.failed_edge, r.error) for r in result.report.replays]
    assert [s for s, _ in events][0] == "explore" and "validate" in {s for s, _ in events}


def test_orchestrate_stops_when_exploration_fails(tmp_path):
    page = tmp_path / "p.html"
    page.write_text(FIXTURE)
    llm = FakeLLM([AgentDecision(reasoning="a CAPTCHA blocks the task", done=True, success=False)])
    req = GenerateRequest(task="impossible", url=page.as_uri(), out=tmp_path / "never.yaml")
    result = asyncio.run(orchestrate(req, llm))

    assert result.error and "exploration failed" in result.error
    assert result.workflow is None and result.report is None  # generate/validate never ran
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

    assert result.error is None and result.validated
    assert result.verdict is not None and result.verdict.achieved
    assert [s for s, _ in events].count("verify") >= 2  # judged twice
    assert result.trajectory.task.endswith("before declaring done.")  # the retry carried the unmet points
    assert "no welcome message visible" in result.trajectory.task
    assert len(llm.judged) == 2
    text = llm.judged[0][0]["text"]
    assert "type the name" not in text and "TASK: fill the name and press go" in text  # evidence only
    assert any(c["type"] == "image_url" for c in llm.judged[0])  # screenshots reached the judge
