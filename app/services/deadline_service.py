"""Deadline warning system.

Iterates over every active aanvraag with a deadline and sends a single
warning email per applicable bucket (verlopen / 7 dagen / 14 dagen),
recording the date so we don't spam — but allowing weekly reminders
once ``last_deadline_warning_sent`` is older than 6 days.

Designed to be invoked from:
* the ``POST /api/v1/admin/run-deadline-check`` endpoint, and
* a scheduled GitHub Actions workflow (see
  ``.github/workflows/deadline-check.yml``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models import Maatregel, Project, SubsidieAanvraag
from app.models.enums import MaatregelStatus
from app.models.enums import AanvraagStatus
from app.services.email import (
    send_deadline_7_dagen_email,
    send_deadline_14_dagen_email,
    send_deadline_verlopen_email,
)

logger = logging.getLogger(__name__)

# Re-send warnings at most once a week so a long-running deadline keeps
# getting reminders without flooding the inbox.
WEEKLY_COOLDOWN_DAYS = 6


@dataclass
class DeadlineRunResult:
    checked: int = 0
    warnings_sent: int = 0
    expired: int = 0
    skipped_recent: int = 0
    skipped_no_contact: int = 0


def _frontend_aanvraag_url(aanvraag_id) -> str:
    base = (settings.FRONTEND_URL or "http://localhost:5173").rstrip("/")
    return f"{base}/aanvraag/{aanvraag_id}"


def _bucket_for(days_remaining: int) -> Optional[str]:
    """Return which warning bucket the deadline currently belongs to.

    Buckets are evaluated in priority order — verlopen first, then the
    nearest deadline window. ``None`` means no warning is needed yet.
    """
    if days_remaining <= 0:
        return "verlopen"
    if days_remaining <= 7:
        return "7d"
    if days_remaining <= 14:
        return "14d"
    return None


def _send_warning(aanvraag: SubsidieAanvraag, bucket: str, today: date) -> bool:
    """Dispatch the right email template for ``bucket``.

    Returns True if the email layer accepted the send. Resend errors are
    swallowed by ``send_email``; we still mark the warning as sent so we
    don't retry every minute.
    """
    contact = aanvraag.aanvrager
    if contact is None:
        return False
    deadline_iso = aanvraag.deadline_datum.strftime("%d-%m-%Y")
    aanvraag_url = _frontend_aanvraag_url(aanvraag.id)
    regeling = aanvraag.regeling.value

    if bucket == "verlopen":
        days_overdue = (today - aanvraag.deadline_datum).days
        send_deadline_verlopen_email(
            to=contact.email,
            first_name=contact.first_name,
            regeling=regeling,
            deadline_iso=deadline_iso,
            aanvraag_url=aanvraag_url,
            days_overdue=days_overdue,
        )
    elif bucket == "7d":
        send_deadline_7_dagen_email(
            to=contact.email,
            first_name=contact.first_name,
            regeling=regeling,
            deadline_iso=deadline_iso,
            aanvraag_url=aanvraag_url,
        )
    elif bucket == "14d":
        send_deadline_14_dagen_email(
            to=contact.email,
            first_name=contact.first_name,
            regeling=regeling,
            deadline_iso=deadline_iso,
            aanvraag_url=aanvraag_url,
        )
    else:
        return False
    return True


def check_all_deadlines(
    db: Session, *, today: Optional[date] = None
) -> DeadlineRunResult:
    """Scan every active aanvraag and send warnings where appropriate."""
    today = today or date.today()
    result = DeadlineRunResult()

    aanvragen = (
        db.execute(
            select(SubsidieAanvraag)
            .options(selectinload(SubsidieAanvraag.aanvrager))
            .where(
                and_(
                    SubsidieAanvraag.deadline_datum.is_not(None),
                    SubsidieAanvraag.status.notin_(
                        [AanvraagStatus.goedgekeurd, AanvraagStatus.afgewezen]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )

    cooldown_cutoff = today - timedelta(days=WEEKLY_COOLDOWN_DAYS)

    for a in aanvragen:
        result.checked += 1
        days_remaining = (a.deadline_datum - today).days
        bucket = _bucket_for(days_remaining)
        if bucket is None:
            continue
        if bucket == "verlopen":
            result.expired += 1

        if (
            a.last_deadline_warning_sent is not None
            and a.last_deadline_warning_sent > cooldown_cutoff
        ):
            result.skipped_recent += 1
            continue

        if a.aanvrager is None:
            result.skipped_no_contact += 1
            continue

        try:
            sent = _send_warning(a, bucket, today)
        except Exception:  # pragma: no cover - logged + swallowed
            logger.exception(
                "Failed to dispatch deadline warning for aanvraag %s", a.id
            )
            sent = False

        if sent:
            a.last_deadline_warning_sent = today
            result.warnings_sent += 1

    db.commit()
    return result


@dataclass
class MaatregelAdminDeadlineResult:
    checked: int = 0
    emails_sent: int = 0


def check_maatregel_deadlines_admin(
    db: Session, *, today: Optional[date] = None
) -> MaatregelAdminDeadlineResult:
    """Stuur TEMPLATE 4 naar admins op 30 / 14 / 7 dagen vóór maatregel-deadline."""
    from app.services.email_service import send_template_4_admin_deadline_warning
    from app.services.projecten_service import verplichte_documenten_telling

    today = today or date.today()
    now = datetime.now(timezone.utc)
    res = MaatregelAdminDeadlineResult()

    rows = (
        db.execute(
            select(Maatregel)
            .join(Project, Maatregel.project_id == Project.id)
            .where(Project.is_deleted.is_(False))
            .where(Maatregel.deadline_indienen.is_not(None))
            .where(
                Maatregel.status.notin_(
                    [MaatregelStatus.goedgekeurd, MaatregelStatus.afgewezen]
                )
            )
            .options(
                selectinload(Maatregel.project).selectinload(Project.organisation),
            )
        )
        .scalars()
        .all()
    )

    for m in rows:
        res.checked += 1
        if m.deadline_indienen is None:
            continue
        d = (m.deadline_indienen - today).days
        project = m.project
        if project is None:
            continue
        org = project.organisation
        klant_naam = org.name if org else "—"
        reg = m.regeling_code.value if m.regeling_code else "—"
        adres = (
            f"{project.straat} {project.huisnummer}, {project.postcode} {project.plaats}"
        )
        tot, up = verplichte_documenten_telling(db, m)
        status_line = f"{up}/{tot} verplichte documenten aanwezig"
        base = (settings.FRONTEND_URL or "").rstrip("/")
        admin_url = f"{base}/admin/projecten/{project.id}/maatregelen/{m.id}"

        try:
            if d == 30 and m.deadline_admin_mail_30_sent_at is None:
                send_template_4_admin_deadline_warning(
                    db,
                    dagen_over=30,
                    klant_naam=klant_naam,
                    subsidie_type=reg,
                    project_adres=adres,
                    deadline_datum=m.deadline_indienen,
                    dossier_status_line=status_line,
                    admin_dossier_url=admin_url,
                )
                m.deadline_admin_mail_30_sent_at = now
                res.emails_sent += 1
            elif d == 14 and m.deadline_admin_mail_14_sent_at is None:
                send_template_4_admin_deadline_warning(
                    db,
                    dagen_over=14,
                    klant_naam=klant_naam,
                    subsidie_type=reg,
                    project_adres=adres,
                    deadline_datum=m.deadline_indienen,
                    dossier_status_line=status_line,
                    admin_dossier_url=admin_url,
                )
                m.deadline_admin_mail_14_sent_at = now
                res.emails_sent += 1
            elif d == 7 and m.deadline_admin_mail_7_sent_at is None:
                send_template_4_admin_deadline_warning(
                    db,
                    dagen_over=7,
                    klant_naam=klant_naam,
                    subsidie_type=reg,
                    project_adres=adres,
                    deadline_datum=m.deadline_indienen,
                    dossier_status_line=status_line,
                    admin_dossier_url=admin_url,
                )
                m.deadline_admin_mail_7_sent_at = now
                res.emails_sent += 1
        except Exception:  # pragma: no cover
            logger.exception(
                "Failed maatregel admin deadline mail for maatregel %s", m.id
            )

    db.commit()
    return res
