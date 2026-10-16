"""PrismHR fixtures: the "brightside" scenario, as PrismHR's API would return it.

The known facts are written down here; every paycheck is computed from them so that gross,
taxes, deductions, net and deposits reconcile exactly. The traps found in discovery are built
in on purpose: V meaning Void (batch) and Vacation (voucher), the undocumented "A" rate basis,
citizenship sent as text, live key aliases, a 9999-12-31 and a 0000-01-01 date, null fields,
masked SSNs and accounts, non-cash pay, hours vs units, HSA "PN", and a refused endpoint.
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

# payCode -> (payClass, payReason, description, rateClass, talxPayType). payClass/payReason meanings are
# documented (A-32, A-38). talxPayType is PrismHR's own category of the code (A-67); live tenants leave it
# blank, as OT does here, which makes the code the customer's own to classify.
PAY_CODES = {
    "REG": ("E", "H", "Regular", "S", "R"),
    "OT": ("E", "H", "Overtime", "P", ""),
    "HOL": ("E", "H", "Holiday", "S", "H"),
    "VAC": ("E", "H", "Vacation", "S", "V"),
    "BONUS": ("E", "U", "Bonus", "S", "B"),
    "TIPS": ("RT", "U", "Reported Tips", "S", "T"),
    "MILE": ("R", "U", "Mileage Reimbursement", "S", ""),
    "FRINGE": ("F", "U", "Fringe", "S", ""),
}
# deductionCode -> (deductionType, calculationMethod, description)
DEDUCTION_CODES = {
    "C401K": ("K", "K", "401(k)"),
    "DEN125": ("C", "F", "Dental Pre-Tax"),
    "LIFE": ("V", "F", "Voluntary Life"),
    "UNIFORM": ("V", "F", "Uniform"),
    "LOAN1": ("L", "F", "Employee Loan"),
    "GARN": ("G", "G", "Garnishment"),
}
PRE_TAX_K, SECTION_125 = {"K", "KC"}, {"C"}
NON_CASH = {"F", "M", "RT"}


@dataclass
class Person:
    id: str
    number: str
    first: str
    last: str
    status_class: str
    status_date: str
    type_code: str
    type_class: str
    pay_method: str
    pay_group: str
    pay_period: str
    hourly: D
    basis: str
    basis_rate: D
    salary: D | None = None
    annual: D | None = None
    term_reason: str = ""
    contractor: bool = False
    deposits: list[tuple] = field(default_factory=list)
    hsa: list[tuple] = field(default_factory=list)
    deductions: list[tuple] = field(default_factory=list)
    effective_date: str = "2025-01-01"
    extra_person: dict = field(default_factory=dict)


@dataclass
class Line:
    code: str
    quantity: D
    rate: D

    @property
    def amount(self) -> D:
        return cents(self.quantity * self.rate)


def people(rng: random.Random) -> dict[str, list[Person]]:
    first = ["Maria", "James", "Ana", "Devon", "Priya", "Omar"]
    last = ["Lopez", "Chen", "Silva", "Price", "Nair", "Haddad"]
    rng.shuffle(last)  # seeded: names change with the seed, the facts don't
    return {
        "201": [
            Person(
                "E1001",
                "1001",
                first[0],
                last[0],
                "A",
                "2021-03-15",
                "FT",
                "F",
                "S",
                "BW",
                "B",
                hourly=D("25.00"),
                basis="A",
                basis_rate=D("52000.00"),
                salary=D("2000.00"),
                annual=D("52000.00"),
                deposits=[("F", "S", D("200.00")), ("B", "C", None)],
                hsa=[("HE", "PN", D("2.0"))],
                deductions=[
                    ("C401K", True, D("5.0"), "12345", "2021-04-01"),
                    ("DEN125", False, D("12.50"), "12345", "2021-04-01"),
                ],
                extra_person={"cobraSSN": "000-12-3456"},
            ),
            Person(
                "E1002",
                "1002",
                first[1],
                last[1],
                "A",
                "2023-06-01",
                "PT",
                "P",
                "H",
                "W",
                "W",
                hourly=D("22.50"),
                basis="H",
                basis_rate=D("22.50"),
                annual=D("46800.00"),
                deposits=[("P", "C", D("30"), D("500.00")), ("PN", "S", D("50")), ("B", "IP", None)],
                deductions=[("LIFE", False, D("8.00"), "12345", "2023-07-01")],
            ),
            Person(
                "E1003",
                "1003",
                first[2],
                last[2],
                "T",
                "2026-09-30",
                "FT",
                "F",
                "H",
                "BW",
                "B",
                hourly=D("30.00"),
                basis="H",
                basis_rate=D("30.00"),
                annual=D("62400.00"),
                term_reason="VOL",
                deposits=[("B", "S", None)],
            ),
            Person(
                "E1004",
                "1004",
                first[3],
                last[3],
                "L",
                "2026-08-01",
                "FT",
                "F",
                "S",
                "M",
                "M",
                hourly=D("28.85"),
                basis="Y",
                basis_rate=D("60000.00"),
                salary=D("5000.00"),
                annual=D("60000.00"),
                effective_date="0000-01-01",
            ),
            Person(
                "E1005",
                "1005",
                first[4],
                last[4],
                "A",
                "2026-05-01",
                "S",
                "F",
                "H",
                "W",
                "W",
                hourly=D("40.00"),
                basis="H",
                basis_rate=D("40.00"),
                annual=D("83200.00"),
                contractor=True,
            ),
        ],
        "202": [
            Person(
                "E2001",
                "2001",
                first[5],
                last[5],
                "A",
                "2022-02-01",
                "FT",
                "F",
                "H",
                "BW",
                "B",
                hourly=D("28.00"),
                basis="H",
                basis_rate=D("28.00"),
                annual=D("58240.00"),
                deposits=[("B", "S", None)],
            ),
        ],
    }


def build(seed: int = SEED) -> FixtureBundle:
    rng = random.Random(seed)
    staff = people(rng)
    bundle = FixtureBundle("prismhr", TENANT, [{"client_id": "201"}, {"client_id": "202"}])
    _client_201(bundle, staff["201"], rng)
    _client_202(bundle, staff["202"], rng)
    for capture in bundle.captures:
        if capture["status"] == 200:
            capture["body"] = complete("prismhr", capture["endpoint"], capture["body"])
    return bundle


# ---------------------------------------------------------------------- company-level responses


def _envelope(**body: Any) -> dict:
    return {**body, "errorCode": "0", "errorMessage": "", "extension": None}


def _client_master(client_id: str, name: str, service: str, employer: str, alt: list[str], fein: str) -> dict:
    return _envelope(
        clientMaster={
            "id": client_id,
            "clientName": name,
            "legalName": f"{name} LLC",
            "serviceType": service,
            "status": "A",
            "statusClass": "A",
            "statusDate": "2020-01-01",
            "employerId": employer,
            "federalIdNumber": fein,
            "addressLine1": "100 Main St",
            "addressLine2": "",
            "city": "Charlotte",
            "stateCode": "NC",
            "zipCode": "28202",
            "zipSuffix": "",
            "mainPhone": "7045550100",
            "mainPhoneExt": "",
            "emailAddress": f"payroll@{client_id}.example",
            "altEmployer": [
                {
                    "altEmployerId": a,
                    "altDisplayName": f"Alternate employer {a}",
                    "altCostCtr": "",
                    "altCheckingAcct": "",
                    "altAchAcct": "",
                    "suppressClientAccess": "Y",
                }
                for a in alt
            ],
            "regRebuild": [{"regRebuildDate": "2025-02-13T18:29:31Z"}],
            "taxLimitBasis": "",
            "categoryCode": "BAKERY" if client_id == "201" else "FREIGHT",
        }
    )


def _client_codes(client_id: str) -> dict:
    return _envelope(
        clientCodes={
            "clientId": client_id,
            "statusCode": [
                {"id": "A", "description": "Active", "statusClass": "A", "obsolete": False},
                {"id": "L", "description": "Leave of Absence", "statusClass": "L", "obsolete": False},
                {"id": "T", "description": "Terminated", "statusClass": "T", "obsolete": False},
            ],
            "typeCode": [
                {"id": "FT", "description": "Full Time", "typeClass": "F"},
                {"id": "PT", "description": "Part Time", "typeClass": "P"},
                {"id": "S", "description": "Seasonal", "typeClass": "F"},
            ],
            "payCode": [
                {
                    "id": code,
                    "payClass": cls,
                    "payReason": reason,
                    "payDescription": desc,
                    "payType": "R",
                    "calcMethod": "S",
                    "rateClass": rate_class,
                    "talxPayType": talx,
                }
                for code, (cls, reason, desc, rate_class, talx) in PAY_CODES.items()
            ],
            "deductionCode": [
                {"id": code, "type": dtype, "calculationMethod": method, "description": desc}
                for code, (dtype, method, desc) in DEDUCTION_CODES.items()
            ],
            "jobCode": [{"id": "BAKER", "jobTitle": "Baker"}, {"id": "DRIVER", "jobTitle": "Delivery Driver"}],
            "departmentCode": [{"id": "PROD", "deptName": "Production"}, {"id": "LOG", "deptName": "Logistics"}],
            "divisionCode": [{"id": "MAIN", "divisionName": "Main"}],
            "locationCode": [{"id": "CLT", "locationName": "Charlotte"}],
            "reasonCode": [{"id": "VOL", "description": "Voluntary resignation", "validActions": "T"}],
            "ethnicCode": [{"id": "H", "description": "Hispanic or Latino", "reportCode": "H"}],
            "relationCodes": [
                {"code": "S", "description": "Spouse", "obsolete": False},
                {"code": "C", "description": "Child", "obsolete": False},
            ],
            "payGroups": [
                {"payGroupCode": "BW", "description": "Biweekly"},
                {"payGroupCode": "W", "description": "Weekly"},
                {"payGroupCode": "M", "description": "Monthly"},
            ],
        }
    )


def _retirement_loan(loan_id: str, employee_id: str, loan_date: str, starts: str, tpa: str) -> dict:
    return {
        "loanId": loan_id,
        "employeeId": employee_id,
        "loanAmount": 5000.0,
        "loanDate": loan_date,
        "interestRate": "4.50",
        "loanReason": "",
        "paymentAmount": 104.17,
        "paybackAmount": 5416.84,
        "amtPaidBackToDate": 1250.04,
        "planId401k": "401k",
        "tpaLoanId": tpa,
        "overridePaymentAmt": None,
        "overridePayFrom": None,
        "overridePayTo": None,
        "deductionStarts": starts,
        "paidbackAdjust": [],
        "checksum": f"RL{loan_id}",
    }


def _schedule() -> dict:
    # Live key is clientPayrollSchedule (singular); the spec documents clientPayrollSchedules (A-16).
    rows = [("BW", "Biweekly", "B", "Biweekly"), ("W", "Weekly", "W", "Weekly"), ("M", "Monthly", "M", "Monthly")]
    return {
        "clientPayrollSchedule": [
            {
                "groupId": g,
                "groupDesc": desc,
                "scheduleId": g,
                "scheduleDesc": desc,
                "weekEndOnDay": "6",
                "printFaxBack": False,
                "payPeriod": code,
                "payPeriodDesc": pdesc,
                "payDay": "5",
                "skipWeekends": True,
            }
            for g, desc, code, pdesc in rows
        ],
        "errorCode": "0",
        "errorMessage": "",
        "extension": None,
    }


# ---------------------------------------------------------------------- employees


def _employee(p: Person, rng: random.Random, employers: dict[str, list[str]]) -> dict:
    deposits = []
    for spec in p.deposits:
        method, account = spec[0], spec[1]
        row = {
            "transitNum": "123456780",
            "accountNum": "*" * rng.randint(6, 10),
            "accountType": account,
            "method": method,
            "status": "D",
            "bankName": "Example Bank",
            "voucherTypeOverride": "",
        }
        if method in ("F", "FS"):
            row["amount"] = float(spec[2])
        elif method in ("P", "PN"):
            row["amount"] = float(spec[2])
            if method == "P" and len(spec) > 3:
                row["limit"] = float(spec[3])
        deposits.append(row)
    hsa = [
        {
            "transitNum": "123456780",
            "accountNum": "*" * 8,
            "accountType": acct,
            "method": method,
            "amount": float(amount),
            "status": "D",
            "bankName": "Example HSA Bank",
            "voucherTypeOverride": "",
        }
        for acct, method, amount in p.hsa
    ]
    return {
        "id": p.id,
        "lastName": p.last,
        "firstName": p.first,
        "middleInitial": "",
        "preferredName": "",
        "person": {
            "birthDate": "1990-04-02",
            "gender": "F" if p.first in ("Maria", "Ana", "Priya") else "M",
            "maritalStatus": "S",
            "ethnicCode": "H" if p.id == "E1001" else "",
            "veteran": "N",
            "handicapped": "",
            "preferredLanguage": "EN",
            "userId": f"{p.first[0]}{p.last}".lower(),
            **employers,
            "nickname": "",
            "hrpCitizenshipCountry": None,
            "emergencyContact": [
                {
                    "contactName": "Pat Example",
                    "contactInfo": "7045550199",
                    "contactRelationship": "Sibling",
                    "contactType": "PHONE",
                }
            ],
            "vehicleDetails": [{"vehicleMake": "Example", "vehicleModel": "Van", "vehicleYear": "2020"}],
            **p.extra_person,
        },
        "contactInformation": {
            "addressLine1": f"{rng.randint(10, 999)} Oak Ave",
            "addressLine2": "",
            "city": "Charlotte",
            "state": "NC",
            "zipcode": "28202",
            "zipSuffix": "",
            "county": "Mecklenburg",
            "homePhone": "7045550100",
            "mobilePhone": "",
            "emailAddress": f"{p.first.lower()}@example.com",
        },
        "client": {
            "employeeStatus": p.status_class,
            "statusClass": p.status_class,
            "statusDate": p.status_date,
            "employeeType": p.type_code,
            "typeClass": p.type_class,
            "typeDate": p.status_date,
            "jobCode": "BAKER" if p.pay_group != "W" else "DRIVER",
            "jobStartDate": "2021-03-15",
            "firstHireDate": "2021-03-15",
            "lastHireDate": "2021-03-15",
            "flsaExempt": p.pay_method == "S",
            "seniorityDate": "2021-03-15",
            "termReasonCode": p.term_reason,
            "termExplanation": "",
            "employee1099": p.contractor,
            "clientEmployeeId": p.number,
            "clockNum": "",
            "workPhone": "",
            "workEmail": f"{p.first.lower()}.{p.last.lower()}@work.example",
            "homeDepartment": "PROD" if p.pay_group != "W" else "LOG",
            "homeDivision": "MAIN",
            "homeLocation": "CLT",
            "manager": "E1001" if p.id != "E1001" else "",
            "unionCode": "",
            "hawaiiMedWaivers": [],
            "returnDate": "2026-11-01" if p.status_class == "L" else "",
        },
        "compensation": {
            "ssn": "***-**-****",
            "payGroup": p.pay_group,
            "payPeriod": p.pay_period,
            "payMethod": p.pay_method,
            "salary": str(p.salary) if p.salary else "",
            "hourlyPay": str(p.hourly),
            "hourlyPayRate": str(p.basis_rate),
            "hourlyPayPeriod": p.basis,
            "annualPay": str(p.annual) if p.annual else "",
            "standardHours": "80.00",
            "effectiveDate": p.effective_date,
            "citizenshipStatus": "A citizen of the United States",
            "fedFilingStatus": "SS",
            "lastWorkedDate": "2026-09-30" if p.status_class == "T" else "",
            "stateTax": [{"stateCode": "NC", "filingStatus": "S", "primaryAllowance": "0"}],
        },
        "directDeposit": {
            "achStatus": "A",
            "voucherType": "RV",
            "suppressAccountPrint": False,
            "achVoucher": deposits,
            "directDepositChecksum": "c-1",
        },
        "hsa": {"hsaDepositSettings": hsa, "achChecksum": "h-1"},
    }


def _employee_setup(bundle: FixtureBundle, client: str, p: Person) -> None:
    person = {"clientId": client, "employeeId": p.id}
    rows = []
    for code, use_percent, amount, period, start in p.deductions:
        dtype, method, desc = DEDUCTION_CODES[code]
        rows.append(
            {
                "deductionCode": code,
                "deductionType": dtype,
                "deductionMethod": method,
                "description": desc,
                "usePercent": use_percent,
                "amount": float(amount),
                "period": period,
                "startDate": start,
                "stopDate": "",
                "trackArrears": False,
                "mandatory": False,
                "loanOrGarnishId": "",
                "benefitPlanId": "",
                "limit": 0.0,
                "maximum": 0.0,
                "basis": "",
                "matchMethod": "P" if code == "C401K" else "",
                "matchAmount": 3.0 if code == "C401K" else 0.0,
                "matchDescription": "401(k) match" if code == "C401K" else "",
                "cutbackPayeeCode": "",
                "detailsChecksum": "d-1",
            }
        )
    bundle.add(
        "deductions/v1/getDeductions",
        "deductions/v1/getDeductions",
        {**person, "options": ""},
        _envelope(employeeDeductions={"deduction": rows}),
    )
    voluntary = [r for r in rows if r["deductionType"] == "V"]
    bundle.add(
        "deductions/v1/getVoluntaryRecurringDeductions",
        "deductions/v1/getVoluntaryRecurringDeductions",
        person,
        {**_envelope(voluntaryDeduction={"deduction": voluntary}), "checksum": "v-1"},
    )
    scheduled, loans = [], []
    if p.id == "E1002":
        scheduled = [
            {
                "deductionCode": "UNIFORM",
                "checkStubDescription": "",
                "status": "O",
                "amount": 15.0,
                "startDate": "2026-09-21",
                "stopDate": "2026-09-27",
                "cutbackPayeeCode": "",
            }
        ]
        # Payment dates fall on Fridays with day > 12: impossible as the documented YYYY-DD-MM (A-17).
        loans = [
            {
                "loanId": "1",
                "checksum": "l-1",
                "loanAmount": 500.0,
                "paymentAmount": 25.0,
                "paymentFreq": "P",
                "paybackAmount": 500.0,
                "loanReason": "Tools",
                "startDate": "2026-06-19",
                "stopDate": "",
                "loanDate": "2026-06-15",
                "paidAmount": 125.0,
                "glOverrideAccount": "",
                "deductionCode": "LOAN1",
                "paymentHistory": [
                    {"paymentDate": d, "paymentVoucherId": f"07{i:04d}", "paymentAmount": 25.0}
                    for i, d in enumerate(["2026-06-19", "2026-06-26", "2026-07-17", "2026-07-24", "2026-08-14"])
                ],
            }
        ]
    bundle.add(
        "employee/v1/getScheduledDeductions",
        "employee/v1/getScheduledDeductions",
        person,
        {
            **_envelope(scheduledDeduction=scheduled),
            "sessionId": "",
            "clientId": client,
            "employeeId": p.id,
            "checksum": "s-1",
        },
    )
    bundle.add(
        "deductions/v1/getEmployeeLoans",
        "deductions/v1/getEmployeeLoans",
        person,
        {**_envelope(employeeLoanDetail=loans), "sessionId": "", "clientId": client, "employeeId": p.id},
    )
    history = [
        {
            "effectiveDate": "9999-12-31",
            "payRate": str(p.salary or p.hourly),
            "payPeriod": p.pay_period if p.salary else "H",
            "annualPay": str(p.annual or ""),
            "standardHours": "80.00",
            "changePercent": "0.00",
            "changeAmount": "0.00",
            "reason": "Promo",
            "percentMidpoint": None,
            "payMethod": p.pay_method,
            "hourlyRate": str(p.hourly),
        }
    ]
    if p.id == "E1001":
        history.append(
            {
                "effectiveDate": "2024-01-01",
                "payRate": "1900.00",
                "payPeriod": "B",
                "annualPay": "49400.00",
                "standardHours": "80.00",
                "changePercent": "0.00",
                "changeAmount": "0.00",
                "reason": "Hire",
                "percentMidpoint": None,
                "payMethod": "S",
                "hourlyRate": "23.75",
            }
        )
    bundle.add(
        "employee/v1/getPayRateHistory",
        "employee/v1/getPayRateHistory",
        person,
        _envelope(payRateHistory={"employeeId": p.id, "clientId": client, "payRate": history}),
    )
    bundle.add(
        "benefits/v1/getActiveBenefitPlans", "benefits/v1/getActiveBenefitPlans", person, _envelope(benefitPlans=[])
    )
    # Client 201 sends the live key historyRecord, 202 the documented historyRecords (A-78).
    key = "historyRecord" if client == "201" else "historyRecords"
    bundle.add("employee/v1/getHistory", "employee/v1/getHistory", person, _envelope(**{key: _history(p)}))
    bundle.add(
        "benefits/v1/getDependents",
        "benefits/v1/getDependents",
        person,
        {**_envelope(dependent=_dependents(p)), "clientId": client, "employeeId": p.id},
    )
    # Garnishment details are refused below; this one employee is reported to have garnishments (A-83).
    has_garnishments = p.id == "E1002"
    bundle.add(
        "employee/v1/checkForGarnishments",
        "employee/v1/checkForGarnishments",
        person,
        _envelope(enrolled=has_garnishments, active=has_garnishments),
    )
    # One employee has a recurring payment set up; the others get PrismHR's "does not exist" 404.
    if p.id == "E1001":
        bundle.add(
            "payroll/v1/getScheduledPayments",
            "payroll/v1/getScheduledPayments",
            person,
            {
                **_envelope(
                    scheduledPayment={
                        "scheduledPaymentDetail": [
                            {
                                "payCode": "BONUS",
                                "payDesc": "Retention bonus",
                                "startPayDate": "2026-11-06",
                                "endPayDate": None,
                                "deductionPeriod": "12345",
                                "status": "A",
                                "amount": 150.0,
                            }
                        ]
                    }
                ),
                "clientId": client,
                "employeeId": p.id,
                "checksum": "sp-1",
            },
        )
    else:
        bundle.add(
            "payroll/v1/getScheduledPayments",
            "payroll/v1/getScheduledPayments",
            person,
            {
                "clientId": None,
                "employeeId": None,
                "checksum": None,
                "scheduledPayment": None,
                "errorCode": "404",
                "errorMessage": f"Scheduled payment for employee '{p.id}' in client '{client}' does not exist.",
                "extension": None,
            },
            status=404,
        )
    # Deduction setup PrismHR files under benefits (A-91): E1001 has a 401(k) plan with a catch-up election and
    # an FSA; E1002 a benefit adjustment deducted over four paychecks. The others answer as live does.
    if p.id == "E1001":
        bundle.add(
            "benefits/v1/getRetirementPlan",
            "benefits/v1/getRetirementPlan",
            person,
            _envelope(
                # Live sends planDetail where the spec documents planDetails, and its numbers as text (A-91).
                retirementPlan={
                    "planId": "401k",
                    "status": "A",
                    "statusDate": "2024-01-01",
                    "matchEligible": True,
                    "catchupStartAtLimit": False,
                    "extraElectiveAmt": "0.00",
                    "planDetail": [
                        {
                            "detailDate": "2024-01-01",
                            "electivePercent": "6.00",
                            "catchupPercent": "2.00",
                            "rothPercent": "0.00",
                        }
                    ],
                    "checksum": "rp-1",
                }
            ),
        )
        bundle.add(
            "benefits/v1/getFlexPlans",
            "benefits/v1/getFlexPlans",
            person,
            _envelope(
                spendingAccounts=[
                    {
                        "planId": "FSA",
                        "account": [
                            {
                                "electAmount": "1200.00",
                                "deductAmount": "50.00",
                                "startDate": "2026-01-01",
                                "stopDate": "2026-12-31",
                            }
                        ],
                    }
                ]
            ),
        )
    else:
        bundle.add(
            "benefits/v1/getRetirementPlan",
            "benefits/v1/getRetirementPlan",
            person,
            {
                "retirementPlan": None,
                "errorCode": "404",
                "errorMessage": f"Retirement plans for employee {p.id} in client {client} does not exist.",
                "extension": None,
            },
            status=404,
        )
        bundle.add("benefits/v1/getFlexPlans", "benefits/v1/getFlexPlans", person, _envelope(spendingAccounts=[]))
    if p.id == "E1002":
        bundle.add(
            "benefits/v1/getBenefitAdjustments",
            "benefits/v1/getBenefitAdjustments",
            person,
            _envelope(
                benefitAdjustments=[
                    {
                        "benefitPlan": "MED",
                        "eeContribution": "17.00",
                        "billAmount": "17.00",
                        "cycles": 4,
                        "cyclesBilled": 1,
                        "startDate": "2026-09-01",
                    }
                ]
            ),
        )
    else:
        bundle.add(
            "benefits/v1/getBenefitAdjustments",
            "benefits/v1/getBenefitAdjustments",
            person,
            {
                "benefitAdjustments": None,
                "errorCode": "404",
                "errorMessage": f"No benefit adjustments found for employee {p.id} and client {client}",
                "extension": None,
            },
            status=404,
        )
    # Mirrors the live tenant: garnishment details are refused for this API user (A-08).
    bundle.add(
        "deductions/v1/getGarnishmentDetails",
        "deductions/v1/getGarnishmentDetails",
        person,
        {
            "garnishmentDetails": None,
            "errorCode": "403",
            "errorMessage": "this user session is not authorized for the method specified",
            "extension": None,
        },
        status=403,
    )


def _history(p: Person) -> list[dict]:
    """getHistory rows: each holds one kind of change (A-76). Pay changes stay raw on the employee."""
    hired = "2023-06-01" if p.id == "E1002" else "2021-03-15"
    rows: list[dict] = [
        {
            "type": "statusChange",
            "effectiveDate": hired,
            "statusChange": {"employeeStatusCode": "A", "employeeTypeCode": p.type_code, "reason": ""},
        },
        {
            "type": "positionChange",
            "effectiveDate": hired,
            "newPositionCode": "DRIVER" if p.pay_group == "W" else "BAKER",
        },
        {
            "type": "payChange",
            "effectiveDate": p.effective_date if p.effective_date != "0000-01-01" else hired,
            "payChange": {
                "newPayRate": str(p.salary or p.hourly),
                "payPeriod": p.pay_period if p.salary else "H",
                "payMethod": p.pay_method,
                "annualPay": str(p.annual or ""),
                "hourlyRate": str(p.hourly),
                "reason": "Merit",
            },
        },
    ]
    if p.id == "E1002":
        rows.append(
            {"type": "departmentChange", "effectiveDate": "2024-02-01", "departmentChange": {"departmentCode": "LOG"}}
        )
        rows.append(
            {
                "type": "benefitGroupChange",
                "effectiveDate": "2024-01-01",
                "benefitGroupChange": {"benefitGroupCode": "PT"},
            }
        )
    if p.status_class == "L":
        rows.append(
            {
                "type": "leave",
                "effectiveDate": p.status_date,
                "leave": {
                    "employeeStatusCode": "L",
                    "employeeTypeCode": p.type_code,
                    "expectedReturnDate": "2026-11-01",
                    "reason": "MED",
                },
            }
        )
    if p.status_class == "T":
        rows.append(
            {
                "type": "termination",
                "effectiveDate": p.status_date,
                "termination": {
                    "employeeStatusCode": "T",
                    "employeeTypeCode": p.type_code,
                    "reason": p.term_reason,
                    "rehireOK": "N",
                    "explanation": "Relocated",
                },
            }
        )
    return rows


def _dependents(p: Person) -> list[dict]:
    """Dependents and beneficiaries (A-77). SSNs arrive masked, as live PrismHR masks them."""
    if p.id == "E1001":
        return [
            {
                "dependentId": "1",
                "firstName": "Sam",
                "lastName": p.last,
                "middleInitial": "",
                "relation": "S",
                "relationType": "D",
                "relationshipCodeType": "SP",
                "beneficiaryType": "P",
                "benefitPercent": "100",
                "spouse": "Y",
                "gender": "M",
                "birthdate": "1989-11-20",
                "ssn": "***-**-6789",
                "status": "A",
                "statusDate": "2021-04-01",
                "homePhone": "7045550111",
                "email": "sam@example.com",
                "address": "12 Oak Ave",
                "city": "Charlotte",
                "state": "NC",
                "zip": "28202",
            },
            {
                "dependentId": "2",
                "firstName": "Kai",
                "lastName": p.last,
                "relation": "C",
                "relationType": "D",
                "relationshipCodeType": "CH",
                "spouse": "N",
                # Live, 12 of 14 dependents' birth dates arrive masked like this (A-77).
                "birthdate": "****-**-**",
                "status": "P",
                "fullTimeStudent": False,
            },
        ]
    if p.id == "E1002":
        return [
            {
                "dependentId": "3",
                "firstName": "Lee",
                "lastName": "Example",
                "relation": "O",
                "relationType": "B",
                "beneficiaryType": "C",
                "benefitPercent": "100",
                "status": "A",
            }
        ]
    return []


def _company_contacts(live_key: bool) -> dict:
    """Client contacts; client 201 sends the live key prismClientContact (A-78, A-84)."""
    contacts = (
        [
            {
                "contactId": "11",
                "contactType": "PAY",
                "contactName": "Robin Example",
                "contactTitle": "Payroll Manager",
                "contactPhone": "7045550120",
                "contactPhoneExt": "12",
                "contactEmail": "payroll@brightside.example",
                "contactAddress": "100 Main St",
                "contactCity": "Charlotte",
                "contactState": "NC",
                "contactZip": "28202",
                "checksum": "pc-11",
            },
            {
                "contactId": "12",
                "contactType": "HR",
                "contactName": "Alex Example",
                "contactTitle": "HR Lead",
                "contactCellPhone": "7045550130",
                "checksum": "pc-12",
            },
        ]
        if live_key
        else []
    )
    key = "prismClientContact" if live_key else "prismClientContacts"
    return _envelope(prismClientContactResult={key: contacts})


# ---------------------------------------------------------------------- payroll


def _taxes(gross: D, pre_k: D, s125: D, contractor: bool) -> tuple[list[dict], list[dict]]:
    if contractor:
        return [], []
    taxable, fica = gross - pre_k - s125, gross - s125
    # Live code shapes (A-68): federal 00-NN; state <state number>-<tax number>, NC being 34.
    employee = [
        ("00-10", "Federal Income Tax", D("0.10"), taxable),
        ("00-11", "Medicare - Employee", D("0.0145"), fica),
        ("00-12", "Soc Security - Employee", D("0.062"), fica),
        ("34-20", "NC Income Tax", D("0.04"), taxable),
    ]
    employer = [
        ("00-15", "Medicare - Employer", D("0.0145"), fica, "9F"),
        ("00-16", "Soc Security - Employer", D("0.062"), fica, "8F"),
        ("00-17", "Fed Unemployment", D("0.006"), gross, "4F"),
        ("34-24", "NC Unemployment", D("0.027"), gross, "4S"),
    ]
    ee = [
        {
            "empTaxDeductCode": c,
            "empTaxDeductCodeDesc": d,
            "empTaxableAmount": float(base),
            "empTaxAmount": float(cents(base * r)),
            "empOverLimitAmount": 0.0,
        }
        for c, d, r, base in employee
    ]
    er = [
        {
            "comTaxEntity": "P",
            "comTaxDeductCode": c,
            "comTaxDeductCodeDesc": d,
            "comExemptAmount": 0.0,
            "comShelteredAmount": 0.0,
            "comTaxableAmount": float(base),
            "comTaxType": basis,
            "comTaxAmount": float(cents(base * r)),
            "comOvrLimit": 0.0,
            "comTaxRate": float(r),
            "comClientSutaRpt": "",
        }
        for c, d, r, base, basis in employer
    ]
    return ee, er


def _deposit_amounts(p: Person, net: D) -> list[tuple[str, D]]:
    """The generator's own allocation logic, used only to make realistic deposit amounts."""
    out, fixed = [], D("0")
    for spec in p.deposits:
        if spec[0] in ("F", "FS"):
            amount = min(spec[2], net - fixed)
            out.append((spec[1], amount))
            fixed += amount
    remaining = net - fixed
    for spec in p.deposits:
        if spec[0] == "P":
            amount = min(cents(net * spec[2] / 100), spec[3])
            out.append((spec[1], amount))
            remaining -= amount
        elif spec[0] == "PN":
            amount = cents((net - fixed) * spec[2] / 100)
            out.append((spec[1], amount))
            remaining -= amount
    for spec in p.deposits:
        if spec[0] == "B":
            out.append((spec[1], remaining))
    return out


def _voucher(
    voucher_id: str,
    batch_id: str,
    vtype: str,
    p: Person,
    pay_date: str,
    period: tuple[str, str],
    lines: list[Line],
    other: list[tuple[str, D]],
    deductions: list[tuple[str, D]],
    other_deductions: Sequence[tuple[str, D]] = (),
    void_date: str = "",
    hide_other_total: bool = False,
) -> dict:
    gross = sum((line.amount for line in lines), D("0")) + sum((a for _, a in other), D("0"))
    non_cash = sum((line.amount for line in lines if PAY_CODES[line.code][0] in NON_CASH), D("0"))
    non_cash += sum((a for code, a in other if PAY_CODES[code][0] in NON_CASH), D("0"))
    pre_k = sum((a for code, a in deductions if DEDUCTION_CODES[code][0] in PRE_TAX_K), D("0"))
    s125 = sum((a for code, a in deductions if DEDUCTION_CODES[code][0] in SECTION_125), D("0"))
    ee, er = _taxes(gross, pre_k, s125, p.contractor)
    ee_total = sum((D(str(t["empTaxAmount"])) for t in ee), D("0"))
    ded_total = sum((a for _, a in deductions), D("0")) + sum((a for _, a in other_deductions), D("0"))
    net = gross - non_cash - ee_total - ded_total
    deposits = _deposit_amounts(p, net) if p.deposits else []
    deposited = sum((a for _, a in deposits), D("0"))
    k401 = next((a for code, a in deductions if code == "C401K"), D("0"))
    other_total = sum((a for _, a in other), D("0"))
    return {
        "voucherId": voucher_id,
        "status": "PRNT",
        "type": vtype,
        "voidDate": void_date,
        "checkNumber": "" if deposits and deposited == net else str(90000 + int(voucher_id[-3:])),
        "payDate": pay_date,
        "employeeId": p.id,
        "payPeriod": p.pay_period,
        "payPeriodStart": period[0],
        "payPeriodEnd": period[1],
        "payGroup": p.pay_group,
        "dateProcessed": pay_date,
        "totalEarnings": float(gross),
        "employeeTax": ee,
        "netPay": float(net),
        "voidVoucherId": "",
        "fitTaxableAmount": float(gross - pre_k - s125),
        "earnAmount": float(sum((line.amount for line in lines), D("0"))),
        # Live vouchers leave Fringe out of otherEarnAmount; the lines are authoritative (A-32, A-42).
        "otherEarnAmount": 0.0 if hide_other_total else float(other_total),
        "wcHomeClass": "8810",
        "wcState": "NC",
        "earning": [
            {
                "payCode": line.code,
                "payClass": PAY_CODES[line.code][0],
                "payClassDescription": "Earnings",
                "chargeDate": period[1],
                "hoursUnits": float(line.quantity),
                "hoursWorked": float(line.quantity) if PAY_CODES[line.code][1] == "H" else 0.0,
                "unitRate": float(line.rate),
                "payAmount": float(line.amount),
                "division": "MAIN",
                "jobCode": "BAKER",
                "shift": "",
                "department": "PROD",
                "location": "CLT",
                "glCode": "",
                "workComp": "8810",
                "projWork": "",
                "projPhase": "",
            }
            for line in lines
        ],
        "otherEarningsDetail": [
            {"otherEarnCode": code, "otherEarnsDesc": PAY_CODES[code][2], "otherEarnAmount": float(amount)}
            for code, amount in other
        ],
        "companyTax": er,
        "batchId": batch_id,
        "deduction": [
            {
                "deductCode": code,
                "deductDescription": DEDUCTION_CODES[code][2],
                "deductAmount": float(a),
                "deductType": DEDUCTION_CODES[code][0],
                "deductUnionId": "",
                "planId": "401K" if code == "C401K" else "",
            }
            for code, a in deductions
        ],
        "otherDeduction": [
            {
                "otherDeductCode": code,
                "otherDeductDescription": DEDUCTION_CODES[code][2],
                "otherDeductAmount": float(a),
                "otherDeductOneTimeSwitch": "Y",
            }
            for code, a in other_deductions
        ],
        "benefit": [
            {
                "planId": "LIFE",
                "premiumAmt": 8.0,
                "empContrib": 0.0,
                "empDeduct": 8.0,
                "coveragePeriod": pay_date[:7].replace("-", ""),
                "adjRef": "",
                "premiumCost": 7.5,
            }
        ]
        if any(code == "LIFE" for code, _ in deductions)
        else [],
        "bankAccount": "OPER",
        "checkNum": None,
        "checkAmt": float(net - deposited),
        "payStubType": "Electronic",
        "checkAccountACH": "ACH1",
        "directDeposit": [
            {"transitNum": "123456780", "accountNum": "******", "status": "D", "amount": float(a)} for _, a in deposits
        ],
        "employerContributions": [
            {"code": "401KM", "description": "401(k) Match", "amount": float(cents(k401 * D("0.6")))}
        ]
        if k401
        else [],
        "retirement": {
            "planId": "401K",
            "planYearPeriod": pay_date[:4],
            "baseEarnings": float(gross),
            "electiveContributionsPreTax": float(k401),
            "employerMatchingContributions": float(cents(k401 * D("0.6"))),
        }
        if k401
        else {},
        "glAcctDistribution": None,
        "taxFilingStatus": [],
        "isManualCheck": False,
        "hsaPeoMatch": 0.0,
    }


def _batch(
    bundle: FixtureBundle,
    client: str,
    batch_id: str,
    pay_date: str,
    btype: str,
    status: str,
    groups: list[tuple[str, str, str]],
    vouchers: list[dict],
) -> dict:
    bundle.add(
        "payroll/v1/getBatchInfo",
        "payroll/v1/getBatchInfo",
        {"clientId": client, "batchId": batch_id},
        _envelope(
            batchControl={
                "batchStatus": status,
                "batchId": batch_id,
                "payDate": pay_date,
                "batchDescription": f"{batch_id} - {pay_date}",
                "batchType": btype,
                "processor": "synthetic",
                "deliveryMethod": "ELEC",
                "voucher": [
                    {
                        "payGroupId": g,
                        "periodStart": s,
                        "periodEnd": e,
                        "weeksWorked": 1.0,
                        "deductPeriod": "1",
                        "payPeriod": "40",
                    }
                    for g, s, e in groups
                ],
            }
        ),
    )
    if vouchers:
        # Live key is payrollVoucher (singular); the spec documents payrollVouchers (A-16).
        bundle.add(
            "payroll/v1/getPayrollVoucherForBatch",
            "payroll/v1/getPayrollVoucherForBatch",
            {
                "clientId": client,
                "batchId": batch_id,
                "count": "25",
                "startpage": "0",
                "options": ["EmployerContribution", "Retirement", "TaxFilingStatus", "Arrears"],
            },
            {
                "total": len(vouchers),
                "startpage": 0,
                "count": 25,
                "errorCode": "0",
                "errorMessage": "",
                "extension": None,
                "payrollVoucher": vouchers,
            },
        )
    return {
        "batchId": batch_id,
        "payDate": pay_date,
        "batchType": btype,
        "batchStatus": status,
        "payGroup": [
            {"payGroupId": g, "payPeriodStartDate": s, "payPeriodEndDate": e, "weeksWorked": "1", "deductPeriod": "1"}
            for g, s, e in groups
        ],
    }


def _client_201(bundle: FixtureBundle, staff: list[Person], rng: random.Random) -> None:
    c = "201"
    maria, james, ana, devon, priya = staff
    bundle.add(
        "clientMaster/v1/getClientMaster",
        "clientMaster/v1/getClientMaster",
        {"clientId": c},
        _client_master(c, "Brightside Bakery", "PEO", "5", ["20"], "**********"),
    )
    bundle.add(
        "clientMaster/v1/getClientCodes",
        "clientMaster/v1/getClientCodes",
        {"clientId": c, "options": "all"},
        _client_codes(c),
    )
    bundle.add("clientMaster/v1/getPayrollSchedule", "clientMaster/v1/getPayrollSchedule", {"clientId": c}, _schedule())
    bundle.add(
        "clientMaster/v1/getAllPrismClientContacts",
        "clientMaster/v1/getAllPrismClientContacts",
        {"clientId": c},
        _company_contacts(live_key=True),
    )
    # One loan against the 401(k) plan (A-87).
    bundle.add(
        "benefits/v1/getRetirementLoans",
        "benefits/v1/getRetirementLoans",
        {"clientId": c},
        _envelope(retirementLoan=[_retirement_loan("1", maria.id, "2025-03-03", "2025-03-14", "TPA-0417")]),
    )
    bundle.add(
        "employee/v1/getEmployeeList",
        "employee/v1/getEmployeeList",
        {"clientId": c},
        _envelope(employeeList={"employeeId": [p.id for p in staff]}),
    )
    bundle.add(
        "employee/v1/getEmployee",
        "employee/v1/getEmployee",
        {"clientId": c, "employeeId": [p.id for p in staff], "options": "Person,Client,Compensation"},
        # Live sends the employee's employers as employerId, documented as employerIds (A-78).
        _envelope(employee=[_employee(p, rng, {"employerId": ["5"]}) for p in staff]),
    )
    for p in staff:
        _employee_setup(bundle, c, p)
    bundle.add(
        "system/v1/getEmployerDetails",
        "system/v1/getEmployerDetails",
        {"employerId": "5"},
        {
            "employerInfo": None,
            "errorCode": "1",
            "errorMessage": "this user session is not authorized for the method specified",
            "extension": None,
        },
        status=403,
    )

    bw, wk = ("BW", "2026-09-14", "2026-09-27"), ("W", "2026-09-21", "2026-09-27")
    batches = [
        _batch(
            bundle,
            c,
            "30115",
            "2026-10-02",
            "R",
            "COMP",
            [bw, wk],
            [
                _voucher(
                    "077001",
                    "30115",
                    "R",
                    maria,
                    "2026-10-02",
                    bw[1:],
                    [Line("REG", D("72"), D("25.00")), Line("HOL", D("8"), D("25.00"))],
                    [("FRINGE", D("3.25"))],
                    [("C401K", D("100.00")), ("DEN125", D("12.50"))],
                    hide_other_total=True,
                ),
                _voucher(
                    "077002",
                    "30115",
                    "R",
                    james,
                    "2026-10-02",
                    wk[1:],
                    [
                        Line("REG", D("20"), D("22.50")),
                        Line("OT", D("4"), D("33.75")),
                        Line("TIPS", D("1"), D("45.00")),
                        Line("MILE", D("120"), D("0.655")),
                    ],
                    [],
                    [("LIFE", D("8.00")), ("LOAN1", D("25.00"))],
                    other_deductions=[("UNIFORM", D("15.00"))],
                ),
                _voucher("077003", "30115", "R", ana, "2026-10-02", bw[1:], [Line("REG", D("64"), D("30.00"))], [], []),
                _voucher(
                    "077004", "30115", "R", priya, "2026-10-02", wk[1:], [Line("REG", D("30"), D("40.00"))], [], []
                ),
            ],
        ),
        # Batch type V is Void; the voided check inside it carries a voidDate.
        _batch(
            bundle,
            c,
            "30116",
            "2026-10-02",
            "V",
            "COMP",
            [wk],
            [
                _voucher(
                    "077005",
                    "30116",
                    "R",
                    priya,
                    "2026-10-02",
                    wk[1:],
                    [Line("REG", D("2"), D("40.00"))],
                    [],
                    [],
                    void_date="2026-10-05",
                ),
            ],
        ),
        # A special batch whose voucher type V means Vacation, not Void.
        _batch(
            bundle,
            c,
            "30117",
            "2026-10-09",
            "S",
            "COMP",
            [bw],
            [
                _voucher(
                    "077006",
                    "30117",
                    "V",
                    maria,
                    "2026-10-09",
                    bw[1:],
                    [Line("VAC", D("40"), D("25.00"))],
                    [],
                    [("C401K", D("50.00"))],
                ),
            ],
        ),
        # An undocumented empty batch type, as seen live; its voucher is an adjustment (J).
        _batch(
            bundle,
            c,
            "30118",
            "2026-10-09",
            "",
            "COMP",
            [wk],
            [
                _voucher(
                    "077007", "30118", "J", james, "2026-10-09", wk[1:], [Line("BONUS", D("1"), D("20.00"))], [], []
                ),
            ],
        ),
        # An open batch with an undocumented status code and no vouchers yet.
        _batch(bundle, c, "30119", "2026-10-16", "R", "TS.READY", [bw], []),
    ]
    bundle.add(
        "payroll/v1/getBatchListByDate",
        "payroll/v1/getBatchListByDate",
        {"clientId": c, "startDate": "2026-01-01", "endDate": "2026-12-31", "dateType": "PAY"},
        _envelope(batchList=batches),
    )


def _client_202(bundle: FixtureBundle, staff: list[Person], rng: random.Random) -> None:
    c = "202"
    (omar,) = staff
    bundle.add(
        "clientMaster/v1/getClientMaster",
        "clientMaster/v1/getClientMaster",
        {"clientId": c},
        _client_master(c, "Harborview Logistics", "ASO", "202", [], ""),
    )
    bundle.add(
        "clientMaster/v1/getClientCodes",
        "clientMaster/v1/getClientCodes",
        {"clientId": c, "options": "all"},
        _client_codes(c),
    )
    bundle.add(
        "clientMaster/v1/getAllPrismClientContacts",
        "clientMaster/v1/getAllPrismClientContacts",
        {"clientId": c},
        _company_contacts(live_key=False),
    )
    bundle.add(
        "benefits/v1/getRetirementLoans",
        "benefits/v1/getRetirementLoans",
        {"clientId": c},
        _envelope(retirementLoan=[]),
    )
    bundle.add(
        "employee/v1/getEmployee",
        "employee/v1/getEmployee",
        {"clientId": c, "employeeId": [omar.id], "options": "Person,Client,Compensation"},
        _envelope(employee=[_employee(omar, rng, {"employerIds": ["202"]})]),
    )
    _employee_setup(bundle, c, omar)
    bw = ("BW", "2026-09-14", "2026-09-27")
    batch = _batch(
        bundle,
        c,
        "40101",
        "2026-10-02",
        "R",
        "COMP",
        [bw],
        [
            _voucher("078001", "40101", "R", omar, "2026-10-02", bw[1:], [Line("REG", D("80"), D("28.00"))], [], []),
        ],
    )
    bundle.add(
        "payroll/v1/getBatchListByDate",
        "payroll/v1/getBatchListByDate",
        {"clientId": c, "startDate": "2026-01-01", "endDate": "2026-12-31", "dateType": "PAY"},
        _envelope(batchList=[batch]),
    )
