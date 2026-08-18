"""Logging setup for netgent: one `netgent.*` logger tree, secrets redacted at the handler.

Redaction is on by default (browser agents echo page state and prompts everywhere — the
leak path named in docs/browser-agents.md §4). Any env value whose name looks secret is
masked in every record before it reaches a handler.
"""

import logging
import os
import re

SECRET_ENV_PATTERN = re.compile(r"(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_MIN_SECRET_LEN = 6  # don't redact trivially short values like "1" or "true"


class RedactSecretsFilter(logging.Filter):
    """Masks the *values* of secret-looking environment variables in log messages."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets = {
            value: f"[redacted:{name}]"
            for name, value in os.environ.items()
            if SECRET_ENV_PATTERN.search(name) and len(value) >= _MIN_SECRET_LEN
        }

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            message = record.getMessage()
            for secret, replacement in self._secrets.items():
                if secret in message:
                    message = message.replace(secret, replacement)
            record.msg, record.args = message, None
        return True


def configure_logging(level: str | None = None) -> None:
    """Configure the `netgent` logger tree. Level from arg, else NETGENT_LOG_LEVEL, else info."""
    level_name = (level or os.getenv("NETGENT_LOG_LEVEL") or "info").upper()
    root = logging.getLogger("netgent")
    root.setLevel(getattr(logging, level_name, logging.INFO))
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        handler.addFilter(RedactSecretsFilter())
        root.addHandler(handler)
        root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the `netgent` tree, e.g. get_logger(__name__)."""
    if name.startswith("netgent"):
        return logging.getLogger(name)
    return logging.getLogger(f"netgent.{name}")
