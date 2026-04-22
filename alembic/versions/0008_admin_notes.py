"""Admin interne notities (organisatie + maatregel)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_admin_notes"
down_revision = "0007_rename_panden_to_projecten"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_organisation_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_org_notes_organisation_id",
        "admin_organisation_notes",
        ["organisation_id"],
        unique=False,
    )

    op.create_table(
        "admin_maatregel_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("maatregel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["maatregel_id"],
            ["maatregelen.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_maatregel_notes_maatregel_id",
        "admin_maatregel_notes",
        ["maatregel_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_maatregel_notes_maatregel_id", table_name="admin_maatregel_notes")
    op.drop_table("admin_maatregel_notes")
    op.drop_index("ix_admin_org_notes_organisation_id", table_name="admin_organisation_notes")
    op.drop_table("admin_organisation_notes")
