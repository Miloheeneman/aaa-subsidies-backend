"""Document upload + download routes (R2 backed)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_verified
from app.models import AanvraagDocument, SubsidieAanvraag
from app.models.enums import AanvraagStatus, DocumentType, UserRole
from app.models.user import User
from app.schemas.documenten import (
    DocumentOut,
    DownloadUrlResponse,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.services import r2_storage
from app.services.subsidy_matching import document_checklist_for

router = APIRouter(prefix="/aanvragen", tags=["documenten"])


VerifiedUser = Annotated[User, Depends(require_verified)]


def _is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def _can_access(aanvraag: SubsidieAanvraag, user: User) -> bool:
    if _is_admin(user):
        return True
    return aanvraag.organisation_id == user.organisation_id


def _get_or_403(
    db, aanvraag_id: UUID, user: User
) -> SubsidieAanvraag:
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
    return aanvraag


def _doc_out(doc: AanvraagDocument) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        aanvraag_id=doc.aanvraag_id,
        document_type=doc.document_type.value
        if hasattr(doc.document_type, "value")
        else str(doc.document_type),
        filename=doc.filename,
        storage_url=doc.storage_url,
        verified=doc.verified,
        pending_upload=doc.storage_url.startswith("pending://"),
        notes=doc.notes,
        uploaded_at=doc.uploaded_at,
    )


@router.post(
    "/{aanvraag_id}/documenten/upload-url",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Vraag een presigned R2 upload-URL aan voor een nieuw document",
)
def request_upload_url(
    aanvraag_id: UUID,
    payload: UploadUrlRequest,
    user: VerifiedUser,
    db: DbSession,
) -> UploadUrlResponse:
    aanvraag = _get_or_403(db, aanvraag_id, user)

    try:
        document_type = DocumentType(payload.document_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Onbekend documenttype '{payload.document_type}'",
        ) from exc

    # Validate document_type belongs to this aanvraag's regeling.
    allowed = set(document_checklist_for(aanvraag.regeling, aanvraag.type_aanvrager))
    if document_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Documenttype '{document_type.value}' is niet vereist voor "
                f"regeling {aanvraag.regeling.value}"
            ),
        )

    # Pre-generate the document id so its key is stable.
    document_id = uuid4()
    object_key = r2_storage.build_object_key(
        organisation_id=aanvraag.organisation_id,
        aanvraag_id=aanvraag.id,
        document_id=document_id,
        filename=payload.filename,
    )

    upload_url = r2_storage.generate_upload_url(
        object_key,
        content_type=payload.content_type,
        expires_in=3600,
    )

    doc = AanvraagDocument(
        id=document_id,
        aanvraag_id=aanvraag.id,
        document_type=document_type,
        filename=r2_storage.safe_filename(payload.filename),
        storage_url=r2_storage.make_pending_url(object_key),
        verified=False,
    )
    db.add(doc)
    db.commit()

    return UploadUrlResponse(
        upload_url=upload_url,
        document_id=document_id,
        expires_in=3600,
        object_key=object_key,
        content_type=payload.content_type,
    )


@router.post(
    "/{aanvraag_id}/documenten/{document_id}/confirm",
    response_model=DocumentOut,
    summary="Bevestig dat een document succesvol naar R2 is geüpload",
)
def confirm_upload(
    aanvraag_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> DocumentOut:
    aanvraag = _get_or_403(db, aanvraag_id, user)
    doc = db.get(AanvraagDocument, document_id)
    if doc is None or doc.aanvraag_id != aanvraag.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document niet gevonden"
        )

    object_key = r2_storage.object_key_from_storage_url(doc.storage_url)
    doc.storage_url = r2_storage.make_committed_url(object_key)
    db.flush()

    if aanvraag.status == AanvraagStatus.intake:
        any_confirmed = db.execute(
            select(AanvraagDocument.id)
            .where(AanvraagDocument.aanvraag_id == aanvraag.id)
            .where(~AanvraagDocument.storage_url.like("pending://%"))
            .limit(1)
        ).scalar_one_or_none()
        if any_confirmed is not None:
            aanvraag.status = AanvraagStatus.documenten

    db.commit()
    db.refresh(doc)
    return _doc_out(doc)


@router.delete(
    "/{aanvraag_id}/documenten/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Verwijder een document (alleen indien nog niet geverifieerd)",
)
def delete_document(
    aanvraag_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> Response:
    aanvraag = _get_or_403(db, aanvraag_id, user)
    doc = db.get(AanvraagDocument, document_id)
    if doc is None or doc.aanvraag_id != aanvraag.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document niet gevonden"
        )

    if doc.verified and not _is_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Geverifieerde documenten kunnen niet meer worden verwijderd"
            ),
        )

    object_key = r2_storage.object_key_from_storage_url(doc.storage_url)
    r2_storage.delete_object(object_key)
    db.delete(doc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{aanvraag_id}/documenten/{document_id}/download-url",
    response_model=DownloadUrlResponse,
    summary="Vraag een presigned R2 download-URL aan voor een document",
)
def request_download_url(
    aanvraag_id: UUID,
    document_id: UUID,
    user: VerifiedUser,
    db: DbSession,
) -> DownloadUrlResponse:
    aanvraag = _get_or_403(db, aanvraag_id, user)
    doc = db.get(AanvraagDocument, document_id)
    if doc is None or doc.aanvraag_id != aanvraag.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document niet gevonden"
        )
    if doc.storage_url.startswith("pending://"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document upload nog niet bevestigd",
        )

    object_key = r2_storage.object_key_from_storage_url(doc.storage_url)
    url = r2_storage.generate_download_url(
        object_key, expires_in=900, download_filename=doc.filename
    )
    return DownloadUrlResponse(download_url=url, expires_in=900)
