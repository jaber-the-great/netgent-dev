"""Cross-origin iframe: observe AND act on an element in a frame from a different origin.

Two local servers on different ports are different origins. The parent page embeds the
child from the other port. Injected page JS could not read the child's DOM (same-origin
policy), but the snapshot walks each Playwright frame in its own context (CDP), so the
child's input is observed — and the resolved frame_locator chain fills it.
"""

import asyncio
import http.server
import socketserver
import threading

from netgent.agent.observation import _locator_for
from netgent.browser.session import BrowserSession

CHILD_HTML = """<!doctype html><html><head><title>Child</title></head><body>
<input id="inner" placeholder="inner field"><div id="echo"></div>
<script>document.getElementById('inner').addEventListener('input', e =>
  document.getElementById('echo').textContent = e.target.value);</script>
</body></html>"""


class _Server:
    def __init__(self, html: str):
        self._html = html.encode()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(outer._html)

            def log_message(self, *a):
                pass

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def port(self):
        return self._srv.server_address[1]

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


def test_cross_origin_iframe_observed_and_acted_on(tmp_path):
    with _Server(CHILD_HTML) as child:
        parent_html = (
            f'<!doctype html><html><head><title>Parent</title></head><body><h1>parent</h1>'
            f'<div class="wrap"><iframe src="http://127.0.0.1:{child.port}/" '
            f'width="400" height="200"></iframe></div></body></html>'
        )
        with _Server(parent_html) as parent:

            async def _run():
                async with BrowserSession(headless=True) as s:
                    await s.page.goto(f"http://127.0.0.1:{parent.port}/", wait_until="networkidle")
                    snap = await s.snapshot()
                    inner = next((e for e in snap.elements if e.name == "inner field"), None)
                    assert inner is not None, "cross-origin iframe input was not observed"
                    assert inner.frame_path, "element should carry a frame path"
                    # act on it through the resolved frame_locator chain
                    await s._resolve(_locator_for(inner)).fill("hello-xorigin", timeout=3000)
                    return await s._resolve(_locator_for(inner)).input_value()

            assert asyncio.run(_run()) == "hello-xorigin"
