"""Trigger evaluation: does the live page satisfy a state's conditions? Polling loop + value reads."""

import asyncio
import re
import time

from netgent.browser.dialogs import DialogLog
from netgent.browser.pw import Locator, Page
from netgent.browser.resolution import LocatorResolver
from netgent.core.errors import TriggerTimeoutError
from netgent.schema.control import ParamSource
from netgent.schema.triggers import (
    DialogMatches,
    MediaPlaying,
    SelectorHidden,
    SelectorVisible,
    TitleContains,
    Trigger,
    UrlMatches,
)
from netgent.schema.workflow import State

POLL_INTERVAL_S = 0.1


class TriggerEngine:
    """Evaluates state conditions and page-extracted parameter sources against the live page."""

    def __init__(self, page: Page, resolver: LocatorResolver, dialogs: DialogLog | None = None):
        self._page = page
        self._resolver = resolver
        self._dialogs = dialogs

    def _element(self, trigger: SelectorVisible | SelectorHidden) -> Locator:
        """The Locator an element trigger is evaluated on: its locator chain through the SAME
        resolver actions use (so an anchor on an edge's target holds exactly when the edge's
        element resolves — never a hand-rendered selector with different name semantics), or
        its selector string in its frame scope."""
        if trigger.locator is not None:
            return self._resolver.resolve(trigger.locator)
        return self._resolver.frame_scope(trigger.frame_path).locator(trigger.selector)

    async def holds(self, trigger: Trigger) -> bool:
        match trigger:
            case UrlMatches():
                return re.search(trigger.pattern, self._page.url) is not None
            case TitleContains():
                return trigger.text in await self._page.title()
            case SelectorVisible():
                return await self._element(trigger).first.is_visible()
            case DialogMatches():
                # Only dialogs raised since the last dispatched action count: the dialog is
                # the edge's own feedback, not ambient page state (browser/dialogs.py).
                if self._dialogs is None:
                    return False
                return any(re.search(trigger.pattern, d) for d in self._dialogs.since_last_action())
            case SelectorHidden():
                # Resolved-and-hidden only: a selector matching nothing must not hold, or a
                # typo'd selector would "recognize" every state (research doc, R2).
                locator = self._element(trigger)
                if await locator.count() == 0:
                    return False
                return not await locator.first.is_visible()
            case MediaPlaying():
                # Element properties only — the playback signal that cannot freeze. No media
                # elements → does not hold (resolved-only, like SelectorHidden). The duration
                # gate is what tells content from an ad playing in the same element.
                locator = self._resolver.frame_scope(trigger.frame_path).locator("video, audio")
                readings = await locator.evaluate_all(
                    "els => els.map((v) => ({ paused: !!v.paused, ended: !!v.ended,"
                    " duration: Number.isFinite(v.duration) ? v.duration : null }))"
                )
                for m in readings:
                    state_ok = (not m["paused"] and not m["ended"]) if trigger.playing else m["paused"]
                    duration_ok = trigger.min_duration_s is None or (
                        m["duration"] is not None and m["duration"] >= trigger.min_duration_s
                    )
                    if state_ok and duration_ok:
                        return True
                return False
        return False

    async def extract_value(self, source: "ParamSource", timeout_ms: int = 5000) -> str | None:
        """Read a dynamic parameter's value from the live page (returns None if unavailable)."""
        try:
            if source.kind == "url_group":
                if not source.pattern:
                    return None
                match = re.search(source.pattern, self._page.url)
                return match.group(source.group) if match else None
            locator = self._resolver.frame_scope(source.frame_path).locator(source.selector).first
            if source.kind == "text":
                return (await locator.inner_text(timeout=timeout_ms)).strip()
            if source.kind == "input_value":
                return await locator.input_value(timeout=timeout_ms)
            if source.kind == "attribute":
                return await locator.get_attribute(source.attribute, timeout=timeout_ms)
        except Exception:  # noqa: BLE001 — a missing value is None (a healable signal), not a crash
            return None
        return None

    async def condition_report(self, state: State) -> list[tuple[str, bool]]:
        """Evaluate each of a state's conditions once; return [(type, met), ...]."""
        return [(t.type, await self.holds(t)) for t in state.conditions]

    async def wait_for_state(self, state: State) -> float:
        """Poll until every condition of `state` holds; return recognition latency in ms.

        Raises TriggerTimeoutError naming the unmet conditions — never a silent timeout.
        """
        start = time.monotonic()
        deadline = start + state.timeout_ms / 1000
        while True:
            unmet = [t.type for t in state.conditions if not await self.holds(t)]
            if not unmet:
                return (time.monotonic() - start) * 1000
            if time.monotonic() >= deadline:
                raise TriggerTimeoutError(state.id, unmet, state.timeout_ms)
            await asyncio.sleep(POLL_INTERVAL_S)
