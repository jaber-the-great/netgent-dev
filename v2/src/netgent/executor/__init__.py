"""Run-time NFA executor: traverses a compiled workflow (states + transitions), evaluates
state conditions via the browser layer's trigger engine, and dispatches each edge's atomic
action. Zero LLM calls — this is what `netgent run` invokes.

Import rule: imports core and browser. Never imports an LLM SDK.
"""
