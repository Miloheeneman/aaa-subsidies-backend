"""Panden + maatregelen + maatregel-documenten endpoints (STAP 9).

Een klant ziet en bewerkt alleen panden van de eigen organisatie; een
admin ziet panden van alle klanten en kan AAA-Lex-only velden vullen
(energielabels, notities, documenten verifiëren).

De deadline engine wordt op elke POST/PUT van een maatregel opnieuw
uitgevoerd zodat de lijstweergave zonder berekeningen direct de juiste
kleur kan tonen.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Annotated, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, require_verified
from app.core.config import settings
from app.models import (
    Maatregel,
    MaatregelDocument,
    Organisation,
    Pand,
    User,
)
from app.models.enums import (
    DeadlineStatus,
    MaatregelDocumentType,
    MaatregelStatus,
    MaatregelType,
    RegelingCode,
    UserRole,
)
from app.schemas.panden import (
    ChecklistItemOut,
    ChecklistResponse,
    DocumentOut,
    MaatregelCreate,
    MaatregelOut,
    MaatregelShort,
    MaatregelUpdate,
    PandCreate,
    PandDetailResponse,
    PandListResponse,
    PandOut,
    PandUpdate,
    QuotaInfo,
    IsdeWarmtepompAanvraagCreate,
    SubsidieMatchOut,
    SubsidieMatchResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services import r2_storage
from app.services.email import send_admin_isde_warmtepomp_intake_email
from app.services.panden_service import (
    allowed_document_types,
    calculate_deadline,
    estimate_subsidie,
    get_matching_subsidies,
    get_required_documents,
    infer_regeling,
)
from app.services.plan_service import get_quota

logger = logging.getLogger(__name__)

router = APIRouter(tags=["panden"])

VerifiedUser = Annotated[User, Depends(require_verified)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def _pand_or_403(db: Session, pand_id: UUID, user: User) -> Pand:
    pand = db.get(Pand, pand_id)
    if pand is None or pand.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pand niet gevonden"
        )
    if not _is_admin(user) and pand.organisation_id != user.organisation_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot dit pand",
        )
    return pand


def _maatregel_or_403(
    db: Session, maatregel_id: UUID, user: User
) -> Maatregel:
    m = db.get(Maatregel, maatregel_id)
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maatregel niet gevonden",
        )
    _pand_or_403(db, m.pand_id, user)  # raises on access denied
    return m


def _admin_notification_recipients(db: Session) -> List[str]:
    """E-mailadressen voor admin-notificaties (Resend)."""
    raw = (settings.ADMIN_NOTIFICATION_EMAIL or "").strip()
    if raw:
        return [e.strip() for e in raw.split(",") if e.strip()]
    rows = db.execute(
        select(User.email).where(User.role == UserRole.admin)
    ).scalars().all()
    return sorted({e for e in rows if e})


def _quota_info(db: Session, user: User) -> QuotaInfo:
    q = get_quota(db, user)
    return QuotaInfo(
        plan=q.plan,
        limit=q.limit,
        used=q.used,
        remaining=q.remaining,
        exceeded=q.exceeded,
    )


def _worst_deadline_status(
    statuses: List[Optional[DeadlineStatus]],
) -> Optional[DeadlineStatus]:
    ORDER = {
        DeadlineStatus.verlopen: 4,
        DeadlineStatus.kritiek: 3,
        DeadlineStatus.waarschuwing: 2,
        DeadlineStatus.ok: 1,
    }
    worst: Optional[DeadlineStatus] = None
    for s in statuses:
        if s is None:
            continue
        if worst is None or ORDER[s] > ORDER[worst]:
            worst = s
    return worst


def _pand_to_out(pand: Pand, *, maatregelen: List[Maatregel]) -> PandOut:
    data = PandOut.model_validate(pand)
    data.aantal_maatregelen = len(maatregelen)
    data.worst_deadline_status = _worst_deadline_status(
        [m.deadline_status for m in maatregelen]
    )
    return data


def _recalc_deadline(m: Maatregel) -> None:
    """Refresh deadline_* columns from the current maatregel state."""
    regeling = m.regeling_code
    if regeling is None:
        regeling = infer_regeling(m.maatregel_type)
        # Don't persist inferred regeling yet — that's an admin decision.
    result = calculate_deadline(
        maatregel_type=m.maatregel_type,
        installatie_datum=m.installatie_datum,
        offerte_datum=m.offerte_datum,
        regeling_code=regeling,
    )
    m.deadline_indienen = result.deadline_indienen
    m.deadline_type = result.deadline_type
    m.deadline_status = result.deadline_status


def _auto_estimate_subsidie(
    m: Maatregel, *, overwrite: bool = False
) -> None:
    """Vul geschatte_subsidie zodra we de input hebben.

    Overschrijft alleen als ``overwrite=True`` (bij PUT als de klant
    expliciet een bedrag doorgeeft krijgt die voorrang).
    """
    if not overwrite and m.geschatte_subsidie is not None:
        return
    est = estimate_subsidie(m.maatregel_type, m.investering_bedrag)
    if est is not None:
        m.geschatte_subsidie = est


# ---------------------------------------------------------------------------
# Panden CRUD
# ---------------------------------------------------------------------------


@router.get("/panden", response_model=PandListResponse)
def list_panden(
    user: VerifiedUser,
    db: DbSession,
    deadline_status: Optional[DeadlineStatus] = Query(default=None),
    organisation_id: Optional[UUID] = Query(default=None),
) -> PandListResponse:
    """Panden van de ingelogde gebruiker. Admin ziet alles."""
    stmt = select(Pand).where(Pand.is_deleted.is_(False))
    if not _is_admin(user):
        if user.organisation_id is None:
            return PandListResponse(
                items=[], totaal=0, quota=_quota_info(db, user)
            )
        stmt = stmt.where(Pand.organisation_id == user.organisation_id)
    else:
        if organisation_id is not None:
            stmt = stmt.where(Pand.organisation_id == organisation_id)

    stmt = stmt.order_by(Pand.created_at.desc())
    panden = list(db.execute(stmt).scalars().all())

    # Bulk-load maatregelen zodat we geen N+1 hebben op het overzicht.
    pand_ids = [p.id for p in panden]
    maatregelen_per_pand: dict[UUID, List[Maatregel]] = {pid: [] for pid in pand_ids}
    if pand_ids:
        rows = db.execute(
            select(Maatregel).where(Maatregel.pand_id.in_(pand_ids))
        ).scalars().all()
        for m in rows:
            maatregelen_per_pand[m.pand_id].append(m)

    # Admins krijgen de organisatie-naam mee zodat het admin-overzicht per
    # rij kan tonen van welke klant het pand is.
    org_names: dict[UUID, str] = {}
    if _is_admin(user) and panden:
        org_ids = {p.organisation_id for p in panden}
        rows = db.execute(
            select(Organisation.id, Organisation.name).where(
                Organisation.id.in_(org_ids)
            )
        ).all()
        org_names = {row[0]: row[1] for row in rows}

    items = []
    for p in panden:
        out = _pand_to_out(p, maatregelen=maatregelen_per_pand.get(p.id, []))
        if _is_admin(user):
            out.organisation_name = org_names.get(p.organisation_id)
        items.append(out)
    if deadline_status is not None:
        items = [i for i in items if i.worst_deadline_status == deadline_status]

    return PandListResponse(
        items=items, totaal=len(items), quota=_quota_info(db, user)
    )


@router.post(
    "/panden",
    response_model=PandOut,
    status_code=status.HTTP_201_CREATED,
)
def create_pand(
    payload: PandCreate,
    user: VerifiedUser,
    db: DbSession,
) -> PandOut:
    if user.organisation_id is None and not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account zonder organisatie kan geen panden aanmaken",
        )

    # Plan-limit enforcement — admins slaan we over (zie get_quota).
    quota = get_quota(db, user)
    if quota.exceeded:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PLAN_LIMIT_REACHED",
                "plan": quota.plan,
                "limit": quota.limit,
                "used": quota.used,
                "message": (
                    f"Uw huidige plan ({quota.plan}) staat {quota.limit} "
                    f"panden toe. Upgrade voor meer panden."
                ),
            },
        )

    pand = Pand(
        organisation_id=user.organisation_id,  # type: ignore[arg-type]
        created_by=user.id,
        straat=payload.straat.strip(),
        huisnummer=payload.huisnummer.strip(),
        postcode=payload.postcode.strip(),
        plaats=payload.plaats.strip(),
        bouwjaar=payload.bouwjaar,
        pand_type=payload.pand_type,
        eigenaar_type=payload.eigenaar_type,
    )
    db.add(pand)
    db.commit()
    db.refresh(pand)
    return _pand_to_out(pand, maatregelen=[])


@router.get("/panden/{pand_id}", response_model=PandDetailResponse)
def get_pand(
    pand_id: UUID, user: VerifiedUser, db: DbSession
) -> PandDetailResponse:
    pand = _pand_or_403(db, pand_id, user)
    maatregelen = list(
        db.execute(
            select(Maatregel)
            .where(Maatregel.pand_id == pand_id)
            .order_by(Maatregel.created_at.desc())
        )
        .scalars()
        .all()
    )
    base = _pand_to_out(pand, maatregelen=maatregelen).model_dump()
    base["maatregelen"] = [MaatregelShort.model_validate(m) for m in maatregelen]
    return PandDetailResponse.model_validate(base)


@router.put("/panden/{pand_id}", response_model=PandOut)
def update_pand(
    pand_id: UUID,
    payload: PandUpdate,
    user: VerifiedUser,
    db: DbSession,
) -> PandOut:
    pand = _pand_or_403(db, pand_id, user)

    # Klant mag alleen pandgegevens aanpassen; AAA-Lex-velden blijven
    # read-only tot een admin ze invult.
    klant_fields = {
        "straat",
        "huisnummer",
        "postcode",
        "plaats",
        "bouwjaar",
        "pand_type",
        "eigenaar_type",
    }
    admin_fields = {
        "energielabel_huidig",
        "energielabel_na_maatregelen",
        "oppervlakte_m2",
        "notities",
        "aaa_lex_project_id",
    }

    data = payload.model_dump(exclude_unset=True)
    for field in klant_fields & data.keys():
        value = data[field]
        if isinstance(value, str):
            value = value.strip()
        setattr(pand, field, value)
    if _is_admin(user):
        for field in admin_fields & data.keys():
            setattr(pand, field, data[field])

    db.commit()
    db.refresh(pand)

    # Aantal maatregelen herberekenen zodat _pand_to_out klopt.
    maatregelen = list(
        db.execute(select(Maatregel).where(Maatregel.pand_id == pand.id))
        .scalars()
        .all()
    )
    return _pand_to_out(pand, maatregelen=maatregelen)


@router.delete(
    "/panden/{pand_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_pand(
    pand_id: UUID, user: VerifiedUser, db: DbSession
) -> Response:
    pand = _pand_or_403(db, pand_id, user)
    pand.is_deleted = True
    pand.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Subsidie matching
# ---------------------------------------------------------------------------


@router.get(
    "/panden/{pand_id}/subsidies",
    response_model=SubsidieMatchResponse,
)
def get_subsidies_voor_pand(
    pand_id: UUID, user: VerifiedUser, db: DbSession
) -> SubsidieMatchResponse:
    """Welke subsidies passen bij dit pand?

    Gebruikt :func:`panden_service.get_matching_subsidies` als single source
    of truth en splitst de uitkomst in eligible / niet-eligible voor de UI.
    """
    pand = _pand_or_403(db, pand_id, user)
    matches = get_matching_subsidies(pand)
    eligible = [
        SubsidieMatchOut(**m.__dict__) for m in matches if m.eligible
    ]
    niet_eligible = [
        SubsidieMatchOut(**m.__dict__) for m in matches if not m.eligible
    ]
    return SubsidieMatchResponse(
        pand_id=pand.id,
        eligible=eligible,
        niet_eligible=niet_eligible,
    )


_ISDE_WP_SUBTYPE_LABELS: dict[MaatregelType, str] = {
    MaatregelType.warmtepomp_lucht_water: "Lucht/water warmtepomp",
    MaatregelType.warmtepomp_water_water: "Water/water warmtepomp",
    MaatregelType.warmtepomp_hybride: "Hybride warmtepomp",
}


def _email_row(label: str, value: object) -> str:
    if value is None or value == "":
        v_html = "—"
    else:
        v_html = html.escape(str(value))
    return (
        "<tr>"
        f'<td style="padding:6px 12px 6px 0;font-weight:600;color:#6b7280;'
        f'vertical-align:top;">{html.escape(label)}</td>'
        f'<td style="padding:6px 0;">{v_html}</td>'
        "</tr>"
    )


@router.post(
    "/panden/{pand_id}/aanvragen/isde-warmtepomp",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_isde_warmtepomp_aanvraag(
    pand_id: UUID,
    payload: IsdeWarmtepompAanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    """Wizard-submit: sla ISDE warmtepomp-intake op als nieuwe maatregel."""
    pand = _pand_or_403(db, pand_id, user)

    m_type = MaatregelType(payload.warmtepomp_subtype)
    if m_type not in _ISDE_WP_SUBTYPE_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ongeldig warmtepomp-type voor deze wizard",
        )

    m_status = (
        MaatregelStatus.gepland
        if payload.situatie == "geinstalleerd"
        else MaatregelStatus.orientatie
    )
    offerte_datum = payload.offerte_datum if payload.heeft_offerte else None

    def _strip_opt(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        t = s.strip()
        return t or None

    m = Maatregel(
        pand_id=pand.id,
        created_by=user.id,
        maatregel_type=m_type,
        omschrijving=(
            "ISDE warmtepomp — intake via wizard ("
            + (
                "reeds geïnstalleerd"
                if payload.situatie == "geinstalleerd"
                else "oriëntatie"
            )
            + ")"
        ),
        status=m_status,
        apparaat_merk=_strip_opt(payload.apparaat_merk),
        apparaat_typenummer=_strip_opt(payload.apparaat_typenummer),
        apparaat_meldcode=_strip_opt(payload.apparaat_meldcode),
        installateur_naam=payload.installateur_naam.strip(),
        installateur_kvk=_strip_opt(payload.installateur_kvk),
        installateur_gecertificeerd=bool(payload.installateur_gecertificeerd),
        installatie_datum=payload.installatie_datum,
        offerte_datum=offerte_datum,
        investering_bedrag=payload.investering_bedrag,
        regeling_code=RegelingCode.ISDE,
    )
    _recalc_deadline(m)
    _auto_estimate_subsidie(m)
    db.add(m)
    db.commit()
    db.refresh(m)

    pand_adres = (
        f"{pand.straat} {pand.huisnummer}, {pand.postcode} {pand.plaats}"
    )
    subject = f"Nieuwe ISDE warmtepomp aanvraag — {pand_adres}"

    situatie_txt = (
        "Ja, al geïnstalleerd"
        if payload.situatie == "geinstalleerd"
        else "Nog aan het oriënteren"
    )
    rows = [
        _email_row("Klant-e-mail", user.email),
        _email_row("Situatie", situatie_txt),
        _email_row(
            "Type warmtepomp",
            _ISDE_WP_SUBTYPE_LABELS.get(m_type, m_type.value),
        ),
        _email_row("Merk", m.apparaat_merk),
        _email_row("Typenummer", m.apparaat_typenummer),
        _email_row("Meldcode", m.apparaat_meldcode),
        _email_row("Installateur", m.installateur_naam),
        _email_row("KvK installateur", m.installateur_kvk),
        _email_row(
            "Gecertificeerd",
            "Ja" if m.installateur_gecertificeerd else "Nee",
        ),
        _email_row(
            "Installatiedatum",
            m.installatie_datum.isoformat() if m.installatie_datum else None,
        ),
        _email_row(
            "Geschatte investering (€)",
            f"{m.investering_bedrag:.2f}" if m.investering_bedrag is not None else None,
        ),
        _email_row(
            "Offerte",
            "Ja"
            if payload.heeft_offerte
            else "Nee",
        ),
        _email_row(
            "Offertedatum",
            m.offerte_datum.isoformat() if m.offerte_datum else None,
        ),
        _email_row(
            "Geschatte subsidie (€)",
            f"{m.geschatte_subsidie:.2f}" if m.geschatte_subsidie is not None else None,
        ),
        _email_row(
            "Deadline indienen",
            m.deadline_indienen.isoformat() if m.deadline_indienen else None,
        ),
        _email_row("Maatregel-ID", str(m.id)),
    ]
    rows_html = "".join(rows)

    for admin_to in _admin_notification_recipients(db):
        send_admin_isde_warmtepomp_intake_email(
            to=admin_to,
            subject=subject,
            pand_adres=pand_adres,
            rows_html=rows_html,
        )

    return MaatregelOut.model_validate(m)


# ---------------------------------------------------------------------------
# Maatregelen
# ---------------------------------------------------------------------------


@router.get(
    "/panden/{pand_id}/maatregelen",
    response_model=List[MaatregelOut],
)
def list_maatregelen(
    pand_id: UUID, user: VerifiedUser, db: DbSession
) -> List[MaatregelOut]:
    _pand_or_403(db, pand_id, user)
    rows = (
        db.execute(
            select(Maatregel)
            .where(Maatregel.pand_id == pand_id)
            .order_by(Maatregel.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [MaatregelOut.model_validate(m) for m in rows]


@router.post(
    "/panden/{pand_id}/maatregelen",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_maatregel(
    pand_id: UUID,
    payload: MaatregelCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    pand = _pand_or_403(db, pand_id, user)

    if payload.maatregel_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="maatregel_type is verplicht",
        )

    m = Maatregel(
        pand_id=pand.id,
        created_by=user.id,
        maatregel_type=payload.maatregel_type,
        omschrijving=payload.omschrijving,
        status=payload.status or MaatregelStatus.orientatie,
        apparaat_merk=payload.apparaat_merk,
        apparaat_typenummer=payload.apparaat_typenummer,
        apparaat_meldcode=payload.apparaat_meldcode,
        installateur_naam=payload.installateur_naam,
        installateur_kvk=payload.installateur_kvk,
        installateur_gecertificeerd=bool(payload.installateur_gecertificeerd),
        installatie_datum=payload.installatie_datum,
        offerte_datum=payload.offerte_datum,
        investering_bedrag=payload.investering_bedrag,
        geschatte_subsidie=payload.geschatte_subsidie,
        regeling_code=payload.regeling_code or infer_regeling(payload.maatregel_type),
    )
    _recalc_deadline(m)
    _auto_estimate_subsidie(m)
    db.add(m)
    db.commit()
    db.refresh(m)
    return MaatregelOut.model_validate(m)


@router.get(
    "/maatregelen/{maatregel_id}",
    response_model=MaatregelOut,
)
def get_maatregel(
    maatregel_id: UUID, user: VerifiedUser, db: DbSession
) -> MaatregelOut:
    m = _maatregel_or_403(db, maatregel_id, user)
    return MaatregelOut.model_validate(m)


@router.put(
    "/maatregelen/{maatregel_id}",
    response_model=MaatregelOut,
)
def update_maatregel(
    maatregel_id: UUID,
    payload: MaatregelUpdate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    m = _maatregel_or_403(db, maatregel_id, user)

    data = payload.model_dump(exclude_unset=True)
    # toegekende_subsidie is AAA-Lex only.
    if "toegekende_subsidie" in data and not _is_admin(user):
        data.pop("toegekende_subsidie")

    for field, value in data.items():
        setattr(m, field, value)

    _recalc_deadline(m)
    # Als de klant geen expliciete schatting meestuurt, recalculeren we;
    # stuurt de klant wel een bedrag mee, dan respecteren we dat.
    if "geschatte_subsidie" not in data:
        _auto_estimate_subsidie(m, overwrite=True)
    db.commit()
    db.refresh(m)
    return MaatregelOut.model_validate(m)


@router.delete(
    "/maatregelen/{maatregel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_maatregel(
    maatregel_id: UUID, user: VerifiedUser, db: DbSession
) -> Response:
    m = _maatregel_or_403(db, maatregel_id, user)
    db.delete(m)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Checklist + documenten
# ---------------------------------------------------------------------------


def _build_checklist(
    m: Maatregel, docs: List[MaatregelDocument]
) -> ChecklistResponse:
    checklist = get_required_documents(m.maatregel_type)

    # Group uploaded docs per type. We accept multiple uploads per type
    # (bijv. meerdere werkzaamheden-fotos) and beschouwen het type als
    # "geüpload" zodra er minimaal één staat.
    docs_per_type: dict[MaatregelDocumentType, List[MaatregelDocument]] = {}
    for d in docs:
        docs_per_type.setdefault(d.document_type, []).append(d)

    items: List[ChecklistItemOut] = []
    for c in checklist:
        uploaded = docs_per_type.get(c.document_type, [])
        verified = any(d.geverifieerd_door_admin for d in uploaded)
        items.append(
            ChecklistItemOut(
                document_type=c.document_type,
                label=c.label,
                uitleg=c.uitleg,
                verplicht=c.verplicht,
                geupload=bool(uploaded),
                geverifieerd=verified,
                document_id=uploaded[0].id if uploaded else None,
            )
        )

    verplicht = [c for c in checklist if c.verplicht]
    verplicht_geupload = sum(1 for c in verplicht if docs_per_type.get(c.document_type))
    verplicht_geverifieerd = sum(
        1
        for c in verplicht
        if any(
            d.geverifieerd_door_admin for d in docs_per_type.get(c.document_type, [])
        )
    )
    return ChecklistResponse(
        maatregel_id=m.id,
        items=items,
        verplicht_totaal=len(verplicht),
        verplicht_geupload=verplicht_geupload,
        verplicht_geverifieerd=verplicht_geverifieerd,
        compleet=verplicht_geupload == len(verplicht),
    )


@router.get(
    "/maatregelen/{maatregel_id}/checklist",
    response_model=ChecklistResponse,
)
def get_checklist(
    maatregel_id: UUID, user: VerifiedUser, db: DbSession
) -> ChecklistResponse:
    m = _maatregel_or_403(db, maatregel_id, user)
    docs = list(
        db.execute(
            select(MaatregelDocument).where(
                MaatregelDocument.maatregel_id == m.id
            )
        )
        .scalars()
        .all()
    )
    return _build_checklist(m, docs)


@router.get(
    "/maatregelen/{maatregel_id}/documenten",
    response_model=List[DocumentOut],
)
def list_documenten(
    maatregel_id: UUID, user: VerifiedUser, db: DbSession
) -> List[DocumentOut]:
    m = _maatregel_or_403(db, maatregel_id, user)
    rows = list(
        db.execute(
            select(MaatregelDocument)
            .where(MaatregelDocument.maatregel_id == m.id)
            .order_by(MaatregelDocument.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        DocumentOut(
            **{
                **DocumentOut.model_validate(d).model_dump(),
                "pending_upload": d.r2_key.startswith("pending://"),
            }
        )
        for d in rows
    ]


@router.post(
    "/maatregelen/{maatregel_id}/documenten",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    maatregel_id: UUID,
    payload: UploadUrlRequest,
    user: VerifiedUser,
    db: DbSession,
) -> UploadUrlResponse:
    """Reserveer een presigned R2-URL voor een nieuw document.

    Het document record wordt direct aangemaakt met een ``pending://``
    r2_key; de client bevestigt de upload via de confirm-endpoint
    hieronder.
    """
    m = _maatregel_or_403(db, maatregel_id, user)

    allowed = allowed_document_types(m.maatregel_type)
    if payload.document_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Documenttype '{payload.document_type.value}' is niet "
                f"geldig voor maatregel {m.maatregel_type.value}"
            ),
        )

    pand = db.get(Pand, m.pand_id)
    assert pand is not None
    document_id = uuid4()
    object_key = (
        f"{pand.organisation_id}/panden/{pand.id}/maatregelen/{m.id}/"
        f"{document_id}/{r2_storage.safe_filename(payload.bestandsnaam)}"
    )

    upload_url = r2_storage.generate_upload_url(
        object_key, content_type=payload.content_type, expires_in=3600
    )

    doc = MaatregelDocument(
        id=document_id,
        maatregel_id=m.id,
        document_type=payload.document_type,
        bestandsnaam=r2_storage.safe_filename(payload.bestandsnaam),
        r2_key=r2_storage.make_pending_url(object_key),
        geupload_door=user.id,
    )
    db.add(doc)
    db.commit()

    return UploadUrlResponse(
        upload_url=upload_url,
        document_id=document_id,
        r2_key=object_key,
        expires_in=3600,
    )


@router.post(
    "/maatregelen/{maatregel_id}/documenten/{document_id}/confirm",
    response_model=DocumentOut,
)
def confirm_document(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> DocumentOut:
    _maatregel_or_403(db, maatregel_id, user)
    doc = db.get(MaatregelDocument, document_id)
    if doc is None or doc.maatregel_id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document niet gevonden",
        )
    object_key = r2_storage.object_key_from_storage_url(doc.r2_key)
    doc.r2_key = r2_storage.make_committed_url(object_key)
    db.commit()
    db.refresh(doc)
    out = DocumentOut.model_validate(doc).model_dump()
    out["pending_upload"] = doc.r2_key.startswith("pending://")
    return DocumentOut(**out)


@router.post(
    "/maatregelen/{maatregel_id}/documenten/{document_id}/verify",
    response_model=DocumentOut,
)
def verify_document(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> DocumentOut:
    """Admin-only: vink document af als geverifieerd."""
    if not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen admins kunnen documenten verifiëren",
        )
    _maatregel_or_403(db, maatregel_id, user)
    doc = db.get(MaatregelDocument, document_id)
    if doc is None or doc.maatregel_id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document niet gevonden",
        )
    doc.geverifieerd_door_admin = True
    db.commit()
    db.refresh(doc)
    out = DocumentOut.model_validate(doc).model_dump()
    out["pending_upload"] = doc.r2_key.startswith("pending://")
    return DocumentOut(**out)


@router.delete(
    "/maatregelen/{maatregel_id}/documenten/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> Response:
    _maatregel_or_403(db, maatregel_id, user)
    doc = db.get(MaatregelDocument, document_id)
    if doc is None or doc.maatregel_id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document niet gevonden",
        )
    if doc.geverifieerd_door_admin and not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geverifieerde documenten kunnen niet meer worden verwijderd",
        )
    object_key = r2_storage.object_key_from_storage_url(doc.r2_key)
    r2_storage.delete_object(object_key)
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/maatregelen/{maatregel_id}/documenten/{document_id}/download-url",
)
def download_document(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> dict[str, object]:
    _maatregel_or_403(db, maatregel_id, user)
    doc = db.get(MaatregelDocument, document_id)
    if doc is None or doc.maatregel_id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document niet gevonden",
        )
    if doc.r2_key.startswith("pending://"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document upload nog niet bevestigd",
        )
    key = r2_storage.object_key_from_storage_url(doc.r2_key)
    url = r2_storage.generate_download_url(
        key, expires_in=900, download_filename=doc.bestandsnaam
    )
    return {"download_url": url, "expires_in": 900}


# ---------------------------------------------------------------------------
# Admin widgets
# ---------------------------------------------------------------------------


@router.get(
    "/admin/panden/kritieke-deadlines",
    response_model=List[MaatregelOut],
)
def kritieke_deadlines(
    user: VerifiedUser,
    db: DbSession,
    max_dagen: int = Query(default=30, ge=0, le=365),
) -> List[MaatregelOut]:
    """Admin-widget: maatregelen met deadline binnen ``max_dagen`` dagen.

    Niet-admins krijgen 403 zodat deze widget alleen op het admin-
    dashboard zichtbaar is.
    """
    if not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen admins",
        )
    today = func.current_date()
    rows = (
        db.execute(
            select(Maatregel)
            .where(Maatregel.deadline_indienen.is_not(None))
            .where(
                Maatregel.deadline_status.in_(
                    [DeadlineStatus.kritiek, DeadlineStatus.waarschuwing, DeadlineStatus.verlopen]
                )
            )
            .order_by(Maatregel.deadline_indienen.asc())
        )
        .scalars()
        .all()
    )
    # In-python filter op max_dagen om ook ``verlopen`` rijen mee te nemen
    # (die hebben een negatieve delta maar blijven relevant op het dashboard).
    result: List[MaatregelOut] = []
    from datetime import date as _date

    today_py = _date.today()
    for m in rows:
        if m.deadline_indienen is None:
            continue
        delta = (m.deadline_indienen - today_py).days
        if delta <= max_dagen:
            result.append(MaatregelOut.model_validate(m))
    return result
