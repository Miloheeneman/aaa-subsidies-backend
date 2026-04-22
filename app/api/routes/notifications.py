"""In-app notificaties voor klantgebruikers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import DbSession, require_verified
from app.models import User
from app.models.enums import UserRole
from app.schemas.klant_notificaties import KlantNotificatieListResponse, KlantNotificatieOut
from app.services import klant_notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])

VerifiedUser = Annotated[User, Depends(require_verified)]


@router.get("", response_model=KlantNotificatieListResponse)
def list_notifications(user: VerifiedUser, db: DbSession) -> KlantNotificatieListResponse:
    if user.role != UserRole.klant:
        return KlantNotificatieListResponse(items=[], unread_count=0)
    rows = klant_notifications.list_for_user(db, user_id=user.id, limit=50)
    uc = klant_notifications.unread_count(db, user_id=user.id)
    return KlantNotificatieListResponse(
        items=[KlantNotificatieOut.model_validate(n) for n in rows],
        unread_count=uc,
    )


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def mark_notification_read(
    notification_id: UUID, user: VerifiedUser, db: DbSession
) -> Response:
    if user.role != UserRole.klant:
        raise HTTPException(status_code=403, detail="Alleen voor klanten")
    ok = klant_notifications.mark_read(
        db, notification_id=notification_id, user_id=user.id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Notificatie niet gevonden")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def mark_all_notifications_read(user: VerifiedUser, db: DbSession) -> Response:
    if user.role != UserRole.klant:
        raise HTTPException(status_code=403, detail="Alleen voor klanten")
    klant_notifications.mark_all_read(db, user_id=user.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
