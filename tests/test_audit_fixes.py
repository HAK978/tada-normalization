"""Regression tests for the implementation audit of 2026-10-13. Each changes a synthetic bundle in
memory the way the audit's reproduction did, and checks the fixed behavior."""

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from normalization import exactjson
from normalization.bundle import Bundle
from normalization.canonical import codes as C
from normalization.canonical.records import EarningLine, PayStatement, PayStatementTotals
from normalization.canonical.types import Coded, Money, Source
from normalization.checks import reconcile
from normalization.export import write_sqlite
from normalization.providers import normalize

ROOT = Path(__file__).resolve().parents[1]


def bundle(provider: str) -> Bundle:
    return Bundle.load(ROOT / f"fixtures/{provider}/brightside")


def capture(b: Bundle, endpoint: str, path_end: str = ""):
    return next(c for c in b.captures if c.endpoint == endpoint and c.path.endswith(path_end))


def one(out, kind, suffix):
    return next(r for r in out.records[kind] if r.id.endswith(suffix))


def codes(record):
    return {d.code for d in record.diagnostics}


def test_a_failed_sqlite_export_keeps_the_previous_database(tmp_path):
    database = tmp_path / "canonical.sqlite"
    good = normalize(bundle("prismhr"))
    write_sqlite([good], database)
    with pytest.raises(sqlite3.IntegrityError):
        write_sqlite([good, good], database)  # every ID twice
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 2
    assert not list(tmp_path.glob("*.building"))


def test_a_ukg_deposit_amount_is_in_the_deposits_own_currency():
    b = bundle("ukg-ready")
    deposit = capture(b, "rest/v2/companies/{company}/employees/{id}/direct-deposits", "5001/direct-deposits")
    deposit.body["deposits"][0]["currency"] = "EUR"
    record = one(normalize(b), "direct_deposits", ":4001")
    assert (record.currency, record.amount.currency) == ("EUR", "EUR")


def test_prism_endpoints_that_disagree_give_one_election_and_a_conflict():
    b = bundle("prismhr")
    rows = [
        r
        for c in b.captures
        if c.endpoint == "deductions/v1/getVoluntaryRecurringDeductions"
        for r in c.body["voluntaryDeduction"]["deduction"]
    ]
    life = next(r for r in rows if r["deductionCode"] == "LIFE")
    life["amount"] = str(Decimal(str(life["amount"])) + 1)
    elections = [e for e in normalize(b).records["deduction_elections"] if ":LIFE:" in e.id]
    assert len(elections) == 1 and "SOURCE_CONFLICT" in codes(elections[0])
    assert any(k.endswith(".amount") for k in elections[0].provider_extensions)


def test_isolved_keeps_calculation_parameters_it_does_not_use():
    b = bundle("isolved")
    items = capture(b, "api/clients/{client}/legals/{legal}/employees/{id}/payItems", "9001/payItems")
    deduction = next(r for r in items.body if r["payItemType"] == "Deduction")
    deduction["calcParams"].append({"paramType": "UnverifiedCeiling", "paramValue": Decimal("98765.43")})
    election = one(normalize(b), "deduction_elections", f":{deduction['id']}")
    kept = {v for k, v in election.provider_extensions.items() if k.startswith("calcParams[")}
    assert {"UnverifiedCeiling", Decimal("98765.43")} <= kept


def test_isolved_keeps_units_when_a_line_also_has_hours():
    b = bundle("isolved")
    check = capture(b, "api/clients/{client}/legals/{legal}/employees/{id}/checks/{id}", "/70001")
    regular = next(e for e in check.body["earnings"] if e["itemDescription"] == "Regular")
    regular["checkUnits"] = Decimal("98765.43")
    statement = one(normalize(b), "pay_statements", ":70001")
    line = next(e for e in statement.earnings if e.code == "Regular")
    assert line.quantity.unit.value == "HOURS"
    assert Decimal("98765.43") in statement.provider_extensions.values()


def test_a_ukg_payment_of_unknown_kind_blocks_the_derived_net():
    b = bundle("ukg-ready")
    statement = capture(b, "rest/v2/companies/{company}/payrolls/{id}/pay-statements/{id}", "/7101")
    statement.body["payments"].append({"type_name": "New Payment Kind", "ee_amount": 17.0})
    record = one(normalize(b), "pay_statements", ":7101")
    assert record.totals.net_pay is None and "NET_PAY_NOT_DERIVED" in codes(record)


def test_a_real_zero_ukg_pay_is_kept():
    b = bundle("ukg-ready")
    history = capture(b, "rest/v2/companies/{company}/employees/{id}/compensation/history", "5001/compensation/history")
    row = next(r for r in history.body["compensations"] if r["effective_from"] == "2024-01-01")
    row["amount"], row["hourly_pay"] = 0.0, 0.0
    change = next(
        h for h in one(normalize(b), "employees", ":5001").compensation.history if str(h.effective_date) == "2024-01-01"
    )
    assert [(r.amount, r.per.value) for r in change.rates] == [(Decimal("0.0"), "YEAR"), (Decimal("0.0"), "HOUR")]
    assert change.annual_pay.amount == Decimal("0")


def test_a_prism_error_inside_http_200_is_reported():
    b = bundle("prismhr")
    master = capture(b, "clientMaster/v1/getClientMaster")
    master.body = {"errorCode": "403", "errorMessage": "Synthetic permission failure"}
    company = one(normalize(b), "companies", f":{master.params['clientId']}")
    assert company.name is None
    assert any(d.code == "SOURCE_ERROR" and d.raw == "403" for d in company.diagnostics)


def test_the_gross_comparison_needs_every_line_classified():
    def line(kind, amount):
        return EarningLine(
            kind=Coded[C.EarningKind](value=kind, source_field="t"),
            in_gross=True,
            amount=Money(amount=Decimal(amount)),
            source_field="t",
        )

    statement = PayStatement(
        id="t:1",
        source=Source(provider="t", tenant_id="t"),
        company_id="c",
        employee_id="e",
        type=Coded[C.PayStatementType](value=C.PayStatementType.REGULAR, source_field="t"),
        totals=PayStatementTotals(gross_wages=Money(amount=Decimal("103")), gross_pay=Money(amount=Decimal("100"))),
        earnings=[line(C.EarningKind.EARNINGS, "100"), line(C.EarningKind.UNMAPPED, "3")],
    )
    assert [c.rule for c in reconcile(statement)] == ["gross wages = sum of earning lines counted in gross"]


def test_a_string_that_looks_like_the_number_marker_stays_a_string():
    text = exactjson.dumps({"raw": "\u0000exact-number:123", "n": Decimal("0.123456789123456789")})
    assert exactjson.loads(text) == {"raw": "\u0000exact-number:123", "n": Decimal("0.123456789123456789")}
