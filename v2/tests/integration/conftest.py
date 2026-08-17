"""Integration tests drive a real headless Chromium via Playwright.

Set NETGENT_BROWSER_TESTS=1 to enable them, e.g.::

    NETGENT_BROWSER_TESTS=1 uv run pytest tests/integration

Without it the whole folder is skipped, so `pytest` stays instant on machines
without the Playwright browsers installed (`playwright install chromium`).

House rules (from the browser-layer research, docs/browser-layer-design.md §7):
mock only the LLM, never mock the browser; serve pages locally (pytest-httpserver
or file:// fixtures) — no live sites; live-site tests belong to the compiler and
are quarantined elsewhere.
"""

import os
from pathlib import Path

import pytest

# NOTE: `pytestmark` in a conftest.py is silently ignored by pytest, so the
# folder-wide gate is a collection hook instead. The hook receives the whole
# session's items, so it must scope itself to this directory.
_HERE = Path(__file__).parent
_SKIP = pytest.mark.skip(
    reason="NETGENT_BROWSER_TESTS not set — skipping browser integration tests"
)


def pytest_collection_modifyitems(items):
    if os.getenv("NETGENT_BROWSER_TESTS"):
        return
    for item in items:
        if _HERE in Path(item.fspath).parents:
            item.add_marker(_SKIP)
