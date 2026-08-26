"""Explorer — ONE browser agent (compile-time only; the pipeline's only LLM role).

`BrowserAgent` observes the page (indexed interactive elements), asks the LLM for ONE
atomic action, dispatches it with a durable locator, and records a trajectory. Its loop is
the LangGraph StateGraph in `graph.py`; the other modules are its parts (decision schema,
observation/locators, prompt, selector normalisation). Its output — trajectories — is the
input to the generator.
"""

from netgent.agent.explorer.browser_agent import AgentStep, AgentTrajectory, BrowserAgent
from netgent.agent.explorer.decision import AgentDecision

__all__ = ["AgentDecision", "AgentStep", "AgentTrajectory", "BrowserAgent"]
