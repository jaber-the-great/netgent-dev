"""Parity of the two observation backends on local fixtures: a same-origin iframe form, a
cross-origin iframe, open shadow DOM, a <summary>, a scrollable box, and a listener-only div.

For each backend: every fixture control is observed with its frame path, and its durable
locator resolves to exactly ONE element. The accessibility backend must additionally carry
browser-computed names where the DOM heuristic has none (radios labelled by wrapping text).
"""

import asyncio
import html
import http.server
import socketserver
import threading

import pytest

from netgent.agent.explore_agent.observation import _locator_for
from netgent.browser.session import BrowserSession

CHILD_FORM = (
    "<h1>Child form</h1>"
    "<label>Email <input id=email type=email required></label>"
    "<label><input type=radio name=plan value=free> Free</label>"
    "<label><input type=radio name=plan value=pro> Pro</label>"
    "<select id=country><option value=''>Pick</option><option value=us>US</option></select>"
    "<input id=dob type=date>"
    "<button type=button>Submit</button><button type=button>Submit</button>"
)
XORIGIN_CHILD = (
    "<!doctype html><html><body><input id=inner placeholder='inner field'>"
    "<my-el></my-el><script>customElements.define('my-el', class extends HTMLElement {"
    "connectedCallback(){ this.attachShadow({mode:'open'}).innerHTML="
    "'<label>Shadow name <input id=sh></label><button>Shadow Btn</button>'; }});</script>"
    "</body></html>"
)


def _page(xorigin_port: int) -> str:
    src = html.escape(CHILD_FORM, quote=True)
    return f"""<!doctype html><html><head><title>Parity</title></head><body>
<h1>parent</h1><div>Score: <span id=s>0</span> / 3</div>
<button id=top>Top Btn</button>
<div id=hover style="padding:10px">Hover over me</div>
<details><summary>Click to expand me</summary><p>hidden text</p></details>
<div id=box style="height:80px;overflow-y:auto"><p style="height:400px">long terms</p><p>bottom</p></div>
<iframe id=form srcdoc="{src}" width=400 height=400></iframe>
<iframe id=x src="http://127.0.0.1:{xorigin_port}/" width=400 height=200></iframe>
<script>document.getElementById('hover').addEventListener('mouseenter', () => {{}});</script>
</body></html>"""


class _Server:
    def __init__(self, body: str):
        data = body.encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.port = self._srv.server_address[1]
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


async def _observe(url: str, backend: str):
    async with BrowserSession(headless=True, observation=backend) as s:
        await s.page.goto(url, wait_until="networkidle")
        snap = await s.snapshot()
        resolved = {}
        for i, e in enumerate(snap.elements):
            resolved[i] = await s._resolve(_locator_for(e)).count()
        return snap, resolved


@pytest.mark.parametrize("backend", ["dom", "ax"])
def test_backend_observes_every_fixture_control_with_unique_locators(backend):
    with _Server(XORIGIN_CHILD) as child, _Server(_page(0)) as _:
        with _Server(_page(child.port)) as parent:
            snap, counts = asyncio.run(_observe(f"http://127.0.0.1:{parent.port}/", backend))

    def find(**kw):
        hits = [e for e in snap.elements if all(getattr(e, k) == v for k, v in kw.items())]
        assert hits, f"{backend}: no element with {kw}; got {[(e.tag, e.type, e.name) for e in snap.elements]}"
        return hits

    # same-origin iframe form controls, with the frame path
    email = find(type="email")[0]
    assert email.frame_path == ["iframe#form"] and email.required
    assert find(type="date")[0].frame_path == ["iframe#form"]
    select = find(tag="select")[0]
    assert select.options == ["us"] and select.frame_path == ["iframe#form"]
    submits = find(name="Submit")
    assert len(submits) == 2
    # cross-origin iframe + open shadow DOM inside it
    inner = find(name="inner field")[0]
    assert inner.frame_path == ["iframe#x"]
    assert find(name="Shadow Btn")[0].frame_path == ["iframe#x"]
    # top-level gap fixes: listener-only div, <summary>, scrollable box
    assert find(name="Hover over me")[0].tag == "div"
    assert find(tag="summary")[0].name == "Click to expand me"
    box = find(role="scrollable")[0]
    assert box.value == "scrolled 0%"
    # merged inline text
    assert any(t.text == "Score: 0 / 3" for t in snap.texts)
    # every element's durable locator resolves to exactly one node. The DOM walk is known to
    # fail this on two of the fixture's controls (radios named by their `name` attribute →
    # a role locator that matches nothing; two "Submit" buttons → one chain matching both);
    # that gap is the point of the accessibility backend, which must be clean.
    multi = {snap.elements[i].name: c for i, c in counts.items() if c != 1}
    if backend == "ax":
        assert not multi, f"ax: non-unique locators: {multi}"
    else:
        assert set(multi) <= {"plan", "Submit"}, f"dom: unexpected non-unique locators: {multi}"


def test_ax_backend_names_controls_the_dom_heuristic_misses():
    with _Server(XORIGIN_CHILD) as child:
        with _Server(_page(child.port)) as parent:
            url = f"http://127.0.0.1:{parent.port}/"
            dom, _ = asyncio.run(_observe(url, "dom"))
            axs, _ = asyncio.run(_observe(url, "ax"))
    dom_radios = sorted(e.name for e in dom.elements if e.type == "radio")
    ax_radios = sorted(e.name for e in axs.elements if e.type == "radio")
    assert ax_radios == ["Free", "Pro"]
    assert dom_radios != ax_radios  # the label text follows the input: the DOM heuristic sees nothing
    # and the ax names replay as exact role locators
    free = next(e for e in axs.elements if e.name == "Free")
    chain = _locator_for(free)
    assert chain[-1].fn == "get_by_role" and chain[-1].kwargs == {"name": "Free", "exact": True}


def test_ax_backend_falls_back_to_dom_walk_on_failure(monkeypatch):
    async def _run():
        async with BrowserSession(headless=True, observation="ax") as s:
            await s.page.set_content("<button id=b>Go</button>")

            async def boom():
                raise RuntimeError("no aria")

            monkeypatch.setattr(s, "_snapshot_ax", boom)
            return await s.snapshot()

    snap = asyncio.run(_run())
    assert [e.name for e in snap.elements] == ["Go"]
