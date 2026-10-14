"""UKG Ready fixtures: the "brightside" scenario, as UKG Ready's API would return it.

Same people as the other scenarios, in UKG's shape, with UKG's traps: full SSNs and account
numbers, times in milliseconds, a 1900-12-31 placeholder pay record, a raise dated after as_of,
the documented open-ended dates, an "active" deposit whose span has ended, a paper-check
reservation, an unlabeled deposit method, a fringe earning balanced by a "Fringe" payment, a
floating-point amount, lines with no amount, an unknown line modifier, a customer pay statement
type, an EIN only payrolls mention, and setup amounts whose unit is undocumented.
"""

from __future__ import annotations

import zlib
from decimal import Decimal as D
from typing import Any

from . import FixtureBundle, cents
from .validate import complete

TENANT = "synthetic"
CID = "7001"
AS_OF = "2026-10-13"
ROOT = f"rest/v2/companies/{CID}"
EP = "rest/v2/companies/{company}"
LINK = "https://example.invalid/ta/" + ROOT

PRIMARY_EIN = {"id": 801, "ein_name": "Brightside Bakery LLC", "ein_tax_id": "12-3456789", "ein_country_id": "USA"}
# Payrolls name this EIN, but lookup/eins doesn't list it (as live, A-60).
SECOND_EIN = {"id": 802, "ein_name": "Brightside Logistics LLC", "ein_tax_id": "98-7654321", "ein_country_id": "USA"}
PAY_TYPES = {"Hourly": 901, "Salaried": 902}
EMPLOYEE_TYPES = {"FT Exempt": 911, "PT Hourly": 912, "Consultant": 913}
JOBS = {"Head Baker": 921, "Driver": 922, "Store Manager": 923}
MS_PER_HOUR = 3_600_000


def _money(value: D) -> float:
    return float(cents(value))


def _ms(hours: int | D) -> int:
    return int(D(hours) * MS_PER_HOUR)


def _employee(
    aid: int,
    number: str,
    first: str,
    last: str,
    status: str,
    hired: str,
    ssn: str,
    *,
    terminated: str | None = None,
    re_hired: str | None = None,
    manager: int | None = None,
    other_id: str | None = None,
) -> dict:
    ids = [{"type": "SSN", "value": ssn, "primary": True}]
    if other_id:
        ids.append({"type": "OTHER_1", "value": other_id, "primary": False})
    dates = {"hired": hired, "started": re_hired or hired, "birthday": "1990-04-12"}
    if terminated:
        dates["terminated"] = terminated
    if re_hired:
        dates["re_hired"] = re_hired
    return {
        "id": aid,
        "employee_id": number,
        "username": f"{first[0]}{last}".lower(),
        "first_name": first,
        "last_name": last,
        "primary_account_id": aid,
        "ein_name": PRIMARY_EIN["ein_name"],
        "ein": {"id": PRIMARY_EIN["id"]},
        "status": status,
        "locked": status != "Active",
        "social_security": ssn,
        "national_id_numbers": ids,
        "address": {
            "address_line_1": f"{100 + aid % 100} Market St",
            "city": "Charlotte",
            "state": "NC",
            "zip": "28202",
            "country": "USA",
        },
        "dates": dates,
        "phones": {"cell_phone": "704-555-0100", "preferred_phone": "CELL"},
        "primary_email": f"{first.lower()}@brightside.example",
        "managers": [{"index": 0, "empl_ref": {"account_id": manager}}] if manager else [],
        "timezone": "America/New_York",
        # A signed photo link works as a credential; the converter must drop it (model §9).
        "photo_href": f"https://example.invalid/photos/{aid}?sig=not-a-real-token",
        "_links": {"self": f"{LINK}/employees/{aid}"},
    }


def _compensation(aid: int, rows: list[tuple[str, D, str, D, int, str, int]]) -> dict:
    """rows: (effective_from, amount, amount_period, hourly_pay, hours, time_period, num_pp_in_year)."""
    return {
        "compensations": [
            {
                "id": int(f"{effective.replace('-', '')}{aid}"),
                "employee": {"account_id": aid},
                "effective_from": effective,
                "amount": _money(amount),
                "amount_period": period,
                "hourly_pay": float(hourly),
                "time": _ms(hours),
                "time_period": time_period,
                "num_pp_in_year": periods,
                "currency": "USD",
            }
            for effective, amount, period, hourly, hours, time_period, periods in rows
        ]
    }


def _deposit(
    deposit_id: int,
    sequence: int,
    method: str,
    label: str,
    account: str | None,
    *,
    account_type: str = "CHECKING",
    kind: str = "DIRECT_DEPOSIT",
    active_from: str = "2024-01-01",
    active_to: str = "3000-01-01",
    active: bool = True,
    amount: D | None = None,
    percentage: int | None = None,
) -> dict:
    row = {
        "id": deposit_id,
        "sequence": sequence,
        "type": kind,
        "active_from": active_from,
        "active_to": active_to,
        "active": active,
        "calc_method": {"type": method, "display_name": label},
        "pre_note_status": "COMPLETE_OK",
        "payroll_frequency": {"type": "EVERY_PAY"},
        "currency": "USD",
        "_links": {"self": f"{LINK}/direct-deposits/{deposit_id}"},
    }
    if account:
        row |= {
            "account_type": account_type,
            "account_number": account,
            "routing_number": "053000196",
            "routing_type": "ABA",
        }
    if amount is not None:
        row["amount"] = _money(amount)
    if percentage is not None:
        row["percentage"] = percentage
    return row


def build() -> FixtureBundle:
    bundle = FixtureBundle("ukg-ready", TENANT, [{"company_id": CID}], as_of=AS_OF)
    _lookups(bundle)
    _people(bundle)
    _payroll(bundle)
    for capture in bundle.captures:
        if capture["status"] == 200:
            capture["body"] = complete("ukg-ready", capture["endpoint"], capture["body"])
    return bundle


def _lookups(bundle: FixtureBundle) -> None:
    items = {
        "eins": [PRIMARY_EIN],
        "pay-types": [{"id": i, "name": n} for n, i in PAY_TYPES.items()],
        "employee-types": [{"id": i, "name": n} for n, i in EMPLOYEE_TYPES.items()],
        "jobs": [{"id": i, "name": n, "visible": True} for n, i in JOBS.items()],
        "payroll-types": [{"id": 641, "display_name": "Regular"}, {"id": 129, "display_name": "Void"}],
        "pay-statement-types": [
            {"id": 36656000, "display_name": "Regular"},
            {"id": 36656008, "display_name": "Comm"},
        ],
        "earning-codes": [
            {"id": 38219544, "code": "Salary", "name": "Salary"},
            {"id": 38219545, "code": "Regular", "name": "Regular"},
            {"id": 38219537, "code": "Holiday", "name": "Holiday"},
            {"id": 38219529, "code": "GTL-Imp Inc", "name": "GTL-Imputed Income"},
        ],
        "deduction-codes": [
            {"id": 38512329, "code": "401k", "name": "401k"},
            {"id": 38512348, "code": "Dental", "name": "Dental Insurance"},
        ],
    }
    for name, rows in items.items():
        bundle.add(f"{EP}/lookup/{name}", f"{ROOT}/lookup/{name}", {}, {"items": rows})


def _people(bundle: FixtureBundle) -> None:
    salaried, hourly = PAY_TYPES["Salaried"], PAY_TYPES["Hourly"]
    people = [
        (
            _employee(5001, "1001", "Maria", "Lopez", "Active", "2019-08-05", "900-10-6781", other_id="A1234567"),
            {"employee_type": EMPLOYEE_TYPES["FT Exempt"], "pay_type": salaried, "default_job": JOBS["Store Manager"]},
            [
                # The 1900-12-31 placeholder row: no amount and 0 pay periods (live has one per employee).
                ("1900-12-31", D("0"), "HOUR", D("0"), 2080, "YEAR", 0),
                ("2024-01-01", D("52000"), "YEAR", D("25.00"), 2080, "YEAR", 26),
                # A raise that takes effect after as_of: history only, not the current pay.
                ("2027-01-01", D("54600"), "YEAR", D("26.25"), 2080, "YEAR", 26),
            ],
            [
                _deposit(4001, 1, "FLAT_AMOUNT", "Flat Amount", "4000123456", account_type="SAVINGS", amount=D("200")),
                _deposit(4002, 2, "FULL", "Entire/Remainder", "4000987654", active_from="1900-01-01"),
            ],
        ),
        (
            _employee(5002, "1002", "James", "Carter", "Active", "2021-03-15", "900-10-6782", manager=5001),
            {"employee_type": EMPLOYEE_TYPES["PT Hourly"], "pay_type": hourly, "default_job": JOBS["Driver"]},
            [
                ("1900-12-31", D("0"), "HOUR", D("0"), 2080, "YEAR", 0),
                ("2025-06-01", D("18.00"), "HOUR", D("18.00"), 20, "WEEK", 26),
            ],
            [
                _deposit(4003, 1, "FULL", "Entire/Remainder", "4000555123"),
                # Still flagged active, but its span ended before as_of: inactive (A-25).
                _deposit(
                    4004, 2, "GROSS_EARNING", "% Of Gross Earnings", "4000555999", active_to="2026-06-30", percentage=10
                ),
            ],
        ),
        (
            _employee(5003, "1003", "Ana", "Reyes", "Terminated", "2018-02-01", "900-10-6783", terminated="2026-09-30"),
            {"employee_type": EMPLOYEE_TYPES["FT Exempt"], "pay_type": salaried},
            [("2018-02-01", D("49920"), "YEAR", D("24.00"), 80, "PAY_PERIOD", 26)],
            [],
        ),
        (
            _employee(5004, "1004", "Devon", "Price", "Active", "2016-06-02", "900-10-6784", re_hired="2025-03-01"),
            {"employee_type": EMPLOYEE_TYPES["PT Hourly"], "pay_type": hourly, "default_job": JOBS["Head Baker"]},
            [("2025-03-01", D("1840.00"), "PAY_PERIOD", D("23.00"), 2080, "YEAR", 26)],
            [
                # Reserves a paper check rather than naming an account.
                _deposit(4005, 1, "FLAT_AMOUNT", "Flat Amount", None, kind="RESERVE_LIVE_CHECK", amount=D("100")),
                # A method UKG never labels: its meaning isn't guessed (A-26).
                _deposit(4006, 2, "NET_PAY", "", "4000777888"),
            ],
        ),
        (
            _employee(5005, "1005", "Priya", "Shah", "Active", "2026-08-01", "900-10-6785"),
            {"employee_type": EMPLOYEE_TYPES["Consultant"], "pay_type": hourly},
            [("2026-08-01", D("40.00"), "HOUR", D("40.00"), 2080, "YEAR", 26)],
            [],
        ),
    ]
    bundle.add(
        f"{EP}/employees",
        f"{ROOT}/employees",
        {},
        {
            "employees": [
                {
                    "id": e["id"],
                    "username": e["username"],
                    "employee_id": e["employee_id"],
                    "first_name": e["first_name"],
                    "last_name": e["last_name"],
                    "dates": {
                        k: v for k, v in e["dates"].items() if k in ("hired", "re_hired", "started", "terminated")
                    },
                    "status": e["status"],
                    "_links": {"self": e["_links"]["self"]},
                }
                for e, *_ in people
            ]
        },
    )
    for employee, info, compensation, deposits in people:
        aid = employee["id"]
        path = f"{ROOT}/employees/{aid}"
        bundle.add(f"{EP}/employees/{{id}}", path, {}, employee)
        pay_info = {
            "employee_type": {"id": info["employee_type"]},
            "pay_type": {"id": info["pay_type"]},
            "standard_work_day": _ms(8),
            "payroll_classification": "REGULAR",
        }
        if "default_job" in info:
            pay_info["default_job"] = {"id": info["default_job"]}
        bundle.add(f"{EP}/employees/{{id}}/pay-info", f"{path}/pay-info", {}, pay_info)
        bundle.add(
            f"{EP}/employees/{{id}}/compensation/history",
            f"{path}/compensation/history",
            {},
            _compensation(aid, compensation),
        )
        bundle.add(f"{EP}/employees/{{id}}/direct-deposits", f"{path}/direct-deposits", {}, {"deposits": deposits})
        _deductions(bundle, aid, path)


def _deductions(bundle: FixtureBundle, aid: int, path: str) -> None:
    """Deduction setup is documented (#/schemas/132, 133) but the live tenant returns 404 (A-12)."""
    endpoint = f"{EP}/employees/{{id}}/deductions"
    if aid == 5001:
        listed = [
            {
                "id": 3001,
                "deduction": {"code": "401k", "name": "401k"},
                "effective_from": "2024-01-01",
                "effective_to": "9999-12-31",
                "sequence": 1,
                "_links": {"self": f"{LINK}/employees/{aid}/deductions/3001"},
            },
            {
                "id": 3002,
                "deduction": {"code": "Dental", "name": "Dental Insurance"},
                "effective_from": "2024-01-01",
                "effective_to": "2026-01-01",
                "sequence": 2,
                "_links": {"self": f"{LINK}/employees/{aid}/deductions/3002"},
            },
        ]
        bundle.add(endpoint, f"{path}/deductions", {}, {"deductions": listed})
        bundle.add(
            endpoint + "/{id}",
            f"{path}/deductions/3001",
            {},
            {
                "id": 3001,
                "sequence": 1,
                "deduction": {"code": "401k", "name": "401k"},
                "effective_from": "2024-01-01",
                "effective_to": "9999-12-31",
                "annual_max_amount": 23000,
                "ee_frequency": {"type": "EVERY_SCHEDULED_PAY", "display_name": "Every Scheduled Pay"},
                "ee_calc_method": {
                    "method": {"type": "EARNING_LIST", "display_name": "% Of Earnings List"},
                    "percent": 5,
                },
                "ee_max_calc_method": {"amount": 500, "percent": 0},
                "vendor": {"id": 65792, "name": "Retirement Plan Vendor"},
            },
        )
        # 3002 is listed but its detail was never fetched.
    else:
        bundle.add(endpoint, f"{path}/deductions", {}, {"errors": [{"code": 404, "message": "Unresolvable URL"}]}, 404)


def _line_batch() -> dict:
    return {"id": 4342647435, "display_name": "Regular Earnings"}


def _statement(statement_id: int, aid: int, type_id: int, type_name: str, lines: dict) -> dict:
    return {
        "employee": {"account_id": aid},
        "id": statement_id,
        "pay_date": "2026-10-02",
        "status": "OPEN",
        "type": {"id": type_id, "display_name": type_name},
        "pay_period_start": "2026-09-14",
        "pay_period_end": "2026-09-27",
        **lines,
    }


def _earning(code: str, name: str, type_name: str, amount: D | None, hours: int | None = None, rate: D | None = None):
    # IDs come from the line's content, so every generation writes the same ones.
    line = {"id": zlib.crc32(f"{code}|{type_name}|{amount}".encode()), "type_name": type_name, "batch": _line_batch()}
    line["earning"] = {"code": code, "name": name}
    if hours is not None:
        line |= {"hours": _ms(hours), "date_range_from": "2026-09-14", "date_range_to": "2026-09-27"}
    if rate is not None:
        line["base_rate"] = float(rate)
    if amount is not None:
        line["ee_amount"] = _money(amount)
    return line


def _tax(code: str, name: str, ee: D | float | None, er: D | None, wages: D) -> dict:
    line: dict[str, Any] = {"type_name": "Tax", "company_tax": {"code": code, "name": name}, "batch": _line_batch()}
    if ee is not None:
        line |= {"ee_amount": ee if isinstance(ee, float) else _money(ee), "ee_subject_wage": _money(wages)}
    if er is not None:
        line |= {"er_amount": _money(er), "er_subject_wage": _money(wages)}
    return line


def _payroll(bundle: FixtureBundle) -> None:
    def run(payroll_id: int, name: str, ein: dict, type_id: int, type_name: str, status: str, pay_date: str) -> dict:
        row = {
            "id": payroll_id,
            "name": name,
            "pay_date": pay_date,
            "start_date": "2026-09-14",
            "end_date": "2026-09-27",
            "type": {"id": type_id, "display_name": type_name},
            "ein": ein,
            "status": status,
            "billable": True,
            "_links": {"self": f"{LINK}/payrolls/{payroll_id}"},
        }
        if status == "FINALIZED":
            row["date_finalized"] = "2026-10-01"
        return row

    runs = [
        run(6001, "Primary-EIN Regular Bi-Weekly 10/02/2026", PRIMARY_EIN, 641, "Regular", "OPEN", "2026-10-02"),
        run(6002, "2nd EIN- Regular Bi-Weekly 10/02/2026", SECOND_EIN, 641, "Regular", "FINALIZED", "2026-10-02"),
        run(6003, "Void 10/09/2026", PRIMARY_EIN, 129, "Void", "CLOSED", "2026-10-09"),
        # Listed only: its detail was never fetched.
        run(6004, "Primary-EIN Regular Bi-Weekly 10/16/2026", PRIMARY_EIN, 641, "Regular", "OPEN", "2026-10-16"),
    ]
    bundle.add(
        f"{EP}/payrolls",
        f"{ROOT}/payrolls",
        {"pay_date_from": "2026-01-01", "pay_date_to": "2026-12-31"},
        {"payrolls": runs},
    )
    for row in runs[:3]:
        bundle.add(f"{EP}/payrolls/{{id}}", f"{ROOT}/payrolls/{row['id']}", {}, row)

    # Maria: salary, holiday hours, imputed group-term life (balanced by a "Fringe" payment), a phone
    # reimbursement, a tax amount in binary floating-point form, and a check line with no amount.
    gross = D("1800") + D("200") + D("3.10") + D("25")
    paid_gross = gross - D("3.10")
    float_tax = 2.4699999999999998  # 2.47 as a binary float, as UKG sent one live (A-59)
    ee_taxes = D("150") + D("125.74") + D("29.41") + D(str(float_tax))
    deductions = D("100") + D("12.50")
    net = cents(paid_gross - ee_taxes - deductions)
    maria = _statement(
        7101,
        5001,
        36656000,
        "Regular",
        {
            "earnings": [
                _earning("Salary", "Salary", "Earning (Auto)", D("1800")),
                _earning("Holiday", "Holiday", "Earning", D("200"), hours=8, rate=D("25")),
                _earning("GTL-Imp Inc", "GTL-Imputed Income", "Earning (Fringe, Auto)", D("3.10")),
                _earning("Cell Reimb", "Cell Reimb", "Reimbursement(Neg Ded, Auto)", D("25")),
            ],
            "taxes": [
                _tax("FIT", "Federal Income Tax", D("150"), None, gross - D("100") - D("12.50")),
                _tax("Social Security", "Social Security", D("125.74"), D("125.74"), gross),
                _tax("Medicare", "Medicare", D("29.41"), D("29.41"), gross),
                # Live: a state income tax is named after the state and taxed on FIT's wage base (A-68).
                _tax("SIT:NC", "North Carolina", float_tax, None, gross - D("100") - D("12.50")),
                _tax("FUTA", "Federal Unemployment Tax", None, D("12.17"), gross),
                _tax("SUTA:NC:2", "ER SUTA North Carolina", None, D("20.28"), gross),
            ],
            "deductions": [
                {
                    "type_name": "Deduction (Auto)",
                    "deduction": {"code": "401k", "name": "401k", "external_id": "D20"},
                    "ee_amount": 100.0,
                    "er_amount": 50.0,
                    "batch": _line_batch(),
                },
                {
                    "type_name": "Deduction (Auto)",
                    "deduction": {"code": "Dental", "name": "Dental Insurance", "external_id": "D11"},
                    "ee_amount": 12.5,
                    "batch": _line_batch(),
                },
            ],
            "payments": [
                {"type_name": "Direct Deposit", "ee_amount": 200.0, "batch": _line_batch()},
                {"type_name": "Direct Deposit", "ee_amount": _money(net - D("200")), "batch": _line_batch()},
                {"type_name": "Fringe", "ee_amount": 3.1, "batch": _line_batch()},
                {"type_name": "Check", "batch": _line_batch()},
            ],
            "messages": [
                {"type_name": "Message", "message": {"text": "Missing company bank settings.", "severity": "ERROR"}}
            ],
        },
    )
    # James: hours in milliseconds (20 h), an overtime line, and an earning line that carries no amount.
    james = _statement(
        7102,
        5002,
        36656000,
        "Regular",
        {
            "earnings": [
                _earning("Regular", "Regular", "Earning", D("360"), hours=20, rate=D("18")),
                # Overtime: amount = 1.5 x hours x base_rate, as on every live overtime line (A-24).
                _earning("OT", "Overtime", "Earning", D("54"), hours=2, rate=D("18")),
                _earning("SECA", "SECA", "Earning (Auto)", None, rate=D("18")),
            ],
            "taxes": [
                _tax("FIT", "Federal Income Tax", D("20"), None, D("360")),
                _tax("Social Security", "Social Security", D("22.32"), D("22.32"), D("360")),
                _tax("Medicare", "Medicare", D("5.22"), D("5.22"), D("360")),
            ],
            "payments": [{"type_name": "Check", "ee_amount": _money(D("414") - D("47.54")), "batch": _line_batch()}],
        },
    )
    # Priya: a customer pay statement type ("Comm") and a line modifier UKG never documents.
    priya = _statement(
        7103,
        5005,
        36656008,
        "Comm",
        {
            "earnings": [
                _earning("Commission", "Commission", "Earning", D("1200")),
                _earning("Tips Memo", "Tips Memo", "Earning (Memo)", D("50")),
            ],
            "taxes": [_tax("FIT", "Federal Income Tax", D("100"), None, D("1250"))],
            "payments": [{"type_name": "Direct Deposit", "ee_amount": 1100.0, "batch": _line_batch()}],
        },
    )
    devon_listed = _statement(7105, 5004, 36656000, "Regular", {})
    lists = {6001: [maria, james, devon_listed], 6002: [priya], 6003: []}
    for payroll_id, statements in lists.items():
        bundle.add(
            f"{EP}/payrolls/{{id}}/pay-statements",
            f"{ROOT}/payrolls/{payroll_id}/pay-statements",
            {},
            {
                "pay_statements": [
                    {
                        k: v
                        for k, v in s.items()
                        if k in ("employee", "id", "pay_date", "status", "type", "pay_period_start", "pay_period_end")
                    }
                    | {"_links": {"self": f"{LINK}/payrolls/{payroll_id}/pay-statements/{s['id']}"}}
                    for s in statements
                ]
            },
        )
    for payroll_id, statement in ((6001, maria), (6001, james), (6002, priya)):
        bundle.add(
            f"{EP}/payrolls/{{id}}/pay-statements/{{id}}",
            f"{ROOT}/payrolls/{payroll_id}/pay-statements/{statement['id']}",
            {},
            statement,
        )
