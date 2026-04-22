"""Upload-verzoeken, admin_notities, maatregel admin deadline-mail flags."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_upload_verzoeken"
down_revision = "0009_maatregel_status_in_beoordeling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "upload_verzoeken",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("maatregel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aangevraagd_door", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("bericht", sa.Text(), nullable=True),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "voltooid",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
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
            ["aangevraagd_door"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_upload_verzoeken_token"),
    )
    op.create_index(
        "ix_upload_verzoeken_maatregel_id",
        "upload_verzoeken",
        ["maatregel_id"],
        unique=False,
    )

    op.create_table(
        "admin_notities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tekst", sa.Text(), nullable=False),
        sa.Column("aangemaakt_door", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["aangemaakt_door"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_notities_entity",
        "admin_notities",
        ["entity_type", "entity_id"],
        unique=False,
    )

    op.add_column(
        "maatregelen",
        sa.Column(
            "deadline_admin_mail_30_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "maatregelen",
        sa.Column(
            "deadline_admin_mail_14_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "maatregelen",
        sa.Column(
            "deadline_admin_mail_7_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("maatregelen", "deadline_admin_mail_7_sent_at")
    op.drop_column("maatregelen", "deadline_admin_mail_14_sent_at")
    op.drop_column("maatregelen", "deadline_admin_mail_30_sent_at")
    op.drop_index("ix_admin_notities_entity", table_name="admin_notities")
    op.drop_table("admin_notities")
    op.drop_index("ix_upload_verzoeken_maatregel_id", table_name="upload_verzoeken")
    op.drop_table("upload_verzoeken")
