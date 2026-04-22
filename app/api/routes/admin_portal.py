"""Admin-portal API (Optie A): stats, klantboom, dossierlijst, export, interne notities."""

from __future__ import annotations

import csv
import html
import io
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from math import ceil
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import extract, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_admin
from app.core.config import settings
from app.models import (
    AdminMaatregelNote,
    AdminNotitie,
    AdminOrganisationNote,
    Maatregel,
    MaatregelDocument,
    Organisation,
    Project,
    UploadVerzoek,
    User,
)
from app.models.enums import (
    AdminNotitieEntityType,
    DeadlineStatus,
    MaatregelDocumentType,
    MaatregelStatus,
    OrganisationType,
    RegelingCode,
    UserRole,
)
from app.schemas.admin_portal import (
    ActionItemOut,
    ActivityItemOut,
    AdminNoteCreate,
    AdminNoteOut,
    DossierListItemOut,
    DossierListPage,
    KlantDetailOut,
    KlantProjectenTreeResponse,
    MaatregelStatusUpdateBody,
    MaatregelTreeOut,
    ProjectTreeOut,
    UploadVerzoekCreateBody,
    UploadVerzoekCreatedOut,
)
from app.services import email_service, klant_notifications
from app.services.projecten_service import allowed_document_types, get_required_documents

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin-portal"],
    dependencies=[Depends(require_admin)],
)


def _adres_label(p: Project) -> str:
    return f"{p.straat} {p.huisnummer}, {p.postcode} {p.plaats}"


def _checklist_counts(db, m: Maatregel) -> tuple[int, int]:
    checklist = get_required_documents(m.maatregel_type)
    verplicht = [c for c in checklist if c.verplicht]
    if not verplicht:
        return 0, 0
    rows = (
        db.execute(
            select(MaatregelDocument.document_type).where(
                MaatregelDocument.maatregel_id == m.id
            )
        )
        .scalars()
        .all()
    )
    have_types = set(rows)
    geupload = sum(1 for c in verplicht if c.document_type in have_types)
    return len(verplicht), geupload


@router.get("/portal/action-items", response_model=list[ActionItemOut])
def portal_action_items(db: DbSession) -> list[ActionItemOut]:
    today = date.today()
    in_14 = today + timedelta(days=14)
    items: list[ActionItemOut] = []

    q_kritiek = (
        select(Maatregel, Project, Organisation)
        .join(Project, Maatregel.project_id == Project.id)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .where(
            Project.is_deleted.is_(False),
            Maatregel.deadline_indienen.is_not(None),
            Maatregel.deadline_indienen <= in_14,
            Maatregel.status.notin_(
                [MaatregelStatus.goedgekeurd, MaatregelStatus.afgewezen]
            ),
        )
        .order_by(Maatregel.deadline_indienen.asc())
        .limit(40)
    )
    for m, p, org in db.execute(q_kritiek).all():
        items.append(
            ActionItemOut(
                urgency="kritiek",
                maatregel_id=m.id,
                project_id=p.id,
                organisation_id=org.id,
                organisation_name=org.name,
                project_adres=_adres_label(p),
                regeling=m.regeling_code.value if m.regeling_code else None,
                deadline_indienen=m.deadline_indienen,
                status=m.status.value,
                link=f"/admin/projecten/{p.id}/maatregelen/{m.id}",
            )
        )

    since = datetime.now(timezone.utc) - timedelta(days=14)
    q_oranje = (
        select(Maatregel, Project, Organisation)
        .join(Project, Maatregel.project_id == Project.id)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .where(
            Project.is_deleted.is_(False),
            Maatregel.status == MaatregelStatus.orientatie,
            Maatregel.created_at >= since,
        )
        .order_by(Maatregel.created_at.desc())
        .limit(40)
    )
    seen_ids = {i.maatregel_id for i in items}
    for row in db.execute(q_oranje).all():
        m, p, org = row[0], row[1], row[2]
        if m.id in seen_ids:
            continue
        items.append(
            ActionItemOut(
                urgency="waarschuwing",
                maatregel_id=m.id,
                project_id=p.id,
                organisation_id=org.id,
                organisation_name=org.name,
                project_adres=_adres_label(p),
                regeling=m.regeling_code.value if m.regeling_code else None,
                deadline_indienen=m.deadline_indienen,
                status=m.status.value,
                link=f"/admin/projecten/{p.id}/maatregelen/{m.id}",
            )
        )
        seen_ids.add(m.id)
    return items[:25]


@router.get("/portal/recent-activity", response_model=list[ActivityItemOut])
def portal_recent_activity(db: DbSession) -> list[ActivityItemOut]:
    events: list[tuple[datetime, str, Optional[str]]] = []

    m_rows = db.execute(
        select(Maatregel, Project, Organisation, User)
        .join(Project, Maatregel.project_id == Project.id)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .join(User, Maatregel.created_by == User.id)
        .where(Project.is_deleted.is_(False))
        .order_by(Maatregel.created_at.desc())
        .limit(8)
    ).all()
    for m, p, org, u in m_rows:
        reg = m.regeling_code.value if m.regeling_code else "subsidie"
        wizard = m.omschrijving and "wizard" in (m.omschrijving or "").lower()
        if wizard:
            msg = f"{org.name} vulde wizard in voor {reg}"
        else:
            msg = f"{org.name} maakte dossier aan ({reg})"
        link = f"/admin/projecten/{p.id}/maatregelen/{m.id}"
        events.append((m.created_at, msg, link))

    p_rows = db.execute(
        select(Project, Organisation, User)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .join(User, Project.created_by == User.id)
        .where(Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
        .limit(8)
    ).all()
    for pr, org, u in p_rows:
        events.append(
            (
                pr.created_at,
                f"{org.name} registreerde nieuw project",
                f"/admin/projecten?zoek={pr.postcode}",
            )
        )

    d_rows = db.execute(
        select(MaatregelDocument, Maatregel, Project, Organisation, User)
        .join(Maatregel, MaatregelDocument.maatregel_id == Maatregel.id)
        .join(Project, Maatregel.project_id == Project.id)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .join(User, MaatregelDocument.geupload_door == User.id)
        .where(User.role == UserRole.admin, Project.is_deleted.is_(False))
        .order_by(MaatregelDocument.created_at.desc())
        .limit(8)
    ).all()
    for doc, m, p, org, u in d_rows:
        events.append(
            (
                doc.created_at,
                f"{u.email} uploadde document voor {_adres_label(p)}",
                f"/admin/projecten/{p.id}/maatregelen/{m.id}",
            )
        )

    events.sort(key=lambda t: t[0], reverse=True)
    out: list[ActivityItemOut] = []
    for at, message, link in events[:10]:
        out.append(ActivityItemOut(at=at, message=message, link=link))
    return out


def _get_klant_org(db, org_id: UUID) -> Organisation:
    org = db.get(Organisation, org_id)
    if org is None or org.type != OrganisationType.klant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Klant niet gevonden",
        )
    return org


@router.get("/klanten/{org_id}", response_model=KlantDetailOut)
def get_klant_detail(org_id: UUID, db: DbSession) -> KlantDetailOut:
    org = _get_klant_org(db, org_id)
    users = list(
        db.execute(
            select(User)
            .where(User.organisation_id == org.id)
            .order_by(User.created_at.asc())
        )
        .scalars()
        .all()
    )
    primary = users[0] if users else None
    return KlantDetailOut(
        id=org.id,
        name=org.name,
        kvk_number=org.kvk_number,
        primary_contact_name=(
            " ".join([p for p in [primary.first_name, primary.last_name] if p])
            or primary.email
        )
        if primary
        else None,
        primary_contact_email=primary.email if primary else None,
        primary_phone=primary.phone if primary else None,
        subscription_plan=org.subscription_plan or (
            primary.subscription_plan if primary else None
        ),
        subscription_status=org.subscription_status
        or (primary.subscription_status if primary else None),
        created_at=org.created_at,
    )


@router.get(
    "/klanten/{org_id}/projecten",
    response_model=KlantProjectenTreeResponse,
)
def get_klant_projecten_tree(org_id: UUID, db: DbSession) -> KlantProjectenTreeResponse:
    org = _get_klant_org(db, org_id)
    projecten = (
        db.execute(
            select(Project)
            .options(selectinload(Project.maatregelen))
            .where(
                Project.organisation_id == org.id,
                Project.is_deleted.is_(False),
            )
            .order_by(Project.created_at.desc())
        )
        .scalars()
        .all()
    )
    out_projects: list[ProjectTreeOut] = []
    for p in projecten:
        ms_sorted = sorted(p.maatregelen, key=lambda x: x.created_at, reverse=True)
        m_out: list[MaatregelTreeOut] = []
        for m in ms_sorted:
            tot, up = _checklist_counts(db, m)
            m_out.append(
                MaatregelTreeOut(
                    id=m.id,
                    regeling_code=m.regeling_code.value if m.regeling_code else None,
                    status=m.status.value,
                    deadline_indienen=m.deadline_indienen,
                    deadline_status=m.deadline_status.value
                    if m.deadline_status
                    else None,
                    verplicht_docs_totaal=tot,
                    verplicht_docs_geupload=up,
                )
            )
        out_projects.append(
            ProjectTreeOut(
                id=p.id,
                adres_label=_adres_label(p),
                bouwjaar=p.bouwjaar,
                maatregelen=m_out,
            )
        )
    return KlantProjectenTreeResponse(
        organisation_id=org.id,
        organisation_name=org.name,
        projecten=out_projects,
    )


@router.get(
    "/klanten/{org_id}/notities",
    response_model=list[AdminNoteOut],
)
def list_org_notes(org_id: UUID, db: DbSession) -> list[AdminNoteOut]:
    _get_klant_org(db, org_id)
    rows = (
        db.execute(
            select(AdminOrganisationNote, User)
            .join(User, AdminOrganisationNote.author_id == User.id)
            .where(AdminOrganisationNote.organisation_id == org_id)
            .order_by(AdminOrganisationNote.created_at.desc())
        )
        .all()
    )
    return [
        AdminNoteOut(
            id=n.id,
            body=n.body,
            author_email=u.email,
            created_at=n.created_at,
        )
        for n, u in rows
    ]


@router.post(
    "/klanten/{org_id}/notities",
    response_model=AdminNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_org_note(
    org_id: UUID,
    payload: AdminNoteCreate,
    db: DbSession,
    user: CurrentUser,
) -> AdminNoteOut:
    _get_klant_org(db, org_id)
    n = AdminOrganisationNote(
        organisation_id=org_id,
        author_id=user.id,
        body=payload.body.strip(),
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return AdminNoteOut(
        id=n.id,
        body=n.body,
        author_email=user.email,
        created_at=n.created_at,
    )


@router.get(
    "/maatregelen/{maatregel_id}/notities",
    response_model=list[AdminNoteOut],
)
def list_maatregel_notes(maatregel_id: UUID, db: DbSession) -> list[AdminNoteOut]:
    m = db.get(Maatregel, maatregel_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Maatregel niet gevonden")
    rows = (
        db.execute(
            select(AdminMaatregelNote, User)
            .join(User, AdminMaatregelNote.author_id == User.id)
            .where(AdminMaatregelNote.maatregel_id == maatregel_id)
            .order_by(AdminMaatregelNote.created_at.desc())
        )
        .all()
    )
    return [
        AdminNoteOut(
            id=n.id,
            body=n.body,
            author_email=u.email,
            created_at=n.created_at,
        )
        for n, u in rows
    ]


@router.post(
    "/maatregelen/{maatregel_id}/notities",
    response_model=AdminNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_maatregel_note(
    maatregel_id: UUID,
    payload: AdminNoteCreate,
    db: DbSession,
    user: CurrentUser,
) -> AdminNoteOut:
    m = db.get(Maatregel, maatregel_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Maatregel niet gevonden")
    n = AdminMaatregelNote(
        maatregel_id=maatregel_id,
        author_id=user.id,
        body=payload.body.strip(),
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return AdminNoteOut(
        id=n.id,
        body=n.body,
        author_email=user.email,
        created_at=n.created_at,
    )


@router.post(
    "/maatregelen/{maatregel_id}/upload-verzoek",
    response_model=UploadVerzoekCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
def create_upload_verzoek(
    maatregel_id: UUID,
    payload: UploadVerzoekCreateBody,
    db: DbSession,
    user: CurrentUser,
) -> UploadVerzoekCreatedOut:
    """Sla uploadverzoek op, token 24u, mail TEMPLATE 3 naar klant."""
    m = db.get(Maatregel, maatregel_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Maatregel niet gevonden")
    project = db.get(Project, m.project_id)
    if project is None or project.is_deleted:
        raise HTTPException(status_code=404, detail="Project niet gevonden")

    allowed = allowed_document_types(m.maatregel_type)
    resolved: list[MaatregelDocumentType] = []
    for raw in payload.document_types:
        try:
            dt = MaatregelDocumentType(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Ongeldig documenttype: {raw}"
            ) from exc
        if dt not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Documenttype niet van toepassing op deze maatregel: {raw}",
            )
        resolved.append(dt)

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    bericht = (
        payload.bericht.strip()
        if payload.bericht and payload.bericht.strip()
        else None
    )
    vz = UploadVerzoek(
        maatregel_id=m.id,
        aangevraagd_door=user.id,
        document_types=[dt.value for dt in resolved],
        bericht=bericht,
        token=token,
        token_expires_at=expires,
    )
    db.add(vz)
    labels_join = ", ".join(dt.value for dt in resolved)
    note_body = f"Uploadverzoek verstuurd naar klant voor: {labels_join}."
    if bericht:
        note_body += f"\n\nBericht aan klant:\n{bericht}"
    db.add(
        AdminNotitie(
            entity_type=AdminNotitieEntityType.maatregel.value,
            entity_id=m.id,
            tekst=note_body,
            aangemaakt_door=user.id,
        )
    )
    db.commit()
    db.refresh(vz)

    checklist = get_required_documents(m.maatregel_type)
    lines: list[str] = []
    for dt in resolved:
        meta = next((c for c in checklist if c.document_type == dt), None)
        label = meta.label if meta else dt.value
        uitleg = (meta.uitleg if meta else "") or ""
        lines.append(
            "<li style='margin:6px 0;'>📄 "
            f"<strong>{html.escape(label)}</strong> — {html.escape(uitleg)}</li>"
        )
    document_lines_html = "".join(lines)

    if project.organisation_id is not None:
        uid = db.execute(
            select(User.id)
            .where(User.organisation_id == project.organisation_id)
            .order_by(User.created_at.asc())
        ).scalar_one_or_none()
        klant = db.get(User, uid) if uid else None
        if klant and klant.email:
            base = (settings.FRONTEND_URL or "").rstrip("/")
            upload_url = f"{base}/projecten/{project.id}/documenten/upload/{token}"
            email_service.send_template_3_klant_document_upload_verzoek(
                to=klant.email,
                first_name=klant.first_name,
                subsidie_type=email_service.maatregel_subsidie_type_label(m),
                document_lines_html=document_lines_html,
                upload_page_url=upload_url,
                deadline_datum=expires.date(),
                optioneel_bericht=bericht,
            )
        else:
            logger.warning(
                "Uploadverzoek zonder klant-e-mail (maatregel_id=%s)", maatregel_id
            )

    if project.organisation_id:
        klant_notifications.notify_upload_verzoek(
            db,
            organisation_id=project.organisation_id,
            project_id=project.id,
            maatregel_id=m.id,
            document_count=len(resolved),
        )

    return UploadVerzoekCreatedOut(
        id=vz.id,
        token_expires_at=vz.token_expires_at,
        document_types=list(vz.document_types or []),
    )


@router.patch("/maatregelen/{maatregel_id}/status")
def admin_update_maatregel_status(
    maatregel_id: UUID,
    payload: MaatregelStatusUpdateBody,
    db: DbSession,
) -> dict:
    m = db.get(Maatregel, maatregel_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Maatregel niet gevonden")
    old_status = m.status
    try:
        m.status = MaatregelStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Ongeldige status: {payload.status}",
        ) from exc
    db.commit()
    db.refresh(m)
    if m.status != old_status:
        email_service.notify_klant_maatregel_status_change(
            db,
            maatregel=m,
            old_status=old_status,
            new_status=m.status,
        )
    return {"id": str(m.id), "status": m.status.value}


def _dossier_base_query():
    return (
        select(Maatregel, Project, Organisation)
        .join(Project, Maatregel.project_id == Project.id)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .where(Project.is_deleted.is_(False))
    )


@router.get("/dossiers", response_model=DossierListPage)
def list_dossiers(
    db: DbSession,
    status_: Annotated[Optional[str], Query(alias="status")] = None,
    regeling: Annotated[Optional[str], Query()] = None,
    deadline_status: Annotated[Optional[str], Query()] = None,
    jaar: Annotated[Optional[int], Query(ge=2000, le=2100)] = None,
    klant_naam: Annotated[Optional[str], Query()] = None,
    zoek: Annotated[Optional[str], Query()] = None,
    quick: Annotated[
        Optional[str],
        Query(description="actie|review|ingediend|goedgekeurd"),
    ] = None,
    sort: Annotated[
        Optional[str],
        Query(
            description=(
                "deadline|aangemaakt|status|klant|adres|regeling|updated"
            )
        ),
    ] = None,
    order: Annotated[Optional[str], Query(description="asc|desc")] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DossierListPage:
    stmt = _dossier_base_query()
    count_stmt = (
        select(func.count())
        .select_from(Maatregel)
        .join(Project, Maatregel.project_id == Project.id)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .where(Project.is_deleted.is_(False))
    )

    if quick == "actie":
        stmt = stmt.where(
            Maatregel.status.notin_(
                [MaatregelStatus.goedgekeurd, MaatregelStatus.afgewezen]
            ),
            or_(
                Maatregel.deadline_status.in_(
                    [DeadlineStatus.kritiek, DeadlineStatus.verlopen]
                ),
                Maatregel.status == MaatregelStatus.orientatie,
            ),
        )
        count_stmt = count_stmt.where(
            Maatregel.status.notin_(
                [MaatregelStatus.goedgekeurd, MaatregelStatus.afgewezen]
            ),
            or_(
                Maatregel.deadline_status.in_(
                    [DeadlineStatus.kritiek, DeadlineStatus.verlopen]
                ),
                Maatregel.status == MaatregelStatus.orientatie,
            ),
        )
    elif quick == "review":
        stmt = stmt.where(Maatregel.status == MaatregelStatus.orientatie)
        count_stmt = count_stmt.where(Maatregel.status == MaatregelStatus.orientatie)
    elif quick == "ingediend":
        stmt = stmt.where(
            Maatregel.status.in_(
                [
                    MaatregelStatus.aangevraagd,
                    MaatregelStatus.in_beoordeling,
                ]
            )
        )
        count_stmt = count_stmt.where(
            Maatregel.status.in_(
                [
                    MaatregelStatus.aangevraagd,
                    MaatregelStatus.in_beoordeling,
                ]
            )
        )
    elif quick == "goedgekeurd":
        stmt = stmt.where(Maatregel.status == MaatregelStatus.goedgekeurd)
        count_stmt = count_stmt.where(Maatregel.status == MaatregelStatus.goedgekeurd)

    if status_:
        try:
            st = MaatregelStatus(status_)
        except ValueError as exc:
            raise HTTPException(422, f"Onbekende status {status_}") from exc
        stmt = stmt.where(Maatregel.status == st)
        count_stmt = count_stmt.where(Maatregel.status == st)
    if regeling:
        try:
            rc = RegelingCode(regeling)
        except ValueError as exc:
            raise HTTPException(422, f"Onbekende regeling {regeling}") from exc
        stmt = stmt.where(Maatregel.regeling_code == rc)
        count_stmt = count_stmt.where(Maatregel.regeling_code == rc)
    if deadline_status:
        try:
            ds = DeadlineStatus(deadline_status)
        except ValueError as exc:
            raise HTTPException(422, f"Onbekende deadline_status {deadline_status}") from exc
        stmt = stmt.where(Maatregel.deadline_status == ds)
        count_stmt = count_stmt.where(Maatregel.deadline_status == ds)
    if jaar is not None:
        stmt = stmt.where(extract("year", Project.created_at) == jaar)
        count_stmt = count_stmt.where(extract("year", Project.created_at) == jaar)
    if klant_naam and klant_naam.strip():
        term = f"%{klant_naam.strip()}%"
        stmt = stmt.where(Organisation.name.ilike(term))
        count_stmt = count_stmt.where(Organisation.name.ilike(term))
    if zoek and zoek.strip():
        term = f"%{zoek.strip()}%"
        stmt = stmt.where(
            or_(
                Project.postcode.ilike(term),
                Project.straat.ilike(term),
                Project.plaats.ilike(term),
                Organisation.name.ilike(term),
            )
        )
        count_stmt = count_stmt.where(
            or_(
                Project.postcode.ilike(term),
                Project.straat.ilike(term),
                Project.plaats.ilike(term),
                Organisation.name.ilike(term),
            )
        )

    total = int(db.execute(count_stmt).scalar_one())
    sort_key = (sort or "updated").lower()
    desc = (order or "desc").lower() != "asc"
    order_cols = {
        "deadline": Maatregel.deadline_indienen,
        "aangemaakt": Maatregel.created_at,
        "status": Maatregel.status,
        "klant": Organisation.name,
        "adres": Project.postcode,
        "regeling": Maatregel.regeling_code,
        "updated": Maatregel.updated_at,
    }
    col = order_cols.get(sort_key, Maatregel.updated_at)
    stmt = stmt.order_by(col.desc() if desc else col.asc()).offset(
        (page - 1) * per_page
    ).limit(per_page)
    rows = db.execute(stmt).all()

    items: list[DossierListItemOut] = []
    for m, p, org in rows:
        tot, up = _checklist_counts(db, m)
        items.append(
            DossierListItemOut(
                maatregel_id=m.id,
                project_id=p.id,
                organisation_id=org.id,
                organisation_name=org.name,
                project_adres=_adres_label(p),
                regeling=m.regeling_code.value if m.regeling_code else None,
                status=m.status.value,
                deadline_indienen=m.deadline_indienen,
                deadline_status=m.deadline_status.value
                if m.deadline_status
                else None,
                verplicht_docs_totaal=tot,
                verplicht_docs_geupload=up,
                missende_verplicht=max(0, tot - up),
                created_at=m.created_at,
            )
        )
    pages = ceil(total / per_page) if per_page else 1
    return DossierListPage(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=max(pages, 1),
    )


@router.get("/export/projecten")
def export_projecten_csv(
    db: DbSession,
    jaar: Annotated[Optional[int], Query(ge=2000, le=2100)] = None,
    regeling: Annotated[Optional[str], Query()] = None,
    status_: Annotated[Optional[str], Query(alias="status")] = None,
    deadline_status: Annotated[Optional[str], Query()] = None,
    zoek: Annotated[Optional[str], Query()] = None,
):
    stmt = (
        select(Project, Organisation)
        .join(Organisation, Project.organisation_id == Organisation.id)
        .where(Project.is_deleted.is_(False))
    )
    if jaar is not None:
        stmt = stmt.where(extract("year", Project.created_at) == jaar)
    if zoek and zoek.strip():
        term = f"%{zoek.strip()}%"
        stmt = stmt.where(
            or_(
                Project.postcode.ilike(term),
                Project.straat.ilike(term),
                Project.plaats.ilike(term),
                Organisation.name.ilike(term),
            )
        )
    stmt = stmt.order_by(Project.created_at.desc())
    project_rows = db.execute(stmt).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "klant",
            "project_id",
            "project_adres",
            "postcode",
            "bouwjaar",
            "aantal_maatregelen",
            "created_at",
        ]
    )
    for p, org in project_rows:
        m_stmt = select(Maatregel).where(Maatregel.project_id == p.id)
        if status_:
            try:
                m_stmt = m_stmt.where(Maatregel.status == MaatregelStatus(status_))
            except ValueError as exc:
                raise HTTPException(422, f"Onbekende status {status_}") from exc
        if regeling:
            try:
                m_stmt = m_stmt.where(Maatregel.regeling_code == RegelingCode(regeling))
            except ValueError as exc:
                raise HTTPException(422, f"Onbekende regeling {regeling}") from exc
        if deadline_status:
            try:
                m_stmt = m_stmt.where(
                    Maatregel.deadline_status == DeadlineStatus(deadline_status)
                )
            except ValueError as exc:
                raise HTTPException(
                    422, f"Onbekende deadline_status {deadline_status}"
                ) from exc
        maatregelen = db.execute(m_stmt).scalars().all()
        if status_ or regeling or deadline_status:
            if not maatregelen:
                continue
        w.writerow(
            [
                org.name,
                str(p.id),
                _adres_label(p),
                p.postcode,
                p.bouwjaar,
                len(maatregelen),
                p.created_at.isoformat() if p.created_at else "",
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="projecten_export.csv"'
        },
    )