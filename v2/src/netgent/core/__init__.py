"""Cross-cutting domain infrastructure: the error taxonomy and logging.

The pydantic models live in netgent.schema; core holds what every layer shares
that isn't a model.

Import rule: imports nothing but stdlib. No Playwright, no LLM SDKs.
"""
