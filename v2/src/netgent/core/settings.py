"""Typed configuration, resolved from environment variables and a .env file.

This is the single source of truth for netgent's config surface (see .env.example). Real
environment variables win over .env — pydantic-settings' default precedence — so an export
or a CI secret is never overridden by a checked-out .env.

Provider keys use exactly the names the LLM SDKs read (GOOGLE_API_KEY for Gemini via
langchain-google-genai, OPENAI_API_KEY, ANTHROPIC_API_KEY) — one name per provider, no
aliases. `sync_provider_keys()` publishes keys loaded from .env into the process environment
so the SDKs see them.
"""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM provider keys (exactly the names the SDKs read) ──────────────────────────────
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    # ── Model selection (`provider:model`, init_chat_model's syntax; `/` also accepted) ─────
    generator_model: str = Field(default="google_genai:gemini-2.5-flash", validation_alias="NETGENT_GENERATOR_MODEL")
    # The generator AGENT's model (the one draft + ≤2 repairs per compile): a long-horizon structural
    # judgement that repays reasoning depth (generator-agent-v2.md §H recommends anthropic:claude-opus-5).
    # None: the pipeline's model.
    generator_agent_model: str | None = Field(default=None, validation_alias="NETGENT_GENERATOR_AGENT_MODEL")
    secondary_model: str | None = Field(default=None, validation_alias="NETGENT_SECONDARY_MODEL")

    # ── Browser ──────────────────────────────────────────────────────────────────────────
    headless: bool = Field(default=True, validation_alias="NETGENT_HEADLESS")
    browser_executable: str | None = Field(default=None, validation_alias="NETGENT_BROWSER_EXECUTABLE")
    browser_storage_dir: str | None = Field(default=None, validation_alias="NETGENT_BROWSER_STORAGE_DIR")

    # ── Site credentials + ops ───────────────────────────────────────────────────────────
    credentials_file: str | None = Field(default=None, validation_alias="NETGENT_CREDENTIALS_FILE")
    langsmith_api_key: str | None = Field(default=None, validation_alias="LANGSMITH_API_KEY")
    log_level: str = Field(default="info", validation_alias="NETGENT_LOG_LEVEL")

    def provider_key(self, provider: str) -> str | None:
        """The API key for a provider prefix ('google_genai'/'openai'/'anthropic'; 'gemini' and 'google'
        are accepted spellings of the Google key)."""
        return {
            "google_genai": self.google_api_key,
            "gemini": self.google_api_key,
            "google": self.google_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider)

    def sync_provider_keys(self) -> None:
        """Publish provider keys into os.environ under the names the LLM SDKs read.

        Only sets a var that isn't already present (real env wins).
        """
        for env_name, value in (
            ("GOOGLE_API_KEY", self.google_api_key),
            ("OPENAI_API_KEY", self.openai_api_key),
            ("ANTHROPIC_API_KEY", self.anthropic_api_key),
            ("LANGSMITH_API_KEY", self.langsmith_api_key),
        ):
            if value and env_name not in os.environ:
                os.environ[env_name] = value


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings (cached). Call get_settings.cache_clear() in tests."""
    return Settings()
