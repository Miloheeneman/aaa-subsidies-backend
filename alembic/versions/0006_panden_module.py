"""panden module: panden + maatregelen + maatregel_documenten

Revision ID: b4f7d2a80006
Revises: 9e3a2c1b0005
Create Date: 2026-04-25 10:00:00.000000+00:00

Introduces the klant-facing panden-module: klanten kunnen
panden registreren, daar maatregelen aan hangen en per maatregel
documenten uploaden. ``regeling_code`` gebruikt hergebruikt het
bestaande ``regeling_code`` Postgres-enum uit 0001.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4f7d2a80006"
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
ENERGIELABEL_HUIDIG_VALUES = ("A", "B", "C", "D", "E", "F", "G")
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
MAATREGEL_DEADLINE_TYPE_VALUES = ("na_installatie", "voor_offerte")
MAATREGEL_DEADLINE_STATUS_VALUES = ("ok", "waarschuwing", "kritiek", "verlopen")
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
    energielabel_huidig = sa.Enum(
        *ENERGIELABEL_HUIDIG_VALUES, name="energielabel_huidig"
    )
    energielabel_na = sa.Enum(
        *ENERGIELABEL_HUIDIG_VALUES, name="energielabel_na_maatregelen"
    )
    maatregel_type = sa.Enum(*MAATREGEL_TYPE_VALUES, name="maatregel_type")
    maatregel_status = sa.Enum(*MAATREGEL_STATUS_VALUES, name="maatregel_status")
    deadline_type_enum = sa.Enum(
        *MAATREGEL_DEADLINE_TYPE_VALUES, name="maatregel_deadline_type"
    )
    deadline_status_enum = sa.Enum(
        *MAATREGEL_DEADLINE_STATUS_VALUES, name="maatregel_deadline_status"
    )
    maatregel_document_type = sa.Enum(
        *MAATREGEL_DOCUMENT_TYPE_VALUES, name="maatregel_document_type"
    )

    op.create_table(
        "panden",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "organisation_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("straat", sa.String(length=255), nullable=False),
        sa.Column("huisnummer", sa.String(length=32), nullable=False),
        sa.Column("postcode", sa.String(length=16), nullable=False),
        sa.Column("plaats", sa.String(length=128), nullable=False),
        sa.Column("bouwjaar", sa.Integer(), nullable=False),
        sa.Column("pand_type", pand_type, nullable=False),
        sa.Column("eigenaar_type", eigenaar_type, nullable=False),
        sa.Column("energielabel_huidig", energielabel_huidig, nullable=True),
        sa.Column(
            "energielabel_na_maatregelen", energielabel_na, nullable=True
        ),
        sa.Column("oppervlakte_m2", sa.Float(), nullable=True),
        sa.Column("notities", sa.Text(), nullable=True),
        sa.Column("aaa_lex_project_id", sa.UUID(), nullable=True),
        sa.Column(
            "deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
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
            ["organisation_id"],
            ["organisations.id"],
            ondelete="CASCADE",
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
        "ix_panden_organisation_id", "panden", ["organisation_id"]
    )
    op.create_index("ix_panden_created_by", "panden", ["created_by"])
    op.create_index("ix_panden_postcode", "panden", ["postcode"])
    op.create_index("ix_panden_deleted", "panden", ["deleted"])
    op.create_index(
        "ix_panden_aaa_lex_project_id",
        "panden",
        ["aaa_lex_project_id"],
    )

    op.create_table(
        "maatregelen",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("pand_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("maatregel_type", maatregel_type, nullable=False),
        sa.Column("omschrijving", sa.Text(), nullable=True),
        sa.Column(
            "status",
            maatregel_status,
            server_default="orientatie",
            nullable=False,
        ),
        sa.Column("apparaat_merk", sa.String(length=128), nullable=True),
        sa.Column(
            "apparaat_typenummer", sa.String(length=128), nullable=True
        ),
        sa.Column("apparaat_meldcode", sa.String(length=64), nullable=True),
        sa.Column("installateur_naam", sa.String(length=255), nullable=True),
        sa.Column("installateur_kvk", sa.String(length=32), nullable=True),
        sa.Column(
            "installateur_gecertificeerd",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("installatie_datum", sa.Date(), nullable=True),
        sa.Column("offerte_datum", sa.Date(), nullable=True),
        sa.Column("investering_bedrag", sa.Float(), nullable=True),
        sa.Column("geschatte_subsidie", sa.Float(), nullable=True),
        sa.Column("toegekende_subsidie", sa.Float(), nullable=True),
        # Hergebruikt het bestaande regeling_code enum uit 0001.
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
        sa.Column("deadline_type", deadline_type_enum, nullable=True),
        sa.Column("deadline_status", deadline_status_enum, nullable=True),
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
    op.create_index("ix_maatregelen_pand_id", "maatregelen", ["pand_id"])
    op.create_index(
        "ix_maatregelen_created_by", "maatregelen", ["created_by"]
    )
    op.create_index(
        "ix_maatregelen_maatregel_type", "maatregelen", ["maatregel_type"]
    )
    op.create_index("ix_maatregelen_status", "maatregelen", ["status"])
    op.create_index(
        "ix_maatregelen_apparaat_meldcode",
        "maatregelen",
        ["apparaat_meldcode"],
    )
    op.create_index(
        "ix_maatregelen_regeling_code", "maatregelen", ["regeling_code"]
    )
    op.create_index(
        "ix_maatregelen_deadline_indienen",
        "maatregelen",
        ["deadline_indienen"],
    )
    op.create_index(
        "ix_maatregelen_deadline_status",
        "maatregelen",
        ["deadline_status"],
    )

    op.create_table(
        "maatregel_documenten",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("maatregel_id", sa.UUID(), nullable=False),
        sa.Column("document_type", maatregel_document_type, nullable=False),
        sa.Column("bestandsnaam", sa.String(length=512), nullable=False),
        sa.Column("r2_key", sa.String(length=1024), nullable=False),
        sa.Column("geupload_door", sa.UUID(), nullable=False),
        sa.Column(
            "geverifieerd_door_admin",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
    )


def downgrade() -> None:
    op.drop_index(
        "ix_maatregel_documenten_maatregel_id",
        table_name="maatregel_documenten",
    )
    op.drop_table("maatregel_documenten")

    op.drop_index("ix_maatregelen_deadline_status", table_name="maatregelen")
    op.drop_index(
        "ix_maatregelen_deadline_indienen", table_name="maatregelen"
    )
    op.drop_index("ix_maatregelen_regeling_code", table_name="maatregelen")
    op.drop_index(
        "ix_maatregelen_apparaat_meldcode", table_name="maatregelen"
    )
    op.drop_index("ix_maatregelen_status", table_name="maatregelen")
    op.drop_index("ix_maatregelen_maatregel_type", table_name="maatregelen")
    op.drop_index("ix_maatregelen_created_by", table_name="maatregelen")
    op.drop_index("ix_maatregelen_pand_id", table_name="maatregelen")
    op.drop_table("maatregelen")

    op.drop_index("ix_panden_aaa_lex_project_id", table_name="panden")
    op.drop_index("ix_panden_deleted", table_name="panden")
    op.drop_index("ix_panden_postcode", table_name="panden")
    op.drop_index("ix_panden_created_by", table_name="panden")
    op.drop_index("ix_panden_organisation_id", table_name="panden")
    op.drop_table("panden")

    bind = op.get_bind()
    for enum_name in (
        "maatregel_document_type",
        "maatregel_deadline_status",
        "maatregel_deadline_type",
        "maatregel_status",
        "maatregel_type",
        "energielabel_na_maatregelen",
        "energielabel_huidig",
        "eigenaar_type",
        "pand_type",
    ):
        sa.Enum(name=enum_name).drop(bind, checkfirst=True)
