from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import OrganisationType
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.subsidie_aanvraag import SubsidieAanvraag
    from app.models.installateur_lead import InstallateurLead


class Organisation(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kvk_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    type: Mapped[OrganisationType] = mapped_column(
        Enum(
            OrganisationType,
            name="organisation_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )

    subscription_plan: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    subscription_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    users: Mapped[List["User"]] = relationship(
        back_populates="organisation",
        foreign_keys="User.organisation_id",
    )

    aanvragen: Mapped[List["SubsidieAanvraag"]] = relationship(
        back_populates="organisation",
        foreign_keys="SubsidieAanvraag.organisation_id",
    )

    leads: Mapped[List["InstallateurLead"]] = relationship(
        back_populates="installateur",
        foreign_keys="InstallateurLead.installateur_id",
    )
