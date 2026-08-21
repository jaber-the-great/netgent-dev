"""Typed configuration, resolved from environment variables and a .env file.

This is the single source of truth for netgent's config surface (see .env.example). Real
environment variables win over .env — pydantic-settings' default precedence — so an export
or a CI secret is never overridden by a checked-out .env.

Provider keys use the names the LLM SDKs themselves read (GOOGLE_API_KEY for Gemini via
langchain-google-genai, OPENAI_API_KEY, ANTHROPIC_API_KEY); GEMINI_API_KEY is accepted as an
alias because Google's own docs use it. `sync_provider_keys()` publishes the resolved keys into
the process environment so the SDKs pick them up regardless of which name was set.
"""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM provider keys (GOOGLE_API_KEY is what langchain reads; GEMINI_API_KEY is an alias) ──
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY")
    )
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    # ── Model selection (litellm-style provider/model) ───────────────────────────────────
    generator_model: str = Field(default="gemini/gemini-2.5-flash", validation_alias="NETGENT_GENERATOR_MODEL")
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
        """The API key for a litellm-style provider prefix ('gemini'/'openai'/'anthropic')."""
        return {
            "gemini": self.gemini_api_key,
            "google": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider)

    def sync_provider_keys(self) -> None:
        """Publish provider keys into os.environ under the names the LLM SDKs read.

        Only sets a var that isn't already present (real env wins). The Gemini key is
        published under both names so either convention works downstream.
        """
        for env_name, value in (
            ("GOOGLE_API_KEY", self.gemini_api_key),
            ("GEMINI_API_KEY", self.gemini_api_key),
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
