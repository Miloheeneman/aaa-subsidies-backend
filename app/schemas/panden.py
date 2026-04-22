"""Pydantic schemas for the panden module (STAP 9)."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    DeadlineStatus,
    DeadlineTiming,
    EigenaarType,
    EnergielabelKlasse,
    MaatregelDocumentType,
    MaatregelStatus,
    MaatregelType,
    PandType,
    RegelingCode,
)


# ---------------------------------------------------------------------------
# Panden
# ---------------------------------------------------------------------------


class PandBase(BaseModel):
    straat: str = Field(min_length=1, max_length=255)
    huisnummer: str = Field(min_length=1, max_length=32)
    postcode: str = Field(min_length=4, max_length=16)
    plaats: str = Field(min_length=1, max_length=128)
    bouwjaar: int = Field(ge=1500, le=2100)
    pand_type: PandType
    eigenaar_type: EigenaarType


class PandCreate(PandBase):
    pass


class PandUpdate(BaseModel):
    """All fields optional; only the fields you send get overwritten."""

    straat: Optional[str] = Field(default=None, min_length=1, max_length=255)
    huisnummer: Optional[str] = Field(default=None, min_length=1, max_length=32)
    postcode: Optional[str] = Field(default=None, min_length=4, max_length=16)
    plaats: Optional[str] = Field(default=None, min_length=1, max_length=128)
    bouwjaar: Optional[int] = Field(default=None, ge=1500, le=2100)
    pand_type: Optional[PandType] = None
    eigenaar_type: Optional[EigenaarType] = None

    # AAA-Lex-only velden — worden door het backend stilletjes genegeerd
    # voor niet-admins (zie routes/panden.py).
    energielabel_huidig: Optional[EnergielabelKlasse] = None
    energielabel_na_maatregelen: Optional[EnergielabelKlasse] = None
    oppervlakte_m2: Optional[float] = Field(default=None, ge=0)
    notities: Optional[str] = None
    aaa_lex_project_id: Optional[UUID] = None


class MaatregelShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    maatregel_type: MaatregelType
    status: MaatregelStatus
    regeling_code: Optional[RegelingCode] = None
    geschatte_subsidie: Optional[float] = None
    deadline_indienen: Optional[date] = None
    deadline_status: Optional[DeadlineStatus] = None


class PandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organisation_id: UUID
    created_by: UUID

    straat: str
    huisnummer: str
    postcode: str
    plaats: str
    bouwjaar: int
    pand_type: PandType
    eigenaar_type: EigenaarType

    energielabel_huidig: Optional[EnergielabelKlasse] = None
    energielabel_na_maatregelen: Optional[EnergielabelKlasse] = None
    oppervlakte_m2: Optional[float] = None
    notities: Optional[str] = None
    aaa_lex_project_id: Optional[UUID] = None

    created_at: datetime
    updated_at: datetime

    # Afgeleid, ingevuld door de route
    aantal_maatregelen: int = 0
    worst_deadline_status: Optional[DeadlineStatus] = None
    organisation_name: Optional[str] = None  # alleen gevuld voor admins


class PandListResponse(BaseModel):
    items: List[PandOut]
    totaal: int
    quota: "QuotaInfo"


class PandDetailResponse(PandOut):
    maatregelen: List[MaatregelShort] = []


# ---------------------------------------------------------------------------
# Maatregelen
# ---------------------------------------------------------------------------


class MaatregelCreate(BaseModel):
    maatregel_type: MaatregelType
    omschrijving: Optional[str] = None
    status: Optional[MaatregelStatus] = None

    apparaat_merk: Optional[str] = Field(default=None, max_length=128)
    apparaat_typenummer: Optional[str] = Field(default=None, max_length=128)
    apparaat_meldcode: Optional[str] = Field(default=None, max_length=128)
    installateur_naam: Optional[str] = Field(default=None, max_length=255)
    installateur_kvk: Optional[str] = Field(default=None, max_length=32)
    installateur_gecertificeerd: Optional[bool] = None
    installatie_datum: Optional[date] = None
    offerte_datum: Optional[date] = None

    investering_bedrag: Optional[float] = Field(default=None, ge=0)
    geschatte_subsidie: Optional[float] = Field(default=None, ge=0)
    regeling_code: Optional[RegelingCode] = None


class MaatregelUpdate(MaatregelCreate):
    maatregel_type: Optional[MaatregelType] = None  # type: ignore[assignment]
    toegekende_subsidie: Optional[float] = Field(default=None, ge=0)


class MaatregelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pand_id: UUID
    created_by: UUID

    maatregel_type: MaatregelType
    omschrijving: Optional[str] = None
    status: MaatregelStatus

    apparaat_merk: Optional[str] = None
    apparaat_typenummer: Optional[str] = None
    apparaat_meldcode: Optional[str] = None
    installateur_naam: Optional[str] = None
    installateur_kvk: Optional[str] = None
    installateur_gecertificeerd: bool
    installatie_datum: Optional[date] = None
    offerte_datum: Optional[date] = None

    investering_bedrag: Optional[float] = None
    geschatte_subsidie: Optional[float] = None
    toegekende_subsidie: Optional[float] = None
    regeling_code: Optional[RegelingCode] = None

    deadline_indienen: Optional[date] = None
    deadline_type: Optional[DeadlineTiming] = None
    deadline_status: Optional[DeadlineStatus] = None

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Checklist + documenten
# ---------------------------------------------------------------------------


class ChecklistItemOut(BaseModel):
    document_type: MaatregelDocumentType
    label: str
    uitleg: str
    verplicht: bool
    geupload: bool
    geverifieerd: bool
    document_id: Optional[UUID] = None


class ChecklistResponse(BaseModel):
    maatregel_id: UUID
    items: List[ChecklistItemOut]
    verplicht_totaal: int
    verplicht_geupload: int
    verplicht_geverifieerd: int
    compleet: bool  # alle verplichte docs geüpload (niet per se geverifieerd)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    maatregel_id: UUID
    document_type: MaatregelDocumentType
    bestandsnaam: str
    r2_key: str
    geupload_door: UUID
    geverifieerd_door_admin: bool
    notities: Optional[str] = None
    created_at: datetime
    pending_upload: bool = False


class UploadUrlRequest(BaseModel):
    document_type: MaatregelDocumentType
    bestandsnaam: str = Field(min_length=1, max_length=512)
    content_type: str = Field(default="application/octet-stream", max_length=128)


class UploadUrlResponse(BaseModel):
    upload_url: str
    document_id: UUID
    r2_key: str
    expires_in: int


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------


class QuotaInfo(BaseModel):
    plan: str
    limit: Optional[int] = None  # None = unlimited (admin/enterprise)
    used: int = 0
    remaining: Optional[int] = None
    exceeded: bool = False


# ---------------------------------------------------------------------------
# Subsidie matching
# ---------------------------------------------------------------------------


class SubsidieMatchOut(BaseModel):
    """Eén regeling-match voor een pand (zie panden_service.SubsidieMatch)."""

    code: str
    naam: str
    beschrijving: str
    max_subsidie: Optional[float] = None
    fee_percentage: float
    deadline_type: str  # "na_installatie" | "voor_offerte"
    deadline_maanden: int
    eligible: bool
    reden: Optional[str] = None


class SubsidieMatchResponse(BaseModel):
    pand_id: UUID
    eligible: List[SubsidieMatchOut]
    niet_eligible: List[SubsidieMatchOut]


class IsdeWarmtepompAanvraagCreate(BaseModel):
    """Payload voor de ISDE warmtepomp intake-wizard (klant)."""

    situatie: Literal["geinstalleerd", "orienteren"]
    warmtepomp_subtype: Literal[
        "warmtepomp_lucht_water",
        "warmtepomp_water_water",
        "warmtepomp_hybride",
    ]
    apparaat_merk: Optional[str] = Field(default=None, max_length=128)
    apparaat_typenummer: Optional[str] = Field(default=None, max_length=128)
    apparaat_meldcode: Optional[str] = Field(default=None, max_length=128)

    installateur_naam: str = Field(min_length=1, max_length=255)
    installateur_kvk: Optional[str] = Field(default=None, max_length=32)
    installateur_gecertificeerd: bool = False
    installatie_datum: Optional[date] = None

    investering_bedrag: Optional[float] = Field(default=None, ge=0)
    heeft_offerte: bool = False
    offerte_datum: Optional[date] = None


class IsdeIsolatieTypeIn(BaseModel):
    """Eén isolatietype binnen de ISDE-isolatie wizard."""

    maatregel_type: Literal["dakisolatie", "gevelisolatie", "vloerisolatie", "hr_glas"]
    oppervlakte_m2: float = Field(gt=0)
    meldcode_materiaal: Optional[str] = Field(default=None, max_length=128)
    al_uitgevoerd: bool = False
    uitvoeringsdatum: Optional[date] = None
    investering_bedrag: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_isolatie_type(self) -> "IsdeIsolatieTypeIn":
        if self.maatregel_type == "hr_glas" and self.oppervlakte_m2 < 3:
            raise ValueError(
                "Voor HR++ glas is minimaal 3 m² vereist voor ISDE"
            )
        if self.al_uitgevoerd and self.uitvoeringsdatum is None:
            raise ValueError(
                "Vul de uitvoeringsdatum in als de isolatie al is uitgevoerd"
            )
        return self


class IsdeIsolatieAanvraagCreate(BaseModel):
    """Payload voor de ISDE isolatie intake-wizard (meerdere maatregelen)."""

    items: List[IsdeIsolatieTypeIn] = Field(min_length=1, max_length=4)
    installateur_naam: str = Field(min_length=1, max_length=255)
    installateur_kvk: Optional[str] = Field(default=None, max_length=32)
    installatie_of_geplande_datum: Optional[date] = None

    @model_validator(mode="after")
    def _unique_types(self) -> "IsdeIsolatieAanvraagCreate":
        ts = [i.maatregel_type for i in self.items]
        if len(ts) != len(set(ts)):
            raise ValueError("Elk isolatietype maximaal één keer kiezen")
        return self


PandListResponse.model_rebuild()
