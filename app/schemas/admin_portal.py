"""Response-modellen voor het admin-portal (Optie A)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminPortalStats(BaseModel):
    totaal_klanten: int
    projecten_deze_maand: int
    openstaande_dossiers: int
    ingediend_deze_maand: int


class ActionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    urgency: Literal["kritiek", "waarschuwing"]
    maatregel_id: UUID
    project_id: UUID
    organisation_id: UUID
    organisation_name: str
    project_adres: str
    regeling: Optional[str] = None
    deadline_indienen: Optional[date] = None
    status: str
    link: str


class ActivityItemOut(BaseModel):
    at: datetime
    message: str
    link: Optional[str] = None


class AdminNoteOut(BaseModel):
    id: UUID
    body: str
    author_email: str
    created_at: datetime


class AdminNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=8000)


class KlantDetailOut(BaseModel):
    id: UUID
    name: str
    kvk_number: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_phone: Optional[str] = None
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    created_at: datetime


class MaatregelTreeOut(BaseModel):
    id: UUID
    regeling_code: Optional[str] = None
    status: str
    deadline_indienen: Optional[date] = None
    deadline_status: Optional[str] = None
    verplicht_docs_totaal: int = 0
    verplicht_docs_geupload: int = 0


class ProjectTreeOut(BaseModel):
    id: UUID
    adres_label: str
    bouwjaar: int
    maatregelen: list[MaatregelTreeOut]


class KlantProjectenTreeResponse(BaseModel):
    organisation_id: UUID
    organisation_name: str
    projecten: list[ProjectTreeOut]


class DossierListItemOut(BaseModel):
    maatregel_id: UUID
    project_id: UUID
    organisation_id: UUID
    organisation_name: str
    project_adres: str
    regeling: Optional[str] = None
    status: str
    deadline_indienen: Optional[date] = None
    deadline_status: Optional[str] = None
    verplicht_docs_totaal: int = 0
    verplicht_docs_geupload: int = 0
    missende_verplicht: int = 0
    created_at: datetime


class DossierListPage(BaseModel):
    items: list[DossierListItemOut]
    total: int
    page: int
    per_page: int
    pages: int


class MaatregelStatusUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)


class UploadVerzoekCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_types: list[str] = Field(min_length=1, max_length=32)
    bericht: Optional[str] = Field(default=None, max_length=4000)


class UploadVerzoekCreatedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    token_expires_at: datetime
    document_types: list[str]
