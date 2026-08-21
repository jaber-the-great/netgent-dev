"""The browser agent (compile-time LLM side): observe → decide → act loop.

Imports LLM SDKs (langchain) lazily inside LangChainLLM, so importing this package does not
require the `netgent[generate]` extra until a real model is actually used. FakeLLM needs nothing.
"""

from netgent.agent.explore_agent.browser_agent import AgentStep, AgentTrajectory, BrowserAgent
from netgent.agent.explore_agent.decision import AgentDecision
from netgent.agent.llm import FakeLLM, LangChainLLM, make_llm

__all__ = [
    "AgentDecision",
    "AgentStep",
    "AgentTrajectory",
    "BrowserAgent",
    "FakeLLM",
    "LangChainLLM",
    "make_llm",
]
