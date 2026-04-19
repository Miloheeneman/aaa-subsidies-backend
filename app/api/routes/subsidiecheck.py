from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import RegelingConfig
from app.models.enums import RegelingCode, TypeAanvrager
from app.schemas.subsidiecheck import (
    RegelingResultaat,
    SubsidieCheckRequest,
    SubsidieCheckResponse,
)
from app.services.subsidy_matching import (
    REGELING_BESCHRIJVING,
    REGELING_NAAM,
    VEREISTE_DOCUMENTEN,
    check_applicability,
    deadline_info,
    estimate_subsidie,
)

router = APIRouter(prefix="/subsidiecheck", tags=["subsidiecheck"])


def _fee_bedrag(
    geschatte_subsidie: Optional[Decimal], fee_percentage: Optional[Decimal]
) -> Optional[Decimal]:
    if geschatte_subsidie is None or fee_percentage is None:
        return None
    return (geschatte_subsidie * fee_percentage / Decimal("100")).quantize(
        Decimal("0.01")
    )


@router.post(
    "/bereken",
    response_model=SubsidieCheckResponse,
    summary="Bereken passende subsidies (publiek, geen login vereist)",
)
def bereken(payload: SubsidieCheckRequest, db: DbSession) -> SubsidieCheckResponse:
    aanvrager = TypeAanvrager(payload.type_aanvrager)

    applic = check_applicability(
        type_aanvrager=aanvrager,
        maatregelen=payload.maatregelen,
        investering_bedrag=payload.investering_bedrag,
    )

    # Pull live fee percentages + actief flag from regelingen_config.
    configs = (
        db.execute(select(RegelingConfig)).scalars().all()
    )
    configs_by_code = {c.code: c for c in configs}

    resultaten: list[RegelingResultaat] = []
    totaal_subsidie = Decimal("0.00")
    totaal_klant = Decimal("0.00")

    ordered_codes = [
        RegelingCode.ISDE,
        RegelingCode.EIA,
        RegelingCode.MIA,
        RegelingCode.VAMIL,
        RegelingCode.DUMAVA,
    ]

    for code in ordered_codes:
        cfg = configs_by_code.get(code)
        actief = cfg.actief if cfg is not None else True
        fee_pct = cfg.fee_percentage if cfg is not None else None

        applies = applic[code] and actief

        geschatte: Optional[Decimal] = None
        fee: Optional[Decimal] = None
        klant: Optional[Decimal] = None

        if applies:
            geschatte = estimate_subsidie(code, payload.investering_bedrag)
            fee = _fee_bedrag(geschatte, fee_pct)
            if geschatte is not None:
                klant = (
                    geschatte - (fee or Decimal("0"))
                ).quantize(Decimal("0.01"))
                totaal_subsidie += geschatte
                totaal_klant += klant

        resultaten.append(
            RegelingResultaat(
                code=code.value,
                naam=REGELING_NAAM[code],
                van_toepassing=applies,
                geschatte_subsidie=geschatte,
                aaa_lex_fee=fee,
                klant_ontvangt=klant,
                deadline_info=(
                    deadline_info(code, offerte_beschikbaar=payload.offerte_beschikbaar)
                    if applies
                    else None
                ),
                vereiste_documenten=VEREISTE_DOCUMENTEN.get(code, []),
                toelichting=REGELING_BESCHRIJVING[code],
            )
        )

    waarschuwingen = _build_warnings(
        aanvrager=aanvrager,
        maatregelen=payload.maatregelen,
        offerte_beschikbaar=payload.offerte_beschikbaar,
        applic=applic,
    )

    if any(r.van_toepassing for r in resultaten):
        volgende_stap = (
            "Maak een account aan om uw aanvraag te starten. AAA-Lex "
            "beoordeelt uw dossier en dient het in bij RVO."
        )
    else:
        volgende_stap = (
            "Op basis van deze gegevens komt u niet direct in aanmerking "
            "voor standaard regelingen. Neem contact op met AAA-Lex voor "
            "persoonlijk advies."
        )

    return SubsidieCheckResponse(
        regelingen=resultaten,
        totaal_geschatte_subsidie=totaal_subsidie,
        totaal_klant_ontvangt=totaal_klant,
        waarschuwingen=waarschuwingen,
        volgende_stap=volgende_stap,
    )


def _build_warnings(
    *,
    aanvrager: TypeAanvrager,
    maatregelen: list[str],
    offerte_beschikbaar: bool,
    applic: dict[RegelingCode, bool],
) -> list[str]:
    warnings: list[str] = []

    if offerte_beschikbaar and (
        applic[RegelingCode.EIA] or applic[RegelingCode.MIA]
    ):
        warnings.append(
            "LET OP: EIA/MIA moet binnen 3 maanden na ondertekening van "
            "de offerte worden aangevraagd — daarna vervalt het recht."
        )

    if applic[RegelingCode.DUMAVA]:
        warnings.append(
            "DUMAVA: aanvragen moet vóór start uitvoering. Start de "
            "uitvoering niet voordat de aanvraag is ingediend."
        )

    if aanvrager == TypeAanvrager.particulier and "warmtepomp" in {
        m.lower() for m in maatregelen
    }:
        warnings.append(
            "Zonneboilers zijn voor particulieren niet meer subsidiabel "
            "via ISDE sinds 2024. Warmtepompen wél."
        )

    if not any(applic.values()):
        warnings.append(
            "Geen standaardregelingen direct van toepassing. AAA-Lex "
            "adviseert u graag persoonlijk over alternatieve routes."
        )

    return warnings
