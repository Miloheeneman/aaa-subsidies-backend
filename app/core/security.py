from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


TokenPurpose = Literal["access", "verify_email", "reset_password"]


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def _create_token(
    subject: str | UUID,
    purpose: TokenPurpose,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "purpose": purpose,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str | UUID, role: str) -> str:
    return _create_token(
        subject=user_id,
        purpose="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"role": role},
    )


def create_email_verification_token(user_id: str | UUID) -> str:
    return _create_token(
        subject=user_id,
        purpose="verify_email",
        expires_delta=timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS),
    )


def create_password_reset_token(user_id: str | UUID) -> str:
    return _create_token(
        subject=user_id,
        purpose="reset_password",
        expires_delta=timedelta(hours=settings.PASSWORD_RESET_TOKEN_EXPIRE_HOURS),
    )


def decode_token(token: str, expected_purpose: TokenPurpose) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ValueError on failure."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise ValueError("Ongeldig of verlopen token") from exc

    if payload.get("purpose") != expected_purpose:
        raise ValueError("Token is niet geldig voor deze actie")

    if "sub" not in payload:
        raise ValueError("Token bevat geen gebruiker")

    return payload
