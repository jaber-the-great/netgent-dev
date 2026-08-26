"""The form sweep completes and VERIFIES multiple forms, driven by a scripted FakeLLM.

Two forms on one page; each reveals a success sentinel on submit. ONE agent works both
forms in turn; the sweep verifies each via the sentinel, not the agent's self-report.
"""

import asyncio
import html

from netgent.agent import AgentDecision, FakeLLM
from netgent.browser.session import BrowserSession
from netgent.evals.sweep import sweep_forms

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

    # One scripted decision set per form: fill the (only) text field, click submit, done.
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


TRANSIENT_FORM = """<!doctype html><html><body>
<input id="e" placeholder="Email"><button id="go" type="button">Submit</button>
<div id="ok" role="status" style="display:none">Form submitted successfully!</div>
<script>
document.getElementById('go').addEventListener('click', () => {
  const ok = document.getElementById('ok');
  ok.style.display = 'block';
  setTimeout(() => { ok.style.display = 'none'; }, 700);  // transient: gone before post-run verify
});
</script></body></html>"""


def test_transient_success_banner_still_verifies(serve):
    """Formik-class banners hide themselves after a few seconds; the sweep verifies against
    the texts the agent's own observations SAW (traj.texts_seen), not only the final page."""
    import asyncio

    from netgent.agent.explorer.decision import AgentDecision
    from netgent.evals.sweep import sweep_forms

    parent = serve({"/": TRANSIENT_FORM})
    top = serve({"/": ('<!doctype html><html><body>'
                       f'<iframe id="tf" src="{parent.url()}" width="400" height="150"></iframe></body></html>')})

    class ScriptedLLM:
        def __init__(self):
            self._steps = iter([
                AgentDecision(reasoning="fill", kind="fill", index=0, text="a@b.co"),
                AgentDecision(reasoning="submit", kind="click", index=1),
                AgentDecision(reasoning="banner seen", kind="done", success=True),
            ])

        async def decide(self, *a, **k):
            return next(self._steps)

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(top.url(), wait_until="networkidle")
            return await sweep_forms(s, ScriptedLLM(), max_steps_per_form=6, retries=0)

    result = asyncio.run(_run())
    assert result.total == 1
    assert result.submitted == 1, result.forms[0]  # verified from texts_seen, not the (now hidden) banner
