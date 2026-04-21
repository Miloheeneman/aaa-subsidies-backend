"""E2E smoke-test voor de panden module.

Dekt:
  * pand aanmaken (klant) + plan-limiet afdwinging
  * maatregel toevoegen → deadline auto-compute
  * document upload-URL aanvragen
  * checklist-berekening (geüpload vs verplicht)
  * admin kan document verifiëren
  * klant B heeft géén toegang tot pand van klant A
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.security import (  # noqa: E402
    create_email_verification_token,
    hash_password,
)
from app.models import Organisation, User  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrganisationType,
    SubscriptionPlan,
    UserRole,
)


BASE = os.environ.get("API_BASE", "http://127.0.0.1:8765/api/v1")
ENGINE = create_engine(settings.DATABASE_URL, future=True)


def _ok(resp: httpx.Response, *expected: int):
    if not expected:
        expected = (200,)
    if resp.status_code not in expected:
        raise AssertionError(
            f"{resp.request.method} {resp.request.url} -> {resp.status_code}\n"
            f"body: {resp.text}"
        )
    return resp.json() if resp.text else None


def register_and_verify(client: httpx.Client, email: str, password: str) -> str:
    _ok(
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": password,
                "first_name": "T",
                "last_name": "User",
                "phone": "+31612345678",
                "organisation_name": f"Org {email}",
            },
        ),
        201,
    )
    with Session(ENGINE) as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        tok = create_email_verification_token(user.id)
    _ok(client.post(f"/auth/verify-email/{tok}"))
    login = _ok(
        client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
    )
    return login["access_token"]


def install_admin() -> str:
    with Session(ENGINE) as db:
        existing = db.execute(
            select(User).where(User.email == "admin-pand@aaa-lexoffices.nl")
        ).scalar_one_or_none()
        if existing is not None:
            return "already"
        admin_org = Organisation(
            name="AAA-Lex Panden", type=OrganisationType.admin
        )
        db.add(admin_org)
        db.flush()
        admin = User(
            email="admin-pand@aaa-lexoffices.nl",
            password_hash=hash_password("AdminPand1!"),
            role=UserRole.admin,
            first_name="Admin",
            last_name="Panden",
            organisation_id=admin_org.id,
            verified=True,
        )
        db.add(admin)
        db.commit()
    return "created"


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    klant_a_token = register_and_verify(
        client, "klant-a@example.com", "ChangeMe123!"
    )
    klant_b_token = register_and_verify(
        client, "klant-b@example.com", "ChangeMe123!"
    )
    install_admin()
    admin_login = _ok(
        client.post(
            "/auth/login",
            json={
                "email": "admin-pand@aaa-lexoffices.nl",
                "password": "AdminPand1!",
            },
        )
    )
    admin_token = admin_login["access_token"]
    print("accounts ready")

    A = {"Authorization": f"Bearer {klant_a_token}"}
    B = {"Authorization": f"Bearer {klant_b_token}"}
    AD = {"Authorization": f"Bearer {admin_token}"}

    # --- create pand ---
    pand = _ok(
        client.post(
            "/panden",
            headers=A,
            json={
                "straat": "Dorpsstraat",
                "huisnummer": "12",
                "postcode": "1234 AB",
                "plaats": "Amsterdam",
                "bouwjaar": 1970,
                "pand_type": "woning",
                "eigenaar_type": "eigenaar_bewoner",
            },
        ),
        201,
    )
    pand_id = pand["id"]
    print(f"create pand OK id={pand_id[:8]}")

    # --- plan limit (gratis = 3) ---
    for i in range(2):
        _ok(
            client.post(
                "/panden",
                headers=A,
                json={
                    "straat": f"Limiet {i}",
                    "huisnummer": "1",
                    "postcode": "1111 AA",
                    "plaats": "Utrecht",
                    "bouwjaar": 1980,
                    "pand_type": "woning",
                    "eigenaar_type": "eigenaar_bewoner",
                },
            ),
            201,
        )
    r = client.post(
        "/panden",
        headers=A,
        json={
            "straat": "Over limiet",
            "huisnummer": "1",
            "postcode": "1111 AA",
            "plaats": "Utrecht",
            "bouwjaar": 1980,
            "pand_type": "woning",
            "eigenaar_type": "eigenaar_bewoner",
        },
    )
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "pand_limit_reached", detail
    assert detail["limit"] == 3
    print(f"plan limit enforced OK ({detail['current']}/{detail['limit']})")

    # --- klant B mag pand van klant A niet zien ---
    r = client.get(f"/panden/{pand_id}", headers=B)
    assert r.status_code in (403, 404), r.text
    print("cross-klant access -> 403/404 OK")

    # --- voeg maatregel toe (warmtepomp met installatiedatum 6m geleden) ---
    inst = (date.today() - timedelta(days=180)).isoformat()
    m = _ok(
        client.post(
            f"/panden/{pand_id}/maatregelen",
            headers=A,
            json={
                "maatregel_type": "warmtepomp_hybride",
                "apparaat_merk": "Daikin",
                "apparaat_typenummer": "Altherma 3",
                "apparaat_meldcode": "KA12345",
                "installateur_naam": "Warmte BV",
                "installateur_kvk": "12345678",
                "installateur_gecertificeerd": True,
                "installatie_datum": inst,
                "investering_bedrag": 8000,
            },
        ),
        201,
    )
    maatregel_id = m["id"]
    assert m["regeling_code"] == "ISDE", m
    assert m["deadline_indienen"] is not None
    assert m["deadline_type"] == "na_installatie", m
    assert m["deadline_status"] in ("ok", "waarschuwing"), m
    assert m["geschatte_subsidie"] is not None and m["geschatte_subsidie"] > 0
    print(
        f"create maatregel OK deadline={m['deadline_indienen']} status={m['deadline_status']}"
    )

    # --- checklist: warmtepomp → 4 verplicht ---
    cl = _ok(
        client.get(
            f"/maatregelen/{maatregel_id}/checklist", headers=A
        )
    )
    assert cl["required_count"] == 4, cl
    assert cl["uploaded_required_count"] == 0, cl
    assert cl["compleet"] is False, cl
    print(f"checklist OK required={cl['required_count']}")

    # --- document upload-url aanvragen ---
    up = _ok(
        client.post(
            f"/maatregelen/{maatregel_id}/documenten",
            headers=A,
            json={
                "document_type": "factuur",
                "filename": "factuur warmtepomp.pdf",
                "content_type": "application/pdf",
            },
        ),
        201,
    )
    assert "upload_url" in up and up["upload_url"]
    assert up["r2_key"].endswith("factuur_warmtepomp.pdf"), up
    document_id = up["document_id"]
    print(f"upload url OK document_id={document_id[:8]}")

    # --- checklist na upload ---
    cl = _ok(
        client.get(f"/maatregelen/{maatregel_id}/checklist", headers=A)
    )
    assert cl["uploaded_required_count"] == 1, cl
    print("checklist updated after upload OK")

    # --- admin verifieert document ---
    v = _ok(
        client.post(
            f"/maatregelen/{maatregel_id}/documenten/{document_id}/verify",
            headers=AD,
        )
    )
    assert v["geverifieerd_door_admin"] is True, v
    print("admin verify OK")

    # --- klant kan niet verifiëren ---
    r = client.post(
        f"/maatregelen/{maatregel_id}/documenten/{document_id}/verify",
        headers=A,
    )
    assert r.status_code == 403, r.text
    print("klant verify -> 403 OK")

    # --- admin ziet alle panden ---
    all_panden = _ok(client.get("/panden", headers=AD))
    assert any(p["id"] == pand_id for p in all_panden)
    print(f"admin list panden OK total={len(all_panden)}")

    # --- update pand (admin vult energielabel) ---
    _ok(
        client.put(
            f"/panden/{pand_id}",
            headers=AD,
            json={
                "energielabel_huidig": "E",
                "energielabel_na_maatregelen": "B",
                "oppervlakte_m2": 95.5,
                "notities": "Opname klaar",
            },
        )
    )
    # --- klant mag energielabel niet zetten ---
    r = client.put(
        f"/panden/{pand_id}",
        headers=A,
        json={"energielabel_huidig": "A"},
    )
    assert r.status_code == 403, r.text
    print("admin update energielabel OK, klant -> 403 OK")

    # --- pand detail toont maatregelen + energielabel ---
    detail = _ok(client.get(f"/panden/{pand_id}", headers=A))
    assert detail["energielabel_huidig"] == "E", detail
    assert len(detail["maatregelen"]) == 1, detail
    m0 = detail["maatregelen"][0]
    assert m0["regeling_code"] == "ISDE"
    assert m0["documents_required"] == 4
    assert m0["documents_uploaded"] == 1
    assert m0["documents_verified"] == 1
    print("pand detail OK")

    # --- soft-delete pand ---
    r = client.delete(f"/panden/{pand_id}", headers=A)
    assert r.status_code == 204, r.text
    r = client.get(f"/panden/{pand_id}", headers=A)
    assert r.status_code == 404, r.text
    print("soft delete OK")

    print("\nAll panden e2e tests passed")


if __name__ == "__main__":
    main()
