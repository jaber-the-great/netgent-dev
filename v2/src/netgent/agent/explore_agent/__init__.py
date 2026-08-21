"""Explore agent — the LLM-driven browser loop (compile-time only).

Observes the page (indexed interactive elements), asks the LLM for ONE atomic action,
dispatches it with a durable locator, and records a trajectory. Runs as a LangGraph
StateGraph (`graph.py`). Also hosts the form sweep harness. Its output — trajectories —
is the input to the workflow generator agent.
"""

from netgent.agent.explore_agent.browser_agent import AgentStep, AgentTrajectory, BrowserAgent
from netgent.agent.explore_agent.decision import AgentDecision

__all__ = ["AgentDecision", "AgentStep", "AgentTrajectory", "BrowserAgent"]
