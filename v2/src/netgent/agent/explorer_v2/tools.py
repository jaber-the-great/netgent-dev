"""One LangChain tool per atomic action kind — the create_agent spelling of v1's `act` node.

Each tool executes ONE action against the live session in `runtime.context` (an ExplorerContext),
records an AgentStep (with the resolved durable locator, so the compiler can read it) and a
StepRecord in the cross-run memory, and returns a Command carrying both the state update and the
ToolMessage. Item-level semantics are v1's: a URL change since the turn's snapshot skips the
remaining calls; a failure is reported, never raised. Tool calls in one turn run under a lock,
in call order (ToolNode gathers them concurrently)."""

import asyncio
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from netgent.agent.explorer.actions import to_action
from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.decision import AgentAction
from netgent.agent.explorer.graph import _target_label, _verified_locator, capture_screenshot, upload_path
from netgent.agent.explorer.models import AgentStep, StepRecord
from netgent.agent.explorer_v2.state import ExplorerV2State
from netgent.core.errors import ExecutionError
from netgent.core.logger import get_logger

logger = get_logger(__name__)

Runtime = ToolRuntime[ExplorerContext, ExplorerV2State]


def _lock(ctx: ExplorerContext) -> asyncio.Lock:
    """One lock per memory (per agent): a turn's tool calls execute one at a time, in order."""
    lock = getattr(ctx.memory, "_v2_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        ctx.memory._v2_lock = lock  # type: ignore[attr-defined]
    return lock


async def _execute(runtime: Runtime, item: AgentAction, reasoning: str) -> Command:
    ctx = runtime.context
    session = ctx.session
    state = runtime.state
    n, snapshot = state.get("n", 0), state["snapshot"]
    async with _lock(ctx):
        if session.page.url != snapshot.url:  # v1's runtime batch guard: the snapshot's indices mean nothing now
            ctx.memory.history.append(StepRecord(
                n=n, kind="note", note=f"{n}. page changed before {item.kind}: it was skipped — decide again "
                "from the new observation",
            ))
            return Command(update={"messages": [ToolMessage(
                content=f"skipped {item.kind}: the page changed; look at the new observation",
                tool_call_id=runtime.tool_call_id,
            )]})
        error: str | None = None
        action: Any = None
        note = None
        try:
            if item.kind not in ctx.allowed_kinds:
                raise ValueError(
                    f"{item.kind} is not available in this task; use one of {', '.join(sorted(ctx.allowed_kinds))}"
                )
            upload = upload_path(ctx) if item.kind == "upload" else None
            locator_for, note = await _verified_locator(session, snapshot, item.index)
            action = to_action(item, snapshot, upload_path=upload, locator_for=locator_for)
            elems = snapshot.interactive()
            if item.index is not None and 0 <= item.index < len(elems):
                if elems[item.index].requires_closed_shadow and hasattr(action, "requires_closed_shadow"):
                    action = action.model_copy(update={"requires_closed_shadow": True})
            await session.dispatch(action)
        except (ExecutionError, ValueError) as exc:
            error = str(exc)
            logger.warning("step %d %s failed: %s", n, item.kind, error)
        step = AgentStep(n=n, kind=item.kind or "", reasoning=reasoning, url=session.page.url, error=error)
        if error is None:
            step.action = action
            step.locator_check = note
            step.dialogs = session.dialogs_since_last_action()
        await capture_screenshot(ctx, step)
        record = StepRecord(
            n=n, kind=item.kind or "", index=item.index, target=_target_label(snapshot, item.index),
            reasoning=reasoning, error=error, outcome="failed" if error else "ok",
        )
        if error is None and item.kind == "wait":
            record.outcome, record.error = "waited", f"you already waited {item.seconds:g}s"
        ctx.memory.history.append(record)
        text = f"{item.kind} FAILED: {error}" if error else f"{item.kind} ok"
        if step.dialogs:
            text += " | dialog: " + " | ".join(step.dialogs)
        msg = ToolMessage(content=text, tool_call_id=runtime.tool_call_id)
        return Command(update={"steps": [step], "messages": [msg]})


@tool
async def click(runtime: Runtime, index: int, reasoning: str) -> Command:
    """Click the element with this index from the observation."""
    return await _execute(runtime, AgentAction(kind="click", index=index), reasoning)


@tool
async def fill(runtime: Runtime, index: int, text: str, reasoning: str) -> Command:
    """Type `text` into the input/textarea/editor with this index (replaces its value)."""
    return await _execute(runtime, AgentAction(kind="fill", index=index, text=text), reasoning)


@tool
async def select(runtime: Runtime, index: int, value: str, reasoning: str) -> Command:
    """Choose `value` (one of the listed options=[…]) in the <select> with this index."""
    return await _execute(runtime, AgentAction(kind="select", index=index, value=value), reasoning)


@tool
async def upload(runtime: Runtime, index: int, reasoning: str) -> Command:
    """Attach the sample file to the input[file] with this index."""
    return await _execute(runtime, AgentAction(kind="upload", index=index), reasoning)


@tool
async def hover(runtime: Runtime, index: int, reasoning: str) -> Command:
    """Hover the element with this index."""
    return await _execute(runtime, AgentAction(kind="hover", index=index), reasoning)


@tool
async def press(runtime: Runtime, keys: str, reasoning: str, index: int | None = None) -> Command:
    """Press a key or chord (Enter, Tab, Control+a); on the element with `index` if given."""
    return await _execute(runtime, AgentAction(kind="press", keys=keys, index=index), reasoning)


@tool
async def goto(runtime: Runtime, url: str, reasoning: str) -> Command:
    """Navigate to `url`."""
    return await _execute(runtime, AgentAction(kind="goto", url=url), reasoning)


@tool
async def go_back(runtime: Runtime, reasoning: str) -> Command:
    """Go back one page in history."""
    return await _execute(runtime, AgentAction(kind="go_back"), reasoning)


@tool
async def scroll(runtime: Runtime, down: bool, reasoning: str, pages: float = 1.0, index: int | None = None) -> Command:
    """Scroll the page (or the box/iframe containing element `index`) by `pages` screens."""
    return await _execute(runtime, AgentAction(kind="scroll", down=down, pages=pages, index=index), reasoning)


@tool
async def wait(runtime: Runtime, seconds: float, reasoning: str) -> Command:
    """Wait `seconds` (a dwell: watching a video, letting a banner appear)."""
    return await _execute(runtime, AgentAction(kind="wait", seconds=seconds), reasoning)


@tool
async def done(runtime: Runtime, success: bool, reasoning: str) -> Command:
    """END the run. success=true only if every TASK requirement is met; false = giving up (say why)."""
    # Never executed: the middleware intercepts `done` calls after the model turn and ends the run.
    return Command(update={"messages": [ToolMessage(content="run ended", tool_call_id=runtime.tool_call_id)]})


ACTION_TOOLS = {t.name: t for t in (click, fill, select, upload, hover, press, goto, go_back, scroll, wait)}


def tools_for(allowed_kinds: frozenset[str]) -> list:
    """The tool set for one task: exactly the allowed kinds, plus `done`."""
    return [ACTION_TOOLS[k] for k in ACTION_TOOLS if k in allowed_kinds] + [done]
