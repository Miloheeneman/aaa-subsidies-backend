from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import MaatregelDocumentType
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.pand_maatregel import Maatregel
    from app.models.user import User


class MaatregelDocument(UUIDPKMixin, Base):
    """Een documentupload gekoppeld aan één maatregel.

    Pad in R2: ``{organisation_id}/panden/{pand_id}/maatregelen/{maatregel_id}/{document_id}/{filename}``.
    """

    __tablename__ = "maatregel_documenten"

    maatregel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("maatregelen.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[MaatregelDocumentType] = mapped_column(
        Enum(
            MaatregelDocumentType,
            name="maatregel_document_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    bestandsnaam: Mapped[str] = mapped_column(String(512), nullable=False)
    r2_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    geupload_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    geverifieerd_door_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    maatregel: Mapped["Maatregel"] = relationship(back_populates="documenten")
    uploader: Mapped["User"] = relationship(foreign_keys=[geupload_door])
