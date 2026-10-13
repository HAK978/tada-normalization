"""The dry-run write path: canonical employees as UKG Ready create requests (A-63). Offline."""

import json
from decimal import Decimal
from pathlib import Path

from normalization.__main__ import main
from normalization.write.ukg_ready import plan

ROOT = Path(__file__).resolve().parents[1]


def employee(provider: str, suffix: str) -> dict:
    golden = json.loads((ROOT / f"tests/golden/{provider}/brightside.json").read_text(encoding="utf-8"))
    return next(e for e in golden["records"]["employees"] if e["id"].endswith(suffix))


def gaps(result) -> set[str]:
    return {g["field"] for g in result.gaps}


def test_a_ukg_employee_round_trips_into_valid_requests():
    result = plan(employee("ukg-ready", ":5001"), company="7001")
    assert result.valid and [r.path for r in result.requests] == [
        "/v2/companies/7001/employees",
        "/v2/companies/7001/compensation/history",
    ]
    person, pay = (r.body for r in result.requests)
    assert (person["username"], person["external_id"]) == ("mlopez", "ukg-ready:synthetic:employee:5001")
    assert (pay["amount"], pay["amount_period"], pay["time"], pay["time_period"]) == (
        Decimal("52000.0"),
        "YEAR",
        7488000000,
        "YEAR",
    )
    # Only the last 4 SSN digits exist in the canonical model, so the SSN is a gap, never filled in.
    assert gaps(result) == {"social_security"} and "social_security" not in person


def test_a_prism_salaried_employee_keeps_its_pay_basis_and_hours():
    result = plan(employee("prismhr", ":E1001"))
    pay = result.requests[1].body
    assert (pay["amount"], pay["amount_period"], pay["num_pp_in_year"]) == (Decimal("52000.00"), "YEAR", 26)
    assert (pay["time"], pay["time_period"]) == (80 * 3_600_000, "PAY_PERIOD")
    assert result.requests[0].body["address"]["country"] == "USA"
    assert [d["field"] for d in result.defaults] == ["address.country"]
    assert "address.county" in gaps(result)


def test_a_missing_required_value_is_a_gap_and_the_request_is_rejected():
    result = plan(employee("isolved", ":9001"))
    assert "username" in gaps(result) and not result.valid
    assert result.requests[0].errors == ["<root>: 'username' is a required property"]
    assert "username" not in result.requests[0].body


def test_an_invalid_source_date_leaves_the_pay_record_incomplete():
    result = plan(employee("prismhr", ":E1004"))  # its effective date is the 0000-01-01 placeholder (A-46)
    assert "effective_from" in gaps(result) and result.requests[1].errors


def test_write_command_writes_one_plan_per_employee_and_sends_nothing(tmp_path, capsys):
    employees = tmp_path / "employees.json"
    employees.write_text(json.dumps([employee("ukg-ready", ":5001"), employee("ukg-ready", ":5003")]), encoding="utf-8")
    assert main(["write", str(employees), "--company", "7001", "--out", str(tmp_path / "plans")]) == 0
    plans = sorted((tmp_path / "plans" / "ukg-ready").glob("*.json"))
    assert [p.name for p in plans] == [
        "ukg-ready_synthetic_employee_5001.json",
        "ukg-ready_synthetic_employee_5003.json",
    ]
    terminated = json.loads(plans[1].read_text(encoding="utf-8"))
    assert terminated["dry_run"] is True and any("TERMINATED" in note for note in terminated["notes"])
    assert "nothing sent" in capsys.readouterr().out
