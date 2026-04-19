from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.enums import RegelingCode
from app.models.mixins import UUIDPKMixin


class RegelingConfig(UUIDPKMixin, Base):
    __tablename__ = "regelingen_config"

    code: Mapped[RegelingCode] = mapped_column(
        Enum(
            RegelingCode,
            name="regeling_code",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            create_type=False,
        ),
        nullable=False,
        unique=True,
        index=True,
    )

    naam: Mapped[str] = mapped_column(String(128), nullable=False)
    beschrijving: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    actief: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    fee_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    min_investering: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    max_subsidie: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    aanvraag_termijn_dagen: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
