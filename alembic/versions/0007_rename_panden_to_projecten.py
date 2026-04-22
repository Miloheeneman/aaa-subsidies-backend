"""Rename panden -> projecten; maatregelen.pand_id -> project_id.

Revision ID: b7c1d2e30007
Revises: a4d7f1c20006
Create Date: 2026-04-22

Pure rename: table, enum type, column names, FKs, indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b7c1d2e30007"
down_revision: Union[str, None] = "a4d7f1c20006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "maatregelen_pand_id_fkey", "maatregelen", type_="foreignkey"
    )
    op.drop_index("ix_maatregelen_pand_id", table_name="maatregelen")
    op.alter_column(
        "maatregelen",
        "pand_id",
        new_column_name="project_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
    )
    op.rename_table("panden", "projecten")

    op.execute('ALTER INDEX "ix_panden_organisation_id" RENAME TO "ix_projecten_organisation_id"')
    op.execute('ALTER INDEX "ix_panden_created_by" RENAME TO "ix_projecten_created_by"')
    op.execute('ALTER INDEX "ix_panden_postcode" RENAME TO "ix_projecten_postcode"')
    op.execute(
        'ALTER INDEX "ix_panden_aaa_lex_project_id" RENAME TO "ix_projecten_aaa_lex_project_id"'
    )

    op.execute("ALTER TYPE pand_type RENAME TO project_type")
    op.execute("ALTER TABLE projecten RENAME COLUMN pand_type TO project_type")

    op.create_foreign_key(
        "maatregelen_project_id_fkey",
        "maatregelen",
        "projecten",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_maatregelen_project_id", "maatregelen", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_maatregelen_project_id", table_name="maatregelen")
    op.drop_constraint(
        "maatregelen_project_id_fkey", "maatregelen", type_="foreignkey"
    )

    op.execute("ALTER TABLE projecten RENAME COLUMN project_type TO pand_type")
    op.execute("ALTER TYPE project_type RENAME TO pand_type")

    op.execute(
        'ALTER INDEX "ix_projecten_aaa_lex_project_id" RENAME TO "ix_panden_aaa_lex_project_id"'
    )
    op.execute('ALTER INDEX "ix_projecten_postcode" RENAME TO "ix_panden_postcode"')
    op.execute('ALTER INDEX "ix_projecten_created_by" RENAME TO "ix_panden_created_by"')
    op.execute(
        'ALTER INDEX "ix_projecten_organisation_id" RENAME TO "ix_panden_organisation_id"'
    )

    op.rename_table("projecten", "panden")
    op.alter_column(
        "maatregelen",
        "project_id",
        new_column_name="pand_id",
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
    )
    op.create_foreign_key(
        "maatregelen_pand_id_fkey",
        "maatregelen",
        "panden",
        ["pand_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_maatregelen_pand_id", "maatregelen", ["pand_id"], unique=False)
