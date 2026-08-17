"""Typed browser-layer failures — replay fails loudly, never silently."""


class NetgentBrowserError(Exception):
    """Base class for browser-layer failures."""


class TriggerTimeoutError(NetgentBrowserError):
    def __init__(self, state_id: str, unmet: list[str], timeout_ms: int):
        self.state_id = state_id
        self.unmet = unmet
        self.timeout_ms = timeout_ms
        super().__init__(f"state {state_id!r} not recognized within {timeout_ms}ms; unmet conditions: {unmet}")


class ActionDispatchError(NetgentBrowserError):
    """An action failed to execute against the live page."""


class LocatorResolutionError(NetgentBrowserError):
    """A stored locator chain could not be resolved on the live page."""
