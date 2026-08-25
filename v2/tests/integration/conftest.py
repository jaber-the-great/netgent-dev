"""Integration tests drive a real headless Chromium via Playwright.

Set NETGENT_BROWSER_TESTS=1 to enable them, e.g.::

    NETGENT_BROWSER_TESTS=1 uv run pytest tests/integration

Without it the whole folder is skipped, so `pytest` stays instant on machines
without the Playwright browsers installed (`playwright install chromium`).

House rules (from the browser-layer research, docs/browser-layer-design.md §7):
mock only the LLM, never mock the browser; serve pages locally (pytest-httpserver
or file:// fixtures) — no live sites; live-site tests belong to the compiler and
are quarantined elsewhere.
"""

import http.server
import os
import socketserver
import threading
from pathlib import Path

import pytest

# NOTE: `pytestmark` in a conftest.py is silently ignored by pytest, so the
# folder-wide gate is a collection hook instead. The hook receives the whole
# session's items, so it must scope itself to this directory.
_HERE = Path(__file__).parent
_SKIP = pytest.mark.skip(
    reason="NETGENT_BROWSER_TESTS not set — skipping browser integration tests"
)


def pytest_collection_modifyitems(items):
    if os.getenv("NETGENT_BROWSER_TESTS"):
        return
    for item in items:
        if _HERE in Path(item.fspath).parents:
            item.add_marker(_SKIP)


# ── Local fixture servers ────────────────────────────────────────────────────
#
# Cross-origin fixtures need two origins; two loopback ports are two origins. `serve`
# starts one static server per call (routes: path → html) and tears it down after the test.


class LocalServer:
    """A tiny threaded static server: `routes` maps a path ("/", "/child") to HTML (".js" paths → JS)."""

    def __init__(self, routes: dict[str, str]):
        pages = {path: html.encode() for path, html in routes.items()}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = pages.get(self.path.split("?", 1)[0])
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                ctype = "text/javascript" if self.path.split("?", 1)[0].endswith(".js") else "text/html; charset=utf-8"
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._srv.server_address[1]

    def url(self, path: str = "/") -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


@pytest.fixture
def serve():
    """Factory fixture: `srv = serve({"/": html})` → a running LocalServer (auto-closed)."""
    servers: list[LocalServer] = []

    def _start(routes: dict[str, str]) -> LocalServer:
        srv = LocalServer(routes).__enter__()
        servers.append(srv)
        return srv

    yield _start
    for srv in servers:
        srv.__exit__(None, None, None)
