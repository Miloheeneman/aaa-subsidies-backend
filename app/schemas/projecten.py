"""Pydantic schemas for the projecten module (STAP 9)."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    DeadlineStatus,
    DeadlineTiming,
    EigenaarType,
    EnergielabelKlasse,
    MaatregelDocumentType,
    MaatregelStatus,
    MaatregelType,
    ProjectType,
    RegelingCode,
)


# ---------------------------------------------------------------------------
# Projecten
# ---------------------------------------------------------------------------


class ProjectBase(BaseModel):
    straat: str = Field(min_length=1, max_length=255)
    huisnummer: str = Field(min_length=1, max_length=32)
    postcode: str = Field(min_length=4, max_length=16)
    plaats: str = Field(min_length=1, max_length=128)
    bouwjaar: int = Field(ge=1500, le=2100)
    project_type: ProjectType
    eigenaar_type: EigenaarType


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    """All fields optional; only the fields you send get overwritten."""

    straat: Optional[str] = Field(default=None, min_length=1, max_length=255)
    huisnummer: Optional[str] = Field(default=None, min_length=1, max_length=32)
    postcode: Optional[str] = Field(default=None, min_length=4, max_length=16)
    plaats: Optional[str] = Field(default=None, min_length=1, max_length=128)
    bouwjaar: Optional[int] = Field(default=None, ge=1500, le=2100)
    project_type: Optional[ProjectType] = None
    eigenaar_type: Optional[EigenaarType] = None

    # AAA-Lex-only velden — worden door het backend stilletjes genegeerd
    # voor niet-admins (zie routes/projecten.py).
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


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organisation_id: UUID
    created_by: UUID

    straat: str
    huisnummer: str
    postcode: str
    plaats: str
    bouwjaar: int
    project_type: ProjectType
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


class ProjectListResponse(BaseModel):
    items: List[ProjectOut]
    totaal: int
    quota: "QuotaInfo"


class ProjectDetailResponse(ProjectOut):
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
    project_id: UUID
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
    """Eén regeling-match voor een project (zie projecten_service.SubsidieMatch)."""

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
    project_id: UUID
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


class EiaAanvraagCreate(BaseModel):
    """Payload voor de EIA intake-wizard (klant)."""

    investering_omschrijving: str = Field(min_length=1, max_length=8000)
    type_investering: Literal[
        "led",
        "warmtepomp_zakelijk",
        "zonnepanelen",
        "energiezuinige_installatie",
        "overig",
    ]
    investering_bedrag: float = Field(ge=2500)
    geplande_startdatum: Optional[date] = None
    heeft_offerte: bool = False
    offerte_datum: Optional[date] = None

    bedrijfsnaam: str = Field(min_length=1, max_length=255)
    kvk_nummer: str = Field(min_length=8, max_length=14)
    type_onderneming: Literal["ib", "bv_nv", "overig"]
    contactpersoon_naam: Optional[str] = Field(default=None, max_length=255)
    telefoon: Optional[str] = Field(default=None, max_length=32)

    @field_validator("kvk_nummer", mode="before")
    @classmethod
    def _normalize_kvk(cls, v: object) -> str:
        if v is None:
            raise ValueError("KvK-nummer is verplicht")
        digits = re.sub(r"\D", "", str(v))
        if len(digits) != 8:
            raise ValueError("KvK-nummer moet 8 cijfers zijn")
        return digits

    @model_validator(mode="after")
    def _offerte_datum(self) -> "EiaAanvraagCreate":
        if self.heeft_offerte and self.offerte_datum is None:
            raise ValueError("Vul de offertedatum in wanneer u al een offerte heeft")
        if not self.heeft_offerte:
            object.__setattr__(self, "offerte_datum", None)
        return self


class MiaVamilAanvraagCreate(BaseModel):
    """Payload voor de MIA + Vamil intake-wizard (klant; gecombineerd)."""

    investering_omschrijving: str = Field(min_length=1, max_length=8000)
    type_milieu_investering: Literal[
        "duurzame_warmte",
        "circulair_bouwen",
        "energieneutrale_gebouwen",
        "hernieuwbare_energie",
        "overig_milieu",
    ]
    milieulijst_categoriecode: Optional[str] = Field(
        default=None,
        max_length=64,
    )
    investering_bedrag: float = Field(ge=2500)
    geplande_startdatum: Optional[date] = None
    heeft_offerte: bool = False
    offerte_datum: Optional[date] = None

    bedrijfsnaam: str = Field(min_length=1, max_length=255)
    kvk_nummer: str = Field(min_length=8, max_length=14)
    type_onderneming: Literal["ib", "bv_nv", "overig"]
    contactpersoon_naam: Optional[str] = Field(default=None, max_length=255)
    telefoon: Optional[str] = Field(default=None, max_length=32)

    @field_validator("kvk_nummer", mode="before")
    @classmethod
    def _normalize_kvk_mia(cls, v: object) -> str:
        if v is None:
            raise ValueError("KvK-nummer is verplicht")
        digits = re.sub(r"\D", "", str(v))
        if len(digits) != 8:
            raise ValueError("KvK-nummer moet 8 cijfers zijn")
        return digits

    @field_validator("milieulijst_categoriecode", mode="before")
    @classmethod
    def _strip_milieulijst(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        t = str(v).strip()
        return t or None

    @model_validator(mode="after")
    def _offerte_datum_mia(self) -> "MiaVamilAanvraagCreate":
        if self.heeft_offerte and self.offerte_datum is None:
            raise ValueError("Vul de offertedatum in wanneer u al een offerte heeft")
        if not self.heeft_offerte:
            object.__setattr__(self, "offerte_datum", None)
        return self


_DUMAVA_ERKENDE_KEYS = frozenset(
    {
        "warmtepomp",
        "zonnepanelen",
        "dakisolatie",
        "gevelisolatie",
        "vloerisolatie",
    }
)


class DumavaWizardMaatregelIn(BaseModel):
    """Eén gekozen verduurzamingsonderdeel in de DUMAVA-wizard."""

    maatregel_key: Literal[
        "warmtepomp",
        "zonnepanelen",
        "dakisolatie",
        "gevelisolatie",
        "led_verlichting",
        "warmtenet",
        "vloerisolatie",
        "overig",
    ]
    beschrijving: str = Field(min_length=1, max_length=8000)
    investering_bedrag: float = Field(gt=0)


class DumavaAanvraagCreate(BaseModel):
    """Payload voor de DUMAVA intake-wizard (meerdere maatregelen op één project)."""

    organisatie_type: Literal[
        "zorg",
        "onderwijs",
        "sport",
        "gemeente",
        "overig_maatschappelijk",
    ]
    items: List[DumavaWizardMaatregelIn] = Field(min_length=2, max_length=16)
    oppervlakte_m2: float = Field(gt=0, le=1_000_000)
    bouwjaar: int = Field(ge=1500, le=2100)
    energielabel_huidig: Optional[
        Literal["A", "B", "C", "D", "E", "F", "G"]
    ] = None
    heeft_maatwerkadvies: bool = False
    contactpersoon_naam: str = Field(min_length=1, max_length=255)
    contact_functie: Optional[str] = Field(default=None, max_length=255)
    telefoon: str = Field(min_length=6, max_length=32)
    rvo_contact_gehad: bool = False

    @field_validator("telefoon", mode="before")
    @classmethod
    def _strip_telefoon(cls, v: object) -> str:
        if v is None:
            raise ValueError("Telefoonnummer is verplicht")
        t = str(v).strip()
        if len(t) < 6:
            raise ValueError("Telefoonnummer is te kort")
        return t

    @field_validator("contact_functie", mode="before")
    @classmethod
    def _strip_functie(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        t = str(v).strip()
        return t or None

    @model_validator(mode="after")
    def _dumava_items(self) -> "DumavaAanvraagCreate":
        keys = [i.maatregel_key for i in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Elke maatregel maximaal één keer kiezen")
        if not any(k in _DUMAVA_ERKENDE_KEYS for k in keys):
            raise ValueError(
                "Kies minimaal één erkende maatregel (bijv. warmtepomp, "
                "zonnepanelen of isolatie)"
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


ProjectListResponse.model_rebuild()
