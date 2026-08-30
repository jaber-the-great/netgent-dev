"""The compile-time agents (the LLM side): the explorer's observe → decide → act loop, the
generator, the validator, the verifier, and the orchestrator that chains them.

Imports LLM SDKs (langchain) lazily inside LangChainLLM and langgraph only inside the graph
modules, so importing this package does not require the `netgent[generate]` extra until a
real model or graph is actually used. FakeLLM needs nothing. `explore`,
`create_explorer_agent` and `EXPLORER` are resolved lazily for the same reason.
"""

from netgent.agent.explorer import ExplorerAgent, ExplorerContext, ExplorerMemory
from netgent.agent.explorer.decision import AgentDecision
from netgent.agent.explorer.models import AgentStep, AgentTrajectory, StepRecord
from netgent.agent.llm import FakeLLM, LangChainLLM, make_llm
from netgent.agent.orchestrator import GenerateRequest, GenerateResult, orchestrate

__all__ = [
    "EXPLORER",
    "AgentDecision",
    "AgentStep",
    "AgentTrajectory",
    "ExplorerAgent",
    "ExplorerContext",
    "ExplorerMemory",
    "FakeLLM",
    "GenerateRequest",
    "GenerateResult",
    "LangChainLLM",
    "StepRecord",
    "create_explorer_agent",
    "explore",
    "make_llm",
    "orchestrate",
]

_LAZY = {"EXPLORER", "create_explorer_agent", "explore"}


def __getattr__(name: str):  # PEP 562: these live in explorer/graph.py, which imports langgraph
    if name in _LAZY:
        from netgent.agent.explorer import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
