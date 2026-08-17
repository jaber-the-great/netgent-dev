"""Compile-time LLM side (`netgent generate`): the LangGraph pipeline — Planner ->
Discovery -> Workflow Generator -> Validation Agent — that compiles a natural-language
workflow spec into the NFA artifact.

Import rule: the ONLY package that imports LLM SDKs (langchain/langgraph, via the
`netgent[generate]` extra). Imports core, browser, executor.
"""
