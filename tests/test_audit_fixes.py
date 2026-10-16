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
    assert any(d.code == "SOURCE_UNAVAILABLE" and d.raw == "403" for d in company.diagnostics)  # A-70


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
    # The comparison with gross pay can't stand on an unknown kind: reported as not applicable, not left out (A-73).
    assert [(c.rule, c.result.value) for c in reconcile(statement)] == [
        ("gross wages = sum of earning lines counted in gross", "pass"),
        ("gross wages - non-cash earnings = gross pay", "not_applicable"),
    ]


def test_a_string_that_looks_like_the_number_marker_stays_a_string():
    text = exactjson.dumps({"raw": "\u0000exact-number:123", "n": Decimal("0.123456789123456789")})
    assert exactjson.loads(text) == {"raw": "\u0000exact-number:123", "n": Decimal("0.123456789123456789")}


# Found by the type checker (mypy): inputs that used to crash a run.


def test_nan_and_infinity_are_not_amounts():
    from normalization.source import decimal

    assert [decimal(v) for v in ("NaN", "Infinity", "-inf", "sNaN")] == [None, None, None, None]
    b = bundle("ukg-ready")
    statement = capture(b, "rest/v2/companies/{company}/payrolls/{id}/pay-statements/{id}", "/7101")
    statement.body["taxes"][0]["ee_amount"] = "NaN"
    record = one(normalize(b), "pay_statements", ":7101")
    assert record.model_dump_json()  # serializes instead of crashing
    # "NaN" is no amount, so there is no FIT line; the paycheck no longer adds up, and that is reported.
    assert "FIT" not in {t.code for t in record.taxes} and "RECONCILIATION_MISMATCH" in codes(record)


def test_a_ukg_lookup_row_without_an_id_is_skipped():
    b = bundle("ukg-ready")
    capture(b, "rest/v2/companies/{company}/lookup/eins").body["items"].append({"ein_name": "No ID"})
    company = one(normalize(b), "companies", ":7001")
    assert [e.provider_id for e in company.employers] == ["801", "802"]


def test_a_prism_pay_card_account_keeps_only_its_last_4():
    # clientMaster.payCardAccount, "Account used to pay cards/debit cards", is a full account number live.
    from normalization.sanitize import sanitize_extensions, sweep

    assert sanitize_extensions({"clientMaster.payCardAccount": "123456789"}) == {
        "clientMaster.payCardAccount": "***6789"
    }
    assert sweep({"clientMaster": {"payCardAccount": 123456789}}) == {"clientMaster": {"payCardAccount": "***6789"}}


# ---------------------------------------------------------------- the audit of 2026-10-15 (Codex): partial addresses


def test_a_ukg_address_with_a_state_but_no_street_is_kept():
    # UKG requires only country in an address (#/schemas/106 address), so a state without a street is valid.
    b = bundle("ukg-ready")
    capture(b, "rest/v2/companies/{company}/employees/{id}", "/5001").body["mailing_address"] = {
        "country": "CAN",
        "state_code": "ON",
    }
    mailing = [a for a in one(normalize(b), "employees", ":5001").addresses if a.type is C.AddressType.MAILING]
    assert [(a.state, a.country) for a in mailing] == [("ON", "CAN")]


@pytest.mark.parametrize("provider", ["isolved", "ukg-ready"])
def test_a_paycheck_known_only_from_a_list_says_its_lines_are_unknown(provider):
    # Its line lists are empty because the lines weren't fetched, not because there are none (A-51, A-70).
    statements = normalize(bundle(provider)).records["pay_statements"]
    listed = [s for s in statements if "DETAIL_NOT_FETCHED" in codes(s)]
    assert listed and all(not s.lines_fetched and not s.taxes for s in listed)
    assert all(s.lines_fetched for s in statements if s not in listed)


def test_an_isolved_pay_item_the_client_offers_but_never_assigned_is_not_an_election():
    # Live, every employee lists the client's whole catalog: the same deduction items under the same negative
    # IDs, with only zero values. They are kept on the employee, not elections; a negative-ID row with a value
    # still is one (A-49).
    def elections(b):
        out = normalize(b)
        return out, [e for e in out.records["deduction_elections"] if e.employee_id.endswith(":9001")]

    b = bundle("isolved")
    items = capture(b, "api/clients/{client}/legals/{legal}/employees/{id}/payItems", "/9001/payItems").body
    deductions = [r for r in items if r["payItemType"] == "Deduction"]
    catalog = [r for r in deductions if r["id"] < 0]
    out, elected = elections(b)
    assert catalog and sorted(e.label for e in elected) == sorted(r["payItemName"] for r in deductions if r["id"] > 0)
    kept = one(out, "employees", ":9001").provider_extensions
    assert {r["payItemName"] for r in catalog} <= {v for k, v in kept.items() if k.endswith(".payItemName")}
    catalog[0]["calcParams"] = [{"paramType": "Amount", "paramValue": 9.0}]
    assert len(elections(b)[1]) == len(elected) + 1


def test_a_prismhr_pay_group_period_that_ends_before_it_starts_is_kept_and_flagged():
    # Live, 48 PrismHR pay-group periods end before they start (2015-01-05 to 2015-01-01, say). The dates are
    # kept as sent, never swapped, and the run carries a warning.
    b = bundle("prismhr")
    batches = capture(b, "payroll/v1/getBatchListByDate")
    group = batches.body["batchList"][0]["payGroup"][0]
    group["payPeriodStartDate"], group["payPeriodEndDate"] = "2015-01-05", "2015-01-01"
    runs = [r for r in normalize(b).records["payroll_runs"] if "PERIOD_ENDS_BEFORE_START" in codes(r)]
    assert len(runs) == 1
    assert [(g.period.start.isoformat(), g.period.end.isoformat()) for g in runs[0].pay_groups][0] == (
        "2015-01-05",
        "2015-01-01",
    )


def test_a_loan_listed_in_both_deduction_endpoints_is_one_election():
    # getDeductions lists a loan's repayment with the loan's ID, and getEmployeeLoans the loan itself; live, both
    # of the tenant's loans are in both, as E1002's loan 1 is in the scenario. They are one election with the
    # loan's details, and a value the two disagree on is kept and named (A-64).
    def loans(start: str):
        b = bundle("prismhr")
        rows = next(
            c for c in b.captures if c.endpoint == "deductions/v1/getDeductions" and c.params["employeeId"] == "E1002"
        ).body["employeeDeductions"]["deduction"]
        next(r for r in rows if r["deductionCode"] == "LOAN1")["startDate"] = start
        out = normalize(b)
        return [e for e in out.records["deduction_elections"] if e.code == "LOAN1" and e.employee_id.endswith(":E1002")]

    [loan] = loans("2026-06-19")
    assert loan.loan_or_garnishment_id == "1" and loan.loan.payback_amount.amount == Decimal("500.0")
    assert loan.source.endpoints == ["deductions/v1/getDeductions", "deductions/v1/getEmployeeLoans"]
    assert "SOURCE_CONFLICT" not in codes(loan)
    [loan] = loans("2026-06-26")
    assert loan.effective_from.isoformat() == "2026-06-26" and "SOURCE_CONFLICT" in codes(loan)
    assert loan.provider_extensions["employeeLoanDetail[0].startDate"] == "2026-06-19"


def test_a_second_key_for_the_same_value_is_dropped_as_a_copy_or_kept_when_it_differs():
    # UKG sends a state as state_code and as state, and a cost center's name as display_name and as name. The
    # first is mapped; a copy is dropped with that reason, and a different value is kept (A-62). Live, 85 of
    # 422 paycheck cost centers have a name different from their display name.
    b = bundle("ukg-ready")
    employee = capture(b, "rest/v2/companies/{company}/employees/{id}", "/5001").body
    employee["address"] |= {"state": "NC", "state_code": "NC"}
    employee["mailing_address"] |= {"state": "North Carolina", "state_code": "NC"}
    statement = capture(b, "rest/v2/companies/{company}/payrolls/{id}/pay-statements/{id}", "/7101").body
    line = next(e for e in statement["earnings"] if e["earning"]["code"] == "Holiday")
    line["cost_centers"] = [{"index": 0, "value": {"id": 6102, "display_name": "CLT Production", "name": "Production"}}]
    out = normalize(b)
    record = one(out, "employees", ":5001")
    assert {a.type: a.state for a in record.addresses} == {C.AddressType.HOME: "NC", C.AddressType.MAILING: "NC"}
    assert "address.state" not in record.provider_extensions
    assert record.provider_extensions["mailing_address.state"] == "North Carolina"
    paycheck = one(out, "pay_statements", ":7101")
    holiday = next(e for e in paycheck.earnings if e.code == "Holiday")
    assert holiday.allocation == {"cost_center[0]": "CLT Production"}
    assert [v for k, v in paycheck.provider_extensions.items() if k.endswith("cost_centers[0].value.name")] == [
        "Production"
    ]


def test_an_address_that_is_only_a_country_stays_as_sent():
    # A country alone may be a provider default, so it isn't an address; it is kept, never dropped (A-62).
    b = bundle("ukg-ready")
    capture(b, "rest/v2/companies/{company}/employees/{id}", "/5001").body["mailing_address"] = {"country": "CAN"}
    employee = one(normalize(b), "employees", ":5001")
    assert not [a for a in employee.addresses if a.type is C.AddressType.MAILING]
    assert employee.provider_extensions["mailing_address.country"] == "CAN"


def test_an_isolved_contact_with_only_a_state_keeps_it():
    b = bundle("isolved")
    contact = capture(b, "api/clients/{client}/legals/{legal}/employees/{id}/contacts", "/9001/contacts").body[0]
    for key in ("address1", "address2", "city", "zipCode"):
        contact.pop(key, None)
    contacts = one(normalize(b), "employees", ":9001").personal.contacts
    found = next(c for c in contacts if c.source_id == str(contact["id"]))
    assert found.address is not None and found.address.state == contact["state"]
