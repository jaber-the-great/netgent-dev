"""The v1 `observe` and `decide` nodes as create_agent middleware.

- `abefore_model`  = observe: step budget, DOM snapshot (scoped for a sweep), observation-equality
                     stuck detection, texts_seen accumulation.
- `awrap_model_call` = the prompt: the accumulated `messages` are NOT sent. Each turn the model gets
                     v1's layout — SystemMessage(system prompt + task) and HumanMessage(RECENT STEPS
                     from the cross-run memory + OBSERVATION) — so context does not grow with steps
                     and a sweep's folds keep working (browser-agent-memory.md §6.2).
- `aafter_model`   = decide's guards: truncate a turn to max_actions_per_step tool calls, intercept
                     `done`, the repeated-action nudge/stop, and re-observe on a turn with no tool
                     call (create_agent would otherwise END the loop).
"""

from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse, hook_config
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime

from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.graph import MAX_REPEAT, REPEAT_NUDGE, REPEAT_STOP
from netgent.agent.explorer.models import AgentStep, StepRecord
from netgent.agent.explorer_v2.prompt import build_system_prompt_v2
from netgent.agent.explorer_v2.state import ExplorerV2State
from netgent.agent.llm import render_prompt
from netgent.browser.dom import format_observation
from netgent.core.logger import get_logger

logger = get_logger(__name__)


class ExplorerMiddleware(AgentMiddleware[ExplorerV2State, ExplorerContext]):
    state_schema = ExplorerV2State

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: ExplorerV2State, runtime: Runtime[ExplorerContext]) -> dict[str, Any] | None:
        ctx = runtime.context
        n = state.get("n", 0) + 1
        if n > ctx.max_steps:
            return {"stopped_reason": f"reached max_steps={ctx.max_steps}", "jump_to": "end"}
        snapshot = await ctx.session.snapshot()
        if ctx.frame_filter is not None:
            snapshot = snapshot.scoped_to(ctx.frame_filter)
        plain = format_observation(snapshot)
        prev = state.get("prev_observation")
        no_progress = state.get("no_progress", 0)
        if prev is not None:
            no_progress = no_progress + 1 if plain == prev else 0
        if no_progress >= MAX_REPEAT:
            reason = f"stuck: {MAX_REPEAT} steps with no change on screen"
            stop = AgentStep(n=n, kind="done", reasoning=reason, url=snapshot.url, error=reason)
            return {"n": n, "steps": [stop], "stopped_reason": reason, "jump_to": "end"}
        seen = list(state.get("texts_seen") or [])
        known = set(seen)
        seen += [t.text for t in snapshot.texts if t.text not in known][:50]
        return {
            "n": n, "snapshot": snapshot, "observation": plain, "prev_observation": plain,
            "prev_url": snapshot.url, "no_progress": no_progress, "texts_seen": seen[-400:],
        }

    async def awrap_model_call(self, request: ModelRequest[ExplorerContext], handler) -> ModelResponse:
        ctx = request.runtime.context
        system = build_system_prompt_v2(ctx.allowed_kinds, ctx.max_actions_per_step)
        static, dynamic = render_prompt(system, ctx.task, request.state["observation"], ctx.memory.history)
        return await handler(request.override(
            system_message=SystemMessage(content=static), messages=[HumanMessage(content=dynamic)],
        ))

    @hook_config(can_jump_to=["end", "model"])
    async def aafter_model(self, state: ExplorerV2State, runtime: Runtime[ExplorerContext]) -> dict[str, Any] | None:
        ctx = runtime.context
        n = state["n"]
        last = state["messages"][-1]
        calls = list(getattr(last, "tool_calls", None) or [])
        if not isinstance(last, AIMessage) or not calls:
            # A turn without a tool call is an invalid decision: costs the step, never ends the run.
            logger.warning("step %d: no tool call in the model's reply", n)
            ctx.memory.history.append(StepRecord(
                n=n, kind="invalid", outcome="invalid", error="no tool call",
                reasoning="(your last reply was not a tool call) — call a tool",
            ))
            return {"prev_observation": None, "jump_to": "model"}
        for tc in calls:
            logger.info("step %d: %s — %s", n, tc["name"], tc["args"].get("reasoning", ""))

        finish = next((tc for tc in calls if tc["name"] == "done"), None)
        if finish is not None:
            args = finish["args"]
            reasoning = str(args.get("reasoning", ""))
            step = AgentStep(n=n, kind="done", reasoning=reasoning, url=state["snapshot"].url)
            closing = [ToolMessage(content="run ended", tool_call_id=tc["id"]) for tc in calls]
            return {
                "steps": [step], "success": bool(args.get("success", False)), "stopped_reason": reasoning,
                "messages": closing, "jump_to": "end",
            }

        update: dict[str, Any] = {}
        if len(calls) > ctx.max_actions_per_step:  # browser-use truncates (agent/service.py:1957); so do we
            calls = calls[: ctx.max_actions_per_step]
            update["messages"] = [AIMessage(content=last.content, tool_calls=calls, id=last.id)]
        first = calls[0]
        a = first["args"]
        key = f"{first['name']}|{a.get('index')}|{a.get('text') or a.get('value') or a.get('url') or ''}"
        repeat = state.get("repeat_count", 0) + 1 if key == state.get("last_action_key") else 1
        if repeat >= REPEAT_STOP:
            reason = f"stuck: repeated the same action {repeat} times ({first['name']} on element {a.get('index')})"
            stop = AgentStep(n=n, kind="done", reasoning=reason, url=state["snapshot"].url, error=reason)
            closing = [ToolMessage(content="run ended", tool_call_id=tc["id"]) for tc in calls]
            return {"steps": [stop], "stopped_reason": reason, "messages": closing, "jump_to": "end"}
        if repeat >= REPEAT_NUDGE:
            ctx.memory.history.append(StepRecord(
                n=n, kind="note",
                note=f"{n}. you have now issued the SAME action {repeat} times ({first['name']} on "
                f"[{a.get('index')}]) and the goal is still not reached — it is not working. Do something "
                "different, or if the task's outcome is already visible, declare done.",
            ))
        update.update({"last_action_key": key, "repeat_count": repeat})
        return update
