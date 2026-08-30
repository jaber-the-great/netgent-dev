"""Explorer — ONE browser agent (compile-time only; the pipeline's only LLM role).

Functions + one compiled graph, the LangGraph shape (docs/research/langgraph-agent-structure.md):
`graph.py` holds the observe → decide → act nodes, `create_explorer_agent()` and the
module-level `EXPLORER`, and `explore()` — the single run API. The explorer observes the
page (indexed interactive elements), asks the LLM for ONE atomic action, dispatches it with
a durable locator, and records a trajectory. What a run needs travels as `ExplorerContext`
(`context.py`, LangGraph `Runtime.context`); what persists across runs is `ExplorerMemory`
(`memory.py`); `ExplorerAgent` (`agent.py`) is a thin façade holding knobs + one memory.
The other modules are its parts (`decision.py` the LLM's output schema, `actions.py`
decision → Action, `prompt.py`, `models.py` the values). Its output — trajectories — is the
input to the generator.

`explore`, `create_explorer_agent` and `EXPLORER` import langgraph; they are resolved lazily
so this package loads without the `generate` extra.
"""

from netgent.agent.explorer.agent import ExplorerAgent
from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.decision import AgentDecision
from netgent.agent.explorer.memory import ExplorerMemory
from netgent.agent.explorer.models import AgentStep, AgentTrajectory, StepRecord

__all__ = [
    "EXPLORER",
    "AgentDecision",
    "AgentStep",
    "AgentTrajectory",
    "ExplorerAgent",
    "ExplorerContext",
    "ExplorerMemory",
    "StepRecord",
    "create_explorer_agent",
    "explore",
]

_LAZY = {"EXPLORER", "create_explorer_agent", "explore"}


def __getattr__(name: str):  # PEP 562: the graph module imports langgraph
    if name in _LAZY:
        from netgent.agent.explorer import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
