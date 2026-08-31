"""The v2 system prompt: v1's prompt (observation legend, grounding, forms, dropdowns, …) with
the DECISION FIELDS contract restated as tool calls."""

from netgent.agent.explorer.prompt import build_system_prompt as _v1_prompt

_TOOLS_HEADER = """You act by calling TOOLS. Each tool is one atomic action (click, fill, select, …) and takes the
fields described under DECISION FIELDS below as its arguments (index, text, value, reasoning, …).
Call at most {max_calls} tool{plural} per turn{order}. To END the run call the `done` tool
with success=true only if every TASK requirement is met (false = you are giving up; say why).
Never reply with plain text: every turn is a tool call.

"""


def build_system_prompt_v2(allowed_kinds: frozenset[str], max_actions: int = 1) -> str:
    header = _TOOLS_HEADER.format(
        max_calls=max_actions,
        plural="" if max_actions == 1 else "s",
        order="" if max_actions == 1 else ", in the order they should run on the SAME page",
    )
    return header + _v1_prompt(allowed_kinds, max_actions)
