"""Live smoke test for POST /api/v1/subsidiecheck/bereken."""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8767/api/v1")


def _ok(resp: httpx.Response, *expected: int) -> dict:
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

    # 1) Particulier + warmtepomp, geen offerte
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "particulier",
                "maatregelen": ["warmtepomp"],
                "type_pand": "woning",
                "investering_bedrag": 9000,
                "offerte_beschikbaar": False,
            },
        )
    )
    by_code = {x["code"]: x for x in r["regelingen"]}
    assert by_code["ISDE"]["van_toepassing"] is True
    assert by_code["EIA"]["van_toepassing"] is False
    assert by_code["DUMAVA"]["van_toepassing"] is False
    # ISDE 25% van 9000 = 2250; fee 8% van 2250 = 180; klant ontvangt = 2070
    assert Decimal(by_code["ISDE"]["geschatte_subsidie"]) == Decimal("2250.00")
    assert Decimal(by_code["ISDE"]["aaa_lex_fee"]) == Decimal("180.00")
    assert Decimal(by_code["ISDE"]["klant_ontvangt"]) == Decimal("2070.00")
    assert Decimal(r["totaal_geschatte_subsidie"]) == Decimal("2250.00")
    assert Decimal(r["totaal_klant_ontvangt"]) == Decimal("2070.00")
    # zonneboiler-warning moet meekomen voor particulier + warmtepomp
    assert any("Zonneboilers" in w for w in r["waarschuwingen"]), r["waarschuwingen"]
    print("particulier+warmtepomp OK")

    # 2) Ondernemer + energiesysteem + offerte beschikbaar -> EIA/MIA/VAMIL
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "ondernemer",
                "maatregelen": ["energiesysteem"],
                "type_pand": "bedrijfspand",
                "investering_bedrag": 8000,
                "offerte_beschikbaar": True,
            },
        )
    )
    by = {x["code"]: x for x in r["regelingen"]}
    assert by["EIA"]["van_toepassing"] is True
    assert by["MIA"]["van_toepassing"] is True
    assert by["VAMIL"]["van_toepassing"] is True
    assert by["ISDE"]["van_toepassing"] is False
    assert by["DUMAVA"]["van_toepassing"] is False
    # deadline_info gevuld bij EIA/MIA/VAMIL omdat offerte_beschikbaar=True
    assert by["EIA"]["deadline_info"] and "3 maanden" in by["EIA"]["deadline_info"]
    # 3-maanden-waarschuwing aanwezig
    assert any("3 maanden" in w for w in r["waarschuwingen"]), r["waarschuwingen"]
    # EIA 45.5% van 8000 = 3640; fee 5% van 3640 = 182; klant = 3458
    assert Decimal(by["EIA"]["geschatte_subsidie"]) == Decimal("3640.00")
    assert Decimal(by["EIA"]["aaa_lex_fee"]) == Decimal("182.00")
    assert Decimal(by["EIA"]["klant_ontvangt"]) == Decimal("3458.00")
    print("ondernemer+offerte OK")

    # 3) Ondernemer onder de drempel -> niks
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "ondernemer",
                "maatregelen": ["energiesysteem"],
                "type_pand": "bedrijfspand",
                "investering_bedrag": 1000,
                "offerte_beschikbaar": False,
            },
        )
    )
    assert not any(x["van_toepassing"] for x in r["regelingen"])
    assert any("Geen standaardregelingen" in w for w in r["waarschuwingen"])
    print("ondernemer-onder-drempel OK")

    # 4) Maatschappelijk -> DUMAVA, deadline_info altijd aanwezig
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "maatschappelijk",
                "maatregelen": ["isolatie", "warmtepomp"],
                "type_pand": "maatschappelijk",
                "investering_bedrag": 50000,
                "offerte_beschikbaar": False,
            },
        )
    )
    by = {x["code"]: x for x in r["regelingen"]}
    assert by["DUMAVA"]["van_toepassing"] is True
    assert by["DUMAVA"]["deadline_info"] and "uitvoering" in by["DUMAVA"]["deadline_info"]
    assert any("DUMAVA" in w for w in r["waarschuwingen"])
    # 30% van 50000 = 15000; fee 10% = 1500; klant = 13500
    assert Decimal(by["DUMAVA"]["geschatte_subsidie"]) == Decimal("15000.00")
    assert Decimal(by["DUMAVA"]["aaa_lex_fee"]) == Decimal("1500.00")
    assert Decimal(by["DUMAVA"]["klant_ontvangt"]) == Decimal("13500.00")
    print("maatschappelijk+DUMAVA OK")

    # 5) Geen investering_bedrag -> van_toepassing kan True zijn maar subsidie=None
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "particulier",
                "maatregelen": ["isolatie"],
                "offerte_beschikbaar": False,
            },
        )
    )
    by = {x["code"]: x for x in r["regelingen"]}
    assert by["ISDE"]["van_toepassing"] is True
    assert by["ISDE"]["geschatte_subsidie"] is None
    assert by["ISDE"]["aaa_lex_fee"] is None
    assert by["ISDE"]["klant_ontvangt"] is None
    # Totaal blijft 0
    assert Decimal(r["totaal_geschatte_subsidie"]) == Decimal("0.00")
    print("particulier zonder bedrag OK")

    # 6) VvE + isolatie -> ISDE
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "vve",
                "maatregelen": ["isolatie"],
                "offerte_beschikbaar": False,
            },
        )
    )
    by = {x["code"]: x for x in r["regelingen"]}
    assert by["ISDE"]["van_toepassing"] is True
    print("vve+isolatie OK")

    # 7) Vereiste documenten zijn altijd aanwezig per regeling
    for code, entry in by.items():
        assert isinstance(entry["vereiste_documenten"], list)
    assert len(by["DUMAVA"]["vereiste_documenten"]) >= 5
    print("vereiste_documenten OK")

    # 8) No-auth required: zonder token lukt het ook
    r = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "particulier",
                "maatregelen": ["warmtepomp"],
                "offerte_beschikbaar": False,
            },
            headers={"Authorization": "Bearer garbage"},
        )
    )
    assert "regelingen" in r
    print("public endpoint OK")

    # 9) Validatie: geen maatregelen -> 422
    bad = client.post(
        "/subsidiecheck/bereken",
        json={"type_aanvrager": "particulier", "maatregelen": [], "offerte_beschikbaar": False},
    )
    assert bad.status_code == 422, bad.text
    print("validation 422 OK")

    # 10) volgende_stap variants
    r_match = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "particulier",
                "maatregelen": ["warmtepomp"],
                "offerte_beschikbaar": False,
            },
        )
    )
    assert "Maak een account" in r_match["volgende_stap"]
    r_nomatch = _ok(
        client.post(
            "/subsidiecheck/bereken",
            json={
                "type_aanvrager": "ondernemer",
                "maatregelen": ["warmtepomp"],
                "investering_bedrag": 100,
                "offerte_beschikbaar": False,
            },
        )
    )
    assert "contact op" in r_nomatch["volgende_stap"]
    print("volgende_stap variants OK")

    print("\nAll subsidiecheck tests passed")


if __name__ == "__main__":
    main()
