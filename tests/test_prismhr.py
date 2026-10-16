"""PrismHR conversion of the synthetic "brightside" scenario: known facts, especially the traps."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.bundle import Bundle
from normalization.canonical.codes import NON_CASH_EARNING_KINDS
from normalization.mappings import reviewed
from normalization.providers import normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/prismhr/brightside"
GOLDEN = ROOT / "tests/golden/prismhr/brightside.json"


@pytest.fixture(scope="module")
def out():
    return normalize(Bundle.load(FIXTURE))


def one(out, kind, suffix):
    matches = [r for r in out.records[kind] if r.id.endswith(suffix)]
    assert len(matches) == 1, (kind, suffix, [r.id for r in out.records[kind]])
    return matches[0]


def codes(record):
    return {d.code for d in record.diagnostics}


def test_output_matches_the_golden_file(out):
    assert normalize(Bundle.load(FIXTURE), mapping_files=reviewed()).to_json() == GOLDEN.read_text(encoding="utf-8")


def test_salary_is_per_pay_period_and_undocumented_basis_a_is_annual(out):
    maria = one(out, "employees", ":201:E1001")
    rates = {r.source_field: (r.amount, r.per.value) for r in maria.compensation.rates}
    assert rates["compensation.salary"] == (Decimal("2000.00"), "PAY_PERIOD")
    assert rates["compensation.hourlyPayRate"] == (Decimal("52000.00"), "YEAR")
    assert rates["compensation.hourlyPay"] == (Decimal("25.00"), "HOUR")
    assert maria.compensation.pay_frequency.frequency.value.value == "BIWEEKLY"
    assert maria.compensation.pay_frequency.periods_per_year == 26
    assert "UNDOCUMENTED_CODE_EVIDENCED" in codes(maria)


def test_letter_v_is_void_for_a_batch_and_vacation_for_a_paycheck(out):
    run = one(out, "payroll_runs", ":201:30116")
    statement = one(out, "pay_statements", ":201:077006")
    assert (run.type.raw, run.type.value.value) == ("V", "VOID")
    assert (statement.type.raw, statement.type.value.value) == ("V", "VACATION")


def test_undocumented_codes_stay_unmapped_and_are_reported(out):
    empty_type = one(out, "payroll_runs", ":201:30118")
    open_batch = one(out, "payroll_runs", ":201:30119")
    assert (empty_type.type.raw, empty_type.type.value.value) == ("", "UNMAPPED")
    assert (open_batch.status.raw, open_batch.status.value.value) == ("TS.READY", "UNMAPPED")
    assert "UNMAPPED_CODE" in codes(empty_type) and "UNMAPPED_CODE" in codes(open_batch)
    assert one(out, "payroll_runs", ":201:30115").status.value.value == "COMPLETED"


def test_every_paycheck_reconciles(out):
    results = [c.result.value for s in out.records["pay_statements"] for c in s.checks]
    assert results and set(results) == {"pass"}


def test_non_cash_pay_counts_toward_gross_but_not_net(out):
    james = one(out, "pay_statements", ":201:077002")
    kinds = {e.code: e.kind.value.value for e in james.earnings}
    assert kinds == {"REG": "EARNINGS", "OT": "EARNINGS", "TIPS": "REPORTED_TIPS", "MILE": "REIMBURSEMENT"}
    wages, gross = james.totals.gross_wages, james.totals.gross_pay
    assert (wages.amount, wages.source_field) == (sum(e.amount.amount for e in james.earnings), "totalEarnings")
    non_cash = sum(e.amount.amount for e in james.earnings if e.kind.value in NON_CASH_EARNING_KINDS)
    assert non_cash == Decimal("45") and (gross.amount, gross.derived) == (wages.amount - non_cash, True)
    taxes = sum(t.amount.amount for t in james.taxes if t.paid_by.value == "EMPLOYEE")
    deductions = sum(d.employee_amount.amount for d in james.deductions)
    assert gross.amount - taxes - deductions == james.totals.net_pay.amount


def test_other_earnings_lines_are_part_of_gross(out):
    maria = one(out, "pay_statements", ":201:077001")
    fringe = next(e for e in maria.earnings if e.code == "FRINGE")
    assert fringe.kind.value.value == "NON_CASH_FRINGE" and fringe.source_field == "otherEarningsDetail[]"
    assert (maria.totals.gross_wages.amount, maria.totals.gross_pay.amount) == (Decimal("2003.25"), Decimal("2000.00"))
    # The voucher's own otherEarnAmount leaves Fringe out (as live data does); it is kept, not used.
    assert maria.provider_extensions["otherEarnAmount"] == Decimal("0.0")


def test_quantities_say_hours_or_units_and_numbers_stay_exact(out):
    james = one(out, "pay_statements", ":201:077002")
    mile = next(e for e in james.earnings if e.code == "MILE")
    reg = next(e for e in james.earnings if e.code == "REG")
    assert (mile.quantity.unit.value, mile.rate.per.value, str(mile.rate.amount)) == ("UNITS", "UNIT", "0.655")
    assert mile.amount.amount == Decimal("78.60")
    assert (reg.quantity.unit.value, reg.rate.per.value) == ("HOURS", "HOUR")


def test_deposit_methods_keep_their_documented_meaning(out):
    deposits = {d.id.split(":", 3)[3]: d for d in out.records["direct_deposits"]}
    fixed = deposits["201:E1001:net_pay:1"]
    remainder = deposits["201:E1001:net_pay:2"]
    hsa = deposits["201:E1001:hsa:1"]
    assert (fixed.method.value.value, fixed.account.type.value.value, fixed.amount.amount) == (
        "FIXED_AMOUNT",
        "SAVINGS",
        Decimal("200.0"),
    )
    assert (remainder.method.value.value, remainder.is_remainder) == ("REMAINDER", True)
    assert remainder.account.type.value.value == "CHECKING_OR_PAY_CARD"  # Prism C may be a pay card
    assert (hsa.purpose.value, hsa.funding.value.value, hsa.method.value.value) == (
        "HSA",
        "EMPLOYEE",
        "PERCENT_OF_NET_AFTER_TAXES",
    )  # HSA PN is "after taxes"
    # No fetched paycheck pays a percent deposit, so no deposit scale is verified (A-29).
    assert (hsa.percent.percent, hsa.percent.scale.value) == (None, "UNVERIFIED")
    percent = deposits["201:E1002:net_pay:1"]
    assert percent.method.value.value == "PERCENT_BASE_UNSPECIFIED"
    assert (percent.percent.percent, percent.percent.scale.value, percent.percent.raw) == (None, "UNVERIFIED", "30.0")
    assert percent.limit.amount == Decimal("500.0")
    assert deposits["201:E1002:net_pay:2"].method.value.value == "PERCENT_OF_NET_AFTER_FIXED"  # ordinary PN
    assert deposits["201:E1002:net_pay:3"].account.type.value.value == "INSTANT_PAY"


def test_deduction_setup_keeps_category_treatment_and_scale(out):
    elections = {e.code: e for e in out.records["deduction_elections"] if e.employee_id.endswith("E1001")}
    k401, dental = elections["C401K"], elections["DEN125"]
    assert (k401.category.value.value, k401.tax_treatment.value) == ("RETIREMENT", "PRE_TAX")
    assert (k401.calculation.percent.percent, k401.calculation.percent.scale.value) == (
        Decimal("5.0"),
        "VERIFIED_POINTS",
    )
    assert k401.employer_match.percent.scale.value == "UNVERIFIED"
    assert (dental.category.value.value, dental.tax_treatment.value) == ("SECTION_125", "PRE_TAX")
    assert dental.calculation.amount.amount == Decimal("12.5")
    james = {e.id.split(":", 3)[3]: e for e in out.records["deduction_elections"] if e.employee_id.endswith("E1002")}
    life = next(e for e in james.values() if e.code == "LIFE")
    assert life.source.endpoints == ["deductions/v1/getDeductions", "deductions/v1/getVoluntaryRecurringDeductions"]
    assert next(e for e in james.values() if e.code == "UNIFORM").status.value.value == "ONE_TIME"
    loan = next(e for e in james.values() if e.loan)
    assert (loan.category.value.value, loan.loan.principal.amount, loan.loan.paid_to_date.amount) == (
        "LOAN",
        Decimal("500.0"),
        Decimal("125.0"),
    )


def test_employment_status_type_and_classification(out):
    ana, devon = one(out, "employees", ":201:E1003"), one(out, "employees", ":201:E1004")
    priya, james = one(out, "employees", ":201:E1005"), one(out, "employees", ":201:E1002")
    assert ana.employment.status.value.value == "TERMINATED"
    assert str(ana.employment.termination_date) == "2026-09-30"
    assert (ana.employment.termination_reason.value, ana.employment.termination_reason.label) == (
        "UNMAPPED",
        "Voluntary resignation",
    )
    assert devon.employment.status.value.value == "ON_LEAVE" and "INVALID_DATE" in codes(devon)
    assert priya.employment.worker_classification.value.value == "CONTRACTOR_1099"
    # The class (F) is PrismHR's; the client's own type code (S, "Seasonal") is a separate domain and stays
    # as sent, never borrowed as the class's label (A-89).
    assert (priya.employment.employment_type.raw, priya.employment.employment_type.label) == ("F", None)
    assert priya.provider_extensions["client.employeeType"] == "S"
    assert james.employment.employment_type.value.value == "PART_TIME"
    assert one(out, "employees", ":201:E1001").personal.citizenship.value.value == "US_CITIZEN"


def test_company_is_the_business_and_employer_fields_stay_separate(out):
    bakery, logistics = one(out, "companies", ":201"), one(out, "companies", ":202")
    assert bakery.service_arrangement.value.value == "PEO"
    assert [(e.kind.value, e.provider_id) for e in bakery.employers] == [("ASSIGNED", "5"), ("ALTERNATE", "20")]
    assert (bakery.own_tax_id.value, bakery.own_tax_id.masked_at_source) == (None, True)
    unavailable = {d.field for d in bakery.diagnostics if d.code == "SOURCE_UNAVAILABLE"}
    assert unavailable == {"system/v1/getEmployerDetails"}  # refused: employer names unknown, not empty (A-70)
    assert (logistics.service_arrangement.value.value, logistics.employers[0].provider_id) == ("ASO", "202")


def test_sensitive_values_are_reduced_everywhere(out):
    maria = one(out, "employees", ":201:E1001")
    assert maria.provider_extensions["person.cobraSSN"] == "***3456"
    assert (maria.national_id.last4, maria.national_id.masked_at_source) == (None, True)
    everything = out.to_json()
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", everything)


def test_unmapped_fields_are_kept_not_dropped(out):
    maria = one(out, "employees", ":201:E1001")
    assert maria.provider_extensions["person.vehicleDetails[0].vehicleMake"] == "Example"
    assert maria.provider_extensions["compensation.fedFilingStatus"] == "SS"  # tax setup stays in extensions (A-34)


def test_records_link_to_each_other(out):
    employees, runs = out.ids("employees"), out.ids("payroll_runs")
    companies = out.ids("companies")
    for kind in ("direct_deposits", "deduction_elections", "pay_statements"):
        for record in out.records[kind]:
            assert record.employee_id in employees and record.company_id in companies
    assert all(s.payroll_run_id in runs for s in out.records["pay_statements"])
    voided = one(out, "pay_statements", ":201:077005")
    assert voided.voided and str(voided.void_date) == "2026-10-05"


def test_golden_file_is_valid_json_with_every_record_type():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert all(golden["records"][kind] for kind in golden["summary"]["counts"])


def test_an_undocumented_history_period_y_is_annual_with_a_note():
    # PayRate.payPeriod doesn't list Y; the sibling field documents it as "(Y)early", and live payRate equals
    # annualPay on all 26 such rows (A-19).
    b = Bundle.load(FIXTURE)
    capture = next(c for c in b.captures if c.endpoint == "employee/v1/getPayRateHistory")
    row = capture.body["payRateHistory"]["payRate"][0]
    row["payPeriod"] = "Y"
    employee = next(e for e in normalize(b).records["employees"] if e.id.endswith(f":{capture.params['employeeId']}"))
    rates = [r for change in employee.compensation.history for r in change.rates if r.source_field.endswith("payRate")]
    assert rates and rates[0].per.value == "YEAR"
    assert "UNDOCUMENTED_CODE_EVIDENCED" in {d.code for d in employee.diagnostics}
