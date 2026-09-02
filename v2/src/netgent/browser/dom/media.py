"""Media elements observed from OUTSIDE the page over CDP — attached to the DOM or not.

Players are not always in the DOM. SoundCloud drives playback through a `new Audio()` it never
inserts, so `document.querySelectorAll('video, audio')` — the DOM walker's path — sees nothing:
zero MEDIA lines in 31 exploration steps, no act→observe loop for play or mute (docs/research/
media-platforms-eval.md). Twitch's `<video>` is attached but its stream never arrives
(`src=""`, readyState 0), and a reading that cannot say "nothing loaded" looks like an ordinary
pause the agent toggles for 25 steps. This module enumerates every live HTMLMediaElement of
every frame and reads its load state alongside playback.

Mechanism, per read (a snapshot, or a replay edge — no LLM, no DOM walk):

1. One CDP session per target and one `DOMSnapshot.captureSnapshot` per session (dom/cdp.py):
   every document's `frameId` and document `backendNodeId`, same- and cross-origin frames.
2. Per document, scripts/media_reader.js runs in OUR isolated world over the document's
   DOM-attached media (open shadow roots included) plus the detached players already known
   for that frame — `DOM.resolveNode(backendNodeId, executionContextId=<our world>)` handles,
   re-resolved from a cache of backend node ids (a node keeps its id for its lifetime; one
   that is gone fails to resolve and is dropped).
3. Only when nothing is playing anywhere — no attached element, no known detached one — the
   heap is searched for players script holds outside the DOM, in each target's TOP document:
   `DOM.resolveNode(backendNodeId)` on the document with no `executionContextId` resolves it in
   the frame's MAIN world; `Runtime.callFunctionOn` reads `this.defaultView.HTMLMediaElement
   .prototype` there (one property chain on the document — no script of ours, nothing defined,
   nothing patched; it must be the main world's prototype because `Runtime.queryObjects`
   matches objects created in the prototype's own context, and the page's wrappers live there);
   `Runtime.queryObjects(prototypeObjectId)` returns "Array with objects" that have it in their
   chain (chromedevtools.github.io/devtools-protocol/tot/Runtime/#method-queryObjects). V8
   collects all garbage first — which is why this is rationed: measured ~1 s per call on
   SoundCloud's heap, and every same-process document would pay it again (7 documents = 6.5 s),
   so same-process child frames' detached players are not searched for (their attached media
   is read like any frame's; an out-of-process iframe is its own target and IS searched).
   The subclass prototypes (HTMLVideoElement.prototype, …) come back too: `DOM.describeNode
   (objectId)` rejects them ("Object id doesn't reference a Node") and they are skipped; each
   real node's `backendNodeId` joins the cache, and the document is read again with them.
   Stale players a site dropped are collected before the walk, so they never surface.
4. `Runtime.releaseObjectGroup` drops every remote object the pass created.

The reads are the isolated world's own wrappers and prototypes, so a page-side getter trap
on the main world's HTMLMediaElement.prototype does not fire (tests/integration/
test_media_detached.py). Cost on a page whose attached player is playing (YouTube, Archive):
one reader call per document, no heap walk. On SoundCloud playing: the same, plus one cached
re-resolve. Nothing playing: one heap walk per target.

No `Runtime.enable` (Patchright's rule — the page can detect it), no main-world script. A CDP
failure never loses an observation: `read()` returns None and the caller falls back to the
DOM-attached reading through Playwright (`MEDIA_DOM_JS`), which is what the walker used to do.

No LLM, no Playwright import (duck-typed CDP session objects).
"""

from typing import Any

from netgent.browser.dom.cdp import CdpFrames
from netgent.browser.dom.models import MediaState
from netgent.core.logger import get_logger

logger = get_logger(__name__)

OBJECT_GROUP = "netgent-media"

# The main world's HTMLMediaElement.prototype, from the frame's document (step 2 above).
_PROTOTYPE_OF_DOCUMENT_JS = "function () { return this.defaultView.HTMLMediaElement.prototype; }"


class MediaObserver:
    """Enumerate and read every live media element of every frame, attached or detached."""

    def __init__(self, frames: CdpFrames, reader_js: str):
        self._frames = frames
        self._reader_js = reader_js
        # frameId → backendNodeIds of detached players found by a heap search: re-resolved on
        # later reads instead of walking the heap again (a node's id lasts its lifetime).
        self._known: dict[str, list[int]] = {}

    async def _handles(self, session: Any, frame_id: str) -> list[dict]:
        """Isolated-world handles for the frame's known detached players; gone ones are forgotten."""
        alive: list[int] = []
        handles: list[dict] = []
        for backend_id in self._known.get(frame_id, ()):
            try:
                handles.append(await self._frames.resolve(session, frame_id, backend_id, OBJECT_GROUP))
            except Exception:  # noqa: BLE001 — the node was collected / the document replaced
                continue
            alive.append(backend_id)
        if alive:
            self._known[frame_id] = alive
        else:
            self._known.pop(frame_id, None)
        return handles

    async def _search_heap(self, session: Any, frame_id: str, document_backend_id: int) -> list[int]:
        """backendNodeIds of every live HTMLMediaElement of the document's main world (step 3)."""
        doc = await session.send("DOM.resolveNode", {"backendNodeId": document_backend_id, "objectGroup": OBJECT_GROUP})
        proto = await session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": doc["object"]["objectId"],
                "functionDeclaration": _PROTOTYPE_OF_DOCUMENT_JS,
                "objectGroup": OBJECT_GROUP,
            },
        )
        if "exceptionDetails" in proto or not proto["result"].get("objectId"):
            raise RuntimeError("HTMLMediaElement.prototype unavailable in the main world")
        found = await session.send(
            "Runtime.queryObjects", {"prototypeObjectId": proto["result"]["objectId"], "objectGroup": OBJECT_GROUP}
        )
        props = await session.send(
            "Runtime.getProperties", {"objectId": found["objects"]["objectId"], "ownProperties": True}
        )
        ids: list[int] = []
        for prop in props.get("result", ()):
            value = prop.get("value") or {}
            if not prop.get("name", "").isdigit() or not value.get("objectId"):
                continue
            try:
                node = await session.send("DOM.describeNode", {"objectId": value["objectId"]})
            except Exception:  # noqa: BLE001 — a prototype object (HTMLVideoElement.prototype), not a node
                continue
            ids.append(node["node"]["backendNodeId"])
        return ids

    async def _read_document(self, session: Any, frame_id: str, handles: list[dict]) -> list[dict]:
        return await self._frames.call(session, frame_id, self._reader_js, handles) or []

    async def read(self) -> list[MediaState] | None:
        """Every media reading across frames, or None when CDP could not enumerate anything
        (the caller then reads DOM-attached media through Playwright). Frame paths are the
        same strings `DomObserver._frame_info` computes, so readings join the snapshot by frame.
        Never raises: a document that fails is logged and skipped."""
        try:
            sessions, opened = await self._frames.sessions()
        except Exception as exc:  # noqa: BLE001 — no page session / context gone
            logger.debug("media: sessions unavailable: %s", exc)
            return None
        raw_by_doc: dict[tuple[Any, str], list[dict]] = {}
        docs: list[tuple[Any, str, int, bool]] = []  # (session, frameId, document backendNodeId, top of target)
        try:
            for session in sessions:
                try:
                    snap = await self._frames.capture(session)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("media: captureSnapshot failed: %s", exc)
                    continue
                strings = snap["strings"]
                for i, doc in enumerate(snap["documents"]):
                    docs.append((session, strings[doc["frameId"]], doc["nodes"]["backendNodeId"][0], i == 0))
            for session, frame_id, _doc_id, _top in docs:
                try:
                    raw_by_doc[(session, frame_id)] = await self._read_document(
                        session, frame_id, await self._handles(session, frame_id)
                    )
                except Exception as exc:  # noqa: BLE001 — detached frame / closed target / stale world
                    logger.debug("media: frame %s not read over CDP: %s", frame_id, _reason(exc))
            playing = any(not m["paused"] and not m["ended"] for raws in raw_by_doc.values() for m in raws)
            if not playing:
                for session, frame_id, doc_id, top in docs:
                    if not top or (session, frame_id) not in raw_by_doc:
                        continue
                    try:
                        ids = await self._search_heap(session, frame_id, doc_id)
                        if not ids:
                            continue
                        self._known[frame_id] = ids
                        raw_by_doc[(session, frame_id)] = await self._read_document(
                            session, frame_id, await self._handles(session, frame_id)
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("media: heap search in frame %s failed: %s", frame_id, _reason(exc))
            readings: list[MediaState] = []
            owners: dict[str, tuple[Any, str | None]] | None = None
            for (_session, frame_id), raws in raw_by_doc.items():
                if not raws:
                    continue
                try:
                    if owners is None:
                        owners = await self._frames.frame_tree(sessions)
                    path = await self._frames.frame_path(frame_id, owners)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("media: frame path for %s unavailable: %s", frame_id, _reason(exc))
                    continue
                for raw in raws:
                    raw["frame_path"] = path
                    readings.append(MediaState.model_validate(raw))
        finally:
            for session in sessions:
                try:
                    await session.send("Runtime.releaseObjectGroup", {"objectGroup": OBJECT_GROUP})
                except Exception:  # noqa: BLE001 — session already gone
                    pass
            await self._frames.detach(opened)
        if docs and not raw_by_doc:
            return None  # CDP saw the page but could read no document: let Playwright try
        return readings


def _reason(exc: Exception) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


async def attached_media(frame: Any, dom_js: str, frame_path: list[str]) -> list[MediaState]:
    """The DOM-attached media of one Playwright frame (the CDP-less fallback: `MEDIA_DOM_JS`
    evaluated where Playwright evaluates — an isolated world under Patchright)."""
    raw = await frame.evaluate(dom_js)
    out = []
    for m in raw or []:
        m["frame_path"] = frame_path
        out.append(MediaState.model_validate(m))
    return out


def by_relevance(readings: list[MediaState]) -> list[MediaState]:
    """Playing first, then attached before detached, frame order otherwise — the first three
    are what an observation shows."""
    return sorted(readings, key=lambda m: (m.paused or m.ended, not m.attached))
