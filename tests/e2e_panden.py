"""Live smoke test for the panden module (STAP 9).

Exercises the full klant flow end-to-end:

1. Register + verify a klant (defaults to plan=gratis, limit=3).
2. Create a pand; bouwjaar is required.
3. Add a warmtepomp maatregel with installatie_datum; backend auto-fills
   deadline fields.
4. Fetch checklist → all ISDE-verplichte documenten zijn aanwezig als
   item, nog niets geüpload, compleet=False.
5. Upload a factuur (presign + confirm) → compleet-teller loopt op.
6. Admin verifieert het document → geverifieerd flag omhoog.
7. Maak 3 panden → vierde geeft 403 met PLAN_LIMIT_REACHED.
"""
from __future__ import annotations

import os
import sys
from uuid import uuid4

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_email_verification_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Organisation, User  # noqa: E402
from app.models.enums import OrganisationType, UserRole  # noqa: E402

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8769/api/v1")


def _ok(resp: httpx.Response, *expected: int):
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


def _register_and_verify(client: httpx.Client, email: str) -> tuple[str, str]:
    _ok(
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "Welkom1234!",
                "first_name": "Pand",
                "last_name": "Tester",
                "organisation_name": "Panden BV",
            },
        ),
        201,
    )
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


def _make_admin(email: str) -> str:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        u.role = UserRole.admin
        org = db.query(Organisation).filter(Organisation.id == u.organisation_id).one()
        org.type = OrganisationType.admin
        db.commit()
        return str(u.id)


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    # --- klant ----------------------------------------------------------
    klant_email = f"klant+{uuid4().hex[:6]}@example.com"
    token, _ = _register_and_verify(client, klant_email)
    H = {"Authorization": f"Bearer {token}"}

    # --- 1. create pand ------------------------------------------------
    body = {
        "straat": "Hoofdstraat",
        "huisnummer": "12A",
        "postcode": "1234 AB",
        "plaats": "Zoetermeer",
        "bouwjaar": 1970,
        "pand_type": "woning",
        "eigenaar_type": "eigenaar_bewoner",
    }
    pand = _ok(client.post("/panden", json=body, headers=H), 201)
    assert pand["bouwjaar"] == 1970
    assert pand["aantal_maatregelen"] == 0
    pand_id = pand["id"]
    print("create pand OK")

    # bouwjaar verplicht: zonder => 422
    bad = dict(body)
    bad.pop("bouwjaar")
    r = client.post("/panden", json=bad, headers=H)
    assert r.status_code == 422, r.text
    print("bouwjaar verplicht -> 422 OK")

    # --- 2. list + detail ---------------------------------------------
    lst = _ok(client.get("/panden", headers=H))
    assert lst["totaal"] == 1
    assert lst["quota"]["plan"] == "gratis"
    assert lst["quota"]["limit"] == 3
    assert lst["quota"]["used"] == 1

    detail = _ok(client.get(f"/panden/{pand_id}", headers=H))
    assert detail["maatregelen"] == []
    print("list + detail pand OK")

    # --- 3. create maatregel (warmtepomp + installatie_datum) ---------
    m_body = {
        "maatregel_type": "warmtepomp_lucht_water",
        "installatie_datum": "2026-01-15",
        "apparaat_merk": "Daikin",
        "apparaat_meldcode": "WP-1234",
        "investering_bedrag": 9500,
    }
    m = _ok(
        client.post(f"/panden/{pand_id}/maatregelen", json=m_body, headers=H),
        201,
    )
    assert m["maatregel_type"] == "warmtepomp_lucht_water"
    assert m["regeling_code"] == "ISDE"
    assert m["deadline_indienen"] == "2028-01-15"  # +24 maanden
    assert m["deadline_type"] == "na_installatie"
    assert m["deadline_status"] in ("ok", "waarschuwing", "kritiek", "verlopen")
    m_id = m["id"]
    print("create maatregel + deadline engine OK")

    # --- 4. checklist ------------------------------------------------
    cl = _ok(client.get(f"/maatregelen/{m_id}/checklist", headers=H))
    types = {i["document_type"] for i in cl["items"]}
    assert "factuur" in types
    assert "betaalbewijs" in types
    assert "meldcode_bewijs" in types
    assert "inbedrijfstelling" in types
    assert cl["verplicht_geupload"] == 0
    assert cl["compleet"] is False
    print("checklist pre-upload OK")

    # --- 5. upload factuur -------------------------------------------
    up = _ok(
        client.post(
            f"/maatregelen/{m_id}/documenten",
            json={
                "document_type": "factuur",
                "bestandsnaam": "factuur.pdf",
                "content_type": "application/pdf",
            },
            headers=H,
        ),
        201,
    )
    assert "upload_url" in up and "document_id" in up
    doc_id = up["document_id"]

    # Confirm (geen echte R2 in dev — de backend zet r2_key naar r2://...)
    confirmed = _ok(
        client.post(
            f"/maatregelen/{m_id}/documenten/{doc_id}/confirm", headers=H
        )
    )
    assert confirmed["pending_upload"] is False

    cl = _ok(client.get(f"/maatregelen/{m_id}/checklist", headers=H))
    factuur = next(i for i in cl["items"] if i["document_type"] == "factuur")
    assert factuur["geupload"] is True
    assert factuur["geverifieerd"] is False
    assert cl["verplicht_geupload"] == 1
    assert cl["compleet"] is False
    print("upload + confirm factuur OK")

    # --- 6. admin verifieert ----------------------------------------
    # Verify document must be admin
    r = client.post(
        f"/maatregelen/{m_id}/documenten/{doc_id}/verify", headers=H
    )
    assert r.status_code == 403, r.text

    # Promote a separate user to admin
    admin_email = f"admin+{uuid4().hex[:6]}@example.com"
    admin_token, _ = _register_and_verify(client, admin_email)
    _make_admin(admin_email)
    # re-login to pick up fresh role
    admin_login = _ok(
        client.post(
            "/auth/login",
            json={"email": admin_email, "password": "Welkom1234!"},
        )
    )
    A = {"Authorization": f"Bearer {admin_login['access_token']}"}

    _ok(
        client.post(
            f"/maatregelen/{m_id}/documenten/{doc_id}/verify", headers=A
        )
    )
    cl = _ok(client.get(f"/maatregelen/{m_id}/checklist", headers=H))
    factuur = next(i for i in cl["items"] if i["document_type"] == "factuur")
    assert factuur["geverifieerd"] is True
    print("admin verifieert document OK")

    # Admin ziet alle panden
    all_panden = _ok(client.get("/panden", headers=A))
    assert all_panden["totaal"] >= 1
    assert all_panden["quota"]["plan"] == "admin"
    print("admin ziet alle panden OK")

    # Kritieke deadlines widget (max_dagen groot genoeg om iets te vinden)
    widget = _ok(
        client.get(
            "/admin/panden/kritieke-deadlines?max_dagen=99999", headers=A
        )
    )
    assert isinstance(widget, list)
    print("kritieke-deadlines widget bereikbaar OK")

    # --- 7. plan-limit --------------------------------------------
    # Gratis plan = 3 panden. We hebben er al 1 — nog 2 erbij = ok.
    for i in range(2):
        body2 = dict(body, straat=f"Bijstraat {i}")
        _ok(client.post("/panden", json=body2, headers=H), 201)

    # Vierde → 403 PLAN_LIMIT_REACHED
    r = client.post("/panden", json=body, headers=H)
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "PLAN_LIMIT_REACHED"
    assert detail["limit"] == 3
    assert detail["used"] == 3
    print("plan-limit enforcement (gratis=3) OK")

    # --- 8. soft-delete -------------------------------------------
    _ok(client.delete(f"/panden/{pand_id}", headers=H), 204)
    lst = _ok(client.get("/panden", headers=H))
    assert all(p["id"] != pand_id for p in lst["items"])
    assert lst["quota"]["used"] == 2  # 2 overgebleven actieve panden
    print("soft-delete + quota herberekend OK")

    print("\nAll panden tests passed")


if __name__ == "__main__":
    main()
