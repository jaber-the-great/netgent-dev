"""Iframe + shadow-DOM robustness fixtures (docs/research/iframes-shadow-dom.md, R1–R8).

Each test is the fixture the research document prescribes for one recommendation. Pages are
served from local threaded servers (`serve` fixture); cross-origin = a second loopback port.
"""

import asyncio

import pytest

from netgent.agent.explore_agent.observation import _locator_for, unique_locator_for
from netgent.browser.session import BrowserSession

# ── R1: two instances of one web component, each exposing #email / #go in an open root ──

TWO_COMPONENTS = """<!doctype html><html><head><title>Dup</title></head><body>
<h1>Two forms</h1>
<my-form data-n="1"></my-form>
<my-form data-n="2"></my-form>
<script>
customElements.define('my-form', class extends HTMLElement {
  connectedCallback() {
    const root = this.attachShadow({mode: 'open'});
    root.innerHTML = `<form><input id="email" type="email" placeholder="Email">
      <button id="go" type="button">Go</button><output id="out"></output></form>`;
    root.getElementById('go').addEventListener('click', () =>
      root.getElementById('out').textContent = 'clicked ' + this.dataset.n);
  }
});
</script></body></html>"""


def test_r1_duplicate_shadow_ids_get_a_unique_chain(serve):
    srv = serve({"/": TWO_COMPONENTS})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            snap = await s.snapshot()
            emails = [e for e in snap.elements if e.tag == "input" and e.name == "Email"]
            gos = [e for e in snap.elements if e.tag == "button" and e.name == "Go"]
            assert len(emails) == 2 and len(gos) == 2, "both component instances must be observed"

            # The pure chain is ambiguous: #id pierces open shadow roots (2 matches).
            assert await s.count(_locator_for(emails[1])) == 2

            # The verified chain resolves to exactly one element — the SECOND instance.
            chain = await unique_locator_for(s, emails[1])
            assert chain[-1].fn == "nth", chain
            assert await s.count(chain) == 1
            await s._resolve(chain).fill("second@example.com", timeout=3000)
            second = await s.page.evaluate(
                "() => document.querySelectorAll('my-form')[1].shadowRoot.getElementById('email').value"
            )
            first = await s.page.evaluate(
                "() => document.querySelectorAll('my-form')[0].shadowRoot.getElementById('email').value"
            )
            go = await unique_locator_for(s, gos[0])
            assert await s.count(go) == 1
            await s._resolve(go).click(timeout=3000)
            out = await s.page.evaluate(
                "() => document.querySelectorAll('my-form')[0].shadowRoot.getElementById('out').textContent"
            )
            return second, first, out

    second, first, out = asyncio.run(_run())
    assert second == "second@example.com" and first == ""
    assert out == "clicked 1"


def test_r1_unique_id_keeps_the_plain_chain(serve):
    srv = serve({"/": '<!doctype html><html><body><input id="solo" placeholder="Solo"></body></html>'})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url())
            snap = await s.snapshot()
            el = next(e for e in snap.elements if e.name == "Solo")
            return await unique_locator_for(s, el)

    chain = asyncio.run(_run())
    assert [(st.fn, st.args) for st in chain] == [("locator", ["#solo"])]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
