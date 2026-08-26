"""JavaScript dialogs (alert / confirm / prompt / beforeunload), recorded for the observation.

Playwright auto-dismisses a dialog when no handler is registered, so a page whose only
feedback is `alert('Form submitted successfully')` leaves NO trace in the DOM: the agent's
next observation is identical to the previous one, it repeats the submit, and the stuck
detector ends the run (measured on browser-use's Vanilla HTML form). Playwright-MCP keeps
dialogs as a "modal state" on the tab and browser-use has a popups watchdog for the same
reason. Here the dialog is accepted (the page continues) and its message is queued; the next
`DomObserver.snapshot()` drains the queue into `DomSnapshot.dialogs`, so the message reaches
the serialized observation exactly once, as the event it is.

Zero page footprint: `page.on("dialog")` is a CDP `Page.javascriptDialogOpening` subscription,
nothing is injected. No LLM.
"""

from typing import Any

from netgent.core.logger import get_logger

logger = get_logger(__name__)


class DialogLog:
    """Accept every dialog on `page` and keep its text until the next snapshot drains it."""

    def __init__(self, page: Any):
        self._pending: list[str] = []
        self._history: list[str] = []  # cumulative, never cleared: post-hoc success checks
        page.on("dialog", self._on_dialog)

    async def _on_dialog(self, dialog: Any) -> None:
        # Accept every type — alert/confirm/prompt AND beforeunload. Accept is the safe default
        # for a forward-moving agent (Skyvern: "safer than dismiss for form submissions";
        # browser-use accepts alert/confirm/beforeunload), and accepting beforeunload lets a
        # pending navigation commit instead of trapping the agent on the page. A prompt() is
        # accepted with its OWN default value (Playwright's accept() ignores promptText for
        # non-prompt types), so a prompt-gated flow continues with the value the page pre-filled
        # rather than an empty string — browser-use instead cancels prompts, which stalls them.
        dtype = dialog.type
        default = dialog.default_value if dtype == "prompt" else None
        entry = f"{dtype}: {dialog.message}".strip()
        if default:
            entry += f'  (answered "{default}")'
        self._pending.append(entry)
        self._history.append(entry)
        logger.info("dialog auto-accepted — %s", entry)
        try:
            await dialog.accept(default) if default else await dialog.accept()
        except Exception as exc:  # noqa: BLE001 — already handled / page gone: never break the run
            logger.debug("dialog accept failed: %s", exc)

    def drain(self) -> list[str]:
        """Dialogs seen since the last drain (oldest first); clears the queue.

        Drained into each `DomSnapshot` so a message shows in the observation exactly once."""
        pending, self._pending = self._pending, []
        return pending

    @property
    def history(self) -> list[str]:
        """Every dialog seen this session, in order — NOT cleared by `drain`. A dialog is a
        one-shot event, so a post-hoc success check (the sweep verifying a form after the
        agent's own snapshots already drained it) reads the history, not the next snapshot."""
        return list(self._history)
