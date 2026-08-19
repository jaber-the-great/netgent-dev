"""The form sweep completes and VERIFIES multiple forms, driven by a scripted FakeLLM.

Two forms on one page (top document); each reveals a success sentinel on submit. The sweep
runs the agent per form and verifies each via the sentinel, not the agent's self-report.
"""

import asyncio
import html

from netgent.agent import AgentDecision, FakeLLM
from netgent.agent.sweep import sweep_forms
from netgent.browser.session import BrowserSession

# Each form lives in its OWN iframe — matching forms-comparison.html, which the sweep
# enumerates frame by frame. srcdoc iframes are same-origin (inherit the parent).
_CHILD = (
    "<input id=n placeholder=name>"
    "<button type=button onclick=\"if(n.value)document.getElementById('ok').style.display='block'\">Submit</button>"
    "<div id=ok style=display:none>the secret is: dumbledore</div>"
)
_SRC = html.escape(_CHILD, quote=True)  # safe inside a double-quoted srcdoc
PAGE = f"""<!doctype html><html><head><title>Two Forms</title></head><body>
<div><iframe srcdoc="{_SRC}" width=400 height=150></iframe></div>
<div><iframe srcdoc="{_SRC}" width=400 height=150></iframe></div>
</body></html>"""


def test_sweep_completes_and_verifies_each_form(tmp_path):
    page = tmp_path / "two.html"
    page.write_text(PAGE)

    # One scripted decision set reused per form (the agent is rebuilt per form in the sweep):
    # fill the (only) text field, click the (only) submit, done.
    def script():
        return FakeLLM(
            [
                AgentDecision(reasoning="fill the name", kind="fill", index=0, text="Ada"),
                AgentDecision(reasoning="submit", kind="click", index=1),
                AgentDecision(reasoning="submitted", kind="done", success=True),
            ]
        )

    class CyclingLLM:
        """Hands the sweep a fresh script each time it builds an agent."""

        def __init__(self):
            self._inner = script()

        async def decide(self, *a, **k):
            try:
                return await self._inner.decide(*a, **k)
            except AssertionError:
                self._inner = script()  # next form
                return await self._inner.decide(*a, **k)

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(page.as_uri(), wait_until="networkidle")
            return await sweep_forms(s, CyclingLLM(), max_steps_per_form=6)

    result = asyncio.run(_run())
    assert result.total == 2
    assert result.submitted == 2, [(f.form, f.submitted) for f in result.forms]
    assert all(f.submitted for f in result.forms)
