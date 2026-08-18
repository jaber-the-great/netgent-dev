"""Logger tree naming and secret redaction."""

import logging

from netgent.core.logger import RedactSecretsFilter, get_logger


def test_loggers_live_under_the_netgent_tree():
    assert get_logger("executor.engine").name == "netgent.executor.engine"
    assert get_logger("netgent.core").name == "netgent.core"


def test_secret_env_values_are_redacted(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-super-secret-123")
    monkeypatch.setenv("NETGENT_LOG_LEVEL", "info")  # non-secret name: never redacted
    redact = RedactSecretsFilter()

    record = logging.LogRecord(
        "netgent.test", logging.INFO, __file__, 1, "calling api with key sk-super-secret-123", None, None
    )
    assert redact.filter(record)
    assert "sk-super-secret-123" not in record.getMessage()
    assert "[redacted:GEMINI_API_KEY]" in record.getMessage()


def test_short_values_not_redacted(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "on")  # too short — redacting "on" would mangle every message
    record = logging.LogRecord("netgent.test", logging.INFO, __file__, 1, "state is on", None, None)
    RedactSecretsFilter().filter(record)
    assert record.getMessage() == "state is on"
