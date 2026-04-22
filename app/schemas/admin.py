from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StatusStr = Literal[
    "intake", "documenten", "review", "ingediend", "goedgekeurd", "afgewezen"
]
RegelingCodeStr = Literal["ISDE", "EIA", "MIA", "VAMIL", "DUMAVA"]


class StatusCounts(BaseModel):
    intake: int = 0
    documenten: int = 0
    review: int = 0
    ingediend: int = 0
    goedgekeurd: int = 0
    afgewezen: int = 0


class RegelingCounts(BaseModel):
    ISDE: int = 0
    EIA: int = 0
    MIA: int = 0
    VAMIL: int = 0
    DUMAVA: int = 0


class AdminDashboardResponse(BaseModel):
    totaal_aanvragen: int
    per_status: StatusCounts
    per_regeling: RegelingCounts
    totaal_geschatte_subsidie: Decimal
    totaal_toegekende_subsidie: Decimal
    totaal_aaa_lex_fee: Decimal
    aanvragen_deze_maand: int
    deadlines_verlopen: int
    deadlines_binnen_14_dagen: int


class AdminAanvraagListItem(BaseModel):
    id: UUID
    regeling: RegelingCodeStr
    type_aanvrager: str
    maatregel: str
    status: StatusStr
    investering_bedrag: Optional[Decimal] = None
    geschatte_subsidie: Optional[Decimal] = None
    toegekende_subsidie: Optional[Decimal] = None
    aaa_lex_fee_percentage: Optional[Decimal] = None
    aaa_lex_fee_bedrag: Optional[Decimal] = None
    deadline_datum: Optional[str] = None
    deadline_type: Optional[str] = None
    created_at: datetime
    organisation_id: UUID
    organisation_name: str
    aanvrager_id: UUID
    aanvrager_name: str
    aanvrager_email: str


class AdminAanvragenPage(BaseModel):
    items: list[AdminAanvraagListItem]
    total: int
    page: int
    per_page: int
    pages: int


class StatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StatusStr
    notes: Optional[str] = Field(default=None, max_length=5000)
    toegekende_subsidie: Optional[Decimal] = Field(default=None, ge=0)


class KlantSummary(BaseModel):
    id: UUID
    name: str
    kvk_number: Optional[str] = None
    primary_contact_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_phone: Optional[str] = None
    subscription_plan: Optional[str] = None
    aanvraag_count: int
    project_count: int = 0
    active_maatregel_count: int = 0
    critical_maatregel_count: int = 0
    totaal_geschatte_subsidie: Decimal
    totaal_toegekende_subsidie: Decimal
    created_at: datetime


class InstallateurSummary(BaseModel):
    id: UUID
    name: str
    subscription_plan: Optional[str] = None
    subscription_status: Optional[str] = None
    lead_count: int
    active_dossier_count: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Regelingen config
# ---------------------------------------------------------------------------


class RegelingConfigOut(BaseModel):
    id: UUID
    code: RegelingCodeStr
    naam: str
    beschrijving: str
    actief: bool
    fee_percentage: Decimal
    min_investering: Optional[Decimal] = None
    max_subsidie: Optional[Decimal] = None
    aanvraag_termijn_dagen: Optional[int] = None
    updated_at: datetime


class RegelingConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    naam: Optional[str] = Field(default=None, min_length=1, max_length=128)
    beschrijving: Optional[str] = Field(default=None, max_length=4000)
    actief: Optional[bool] = None
    fee_percentage: Optional[Decimal] = Field(default=None, ge=0, le=100)
    min_investering: Optional[Decimal] = Field(default=None, ge=0)
    max_subsidie: Optional[Decimal] = Field(default=None, ge=0)
    aanvraag_termijn_dagen: Optional[int] = Field(default=None, ge=1, le=3650)


# ---------------------------------------------------------------------------
# Deadline check
# ---------------------------------------------------------------------------


class DeadlineRunResponse(BaseModel):
    checked: int
    warnings_sent: int
    expired: int
    skipped_recent: int = 0
    skipped_no_contact: int = 0
    maatregelen_checked: int = 0
    maatregel_admin_deadline_mails: int = 0
