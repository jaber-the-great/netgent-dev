"""Explorer v2 — the same browser agent on `langchain.agents.create_agent` (an A/B arm).

Same job, same values (explorer/models.py), same context (explorer/context.py) and memory
(explorer/memory.py), same `explore()` / `ExplorerAgent` API — but the loop is LangChain's:
the atomic actions are tools (`tools.py`), observe/decide are middleware (`middleware.py`),
and `create_explorer_agent()` returns what `create_agent` builds (`graph.py`). Select it in
the evals with NETGENT_EXPLORER=v2. Everything here imports langchain/langgraph; the package
loads lazily from `netgent.agent`.
"""

from netgent.agent.explorer_v2.agent import ExplorerAgent

__all__ = ["ExplorerAgent", "create_explorer_agent", "explore"]

_LAZY = {"create_explorer_agent", "explore"}


def __getattr__(name: str):  # PEP 562: graph.py imports langchain's create_agent
    if name in _LAZY:
        from netgent.agent.explorer_v2 import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
