"""Document-checklist service voor de panden-module.

Per maatregel-type bepaalt deze module welke documenten verplicht zijn
voordat AAA-Lex de aanvraag kan indienen bij RVO. Gebruikt door zowel
de upload-endpoint (validatie) als de GET /checklist endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.models.enums import MaatregelDocumentType, MaatregelType


@dataclass(frozen=True)
class DocumentSpec:
    document_type: MaatregelDocumentType
    label: str
    uitleg: str
    verplicht: bool = True


_WARMTEPOMP_DOCS: Tuple[DocumentSpec, ...] = (
    DocumentSpec(
        MaatregelDocumentType.factuur,
        "Factuur",
        "Factuur met meldcode en installatiedatum.",
    ),
    DocumentSpec(
        MaatregelDocumentType.betaalbewijs,
        "Betaalbewijs",
        "Bankafschrift of betaalbevestiging.",
    ),
    DocumentSpec(
        MaatregelDocumentType.meldcode_bewijs,
        "Meldcode-bewijs",
        "Document waarop de ISDE-meldcode van het apparaat staat.",
    ),
    DocumentSpec(
        MaatregelDocumentType.inbedrijfstelling,
        "Inbedrijfstellingsformulier",
        "Ingevuld door de monteur bij oplevering.",
    ),
    DocumentSpec(
        MaatregelDocumentType.offerte,
        "Offerte (optioneel)",
        "Originele offerte — aanbevolen voor dossieropbouw.",
        verplicht=False,
    ),
)

_ISOLATIE_DOCS: Tuple[DocumentSpec, ...] = (
    DocumentSpec(
        MaatregelDocumentType.factuur,
        "Factuur",
        "Factuur met meldcode isolatiemateriaal.",
    ),
    DocumentSpec(
        MaatregelDocumentType.betaalbewijs,
        "Betaalbewijs",
        "Bankafschrift of betaalbevestiging.",
    ),
    DocumentSpec(
        MaatregelDocumentType.meldcode_bewijs,
        "Meldcode-bewijs",
        "Document waarop de ISDE-meldcode van het isolatiemateriaal staat.",
    ),
    DocumentSpec(
        MaatregelDocumentType.foto_werkzaamheden,
        "Foto tijdens werkzaamheden",
        "Naam, merk en dikte van het materiaal moeten zichtbaar zijn.",
    ),
)

_EIA_MIA_DOCS: Tuple[DocumentSpec, ...] = (
    DocumentSpec(
        MaatregelDocumentType.offerte,
        "Offerte",
        "Offerte van de investering. LET OP: aanvragen VÓÓR u de offerte ondertekent.",
    ),
    DocumentSpec(
        MaatregelDocumentType.kvk_uittreksel,
        "KvK-uittreksel",
        "Recent uittreksel van de Kamer van Koophandel.",
    ),
    DocumentSpec(
        MaatregelDocumentType.factuur,
        "Factuur",
        "Factuur van de investering (na aankoop).",
    ),
    DocumentSpec(
        MaatregelDocumentType.betaalbewijs,
        "Betaalbewijs",
        "Bankafschrift of betaalbevestiging van de investering.",
    ),
)

_DUMAVA_DOCS: Tuple[DocumentSpec, ...] = (
    DocumentSpec(
        MaatregelDocumentType.offerte,
        "Offerte",
        "Offerte met specificatie van de maatregelen.",
    ),
    DocumentSpec(
        MaatregelDocumentType.factuur,
        "Factuur",
        "Factuur van de uitgevoerde werkzaamheden.",
    ),
    DocumentSpec(
        MaatregelDocumentType.betaalbewijs,
        "Betaalbewijs",
        "Bankafschrift of betaalbevestiging.",
    ),
    DocumentSpec(
        MaatregelDocumentType.machtiging,
        "Machtiging",
        "Machtigingsformulier voor AAA-Lex als intermediair.",
    ),
)


_REQUIRED_BY_TYPE: Dict[MaatregelType, Tuple[DocumentSpec, ...]] = {
    MaatregelType.warmtepomp_lucht_water: _WARMTEPOMP_DOCS,
    MaatregelType.warmtepomp_water_water: _WARMTEPOMP_DOCS,
    MaatregelType.warmtepomp_hybride: _WARMTEPOMP_DOCS,
    MaatregelType.zonneboiler: _WARMTEPOMP_DOCS,
    MaatregelType.dakisolatie: _ISOLATIE_DOCS,
    MaatregelType.gevelisolatie: _ISOLATIE_DOCS,
    MaatregelType.vloerisolatie: _ISOLATIE_DOCS,
    MaatregelType.hr_glas: _ISOLATIE_DOCS,
    MaatregelType.eia_investering: _EIA_MIA_DOCS,
    MaatregelType.mia_vamil_investering: _EIA_MIA_DOCS,
    MaatregelType.dumava_maatregel: _DUMAVA_DOCS,
}


def get_required_documents(
    maatregel_type: MaatregelType,
) -> List[DocumentSpec]:
    """Return the ordered list of DocumentSpec for a maatregel type."""
    return list(_REQUIRED_BY_TYPE.get(maatregel_type, ()))


def document_type_is_valid_for(
    maatregel_type: MaatregelType,
    document_type: MaatregelDocumentType,
) -> bool:
    """Laat ook ``overig`` altijd toe — is een escape-hatch voor admin."""
    if document_type == MaatregelDocumentType.overig:
        return True
    specs = _REQUIRED_BY_TYPE.get(maatregel_type)
    if not specs:
        return True  # onbekend type → niet blokkeren
    return any(s.document_type == document_type for s in specs)


DOCUMENT_LABELS: Dict[MaatregelDocumentType, str] = {
    MaatregelDocumentType.factuur: "Factuur",
    MaatregelDocumentType.betaalbewijs: "Betaalbewijs",
    MaatregelDocumentType.meldcode_bewijs: "Meldcode-bewijs",
    MaatregelDocumentType.foto_werkzaamheden: "Foto tijdens werkzaamheden",
    MaatregelDocumentType.inbedrijfstelling: "Inbedrijfstellingsformulier",
    MaatregelDocumentType.offerte: "Offerte",
    MaatregelDocumentType.kvk_uittreksel: "KvK-uittreksel",
    MaatregelDocumentType.machtiging: "Machtiging",
    MaatregelDocumentType.overig: "Overig",
}


def label_for(document_type: MaatregelDocumentType) -> str:
    return DOCUMENT_LABELS.get(document_type, document_type.value)


def uitleg_for(
    document_type: MaatregelDocumentType,
    maatregel_type: Optional[MaatregelType] = None,
) -> str:
    if maatregel_type is not None:
        for spec in _REQUIRED_BY_TYPE.get(maatregel_type, ()):
            if spec.document_type == document_type:
                return spec.uitleg
    fallback = {
        MaatregelDocumentType.factuur: "Factuur van de investering.",
        MaatregelDocumentType.betaalbewijs: "Bankafschrift of betaalbevestiging.",
        MaatregelDocumentType.meldcode_bewijs: "Bewijs van de meldcode.",
        MaatregelDocumentType.foto_werkzaamheden: "Foto tijdens de werkzaamheden.",
        MaatregelDocumentType.inbedrijfstelling: "Inbedrijfstellingsformulier.",
        MaatregelDocumentType.offerte: "Offerte van de investering.",
        MaatregelDocumentType.kvk_uittreksel: "Recent KvK-uittreksel.",
        MaatregelDocumentType.machtiging: "Machtigingsformulier.",
        MaatregelDocumentType.overig: "Aanvullend document.",
    }
    return fallback.get(document_type, "")
