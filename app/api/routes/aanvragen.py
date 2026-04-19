from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_verified
from app.models import (
    AAALexProject,
    AanvraagDocument,
    RegelingConfig,
    SubsidieAanvraag,
)
from app.models.enums import (
    AanvraagStatus,
    DeadlineType,
    DocumentType,
    Maatregel,
    RegelingCode,
    TypeAanvrager,
    UserRole,
)
from app.models.user import User
from app.schemas.aanvraag import (
    AanvraagCreate,
    AanvraagDocumentOut,
    AanvraagListItem,
    AanvraagOut,
    AanvraagUpdate,
    DocumentChecklistItem,
    DocumentChecklistResponse,
    StatusTimelineEvent,
)
from app.services.r2_storage import is_pending_storage_url
from app.services.subsidy_matching import (
    DOCUMENT_LABELS,
    REGELING_ESTIMATE_PCT,
    document_checklist_for,
)

router = APIRouter(prefix="/aanvragen", tags=["aanvragen"])


VerifiedUser = Annotated[User, Depends(require_verified)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATUS_TIMELINE_ORDER: list[AanvraagStatus] = [
    AanvraagStatus.intake,
    AanvraagStatus.documenten,
    AanvraagStatus.review,
    AanvraagStatus.ingediend,
    AanvraagStatus.goedgekeurd,
]

_STATUS_LABEL: dict[AanvraagStatus, str] = {
    AanvraagStatus.intake: "Intake",
    AanvraagStatus.documenten: "Documenten",
    AanvraagStatus.review: "Review",
    AanvraagStatus.ingediend: "Ingediend bij RVO",
    AanvraagStatus.goedgekeurd: "Goedgekeurd",
    AanvraagStatus.afgewezen: "Afgewezen",
}


def _is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def _can_access(aanvraag: SubsidieAanvraag, user: User) -> bool:
    if _is_admin(user):
        return True
    return aanvraag.organisation_id == user.organisation_id


def _fee_bedrag(
    geschatte: Optional[Decimal], fee_pct: Optional[Decimal]
) -> Optional[Decimal]:
    if geschatte is None or fee_pct is None:
        return None
    return (geschatte * fee_pct / Decimal("100")).quantize(Decimal("0.01"))


def _klant_ontvangt(
    geschatte: Optional[Decimal], fee: Optional[Decimal]
) -> Optional[Decimal]:
    if geschatte is None:
        return None
    return (geschatte - (fee or Decimal("0"))).quantize(Decimal("0.01"))


def _deadline_for(regeling: RegelingCode) -> tuple[Optional[date], Optional[DeadlineType]]:
    """Return (deadline_datum, deadline_type) for a newly created aanvraag."""
    today = date.today()
    if regeling in (RegelingCode.EIA, RegelingCode.MIA, RegelingCode.VAMIL):
        return today + timedelta(days=90), DeadlineType.EIA_3maanden
    if regeling == RegelingCode.DUMAVA:
        return today + timedelta(days=730), DeadlineType.DUMAVA_2jaar
    return None, None


def _estimate_subsidie(
    regeling: RegelingCode, investering: Optional[Decimal]
) -> Optional[Decimal]:
    if investering is None or investering <= 0:
        return None
    pct = REGELING_ESTIMATE_PCT[regeling]
    return (Decimal(str(investering)) * pct).quantize(Decimal("0.01"))


def _status_timeline(aanvraag: SubsidieAanvraag) -> list[StatusTimelineEvent]:
    current = aanvraag.status
    current_idx = (
        _STATUS_TIMELINE_ORDER.index(current)
        if current in _STATUS_TIMELINE_ORDER
        else -1
    )

    events: list[StatusTimelineEvent] = []

    # Handle 'afgewezen' specially — show happy path up to review + a rejected step
    if current == AanvraagStatus.afgewezen:
        for i, step in enumerate(_STATUS_TIMELINE_ORDER[:-1]):  # intake..ingediend
            events.append(
                StatusTimelineEvent(
                    status=step.value,
                    label=_STATUS_LABEL[step],
                    reached=True,
                    current=False,
                )
            )
        events.append(
            StatusTimelineEvent(
                status=AanvraagStatus.afgewezen.value,
                label=_STATUS_LABEL[AanvraagStatus.afgewezen],
                reached=True,
                current=True,
            )
        )
        return events

    for i, step in enumerate(_STATUS_TIMELINE_ORDER):
        reached = current_idx >= i
        is_current = i == current_idx
        events.append(
            StatusTimelineEvent(
                status=step.value,
                label=_STATUS_LABEL[step],
                reached=reached,
                current=is_current,
                at=aanvraag.updated_at if is_current else None,
            )
        )
    return events


def _document_out(doc: AanvraagDocument) -> AanvraagDocumentOut:
    return AanvraagDocumentOut(
        id=doc.id,
        document_type=doc.document_type.value
        if hasattr(doc.document_type, "value")
        else str(doc.document_type),
        filename=doc.filename,
        storage_url=doc.storage_url,
        verified=doc.verified,
        notes=doc.notes,
        uploaded_at=doc.uploaded_at,
    )


def _aanvraag_out(
    aanvraag: SubsidieAanvraag, *, aaa_lex_project_id=None
) -> AanvraagOut:
    fee = aanvraag.aaa_lex_fee_bedrag
    geschatte = aanvraag.geschatte_subsidie
    klant = _klant_ontvangt(geschatte, fee) if geschatte is not None else None
    org = aanvraag.organisation
    contact = aanvraag.aanvrager
    contact_name = None
    if contact is not None:
        contact_name = (
            " ".join([p for p in [contact.first_name, contact.last_name] if p])
            or contact.email
        )

    return AanvraagOut(
        id=aanvraag.id,
        organisation_id=aanvraag.organisation_id,
        aanvrager_id=aanvraag.aanvrager_id,
        regeling=aanvraag.regeling.value,
        type_aanvrager=aanvraag.type_aanvrager.value,
        maatregel=aanvraag.maatregel.value,
        status=aanvraag.status.value,
        investering_bedrag=aanvraag.investering_bedrag,
        geschatte_subsidie=geschatte,
        toegekende_subsidie=aanvraag.toegekende_subsidie,
        aaa_lex_fee_percentage=aanvraag.aaa_lex_fee_percentage,
        aaa_lex_fee_bedrag=fee,
        klant_ontvangt=klant,
        deadline_datum=aanvraag.deadline_datum,
        deadline_type=(
            aanvraag.deadline_type.value
            if aanvraag.deadline_type is not None
            else None
        ),
        rvo_aanvraagnummer=aanvraag.rvo_aanvraagnummer,
        rvo_status=aanvraag.rvo_status,
        notes=aanvraag.notes,
        created_at=aanvraag.created_at,
        updated_at=aanvraag.updated_at,
        organisation_name=org.name if org is not None else None,
        aanvrager_name=contact_name,
        aanvrager_email=contact.email if contact is not None else None,
        aanvrager_phone=contact.phone if contact is not None else None,
        aaa_lex_project_id=aaa_lex_project_id,
        documenten=[
            _document_out(d)
            for d in aanvraag.documenten
            if not is_pending_storage_url(d.storage_url)
        ],
        status_timeline=_status_timeline(aanvraag),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[AanvraagListItem],
    summary="Overzicht van aanvragen voor de huidige gebruiker",
)
def list_aanvragen(
    user: VerifiedUser,
    db: DbSession,
    status_: Annotated[
        Optional[str], Query(alias="status", description="Filter op status")
    ] = None,
    regeling: Annotated[
        Optional[str], Query(description="Filter op regeling (ISDE/EIA/MIA/VAMIL/DUMAVA)")
    ] = None,
) -> list[AanvraagListItem]:
    stmt = select(SubsidieAanvraag).options(selectinload(SubsidieAanvraag.documenten))

    if not _is_admin(user):
        if user.organisation_id is None:
            return []
        stmt = stmt.where(SubsidieAanvraag.organisation_id == user.organisation_id)

    if status_:
        try:
            status_enum = AanvraagStatus(status_)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Onbekende status '{status_}'",
            ) from exc
        stmt = stmt.where(SubsidieAanvraag.status == status_enum)

    if regeling:
        try:
            regeling_enum = RegelingCode(regeling)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Onbekende regeling '{regeling}'",
            ) from exc
        stmt = stmt.where(SubsidieAanvraag.regeling == regeling_enum)

    stmt = stmt.order_by(SubsidieAanvraag.created_at.desc())

    items: list[AanvraagListItem] = []
    for a in db.execute(stmt).scalars().all():
        required_types = document_checklist_for(a.regeling, a.type_aanvrager)
        uploaded_types = {
            d.document_type
            for d in a.documenten
            if not is_pending_storage_url(d.storage_url)
        }
        missing = [t for t in required_types if t not in uploaded_types]
        items.append(
            AanvraagListItem(
                id=a.id,
                regeling=a.regeling.value,
                type_aanvrager=a.type_aanvrager.value,
                maatregel=a.maatregel.value,
                status=a.status.value,
                investering_bedrag=a.investering_bedrag,
                geschatte_subsidie=a.geschatte_subsidie,
                toegekende_subsidie=a.toegekende_subsidie,
                aaa_lex_fee_percentage=a.aaa_lex_fee_percentage,
                aaa_lex_fee_bedrag=a.aaa_lex_fee_bedrag,
                deadline_datum=a.deadline_datum,
                deadline_type=(
                    a.deadline_type.value if a.deadline_type is not None else None
                ),
                created_at=a.created_at,
                document_count=len(a.documenten),
                missing_document_count=len(missing),
            )
        )
    return items


@router.post(
    "",
    response_model=AanvraagOut,
    status_code=status.HTTP_201_CREATED,
    summary="Maak een nieuwe aanvraag aan",
)
def create_aanvraag(
    payload: AanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> AanvraagOut:
    if user.organisation_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uw account is niet gekoppeld aan een organisatie",
        )

    regeling = RegelingCode(payload.regeling)
    type_aanvrager = TypeAanvrager(payload.type_aanvrager)
    maatregel = Maatregel(payload.maatregel)

    # Pull live fee percentage + actief from regelingen_config.
    cfg = db.execute(
        select(RegelingConfig).where(RegelingConfig.code == regeling)
    ).scalar_one_or_none()
    if cfg is None or not cfg.actief:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Regeling {regeling.value} is momenteel niet actief",
        )

    fee_pct = cfg.fee_percentage
    geschatte = _estimate_subsidie(regeling, payload.investering_bedrag)
    fee_bedrag = _fee_bedrag(geschatte, fee_pct)
    deadline_datum, deadline_type = _deadline_for(regeling)

    notes = payload.notes
    if payload.offerte_beschikbaar and notes is None:
        notes = (
            "Offerte is al beschikbaar. Deadline voor EIA/MIA/Vamil loopt "
            "vanaf ondertekening offerte."
        )

    aanvraag = SubsidieAanvraag(
        organisation_id=user.organisation_id,
        aanvrager_id=user.id,
        regeling=regeling,
        type_aanvrager=type_aanvrager,
        status=AanvraagStatus.intake,
        maatregel=maatregel,
        investering_bedrag=payload.investering_bedrag,
        geschatte_subsidie=geschatte,
        aaa_lex_fee_percentage=fee_pct,
        aaa_lex_fee_bedrag=fee_bedrag,
        deadline_datum=deadline_datum,
        deadline_type=deadline_type,
        notes=notes,
    )
    db.add(aanvraag)
    db.commit()
    db.refresh(aanvraag)

    return _aanvraag_out(aanvraag)


@router.get(
    "/{aanvraag_id}",
    response_model=AanvraagOut,
    summary="Detail van één aanvraag",
)
def get_aanvraag(
    aanvraag_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> AanvraagOut:
    aanvraag = db.get(SubsidieAanvraag, aanvraag_id)
    if aanvraag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Aanvraag niet gevonden"
        )
    if not _can_access(aanvraag, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot deze aanvraag",
        )
    project_id = db.execute(
        select(AAALexProject.id).where(AAALexProject.aanvraag_id == aanvraag.id)
    ).scalar_one_or_none()
    return _aanvraag_out(aanvraag, aaa_lex_project_id=project_id)


@router.patch(
    "/{aanvraag_id}",
    response_model=AanvraagOut,
    summary="Werk een aanvraag bij (klant mag geen status of regeling wijzigen)",
)
def update_aanvraag(
    aanvraag_id: UUID,
    payload: AanvraagUpdate,
    user: VerifiedUser,
    db: DbSession,
) -> AanvraagOut:
    aanvraag = db.get(SubsidieAanvraag, aanvraag_id)
    if aanvraag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Aanvraag niet gevonden"
        )
    if not _can_access(aanvraag, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot deze aanvraag",
        )

    data = payload.model_dump(exclude_unset=True)
    if "notes" in data:
        aanvraag.notes = data["notes"]
    if "gewenste_startdatum" in data:
        # gewenste_startdatum is not a dedicated column; we append to notes
        # so the wish is persisted. (A dedicated column can be added later
        # without breaking the API contract.)
        wens = data["gewenste_startdatum"]
        if wens is not None:
            marker = f"[gewenste startdatum: {wens.isoformat()}]"
            base = aanvraag.notes or ""
            if marker not in base:
                aanvraag.notes = (base + ("\n" if base else "") + marker).strip()
    if "investering_bedrag" in data:
        new_invest = data["investering_bedrag"]
        aanvraag.investering_bedrag = new_invest
        # Recalculate geschatte_subsidie + fee_bedrag when investment changes.
        new_geschatte = _estimate_subsidie(aanvraag.regeling, new_invest)
        aanvraag.geschatte_subsidie = new_geschatte
        aanvraag.aaa_lex_fee_bedrag = _fee_bedrag(
            new_geschatte, aanvraag.aaa_lex_fee_percentage
        )

    db.commit()
    db.refresh(aanvraag)
    return _aanvraag_out(aanvraag)


@router.get(
    "/{aanvraag_id}/documenten",
    response_model=DocumentChecklistResponse,
    summary="Documentenchecklist voor deze aanvraag",
)
def aanvraag_documenten(
    aanvraag_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> DocumentChecklistResponse:
    aanvraag = db.get(SubsidieAanvraag, aanvraag_id)
    if aanvraag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Aanvraag niet gevonden"
        )
    if not _can_access(aanvraag, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot deze aanvraag",
        )

    required_types = document_checklist_for(aanvraag.regeling, aanvraag.type_aanvrager)

    # Index uploaded docs by type (take most recent per type).
    # We only count documents that have actually been confirmed via R2 (not
    # presigned-but-not-confirmed rows).
    uploaded_by_type: dict[DocumentType, AanvraagDocument] = {}
    for doc in aanvraag.documenten:
        if is_pending_storage_url(doc.storage_url):
            continue
        dt = doc.document_type
        existing = uploaded_by_type.get(dt)
        if existing is None or doc.uploaded_at > existing.uploaded_at:
            uploaded_by_type[dt] = doc

    items: list[DocumentChecklistItem] = []
    for dt in required_types:
        doc = uploaded_by_type.get(dt)
        items.append(
            DocumentChecklistItem(
                document_type=dt.value,
                label=DOCUMENT_LABELS[dt],
                required=True,
                uploaded=doc is not None,
                verified=bool(doc.verified) if doc is not None else False,
                document_id=doc.id if doc is not None else None,
                upload_url=None,  # R2 upload lands in step 6
            )
        )

    # Also include any uploaded documents that are NOT on the required list
    # (marked required=False) so the client can still see them.
    for dt, doc in uploaded_by_type.items():
        if dt in required_types:
            continue
        items.append(
            DocumentChecklistItem(
                document_type=dt.value,
                label=DOCUMENT_LABELS.get(dt, dt.value),
                required=False,
                uploaded=True,
                verified=bool(doc.verified),
                document_id=doc.id,
                upload_url=None,
            )
        )

    uploaded_required = sum(
        1 for it in items if it.required and it.uploaded
    )
    required_count = sum(1 for it in items if it.required)
    missing_count = required_count - uploaded_required

    return DocumentChecklistResponse(
        aanvraag_id=aanvraag.id,
        regeling=aanvraag.regeling.value,
        items=items,
        uploaded_count=uploaded_required,
        required_count=required_count,
        missing_count=missing_count,
    )
