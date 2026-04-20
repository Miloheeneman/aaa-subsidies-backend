from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organisation import Organisation
    from app.models.subsidie_aanvraag import SubsidieAanvraag


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )

    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    organisation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    # Per-user subscription tracking (new klant-onboarding flow).
    # See app.models.enums.SubscriptionPlan for the allowed values.
    # subscription_status is a free-form string that mirrors Stripe's own
    # statuses (active, past_due, canceled, …) plus our own "pending"
    # for the interval between checkout and the webhook confirmation.
    subscription_plan: Mapped[str] = mapped_column(
        String(32), nullable=False, default="gratis", server_default="gratis"
    )
    subscription_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )

    organisation: Mapped[Optional["Organisation"]] = relationship(
        back_populates="users",
        foreign_keys=[organisation_id],
    )

    aanvragen: Mapped[List["SubsidieAanvraag"]] = relationship(
        back_populates="aanvrager",
        foreign_keys="SubsidieAanvraag.aanvrager_id",
    )
