from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


RegelingCodeStr = Literal["ISDE", "EIA", "MIA", "VAMIL", "DUMAVA"]
TypeAanvragerStr = Literal[
    "particulier", "zakelijk", "vve", "maatschappelijk", "ondernemer"
]
MaatregelStr = Literal["warmtepomp", "isolatie", "energiesysteem", "meerdere"]
StatusStr = Literal[
    "intake", "documenten", "review", "ingediend", "goedgekeurd", "afgewezen"
]
DeadlineTypeStr = Literal["EIA_3maanden", "DUMAVA_2jaar", "DUMAVA_3jaar"]


class AanvraagCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regeling: RegelingCodeStr
    type_aanvrager: TypeAanvragerStr
    maatregel: MaatregelStr
    investering_bedrag: Optional[Decimal] = Field(default=None, ge=0)
    offerte_beschikbaar: bool = False
    gewenste_startdatum: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=5000)


class AanvraagUpdate(BaseModel):
    """Fields a client can update on their own aanvraag.

    Clients cannot change status, regeling or financial fields that
    belong to AAA-Lex workflow.
    """

    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = Field(default=None, max_length=5000)
    investering_bedrag: Optional[Decimal] = Field(default=None, ge=0)
    gewenste_startdatum: Optional[date] = None


class AanvraagListItem(BaseModel):
    id: UUID
    regeling: RegelingCodeStr
    type_aanvrager: TypeAanvragerStr
    maatregel: MaatregelStr
    status: StatusStr
    investering_bedrag: Optional[Decimal] = None
    geschatte_subsidie: Optional[Decimal] = None
    toegekende_subsidie: Optional[Decimal] = None
    aaa_lex_fee_percentage: Optional[Decimal] = None
    aaa_lex_fee_bedrag: Optional[Decimal] = None
    deadline_datum: Optional[date] = None
    deadline_type: Optional[DeadlineTypeStr] = None
    created_at: datetime
    document_count: int = 0
    missing_document_count: int = 0


class AanvraagDocumentOut(BaseModel):
    id: UUID
    document_type: str
    filename: str
    storage_url: str
    verified: bool
    notes: Optional[str] = None
    uploaded_at: datetime


class StatusTimelineEvent(BaseModel):
    status: StatusStr
    label: str
    reached: bool
    current: bool
    at: Optional[datetime] = None


class AanvraagOut(BaseModel):
    id: UUID
    organisation_id: UUID
    aanvrager_id: UUID
    regeling: RegelingCodeStr
    type_aanvrager: TypeAanvragerStr
    maatregel: MaatregelStr
    status: StatusStr
    investering_bedrag: Optional[Decimal] = None
    geschatte_subsidie: Optional[Decimal] = None
    toegekende_subsidie: Optional[Decimal] = None
    aaa_lex_fee_percentage: Optional[Decimal] = None
    aaa_lex_fee_bedrag: Optional[Decimal] = None
    klant_ontvangt: Optional[Decimal] = None
    deadline_datum: Optional[date] = None
    deadline_type: Optional[DeadlineTypeStr] = None
    rvo_aanvraagnummer: Optional[str] = None
    rvo_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    organisation_name: Optional[str] = None
    aanvrager_name: Optional[str] = None
    aanvrager_email: Optional[str] = None
    aanvrager_phone: Optional[str] = None
    aaa_lex_project_id: Optional[UUID] = None
    documenten: list[AanvraagDocumentOut] = Field(default_factory=list)
    status_timeline: list[StatusTimelineEvent] = Field(default_factory=list)


class DocumentChecklistItem(BaseModel):
    document_type: str
    label: str
    required: bool
    uploaded: bool
    verified: bool
    document_id: Optional[UUID] = None
    upload_url: Optional[str] = None


class DocumentChecklistResponse(BaseModel):
    aanvraag_id: UUID
    regeling: RegelingCodeStr
    items: list[DocumentChecklistItem]
    uploaded_count: int
    required_count: int
    missing_count: int
