"""Klant-facing subscription endpoints.

Backs the ``/onboarding/plan`` UI: any authenticated user can pick a
paid plan (``starter`` / ``pro``) and be redirected to a Stripe
Checkout session. Gratis and enterprise are handled entirely in the
frontend (no backend call for gratis; mailto: CTA for enterprise).

This is intentionally a separate router from ``/stripe/*`` because the
latter is still used by the legacy installateur subscription flow and
we don't want the two to collide on URLs, permissions or webhook
metadata.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.models.enums import PAID_PLANS
from app.services import stripe_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"] = Field(
        ..., description="Betaald plan: starter (€39) of pro (€99)"
    )


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


@router.post(
    "/create-checkout-session",
    response_model=CheckoutResponse,
    summary="Start Stripe Checkout voor klant-plan (starter/pro)",
)
def create_checkout_session(
    payload: CheckoutRequest,
    user: CurrentUser,
    db: DbSession,
) -> CheckoutResponse:
    if payload.plan not in PAID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Plan '{payload.plan}' is niet via Stripe af te rekenen",
        )
    try:
        result = stripe_service.create_checkout_session_for_user(
            plan=payload.plan,
            user_id=str(user.id),
            customer_email=user.email,
            existing_customer_id=user.stripe_customer_id,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover - Stripe network errors
        logger.exception("Stripe checkout session creation failed for user %s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe checkout-sessie aanmaken mislukt",
        ) from exc

    # Mark the user as pending until the webhook confirms activation.
    # This gives the /onboarding/success page something to poll.
    user.subscription_plan = payload.plan
    user.subscription_status = "pending"
    db.commit()

    return CheckoutResponse(url=result.url, session_id=result.session_id)
