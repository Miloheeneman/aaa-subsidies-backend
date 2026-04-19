"""Admin-only API routes (KPIs, full aanvraag list, status updates,
document verification, klant + installateur overviews)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from math import ceil
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, require_admin
from app.core.config import settings
from app.models import (
    AanvraagDocument,
    InstallateurLead,
    Organisation,
    RegelingConfig,
    SubsidieAanvraag,
    User,
)
from app.models.enums import (
    AanvraagStatus,
    LeadStatus,
    OrganisationType,
    RegelingCode,
)
from app.schemas.admin import (
    AdminAanvraagListItem,
    AdminAanvragenPage,
    AdminDashboardResponse,
    DeadlineRunResponse,
    InstallateurSummary,
    KlantSummary,
    RegelingCounts,
    RegelingConfigOut,
    RegelingConfigUpdate,
    StatusCounts,
    StatusUpdateRequest,
)
from app.schemas.documenten import DocumentOut
from app.services.deadline_service import check_all_deadlines
from app.services.email import (
    send_aanvraag_afgewezen_email,
    send_aanvraag_goedgekeurd_email,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _frontend_aanvraag_url(aanvraag_id: UUID) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/aanvraag/{aanvraag_id}"


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=AdminDashboardResponse,
    summary="KPI overzicht voor admin",
)
def dashboard(db: DbSession) -> AdminDashboardResponse:
    today = date.today()
    start_of_month = today.replace(day=1)
    in_14_days = today + timedelta(days=14)

    totaal = db.execute(select(func.count()).select_from(SubsidieAanvraag)).scalar_one()

    per_status_rows = db.execute(
        select(SubsidieAanvraag.status, func.count())
        .group_by(SubsidieAanvraag.status)
    ).all()
    per_status = StatusCounts()
    for stat, count in per_status_rows:
        setattr(per_status, stat.value, int(count))

    per_regeling_rows = db.execute(
        select(SubsidieAanvraag.regeling, func.count())
        .group_by(SubsidieAanvraag.regeling)
    ).all()
    per_regeling = RegelingCounts()
    for reg, count in per_regeling_rows:
        setattr(per_regeling, reg.value, int(count))

    totaal_geschatte = db.execute(
        select(func.coalesce(func.sum(SubsidieAanvraag.geschatte_subsidie), 0))
    ).scalar_one()
    totaal_toegekend = db.execute(
        select(func.coalesce(func.sum(SubsidieAanvraag.toegekende_subsidie), 0))
    ).scalar_one()
    totaal_fee = db.execute(
        select(func.coalesce(func.sum(SubsidieAanvraag.aaa_lex_fee_bedrag), 0))
    ).scalar_one()

    aanvragen_deze_maand = db.execute(
        select(func.count())
        .select_from(SubsidieAanvraag)
        .where(SubsidieAanvraag.created_at >= datetime.combine(start_of_month, datetime.min.time(), tzinfo=timezone.utc))
    ).scalar_one()

    deadlines_verlopen = db.execute(
        select(func.count())
        .select_from(SubsidieAanvraag)
        .where(
            and_(
                SubsidieAanvraag.deadline_datum.is_not(None),
                SubsidieAanvraag.deadline_datum < today,
                SubsidieAanvraag.status.notin_(
                    [AanvraagStatus.goedgekeurd, AanvraagStatus.afgewezen]
                ),
            )
        )
    ).scalar_one()

    deadlines_binnen_14 = db.execute(
        select(func.count())
        .select_from(SubsidieAanvraag)
        .where(
            and_(
                SubsidieAanvraag.deadline_datum.is_not(None),
                SubsidieAanvraag.deadline_datum >= today,
                SubsidieAanvraag.deadline_datum <= in_14_days,
                SubsidieAanvraag.status.notin_(
                    [AanvraagStatus.goedgekeurd, AanvraagStatus.afgewezen]
                ),
            )
        )
    ).scalar_one()

    return AdminDashboardResponse(
        totaal_aanvragen=int(totaal),
        per_status=per_status,
        per_regeling=per_regeling,
        totaal_geschatte_subsidie=_quantize(_to_decimal(totaal_geschatte)),
        totaal_toegekende_subsidie=_quantize(_to_decimal(totaal_toegekend)),
        totaal_aaa_lex_fee=_quantize(_to_decimal(totaal_fee)),
        aanvragen_deze_maand=int(aanvragen_deze_maand),
        deadlines_verlopen=int(deadlines_verlopen),
        deadlines_binnen_14_dagen=int(deadlines_binnen_14),
    )


# ---------------------------------------------------------------------------
# Aanvragen list (admin)
# ---------------------------------------------------------------------------


@router.get(
    "/aanvragen",
    response_model=AdminAanvragenPage,
    summary="Volledige aanvraaglijst met filters en paginering",
)
def list_aanvragen(
    db: DbSession,
    status_: Annotated[
        Optional[str], Query(alias="status", description="Filter op status")
    ] = None,
    regeling: Annotated[Optional[str], Query()] = None,
    organisation_id: Annotated[Optional[UUID], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=200)] = 20,
) -> AdminAanvragenPage:
    base = select(SubsidieAanvraag).options(
        selectinload(SubsidieAanvraag.organisation),
        selectinload(SubsidieAanvraag.aanvrager),
    )
    count_stmt = select(func.count()).select_from(SubsidieAanvraag)

    if status_:
        try:
            status_enum = AanvraagStatus(status_)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Onbekende status '{status_}'",
            ) from exc
        base = base.where(SubsidieAanvraag.status == status_enum)
        count_stmt = count_stmt.where(SubsidieAanvraag.status == status_enum)
    if regeling:
        try:
            reg_enum = RegelingCode(regeling)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Onbekende regeling '{regeling}'",
            ) from exc
        base = base.where(SubsidieAanvraag.regeling == reg_enum)
        count_stmt = count_stmt.where(SubsidieAanvraag.regeling == reg_enum)
    if organisation_id is not None:
        base = base.where(SubsidieAanvraag.organisation_id == organisation_id)
        count_stmt = count_stmt.where(
            SubsidieAanvraag.organisation_id == organisation_id
        )

    total = int(db.execute(count_stmt).scalar_one())
    base = (
        base.order_by(SubsidieAanvraag.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = db.execute(base).scalars().all()
    items: list[AdminAanvraagListItem] = []
    for a in rows:
        contact = a.aanvrager
        org = a.organisation
        items.append(
            AdminAanvraagListItem(
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
                deadline_datum=a.deadline_datum.isoformat()
                if a.deadline_datum
                else None,
                deadline_type=(
                    a.deadline_type.value if a.deadline_type is not None else None
                ),
                created_at=a.created_at,
                organisation_id=a.organisation_id,
                organisation_name=org.name if org else "—",
                aanvrager_id=a.aanvrager_id,
                aanvrager_name=" ".join(
                    [p for p in [contact.first_name, contact.last_name] if p]
                )
                or contact.email,
                aanvrager_email=contact.email,
            )
        )

    pages = ceil(total / per_page) if per_page > 0 else 1
    return AdminAanvragenPage(
        items=items, total=total, page=page, per_page=per_page, pages=max(pages, 1)
    )


# ---------------------------------------------------------------------------
# Status update
# ---------------------------------------------------------------------------


@router.patch(
    "/aanvragen/{aanvraag_id}/status",
    summary="Update aanvraagstatus (admin only). Trigger emails bij goed/afgekeurd.",
)
def update_status(
    aanvraag_id: UUID,
    payload: StatusUpdateRequest,
    db: DbSession,
) -> dict:
    aanvraag = db.get(SubsidieAanvraag, aanvraag_id)
    if aanvraag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Aanvraag niet gevonden"
        )
    new_status = AanvraagStatus(payload.status)

    if new_status == AanvraagStatus.goedgekeurd:
        if payload.toegekende_subsidie is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "toegekende_subsidie is verplicht bij goedkeuring"
                ),
            )
        aanvraag.toegekende_subsidie = payload.toegekende_subsidie
        # Recompute fee based on toegekende_subsidie + active fee_percentage.
        if aanvraag.aaa_lex_fee_percentage is not None:
            aanvraag.aaa_lex_fee_bedrag = (
                payload.toegekende_subsidie
                * aanvraag.aaa_lex_fee_percentage
                / Decimal("100")
            ).quantize(Decimal("0.01"))
    elif new_status == AanvraagStatus.afgewezen:
        if not (payload.notes and payload.notes.strip()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Notities (reden) zijn verplicht bij afwijzing",
            )

    aanvraag.status = new_status
    if payload.notes is not None and payload.notes.strip():
        prefix = aanvraag.notes or ""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        marker = (
            f"[admin {timestamp} → {new_status.value}] "
            f"{payload.notes.strip()}"
        )
        aanvraag.notes = (prefix + ("\n" if prefix else "") + marker).strip()

    db.commit()
    db.refresh(aanvraag)

    # Emails (non-blocking; logged if Resend not configured).
    aanvraag_url = _frontend_aanvraag_url(aanvraag.id)
    contact = aanvraag.aanvrager
    if new_status == AanvraagStatus.goedgekeurd and contact is not None:
        toegekend = _quantize(_to_decimal(aanvraag.toegekende_subsidie))
        fee = _quantize(_to_decimal(aanvraag.aaa_lex_fee_bedrag))
        netto = _quantize(toegekend - fee)
        send_aanvraag_goedgekeurd_email(
            to=contact.email,
            first_name=contact.first_name,
            regeling=aanvraag.regeling.value,
            toegekende_subsidie=f"€ {toegekend}",
            aaa_lex_fee=f"€ {fee}",
            netto_uitbetaling=f"€ {netto}",
            aanvraag_url=aanvraag_url,
        )
    elif new_status == AanvraagStatus.afgewezen and contact is not None:
        send_aanvraag_afgewezen_email(
            to=contact.email,
            first_name=contact.first_name,
            regeling=aanvraag.regeling.value,
            reden=(payload.notes or "").strip() or "Geen reden opgegeven.",
            aanvraag_url=aanvraag_url,
        )

    return {
        "id": str(aanvraag.id),
        "status": aanvraag.status.value,
        "toegekende_subsidie": (
            str(aanvraag.toegekende_subsidie)
            if aanvraag.toegekende_subsidie is not None
            else None
        ),
        "aaa_lex_fee_bedrag": (
            str(aanvraag.aaa_lex_fee_bedrag)
            if aanvraag.aaa_lex_fee_bedrag is not None
            else None
        ),
        "notes": aanvraag.notes,
    }


# ---------------------------------------------------------------------------
# Document verification
# ---------------------------------------------------------------------------


@router.patch(
    "/documenten/{document_id}/verify",
    response_model=DocumentOut,
    summary="Markeer document als geverifieerd",
)
def verify_document(document_id: UUID, db: DbSession) -> DocumentOut:
    doc = db.get(AanvraagDocument, document_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document niet gevonden"
        )
    if doc.storage_url.startswith("pending://"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document upload nog niet bevestigd",
        )
    doc.verified = True
    db.commit()
    db.refresh(doc)
    return DocumentOut(
        id=doc.id,
        aanvraag_id=doc.aanvraag_id,
        document_type=doc.document_type.value,
        filename=doc.filename,
        storage_url=doc.storage_url,
        verified=doc.verified,
        pending_upload=False,
        notes=doc.notes,
        uploaded_at=doc.uploaded_at,
    )


# ---------------------------------------------------------------------------
# Klanten + Installateurs
# ---------------------------------------------------------------------------


@router.get(
    "/klanten",
    response_model=list[KlantSummary],
    summary="Overzicht klantorganisaties",
)
def list_klanten(db: DbSession) -> list[KlantSummary]:
    rows = (
        db.execute(
            select(Organisation)
            .where(Organisation.type == OrganisationType.klant)
            .options(selectinload(Organisation.users))
            .order_by(Organisation.created_at.desc())
        )
        .scalars()
        .all()
    )

    out: list[KlantSummary] = []
    for org in rows:
        agg = db.execute(
            select(
                func.count(SubsidieAanvraag.id),
                func.coalesce(func.sum(SubsidieAanvraag.geschatte_subsidie), 0),
                func.coalesce(func.sum(SubsidieAanvraag.toegekende_subsidie), 0),
            ).where(SubsidieAanvraag.organisation_id == org.id)
        ).one()
        primary = (
            min(org.users, key=lambda u: u.created_at) if org.users else None
        )
        out.append(
            KlantSummary(
                id=org.id,
                name=org.name,
                kvk_number=org.kvk_number,
                primary_contact_name=(
                    " ".join(
                        [p for p in [primary.first_name, primary.last_name] if p]
                    )
                    or primary.email
                )
                if primary
                else None,
                primary_contact_email=primary.email if primary else None,
                aanvraag_count=int(agg[0]),
                totaal_geschatte_subsidie=_quantize(_to_decimal(agg[1])),
                totaal_toegekende_subsidie=_quantize(_to_decimal(agg[2])),
                created_at=org.created_at,
            )
        )
    return out


@router.get(
    "/installateurs",
    response_model=list[InstallateurSummary],
    summary="Overzicht installateurorganisaties",
)
def list_installateurs(db: DbSession) -> list[InstallateurSummary]:
    rows = (
        db.execute(
            select(Organisation)
            .where(Organisation.type == OrganisationType.installateur)
            .order_by(Organisation.created_at.desc())
        )
        .scalars()
        .all()
    )
    out: list[InstallateurSummary] = []
    for org in rows:
        lead_count = int(
            db.execute(
                select(func.count(InstallateurLead.id)).where(
                    InstallateurLead.installateur_id == org.id
                )
            ).scalar_one()
        )
        active_dossier_count = int(
            db.execute(
                select(func.count(SubsidieAanvraag.id)).where(
                    and_(
                        SubsidieAanvraag.installateur_id == org.id,
                        SubsidieAanvraag.status.notin_(
                            [
                                AanvraagStatus.goedgekeurd,
                                AanvraagStatus.afgewezen,
                            ]
                        ),
                    )
                )
            ).scalar_one()
        )
        out.append(
            InstallateurSummary(
                id=org.id,
                name=org.name,
                subscription_plan=org.subscription_plan,
                subscription_status=org.subscription_status,
                lead_count=lead_count,
                active_dossier_count=active_dossier_count,
                created_at=org.created_at,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Regelingen config (admin)
# ---------------------------------------------------------------------------


def _regeling_out(cfg: RegelingConfig) -> RegelingConfigOut:
    return RegelingConfigOut(
        id=cfg.id,
        code=cfg.code.value,
        naam=cfg.naam,
        beschrijving=cfg.beschrijving or "",
        actief=cfg.actief,
        fee_percentage=cfg.fee_percentage,
        min_investering=cfg.min_investering,
        max_subsidie=cfg.max_subsidie,
        aanvraag_termijn_dagen=cfg.aanvraag_termijn_dagen,
        updated_at=cfg.updated_at,
    )


@router.get(
    "/regelingen",
    response_model=list[RegelingConfigOut],
    summary="Volledige regelingenconfig (alle 5 regelingen)",
)
def list_regelingen(db: DbSession) -> list[RegelingConfigOut]:
    rows = (
        db.execute(select(RegelingConfig).order_by(RegelingConfig.code))
        .scalars()
        .all()
    )
    return [_regeling_out(r) for r in rows]


@router.patch(
    "/regelingen/{code}",
    response_model=RegelingConfigOut,
    summary="Werk één regeling bij (naam, fee%, actief, ...)",
)
def update_regeling(
    code: str, payload: RegelingConfigUpdate, db: DbSession
) -> RegelingConfigOut:
    try:
        reg_enum = RegelingCode(code)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Onbekende regeling '{code}'",
        ) from exc

    cfg = db.execute(
        select(RegelingConfig).where(RegelingConfig.code == reg_enum)
    ).scalar_one_or_none()
    if cfg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Regeling {reg_enum.value} niet gevonden in config",
        )

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(cfg, field, value)

    db.commit()
    db.refresh(cfg)
    return _regeling_out(cfg)


# ---------------------------------------------------------------------------
# Deadline check (manual trigger; cron lives in GitHub Actions)
# ---------------------------------------------------------------------------


@router.post(
    "/run-deadline-check",
    response_model=DeadlineRunResponse,
    summary="Trigger deadline-warning emails handmatig",
)
def run_deadline_check(db: DbSession) -> DeadlineRunResponse:
    result = check_all_deadlines(db)
    return DeadlineRunResponse(
        checked=result.checked,
        warnings_sent=result.warnings_sent,
        expired=result.expired,
        skipped_recent=result.skipped_recent,
        skipped_no_contact=result.skipped_no_contact,
    )
