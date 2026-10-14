"""Properties that must hold for any input, not only the fixtures' (A-72).

Hypothesis generates the inputs: codes no table has seen, amounts of any size, captures in any order or
missing, fields no converter knows. Runs are derandomized and keep no example database, so the suite
stays deterministic and offline. For a deeper, randomized search, set PROPERTY_EXAMPLES:

    PROPERTY_EXAMPLES=500 pytest tests/test_properties.py
"""

import copy
import json
import os
import string
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings, strategies as st

from normalization import exactjson
from normalization.bundle import Bundle
from normalization.providers import PROVIDERS, normalize
from normalization.providers.isolved import codes as isolved_codes
from normalization.providers.prismhr import codes as prism_codes
from normalization.providers.ukg_ready import codes as ukg_codes

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {provider: Bundle.load(ROOT / f"fixtures/{provider}/brightside") for provider in PROVIDERS}
BASELINE = {provider: normalize(copy.deepcopy(bundle)).to_json() for provider, bundle in FIXTURES.items()}
DEEP = int(os.environ.get("PROPERTY_EXAMPLES", "0"))
EXAMPLES = settings(
    max_examples=DEEP or 20,
    derandomize=not DEEP,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
CODE = st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=12)
# Letters that can't spell anything the sanitizer masks (ssn, account, routing, tax, birth, pin, ...).
PLAIN = "bcdfghjklmqvwxz"


def fresh(provider: str) -> Bundle:
    return copy.deepcopy(FIXTURES[provider])


def capture(b: Bundle, path_end: str):
    return next(c for c in b.captures if c.path.endswith(path_end))


def voucher(b: Bundle, voucher_id: str) -> dict:
    return next(
        v
        for c in b.captures
        if c.endpoint == "payroll/v1/getPayrollVoucherForBatch"
        for v in c.body["payrollVoucher"]
        if v["voucherId"] == voucher_id
    )


def record(out, kind: str, suffix: str):
    return next(r for r in out.records[kind] if r.id.endswith(suffix))


# ---------------------------------------------------------------- unknown codes are never guessed


def ukg_employee_status(code):
    b = fresh("ukg-ready")
    capture(b, "employees/5001").body["status"] = code
    employee = record(normalize(b), "employees", ":5001")
    return employee, employee.employment.status


def prism_voucher_type(code):
    b = fresh("prismhr")
    voucher(b, "077001")["type"] = code
    statement = record(normalize(b), "pay_statements", ":077001")
    return statement, statement.type


def isolved_account_type(code):
    b = fresh("isolved")
    capture(b, "9001/directdeposits").body[0]["accountType"] = code
    deposit = next(d for d in normalize(b).records["direct_deposits"] if d.account.type.raw == code)
    return deposit, deposit.account.type


def ukg_tax_code(code):
    b = fresh("ukg-ready")
    capture(b, "pay-statements/7101").body["taxes"][0]["company_tax"]["code"] = code
    statement = record(normalize(b), "pay_statements", ":7101")
    return statement, next(t for t in statement.taxes if t.code == code).type


def prism_talx_type(code):
    b = fresh("prismhr")
    for c in b.captures:
        if c.endpoint == "clientMaster/v1/getClientCodes":
            next(row for row in c.body["clientCodes"]["payCode"] if row["id"] == "REG")["talxPayType"] = code
    statement = record(normalize(b), "pay_statements", ":077001")
    return statement, next(e for e in statement.earnings if e.code == "REG").category


UNKNOWN_CODE_TARGETS = {
    "UKG employee status": (ukg_employee_status, ukg_codes.EMPLOYEE_STATUS),
    "PrismHR voucher type": (prism_voucher_type, prism_codes.VOUCHER_TYPE),
    "isolved account type": (isolved_account_type, isolved_codes.DD_ACCOUNT_TYPE),
    "UKG tax code": (ukg_tax_code, ukg_codes.TAX_CODE),
    "PrismHR TALX pay type": (prism_talx_type, prism_codes.TALX_PAY_TYPE),
}


@pytest.mark.parametrize("target", UNKNOWN_CODE_TARGETS)
@EXAMPLES
@given(code=CODE)
def test_a_code_no_table_knows_comes_out_unmapped_with_its_raw_value(target, code):
    convert, known = UNKNOWN_CODE_TARGETS[target]
    assume(code not in known)
    owner, coded = convert(code)
    assert (str(coded.value), coded.raw) == ("UNMAPPED", code)
    assert any(d.code == "UNMAPPED_CODE" and d.raw == code for d in owner.diagnostics)


# ---------------------------------------------------------------- exact money

UKG_LINES = len(capture(FIXTURES["ukg-ready"], "pay-statements/7102").body["earnings"])


@EXAMPLES
@given(
    amounts=st.lists(
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999.99"), places=2),
        min_size=UKG_LINES,
        max_size=UKG_LINES,
    )
)
def test_amounts_stay_exact_and_derived_totals_add_up_to_the_cent(amounts):
    b = fresh("ukg-ready")
    for line, amount in zip(capture(b, "pay-statements/7102").body["earnings"], amounts, strict=True):
        line["ee_amount"] = amount
    statement = record(normalize(b), "pay_statements", ":7102")
    assert [e.amount.amount for e in statement.earnings] == amounts
    assert statement.totals.gross_wages.derived and statement.totals.gross_wages.amount == sum(amounts)


@EXAMPLES
@given(value=st.decimals(allow_nan=False, allow_infinity=False))
def test_any_decimal_survives_the_json_writer_digit_for_digit(value):
    assert str(exactjson.loads(exactjson.dumps({"amount": value}))["amount"]) == str(value)


# ---------------------------------------------------------------- zero is never missing


def ukg_deposit_amount(zero: bool):
    b = fresh("ukg-ready")
    deposit = capture(b, "5001/direct-deposits").body["deposits"][0]
    deposit["amount"] = 0 if zero else deposit.pop("amount") and None
    found = next(d for d in normalize(b).records["direct_deposits"] if d.employee_id.endswith(":5001"))
    return found, found.amount


def isolved_net_pay(zero: bool):
    b = fresh("isolved")
    check = capture(b, "/checks/70001").body
    check["netPay"] = 0 if zero else check.pop("netPay") and None
    statement = record(normalize(b), "pay_statements", ":70001")
    return statement, statement.totals.net_pay


def prism_tax_amount(zero: bool):
    b = fresh("prismhr")
    tax = voucher(b, "077001")["employeeTax"][0]
    tax["empTaxAmount"] = 0 if zero else tax.pop("empTaxAmount") and None
    statement = record(normalize(b), "pay_statements", ":077001")
    return statement, statement.taxes[0].amount


@pytest.mark.parametrize("target", [ukg_deposit_amount, isolved_net_pay, prism_tax_amount])
def test_a_zero_amount_is_kept_and_a_missing_one_never_passes_for_zero(target):
    owner, zero = target(zero=True)
    assert zero is not None and zero.amount == 0 and not zero.derived
    assert "AMOUNT_MISSING" not in {d.code for d in owner.diagnostics}
    owner, missing = target(zero=False)
    # Either absent, or a 0 that stands in for a required line amount and says so (A-72).
    assert missing is None or (missing.amount == 0 and "AMOUNT_MISSING" in {d.code for d in owner.diagnostics})


# ---------------------------------------------------------------- order and partial data


@pytest.mark.parametrize("provider", PROVIDERS)
@EXAMPLES
@given(data=st.data())
def test_the_output_does_not_depend_on_the_order_of_captures(provider, data):
    b = fresh(provider)
    b.captures = data.draw(st.permutations(b.captures))
    assert normalize(b).to_json() == BASELINE[provider]


@pytest.mark.parametrize("provider", PROVIDERS)
@EXAMPLES
@given(data=st.data())
def test_a_partial_bundle_never_crashes_and_every_dangling_link_is_explained(provider, data):
    b = fresh(provider)
    dropped = data.draw(st.sets(st.sampled_from(range(len(b.captures))), max_size=len(b.captures) // 2))
    b.captures = [c for i, c in enumerate(b.captures) if i not in dropped]
    out = normalize(b)
    companies, employees, runs = out.ids("companies"), out.ids("employees"), out.ids("payroll_runs")
    for kind, records in out.records.items():
        for r in records:
            assert kind == "companies" or r.company_id in companies, (kind, r.id)
    for kind in ("direct_deposits", "deduction_elections", "pay_statements"):
        for r in out.records[kind]:
            explained = {d.code for d in r.diagnostics}
            assert r.employee_id in employees or "EMPLOYEE_NOT_IN_BUNDLE" in explained, (kind, r.id)
    for s in out.records["pay_statements"]:
        explained = {d.code for d in s.diagnostics}
        assert s.payroll_run_id is None or s.payroll_run_id in runs or "RUN_NOT_IN_BUNDLE" in explained, s.id


def test_elections_whose_employee_is_missing_say_so():
    # Found by the property above: PrismHR deduction setup kept for an employee whose record wasn't fetched.
    b = fresh("prismhr")
    b.captures = [
        c for c in b.captures if not (c.endpoint == "employee/v1/getEmployee" and c.params["clientId"] == "201")
    ]
    out = normalize(b)
    elections = [e for e in out.records["deduction_elections"] if e.employee_id.endswith(":201:E1001")]
    assert elections and all("EMPLOYEE_NOT_IN_BUNDLE" in {d.code for d in e.diagnostics} for e in elections)


def test_a_statement_whose_payroll_is_missing_says_so():
    # Found by the property above: a UKG statement kept pointing at a payroll that wasn't fetched.
    b = fresh("ukg-ready")
    b.captures = [c for c in b.captures if not c.path.endswith(("/payrolls", "/payrolls/6001"))]  # list and detail
    statement = record(normalize(b), "pay_statements", ":7101")
    assert statement.payroll_run_id.endswith(":6001")
    assert "RUN_NOT_IN_BUNDLE" in {d.code for d in statement.diagnostics}


# ---------------------------------------------------------------- nothing is lost


def ukg_employee(key, value):
    b = fresh("ukg-ready")
    capture(b, "employees/5001").body[key] = value
    return b, "employees", ":5001"


def prism_voucher(key, value):
    b = fresh("prismhr")
    voucher(b, "077001")[key] = value
    return b, "pay_statements", ":077001"


def isolved_check(key, value):
    b = fresh("isolved")
    capture(b, "/checks/70001").body[key] = value
    return b, "pay_statements", ":70001"


@pytest.mark.parametrize("place", [ukg_employee, prism_voucher, isolved_check])
@EXAMPLES
@given(key=st.text(alphabet=PLAIN, min_size=1, max_size=8).map("zz".__add__), value=st.text(PLAIN, min_size=1))
def test_a_field_no_converter_knows_is_kept_in_provider_extensions(place, key, value):
    b, kind, suffix = place(key, value)
    assert record(normalize(b), kind, suffix).provider_extensions.get(key) == value


# ---------------------------------------------------------------- mapping files stay in scope


@EXAMPLES
@given(
    companies=st.sets(st.sampled_from(["201", "202"]), min_size=1),
    value=st.text(alphabet=string.ascii_letters + "_", min_size=1, max_size=12),
)
def test_a_mapping_rule_reaches_exactly_the_companies_it_names(companies, value):
    assume(value != "UNMAPPED")
    rule = {"field": "status", "raw": "PRNT", "value": value, "evidence": "property test"}
    rule["companies"] = [f"prismhr:synthetic:company:{c}" for c in sorted(companies)]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "mappings.json"
        path.write_text(json.dumps({"provider": "prismhr", "tenant": "synthetic", "mappings": [rule]}))
        out = normalize(fresh("prismhr"), mapping_files=[path])
    for statement in out.records["pay_statements"]:
        in_scope = statement.company_id.rsplit(":", 1)[1] in companies
        assert (statement.status.value == value) == in_scope, statement.id
