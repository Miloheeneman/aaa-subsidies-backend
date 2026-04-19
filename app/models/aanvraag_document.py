from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import DocumentType
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.subsidie_aanvraag import SubsidieAanvraag


class AanvraagDocument(UUIDPKMixin, Base):
    __tablename__ = "aanvraag_documenten"

    aanvraag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subsidie_aanvragen.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_type: Mapped[DocumentType] = mapped_column(
        Enum(
            DocumentType,
            name="document_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(1024), nullable=False)

    verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    aanvraag: Mapped["SubsidieAanvraag"] = relationship(back_populates="documenten")
