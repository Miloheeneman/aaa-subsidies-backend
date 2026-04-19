from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organisation import Organisation
    from app.models.subsidie_aanvraag import SubsidieAanvraag


class AAALexProject(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "aaa_lex_projecten"

    external_reference: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )

    organisation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    aanvraag_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subsidie_aanvragen.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Pand data
    pandadres: Mapped[str] = mapped_column(String(512), nullable=False)
    postcode: Mapped[str] = mapped_column(String(16), nullable=False)
    plaats: Mapped[str] = mapped_column(String(128), nullable=False)
    bouwjaar: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    huidig_energielabel: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    nieuw_energielabel: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    type_pand: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    oppervlakte_m2: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    dakoppervlakte_m2: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    geveloppervlakte_m2: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Measures / recommendations (JSON blob from AAA-Lex report)
    aanbevolen_maatregelen: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    geschatte_investering: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    geschatte_co2_besparing: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # Meta
    ingevoerd_door: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organisation: Mapped[Optional["Organisation"]] = relationship(
        foreign_keys=[organisation_id]
    )
    aanvraag: Mapped[Optional["SubsidieAanvraag"]] = relationship(
        foreign_keys=[aanvraag_id]
    )
