"""Missing is never zero (A-73).

For every number (sent as a number or as text) and yes/no in the synthetic scenarios, normalizing with the
field deleted must give a
different output from normalizing with it set to 0 or false: otherwise "the provider didn't say" and "the
provider said zero" have become the same thing. Where the two may agree, a reviewed reason below says
why. A new field where they agree fails this test until someone keeps them apart or writes the reason
down, and a reason that no longer applies fails it too.
"""

import copy
import re
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.bundle import Bundle
from normalization.providers import PROVIDERS, normalize

ROOT = Path(__file__).resolve().parents[1]
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

ID = "an ID: 0 is never a real one, and the record takes its ID from the request path or another field"
PAGING = "paging metadata about the response, not data"
LOOKUP = "a row of a code table, read by code or name; not a record of its own"
SECOND = "the second source of an election also in getDeductions: repeating or leaving out a value is no conflict"
DETAIL = "a list row whose detail this scenario also fetched, which replaces it (list-only rows: tested below)"
CONTACT_DEFAULT = "documented with a default of false (#/schemas/124), so a missing role flag is a false one (A-77)"
ENVELOPE = 'the response envelope\'s status, not data: "0" and none both mean no error was reported (A-70)'
ECHO = "an echo of the request's own clientId; records take their client from the request"
NOT_KEPT = "identity documents are never kept (model §9), so nothing about them reaches the output"
# PrismHR endpoints whose responses carry the errorCode envelope in the synthetic scenario.
ENVELOPED = (
    "benefits/v1/getActiveBenefitPlans",
    "benefits/v1/getDependents",
    "benefits/v1/getRetirementLoans",
    "clientMaster/v1/getAllPrismClientContacts",
    "clientMaster/v1/getClientCodes",
    "clientMaster/v1/getClientMaster",
    "clientMaster/v1/getPayrollSchedule",
    "deductions/v1/getDeductions",
    "deductions/v1/getEmployeeLoans",
    "deductions/v1/getVoluntaryRecurringDeductions",
    "employee/v1/checkForGarnishments",
    "employee/v1/getEmployee",
    "employee/v1/getEmployeeList",
    "employee/v1/getHistory",
    "employee/v1/getPayRateHistory",
    "employee/v1/getScheduledDeductions",
    "payroll/v1/getBatchInfo",
    "payroll/v1/getBatchListByDate",
    "payroll/v1/getPayrollVoucherForBatch",
    "payroll/v1/getScheduledPayments",
)

AGREE = {
    "prismhr": {
        ("clientMaster/v1/getClientCodes", "clientCodes.statusCode[].obsolete"): LOOKUP,
        ("clientMaster/v1/getClientCodes", "clientCodes.relationCodes[].obsolete"): LOOKUP,
        ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction.deduction[].usePercent"): SECOND,
        ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction.deduction[].trackArrears"): SECOND,
        ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction.deduction[].mandatory"): SECOND,
        ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction.deduction[].limit"): SECOND,
        ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction.deduction[].maximum"): SECOND,
        ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction.deduction[].matchAmount"): SECOND,
        ("payroll/v1/getPayrollVoucherForBatch", "total"): PAGING,
        ("payroll/v1/getPayrollVoucherForBatch", "startpage"): PAGING,
        ("payroll/v1/getPayrollVoucherForBatch", "count"): PAGING,
        **{(endpoint, "errorCode"): ENVELOPE for endpoint in ENVELOPED},
        ("benefits/v1/getDependents", "clientId"): ECHO,
        ("clientMaster/v1/getClientCodes", "clientCodes.clientId"): ECHO,
        ("deductions/v1/getEmployeeLoans", "clientId"): ECHO,
        ("employee/v1/getPayRateHistory", "payRateHistory.clientId"): ECHO,
        ("employee/v1/getScheduledDeductions", "clientId"): ECHO,
        ("payroll/v1/getScheduledPayments", "clientId"): ECHO,
    },
    "isolved": {
        ("api/lookup/Frequencies", "[].id"): "frequencies are matched by description, never by ID (A-27)",
        ("api/clients/{client}", "id"): ID,
        ("api/clients/{client}/payItems", "[].id"): LOOKUP,
        ("api/clients/{client}/payItems", "[].isInactive"): LOOKUP,
        ("api/clients/{client}/payItems", "[].hasDecliningBalance"): LOOKUP,
        ("api/clients/{client}/payItems", "[].sequenceNumber"): LOOKUP,
        ("api/clients/{client}/legals/{legal}", "client.id"): ID,
        ("api/clients/{client}/legals/{legal}/employees/{id}", "id"): ID,
        ("api/clients/{client}/legals/{legal}/employees/{id}/statuses", "[].isImpliedStatus"): (
            "only a status the flag marks as implied is mapped (A-48); without it the status is UNMAPPED, "
            "which already says unknown"
        ),
        ("api/clients/{client}/legals/{legal}/employees/{id}/payItems", "[].id"): ID,
        ("api/clients/{client}/legals/{legal}/employees/{id}/payItems", "[].employeeId"): ID,
        ("api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory/{id}", "runNumber"): (
            "a run number only links checks to runs (A-40); 0 matches no check, as a missing one doesn't"
        ),
        ("api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory", "[].runNumber"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].checkNumber"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].checkSequence"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].payrollRunNumber"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].employeeId"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].grossWages"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].grossPay"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].netPay"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].checkAmount"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "results[].directDepositAmount"): DETAIL,
        ("api/clients/{client}/legals/{legal}/checks", "totalItems"): PAGING,
        ("api/clients/{client}/legals/{legal}/checks", "totalPages"): PAGING,
        ("api/clients/{client}/legals/{legal}/checks", "results[].employeeNumber"): DETAIL,
        ("api/clients/{client}/legals/{legal}/employees/{id}", "i9Documents.documentA.documentCode"): NOT_KEPT,
        ("api/clients/{client}/legals/{legal}/employees/{id}/payItems", "[].employeeNumber"): (
            "the employee's own number, repeated on each of their pay items; the employee record has it"
        ),
        ("api/lookup/citizenships", "[].id"): "citizenships are matched by description, never by ID",
        ("api/system/payTypes", "[].id"): LOOKUP,
        ("api/system/payTypes", "[].description"): LOOKUP,
    },
    "ukg-ready": {
        ("rest/v2/companies/{company}/lookup/pay-types", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/employee-types", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/jobs", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/jobs", "items[].visible"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/payroll-types", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/pay-statement-types", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/earning-codes", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/lookup/deduction-codes", "items[].id"): LOOKUP,
        ("rest/v2/companies/{company}/employees", "employees[].id"): DETAIL,
        ("rest/v2/companies/{company}/employees", "employees[].employee_id"): DETAIL,
        ("rest/v2/companies/{company}/employees/{id}", "id"): ID,
        ("rest/v2/companies/{company}/employees/{id}/compensation/history", "compensations[].employee.account_id"): ID,
        ("rest/v2/companies/{company}/employees/{id}/direct-deposits", "deposits[].id"): ID,
        ("rest/v2/companies/{company}/employees/{id}/deductions", "deductions[].sequence"): DETAIL,
        ("rest/v2/companies/{company}/employees/{id}/deductions/{id}", "id"): ID,
        ("rest/v2/companies/{company}/employees/{id}", "managers[].index"): (
            "only orders the managers; a missing index sorts as 0"
        ),
        ("rest/v2/companies/{company}/payrolls", "payrolls[].type.id"): DETAIL,
        ("rest/v2/companies/{company}/payrolls", "payrolls[].ein.id"): DETAIL,
        ("rest/v2/companies/{company}/payrolls", "payrolls[].billable"): DETAIL,
        ("rest/v2/companies/{company}/payrolls/{id}", "id"): ID,
        ("rest/v2/companies/{company}/payrolls/{id}/pay-statements", "pay_statements[].employee.account_id"): DETAIL,
        ("rest/v2/companies/{company}/payrolls/{id}/pay-statements", "pay_statements[].type.id"): DETAIL,
        ("rest/v2/companies/{company}/payrolls/{id}/pay-statements/{id}", "id"): ID,
        ("rest/v2/companies/{company}/employees/{id}/contacts", "contacts[].employee.account_id"): ID,
        ("rest/v2/companies/{company}/employees/{id}/contacts", "contacts[].emergency"): CONTACT_DEFAULT,
        ("rest/v2/companies/{company}/employees/{id}/contacts", "contacts[].dependent"): CONTACT_DEFAULT,
        ("rest/v2/companies/{company}/employees/{id}/contacts", "contacts[].beneficiary"): CONTACT_DEFAULT,
    },
}


def _leaves(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _leaves(value, (*path, i))
    else:
        yield path, node


def _at(node, path):
    for part in path:
        node = node[part]
    return node


def _fold(path) -> str:
    return "".join("[]" if isinstance(p, int) else (f".{p}" if i else str(p)) for i, p in enumerate(path))


def agreeing_fields(provider: str) -> set[tuple[str, str]]:
    """(endpoint, field) where a deleted value and a 0/false one give the same output; first occurrence of each."""
    base = Bundle.load(ROOT / f"fixtures/{provider}/brightside")
    tried, agree = set(), set()
    for i, capture in enumerate(base.captures):
        if capture.status != 200:
            continue
        for path, value in _leaves(capture.body):
            if isinstance(value, bool):
                falsy: object = False
            elif isinstance(value, (int, float, Decimal)):
                falsy = 0
            elif isinstance(value, str) and NUMBER.fullmatch(value):
                falsy = "0"  # PrismHR sends most numbers as text
            else:
                continue
            key = (capture.endpoint, _fold(path))
            if not path or isinstance(path[-1], int) or key in tried:
                continue
            tried.add(key)
            deleted, zeroed = copy.deepcopy(base), copy.deepcopy(base)
            del _at(deleted.captures[i].body, path[:-1])[path[-1]]
            _at(zeroed.captures[i].body, path[:-1])[path[-1]] = falsy
            if normalize(deleted).to_json() == normalize(zeroed).to_json():
                agree.add(key)
    return agree


@pytest.mark.parametrize("provider", PROVIDERS)
def test_missing_and_zero_stay_apart_unless_a_reviewed_reason_says_why(provider):
    agree, reviewed = agreeing_fields(provider), set(AGREE[provider])
    assert not agree - reviewed, f"missing and zero agree here, with no reason given: {sorted(agree - reviewed)}"
    assert not reviewed - agree, f"these now stay apart; remove their reasons: {sorted(reviewed - agree)}"


def test_a_list_only_check_keeps_zero_apart_from_missing():
    # 70009 is listed but its detail wasn't fetched, so its list row is all there is.
    def net(value):
        b = Bundle.load(ROOT / "fixtures/isolved/brightside")
        row = next(
            r
            for c in b.captures
            if c.endpoint == "api/clients/{client}/legals/{legal}/checks"
            for r in c.body["results"]
            if r["id"] == 70009
        )
        if value is None:
            del row["netPay"]
        else:
            row["netPay"] = value
        return next(s for s in normalize(b).records["pay_statements"] if s.id.endswith(":70009")).totals.net_pay

    assert net(None) is None and net(0).amount == 0


# ---------------------------------------------------------------- the fixes this found (A-73)


def fixture(provider: str) -> Bundle:
    return Bundle.load(ROOT / f"fixtures/{provider}/brightside")


def record(out, kind: str, suffix: str):
    return next(r for r in out.records[kind] if r.id.endswith(suffix))


def codes(r) -> set[str]:
    return {d.code for d in r.diagnostics}


def checks(statement) -> dict[str, str]:
    return {c.rule: c.result.value for c in statement.checks}


def isolved_check(b: Bundle, check_id: str) -> dict:
    return next(c for c in b.captures if c.path.endswith(f"/checks/{check_id}")).body


def test_an_isolved_tax_without_its_employee_flag_has_an_unknown_payer():
    b = fixture("isolved")
    del isolved_check(b, "70001")["taxes"][0]["isEmployeeTax"]
    statement = record(normalize(b), "pay_statements", ":70001")
    assert statement.taxes[0].paid_by.value == "UNMAPPED"  # not quietly the employer's
    assert "FLAG_MISSING" in codes(statement)
    assert checks(statement)["gross pay - employee taxes - deductions = net"] == "not_applicable"


def test_an_isolved_line_without_its_memo_flag_may_or_may_not_count_in_gross():
    b = fixture("isolved")
    del isolved_check(b, "70001")["earnings"][0]["isMemoEarning"]
    statement = record(normalize(b), "pay_statements", ":70001")
    assert statement.earnings[0].in_gross is None and "FLAG_MISSING" in codes(statement)
    assert checks(statement)["gross wages = sum of earning lines counted in gross"] == "not_applicable"


def _prism_deduction(b: Bundle) -> dict:
    return next(
        r
        for c in b.captures
        if c.endpoint == "deductions/v1/getDeductions"
        for r in c.body["employeeDeductions"]["deduction"]
        if r.get("amount")
    )


def test_a_prism_deduction_without_its_percent_flag_uses_the_documented_default():
    # usePercent: "Valid values are T (True) or F (False). The default is False." (EmployeeDeductions-Deduction)
    b = fixture("prismhr")
    row = _prism_deduction(b)
    del row["usePercent"]
    election = next(
        e
        for e in normalize(b).records["deduction_elections"]
        if f":{row['deductionCode']}:" in e.id and "DOCUMENTED_DEFAULT" in codes(e)
    )
    assert election.calculation.amount is not None and election.calculation.percent is None  # dollars, as documented


def test_a_prism_deduction_percent_flag_that_isnt_a_yes_no_leaves_the_amount_raw():
    b = fixture("prismhr")
    row = _prism_deduction(b)
    row["usePercent"] = "maybe"
    election = next(
        e
        for e in normalize(b).records["deduction_elections"]
        if f":{row['deductionCode']}:" in e.id and "FLAG_MISSING" in codes(e)
    )
    calculation = election.calculation
    assert calculation.amount is None and calculation.percent is None  # neither dollars nor percent is guessed
    assert any(k.endswith(".amount") for k in election.provider_extensions)  # the amount is kept as sent


def test_an_isolved_rate_of_zero_is_no_rate_and_stays_as_sent():
    b = fixture("isolved")
    employee = next(c for c in b.captures if c.path.endswith("/employees/9001")).body
    employee["hourlyRate"], employee["perPaySalary"] = 0, 0
    found = record(normalize(b), "employees", ":9001")
    assert found.compensation.rates == [] and "NO_PAY_RATE" in codes(found)
    assert {found.provider_extensions["hourlyRate"], found.provider_extensions["perPaySalary"]} == {0}


def test_history_fields_that_are_not_mapped_are_kept():
    isolved = record(normalize(fixture("isolved")), "employees", ":9001")
    assert isolved.provider_extensions["salaries[0].frequency.description"] == "Bi-Weekly"
    prism = record(normalize(fixture("prismhr")), "employees", ":201:E1001")
    assert any(k.startswith("payRateHistory.payRate[") for k in prism.provider_extensions)
