"""Bewijs: klant A kan geen project/maatregel van klant B ophalen (403/404)."""

from __future__ import annotations

import os
import sys
from uuid import uuid4

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_email_verification_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8769/api/v1")


def _ok(resp: httpx.Response, *expected: int):
    if not expected:
        expected = (200,)
    if resp.status_code not in expected:
        raise AssertionError(
            f"{resp.request.method} {resp.request.url} -> {resp.status_code}\n{resp.text}"
        )
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


def _register_and_verify(client: httpx.Client, email: str) -> str:
    _ok(
        client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "Welkom1234!",
                "first_name": "Iso",
                "last_name": "Test",
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
        client.post("/auth/login", json={"email": email, "password": "Welkom1234!"})
    )
    return login["access_token"]


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=20.0)

    email_a = f"iso-a-{uuid4().hex[:8]}@example.com"
    email_b = f"iso-b-{uuid4().hex[:8]}@example.com"
    token_a = _register_and_verify(client, email_a)
    token_b = _register_and_verify(client, email_b)
    ha = {"Authorization": f"Bearer {token_a}"}
    hb = {"Authorization": f"Bearer {token_b}"}

    proj = _ok(
        client.post(
            "/projecten",
            headers=ha,
            json={
                "straat": "Secretstraat",
                "huisnummer": "1",
                "postcode": "1111 AA",
                "plaats": "A-stad",
                "bouwjaar": 1980,
                "project_type": "woning",
                "eigenaar_type": "eigenaar_bewoner",
            },
        ),
        201,
    )
    pid = proj["id"]

    m = _ok(
        client.post(
            f"/projecten/{pid}/maatregelen",
            headers=ha,
            json={
                "maatregel_type": "warmtepomp_lucht_water",
                "installatie_datum": "2026-03-01",
                "investering_bedrag": 8000,
            },
        ),
        201,
    )
    mid = m["id"]

    r_detail = client.get(f"/projecten/{pid}", headers=hb)
    assert r_detail.status_code == 403, r_detail.text
    r_m = client.get(f"/maatregelen/{mid}", headers=hb)
    assert r_m.status_code == 403, r_m.text
    r_cl = client.get(f"/maatregelen/{mid}/checklist", headers=hb)
    assert r_cl.status_code == 403, r_cl.text

    print("org isolation projecten: B krijgt 403 op project en maatregel van A — OK")


if __name__ == "__main__":
    main()
