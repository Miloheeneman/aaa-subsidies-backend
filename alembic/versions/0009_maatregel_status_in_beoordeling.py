"""Voeg maatregel_status-waarde in_beoordeling toe (PostgreSQL enum)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_maatregel_status_in_beoordeling"
down_revision = "0008_admin_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_enum e
            JOIN pg_type t ON e.enumtypid = t.oid
            WHERE t.typname = 'maatregel_status'
              AND e.enumlabel = 'in_beoordeling'
            """
        )
    ).scalar()
    if row is None:
        op.execute(
            sa.text("ALTER TYPE maatregel_status ADD VALUE 'in_beoordeling'")
        )


def downgrade() -> None:
    # PostgreSQL: enum values verwijderen is lastig; leeg laten.
    pass
