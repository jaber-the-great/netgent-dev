"""The verifier as LangGraph sees it — the explorer's shape (test_explorer_graph.py): one compiled
module-level graph, its rendered structure, and a run with no key through the FakeLLM seam."""

import asyncio

import pytest

from netgent.agent import AgentStep, AgentTrajectory, FakeLLM
from netgent.agent.verifier import Verdict, VerifierContext

pytest.importorskip("langgraph")

from netgent.agent.verifier.graph import VERIFIER, create_verifier_agent, verify  # noqa: E402


def _traj() -> AgentTrajectory:
    return AgentTrajectory(
        task="submit the form", success=True, texts_seen=["Success!"],
        steps=[AgentStep(n=1, kind="click", reasoning="SECRET REASONING", url="http://x")],
    )


def test_verifier_is_one_compiled_graph_gather_then_judge():
    mermaid = VERIFIER.get_graph().draw_mermaid()
    assert VERIFIER.name == "verifier"
    assert "__start__ --> gather;" in mermaid and "gather --> judge;" in mermaid and "judge --> __end__;" in mermaid
    assert create_verifier_agent().get_graph().draw_mermaid() == mermaid


def test_graph_runs_through_the_llm_seam_with_no_key():
    llm = FakeLLM([], verdicts=[Verdict(achieved=False, confidence="high", unmet=["no confirmation"])])
    final = asyncio.run(
        VERIFIER.ainvoke({"task": "submit the form", "trajectory": _traj(), "params": {"who": "Ada"}},
                         context=VerifierContext(llm=llm))
    )
    assert final["verdict"].unmet == ["no confirmation"]
    assert final["evidence"].action_log == ["1. click"] and final["evidence"].params == {"who": "Ada"}
    text = llm.judged[0][0]["text"]
    assert "SECRET REASONING" not in text and "${who} = 'Ada'" in text  # evidence only, never the narration


def test_verify_is_the_run_api_and_the_context_owns_the_knobs():
    verdict = asyncio.run(verify(_traj(), "submit the form", llm=FakeLLM([])))
    assert verdict.achieved and verdict.confidence == "high"  # FakeLLM's default verdict
    with pytest.raises(ValueError, match="max_screenshots"):
        VerifierContext(llm=FakeLLM([]), max_screenshots=-1)
    with pytest.raises(AttributeError):  # frozen
        VerifierContext(llm=FakeLLM([])).run_dir = None


def test_orchestrator_nests_both_the_explorer_and_the_verifier():
    from netgent.agent import GenerateRequest
    from netgent.agent.orchestrator import build_orchestration_graph

    pipeline = build_orchestration_graph(GenerateRequest(task="t"), FakeLLM([]))
    assert sorted(name for name, _ in pipeline.get_subgraphs()) == ["explore", "verify"]
    xray = pipeline.get_graph(xray=True).draw_mermaid()
    assert "subgraph verify" in xray and "gather(gather)" in xray and "judge(judge)" in xray
