"""klant_notificaties — in-app notificaties voor klanten."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0011_klant_notificaties"
down_revision = "0010_upload_verzoeken"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "klant_notificaties",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projecten.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "maatregel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("maatregelen.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_klant_notificaties_user_created",
        "klant_notificaties",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_klant_notificaties_user_created", table_name="klant_notificaties")
    op.drop_table("klant_notificaties")
