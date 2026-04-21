from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import (
    DeadlineStatus,
    MaatregelDeadlineType,
    MaatregelStatus,
    MaatregelType,
    RegelingCode,
)
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.pand import Pand
    from app.models.pand_maatregel_document import MaatregelDocument
    from app.models.user import User


class Maatregel(UUIDPKMixin, TimestampMixin, Base):
    """Een concrete subsidie-maatregel voor één pand.

    Dit is een fors bredere entiteit dan de legacy
    ``SubsidieAanvraag``: we slaan hier apparaat-details, installateur,
    financiën én deadline-engine state op. Eén pand heeft typisch
    meerdere maatregelen (warmtepomp + isolatie + ... ) die ieder hun
    eigen regeling en deadline kennen.

    Let op: het legacy ``maatregel`` enum in :mod:`app.models.enums`
    (uitsluitend warmtepomp/isolatie/energiesysteem/meerdere) is te
    grof voor dit model en wordt hier bewust vervangen door
    :class:`MaatregelType`.
    """

    __tablename__ = "maatregelen"

    pand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("panden.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    maatregel_type: Mapped[MaatregelType] = mapped_column(
        Enum(
            MaatregelType,
            name="maatregel_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    omschrijving: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[MaatregelStatus] = mapped_column(
        Enum(
            MaatregelStatus,
            name="maatregel_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=MaatregelStatus.orientatie,
        server_default=MaatregelStatus.orientatie.value,
        index=True,
    )

    apparaat_merk: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    apparaat_typenummer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    apparaat_meldcode: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    installateur_naam: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    installateur_kvk: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )
    installateur_gecertificeerd: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    installatie_datum: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    offerte_datum: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    investering_bedrag: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    geschatte_subsidie: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    toegekende_subsidie: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    regeling_code: Mapped[Optional[RegelingCode]] = mapped_column(
        Enum(
            RegelingCode,
            name="regeling_code",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            # Bestaat al in DB vanaf 0001 — niet opnieuw creëeren.
            create_type=False,
        ),
        nullable=True,
        index=True,
    )

    deadline_indienen: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )
    deadline_type: Mapped[Optional[MaatregelDeadlineType]] = mapped_column(
        Enum(
            MaatregelDeadlineType,
            name="maatregel_deadline_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
    )
    deadline_status: Mapped[Optional[DeadlineStatus]] = mapped_column(
        Enum(
            DeadlineStatus,
            name="maatregel_deadline_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
        index=True,
    )

    pand: Mapped["Pand"] = relationship(back_populates="maatregelen")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    documenten: Mapped[List["MaatregelDocument"]] = relationship(
        back_populates="maatregel",
        cascade="all, delete-orphan",
    )
