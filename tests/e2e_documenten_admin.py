"""Live smoke test for document upload (R2 stub) + admin routes."""
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


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=15.0)

    klant_email = f"klant+{uuid4().hex[:8]}@example.com"
    other_email = f"other+{uuid4().hex[:8]}@example.com"
    admin_email = f"admin+{uuid4().hex[:8]}@example.com"

    klant_token = register(client, klant_email)
    other_token = register(client, other_email)
    admin_token = register(client, admin_email)
    promote_admin(admin_email)

    H = {"Authorization": f"Bearer {klant_token}"}
    H_OTHER = {"Authorization": f"Bearer {other_token}"}
    H_ADMIN = {"Authorization": f"Bearer {admin_token}"}

    # ---------------------------------------------------------------
    # Setup: create one ISDE aanvraag for the klant
    # ---------------------------------------------------------------
    aan = _ok(
        client.post(
            "/aanvragen",
            json={
                "regeling": "ISDE",
                "type_aanvrager": "particulier",
                "maatregel": "warmtepomp",
                "investering_bedrag": 10000,
                "offerte_beschikbaar": False,
            },
            headers=H,
        ),
        201,
    )
    aan_id = aan["id"]
    print("setup aanvraag OK")

    # ---------------------------------------------------------------
    # 1) Request upload URL for invalid doc type for ISDE -> 422
    # ---------------------------------------------------------------
    bad = client.post(
        f"/aanvragen/{aan_id}/documenten/upload-url",
        json={
            "document_type": "maatwerkadvies",
            "filename": "rapport.pdf",
            "content_type": "application/pdf",
        },
        headers=H,
    )
    assert bad.status_code == 422, bad.text
    print("invalid doc-type for regeling -> 422 OK")

    # ---------------------------------------------------------------
    # 2) Request upload URL for valid type
    # ---------------------------------------------------------------
    presign = _ok(
        client.post(
            f"/aanvragen/{aan_id}/documenten/upload-url",
            json={
                "document_type": "offerte",
                "filename": "Mijn Offerte.pdf",
                "content_type": "application/pdf",
            },
            headers=H,
        ),
        201,
    )
    assert presign["upload_url"].startswith("https://r2.local/")
    assert presign["object_key"].endswith("/Mijn_Offerte.pdf")
    assert presign["expires_in"] == 3600
    doc_id = presign["document_id"]
    print("presign upload OK")

    # Pending doc should NOT count as uploaded yet.
    detail = _ok(client.get(f"/aanvragen/{aan_id}", headers=H))
    assert detail["status"] == "intake"
    assert detail["documenten"] == []  # filtered out (pending)
    cl = _ok(client.get(f"/aanvragen/{aan_id}/documenten", headers=H))
    assert cl["uploaded_count"] == 0
    assert cl["missing_count"] == 6
    print("pending-not-counted OK")

    # ---------------------------------------------------------------
    # 3) Confirm upload -> doc counts + status auto-advances to documenten
    # ---------------------------------------------------------------
    confirmed = _ok(
        client.post(
            f"/aanvragen/{aan_id}/documenten/{doc_id}/confirm",
            headers=H,
        )
    )
    assert confirmed["pending_upload"] is False
    assert confirmed["verified"] is False
    assert confirmed["storage_url"].startswith("r2://")

    detail = _ok(client.get(f"/aanvragen/{aan_id}", headers=H))
    assert detail["status"] == "documenten"
    assert len(detail["documenten"]) == 1
    cl = _ok(client.get(f"/aanvragen/{aan_id}/documenten", headers=H))
    assert cl["uploaded_count"] == 1
    assert cl["missing_count"] == 5
    offerte_item = next(
        it for it in cl["items"] if it["document_type"] == "offerte"
    )
    assert offerte_item["uploaded"] is True
    assert offerte_item["verified"] is False
    assert offerte_item["document_id"] == doc_id
    print("confirm + status auto-advance OK")

    # ---------------------------------------------------------------
    # 4) Download URL for confirmed doc
    # ---------------------------------------------------------------
    dl = _ok(
        client.get(
            f"/aanvragen/{aan_id}/documenten/{doc_id}/download-url",
            headers=H,
        )
    )
    assert dl["expires_in"] == 900
    assert dl["download_url"].startswith("https://r2.local/")
    print("download URL OK")

    # ---------------------------------------------------------------
    # 5) Cross-org isolation: other klant can't access uploads/downloads
    # ---------------------------------------------------------------
    forbidden = client.get(
        f"/aanvragen/{aan_id}/documenten/{doc_id}/download-url",
        headers=H_OTHER,
    )
    assert forbidden.status_code == 403
    forbidden_post = client.post(
        f"/aanvragen/{aan_id}/documenten/upload-url",
        json={
            "document_type": "offerte",
            "filename": "x.pdf",
            "content_type": "application/pdf",
        },
        headers=H_OTHER,
    )
    assert forbidden_post.status_code == 403
    print("cross-org blocked OK")

    # ---------------------------------------------------------------
    # 6) Admin verifies the doc; client then can't delete it
    # ---------------------------------------------------------------
    verified = _ok(
        client.patch(
            f"/admin/documenten/{doc_id}/verify",
            headers=H_ADMIN,
        )
    )
    assert verified["verified"] is True
    cl_after = _ok(client.get(f"/aanvragen/{aan_id}/documenten", headers=H))
    item = next(it for it in cl_after["items"] if it["document_id"] == doc_id)
    assert item["verified"] is True

    cant_delete = client.delete(
        f"/aanvragen/{aan_id}/documenten/{doc_id}", headers=H
    )
    assert cant_delete.status_code == 403, cant_delete.text
    # Admin can still delete (allowed)
    print("verify + client-can't-delete-verified OK")

    # ---------------------------------------------------------------
    # 7) Add another doc, then delete it as klant
    # ---------------------------------------------------------------
    p2 = _ok(
        client.post(
            f"/aanvragen/{aan_id}/documenten/upload-url",
            json={
                "document_type": "factuur",
                "filename": "factuur.pdf",
                "content_type": "application/pdf",
            },
            headers=H,
        ),
        201,
    )
    _ok(
        client.post(
            f"/aanvragen/{aan_id}/documenten/{p2['document_id']}/confirm",
            headers=H,
        )
    )
    deleted = client.delete(
        f"/aanvragen/{aan_id}/documenten/{p2['document_id']}", headers=H
    )
    assert deleted.status_code == 204
    cl_after2 = _ok(client.get(f"/aanvragen/{aan_id}/documenten", headers=H))
    assert cl_after2["uploaded_count"] == 1  # only the verified one remains
    print("delete unverified OK")

    # ---------------------------------------------------------------
    # 8) Admin dashboard
    # ---------------------------------------------------------------
    dash = _ok(client.get("/admin/dashboard", headers=H_ADMIN))
    assert dash["totaal_aanvragen"] >= 1
    assert dash["per_status"]["documenten"] >= 1
    assert dash["per_regeling"]["ISDE"] >= 1
    assert Decimal(dash["totaal_geschatte_subsidie"]) >= Decimal("2500.00")
    assert dash["aanvragen_deze_maand"] >= 1
    assert dash["deadlines_verlopen"] >= 0
    assert dash["deadlines_binnen_14_dagen"] >= 0
    print("admin dashboard OK")

    # ---------------------------------------------------------------
    # 9) Admin aanvragen list + filters + pagination
    # ---------------------------------------------------------------
    page = _ok(client.get("/admin/aanvragen", headers=H_ADMIN))
    assert page["total"] >= 1
    assert page["page"] == 1
    assert page["per_page"] == 20
    assert any(it["id"] == aan_id for it in page["items"])
    first = next(it for it in page["items"] if it["id"] == aan_id)
    assert first["organisation_name"].startswith("Org klant+")
    assert first["aanvrager_email"] == klant_email

    # Filter by status
    filtered = _ok(
        client.get("/admin/aanvragen?status=documenten", headers=H_ADMIN)
    )
    assert filtered["total"] >= 1
    none = _ok(client.get("/admin/aanvragen?status=goedgekeurd", headers=H_ADMIN))
    assert none["total"] == 0
    bad_filter = client.get("/admin/aanvragen?status=xx", headers=H_ADMIN)
    assert bad_filter.status_code == 422
    # Pagination shapes
    paged = _ok(
        client.get("/admin/aanvragen?page=1&per_page=1", headers=H_ADMIN)
    )
    assert paged["per_page"] == 1
    assert len(paged["items"]) == 1
    print("admin list + filters OK")

    # ---------------------------------------------------------------
    # 10) Status update: requires toegekende_subsidie when goedkeuring
    # ---------------------------------------------------------------
    bad_approve = client.patch(
        f"/admin/aanvragen/{aan_id}/status",
        json={"status": "goedgekeurd"},
        headers=H_ADMIN,
    )
    assert bad_approve.status_code == 422

    bad_reject = client.patch(
        f"/admin/aanvragen/{aan_id}/status",
        json={"status": "afgewezen"},
        headers=H_ADMIN,
    )
    assert bad_reject.status_code == 422

    approved = _ok(
        client.patch(
            f"/admin/aanvragen/{aan_id}/status",
            json={"status": "goedgekeurd", "toegekende_subsidie": 2500},
            headers=H_ADMIN,
        )
    )
    assert approved["status"] == "goedgekeurd"
    # Fee is 8% of 2500 = 200
    assert Decimal(approved["toegekende_subsidie"]) == Decimal("2500")
    assert Decimal(approved["aaa_lex_fee_bedrag"]) == Decimal("200.00")

    # Detail should reflect new status + recomputed klant_ontvangt
    after = _ok(client.get(f"/aanvragen/{aan_id}", headers=H))
    assert after["status"] == "goedgekeurd"
    assert Decimal(after["toegekende_subsidie"]) == Decimal("2500.00")
    print("status -> goedgekeurd OK (with fee recompute + email triggered)")

    # Reject another aanvraag flow
    other_aan = _ok(
        client.post(
            "/aanvragen",
            json={
                "regeling": "ISDE",
                "type_aanvrager": "particulier",
                "maatregel": "isolatie",
                "investering_bedrag": 5000,
                "offerte_beschikbaar": False,
            },
            headers=H,
        ),
        201,
    )
    rej = _ok(
        client.patch(
            f"/admin/aanvragen/{other_aan['id']}/status",
            json={
                "status": "afgewezen",
                "notes": "Adres komt niet overeen met BAG-registratie.",
            },
            headers=H_ADMIN,
        )
    )
    assert rej["status"] == "afgewezen"
    assert "BAG" in (rej["notes"] or "")
    print("status -> afgewezen OK")

    # ---------------------------------------------------------------
    # 11) Klanten + Installateurs lijsten
    # ---------------------------------------------------------------
    klanten = _ok(client.get("/admin/klanten", headers=H_ADMIN))
    assert any(k["primary_contact_email"] == klant_email for k in klanten)
    me_klant = next(
        k for k in klanten if k["primary_contact_email"] == klant_email
    )
    assert me_klant["aanvraag_count"] >= 2
    # The approved one contributes toegekende_subsidie
    assert Decimal(me_klant["totaal_toegekende_subsidie"]) >= Decimal("2500.00")
    installateurs = _ok(client.get("/admin/installateurs", headers=H_ADMIN))
    assert isinstance(installateurs, list)
    print("admin klanten/installateurs OK")

    # ---------------------------------------------------------------
    # 12) Non-admin can't reach admin routes
    # ---------------------------------------------------------------
    forb = client.get("/admin/dashboard", headers=H)
    assert forb.status_code == 403
    forb2 = client.patch(
        f"/admin/aanvragen/{aan_id}/status",
        json={"status": "review"},
        headers=H,
    )
    assert forb2.status_code == 403
    forb3 = client.patch(
        f"/admin/documenten/{doc_id}/verify",
        headers=H,
    )
    assert forb3.status_code == 403
    print("admin-only enforced OK")

    # ---------------------------------------------------------------
    # 13) Validation: 404 for missing aanvraag/document
    # ---------------------------------------------------------------
    missing = client.get(
        f"/aanvragen/{uuid4()}/documenten/{uuid4()}/download-url",
        headers=H_ADMIN,
    )
    assert missing.status_code == 404
    print("404 OK")

    print("\nAll documenten + admin tests passed")


if __name__ == "__main__":
    main()
