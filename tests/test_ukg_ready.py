"""UKG Ready conversion of the synthetic "brightside" scenario: known facts, especially the traps."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.bundle import Bundle
from normalization.providers.ukg_ready import normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/ukg-ready/brightside"
GOLDEN = ROOT / "tests/golden/ukg-ready/brightside.json"


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
    assert out.to_json() == GOLDEN.read_text(encoding="utf-8")


def test_the_bundle_fixes_the_as_of_date():
    assert Bundle.load(FIXTURE).as_of == date(2026, 10, 13)


def test_company_lists_every_ein_including_one_only_payrolls_name(out):
    company = one(out, "companies", ":7001")
    assert [(e.provider_id, e.tax_id.value) for e in company.employers] == [
        ("801", "12-3456789"),
        ("802", "98-7654321"),
    ]
    assert "EIN_FROM_PAYROLL" in codes(company)
    assert one(out, "payroll_runs", ":6002").legal_entity_id == "802"


def test_full_ssns_keep_only_their_last_four_everywhere(out):
    maria = one(out, "employees", ":5001")
    assert (maria.national_id.last4, maria.national_id.masked_at_source) == ("6781", False)
    assert maria.provider_extensions["national_id_numbers[1].value"] == "***4567"
    text = out.to_json()
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)
    assert "4000123456" not in text and "photo" not in text


def test_status_is_the_live_text_and_matches_the_termination_date(out):
    ana = one(out, "employees", ":5003")
    assert (ana.employment.status.value.value, str(ana.employment.termination_date)) == ("TERMINATED", "2026-09-30")
    devon = one(out, "employees", ":5004")
    assert (str(devon.employment.hire_date), str(devon.employment.rehire_date)) == ("2016-06-02", "2025-03-01")


def test_customer_pay_and_employee_types_keep_their_labels(out):
    maria = one(out, "employees", ":5001")
    assert (maria.compensation.pay_type.value.value, maria.compensation.pay_type.label) == ("UNMAPPED", "Salaried")
    assert (maria.employment.employment_type.value, maria.employment.employment_type.label) == ("UNMAPPED", "FT Exempt")
    assert maria.job.title == "Store Manager"


def test_current_pay_is_the_record_in_effect_at_as_of_and_later_raises_are_history(out):
    comp = one(out, "employees", ":5001").compensation
    assert str(comp.effective_date) == "2024-01-01"
    assert [(r.amount, r.per.value) for r in comp.rates] == [(Decimal("52000.0"), "YEAR"), (Decimal("25.0"), "HOUR")]
    assert [str(h.effective_date) for h in comp.history] == ["1900-12-31", "2024-01-01", "2027-01-01"]
    assert (comp.pay_frequency.frequency.value.value, comp.pay_frequency.periods_per_year) == ("BIWEEKLY", 26)


def test_times_are_milliseconds_converted_to_hours(out):
    comp = one(out, "employees", ":5002").compensation
    assert (comp.standard_hours.value, comp.standard_hours.raw, comp.standard_hours_per) == (
        Decimal("20"),
        72000000,
        "WEEK",
    )
    line = one(out, "pay_statements", ":7102").earnings[0]
    assert (line.quantity.value, line.quantity.unit.value, line.rate.amount) == (
        Decimal("20"),
        "HOURS",
        Decimal("18.0"),
    )
    assert line.quantity.value * line.rate.amount == line.amount.amount


def test_base_rate_is_the_line_rate_only_where_it_multiplies_out(out):
    james = one(out, "pay_statements", ":7102")
    regular, overtime = (next(e for e in james.earnings if e.code == code) for code in ("Regular", "OT"))
    assert regular.rate.amount == Decimal("18.0") and overtime.rate is None
    assert overtime.quantity.value == Decimal("2") and overtime.amount.amount == Decimal("54.00")
    assert "BASE_RATE_NOT_LINE_RATE" in codes(james)
    assert any(k.endswith(".base_rate") and v == Decimal("18.0") for k, v in james.provider_extensions.items())


def test_deposit_status_needs_the_flag_and_the_span(out):
    ended = one(out, "direct_deposits", ":4004")
    assert (ended.status.value.value, str(ended.effective_to)) == ("INACTIVE", "2026-06-30")
    assert (ended.method.value.value, ended.percent.scale.value, ended.percent.raw) == (
        "PERCENT_OF_GROSS",
        "UNVERIFIED",
        "10",
    )
    remainder = one(out, "direct_deposits", ":4002")
    assert (remainder.effective_from, remainder.effective_to, remainder.is_remainder) == (None, None, True)
    assert "OPEN_ENDED" in codes(remainder)


def test_unlabeled_methods_and_paper_checks(out):
    unlabeled = one(out, "direct_deposits", ":4006")
    assert unlabeled.method.value.value == "UNMAPPED" and "UNMAPPED_CODE" in codes(unlabeled)
    paper = one(out, "direct_deposits", ":4005")
    assert (paper.account.type.value.value, paper.amount.amount) == ("PAPER_CHECK", Decimal("100.00"))


def test_deduction_setup_keeps_open_methods_and_unverified_amounts_raw(out):
    plan = one(out, "deduction_elections", ":3001")
    assert (plan.category.value.value, plan.calculation.method.label, plan.calculation.percent.raw) == (
        "UNMAPPED",
        "% Of Earnings List",
        "5",
    )
    assert plan.provider_extensions["annual_max_amount"] == 23000 and "AMOUNT_UNIT_UNVERIFIED" in codes(plan)
    listed_only = one(out, "deduction_elections", ":3002")
    assert listed_only.status.value.value == "INACTIVE" and "DETAIL_NOT_FETCHED" in codes(listed_only)


def test_fringe_is_in_gross_wages_but_not_paid(out):
    maria = one(out, "pay_statements", ":7101")
    kinds = {e.code: e.kind.value.value for e in maria.earnings}
    assert kinds == {
        "Salary": "EARNINGS",
        "Holiday": "EARNINGS",
        "GTL-Imp Inc": "NON_CASH_FRINGE",
        "Cell Reimb": "REIMBURSEMENT",
    }
    totals = maria.totals
    assert (totals.gross_wages.amount, totals.gross_pay.amount, totals.net_pay.amount) == (
        Decimal("2028.10"),
        Decimal("2025.00"),
        Decimal("1604.88"),
    )
    assert all(t.derived for t in (totals.gross_wages, totals.gross_pay, totals.net_pay))
    # The "Fringe" payment balances the non-cash earning; nothing is paid, so it isn't a payment.
    assert [p.kind.value.value for p in maria.payments] == ["DIRECT_DEPOSIT", "DIRECT_DEPOSIT"]
    assert [(c.rule, c.result.value) for c in maria.checks] == [
        ("gross pay - employee taxes - deductions = net", "pass")
    ]


def test_float_artifacts_are_reported_and_kept_as_sent(out):
    maria = one(out, "pay_statements", ":7101")
    tax = next(t for t in maria.taxes if t.code == "SIT:NC")
    assert tax.amount.amount == Decimal("2.4699999999999998") and "FLOAT_ARTIFACT" in codes(maria)


def test_employer_taxes_and_contributions_are_their_own_lines(out):
    maria = one(out, "pay_statements", ":7101")
    assert {(t.code, t.paid_by.value) for t in maria.taxes if t.code == "Social Security"} == {
        ("Social Security", "EMPLOYEE"),
        ("Social Security", "EMPLOYER"),
    }
    assert [(c.code, c.amount.amount) for c in maria.employer_contributions] == [("401k", Decimal("50.0"))]


def test_unknown_line_types_block_the_derived_gross_pay(out):
    priya = one(out, "pay_statements", ":7103")
    assert priya.totals.gross_pay is None and {"GROSS_PAY_NOT_DERIVED", "UNMAPPED_CODE"} <= codes(priya)
    assert (priya.type.value.value, priya.type.label) == ("UNMAPPED", "Comm") and not priya.checks


def test_runs_and_statements_carry_their_status_and_link(out):
    run = one(out, "payroll_runs", ":6002")
    assert (run.type.value.value, run.status.value.value, str(run.processed_date)) == (
        "REGULAR",
        "COMPLETED",
        "2026-10-01",
    )
    assert one(out, "payroll_runs", ":6003").type.value.value == "VOID"
    listed = one(out, "pay_statements", ":7105")
    assert listed.payroll_run_id.endswith(":6001") and "DETAIL_NOT_FETCHED" in codes(listed)
    assert "NOT_FINALIZED" in codes(one(out, "pay_statements", ":7101"))
