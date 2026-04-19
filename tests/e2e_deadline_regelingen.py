"""Live smoke test for the deadline-warning service + admin
regelingen-config endpoints.

Covers:
* GET /api/v1/admin/regelingen returns the 5 seeded regelingen.
* PATCH /api/v1/admin/regelingen/{code} updates fields, validates
  bounds (fee_percentage 0..100), respects ``actief`` everywhere
  (subsidiecheck + create aanvraag).
* POST /api/v1/admin/run-deadline-check correctly classifies aanvragen
  in the ``verlopen`` / 7d / 14d / safe buckets, deduplicates within
  the cooldown window, and ignores done dossiers
  (goedgekeurd/afgewezen).
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from uuid import uuid4

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import create_email_verification_token  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import RegelingConfig, SubsidieAanvraag, User  # noqa: E402
from app.models.enums import (  # noqa: E402
    AanvraagStatus,
    Maatregel,
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


def register(client, email: str) -> str:
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
                "organisation_type": "klant",
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


def promote_admin(email: str) -> None:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        u.role = UserRole.admin
        db.commit()


def seed_aanvraag(
    klant_email: str,
    *,
    regeling: RegelingCode,
    deadline_in_days: int | None,
    status: AanvraagStatus = AanvraagStatus.documenten,
) -> str:
    """Insert an aanvraag directly so we can pin its deadline anywhere."""
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == klant_email).one()
        a = SubsidieAanvraag(
            organisation_id=u.organisation_id,
            aanvrager_id=u.id,
            regeling=regeling,
            type_aanvrager=TypeAanvrager.particulier,
            status=status,
            maatregel=Maatregel.warmtepomp,
        )
        if deadline_in_days is not None:
            a.deadline_datum = date.today() + timedelta(days=deadline_in_days)
        db.add(a)
        db.commit()
        return str(a.id)


def get_warning_state(aanvraag_id: str) -> tuple[date | None, AanvraagStatus]:
    with SessionLocal() as db:
        a = db.query(SubsidieAanvraag).filter(SubsidieAanvraag.id == aanvraag_id).one()
        return a.last_deadline_warning_sent, a.status


def reset_warning(aanvraag_id: str) -> None:
    with SessionLocal() as db:
        a = db.query(SubsidieAanvraag).filter(SubsidieAanvraag.id == aanvraag_id).one()
        a.last_deadline_warning_sent = None
        db.commit()


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    klant_email = f"klant+{uuid4().hex[:8]}@example.com"
    admin_email = f"admin+{uuid4().hex[:8]}@example.com"

    klant_token = register(client, klant_email)
    admin_token = register(client, admin_email)
    promote_admin(admin_email)

    H = {"Authorization": f"Bearer {klant_token}"}
    H_ADMIN = {"Authorization": f"Bearer {admin_token}"}

    # -----------------------------------------------------------------
    # 1) GET /admin/regelingen returns 5 seeded entries
    # -----------------------------------------------------------------
    regelingen = _ok(client.get("/admin/regelingen", headers=H_ADMIN))
    codes = sorted(r["code"] for r in regelingen)
    assert codes == ["DUMAVA", "EIA", "ISDE", "MIA", "VAMIL"], codes
    by_code = {r["code"]: r for r in regelingen}
    assert by_code["ISDE"]["actief"] is True
    print("GET /admin/regelingen OK (5 regelingen, ISDE actief)")

    # Klant cannot reach this
    forbidden = client.get("/admin/regelingen", headers=H)
    assert forbidden.status_code == 403, forbidden.text
    print("klant -> /admin/regelingen -> 403 OK")

    # -----------------------------------------------------------------
    # 2) PATCH validation: fee_percentage > 100 should fail
    # -----------------------------------------------------------------
    bad = client.patch(
        "/admin/regelingen/ISDE",
        json={"fee_percentage": 250},
        headers=H_ADMIN,
    )
    assert bad.status_code == 422, bad.text
    bad2 = client.patch(
        "/admin/regelingen/ISDE",
        json={"fee_percentage": -5},
        headers=H_ADMIN,
    )
    assert bad2.status_code == 422, bad2.text
    print("PATCH validation (fee bounds) OK")

    # 404 for unknown code
    nope = client.patch(
        "/admin/regelingen/XYZ",
        json={"actief": False},
        headers=H_ADMIN,
    )
    assert nope.status_code == 404, nope.text
    print("PATCH unknown regeling -> 404 OK")

    # -----------------------------------------------------------------
    # 3) PATCH actief=False deactivates the regeling end-to-end
    # -----------------------------------------------------------------
    updated = _ok(
        client.patch(
            "/admin/regelingen/ISDE",
            json={"actief": False, "fee_percentage": 9, "naam": "ISDE-2026"},
            headers=H_ADMIN,
        )
    )
    assert updated["actief"] is False
    assert updated["naam"] == "ISDE-2026"
    assert float(updated["fee_percentage"]) == 9.0

    # subsidiecheck no longer offers ISDE
    sub = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "particulier",
                "maatregelen": ["warmtepomp"],
                "investering_bedrag": 10000,
                "offerte_beschikbaar": False,
            },
        )
    )
    matched_codes = [r["code"] for r in sub["regelingen"] if r["van_toepassing"]]
    assert "ISDE" not in matched_codes, matched_codes
    print("subsidiecheck respects actief=False OK")

    # creating a new ISDE aanvraag is rejected
    create = client.post(
        "/aanvragen",
        json={
            "regeling": "ISDE",
            "type_aanvrager": "particulier",
            "maatregel": "warmtepomp",
            "investering_bedrag": 10000,
            "offerte_beschikbaar": False,
        },
        headers=H,
    )
    assert create.status_code == 400, create.text
    print("create aanvraag respects actief=False -> 400 OK")

    # Re-activate (so the rest of the suite can still use ISDE)
    re_activated = _ok(
        client.patch(
            "/admin/regelingen/ISDE",
            json={"actief": True, "fee_percentage": 8, "naam": "ISDE"},
            headers=H_ADMIN,
        )
    )
    assert re_activated["actief"] is True

    # -----------------------------------------------------------------
    # 4) Deadline check: seed a fixture set
    # -----------------------------------------------------------------
    a_safe = seed_aanvraag(
        klant_email, regeling=RegelingCode.EIA, deadline_in_days=60
    )
    a_14 = seed_aanvraag(
        klant_email, regeling=RegelingCode.EIA, deadline_in_days=12
    )
    a_7 = seed_aanvraag(
        klant_email, regeling=RegelingCode.MIA, deadline_in_days=5
    )
    a_overdue = seed_aanvraag(
        klant_email, regeling=RegelingCode.DUMAVA, deadline_in_days=-3
    )
    a_done = seed_aanvraag(
        klant_email,
        regeling=RegelingCode.EIA,
        deadline_in_days=-30,
        status=AanvraagStatus.goedgekeurd,
    )
    a_no_deadline = seed_aanvraag(
        klant_email, regeling=RegelingCode.ISDE, deadline_in_days=None
    )

    # First run: only 14d, 7d, verlopen should send (3 emails); the
    # safe one + done one + no-deadline one are skipped.
    result = _ok(
        client.post("/admin/run-deadline-check", headers=H_ADMIN)
    )
    # checked counts: a_safe + a_14 + a_7 + a_overdue (a_done excluded;
    # a_no_deadline excluded by deadline_datum is_not(null))
    assert result["checked"] == 4, result
    assert result["warnings_sent"] == 3, result
    assert result["expired"] == 1, result
    assert result["skipped_recent"] == 0
    print(f"deadline run #1 OK: {result}")

    today = date.today()
    for aid, expect_sent in [
        (a_14, today),
        (a_7, today),
        (a_overdue, today),
        (a_safe, None),
        (a_done, None),
        (a_no_deadline, None),
    ]:
        last, _ = get_warning_state(aid)
        assert last == expect_sent, (aid, last, expect_sent)
    print("warning bookkeeping per aanvraag OK")

    # -----------------------------------------------------------------
    # 5) Re-run immediately: cooldown should suppress all warnings
    # -----------------------------------------------------------------
    result2 = _ok(
        client.post("/admin/run-deadline-check", headers=H_ADMIN)
    )
    assert result2["checked"] == 4
    assert result2["warnings_sent"] == 0
    assert result2["skipped_recent"] == 3
    print("deadline run #2 OK (cooldown active)")

    # -----------------------------------------------------------------
    # 6) Reset one warning timestamp -> it sends again next run
    # -----------------------------------------------------------------
    reset_warning(a_overdue)
    result3 = _ok(
        client.post("/admin/run-deadline-check", headers=H_ADMIN)
    )
    assert result3["warnings_sent"] == 1
    assert result3["expired"] == 1
    print("deadline run #3 OK (reset triggers resend)")

    # -----------------------------------------------------------------
    # 7) Klant cannot trigger the deadline check
    # -----------------------------------------------------------------
    forbidden = client.post("/admin/run-deadline-check", headers=H)
    assert forbidden.status_code == 403, forbidden.text
    print("klant -> /admin/run-deadline-check -> 403 OK")

    print("\nAll deadline + regelingen tests passed")


if __name__ == "__main__":
    main()
