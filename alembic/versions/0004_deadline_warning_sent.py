"""add last_deadline_warning_sent to subsidie_aanvragen

Revision ID: 7c1e91e0a004
Revises: 48c28c869837
Create Date: 2026-04-19 20:00:00.000000+00:00

Adds a single nullable Date column used by the nightly deadline-check
cron (see app/services/deadline_service.py) to suppress duplicate
warning emails while still allowing weekly reminders.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c1e91e0a004"
down_revision: Union[str, None] = "48c28c869837"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subsidie_aanvragen",
        sa.Column("last_deadline_warning_sent", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subsidie_aanvragen", "last_deadline_warning_sent")
