"""Project (building / dossier) owned by a klant organisation.

STAP 9 — projecten module. Each Project belongs to exactly one
organisation and can have zero-or-more Maatregelen (measures). The
AAA-Lex-specific fields (energielabel, oppervlakte, notities) are
filled in by admins after an on-site assessment.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import EigenaarType, EnergielabelKlasse, ProjectType
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.maatregel import Maatregel
    from app.models.organisation import Organisation
    from app.models.user import User


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projecten"

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

    # --- Adres ------------------------------------------------------------
    straat: Mapped[str] = mapped_column(String(255), nullable=False)
    huisnummer: Mapped[str] = mapped_column(String(32), nullable=False)
    postcode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    plaats: Mapped[str] = mapped_column(String(128), nullable=False)

    # --- Projectgegevens ---------------------------------------------------
    # Bouwjaar is required — it drives the ISDE eligibility check
    # (woning < 2019) and is the first thing AAA-Lex asks for.
    bouwjaar: Mapped[int] = mapped_column(Integer, nullable=False)
    project_type: Mapped[ProjectType] = mapped_column(
        Enum(
            ProjectType,
            name="project_type",
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

    # --- AAA-Lex data (filled in by admins after opname) ------------------
    energielabel_huidig: Mapped[Optional[EnergielabelKlasse]] = mapped_column(
        Enum(
            EnergielabelKlasse,
            name="energielabel_klasse",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
    )
    energielabel_na_maatregelen: Mapped[Optional[EnergielabelKlasse]] = mapped_column(
        Enum(
            EnergielabelKlasse,
            name="energielabel_klasse",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            create_type=False,
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

    # --- Soft delete ------------------------------------------------------
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # --- Relationships ----------------------------------------------------
    organisation: Mapped["Organisation"] = relationship(
        foreign_keys=[organisation_id]
    )
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    maatregelen: Mapped[List["Maatregel"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
