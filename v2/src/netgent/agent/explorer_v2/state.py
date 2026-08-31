"""Graph state for the create_agent-based explorer: LangChain's AgentState (messages, jump_to)
plus the loop bookkeeping the v1 graph keeps in explorer/graph.py::AgentState."""

import operator
from typing import Annotated, Any

from langchain.agents.middleware import AgentState

from netgent.agent.explorer.models import AgentStep


class ExplorerV2State(AgentState, total=False):
    n: int  # step number of the step being worked on
    snapshot: Any  # DomSnapshot for the current step
    observation: str
    prev_observation: str | None  # the diff-free rendering of the previous step (equality check)
    prev_url: str | None
    no_progress: int
    texts_seen: list[str]
    steps: Annotated[list[AgentStep], operator.add]  # the trajectory, appended per executed tool
    last_action_key: str  # "kind|index|text" of the previous turn's first tool call
    repeat_count: int  # consecutive turns with the same first tool call
    success: bool
    stopped_reason: str
