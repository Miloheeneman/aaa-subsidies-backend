"""Gedeelde KPI-queries voor het admin-portal (één bron, één route)."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Maatregel, Organisation, Project
from app.models.enums import (
    DeadlineStatus,
    MaatregelStatus,
    OrganisationType,
)
from app.schemas.admin_portal import AdminPortalStats


def compute_admin_portal_stats(db: Session) -> AdminPortalStats:
    today = date.today()
    start = datetime.combine(
        today.replace(day=1), datetime.min.time(), tzinfo=timezone.utc
    )

    totaal_klanten = int(
        db.execute(
            select(func.count())
            .select_from(Organisation)
            .where(Organisation.type == OrganisationType.klant)
        ).scalar_one()
    )
    projecten_deze_maand = int(
        db.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.created_at >= start, Project.is_deleted.is_(False))
        ).scalar_one()
    )
    openstaande_dossiers = int(
        db.execute(
            select(func.count())
            .select_from(Maatregel)
            .where(
                Maatregel.status.notin_(
                    [MaatregelStatus.goedgekeurd, MaatregelStatus.afgewezen]
                ),
                or_(
                    Maatregel.deadline_status.in_(
                        [
                            DeadlineStatus.kritiek,
                            DeadlineStatus.verlopen,
                            DeadlineStatus.waarschuwing,
                        ]
                    ),
                    Maatregel.status == MaatregelStatus.orientatie,
                ),
            )
        ).scalar_one()
    )
    ingediend_deze_maand = int(
        db.execute(
            select(func.count())
            .select_from(Maatregel)
            .where(
                Maatregel.status.in_(
                    [
                        MaatregelStatus.aangevraagd,
                        MaatregelStatus.in_beoordeling,
                    ]
                ),
                Maatregel.updated_at >= start,
            )
        ).scalar_one()
    )

    return AdminPortalStats(
        totaal_klanten=totaal_klanten,
        projecten_deze_maand=projecten_deze_maand,
        openstaande_dossiers=openstaande_dossiers,
        ingediend_deze_maand=ingediend_deze_maand,
    )
