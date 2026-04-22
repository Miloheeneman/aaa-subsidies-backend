"""In-app notificaties voor klantaccounts (niet admin/installateur)."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import KlantNotificatie, User
from app.models.enums import MaatregelStatus, UserRole

logger = logging.getLogger(__name__)


def _kind_for_status(status: MaatregelStatus) -> str:
    if status in (MaatregelStatus.goedgekeurd, MaatregelStatus.afgewezen):
        return "subsidie_beslissing"
    return "status_update"


def notify_organisation_users(
    db: Session,
    *,
    organisation_id: UUID,
    kind: str,
    title: str,
    body: Optional[str],
    project_id: UUID,
    maatregel_id: Optional[UUID] = None,
) -> None:
    """Schrijf dezelfde notificatie voor alle gebruikers in de organisatie."""
    user_ids = (
        db.execute(
            select(User.id).where(
                User.organisation_id == organisation_id,
                User.role == UserRole.klant,
            )
        )
        .scalars()
        .all()
    )
    if not user_ids:
        logger.warning(
            "klant_notifications: geen klant-gebruikers voor org %s", organisation_id
        )
        return
    for uid in user_ids:
        db.add(
            KlantNotificatie(
                user_id=uid,
                kind=kind,
                title=title[:255],
                body=body,
                project_id=project_id,
                maatregel_id=maatregel_id,
            )
        )
    db.commit()


def notify_status_change_for_maatregel(
    db: Session,
    *,
    organisation_id: UUID,
    project_id: UUID,
    maatregel_id: UUID,
    subsidie_label: str,
    new_status: MaatregelStatus,
    status_label_nl: str,
) -> None:
    kind = _kind_for_status(new_status)
    title = (
        f"Beslissing RVO: {subsidie_label}"
        if kind == "subsidie_beslissing"
        else f"Statusupdate: {subsidie_label}"
    )
    body = f"De status van uw aanvraag is bijgewerkt naar: {status_label_nl}."
    notify_organisation_users(
        db,
        organisation_id=organisation_id,
        kind=kind,
        title=title,
        body=body,
        project_id=project_id,
        maatregel_id=maatregel_id,
    )


def notify_upload_verzoek(
    db: Session,
    *,
    organisation_id: UUID,
    project_id: UUID,
    maatregel_id: UUID,
    document_count: int,
) -> None:
    title = "Documenten nodig voor uw aanvraag"
    body = (
        f"AAA-Lex heeft {document_count} document(en) van u nodig om verder te gaan."
    )
    notify_organisation_users(
        db,
        organisation_id=organisation_id,
        kind="upload_verzoek",
        title=title,
        body=body,
        project_id=project_id,
        maatregel_id=maatregel_id,
    )


def list_for_user(db: Session, *, user_id: UUID, limit: int = 40) -> list[KlantNotificatie]:
    return list(
        db.execute(
            select(KlantNotificatie)
            .where(KlantNotificatie.user_id == user_id)
            .order_by(KlantNotificatie.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def unread_count(db: Session, *, user_id: UUID) -> int:
    from sqlalchemy import func

    return int(
        db.execute(
            select(func.count())
            .select_from(KlantNotificatie)
            .where(
                KlantNotificatie.user_id == user_id,
                KlantNotificatie.read_at.is_(None),
            )
        ).scalar_one()
    )


def mark_read(db: Session, *, notification_id: UUID, user_id: UUID) -> bool:
    from datetime import datetime, timezone

    res = db.execute(
        update(KlantNotificatie)
        .where(
            KlantNotificatie.id == notification_id,
            KlantNotificatie.user_id == user_id,
            KlantNotificatie.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
    return res.rowcount > 0  # type: ignore[attr-defined]


def mark_all_read(db: Session, *, user_id: UUID) -> None:
    from datetime import datetime, timezone

    db.execute(
        update(KlantNotificatie)
        .where(
            KlantNotificatie.user_id == user_id,
            KlantNotificatie.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
    )
