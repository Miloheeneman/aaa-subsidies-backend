from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DocumentTypeStr = Literal[
    "offerte",
    "factuur",
    "betalingsbewijs",
    "foto_installatie",
    "werkbon",
    "energielabel",
    "kvk_uittreksel",
    "technische_specs",
    "energielijst_bewijs",
    "milieulijst_bewijs",
    "maatwerkadvies",
    "begroting",
    "foto_voor",
    "foto_na",
]


class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentTypeStr
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)


class UploadUrlResponse(BaseModel):
    upload_url: str
    document_id: UUID
    expires_in: int = 3600
    object_key: str
    content_type: str


class DocumentOut(BaseModel):
    id: UUID
    aanvraag_id: UUID
    document_type: str
    filename: str
    storage_url: str
    verified: bool
    pending_upload: bool
    notes: Optional[str] = None
    uploaded_at: datetime


class DownloadUrlResponse(BaseModel):
    download_url: str
    expires_in: int = 900
