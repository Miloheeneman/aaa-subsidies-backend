from __future__ import annotations

import html
import logging
from typing import Optional

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)


BRAND_GREEN = "#2d6a2d"
BRAND_GREEN_LIGHT = "#e8f5e8"


def _wrap(title: str, body_html: str) -> str:
    """Wrap body HTML in a brand-styled Dutch email shell."""
    return f"""\
<!doctype html>
<html lang="nl">
  <body style="margin:0;padding:0;background:{BRAND_GREEN_LIGHT};font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#111827;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{BRAND_GREEN_LIGHT};padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <tr>
              <td style="background:{BRAND_GREEN};padding:20px 28px;color:#ffffff;">
                <div style="font-size:13px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.85;">AAA-Lex Offices</div>
                <div style="font-size:22px;font-weight:800;margin-top:4px;">AAA-Subsidies</div>
              </td>
            </tr>
            <tr>
              <td style="padding:28px;">
                <h1 style="margin:0 0 16px 0;font-size:20px;color:#111827;">{title}</h1>
                {body_html}
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px;background:{BRAND_GREEN_LIGHT};color:#4b5563;font-size:12px;">
                U ontvangt deze e-mail omdat u zich heeft geregistreerd op
                app.aaa-lexoffices.nl. Heeft u dit niet gedaan? Dan kunt u deze
                e-mail negeren.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


def _button(label: str, url: str) -> str:
    return (
        f'<p style="margin:24px 0;">'
        f'<a href="{url}" style="display:inline-block;background:{BRAND_GREEN};'
        f"color:#ffffff;text-decoration:none;font-weight:600;padding:12px 20px;"
        f'border-radius:8px;">{label}</a>'
        f"</p>"
    )


def send_email(*, to: str, subject: str, html: str) -> None:
    """Send an email via Resend. Logs (does not raise) if not configured."""
    if not settings.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY not set; skipping email to %s subject=%r", to, subject
        )
        return

    resend.api_key = settings.RESEND_API_KEY
    from_addr = f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>"
    try:
        resend.Emails.send(
            {
                "from": from_addr,
                "to": [to],
                "subject": subject,
                "html": html,
            }
        )
    except Exception:
        logger.exception("Failed to send email to %s", to)


def send_verification_email(
    *, to: str, first_name: Optional[str], token: str
) -> None:
    verify_url = f"{settings.FRONTEND_URL.rstrip('/')}/verify-email/{token}"
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  Welkom bij AAA-Subsidies. Bevestig uw e-mailadres om uw account te
  activeren en uw subsidieaanvraag te kunnen starten.
</p>
{_button("Bevestig e-mailadres", verify_url)}
<p style="margin:0 0 12px 0;font-size:13px;color:#4b5563;">
  Werkt de knop niet? Kopieer deze link naar uw browser:<br/>
  <span style="word-break:break-all;">{verify_url}</span>
</p>
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Deze link is 24 uur geldig.
</p>
"""
    send_email(
        to=to,
        subject="Bevestig uw e-mailadres bij AAA-Subsidies",
        html=_wrap("Bevestig uw e-mailadres", body),
    )


def send_password_reset_email(
    *, to: str, first_name: Optional[str], token: str
) -> None:
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/reset-password/{token}"
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  U heeft verzocht om uw wachtwoord te herstellen. Klik op onderstaande
  knop om een nieuw wachtwoord in te stellen.
</p>
{_button("Wachtwoord herstellen", reset_url)}
<p style="margin:0 0 12px 0;font-size:13px;color:#4b5563;">
  Werkt de knop niet? Kopieer deze link naar uw browser:<br/>
  <span style="word-break:break-all;">{reset_url}</span>
</p>
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Deze link is 1 uur geldig. Heeft u dit verzoek niet gedaan? Dan kunt u
  deze e-mail negeren.
</p>
"""
    send_email(
        to=to,
        subject="Wachtwoord herstellen bij AAA-Subsidies",
        html=_wrap("Wachtwoord herstellen", body),
    )


def send_aanvraag_goedgekeurd_email(
    *,
    to: str,
    first_name: Optional[str],
    regeling: str,
    toegekende_subsidie: str,
    aaa_lex_fee: str,
    netto_uitbetaling: str,
    aanvraag_url: str,
) -> None:
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  Goed nieuws — uw subsidieaanvraag voor <strong>{regeling}</strong> is
  <strong style="color:{BRAND_GREEN};">goedgekeurd</strong>.
</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="margin:8px 0 16px 0;background:{BRAND_GREEN_LIGHT};border-radius:8px;width:100%;">
  <tr>
    <td style="padding:16px;">
      <div style="font-size:13px;color:#4b5563;">Toegekende subsidie</div>
      <div style="font-size:22px;font-weight:800;color:{BRAND_GREEN};margin-top:2px;">{toegekende_subsidie}</div>
      <hr style="border:0;border-top:1px solid #d1d5db;margin:12px 0;"/>
      <div style="display:flex;justify-content:space-between;font-size:14px;color:#374151;">
        <span>AAA-Lex fee</span>
        <strong>{aaa_lex_fee}</strong>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:14px;color:#111827;margin-top:6px;">
        <span><strong>U ontvangt netto</strong></span>
        <strong>{netto_uitbetaling}</strong>
      </div>
    </td>
  </tr>
</table>
{_button("Bekijk uw aanvraag", aanvraag_url)}
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Heeft u vragen over de uitbetaling of de fee? Neem contact op met
  AAA-Lex Offices, wij helpen u graag verder.
</p>
"""
    send_email(
        to=to,
        subject=f"Uw {regeling}-aanvraag is goedgekeurd",
        html=_wrap("Subsidieaanvraag goedgekeurd", body),
    )


def send_aanvraag_afgewezen_email(
    *,
    to: str,
    first_name: Optional[str],
    regeling: str,
    reden: str,
    aanvraag_url: str,
) -> None:
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  Helaas hebben wij uw aanvraag voor <strong>{regeling}</strong> moeten
  afwijzen.
</p>
<div style="margin:8px 0 16px 0;padding:14px 16px;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;color:#991b1b;">
  <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.06em;font-weight:600;">Reden</div>
  <div style="margin-top:4px;font-size:14px;color:#7f1d1d;">{reden}</div>
</div>
{_button("Bekijk uw aanvraag", aanvraag_url)}
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Wilt u dit bespreken of een nieuwe aanvraag voorbereiden? Neem
  contact op met AAA-Lex Offices, dan kijken wij samen naar de
  vervolgmogelijkheden.
</p>
"""
    send_email(
        to=to,
        subject=f"Uw {regeling}-aanvraag is afgewezen",
        html=_wrap("Aanvraag afgewezen", body),
    )


def _deadline_card(regeling: str, deadline_iso: str) -> str:
    return f"""\
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="margin:8px 0 16px 0;background:{BRAND_GREEN_LIGHT};border-radius:8px;width:100%;">
  <tr>
    <td style="padding:16px;">
      <div style="font-size:13px;color:#4b5563;">Regeling</div>
      <div style="font-size:18px;font-weight:800;color:{BRAND_GREEN};margin-top:2px;">{regeling}</div>
      <hr style="border:0;border-top:1px solid #d1d5db;margin:12px 0;"/>
      <div style="font-size:13px;color:#4b5563;">Deadline</div>
      <div style="font-size:18px;font-weight:800;color:#111827;margin-top:2px;">{deadline_iso}</div>
    </td>
  </tr>
</table>
"""


def send_deadline_verlopen_email(
    *,
    to: str,
    first_name: Optional[str],
    regeling: str,
    deadline_iso: str,
    aanvraag_url: str,
    days_overdue: int,
) -> None:
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  De deadline voor uw <strong>{regeling}</strong>-aanvraag was
  <strong>{deadline_iso}</strong> ({days_overdue} dagen geleden) en is
  inmiddels verlopen.
</p>
{_deadline_card(regeling, deadline_iso)}
<p style="margin:0 0 12px 0;">
  Neem direct contact op met AAA-Lex zodat we samen kunnen bekijken
  welke opties er nog zijn — voor sommige regelingen kan de aanvraag
  nog gered worden, voor andere is het van belang om snel een vervolg
  te plannen.
</p>
{_button("Bekijk uw aanvraag", aanvraag_url)}
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Heeft u vragen? Neem contact op met AAA-Lex Offices via
  noreply@aaa-lexoffices.nl of bel ons op kantoortijden.
</p>
"""
    send_email(
        to=to,
        subject="Uw subsidiedeadline is verlopen",
        html=_wrap("Subsidiedeadline verlopen", body),
    )


def send_deadline_7_dagen_email(
    *,
    to: str,
    first_name: Optional[str],
    regeling: str,
    deadline_iso: str,
    aanvraag_url: str,
) -> None:
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  Uw <strong>{regeling}</strong>-aanvraag heeft een deadline op
  <strong>{deadline_iso}</strong>. U heeft nog <strong>7 dagen</strong>
  om uw dossier compleet te maken en in te dienen.
</p>
{_deadline_card(regeling, deadline_iso)}
<p style="margin:0 0 12px 0;">
  Controleer in uw dashboard welke documenten nog ontbreken en upload
  deze zo snel mogelijk. AAA-Lex helpt u graag indien u tegen
  problemen aanloopt.
</p>
{_button("Open uw dossier", aanvraag_url)}
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Heeft u vragen? Neem contact op met AAA-Lex Offices.
</p>
"""
    send_email(
        to=to,
        subject="Nog 7 dagen: dien uw subsidieaanvraag in",
        html=_wrap("Deadline over 7 dagen", body),
    )


def send_deadline_14_dagen_email(
    *,
    to: str,
    first_name: Optional[str],
    regeling: str,
    deadline_iso: str,
    aanvraag_url: str,
) -> None:
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  Een vriendelijke herinnering: uw <strong>{regeling}</strong>-aanvraag
  heeft een deadline op <strong>{deadline_iso}</strong>. Dat is over
  <strong>14 dagen</strong>.
</p>
{_deadline_card(regeling, deadline_iso)}
<p style="margin:0 0 12px 0;">
  Plan tijd in om eventueel ontbrekende documenten te uploaden zodat
  AAA-Lex het dossier ruim voor de deadline bij RVO kan indienen.
</p>
{_button("Bekijk uw aanvraag", aanvraag_url)}
<p style="margin:16px 0 0 0;font-size:13px;color:#4b5563;">
  Heeft u vragen? Neem contact op met AAA-Lex Offices.
</p>
"""
    send_email(
        to=to,
        subject="Herinnering: subsidiedeadline over 14 dagen",
        html=_wrap("Deadline over 14 dagen", body),
    )


def send_aaa_lex_match_email(
    *,
    to: str,
    first_name: Optional[str],
    pandadres: str,
    regeling_labels: list[str],
    geschatte_totaal: Optional[str] = None,
) -> None:
    start_url = f"{settings.FRONTEND_URL.rstrip('/')}/dashboard"
    greeting = f"Beste {first_name}," if first_name else "Beste klant,"
    regelingen_line = (
        ", ".join(regeling_labels) if regeling_labels else "geen passende regelingen"
    )
    totaal_line = (
        f'<p style="margin:0 0 12px 0;">Geschatte totale subsidie: '
        f"<strong>{geschatte_totaal}</strong>.</p>"
        if geschatte_totaal
        else ""
    )
    body = f"""\
<p style="margin:0 0 12px 0;">{greeting}</p>
<p style="margin:0 0 12px 0;">
  AAA-Lex heeft uw pand op <strong>{pandadres}</strong> opgemeten.
  Op basis van deze meting komt u mogelijk in aanmerking voor:
  <strong>{regelingen_line}</strong>.
</p>
{totaal_line}
{_button("Start mijn aanvraag", start_url)}
<p style="margin:0 0 12px 0;font-size:13px;color:#4b5563;">
  U kunt via uw dashboard de aanvraag afronden en ontbrekende documenten
  uploaden. AAA-Lex begeleidt u door het hele proces.
</p>
"""
    send_email(
        to=to,
        subject="Uw subsidiemogelijkheden op basis van de AAA-Lex meting",
        html=_wrap("Subsidiekansen voor uw pand", body),
    )


def send_admin_isde_warmtepomp_intake_email(
    *,
    to: str,
    subject: str,
    pand_adres: str,
    rows_html: str,
) -> None:
    """Admin-notificatie: nieuwe ISDE warmtepomp-intake via klantwizard."""
    body = f"""\
<p style="margin:0 0 12px 0;">
  Er is een nieuwe ISDE warmtepomp-aanvraag binnengekomen via AAA-Subsidies.
</p>
<p style="margin:0 0 12px 0;">
  <strong>Pand:</strong> {html.escape(pand_adres)}
</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="margin:8px 0 0 0;width:100%;font-size:14px;color:#374151;">
  {rows_html}
</table>
<p style="margin:20px 0 0 0;font-size:13px;color:#4b5563;">
  Log in op het admin-dashboard om het dossier te bekijken en verder te
  begeleiden.
</p>
"""
    send_email(
        to=to,
        subject=subject,
        html=_wrap("Nieuwe ISDE warmtepomp aanvraag", body),
    )
