"""Projecten + maatregelen + maatregel-documenten endpoints (STAP 9).

Een klant ziet en bewerkt alleen projecten van de eigen organisatie; een
admin ziet projecten van alle klanten en kan AAA-Lex-only velden vullen
(energielabels, notities, documenten verifiëren).

De deadline engine wordt op elke POST/PUT van een maatregel opnieuw
uitgevoerd zodat de lijstweergave zonder berekeningen direct de juiste
kleur kan tonen.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
    Project,
    UploadVerzoek,
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
from app.schemas.projecten import (
    ChecklistItemOut,
    ChecklistResponse,
    DocumentOut,
    EiaAanvraagCreate,
    MiaVamilAanvraagCreate,
    DumavaAanvraagCreate,
    MaatregelCreate,
    MaatregelOut,
    MaatregelShort,
    MaatregelUpdate,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectListResponse,
    OpenUploadVerzoekOut,
    ProjectOut,
    ProjectUpdate,
    PublicUploadDocItemOut,
    PublicUploadMetaOut,
    QuotaInfo,
    IsdeIsolatieAanvraagCreate,
    IsdeWarmtepompAanvraagCreate,
    SubsidieMatchOut,
    SubsidieMatchResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services import email_service, r2_storage
from app.services.projecten_service import (
    allowed_document_types,
    calculate_deadline,
    estimate_isolatie_subsidie_from_m2,
    estimate_subsidie,
    get_matching_subsidies,
    get_required_documents,
    infer_regeling,
    maybe_complete_upload_verzoek,
    open_upload_verzoek_rows_for_project,
    project_ids_with_open_upload_verzoek,
)
from app.services.plan_service import get_quota

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projecten"])

VerifiedUser = Annotated[User, Depends(require_verified)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def _project_or_403(db: Session, project_id: UUID, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project niet gevonden"
        )
    if not _is_admin(user) and project.organisation_id != user.organisation_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geen toegang tot dit project",
        )
    return project


def _maatregel_or_403(
    db: Session, maatregel_id: UUID, user: User
) -> Maatregel:
    m = db.get(Maatregel, maatregel_id)
    if m is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maatregel niet gevonden",
        )
    _project_or_403(db, m.project_id, user)  # raises on access denied
    return m


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


def _project_to_out(project: Project, *, maatregelen: List[Maatregel]) -> ProjectOut:
    data = ProjectOut.model_validate(project)
    data.aantal_maatregelen = len(maatregelen)
    data.totaal_geschatte_subsidie = sum(
        float(m.geschatte_subsidie or 0) for m in maatregelen
    )
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


def _primary_user_id_for_org(db: Session, organisation_id: UUID) -> Optional[UUID]:
    return db.execute(
        select(User.id)
        .where(User.organisation_id == organisation_id)
        .order_by(User.created_at.asc())
    ).scalar_one_or_none()


def _upload_verzoek_bundle(
    db: Session, project_id: UUID, token: str
) -> tuple[UploadVerzoek, Project, Maatregel]:
    vz = db.execute(
        select(UploadVerzoek).where(UploadVerzoek.token == token)
    ).scalar_one_or_none()
    if vz is None or vz.voltooid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ongeldige of verlopen link",
        )
    if vz.token_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ongeldige of verlopen link",
        )
    m = db.get(Maatregel, vz.maatregel_id)
    if m is None or m.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ongeldige of verlopen link",
        )
    p = db.get(Project, project_id)
    if p is None or p.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project niet gevonden",
        )
    return vz, p, m


# ---------------------------------------------------------------------------
# Publieke document-upload (token uit e-mail)
# ---------------------------------------------------------------------------


@router.get(
    "/projecten/{project_id}/documenten/upload/{token}",
    response_model=PublicUploadMetaOut,
)
def public_upload_meta(
    project_id: UUID, token: str, db: DbSession
) -> PublicUploadMetaOut:
    vz, p, m = _upload_verzoek_bundle(db, project_id, token)
    raw_types = list(vz.document_types or [])
    out_docs: list[PublicUploadDocItemOut] = []
    for dt_s in raw_types:
        try:
            dt = MaatregelDocumentType(dt_s)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ongeldige documentconfig in verzoek",
            ) from exc
        for c in get_required_documents(m.maatregel_type):
            if c.document_type == dt:
                out_docs.append(
                    PublicUploadDocItemOut(
                        document_type=dt.value,
                        label=c.label,
                        uitleg=c.uitleg,
                    )
                )
                break
    reg = m.regeling_code.value if m.regeling_code else "Subsidie"
    adres = f"{p.straat} {p.huisnummer}, {p.postcode} {p.plaats}"
    return PublicUploadMetaOut(
        project_id=p.id,
        maatregel_id=m.id,
        subsidie_type=reg,
        project_adres=adres,
        bericht=vz.bericht,
        documenten=out_docs,
        token_expires_at=vz.token_expires_at,
        deadline_indienen=m.deadline_indienen,
    )


@router.post(
    "/projecten/{project_id}/documenten/upload/{token}/presign",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
)
def public_upload_presign(
    project_id: UUID,
    token: str,
    payload: UploadUrlRequest,
    db: DbSession,
) -> UploadUrlResponse:
    vz, project, m = _upload_verzoek_bundle(db, project_id, token)
    allowed_raw = {str(x) for x in (vz.document_types or [])}
    if payload.document_type.value not in allowed_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dit documenttype hoort niet bij dit uploadverzoek",
        )
    allowed = allowed_document_types(m.maatregel_type)
    if payload.document_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Documenttype niet geldig voor deze maatregel",
        )
    uploader = _primary_user_id_for_org(db, project.organisation_id)
    if uploader is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Geen gebruiker gevonden voor deze organisatie",
        )

    document_id = uuid4()
    object_key = (
        f"{project.organisation_id}/projecten/{project.id}/maatregelen/{m.id}/"
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
        geupload_door=uploader,
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
    "/projecten/{project_id}/documenten/upload/{token}/confirm/{document_id}",
    response_model=DocumentOut,
)
def public_upload_confirm(
    project_id: UUID,
    token: str,
    document_id: UUID,
    db: DbSession,
) -> DocumentOut:
    vz, _p, m = _upload_verzoek_bundle(db, project_id, token)
    doc = db.get(MaatregelDocument, document_id)
    if doc is None or doc.maatregel_id != m.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document niet gevonden",
        )
    allowed_raw = {str(x) for x in (vz.document_types or [])}
    if doc.document_type.value not in allowed_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dit document hoort niet bij dit uploadverzoek",
        )
    object_key = r2_storage.object_key_from_storage_url(doc.r2_key)
    doc.r2_key = r2_storage.make_committed_url(object_key)
    maybe_complete_upload_verzoek(db, vz)
    db.commit()
    db.refresh(doc)
    out = DocumentOut.model_validate(doc).model_dump()
    out["pending_upload"] = doc.r2_key.startswith("pending://")
    return DocumentOut(**out)


# ---------------------------------------------------------------------------
# Projecten CRUD
# ---------------------------------------------------------------------------


@router.get("/projecten", response_model=ProjectListResponse)
def list_projecten(
    user: VerifiedUser,
    db: DbSession,
    deadline_status: Optional[DeadlineStatus] = Query(default=None),
    organisation_id: Optional[UUID] = Query(default=None),
) -> ProjectListResponse:
    """Projecten van de ingelogde gebruiker. Admin ziet alles."""
    stmt = select(Project).where(Project.is_deleted.is_(False))
    if not _is_admin(user):
        if user.organisation_id is None:
            return ProjectListResponse(
                items=[], totaal=0, quota=_quota_info(db, user)
            )
        stmt = stmt.where(Project.organisation_id == user.organisation_id)
    else:
        if organisation_id is not None:
            stmt = stmt.where(Project.organisation_id == organisation_id)

    stmt = stmt.order_by(Project.created_at.desc())
    projecten = list(db.execute(stmt).scalars().all())

    # Bulk-load maatregelen zodat we geen N+1 hebben op het overzicht.
    project_ids = [project.id for project in projecten]
    maatregelen_per_project: dict[UUID, List[Maatregel]] = {pid: [] for pid in project_ids}
    if project_ids:
        rows = db.execute(
            select(Maatregel).where(Maatregel.project_id.in_(project_ids))
        ).scalars().all()
        for m in rows:
            maatregelen_per_project[m.project_id].append(m)

    open_flags = project_ids_with_open_upload_verzoek(db, project_ids)

    # Admins krijgen de organisatie-naam mee zodat het admin-overzicht per
    # rij kan tonen van welke klant het project is.
    org_names: dict[UUID, str] = {}
    if _is_admin(user) and projecten:
        org_ids = {project.organisation_id for project in projecten}
        rows = db.execute(
            select(Organisation.id, Organisation.name).where(
                Organisation.id.in_(org_ids)
            )
        ).all()
        org_names = {row[0]: row[1] for row in rows}

    items = []
    for project in projecten:
        out = _project_to_out(project, maatregelen=maatregelen_per_project.get(project.id, []))
        out.heeft_open_upload_verzoek = project.id in open_flags
        if _is_admin(user):
            out.organisation_name = org_names.get(project.organisation_id)
        items.append(out)
    if deadline_status is not None:
        items = [i for i in items if i.worst_deadline_status == deadline_status]

    return ProjectListResponse(
        items=items, totaal=len(items), quota=_quota_info(db, user)
    )


@router.post(
    "/projecten",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreate,
    user: VerifiedUser,
    db: DbSession,
) -> ProjectOut:
    if user.organisation_id is None and not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account zonder organisatie kan geen projecten aanmaken",
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
                    f"projecten toe. Upgrade voor meer projecten."
                ),
            },
        )

    project = Project(
        organisation_id=user.organisation_id,  # type: ignore[arg-type]
        created_by=user.id,
        straat=payload.straat.strip(),
        huisnummer=payload.huisnummer.strip(),
        postcode=payload.postcode.strip(),
        plaats=payload.plaats.strip(),
        bouwjaar=payload.bouwjaar,
        project_type=payload.project_type,
        eigenaar_type=payload.eigenaar_type,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_to_out(project, maatregelen=[])


@router.get("/projecten/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: UUID, user: VerifiedUser, db: DbSession
) -> ProjectDetailResponse:
    project = _project_or_403(db, project_id, user)
    maatregelen = list(
        db.execute(
            select(Maatregel)
            .where(Maatregel.project_id == project_id)
            .order_by(Maatregel.created_at.desc())
        )
        .scalars()
        .all()
    )
    base = _project_to_out(project, maatregelen=maatregelen).model_dump()
    base["maatregelen"] = [MaatregelShort.model_validate(m) for m in maatregelen]
    ou_rows = open_upload_verzoek_rows_for_project(db, project_id)
    base["open_upload_verzoeken"] = [OpenUploadVerzoekOut(**r) for r in ou_rows]
    base["heeft_open_upload_verzoek"] = bool(ou_rows)
    if not _is_admin(user):
        base["notities"] = None
    return ProjectDetailResponse.model_validate(base)


@router.put("/projecten/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    user: VerifiedUser,
    db: DbSession,
) -> ProjectOut:
    project = _project_or_403(db, project_id, user)

    # Klant mag alleen projectgegevens aanpassen; AAA-Lex-velden blijven
    # read-only tot een admin ze invult.
    klant_fields = {
        "straat",
        "huisnummer",
        "postcode",
        "plaats",
        "bouwjaar",
        "project_type",
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
        setattr(project, field, value)
    if _is_admin(user):
        for field in admin_fields & data.keys():
            setattr(project, field, data[field])

    db.commit()
    db.refresh(project)

    # Aantal maatregelen herberekenen zodat _project_to_out klopt.
    maatregelen = list(
        db.execute(select(Maatregel).where(Maatregel.project_id == project.id))
        .scalars()
        .all()
    )
    return _project_to_out(project, maatregelen=maatregelen)


@router.delete(
    "/projecten/{project_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_project(
    project_id: UUID, user: VerifiedUser, db: DbSession
) -> Response:
    project = _project_or_403(db, project_id, user)
    project.is_deleted = True
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Subsidie matching
# ---------------------------------------------------------------------------


@router.get(
    "/projecten/{project_id}/subsidies",
    response_model=SubsidieMatchResponse,
)
def get_subsidies_voor_project(
    project_id: UUID, user: VerifiedUser, db: DbSession
) -> SubsidieMatchResponse:
    """Welke subsidies passen bij dit project?

    Gebruikt :func:`projecten_service.get_matching_subsidies` als single source
    of truth en splitst de uitkomst in eligible / niet-eligible voor de UI.
    """
    project = _project_or_403(db, project_id, user)
    matches = get_matching_subsidies(project)
    eligible = [
        SubsidieMatchOut(**m.__dict__) for m in matches if m.eligible
    ]
    niet_eligible = [
        SubsidieMatchOut(**m.__dict__) for m in matches if not m.eligible
    ]
    return SubsidieMatchResponse(
        project_id=project.id,
        eligible=eligible,
        niet_eligible=niet_eligible,
    )


_ISDE_WP_SUBTYPE_LABELS: dict[MaatregelType, str] = {
    MaatregelType.warmtepomp_lucht_water: "Lucht/water warmtepomp",
    MaatregelType.warmtepomp_water_water: "Water/water warmtepomp",
    MaatregelType.warmtepomp_hybride: "Hybride warmtepomp",
}


def _strip_optional_str(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    t = s.strip()
    return t or None


_EIA_TYPE_LABELS: dict[str, str] = {
    "led": "LED verlichting",
    "warmtepomp_zakelijk": "Warmtepomp zakelijk",
    "zonnepanelen": "Zonnepanelen",
    "energiezuinige_installatie": "Energiezuinige installatie",
    "overig": "Overig energiebesparend",
}
_EIA_ONDERNEMING_LABELS: dict[str, str] = {
    "ib": "IB-ondernemer (inkomstenbelasting)",
    "bv_nv": "BV / NV (vennootschapsbelasting)",
    "overig": "Overig",
}
_MIA_MILIEU_TYPE_LABELS: dict[str, str] = {
    "duurzame_warmte": "Duurzame warmte (warmtepomp, WKO)",
    "circulair_bouwen": "Circulair bouwen",
    "energieneutrale_gebouwen": "Energieneutrale gebouwen",
    "hernieuwbare_energie": "Hernieuwbare energie",
    "overig_milieu": "Overig milieuvriendelijk",
}
_VAMIL_LIQUIDITEIT_INDICATIE_PCT = 0.03

_DUMAVA_ORG_LABELS: dict[str, str] = {
    "zorg": "Zorginstelling",
    "onderwijs": "Onderwijs",
    "sport": "Sport",
    "gemeente": "Gemeente / overheid",
    "overig_maatschappelijk": "Overig maatschappelijk",
}
_DUMAVA_MAATREGEL_KEY_LABELS: dict[str, str] = {
    "warmtepomp": "Warmtepomp",
    "zonnepanelen": "Zonnepanelen",
    "dakisolatie": "Dakisolatie",
    "gevelisolatie": "Gevelisolatie",
    "led_verlichting": "LED verlichting",
    "warmtenet": "Warmtenet aansluiting",
    "vloerisolatie": "Vloerisolatie",
    "overig": "Overige maatregel",
}
_DUMAVA_MAX_INVESTERING_PER_GEBOUW = 1_500_000.0


@router.post(
    "/projecten/{project_id}/aanvragen/isde-warmtepomp",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_isde_warmtepomp_aanvraag(
    project_id: UUID,
    payload: IsdeWarmtepompAanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    """Wizard-submit: sla ISDE warmtepomp-intake op als nieuwe maatregel."""
    project = _project_or_403(db, project_id, user)

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
        project_id=project.id,
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

    situatie_txt = (
        "Ja, al geïnstalleerd"
        if payload.situatie == "geinstalleerd"
        else "Nog aan het oriënteren"
    )
    row_tuples: List[tuple[str, Optional[str]]] = [
        ("Klant-e-mail", user.email),
        ("Situatie", situatie_txt),
        (
            "Type warmtepomp",
            _ISDE_WP_SUBTYPE_LABELS.get(m_type, m_type.value),
        ),
        ("Merk", m.apparaat_merk),
        ("Typenummer", m.apparaat_typenummer),
        ("Meldcode", m.apparaat_meldcode),
        ("Installateur", m.installateur_naam),
        ("KvK installateur", m.installateur_kvk),
        (
            "Gecertificeerd",
            "Ja" if m.installateur_gecertificeerd else "Nee",
        ),
        (
            "Installatiedatum",
            m.installatie_datum.isoformat() if m.installatie_datum else None,
        ),
        (
            "Geschatte investering (€)",
            f"{m.investering_bedrag:.2f}" if m.investering_bedrag is not None else None,
        ),
        ("Offerte", "Ja" if payload.heeft_offerte else "Nee"),
        (
            "Offertedatum",
            m.offerte_datum.isoformat() if m.offerte_datum else None,
        ),
        (
            "Geschatte subsidie (€)",
            f"{m.geschatte_subsidie:.2f}" if m.geschatte_subsidie is not None else None,
        ),
        (
            "Deadline indienen",
            m.deadline_indienen.isoformat() if m.deadline_indienen else None,
        ),
        ("Maatregel-ID", str(m.id)),
    ]
    email_service.notify_admins_new_wizard_maatregel(
        db,
        user=user,
        project=project,
        maatregel=m,
        subsidie_type_label="ISDE (warmtepomp)",
        wizard_rows=row_tuples,
    )

    return MaatregelOut.model_validate(m)


_ISOL_WIZARD_LABELS: dict[MaatregelType, str] = {
    MaatregelType.dakisolatie: "Dakisolatie",
    MaatregelType.gevelisolatie: "Gevelisolatie",
    MaatregelType.vloerisolatie: "Vloerisolatie",
    MaatregelType.hr_glas: "HR++ glas",
}


@router.post(
    "/projecten/{project_id}/aanvragen/isde-isolatie",
    response_model=List[MaatregelOut],
    status_code=status.HTTP_201_CREATED,
)
def create_isde_isolatie_aanvragen(
    project_id: UUID,
    payload: IsdeIsolatieAanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> List[MaatregelOut]:
    """Wizard-submit: één Maatregel per gekozen isolatietype op hetzelfde project."""
    project = _project_or_403(db, project_id, user)

    def _strip_opt(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        t = s.strip()
        return t or None

    created: List[Maatregel] = []
    for item in payload.items:
        mt = MaatregelType(item.maatregel_type)
        if mt not in _ISOL_WIZARD_LABELS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Ongeldig isolatietype: {item.maatregel_type}",
            )

        if item.al_uitgevoerd and item.uitvoeringsdatum:
            inst_datum = item.uitvoeringsdatum
        else:
            inst_datum = payload.installatie_of_geplande_datum

        m_status = (
            MaatregelStatus.gepland
            if item.al_uitgevoerd and item.uitvoeringsdatum
            else MaatregelStatus.orientatie
        )
        label = _ISOL_WIZARD_LABELS[mt]
        oms = (
            f"ISDE isolatie — wizard ({label}, {item.oppervlakte_m2:g} m²)"
        )

        m = Maatregel(
            project_id=project.id,
            created_by=user.id,
            maatregel_type=mt,
            omschrijving=oms,
            status=m_status,
            apparaat_meldcode=_strip_opt(item.meldcode_materiaal),
            installateur_naam=payload.installateur_naam.strip(),
            installateur_kvk=_strip_opt(payload.installateur_kvk),
            installateur_gecertificeerd=False,
            installatie_datum=inst_datum,
            investering_bedrag=item.investering_bedrag,
            regeling_code=RegelingCode.ISDE,
            geschatte_subsidie=estimate_isolatie_subsidie_from_m2(
                mt, item.oppervlakte_m2
            ),
        )
        _recalc_deadline(m)
        db.add(m)
        created.append(m)

    db.commit()
    for m in created:
        db.refresh(m)

    common_tuples: List[tuple[str, Optional[str]]] = [
        ("Klant-e-mail", user.email),
        ("Installateur / uitvoerder", payload.installateur_naam.strip()),
        ("KvK uitvoerder", _strip_opt(payload.installateur_kvk)),
        (
            "Geplande / algemene datum",
            payload.installatie_of_geplande_datum.isoformat()
            if payload.installatie_of_geplande_datum
            else None,
        ),
    ]
    for m in created:
        item = next(
            (
                i
                for i in payload.items
                if i.maatregel_type == m.maatregel_type.value
            ),
            None,
        )
        m_rows: List[tuple[str, Optional[str]]] = list(common_tuples)
        m_rows.append(
            (
                "Type",
                _ISOL_WIZARD_LABELS.get(m.maatregel_type, m.maatregel_type.value),
            )
        )
        if item:
            m_rows.append(("Oppervlakte (m²)", f"{item.oppervlakte_m2:g}"))
            m_rows.append(
                ("Al uitgevoerd", "Ja" if item.al_uitgevoerd else "Nee")
            )
            if item.uitvoeringsdatum:
                m_rows.append(
                    ("Uitvoeringsdatum", item.uitvoeringsdatum.isoformat())
                )
        m_rows.append(("Meldcode", m.apparaat_meldcode))
        m_rows.append(
            (
                "Investering (€)",
                f"{m.investering_bedrag:.2f}"
                if m.investering_bedrag is not None
                else None,
            )
        )
        m_rows.append(
            (
                "Geschatte subsidie (€)",
                f"{m.geschatte_subsidie:.2f}"
                if m.geschatte_subsidie is not None
                else None,
            )
        )
        m_rows.append(
            (
                "Deadline indienen",
                m.deadline_indienen.isoformat() if m.deadline_indienen else None,
            )
        )
        m_rows.append(("Maatregel-ID", str(m.id)))
        email_service.notify_admins_new_wizard_maatregel(
            db,
            user=user,
            project=project,
            maatregel=m,
            subsidie_type_label="ISDE (isolatie)",
            wizard_rows=m_rows,
        )

    return [MaatregelOut.model_validate(m) for m in created]


@router.post(
    "/projecten/{project_id}/aanvragen/eia",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_eia_aanvraag(
    project_id: UUID,
    payload: EiaAanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    """Wizard-submit: EIA-intake als één Maatregel (eia_investering, EIA)."""
    project = _project_or_403(db, project_id, user)
    type_label = _EIA_TYPE_LABELS[payload.type_investering]
    ond_label = _EIA_ONDERNEMING_LABELS[payload.type_onderneming]
    contact_naam = _strip_optional_str(payload.contactpersoon_naam)
    tel = _strip_optional_str(payload.telefoon)

    oms_lines = [
        payload.investering_omschrijving.strip(),
        "",
        "--- EIA intake (klantwizard) ---",
        f"Type investering: {type_label}",
        f"Bedrijfsnaam: {payload.bedrijfsnaam.strip()}",
        f"KvK: {payload.kvk_nummer}",
        f"Type onderneming: {ond_label}",
    ]
    if contact_naam:
        oms_lines.append(f"Contactpersoon: {contact_naam}")
    if tel:
        oms_lines.append(f"Telefoon: {tel}")
    oms = "\n".join(oms_lines)

    urgent = bool(payload.heeft_offerte and payload.offerte_datum)
    m_status = (
        MaatregelStatus.gepland
        if urgent or payload.geplande_startdatum is not None
        else MaatregelStatus.orientatie
    )

    m = Maatregel(
        project_id=project.id,
        created_by=user.id,
        maatregel_type=MaatregelType.eia_investering,
        omschrijving=oms,
        status=m_status,
        apparaat_merk=type_label[:128],
        installateur_naam=payload.bedrijfsnaam.strip(),
        installateur_kvk=payload.kvk_nummer,
        installateur_gecertificeerd=False,
        installatie_datum=payload.geplande_startdatum,
        offerte_datum=payload.offerte_datum,
        investering_bedrag=float(payload.investering_bedrag),
        regeling_code=RegelingCode.EIA,
    )
    _recalc_deadline(m)
    if urgent:
        m.deadline_status = DeadlineStatus.kritiek
    _auto_estimate_subsidie(m)
    db.add(m)
    db.commit()
    db.refresh(m)

    row_tuples: List[tuple[str, Optional[str]]] = [
        ("Klant-e-mail", user.email),
        ("Bedrijfsnaam", payload.bedrijfsnaam.strip()),
        ("KvK", payload.kvk_nummer),
        ("Type investering", type_label),
        ("Geschatte investering (€)", f"{float(payload.investering_bedrag):.2f}"),
        (
            "Geplande startdatum",
            payload.geplande_startdatum.isoformat()
            if payload.geplande_startdatum
            else None,
        ),
        ("Al een offerte?", "Ja" if payload.heeft_offerte else "Nee"),
        (
            "Offertedatum",
            payload.offerte_datum.isoformat() if payload.offerte_datum else None,
        ),
        (
            "Deadline RVO (indicatie +3 mnd)",
            m.deadline_indienen.isoformat() if m.deadline_indienen else None,
        ),
        (
            "Geschatte fiscale aftrek (€)",
            f"{m.geschatte_subsidie:.2f}" if m.geschatte_subsidie else None,
        ),
        ("Contactpersoon", contact_naam),
        ("Telefoon", tel),
        ("Maatregel-ID", str(m.id)),
    ]
    email_service.notify_admins_new_wizard_maatregel(
        db,
        user=user,
        project=project,
        maatregel=m,
        subsidie_type_label="EIA",
        wizard_rows=row_tuples,
        urgent=urgent,
    )

    return MaatregelOut.model_validate(m)


@router.post(
    "/projecten/{project_id}/aanvragen/mia-vamil",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_mia_vamil_aanvraag(
    project_id: UUID,
    payload: MiaVamilAanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    """Wizard-submit: MIA + Vamil-intake als één Maatregel (gecombineerd)."""
    project = _project_or_403(db, project_id, user)
    type_label = _MIA_MILIEU_TYPE_LABELS[payload.type_milieu_investering]
    ond_label = _EIA_ONDERNEMING_LABELS[payload.type_onderneming]
    contact_naam = _strip_optional_str(payload.contactpersoon_naam)
    tel = _strip_optional_str(payload.telefoon)

    oms_lines = [
        payload.investering_omschrijving.strip(),
        "",
        "--- MIA/Vamil intake (klantwizard) ---",
        f"Type milieu-investering: {type_label}",
    ]
    if payload.milieulijst_categoriecode:
        oms_lines.append(
            f"Milieulijst categoriecode (klant): {payload.milieulijst_categoriecode}"
        )
    oms_lines.extend(
        [
            f"Bedrijfsnaam: {payload.bedrijfsnaam.strip()}",
            f"KvK: {payload.kvk_nummer}",
            f"Type onderneming: {ond_label}",
        ]
    )
    if contact_naam:
        oms_lines.append(f"Contactpersoon: {contact_naam}")
    if tel:
        oms_lines.append(f"Telefoon: {tel}")
    oms = "\n".join(oms_lines)

    urgent = bool(payload.heeft_offerte and payload.offerte_datum)
    m_status = (
        MaatregelStatus.gepland
        if urgent or payload.geplande_startdatum is not None
        else MaatregelStatus.orientatie
    )

    m = Maatregel(
        project_id=project.id,
        created_by=user.id,
        maatregel_type=MaatregelType.mia_vamil_investering,
        omschrijving=oms,
        status=m_status,
        apparaat_merk=type_label[:128],
        installateur_naam=payload.bedrijfsnaam.strip(),
        installateur_kvk=payload.kvk_nummer,
        installateur_gecertificeerd=False,
        installatie_datum=payload.geplande_startdatum,
        offerte_datum=payload.offerte_datum,
        investering_bedrag=float(payload.investering_bedrag),
        regeling_code=RegelingCode.MIA,
    )
    _recalc_deadline(m)
    if urgent:
        m.deadline_status = DeadlineStatus.kritiek
    _auto_estimate_subsidie(m)
    db.add(m)
    db.commit()
    db.refresh(m)

    inv = float(payload.investering_bedrag)
    vamil_indicatie = round(inv * _VAMIL_LIQUIDITEIT_INDICATIE_PCT, 2)

    row_tuples: List[tuple[str, Optional[str]]] = [
        ("Klant-e-mail", user.email),
        ("Bedrijfsnaam", payload.bedrijfsnaam.strip()),
        ("KvK", payload.kvk_nummer),
        ("Type milieu-investering", type_label),
        ("Milieulijst categoriecode", payload.milieulijst_categoriecode),
        ("Geschatte investering (€)", f"{inv:.2f}"),
        (
            "Geplande startdatum",
            payload.geplande_startdatum.isoformat()
            if payload.geplande_startdatum
            else None,
        ),
        ("Al een offerte?", "Ja" if payload.heeft_offerte else "Nee"),
        (
            "Offertedatum",
            payload.offerte_datum.isoformat() if payload.offerte_datum else None,
        ),
        (
            "Deadline RVO (indicatie +3 mnd)",
            m.deadline_indienen.isoformat() if m.deadline_indienen else None,
        ),
        (
            "Geschatte MIA-aftrek (36%) (€)",
            f"{m.geschatte_subsidie:.2f}" if m.geschatte_subsidie else None,
        ),
        ("Vamil liquiditeit (indicatie 3%) (€)", f"{vamil_indicatie:.2f}"),
        ("Contactpersoon", contact_naam),
        ("Telefoon", tel),
        ("Maatregel-ID", str(m.id)),
    ]
    email_service.notify_admins_new_wizard_maatregel(
        db,
        user=user,
        project=project,
        maatregel=m,
        subsidie_type_label="MIA / Vamil",
        wizard_rows=row_tuples,
        urgent=urgent,
    )

    return MaatregelOut.model_validate(m)


@router.post(
    "/projecten/{project_id}/aanvragen/dumava",
    response_model=List[MaatregelOut],
    status_code=status.HTTP_201_CREATED,
)
def create_dumava_aanvragen(
    project_id: UUID,
    payload: DumavaAanvraagCreate,
    user: VerifiedUser,
    db: DbSession,
) -> List[MaatregelOut]:
    """Wizard-submit: één DUMAVA-maatregel per gekozen onderdeel op het project."""
    project = _project_or_403(db, project_id, user)
    org_label = _DUMAVA_ORG_LABELS[payload.organisatie_type]
    functie_s = _strip_optional_str(payload.contact_functie)

    energie_line = payload.energielabel_huidig
    shared_tail = (
        f"Organisatie-type: {org_label}\n"
        f"Oppervlakte gebouw: {payload.oppervlakte_m2:g} m²\n"
        f"Bouwjaar: {payload.bouwjaar}\n"
        f"Huidig energielabel: {energie_line or '—'}\n"
        f"EPA-maatwerkadvies reeds aanwezig: "
        f"{'Ja' if payload.heeft_maatwerkadvies else 'Nee'}\n"
        f"Contactpersoon: {payload.contactpersoon_naam.strip()}\n"
        f"Functie: {functie_s or '—'}\n"
        f"Telefoon: {payload.telefoon.strip()}\n"
        f"Eerder contact met RVO over dit project: "
        f"{'Ja' if payload.rvo_contact_gehad else 'Nee'}"
    )

    created: List[Maatregel] = []
    for item in payload.items:
        label = _DUMAVA_MAATREGEL_KEY_LABELS[item.maatregel_key]
        oms = (
            f"{item.beschrijving.strip()}\n\n"
            "--- DUMAVA wizard (gedeelde gegevens) ---\n"
            f"Maatregel-onderdeel: {label}\n"
            f"{shared_tail}"
        )
        m = Maatregel(
            project_id=project.id,
            created_by=user.id,
            maatregel_type=MaatregelType.dumava_maatregel,
            omschrijving=oms,
            status=MaatregelStatus.orientatie,
            apparaat_merk=label[:128],
            apparaat_typenummer=item.maatregel_key[:128],
            installateur_naam=payload.contactpersoon_naam.strip(),
            installateur_kvk=None,
            installateur_gecertificeerd=False,
            investering_bedrag=float(item.investering_bedrag),
            regeling_code=RegelingCode.DUMAVA,
        )
        _recalc_deadline(m)
        _auto_estimate_subsidie(m)
        db.add(m)
        created.append(m)

    db.commit()
    for m in created:
        db.refresh(m)

    totaal_inv = sum(float(i.investering_bedrag) for i in payload.items)
    totaal_sub = sum(float(m.geschatte_subsidie or 0) for m in created)
    common_tuples: List[tuple[str, Optional[str]]] = [
        ("Klant-e-mail", user.email),
        ("Organisatie-type", org_label),
        ("Contactpersoon", payload.contactpersoon_naam.strip()),
        ("Functie", functie_s),
        ("Telefoon", payload.telefoon.strip()),
        (
            "Eerder contact RVO",
            "Ja" if payload.rvo_contact_gehad else "Nee",
        ),
        ("Oppervlakte gebouw (m²)", f"{payload.oppervlakte_m2:g}"),
        ("Bouwjaar", str(payload.bouwjaar)),
        ("Energielabel", energie_line),
        (
            "EPA-maatwerkadvies aanwezig",
            "Ja" if payload.heeft_maatwerkadvies else "Nee",
        ),
        ("Totaal investering maatregelen (€)", f"{totaal_inv:.2f}"),
        (
            "Som geschatte DUMAVA (30%) (€)",
            f"{totaal_sub:.2f}" if totaal_sub else None,
        ),
    ]
    if totaal_inv > _DUMAVA_MAX_INVESTERING_PER_GEBOUW:
        common_tuples.append(
            (
                "Let op",
                "Totaalinvestering overschrijdt indicatief €1.500.000 per gebouw; "
                "controleer subsidiabele kosten bij RVO.",
            )
        )
    for idx, m in enumerate(created):
        w_item = payload.items[idx]
        lab = _DUMAVA_MAATREGEL_KEY_LABELS[w_item.maatregel_key]
        m_rows = list(common_tuples)
        m_rows.append(("Maatregel", lab))
        m_rows.append(("Investering (€)", f"{w_item.investering_bedrag:.2f}"))
        m_rows.append(
            (
                "Geschatte DUMAVA (€)",
                f"{m.geschatte_subsidie:.2f}" if m.geschatte_subsidie else None,
            )
        )
        m_rows.append(("Maatregel-ID", str(m.id)))
        email_service.notify_admins_new_wizard_maatregel(
            db,
            user=user,
            project=project,
            maatregel=m,
            subsidie_type_label="DUMAVA",
            wizard_rows=m_rows,
        )

    return [MaatregelOut.model_validate(m) for m in created]


@router.get(
    "/projecten/{project_id}/maatregelen",
    response_model=List[MaatregelOut],
)
def list_maatregelen(
    project_id: UUID, user: VerifiedUser, db: DbSession
) -> List[MaatregelOut]:
    _project_or_403(db, project_id, user)
    rows = (
        db.execute(
            select(Maatregel)
            .where(Maatregel.project_id == project_id)
            .order_by(Maatregel.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [MaatregelOut.model_validate(m) for m in rows]


@router.post(
    "/projecten/{project_id}/maatregelen",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
)
def create_maatregel(
    project_id: UUID,
    payload: MaatregelCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    project = _project_or_403(db, project_id, user)

    if payload.maatregel_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="maatregel_type is verplicht",
        )

    m = Maatregel(
        project_id=project.id,
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
    old_status = m.status

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
    if _is_admin(user) and m.status != old_status:
        email_service.notify_klant_maatregel_status_change(
            db,
            maatregel=m,
            old_status=old_status,
            new_status=m.status,
        )
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

    project = db.get(Project, m.project_id)
    assert project is not None
    document_id = uuid4()
    object_key = (
        f"{project.organisation_id}/projecten/{project.id}/maatregelen/{m.id}/"
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
    "/admin/projecten/kritieke-deadlines",
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
