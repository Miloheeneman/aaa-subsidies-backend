"""panden + maatregelen + maatregel_documenten

Revision ID: a4d7f1c20006
Revises: 9e3a2c1b0005
Create Date: 2026-04-20 19:00:00.000000+00:00

STAP 9 — panden module. Creates three tables that represent a klant's
buildings, the (subsidy-eligible) measures on them and the documents
uploaded per measure. Also adds all supporting Postgres ENUM types.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4d7f1c20006"
down_revision: Union[str, None] = "9e3a2c1b0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PAND_TYPE_VALUES = (
    "woning",
    "appartement",
    "kantoor",
    "bedrijfspand",
    "zorginstelling",
    "school",
    "sportaccommodatie",
    "overig",
)
EIGENAAR_TYPE_VALUES = (
    "eigenaar_bewoner",
    "particulier_verhuurder",
    "zakelijk_verhuurder",
    "vve",
    "overig",
)
ENERGIELABEL_VALUES = ("A", "B", "C", "D", "E", "F", "G")
MAATREGEL_TYPE_VALUES = (
    "warmtepomp_lucht_water",
    "warmtepomp_water_water",
    "warmtepomp_hybride",
    "dakisolatie",
    "gevelisolatie",
    "vloerisolatie",
    "hr_glas",
    "zonneboiler",
    "eia_investering",
    "mia_vamil_investering",
    "dumava_maatregel",
)
MAATREGEL_STATUS_VALUES = (
    "orientatie",
    "gepland",
    "uitgevoerd",
    "aangevraagd",
    "goedgekeurd",
    "afgewezen",
)
DEADLINE_TIMING_VALUES = ("na_installatie", "voor_offerte")
DEADLINE_STATUS_VALUES = ("ok", "waarschuwing", "kritiek", "verlopen")
MAATREGEL_DOCUMENT_TYPE_VALUES = (
    "factuur",
    "betaalbewijs",
    "meldcode_bewijs",
    "foto_werkzaamheden",
    "inbedrijfstelling",
    "offerte",
    "kvk_uittreksel",
    "machtiging",
    "overig",
)


def upgrade() -> None:
    pand_type = sa.Enum(*PAND_TYPE_VALUES, name="pand_type")
    eigenaar_type = sa.Enum(*EIGENAAR_TYPE_VALUES, name="eigenaar_type")
    energielabel_klasse = sa.Enum(*ENERGIELABEL_VALUES, name="energielabel_klasse")
    maatregel_type = sa.Enum(*MAATREGEL_TYPE_VALUES, name="maatregel_type")
    maatregel_status = sa.Enum(*MAATREGEL_STATUS_VALUES, name="maatregel_status")
    deadline_timing = sa.Enum(*DEADLINE_TIMING_VALUES, name="deadline_timing")
    deadline_status = sa.Enum(*DEADLINE_STATUS_VALUES, name="deadline_status")
    maatregel_document_type = sa.Enum(
        *MAATREGEL_DOCUMENT_TYPE_VALUES, name="maatregel_document_type"
    )

    bind = op.get_bind()
    for enum_ in (
        pand_type,
        eigenaar_type,
        energielabel_klasse,
        maatregel_type,
        maatregel_status,
        deadline_timing,
        deadline_status,
        maatregel_document_type,
    ):
        enum_.create(bind, checkfirst=True)

    # --- panden -----------------------------------------------------------
    op.create_table(
        "panden",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("straat", sa.String(length=255), nullable=False),
        sa.Column("huisnummer", sa.String(length=32), nullable=False),
        sa.Column("postcode", sa.String(length=16), nullable=False),
        sa.Column("plaats", sa.String(length=128), nullable=False),
        sa.Column("bouwjaar", sa.Integer(), nullable=False),
        sa.Column(
            "pand_type",
            sa.Enum(*PAND_TYPE_VALUES, name="pand_type", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "eigenaar_type",
            sa.Enum(
                *EIGENAAR_TYPE_VALUES, name="eigenaar_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "energielabel_huidig",
            sa.Enum(
                *ENERGIELABEL_VALUES,
                name="energielabel_klasse",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "energielabel_na_maatregelen",
            sa.Enum(
                *ENERGIELABEL_VALUES,
                name="energielabel_klasse",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("oppervlakte_m2", sa.Float(), nullable=True),
        sa.Column("notities", sa.Text(), nullable=True),
        sa.Column("aaa_lex_project_id", sa.UUID(), nullable=True),
        sa.Column(
            "deleted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "is_deleted",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["aaa_lex_project_id"],
            ["aaa_lex_projecten.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_panden_organisation_id", "panden", ["organisation_id"], unique=False
    )
    op.create_index("ix_panden_created_by", "panden", ["created_by"], unique=False)
    op.create_index("ix_panden_postcode", "panden", ["postcode"], unique=False)
    op.create_index(
        "ix_panden_aaa_lex_project_id",
        "panden",
        ["aaa_lex_project_id"],
        unique=False,
    )

    # --- maatregelen -----------------------------------------------------
    op.create_table(
        "maatregelen",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pand_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "maatregel_type",
            sa.Enum(
                *MAATREGEL_TYPE_VALUES,
                name="maatregel_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                *MAATREGEL_STATUS_VALUES,
                name="maatregel_status",
                create_type=False,
            ),
            server_default="orientatie",
            nullable=False,
        ),
        sa.Column("apparaat_merk", sa.String(length=128), nullable=True),
        sa.Column("apparaat_typenummer", sa.String(length=128), nullable=True),
        sa.Column("apparaat_meldcode", sa.String(length=128), nullable=True),
        sa.Column("installateur_naam", sa.String(length=255), nullable=True),
        sa.Column("installateur_kvk", sa.String(length=32), nullable=True),
        sa.Column(
            "installateur_gecertificeerd",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("installatie_datum", sa.Date(), nullable=True),
        sa.Column("offerte_datum", sa.Date(), nullable=True),
        sa.Column("investering_bedrag", sa.Float(), nullable=True),
        sa.Column("geschatte_subsidie", sa.Float(), nullable=True),
        sa.Column("toegekende_subsidie", sa.Float(), nullable=True),
        # regeling_code reuses the existing "regeling_code" ENUM created
        # in the initial migration (0001). create_type=False prevents a
        # duplicate-type error on upgrade.
        sa.Column(
            "regeling_code",
            sa.Enum(
                "ISDE",
                "EIA",
                "MIA",
                "VAMIL",
                "DUMAVA",
                name="regeling_code",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("deadline_indienen", sa.Date(), nullable=True),
        sa.Column(
            "deadline_type",
            sa.Enum(
                *DEADLINE_TIMING_VALUES,
                name="deadline_timing",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "deadline_status",
            sa.Enum(
                *DEADLINE_STATUS_VALUES,
                name="deadline_status",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pand_id"], ["panden.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_maatregelen_pand_id", "maatregelen", ["pand_id"], unique=False
    )
    op.create_index(
        "ix_maatregelen_created_by",
        "maatregelen",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_maatregelen_status", "maatregelen", ["status"], unique=False
    )
    op.create_index(
        "ix_maatregelen_regeling_code",
        "maatregelen",
        ["regeling_code"],
        unique=False,
    )
    op.create_index(
        "ix_maatregelen_deadline_status",
        "maatregelen",
        ["deadline_status"],
        unique=False,
    )
    op.create_index(
        "ix_maatregelen_apparaat_meldcode",
        "maatregelen",
        ["apparaat_meldcode"],
        unique=False,
    )

    # --- maatregel_documenten --------------------------------------------
    op.create_table(
        "maatregel_documenten",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("maatregel_id", sa.UUID(), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum(
                *MAATREGEL_DOCUMENT_TYPE_VALUES,
                name="maatregel_document_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("bestandsnaam", sa.String(length=512), nullable=False),
        sa.Column("r2_key", sa.String(length=1024), nullable=False),
        sa.Column("geupload_door", sa.UUID(), nullable=False),
        sa.Column(
            "geverifieerd_door_admin",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.Column("notities", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["maatregel_id"], ["maatregelen.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["geupload_door"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_maatregel_documenten_maatregel_id",
        "maatregel_documenten",
        ["maatregel_id"],
        unique=False,
    )
    op.create_index(
        "ix_maatregel_documenten_geupload_door",
        "maatregel_documenten",
        ["geupload_door"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_maatregel_documenten_geupload_door",
        table_name="maatregel_documenten",
    )
    op.drop_index(
        "ix_maatregel_documenten_maatregel_id",
        table_name="maatregel_documenten",
    )
    op.drop_table("maatregel_documenten")

    op.drop_index("ix_maatregelen_apparaat_meldcode", table_name="maatregelen")
    op.drop_index("ix_maatregelen_deadline_status", table_name="maatregelen")
    op.drop_index("ix_maatregelen_regeling_code", table_name="maatregelen")
    op.drop_index("ix_maatregelen_status", table_name="maatregelen")
    op.drop_index("ix_maatregelen_created_by", table_name="maatregelen")
    op.drop_index("ix_maatregelen_pand_id", table_name="maatregelen")
    op.drop_table("maatregelen")

    op.drop_index("ix_panden_aaa_lex_project_id", table_name="panden")
    op.drop_index("ix_panden_postcode", table_name="panden")
    op.drop_index("ix_panden_created_by", table_name="panden")
    op.drop_index("ix_panden_organisation_id", table_name="panden")
    op.drop_table("panden")

    for enum_name in (
        "maatregel_document_type",
        "deadline_status",
        "deadline_timing",
        "maatregel_status",
        "maatregel_type",
        "energielabel_klasse",
        "eigenaar_type",
        "pand_type",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
