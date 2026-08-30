"""The explorer as LangGraph sees it: the compiled module-level graph, its rendered structure,
and a run with no browser and no key (docs/research/langgraph-agent-structure.md §3e, §5.5).

The mermaid snapshot is derived from the nodes' `Command[Literal[...]]` annotations, so it
catches a node whose declared successors drift from its real `goto`s — the honest replacement
for the hand-mirrored diagrams dropped in 70a3a3b / 0a70be2."""

import asyncio

import pytest

from netgent.agent import ExplorerAgent, ExplorerContext, ExplorerMemory, FakeLLM
from netgent.agent.explorer.decision import ALL_KINDS, DEFAULT_KINDS, MAX_BATCH

pytest.importorskip("langgraph")

from netgent.agent.explorer.graph import EXPLORER, create_explorer_agent, explore  # noqa: E402


def test_explorer_is_one_compiled_graph_with_the_loop_and_its_exits():
    mermaid = EXPLORER.get_graph().draw_mermaid()
    assert EXPLORER.name == "explorer"
    for node in ("observe", "decide", "act"):
        assert f"\t{node}({node})" in mermaid
    # the loop
    assert "__start__ --> observe;" in mermaid
    assert "observe -.-> decide;" in mermaid
    assert "decide -.-> act;" in mermaid
    assert "act -.-> observe;" in mermaid
    # the exits: budget/stuck (observe), done (decide), repeated-action stop (act);
    # an invalid decision costs the step and re-observes (decide → observe)
    assert "observe -.-> __end__;" in mermaid
    assert "decide -.-> __end__;" in mermaid
    assert "act -.-> __end__;" in mermaid
    assert "decide -.-> observe;" in mermaid
    # nothing else: no act → decide, no observe → act
    assert "act -.-> decide;" not in mermaid and "observe -.-> act;" not in mermaid


def test_factory_builds_the_same_topology_as_the_module_level_graph():
    fresh = create_explorer_agent()
    assert fresh is not EXPLORER
    assert fresh.get_graph().draw_mermaid() == EXPLORER.get_graph().draw_mermaid()
    assert {"observe", "decide", "act"} <= set(EXPLORER.nodes)


def test_graph_runs_without_a_browser_when_the_budget_is_spent():
    """The node reads its dependencies from Runtime.context; with max_steps=0 the observe node
    ends the run before it touches the session, so a graph-level invoke needs no browser."""
    ctx = ExplorerContext(session=None, llm=FakeLLM([]), memory=ExplorerMemory(), task="t", max_steps=0)
    final = asyncio.run(EXPLORER.ainvoke({"steps": []}, context=ctx))
    assert final["stopped_reason"] == "reached max_steps=0"
    assert final["steps"] == []


def test_context_owns_the_knob_validation():
    mem = ExplorerMemory()
    with pytest.raises(ValueError, match=f"1..{MAX_BATCH}"):
        ExplorerContext(session=None, llm=FakeLLM([]), memory=mem, task="t", max_actions_per_step=MAX_BATCH + 1)
    with pytest.raises(ValueError, match="unknown action kinds"):
        ExplorerContext(session=None, llm=FakeLLM([]), memory=mem, task="t", allowed_kinds=frozenset({"teleport"}))
    ctx = ExplorerContext(session=None, llm=FakeLLM([]), memory=mem, task="t", allowed_kinds=set(ALL_KINDS))
    assert isinstance(ctx.allowed_kinds, frozenset) and ctx.allowed_kinds == ALL_KINDS
    with pytest.raises(AttributeError):  # frozen: a run's dependencies are fixed
        ctx.task = "u"


def test_agent_facade_validates_early_and_shares_one_memory_across_runs():
    with pytest.raises(ValueError, match="unknown action kinds"):
        ExplorerAgent(FakeLLM([]), allowed_kinds={"teleport"})
    with pytest.raises(ValueError, match="max_actions_per_step"):
        ExplorerAgent(FakeLLM([]), max_actions_per_step=0)
    shared = ExplorerMemory()
    agent = ExplorerAgent(FakeLLM([]), memory=shared)
    assert agent.memory is shared and agent.allowed_kinds == DEFAULT_KINDS
    agent.note("--- form 1 ---")
    assert agent.history is shared.history and shared.history[-1].note == "--- form 1 ---"
    # the façade's run() is explore(); both accept a memory to carry across tasks
    assert explore.__name__ == "explore" and ExplorerAgent.run.__doc__


def test_orchestrator_sees_the_explorer_as_a_nested_subgraph():
    """The orchestrator's explore node closes over the module-level EXPLORER (via explore()),
    so static introspection — get_subgraphs(), xray mermaid, Studio — shows the loop nested
    inside the pipeline instead of an opaque node (§3d probe C → A)."""
    from netgent.agent import GenerateRequest
    from netgent.agent.orchestrator import build_orchestration_graph

    pipeline = build_orchestration_graph(GenerateRequest(task="t"), FakeLLM([]))
    assert [name for name, _ in pipeline.get_subgraphs()] == ["explore"]
    xray = pipeline.get_graph(xray=True).draw_mermaid()
    assert "subgraph explore" in xray
    for node in ("observe", "decide", "act"):  # namespaced ids: "explore:observe" is rendered explore\3aobserve
        assert f"{node}({node})" in xray
