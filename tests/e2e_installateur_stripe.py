"""Live smoke test for the installateur dashboard + Stripe webhook flow.

We don't hit the real Stripe API; instead the test:

1. Verifies all installateur endpoints are subscription-gated (402 / 403
   for the wrong roles, 200 once the org is marked active).
2. Drives the full lead lifecycle (nieuw → contact_opgenomen → gewonnen)
   and asserts that lead unlocking, dossier visibility and stats counters
   all behave correctly.
3. Posts simulated Stripe webhook events directly at
   ``/stripe/webhook`` (no signing secret in dev) to flip the
   organisation's subscription state, including cancellation.
4. Asserts the Stripe checkout / customer-portal endpoints fail loudly
   when no Stripe key is configured (the expected dev behaviour).
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
from app.models import (  # noqa: E402
    AAALexProject,
    InstallateurLead,
    Organisation,
    SubsidieAanvraag,
    User,
)
from app.models.enums import (  # noqa: E402
    AanvraagStatus,
    LeadStatus,
    Maatregel,
    OrganisationType,
    RegelingCode,
    TypeAanvrager,
    UserRole,
)

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


def register(client, email: str, *, org_type: str = "klant") -> str:
    _ok(
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "Welkom1234!",
                "first_name": "Test",
                "last_name": "User",
                "phone": "+31612345678",
                "organisation_name": f"Org {email}",
                "organisation_type": org_type,
            },
        ),
        201,
    )
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        token = create_email_verification_token(str(u.id))
    _ok(client.post(f"/auth/verify-email/{token}"))
    return _ok(
        client.post(
            "/auth/login", json={"email": email, "password": "Welkom1234!"}
        )
    )["access_token"]


def org_id_for(email: str) -> str:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        return str(u.organisation_id)


def set_subscription(email: str, *, plan: str | None, status: str | None) -> None:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        org = db.query(Organisation).filter(Organisation.id == u.organisation_id).one()
        org.subscription_plan = plan
        org.subscription_status = status
        db.commit()


def set_stripe_customer(email: str, customer_id: str) -> None:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        org = db.query(Organisation).filter(Organisation.id == u.organisation_id).one()
        org.stripe_customer_id = customer_id
        db.commit()


def get_org_state(email: str) -> tuple[str | None, str | None, str | None]:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        org = db.query(Organisation).filter(Organisation.id == u.organisation_id).one()
        return org.subscription_plan, org.subscription_status, org.stripe_customer_id


def _seed_lead(installateur_email: str, klant_email: str) -> tuple[str, str]:
    """Create a klant-owned aanvraag + AAA-Lex pand + a fresh lead pointing
    at the installateur. Returns (aanvraag_id, lead_id)."""
    with SessionLocal() as db:
        installateur_user = (
            db.query(User).filter(User.email == installateur_email).one()
        )
        klant_user = db.query(User).filter(User.email == klant_email).one()
        aanvraag = SubsidieAanvraag(
            organisation_id=klant_user.organisation_id,
            aanvrager_id=klant_user.id,
            regeling=RegelingCode.ISDE,
            type_aanvrager=TypeAanvrager.particulier,
            status=AanvraagStatus.documenten,
            maatregel=Maatregel.warmtepomp,
        )
        db.add(aanvraag)
        db.flush()
        project = AAALexProject(
            external_reference=f"REF-{uuid4().hex[:6]}",
            organisation_id=klant_user.organisation_id,
            aanvraag_id=aanvraag.id,
            pandadres="Hoofdstraat 1",
            postcode="1011AB",
            plaats="Amsterdam",
        )
        lead = InstallateurLead(
            installateur_id=installateur_user.organisation_id,
            aanvraag_id=aanvraag.id,
            status=LeadStatus.nieuw,
            regio="Amsterdam",
        )
        db.add_all([project, lead])
        db.commit()
        return str(aanvraag.id), str(lead.id)


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    inst_email = f"inst+{uuid4().hex[:8]}@example.com"
    klant_email = f"klant+{uuid4().hex[:8]}@example.com"

    inst_token = register(client, inst_email, org_type="installateur")
    klant_token = register(client, klant_email, org_type="klant")

    H_INST = {"Authorization": f"Bearer {inst_token}"}
    H_KLANT = {"Authorization": f"Bearer {klant_token}"}

    inst_org_id = org_id_for(inst_email)

    # -----------------------------------------------------------------
    # 1) Klant cannot reach installateur endpoints (role gate)
    # -----------------------------------------------------------------
    forbidden = client.get("/installateur/stats", headers=H_KLANT)
    assert forbidden.status_code == 403, forbidden.text
    print("klant -> /installateur/stats -> 403 OK")

    # Anonymous → 401
    anon = client.get("/installateur/stats")
    assert anon.status_code == 401, anon.text
    print("anon -> /installateur/stats -> 401 OK")

    # -----------------------------------------------------------------
    # 2) Stats works without a subscription (banner data)
    # -----------------------------------------------------------------
    stats = _ok(client.get("/installateur/stats", headers=H_INST))
    assert stats == {
        "active_leads": 0,
        "won_leads": 0,
        "active_dossiers": 0,
        "subscription_plan": None,
        "subscription_status": None,
    }
    print("stats without subscription OK")

    # -----------------------------------------------------------------
    # 3) Leads + dossiers are 402-gated when no active subscription
    # -----------------------------------------------------------------
    locked = client.get("/installateur/leads", headers=H_INST)
    assert locked.status_code == 402, locked.text
    assert "abonnement" in locked.json().get("detail", "").lower()
    locked2 = client.get("/installateur/dossiers", headers=H_INST)
    assert locked2.status_code == 402, locked2.text
    print("leads/dossiers 402 without subscription OK")

    # subscription-status reflects the empty state
    sub = _ok(client.get("/stripe/subscription-status", headers=H_INST))
    assert sub == {
        "plan": None,
        "status": None,
        "next_billing_date": None,
        "has_customer": False,
    }
    print("/stripe/subscription-status (empty) OK")

    # -----------------------------------------------------------------
    # 4) Stripe checkout fails loudly when no STRIPE_SECRET_KEY / price
    # -----------------------------------------------------------------
    bad_plan = client.post(
        "/stripe/create-checkout-session",
        json={"plan": "ultra"},
        headers=H_INST,
    )
    assert bad_plan.status_code == 422, bad_plan.text
    print("checkout invalid plan -> 422 OK")

    no_price = client.post(
        "/stripe/create-checkout-session",
        json={"plan": "starter"},
        headers=H_INST,
    )
    # In dev (no STRIPE_STARTER_PRICE_ID set) we expect a 400 with a clear
    # message — never a silent 500.
    assert no_price.status_code == 400, no_price.text
    assert "price" in no_price.json()["detail"].lower()
    print("checkout no-price-id -> 400 OK")

    no_portal = client.post("/stripe/customer-portal", headers=H_INST)
    assert no_portal.status_code == 400, no_portal.text
    print("portal without stripe customer -> 400 OK")

    # -----------------------------------------------------------------
    # 5) Simulate Stripe webhook: checkout.session.completed → activates
    # -----------------------------------------------------------------
    cust_id = f"cus_test_{uuid4().hex[:10]}"
    completed = {
        "id": f"evt_{uuid4().hex[:10]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": cust_id,
                "metadata": {
                    "organisation_id": inst_org_id,
                    "plan": "starter",
                },
            }
        },
    }
    _ok(
        client.post(
            "/stripe/webhook",
            content=json.dumps(completed),
            headers={"content-type": "application/json"},
        )
    )
    plan, status_, customer = get_org_state(inst_email)
    assert (plan, status_, customer) == ("starter", "active", cust_id)
    print("webhook checkout.session.completed -> active OK")

    sub = _ok(client.get("/stripe/subscription-status", headers=H_INST))
    assert sub["plan"] == "starter"
    assert sub["status"] == "active"
    assert sub["has_customer"] is True
    print("/stripe/subscription-status (active) OK")

    # -----------------------------------------------------------------
    # 6) With a subscription, leads endpoint is reachable + empty
    # -----------------------------------------------------------------
    leads = _ok(client.get("/installateur/leads", headers=H_INST))
    assert leads == []
    dossiers = _ok(client.get("/installateur/dossiers", headers=H_INST))
    assert dossiers == []
    print("active sub -> leads/dossiers reachable OK")

    # -----------------------------------------------------------------
    # 7) Seed a lead and verify the privacy preview before acceptance
    # -----------------------------------------------------------------
    aanvraag_id, lead_id = _seed_lead(inst_email, klant_email)

    leads = _ok(client.get("/installateur/leads", headers=H_INST))
    assert len(leads) == 1
    lead = leads[0]
    assert lead["id"] == lead_id
    assert lead["status"] == "nieuw"
    assert lead["aanvraag"]["regeling"] == "ISDE"
    assert lead["aanvraag"]["postcode"] == "1011AB"
    assert lead["aanvraag"]["plaats"] == "Amsterdam"
    # Preview only — no full client info yet
    assert lead["client"] is None
    assert lead["client_preview"]["first_name"] == "Test"
    print("lead preview redacts client OK")

    # filter by status
    new_leads = _ok(
        client.get("/installateur/leads?status=nieuw", headers=H_INST)
    )
    assert len(new_leads) == 1
    no_leads = _ok(
        client.get("/installateur/leads?status=gewonnen", headers=H_INST)
    )
    assert no_leads == []
    print("lead status filter OK")

    bad_filter = client.get(
        "/installateur/leads?status=onbekend", headers=H_INST
    )
    assert bad_filter.status_code == 422, bad_filter.text
    print("lead bad-status filter -> 422 OK")

    # Dossier still empty (lead not accepted yet)
    dossiers = _ok(client.get("/installateur/dossiers", headers=H_INST))
    assert dossiers == []

    # -----------------------------------------------------------------
    # 8) Accept lead → reveals client info + assigns dossier
    # -----------------------------------------------------------------
    accepted = _ok(
        client.patch(
            f"/installateur/leads/{lead_id}",
            json={"status": "contact_opgenomen"},
            headers=H_INST,
        )
    )
    assert accepted["status"] == "contact_opgenomen"
    assert accepted["client"] is not None
    assert accepted["client"]["email"] == klant_email
    assert accepted["client"]["last_name"] == "User"
    assert accepted["client"]["full_address"] == "Hoofdstraat 1"
    print("accept lead -> client revealed OK")

    dossiers = _ok(client.get("/installateur/dossiers", headers=H_INST))
    assert len(dossiers) == 1
    assert dossiers[0]["id"] == aanvraag_id
    assert dossiers[0]["aanvrager_name"] == "Test User"
    print("dossier auto-assigned OK")

    detail = _ok(
        client.get(f"/installateur/dossiers/{aanvraag_id}", headers=H_INST)
    )
    assert detail["id"] == aanvraag_id
    assert detail["organisation_name"] is not None
    assert detail["aaa_lex_project_id"] is not None
    print("dossier detail (read-only) OK")

    # 9) Stats updated
    stats = _ok(client.get("/installateur/stats", headers=H_INST))
    assert stats["active_leads"] == 1  # contact_opgenomen still counts
    assert stats["won_leads"] == 0
    assert stats["active_dossiers"] == 1
    assert stats["subscription_plan"] == "starter"

    # Mark won
    won = _ok(
        client.patch(
            f"/installateur/leads/{lead_id}",
            json={"status": "gewonnen"},
            headers=H_INST,
        )
    )
    assert won["status"] == "gewonnen"
    stats = _ok(client.get("/installateur/stats", headers=H_INST))
    assert stats["active_leads"] == 0
    assert stats["won_leads"] == 1
    print("stats counters OK")

    # invalid status update
    bad_patch = client.patch(
        f"/installateur/leads/{lead_id}",
        json={"status": "magic"},
        headers=H_INST,
    )
    assert bad_patch.status_code == 422, bad_patch.text

    # cross-installer cannot touch this lead
    other_inst_email = f"other-inst+{uuid4().hex[:8]}@example.com"
    other_inst_token = register(client, other_inst_email, org_type="installateur")
    set_subscription(other_inst_email, plan="pro", status="active")
    other = client.patch(
        f"/installateur/leads/{lead_id}",
        json={"status": "verloren"},
        headers={"Authorization": f"Bearer {other_inst_token}"},
    )
    assert other.status_code == 404, other.text
    print("cross-installer lead access blocked OK")

    # -----------------------------------------------------------------
    # 10) Stripe webhook: subscription.updated → switch plan
    # -----------------------------------------------------------------
    upgraded = {
        "id": f"evt_{uuid4().hex[:10]}",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "customer": cust_id,
                "status": "active",
                "metadata": {
                    "organisation_id": inst_org_id,
                    "plan": "pro",
                },
                "items": {"data": [{"price": {"id": "price_pro_xxx"}}]},
            }
        },
    }
    _ok(
        client.post(
            "/stripe/webhook",
            content=json.dumps(upgraded),
            headers={"content-type": "application/json"},
        )
    )
    plan, status_, _ = get_org_state(inst_email)
    assert (plan, status_) == ("pro", "active")
    print("webhook subscription.updated -> pro OK")

    # 11) Stripe webhook: subscription.deleted → cancel + lock back
    cancelled = {
        "id": f"evt_{uuid4().hex[:10]}",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "customer": cust_id,
                "metadata": {"organisation_id": inst_org_id},
            }
        },
    }
    _ok(
        client.post(
            "/stripe/webhook",
            content=json.dumps(cancelled),
            headers={"content-type": "application/json"},
        )
    )
    plan, status_, _ = get_org_state(inst_email)
    assert plan is None
    assert status_ == "cancelled"

    locked = client.get("/installateur/leads", headers=H_INST)
    assert locked.status_code == 402, locked.text
    print("webhook subscription.deleted -> cancelled + 402 lock OK")

    # 12) Webhook with unknown event type is accepted (200) but ignored
    misc = {
        "id": f"evt_{uuid4().hex[:10]}",
        "type": "ping.something",
        "data": {"object": {}},
    }
    body = _ok(
        client.post(
            "/stripe/webhook",
            content=json.dumps(misc),
            headers={"content-type": "application/json"},
        )
    )
    assert body["received"] is True
    print("unknown webhook event -> 200 OK")

    print("\nAll installateur + stripe tests passed")


if __name__ == "__main__":
    main()
