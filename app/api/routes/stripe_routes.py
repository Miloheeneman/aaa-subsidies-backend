"""Stripe subscription endpoints for the installateur abonnement flow.

Endpoints
---------
* ``POST /stripe/create-checkout-session`` — start a hosted checkout
* ``POST /stripe/customer-portal``         — open the Stripe billing portal
* ``GET  /stripe/subscription-status``     — current plan/status for org
* ``POST /stripe/webhook``                 — Stripe → backend event sink
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DbSession, require_installateur
from app.models import Organisation, User
from app.models.enums import OrganisationType
from app.services import stripe_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stripe", tags=["stripe"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"] = Field(
        ..., description="Abonnementsplan: starter (€49) of pro (€99)"
    )


class CheckoutResponse(BaseModel):
    url: str
    session_id: str


class PortalResponse(BaseModel):
    url: str


class SubscriptionStatusResponse(BaseModel):
    plan: Optional[str] = None
    status: Optional[str] = None
    next_billing_date: Optional[datetime] = None
    has_customer: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_installateur_org(user: User) -> Organisation:
    org = user.organisation
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geen organisatie gekoppeld aan dit account",
        )
    if org.type != OrganisationType.installateur:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Alleen installateurs kunnen een abonnement afsluiten",
        )
    return org


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


@router.post(
    "/create-checkout-session",
    response_model=CheckoutResponse,
    summary="Start Stripe Checkout voor installateur abonnement",
)
def create_checkout(
    payload: CheckoutRequest,
    db: DbSession,
    user: Annotated[User, Depends(require_installateur)],
) -> CheckoutResponse:
    org = _ensure_installateur_org(user)
    try:
        result = stripe_service.create_checkout_session(
            plan=payload.plan,
            organisation_id=str(org.id),
            customer_email=user.email,
            existing_customer_id=org.stripe_customer_id,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover - network errors surfaced to caller
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe checkout-sessie aanmaken mislukt",
        ) from exc
    return CheckoutResponse(url=result.url, session_id=result.session_id)


@router.post(
    "/customer-portal",
    response_model=PortalResponse,
    summary="Open Stripe Customer Portal voor abonnementsbeheer",
)
def customer_portal(
    db: DbSession,
    user: Annotated[User, Depends(require_installateur)],
) -> PortalResponse:
    org = _ensure_installateur_org(user)
    if not org.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Geen Stripe-klant gekoppeld aan deze organisatie",
        )
    try:
        result = stripe_service.create_customer_portal_session(
            customer_id=org.stripe_customer_id,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Stripe customer portal session creation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe portal openen mislukt",
        ) from exc
    return PortalResponse(url=result.url)


# ---------------------------------------------------------------------------
# Subscription status
# ---------------------------------------------------------------------------


@router.get(
    "/subscription-status",
    response_model=SubscriptionStatusResponse,
    summary="Huidige abonnementsstatus voor de installateur",
)
def subscription_status(
    db: DbSession,
    user: Annotated[User, Depends(require_installateur)],
) -> SubscriptionStatusResponse:
    org = _ensure_installateur_org(user)
    return SubscriptionStatusResponse(
        plan=org.subscription_plan,
        status=org.subscription_status,
        next_billing_date=getattr(org, "subscription_renews_at", None),
        has_customer=bool(org.stripe_customer_id),
    )


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


_UNSET = object()


def _apply_subscription_state(
    db,
    *,
    organisation_id: Optional[str],
    customer_id: Optional[str],
    plan=_UNSET,
    status_str=_UNSET,
) -> None:
    """Update an organisation row from a Stripe payload."""
    org: Optional[Organisation] = None
    if organisation_id:
        org = db.execute(
            select(Organisation).where(Organisation.id == organisation_id)
        ).scalar_one_or_none()
    if org is None and customer_id:
        org = db.execute(
            select(Organisation).where(
                Organisation.stripe_customer_id == customer_id
            )
        ).scalar_one_or_none()
    if org is None:
        logger.warning(
            "Stripe webhook: kon geen organisatie matchen "
            "(org_id=%s customer_id=%s)",
            organisation_id,
            customer_id,
        )
        return

    if customer_id:
        org.stripe_customer_id = customer_id
    if plan is not _UNSET:
        org.subscription_plan = plan
    if status_str is not _UNSET:
        org.subscription_status = status_str
    db.commit()


@router.post(
    "/webhook",
    summary="Stripe webhook handler (signature-verified)",
    status_code=status.HTTP_200_OK,
)
async def stripe_webhook(
    request: Request,
    db: DbSession,
    stripe_signature: Annotated[Optional[str], Header(alias="stripe-signature")] = None,
) -> dict:
    payload = await request.body()
    try:
        event = stripe_service.construct_webhook_event(payload, stripe_signature or "")
    except Exception as exc:  # signature failure or malformed
        logger.warning("Stripe webhook verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ongeldige Stripe webhook signature",
        ) from exc

    event_type = (
        event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    )
    data_obj = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else event["data"]["object"]
    )
    metadata = data_obj.get("metadata") or {}
    organisation_id = metadata.get("organisation_id")
    plan_meta = metadata.get("plan")
    customer_id = data_obj.get("customer") if isinstance(data_obj, dict) else None

    if event_type == "checkout.session.completed":
        kwargs = {"status_str": "active"}
        if plan_meta:
            kwargs["plan"] = plan_meta
        _apply_subscription_state(
            db,
            organisation_id=organisation_id,
            customer_id=customer_id,
            **kwargs,
        )
    elif event_type == "customer.subscription.updated":
        # Try to derive plan from price ID if metadata is empty.
        plan = plan_meta
        items = (data_obj.get("items") or {}).get("data") or []
        if not plan and items:
            price = items[0].get("price") or {}
            plan = stripe_service.plan_from_price_id(price.get("id"))
        new_status = data_obj.get("status")
        kwargs = {}
        if plan:
            kwargs["plan"] = plan
        if new_status:
            kwargs["status_str"] = new_status
        _apply_subscription_state(
            db,
            organisation_id=organisation_id,
            customer_id=customer_id,
            **kwargs,
        )
    elif event_type == "customer.subscription.deleted":
        _apply_subscription_state(
            db,
            organisation_id=organisation_id,
            customer_id=customer_id,
            plan=None,
            status_str="cancelled",
        )
    else:
        logger.info("Stripe webhook: ongebruikt event %s", event_type)

    return {"received": True, "type": event_type}
