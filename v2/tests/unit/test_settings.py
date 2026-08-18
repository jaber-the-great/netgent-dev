"""Typed settings: env + .env precedence, gemini/google alias, provider-key sync."""

import os

from netgent.core.settings import Settings


def test_reads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")
    monkeypatch.setenv("NETGENT_GENERATOR_MODEL", "anthropic/claude-haiku-4-5")
    s = Settings(_env_file=None)  # ignore any real .env for this test
    assert s.anthropic_api_key == "sk-ant-xyz"
    assert s.generator_model == "anthropic/claude-haiku-4-5"
    assert s.headless is True  # default


def test_gemini_falls_back_to_google_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-123")
    assert Settings(_env_file=None).gemini_api_key == "goog-123"


def test_loads_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text('OPENAI_API_KEY="sk-openai-file"\nNETGENT_LOG_LEVEL=debug\n')
    s = Settings(_env_file=env)
    assert s.openai_api_key == "sk-openai-file"
    assert s.log_level == "debug"


def test_real_env_wins_over_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert Settings(_env_file=env).openai_api_key == "from-env"


def test_sync_provider_keys_maps_gemini_to_google(monkeypatch):
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    object.__setattr__(s, "gemini_api_key", "g-key")
    s.sync_provider_keys()
    assert os.environ["GOOGLE_API_KEY"] == "g-key"  # what langchain-google reads
    assert os.environ["GEMINI_API_KEY"] == "g-key"


def test_provider_key_lookup():
    s = Settings(_env_file=None)
    object.__setattr__(s, "anthropic_api_key", "a")
    assert s.provider_key("anthropic") == "a"
    assert s.provider_key("openai") is None
