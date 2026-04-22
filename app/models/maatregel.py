"""Maatregel (measure) linked to a Project.

Represents a single subsidy-eligible investment/installation on one
Project. Captures installer details, meldcodes, deadlines, financials and
the chosen regeling.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import (
    DeadlineStatus,
    DeadlineTiming,
    MaatregelStatus,
    MaatregelType,
    RegelingCode,
)
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.maatregel_document import MaatregelDocument
    from app.models.project import Project
    from app.models.user import User


class Maatregel(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "maatregelen"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projecten.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # --- Wat is de maatregel? --------------------------------------------
    maatregel_type: Mapped[MaatregelType] = mapped_column(
        Enum(
            MaatregelType,
            name="maatregel_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
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

    # --- Apparaat / installatie ------------------------------------------
    apparaat_merk: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    apparaat_typenummer: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    # Meldcode is verplicht voor ISDE maar schema-optioneel zodat klanten
    # eerst de maatregel kunnen aanmaken en pas later de meldcode invullen
    # wanneer de installateur deze aanlevert.
    apparaat_meldcode: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
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

    # --- Financieel -------------------------------------------------------
    investering_bedrag: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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
            create_type=False,
        ),
        nullable=True,
        index=True,
    )

    # --- Deadline engine --------------------------------------------------
    # These are computed by app.services.deadline_service.calculate_maatregel_deadline
    # on every POST/PUT; we persist them so list endpoints can sort/filter
    # without re-running the engine per row.
    deadline_indienen: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    deadline_type: Mapped[Optional[DeadlineTiming]] = mapped_column(
        Enum(
            DeadlineTiming,
            name="deadline_timing",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
    )
    deadline_status: Mapped[Optional[DeadlineStatus]] = mapped_column(
        Enum(
            DeadlineStatus,
            name="deadline_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
        index=True,
    )

    # Admin deadline-waarschuwingen (Resend naar subsidies@…)
    deadline_admin_mail_30_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_admin_mail_14_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_admin_mail_7_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Relationships ----------------------------------------------------
    project: Mapped["Project"] = relationship(back_populates="maatregelen")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    documenten: Mapped[List["MaatregelDocument"]] = relationship(
        back_populates="maatregel",
        cascade="all, delete-orphan",
    )
