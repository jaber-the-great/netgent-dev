"""Closed shadow roots, observed from OUTSIDE the page over CDP (R8, zero footprint).

The page never sees us. Nothing runs in the main world, no prototype is patched, no global is
defined, no attribute or element is added: every read below is a DevTools-protocol read on a
CDP session, and the one script we run (the DOM walker) runs in an isolated world we create
with `Page.createIsolatedWorld` — the same kind of world Playwright's own utility scripts use,
invisible to page JavaScript (separate global, shared DOM). Measured after a snapshot:
`Element.prototype.attachShadow.toString()` is native, `.name === "attachShadow"`, and
`window` has no `__`-prefixed own property (tests/integration/test_browser_profile.py).

Mechanism, per snapshot:

1. One CDP session per *target*: the page's own session covers the top frame and every
   same-process child frame; each out-of-process iframe (OOPIF) gets `new_cdp_session(frame)`
   — Playwright refuses that call for same-process frames ("part of the parent frame's
   session"), which is exactly how we tell the two apart.
2. `DOMSnapshot.captureSnapshot` on each session: a flat, cheap dump of every local document
   (1–5 ms measured) whose `shadowRootType` column says whether the document contains ANY
   closed shadow tree. Most pages contain none and stop here.
3. For a document that does: `DOM.describeNode(depth=-1, pierce=true)` — Patchright's own
   pierce (driver `_customFindElementsByParsed`) — lists every closed `ShadowRoot` with its
   `backendNodeId`, nested ones included, declarative (`<template shadowrootmode="closed">`)
   ones included. `DOM.resolveNode(backendNodeId, executionContextId=<our world>)` turns
   each into a JS handle in the isolated world and `Runtime.callFunctionOn` runs the same
   `DOM_SNAPSHOT_JS` walker the ordinary frames use, with those roots as arguments, so the
   walker descends into each closed root at its host's position (same element order).
4. The result is keyed by the frame's selector path — `FRAME_SELECTOR_JS` run on the owner
   `<iframe>` (`DOM.getFrameOwner`) in each ancestor's isolated world — which is the same
   string `DomObserver._frame_info` (dom/observer.py) computes with Playwright for the same
   frame, so the observer joins the two by an exact key instead of guessing frames by URL.

Everything is best-effort: a frame that detaches mid-way, a world destroyed by a navigation
(retried once in a fresh world — see `CdpFrames.in_world`, dom/cdp.py), a target that closed —
each is logged and that document falls back to the plain (closed-blind) walk. A CDP failure
never loses an observation.

Protocol references (chromedevtools.github.io/devtools-protocol): `DOM.describeNode` "does not
require domain to be enabled", `pierce` = "whether iframes and shadow roots should be traversed";
`DOM.resolveNode(backendNodeId, executionContextId)` = "execution context in which to resolve the
node"; `Page.createIsolatedWorld(frameId, worldName, grantUniveralAccess)` [sic] returns the
world's `executionContextId`; `DOMSnapshot.captureSnapshot` returns `documents[].frameId` and a
per-node `shadowRootType` = "type of the shadow root the Node is in". Playwright:
`BrowserContext.new_cdp_session(page | frame)` — "it can be a Page or Frame"; Patchright README:
"Patchright avoids using Runtime.enable by executing Javascript in (isolated) ExecutionContexts"
— the same discipline this module follows (no Runtime.enable, no main-world script).

No LLM, no Playwright import beyond duck-typed `page` / `cdp` objects (import boundary: this
package must not import langchain; it needn't import playwright either).
"""

from typing import Any

from netgent.browser.dom.cdp import CdpFrames
from netgent.core.logger import get_logger

logger = get_logger(__name__)


def _closed_root_ids(node: dict, out: list[int]) -> list[int]:
    """backendNodeIds of every closed ShadowRoot under `node` (DOM.describeNode pierce tree),
    NOT descending into <iframe> content documents — each frame is walked in its own world."""
    for root in node.get("shadowRoots") or ():
        if root.get("shadowRootType") == "closed" and root.get("backendNodeId"):
            out.append(root["backendNodeId"])
        _closed_root_ids(root, out)
    if node.get("nodeName") != "IFRAME":
        for child in node.get("children") or ():
            _closed_root_ids(child, out)
    return out


class ClosedShadowObserver:
    """Observe elements inside closed shadow roots, per frame, without touching the page.

    The CDP mechanics (sessions per target, frame tree, isolated worlds) are `CdpFrames`
    (dom/cdp.py), shared with the media observer so a frame gets ONE isolated world.
    """

    def __init__(self, frames: CdpFrames, walker_js: str):
        self._frames = frames
        self._walker_js = walker_js

    # ── the observation ─────────────────────────────────────────────────────────

    async def _observe_document(
        self, session: Any, frame_id: str, document_backend_id: int, owners: dict
    ) -> tuple[tuple[str, ...], dict] | None:
        described = await session.send(
            "DOM.describeNode", {"backendNodeId": document_backend_id, "depth": -1, "pierce": True}
        )
        roots = _closed_root_ids(described["node"], [])
        if not roots:
            return None
        handles = [await self._frames.resolve(session, frame_id, root) for root in roots]
        raw = await self._frames.call(session, frame_id, self._walker_js, handles)
        path = await self._frames.frame_path(frame_id, owners)
        return tuple(path), raw

    async def observe(self) -> dict[tuple[str, ...], dict]:
        """{frame selector path: walker result} for every document containing a closed root.

        Documents without one are absent — the session walks those through Playwright as
        usual. Never raises: any per-document failure is logged and skipped.
        """
        results: dict[tuple[str, ...], dict] = {}
        sessions, opened = await self._frames.sessions()
        try:
            candidates: list[tuple[Any, str, int]] = []  # (session, frameId, document backendNodeId)
            for session in sessions:
                try:
                    snap = await self._frames.capture(session)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("closed-shadow: captureSnapshot failed: %s", exc)
                    continue
                strings = snap["strings"]
                for doc in snap["documents"]:
                    nodes = doc["nodes"]
                    kinds = nodes.get("shadowRootType") or {}
                    if any(strings[v] == "closed" for v in kinds.get("value", ())):
                        candidates.append((session, strings[doc["frameId"]], nodes["backendNodeId"][0]))
            if not candidates:
                return results
            owners = await self._frames.frame_tree(sessions)
            for session, frame_id, doc_id in candidates:
                try:
                    observed = await self._observe_document(session, frame_id, doc_id, owners)
                except Exception as exc:  # noqa: BLE001 — detached frame / closed target / stale world
                    reason = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                    logger.warning("closed-shadow: frame %s not observed over CDP: %s", frame_id, reason)
                    continue
                if observed is not None:
                    results[observed[0]] = observed[1]
            return results
        finally:
            await self._frames.detach(opened)
