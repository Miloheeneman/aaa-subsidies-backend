"""add subscription_plan / subscription_status / stripe_customer_id to users

Revision ID: 9e3a2c1b0005
Revises: 7c1e91e0a004
Create Date: 2026-04-20 17:00:00.000000+00:00

Introduces per-user subscription tracking so the new klant-onboarding
flow can route a user through a plan picker (gratis / starter / pro /
enterprise) without touching the legacy organisation-scoped subscription
columns (which still drive the installateur abonnement flow).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9e3a2c1b0005"
down_revision: Union[str, None] = "7c1e91e0a004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "subscription_plan",
            sa.String(length=32),
            nullable=False,
            server_default="gratis",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "subscription_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "stripe_customer_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_users_stripe_customer_id",
        "users",
        ["stripe_customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "stripe_customer_id")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "subscription_plan")
