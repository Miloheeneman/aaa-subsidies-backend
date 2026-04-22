"""Resend-e-mails voor AAA-Subsidies (templates + routing).

Adressen komen uit settings (Railway):
  RESEND_FROM_EMAIL, RESEND_ADMIN_EMAIL
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, timezone
from typing import Iterable, Optional, Sequence

import resend
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User
from app.models.enums import (
    MaatregelDocumentType,
    MaatregelStatus,
    MaatregelType,
    UserRole,
)

logger = logging.getLogger(__name__)

HEADER_GREEN = "#5a9e1e"
BODY_BG = "#e8f5e8"


def deliver_resend_email(*, to: str | Sequence[str], subject: str, html: str) -> None:
    """Verstuur één HTML-mail via Resend (zelfde gedrag als legacy ``send_email``)."""
    if not settings.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY not set; skipping email subject=%r to=%r",
            subject,
            to,
        )
        return

    recipients: list[str]
    if isinstance(to, str):
        recipients = [to]
    else:
        recipients = [t for t in to if t]

    if not recipients:
        return

    resend.api_key = settings.RESEND_API_KEY
    from_addr = f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>"
    try:
        resend.Emails.send(
            {
                "from": from_addr,
                "to": recipients,
                "subject": subject,
                "html": html,
            }
        )
    except Exception:
        logger.exception("Failed to send email to %s", recipients)


def resolve_admin_recipient_emails(db: Session) -> list[str]:
    """Prioriteit: RESEND_ADMIN_EMAIL → ADMIN_NOTIFICATION_EMAIL → admin-users."""
    raw = (settings.RESEND_ADMIN_EMAIL or "").strip()
    if raw:
        return sorted({e.strip() for e in raw.split(",") if e.strip()})
    legacy = (settings.ADMIN_NOTIFICATION_EMAIL or "").strip()
    if legacy:
        return sorted({e.strip() for e in legacy.split(",") if e.strip()})
    rows = db.execute(select(User.email).where(User.role == UserRole.admin)).scalars().all()
    return sorted({e for e in rows if e})


def _cta_button(label: str, url: str) -> str:
    u = html.escape(url, quote=True)
    return (
        f'<p style="margin:24px 0;">'
        f'<a href="{u}" style="display:inline-block;background:{HEADER_GREEN};'
        f"color:#ffffff;text-decoration:none;font-weight:600;padding:12px 24px;"
        f'border-radius:8px;">{html.escape(label)}</a>'
        f"</p>"
    )


def _layout_email(*, title: str, inner_html: str) -> str:
    """AAA-Subsidies shell: groene header, witte body, footer."""
    return f"""<!doctype html>
<html lang="nl">
  <body style="margin:0;padding:0;background:{BODY_BG};font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#111827;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{BODY_BG};padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
            <tr>
              <td style="background:{HEADER_GREEN};padding:22px 28px;color:#ffffff;">
                <div style="font-size:22px;font-weight:800;letter-spacing:-0.02em;">AAA-Subsidies</div>
                <div style="font-size:12px;opacity:0.9;margin-top:4px;">AAA-Lex Offices</div>
              </td>
            </tr>
            <tr>
              <td style="padding:28px 28px 8px 28px;">
                <h1 style="margin:0 0 16px 0;font-size:20px;color:#111827;">{html.escape(title)}</h1>
                {inner_html}
              </td>
            </tr>
            <tr>
              <td style="padding:16px 28px 24px 28px;background:#f9fafb;font-size:12px;color:#6b7280;text-align:center;">
                AAA-Subsidies | AAA-Lex Offices B.V.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _status_badge_html(status: str) -> str:
    label = _maatregel_status_label_nl(status)
    return f"""<div style="display:inline-block;margin:12px 0;padding:10px 16px;background:{BODY_BG};border:1px solid #d1d5db;border-radius:8px;font-weight:700;color:#166534;">{html.escape(label)}</div>"""


def _maatregel_status_label_nl(status: str) -> str:
    return {
        "orientatie": "Oriëntatie",
        "gepland": "Gepland",
        "uitgevoerd": "Uitgevoerd",
        "aangevraagd": "Aangevraagd bij RVO",
        "in_beoordeling": "In beoordeling bij RVO",
        "goedgekeurd": "Goedgekeurd",
        "afgewezen": "Afgewezen",
    }.get(status, status)


def _status_toelichting(
    status: str, *, toegekende_euro: Optional[str] = None
) -> str:
    if status == MaatregelStatus.aangevraagd.value:
        return (
            "Wij hebben uw dossier ingediend bij RVO. U ontvangt binnen 13 weken een besluit."
        )
    if status == MaatregelStatus.goedgekeurd.value:
        bed = toegekende_euro or "—"
        return f"Gefeliciteerd! Uw subsidie van € {bed} is goedgekeurd door RVO."
    if status == MaatregelStatus.afgewezen.value:
        return (
            "Helaas is uw aanvraag niet goedgekeurd. AAA-Lex neemt contact met u op "
            "om de opties te bespreken."
        )
    if status == MaatregelStatus.in_beoordeling.value:
        return "RVO beoordeelt momenteel uw aanvraag."
    if status == MaatregelStatus.orientatie.value:
        return "Uw dossier staat in oriëntatie. Zodra er meer bekend is, informeren wij u."
    if status == MaatregelStatus.gepland.value:
        return "De maatregel is gepland. Wij houden u op de hoogte van de volgende stappen."
    if status == MaatregelStatus.uitgevoerd.value:
        return "De maatregel is uitgevoerd. Wij werken uw dossier verder af richting aanvraag."
    return "De status van uw aanvraag is bijgewerkt."


def send_template_1_admin_new_wizard(
    db: Session,
    *,
    subsidie_type: str,
    klant_naam: str,
    klant_email: str,
    project_adres: str,
    ingediend_at: datetime,
    wizard_resultaten_html: str,
    missing_doc_labels: Sequence[str],
    admin_dossier_url: str,
    urgent: bool = False,
) -> None:
    """TEMPLATE 1 — Nieuwe wizard (naar admin(s))."""
    admins = resolve_admin_recipient_emails(db)
    if not admins:
        logger.warning("No admin recipients for wizard notification")
        return

    miss = "".join(
        f"<li style='margin:4px 0;color:#b91c1c;'>✗ {html.escape(x)}</li>"
        for x in missing_doc_labels
    ) or "<li style='color:#6b7280;'>Geen verplichte documenten gemist (checklist)</li>"

    ts = ingediend_at.strftime("%d-%m-%Y %H:%M")
    inner = f"""\
<p style="margin:0 0 12px 0;line-height:1.5;">
  <strong>Klant:</strong> {html.escape(klant_naam)}<br/>
  <strong>E-mail:</strong> {html.escape(klant_email)}<br/>
  <strong>Project:</strong> {html.escape(project_adres)}<br/>
  <strong>Subsidie:</strong> {html.escape(subsidie_type)}<br/>
  <strong>Ingediend:</strong> {html.escape(ts)}
</p>
<h2 style="font-size:15px;margin:20px 0 8px 0;color:#374151;">Wizard-resultaten</h2>
<div style="font-size:14px;color:#374151;">{wizard_resultaten_html}</div>
<h2 style="font-size:15px;margin:20px 0 8px 0;color:#374151;">Missende documenten</h2>
<ul style="margin:0;padding-left:20px;">{miss}</ul>
{_cta_button("Bekijk dossier in admin →", admin_dossier_url)}
<p style="font-size:13px;color:#6b7280;">Werkt de knop niet? Kopieer deze link:<br/>
<span style="word-break:break-all;">{html.escape(admin_dossier_url)}</span></p>
"""

    prefix = "[URGENT] " if urgent else ""
    subject = f"{prefix}🔔 Nieuwe aanvraag: {subsidie_type} — {klant_naam}"
    deliver_resend_email(
        to=admins,
        subject=subject,
        html=_layout_email(title="Nieuwe aanvraag binnengekomen", inner_html=inner),
    )


def send_template_2_klant_maatregel_status(
    *,
    to: str,
    first_name: Optional[str],
    subsidie_type: str,
    project_adres: str,
    new_status: str,
    dossier_url: str,
    toegekende_subsidie: Optional[float] = None,
) -> None:
    """TEMPLATE 2 — Statusupdate maatregel (naar klant)."""
    greeting = f"Geachte {first_name}," if first_name else "Geachte relatie,"
    toe_str: Optional[str] = None
    if toegekende_subsidie is not None:
        toe_str = f"{float(toegekende_subsidie):.2f}".replace(".", ",")

    body_txt = _status_toelichting(new_status, toegekende_euro=toe_str)
    inner = f"""\
<p style="margin:0 0 12px 0;">{html.escape(greeting)}</p>
<p style="margin:0 0 12px 0;line-height:1.6;">
  De status van uw aanvraag voor <strong>{html.escape(subsidie_type)}</strong>
  voor project <strong>{html.escape(project_adres)}</strong> is bijgewerkt naar:
</p>
{_status_badge_html(new_status)}
<p style="margin:16px 0;line-height:1.6;">{html.escape(body_txt)}</p>
{_cta_button("Bekijk uw dossier →", dossier_url)}
<p style="margin:20px 0 0 0;font-size:13px;color:#6b7280;">
  Met vriendelijke groet,<br/>
  AAA-Subsidies | AAA-Lex Offices
</p>
"""

    deliver_resend_email(
        to=to,
        subject=f"Update voor uw aanvraag: {subsidie_type}",
        html=_layout_email(title="Statusupdate", inner_html=inner),
    )


def send_template_3_klant_document_upload_verzoek(
    *,
    to: str,
    first_name: Optional[str],
    subsidie_type: str,
    document_lines_html: str,
    upload_page_url: str,
    deadline_datum: Optional[date],
    optioneel_bericht: Optional[str] = None,
) -> None:
    """TEMPLATE 3 — Document-uploadverzoek (naar klant)."""
    raw_support = (settings.RESEND_ADMIN_EMAIL or "").strip()
    support_email = raw_support.split(",")[0].strip() if raw_support else ""
    support_email_e = html.escape(support_email) if support_email else ""
    greeting = f"Geachte {first_name}," if first_name else "Geachte relatie,"
    extra = ""
    if optioneel_bericht and optioneel_bericht.strip():
        extra = f"""<div style="margin:16px 0;padding:14px;background:#f3f4f6;border-radius:8px;font-size:14px;">{html.escape(optioneel_bericht.strip())}</div>"""

    dl = deadline_datum.strftime("%d-%m-%Y") if deadline_datum else "de aangegeven datum"
    mail_part = (
        f'Neem contact op via <a href="mailto:{support_email_e}" style="color:{HEADER_GREEN};font-weight:600;">{support_email_e}</a>, of '
        if support_email
        else ""
    )

    inner = f"""\
<p style="margin:0 0 12px 0;">{html.escape(greeting)}</p>
<p style="margin:0 0 12px 0;line-height:1.6;">
  Voor uw <strong>{html.escape(subsidie_type)}</strong>-aanvraag hebben wij nog de volgende documenten nodig:
</p>
<ul style="margin:0 0 16px 0;padding-left:20px;line-height:1.6;">
{document_lines_html}
</ul>
{extra}
{_cta_button("Upload documenten →", upload_page_url)}
<p style="margin:12px 0;font-size:14px;">U kunt de documenten uploaden tot <strong>{html.escape(dl)}</strong>.</p>
<p style="margin:16px 0 0 0;font-size:13px;color:#6b7280;line-height:1.5;">
  Heeft u vragen? {mail_part}bel +31 (0)70 753 00 88.
</p>
<p style="margin:20px 0 0 0;font-size:13px;color:#6b7280;">
  Met vriendelijke groet,<br/>
  AAA-Subsidies | AAA-Lex Offices
</p>
"""

    deliver_resend_email(
        to=to,
        subject="Actie vereist: documenten nodig voor uw aanvraag",
        html=_layout_email(title="Documenten nodig", inner_html=inner),
    )


def send_template_4_admin_deadline_warning(
    db: Session,
    *,
    dagen_over: int,
    klant_naam: str,
    subsidie_type: str,
    project_adres: str,
    deadline_datum: date,
    dossier_status_line: str,
    admin_dossier_url: str,
) -> None:
    """TEMPLATE 4 — Deadline waarschuwing (naar admin)."""
    admins = resolve_admin_recipient_emails(db)
    if not admins:
        return

    inner = f"""\
<p style="margin:0 0 12px 0;line-height:1.5;">
  <strong>Project:</strong> {html.escape(project_adres)}<br/>
  <strong>Klant:</strong> {html.escape(klant_naam)}<br/>
  <strong>Subsidie:</strong> {html.escape(subsidie_type)}<br/>
  <strong>Deadline:</strong> {html.escape(deadline_datum.strftime('%d-%m-%Y'))}<br/>
  <strong>Nog:</strong> {dagen_over} dagen
</p>
<p style="margin:12px 0;"><strong>Dossier status:</strong> {html.escape(dossier_status_line)}</p>
{_cta_button("Bekijk dossier →", admin_dossier_url)}
"""

    deliver_resend_email(
        to=admins,
        subject=f"⚠️ Deadline over {dagen_over} dagen: {klant_naam} — {subsidie_type}",
        html=_layout_email(title="Deadline nadert", inner_html=inner),
    )


def format_wizard_rows_table(rows: Iterable[tuple[str, Optional[str]]]) -> str:
    """Zet label/waarde-rijen om naar een simpele HTML-tabel."""
    parts = [
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="6" '
        'style="border-collapse:collapse;font-size:14px;">'
    ]
    for label, value in rows:
        v = value if value not in (None, "") else "—"
        parts.append(
            "<tr>"
            f'<td style="border-bottom:1px solid #e5e7eb;color:#6b7280;width:40%;">{html.escape(label)}</td>'
            f'<td style="border-bottom:1px solid #e5e7eb;">{html.escape(v)}</td>'
            "</tr>"
        )
    parts.append("</table>")
    return "".join(parts)


def missing_mandatory_labels_from_checklist(
    maatregel_type: MaatregelType,
    existing_doc_types: set[MaatregelDocumentType],
) -> list[str]:
    from app.services.projecten_service import get_required_documents

    out: list[str] = []
    for c in get_required_documents(maatregel_type):
        if c.verplicht and c.document_type not in existing_doc_types:
            out.append(c.label)
    return out


def _project_adres_label(project: object) -> str:
    return (
        f"{project.straat} {project.huisnummer}, {project.postcode} {project.plaats}"
    )


def notify_admins_new_wizard_maatregel(
    db: Session,
    *,
    user: User,
    project: object,
    maatregel: object,
    subsidie_type_label: str,
    wizard_rows: list[tuple[str, Optional[str]]],
    urgent: bool = False,
) -> None:
    """TEMPLATE 1 — na wizard-submit (één maatregel)."""
    from app.models import MaatregelDocument, Organisation
    from sqlalchemy import select

    org = db.get(Organisation, project.organisation_id)
    klant_naam = org.name if org else "—"
    rows = (
        db.execute(
            select(MaatregelDocument.document_type).where(
                MaatregelDocument.maatregel_id == maatregel.id
            )
        )
        .scalars()
        .all()
    )
    have = set(rows)
    missing = missing_mandatory_labels_from_checklist(maatregel.maatregel_type, have)
    wizard_html = format_wizard_rows_table(wizard_rows)
    base = (settings.FRONTEND_URL or "").rstrip("/")
    admin_url = f"{base}/admin/projecten/{project.id}/maatregelen/{maatregel.id}"
    send_template_1_admin_new_wizard(
        db,
        subsidie_type=subsidie_type_label,
        klant_naam=klant_naam,
        klant_email=user.email,
        project_adres=_project_adres_label(project),
        ingediend_at=datetime.now(timezone.utc),
        wizard_resultaten_html=wizard_html,
        missing_doc_labels=missing,
        admin_dossier_url=admin_url,
        urgent=urgent,
    )


def maatregel_subsidie_type_label(maatregel: object) -> str:
    rc = getattr(maatregel, "regeling_code", None)
    if rc is not None:
        return str(getattr(rc, "value", rc))
    mt = getattr(maatregel, "maatregel_type", None)
    if mt is not None:
        return str(getattr(mt, "value", mt))
    return "Subsidie"


def notify_klant_maatregel_status_change(
    db: Session,
    *,
    maatregel: object,
    old_status: MaatregelStatus,
    new_status: MaatregelStatus,
) -> None:
    """TEMPLATE 2 — bij gewijzigde maatregelstatus (naar primaire klantgebruiker)."""
    if old_status == new_status:
        return
    from app.models import Project, User

    project = db.get(Project, getattr(maatregel, "project_id"))
    if project is None:
        return
    org_id = getattr(project, "organisation_id", None)
    if org_id is None:
        return
    uid = db.execute(
        select(User.id)
        .where(User.organisation_id == org_id)
        .order_by(User.created_at.asc())
    ).scalar_one_or_none()
    if uid is None:
        return
    klant = db.get(User, uid)
    if klant is None or not klant.email:
        logger.warning(
            "No customer email for status update (maatregel %s)",
            getattr(maatregel, "id", None),
        )
        return
    base = (settings.FRONTEND_URL or "").rstrip("/")
    dossier_url = f"{base}/projecten/{project.id}/maatregelen/{maatregel.id}"
    toe: Optional[float] = None
    if new_status == MaatregelStatus.goedgekeurd:
        toe = getattr(maatregel, "toegekende_subsidie", None)
    send_template_2_klant_maatregel_status(
        to=klant.email,
        first_name=getattr(klant, "first_name", None),
        subsidie_type=maatregel_subsidie_type_label(maatregel),
        project_adres=_project_adres_label(project),
        new_status=new_status.value,
        dossier_url=dossier_url,
        toegekende_subsidie=toe,
    )
    from app.services import klant_notifications

    klant_notifications.notify_status_change_for_maatregel(
        db,
        organisation_id=org_id,
        project_id=project.id,
        maatregel_id=getattr(maatregel, "id"),
        subsidie_label=maatregel_subsidie_type_label(maatregel),
        new_status=new_status,
        status_label_nl=_maatregel_status_label_nl(new_status.value),
    )
