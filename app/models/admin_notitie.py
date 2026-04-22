"""Generieke interne admin-notitie (optioneel naast bestaande koppeltabellen)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User


class AdminNotitie(UUIDPKMixin, Base):
    __tablename__ = "admin_notities"

    entity_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tekst: Mapped[str] = mapped_column(Text, nullable=False)
    aangemaakt_door: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    author: Mapped["User"] = relationship(foreign_keys=[aangemaakt_door])
