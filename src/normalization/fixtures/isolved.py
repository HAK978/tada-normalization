"""isolved fixtures: the "brightside" scenario, as isolved's API would return it.

Same people and facts as the PrismHR scenario, in isolved's shape, with isolved's traps: sequence
0 is the net-pay account, memo earnings sit outside gross wages, group-term life is in gross wages
but not gross pay, a 1-character lookup code where live sends text, a customer-defined status, a
contractor pay item with no documented cash treatment, a garnishment, a paycheck whose run is
ambiguous, a year-to-date-only line, and a check seen only in the list.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal as D
from typing import Any

from . import FixtureBundle, cents
from .validate import complete

TENANT = "synthetic"
SEED = 2026
CLIENT, LEGAL = "501", "601"
BASE = f"api/clients/{CLIENT}/legals/{LEGAL}"
EP = "api/clients/{client}/legals/{legal}"

# client pay item title -> (payItemType, systemBenefitType, systemPayItemType)
PAY_ITEMS = {
    "Regular": ("Earning", None, "Regular"),
    "Overtime": ("Earning", None, "Overtime @ Flat 1.5"),
    "Holiday": ("Earning", "Leave Accrual", "Holiday"),
    "Bonus": ("Earning", None, "Bonus"),
    "GTL": ("Earning", "Group Term Life", "GTL"),
    "1099 Comp": ("Earning", None, "1099M Non EE Comp"),
    "401K": ("Deduction", "401(k)", "401K"),
    "401K Loan": ("Deduction", "401(k)", "401K Loan"),
    "Dental Pre-tax": ("Deduction", "Dental Pre-Tax 125", "Dental Pre-tax"),
    "HSA After-tax": ("Deduction", "Health Savings Account", "HSA After-tax"),
    "Voluntary Life": ("Deduction", None, "Voluntary Deduction"),
    "401(k) Match": ("Memo Calc", "401(k)", "401(k) Match"),
}


@dataclass
class Worker:
    id: str
    number: str
    first: str
    last: str
    status: str
    implied: bool
    status_date: str
    category: str
    pay_type: str
    pay_group: tuple[str, str, int]
    hourly: D
    per_pay: D | None
    annual: D
    marital: str = "Single"
    deposits: list[tuple] = field(default_factory=list)
    items: list[tuple] = field(default_factory=list)
    garnishment: bool = False


BIWEEKLY, WEEKLY = ("701", "Biweekly", 26), ("702", "Weekly", 52)


def workers(rng: random.Random) -> list[Worker]:
    last = ["Lopez", "Chen", "Silva", "Price", "Nair"]
    rng.shuffle(last)
    common: dict[str, Any] = dict(implied=True, category="FT")
    return [
        Worker(
            id="9001",
            number="1001",
            first="Maria",
            last=last[0],
            status="Active",
            status_date="2021-03-15",
            pay_type="Salary",
            pay_group=BIWEEKLY,
            hourly=D("25.00"),
            per_pay=D("2000.00"),
            annual=D("52000.00"),
            deposits=[
                (1, "Savings", "amount", D("200.00"), "000123456789"),
                (0, "Checking", None, None, "000987654321"),
            ],
            items=[("401K", "Percent", D("5.0")), ("Dental Pre-tax", "Amount", D("12.50"))],
            **common,
        ),
        # Marital status sent as the 1-character code the spec documents; live sends the text (A-52).
        Worker(
            id="9002",
            number="1002",
            first="James",
            last=last[1],
            status="Active",
            status_date="2023-06-01",
            pay_type="Hourly",
            pay_group=WEEKLY,
            hourly=D("22.50"),
            per_pay=None,
            annual=D("46800.00"),
            marital="M",
            deposits=[(1, "Checking", "percent", D("30"), "000555012345"), (0, "Savings", None, None, "000555067890")],
            items=[("Voluntary Life", "Amount", D("8.00")), ("401K Loan", "Amount", D("25.00"))],
            garnishment=True,
            implied=True,
            category="PT",
        ),
        Worker(
            id="9003",
            number="1003",
            first="Ana",
            last=last[2],
            status="Terminated",
            status_date="2026-09-30",
            pay_type="Hourly",
            pay_group=BIWEEKLY,
            hourly=D("30.00"),
            per_pay=None,
            annual=D("62400.00"),
            deposits=[(0, "Savings", None, None, "000777011111")],
            **common,
        ),
        # A customer-defined status: not an implied system status, so it stays a label (A-48).
        Worker(
            id="9004",
            number="1004",
            first="Devon",
            last=last[3],
            status="Leave - FMLA",
            status_date="2026-08-01",
            pay_type="Salary",
            pay_group=BIWEEKLY,
            hourly=D("28.85"),
            per_pay=D("2307.69"),
            annual=D("60000.00"),
            implied=False,
            category="FT",
        ),
        Worker(
            id="9005",
            number="1005",
            first="Priya",
            last=last[4],
            status="Active",
            status_date="2026-05-01",
            pay_type="1099",
            pay_group=WEEKLY,
            hourly=D("40.00"),
            per_pay=None,
            annual=D("83200.00"),
            **common,
        ),
    ]


def _money(value: D) -> float:
    return float(cents(value))


def _bucket(amount: D | None, ytd: D) -> dict:
    """isolved reports each line in check/current/ptd/mtd/qtd/ytd/ftd buckets; check equals current (A-28)."""
    a = None if amount is None else _money(amount)
    return {
        "checkDollars": a,
        "currentDollars": a,
        "ptdDollars": a,
        "mtdDollars": a,
        "qtdDollars": _money(ytd / 4),
        "ytdDollars": _money(ytd),
        "ftdDollars": _money(ytd),
    }


def build(seed: int = SEED) -> FixtureBundle:
    rng = random.Random(seed)
    staff = workers(rng)
    bundle = FixtureBundle("isolved", TENANT, [{"client_id": CLIENT, "legal_id": LEGAL}])
    _lookups(bundle)
    _company(bundle)
    for w in staff:
        _worker(bundle, w)
    _payroll(bundle, {w.id: w for w in staff})
    for capture in bundle.captures:
        if capture["status"] == 200:
            capture["body"] = complete("isolved", capture["endpoint"], capture["body"])
    return bundle


def _lookups(bundle: FixtureBundle) -> None:
    rows = {
        "api/lookup/Frequencies": [
            {"id": 12, "description": "Monthly"},
            {"id": 13, "description": "13 Pay Periods Per Year"},
            {"id": 24, "description": "Semi-Monthly"},
            {"id": 26, "description": "Bi-Weekly"},
            {"id": 52, "description": "Weekly"},
        ],
        "api/lookup/genders": [
            {"id": "F", "description": "Female"},
            {"id": "M", "description": "Male"},
            {"id": "X", "description": "Non-binary"},
            {"id": "N", "description": "Chose not to answer"},
        ],
        "api/lookup/maritalStatuses": [
            {"id": "S", "description": "Single"},
            {"id": "M", "description": "Married"},
            {"id": "R", "description": "Chose not to answer"},
        ],
        "api/lookup/citizenships": [
            {"id": "1", "description": "Citizen of the United States"},
            {"id": "5", "description": "National of the United States"},
        ],
        "api/system/payTypes": [
            {"id": "1", "description": "Hourly"},
            {"id": "2", "description": "Salary"},
            {"id": "4", "description": "1099"},
        ],
    }
    for endpoint, body in rows.items():
        bundle.add(endpoint, endpoint, {}, body)


def _company(bundle: FixtureBundle) -> None:
    bundle.add(
        "api/clients/{client}",
        f"api/clients/{CLIENT}",
        {},
        {"id": int(CLIENT), "clientCode": "BRT", "clientName": "Brightside Holdings", "links": []},
    )
    bundle.add(
        "api/clients/{client}/payItems",
        f"api/clients/{CLIENT}/payItems",
        {},
        [
            {
                "id": 900 + i,
                "title": title,
                "code": None,
                "description": None,
                "payItemType": kind,
                "systemBenefitType": benefit,
                "systemPayItemType": system,
                "scheduleDefault": "Every Pay",
                "isInactive": False,
                "hasDecliningBalance": False,
                "sequenceNumber": i,
                "calcParams": [{"paramType": "Amount"}],
            }
            for i, (title, (kind, benefit, system)) in enumerate(PAY_ITEMS.items())
        ],
    )
    bundle.add(
        EP,
        BASE,
        {"includeDetails": "true"},
        {
            "id": int(LEGAL),
            "legalName": "Brightside Bakery LLC",
            "legalCode": "BRT-01",
            "federalEIN": "12-3456789",
            "status": "Active",
            "allowRemoteWorkers": False,
            "iSolvedTimeEnabled": False,
            "forceDirectDepositPrenote": True,
            "legalAddress": {
                "streetAddress1": "100 Main St",
                "streetAddress2": None,
                "city": "Charlotte",
                "state": "NC",
                "zipCode": "28202",
                "phoneNumber": "7045550100",
                "addressDescription": "Headquarters",
            },
            "payGroups": [
                {
                    "id": int(g),
                    "payGroupName": name,
                    "payFrequency": freq,
                    "payrollType": "Regular Payroll",
                    "isInactive": False,
                    "normalHours": 80.0 if freq == 26 else 40.0,
                }
                for g, name, freq in (BIWEEKLY, WEEKLY)
            ],
            "client": {"id": int(CLIENT), "clientCode": "BRT", "clientName": "Brightside Holdings"},
            "workLocations": [],
            "services": [],
            "links": [],
        },
    )


def _worker(bundle: FixtureBundle, w: Worker) -> None:
    path = f"{BASE}/employees/{w.id}"
    contractor = w.pay_type == "1099"
    body = {
        "id": int(w.id),
        "employeeNumber": w.number,
        "timeclockId": f"T{w.number}",
        "uniqueId": f"U-{w.id}",
        "ssn": None,
        "idType": None,
        "birthDate": "1990-04-02T00:00:00",
        "gender": "Female" if w.first in ("Maria", "Ana", "Priya") else "Male",
        "maritalStatus": w.marital,
        "ethnicOrigin": "Hispanic or Latino" if w.first == "Maria" else None,
        "citizenship": "Citizen of the United States",
        "disabled": False,
        "employmentStatus": w.status,
        "statusDate": f"{w.status_date}T00:00:00",
        "terminationDate": f"{w.status_date}T00:00:00" if w.status == "Terminated" else None,
        "terminationReason": "Relocation" if w.status == "Terminated" else None,
        "terminationType": "Voluntary Termination" if w.status == "Terminated" else None,
        "workLocation": "NC1",
        "workLocationDashDescription": "NC1 - CHARLOTTE, NC",
        "employmentCategoryCode": w.category,
        "hireDate": "2021-03-15T00:00:00",
        "originalHireDate": "2021-03-15T00:00:00",
        "rehireDate": None,
        "jobCode": "BAKER",
        "jobTitle": "Baker",
        "jobFLSAExempt": w.pay_type == "Salary",
        "payType": w.pay_type,
        "payGroup": w.pay_group[1],
        "payFrequency": w.pay_group[2],
        "hourlyRate": float(w.hourly),
        "perPaySalary": float(w.per_pay) if w.per_pay else 0.0,
        "annualSalary": float(w.annual),
        "normalHours": 80.0 if w.pay_group == BIWEEKLY else 40.0,
        "salaryEffectiveDate": "2025-01-01T00:00:00",
        "emailAddress": f"{w.first.lower()}@work.example",
        "nameAddress": {
            "firstName": w.first,
            "middleName": None,
            "lastName": w.last,
            "preferredName": None,
            "address1": "12 Oak Ave",
            "address2": None,
            "city": "Charlotte",
            "state": "NC",
            "zipCode": "28202",
        },
        "personal": {
            "homePhone": "7045550100",
            "mobilePhone": None,
            "personalEmailAddress": f"{w.first.lower()}@example.com",
        },
        "assignedManager": {"id": 9001, "employeeName": "Maria"} if w.id != "9001" else None,
        "taxes": {"federal": {"filingStatus": "Single", "primaryExemptions": 0}} if not contractor else None,
        "i9Documents": {"documentA": {"documentNumber": "A1234567", "documentCode": "01"}},
        "links": [{"href": f"/{path}", "method": "GET", "rel": "self"}],
    }
    bundle.add(EP + "/employees/{id}", path, {"includeTaxes": "true"}, body)
    bundle.add(
        EP + "/employees/{id}/statuses",
        f"{path}/statuses",
        {},
        [
            {
                "statusId": -1 if w.implied else 55,
                "clientEmploymentStatusId": -1 if w.implied else 55,
                "clientEmploymentStatusDescription": w.status,
                "isImpliedStatus": w.implied,
                "effectiveDate": f"{w.status_date}T00:00:00",
                "endDate": None,
                "employeeEmploymentId": int(w.id) * 10,
            }
        ],
    )
    salaries = [
        {
            "id": int(w.id) * 100 + 1,
            "effectiveDate": "2025-01-01T00:00:00",
            "hourlyRate": float(w.hourly),
            "perPaySalary": float(w.per_pay) if w.per_pay else 0.0,
            "normalHours": 80.0,
            "isInactive": False,
            "frequency": {"id": w.pay_group[2], "description": "Bi-Weekly" if w.pay_group == BIWEEKLY else "Weekly"},
            "payType": {"id": "2" if w.pay_type == "Salary" else "1", "description": w.pay_type},
            "payGroup": {"id": int(w.pay_group[0]), "description": w.pay_group[1]},
            "changeReason": {"id": 1, "description": "Merit"},
        }
    ]
    bundle.add(EP + "/employees/{id}/salaries", f"{path}/salaries", {}, salaries)
    bundle.add(EP + "/employees/{id}/payRates", f"{path}/payRates", {}, [])
    deposits = [
        {
            "id": int(w.id) * 10 + i,
            "sequenceNumber": seq,
            "accountType": kind,
            "amount": float(value) if how == "amount" else None,
            "percent": float(value) if how == "percent" else None,
            "accountNumber": account,
            "routingNumber": "123456780",
            "bankName": "Example Bank",
            "description": kind,
            "frequency": "Every Pay",
            "status": "Active",
        }
        for i, (seq, kind, how, value, account) in enumerate(w.deposits)
    ]
    bundle.add(EP + "/employees/{id}/directdeposits", f"{path}/directdeposits", {}, deposits)
    items = [
        {
            "id": -(i + 1),
            "payItemId": -(i + 1),
            "payItemCode": None,
            "payItemName": title,
            "payItemType": PAY_ITEMS[title][0],
            "employeeId": int(w.id),
            "employeeNumber": w.number,
            "firstName": w.first,
            "lastName": w.last,
            "referenceNumber": None,
            "scheduleOverride": None,
            "startDate": "2025-01-01T00:00:00",
            "stopDate": None,
            "calcParams": [{"paramType": param, "paramValue": float(value)}],
        }
        for i, (title, param, value) in enumerate([*w.items, ("Regular", "Amount", D("0"))])
    ]
    bundle.add(EP + "/employees/{id}/payItems", f"{path}/payItems", {}, items)
    if w.garnishment:
        bundle.add(
            EP + "/employees/{id}/garnishments",
            f"{path}/garnishments",
            {},
            [
                {
                    "id": 4401,
                    "garnishmentSequence": 1,
                    "garnishmentDescription": "Child support order",
                    "garnishmentType": {"id": "CS", "typeDescription": "Child Support"},
                    "caseNumber": "CASE-0001",
                    "amount": 50.0,
                    "percent": None,
                    "percentageOf": "Disposable Income",
                    "status": "Active",
                    "startDate": "2026-01-01T00:00:00",
                    "stopDate": None,
                    "limit": 0.0,
                    "maximumAmount": 2000.0,
                    "garnishmentPayee": {"id": 7, "payeeName": "State Disbursement Unit"},
                    "state": {"id": "NC", "stateName": "NC"},
                    "arrearsBalance": 0.0,
                    "remainingBalance": 1500.0,
                    "feeAmount": 1.0,
                }
            ],
        )
    else:
        # Live isolved answers 404 when an employee has no garnishments.
        bundle.add(EP + "/employees/{id}/garnishments", f"{path}/garnishments", {}, {"_non_json_body": ""}, status=404)


# ---------------------------------------------------------------------- payroll

RUNS = [  # (pay group, run id, run number, pay date, type, status)
    (BIWEEKLY, "8800", 35, "2018-08-03", "Data Conversion", "Completed Payroll Run"),
    (BIWEEKLY, "8801", 1, "2026-10-02", "Regular Payroll", "Completed Payroll Run"),
    (BIWEEKLY, "8803", 3, "2026-10-09", "Regular Payroll", "Completed Payroll Run"),
    (BIWEEKLY, "8802", 1, "2026-10-16", "Regular Payroll", "Payroll Not Processed"),
    (WEEKLY, "8811", 2, "2026-10-02", "Regular Payroll", "Completed Payroll Run"),
    # Same pay date and run number as 8803 in the other pay group: a check from either is ambiguous (A-40).
    (WEEKLY, "8813", 3, "2026-10-09", "Regular Payroll", "Completed Payroll Run"),
]


def _check(
    check_id: int,
    w: Worker,
    date: str,
    period: tuple[str, str],
    run_number: int,
    check_type: str,
    earnings: list[tuple[str, D, D | None]],
    deductions: list[tuple[str, D]],
    garnishments: list[tuple[str, D]],
    memo: Sequence[tuple[str, D]] = (),
    non_cash: Sequence[tuple[str, D]] = (),
    ytd_only: bool = False,
) -> dict:
    # Live: grossWages - grossPay = the group-term life lines, which are taxed but not paid (A-28).
    gross_pay = sum((amount for _, amount, _ in earnings), D("0"))
    wages = gross_pay + sum((amount for _, amount in non_cash), D("0"))
    contractor = w.pay_type == "1099"
    pre_tax = sum((a for t, a in deductions if PAY_ITEMS[t][1] in ("401(k)", "Dental Pre-Tax 125")), D("0"))
    taxable = wages - pre_tax
    ee = (
        []
        if contractor
        else [
            # Live: itemCode is null and the description is the system tax's (A-68).
            (None, "FEDERAL WH", taxable * D("0.10")),
            (None, "SOC SEC EE", wages * D("0.062")),
            (None, "MED EE", wages * D("0.0145")),
            (None, "NORTH CAROLINA WH", taxable * D("0.04")),
        ]
    )
    er = (
        []
        if contractor
        else [
            (None, "SOC SEC ER", wages * D("0.062")),
            (None, "MED ER", wages * D("0.0145")),
            (None, "FUTA ER", wages * D("0.006")),
            (None, "NORTH CAROLINA SUI ER", wages * D("0.01")),
        ]
    )
    ee_total = sum((cents(a) for _, _, a in ee), D("0"))
    ded_total = sum((a for _, a in deductions), D("0")) + sum((a for _, a in garnishments), D("0"))
    net = gross_pay - ee_total - ded_total
    deposits, remaining = [], net
    for seq, kind, how, value, account in sorted(w.deposits, key=lambda d: (d[0] == 0, d[0])):
        amount = remaining if seq == 0 else (min(value, remaining) if how == "amount" else cents(net * value / 100))
        deposits.append(
            {
                "account": "X" * (len(account) - 4) + account[-4:],
                "depositAmount": _money(amount),
                "itemDescription": kind,
            }
        )
        remaining -= amount
    deposited = sum((D(str(d["depositAmount"])) for d in deposits), D("0"))
    lines = [
        {
            "itemCode": code,
            "itemDescription": code,
            "isMemoEarning": False,
            "checkHours": float(hours) if hours else None,
            "checkUnits": None,
            **_bucket(amount, amount * 20),
        }
        for code, amount, hours in earnings
    ]
    lines += [
        {
            "itemCode": code,
            "itemDescription": code,
            "isMemoEarning": False,
            "checkHours": None,
            "checkUnits": None,
            **_bucket(amount, amount * 20),
        }
        for code, amount in non_cash
    ]
    lines += [
        {
            "itemCode": code,
            "itemDescription": code,
            "isMemoEarning": True,
            "checkHours": None,
            "checkUnits": None,
            **_bucket(amount, amount * 20),
        }
        for code, amount in memo
    ]
    if ytd_only:
        # Nothing on this check, only year-to-date history: not a line of this paycheck (kept in extensions).
        lines.append(
            {
                "itemCode": "Bonus",
                "itemDescription": "Bonus",
                "isMemoEarning": False,
                "checkHours": None,
                "checkUnits": None,
                **_bucket(None, D("500")),
            }
        )
    return {
        "id": check_id,
        "checkDate": f"{date}T00:00:00",
        "checkNumber": check_id % 100000,
        "checkSequence": 0,
        "checkTypeDescription": check_type,
        "payrollRunNumber": run_number,
        "payrollRunType": "Data Conversion" if date.startswith("2018") else "Regular Payroll",
        "periodBeginDate": f"{period[0]}T00:00:00",
        "periodEndDate": f"{period[1]}T00:00:00",
        "employeeId": int(w.id),
        "employeeNumber": w.number,
        "employeeName": f"{w.first} {w.last}",
        "employeeSSN": "XXX-XX-" + str(6789 - int(w.id) % 10),
        "legalCompanyName": "Brightside Bakery LLC",
        "grossWages": _money(wages),
        "grossPay": _money(gross_pay),
        "netPay": _money(net),
        "checkAmount": _money(net - deposited),
        "directDepositAmount": _money(deposited),
        "earnings": lines,
        "taxes": [
            {
                "itemCode": c,
                "itemDescription": d,
                "isEmployeeTax": True,
                "checkTaxableWages": _money(taxable),
                **_bucket(a, a * 20),
            }
            for c, d, a in ee
        ]
        + [
            {
                "itemCode": c,
                "itemDescription": d,
                "isEmployeeTax": False,
                "checkTaxableWages": _money(wages),
                **_bucket(a, a * 20),
            }
            for c, d, a in er
        ],
        "deductions": [{"itemCode": t, "itemDescription": t, **_bucket(a, a * 20)} for t, a in deductions],
        "garnishments": [{"itemCode": t, "itemDescription": t, **_bucket(a, a * 20)} for t, a in garnishments],
        "benefits": [
            {
                "benefitTitle": "401(k)",
                "benefitDescription": "401(k)",
                "checkEmployeeDeduction": _money(a),
                "checkEmployerContribution": _money(m),
                "checkEmployeeCatchUp": 0.0,
            }
            for (t, a), (_, m) in zip(deductions, memo, strict=False)
            if t == "401K"
        ],
        "directDeposits": deposits,
        "accruals": [],
        "employeeOrganizations": [],
    }


def _payroll(bundle: FixtureBundle, staff: dict[str, Worker]) -> None:
    for (group, _name, _freq), run_id, number, date, run_type, status in RUNS:
        row = {
            "id": int(run_id),
            "runNumber": number,
            "payDate": f"{date}T00:00:00",
            "runDate": f"{date}T00:00:00",
            "payrollRunType": run_type,
            "status": status,
            "payOfTheMonth": "1st",
            "periodBeginDate": f"{date}T00:00:00",
            "periodEndDate": f"{date}T00:00:00",
            "payPeriod": number,
        }
        bundle.add(
            EP + "/paygroupId/{id}/payrollRunHistory/{id}",
            f"{BASE}/paygroupId/{group}/payrollRunHistory/{run_id}",
            {},
            row,
        )
    for pay_group in (BIWEEKLY, WEEKLY):
        rows = [
            {"id": int(r[1]), "runNumber": r[2], "payDate": f"{r[3]}T00:00:00", "payrollRunType": r[4], "status": r[5]}
            for r in RUNS
            if r[0] == pay_group
        ]
        bundle.add(
            EP + "/paygroupId/{id}/payrollRunHistory", f"{BASE}/paygroupId/{pay_group[0]}/payrollRunHistory", {}, rows
        )

    maria, james, ana, priya = staff["9001"], staff["9002"], staff["9003"], staff["9005"]
    bw, wk = ("2026-09-14", "2026-09-27"), ("2026-09-21", "2026-09-27")
    detailed = [
        _check(
            70001,
            maria,
            "2026-10-02",
            bw,
            1,
            "Regular",
            [("Regular", D("1800.00"), D("72")), ("Holiday", D("200.00"), D("8"))],
            [("401K", D("100.00")), ("Dental Pre-tax", D("12.50"))],
            [],
            memo=[("401(k) Match", D("60.00"))],
            non_cash=[("GTL", D("3.10"))],
            ytd_only=True,
        ),
        _check(
            70002,
            james,
            "2026-10-02",
            wk,
            2,
            "Regular",
            [("Regular", D("450.00"), D("20")), ("Overtime", D("135.00"), D("4"))],
            [("Voluntary Life", D("8.00")), ("401K Loan", D("25.00"))],
            [("Child Support", D("50.00"))],
        ),
        _check(70003, ana, "2026-10-02", bw, 1, "Regular", [("Regular", D("1920.00"), D("64"))], [], []),
        _check(70004, priya, "2026-10-02", wk, 2, "Regular", [("1099 Comp", D("1200.00"), None)], [], []),
        _check(
            70005, maria, "2026-10-09", bw, 3, "Regular", [("Bonus", D("500.00"), None)], [("401K", D("25.00"))], []
        ),
        _check(
            60001,
            ana,
            "2018-08-03",
            ("2018-07-16", "2018-07-29"),
            35,
            "Adjustment",
            [("Regular", D("1500.00"), D("50"))],
            [],
            [],
        ),
    ]
    for body in detailed:
        employee = str(body["employeeId"])
        bundle.add(EP + "/employees/{id}/checks/{id}", f"{BASE}/employees/{employee}/checks/{body['id']}", {}, body)
    # The legal-level list returns headers only; one check there was never fetched in detail.
    extra = _check(70009, james, "2026-09-25", wk, 9, "Regular", [("Regular", D("400.00"), D("20"))], [], [])
    headers = [
        {
            **{
                k: v
                for k, v in b.items()
                if k not in ("earnings", "taxes", "deductions", "garnishments", "benefits", "directDeposits")
            },
            "earnings": None,
            "taxes": None,
            "deductions": None,
            "garnishments": None,
            "benefits": None,
            "directDeposits": None,
            "checkTypeDescription": None,
            "checkSequence": 1,
        }
        for b in [*detailed, extra]
    ]
    bundle.add(
        EP + "/checks",
        f"{BASE}/checks",
        {"filter.fromDate": "2015-01-01", "filter.toDate": "2027-12-31", "filter.pageSize": 500, "filter.page": 0},
        {
            "results": headers,
            "nextPageUrl": None,
            "previousPageUrl": None,
            "totalItems": len(headers),
            "totalPages": 1.0,
        },
    )
