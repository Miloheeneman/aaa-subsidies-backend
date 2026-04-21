"""Panden CRUD + maatregelen binnen een pand."""

from __future__ import annotations

from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_verified
from app.api.routes._panden_common import (
    can_access_pand,
    enforce_pand_limit,
    get_pand_or_404,
    is_admin,
)
from app.models import Maatregel, Organisation, Pand, User
from app.models.enums import (
    DeadlineStatus,
    EigenaarType,
    Energielabel,
    PandType,
    UserRole,
)
from app.schemas.panden import (
    MaatregelListItem,
    PandCreate,
    PandDetail,
    PandListItem,
    PandOut,
    PandUpdate,
)
from app.services import panden_deadline

router = APIRouter(prefix="/panden", tags=["panden"])

VerifiedUser = Annotated[User, Depends(require_verified)]


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


_DEADLINE_PRIORITY = {
    DeadlineStatus.verlopen: 4,
    DeadlineStatus.kritiek: 3,
    DeadlineStatus.waarschuwing: 2,
    DeadlineStatus.ok: 1,
}


def _pand_out(pand: Pand) -> PandOut:
    org_name = pand.organisation.name if pand.organisation is not None else None
    return PandOut(
        id=pand.id,
        organisation_id=pand.organisation_id,
        organisation_name=org_name,
        created_by=pand.created_by,
        straat=pand.straat,
        huisnummer=pand.huisnummer,
        postcode=pand.postcode,
        plaats=pand.plaats,
        bouwjaar=pand.bouwjaar,
        pand_type=pand.pand_type.value,
        eigenaar_type=pand.eigenaar_type.value,
        energielabel_huidig=(
            pand.energielabel_huidig.value
            if pand.energielabel_huidig is not None
            else None
        ),
        energielabel_na_maatregelen=(
            pand.energielabel_na_maatregelen.value
            if pand.energielabel_na_maatregelen is not None
            else None
        ),
        oppervlakte_m2=pand.oppervlakte_m2,
        notities=pand.notities,
        aaa_lex_project_id=pand.aaa_lex_project_id,
        created_at=pand.created_at,
        updated_at=pand.updated_at,
    )


def _maatregel_list_item(m: Maatregel) -> MaatregelListItem:
    docs = getattr(m, "documenten", None) or []
    return MaatregelListItem(
        id=m.id,
        pand_id=m.pand_id,
        maatregel_type=m.maatregel_type.value,
        status=m.status.value,
        regeling_code=(
            m.regeling_code.value if m.regeling_code is not None else None
        ),
        deadline_indienen=m.deadline_indienen,
        deadline_type=(
            m.deadline_type.value if m.deadline_type is not None else None
        ),
        deadline_status=(
            m.deadline_status.value if m.deadline_status is not None else None
        ),
        investering_bedrag=m.investering_bedrag,
        geschatte_subsidie=m.geschatte_subsidie,
        toegekende_subsidie=m.toegekende_subsidie,
        document_count=len(docs),
        documents_uploaded=len(docs),
        documents_verified=sum(1 for d in docs if d.geverifieerd_door_admin),
        # documents_required wordt gevuld bij /checklist — in de
        # lijst-context is dat te duur (N+1), dus rapporteren we 0.
        documents_required=0,
        created_at=m.created_at,
    )


def _pand_deadline_status(pand: Pand) -> Optional[str]:
    """Neem de 'meest urgente' deadline over de maatregelen."""
    best: Optional[DeadlineStatus] = None
    best_priority = 0
    for m in getattr(pand, "maatregelen", []) or []:
        s = m.deadline_status
        if s is None:
            continue
        prio = _DEADLINE_PRIORITY.get(s, 0)
        if prio > best_priority:
            best = s
            best_priority = prio
    return best.value if best is not None else None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[PandListItem],
    summary="Lijst van panden",
)
def list_panden(
    user: VerifiedUser,
    db: DbSession,
    deadline_status: Annotated[
        Optional[str],
        Query(description="Filter op dominante deadline status"),
    ] = None,
    klant_organisation_id: Annotated[
        Optional[UUID],
        Query(
            description=(
                "Admin-only: filter op klant-organisatie (genegeerd voor "
                "niet-admin accounts)."
            )
        ),
    ] = None,
) -> list[PandListItem]:
    stmt = (
        select(Pand)
        .where(Pand.deleted.is_(False))
        .options(selectinload(Pand.maatregelen))
        .order_by(Pand.created_at.desc())
    )

    if not is_admin(user):
        if user.organisation_id is None:
            return []
        stmt = stmt.where(Pand.organisation_id == user.organisation_id)
    elif klant_organisation_id is not None:
        stmt = stmt.where(Pand.organisation_id == klant_organisation_id)

    items: list[PandListItem] = []
    for pand in db.execute(stmt).scalars().all():
        status_value = _pand_deadline_status(pand)
        if deadline_status and status_value != deadline_status:
            continue
        items.append(
            PandListItem(
                id=pand.id,
                straat=pand.straat,
                huisnummer=pand.huisnummer,
                postcode=pand.postcode,
                plaats=pand.plaats,
                bouwjaar=pand.bouwjaar,
                pand_type=pand.pand_type.value,
                eigenaar_type=pand.eigenaar_type.value,
                energielabel_huidig=(
                    pand.energielabel_huidig.value
                    if pand.energielabel_huidig is not None
                    else None
                ),
                maatregelen_count=len(pand.maatregelen),
                deadline_status=status_value,
                created_at=pand.created_at,
            )
        )
    return items


@router.post(
    "",
    response_model=PandOut,
    status_code=status.HTTP_201_CREATED,
    summary="Maak een nieuw pand aan",
)
def create_pand(
    payload: PandCreate,
    user: VerifiedUser,
    db: DbSession,
) -> PandOut:
    # Klant-accounts moeten aan een organisatie gekoppeld zijn.
    if user.organisation_id is None and not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uw account is niet gekoppeld aan een organisatie",
        )

    enforce_pand_limit(db, user)

    pand = Pand(
        organisation_id=user.organisation_id,
        created_by=user.id,
        straat=payload.straat.strip(),
        huisnummer=payload.huisnummer.strip(),
        postcode=payload.postcode.strip().upper(),
        plaats=payload.plaats.strip(),
        bouwjaar=payload.bouwjaar,
        pand_type=PandType(payload.pand_type),
        eigenaar_type=EigenaarType(payload.eigenaar_type),
        oppervlakte_m2=payload.oppervlakte_m2,
        notities=payload.notities,
    )
    db.add(pand)
    db.commit()
    db.refresh(pand)
    return _pand_out(pand)


@router.get(
    "/{pand_id}",
    response_model=PandDetail,
    summary="Pand detail inclusief maatregelen",
)
def get_pand(
    pand_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> PandDetail:
    pand = db.execute(
        select(Pand)
        .where(Pand.id == pand_id)
        .options(selectinload(Pand.maatregelen).selectinload(Maatregel.documenten))
    ).scalar_one_or_none()
    if pand is None or pand.deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pand niet gevonden"
        )
    if not can_access_pand(pand, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot dit pand",
        )

    base = _pand_out(pand)
    maatregelen = [
        _maatregel_list_item(m)
        for m in sorted(
            pand.maatregelen, key=lambda x: x.created_at, reverse=True
        )
    ]
    return PandDetail(**base.model_dump(), maatregelen=maatregelen)


@router.put(
    "/{pand_id}",
    response_model=PandOut,
    summary="Bewerk een pand",
)
def update_pand(
    pand_id: UUID,
    payload: PandUpdate,
    user: VerifiedUser,
    db: DbSession,
) -> PandOut:
    pand = get_pand_or_404(db, pand_id, user)
    data = payload.model_dump(exclude_unset=True)

    # Klant mag AAA-Lex opname-velden niet wijzigen.
    admin_only_fields = {
        "energielabel_huidig",
        "energielabel_na_maatregelen",
    }
    if not is_admin(user):
        for field in admin_only_fields:
            if field in data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Veld '{field}' kan alleen door AAA-Lex worden ingevuld"
                    ),
                )

    if "straat" in data and data["straat"] is not None:
        pand.straat = data["straat"].strip()
    if "huisnummer" in data and data["huisnummer"] is not None:
        pand.huisnummer = data["huisnummer"].strip()
    if "postcode" in data and data["postcode"] is not None:
        pand.postcode = data["postcode"].strip().upper()
    if "plaats" in data and data["plaats"] is not None:
        pand.plaats = data["plaats"].strip()
    if "bouwjaar" in data and data["bouwjaar"] is not None:
        pand.bouwjaar = data["bouwjaar"]
    if "pand_type" in data and data["pand_type"] is not None:
        pand.pand_type = PandType(data["pand_type"])
    if "eigenaar_type" in data and data["eigenaar_type"] is not None:
        pand.eigenaar_type = EigenaarType(data["eigenaar_type"])
    if "oppervlakte_m2" in data:
        pand.oppervlakte_m2 = data["oppervlakte_m2"]
    if "notities" in data:
        pand.notities = data["notities"]
    if "energielabel_huidig" in data:
        pand.energielabel_huidig = (
            Energielabel(data["energielabel_huidig"])
            if data["energielabel_huidig"] is not None
            else None
        )
    if "energielabel_na_maatregelen" in data:
        pand.energielabel_na_maatregelen = (
            Energielabel(data["energielabel_na_maatregelen"])
            if data["energielabel_na_maatregelen"] is not None
            else None
        )

    db.commit()
    db.refresh(pand)
    return _pand_out(pand)


@router.delete(
    "/{pand_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete een pand",
)
def delete_pand(
    pand_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> Response:
    pand = get_pand_or_404(db, pand_id, user)
    pand.deleted = True
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
