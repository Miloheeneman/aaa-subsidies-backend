from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


EnergieLabel = Literal["A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]
TypePand = Literal["woning", "bedrijfspand", "maatschappelijk"]


class AanbevolenMaatregel(BaseModel):
    """One recommended measure from the AAA-Lex field report."""

    naam: str = Field(description="Bijv. 'Warmtepomp lucht/water 10 kW'")
    categorie: Literal[
        "warmtepomp", "isolatie", "energiesysteem", "overig"
    ] = Field(description="Matching category for subsidy logic")
    geschatte_kosten: Optional[Decimal] = Field(default=None, ge=0)
    toelichting: Optional[str] = None


class AAALexProjectCreate(BaseModel):
    external_reference: Optional[str] = Field(default=None, max_length=128)
    organisation_id: Optional[UUID] = None

    pandadres: str = Field(min_length=1, max_length=512)
    postcode: str = Field(min_length=1, max_length=16)
    plaats: str = Field(min_length=1, max_length=128)
    bouwjaar: Optional[int] = Field(default=None, ge=1500, le=2100)
    huidig_energielabel: Optional[EnergieLabel] = None
    nieuw_energielabel: Optional[EnergieLabel] = None
    type_pand: Optional[TypePand] = None
    oppervlakte_m2: Optional[Decimal] = Field(default=None, ge=0)
    dakoppervlakte_m2: Optional[Decimal] = Field(default=None, ge=0)
    geveloppervlakte_m2: Optional[Decimal] = Field(default=None, ge=0)

    aanbevolen_maatregelen: Optional[list[AanbevolenMaatregel]] = None
    geschatte_investering: Optional[Decimal] = Field(default=None, ge=0)
    geschatte_co2_besparing: Optional[Decimal] = Field(default=None, ge=0)

    ingevoerd_door: Optional[str] = Field(default=None, max_length=128)
    notities: Optional[str] = None


class MatchedSubsidie(BaseModel):
    regeling: str
    naam: str
    fee_percentage: Decimal
    geschatte_subsidie: Optional[Decimal] = None
    aaa_lex_fee_bedrag: Optional[Decimal] = None
    deadline_type: Optional[str] = None
    toelichting: Optional[str] = None
    aanvraag_id: Optional[UUID] = None


class AAALexProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_reference: Optional[str] = None
    organisation_id: Optional[UUID] = None
    aanvraag_id: Optional[UUID] = None

    pandadres: str
    postcode: str
    plaats: str
    bouwjaar: Optional[int] = None
    huidig_energielabel: Optional[str] = None
    nieuw_energielabel: Optional[str] = None
    type_pand: Optional[str] = None
    oppervlakte_m2: Optional[Decimal] = None
    dakoppervlakte_m2: Optional[Decimal] = None
    geveloppervlakte_m2: Optional[Decimal] = None

    aanbevolen_maatregelen: Optional[list[dict[str, Any]]] = None
    geschatte_investering: Optional[Decimal] = None
    geschatte_co2_besparing: Optional[Decimal] = None

    ingevoerd_door: Optional[str] = None
    notities: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class AAALexProjectCreateResponse(BaseModel):
    project: AAALexProjectOut
    matched_subsidies: list[MatchedSubsidie]
    total_geschatte_subsidie: Optional[Decimal] = None
    client_notified: bool
