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


# ── R2: a cross-origin payment iframe whose success banner appears INSIDE the frame ──

PAY_FRAME = """<!doctype html><html><head><title>Pay</title></head><body>
<input id="card" placeholder="Card number">
<button id="pay" type="button">Pay now</button>
<div id="banner" style="display:none" role="status">Payment accepted</div>
<div id="hint">Enter your card</div>
<script>document.getElementById('pay').addEventListener('click', () => {
  document.getElementById('banner').style.display = 'block';
  document.getElementById('hint').style.display = 'none';
  document.getElementById('banner').textContent = 'Payment accepted: ORD-42';
});</script></body></html>"""


def _pay_parent(child_url: str) -> str:
    return (
        '<!doctype html><html><head><title>Checkout</title></head><body><h1>Checkout</h1>'
        f'<iframe name="payframe" src="{child_url}" width="500" height="250"></iframe>'
        '</body></html>'
    )


def test_r2_triggers_and_param_sources_are_frame_aware(serve):
    from netgent.core.errors import TriggerTimeoutError
    from netgent.schema.control import ParamSource
    from netgent.schema.workflow import State

    child = serve({"/": PAY_FRAME})
    parent = serve({"/": _pay_parent(child.url())})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(parent.url(), wait_until="networkidle")
            frame = ["iframe[name=\"payframe\"]"]
            before = State(
                id="pay-form",
                conditions=[{"type": "selector_visible", "selector": "#pay", "frame_path": frame}],
                timeout_ms=3000,
            )
            await s.wait_for_state(before)  # in-frame element recognized

            # The same trigger WITHOUT a frame path is frame-blind (the documented bug):
            blind = State(id="blind", conditions=[{"type": "selector_visible", "selector": "#pay"}], timeout_ms=500)
            with pytest.raises(TriggerTimeoutError):
                await s.wait_for_state(blind)

            # selector_hidden: a selector that matches nothing must NOT hold ...
            typo = State(id="typo", conditions=[{"type": "selector_hidden", "selector": "#no-such"}], timeout_ms=300)
            with pytest.raises(TriggerTimeoutError):
                await s.wait_for_state(typo)
            # ... but a resolved-and-hidden in-frame element does.
            hidden = State(
                id="hidden",
                conditions=[{"type": "selector_hidden", "selector": "#banner", "frame_path": frame}],
                timeout_ms=1000,
            )
            await s.wait_for_state(hidden)

            pay = next(e for e in (await s.snapshot()).elements if e.name == "Pay now")
            await s._resolve(_locator_for(pay)).click()
            after = State(
                id="paid",
                conditions=[
                    {"type": "selector_visible", "selector": "#banner", "frame_path": frame},
                    {"type": "selector_hidden", "selector": "#hint", "frame_path": frame},
                ],
                timeout_ms=3000,
            )
            latency = await s.wait_for_state(after)
            code = await s.extract_value(ParamSource(kind="text", selector="#banner", frame_path=frame))
            blind_code = await s.extract_value(ParamSource(kind="text", selector="#banner"), timeout_ms=300)
            return latency, code, blind_code

    latency, code, blind_code = asyncio.run(_run())
    assert latency >= 0
    assert code == "Payment accepted: ORD-42"
    assert blind_code is None  # top-frame lookup cannot see into the iframe


# ── R3: an iframe that removes itself shortly after load — skipped, but REPORTED ──

SELF_REMOVING = """<!doctype html><html><head><title>Churn</title></head><body>
<button id="stay">Stay</button>
<iframe id="ad" srcdoc="<button id='inner'>Inner</button>"></iframe>
<script>
window.addEventListener('load', () => setTimeout(() => document.getElementById('ad').remove(), 100));
</script></body></html>"""


def test_r3_detached_frame_is_reported_not_swallowed(serve):
    from netgent.core.errors import LocatorResolutionError
    from netgent.schema.actions import LocatorStep

    srv = serve({"/": SELF_REMOVING})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="load")
            # Stall the walk on the child so the fixture's 100 ms self-removal fires while
            # the frame is still in page.frames — the detach then happens mid-snapshot.
            original = s._frame_info

            async def stalled(frame):
                if frame.parent_frame is not None:
                    await asyncio.sleep(0.4)
                return await original(frame)

            s._frame_info = stalled
            snap = await s.snapshot()
            # The runtime backstop for a chain ending on a FrameLocator (schema rejects it
            # in artifacts; this covers hand-built chains reaching _resolve directly).
            with pytest.raises(LocatorResolutionError, match="FrameLocator"):
                s._resolve([LocatorStep(fn="frame_locator", args=["iframe"])])
            return snap

    snap = asyncio.run(_run())
    assert [e.name for e in snap.elements] == ["Stay"]  # the top frame is never lost
    assert snap.frames_skipped == 1
    assert len(snap.skipped_frames) == 1 and "srcdoc" in snap.skipped_frames[0]
    from netgent.agent.explore_agent.observation import format_observation

    assert "1 frame(s) could not be observed" in format_observation(snap)


# ── R4: the hostile page — our chain and Playwright's normalize() chain must agree ──

HOSTILE_LEAF = """<!doctype html><html><head><title>Leaf</title></head><body>
<input id="d2" placeholder="deep field"><button id="deep-go">Deep go</button>
</body></html>"""

HOSTILE_MID = """<!doctype html><html><head><title>Mid</title></head><body>
<label for="mi">Middle</label><input id="mi">
<iframe id="inner" src="{leaf}"></iframe>
</body></html>"""

HOSTILE_PAY = """<!doctype html><html><head><title>Pay</title></head><body>
<div id="host"></div>
<script>
const r = document.getElementById('host').attachShadow({mode: 'open'});
r.innerHTML = '<input data-testid="cardno" placeholder="Card"><button data-testid="deepbtn">Pay</button>';
</script></body></html>"""


def _hostile_top(pay_url: str, mid_url: str, leaf_url: str) -> str:
    return f"""<!doctype html><html><head><title>Hostile</title></head><body>
<button id="top-btn">Top</button>
<iframe title="Pay" src="{pay_url}" width="400" height="120"></iframe>
<iframe id="nest" src="{mid_url}" width="400" height="300"></iframe>
<my-form data-n="1"></my-form><my-form data-n="2"></my-form>
<shadow-host></shadow-host>
<script>
customElements.define('my-form', class extends HTMLElement {{
  connectedCallback() {{
    const root = this.attachShadow({{mode: 'open'}});
    root.innerHTML = '<input id="email" placeholder="Email"><button id="go">Go</button>';
  }}
}});
customElements.define('shadow-host', class extends HTMLElement {{
  connectedCallback() {{
    const root = this.attachShadow({{mode: 'open'}});
    root.innerHTML = '<iframe id="fb" src="{leaf_url}" width="300" height="80"></iframe>';
  }}
}});
</script></body></html>"""


def test_r4_our_chains_agree_with_playwrights_normalized_chains(serve):
    from netgent.agent.explore_agent.normalized import chain_from_normalized
    from netgent.agent.explore_agent.observation import capture_locator

    leaf = serve({"/": HOSTILE_LEAF})
    mid = serve({"/": HOSTILE_MID.format(leaf=leaf.url())})
    pay = serve({"/": HOSTILE_PAY})
    top = serve({"/": _hostile_top(pay.url(), mid.url(), leaf.url())})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(top.url(), wait_until="networkidle")
            snap = await s.snapshot()
            assert snap.frames_skipped == 0
            results = []
            for el in snap.elements:
                ours = await unique_locator_for(s, el)
                theirs = chain_from_normalized(await s.normalize(ours))  # total: raises if unmappable
                same = await s.same_element(ours, theirs)
                stored, note = await capture_locator(s, el)
                results.append((el.name, el.frame_path, ours, theirs, same, stored, note, await s.count(stored)))
            return results

    results = asyncio.run(_run())
    names = sorted(r[0] for r in results)
    assert names == sorted(["Top", "Card", "Pay", "Middle", "deep field", "Deep go",
                            "Email", "Go", "Email", "Go", "deep field", "Deep go"]), names
    for name, frame_path, ours, theirs, same, stored, note, n in results:
        assert same, (name, frame_path, ours, theirs)
        assert n == 1, (name, stored)
        assert note.startswith("normalize agreed"), (name, note)
    # The title-only iframe: our path was positional; Playwright's iframe[title="Pay"] replaces it.
    card = next(r for r in results if r[0] == "Card")
    assert card[5][0].args == ['iframe[title="Pay"]'], card[5]
    assert "frame selectors" in card[6]
    # Two hops deep and iframe-in-shadow: both agree and stay unique.
    assert sum(1 for r in results if r[0] == "deep field") == 2
