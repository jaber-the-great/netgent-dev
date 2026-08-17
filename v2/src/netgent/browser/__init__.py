"""Playwright layer: session/context lifecycle, capture contract, element resolution,
trigger evaluation, and observation. The only package that imports playwright.

Import rule: imports core. Never imports an LLM SDK — `netgent run` must work with no
model provider configured.
"""
