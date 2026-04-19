from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import (
    AanvraagStatus,
    DeadlineType,
    Maatregel,
    RegelingCode,
    TypeAanvrager,
)
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.aanvraag_document import AanvraagDocument
    from app.models.installateur_lead import InstallateurLead
    from app.models.organisation import Organisation
    from app.models.user import User


class SubsidieAanvraag(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "subsidie_aanvragen"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    aanvrager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    installateur_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    regeling: Mapped[RegelingCode] = mapped_column(
        Enum(
            RegelingCode,
            name="regeling_code",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        index=True,
    )
    type_aanvrager: Mapped[TypeAanvrager] = mapped_column(
        Enum(
            TypeAanvrager,
            name="type_aanvrager",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    status: Mapped[AanvraagStatus] = mapped_column(
        Enum(
            AanvraagStatus,
            name="aanvraag_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=AanvraagStatus.intake,
        server_default=AanvraagStatus.intake.value,
        index=True,
    )
    maatregel: Mapped[Maatregel] = mapped_column(
        Enum(
            Maatregel,
            name="maatregel",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )

    investering_bedrag: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    geschatte_subsidie: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    toegekende_subsidie: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    aaa_lex_fee_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    aaa_lex_fee_bedrag: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    deadline_datum: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    deadline_type: Mapped[Optional[DeadlineType]] = mapped_column(
        Enum(
            DeadlineType,
            name="deadline_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=True,
    )

    rvo_aanvraagnummer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    rvo_status: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Tracks the last date a deadline-warning email was sent so the
    # nightly cron job (see app/services/deadline_service.py) doesn't
    # spam clients but still re-sends weekly while a deadline is active.
    last_deadline_warning_sent: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )

    organisation: Mapped["Organisation"] = relationship(
        back_populates="aanvragen",
        foreign_keys=[organisation_id],
    )
    aanvrager: Mapped["User"] = relationship(
        back_populates="aanvragen",
        foreign_keys=[aanvrager_id],
    )
    installateur: Mapped[Optional["Organisation"]] = relationship(
        foreign_keys=[installateur_id],
    )

    documenten: Mapped[List["AanvraagDocument"]] = relationship(
        back_populates="aanvraag",
        cascade="all, delete-orphan",
    )
    leads: Mapped[List["InstallateurLead"]] = relationship(
        back_populates="aanvraag",
        cascade="all, delete-orphan",
    )
