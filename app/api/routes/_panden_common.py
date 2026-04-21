"""Gedeelde helpers voor de /panden, /maatregelen en /documenten routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Maatregel, MaatregelDocument, Pand, User
from app.models.enums import PLAN_PAND_LIMITS, UserRole


def is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def can_access_pand(pand: Pand, user: User) -> bool:
    if is_admin(user):
        return True
    return (
        user.organisation_id is not None
        and pand.organisation_id == user.organisation_id
    )


def get_pand_or_404(db: Session, pand_id: UUID, user: User) -> Pand:
    pand = db.get(Pand, pand_id)
    if pand is None or pand.deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pand niet gevonden",
        )
    if not can_access_pand(pand, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot dit pand",
        )
    return pand


def get_maatregel_or_404(
    db: Session, maatregel_id: UUID, user: User
) -> Maatregel:
    maatregel = db.get(Maatregel, maatregel_id)
    if maatregel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maatregel niet gevonden",
        )
    pand = db.get(Pand, maatregel.pand_id)
    if pand is None or pand.deleted:
        # Parent pand weg/soft-deleted — als admin wel tonen is te
        # permissief; we behandelen 'n weesmaatregel gewoon als 404.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maatregel niet gevonden",
        )
    if not can_access_pand(pand, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot deze maatregel",
        )
    return maatregel


def get_maatregel_document_or_404(
    db: Session, document_id: UUID, user: User
) -> tuple[MaatregelDocument, Maatregel]:
    doc = db.get(MaatregelDocument, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document niet gevonden",
        )
    maatregel = get_maatregel_or_404(db, doc.maatregel_id, user)
    return doc, maatregel


def enforce_pand_limit(db: Session, user: User) -> None:
    """Gate voor POST /panden: handhaaft de plan-specifieke limiet.

    Admins én installateurs (die gaan niet via deze module maar kunnen
    in principe wel een pand aanmaken) hebben geen limiet.
    Klant-accounts bepalen op basis van hun ``subscription_plan``.
    """
    if is_admin(user) or user.role == UserRole.installateur:
        return
    if user.organisation_id is None:
        # Tel alleen per-user panden die deze user heeft aangemaakt.
        scope_filter = Pand.created_by == user.id
    else:
        scope_filter = Pand.organisation_id == user.organisation_id

    plan = (user.subscription_plan or "gratis").lower()
    limit = PLAN_PAND_LIMITS.get(plan)
    if limit is None:
        return  # enterprise / onbekend → geen limiet

    current = db.execute(
        select(func.count())
        .select_from(Pand)
        .where(scope_filter)
        .where(Pand.deleted.is_(False))
    ).scalar_one()

    if current >= limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "pand_limit_reached",
                "message": (
                    f"U heeft het maximum van {limit} panden bereikt voor "
                    f"het {plan}-plan. Upgrade voor meer panden."
                ),
                "plan": plan,
                "limit": limit,
                "current": int(current),
            },
        )
