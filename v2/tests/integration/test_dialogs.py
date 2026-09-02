"""JavaScript dialogs reach the observation (browser/dialogs.py).

The measured failure: browser-use's Vanilla HTML form confirms submission ONLY via alert();
Playwright auto-dismissed it, the DOM never changed, the agent re-clicked submit until the
stuck detector fired. Now the dialog is accepted and shows up once in the next snapshot.
"""

import asyncio

from netgent.browser import BrowserSession
from netgent.browser.dom import format_observation

ALERT_FORM = """<!doctype html><html><head><title>Alert</title></head><body>
<form id="f"><input id="email" placeholder="Email" required><button id="go" type="submit">Submit Form</button></form>
<script>
document.getElementById('f').addEventListener('submit', (e) => {
  e.preventDefault();
  alert('Form submitted successfully! The secret is: dumbledore');
});
</script></body></html>"""


def test_alert_is_accepted_and_observed_once(serve):
    srv = serve({"/": ALERT_FORM})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            before = await s.snapshot()
            await s.page.locator("#email").fill("a@b.co")
            await s.page.locator("#go").click()
            await s.page.wait_for_timeout(200)
            after = await s.snapshot()
            again = await s.snapshot()
            # the page was not blocked by the dialog: it still responds
            title = await s.page.title()
            return before.dialogs, after.dialogs, again.dialogs, format_observation(after), title

    before, after, again, obs, title = asyncio.run(_run())
    assert before == []
    assert after == ["alert: Form submitted successfully! The secret is: dumbledore"]
    assert again == []  # drained: an event, shown at the step it happened
    assert "DIALOGS" in obs and "dumbledore" in obs
    assert title == "Alert"


PROMPT_CONFIRM = """<!doctype html><html><head><title>PC</title></head><body>
<button id="go" type="button">Run</button><div id="echo"></div>
<script>
document.getElementById('go').addEventListener('click', () => {
  const ok = confirm('Proceed?');
  const name = prompt('Your name?', 'Ada');
  document.getElementById('echo').textContent = 'confirm=' + ok + ' name=' + name;
});
</script></body></html>"""


def test_confirm_accepted_and_prompt_answered_with_default(serve):
    srv = serve({"/": PROMPT_CONFIRM})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            await s.page.locator("#go").click()
            await s.page.wait_for_timeout(200)
            echo = await s.page.locator("#echo").inner_text()
            snap = await s.snapshot()
            return echo, snap.dialogs

    echo, dialogs = asyncio.run(_run())
    assert echo == "confirm=true name=Ada"  # confirm accepted, prompt answered with its default
    assert dialogs == ["confirm: Proceed?", 'prompt: Your name?  (answered "Ada")']


def test_dialog_matches_trigger_recognizes_an_alert_only_submit(serve):
    """Replay path: dispatch the submit through the session (the dispatcher marks the edge),
    then wait_for_state on a dialog_matches condition — the mechanism a compiled workflow
    uses when a dialog is the page's only feedback. A later edge must NOT re-match it."""
    import re

    import pytest

    from netgent.core.errors import TriggerTimeoutError
    from netgent.schema.actions import ClickAction, FillAction, LocatorStep
    from netgent.schema.workflow import State

    srv = serve({"/": ALERT_FORM})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            await s.dispatch(FillAction(locator=[LocatorStep(fn="locator", args=["#email"])], text="a@b.co"))
            await s.dispatch(ClickAction(locator=[LocatorStep(fn="locator", args=["#go"])]))
            submitted = State(
                id="submitted",
                conditions=[{"type": "dialog_matches", "pattern": re.escape("alert: Form submitted successfully")}],
                timeout_ms=3000,
            )
            latency = await s.wait_for_state(submitted)
            # A later edge (new mark) must not be satisfied by the OLD dialog.
            await s.dispatch(FillAction(locator=[LocatorStep(fn="locator", args=["#email"])], text="x@y.co"))
            stale = State(id="stale", conditions=list(submitted.conditions), timeout_ms=400)
            with pytest.raises(TriggerTimeoutError):
                await s.wait_for_state(stale)
            return latency

    assert asyncio.run(_run()) >= 0


CHOOSER_BUTTON = """<!doctype html><html><head><title>FC</title></head><body>
<input id="real" type="file" style="display:none">
<button id="pick" type="button" onclick="document.getElementById('real').click()">Choose file</button>
</body></html>"""


def test_file_chooser_opened_by_a_click_is_reported(serve):
    from netgent.schema.actions import ClickAction, LocatorStep

    srv = serve({"/": CHOOSER_BUTTON})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            await s.dispatch(ClickAction(locator=[LocatorStep(fn="locator", args=["#pick"])], timeout_ms=3000))
            await s.page.wait_for_timeout(300)
            snap = await s.snapshot()
            return snap.dialogs, format_observation(snap)

    dialogs, obs = asyncio.run(_run())
    assert dialogs and dialogs[0].startswith("filechooser:")
    assert "upload action" in obs


def test_peeking_snapshot_leaves_the_dialog_for_the_next_real_observation(serve):
    """The settle watcher snapshots right after an action; it must PEEK (drain_dialogs=False),
    otherwise it consumes the submit's alert and the agent never sees its own success
    message (measured: re-submit loops on the vanilla stress form)."""
    srv = serve({"/": ALERT_FORM})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url("/"), wait_until="networkidle")
            await s.page.locator("#email").fill("a@b.co")
            await s.page.locator("#go").click()
            await s.page.wait_for_timeout(200)
            peek1 = await s.snapshot(drain_dialogs=False)
            peek2 = await s.snapshot(drain_dialogs=False)
            real = await s.snapshot()
            after = await s.snapshot()
            return peek1.dialogs, peek2.dialogs, real.dialogs, after.dialogs

    peek1, peek2, real, after = asyncio.run(_run())
    assert peek1 and peek1 == peek2 == real  # visible to peeks and to the draining observation
    assert after == []  # shown once
