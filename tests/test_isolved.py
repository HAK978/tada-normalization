"""isolved conversion of the synthetic "brightside" scenario: known facts, especially the traps."""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.bundle import Bundle
from normalization.providers.isolved import normalize

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures/isolved/brightside"
GOLDEN = ROOT / "tests/golden/isolved/brightside.json"


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


def test_sequence_zero_is_the_net_pay_remainder_not_the_first_account(out):
    deposits = {d.sequence: d for d in out.records["direct_deposits"] if d.employee_id.endswith(":9001")}
    assert (deposits[0].method.value.value, deposits[0].is_remainder) == ("REMAINDER", True)
    fixed = deposits[1]
    assert (fixed.method.value.value, fixed.amount.amount, fixed.account.type.value.value) == (
        "FIXED_AMOUNT",
        Decimal("200.0"),
        "SAVINGS",
    )
    assert (fixed.account.account_last4, fixed.account.masked_at_source) == (
        "6789",
        False,
    )  # sent in full, kept as last 4


def test_percent_deposit_scale_is_not_guessed(out):
    deposit = next(d for d in out.records["direct_deposits"] if d.employee_id.endswith(":9002") and d.sequence == 1)
    assert deposit.method.value.value == "PERCENT_BASE_UNSPECIFIED"
    assert (deposit.percent.percent, deposit.percent.scale.value, deposit.percent.raw) == (None, "UNVERIFIED", "30.0")


def test_memo_earnings_sit_outside_gross_wages_and_gross_pay_differs(out):
    check = one(out, "pay_statements", ":70001")
    memo = next(e for e in check.earnings if e.code == "401(k) Match")
    assert (memo.kind.value.value, memo.in_gross) == ("MEMO", False)
    counted = sum(e.amount.amount for e in check.earnings if e.in_gross)
    assert check.totals.gross_wages.amount == counted == Decimal("2000.0")
    assert check.totals.gross_pay.amount == Decimal("1996.9")
    assert "GROSS_PAY_DIFFERS_FROM_GROSS_WAGES" in codes(check)
    assert {c.result.value for c in check.checks} == {"pass"} and len(check.checks) == 3


def test_year_to_date_only_lines_are_not_part_of_this_paycheck(out):
    check = one(out, "pay_statements", ":70001")
    assert "Bonus" not in {e.code for e in check.earnings}
    assert any(
        k.startswith("earnings[") and k.endswith(".ytdDollars") and v == Decimal("500.0")
        for k, v in check.provider_extensions.items()
    )


def test_status_maps_only_when_it_is_an_implied_system_status(out):
    maria, ana, devon = (one(out, "employees", f":{i}") for i in ("9001", "9003", "9004"))
    assert maria.employment.status.value.value == "ACTIVE"
    assert (ana.employment.status.value.value, str(ana.employment.termination_date)) == ("TERMINATED", "2026-09-30")
    assert (devon.employment.status.value.value, devon.employment.status.label) == ("UNMAPPED", "Leave - FMLA")
    assert "CUSTOMER_STATUS" in codes(devon)


def test_lookup_code_and_description_both_map_and_raw_is_what_was_sent(out):
    james, maria = one(out, "employees", ":9002"), one(out, "employees", ":9001")
    assert (
        james.personal.marital_status.raw,
        james.personal.marital_status.value.value,
        james.personal.marital_status.label,
    ) == ("M", "MARRIED", "Married")
    assert (maria.personal.marital_status.raw, maria.personal.marital_status.value.value) == ("Single", "SINGLE")


def test_1099_is_a_worker_classification_not_a_pay_type(out):
    priya = one(out, "employees", ":9005")
    assert priya.employment.worker_classification.value.value == "CONTRACTOR_1099"
    assert (priya.compensation.pay_type.value.value, priya.compensation.pay_type.raw) == ("UNMAPPED", "1099")


def test_frequency_resolves_by_description_never_by_id(out):
    maria = one(out, "employees", ":9001")
    frequency = maria.compensation.pay_frequency
    assert (
        frequency.frequency.raw,
        frequency.frequency.label,
        frequency.frequency.value.value,
        frequency.periods_per_year,
    ) == ("26", "Bi-Weekly", "BIWEEKLY", 26)
    company = one(out, "companies", ":501:601")
    assert {g.code: g.frequency.periods_per_year for g in company.pay_groups} == {"701": 26, "702": 52}


def test_deduction_setup_is_classified_from_the_system_pay_item_type(out):
    elections = {e.label: e for e in out.records["deduction_elections"]}
    assert (elections["401K"].category.value.value, elections["401K"].tax_treatment.value) == (
        "RETIREMENT",
        "UNSPECIFIED",
    )
    assert elections["401K"].calculation.percent.scale.value == "UNVERIFIED"
    assert (elections["Dental Pre-tax"].category.value.value, elections["Dental Pre-tax"].tax_treatment.value) == (
        "SECTION_125",
        "PRE_TAX",
    )
    assert elections["401K Loan"].category.value.value == "RETIREMENT_LOAN"
    assert elections["Voluntary Life"].category.value.value == "VOLUNTARY"
    garnishment = next(e for e in out.records["deduction_elections"] if e.garnishment)
    assert (garnishment.category.value.value, garnishment.calculation.basis.value) == (
        "GARNISHMENT",
        "DISPOSABLE_INCOME",
    )
    assert (garnishment.garnishment.case_number, garnishment.garnishment.payee) == (
        "CASE-0001",
        "State Disbursement Unit",
    )
    assert garnishment.limits.maximum.amount == Decimal("2000.0")


def test_paychecks_link_to_runs_only_when_the_match_is_unique(out):
    assert one(out, "pay_statements", ":70001").payroll_run_id.endswith(":701:8801")
    ambiguous = one(out, "pay_statements", ":70005")
    assert ambiguous.payroll_run_id is None and "RUN_NOT_MATCHED" in codes(ambiguous)
    list_only = one(out, "pay_statements", ":70009")
    assert {"DETAIL_NOT_FETCHED", "RUN_NOT_MATCHED"} <= codes(list_only) and not list_only.checks
    imported = one(out, "pay_statements", ":60001")
    assert imported.type.value.value == "ADJUSTMENT"
    run = one(out, "payroll_runs", ":701:8800")
    assert (run.type.value.value, run.status.value.value) == ("HISTORICAL_IMPORT", "COMPLETED")
    assert one(out, "payroll_runs", ":701:8802").status.value.value == "NOT_PROCESSED"


def test_garnishments_on_paychecks_are_deductions_with_their_own_category(out):
    check = one(out, "pay_statements", ":70002")
    by_label = {d.label: d.category.value.value for d in check.deductions}
    assert by_label == {"Voluntary Life": "VOLUNTARY", "401K Loan": "RETIREMENT_LOAN", "Child Support": "GARNISHMENT"}
    assert {c.result.value for c in check.checks} == {"pass"}


def test_ssn_last4_comes_from_check_details_and_nothing_sensitive_leaks(out):
    maria = one(out, "employees", ":9001")
    assert (maria.national_id.last4, maria.national_id.source_field) == ("6788", "checks[].employeeSSN")
    assert not any(k.startswith(("i9Documents", "links")) or ".links[" in k for k in maria.provider_extensions)
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", out.to_json())


def test_company_is_the_legal_company_with_its_client_as_parent(out):
    company = one(out, "companies", ":501:601")
    assert (company.parent.code, company.parent.name) == ("501", "Brightside Holdings")
    assert company.own_tax_id.value == "12-3456789"
    assert [(e.kind.value, e.provider_id) for e in company.employers] == [("LEGAL_COMPANY", "601")]
