"""What to fetch from each demo tenant, in dependency order.

Each crawl walks company -> employees -> per-employee setup -> payroll runs
-> paychecks, using IDs taken from earlier responses. Limits keep a run small
and polite; every response, including errors, is saved by the Recorder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .client import ReadOnlyClient

# Health is excluded on purpose: it returns medical data that the canonical model does not need.
PRISM_EMPLOYEE_OPTIONS = ",".join(
    [
        "Person",
        "Client",
        "Compensation",
        "ContactInformation",
        "DirectDeposit",
        "HSA",
        "ScheduledDeductions",
        "EmployeeEvents",
        "Skills",
        "AbsenceJournal",
        "BenefitEnrollStatus",
        "NewHireQuestions",
        "EnrollmentInprogress",
    ]
)
PRISM_CLIENT_CODE_OPTIONS = ",".join(
    [
        "BenefitGroup",
        "Deduction",
        "Department",
        "Division",
        "Ethnic",
        "Job",
        "Location",
        "Pay",
        "PGroups",
        "PositionClass",
        "Reason",
        "Relation",
        "RetirementPlan",
        "Shift",
        "Status",
        "Type",
        "Union",
        "Workgroup",
    ]
)
PRISM_SYSTEM_CODE_OPTIONS = "SYSTEM.Deduction,SYSTEM.Pay,SYSTEM.Reason,SYSTEM.Status,SYSTEM.Type"
PRISM_VOUCHER_OPTIONS = ["EmployerContribution", "Retirement", "TaxFilingStatus", "Arrears"]
UKG_DEPRECATED_DD_HEADERS = {"X-End-of-Support-Timeline": "2026-01-29"}


@dataclass
class Limits:
    since: date
    until: date
    max_employees: int = 25
    max_payrolls: int = 12
    max_paychecks: int = 40
    max_companies: int | None = None


def crawl(client: ReadOnlyClient, limits: Limits) -> None:
    {"prismhr": _prismhr, "isolved": _isolved, "ukg-ready": _ukg}[client.provider](client, limits)


def _dig(body, *keys):
    for key in keys:
        if isinstance(body, dict):
            body = body.get(key)
        else:
            return None
    return body


def _ids(items, key="id") -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item[key]) for item in items if isinstance(item, dict) and item.get(key) not in (None, "")]


def _pick_batches(batches: list[dict], limit: int) -> list[dict]:
    """Most recent completed batches, plus the latest completed one of every batch type seen."""
    completed = [b for b in batches if b.get("batchStatus") == "COMP"]
    chosen = completed[-limit:]
    for batch_type in {b.get("batchType") for b in completed}:
        latest = [b for b in completed if b.get("batchType") == batch_type][-1]
        if latest not in chosen:
            chosen.append(latest)
    return chosen


def _prismhr(c: ReadOnlyClient, limits: Limits) -> None:
    employers_fetched: set[str] = set()
    for client_id in sorted(c.session.companies.clients)[: limits.max_companies]:
        base = {"clientId": client_id}
        c.get("clientMaster/v1/getClientMaster", base)
        for employer_id in sorted(c.employers - employers_fetched):
            employers_fetched.add(employer_id)
            c.get("system/v1/getEmployerDetails", {"employerId": employer_id})
        c.get("clientMaster/v1/getClientCodes", {**base, "options": PRISM_CLIENT_CODE_OPTIONS})
        c.get("clientMaster/v1/getClientCodes", {**base, "options": PRISM_SYSTEM_CODE_OPTIONS})
        c.get("clientMaster/v1/getPayrollSchedule", base)

        listing = c.get("employee/v1/getEmployeeList", base)["body"]
        employee_ids = [str(i) for i in (_dig(listing, "employeeList", "employeeId") or [])]
        selected = employee_ids[: limits.max_employees]
        for start in range(0, len(selected), 20):
            c.get(
                "employee/v1/getEmployee",
                {**base, "employeeId": selected[start : start + 20], "options": PRISM_EMPLOYEE_OPTIONS},
            )
        for employee_id in selected:
            person = {**base, "employeeId": employee_id}
            c.get("employee/v1/getPayRateHistory", person)
            c.get("employee/v1/getScheduledDeductions", person)
            c.get("deductions/v1/getDeductions", {**person, "options": ""})
            c.get("deductions/v1/getVoluntaryRecurringDeductions", person)
            c.get("deductions/v1/getEmployeeLoans", person)
            if "deductions/v1/getGarnishmentDetails" not in c.denied:
                record = c.get("deductions/v1/getGarnishmentDetails", person)
                if str(_dig(record["body"], "errorCode")) == "403":
                    c.denied.add("deductions/v1/getGarnishmentDetails")
            c.get("benefits/v1/getActiveBenefitPlans", person)

        batches: dict[str, dict] = {}
        for year in range(limits.since.year, limits.until.year + 1):
            window = {
                "startDate": max(limits.since, date(year, 1, 1)).isoformat(),
                "endDate": min(limits.until, date(year, 12, 31)).isoformat(),
                "dateType": "PAY",
            }
            listing = c.get("payroll/v1/getBatchListByDate", {**base, **window})["body"]
            for batch in _dig(listing, "batchList") or []:
                if isinstance(batch, dict) and batch.get("batchId"):
                    batches.setdefault(str(batch["batchId"]), batch)
        for batch in _pick_batches(list(batches.values()), limits.max_payrolls):
            batch_id = str(batch["batchId"])
            c.get("payroll/v1/getBatchInfo", {**base, "batchId": batch_id})
            seen: set[str] = set()
            for page in range(0, 20):
                vouchers = c.get(
                    "payroll/v1/getPayrollVoucherForBatch",
                    {
                        **base,
                        "batchId": batch_id,
                        "count": "25",
                        "startpage": str(page),
                        "options": PRISM_VOUCHER_OPTIONS,
                    },
                )["body"]
                # Live responses use "payrollVoucher"; the 2025.09 spec documents "payrollVouchers".
                listed = _dig(vouchers, "payrollVoucher") or _dig(vouchers, "payrollVouchers")
                new_ids = set(_ids(listed, "voucherId")) - seen
                seen |= new_ids
                total = _dig(vouchers, "total")
                if not new_ids or (isinstance(total, int) and len(seen) >= total) or len(seen) >= limits.max_paychecks:
                    break


def _paged(c: ReadOnlyClient, path: str, params: dict, limit: int, page_param: str = "page") -> list[dict]:
    results: list[dict] = []
    for page in range(0, 50):
        body = c.get(path, {**params, page_param: page})["body"]
        batch = _dig(body, "results")
        if not isinstance(batch, list) or not batch:
            break
        results += batch
        if not _dig(body, "nextPageUrl") or len(results) >= limit:
            break
    return results


def _isolved(c: ReadOnlyClient, limits: Limits) -> None:
    for path in (
        "api/lookup/Frequencies",
        "api/lookup/genders",
        "api/lookup/maritalStatuses",
        "api/lookup/ethnicorigins",
        "api/lookup/citizenships",
        "api/system/payTypes",
        "api/system/earnings",
    ):
        c.get(path)
    for client_id in sorted(c.session.companies.clients):
        c.get(f"api/clients/{client_id}")
        c.get(f"api/clients/{client_id}/payItems")
    for client_id, legal_id in sorted(c.session.companies.legals)[: limits.max_companies]:
        root = f"api/clients/{client_id}/legals/{legal_id}"
        corestream = f"api/corestream/clients/{client_id}/legals/{legal_id}"
        legal = c.get(root, {"includeDetails": "true"})["body"]

        # Paychecks are sparse, so find them company-wide first and make sure their employees are sampled.
        checks = _paged(
            c,
            f"{root}/checks",
            {
                "filter.fromDate": limits.since.isoformat(),
                "filter.toDate": limits.until.isoformat(),
                "filter.pageSize": 500,
            },
            5000,
            page_param="filter.page",
        )
        check_owners = list(dict.fromkeys(_ids(checks, "employeeId")))
        employees = _paged(c, f"{root}/employees", {"pageSize": 100}, 10_000)
        sample = list(dict.fromkeys(check_owners[: limits.max_employees] + _ids(employees)))[: limits.max_employees]
        for employee_id in sample:
            person = f"{root}/employees/{employee_id}"
            c.get(
                person,
                {
                    "includeMiscFields": "true",
                    "includeLabors": "true",
                    "includeOrganizations": "true",
                    "includeAlternateRates": "true",
                    "includeTaxes": "true",
                },
            )
            for suffix in ("directdeposits", "salaries", "statuses", "payRates", "payItems", "garnishments"):
                c.get(f"{person}/{suffix}")
            for template, path in (
                ("api/clients/{client}/legals/{legal}/employees/{id}/payroll", f"{person}/payroll"),
                (
                    "api/corestream/clients/{client}/legals/{legal}/employees/{id}/deductions",
                    f"{corestream}/employees/{employee_id}/deductions",
                ),
            ):
                if template not in c.denied:
                    c.get(path)
        picked = [check for check in checks if isinstance(check, dict) and check.get("id") is not None]
        by_owner: dict[str, list[dict]] = {}
        for check in picked:
            by_owner.setdefault(str(check.get("employeeId")), []).append(check)
        spread = [owned[-1] for owned in by_owner.values()] + picked[::-1]
        fetched: set[str] = set()
        for check in spread:
            if len(fetched) >= limits.max_paychecks:
                break
            check_id = str(check["id"])
            if check_id not in fetched:
                fetched.add(check_id)
                c.get(f"{root}/employees/{check.get('employeeId')}/checks/{check_id}")

        for pay_group_id in _ids(_dig(legal, "payGroups")):
            history = c.get(f"{root}/paygroupId/{pay_group_id}/payrollRunHistory")["body"]
            runs = history if isinstance(history, list) else []
            completed = [r for r in runs if "complete" in str(r.get("status", "")).lower()]
            others = [r for r in runs if r not in completed]
            for payroll_id in _ids(completed[-limits.max_payrolls :] + others[-2:]):
                c.get(f"{root}/paygroupId/{pay_group_id}/payrollRunHistory/{payroll_id}")
                template = "api/corestream/clients/{client}/legals/{legal}/paygroups/{id}/payrolls/{id}"
                if template not in c.denied:
                    c.get(f"{corestream}/paygroups/{pay_group_id}/payrolls/{payroll_id}")


def _ukg(c: ReadOnlyClient, limits: Limits) -> None:
    for company_id in sorted(c.session.companies.companies)[: limits.max_companies]:
        root = f"rest/v2/companies/{company_id}"
        for lookup in (
            "eins",
            "earning-codes",
            "deduction-codes",
            "pay-types",
            "payroll-types",
            "pay-statement-types",
            "employee-types",
            "jobs",
        ):
            c.get(f"{root}/lookup/{lookup}")
        # Paychecks are sparse, so find them first and make sure their employees are sampled (A-07).
        listing = c.get(
            f"{root}/payrolls", {"pay_date_from": limits.since.isoformat(), "pay_date_to": limits.until.isoformat()}
        )["body"]
        payrolls = [p for p in _dig(listing, "payrolls") or [] if isinstance(p, dict) and p.get("id")]
        past = sorted(
            (p for p in payrolls if str(p.get("pay_date", "")) <= date.today().isoformat()),
            key=lambda p: str(p.get("pay_date")),
            reverse=True,
        )
        owners: list[str] = []
        with_statements = probed = 0
        for payroll in past + [p for p in payrolls if p not in past][:2]:
            if with_statements >= limits.max_payrolls or probed >= limits.max_payrolls * 3:
                break
            probed += 1
            payroll_id = str(payroll["id"])
            c.get(f"{root}/payrolls/{payroll_id}")
            statements = c.get(f"{root}/payrolls/{payroll_id}/pay-statements")["body"]
            rows = [s for s in _dig(statements, "pay_statements") or [] if isinstance(s, dict)]
            owners += [str(a) for s in rows if (a := (s.get("employee") or {}).get("account_id")) not in (None, "")]
            statement_ids = _ids(rows)
            with_statements += bool(statement_ids)
            for statement_id in statement_ids[: limits.max_paychecks]:
                c.get(f"{root}/payrolls/{payroll_id}/pay-statements/{statement_id}")

        employees = c.get(f"{root}/employees")["body"]
        listed = _ids(_dig(employees, "employees"))
        sample = list(dict.fromkeys(owners + listed))[: limits.max_employees]  # owners first, without repeats
        for account_id in sample:
            person = f"{root}/employees/{account_id}"
            c.get(person)
            c.get(f"{person}/pay-info")
            c.get(f"{person}/compensation/history")
            c.get(f"{person}/direct-deposits", headers=UKG_DEPRECATED_DD_HEADERS)
            deductions = c.get(f"{person}/deductions")["body"]
            for deduction_id in _ids(_dig(deductions, "deductions")):
                c.get(f"{person}/deductions/{deduction_id}")
