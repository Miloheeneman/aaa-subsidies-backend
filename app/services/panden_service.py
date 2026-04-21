"""Domain services for the panden module (STAP 9).

Three concerns live here:

* **Deadline engine** — compute ``deadline_indienen``, ``deadline_type``
  and ``deadline_status`` for a :class:`~app.models.maatregel.Maatregel`
  from the user-supplied dates. Runs on every POST/PUT so list pages
  don't need to derive them per request.

* **Document checklist** — declarative mapping of ``MaatregelType`` →
  the list of ``MaatregelDocumentType``'s that are required (or
  recommended) before an aanvraag can be submitted to RVO.

* **Regeling inference** — the platform infers a likely ``regeling_code``
  from ``MaatregelType`` so the UI can show the right deadline /
  checklist copy even before an admin confirms the regeling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Sequence

from app.models.enums import (
    DeadlineStatus,
    DeadlineTiming,
    MaatregelDocumentType,
    MaatregelType,
    RegelingCode,
)


# ---------------------------------------------------------------------------
# Regeling inference
# ---------------------------------------------------------------------------


_MAATREGEL_TO_REGELING: dict[MaatregelType, RegelingCode] = {
    MaatregelType.warmtepomp_lucht_water: RegelingCode.ISDE,
    MaatregelType.warmtepomp_water_water: RegelingCode.ISDE,
    MaatregelType.warmtepomp_hybride: RegelingCode.ISDE,
    MaatregelType.dakisolatie: RegelingCode.ISDE,
    MaatregelType.gevelisolatie: RegelingCode.ISDE,
    MaatregelType.vloerisolatie: RegelingCode.ISDE,
    MaatregelType.hr_glas: RegelingCode.ISDE,
    MaatregelType.zonneboiler: RegelingCode.ISDE,
    MaatregelType.eia_investering: RegelingCode.EIA,
    MaatregelType.mia_vamil_investering: RegelingCode.MIA,
    MaatregelType.dumava_maatregel: RegelingCode.DUMAVA,
}


def infer_regeling(maatregel_type: MaatregelType) -> RegelingCode:
    """Default regeling for a measure type.

    Used only when ``regeling_code`` is not explicitly set on the
    maatregel. The DUMAVA / MIA-Vamil heuristics are deliberately
    conservative — an admin can always override via PUT.
    """
    return _MAATREGEL_TO_REGELING[maatregel_type]


# ---------------------------------------------------------------------------
# Deadline engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeadlineResult:
    deadline_indienen: Optional[date]
    deadline_type: Optional[DeadlineTiming]
    deadline_status: Optional[DeadlineStatus]


_ISDE_DURATION_MONTHS = 24
_EIA_MIA_VAMIL_DAYS = 90  # ~3 maanden; RVO hanteert 3 kalendermaanden


def _add_months(d: date, months: int) -> date:
    """Return ``d`` + ``months`` without pulling in python-dateutil.

    Caps on month-end to avoid ValueError on e.g. 31-jan + 1 maand.
    """
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    # clamp day to the last day of the target month
    if month == 12:
        last_day = 31
    else:
        next_month_first = date(year, month + 1, 1)
        last_day = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _status_for_delta(days_until: int) -> DeadlineStatus:
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
    installatie_datum: Optional[date],
    offerte_datum: Optional[date],
    regeling_code: Optional[RegelingCode] = None,
    today: Optional[date] = None,
) -> DeadlineResult:
    """Compute the indienings-deadline for one maatregel.

    Rules (per spec):

    * ISDE → deadline = ``installatie_datum`` + 24 maanden, timing
      ``na_installatie``.
    * EIA / MIA / VAMIL → deadline = ``offerte_datum`` + 3 maanden,
      timing ``voor_offerte`` (the UI warns that the signature on the
      offerte has to be *after* the RVO aanvraag).
    * DUMAVA → no automatic deadline.

    Returns ``DeadlineResult(None, None, None)`` if the required input
    date is missing (e.g. ISDE without installatie_datum) so the UI can
    show the raw measure without a misleading badge.
    """
    today = today or date.today()
    regeling = regeling_code or infer_regeling(maatregel_type)

    if regeling == RegelingCode.ISDE:
        if installatie_datum is None:
            return DeadlineResult(None, None, None)
        deadline = _add_months(installatie_datum, _ISDE_DURATION_MONTHS)
        return DeadlineResult(
            deadline,
            DeadlineTiming.na_installatie,
            _status_for_delta((deadline - today).days),
        )

    if regeling in (RegelingCode.EIA, RegelingCode.MIA, RegelingCode.VAMIL):
        if offerte_datum is None:
            return DeadlineResult(None, None, None)
        deadline = offerte_datum + timedelta(days=_EIA_MIA_VAMIL_DAYS)
        return DeadlineResult(
            deadline,
            DeadlineTiming.voor_offerte,
            _status_for_delta((deadline - today).days),
        )

    # DUMAVA + any future regelingen without a fixed client-side deadline.
    return DeadlineResult(None, None, None)


# ---------------------------------------------------------------------------
# Document checklist
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChecklistItem:
    document_type: MaatregelDocumentType
    label: str
    uitleg: str
    verplicht: bool


_WARMTEPOMP_TYPES = {
    MaatregelType.warmtepomp_lucht_water,
    MaatregelType.warmtepomp_water_water,
    MaatregelType.warmtepomp_hybride,
}
_ZONNEBOILER_TYPES = {
    MaatregelType.zonneboiler,
}
_ISOLATIE_TYPES = {
    MaatregelType.dakisolatie,
    MaatregelType.gevelisolatie,
    MaatregelType.vloerisolatie,
    MaatregelType.hr_glas,
}

# Labels + uitleg voor de UI — wordt 1-op-1 getoond op de dossier pagina.
_DOC_LABELS: dict[MaatregelDocumentType, tuple[str, str]] = {
    MaatregelDocumentType.factuur: (
        "Factuur",
        "Factuur met installatiedatum en meldcode.",
    ),
    MaatregelDocumentType.betaalbewijs: (
        "Betaalbewijs",
        "Bankafschrift of betaalbevestiging van de factuur.",
    ),
    MaatregelDocumentType.meldcode_bewijs: (
        "Meldcode",
        "Bewijs van de meldcode (staat op de factuur of technische specificatie).",
    ),
    MaatregelDocumentType.foto_werkzaamheden: (
        "Foto tijdens werkzaamheden",
        "Naam, merk en dikte van het isolatiemateriaal moeten zichtbaar zijn.",
    ),
    MaatregelDocumentType.inbedrijfstelling: (
        "Inbedrijfstellingsformulier",
        "Ingevuld door de monteur bij oplevering.",
    ),
    MaatregelDocumentType.offerte: (
        "Offerte",
        "Getekende offerte met datum en specificatie van de investering.",
    ),
    MaatregelDocumentType.kvk_uittreksel: (
        "KvK-uittreksel",
        "Recent uittreksel van de Kamer van Koophandel (< 3 maanden oud).",
    ),
    MaatregelDocumentType.machtiging: (
        "Machtiging namens klant",
        "Machtigingsformulier waarmee AAA-Lex als intermediair kan indienen.",
    ),
    MaatregelDocumentType.overig: (
        "Overig",
        "Aanvullende documenten die AAA-Lex heeft opgevraagd.",
    ),
}


def _mk(
    doc: MaatregelDocumentType, *, verplicht: bool = True
) -> ChecklistItem:
    label, uitleg = _DOC_LABELS[doc]
    return ChecklistItem(
        document_type=doc, label=label, uitleg=uitleg, verplicht=verplicht
    )


def get_required_documents(
    maatregel_type: MaatregelType,
) -> List[ChecklistItem]:
    """Return the ordered checklist for one maatregel type."""
    if maatregel_type in _WARMTEPOMP_TYPES | _ZONNEBOILER_TYPES:
        return [
            _mk(MaatregelDocumentType.factuur),
            _mk(MaatregelDocumentType.betaalbewijs),
            _mk(MaatregelDocumentType.meldcode_bewijs),
            _mk(MaatregelDocumentType.inbedrijfstelling),
            _mk(MaatregelDocumentType.offerte, verplicht=False),
        ]
    if maatregel_type in _ISOLATIE_TYPES:
        return [
            _mk(MaatregelDocumentType.factuur),
            _mk(MaatregelDocumentType.betaalbewijs),
            _mk(MaatregelDocumentType.meldcode_bewijs),
            _mk(MaatregelDocumentType.foto_werkzaamheden),
        ]
    if maatregel_type in (
        MaatregelType.eia_investering,
        MaatregelType.mia_vamil_investering,
    ):
        return [
            _mk(MaatregelDocumentType.offerte),
            _mk(MaatregelDocumentType.kvk_uittreksel),
            _mk(MaatregelDocumentType.factuur),
            _mk(MaatregelDocumentType.betaalbewijs),
        ]
    if maatregel_type == MaatregelType.dumava_maatregel:
        return [
            _mk(MaatregelDocumentType.offerte),
            _mk(MaatregelDocumentType.factuur),
            _mk(MaatregelDocumentType.betaalbewijs),
            _mk(MaatregelDocumentType.machtiging),
        ]
    return []


def required_document_types(
    maatregel_type: MaatregelType,
) -> Sequence[MaatregelDocumentType]:
    return [c.document_type for c in get_required_documents(maatregel_type) if c.verplicht]


def allowed_document_types(
    maatregel_type: MaatregelType,
) -> set[MaatregelDocumentType]:
    """Superset: verplicht + optioneel + ``overig`` (altijd toegestaan)."""
    base = {c.document_type for c in get_required_documents(maatregel_type)}
    base.add(MaatregelDocumentType.overig)
    return base


# ---------------------------------------------------------------------------
# Subsidie schatting
# ---------------------------------------------------------------------------


# Vaste bedragen + percentages; alle drempels zijn conservatief volgens
# de 2025 RVO-tabellen. AAA-Lex overschrijft dit bedrag handmatig zodra
# de echte ``toegekende_subsidie`` binnen is.
_FLAT_AMOUNTS: dict[MaatregelType, float] = {
    MaatregelType.warmtepomp_lucht_water: 2500.0,
    MaatregelType.warmtepomp_water_water: 3500.0,
    MaatregelType.warmtepomp_hybride: 1500.0,
}

# (percentage, cap) — cap=None voor "geen plafond".
_PCT_AMOUNTS: dict[MaatregelType, tuple[float, Optional[float]]] = {
    MaatregelType.dakisolatie: (0.20, 3000.0),
    MaatregelType.gevelisolatie: (0.20, 2500.0),
    MaatregelType.vloerisolatie: (0.20, 1500.0),
    MaatregelType.hr_glas: (0.20, 2000.0),
    MaatregelType.zonneboiler: (0.20, 2000.0),
    MaatregelType.eia_investering: (0.455, None),
    MaatregelType.mia_vamil_investering: (0.36, None),
    MaatregelType.dumava_maatregel: (0.30, None),
}


def estimate_subsidie(
    maatregel_type: MaatregelType,
    investering_bedrag: Optional[float],
) -> Optional[float]:
    """Geef een conservatieve schatting van de subsidie terug.

    * Warmtepompen krijgen een vast bedrag (ISDE-tabel).
    * Isolatie/HR++ glas en zonneboiler: 20 % van de investering, plafond
      per maatregel.
    * EIA/MIA/Vamil/DUMAVA: percentage van de investering zonder plafond
      (daar bepaalt het belastingvoordeel de werkelijke waarde — de
      frontend toont 'geschat').

    Return ``None`` als we geen schatting kunnen maken (bijv. EIA zonder
    investering_bedrag) zodat de UI geen fantasiegetal toont.
    """
    if maatregel_type in _FLAT_AMOUNTS:
        return _FLAT_AMOUNTS[maatregel_type]
    if maatregel_type in _PCT_AMOUNTS:
        if investering_bedrag is None or investering_bedrag <= 0:
            return None
        pct, cap = _PCT_AMOUNTS[maatregel_type]
        raw = round(investering_bedrag * pct, 2)
        if cap is not None and raw > cap:
            return float(cap)
        return float(raw)
    return None
