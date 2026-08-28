"""Explorer — ONE browser agent (compile-time only; the pipeline's only LLM role).

`Agent` observes the page (indexed interactive elements), asks the LLM for ONE
atomic action, dispatches it with a durable locator, and records a trajectory. Its loop is
the LangGraph StateGraph in `graph.py`; the other modules are its parts (`decision.py` the
LLM's output schema, `actions.py` decision → Action, `prompt.py`). Locator building lives
in browser/locators.py. Its output — trajectories — is the
input to the generator.
"""

from netgent.agent.explorer.agent import Agent, AgentStep, AgentTrajectory
from netgent.agent.explorer.decision import AgentDecision

__all__ = ["AgentDecision", "AgentStep", "AgentTrajectory", "Agent"]
