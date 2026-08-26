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
(retried once in a fresh world — see `_in_world`), a target that closed — each is logged and
that document falls back to the plain (closed-blind) walk. A CDP failure never loses an
observation.

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

from collections.abc import Awaitable, Callable
from typing import Any

from netgent.core.logger import get_logger

logger = get_logger(__name__)

WORLD_NAME = "netgent-observe"


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
    """Observe elements inside closed shadow roots, per frame, without touching the page."""

    def __init__(self, page: Any, cdp: Any, walker_js: str, frame_selector_js: str):
        self._page = page
        self._cdp = cdp  # the page target's session (owned by BrowserSession, via factory.launch)
        self._walker_js = walker_js
        self._frame_selector_js = frame_selector_js
        # frameId → executionContextId of our isolated world. Worlds live in the renderer, not
        # in the session that created them, so the cache survives per-snapshot OOPIF sessions;
        # a navigation destroys the context and `_in_world` recreates it on the first failure.
        self._worlds: dict[str, int] = {}

    # ── CDP plumbing ─────────────────────────────────────────────────────────────

    async def _in_world(self, session: Any, frame_id: str, op: Callable[[int], Awaitable[Any]]) -> Any:
        """Run `op(executionContextId)` in the frame's isolated world.

        The world is created once per frame and cached. A navigation replaces the frame's
        document and destroys the context; Chrome reports that as `Cannot find context with
        specified id` from Runtime.* but as `Node with given id does not belong to the
        document` from DOM.resolveNode (measured) — so a cached world that fails for ANY reason
        is dropped and the call retried once in a fresh world, and only that failure raises.
        """
        fresh = frame_id not in self._worlds
        ctx = await self._world(session, frame_id)
        try:
            return await op(ctx)
        except Exception:  # noqa: BLE001 — stale world after a navigation, or a real failure
            if fresh:
                raise
            self._worlds.pop(frame_id, None)
            return await op(await self._world(session, frame_id))

    async def _world(self, session: Any, frame_id: str) -> int:
        if frame_id not in self._worlds:
            created = await session.send(
                "Page.createIsolatedWorld",
                {"frameId": frame_id, "worldName": WORLD_NAME, "grantUniveralAccess": False},
            )
            self._worlds[frame_id] = created["executionContextId"]
        return self._worlds[frame_id]

    async def _call(self, session: Any, frame_id: str, fn: str, args: list[dict]) -> Any:
        """Run `fn(*args)` in the frame's isolated world and return its JSON value."""

        async def op(ctx: int) -> Any:
            result = await session.send(
                "Runtime.callFunctionOn",
                {"functionDeclaration": fn, "executionContextId": ctx, "arguments": args, "returnByValue": True},
            )
            if "exceptionDetails" in result:
                raise RuntimeError(result["exceptionDetails"].get("text", "walker threw"))
            return result["result"].get("value")

        return await self._in_world(session, frame_id, op)

    async def _resolve(self, session: Any, frame_id: str, backend_node_id: int) -> dict:
        """A JS handle (CDP argument form) for a backend node, in the frame's isolated world."""

        async def op(ctx: int) -> dict:
            resolved = await session.send(
                "DOM.resolveNode", {"backendNodeId": backend_node_id, "executionContextId": ctx}
            )
            return {"objectId": resolved["object"]["objectId"]}

        return await self._in_world(session, frame_id, op)

    @staticmethod
    async def _capture(session: Any) -> dict:
        """DOMSnapshot.captureSnapshot — works without DOMSnapshot.enable on current Chrome
        (measured); the protocol docs list `enable`, so if a build insists, enable and retry."""
        params = {"computedStyles": []}
        try:
            return await session.send("DOMSnapshot.captureSnapshot", params)
        except Exception:  # noqa: BLE001
            await session.send("DOMSnapshot.enable")
            return await session.send("DOMSnapshot.captureSnapshot", params)

    async def _sessions(self) -> tuple[list[Any], list[Any]]:
        """(all distinct sessions, the ones we opened and must detach) — one per target."""
        opened: list[Any] = []
        sessions: list[Any] = [self._cdp]
        for frame in self._page.frames:
            if frame.parent_frame is None:
                continue
            try:
                session = await self._page.context.new_cdp_session(frame)
            except Exception:  # noqa: BLE001 — same-process frame: covered by an ancestor's session
                continue
            opened.append(session)
            sessions.append(session)
        return sessions, opened

    async def _frame_tree(self, sessions: list[Any]) -> dict[str, tuple[Any, str | None]]:
        """frameId → (session that owns it, parent frameId). OOPIF roots carry their parent's id."""
        owners: dict[str, tuple[Any, str | None]] = {}

        def walk(tree: dict, session: Any, parent: str | None) -> None:
            frame = tree["frame"]
            owners[frame["id"]] = (session, frame.get("parentId") or parent)
            for child in tree.get("childFrames") or ():
                walk(child, session, frame["id"])

        for session in sessions:
            try:
                walk((await session.send("Page.getFrameTree"))["frameTree"], session, None)
            except Exception as exc:  # noqa: BLE001 — a target that closed: its frames are gone anyway
                logger.debug("closed-shadow: frame tree unavailable: %s", exc)
        return owners

    async def _frame_path(self, frame_id: str, owners: dict[str, tuple[Any, str | None]]) -> list[str]:
        """The iframe selector chain for `frame_id` — the same strings `_frame_info` computes."""
        path: list[str] = []
        current = frame_id
        while owners.get(current, (None, None))[1]:
            parent = owners[current][1]
            parent_session = owners[parent][0]
            owner = await parent_session.send("DOM.getFrameOwner", {"frameId": current})
            handle = await self._resolve(parent_session, parent, owner["backendNodeId"])
            path.insert(0, await self._call(parent_session, parent, self._frame_selector_js, [handle]))
            current = parent
        return path

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
        handles = [await self._resolve(session, frame_id, root) for root in roots]
        raw = await self._call(session, frame_id, self._walker_js, handles)
        path = await self._frame_path(frame_id, owners)
        return tuple(path), raw

    async def observe(self) -> dict[tuple[str, ...], dict]:
        """{frame selector path: walker result} for every document containing a closed root.

        Documents without one are absent — the session walks those through Playwright as
        usual. Never raises: any per-document failure is logged and skipped.
        """
        results: dict[tuple[str, ...], dict] = {}
        sessions, opened = await self._sessions()
        try:
            candidates: list[tuple[Any, str, int]] = []  # (session, frameId, document backendNodeId)
            for session in sessions:
                try:
                    snap = await self._capture(session)
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
            owners = await self._frame_tree(sessions)
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
            for session in opened:
                try:
                    await session.detach()
                except Exception:  # noqa: BLE001 — target already gone
                    pass
