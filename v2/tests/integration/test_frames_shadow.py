"""Iframe + shadow-DOM robustness fixtures (docs/research/iframes-shadow-dom.md, R1–R8).

Each test is the fixture the research document prescribes for one recommendation. Pages are
served from local threaded servers (`serve` fixture); cross-origin = a second loopback port.
"""

import asyncio

import pytest

from netgent.browser.locators import durable_locator, unique_locator_for
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
            assert await s.count(durable_locator(emails[1])) == 2

            # The verified chain resolves to exactly one element — the SECOND instance.
            chain = await unique_locator_for(s, emails[1])
            assert chain[-1].fn == "nth", chain
            assert await s.count(chain) == 1
            await s.resolve(chain).fill("second@example.com", timeout=3000)
            second = await s.page.evaluate(
                "() => document.querySelectorAll('my-form')[1].shadowRoot.getElementById('email').value"
            )
            first = await s.page.evaluate(
                "() => document.querySelectorAll('my-form')[0].shadowRoot.getElementById('email').value"
            )
            go = await unique_locator_for(s, gos[0])
            assert await s.count(go) == 1
            await s.resolve(go).click(timeout=3000)
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
            await s.resolve(durable_locator(pay)).click()
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
            original = s._dom._frame_info

            async def stalled(frame, cache=None):
                if frame.parent_frame is not None:
                    await asyncio.sleep(0.4)
                return await original(frame, cache)

            s._dom._frame_info = stalled
            snap = await s.snapshot()
            # The runtime backstop for a chain ending on a FrameLocator (schema rejects it
            # in artifacts; this covers hand-built chains reaching resolve directly).
            with pytest.raises(LocatorResolutionError, match="FrameLocator"):
                s.resolve([LocatorStep(fn="frame_locator", args=["iframe"])])
            return snap

    snap = asyncio.run(_run())
    assert [e.name for e in snap.elements] == ["Stay"]  # the top frame is never lost
    assert snap.frames_skipped == 1
    assert len(snap.skipped_frames) == 1 and "srcdoc" in snap.skipped_frames[0]
    from netgent.browser.dom import format_observation

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
    from netgent.browser.locators import capture_locator
    from netgent.browser.normalized import chain_from_normalized

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
    # The title-only iframe is addressed by attribute, never by a positional path (ours and
    # Playwright's generator agree on iframe[title="Pay"] since R7; before R7 the swap did it).
    card = next(r for r in results if r[0] == "Card")
    assert card[5][0].args == ['iframe[title="Pay"]'], card[5]
    # Two hops deep and iframe-in-shadow: both agree and stay unique.
    assert sum(1 for r in results if r[0] == "deep field") == 2


# ── R5: a 3000px document inside a 400px cross-origin iframe; the button is at the bottom ──

TALL_CHILD = """<!doctype html><html><head><title>Tall</title></head><body style="margin:0">
<input id="first" placeholder="first field">
<div style="height:2900px"></div>
<button id="bottom">Bottom</button>
</body></html>"""


def test_r5_scroll_reaches_into_a_cross_origin_iframe(serve):
    from netgent.agent.explorer.actions import to_action
    from netgent.agent.explorer.decision import AgentDecision

    child = serve({"/": TALL_CHILD})
    parent = serve({"/": (
        '<!doctype html><html><head><title>Host</title></head><body style="margin:0">'
        '<div style="height:100px">top</div>'
        f'<iframe id="tall" src="{child.url()}" width="500" height="400" style="border:0"></iframe>'
        '<div style="height:2000px">filler</div></body></html>'
    )})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(parent.url(), wait_until="networkidle")
            snap = await s.snapshot()
            scoped = snap.scoped_to(["iframe#tall"])
            assert {e.name for e in scoped.elements} == {"first field", "Bottom"}
            # A frame-scoped observation anchors the scroll on the frame (no index needed).
            action = to_action(AgentDecision(reasoning="x", kind="scroll", down=True, pages=10), scoped)
            assert action.locator is not None
            await s.dispatch(action)
            await s.page.wait_for_timeout(300)
            inner = await s.page.frame_locator("iframe#tall").locator("body").evaluate("() => window.scrollY")
            outer = await s.page.evaluate("() => window.scrollY")
            # The plain (unanchored) scroll still moves the top frame.
            await s.dispatch(to_action(AgentDecision(reasoning="x", kind="scroll", down=True, pages=1), snap))
            await s.page.wait_for_timeout(300)
            outer_after = await s.page.evaluate("() => window.scrollY")
            return inner, outer, outer_after

    inner, outer, outer_after = asyncio.run(_run())
    assert inner >= 2500, inner  # the iframe scrolled to its bottom
    assert outer == 0  # the top frame did not move
    assert outer_after > 0


# ── R6: an element in an iframe with border + padding — bbox must match bounding_box() ──

def test_r6_bbox_is_in_top_viewport_coordinates_on_both_axes(serve):
    child = serve({"/": '<!doctype html><html><body style="margin:0"><div style="height:37px"></div>'
                        '<button id="b" style="margin-left:23px">In frame</button></body></html>'})
    parent = serve({"/": (
        '<!doctype html><html><body style="margin:0"><div style="height:50px;width:70px"></div>'
        f'<iframe id="f" src="{child.url()}" style="border:8px solid red;padding:5px;margin-left:30px;'
        'width:300px;height:200px"></iframe></body></html>'
    )})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(parent.url(), wait_until="networkidle")
            snap = await s.snapshot()
            el = next(e for e in snap.elements if e.name == "In frame")
            truth = await s.page.frame_locator("iframe#f").locator("#b").bounding_box()
            return el.bbox, truth

    bbox, truth = asyncio.run(_run())
    assert abs(bbox.x - truth["x"]) <= 1 and abs(bbox.y - truth["y"]) <= 1, (bbox, truth)
    assert bbox.x >= 30 + 8 + 5 + 23  # margin + border + padding + inner margin


# ── R7: two sibling iframes sharing a class (no id/name) + a legacy <frame> in a frameset ──

def test_r7_frame_selectors_are_unique_and_use_the_real_tag(serve):
    leaf_a = serve({"/": '<!doctype html><html><body><input placeholder="in A"></body></html>'})
    leaf_b = serve({"/": '<!doctype html><html><body><input placeholder="in B"></body></html>'})
    frameset = serve({"/": (
        '<!doctype html><html><head><title>Legacy</title></head>'
        f'<frameset cols="50%,50%"><frame name="left" src="{leaf_a.url()}"><frame src="{leaf_b.url()}"></frameset>'
        '</html>'
    )})
    top = serve({"/": (
        '<!doctype html><html><body>'
        f'<iframe class="two" src="{leaf_a.url()}"></iframe><iframe class="two" src="{leaf_b.url()}"></iframe>'
        f'<iframe id="legacy" src="{frameset.url()}" width="600" height="200"></iframe>'
        '</body></html>'
    )})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(top.url(), wait_until="networkidle")
            snap = await s.snapshot()
            out = []
            for el in snap.elements:
                # every frame path resolves strictly (no 'resolved to N elements')
                n = await s.count(durable_locator(el))
                out.append((el.name, el.frame_path, n))
            return snap.frames_skipped, out

    skipped, out = asyncio.run(_run())
    assert skipped == 0
    paths = {tuple(p) for _, p, _ in out}
    assert len(paths) == 4, out  # two .two iframes + two legacy frames: four distinct paths
    assert all(n == 1 for _, _, n in out), out
    twos = sorted(p[0] for p in paths if len(p) == 1)
    assert twos == ["iframe.two >> nth=0", "iframe.two >> nth=1"] or all(":nth-of-type" in t for t in twos), twos
    legacy = sorted(p[1] for p in paths if len(p) == 2)
    assert legacy[0].startswith("frame") and 'frame[name="left"]' in legacy, legacy


# ── R8: closed shadow roots — observe (CDP, from outside the page), act (Patchright), flag ──

from netgent.browser.session import PATCHED_BROWSER  # noqa: E402

# The page echoes what happens INSIDE its closed root into light DOM (#echo) — the only way a
# test can read it without a page-side hook, which is precisely what we no longer install.
CLOSED_ROOT = """<!doctype html><html><head><title>Closed</title></head><body>
<div id="host"></div>
<div id="leak">unknown</div>
<div id="echo"></div>
<script>
const r = document.getElementById('host').attachShadow({mode: 'closed'});
r.innerHTML = '<input id="ci" placeholder="closed input"><button id="cb" type="button">Closed Submit</button>'
  + '<output id="out"></output>';
r.getElementById('ci').addEventListener('input', () => {
  document.getElementById('echo').textContent = 'value:' + r.getElementById('ci').value;
});
r.getElementById('cb').addEventListener('click', () => {
  r.getElementById('out').textContent = 'clicked:' + r.getElementById('ci').value;
  document.getElementById('echo').textContent = r.getElementById('out').textContent;
});
// The page's OWN encapsulation check must be UNCHANGED by our observation.
const sealed = document.getElementById('host').shadowRoot === null;
document.getElementById('leak').textContent = sealed ? 'still-closed' : 'LEAKED';
</script></body></html>"""


@pytest.mark.skipif(not PATCHED_BROWSER, reason="closed-shadow observation requires Patchright")
def test_r8a_closed_root_over_http_observed_acted_flagged(serve):
    from netgent.browser.dom import format_observation
    from netgent.browser.locators import capture_locator

    srv = serve({"/": CLOSED_ROOT})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            snap = await s.snapshot()
            ci = next((e for e in snap.elements if e.name == "closed input"), None)
            cb = next((e for e in snap.elements if e.name == "Closed Submit"), None)
            assert ci is not None and cb is not None, "closed-root elements must be observed"
            assert ci.requires_closed_shadow and cb.requires_closed_shadow
            obs = format_observation(snap)
            # Act through Patchright natively (fill + click both pierce the closed root).
            chain, note = await capture_locator(s, ci)
            await s.resolve(chain).fill("secret", timeout=3000)
            btn, _ = await capture_locator(s, cb)
            await s.resolve(btn).click(timeout=3000)
            # The effect inside the closed root, as the page itself reports it (light-DOM echo) —
            # input_value() on a closed-root locator hangs under Patchright, so read the echo.
            out = await s.page.locator("#echo").inner_text()
            leak = await s.page.locator("#leak").inner_text()
            # A second observation sees the new value INSIDE the closed root (CDP re-walk).
            after = next(e for e in (await s.snapshot()).elements if e.name == "closed input")
            return ci, obs, out, leak, after.value

    ci, obs, out, leak, value = asyncio.run(_run())
    assert leak == "still-closed", "observing must NOT flip the page's own shadowRoot===null check"
    assert out == "clicked:secret"  # fill AND click landed inside the closed root
    assert value == "secret"
    assert "|SHADOW(closed)|" in obs


@pytest.mark.skipif(not PATCHED_BROWSER, reason="closed-shadow observation requires Patchright")
def test_r8b_closed_root_inside_cross_origin_iframe(serve):
    child = serve({"/": CLOSED_ROOT})
    parent = serve({"/": (
        '<!doctype html><html><head><title>Host</title></head><body>'
        f'<iframe id="cf" src="{child.url()}" width="400" height="200"></iframe></body></html>'
    )})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(parent.url(), wait_until="networkidle")
            snap = await s.snapshot()
            ci = next((e for e in snap.elements if e.name == "closed input"), None)
            assert ci is not None, "closed root inside a cross-origin iframe must be observed"
            assert ci.frame_path == ["iframe#cf"] and ci.requires_closed_shadow
            from netgent.browser.locators import unique_locator_for

            chain = await unique_locator_for(s, ci)
            await s.resolve(chain).fill("xframe-secret", timeout=3000)
            val = await s.page.frame_locator("iframe#cf").locator("#echo").inner_text()
            leak = await s.page.frame_locator("iframe#cf").locator("#leak").inner_text()
            return val, leak

    val, leak = asyncio.run(_run())
    assert val == "value:xframe-secret"
    assert leak == "still-closed"


DECLARATIVE_CLOSED = """<!doctype html><html><head><title>Decl</title></head><body>
<div id="d"><template shadowrootmode="closed"><button id="db" type="button">Declarative</button></template></div>
<button id="real" type="button">Real</button>
<div id="echo"></div>
<script>
document.getElementById('real').addEventListener('click', () => {
  document.getElementById('echo').textContent = 'real';
});
</script>
</body></html>"""


@pytest.mark.skipif(not PATCHED_BROWSER, reason="requires Patchright")
def test_r8c_declarative_closed_shadow_is_observed_and_flagged(serve):
    """A `<template shadowrootmode="closed">` root never calls attachShadow, so the old
    page-side registry could not see it. The CDP read (DOM.describeNode pierce) lists it like
    any other closed root: observed, flagged, and — Patchright's pierce is the same call —
    actionable."""
    from netgent.browser.locators import capture_locator

    srv = serve({"/": DECLARATIVE_CLOSED})

    async def _run():
        async with BrowserSession(headless=True) as s:
            await s.page.goto(srv.url(), wait_until="networkidle")
            snap = await s.snapshot()
            decl = next((e for e in snap.elements if e.name == "Declarative"), None)
            assert decl is not None and decl.requires_closed_shadow
            chain, _ = await capture_locator(s, decl)
            await s.resolve(chain).click(timeout=3000)  # resolves through the closed root
            return [e.name for e in snap.elements]

    names = asyncio.run(_run())
    assert "Declarative" in names
    assert "Real" in names  # the ordinary top-frame button is still observed
