"""The explorer on `langchain.agents.create_agent` — the A/B arm against explorer/graph.py.

    create_agent(model, tools=[click, fill, …, done], middleware=[ExplorerMiddleware()],
                 context_schema=ExplorerContext)

The atomic actions are tools executed by LangChain's ToolNode; the observe/decide logic is
middleware (middleware.py); the run's dependencies travel as `Runtime.context` (v1's
ExplorerContext, unchanged — its `llm` slot carries the chat model here). `explore()` has v1's
signature so the sweep, the stress eval and the tests can switch arms.

Differences from v1, by construction:
- the model is a BaseChatModel (or its `provider:model` string), not the `LLM` seam — usage is
  collected with LangChain's usage callback instead of LangChainLLM.usage;
- no settle watcher (transient banners are only caught by the per-step snapshot);
- the structured-output retry ladder is create_agent's: a turn with no tool call costs the step;
- a turn's tool calls beyond max_actions_per_step are truncated (browser-use), not rejected;
- no module-level compiled graph: the tool set depends on allowed_kinds, so agents are built
  per (model, kinds, max_actions) and cached.
"""

from pathlib import Path

from langchain.agents import create_agent
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.decision import DEFAULT_KINDS
from netgent.agent.explorer.graph import _write_trajectory
from netgent.agent.explorer.memory import ExplorerMemory
from netgent.agent.explorer.models import AgentStep, AgentTrajectory
from netgent.agent.explorer_v2.middleware import ExplorerMiddleware
from netgent.agent.explorer_v2.state import ExplorerV2State
from netgent.agent.explorer_v2.tools import tools_for
from netgent.agent.llm import model_ref
from netgent.browser.dom import format_observation
from netgent.browser.session import BrowserSession
from netgent.schema.actions import GotoAction

_AGENTS: dict[tuple, CompiledStateGraph] = {}


def resolve_model(model: "str | BaseChatModel") -> BaseChatModel:
    if isinstance(model, BaseChatModel):
        return model
    from langchain.chat_models import init_chat_model

    ref = model_ref(model)
    anthropic = ref.startswith("anthropic:") or ref.rsplit(":", 1)[-1].startswith("claude")
    return init_chat_model(ref, **({} if anthropic else {"temperature": 0}))


def create_explorer_agent(
    model: "str | BaseChatModel", *, allowed_kinds: frozenset[str] = DEFAULT_KINDS, max_actions_per_step: int = 1
) -> CompiledStateGraph:
    """Build the create_agent explorer for one tool set. Cached per (model, kinds, max_actions)."""
    chat = resolve_model(model)
    key = (id(chat), frozenset(allowed_kinds), max_actions_per_step)
    if key not in _AGENTS:
        _AGENTS[key] = create_agent(
            chat,
            tools=tools_for(frozenset(allowed_kinds)),
            middleware=[ExplorerMiddleware()],
            state_schema=ExplorerV2State,
            context_schema=ExplorerContext,
            name="explorer_v2",
        )
    return _AGENTS[key]


async def explore(
    session: BrowserSession,
    task: str,
    *,
    model: "str | BaseChatModel",
    memory: ExplorerMemory | None = None,
    url: str | None = None,
    frame_filter: list[str] | None = None,
    max_steps: int = 25,
    run_dir: Path | None = None,
    allowed_kinds: frozenset[str] | set[str] = DEFAULT_KINDS,
    max_actions_per_step: int = 1,
    upload_file: Path | None = None,
    usage: UsageMetadataCallbackHandler | None = None,
) -> AgentTrajectory:
    """v1's `explore()` on the create_agent arm. `usage` (a LangChain usage callback) accumulates
    token counts across calls when given."""
    memory = memory or ExplorerMemory()
    chat = resolve_model(model)
    traj = AgentTrajectory(task=task)
    dialog_mark = len(session.dialogs_seen())
    if url:
        await session.page.goto(url)
        traj.steps.append(
            AgentStep(n=0, kind="goto", reasoning="starting URL", url=session.page.url, action=GotoAction(url=url))
        )
    ctx = ExplorerContext(
        session=session, llm=chat, memory=memory, task=task, max_steps=max_steps, frame_filter=frame_filter,  # type: ignore[arg-type]
        allowed_kinds=frozenset(allowed_kinds), max_actions_per_step=max_actions_per_step, run_dir=run_dir,
        upload_file=upload_file,
    )
    agent = create_explorer_agent(chat, allowed_kinds=ctx.allowed_kinds, max_actions_per_step=max_actions_per_step)
    # One step is ~6 graph nodes (three hooks, model, tools, routing); a backstop, never the cap.
    config: dict = {"recursion_limit": 8 * max_steps + 20}
    if usage is not None:
        config["callbacks"] = [usage]
    final = await agent.ainvoke({"messages": [HumanMessage(content=task)], "steps": []}, config=config, context=ctx)

    traj.steps.extend(final.get("steps", []))
    traj.success = bool(final.get("success", False))
    traj.stopped_reason = final.get("stopped_reason", "")
    traj.texts_seen = list(final.get("texts_seen") or [])
    try:
        snap = await session.snapshot()
        if frame_filter is not None:
            snap = snap.scoped_to(frame_filter)
        traj.final_observation = format_observation(snap)
        traj.final_url = snap.url
    except Exception:  # noqa: BLE001 — a page mid-navigation: leave the evidence empty
        pass
    traj.dialogs = list(session.dialogs_seen())[dialog_mark:]
    if run_dir is not None:
        _write_trajectory(run_dir, traj)
    return traj
