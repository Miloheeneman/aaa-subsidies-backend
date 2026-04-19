"""Installer-facing API: leads, dossiers, stats.

All endpoints require an ``installateur`` (or admin) role.  Lead and
dossier data is gated behind ``require_active_subscription`` so a
non-paying installateur sees only the subscription page.

Lead privacy
------------
Until an installateur explicitly accepts a lead by setting status to
``contact_opgenomen`` we redact full client contact details (email,
phone, full address, last name).  Postcode + city remain visible so
the installateur can judge regional fit.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import (
    DbSession,
    require_active_subscription,
    require_installateur,
)
from app.api.routes.aanvragen import _aanvraag_out
from app.models import (
    AAALexProject,
    InstallateurLead,
    Organisation,
    SubsidieAanvraag,
    User,
)
from app.models.enums import (
    AanvraagStatus,
    LeadStatus,
    OrganisationType,
    UserRole,
)
from app.schemas.aanvraag import AanvraagOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/installateur", tags=["installateur"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LeadAanvraagSummary(BaseModel):
    id: UUID
    regeling: str
    type_aanvrager: str
    maatregel: str
    investering_bedrag: Optional[Decimal] = None
    geschatte_subsidie: Optional[Decimal] = None
    postcode: Optional[str] = None
    plaats: Optional[str] = None


class LeadClientPreview(BaseModel):
    """Limited client data shown before the lead is accepted."""

    first_name: Optional[str] = None


class LeadClientFull(BaseModel):
    """Full client contact data, only visible after `contact_opgenomen`."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    phone: Optional[str] = None
    organisation_name: Optional[str] = None
    full_address: Optional[str] = None


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    id: UUID
    status: str
    regio: Optional[str] = None
    created_at: str
    aanvraag: LeadAanvraagSummary
    client_preview: LeadClientPreview
    client: Optional[LeadClientFull] = None  # populated only when unlocked


class LeadStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


class DossierListItem(BaseModel):
    id: UUID
    regeling: str
    type_aanvrager: str
    status: str
    investering_bedrag: Optional[Decimal] = None
    geschatte_subsidie: Optional[Decimal] = None
    toegekende_subsidie: Optional[Decimal] = None
    deadline_datum: Optional[str] = None
    organisation_name: Optional[str] = None
    aanvrager_name: Optional[str] = None


class StatsResponse(BaseModel):
    active_leads: int
    won_leads: int
    active_dossiers: int
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_installateur_org(user: User) -> Organisation:
    org = user.organisation
    if org is None or org.type != OrganisationType.installateur:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen installateurs hebben toegang tot deze pagina",
        )
    return org


def _project_for_aanvraag(db, aanvraag_id: UUID) -> Optional[AAALexProject]:
    return db.execute(
        select(AAALexProject).where(AAALexProject.aanvraag_id == aanvraag_id)
    ).scalar_one_or_none()


def _primary_user(org: Organisation) -> Optional[User]:
    if not org or not org.users:
        return None
    return min(org.users, key=lambda u: u.created_at)


def _build_lead_out(db, lead: InstallateurLead) -> LeadOut:
    aanvraag = lead.aanvraag
    project = _project_for_aanvraag(db, aanvraag.id) if aanvraag else None
    org = aanvraag.organisation if aanvraag else None
    contact = aanvraag.aanvrager if aanvraag else None

    summary = LeadAanvraagSummary(
        id=aanvraag.id,
        regeling=aanvraag.regeling.value,
        type_aanvrager=aanvraag.type_aanvrager.value,
        maatregel=aanvraag.maatregel.value,
        investering_bedrag=aanvraag.investering_bedrag,
        geschatte_subsidie=aanvraag.geschatte_subsidie,
        postcode=project.postcode if project else None,
        plaats=project.plaats if project else (lead.regio or None),
    )

    preview = LeadClientPreview(
        first_name=contact.first_name if contact else None,
    )

    full: Optional[LeadClientFull] = None
    if lead.status != LeadStatus.nieuw:
        # Lead has been accepted (or beyond) → reveal full contact details.
        if contact is not None:
            full = LeadClientFull(
                first_name=contact.first_name,
                last_name=contact.last_name,
                email=contact.email,
                phone=contact.phone,
                organisation_name=org.name if org else None,
                full_address=project.pandadres if project else (org.address if org else None),
            )

    return LeadOut(
        id=lead.id,
        status=lead.status.value,
        regio=lead.regio,
        created_at=lead.created_at.isoformat() if lead.created_at else "",
        aanvraag=summary,
        client_preview=preview,
        client=full,
    )


# ---------------------------------------------------------------------------
# Stats (no subscription required so the dashboard can render a banner)
# ---------------------------------------------------------------------------


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="KPI's voor de installateur dashboard",
)
def stats(
    db: DbSession,
    user: Annotated[User, Depends(require_installateur)],
) -> StatsResponse:
    org = _ensure_installateur_org(user)

    active_leads = int(
        db.execute(
            select(func.count(InstallateurLead.id)).where(
                and_(
                    InstallateurLead.installateur_id == org.id,
                    InstallateurLead.status.in_(
                        [LeadStatus.nieuw, LeadStatus.contact_opgenomen]
                    ),
                )
            )
        ).scalar_one()
    )
    won_leads = int(
        db.execute(
            select(func.count(InstallateurLead.id)).where(
                and_(
                    InstallateurLead.installateur_id == org.id,
                    InstallateurLead.status == LeadStatus.gewonnen,
                )
            )
        ).scalar_one()
    )
    active_dossiers = int(
        db.execute(
            select(func.count(SubsidieAanvraag.id)).where(
                and_(
                    SubsidieAanvraag.installateur_id == org.id,
                    SubsidieAanvraag.status.notin_(
                        [AanvraagStatus.goedgekeurd, AanvraagStatus.afgewezen]
                    ),
                )
            )
        ).scalar_one()
    )

    return StatsResponse(
        active_leads=active_leads,
        won_leads=won_leads,
        active_dossiers=active_dossiers,
        subscription_plan=org.subscription_plan,
        subscription_status=org.subscription_status,
    )


# ---------------------------------------------------------------------------
# Leads (subscription gated)
# ---------------------------------------------------------------------------


@router.get(
    "/leads",
    response_model=list[LeadOut],
    summary="Leads voor deze installateur",
)
def list_leads(
    db: DbSession,
    user: Annotated[User, Depends(require_active_subscription)],
    status_: Annotated[
        Optional[str], Query(alias="status", description="Filter op leadstatus")
    ] = None,
) -> list[LeadOut]:
    org = _ensure_installateur_org(user)
    stmt = (
        select(InstallateurLead)
        .where(InstallateurLead.installateur_id == org.id)
        .options(
            selectinload(InstallateurLead.aanvraag).selectinload(
                SubsidieAanvraag.organisation
            ),
            selectinload(InstallateurLead.aanvraag).selectinload(
                SubsidieAanvraag.aanvrager
            ),
        )
        .order_by(InstallateurLead.created_at.desc())
    )
    if status_:
        try:
            stmt = stmt.where(InstallateurLead.status == LeadStatus(status_))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Onbekende leadstatus '{status_}'",
            ) from exc
    leads = db.execute(stmt).scalars().all()
    return [_build_lead_out(db, lead) for lead in leads]


@router.patch(
    "/leads/{lead_id}",
    response_model=LeadOut,
    summary="Werk de status van een lead bij",
)
def update_lead(
    lead_id: UUID,
    payload: LeadStatusUpdate,
    db: DbSession,
    user: Annotated[User, Depends(require_active_subscription)],
) -> LeadOut:
    org = _ensure_installateur_org(user)
    lead = db.get(InstallateurLead, lead_id)
    if lead is None or lead.installateur_id != org.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lead niet gevonden"
        )
    try:
        new_status = LeadStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Onbekende leadstatus '{payload.status}'",
        ) from exc

    lead.status = new_status

    # When the installateur accepts the lead, also wire them onto the
    # aanvraag as the assigned installateur (so the dossier shows up
    # under /installateur/dossiers).
    if (
        new_status == LeadStatus.contact_opgenomen
        and lead.aanvraag is not None
        and lead.aanvraag.installateur_id is None
    ):
        lead.aanvraag.installateur_id = org.id

    db.commit()
    db.refresh(lead)
    return _build_lead_out(db, lead)


# ---------------------------------------------------------------------------
# Dossiers (subscription gated)
# ---------------------------------------------------------------------------


@router.get(
    "/dossiers",
    response_model=list[DossierListItem],
    summary="Dossiers waar deze installateur op zit",
)
def list_dossiers(
    db: DbSession,
    user: Annotated[User, Depends(require_active_subscription)],
) -> list[DossierListItem]:
    org = _ensure_installateur_org(user)
    rows = (
        db.execute(
            select(SubsidieAanvraag)
            .where(SubsidieAanvraag.installateur_id == org.id)
            .options(
                selectinload(SubsidieAanvraag.organisation),
                selectinload(SubsidieAanvraag.aanvrager),
            )
            .order_by(SubsidieAanvraag.created_at.desc())
        )
        .scalars()
        .all()
    )
    items: list[DossierListItem] = []
    for a in rows:
        contact = a.aanvrager
        contact_name = None
        if contact is not None:
            contact_name = (
                " ".join([p for p in [contact.first_name, contact.last_name] if p])
                or contact.email
            )
        items.append(
            DossierListItem(
                id=a.id,
                regeling=a.regeling.value,
                type_aanvrager=a.type_aanvrager.value,
                status=a.status.value,
                investering_bedrag=a.investering_bedrag,
                geschatte_subsidie=a.geschatte_subsidie,
                toegekende_subsidie=a.toegekende_subsidie,
                deadline_datum=(
                    a.deadline_datum.isoformat() if a.deadline_datum else None
                ),
                organisation_name=a.organisation.name if a.organisation else None,
                aanvrager_name=contact_name,
            )
        )
    return items


@router.get(
    "/dossiers/{aanvraag_id}",
    response_model=AanvraagOut,
    summary="Detailweergave van een dossier voor de installateur",
)
def dossier_detail(
    aanvraag_id: UUID,
    db: DbSession,
    user: Annotated[User, Depends(require_active_subscription)],
) -> AanvraagOut:
    org = _ensure_installateur_org(user)
    aanvraag = db.get(SubsidieAanvraag, aanvraag_id)
    if aanvraag is None or (
        aanvraag.installateur_id != org.id and user.role != UserRole.admin
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dossier niet gevonden"
        )
    project_id = db.execute(
        select(AAALexProject.id).where(AAALexProject.aanvraag_id == aanvraag.id)
    ).scalar_one_or_none()
    return _aanvraag_out(aanvraag, aaa_lex_project_id=project_id)
