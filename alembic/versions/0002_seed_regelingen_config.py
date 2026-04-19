"""seed_regelingen_config

Seeds the regelingen_config table with ISDE, EIA, MIA, VAMIL and DUMAVA
default values.

Revision ID: a8102ec2b1ac
Revises: 8952b948d5be
Create Date: 2026-04-19 15:49:49.065385+00:00
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a8102ec2b1ac"
down_revision: Union[str, None] = "8952b948d5be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REGELINGEN = [
    {
        "code": "ISDE",
        "naam": "ISDE",
        "beschrijving": (
            "Investeringssubsidie Duurzame Energie voor particulieren en "
            "zakelijke verhuurders. Subsidie voor warmtepompen, "
            "warmtepompboilers en isolatie."
        ),
        "actief": True,
        "fee_percentage": 8.00,
        "min_investering": None,
        "max_subsidie": None,
        "aanvraag_termijn_dagen": None,
    },
    {
        "code": "EIA",
        "naam": "EIA",
        "beschrijving": (
            "Energie-investeringsaftrek voor ondernemers. Fiscaal voordeel "
            "van 45,5% van de investering. LET OP: aanvragen binnen 3 maanden "
            "na ondertekening offerte."
        ),
        "actief": True,
        "fee_percentage": 5.00,
        "min_investering": 2500.00,
        "max_subsidie": None,
        "aanvraag_termijn_dagen": 90,
    },
    {
        "code": "MIA",
        "naam": "MIA",
        "beschrijving": (
            "Milieu-investeringsaftrek voor ondernemers. Fiscaal voordeel "
            "van 27-45% afhankelijk van categorie. Altijd combineren met "
            "Vamil. Aanvragen binnen 3 maanden na offerte."
        ),
        "actief": True,
        "fee_percentage": 5.00,
        "min_investering": 2500.00,
        "max_subsidie": None,
        "aanvraag_termijn_dagen": 90,
    },
    {
        "code": "VAMIL",
        "naam": "Vamil",
        "beschrijving": (
            "Willekeurige afschrijving milieu-investeringen. 75% van de "
            "investering willekeurig afschrijven voor liquiditeitsvoordeel. "
            "Altijd samen met MIA aanvragen."
        ),
        "actief": True,
        "fee_percentage": 4.00,
        "min_investering": 2500.00,
        "max_subsidie": None,
        "aanvraag_termijn_dagen": 90,
    },
    {
        "code": "DUMAVA",
        "naam": "DUMAVA",
        "beschrijving": (
            "Subsidie Duurzaam Maatschappelijk Vastgoed. Tot 30% subsidie "
            "voor verduurzaming van maatschappelijk vastgoed (zorg, "
            "onderwijs, sport, gemeenten). Minimaal 2 maatregelen waarvan "
            "1 erkend."
        ),
        "actief": True,
        "fee_percentage": 10.00,
        "min_investering": None,
        "max_subsidie": None,
        "aanvraag_termijn_dagen": None,
    },
]


def upgrade() -> None:
    regelingen = sa.table(
        "regelingen_config",
        sa.column("id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.Enum(name="regeling_code", create_type=False)),
        sa.column("naam", sa.String),
        sa.column("beschrijving", sa.Text),
        sa.column("actief", sa.Boolean),
        sa.column("fee_percentage", sa.Numeric),
        sa.column("min_investering", sa.Numeric),
        sa.column("max_subsidie", sa.Numeric),
        sa.column("aanvraag_termijn_dagen", sa.Integer),
    )

    rows = [{"id": uuid.uuid4(), **r} for r in REGELINGEN]
    op.bulk_insert(regelingen, rows)


def downgrade() -> None:
    codes = ", ".join(f"'{r['code']}'" for r in REGELINGEN)
    op.execute(f"DELETE FROM regelingen_config WHERE code IN ({codes})")
