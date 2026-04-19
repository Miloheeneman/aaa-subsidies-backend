"""Subsidy matching logic.

Given an AAA-Lex measurement or a public subsidiecheck wizard input,
determine which Dutch subsidy regelingen apply and estimate the potential
subsidy amount per regeling.

Rules are derived from the specification:

- ISDE        : particulieren + zakelijke verhuurders; warmtepomp / isolatie
- EIA         : ondernemers / bedrijven; min €2.500; maatregel op Energielijst
- MIA + Vamil : ondernemers / bedrijven; min €2.500; altijd samen
- DUMAVA      : maatschappelijk vastgoed; tot 30% subsidiabele kosten

These estimates are intentionally conservative and indicative. Actual
granted amounts depend on RVO review and the exact measures.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from app.models.enums import (
    DeadlineType,
    DocumentType,
    Maatregel,
    RegelingCode,
    TypeAanvrager,
)

# ---------------------------------------------------------------------------
# Indicative subsidy / benefit percentages used for estimation only.
# These are not authoritative and are only used to populate
# "geschatte_subsidie" for the client.
# ---------------------------------------------------------------------------
ISDE_ESTIMATE_PCT = Decimal("0.25")   # ~25% gemiddeld over warmtepomp / isolatie
EIA_ESTIMATE_PCT = Decimal("0.455")   # 45,5% aftrek (fiscaal voordeel)
MIA_ESTIMATE_PCT = Decimal("0.36")    # midden van 27-45% range
VAMIL_ESTIMATE_PCT = Decimal("0.03")  # geschatte liquiditeitswaarde
DUMAVA_ESTIMATE_PCT = Decimal("0.30")  # tot 30%

EIA_MIA_MIN_INVESTERING = Decimal("2500")


@dataclass(frozen=True)
class MatchedRegeling:
    code: RegelingCode
    naam: str
    maatregel: Maatregel
    type_aanvrager: TypeAanvrager
    geschatte_subsidie: Optional[Decimal]
    deadline_type: Optional[DeadlineType]
    toelichting: str


TYPE_PAND_TO_AANVRAGER: dict[str, TypeAanvrager] = {
    "woning": TypeAanvrager.particulier,
    "bedrijfspand": TypeAanvrager.ondernemer,
    # 'utiliteit' = niet-woninggebouw, gedraagt zich als ondernemerspand
    "utiliteit": TypeAanvrager.ondernemer,
    "maatschappelijk": TypeAanvrager.maatschappelijk,
}


# Required document checklists per regeling (from the project spec).
VEREISTE_DOCUMENTEN: dict[RegelingCode, list[str]] = {
    RegelingCode.ISDE: [
        "Offerte",
        "Factuur",
        "Betalingsbewijs",
        "Foto installatie",
        "Werkbon (gecertificeerde installateur)",
        "Energielabel",
    ],
    RegelingCode.EIA: [
        "Ondertekende offerte",
        "KvK uittreksel",
        "Technische specificaties",
        "Energielijst referentie (RVO)",
    ],
    RegelingCode.MIA: [
        "Ondertekende offerte",
        "KvK uittreksel",
        "Technische specificaties",
        "Milieulijst referentie (RVO)",
    ],
    RegelingCode.VAMIL: [
        "Ondertekende offerte",
        "KvK uittreksel",
        "Technische specificaties",
        "Milieulijst referentie (RVO)",
    ],
    RegelingCode.DUMAVA: [
        "Maatwerkadvies of energie-audit",
        "Offertes",
        "Begroting",
        "Foto voor aanvang",
        "Facturen",
        "Foto na oplevering",
    ],
}


REGELING_NAAM: dict[RegelingCode, str] = {
    RegelingCode.ISDE: "ISDE",
    RegelingCode.EIA: "EIA",
    RegelingCode.MIA: "MIA",
    RegelingCode.VAMIL: "Vamil",
    RegelingCode.DUMAVA: "DUMAVA",
}


REGELING_BESCHRIJVING: dict[RegelingCode, str] = {
    RegelingCode.ISDE: (
        "Investeringssubsidie Duurzame Energie voor particulieren en "
        "zakelijke verhuurders. Voor warmtepomp en isolatie. Aanvragen "
        "via RVO na installatie."
    ),
    RegelingCode.EIA: (
        "Energie-investeringsaftrek: 45,5% fiscaal voordeel over de "
        "investering. KRITIEK: aanvragen binnen 3 maanden na "
        "ondertekening offerte."
    ),
    RegelingCode.MIA: (
        "Milieu-investeringsaftrek: 27-45% aftrek afhankelijk van "
        "categorie. Altijd combineren met Vamil. 3 maanden deadline."
    ),
    RegelingCode.VAMIL: (
        "Willekeurige afschrijving milieu-investeringen. 75% van de "
        "investering willekeurig afschrijven voor liquiditeitsvoordeel. "
        "Altijd samen met MIA."
    ),
    RegelingCode.DUMAVA: (
        "Subsidie Duurzaam Maatschappelijk Vastgoed. Tot 30% subsidie "
        "voor verduurzaming van maatschappelijk vastgoed. Minimaal 2 "
        "maatregelen waarvan 1 erkend. Aanvragen VOOR start uitvoering."
    ),
}


# Structured document checklist per regeling (typed DocumentType + label).
# Used by GET /aanvragen/{id}/documenten to produce a full checklist.
DOCUMENT_LABELS: dict[DocumentType, str] = {
    DocumentType.offerte: "Offerte",
    DocumentType.factuur: "Factuur",
    DocumentType.betalingsbewijs: "Betalingsbewijs",
    DocumentType.foto_installatie: "Foto installatie",
    DocumentType.werkbon: "Werkbon (gecertificeerde installateur)",
    DocumentType.energielabel: "Energielabel",
    DocumentType.kvk_uittreksel: "KvK uittreksel",
    DocumentType.technische_specs: "Technische specificaties",
    DocumentType.energielijst_bewijs: "Energielijst referentie (RVO)",
    DocumentType.milieulijst_bewijs: "Milieulijst referentie (RVO)",
    DocumentType.maatwerkadvies: "Maatwerkadvies of energie-audit",
    DocumentType.begroting: "Begroting",
    DocumentType.foto_voor: "Foto voor aanvang",
    DocumentType.foto_na: "Foto na oplevering",
}


DOCUMENT_CHECKLIST: dict[RegelingCode, list[DocumentType]] = {
    RegelingCode.ISDE: [
        DocumentType.offerte,
        DocumentType.factuur,
        DocumentType.betalingsbewijs,
        DocumentType.foto_installatie,
        DocumentType.werkbon,
        DocumentType.energielabel,
    ],
    RegelingCode.EIA: [
        DocumentType.offerte,
        DocumentType.kvk_uittreksel,
        DocumentType.technische_specs,
        DocumentType.energielijst_bewijs,
    ],
    RegelingCode.MIA: [
        DocumentType.offerte,
        DocumentType.kvk_uittreksel,
        DocumentType.technische_specs,
        DocumentType.milieulijst_bewijs,
    ],
    RegelingCode.VAMIL: [
        DocumentType.offerte,
        DocumentType.kvk_uittreksel,
        DocumentType.technische_specs,
        DocumentType.milieulijst_bewijs,
    ],
    RegelingCode.DUMAVA: [
        DocumentType.maatwerkadvies,
        DocumentType.offerte,
        DocumentType.begroting,
        DocumentType.foto_voor,
        DocumentType.factuur,
        DocumentType.foto_na,
    ],
}


def document_checklist_for(
    regeling: RegelingCode, type_aanvrager: TypeAanvrager
) -> list[DocumentType]:
    """Return the required document types for a given regeling + aanvrager.

    `type_aanvrager` is currently kept as a parameter for future refinements
    (for example: particulier-only vs zakelijk variants), but today the
    checklist depends only on the regeling itself.
    """
    # type_aanvrager unused for now; reserved for future per-aanvrager
    # refinements. Kept in the signature for API stability.
    del type_aanvrager
    return list(DOCUMENT_CHECKLIST[regeling])


# Approximate subsidy percentages used purely for estimation in the wizard
# when no per-category breakdown is provided.
REGELING_ESTIMATE_PCT: dict[RegelingCode, Decimal] = {
    RegelingCode.ISDE: ISDE_ESTIMATE_PCT,
    RegelingCode.EIA: EIA_ESTIMATE_PCT,
    RegelingCode.MIA: MIA_ESTIMATE_PCT,
    RegelingCode.VAMIL: VAMIL_ESTIMATE_PCT,
    RegelingCode.DUMAVA: DUMAVA_ESTIMATE_PCT,
}


def infer_type_aanvrager(type_pand: Optional[str]) -> TypeAanvrager:
    if type_pand and type_pand in TYPE_PAND_TO_AANVRAGER:
        return TYPE_PAND_TO_AANVRAGER[type_pand]
    return TypeAanvrager.particulier


def _category_totals(
    maatregelen: Iterable[dict] | None,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (warmtepomp_eur, isolatie_eur, energiesysteem_eur, overig_eur)."""
    wp = Decimal("0")
    iso = Decimal("0")
    energy = Decimal("0")
    overig = Decimal("0")
    for m in maatregelen or ():
        if not isinstance(m, dict):
            continue
        kosten_raw = m.get("geschatte_kosten") or 0
        try:
            kosten = Decimal(str(kosten_raw))
        except Exception:
            kosten = Decimal("0")
        cat = (m.get("categorie") or "").lower()
        if cat == "warmtepomp":
            wp += kosten
        elif cat == "isolatie":
            iso += kosten
        elif cat == "energiesysteem":
            energy += kosten
        else:
            overig += kosten
    return wp, iso, energy, overig


def _primary_maatregel(
    wp: Decimal, iso: Decimal, energy: Decimal
) -> Maatregel:
    categories = {
        Maatregel.warmtepomp: wp,
        Maatregel.isolatie: iso,
        Maatregel.energiesysteem: energy,
    }
    non_zero = [(k, v) for k, v in categories.items() if v > 0]
    if not non_zero:
        return Maatregel.meerdere
    if len(non_zero) >= 2:
        return Maatregel.meerdere
    return non_zero[0][0]


def match_subsidies(
    *,
    type_pand: Optional[str],
    aanbevolen_maatregelen: Optional[list[dict]],
    geschatte_investering: Optional[Decimal],
) -> tuple[TypeAanvrager, list[MatchedRegeling]]:
    """Return (type_aanvrager, matched) list of regelingen that apply."""
    aanvrager = infer_type_aanvrager(type_pand)

    wp, iso, energy, _overig = _category_totals(aanbevolen_maatregelen)
    total_measures_cost = wp + iso + energy
    # Fall back to provided total if individual measures have no costs.
    if total_measures_cost == 0 and geschatte_investering is not None:
        total_measures_cost = Decimal(str(geschatte_investering))

    primary = _primary_maatregel(wp, iso, energy)

    matched: list[MatchedRegeling] = []

    # ----- ISDE -----
    isde_applies = aanvrager in (
        TypeAanvrager.particulier,
        TypeAanvrager.zakelijk,
        TypeAanvrager.vve,
    ) and (wp > 0 or iso > 0)
    if isde_applies:
        isde_basis = wp + iso
        matched.append(
            MatchedRegeling(
                code=RegelingCode.ISDE,
                naam="ISDE",
                maatregel=primary,
                type_aanvrager=aanvrager,
                geschatte_subsidie=(isde_basis * ISDE_ESTIMATE_PCT).quantize(Decimal("0.01")),
                deadline_type=None,
                toelichting=(
                    "Van toepassing voor particulieren en zakelijke verhuurders "
                    "voor warmtepomp en/of isolatie. Aanvragen via RVO na installatie."
                ),
            )
        )

    # ----- EIA / MIA / Vamil (ondernemers) -----
    ondernemer = aanvrager == TypeAanvrager.ondernemer
    min_investering_gehaald = total_measures_cost >= EIA_MIA_MIN_INVESTERING
    if ondernemer and min_investering_gehaald:
        matched.append(
            MatchedRegeling(
                code=RegelingCode.EIA,
                naam="EIA",
                maatregel=primary,
                type_aanvrager=aanvrager,
                geschatte_subsidie=(
                    total_measures_cost * EIA_ESTIMATE_PCT
                ).quantize(Decimal("0.01")),
                deadline_type=DeadlineType.EIA_3maanden,
                toelichting=(
                    "45,5% aftrek van investering. KRITIEK: aanvragen binnen "
                    "3 maanden na ondertekening offerte."
                ),
            )
        )
        matched.append(
            MatchedRegeling(
                code=RegelingCode.MIA,
                naam="MIA",
                maatregel=primary,
                type_aanvrager=aanvrager,
                geschatte_subsidie=(
                    total_measures_cost * MIA_ESTIMATE_PCT
                ).quantize(Decimal("0.01")),
                deadline_type=DeadlineType.EIA_3maanden,
                toelichting=(
                    "27-45% aftrek voor milieu-investeringen. Altijd samen "
                    "met Vamil aanvragen. 3 maanden deadline."
                ),
            )
        )
        matched.append(
            MatchedRegeling(
                code=RegelingCode.VAMIL,
                naam="Vamil",
                maatregel=primary,
                type_aanvrager=aanvrager,
                geschatte_subsidie=(
                    total_measures_cost * VAMIL_ESTIMATE_PCT
                ).quantize(Decimal("0.01")),
                deadline_type=DeadlineType.EIA_3maanden,
                toelichting=(
                    "Willekeurige afschrijving (liquiditeitsvoordeel). "
                    "Altijd samen met MIA aanvragen."
                ),
            )
        )

    # ----- DUMAVA -----
    if aanvrager == TypeAanvrager.maatschappelijk:
        matched.append(
            MatchedRegeling(
                code=RegelingCode.DUMAVA,
                naam="DUMAVA",
                maatregel=Maatregel.meerdere,
                type_aanvrager=aanvrager,
                geschatte_subsidie=(
                    total_measures_cost * DUMAVA_ESTIMATE_PCT
                ).quantize(Decimal("0.01")),
                deadline_type=DeadlineType.DUMAVA_2jaar,
                toelichting=(
                    "Tot 30% subsidie voor verduurzaming maatschappelijk "
                    "vastgoed. Minimaal 2 maatregelen waarvan 1 erkend. "
                    "Aanvragen VOOR start uitvoering."
                ),
            )
        )

    return aanvrager, matched


# ---------------------------------------------------------------------------
# Wizard-oriented applicability check
# ---------------------------------------------------------------------------

def _has_wp_or_isolatie(maatregelen: list[str]) -> bool:
    s = {m.lower() for m in maatregelen}
    return "warmtepomp" in s or "isolatie" in s or "meerdere" in s


def check_applicability(
    *,
    type_aanvrager: TypeAanvrager,
    maatregelen: list[str],
    investering_bedrag: Optional[Decimal],
) -> dict[RegelingCode, bool]:
    """Return which regelingen apply given the wizard input.

    Rules (exactly as specified):

    - ISDE   : particulier / zakelijk + (warmtepomp of isolatie)
    - EIA    : ondernemer + investering >= €2.500
    - MIA    : ondernemer + investering >= €2.500
    - VAMIL  : if MIA applies (always combined)
    - DUMAVA : maatschappelijk
    """
    invest = (
        Decimal(str(investering_bedrag))
        if investering_bedrag is not None
        else Decimal("0")
    )
    meets_min = invest >= EIA_MIA_MIN_INVESTERING

    isde = type_aanvrager in (
        TypeAanvrager.particulier,
        TypeAanvrager.zakelijk,
        TypeAanvrager.vve,
    ) and _has_wp_or_isolatie(maatregelen)

    ondernemer = type_aanvrager == TypeAanvrager.ondernemer
    eia = ondernemer and meets_min
    mia = ondernemer and meets_min
    vamil = mia
    dumava = type_aanvrager == TypeAanvrager.maatschappelijk

    return {
        RegelingCode.ISDE: isde,
        RegelingCode.EIA: eia,
        RegelingCode.MIA: mia,
        RegelingCode.VAMIL: vamil,
        RegelingCode.DUMAVA: dumava,
    }


def estimate_subsidie(
    code: RegelingCode, investering_bedrag: Optional[Decimal]
) -> Optional[Decimal]:
    if investering_bedrag is None or investering_bedrag <= 0:
        return None
    pct = REGELING_ESTIMATE_PCT[code]
    return (Decimal(str(investering_bedrag)) * pct).quantize(Decimal("0.01"))


def deadline_info(code: RegelingCode, *, offerte_beschikbaar: bool) -> Optional[str]:
    if code == RegelingCode.EIA and offerte_beschikbaar:
        return (
            "Aanvragen binnen 3 maanden na ondertekening offerte — daarna "
            "vervalt het recht op EIA volledig."
        )
    if code == RegelingCode.MIA and offerte_beschikbaar:
        return (
            "Aanvragen binnen 3 maanden na ondertekening offerte (samen "
            "met Vamil)."
        )
    if code == RegelingCode.VAMIL and offerte_beschikbaar:
        return "Samen met MIA aanvragen — 3 maanden na offerte."
    if code == RegelingCode.DUMAVA:
        return "Aanvragen moet vóór start uitvoering. Realisatie binnen 2 jaar."
    return None
