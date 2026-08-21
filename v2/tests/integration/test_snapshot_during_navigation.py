"""A snapshot taken while the page navigates must retry, not raise.

`Page.evaluate: Execution context was destroyed` crashed a 21-form sweep at form 14 once —
the agent clicked Submit, the form navigated, and the next observe() walked a dying document.
"""

import asyncio

import pytest

from netgent.browser.session import BrowserSession


def test_snapshot_retries_after_navigation_error(monkeypatch):
    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.set_content("<button id=b>Go</button>")
            real = s._snapshot_dom
            calls = {"n": 0}

            async def flaky():
                calls["n"] += 1
                if calls["n"] < 3:
                    raise RuntimeError(
                        "Page.evaluate: Execution context was destroyed, most likely because of a navigation."
                    )
                return await real()

            monkeypatch.setattr(s, "_snapshot_dom", flaky)
            snap = await s.snapshot()
            return calls["n"], [e.name for e in snap.elements]

    assert asyncio.run(_run()) == (3, ["Go"])


def test_non_navigation_errors_still_raise(monkeypatch):
    async def _run():
        async with BrowserSession(headless=True) as s:
            async def boom():
                raise RuntimeError("something else")

            monkeypatch.setattr(s, "_snapshot_dom", boom)
            await s.snapshot()

    with pytest.raises(RuntimeError, match="something else"):
        asyncio.run(_run())


@pytest.mark.parametrize("backend", ["dom", "ax"])
def test_snapshot_survives_a_real_navigation(tmp_path, backend):
    second = tmp_path / "second.html"
    second.write_text("<!doctype html><title>Second</title><button id=done>Done</button>")
    first = tmp_path / "first.html"
    # navigate shortly after load, while snapshots are being taken
    first.write_text(
        f"<!doctype html><title>First</title><button>Go</button>"
        f"<script>setTimeout(() => location.href = '{second.as_uri()}', 30)</script>"
    )

    async def _run():
        async with BrowserSession(headless=True, observation=backend) as s:
            await s.page.goto(first.as_uri())
            titles = set()
            for _ in range(12):  # spans the navigation
                snap = await s.snapshot()
                titles.add(snap.title)
                await s.page.wait_for_timeout(10)
            return titles

    titles = asyncio.run(_run())
    assert "Second" in titles
