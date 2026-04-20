"""Thin wrapper around the Stripe SDK.

This module isolates Stripe network calls behind small functions so the
installateur subscription flow stays testable and so we can stub Stripe
in development / CI when ``STRIPE_SECRET_KEY`` is not configured.

Plans
-----
* ``starter`` — €49/month, up to 10 active dossiers
* ``pro``     — €99/month, unlimited dossiers
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import stripe

from app.core.config import settings

logger = logging.getLogger(__name__)


PLAN_STARTER = "starter"
PLAN_PRO = "pro"
ALLOWED_PLANS = {PLAN_STARTER, PLAN_PRO}

PLAN_LABELS = {
    PLAN_STARTER: "Starter",
    PLAN_PRO: "Pro",
}
PLAN_PRICES_EUR = {
    PLAN_STARTER: 49,
    PLAN_PRO: 99,
}


@dataclass
class CheckoutSessionResult:
    url: str
    session_id: str


@dataclass
class PortalSessionResult:
    url: str


def _stripe_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def init_stripe() -> None:
    """Configure the Stripe SDK from environment settings."""
    if not _stripe_configured():
        # Allow the app to boot in dev / CI without Stripe credentials.
        return
    stripe.api_key = settings.STRIPE_SECRET_KEY


def price_id_for_plan(plan: str) -> str:
    # Accept three naming schemes so Railway / Vercel env-var config
    # from any of the product iterations keeps working:
    #   STRIPE_PRICE_STARTER / STRIPE_PRICE_PRO   (current spec)
    #   STRIPE_STARTER_PRICE_ID / STRIPE_PRO_PRICE_ID
    #   STRIPE_PRICE_BASIC / STRIPE_PRICE_PRO     (first iteration)
    if plan == PLAN_STARTER:
        return (
            settings.STRIPE_PRICE_STARTER
            or settings.STRIPE_STARTER_PRICE_ID
            or settings.STRIPE_PRICE_BASIC
        )
    if plan == PLAN_PRO:
        return settings.STRIPE_PRO_PRICE_ID or settings.STRIPE_PRICE_PRO
    raise ValueError(f"Onbekend abonnementsplan: {plan}")


def _frontend_url(path: str) -> str:
    base = (settings.FRONTEND_URL or "http://localhost:5173").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def create_checkout_session(
    *,
    plan: str,
    organisation_id: str,
    customer_email: str,
    existing_customer_id: Optional[str] = None,
) -> CheckoutSessionResult:
    """Create a Stripe Checkout session for the given plan.

    The ``organisation_id`` is attached to ``metadata`` so the webhook
    handler can credit the right tenant when the subscription becomes
    active.
    """
    if plan not in ALLOWED_PLANS:
        raise ValueError(f"Onbekend abonnementsplan: {plan}")

    init_stripe()
    price_id = price_id_for_plan(plan)
    if not price_id:
        raise RuntimeError(
            f"Stripe price ID voor plan '{plan}' is niet geconfigureerd"
        )

    success_url = _frontend_url(
        "/installateur/abonnement?success=true&session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = _frontend_url("/installateur/abonnement?cancelled=true")

    kwargs = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {
            "organisation_id": organisation_id,
            "plan": plan,
        },
        "subscription_data": {
            "metadata": {
                "organisation_id": organisation_id,
                "plan": plan,
            },
        },
        "allow_promotion_codes": True,
    }
    if existing_customer_id:
        kwargs["customer"] = existing_customer_id
    else:
        kwargs["customer_email"] = customer_email
        kwargs["customer_creation"] = "always"

    session = stripe.checkout.Session.create(**kwargs)
    return CheckoutSessionResult(url=session.url, session_id=session.id)


def create_checkout_session_for_user(
    *,
    plan: str,
    user_id: str,
    customer_email: str,
    existing_customer_id: Optional[str] = None,
) -> CheckoutSessionResult:
    """Create a Stripe Checkout session for a klant-level subscription.

    Variant of :func:`create_checkout_session` that tags the session
    with ``user_id`` metadata (instead of ``organisation_id``) and
    redirects back to the onboarding success / plan-picker pages. The
    Stripe webhook routes these events based on which metadata key is
    present — see :mod:`app.api.routes.stripe_routes`.
    """
    if plan not in ALLOWED_PLANS:
        raise ValueError(f"Onbekend abonnementsplan: {plan}")

    init_stripe()
    price_id = price_id_for_plan(plan)
    if not price_id:
        raise RuntimeError(
            f"Stripe price ID voor plan '{plan}' is niet geconfigureerd"
        )

    success_url = _frontend_url(
        "/onboarding/success?session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = _frontend_url("/onboarding/plan?cancelled=true")

    kwargs = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"user_id": user_id, "plan": plan},
        "subscription_data": {
            "metadata": {"user_id": user_id, "plan": plan},
        },
        "allow_promotion_codes": True,
    }
    if existing_customer_id:
        kwargs["customer"] = existing_customer_id
    else:
        kwargs["customer_email"] = customer_email
        kwargs["customer_creation"] = "always"

    session = stripe.checkout.Session.create(**kwargs)
    return CheckoutSessionResult(url=session.url, session_id=session.id)


def create_customer_portal_session(
    *, customer_id: str, return_path: str = "/installateur/abonnement"
) -> PortalSessionResult:
    init_stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=_frontend_url(return_path),
    )
    return PortalSessionResult(url=session.url)


def construct_webhook_event(payload: bytes, sig_header: str):
    """Verify + parse a webhook payload using Stripe's signing secret."""
    init_stripe()
    if not settings.STRIPE_WEBHOOK_SECRET:
        # Without a webhook secret we can't safely verify signatures;
        # fall back to JSON parsing so local development still works.
        logger.warning("STRIPE_WEBHOOK_SECRET is not set; skipping signature check")
        import json
        return json.loads(payload.decode("utf-8"))
    return stripe.Webhook.construct_event(
        payload=payload,
        sig_header=sig_header,
        secret=settings.STRIPE_WEBHOOK_SECRET,
    )


def plan_from_price_id(price_id: Optional[str]) -> Optional[str]:
    """Reverse-map a price ID to our internal plan code."""
    if not price_id:
        return None
    starter_ids = {
        settings.STRIPE_PRICE_STARTER,
        settings.STRIPE_STARTER_PRICE_ID,
        settings.STRIPE_PRICE_BASIC,
    }
    pro_ids = {settings.STRIPE_PRO_PRICE_ID, settings.STRIPE_PRICE_PRO}
    if price_id in starter_ids:
        return PLAN_STARTER
    if price_id in pro_ids:
        return PLAN_PRO
    return None
