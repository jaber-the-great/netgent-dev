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
