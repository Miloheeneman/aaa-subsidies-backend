"""Live smoke test covering auth + AAA-Lex endpoints.

Uses httpx to hit a running uvicorn; intended to be run by a harness
that starts uvicorn and applies migrations first.
"""
from __future__ import annotations

import os
import re
import sys
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.security import (  # noqa: E402
    create_email_verification_token,
)
from app.models import User  # noqa: E402
from app.models.enums import UserRole  # noqa: E402


BASE = os.environ.get("API_BASE", "http://127.0.0.1:8765/api/v1")
ENGINE = create_engine(settings.DATABASE_URL, future=True)


def _ok(resp: httpx.Response, *expected: int) -> dict | list:
    if not expected:
        expected = (200,)
    if resp.status_code not in expected:
        raise AssertionError(
            f"{resp.request.method} {resp.request.url} -> {resp.status_code}\n"
            f"body: {resp.text}"
        )
    return resp.json()


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    # --- 1. register klant ---
    reg = _ok(
        client.post(
            "/auth/register",
            json={
                "email": "klant@example.com",
                "password": "ChangeMe123!",
                "first_name": "Test",
                "last_name": "Klant",
                "phone": "+31612345678",
                "organisation_name": "Testklant BV",
                "organisation_type": "klant",
            },
        ),
        201,
    )
    assert reg["message"] == "Verificatie email verstuurd", reg
    print("register klant OK")

    # --- 2. login before verify -> 403 ---
    r = client.post(
        "/auth/login",
        json={"email": "klant@example.com", "password": "ChangeMe123!"},
    )
    assert r.status_code == 403, r.text
    print("login before verify -> 403 OK")

    # --- 3. programmatically issue verify token + call verify endpoint ---
    with Session(ENGINE) as db:
        user = db.execute(
            select(User).where(User.email == "klant@example.com")
        ).scalar_one()
        tok = create_email_verification_token(user.id)
    _ok(client.post(f"/auth/verify-email/{tok}"))
    print("verify email OK")

    # --- 4. login after verify ---
    login = _ok(
        client.post(
            "/auth/login",
            json={"email": "klant@example.com", "password": "ChangeMe123!"},
        )
    )
    assert login["token_type"] == "bearer"
    assert login["user"]["email"] == "klant@example.com"
    assert login["user"]["role"] == "klant"
    assert login["organisation"]["type"] == "klant"
    klant_token = login["access_token"]
    klant_user_id = login["user"]["id"]
    klant_org_id = login["organisation"]["id"]
    print(f"login OK (expires_in_minutes={login['expires_in_minutes']})")

    # --- 5. /auth/me ---
    me = _ok(
        client.get(
            "/auth/me", headers={"Authorization": f"Bearer {klant_token}"}
        )
    )
    assert me["user"]["id"] == klant_user_id
    assert me["organisation"]["id"] == klant_org_id
    print("/auth/me OK")

    # --- 6. /auth/me without token -> 401 ---
    r = client.get("/auth/me")
    assert r.status_code == 401, r.text
    print("/auth/me without token -> 401 OK")

    # --- 7. /auth/me with garbage token -> 401 ---
    r = client.get(
        "/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert r.status_code == 401, r.text
    print("/auth/me garbage token -> 401 OK")

    # --- 8. forgot-password always 200, even for unknown email ---
    _ok(
        client.post(
            "/auth/forgot-password", json={"email": "nonexistent@example.com"}
        )
    )
    _ok(client.post("/auth/forgot-password", json={"email": "klant@example.com"}))
    print("forgot-password (both cases) OK")

    # --- 9. reset-password: generate token, update pw, login with new pw ---
    from app.core.security import create_password_reset_token

    with Session(ENGINE) as db:
        user = db.execute(
            select(User).where(User.email == "klant@example.com")
        ).scalar_one()
        reset_tok = create_password_reset_token(user.id)
    _ok(
        client.post(
            f"/auth/reset-password/{reset_tok}",
            json={"new_password": "Brandnew456!"},
        )
    )
    # old password should now fail
    r = client.post(
        "/auth/login",
        json={"email": "klant@example.com", "password": "ChangeMe123!"},
    )
    assert r.status_code == 401, r.text
    _ok(
        client.post(
            "/auth/login",
            json={"email": "klant@example.com", "password": "Brandnew456!"},
        )
    )
    print("reset-password OK")

    # --- 10. duplicate register -> 409 ---
    r = client.post(
        "/auth/register",
        json={
            "email": "klant@example.com",
            "password": "Whatever123",
            "first_name": "X",
            "last_name": "Y",
            "organisation_name": "Dup BV",
            "organisation_type": "klant",
        },
    )
    assert r.status_code == 409, r.text
    print("duplicate register -> 409 OK")

    # --- 11. install admin user directly in DB and login ---
    from app.core.security import hash_password
    from app.models import Organisation
    from app.models.enums import OrganisationType

    with Session(ENGINE) as db:
        admin_org = Organisation(name="AAA-Lex", type=OrganisationType.admin)
        db.add(admin_org)
        db.flush()
        admin = User(
            email="admin@aaa-lexoffices.nl",
            password_hash=hash_password("Admin123!"),
            role=UserRole.admin,
            first_name="Admin",
            last_name="AAA",
            organisation_id=admin_org.id,
            verified=True,
        )
        db.add(admin)
        db.commit()

    admin_login = _ok(
        client.post(
            "/auth/login",
            json={"email": "admin@aaa-lexoffices.nl", "password": "Admin123!"},
        )
    )
    assert admin_login["user"]["role"] == "admin"
    admin_token = admin_login["access_token"]
    print("admin login OK")

    # --- 12. klant cannot access admin endpoint ---
    r = client.post(
        "/aaa-lex/project",
        headers={"Authorization": f"Bearer {klant_token}"},
        json={
            "pandadres": "Test 1",
            "postcode": "1000 AA",
            "plaats": "Amsterdam",
        },
    )
    assert r.status_code == 403, r.text
    print("klant -> aaa-lex admin endpoint -> 403 OK")

    # --- 13. admin creates AAA-Lex project linked to klant org ---
    project = _ok(
        client.post(
            "/aaa-lex/project",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "external_reference": "AAALEX-2026-0001",
                "organisation_id": klant_org_id,
                "pandadres": "Dorpsstraat 12",
                "postcode": "1234 AB",
                "plaats": "Amsterdam",
                "bouwjaar": 1975,
                "huidig_energielabel": "E",
                "nieuw_energielabel": "A",
                "type_pand": "woning",
                "oppervlakte_m2": 120,
                "dakoppervlakte_m2": 60,
                "geveloppervlakte_m2": 140,
                "aanbevolen_maatregelen": [
                    {
                        "naam": "Hybride warmtepomp",
                        "categorie": "warmtepomp",
                        "geschatte_kosten": 6500,
                    },
                    {
                        "naam": "Spouwmuurisolatie",
                        "categorie": "isolatie",
                        "geschatte_kosten": 2500,
                    },
                ],
                "geschatte_investering": 9000,
                "geschatte_co2_besparing": 2500,
                "ingevoerd_door": "Jan de Vries",
            },
        ),
        201,
    )
    assert project["project"]["pandadres"] == "Dorpsstraat 12"
    matched = project["matched_subsidies"]
    codes = sorted(m["regeling"] for m in matched)
    # type_pand=woning -> particulier -> ISDE only
    assert codes == ["ISDE"], codes
    isde = matched[0]
    assert isde["aanvraag_id"] is not None
    # 25% of 9000 = 2250
    assert Decimal(isde["geschatte_subsidie"]) == Decimal("2250.00"), isde
    # fee = 8% of 2250 = 180
    assert Decimal(isde["aaa_lex_fee_bedrag"]) == Decimal("180.00"), isde
    # client_notified is True because org + primary-contact user + matches all exist.
    # (Resend is not configured in tests; the service logs and does not raise.)
    assert project["client_notified"] is True, project
    print(
        f"aaa-lex project (particulier) OK -> project_id={project['project']['id']}"
        f" matched={codes} total={project['total_geschatte_subsidie']}"
    )
    particulier_project_id = project["project"]["id"]

    # --- 14. admin creates AAA-Lex project for maatschappelijk vastgoed ---
    project2 = _ok(
        client.post(
            "/aaa-lex/project",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "pandadres": "Schoolweg 5",
                "postcode": "3500 XX",
                "plaats": "Utrecht",
                "type_pand": "maatschappelijk",
                "aanbevolen_maatregelen": [
                    {
                        "naam": "Dakisolatie",
                        "categorie": "isolatie",
                        "geschatte_kosten": 15000,
                    },
                    {
                        "naam": "Warmtepomp",
                        "categorie": "warmtepomp",
                        "geschatte_kosten": 35000,
                    },
                ],
                "geschatte_investering": 50000,
            },
        ),
        201,
    )
    codes2 = sorted(m["regeling"] for m in project2["matched_subsidies"])
    assert codes2 == ["DUMAVA"], codes2
    # No organisation_id -> no aanvraag created -> client_notified False
    assert project2["client_notified"] is False
    assert all(m["aanvraag_id"] is None for m in project2["matched_subsidies"])
    print("aaa-lex project (maatschappelijk -> DUMAVA) OK, no org linked")

    # --- 15. admin creates AAA-Lex project for ondernemer ---
    project3 = _ok(
        client.post(
            "/aaa-lex/project",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "pandadres": "Kantoorlaan 99",
                "postcode": "1017 AA",
                "plaats": "Amsterdam",
                "type_pand": "bedrijfspand",
                "aanbevolen_maatregelen": [
                    {
                        "naam": "LED-verlichting",
                        "categorie": "energiesysteem",
                        "geschatte_kosten": 8000,
                    },
                ],
                "geschatte_investering": 8000,
            },
        ),
        201,
    )
    codes3 = sorted(m["regeling"] for m in project3["matched_subsidies"])
    assert codes3 == ["EIA", "MIA", "VAMIL"], codes3
    print("aaa-lex project (ondernemer -> EIA+MIA+VAMIL) OK")

    # --- 16. GET /aaa-lex/project/{id} as admin ---
    detail = _ok(
        client.get(
            f"/aaa-lex/project/{particulier_project_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    )
    assert detail["project"]["pandadres"] == "Dorpsstraat 12"
    assert len(detail["linked_aanvragen"]) == 1
    assert detail["linked_aanvragen"][0]["regeling"] == "ISDE"
    print("GET aaa-lex project detail OK")

    # --- 17. non-admin cannot GET aaa-lex project ---
    r = client.get(
        f"/aaa-lex/project/{particulier_project_id}",
        headers={"Authorization": f"Bearer {klant_token}"},
    )
    assert r.status_code == 403, r.text
    print("klant -> GET aaa-lex project -> 403 OK")

    # --- 18. sub-threshold investment for ondernemer -> no EIA/MIA ---
    project4 = _ok(
        client.post(
            "/aaa-lex/project",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "pandadres": "Klein 2",
                "postcode": "1000 AA",
                "plaats": "Amsterdam",
                "type_pand": "bedrijfspand",
                "aanbevolen_maatregelen": [
                    {
                        "naam": "Kleine LED",
                        "categorie": "energiesysteem",
                        "geschatte_kosten": 500,
                    }
                ],
                "geschatte_investering": 500,
            },
        ),
        201,
    )
    assert project4["matched_subsidies"] == []
    print("sub-threshold ondernemer -> no subsidies OK")

    # --- 19. invalid verification token -> 400 ---
    r = client.post("/auth/verify-email/not-a-token")
    assert r.status_code == 400, r.text
    print("invalid verify token -> 400 OK")

    # --- 20. reset with short password -> 422 ---
    r = client.post(
        "/auth/reset-password/anything",
        json={"new_password": "short"},
    )
    assert r.status_code == 422, r.text
    print("reset password validation -> 422 OK")

    print("\nAll smoke tests passed")


if __name__ == "__main__":
    main()
