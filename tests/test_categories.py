"""Earning categories (A-67) and tax types (A-68): mapped from each provider's own classification, codes
no rule covers left UNMAPPED for review, and a customer's names never read as meaning."""

import json
import sqlite3
from pathlib import Path

from normalization.bundle import Bundle
from normalization.export import write_sqlite
from normalization.mappings import review
from normalization.providers import normalize
from normalization.suggest import suggest

ROOT = Path(__file__).resolve().parents[1]


def bundle(provider: str) -> Bundle:
    return Bundle.load(ROOT / f"fixtures/{provider}/brightside")


def statement(out, suffix):
    return next(r for r in out.records["pay_statements"] if r.id.endswith(suffix))


def categories(st):
    return {e.code or e.label: e.category and (e.category.value.value, e.category.raw) for e in st.earnings}


def tax_types(st):
    return {(t.code or t.label, t.paid_by.value): t.type and (t.type.value.value, t.state) for t in st.taxes}


def unmapped(st):
    return {(d.field, d.raw) for d in st.diagnostics if d.code == "UNMAPPED_CODE"}


def prism_voucher(b: Bundle, voucher_id: str) -> dict:
    return next(
        v
        for c in b.captures
        if c.endpoint == "payroll/v1/getPayrollVoucherForBatch"
        for v in c.body.get("payrollVoucher") or []
        if v["voucherId"] == voucher_id
    )


def prism_pay_code(b: Bundle, code: str) -> list[dict]:
    return [
        row
        for c in b.captures
        if c.endpoint == "clientMaster/v1/getClientCodes"
        for row in c.body["clientCodes"]["payCode"]
        if row["id"] == code
    ]


# ---------------------------------------------------------------- PrismHR


def test_prism_category_is_the_pay_codes_talx_type_and_a_code_without_one_waits_for_review():
    st = statement(normalize(bundle("prismhr")), ":077002")
    assert categories(st) == {"REG": ("REGULAR", "R"), "OT": ("UNMAPPED", "OT"), "TIPS": None, "MILE": None}
    ot = next(e for e in st.earnings if e.code == "OT")
    assert ot.category.source_field == "clientCodes.payCode[].id" and ot.category.label == "Overtime"
    assert not unmapped(st)  # the customer's own code: one review decision, not a warning per paycheck


def test_prism_doubletime_rate_class_is_double_time_and_an_unknown_talx_type_warns():
    b = bundle("prismhr")
    for row in prism_pay_code(b, "OT"):
        row["rateClass"] = "D"
    for row in prism_pay_code(b, "REG"):
        row["talxPayType"] = "Z"
    st = statement(normalize(b), ":077002")
    assert categories(st)["OT"] == ("DOUBLE_TIME", "D")
    assert categories(st)["REG"] == ("UNMAPPED", "Z")
    assert ("clientCodes.payCode[].talxPayType", "Z") in unmapped(st)


def test_prism_tax_type_comes_from_the_code_and_the_state_from_the_description():
    st = statement(normalize(bundle("prismhr")), ":077001")
    assert tax_types(st) == {
        ("00-10", "EMPLOYEE"): ("FEDERAL_INCOME", None),
        ("00-11", "EMPLOYEE"): ("MEDICARE", None),
        ("00-12", "EMPLOYEE"): ("SOCIAL_SECURITY", None),
        ("34-20", "EMPLOYEE"): ("STATE_INCOME", "NC"),
        ("00-15", "EMPLOYER"): ("MEDICARE", None),
        ("00-16", "EMPLOYER"): ("SOCIAL_SECURITY", None),
        ("00-17", "EMPLOYER"): ("FEDERAL_UNEMPLOYMENT", None),
        ("34-24", "EMPLOYER"): ("STATE_UNEMPLOYMENT", "NC"),
    }


def test_prism_tax_numbers_that_mix_meanings_stay_unmapped():
    b = bundle("prismhr")
    voucher = prism_voucher(b, "077001")
    zero = {"empTaxableAmount": 0.0, "empTaxAmount": 0.0}
    voucher["employeeTax"] += [
        {"empTaxDeductCode": "360350510-31", "empTaxDeductCodeDesc": "CLEVELAND,OH CIWT", **zero},
        {"empTaxDeductCode": "02-22", "empTaxDeductCodeDesc": "ALASKA SUTA EE", **zero},
        {"empTaxDeductCode": "00-20", "empTaxDeductCodeDesc": "", **zero},  # federal, but not a known code
    ]
    voucher["companyTax"].append(
        {"comTaxDeductCode": "06-41", "comTaxDeductCodeDesc": "BOND", "comTaxableAmount": 0.0, "comTaxAmount": 0.0}
    )
    st = statement(normalize(b), ":077001")
    types = tax_types(st)
    assert types[("360350510-31", "EMPLOYEE")] == ("LOCAL_INCOME", None)
    assert types[("02-22", "EMPLOYEE")] == ("STATE_UNEMPLOYMENT", "AK")  # a state named in full
    assert types[("00-20", "EMPLOYEE")] == ("UNMAPPED", None)
    assert types[("06-41", "EMPLOYER")] == ("UNMAPPED", None)  # live, 41 is paid leave in one state, a bond in another
    assert {("employeeTax[].empTaxDeductCode", "00-20"), ("companyTax[].comTaxDeductCode", "06-41")} <= unmapped(st)
    assert st.checks and all(c.result.value == "pass" for c in st.checks)  # a type never changes an amount


# ---------------------------------------------------------------- isolved


def test_isolved_category_comes_from_the_system_earning():
    out = normalize(bundle("isolved"))
    assert categories(statement(out, ":70002")) == {
        "Regular": ("REGULAR", "Regular"),
        "Overtime": ("OVERTIME", "Overtime @ Flat 1.5"),
    }
    assert categories(statement(out, ":70004")) == {"1099 Comp": ("NON_EMPLOYEE_COMPENSATION", "1099M Non EE Comp")}
    assert categories(statement(out, ":70001"))["GTL"] is None  # non-cash fringe: the kind says it all
    assert categories(statement(out, ":70001"))["401(k) Match"] is None  # memo


def test_isolved_leave_accrual_falls_back_to_paid_time_off_and_an_unknown_system_earning_warns():
    b = bundle("isolved")
    items = next(c for c in b.captures if c.path == "api/clients/501/payItems").body
    next(i for i in items if i["title"] == "Holiday")["systemPayItemType"] = "Bereavement"
    next(i for i in items if i["title"] == "Regular")["systemPayItemType"] = "Jury Duty"
    st = statement(normalize(b), ":70001")
    assert categories(st)["Holiday"] == ("PAID_TIME_OFF", "Bereavement")  # under "Leave Accrual"
    assert categories(st)["Regular"] == ("UNMAPPED", "Jury Duty")
    assert ("clientPayItems[].systemPayItemType", "Jury Duty") in unmapped(st)


def test_isolved_tax_type_reads_the_system_tax_description():
    b = bundle("isolved")
    check = next(c for c in b.captures if c.path.endswith("/checks/70001"))
    zero = {"checkDollars": 0.0, "checkTaxableWages": 0.0, "itemCode": None}
    check.body["taxes"] += [
        {"itemDescription": "PA WH", "isEmployeeTax": True, **zero},
        {"itemDescription": "CALIFORNIA SDI EE", "isEmployeeTax": True, **zero},
        {"itemDescription": "KANSAS CITY WH", "isEmployeeTax": True, **zero},  # a city, not a state
        {"itemDescription": "LANCASTER CITY LST (LANCASTER)(LANCASTER SD)", "isEmployeeTax": True, **zero},
    ]
    st = statement(normalize(b), ":70001")
    assert tax_types(st) == {
        ("FEDERAL WH", "EMPLOYEE"): ("FEDERAL_INCOME", None),
        ("SOC SEC EE", "EMPLOYEE"): ("SOCIAL_SECURITY", None),
        ("MED EE", "EMPLOYEE"): ("MEDICARE", None),
        ("NORTH CAROLINA WH", "EMPLOYEE"): ("STATE_INCOME", "NC"),
        ("SOC SEC ER", "EMPLOYER"): ("SOCIAL_SECURITY", None),
        ("MED ER", "EMPLOYER"): ("MEDICARE", None),
        ("FUTA ER", "EMPLOYER"): ("FEDERAL_UNEMPLOYMENT", None),
        ("NORTH CAROLINA SUI ER", "EMPLOYER"): ("STATE_UNEMPLOYMENT", "NC"),
        ("PA WH", "EMPLOYEE"): ("STATE_INCOME", "PA"),
        ("CALIFORNIA SDI EE", "EMPLOYEE"): ("STATE_DISABILITY", "CA"),
        ("KANSAS CITY WH", "EMPLOYEE"): ("UNMAPPED", None),
        ("LANCASTER CITY LST (LANCASTER)(LANCASTER SD)", "EMPLOYEE"): ("UNMAPPED", None),
    }
    assert ("taxes[].itemDescription", "KANSAS CITY WH") in unmapped(st)


# ---------------------------------------------------------------- UKG Ready


def test_ukg_tax_type_from_documented_codes_and_state_codes():
    b = bundle("ukg-ready")
    taxes = next(c for c in b.captures if c.path.endswith("/pay-statements/7101")).body["taxes"]
    for code in ("MEDI", "FICA", "SUTA_SC:MN:2", "SIT:XX"):
        taxes.append({"type_name": "Tax", "company_tax": {"code": code, "name": code}, "er_amount": 0.0})
    st = statement(normalize(b), ":7101")
    assert tax_types(st) == {
        ("FIT", "EMPLOYEE"): ("FEDERAL_INCOME", None),
        ("Social Security", "EMPLOYEE"): ("SOCIAL_SECURITY", None),
        ("Social Security", "EMPLOYER"): ("SOCIAL_SECURITY", None),
        ("Medicare", "EMPLOYEE"): ("MEDICARE", None),
        ("Medicare", "EMPLOYER"): ("MEDICARE", None),
        ("SIT:NC", "EMPLOYEE"): ("STATE_INCOME", "NC"),
        ("FUTA", "EMPLOYER"): ("FEDERAL_UNEMPLOYMENT", None),
        ("SUTA:NC:2", "EMPLOYER"): ("STATE_UNEMPLOYMENT", "NC"),
        ("MEDI", "EMPLOYER"): ("MEDICARE", None),
        ("FICA", "EMPLOYER"): ("SOCIAL_SECURITY", None),  # documented as "OASDI"
        ("SUTA_SC:MN:2", "EMPLOYER"): ("UNMAPPED", None),
        ("SIT:XX", "EMPLOYER"): ("UNMAPPED", None),  # XX is no state
    }


def test_ukg_earning_codes_are_the_tenants_own_and_wait_for_review():
    out = normalize(bundle("ukg-ready"))
    st = statement(out, ":7102")
    assert categories(st) == {"Regular": ("UNMAPPED", "Regular"), "OT": ("UNMAPPED", "OT")}
    assert not unmapped(st)
    assert categories(statement(out, ":7101"))["GTL-Imp Inc"] is None
    assert categories(statement(out, ":7101"))["Cell Reimb"] is None  # a reimbursement


# ---------------------------------------------------------------- review, mapping files, export


def test_a_mapping_file_resolves_a_category_and_a_tax_type(tmp_path):
    b = bundle("ukg-ready")
    taxes = next(c for c in b.captures if c.path.endswith("/pay-statements/7101")).body["taxes"]
    taxes.append({"type_name": "Tax", "company_tax": {"code": "SUTA_SC:NC:2", "name": "Surcharge"}, "er_amount": 1.0})
    path = tmp_path / "mappings.json"
    evidence = "Tenant payroll admin, 2026-10-14"
    path.write_text(
        json.dumps(
            {
                "provider": "ukg-ready",
                "tenant": "synthetic",
                "mappings": [
                    {"field": "earnings[].earning.code", "raw": "OT", "value": "OVERTIME", "evidence": evidence},
                    {
                        "field": "taxes[].company_tax.code",
                        "raw": "SUTA_SC:NC:2",
                        "value": "STATE_UNEMPLOYMENT",
                        "evidence": evidence,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    out = normalize(b, mapping_files=[path])
    assert categories(statement(out, ":7102"))["OT"] == ("OVERTIME", "OT")
    maria = statement(out, ":7101")
    assert tax_types(maria)[("SUTA_SC:NC:2", "EMPLOYER")] == ("STATE_UNEMPLOYMENT", None)  # a file sets no state
    assert not unmapped(maria)
    assert "MAPPED_BY_FILE" in {d.code for d in maria.diagnostics}


def test_review_lists_a_customer_code_once_and_suggests_a_statutory_rate():
    b = bundle("ukg-ready")
    taxes = next(c for c in b.captures if c.path.endswith("/pay-statements/7101")).body["taxes"]
    next(t for t in taxes if t["company_tax"]["code"] == "Social Security")["company_tax"]["code"] = "OASDI-X"
    out = normalize(b)
    items = review([("ukg-ready", out)])
    suggest(items, [("ukg-ready", out)])
    found = {(u.field, u.raw): u for u in items}
    oasdi = found[("taxes[].company_tax.code", "OASDI-X")]
    arithmetic = next(s for s in oasdi.suggestions if s.method == "arithmetic")
    assert arithmetic.values == ["SOCIAL_SECURITY"] and "6.2% of taxable wages on 2 of 2 lines" in arithmetic.reasoning
    ot = found[("earnings[].earning.code", "OT")]
    assert ot.records == 1 and "OVERTIME" in ot.allowed


def test_a_code_without_letters_gets_no_name_hint():
    b = bundle("prismhr")
    prism_voucher(b, "077001")["companyTax"].append(
        {"comTaxDeductCode": "34-26", "comTaxDeductCodeDesc": "", "comTaxableAmount": 0.0, "comTaxAmount": 0.0}
    )
    out = normalize(b)
    items = review([("prismhr", out)])
    suggest(items, [("prismhr", out)])
    item = next(u for u in items if u.raw == "34-26")
    assert item.suggestions == []  # 34-26 is not like 34-24: the shared digits are a state number, not a name


def test_sqlite_has_category_type_and_state_columns(tmp_path):
    database = tmp_path / "canonical.sqlite"
    write_sqlite([normalize(bundle("ukg-ready"))], database)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT type, type_raw, state FROM tax_lines WHERE code = 'SIT:NC'").fetchone() == (
            "STATE_INCOME",
            "SIT:NC",
            "NC",
        )
        assert db.execute("SELECT category, category_raw FROM earning_lines WHERE code = 'OT'").fetchone() == (
            "UNMAPPED",
            "OT",
        )
