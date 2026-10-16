"""Every read endpoint the providers document, and what this tool does with it (A-74).

The three specs document 855 read (GET) endpoints. Each one is either fetched (it is in scope.py's
allowlist) or has a recorded reason it isn't. An endpoint that holds the five data types (company,
employee, direct deposit, deduction, payroll) carries its own decision in DECISIONS; the rest are
grouped by topic, each topic with one reason. tests/test_endpoint_inventory.py fails when a documented
read endpoint in the five data types has neither, so a skipped endpoint can't go unnoticed again.

Read offline, from contracts/ only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from .scope import ISOLVED_TEMPLATES, PRISM_EMPLOYER_OPERATION, PRISM_OPERATIONS, UKG_TEMPLATES

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
PROVIDERS = ("prismhr", "isolved", "ukg-ready")

# Why an endpoint isn't fetched.
FETCHED = "FETCHED"
SAME = "SAME"  # returns records already fetched: another filter, a bulk or single form, an older version, a subset
WORKFLOW = "WORKFLOW"  # a processing step, status, preview or generated document, not a stored record
CONFIG = "CONFIG"  # company or system configuration, not records of the five data types
UNREACHABLE = "UNREACHABLE"  # needs an ID or scope that /signin doesn't give
EMPTY_LIVE = "EMPTY_LIVE"  # asked live on 2026-10-14: no data for any demo employee or company
REFUSED_LIVE = "REFUSED_LIVE"  # asked live on 2026-10-14: refused for the demo API user
OUT = "OUT"  # a topic outside the five data types
PRIVATE = "PRIVATE"  # returns personal data the model deliberately doesn't hold (full SSNs): never called (A-23)
UNDECIDED = "UNDECIDED"  # holds one of the five data types, with no decision recorded: the test fails

TOPICS = {
    1: "employee",
    2: "direct deposits",
    3: "deductions",
    4: "payroll",
    5: "company setup and code lists",
    6: "benefits",
    7: "time off and timekeeping",
    8: "tax setup and year-end forms",
    9: "hiring, onboarding, documents and skills",
    10: "billing, accounting and banking",
    11: "logins, security and system plumbing",
}
# Topics 1-4 need a decision per endpoint; the others share one.
TOPIC_DECISIONS = {
    5: (CONFIG, "company or system setup, or a code list the records don't need"),
    6: (OUT, "benefit plans and enrollment are not one of the five data types"),
    7: (OUT, "time off and timekeeping are not one of the five data types"),
    8: (OUT, "tax setup and year-end forms: tax setup that arrives with the employee is kept (A-34)"),
    9: (OUT, "hiring, onboarding, documents, skills and training are not one of the five data types"),
    10: (OUT, "the provider's own billing, accounting and banking"),
    11: (OUT, "logins, security, notifications and system plumbing"),
}

P, ISO, U = "prismhr", "isolved", "ukg-ready"
IL = "/api/clients/{clientId}/legals/{legalId}"
IE = IL + "/employees/{employeeId}"
UK = "/v2/companies/(cid)"

DECISIONS: dict[tuple[str, str], tuple[str, str]] = {
    # ------------------------------------------------------------------ PrismHR: employee
    (P, "/clientMaster/v1/getEmployeeListByEntity"): (
        SAME,
        "the employee list, filtered by division, location or project",
    ),
    (P, "/clientMaster/v1/getEmployeesInPayGroup"): (SAME, "the employee list, filtered by pay group"),
    (P, "/employee/v1/getAddressInfo"): (
        SAME,
        "home, W-2 and alternate mailing addresses all come with getEmployee; this adds only an "
        "international-address flag",
    ),
    (P, "/employee/v1/getEmployeeEvents"): (SAME, "getEmployee's EmployeeEvents option returns the same model"),
    (P, "/employee/v1/getEmployeeSSNList"): (
        PRIVATE,
        "employee IDs with full SSNs. getEmployee masks the whole SSN, so this is the only source of its last 4, "
        "but the model keeps no more than 4 digits, and pulling full SSNs from a live system to keep 4 isn't "
        "worth the exposure (A-23, A-50)",
    ),
    (P, "/employee/v1/getEmployersInfo"): (
        SAME,
        "the employee's employer, also in getEmployee's person.employerId (A-78); the same for all 35 employees asked",
    ),
    (P, "/employee/v1/getFutureEeChange"): (UNREACHABLE, "needs an eventObjectId from the subscription event stream"),
    (P, "/employee/v1/getStatusHistoryForAdjustment"): (
        SAME,
        "status and type history, also in getHistory; hire dates, also in getEmployee",
    ),
    (P, "/employee/v1/getTerminationDateRange"): (WORKFLOW, "the date range a termination may be entered for"),
    (P, "/humanResources/v1/getStaffingPlacement"): (SAME, "one placement of getStaffingPlacementList"),
    (P, "/humanResources/v1/getStaffingPlacementList"): (
        EMPTY_LIVE,
        'staffing placements: "No placement records found" for all 35 employees asked',
    ),
    (P, "/payroll/v1/getEmployeeOverrideRates"): (
        EMPTY_LIVE,
        "pay-code override rates: none for the 35 employees asked",
    ),
    (P, "/employee/v1/getPositionRate"): (EMPTY_LIVE, "position rates: none for the 35 employees asked"),
    (P, "/codeFiles/v1/getUserDefinedFields"): (
        EMPTY_LIVE,
        "customer-defined fields: definitions, but no values for any employee or client asked",
    ),
    (P, "/signOn/v1/getEmployeeImage"): (UNREACHABLE, "takes a PrismHR user ID, not a client; and it is a photo"),
    # ------------------------------------------------------------------ PrismHR: deposits and deductions
    (P, "/employee/v1/getPayCardEmployees"): (SAME, "a reverse lookup of employees by routing number"),
    (P, "/deductions/v1/getDeductionArrears"): (
        EMPTY_LIVE,
        'deduction arrears: "No employee deduction arrears found" for all 35 employees asked; vouchers carry '
        "arrears taken and added",
    ),
    (P, "/deductions/v1/getGarnishmentPaymentHistory"): (
        EMPTY_LIVE,
        '"No garnishment records exist" for all 35 employees asked',
    ),
    (P, "/employee/v1/getACHDeductions"): (
        EMPTY_LIVE,
        "voluntary deductions paid to a bank account: none for the 35 employees asked (a custom feature)",
    ),
    (P, "/employee/v1/getGarnishmentEmployee"): (SAME, "a reverse lookup of the employee by garnishment ID"),
    # ------------------------------------------------------------------ PrismHR: payroll
    (P, "/clientMaster/v1/getPayDayRules"): (CONFIG, "how pay dates move for weekends and holidays"),
    (P, "/clientMaster/v1/getPayGroupDetails"): (
        CONFIG,
        "pay group setup; the groups and their frequencies come from getPayrollSchedule",
    ),
    (P, "/payroll/v1/checkInitializationStatus"): (WORKFLOW, "the progress of a batch initialization"),
    (P, "/payroll/v1/getApprovalSummary"): (WORKFLOW, "the summary of a batch awaiting approval"),
    (P, "/payroll/v1/getBatchListForApproval"): (WORKFLOW, "batches awaiting approval"),
    (P, "/payroll/v1/getBatchListForInitialization"): (WORKFLOW, "batches awaiting initialization"),
    (P, "/payroll/v1/getBatchPayments"): (
        WORKFLOW,
        "payments queued for a batch not yet run; once paid, they are on its vouchers",
    ),
    (P, "/payroll/v1/getBatchStatus"): (SAME, "batch statuses, also in getBatchListByDate and getBatchInfo"),
    (P, "/payroll/v1/getBulkYearToDateValues"): (SAME, "the asynchronous bulk form of getYearToDateValues"),
    (P, "/payroll/v1/getClientsWithVouchers"): (UNREACHABLE, "takes no clientId and lists every client"),
    (P, "/payroll/v1/getEmployee401KContributionsByDate"): (
        SAME,
        "per-voucher retirement amounts, also on vouchers fetched with the Retirement option; the census "
        "fields repeat the employee",
    ),
    (P, "/payroll/v1/getEmployeeForBatch"): (SAME, "employee IDs in a batch; its vouchers name them"),
    (P, "/payroll/v1/getEmployeePayrollSummary"): (SAME, "a voucher-by-voucher summary of the vouchers"),
    (P, "/payroll/v1/getManualChecks"): (
        SAME,
        "posted manual checks are vouchers (batch type M); unposted ones are pending entries",
    ),
    (P, "/payroll/v1/getPayrollApproval"): (WORKFLOW, "the approval state of a batch"),
    (P, "/payroll/v1/getPayrollBatchWithOptions"): (CONFIG, "batch processing options"),
    (P, "/payroll/v1/getPayrollNotes"): (WORKFLOW, "operator notes, not tied to a run"),
    (P, "/payroll/v1/getPayrollSchedule"): (UNREACHABLE, "a system-level schedule definition; takes no clientId"),
    (P, "/payroll/v1/getPayrollScheduleCodes"): (UNREACHABLE, "a system-level code list; takes no clientId"),
    (P, "/payroll/v1/getPayrollSummary"): (SAME, "totals summed from the vouchers"),
    (P, "/payroll/v1/getPayrollVoucherById"): (SAME, "one voucher, in the same model as getPayrollVoucherForBatch"),
    (P, "/payroll/v1/getPayrollVouchers"): (SAME, "vouchers by pay-date range, in the same model"),
    (P, "/payroll/v1/getPayrollVouchersForEmployee"): (SAME, "vouchers by employee, in the same model"),
    (P, "/payroll/v1/getProcessSchedule"): (UNREACHABLE, "a system-level processing schedule; takes no clientId"),
    (P, "/payroll/v1/getProcessScheduleCodes"): (UNREACHABLE, "a system-level code list; takes no clientId"),
    (P, "/payroll/v1/getRetirementAdjVoucherListByDate"): (
        WORKFLOW,
        "an asynchronous list of retirement-adjustment voucher IDs, not vouchers",
    ),
    (P, "/payroll/v1/getYearToDateValues"): (
        SAME,
        "year-, quarter- and month-to-date sums of the employee's vouchers; asked live, 34 of 35 employees "
        "had none this year",
    ),
    (P, "/payroll/v1/payGroupScheduleReport"): (WORKFLOW, "an asynchronous pay-calendar report"),
    (P, "/payroll/v1/reprintCheckStub"): (WORKFLOW, "generates a PDF"),
    (P, "/timesheet/v1/getBatchStatus"): (WORKFLOW, "the timesheet entry status of a batch"),
    # ------------------------------------------------------------------ PrismHR: other topics touching the five
    (P, "/benefits/v1/getBenefitPlans"): (
        OUT,
        "plans in every status, which getActiveBenefitPlans isn't: asked live on 2026-10-16, 794 of its 1,002 "
        "plans were 'eligible, not enrolled' and 32 terminated or waived. Benefit enrollment and its history are "
        "outside the five data types; the active plans, with their current employee contributions, are fetched",
    ),
    (P, "/codeFiles/v1/getDeductionCodeDetails"): (
        SAME,
        "getClientCodes already returns each deduction code's classification; this one takes no clientId",
    ),
    (P, "/codeFiles/v1/getPaycodeDetails"): (
        SAME,
        "getClientCodes already returns each pay code's classification; this one takes no clientId",
    ),
    # ------------------------------------------------------------------ isolved: employee
    (ISO, IE + "/contacts/{id}"): (SAME, "one contact, in the same model as /contacts"),
    (ISO, "/api/corestream/clients/{clientId}/legals/{legalId}/employees/{employeeId}"): (
        SAME,
        "a Corestream subset of the employee record; Corestream is refused live",
    ),
    (ISO, "/api/corestream/clients/{clientId}/legals/{legalId}/employees"): (
        SAME,
        "a Corestream subset of the employee list; Corestream is refused live",
    ),
    (ISO, IE + "/disabilityStatus"): (
        SAME,
        "disabled, its effective date and accommodation flag, also in the employee record; the 2 of 45 "
        "employees with an answer repeat it",
    ),
    (ISO, IE + "/eeoStatus"): (SAME, "gender and ethnicity, also in the employee record"),
    (ISO, "/api/clients/{clientId}/employees"): (SAME, "the client-wide employee list, in the same model"),
    (ISO, "/api/clients/{clientId}/employeesWithSSN"): (
        PRIVATE,
        "the client-wide employee list with full SSNs; the last 4 come from checks instead (A-23, A-50)",
    ),
    (ISO, IL + "/employeesWithSSN"): (
        PRIVATE,
        "the employee list with full SSNs; the last 4 come from checks instead (A-23, A-50)",
    ),
    (ISO, IL + "/employeesMinimal"): (SAME, "a minimal employee list"),
    (ISO, "/api/clients/{clientId}/employeesMinimal"): (SAME, "a minimal employee list"),
    (ISO, IL + "/employeesWithSSN/{id}"): (
        PRIVATE,
        "the employee record with its full SSN; the last 4 come from checks instead (A-23, A-50)",
    ),
    (ISO, IE + "/employments/{employmentId}/categories"): (
        SAME,
        "the categories of one employment; /categories lists all",
    ),
    (ISO, IE + "/employment/{employmentId}/statuses"): (SAME, "the statuses of one employment, as in /statuses"),
    (ISO, "/api/peos/{peoId}/employees/{id}"): (UNREACHABLE, "PEO-level: /signin gives no PEO ID"),
    (ISO, "/api/peos/{peoId}/employees"): (UNREACHABLE, "PEO-level: /signin gives no PEO ID"),
    (ISO, IL + "/employees/{id}/nameAddress"): (SAME, "part of the employee record (nameAddress)"),
    (ISO, IL + "/employees/{id}/personal"): (SAME, "part of the employee record (personal)"),
    (ISO, IE + "/salaries/{id}"): (SAME, "one salary row, in the same model as /salaries"),
    # ------------------------------------------------------------------ isolved: deposits and deductions
    (ISO, "/api/clients/{clientId}/directdeposits"): (SAME, "a reverse lookup by routing number"),
    (ISO, IL + "/directdeposits"): (SAME, "a reverse lookup by routing number"),
    (ISO, IE + "/directdeposits/{id}"): (SAME, "one deposit, in the same model"),
    (ISO, IE + "/garnishments/{id}"): (SAME, "one garnishment, in the same model"),
    (ISO, IL + "/payItems"): (SAME, "every employee's pay items in one list, in the same model"),
    (ISO, IL + "/payGroups/{payGroupId}/payItems"): (SAME, "pay items by pay group, in the same model"),
    (ISO, "/api/peos/{peoId}/employees/{employeeId}/payItems"): (UNREACHABLE, "PEO-level: /signin gives no PEO ID"),
    # ------------------------------------------------------------------ isolved: payroll
    (ISO, IE + "/checks/years"): (SAME, "the years that have checks"),
    (ISO, IL + "/payGroups/{payGroupId}/checks"): (SAME, "checks by pay group, in the same model as /checks"),
    (ISO, IE + "/checks"): (
        SAME,
        "one employee's checks, in the same model as the legal-level /checks the crawl pages through",
    ),
    (ISO, IE + "/checks/{id}/checkStubReport"): (WORKFLOW, "starts a report job"),
    (ISO, IE + "/checks/preview"): (WORKFLOW, "a preview of a future check"),
    (ISO, "/api/corestream/clients/{clientId}/legals/{legalId}/legalAndPayGroupsWithPayrollSchedules"): (
        REFUSED_LIVE,
        'payroll schedule dates: "Authorization has been denied", as for the other Corestream endpoints',
    ),
    (ISO, IE + "/payroll/accumulations"): (
        REFUSED_LIVE,
        'period-, quarter- and year-to-date totals: "Authorization has been denied", as for /payroll',
    ),
    (ISO, "/api/clients/{clientId}/legals/{LegalId}/payGroups/{payGroupId}/payrolls"): (
        CONFIG,
        "the pay group's payroll calendar; runs come from payrollRunHistory",
    ),
    (ISO, IL + "/paygroupId/{paygroupId}/payrollRunHistory/byDate"): (SAME, "run history by date, in the same model"),
    # ------------------------------------------------------------------ isolved: other topics touching the five
    (ISO, IE + "/benefits"): (
        EMPTY_LIVE,
        'benefit elections with per-pay deduction amounts: "No employee benefits found." for all 45 employees',
    ),
    (ISO, "/api/clients/{clientId}/organizations"): (
        SAME,
        "organization titles and values already come in each employee record (A-75)",
    ),
    (ISO, "/api/lookup/militaryStatus"): (CONFIG, "military status labels; veteran status values aren't among them"),
    (ISO, IL + "/workLocations"): (CONFIG, "work location setup; each employee carries its own work location"),
    (ISO, "/api/clients/{clientId}/miscEmployeeFields"): (CONFIG, "definitions of custom employee fields"),
    # ------------------------------------------------------------------ UKG: employee
    (U, "/v1/employees/"): (SAME, "the v1 version of the employee list"),
    (U, "/v1/employees/(account_id)"): (SAME, "the v1 version of the employee record"),
    (U, UK + "/compensation/additional/(acid)"): (SAME, "one additional compensation record"),
    (U, UK + "/compensation/additional"): (SAME, "every subordinate's additional compensation in one list"),
    (U, UK + "/compensation/history/(id)"): (SAME, "one base compensation entry"),
    (U, UK + "/compensation/history"): (SAME, "every subordinate's base compensation in one list"),
    (U, UK + "/compensation/total"): (SAME, "every subordinate's total compensation in one list"),
    (U, UK + "/contacts/(id)"): (SAME, "one contact"),
    (U, UK + "/primary-assignment"): (SAME, "primary position assignments, as in position/assignments"),
    (U, UK + "/employees/changed"): (SAME, "a change feed of employee records"),
    (U, UK + "/employees/(aid)/compensation/additional"): (
        EMPTY_LIVE,
        "additional compensation: none for the 25 employees asked",
    ),
    (U, UK + "/employees/(aid)/compensation/total"): (
        SAME,
        "the hourly total UKG computes from base and additional compensation; base comes from "
        "compensation/history and additional is empty",
    ),
    (U, UK + "/employees/(aid)/currency"): (CONFIG, "the employee's currency setting"),
    (U, UK + "/employees/(aid)/hr-custom-fields"): (
        EMPTY_LIVE,
        "custom HR fields: no values for the 25 employees asked",
    ),
    (U, UK + "/employees/(aid)/managed-cost-centers/(mccid)"): (OUT, "a manager's permissions over cost centers"),
    (U, UK + "/employees/(aid)/managed-cost-centers"): (OUT, "a manager's permissions over cost centers"),
    (U, UK + "/employees/(aid)/profiles"): (CONFIG, "the configuration profiles assigned to the employee"),
    (U, UK + "/position/position-assignments/changed"): (SAME, "a change feed of position assignments"),
    (U, UK + "/position/assignments"): (SAME, "every employee's position assignments in one list"),
    (U, UK + "/employees/info"): (SAME, "employees by pay group"),
    # ------------------------------------------------------------------ UKG: deposits and payroll
    (U, UK + "/direct-deposits/(id)"): (SAME, "one deposit (deprecated)"),
    (U, UK + "/external-pay-statements/(pst_id)"): (
        UNREACHABLE,
        "needs a statement ID no listing gives; returns document links",
    ),
    (U, UK + "/pay-periods/(pay_period_id)/action/process-records/(job_id)"): (WORKFLOW, "a processing job's status"),
    (U, UK + "/pay-periods/(pay_period_id)/snapshots"): (WORKFLOW, "snapshots for a payroll export"),
    (U, UK + "/pay-periods/(pay_period_id)"): (SAME, "one pay period"),
    (U, UK + "/pay-periods"): (
        CONFIG,
        "the pay-period calendar and its processing state; each payroll carries its own period",
    ),
    (U, UK + "/payrolls/(id)/batches"): (WORKFLOW, "how a payroll's entries were batched for processing"),
    # ------------------------------------------------------------------ UKG: other topics touching the five
    (U, UK + "/config/cost-centers/lists"): (CONFIG, "lists that group cost centers; a tree's name is its root's"),
    (U, UK + "/lookup/additional-compensation-types"): (CONFIG, "labels for additional compensation, which is empty"),
    # ------------------------------------------------------------------ flagged by the content check
    # Their responses use the vocabulary of a core topic (core_scores), so each is decided on its own, from its
    # spec, instead of by its topic rule (A-74).
    (P, "/applicant/v1/getJobApplicants"): (OUT, "job applicants, who aren't employees yet: hiring"),
    (P, "/benefits/v1/get401KMatchRules"): (CONFIG, "the client's 401(k) matching rules: plan setup, not an election"),
    (P, "/benefits/v1/getBenefitRule"): (CONFIG, "a benefit rule's setup, not an employee's election"),
    (P, "/benefits/v1/getClientBenefitPlanSetupDetails"): (CONFIG, "the client's benefit plan setup"),
    (P, "/benefits/v1/getEmployeePremium"): (
        WORKFLOW,
        "calculates premium and billing rates for one employee and plan on request; not a stored record",
    ),
    (P, "/benefits/v1/getEmployeeRetirementSummary"): (
        SAME,
        "each voucher's retirement amounts for a plan year, as the fetched vouchers' retirement breakdown",
    ),
    (P, "/benefits/v1/getGroupBenefitPlan"): (CONFIG, "a benefit group's plan setup"),
    (P, "/benefits/v1/getGroupBenefitRates"): (CONFIG, "a plan's premium and billing rate tables"),
    (P, "/benefits/v1/getPtoPlanDetails"): (OUT, "paid time off plan setup: time off"),
    (P, "/clientMaster/v1/getClientBillingBankAccount"): (OUT, "the bank account the provider bills the client from"),
    (P, "/clientMaster/v1/getClientLocationDetails"): (
        CONFIG,
        "a work location's setup, with its tax rates and the client's own bank and garnishment accounts",
    ),
    (P, "/clientMaster/v2/getClientLocationDetails"): (CONFIG, "a newer form of the location setup above"),
    (P, "/codeFiles/v1/getDivisionCode"): (CONFIG, "the division code table, with general-ledger segments"),
    (P, "/codeFiles/v1/getEeoCodes"): (CONFIG, "EEO code tables, read through the employee's own codes"),
    (P, "/codeFiles/v1/getPositionCode"): (CONFIG, "the position code table, with general-ledger segments"),
    (P, "/employee/v1/getI9Data"): (
        OUT,
        "Form I-9 data: identity documents, which are never kept (model §9); the employee record already has "
        "citizenship status",
    ),
    (P, "/generalLedger/v1/getClientAccountingTemplate"): (OUT, "general-ledger setup: the client's accounting"),
    (P, "/generalLedger/v1/getGLSetup"): (OUT, "general-ledger setup: the client's accounting"),
    (P, "/payroll/v1/getBillingCodeTotalsByPayGroup"): (OUT, "what the provider bills the client: its own billing"),
    (P, "/payroll/v1/getBillingRuleUnbundled"): (OUT, "the provider's billing rules for the client"),
    (P, "/payroll/v1/getBillingVouchers"): (OUT, "the provider's invoices to the client, not employee pay"),
    (P, "/payroll/v1/getBillingVouchersByBatch"): (OUT, "the provider's invoices to the client, by batch"),
    (P, "/timesheet/v1/getTimeSheetData"): (
        OUT,
        "timesheets before payroll: timekeeping; paychecks carry the hours paid",
    ),
    (ISO, IE + "/absences"): (OUT, "absences: time off"),
    (ISO, "/api/clients/{clientId}/ClientShifts/{shiftId}"): (OUT, "shift setup: timekeeping"),
    (ISO, IL + "/bankaccounts"): (OUT, "the legal company's own bank accounts, which fund payroll"),
    (ISO, IL + "/bankaccounts/{bankAccountId}"): (OUT, "one of the legal company's own bank accounts"),
    (ISO, "/api/clients/{clientId}/options"): (
        CONFIG,
        "the client's settings, such as which personal fields are required",
    ),
    (ISO, IE + "/benefitUpdates"): (WORKFLOW, "what the employee may change in their benefits in self-service"),
    (ISO, IE + "/benefits/openEnrollment"): (WORKFLOW, "open enrollment: the benefit election workflow"),
    (ISO, IE + "/benefits/openEnrollment/{enrollmentPeriodId}/costAnalysis"): (
        WORKFLOW,
        "an open-enrollment cost preview",
    ),
    (ISO, IE + "/benefits/openEnrollment/{enrollmentPeriodId}/validationErrors"): (
        WORKFLOW,
        "validation errors of an open-enrollment session",
    ),
    (ISO, IE + "/benefits/openEnrollment/{enrollmentPeriodId}/elections/{benefitTypeId}"): (
        WORKFLOW,
        "the choices offered during open enrollment",
    ),
    (ISO, IE + "/benefits/openEnrollment/{enrollmentPeriodId}/bundleElections/{benefitGroupItemId}"): (
        WORKFLOW,
        "the bundled choices offered during open enrollment",
    ),
    (ISO, "/api/clients/{clientId}/generalledger/detail"): (OUT, "general-ledger postings of payroll: accounting"),
    (ISO, "/api/clients/{clientId}/generalledger/summary"): (OUT, "general-ledger totals of payroll: accounting"),
    (ISO, IL + "/laborGlRules"): (CONFIG, "rules that post labor and garnishments to general-ledger accounts"),
    (ISO, IL + "/laborGlRules/{id}"): (CONFIG, "one labor general-ledger rule"),
    (ISO, "/api/systembankaccounts"): (OUT, "the provider's own bank accounts"),
    (ISO, "/api/systembankaccounts/{systemBankAccountId}"): (OUT, "one of the provider's own bank accounts"),
    (ISO, IE + "/timecardView"): (OUT, "timecards: timekeeping; checks carry the hours paid"),
    (ISO, IE + "/timecardView/{year}/{month}/{day}"): (OUT, "one day's timecard: timekeeping"),
    (ISO, IL + "/scheduleView"): (OUT, "work schedules: timekeeping"),
    (ISO, "/api/clients/{clientId}/timecardVerification/employeeStatusForDate"): (
        OUT,
        "timecard verification status for a date: timekeeping",
    ),
    (U, UK + "/applicants/(account_id)"): (OUT, "a job applicant: hiring"),
    (U, UK + "/benefits/(id)"): (CONFIG, "a company benefit plan's setup; each employee's plans come from /benefits"),
}


@dataclass(frozen=True)
class Endpoint:
    provider: str
    path: str  # as documented
    topic: int
    disposition: str
    reason: str


# ---------------------------------------------------------------------- reading the specs


def _paths(provider: str) -> list[tuple[str, str]]:
    """(documented path, documented group) of every GET operation."""
    if provider == "ukg-ready":
        return _ukg_paths()
    spec = {
        "prismhr": CONTRACTS / "prismhr/openapi/prismhr-2025.09.openapi.json",
        "isolved": CONTRACTS / "isolved/openapi/isolved-v6.swagger.json",
    }[provider]
    document = json.loads(spec.read_text(encoding="utf-8"))
    return [
        (path, (ops["get"].get("tags") or ["?"])[0].strip())
        for path, ops in document["paths"].items()
        if isinstance(ops, dict) and "get" in ops
    ]


class _Nav(HTMLParser):
    """UKG's documentation index: nested resources, each listing the methods it supports."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = False
        self.stack: list[dict] = []
        self.items: list[bool] = []
        self.naming = False
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self.inside = self.inside or a.get("id") == "resourceNav"
        if not self.inside:
            return
        css = a.get("class") or ""
        if tag == "li":
            self.items.append("navMethod" in css)
            if "navMethod" in css:
                self.stack.append({"id": a.get("id"), "name": "", "get": False})
        elif tag == "a" and self.stack and "resourceMenuItem" in css:
            self.naming = True
        elif tag == "a" and self.stack and css.startswith("method ") and a.get("title") == "GET":
            self.stack[-1]["get"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.naming = False
        elif tag == "li" and self.inside and self.items and self.items.pop():
            node = self.stack.pop()
            if node["id"] and node["get"]:
                self.found.append((node["id"].replace("__", "/"), "/".join(n["name"] for n in self.stack)))

    def handle_data(self, data: str) -> None:
        if self.naming and self.stack:
            self.stack[-1]["name"] += data.strip()


def _ukg_paths() -> list[tuple[str, str]]:
    nav = _Nav()
    nav.feed((CONTRACTS / "ukg-ready/reference-docs/index.html").read_text(encoding="utf-8"))
    return nav.found


# ---------------------------------------------------------------------- topics


def _first(rules: list[tuple[str, int]], text: str, default: int) -> int:
    return next((topic for pattern, topic in rules if re.search(pattern, text)), default)


_PRISM_TAG = {
    "applicant": 9, "benefits": 6, "clientMaster": 5, "codeFiles": 5, "deductions": 3, "documentService": 9,
    "employee": 1, "generalLedger": 10, "humanResources": 9, "login": 11, "newHire": 9, "payroll": 4,
    "prismSecurity": 11, "signon": 11, "subscription": 11, "system": 10, "taxRate": 8, "timesheet": 7,
}  # fmt: skip
_PRISM_RULES = [
    (r"benefits/.*(Pto|PTO|PaidTimeOff|Absence)", 7),
    (r"benefits/.*getDependents", 1),
    (r"clientMaster/.*(getBenefitGroup|getRetirementPlanList|getACALargeEmployer)", 6),
    (r"clientMaster/.*(Bill|GL|WCAccrual|WCBilling)", 10),
    (r"clientMaster/.*(getDocExpirations|getOSHA300Astats)", 9),
    (r"clientMaster/.*(getEmployeeListByEntity|getEmployeesInPayGroup)", 1),
    (r"clientMaster/.*(getMessage|getBackupAssignments|getGeoLocations)", 11),
    (r"clientMaster/.*(getPayDayRules|getPayGroupDetails|getPayrollSchedule)", 4),
    (r"clientMaster/.*getSutaRates", 8),
    (r"codeFiles/.*getBillingCode", 10),
    (r"codeFiles/.*getUserDefinedFields", 1),
    (r"employee/.*(checkForGarnishments|getGarnishmentEmployee|getACHDeductions|getScheduledDeductions)", 3),
    (r"employee/.*(1095C|W2|1099)", 8),
    (r"employee/.*(Everify|getI9Data|getOSHA)", 9),
    (r"employee/.*getLeaveRequests", 7),
    (r"employee/.*getLifeEvent", 6),
    (r"employee/.*getPayCardEmployees", 2),
    (r"employee/.*getPendingApproval", 11),
    (r"humanResources/.*getAssignedPendingApprovals", 11),
    (r"humanResources/.*getStaffingPlacement", 1),
    (r"payroll/.*Billing", 10),
    (r"payroll/.*getExternalPtoBalance", 7),
    (r"payroll/.*getEmployeeOverrideRates", 1),
    (r"payroll/.*getStandardHours", 5),
    (r"signOn/.*getEmployeeImage", 1),
    (r"system/.*getData$", 11),
    (r"system/.*(getEmployerDetails|getMultiEntityGroupList)", 5),
    (r"taxRate/.*WorkersComp", 5),
    (r"timesheet/.*getBatchStatus", 4),
]
_ISOLVED_TAG = {
    "Absence Policies": 7, "Absences": 7, "Account Statuses": 5, "Accrual Types": 7, "Accruals": 7,
    "Alternate Calculations": 5, "Bank Accounts": 10, "Benefit Plans": 6, "Billing Items": 10, "Branding": 11,
    "Certifications": 9, "Check Details": 4, "Citizenships": 5, "Client Benefit Enrollment": 6,
    "Client Change Reasons": 5, "Client File Subcategories": 9, "Client Holidays": 7,
    "Client Integration Mappings": 11, "Client Job Groups": 5, "Client Job Levels": 5, "Client Jobs": 5,
    "Client Options": 5, "Client Shifts": 7, "Clients": 5, "Contact Relationship Codes": 5, "Contacts": 1,
    "Corestream": 4, "Countries": 5, "Default Schedules": 7, "Deferred Comp": 6, "DirectDeposits": 2,
    "Disability Status": 1, "Disbursement Rule": 7, "Document Categories": 9, "Document Types": 9,
    "Documents": 9, "EEO Status": 1, "Earnings": 5, "Education": 9, "Education Types": 9,
    "Employee Benefits": 6, "Employee Dashboard": 7, "Employee Garnishments": 3, "Employee Groups": 5,
    "Employee I9": 9, "Employee Messages": 11, "Employee Notices": 11, "Employee Notifications": 11,
    "Employee Payroll": 4, "Employee Workflow": 11, "Employees": 1, "Employment Category": 1,
    "Employment Status History": 1, "EthnicOrigins": 5, "Filing Statuses": 8, "Frequency Types": 5,
    "Genders": 5, "General Ledger": 10, "Geocode Locations": 11, "Geofences": 7, "Imports": 11, "Jobs": 1,
    "Labor Fields": 5, "Labor GL Rules": 10, "Labor Groups": 5, "Legal Life Events": 6,
    "Legal Miscellaneous Fields": 5, "Legal Seasons": 5, "Legal Time Clocks": 7, "Legals": 5,
    "Managers/Supervisors": 5, "MaritalStatuses": 5, "Military Cities": 5, "Military States": 5,
    "Military Status": 5, "Misc Employee Fields": 5, "Miscellaneous Fields": 5, "Onboarding Templates": 9,
    "Organization Fields": 5, "Organization Workers Comp": 5, "PEO": 5, "PEO Employees": 1,
    "PEO Pay Items": 3, "PEO Workers Comp Policies": 5, "Pay": 5, "Pay Group Seasons": 5,
    "Pay Item Schedules": 5, "Pay Items": 3, "Pay Rates": 1, "Pay Types": 5, "Payroll": 4,
    "Payroll History": 4, "Pending Employees": 9, "Pending Time Off Requests": 7,
    "Pending Workflow Transactions": 11, "Person Name Address": 1, "Person Personal": 1, "Policy Groups": 7,
    "Prior Employment": 9, "Punch Statuses": 7, "Rule Sets": 7, "SOC Codes": 5, "Salaries": 1,
    "Salary Grade": 5, "Security Rules": 7, "Self Service Roles": 11, "Skill Types": 9, "Skills": 9,
    "States": 5, "System Ach Banks": 10, "System Bank Accounts": 10, "System Banks": 10,
    "System Benefit Plans": 6, "Tax Forms": 8, "Taxes": 8, "Teams": 5, "Time Zones": 5, "Training": 9,
    "Training Types": 9, "User Notification Methods": 11, "User Preferences": 11, "Veteran Status": 1,
    "Work Classifications": 5, "Work Locations": 5, "Work Locations by Labor": 5,
    "Workers Compensation Codes": 5,
}  # fmt: skip
_ISOLVED_RULES = [
    (r"corestream/.*/employees(/\{[^}]+\})?$", 1),
    (r"corestream/.*/deductions$", 3),
    (r"employees/\{id\}/holidays$", 7),
    (r"dashboard/clientContacts$", 11),
    (r"employees/\{employeeId\}/payroll$", 1),
    (r"employees/\{employeeId\}/benefits$", 3),
]
_UKG_RULES = [
    (r"expense-tracking", 10),
    (
        r"(login|logout|refresh-token|oauth|session|service-accounts|/accounts|access-profiles|account-groups|"
        r"password-policy|navigation|dashboard|/hcm/|announcements|notifications|todo|integrations|system-jobs|"
        r"exports?\b|data-exports|imports?\b|reports?\b|datadelivery|vca-report|manager-replacements|/notes$|"
        r"hr-actions|calendar|/me\b|/me/)",
        11,
    ),
    (r"/lookup/", 5),
    (
        r"(applicants|job-applications|recruitment|/ids\b|/forms/(custom|system)|forms/custom/ids|forms/system/ids|"
        r"skills|training|credentials|asset|inventory|vehicle)",
        9,
    ),
    (
        r"(time-entries|timesheets|punches|timeoff|attendance|accrual|counter-adjustments|overtime|/loa/|"
        r"ptorequest|schedules|holiday|badges|work-time-preferences|timeoffs)",
        7,
    ),
    (r"(tax-info|/taxes/|forms/pay)", 8),
    (r"benefits", 6),
    (r"direct-deposits", 2),
    (r"deductions", 3),
    (r"(payrolls|pay-periods|external-pay-statements)", 4),
    (
        r"(config/cost-center|rates/tables|rate-tables|rate-items|pay-types|pay-period-profiles|company/profiles|"
        r"position/positions|projects)",
        5,
    ),
    (r"(employees|employee\b|compensation|primary-assignment|position/|contacts)", 1),
]


def topic(provider: str, path: str, group: str) -> int:
    if provider == "prismhr":
        return _first(_PRISM_RULES, path, _PRISM_TAG[group])
    if provider == "isolved":
        return _first(_ISOLVED_RULES, path, 7 if group.startswith("Timecard") else _ISOLVED_TAG[group])
    return _first(_UKG_RULES, path, 11)


# ---------------------------------------------------------------------- the inventory


def _shape(path: str) -> str:
    """One form for documented paths and allowlist templates: every placeholder becomes {}."""
    return re.sub(r"\{[^}]*\}|\([^)]*\)", "{}", path).strip("/").lower()


def fetched(provider: str) -> set[str]:
    """The allowlisted endpoints, in the shape of documented paths."""
    if provider == "prismhr":
        return {_shape(op) for op in PRISM_OPERATIONS | {PRISM_EMPLOYER_OPERATION}}
    if provider == "isolved":
        return {_shape(t) for t in ISOLVED_TEMPLATES}
    return {_shape(t.removeprefix("rest/")) for t in UKG_TEMPLATES}


@lru_cache(maxsize=None)
def inventory(provider: str) -> tuple[Endpoint, ...]:
    allowlisted = fetched(provider)
    entries = []
    for path, group in _paths(provider):
        t = topic(provider, path, group)
        if _shape(path) in allowlisted:
            disposition, reason = FETCHED, "in scope.py's allowlist"
        elif (provider, path) in DECISIONS:
            disposition, reason = DECISIONS[(provider, path)]
        elif t in TOPIC_DECISIONS:
            disposition, reason = TOPIC_DECISIONS[t]
        else:
            disposition, reason = UNDECIDED, f"holds {TOPICS[t]} data, and no decision is recorded"
        entries.append(Endpoint(provider, path, t, disposition, reason))
    return tuple(entries)


# ---------------------------------------------------------------------- content check

# Topic rules read an endpoint's tag or path, not what it returns, and twice they filed deduction setup under
# "benefits" (retirement loans; retirement, flex and adjustment plans). So each response schema is also
# scored by content: how many of its properties, by name or description, use the vocabulary of each core
# topic. An endpoint that reaches CONTENT_THRESHOLD in a core topic needs a decision of its own; a topic rule
# alone is not enough (A-74).
CORE_TERMS = {
    1: r"birth ?date|date of birth|hire ?date|rehire|termination date|\bssn\b|social security|gender|marital"
    r"|ethnic|citizenship|seniority",
    2: r"routing|transit (?:number|num)|bank account|account (?:number|num)|account type|direct deposit|prenote"
    r"|pre-note",
    3: r"deduct|garnish|elective|catch ?-?up|payback|contribution|arrears|\bloan",
    4: r"gross (?:pay|wages)|net pay|check (?:number|num|date)|pay date|voucher|earning|withh|taxable wage",
}
CONTENT_THRESHOLD = 3


def _words(name: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").lower()


def _properties(schema: object, root: dict, out: list[str], depth: int = 0, seen: frozenset[str] = frozenset()) -> None:
    """Each property under a response schema, as "name words | description", following $ref within root."""
    if depth > 6 or not isinstance(schema, dict):
        return
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if ref in seen or not ref.startswith("#/"):
            return
        node: object = root
        for part in ref[2:].split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        _properties(node, root, out, depth + 1, seen | {ref})
        return
    for key in ("allOf", "anyOf", "oneOf"):
        for part in schema.get(key) or []:
            _properties(part, root, out, depth + 1, seen)
    _properties(schema.get("items"), root, out, depth + 1, seen)
    for name, prop in (schema.get("properties") or {}).items():
        description = prop.get("description", "") if isinstance(prop, dict) else ""
        out.append(f"{_words(name)} | {str(description).lower()}")
        _properties(prop, root, out, depth + 1, seen)


@lru_cache(maxsize=None)
def _document(provider: str) -> dict:
    name = {
        "prismhr": "prismhr/openapi/prismhr-2025.09.openapi.json",
        "isolved": "isolved/openapi/isolved-v6.swagger.json",
        "ukg-ready": "ukg-ready/reference-schemas.json",
    }[provider]
    document: dict = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    return document


def response_properties(provider: str, path: str) -> list[str]:
    """The properties of an endpoint's documented 200 response. UKG documents 260 of its 300 read endpoints
    with a schema; the others have none to score."""
    out: list[str] = []
    document = _document(provider)
    if provider == "ukg-ready":
        page = "reference-docs/res/__" + path.lstrip("/").replace("/", "__") + ".html"
        for block in document["schemas"]:
            if block["source_page"] == page and block["method"] == "GET" and isinstance(block["schema"], dict):
                _properties(block["schema"], block["schema"], out)
        return out
    response = ((document["paths"][path].get("get") or {}).get("responses") or {}).get("200") or {}
    schema = ((response.get("content") or {}).get("application/json") or {}).get("schema") or response.get("schema")
    _properties(schema, document, out)
    return out


def core_scores(provider: str, path: str) -> dict[int, int]:
    """For each core topic, how many response properties use its vocabulary."""
    properties = response_properties(provider, path)
    return {t: sum(1 for p in properties if re.search(pattern, p)) for t, pattern in CORE_TERMS.items()}


def looks_like_core_data(provider: str) -> list[tuple[Endpoint, dict[int, int]]]:
    """Endpoints decided only by a topic rule whose response looks like core data: each needs its own decision."""
    found = []
    for entry in inventory(provider):
        if entry.disposition == FETCHED or (provider, entry.path) in DECISIONS:
            continue
        scores = core_scores(provider, entry.path)
        if max(scores.values()) >= CONTENT_THRESHOLD:
            found.append((entry, scores))
    return found
