from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import EigenaarType, Energielabel, PandType
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.aaa_lex_project import AAALexProject
    from app.models.organisation import Organisation
    from app.models.pand_maatregel import Maatregel
    from app.models.user import User


class Pand(UUIDPKMixin, TimestampMixin, Base):
    """Een vastgoedobject van een klant.

    Panden zijn het centrale organisatorische niveau voor de
    panden-module: per pand houden we adresgegevens, AAA-Lex-opname
    data en een lijst maatregelen bij. Soft-delete gebeurt via de
    ``deleted`` kolom zodat we R2-documenten kunnen terughalen mocht
    een klant per ongeluk verwijderen.
    """

    __tablename__ = "panden"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    straat: Mapped[str] = mapped_column(String(255), nullable=False)
    huisnummer: Mapped[str] = mapped_column(String(32), nullable=False)
    postcode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    plaats: Mapped[str] = mapped_column(String(128), nullable=False)
    bouwjaar: Mapped[int] = mapped_column(Integer, nullable=False)

    pand_type: Mapped[PandType] = mapped_column(
        Enum(
            PandType,
            name="pand_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    eigenaar_type: Mapped[EigenaarType] = mapped_column(
        Enum(
            EigenaarType,
            name="eigenaar_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )

    # AAA-Lex opname-velden. Worden door admin ingevuld na een bezoek
    # en door de klant alleen gelezen (frontend maakt ze read-only).
    energielabel_huidig: Mapped[Optional[Energielabel]] = mapped_column(
        Enum(
            Energielabel,
            name="energielabel_huidig",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
    )
    energielabel_na_maatregelen: Mapped[Optional[Energielabel]] = mapped_column(
        Enum(
            Energielabel,
            name="energielabel_na_maatregelen",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
    )
    oppervlakte_m2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    aaa_lex_project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("aaa_lex_projecten.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )

    organisation: Mapped["Organisation"] = relationship(
        foreign_keys=[organisation_id]
    )
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    aaa_lex_project: Mapped[Optional["AAALexProject"]] = relationship(
        foreign_keys=[aaa_lex_project_id]
    )
    maatregelen: Mapped[List["Maatregel"]] = relationship(
        back_populates="pand",
        cascade="all, delete-orphan",
    )
