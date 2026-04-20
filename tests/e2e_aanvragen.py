"""Live smoke test for /api/v1/aanvragen endpoints."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_email_verification_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8768/api/v1")


def _ok(resp: httpx.Response, *expected: int) -> dict:
    if not expected:
        expected = (200,)
    if resp.status_code not in expected:
        raise AssertionError(
            f"{resp.request.method} {resp.request.url} -> {resp.status_code}\n"
            f"body: {resp.text}"
        )
    return resp.json() if resp.content else {}


def register_and_verify(client, email: str) -> str:
    """Register a klant and programmatically verify + login. Returns token."""
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
            },
        ),
        201,
    )
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        token = create_email_verification_token(str(u.id))
    _ok(client.post(f"/auth/verify-email/{token}"))
    login = _ok(
        client.post(
            "/auth/login", json={"email": email, "password": "Welkom1234!"}
        )
    )
    return login["access_token"]


def promote_to_admin(email: str) -> None:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        u.role = UserRole.admin
        db.commit()


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    # --- Set up two klant accounts and one admin ---
    klant_email = f"klant+{uuid4().hex[:8]}@example.com"
    other_email = f"other+{uuid4().hex[:8]}@example.com"
    admin_email = f"admin+{uuid4().hex[:8]}@example.com"

    klant_token = register_and_verify(client, klant_email)
    other_token = register_and_verify(client, other_email)
    admin_token_before_promo = register_and_verify(client, admin_email)
    promote_to_admin(admin_email)
    # Re-login to get a token that still works; role is only checked at
    # request time via the user row, so the old token is still valid.
    admin_token = admin_token_before_promo

    H = {"Authorization": f"Bearer {klant_token}"}
    H_OTHER = {"Authorization": f"Bearer {other_token}"}
    H_ADMIN = {"Authorization": f"Bearer {admin_token}"}

    # --- Empty list to start ---
    r = _ok(client.get("/aanvragen", headers=H))
    assert r == [], r
    print("empty list OK")

    # --- Create ISDE aanvraag ---
    payload = {
        "regeling": "ISDE",
        "type_aanvrager": "particulier",
        "maatregel": "warmtepomp",
        "investering_bedrag": 9000,
        "offerte_beschikbaar": False,
    }
    created = _ok(client.post("/aanvragen", json=payload, headers=H), 201)
    assert created["regeling"] == "ISDE"
    assert created["status"] == "intake"
    # 25% van 9000 = 2250; fee 8% = 180; klant_ontvangt = 2070
    assert Decimal(created["geschatte_subsidie"]) == Decimal("2250.00")
    assert Decimal(created["aaa_lex_fee_bedrag"]) == Decimal("180.00")
    assert Decimal(created["klant_ontvangt"]) == Decimal("2070.00")
    # ISDE has no deadline column
    assert created["deadline_datum"] is None
    assert created["deadline_type"] is None
    assert len(created["status_timeline"]) >= 5
    assert created["status_timeline"][0]["status"] == "intake"
    assert created["status_timeline"][0]["current"] is True
    isde_id = created["id"]
    print("create ISDE OK")

    # --- Create EIA aanvraag -> deadline = today + 90d ---
    eia_payload = {
        "regeling": "EIA",
        "type_aanvrager": "ondernemer",
        "maatregel": "energiesysteem",
        "investering_bedrag": 8000,
        "offerte_beschikbaar": True,
    }
    eia = _ok(client.post("/aanvragen", json=eia_payload, headers=H), 201)
    assert eia["deadline_type"] == "EIA_3maanden"
    dl = date.fromisoformat(eia["deadline_datum"])
    assert dl == date.today() + timedelta(days=90)
    # EIA 45.5% van 8000 = 3640; fee 5% = 182
    assert Decimal(eia["geschatte_subsidie"]) == Decimal("3640.00")
    assert Decimal(eia["aaa_lex_fee_bedrag"]) == Decimal("182.00")
    # offerte_beschikbaar -> auto-notes injected
    assert "Offerte" in (eia["notes"] or ""), eia["notes"]
    eia_id = eia["id"]
    print("create EIA OK (deadline + auto-note)")

    # --- Create DUMAVA aanvraag -> deadline = today + 730d ---
    dumava = _ok(
        client.post(
            "/aanvragen",
            json={
                "regeling": "DUMAVA",
                "type_aanvrager": "maatschappelijk",
                "maatregel": "meerdere",
                "investering_bedrag": 50000,
                "offerte_beschikbaar": False,
            },
            headers=H,
        ),
        201,
    )
    assert dumava["deadline_type"] == "DUMAVA_2jaar"
    dl = date.fromisoformat(dumava["deadline_datum"])
    assert dl == date.today() + timedelta(days=730)
    # 30% van 50000 = 15000; fee 10% = 1500
    assert Decimal(dumava["geschatte_subsidie"]) == Decimal("15000.00")
    assert Decimal(dumava["aaa_lex_fee_bedrag"]) == Decimal("1500.00")
    dumava_id = dumava["id"]
    print("create DUMAVA OK")

    # --- List aanvragen for the klant (3 items) ---
    lst = _ok(client.get("/aanvragen", headers=H))
    assert len(lst) == 3, lst
    by_reg = {x["regeling"]: x for x in lst}
    assert set(by_reg) == {"ISDE", "EIA", "DUMAVA"}
    # ISDE has 6 required documents, none uploaded
    assert by_reg["ISDE"]["missing_document_count"] == 6
    assert by_reg["ISDE"]["document_count"] == 0
    print("list OK")

    # --- Filter by status and regeling ---
    lst_intake = _ok(client.get("/aanvragen?status=intake", headers=H))
    assert len(lst_intake) == 3
    lst_none = _ok(client.get("/aanvragen?status=ingediend", headers=H))
    assert lst_none == []
    lst_isde = _ok(client.get("/aanvragen?regeling=ISDE", headers=H))
    assert len(lst_isde) == 1 and lst_isde[0]["regeling"] == "ISDE"
    bad = client.get("/aanvragen?status=nonsense", headers=H)
    assert bad.status_code == 422
    bad2 = client.get("/aanvragen?regeling=XXX", headers=H)
    assert bad2.status_code == 422
    print("filters OK")

    # --- Other klant cannot see these aanvragen in their list ---
    other_list = _ok(client.get("/aanvragen", headers=H_OTHER))
    assert other_list == []
    # ... and cannot GET by id (403)
    forbidden = client.get(f"/aanvragen/{isde_id}", headers=H_OTHER)
    assert forbidden.status_code == 403, forbidden.text
    print("cross-org isolation OK")

    # --- Detail endpoint ---
    detail = _ok(client.get(f"/aanvragen/{isde_id}", headers=H))
    assert detail["id"] == isde_id
    assert detail["documenten"] == []
    assert detail["status_timeline"][0]["current"] is True
    print("detail OK")

    # --- PATCH: update notes + investering_bedrag -> subsidie/fee recomputed ---
    patched = _ok(
        client.patch(
            f"/aanvragen/{isde_id}",
            json={"notes": "Extra aandachtspunt", "investering_bedrag": 12000},
            headers=H,
        )
    )
    assert patched["notes"] == "Extra aandachtspunt"
    # 25% van 12000 = 3000; fee 8% = 240
    assert Decimal(patched["geschatte_subsidie"]) == Decimal("3000.00")
    assert Decimal(patched["aaa_lex_fee_bedrag"]) == Decimal("240.00")
    print("patch recomputes OK")

    # --- PATCH: gewenste_startdatum wordt in notes gemarkeerd ---
    future = (date.today() + timedelta(days=30)).isoformat()
    patched2 = _ok(
        client.patch(
            f"/aanvragen/{isde_id}",
            json={"gewenste_startdatum": future},
            headers=H,
        )
    )
    assert future in (patched2["notes"] or "")
    print("gewenste_startdatum stored OK")

    # --- PATCH cannot change status (schema forbids extra fields) ---
    bad_patch = client.patch(
        f"/aanvragen/{isde_id}",
        json={"status": "goedgekeurd"},
        headers=H,
    )
    assert bad_patch.status_code == 422, bad_patch.text
    print("patch rejects status OK")

    # --- Document checklist: ISDE has 6 required, none uploaded ---
    cl = _ok(client.get(f"/aanvragen/{isde_id}/documenten", headers=H))
    assert cl["regeling"] == "ISDE"
    assert cl["required_count"] == 6
    assert cl["uploaded_count"] == 0
    assert cl["missing_count"] == 6
    required_types = {it["document_type"] for it in cl["items"] if it["required"]}
    assert required_types == {
        "offerte",
        "factuur",
        "betalingsbewijs",
        "foto_installatie",
        "werkbon",
        "energielabel",
    }
    for it in cl["items"]:
        assert it["uploaded"] is False
        assert it["verified"] is False
        assert it["upload_url"] is None
    print("checklist ISDE OK")

    # --- Document checklist: DUMAVA has 6 required ---
    cl_d = _ok(client.get(f"/aanvragen/{dumava_id}/documenten", headers=H))
    assert cl_d["required_count"] == 6
    required_dumava = {it["document_type"] for it in cl_d["items"] if it["required"]}
    assert required_dumava == {
        "maatwerkadvies",
        "offerte",
        "begroting",
        "foto_voor",
        "factuur",
        "foto_na",
    }
    print("checklist DUMAVA OK")

    # --- Other klant cannot access checklist ---
    forbidden_cl = client.get(
        f"/aanvragen/{isde_id}/documenten", headers=H_OTHER
    )
    assert forbidden_cl.status_code == 403
    print("checklist isolation OK")

    # --- Admin can see all ---
    admin_list = _ok(client.get("/aanvragen", headers=H_ADMIN))
    assert len(admin_list) >= 3
    admin_detail = _ok(client.get(f"/aanvragen/{isde_id}", headers=H_ADMIN))
    assert admin_detail["id"] == isde_id
    print("admin visibility OK")

    # --- No auth -> 401 ---
    no_auth = client.get("/aanvragen")
    assert no_auth.status_code == 401
    # Also: POST unauth
    no_auth_post = client.post("/aanvragen", json=payload)
    assert no_auth_post.status_code == 401
    print("auth required OK")

    # --- 404 on nonexistent ---
    missing = client.get(f"/aanvragen/{uuid4()}", headers=H)
    assert missing.status_code == 404
    print("404 OK")

    # --- Create validation: unknown regeling -> 422 ---
    bad_create = client.post(
        "/aanvragen",
        json={
            "regeling": "XXX",
            "type_aanvrager": "particulier",
            "maatregel": "warmtepomp",
            "offerte_beschikbaar": False,
        },
        headers=H,
    )
    assert bad_create.status_code == 422
    print("create validation OK")

    print("\nAll aanvragen tests passed")


if __name__ == "__main__":
    main()
