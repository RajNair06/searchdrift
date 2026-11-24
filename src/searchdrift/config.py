"""Application settings, read from environment variables (and `.env` in development).

One place for every setting means nothing is hard-coded, and a missing or
malformed value fails at startup instead of halfway through a run.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",  # .env also holds keys we don't use yet (Gemini, Groq, ...)
    )

    # Local default matches compose.yaml (host port 15432).
    database_url: str = "postgresql+asyncpg://searchdrift:searchdrift@localhost:15432/searchdrift"

    # Vendor API keys. SecretStr hides the value in logs and reprs: printing
    # settings shows '**********' instead of the key. Optional until a live
    # call actually needs one (replay mode needs no keys at all).
    tavily_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    """Read settings once and reuse them (environment is read at first call)."""
    return Settings()
