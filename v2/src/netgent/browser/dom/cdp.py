"""CDP plumbing shared by the out-of-page observers (closed shadow roots, media elements):
one session per target, the frame tree across targets, a frame's selector path, and one
isolated world per frame in which the injected scripts run.

Zero page footprint, the discipline of dom/closed_shadow.py: no `Runtime.enable` (Patchright
avoids it — the page can detect it), no main-world script, no global, no prototype patch.
Scripts run in a world created with `Page.createIsolatedWorld` — the same kind of world
Playwright's own utility scripts use: separate global, shared DOM, invisible to page JS.

Protocol references (chromedevtools.github.io/devtools-protocol): `Page.createIsolatedWorld
(frameId, worldName, grantUniveralAccess)` [sic] returns the world's `executionContextId`;
`Page.getFrameTree` "returns present frame tree structure"; `DOM.getFrameOwner(frameId)` returns
the owner iframe's `backendNodeId`; `DOM.resolveNode(backendNodeId, executionContextId,
objectGroup)` resolves "the JavaScript node object" in that context; `Runtime.callFunctionOn
(functionDeclaration, executionContextId, arguments, returnByValue)`; `DOMSnapshot.captureSnapshot`
returns `documents[].frameId` and per-node `backendNodeId`. Playwright: `BrowserContext.new_cdp_session
(page | frame)` — "it can be a Page or Frame".

No LLM, no Playwright import (duck-typed `page` / `cdp` objects).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from netgent.core.logger import get_logger

logger = get_logger(__name__)

WORLD_NAME = "netgent-observe"


class CdpFrames:
    """Sessions, frames and isolated worlds for observers that read the page from outside."""

    def __init__(self, page: Any, cdp: Any, frame_selector_js: str):
        self._page = page
        self._cdp = cdp  # the page target's session (owned by BrowserSession, via factory.launch)
        self._frame_selector_js = frame_selector_js
        # frameId → executionContextId of our isolated world. Worlds live in the renderer, not
        # in the session that created them, so the cache survives per-snapshot OOPIF sessions;
        # a navigation destroys the context and `in_world` recreates it on the first failure.
        self._worlds: dict[str, int] = {}

    # ── worlds ──────────────────────────────────────────────────────────────────

    async def in_world(self, session: Any, frame_id: str, op: Callable[[int], Awaitable[Any]]) -> Any:
        """Run `op(executionContextId)` in the frame's isolated world.

        The world is created once per frame and cached. A navigation replaces the frame's
        document and destroys the context; Chrome reports that as `Cannot find context with
        specified id` from Runtime.* but as `Node with given id does not belong to the
        document` from DOM.resolveNode (measured) — so a cached world that fails for ANY reason
        is dropped and the call retried once in a fresh world, and only that failure raises.
        """
        fresh = frame_id not in self._worlds
        ctx = await self.world(session, frame_id)
        try:
            return await op(ctx)
        except Exception:  # noqa: BLE001 — stale world after a navigation, or a real failure
            if fresh:
                raise
            self._worlds.pop(frame_id, None)
            return await op(await self.world(session, frame_id))

    async def world(self, session: Any, frame_id: str) -> int:
        if frame_id not in self._worlds:
            created = await session.send(
                "Page.createIsolatedWorld",
                {"frameId": frame_id, "worldName": WORLD_NAME, "grantUniveralAccess": False},
            )
            self._worlds[frame_id] = created["executionContextId"]
        return self._worlds[frame_id]

    async def call(self, session: Any, frame_id: str, fn: str, args: list[dict]) -> Any:
        """Run `fn(*args)` in the frame's isolated world and return its JSON value."""

        async def op(ctx: int) -> Any:
            result = await session.send(
                "Runtime.callFunctionOn",
                {"functionDeclaration": fn, "executionContextId": ctx, "arguments": args, "returnByValue": True},
            )
            if "exceptionDetails" in result:
                raise RuntimeError(result["exceptionDetails"].get("text", "script threw"))
            return result["result"].get("value")

        return await self.in_world(session, frame_id, op)

    async def resolve(
        self, session: Any, frame_id: str, backend_node_id: int, object_group: str | None = None
    ) -> dict:
        """A JS handle (CDP argument form) for a backend node, in the frame's isolated world.
        `object_group` lets the caller release every handle at once (Runtime.releaseObjectGroup)."""

        async def op(ctx: int) -> dict:
            params: dict[str, Any] = {"backendNodeId": backend_node_id, "executionContextId": ctx}
            if object_group:
                params["objectGroup"] = object_group
            resolved = await session.send("DOM.resolveNode", params)
            return {"objectId": resolved["object"]["objectId"]}

        return await self.in_world(session, frame_id, op)

    # ── targets and frames ──────────────────────────────────────────────────────

    @staticmethod
    async def capture(session: Any) -> dict:
        """DOMSnapshot.captureSnapshot — works without DOMSnapshot.enable on current Chrome
        (measured); the protocol docs list `enable`, so if a build insists, enable and retry."""
        params = {"computedStyles": []}
        try:
            return await session.send("DOMSnapshot.captureSnapshot", params)
        except Exception:  # noqa: BLE001
            await session.send("DOMSnapshot.enable")
            return await session.send("DOMSnapshot.captureSnapshot", params)

    async def sessions(self) -> tuple[list[Any], list[Any]]:
        """(all distinct sessions, the ones we opened and must detach) — one per target.

        The page's own session covers the top frame and every same-process child frame; each
        out-of-process iframe (OOPIF) gets `new_cdp_session(frame)` — Playwright refuses that
        call for same-process frames ("part of the parent frame's session"), which is exactly
        how we tell the two apart.
        """
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

    @staticmethod
    async def detach(opened: list[Any]) -> None:
        for session in opened:
            try:
                await session.detach()
            except Exception:  # noqa: BLE001 — target already gone
                pass

    async def frame_tree(self, sessions: list[Any]) -> dict[str, tuple[Any, str | None]]:
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
                logger.debug("cdp: frame tree unavailable: %s", exc)
        return owners

    async def frame_path(self, frame_id: str, owners: dict[str, tuple[Any, str | None]]) -> list[str]:
        """The iframe selector chain for `frame_id` — the same strings `DomObserver._frame_info`
        computes with Playwright for the same frame (FRAME_SELECTOR_JS on the owner element,
        run in each ancestor's isolated world), so results join by an exact key."""
        path: list[str] = []
        current = frame_id
        while owners.get(current, (None, None))[1]:
            parent = owners[current][1]
            parent_session = owners[parent][0]
            owner = await parent_session.send("DOM.getFrameOwner", {"frameId": current})
            handle = await self.resolve(parent_session, parent, owner["backendNodeId"])
            path.insert(0, await self.call(parent_session, parent, self._frame_selector_js, [handle]))
            current = parent
        return path
