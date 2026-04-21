"""Deadline-engine voor de panden-module.

Berekent per maatregel de indien-deadline én een bijbehorend
``deadline_status`` (ok/waarschuwing/kritiek/verlopen) op basis van
regeling + data. Deze functies zijn pure (geen DB-side-effects); de
caller is verantwoordelijk voor ``db.commit()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from app.models.enums import (
    DeadlineStatus,
    MaatregelDeadlineType,
    MaatregelType,
    RegelingCode,
)

_ISDE_MAATREGELEN = frozenset(
    {
        MaatregelType.warmtepomp_lucht_water,
        MaatregelType.warmtepomp_water_water,
        MaatregelType.warmtepomp_hybride,
        MaatregelType.dakisolatie,
        MaatregelType.gevelisolatie,
        MaatregelType.vloerisolatie,
        MaatregelType.hr_glas,
        MaatregelType.zonneboiler,
    }
)

_EIA_MIA_MAATREGELEN = frozenset(
    {
        MaatregelType.eia_investering,
        MaatregelType.mia_vamil_investering,
    }
)


def infer_regeling(maatregel_type: MaatregelType) -> Optional[RegelingCode]:
    """Afleiden van de default regeling op basis van maatregel-type."""
    if maatregel_type in _ISDE_MAATREGELEN:
        return RegelingCode.ISDE
    if maatregel_type == MaatregelType.eia_investering:
        return RegelingCode.EIA
    if maatregel_type == MaatregelType.mia_vamil_investering:
        return RegelingCode.MIA
    if maatregel_type == MaatregelType.dumava_maatregel:
        return RegelingCode.DUMAVA
    return None


@dataclass(frozen=True)
class DeadlineInfo:
    deadline_indienen: Optional[date]
    deadline_type: Optional[MaatregelDeadlineType]
    deadline_status: Optional[DeadlineStatus]


def _status_from_days(days_until: Optional[int]) -> Optional[DeadlineStatus]:
    if days_until is None:
        return None
    if days_until < 0:
        return DeadlineStatus.verlopen
    if days_until < 30:
        return DeadlineStatus.kritiek
    if days_until <= 60:
        return DeadlineStatus.waarschuwing
    return DeadlineStatus.ok


def calculate_deadline(
    *,
    maatregel_type: MaatregelType,
    regeling_code: Optional[RegelingCode],
    installatie_datum: Optional[date],
    offerte_datum: Optional[date],
    today: Optional[date] = None,
) -> DeadlineInfo:
    """Bereken deadline + status voor één maatregel.

    * **ISDE** → ``installatie_datum + 24 maanden`` (~ 730 dagen) als
      ``na_installatie``-deadline. Zonder installatiedatum nog
      geen deadline — klant heeft dan nog niets geïnstalleerd.
    * **EIA / MIA / Vamil** → ``offerte_datum + 3 maanden`` (~ 90 dagen)
      als ``voor_offerte``-deadline. Zonder offertedatum vallen we
      terug op ``vandaag + 90 dagen`` zodat de klant gealarmeerd
      wordt zodra hij daadwerkelijk een offerte krijgt.
    * **DUMAVA** → geen automatische deadline. Status blijft ``None``.
    """

    today = today or date.today()
    regeling = regeling_code or infer_regeling(maatregel_type)

    deadline_date: Optional[date] = None
    deadline_type: Optional[MaatregelDeadlineType] = None

    if regeling == RegelingCode.ISDE:
        if installatie_datum is not None:
            deadline_date = installatie_datum + timedelta(days=730)
            deadline_type = MaatregelDeadlineType.na_installatie
    elif regeling in (RegelingCode.EIA, RegelingCode.MIA, RegelingCode.VAMIL):
        base = offerte_datum or today
        deadline_date = base + timedelta(days=90)
        deadline_type = MaatregelDeadlineType.voor_offerte
    elif regeling == RegelingCode.DUMAVA:
        deadline_date = None
        deadline_type = None

    if deadline_date is None:
        return DeadlineInfo(
            deadline_indienen=None,
            deadline_type=deadline_type,
            deadline_status=None,
        )

    days_until = (deadline_date - today).days
    status = _status_from_days(days_until)

    return DeadlineInfo(
        deadline_indienen=deadline_date,
        deadline_type=deadline_type,
        deadline_status=status,
    )


def apply_deadline_to(maatregel) -> None:
    """In-place updaten van een ``Maatregel`` ORM-instance.

    Caller schrijft de wijziging in de DB via ``db.commit()``.
    """
    info = calculate_deadline(
        maatregel_type=maatregel.maatregel_type,
        regeling_code=maatregel.regeling_code,
        installatie_datum=maatregel.installatie_datum,
        offerte_datum=maatregel.offerte_datum,
    )
    maatregel.deadline_indienen = info.deadline_indienen
    maatregel.deadline_type = info.deadline_type
    maatregel.deadline_status = info.deadline_status


# Eenvoudige schatting van toegekend subsidiebedrag op basis van
# investeringsbedrag + regeling. Niet bedoeld als RVO-simulatie — de
# frontend toont dit expliciet als "indicatief".
_ESTIMATE_PCT = {
    RegelingCode.ISDE: 0.30,
    RegelingCode.EIA: 0.1365,  # 45,5% fiscaal, netto ~13,65%
    RegelingCode.MIA: 0.135,  # ~45% MIA -> ~13,5% netto
    RegelingCode.VAMIL: 0.02,  # liquiditeitsvoordeel indicatief
    RegelingCode.DUMAVA: 0.30,
}


def estimate_subsidie(
    regeling: Optional[RegelingCode],
    investering_bedrag: Optional[float],
) -> Optional[float]:
    if regeling is None or investering_bedrag is None or investering_bedrag <= 0:
        return None
    pct = _ESTIMATE_PCT.get(regeling)
    if pct is None:
        return None
    return round(float(investering_bedrag) * pct, 2)
