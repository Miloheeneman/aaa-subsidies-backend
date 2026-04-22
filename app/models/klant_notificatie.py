"""In-app notificaties voor klantgebruikers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.maatregel import Maatregel
    from app.models.project import Project
    from app.models.user import User


class KlantNotificatie(UUIDPKMixin, Base):
    __tablename__ = "klant_notificaties"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projecten.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    maatregel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("maatregelen.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    project: Mapped["Project"] = relationship(foreign_keys=[project_id])
    maatregel: Mapped[Optional["Maatregel"]] = relationship(
        foreign_keys=[maatregel_id]
    )
