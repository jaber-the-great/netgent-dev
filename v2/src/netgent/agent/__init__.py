"""The browser agent (compile-time LLM side): observe → decide → act loop.

Imports LLM SDKs (langchain) lazily inside LangChainLLM, so importing this package does not
require the `netgent[generate]` extra until a real model is actually used. FakeLLM needs nothing.
"""

from netgent.agent.explorer.agent import Agent, AgentStep, AgentTrajectory
from netgent.agent.explorer.decision import AgentDecision
from netgent.agent.llm import FakeLLM, LangChainLLM, make_llm
from netgent.agent.orchestrator import GenerateRequest, GenerateResult, orchestrate

__all__ = [
    "AgentDecision",
    "AgentStep",
    "AgentTrajectory",
    "Agent",
    "FakeLLM",
    "GenerateRequest",
    "GenerateResult",
    "LangChainLLM",
    "make_llm",
    "orchestrate",
]
