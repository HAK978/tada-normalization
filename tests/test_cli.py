"""The command line and its outputs: JSON per record type, SQLite and the JSON Schemas. Offline."""

import json
import sqlite3
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from normalization.__main__ import main
from normalization.bundle import Bundle
from normalization.coverage import measure, render
from normalization.live.signin import API_KEY_VARIABLE

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("prismhr", "isolved", "ukg-ready")


def golden(provider: str) -> dict:
    return json.loads((ROOT / f"tests/golden/{provider}/brightside.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    assert main(["demo", "--out", str(out)]) == 0
    return out


@pytest.mark.parametrize("provider", PROVIDERS)
def test_demo_writes_each_record_type_as_json_matching_the_golden_file(demo, provider):
    expected = golden(provider)
    for kind, records in expected["records"].items():
        assert json.loads((demo / provider / f"{kind}.json").read_text(encoding="utf-8")) == records
    assert json.loads((demo / provider / "summary.json").read_text(encoding="utf-8")) == expected["summary"]


def test_demo_writes_one_sqlite_database_for_all_providers(demo):
    with sqlite3.connect(demo / "canonical.sqlite") as db:
        for kind in golden("prismhr")["records"]:
            count = db.execute(f"SELECT COUNT(*) FROM {kind}").fetchone()[0]
            assert count == sum(len(golden(p)["records"][kind]) for p in PROVIDERS), kind
        # Every reference resolves: fixtures fetch every employee their paychecks name.
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        providers = db.execute("SELECT DISTINCT provider FROM companies ORDER BY 1").fetchall()
        assert [p for (p,) in providers] == sorted(PROVIDERS)


def test_sqlite_keeps_exact_money_and_the_whole_record(demo):
    statement = next(s for s in golden("ukg-ready")["records"]["pay_statements"] if s["id"].endswith(":7101"))
    with sqlite3.connect(demo / "canonical.sqlite") as db:
        row = db.execute(
            "SELECT gross_wages, gross_pay, employee_taxes, record FROM pay_statements WHERE id = ?", (statement["id"],)
        ).fetchone()
        tax = db.execute(
            "SELECT amount FROM tax_lines WHERE pay_statement_id = ? AND code = 'SIT:NC'", (statement["id"],)
        ).fetchone()
    assert row[:3] == ("2028.10", "2025.00", "307.6199999999999998")
    assert tax == ("2.4699999999999998",)
    assert json.loads(row[3]) == statement


def test_sqlite_lists_contacts_and_organization_units_by_employee(demo):
    with sqlite3.connect(demo / "canonical.sqlite") as db:
        roles = db.execute(
            "SELECT roles FROM employee_contacts WHERE employee_id = ? ORDER BY line",
            ("ukg-ready:synthetic:employee:5001",),
        ).fetchall()
        units = db.execute(
            "SELECT dimension, name, path FROM employee_org_units WHERE employee_id = ? ORDER BY line",
            ("ukg-ready:synthetic:employee:5001",),
        ).fetchall()
    assert roles == [("EMERGENCY,DEPENDENT,BENEFICIARY",), ("DEPENDENT",)]
    assert units == [
        ("Location-Dept", "Production", "Charlotte / Production"),
        ("Position", "Store Manager", "Store Manager"),
    ]


def test_sqlite_overview_joins_paychecks_to_employees_and_checks(demo):
    with sqlite3.connect(demo / "canonical.sqlite") as db:
        rows = db.execute(
            "SELECT provider, first_name, checks_passed, checks_failed FROM pay_statement_overview "
            "WHERE id LIKE '%:7101'"
        ).fetchall()
    assert rows == [("ukg-ready", "Maria", 1, 0)]


def test_normalize_writes_the_same_records_as_the_golden_file(tmp_path):
    bundle = ROOT / "fixtures/isolved/brightside"
    assert main(["normalize", str(bundle), "--out", str(tmp_path), "--no-sqlite"]) == 0
    expected = golden("isolved")["records"]
    assert {p.name for p in tmp_path.iterdir()} == {f"{kind}.json" for kind in expected} | {
        "summary.json",
        "provenance.json",
    }
    assert json.loads((tmp_path / "employees.json").read_text(encoding="utf-8")) == expected["employees"]


def test_normalize_reports_a_missing_bundle(tmp_path, capsys):
    assert main(["normalize", str(tmp_path / "nothing-here")]) == 1
    assert "cannot normalize" in capsys.readouterr().err


def test_fetch_without_an_api_key_stops_before_any_request(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    empty = tmp_path / ".env"
    empty.write_text("", encoding="utf-8")
    args = ["fetch", "--provider", "ukg-ready", "--env-file", str(empty), "--out", str(tmp_path / "bundles")]
    assert main(args) == 1
    assert API_KEY_VARIABLE in capsys.readouterr().err
    assert not (tmp_path / "bundles").exists()


def test_committed_json_schemas_match_the_model(tmp_path):
    assert main(["schema", "--out", str(tmp_path)]) == 0
    for path in sorted(tmp_path.glob("*.schema.json")):
        committed = ROOT / "schemas" / path.name
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), path.name


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_golden_record_matches_its_exported_schema(provider):
    for kind, records in golden(provider)["records"].items():
        validator = Draft202012Validator(json.loads((ROOT / f"schemas/{kind}.schema.json").read_text(encoding="utf-8")))
        for record in records:
            assert not list(validator.iter_errors(record)), record["id"]


@pytest.fixture(scope="module")
def coverage():
    return {p: measure(Bundle.load(ROOT / f"fixtures/{p}/brightside"), "fixture") for p in PROVIDERS}


@pytest.mark.parametrize("provider", PROVIDERS)
def test_no_field_is_both_mapped_and_kept(coverage, provider):
    assert coverage[provider].read_after_kept == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_no_field_is_lost_neither_mapped_nor_kept(coverage, provider):
    # Before A-73, isolved salary history and PrismHR pay rate history dropped what they didn't map.
    assert coverage[provider].lost == []


def test_coverage_labels_dropped_kept_and_mapped_fields(coverage):
    ukg = coverage["ukg-ready"]
    assert ukg.label(("rest/v2/companies/{company}/employees/{id}", "photo_href")).startswith("dropped: a signed link")
    assert ukg.label(("rest/v2/companies/{company}/employees/{id}", "social_security")) == "mapped"
    isolved = coverage["isolved"]
    # Status history is mapped (A-76); what it has no canonical field for is kept on the record.
    statuses = "api/clients/{client}/legals/{legal}/employees/{id}/statuses"
    assert isolved.label((statuses, "[].effectiveDate")) == "mapped"
    assert isolved.label((statuses, "[].statusId")) == "kept"
    assert (
        isolved.label(("api/clients/{client}/legals/{legal}/employees/{id}/statuses", "[].isImpliedStatus")) == "mapped"
    )


def test_coverage_counts_how_many_employees_have_each_canonical_field(coverage):
    # The count that would have shown fields never fetched: UKG gender was empty for every employee (A-74).
    ukg = coverage["ukg-ready"]
    assert ukg.employees == 5
    assert ukg.employee_fields["personal.gender"] == 4  # one employee's demographics are empty
    assert ukg.employee_fields["job.department"] == 0  # UKG's organization is in org_units (A-75)
    assert "| `personal.gender` | 6 | 5 | 4 |" in render(list(coverage.values()))


def test_only_crawl_indexes_duplicates_and_unneeded_lookups_go_unread(coverage):
    unread = {(r.provider, e) for r in coverage.values() for (e, _), c in r.fields.items() if set(c) == {"unused"}}
    assert unread <= {
        # Crawl indexes: the converters read each record's own response instead.
        ("prismhr", "employee/v1/getEmployeeList"),
        ("isolved", "api/clients/{client}/legals/{legal}/employees"),
        ("ukg-ready", "rest/v2/companies/{company}/employees"),
        # List rows whose detail response was used instead.
        ("isolved", "api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory"),
        ("ukg-ready", "rest/v2/companies/{company}/payrolls"),
        # Lookups the converters don't need: the lines carry their own codes and names.
        ("isolved", "api/system/payTypes"),
        ("ukg-ready", "rest/v2/companies/{company}/lookup/earning-codes"),
        ("ukg-ready", "rest/v2/companies/{company}/lookup/deduction-codes"),
        ("ukg-ready", "rest/v2/companies/{company}/lookup/payroll-types"),
        ("ukg-ready", "rest/v2/companies/{company}/lookup/pay-statement-types"),
    }, unread


def test_coverage_command_writes_the_report(tmp_path):
    out = tmp_path / "FIELD_COVERAGE.md"
    assert main(["coverage", "--out", str(out)]) == 0
    report = out.read_text(encoding="utf-8")
    assert report.startswith("# Field coverage") and "| `photo_href` | dropped: a signed link" in report
