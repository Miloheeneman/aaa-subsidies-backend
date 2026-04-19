from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    auto_error=False,
)

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    db: DbSession,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    if not token:
        raise _unauthorized("Niet ingelogd")
    try:
        payload = decode_token(token, expected_purpose="access")
    except ValueError as exc:
        raise _unauthorized(str(exc)) from exc

    try:
        user_id = UUID(payload["sub"])
    except (ValueError, KeyError) as exc:
        raise _unauthorized("Ongeldig token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized("Gebruiker niet gevonden")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_verified(user: CurrentUser) -> User:
    if not user.verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email niet geverifieerd",
        )
    return user


def require_role(*roles: UserRole):
    allowed = {r.value for r in roles}

    def _check(user: CurrentUser) -> User:
        if user.role.value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Onvoldoende rechten voor deze actie",
            )
        return user

    return _check


require_admin = require_role(UserRole.admin)
require_installateur = require_role(UserRole.installateur, UserRole.admin)
require_klant = require_role(UserRole.klant, UserRole.admin)


def require_active_subscription(
    user: Annotated[User, Depends(require_installateur)],
) -> User:
    """Block access for installateurs without an active Stripe subscription.

    Admins bypass this gate so AAA-Lex staff can always inspect data.
    """
    if user.role == UserRole.admin:
        return user
    org = user.organisation
    if org is None or (org.subscription_status or "").lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Actief abonnement vereist",
        )
    return user
