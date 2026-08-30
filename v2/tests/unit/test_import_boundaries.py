"""Enforce the one-directional import rule: core ← browser ← executor ← agent.

Each check runs in a subprocess so a previously-imported module can't mask a violation.
`netgent run` must work with no LLM SDK installed, so browser/executor importing
langchain/langgraph is a hard failure, not a style issue.
"""

import subprocess
import sys

FORBIDDEN = {
    "netgent.schema": ["playwright", "langchain", "langgraph", "langchain_core"],
    "netgent.core": ["playwright", "langchain", "langgraph", "langchain_core"],
    "netgent.browser": ["langchain", "langgraph", "langchain_core"],
    "netgent.executor": ["langchain", "langgraph", "langchain_core"],
    "netgent.report": ["playwright", "langchain", "langgraph", "langchain_core"],
    # The agent package promises to load without the `generate` extra: langchain stays inside
    # LangChainLLM, langgraph inside the graph modules (explorer/graph.py is the only module-level
    # importer, resolved lazily from the package).
    "netgent.agent": ["langchain", "langgraph", "langchain_core"],
}


def _imports_after(module: str) -> set[str]:
    code = f"import {module}, sys; print(chr(10).join(sys.modules))"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


def test_import_boundaries():
    for module, forbidden in FORBIDDEN.items():
        loaded = _imports_after(module)
        violations = [pkg for pkg in forbidden if pkg in loaded]
        assert not violations, f"{module} pulled in forbidden packages: {violations}"
