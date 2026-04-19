from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import LeadStatus
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organisation import Organisation
    from app.models.subsidie_aanvraag import SubsidieAanvraag


class InstallateurLead(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "installateur_leads"

    installateur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    aanvraag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subsidie_aanvragen.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[LeadStatus] = mapped_column(
        Enum(
            LeadStatus,
            name="lead_status",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=LeadStatus.nieuw,
        server_default=LeadStatus.nieuw.value,
    )
    regio: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    installateur: Mapped["Organisation"] = relationship(
        back_populates="leads",
        foreign_keys=[installateur_id],
    )
    aanvraag: Mapped["SubsidieAanvraag"] = relationship(
        back_populates="leads",
        foreign_keys=[aanvraag_id],
    )
