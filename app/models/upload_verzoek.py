"""Tijdelijke upload-links voor klanten (documentaanvraag via e-mail)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, List

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.maatregel import Maatregel
    from app.models.user import User


class UploadVerzoek(UUIDPKMixin, Base):
    __tablename__ = "upload_verzoeken"

    maatregel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("maatregelen.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    aangevraagd_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_types: Mapped[List[Any]] = mapped_column(JSONB, nullable=False)
    bericht: Mapped[str | None] = mapped_column(Text, nullable=True)
    token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    voltooid: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    maatregel: Mapped["Maatregel"] = relationship()
    aangevraagd_door_user: Mapped["User"] = relationship(
        foreign_keys=[aangevraagd_door]
    )
