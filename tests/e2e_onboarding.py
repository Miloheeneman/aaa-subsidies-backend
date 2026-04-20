"""Live smoke test for the new klant onboarding flow.

Exercises the public parts of the flow end-to-end against a running
uvicorn without actually hitting Stripe:

1. ``POST /auth/register`` — installateur is no longer an option and
   ``organisation_name`` is optional.
2. The brand-new user lands on ``/users/me`` with the default plan
   ``gratis`` / status ``active``.
3. ``POST /subscriptions/create-checkout-session`` fails loudly (502)
   when no Stripe key is configured — the expected dev behaviour — and
   the pre-emptive "pending" flip happens only on success (i.e. is not
   applied on failure).
4. A simulated ``checkout.session.completed`` webhook upgrades the
   user's plan/status via ``metadata.user_id``.
"""
from __future__ import annotations

import json
import os
import sys
from uuid import uuid4

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_email_verification_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8769/api/v1")


def _ok(resp: httpx.Response, *expected: int) -> dict:
    if not expected:
        expected = (200,)
    if resp.status_code not in expected:
        raise AssertionError(
            f"{resp.request.method} {resp.request.url} -> {resp.status_code}\n"
            f"body: {resp.text}"
        )
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


def _register_and_verify(client: httpx.Client, email: str, *, org_name: str | None = None) -> str:
    payload = {
        "email": email,
        "password": "Welkom1234!",
        "first_name": "Ono",
        "last_name": "Boarding",
    }
    if org_name is not None:
        payload["organisation_name"] = org_name
    _ok(client.post("/auth/register", json=payload), 201)
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        token = create_email_verification_token(str(u.id))
        user_id = str(u.id)
    _ok(client.post(f"/auth/verify-email/{token}"))
    login = _ok(
        client.post(
            "/auth/login", json={"email": email, "password": "Welkom1234!"}
        )
    )
    return login["access_token"], user_id


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    # 1) Registration without organisation_name falls back to a private
    #    "{first} {last}" org and always yields role=klant.
    email_solo = f"solo+{uuid4().hex[:8]}@example.com"
    token_solo, user_id_solo = _register_and_verify(client, email_solo)
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email_solo).one()
        assert u.role == UserRole.klant, u.role
        assert u.subscription_plan == "gratis", u.subscription_plan
        assert u.subscription_status == "active", u.subscription_status
        assert u.organisation_id is not None
    print("register without org_name -> klant + gratis OK")

    # 2) /users/me returns plan + status.
    H = {"Authorization": f"Bearer {token_solo}"}
    me = _ok(client.get("/users/me", headers=H))
    assert me["user"]["subscription_plan"] == "gratis"
    assert me["user"]["subscription_status"] == "active"
    assert me["user"]["role"] == "klant"
    assert me["user"]["email"] == email_solo
    print("/users/me returns plan + status OK")

    # 3) installateur is no longer accepted as a public role: the legacy
    #    organisation_type field is ignored and the account is still
    #    created as klant.
    email_try_inst = f"wannabe+{uuid4().hex[:8]}@example.com"
    _ok(
        client.post(
            "/auth/register",
            json={
                "email": email_try_inst,
                "password": "Welkom1234!",
                "first_name": "Wannabe",
                "last_name": "Installer",
                "organisation_name": "Try Inst BV",
                "organisation_type": "installateur",
            },
        ),
        201,
    )
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email_try_inst).one()
        assert u.role == UserRole.klant, u.role
    print("installateur via register -> silently demoted to klant OK")

    # 4) /subscriptions/create-checkout-session fails loudly without Stripe
    #    credentials, and does NOT flip the user's plan.
    resp = client.post(
        "/subscriptions/create-checkout-session",
        json={"plan": "starter"},
        headers=H,
    )
    # In dev without STRIPE_SECRET_KEY + price IDs we expect 400 (price
    # not configured) or 502 (Stripe network error) — both must leave
    # the user untouched.
    assert resp.status_code in (400, 502), resp.text
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email_solo).one()
        assert u.subscription_plan == "gratis", u.subscription_plan
        assert u.subscription_status == "active", u.subscription_status
    print("checkout without Stripe creds -> refused, user untouched OK")

    # 5) Invalid plan -> 422 (pydantic Literal validation).
    resp = client.post(
        "/subscriptions/create-checkout-session",
        json={"plan": "gratis"},
        headers=H,
    )
    assert resp.status_code == 422, resp.text
    print("checkout with plan=gratis -> 422 OK")

    # 6) Stripe webhook routes via metadata.user_id → flips the right
    #    user to starter/active.
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_onboardingsmoke",
                    "metadata": {
                        "user_id": user_id_solo,
                        "plan": "starter",
                    },
                }
            },
        }
    ).encode()
    resp = client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email_solo).one()
        assert u.subscription_plan == "starter", u.subscription_plan
        assert u.subscription_status == "active", u.subscription_status
        assert u.stripe_customer_id == "cus_onboardingsmoke"
    print("webhook checkout.session.completed (user_id) -> starter/active OK")

    # 7) Cancellation via webhook drops klant back to gratis/cancelled.
    payload = json.dumps(
        {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_onboardingsmoke",
                    "metadata": {"user_id": user_id_solo},
                    "status": "canceled",
                }
            },
        }
    ).encode()
    resp = client.post(
        "/stripe/webhook",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email_solo).one()
        assert u.subscription_plan == "gratis", u.subscription_plan
        assert u.subscription_status == "cancelled", u.subscription_status
    print("webhook subscription.deleted (user_id) -> gratis/cancelled OK")

    print("\nAll onboarding tests passed")


if __name__ == "__main__":
    main()
