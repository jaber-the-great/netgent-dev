"""The browser agent's loop is a LangGraph StateGraph with the expected shape."""

from netgent.agent.graph import agent_graph_mermaid


def test_agent_loop_is_a_langgraph_with_observe_decide_act():
    mermaid = agent_graph_mermaid()
    for node in ("observe", "decide", "act"):
        assert node in mermaid
    # the loop: observe → decide → act → observe, plus the exits to END
    assert "observe --> decide" in mermaid or "observe -.-> decide" in mermaid
    assert "decide --> act" in mermaid or "decide -.-> act" in mermaid
    assert "act --> observe" in mermaid or "act -.-> observe" in mermaid
    assert "__end__" in mermaid
