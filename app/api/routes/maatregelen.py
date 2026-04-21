"""Maatregelen CRUD + document checklist + upload.

Routes:
  GET    /panden/{pand_id}/maatregelen
  POST   /panden/{pand_id}/maatregelen
  GET    /maatregelen/{maatregel_id}
  PUT    /maatregelen/{maatregel_id}
  DELETE /maatregelen/{maatregel_id}
  GET    /maatregelen/{maatregel_id}/documenten
  POST   /maatregelen/{maatregel_id}/documenten         (upload-url)
  GET    /maatregelen/{maatregel_id}/checklist
  POST   /maatregelen/{maatregel_id}/documenten/{document_id}/verify  (admin)
  DELETE /maatregelen/{maatregel_id}/documenten/{document_id}
"""

from __future__ import annotations

from typing import Annotated, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, require_verified
from app.api.routes._panden_common import (
    get_maatregel_document_or_404,
    get_maatregel_or_404,
    get_pand_or_404,
    is_admin,
)
from app.models import Maatregel, MaatregelDocument, Pand, User
from app.models.enums import (
    MaatregelDocumentType,
    MaatregelStatus,
    MaatregelType,
    RegelingCode,
)
from app.schemas.panden import (
    ChecklistItem,
    ChecklistResponse,
    DocumentOut,
    DocumentUploadRequest,
    DocumentUploadResponse,
    MaatregelCreate,
    MaatregelListItem,
    MaatregelOut,
    MaatregelUpdate,
)
from app.services import panden_checklist, panden_deadline, r2_storage

VerifiedUser = Annotated[User, Depends(require_verified)]


panden_nested = APIRouter(prefix="/panden", tags=["maatregelen"])
maatregelen_router = APIRouter(prefix="/maatregelen", tags=["maatregelen"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maatregel_out(m: Maatregel) -> MaatregelOut:
    return MaatregelOut(
        id=m.id,
        pand_id=m.pand_id,
        created_by=m.created_by,
        maatregel_type=m.maatregel_type.value,
        omschrijving=m.omschrijving,
        status=m.status.value,
        regeling_code=(
            m.regeling_code.value if m.regeling_code is not None else None
        ),
        apparaat_merk=m.apparaat_merk,
        apparaat_typenummer=m.apparaat_typenummer,
        apparaat_meldcode=m.apparaat_meldcode,
        installateur_naam=m.installateur_naam,
        installateur_kvk=m.installateur_kvk,
        installateur_gecertificeerd=m.installateur_gecertificeerd,
        installatie_datum=m.installatie_datum,
        offerte_datum=m.offerte_datum,
        investering_bedrag=m.investering_bedrag,
        geschatte_subsidie=m.geschatte_subsidie,
        toegekende_subsidie=m.toegekende_subsidie,
        deadline_indienen=m.deadline_indienen,
        deadline_type=(
            m.deadline_type.value if m.deadline_type is not None else None
        ),
        deadline_status=(
            m.deadline_status.value if m.deadline_status is not None else None
        ),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _maatregel_list_item(m: Maatregel) -> MaatregelListItem:
    docs = getattr(m, "documenten", None) or []
    specs = panden_checklist.get_required_documents(m.maatregel_type)
    uploaded_types = {d.document_type for d in docs}
    uploaded_required = sum(
        1 for s in specs if s.verplicht and s.document_type in uploaded_types
    )
    required = sum(1 for s in specs if s.verplicht)
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
        documents_required=required,
        documents_uploaded=uploaded_required,
        documents_verified=sum(1 for d in docs if d.geverifieerd_door_admin),
        created_at=m.created_at,
    )


def _document_out(doc: MaatregelDocument) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        maatregel_id=doc.maatregel_id,
        document_type=doc.document_type.value,
        bestandsnaam=doc.bestandsnaam,
        r2_key=doc.r2_key,
        geupload_door=doc.geupload_door,
        geverifieerd_door_admin=doc.geverifieerd_door_admin,
        created_at=doc.created_at,
    )


def _build_r2_key(
    *, pand: Pand, maatregel_id: UUID, document_id: UUID, filename: str
) -> str:
    base = (
        f"{pand.organisation_id}/panden/{pand.id}/maatregelen/"
        f"{maatregel_id}/{document_id}"
    )
    return f"{base}/{r2_storage.safe_filename(filename)}"


def _apply_maatregel_defaults(m: Maatregel) -> None:
    """Re-infer regeling + bereken deadline + schat subsidie."""
    if m.regeling_code is None:
        m.regeling_code = panden_deadline.infer_regeling(m.maatregel_type)
    panden_deadline.apply_deadline_to(m)
    m.geschatte_subsidie = panden_deadline.estimate_subsidie(
        m.regeling_code, m.investering_bedrag
    )


# ---------------------------------------------------------------------------
# /panden/{pand_id}/maatregelen
# ---------------------------------------------------------------------------


@panden_nested.get(
    "/{pand_id}/maatregelen",
    response_model=List[MaatregelListItem],
    summary="Lijst van maatregelen voor een pand",
)
def list_maatregelen_voor_pand(
    pand_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> List[MaatregelListItem]:
    pand = get_pand_or_404(db, pand_id, user)
    rows = (
        db.execute(
            select(Maatregel)
            .where(Maatregel.pand_id == pand.id)
            .options(selectinload(Maatregel.documenten))
            .order_by(Maatregel.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_maatregel_list_item(m) for m in rows]


@panden_nested.post(
    "/{pand_id}/maatregelen",
    response_model=MaatregelOut,
    status_code=status.HTTP_201_CREATED,
    summary="Voeg een maatregel toe aan een pand",
)
def create_maatregel(
    pand_id: UUID,
    payload: MaatregelCreate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    pand = get_pand_or_404(db, pand_id, user)

    m = Maatregel(
        pand_id=pand.id,
        created_by=user.id,
        maatregel_type=MaatregelType(payload.maatregel_type),
        omschrijving=payload.omschrijving,
        status=(
            MaatregelStatus(payload.status)
            if payload.status is not None
            else MaatregelStatus.orientatie
        ),
        apparaat_merk=payload.apparaat_merk,
        apparaat_typenummer=payload.apparaat_typenummer,
        apparaat_meldcode=payload.apparaat_meldcode,
        installateur_naam=payload.installateur_naam,
        installateur_kvk=payload.installateur_kvk,
        installateur_gecertificeerd=bool(payload.installateur_gecertificeerd),
        installatie_datum=payload.installatie_datum,
        offerte_datum=payload.offerte_datum,
        investering_bedrag=payload.investering_bedrag,
        regeling_code=(
            RegelingCode(payload.regeling_code)
            if payload.regeling_code is not None
            else None
        ),
    )
    _apply_maatregel_defaults(m)
    db.add(m)
    db.commit()
    db.refresh(m)
    return _maatregel_out(m)


# ---------------------------------------------------------------------------
# /maatregelen/{id}
# ---------------------------------------------------------------------------


@maatregelen_router.get(
    "/{maatregel_id}",
    response_model=MaatregelOut,
    summary="Maatregel detail",
)
def get_maatregel(
    maatregel_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    m = get_maatregel_or_404(db, maatregel_id, user)
    return _maatregel_out(m)


@maatregelen_router.put(
    "/{maatregel_id}",
    response_model=MaatregelOut,
    summary="Maatregel bewerken",
)
def update_maatregel(
    maatregel_id: UUID,
    payload: MaatregelUpdate,
    user: VerifiedUser,
    db: DbSession,
) -> MaatregelOut:
    m = get_maatregel_or_404(db, maatregel_id, user)
    data = payload.model_dump(exclude_unset=True)

    # ``toegekende_subsidie`` alleen door admin te zetten — dit is
    # de daadwerkelijke RVO-uitkomst.
    if "toegekende_subsidie" in data and not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen AAA-Lex kan de toegekende subsidie invullen",
        )

    if "omschrijving" in data:
        m.omschrijving = data["omschrijving"]
    if "status" in data and data["status"] is not None:
        m.status = MaatregelStatus(data["status"])
    if "apparaat_merk" in data:
        m.apparaat_merk = data["apparaat_merk"]
    if "apparaat_typenummer" in data:
        m.apparaat_typenummer = data["apparaat_typenummer"]
    if "apparaat_meldcode" in data:
        m.apparaat_meldcode = data["apparaat_meldcode"]
    if "installateur_naam" in data:
        m.installateur_naam = data["installateur_naam"]
    if "installateur_kvk" in data:
        m.installateur_kvk = data["installateur_kvk"]
    if "installateur_gecertificeerd" in data:
        m.installateur_gecertificeerd = bool(
            data["installateur_gecertificeerd"]
        )
    if "installatie_datum" in data:
        m.installatie_datum = data["installatie_datum"]
    if "offerte_datum" in data:
        m.offerte_datum = data["offerte_datum"]
    if "investering_bedrag" in data:
        m.investering_bedrag = data["investering_bedrag"]
    if "toegekende_subsidie" in data:
        m.toegekende_subsidie = data["toegekende_subsidie"]
    if "regeling_code" in data:
        m.regeling_code = (
            RegelingCode(data["regeling_code"])
            if data["regeling_code"] is not None
            else None
        )

    _apply_maatregel_defaults(m)
    db.commit()
    db.refresh(m)
    return _maatregel_out(m)


@maatregelen_router.delete(
    "/{maatregel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Maatregel verwijderen",
)
def delete_maatregel(
    maatregel_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> Response:
    m = get_maatregel_or_404(db, maatregel_id, user)
    # Verwijder R2 objecten bij de documenten voordat we de rij droppen.
    for doc in list(m.documenten):
        r2_storage.delete_object(doc.r2_key)
    db.delete(m)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Documenten + checklist
# ---------------------------------------------------------------------------


@maatregelen_router.get(
    "/{maatregel_id}/documenten",
    response_model=List[DocumentOut],
    summary="Documenten van een maatregel",
)
def list_documenten(
    maatregel_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> List[DocumentOut]:
    m = get_maatregel_or_404(db, maatregel_id, user)
    return [_document_out(d) for d in sorted(
        m.documenten, key=lambda d: d.created_at, reverse=True
    )]


@maatregelen_router.post(
    "/{maatregel_id}/documenten",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Vraag een presigned R2 upload-URL aan en registreer het document",
)
def create_document_upload(
    maatregel_id: UUID,
    payload: DocumentUploadRequest,
    user: VerifiedUser,
    db: DbSession,
) -> DocumentUploadResponse:
    m = get_maatregel_or_404(db, maatregel_id, user)

    try:
        document_type = MaatregelDocumentType(payload.document_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Onbekend documenttype '{payload.document_type}'",
        ) from exc

    if not panden_checklist.document_type_is_valid_for(
        m.maatregel_type, document_type
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Documenttype '{document_type.value}' is niet toegestaan "
                f"voor maatregel-type '{m.maatregel_type.value}'"
            ),
        )

    document_id = uuid4()
    r2_key = _build_r2_key(
        pand=m.pand,
        maatregel_id=m.id,
        document_id=document_id,
        filename=payload.filename,
    )
    upload_url = r2_storage.generate_upload_url(
        r2_key,
        content_type=payload.content_type,
        expires_in=3600,
    )

    doc = MaatregelDocument(
        id=document_id,
        maatregel_id=m.id,
        document_type=document_type,
        bestandsnaam=r2_storage.safe_filename(payload.filename),
        r2_key=r2_key,
        geupload_door=user.id,
        geverifieerd_door_admin=False,
    )
    db.add(doc)
    db.commit()

    return DocumentUploadResponse(
        upload_url=upload_url,
        document_id=document_id,
        expires_in=3600,
        r2_key=r2_key,
        content_type=payload.content_type,
    )


@maatregelen_router.get(
    "/{maatregel_id}/checklist",
    response_model=ChecklistResponse,
    summary="Document checklist voor een maatregel",
)
def get_checklist(
    maatregel_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> ChecklistResponse:
    m = get_maatregel_or_404(db, maatregel_id, user)
    specs = panden_checklist.get_required_documents(m.maatregel_type)

    # Houd per document_type de meest recente upload aan.
    latest_by_type: dict[MaatregelDocumentType, MaatregelDocument] = {}
    for doc in m.documenten:
        cur = latest_by_type.get(doc.document_type)
        if cur is None or doc.created_at > cur.created_at:
            latest_by_type[doc.document_type] = doc

    items: List[ChecklistItem] = []
    seen_types: set[MaatregelDocumentType] = set()
    for spec in specs:
        seen_types.add(spec.document_type)
        doc = latest_by_type.get(spec.document_type)
        items.append(
            ChecklistItem(
                document_type=spec.document_type.value,
                label=spec.label,
                uitleg=spec.uitleg,
                verplicht=spec.verplicht,
                geupload=doc is not None,
                geverifieerd=bool(doc.geverifieerd_door_admin) if doc else False,
                document_id=doc.id if doc else None,
                bestandsnaam=doc.bestandsnaam if doc else None,
            )
        )

    # Toon eveneens extra geüploade documenten die niet in de spec staan.
    for dt, doc in latest_by_type.items():
        if dt in seen_types:
            continue
        items.append(
            ChecklistItem(
                document_type=dt.value,
                label=panden_checklist.label_for(dt),
                uitleg=panden_checklist.uitleg_for(dt, m.maatregel_type),
                verplicht=False,
                geupload=True,
                geverifieerd=bool(doc.geverifieerd_door_admin),
                document_id=doc.id,
                bestandsnaam=doc.bestandsnaam,
            )
        )

    required_count = sum(1 for it in items if it.verplicht)
    uploaded_required = sum(1 for it in items if it.verplicht and it.geupload)
    missing = required_count - uploaded_required

    return ChecklistResponse(
        maatregel_id=m.id,
        items=items,
        required_count=required_count,
        uploaded_required_count=uploaded_required,
        missing_count=missing,
        compleet=missing == 0 and required_count > 0,
    )


@maatregelen_router.post(
    "/{maatregel_id}/documenten/{document_id}/verify",
    response_model=DocumentOut,
    summary="Admin: markeer een document als geverifieerd",
)
def verify_document(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> DocumentOut:
    if not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen AAA-Lex (admin) kan documenten verifiëren",
        )
    doc, m = get_maatregel_document_or_404(db, document_id, user)
    if m.id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document hoort niet bij deze maatregel",
        )
    doc.geverifieerd_door_admin = True
    db.commit()
    db.refresh(doc)
    return _document_out(doc)


@maatregelen_router.delete(
    "/{maatregel_id}/documenten/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Document verwijderen",
)
def delete_document(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> Response:
    doc, m = get_maatregel_document_or_404(db, document_id, user)
    if m.id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document hoort niet bij deze maatregel",
        )
    if doc.geverifieerd_door_admin and not is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geverifieerde documenten kunnen alleen door AAA-Lex worden verwijderd",
        )
    r2_storage.delete_object(doc.r2_key)
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@maatregelen_router.get(
    "/{maatregel_id}/documenten/{document_id}/download-url",
    summary="Presigned download URL voor een document",
)
def document_download_url(
    maatregel_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> dict:
    doc, m = get_maatregel_document_or_404(db, document_id, user)
    if m.id != maatregel_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document hoort niet bij deze maatregel",
        )
    url = r2_storage.generate_download_url(
        doc.r2_key, expires_in=900, download_filename=doc.bestandsnaam
    )
    return {"download_url": url, "expires_in": 900}
