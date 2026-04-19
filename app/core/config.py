import logging
import os
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _normalize_db_url(raw: str) -> str:
    """Normalize a Postgres URL so it always uses the psycopg v3 driver.

    Railway, Heroku and most managed Postgres providers hand out a URL
    that starts with ``postgres://`` or ``postgresql://``. SQLAlchemy 2.x
    treats those as the legacy psycopg2 driver, which isn't installed
    here — so connecting blows up before the app even starts. We rewrite
    them to ``postgresql+psycopg://`` to force SQLAlchemy onto psycopg 3.
    """
    if not raw:
        return raw
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://") and "+psycopg" not in raw.split("://", 1)[0]:
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_ENV: str = "development"
    APP_NAME: str = "AAA-Subsidies"
    API_V1_PREFIX: str = "/api/v1"
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/aaa_subsidies"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _coerce_database_url(cls, value):
        # Pydantic-settings already prefers the env var over the default,
        # but Railway exposes the database under a couple of names
        # depending on how the service is wired (Postgres plugin vs.
        # template). Fall back through the common ones so a freshly
        # provisioned service "just works".
        if not value or value == cls.model_fields["DATABASE_URL"].default:
            for alt in ("DATABASE_URL", "POSTGRES_URL", "POSTGRES_PRISMA_URL"):
                from_env = os.environ.get(alt)
                if from_env:
                    value = from_env
                    break
        return _normalize_db_url(value)

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days per spec
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 1

    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "noreply@aaa-lexoffices.nl"
    RESEND_FROM_NAME: str = "AAA-Lex Offices"

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Legacy aliases (kept for compatibility with .env.example).
    STRIPE_PRICE_BASIC: str = ""
    STRIPE_PRICE_PRO: str = ""
    # New per-plan price IDs used by the installateur subscription flow.
    STRIPE_STARTER_PRICE_ID: str = ""
    STRIPE_PRO_PRICE_ID: str = ""

    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "aaa-subsidies-docs"
    R2_PUBLIC_URL: str = ""
    R2_ENDPOINT_URL: str = ""


def _redact_db_url(url: str) -> str:
    """Strip the password out of a postgres URL so it's safe to log."""
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(url)
        if parts.password:
            netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
            return urlunsplit(parts._replace(netloc=netloc))
    except Exception:
        pass
    return url


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Loud, single-line log so misconfiguration is obvious in Railway/Heroku
    # logs the moment the worker boots. Password is redacted.
    logger.info(
        "AAA-Subsidies config loaded: env=%s db=%s frontend_url=%s",
        s.APP_ENV,
        _redact_db_url(s.DATABASE_URL),
        s.FRONTEND_URL,
    )
    return s


settings = get_settings()
