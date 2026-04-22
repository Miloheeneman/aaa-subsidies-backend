"""Domain services for the projecten module (STAP 9).

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
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from app.models.enums import (
    DeadlineStatus,
    DeadlineTiming,
    EigenaarType,
    MaatregelDocumentType,
    MaatregelType,
    ProjectType,
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


# m²-tarief (€/m²) en plafond voor ISDE-isolatie wizard (RVO-richting).
_ISOLATIE_M2_TARIEVEN: dict[MaatregelType, tuple[float, float]] = {
    MaatregelType.dakisolatie: (16.25, 3000.0),
    MaatregelType.gevelisolatie: (14.50, 2500.0),
    MaatregelType.vloerisolatie: (12.00, 1500.0),
    MaatregelType.hr_glas: (65.00, 2000.0),
}


def estimate_isolatie_subsidie_from_m2(
    maatregel_type: MaatregelType, oppervlakte_m2: float
) -> float:
    """Geschatte ISDE-subsidie op basis van m² (wizard ISDE isolatie).

    Gebruikt door de isolatie-intake zodat dit gelijk blijft aan de UI.
    """
    if maatregel_type not in _ISOLATIE_M2_TARIEVEN:
        return 0.0
    rate, cap = _ISOLATIE_M2_TARIEVEN[maatregel_type]
    raw = round(oppervlakte_m2 * rate, 2)
    return float(min(raw, cap))


# ---------------------------------------------------------------------------
# Subsidie matching engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubsidieMatch:
    """One regeling evaluated against a single :class:`Project`."""

    code: str
    naam: str
    beschrijving: str
    max_subsidie: Optional[float]
    fee_percentage: float
    deadline_type: str  # "na_installatie" | "voor_offerte"
    deadline_maanden: int
    eligible: bool
    reden: Optional[str] = None


# Een eligibility-check is een lijst van (predikaat, faal-reden) tuples.
# Predikaten krijgen het project mee en geven True terug als de voorwaarde
# voldoet. ``_evaluate`` walkt deze door:
#   * alle voldaan → eligible=True
#   * exact 1 niet voldaan → eligible=False met die reden ("bijna" match)
#   * meer dan 1 niet voldaan → niet relevant, niet teruggeven
_Predicate = Tuple[
    "callable[[object], bool]",  # type: ignore[type-arg]
    str,
]


_WOON_TYPES = {ProjectType.woning, ProjectType.appartement}
_PARTICULIER_EIGENAREN = {
    EigenaarType.eigenaar_bewoner,
    EigenaarType.particulier_verhuurder,
}
_ISDE_WP_EIGENAREN = _PARTICULIER_EIGENAREN | {
    EigenaarType.zakelijk_verhuurder,
}
_EIA_EIGENAREN = {EigenaarType.zakelijk_verhuurder, EigenaarType.overig}
_EIA_PROJECT_TYPES = {ProjectType.kantoor, ProjectType.bedrijfspand}
_DUMAVA_PROJECT_TYPES = {
    ProjectType.zorginstelling,
    ProjectType.school,
    ProjectType.sportaccommodatie,
}


def _evaluate(
    project: object,
    base: dict,
    checks: Iterable[_Predicate],
    *,
    near_miss_threshold: int = 1,
) -> Optional[SubsidieMatch]:
    """Run alle predikaten en bouw een :class:`SubsidieMatch` of ``None``."""
    failures: List[str] = []
    for predicate, reason in checks:
        if not predicate(project):
            failures.append(reason)

    if not failures:
        return SubsidieMatch(**base, eligible=True, reden=None)
    if len(failures) <= near_miss_threshold:
        return SubsidieMatch(**base, eligible=False, reden=failures[0])
    return None


def _match_isde_warmtepomp(project: object) -> Optional[SubsidieMatch]:
    base = dict(
        code="ISDE_WARMTEPOMP",
        naam="ISDE — Warmtepomp",
        beschrijving=(
            "Subsidie voor installatie van een warmtepomp in uw woning."
        ),
        max_subsidie=3500.0,
        fee_percentage=8.0,
        deadline_type="na_installatie",
        deadline_maanden=24,
    )
    return _evaluate(
        project,
        base,
        [
            (lambda p: p.bouwjaar < 2019, "Bouwjaar moet vóór 2019 zijn voor ISDE"),
            (
                lambda p: p.eigenaar_type in _ISDE_WP_EIGENAREN,
                "ISDE warmtepomp is alleen voor eigenaar-bewoners en verhuurders",
            ),
            (
                lambda p: p.project_type in _WOON_TYPES,
                "ISDE warmtepomp is alleen voor woningen of appartementen",
            ),
        ],
    )


def _match_isde_isolatie(project: object) -> Optional[SubsidieMatch]:
    base = dict(
        code="ISDE_ISOLATIE",
        naam="ISDE — Isolatie",
        beschrijving=(
            "Subsidie voor dak, gevel, vloer of HR++ glas isolatie."
        ),
        max_subsidie=3000.0,
        fee_percentage=8.0,
        deadline_type="na_installatie",
        deadline_maanden=24,
    )
    return _evaluate(
        project,
        base,
        [
            (lambda p: p.bouwjaar < 2019, "Bouwjaar moet vóór 2019 zijn voor ISDE"),
            (
                lambda p: p.eigenaar_type in _PARTICULIER_EIGENAREN,
                "ISDE isolatie is alleen voor eigenaar-bewoners en particuliere verhuurders",
            ),
            (
                lambda p: p.project_type in _WOON_TYPES,
                "ISDE isolatie is alleen voor woningen of appartementen",
            ),
        ],
    )


def _match_eia(project: object) -> Optional[SubsidieMatch]:
    base = dict(
        code="EIA",
        naam="EIA — Energie Investeringsaftrek",
        beschrijving=(
            "45,5% fiscale aftrek op energiebesparende investeringen."
        ),
        max_subsidie=None,
        fee_percentage=5.0,
        deadline_type="voor_offerte",
        deadline_maanden=3,
    )
    return _evaluate(
        project,
        base,
        [
            (
                lambda p: p.eigenaar_type in _EIA_EIGENAREN,
                "EIA is alleen voor zakelijke eigenaren",
            ),
            (
                lambda p: p.project_type in _EIA_PROJECT_TYPES,
                "EIA is bedoeld voor kantoor- of bedrijfsgebouwen",
            ),
        ],
    )


def _match_mia_vamil(project: object) -> Optional[SubsidieMatch]:
    base = dict(
        code="MIA_VAMIL",
        naam="MIA + Vamil",
        beschrijving=(
            "27-45% milieu-investeringsaftrek plus liquiditeitsvoordeel."
        ),
        max_subsidie=None,
        fee_percentage=5.0,
        deadline_type="voor_offerte",
        deadline_maanden=3,
    )
    return _evaluate(
        project,
        base,
        [
            (
                lambda p: p.eigenaar_type in _EIA_EIGENAREN,
                "MIA/Vamil is alleen voor zakelijke eigenaren",
            ),
            (
                lambda p: p.project_type in _EIA_PROJECT_TYPES,
                "MIA/Vamil is bedoeld voor kantoor- of bedrijfsgebouwen",
            ),
        ],
    )


def _match_dumava(project: object) -> Optional[SubsidieMatch]:
    base = dict(
        code="DUMAVA",
        naam="DUMAVA",
        beschrijving=(
            "Tot 30% subsidie voor verduurzaming van maatschappelijk vastgoed."
        ),
        max_subsidie=150000.0,
        fee_percentage=10.0,
        deadline_type="na_installatie",
        deadline_maanden=24,
    )
    # Twee aparte routes: maatschappelijk vastgoed, OF VvE met overig type.
    is_maatschappelijk = project.project_type in _DUMAVA_PROJECT_TYPES
    is_vve_overig = (
        project.eigenaar_type == EigenaarType.vve
        and project.project_type == ProjectType.overig
    )
    if is_maatschappelijk or is_vve_overig:
        return SubsidieMatch(**base, eligible=True, reden=None)

    # "Bijna" match: VvE met een ander project-type — we melden dat het
    # alleen voor maatschappelijk vastgoed of VvE-overig geldt.
    if project.eigenaar_type == EigenaarType.vve:
        return SubsidieMatch(
            **base,
            eligible=False,
            reden=(
                "DUMAVA is voor maatschappelijk vastgoed of VvE met "
                "project-type 'overig'"
            ),
        )
    return None


def _match_svve(project: object) -> Optional[SubsidieMatch]:
    base = dict(
        code="SVVE",
        naam="SVVE — VvE verduurzaming",
        beschrijving="Subsidie voor verduurzaming van VvE gebouwen.",
        max_subsidie=5000.0,
        fee_percentage=8.0,
        deadline_type="na_installatie",
        deadline_maanden=24,
    )
    if project.eigenaar_type == EigenaarType.vve:
        return SubsidieMatch(**base, eligible=True, reden=None)
    return None


_MATCHERS = (
    _match_isde_warmtepomp,
    _match_isde_isolatie,
    _match_eia,
    _match_mia_vamil,
    _match_dumava,
    _match_svve,
)


def get_matching_subsidies(project: object) -> List[SubsidieMatch]:
    """Bepaal alle subsidies die voor dit project relevant zijn.

    De terugkomende lijst bevat zowel ``eligible=True`` (volledig matchend)
    als ``eligible=False`` (bijna-match, met ``reden``). Niet-relevante
    regelingen worden weggelaten.

    De caller (route-laag) splitst de lijst in eligible/niet_eligible.
    """
    results: List[SubsidieMatch] = []
    for matcher in _MATCHERS:
        m = matcher(project)
        if m is not None:
            results.append(m)
    return results


def verplichte_documenten_telling(db: object, maatregel: object) -> tuple[int, int]:
    """Aantal verplichte checklist-items vs. geüpload (per documenttype)."""
    from sqlalchemy import select

    from app.models.maatregel_document import MaatregelDocument

    checklist = get_required_documents(maatregel.maatregel_type)
    verplicht = [c for c in checklist if c.verplicht]
    rows = (
        db.execute(
            select(MaatregelDocument.document_type).where(
                MaatregelDocument.maatregel_id == maatregel.id
            )
        )
        .scalars()
        .all()
    )
    have = set(rows)
    geupload = sum(1 for c in verplicht if c.document_type in have)
    return len(verplicht), geupload


def _document_types_from_verzoek_raw(raw: list) -> List[MaatregelDocumentType]:
    out: List[MaatregelDocumentType] = []
    for x in raw or []:
        try:
            out.append(MaatregelDocumentType(x))
        except ValueError:
            continue
    return out


def fulfilled_verzoek_document_types(
    db: object,
    *,
    maatregel_id: UUID,
    vz_created_at: datetime,
    types: Sequence[MaatregelDocumentType],
) -> set[MaatregelDocumentType]:
    if not types:
        return set()
    from sqlalchemy import select

    from app.models.maatregel_document import MaatregelDocument

    rows = (
        db.execute(
            select(MaatregelDocument.document_type).where(
                MaatregelDocument.maatregel_id == maatregel_id,
                MaatregelDocument.created_at >= vz_created_at,
                MaatregelDocument.document_type.in_(types),
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


def open_upload_verzoek_rows_for_project(db: object, project_id: UUID) -> List[dict]:
    """Actieve (niet verlopen, niet voltooid) uploadverzoeken voor klant-UI."""
    from sqlalchemy import select

    from app.models.maatregel import Maatregel
    from app.models.upload_verzoek import UploadVerzoek

    now = datetime.now(timezone.utc)
    q = (
        select(UploadVerzoek, Maatregel)
        .join(Maatregel, UploadVerzoek.maatregel_id == Maatregel.id)
        .where(
            Maatregel.project_id == project_id,
            UploadVerzoek.voltooid.is_(False),
            UploadVerzoek.token_expires_at > now,
        )
    )
    out: List[dict] = []
    for vz, m in db.execute(q).all():
        types = _document_types_from_verzoek_raw(list(vz.document_types or []))
        total = len(types)
        if total == 0:
            continue
        ful = fulfilled_verzoek_document_types(
            db,
            maatregel_id=m.id,
            vz_created_at=vz.created_at,
            types=types,
        )
        nog = len(set(types) - ful)
        out.append(
            {
                "id": vz.id,
                "maatregel_id": m.id,
                "token": vz.token,
                "token_expires_at": vz.token_expires_at,
                "documenten_nog_nodig": nog,
                "documenten_totaal": total,
            }
        )
    return out


def project_ids_with_open_upload_verzoek(
    db: object, project_ids: List[UUID]
) -> set[UUID]:
    if not project_ids:
        return set()
    from sqlalchemy import select

    from app.models.maatregel import Maatregel
    from app.models.upload_verzoek import UploadVerzoek

    now = datetime.now(timezone.utc)
    rows = (
        db.execute(
            select(Maatregel.project_id)
            .join(UploadVerzoek, UploadVerzoek.maatregel_id == Maatregel.id)
            .where(
                Maatregel.project_id.in_(project_ids),
                UploadVerzoek.voltooid.is_(False),
                UploadVerzoek.token_expires_at > now,
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    return set(rows)


def maybe_complete_upload_verzoek(db: object, vz: object) -> None:
    types = _document_types_from_verzoek_raw(list(vz.document_types or []))
    if not types:
        return
    ful = fulfilled_verzoek_document_types(
        db,
        maatregel_id=vz.maatregel_id,
        vz_created_at=vz.created_at,
        types=types,
    )
    if set(types) <= ful:
        vz.voltooid = True
