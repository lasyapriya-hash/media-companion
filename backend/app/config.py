"""Application configuration, loaded from environment variables.

All secrets (API keys, DB URL) are read here and nowhere else. Nothing in this
module is ever sent to the frontend.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Core
    database_url: str = "postgresql+psycopg://localhost/media_companion"
    env: str = "development"

    # CORS: comma-separated list of allowed frontend origins
    frontend_origin: str = "http://localhost:3000"

    # External API credentials (server-side only)
    tmdb_api_key: str = ""
    # Open Library is primary (spec §15 D1); Google Books is the fallback and
    # works without a key for basic search — the key just raises rate limits.
    google_books_api_key: str = ""

    # --- LLM provider (spec §7, §10, §15 D6/D7) --- #
    # Provider-agnostic. "gemini" (initial) or "none" to disable the LLM
    # entirely. When disabled or key-less: preference extraction uses the
    # deterministic fallback and mood-tag classification is skipped. No
    # Anthropic / paid-subscription dependency anywhere.
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    # A current free-tier Gemini model. Blank -> service default.
    gemini_model: str = ""

    # --- Auth (Phase 8: authentication foundation) --- #
    # No default: a blank/predictable signing key would let anyone forge a
    # token. app/services/auth.py refuses to sign or verify a token when this
    # is empty, rather than silently using an insecure fallback.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24 * 7  # 7 days — a personal app, not a bank

    # --- Legacy library claim (Phase 8.2 bootstrap, temporary) --- #
    # The only account allowed to call POST /admin/claim-legacy-library
    # (app/api/admin.py). Blank disables the endpoint for everyone, since no
    # real email can ever equal "" — fails closed by default. Remove this
    # setting and app/api/admin.py together once the legacy rows are claimed.
    legacy_claim_allowed_email: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Managed hosts (Render, Railway, Heroku) hand out `postgres://` or
        `postgresql://` URLs. SQLAlchemy needs an explicit driver; pin psycopg3.
        """
        if v.startswith("postgres://"):
            v = "postgresql+psycopg://" + v[len("postgres://") :]
        elif v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origin.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
