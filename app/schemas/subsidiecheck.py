from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


TypeAanvragerStr = Literal[
    "particulier", "zakelijk", "vve", "maatschappelijk", "ondernemer"
]
MaatregelStr = Literal["warmtepomp", "isolatie", "energiesysteem", "meerdere"]
# Spec allows 'utiliteit' for step 3 even though the DB-backed AAA-Lex project
# only stores {woning, bedrijfspand, maatschappelijk}. The wizard is public
# and does not persist so we accept the extra option and map internally.
TypePandStr = Literal["woning", "bedrijfspand", "maatschappelijk", "utiliteit"]
EnergieLabelStr = Literal["A+++", "A++", "A+", "A", "B", "C", "D", "E", "F", "G"]


class SubsidieCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_aanvrager: TypeAanvragerStr
    maatregelen: list[MaatregelStr] = Field(min_length=1)
    type_pand: Optional[TypePandStr] = None
    bouwjaar: Optional[int] = Field(default=None, ge=1500, le=2100)
    energielabel: Optional[EnergieLabelStr] = None
    investering_bedrag: Optional[Decimal] = Field(default=None, ge=0)
    offerte_beschikbaar: bool = False
    gewenste_startdatum: Optional[date] = None
    postcode: Optional[str] = Field(default=None, max_length=16)


class RegelingResultaat(BaseModel):
    code: Literal["ISDE", "EIA", "MIA", "VAMIL", "DUMAVA"]
    naam: str
    van_toepassing: bool
    geschatte_subsidie: Optional[Decimal] = None
    aaa_lex_fee: Optional[Decimal] = None
    klant_ontvangt: Optional[Decimal] = None
    deadline_info: Optional[str] = None
    vereiste_documenten: list[str] = Field(default_factory=list)
    toelichting: str


class SubsidieCheckResponse(BaseModel):
    regelingen: list[RegelingResultaat]
    totaal_geschatte_subsidie: Decimal
    totaal_klant_ontvangt: Decimal
    waarschuwingen: list[str] = Field(default_factory=list)
    volgende_stap: str
