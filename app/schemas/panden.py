"""Pydantic schemas voor de panden-module."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Panden
# ---------------------------------------------------------------------------


class PandBase(BaseModel):
    straat: str = Field(min_length=1, max_length=255)
    huisnummer: str = Field(min_length=1, max_length=32)
    postcode: str = Field(min_length=1, max_length=16)
    plaats: str = Field(min_length=1, max_length=128)
    bouwjaar: int = Field(ge=1500, le=2100)
    pand_type: Literal[
        "woning",
        "appartement",
        "kantoor",
        "bedrijfspand",
        "zorginstelling",
        "school",
        "sportaccommodatie",
        "overig",
    ]
    eigenaar_type: Literal[
        "eigenaar_bewoner",
        "particulier_verhuurder",
        "zakelijk_verhuurder",
        "vve",
        "overig",
    ]


class PandCreate(PandBase):
    # Klanten kunnen deze optioneel meegeven; admin vult ze later bij.
    oppervlakte_m2: Optional[float] = Field(default=None, ge=0)
    notities: Optional[str] = None


class PandUpdate(BaseModel):
    straat: Optional[str] = Field(default=None, min_length=1, max_length=255)
    huisnummer: Optional[str] = Field(default=None, min_length=1, max_length=32)
    postcode: Optional[str] = Field(default=None, min_length=1, max_length=16)
    plaats: Optional[str] = Field(default=None, min_length=1, max_length=128)
    bouwjaar: Optional[int] = Field(default=None, ge=1500, le=2100)
    pand_type: Optional[
        Literal[
            "woning",
            "appartement",
            "kantoor",
            "bedrijfspand",
            "zorginstelling",
            "school",
            "sportaccommodatie",
            "overig",
        ]
    ] = None
    eigenaar_type: Optional[
        Literal[
            "eigenaar_bewoner",
            "particulier_verhuurder",
            "zakelijk_verhuurder",
            "vve",
            "overig",
        ]
    ] = None
    # AAA-Lex opname-velden (admin-only via API dispatcher).
    energielabel_huidig: Optional[
        Literal["A", "B", "C", "D", "E", "F", "G"]
    ] = None
    energielabel_na_maatregelen: Optional[
        Literal["A", "B", "C", "D", "E", "F", "G"]
    ] = None
    oppervlakte_m2: Optional[float] = Field(default=None, ge=0)
    notities: Optional[str] = None


class PandListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    straat: str
    huisnummer: str
    postcode: str
    plaats: str
    bouwjaar: int
    pand_type: str
    eigenaar_type: str
    energielabel_huidig: Optional[str] = None
    maatregelen_count: int = 0
    # Samenvatting van deadlines op maatregel-niveau ("kritiek" dominante).
    deadline_status: Optional[str] = None
    created_at: datetime


class PandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organisation_id: UUID
    organisation_name: Optional[str] = None
    created_by: UUID
    straat: str
    huisnummer: str
    postcode: str
    plaats: str
    bouwjaar: int
    pand_type: str
    eigenaar_type: str
    energielabel_huidig: Optional[str] = None
    energielabel_na_maatregelen: Optional[str] = None
    oppervlakte_m2: Optional[float] = None
    notities: Optional[str] = None
    aaa_lex_project_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Maatregelen
# ---------------------------------------------------------------------------


MAATREGEL_TYPES = [
    "warmtepomp_lucht_water",
    "warmtepomp_water_water",
    "warmtepomp_hybride",
    "dakisolatie",
    "gevelisolatie",
    "vloerisolatie",
    "hr_glas",
    "zonneboiler",
    "eia_investering",
    "mia_vamil_investering",
    "dumava_maatregel",
]
MAATREGEL_STATUSES = [
    "orientatie",
    "gepland",
    "uitgevoerd",
    "aangevraagd",
    "goedgekeurd",
    "afgewezen",
]
REGELING_CODES = ["ISDE", "EIA", "MIA", "VAMIL", "DUMAVA"]


class MaatregelCreate(BaseModel):
    maatregel_type: Literal[
        "warmtepomp_lucht_water",
        "warmtepomp_water_water",
        "warmtepomp_hybride",
        "dakisolatie",
        "gevelisolatie",
        "vloerisolatie",
        "hr_glas",
        "zonneboiler",
        "eia_investering",
        "mia_vamil_investering",
        "dumava_maatregel",
    ]
    omschrijving: Optional[str] = None
    status: Optional[
        Literal[
            "orientatie",
            "gepland",
            "uitgevoerd",
            "aangevraagd",
            "goedgekeurd",
            "afgewezen",
        ]
    ] = None

    apparaat_merk: Optional[str] = Field(default=None, max_length=128)
    apparaat_typenummer: Optional[str] = Field(default=None, max_length=128)
    apparaat_meldcode: Optional[str] = Field(default=None, max_length=64)
    installateur_naam: Optional[str] = Field(default=None, max_length=255)
    installateur_kvk: Optional[str] = Field(default=None, max_length=32)
    installateur_gecertificeerd: Optional[bool] = None
    installatie_datum: Optional[date] = None
    offerte_datum: Optional[date] = None

    investering_bedrag: Optional[float] = Field(default=None, ge=0)
    regeling_code: Optional[Literal["ISDE", "EIA", "MIA", "VAMIL", "DUMAVA"]] = None


class MaatregelUpdate(BaseModel):
    omschrijving: Optional[str] = None
    status: Optional[
        Literal[
            "orientatie",
            "gepland",
            "uitgevoerd",
            "aangevraagd",
            "goedgekeurd",
            "afgewezen",
        ]
    ] = None
    apparaat_merk: Optional[str] = Field(default=None, max_length=128)
    apparaat_typenummer: Optional[str] = Field(default=None, max_length=128)
    apparaat_meldcode: Optional[str] = Field(default=None, max_length=64)
    installateur_naam: Optional[str] = Field(default=None, max_length=255)
    installateur_kvk: Optional[str] = Field(default=None, max_length=32)
    installateur_gecertificeerd: Optional[bool] = None
    installatie_datum: Optional[date] = None
    offerte_datum: Optional[date] = None
    investering_bedrag: Optional[float] = Field(default=None, ge=0)
    toegekende_subsidie: Optional[float] = Field(default=None, ge=0)
    regeling_code: Optional[Literal["ISDE", "EIA", "MIA", "VAMIL", "DUMAVA"]] = None


class MaatregelListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pand_id: UUID
    maatregel_type: str
    status: str
    regeling_code: Optional[str] = None
    deadline_indienen: Optional[date] = None
    deadline_type: Optional[str] = None
    deadline_status: Optional[str] = None
    investering_bedrag: Optional[float] = None
    geschatte_subsidie: Optional[float] = None
    toegekende_subsidie: Optional[float] = None
    document_count: int = 0
    documents_required: int = 0
    documents_uploaded: int = 0
    documents_verified: int = 0
    created_at: datetime


class MaatregelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pand_id: UUID
    created_by: UUID
    maatregel_type: str
    omschrijving: Optional[str] = None
    status: str
    regeling_code: Optional[str] = None

    apparaat_merk: Optional[str] = None
    apparaat_typenummer: Optional[str] = None
    apparaat_meldcode: Optional[str] = None
    installateur_naam: Optional[str] = None
    installateur_kvk: Optional[str] = None
    installateur_gecertificeerd: bool = False
    installatie_datum: Optional[date] = None
    offerte_datum: Optional[date] = None

    investering_bedrag: Optional[float] = None
    geschatte_subsidie: Optional[float] = None
    toegekende_subsidie: Optional[float] = None

    deadline_indienen: Optional[date] = None
    deadline_type: Optional[str] = None
    deadline_status: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class PandDetail(PandOut):
    maatregelen: List[MaatregelListItem] = []


# ---------------------------------------------------------------------------
# Documenten
# ---------------------------------------------------------------------------


class DocumentUploadRequest(BaseModel):
    document_type: Literal[
        "factuur",
        "betaalbewijs",
        "meldcode_bewijs",
        "foto_werkzaamheden",
        "inbedrijfstelling",
        "offerte",
        "kvk_uittreksel",
        "machtiging",
        "overig",
    ]
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(default="application/octet-stream", max_length=128)


class DocumentUploadResponse(BaseModel):
    upload_url: str
    document_id: UUID
    expires_in: int
    r2_key: str
    content_type: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    maatregel_id: UUID
    document_type: str
    bestandsnaam: str
    r2_key: str
    geupload_door: UUID
    geverifieerd_door_admin: bool
    created_at: datetime


class ChecklistItem(BaseModel):
    document_type: str
    label: str
    uitleg: Optional[str] = None
    verplicht: bool
    geupload: bool
    geverifieerd: bool
    document_id: Optional[UUID] = None
    bestandsnaam: Optional[str] = None


class ChecklistResponse(BaseModel):
    maatregel_id: UUID
    items: List[ChecklistItem]
    required_count: int
    uploaded_required_count: int
    missing_count: int
    compleet: bool


class PlanLimitError(BaseModel):
    detail: str
    plan: str
    limit: int
    current: int
