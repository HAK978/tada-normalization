"""PrismHR: raw bundle in, canonical records out.

A PrismHR "client" is the company (A-30). Every field is read through Src, so anything
not mapped here is kept in provider_extensions; field meanings come from codes.py.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from normalization.bundle import Bundle, Capture
from normalization.canonical import codes as C
from normalization.canonical.records import (
    Address,
    BankAccount,
    BenefitDetail,
    Calculation,
    Company,
    CompanyContact,
    Compensation,
    CompensationChange,
    Contact,
    ContributionLine,
    DeductionElection,
    DeductionLimits,
    DeductionLine,
    DirectDeposit,
    EarningLine,
    Email,
    Employee,
    EmployerMatch,
    EmployerRef,
    EmploymentChange,
    FrequencyInfo,
    Identifier,
    JobChange,
    LoanDetails,
    OrgUnit,
    PayGroup,
    PaymentLine,
    PayrollRun,
    PayStatement,
    PayStatementTotals,
    PersonName,
    Phone,
    RetirementSummary,
    RunPayGroup,
    TaxLine,
)
from normalization.canonical.types import (
    Coded,
    DateRange,
    Diagnostic,
    Money,
    NationalId,
    Percent,
    Quantity,
    Rate,
    Source,
    TaxIdentifier,
    company_scope,
)
from normalization.output import Output
from normalization.sanitize import last4, sanitize_extensions
from normalization.source import Notes, Src, coded, decimal, flag, iso_date, known_flag, text, unmapped_label

from ..common import (
    ZERO,
    attach_checks,
    categorized,
    customer_category,
    derived_sum,
    is_remainder,
    line_amount,
    masked,
    money,
    nonzero,
    paid_gross,
    tax_type,
    unmasked_date,
    us_state,
)
from . import codes as P

PROVIDER = "prismhr"
# Responses about one employee that are read into the employee record, besides getEmployee.
PER_EMPLOYEE = (
    "employee/v1/getHistory",
    "benefits/v1/getDependents",
    "employee/v1/checkForGarnishments",
    "payroll/v1/getScheduledPayments",
    "benefits/v1/getRetirementPlan",
    "benefits/v1/getFlexPlans",
    "benefits/v1/getBenefitAdjustments",
)
# Deduction setup with no record type of its own: kept with the employee as sent (A-91).
KEPT_WITH_EMPLOYEE = ("benefits/v1/getRetirementPlan", "benefits/v1/getFlexPlans", "benefits/v1/getBenefitAdjustments")

RETIREMENT_FIELDS = {
    "electiveContributionsPreTax": "employee_pre_tax",
    "catchUpContributionsPreTax": "employee_pre_tax_catch_up",
    "rothContributionsPostTax": "employee_roth",
    "rothCatchUpContributionsPostTax": "employee_roth_catch_up",
    "employeeContributionsPostTax": "employee_post_tax",
    "employerMatchingContributions": "employer_match",
    "employerNonElectiveContributions": "employer_non_elective",
    "employerSafeHarborMatchType1": "employer_safe_harbor_1",
    "employerSafeHarborMatchType2": "employer_safe_harbor_2",
    "peoMatchingContribution": "peo_match",
    "employeeRetirementLoanPayments": "loan_repayment",
}


def normalize(bundle: Bundle, as_of: date | None = None) -> Output:
    out = Output()
    # PrismHR can report a failure inside an HTTP 200 (errorCode). Such a response is not data: it is
    # taken out of the successful ones here, and reported on the records it would have fed (A-70).
    failed = [c for c in bundle.captures if error_in_body(c)]
    if failed:
        bundle = replace(bundle, captures=[replace(c, status=-1) if c in failed else c for c in bundle.captures])
    clients = {str(c["client_id"]) for c in bundle.companies if c.get("client_id")}
    clients |= {str(c.params["clientId"]) for c in bundle.captures if c.params.get("clientId")}
    for client_id in sorted(clients):
        client = _Client(bundle, client_id, out)
        with company_scope(client.company_id):
            client.run()
    return out


def request_scope(capture: Capture) -> list[tuple[str, dict[str, str]]]:
    """The records a request feeds, by the IDs in their Source.ids: its employees, else its client (A-70)."""
    client = text(capture.params.get("clientId"))
    if client is None:
        return []  # e.g. employer lookups, keyed by employer ID; reported by the converter (A-09)
    employees = capture.params.get("employeeId")
    ids = employees if isinstance(employees, list) else [employees] if employees not in (None, "") else []
    return [("employees", {"clientId": client, "employeeId": str(e)}) for e in ids] + [
        ("companies", {"clientId": client})
    ]


def error_in_body(capture: Capture) -> str | None:
    """PrismHR can report a failure inside an HTTP 200: a nonzero errorCode (A-64)."""
    return _error_code(capture.body) if capture.status == 200 else None


def _error_code(body: Any) -> str | None:
    code = text(body.get("errorCode")) if isinstance(body, dict) else None
    return code if code not in (None, "0") else None


def _codes_table(rows: Any, key: str = "id") -> dict[str, dict]:
    return {str(row[key]): row for row in rows or [] if isinstance(row, dict) and row.get(key) not in (None, "")}


class _Client:
    def __init__(self, bundle: Bundle, client_id: str, out: Output):
        self.bundle, self.client_id, self.out = bundle, client_id, out
        self.tenant = bundle.tenant_id
        self.company_id = self._id("company", client_id)
        self.codes = self._load_codes()

    # -------------------------------------------------------------- helpers

    def _id(self, kind: str, *parts: Any) -> str:
        return ":".join([PROVIDER, self.tenant, kind, *[str(p) for p in parts]])

    def _source(self, endpoints: list[str], **ids: Any) -> Source:
        return Source(
            provider=PROVIDER,
            tenant_id=self.tenant,
            endpoints=sorted(set(endpoints)),
            ids={k: str(v) for k, v in ids.items() if v not in (None, "")},
        )

    def _load_codes(self) -> dict[str, dict[str, dict]]:
        """Client code tables (labels, pay classes, deduction types). Client-level rows win over SYSTEM ones."""
        tables: dict[str, dict[str, dict]] = {}
        captures = sorted(
            self.bundle.ok("clientMaster/v1/getClientCodes", clientId=self.client_id),
            key=lambda c: "SYSTEM." not in str(c.params.get("options")),
        )
        for capture in captures:
            codes = capture.body.get("clientCodes") or {}
            for name, key in (
                ("statusCode", "id"),
                ("typeCode", "id"),
                ("payCode", "id"),
                ("deductionCode", "id"),
                ("jobCode", "id"),
                ("departmentCode", "id"),
                ("divisionCode", "id"),
                ("locationCode", "id"),
                ("reasonCode", "id"),
                ("ethnicCode", "id"),
                ("relationCodes", "code"),
                ("unionCodes", "code"),
                ("payGroups", "payGroupCode"),
            ):
                tables.setdefault(name, {}).update(_codes_table(codes.get(name), key))
        return tables

    def _label(self, table: str, code: Any, *fields: str) -> str | None:
        row = self.codes.get(table, {}).get(str(code)) if code not in (None, "") else None
        return next((text(row.get(f)) for f in fields if row and text(row.get(f))), None)

    def _refused(self, endpoint: str, **params: Any) -> bool:
        params = params or {"clientId": self.client_id}
        return any(
            str((c.body or {}).get("errorCode", "0")) not in ("0", "") or c.status in (401, 403)
            for c in self.bundle.find(endpoint, **params)
        )

    def _org(self, table: str, code: Any, *name_fields: str) -> OrgUnit | None:
        code = text(code)
        return OrgUnit(code=code, name=self._label(table, code, *name_fields)) if code else None

    def _employee_ref(self, employee_id: Any) -> str | None:
        employee_id = text(employee_id)
        return self._id("employee", self.client_id, employee_id) if employee_id else None

    # -------------------------------------------------------------- run

    def run(self) -> None:
        self._company()
        employee_ids = self._employees()
        for employee_id in sorted(employee_ids | self._employees_with_setup()):
            added = len(self.out.records["deduction_elections"])
            self._deductions(employee_id)
            if employee_id not in employee_ids:  # the setup is kept, but its employee wasn't fetched
                for election in self.out.records["deduction_elections"][added:]:
                    election.diagnostics.append(
                        Diagnostic(
                            code="EMPLOYEE_NOT_IN_BUNDLE",
                            severity=C.Severity.INFO,
                            field="employeeId",
                            message="employee record was not fetched into this bundle",
                            raw=employee_id,
                        )
                    )
        for election in self._retirement_loans():
            if election.source.ids.get("employeeId") not in employee_ids:
                election.diagnostics.append(
                    Diagnostic(
                        code="EMPLOYEE_NOT_IN_BUNDLE",
                        severity=C.Severity.INFO,
                        field="employeeId",
                        message="employee record was not fetched into this bundle",
                        raw=election.source.ids.get("employeeId"),
                    )
                )
            self.out.add("deduction_elections", election)
        runs = self._payroll_runs()
        self._pay_statements(runs, employee_ids)

    # -------------------------------------------------------------- company

    def _company(self) -> None:
        notes, endpoints = Notes(), ["clientMaster/v1/getClientMaster"]
        capture = next(self.bundle.ok("clientMaster/v1/getClientMaster", clientId=self.client_id), None)
        s = Src((capture.body or {}).get("clientMaster") if capture else {})
        if capture is None:
            notes.warn("SOURCE_MISSING", None, "getClientMaster is not in the bundle; company fields are empty")
        fein = text(s.get("federalIdNumber"))
        employers = []
        if text(s.get("employerId")):
            employers.append(EmployerRef(kind=C.EmployerKind.ASSIGNED, provider_id=text(s.get("employerId"))))
        for alt in s.children("altEmployer"):
            employers.append(
                EmployerRef(
                    kind=C.EmployerKind.ALTERNATE,
                    provider_id=text(alt.get("altEmployerId")),
                    name=text(alt.get("altDisplayName")),
                )
            )
        # Employer lookups are keyed by employer ID, not client ID (A-05).
        # Keyed by employer ID, not client, so the general report can't place it (A-70); it is placed here.
        if any(self._refused("system/v1/getEmployerDetails", employerId=e.provider_id) for e in employers):
            notes.warn(
                "SOURCE_UNAVAILABLE",
                "system/v1/getEmployerDetails",
                "refused: the employers' names and EINs are unknown, not empty (A-09, A-70)",
            )
        pay_groups, schedule_extras = self._pay_groups()
        if pay_groups:
            endpoints += ["clientMaster/v1/getPayrollSchedule", "clientMaster/v1/getClientCodes"]
        addresses = [
            a
            for a in (
                self._address(
                    C.AddressType.COMPANY,
                    s,
                    "addressLine1",
                    "addressLine2",
                    "city",
                    "stateCode",
                    "zipCode",
                    "zipSuffix",
                ),
                self._address(
                    C.AddressType.BILLING,
                    s,
                    "billAddressLine1",
                    "billAddressLine2",
                    "billCity",
                    "billStateCode",
                    "billZipCode",
                    "billZipSuffix",
                ),
            )
            if a
        ]
        phone = text(s.get("mainPhone"))
        email = text(s.get("emailAddress"))
        contacts, contact_extras = self._company_contacts()
        if contacts or contact_extras:
            endpoints.append("clientMaster/v1/getAllPrismClientContacts")
        self.out.add(
            "companies",
            Company(
                id=self.company_id,
                source=self._source(endpoints, clientId=self.client_id),
                name=text(s.get("clientName")),
                legal_name=text(s.get("legalName")),
                status=coded(
                    P.COMPANY_STATUS, s.get("statusClass"), "clientMaster.statusClass", notes, C.CompanyStatus.UNMAPPED
                ),
                own_tax_id=TaxIdentifier(
                    value=None if masked(fein) else fein,
                    masked_at_source=masked(fein),
                    source_field="clientMaster.federalIdNumber",
                )
                if fein
                else None,
                service_arrangement=coded(
                    P.SERVICE_TYPE,
                    s.get("serviceType"),
                    "clientMaster.serviceType",
                    notes,
                    C.ServiceArrangement.UNMAPPED,
                ),
                employers=employers,
                pay_groups=pay_groups,
                addresses=addresses,
                phones=[Phone(type=C.PhoneType.MAIN, number=phone, extension=text(s.get("mainPhoneExt")))]
                if phone
                else [],
                emails=[Email(type=C.EmailType.MAIN, address=email)] if email else [],
                contacts=contacts,
                provider_extensions=sanitize_extensions({**s.leftovers(), **schedule_extras, **contact_extras}),
                diagnostics=notes.items,
            ),
        )

    def _company_contacts(self) -> tuple[list[CompanyContact], dict[str, Any]]:
        """The client's contacts (A-84); contact types are defined by the service provider and kept as sent."""
        contacts: list[CompanyContact] = []
        kept: dict[str, Any] = {}
        for capture in self.bundle.ok("clientMaster/v1/getAllPrismClientContacts", clientId=self.client_id):
            body = Src(capture.body)
            body.mark("errorCode", "errorMessage", "extension")
            result = body.child("prismClientContactResult") or Src({})
            # Live key is prismClientContact; the spec documents prismClientContacts (A-78).
            key = "prismClientContact" if "prismClientContact" in result.data else "prismClientContacts"
            for row in result.children(key):
                email = text(row.get("contactEmail"))
                contacts.append(
                    CompanyContact(
                        source_id=text(row.get("contactId")),
                        name=text(row.get("contactName")),
                        title=text(row.get("contactTitle")),
                        contact_type=text(row.get("contactType")),
                        phones=[
                            Phone(type=t, number=n, extension=x)
                            for t, n, x in (
                                (C.PhoneType.MAIN, text(row.get("contactPhone")), text(row.get("contactPhoneExt"))),
                                (C.PhoneType.MOBILE, text(row.get("contactCellPhone")), None),
                            )
                            if n
                        ],
                        emails=[Email(type=C.EmailType.MAIN, address=email)] if email else [],
                    )
                )
            kept.update(body.leftovers())
        return contacts, kept

    def _pay_groups(self) -> tuple[list[PayGroup], dict]:
        groups: dict[str, PayGroup] = {}
        extras: dict = {}
        for code, row in sorted(self.codes.get("payGroups", {}).items()):
            groups[code] = PayGroup(code=code, name=text(row.get("description")))
        for capture in self.bundle.ok("clientMaster/v1/getPayrollSchedule", clientId=self.client_id):
            # Live key is clientPayrollSchedule; the spec documents clientPayrollSchedules (A-16).
            key = "clientPayrollSchedule" if "clientPayrollSchedule" in capture.body else "clientPayrollSchedules"
            schedule = Src(capture.body)
            for entry in schedule.children(key):
                group_code = text(entry.get("groupId"))
                if not group_code:
                    continue
                notes = Notes()
                frequency = self._frequency(
                    entry.get("payPeriod"), f"{key}[].payPeriod", notes, label=text(entry.get("payPeriodDesc"))
                )
                groups[group_code] = PayGroup(
                    code=group_code,
                    name=text(entry.get("groupDesc")) or (groups[group_code].name if group_code in groups else None),
                    frequency=frequency,
                )
            schedule.mark("errorCode", "errorMessage", "extension")
            extras.update(schedule.leftovers())
        return list(groups.values()), extras

    def _frequency(self, code: Any, field: str, notes: Notes, label: str | None = None) -> FrequencyInfo | None:
        raw = text(code)
        if raw is None:
            return None
        known = P.PAY_PERIOD.get(raw)
        table = {k: v[0] for k, v in P.PAY_PERIOD.items()}
        return FrequencyInfo(
            frequency=coded(table, raw, field, notes, C.PayFrequency.UNMAPPED, label=label),
            periods_per_year=known[1] if known else None,
        )

    @staticmethod
    def _address(
        kind: C.AddressType,
        s: Src,
        line1: str,
        line2: str,
        city: str,
        state: str,
        zipcode: str,
        suffix: str,
        county: str | None = None,
    ) -> Address | None:
        values = {
            "line1": text(s.get(line1)),
            "line2": text(s.get(line2)),
            "city": text(s.get(city)),
            "state": text(s.get(state)),
            "county": text(s.get(county)) if county else None,
        }
        zip_main, zip_suffix = text(s.get(zipcode)), text(s.get(suffix))
        values["postal_code"] = f"{zip_main}-{zip_suffix}" if zip_main and zip_suffix else zip_main
        return Address(type=kind, **values) if any(values.values()) else None

    # -------------------------------------------------------------- employees

    def _benefit_plans(self, employee_id: str) -> dict[str, Any]:
        """Active benefit plans have no canonical record (model §7); they are kept with the employee."""
        kept: dict[str, Any] = {}
        for capture in self.bundle.ok(
            "benefits/v1/getActiveBenefitPlans", clientId=self.client_id, employeeId=employee_id
        ):
            for i, plan in enumerate(capture.body.get("benefitPlan") or []):
                kept.update(Src(plan, f"benefitPlans[{i}]").leftovers())
        return kept

    def _employees(self) -> set[str]:
        seen: set[str] = set()
        for capture in self.bundle.ok("employee/v1/getEmployee", clientId=self.client_id):
            for raw in capture.body.get("employee") or []:
                employee_id = text((raw or {}).get("id"))
                if employee_id and employee_id not in seen:
                    seen.add(employee_id)
                    self._employee(Src(raw), employee_id)
        return seen

    def _employees_with_setup(self) -> set[str]:
        endpoints = (
            "deductions/v1/getDeductions",
            "deductions/v1/getVoluntaryRecurringDeductions",
            "employee/v1/getScheduledDeductions",
            "deductions/v1/getEmployeeLoans",
        )
        return {
            str(c.params["employeeId"])
            for e in endpoints
            for c in self.bundle.ok(e, clientId=self.client_id)
            if c.params.get("employeeId")
        }

    def _employee(self, s: Src, employee_id: str) -> None:
        notes = Notes()
        employee_ref = self._id("employee", self.client_id, employee_id)
        person, contact, client, comp = (
            s.child(k) or Src({}) for k in ("person", "contactInformation", "client", "compensation")
        )
        s.get("id")
        # Handled as separate records, or never requested: medical data (model §9).
        s.mark("directDeposit", "hsa", "scheduledDeduction", "health")

        identifiers = [Identifier(type=C.IdentifierType.PROVIDER_ID, value=employee_id, source_field="id")]
        for kind, src, field in (
            (C.IdentifierType.EMPLOYEE_NUMBER, client, "clientEmployeeId"),
            (C.IdentifierType.CLOCK_NUMBER, client, "clockNum"),
            (C.IdentifierType.USERNAME, person, "userId"),
        ):
            value = text(src.get(field))
            if value:
                identifiers.append(Identifier(type=kind, value=value, source_field=f"{src.path}.{field}"))

        ssn = text(comp.get("ssn"))
        ssn_last4, ssn_masked = last4(ssn)

        # employeeStatus and employeeType are the client's own codes, a separate domain from PrismHR's documented
        # status and type classes (REFERENCE_AUDIT). They aren't read here, so they stay as sent in
        # provider_extensions, and their labels aren't attached to the class codes (A-89).
        status_class = text(client.get("statusClass"))
        status_date = iso_date(client.get("statusDate"), "client.statusDate", notes)
        employment: dict[str, Any] = dict(
            status=coded(
                P.STATUS_CLASS,
                status_class,
                "client.statusClass",
                notes,
                C.EmploymentStatus.UNMAPPED,
            ),
            status_date=status_date,
            employment_type=coded(
                P.TYPE_CLASS,
                client.get("typeClass"),
                "client.typeClass",
                notes,
                C.EmploymentType.UNMAPPED,
            ),
            original_hire_date=iso_date(client.get("firstHireDate"), "client.firstHireDate", notes),
            hire_date=iso_date(client.get("lastHireDate"), "client.lastHireDate", notes),
            start_date=iso_date(client.get("jobStartDate"), "client.jobStartDate", notes),
            seniority_date=iso_date(client.get("seniorityDate"), "client.seniorityDate", notes),
            last_worked_date=iso_date(comp.get("lastWorkedDate"), "compensation.lastWorkedDate", notes),
            termination_date=status_date if status_class == "T" else None,
            termination_reason=unmapped_label(
                client.get("termReasonCode"),
                self._label("reasonCode", client.get("termReasonCode"), "description"),
                "client.termReasonCode",
            ),
            flsa_exempt=flag(client.get("flsaExempt")),
            # Documented as employerIds; live sends employerId (A-78).
            employer_ids=[str(x) for x in (person.first("employerIds", "employerId") or []) if x not in (None, "")],
        )
        contractor = flag(client.get("employee1099"))
        if contractor is not None:
            employment["worker_classification"] = Coded[C.WorkerClassification](
                value=C.WorkerClassification.CONTRACTOR_1099 if contractor else C.WorkerClassification.EMPLOYEE,
                raw=contractor,
                source_field="client.employee1099",
            )

        addresses = [
            a
            for a in (
                self._address(
                    C.AddressType.HOME,
                    contact,
                    "addressLine1",
                    "addressLine2",
                    "city",
                    "state",
                    "zipcode",
                    "zipSuffix",
                    county="county",
                ),
                self._address(
                    C.AddressType.MAILING, client, "addressLine1", "addressLine2", "city", "state", "zip", "zipSuffix"
                ),
                self._address(
                    C.AddressType.W2,
                    person,
                    "w2AddressLine1",
                    "w2AddressLine2",
                    "w2City",
                    "w2State",
                    "w2PostalCode",
                    "w2PostalSuffix",
                ),
            )
            if a
        ]
        phones = [
            Phone(type=t, number=n, extension=x)
            for t, n, x in (
                (C.PhoneType.HOME, text(contact.get("homePhone")), None),
                (C.PhoneType.MOBILE, text(contact.get("mobilePhone")), None),
                (C.PhoneType.WORK, text(client.get("workPhone")), text(client.get("workPhoneExt"))),
            )
            if n
        ]
        emails = [
            Email(type=t, address=a)
            for t, a in (
                (C.EmailType.PERSONAL, text(contact.get("emailAddress"))),
                (C.EmailType.WORK, text(client.get("workEmail"))),
                (C.EmailType.BENEFITS, text(client.get("benefitEmail"))),
            )
            if a
        ]

        # Fields of the other per-employee responses that aren't mapped (A-62).
        kept: dict[str, Any] = {}
        personal = dict(
            birth_date=iso_date(person.get("birthDate"), "person.birthDate", notes),
            gender=coded(P.GENDER, person.get("gender"), "person.gender", notes, C.Gender.UNMAPPED),
            marital_status=coded(
                P.MARITAL, person.get("maritalStatus"), "person.maritalStatus", notes, C.MaritalStatus.UNMAPPED
            ),
            ethnicity=unmapped_label(
                person.get("ethnicCode"),
                self._label("ethnicCode", person.get("ethnicCode"), "description"),
                "person.ethnicCode",
            ),
            veteran=coded(
                P.YES_NO_DECLINED,
                person.get("veteran"),
                "person.veteran",
                notes,
                C.YesNoDeclined.UNMAPPED,
                empty_is_none=False,
            )
            if "veteran" in person.data
            else None,
            disabled=coded(
                P.YES_NO_DECLINED,
                person.get("handicapped"),
                "person.handicapped",
                notes,
                C.YesNoDeclined.UNMAPPED,
                empty_is_none=False,
            )
            if "handicapped" in person.data
            else None,
            citizenship=coded(
                P.CITIZENSHIP,
                comp.get("citizenshipStatus"),
                "compensation.citizenshipStatus",
                notes,
                C.Citizenship.UNMAPPED,
            ),
            preferred_language=text(person.get("preferredLanguage")),
            contacts=[
                Contact(
                    roles=[C.ContactRole.EMERGENCY],
                    full_name=text(c.get("contactName")),
                    relationship=text(c.get("contactRelationship")),
                    contact_type=text(c.get("contactType")),
                    contact_info=text(c.get("contactInfo")),
                    source_field=c.path,
                )
                for c in person.children("emergencyContact")
            ]
            + self._dependents(employee_id, notes, kept),
        )

        job: dict[str, Any] = dict(
            title=self._label("jobCode", client.get("jobCode"), "jobTitle"),
            job_code=text(client.get("jobCode")),
            department=self._org("departmentCode", client.get("homeDepartment"), "deptName"),
            division=self._org("divisionCode", client.get("homeDivision"), "divisionName"),
            location=self._org("locationCode", client.get("homeLocation"), "locationName"),
            manager_employee_id=self._employee_ref(client.get("manager")),
            union=self._org("unionCodes", client.get("unionCode"), "name"),
            pay_group=text(comp.get("payGroup")),
        )
        employment["history"], job["history"] = self._history(employee_id, notes, kept)
        self._garnishment_check(employee_id, notes, kept)
        # Recurring payments set up for future payrolls have no canonical record; they are kept as sent (A-80).
        for capture in self.bundle.ok(
            "payroll/v1/getScheduledPayments", clientId=self.client_id, employeeId=employee_id
        ):
            scheduled = Src(capture.body)
            scheduled.mark("errorCode", "errorMessage", "extension", "clientId", "employeeId", "checksum")
            kept.update(scheduled.leftovers())
        # The 401(k) plan's rules (its elections themselves come from getDeductions), FSA elections, and benefit
        # adjustments deducted over future paychecks: no record type holds them, so they stay as sent (A-91).
        for endpoint in KEPT_WITH_EMPLOYEE:
            for capture in self.bundle.ok(endpoint, clientId=self.client_id, employeeId=employee_id):
                body = Src(capture.body)
                body.mark("errorCode", "errorMessage", "extension")
                kept.update(body.leftovers())

        # Settings that apply to all of an employee's accounts are copied onto each deposit record. With no
        # account there is no deposit record, so they stay with the employee instead (A-62).
        deposit_settings = self._deposit_settings(s)
        for shared, rows, _ in deposit_settings.values():
            if not rows:
                kept.update(shared)
        history_kept: dict[str, Any] = {}  # pay rate history fields that aren't mapped (A-62)
        compensation = self._compensation(comp, employee_id, notes, history_kept)
        self.out.add(
            "employees",
            Employee(
                id=employee_ref,
                company_id=self.company_id,
                source=self._source(
                    ["employee/v1/getEmployee"]
                    + (["employee/v1/getPayRateHistory"] if compensation.history else [])
                    + [
                        e
                        for e in PER_EMPLOYEE
                        if any(True for _ in self.bundle.ok(e, clientId=self.client_id, employeeId=employee_id))
                    ],
                    clientId=self.client_id,
                    employeeId=employee_id,
                ),
                identifiers=identifiers,
                national_id=NationalId(
                    type=C.NationalIdType.SSN,
                    last4=ssn_last4,
                    masked_at_source=ssn_masked,
                    source_field="compensation.ssn",
                )
                if ssn
                else None,
                name=dict(
                    first=text(s.get("firstName")),
                    middle=text(s.get("middleInitial")),
                    last=text(s.get("lastName")),
                    preferred=text(s.get("preferredName")),
                    nickname=text(person.get("nickname")),
                ),
                personal=personal,
                addresses=addresses,
                phones=phones,
                emails=emails,
                employment=employment,
                job=job,
                compensation=compensation,
                provider_extensions=sanitize_extensions(
                    {**s.leftovers(), **history_kept, **kept, **self._benefit_plans(employee_id)}
                ),
                diagnostics=notes.items,
            ),
        )
        self._deposits(employee_id, deposit_settings)

    def _dependents(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[Contact]:
        """Dependents and beneficiaries from getDependents, as contacts (A-77)."""
        contacts = []
        for capture in self.bundle.ok("benefits/v1/getDependents", clientId=self.client_id, employeeId=employee_id):
            body = Src(capture.body)
            body.mark("errorCode", "errorMessage", "extension", "clientId", "employeeId")
            for d in body.children("dependent"):
                relation_type = text(d.get("relationType"))
                roles = list(P.DEPENDENT_RELATION_TYPE.get(relation_type or "", ()))
                if relation_type and not roles:
                    notes.warn("UNMAPPED_CODE", f"{d.path}.relationType", "not a documented type", relation_type)
                # Read only to add the role: the primary/contingent distinction stays as sent.
                beneficiary = text(d.data.get("beneficiaryType")) in P.BENEFICIARY_TYPES
                if beneficiary and C.ContactRole.BENEFICIARY not in roles:
                    roles.append(C.ContactRole.BENEFICIARY)
                status = text(d.data.get("status"))
                if status in P.DEPENDENT_STATUS:
                    d.get("status")
                relation = text(d.get("relation"))
                email = text(d.get("email"))
                contacts.append(
                    Contact(
                        source_id=text(d.get("dependentId")),
                        roles=roles,
                        name=PersonName(
                            first=text(d.get("firstName")),
                            middle=text(d.get("middleInitial")),
                            last=text(d.get("lastName")),
                        ),
                        relationship=self._label("relationCodes", relation, "description"),
                        relationship_code=relation,
                        birth_date=unmasked_date(d, "birthdate", notes),
                        phones=[
                            Phone(type=t, number=n)
                            for t, n in (
                                (C.PhoneType.HOME, text(d.get("homePhone"))),
                                (C.PhoneType.WORK, text(d.get("workPhone"))),
                            )
                            if n
                        ],
                        emails=[Email(type=C.EmailType.MAIN, address=email)] if email else [],
                        address=self._address(
                            C.AddressType.HOME, d, "address", "addressLine2", "city", "state", "zip", "zipSuffix"
                        ),
                        active=P.DEPENDENT_STATUS.get(status or ""),
                        source_field=d.path,
                    )
                )
            kept.update(body.leftovers())
        return contacts

    def _history(
        self, employee_id: str, notes: Notes, kept: dict[str, Any]
    ) -> tuple[list[EmploymentChange], list[JobChange]]:
        """Status, leave, termination, position and organization changes from getHistory (A-76).

        Each row carries one kind of change, named by the object it holds. Pay changes are kept as sent:
        the compensation history comes from getPayRateHistory. Benefit-group and wellness changes are kept too.
        """
        changes: list[EmploymentChange] = []
        jobs: list[JobChange] = []
        for capture in self.bundle.ok("employee/v1/getHistory", clientId=self.client_id, employeeId=employee_id):
            body = Src(capture.body)
            body.mark("errorCode", "errorMessage", "extension")
            # Live key is historyRecord; the spec documents historyRecords (A-78).
            key = "historyRecord" if "historyRecord" in capture.body else "historyRecords"
            for row in body.children(key):
                # A row names its kind by the one object it fills; the others arrive null.
                event = next((k for k in ("statusChange", "leave", "termination") if row.data.get(k)), None)
                orgs = {
                    k: row.child(k) for k in ("departmentChange", "divisionChange", "locationChange") if row.data.get(k)
                }
                position = text(row.data.get("newPositionCode"))
                if not (event or orgs or position):
                    continue  # pay, benefit-group and wellness changes stay in provider_extensions
                row_effective = iso_date(row.get("effectiveDate"), f"{row.path}.effectiveDate", notes)
                if event:
                    e = row.child(event) or Src({})
                    reason = e.get("reason")
                    changes.append(
                        EmploymentChange(
                            kind=P.HISTORY_EVENT[event],
                            effective_date=row_effective,
                            status=self._status_by_code(
                                e.get("employeeStatusCode"), f"{e.path}.employeeStatusCode", notes
                            ),
                            employment_type=self._type_by_code(
                                e.get("employeeTypeCode"), f"{e.path}.employeeTypeCode", notes
                            ),
                            # Reason codes are client-defined: kept with their label, not translated (A-35).
                            reason=unmapped_label(
                                reason, self._label("reasonCode", reason, "description"), f"{e.path}.reason"
                            ),
                            expected_return_date=iso_date(
                                e.get("expectedReturnDate"), f"{e.path}.expectedReturnDate", notes
                            ),
                            source_field=row.path,
                        )
                    )
                else:
                    department = orgs.get("departmentChange")
                    division = orgs.get("divisionChange")
                    location = orgs.get("locationChange")
                    row.get("newPositionCode")
                    jobs.append(
                        JobChange(
                            effective_date=row_effective,
                            title=self._label("jobCode", position, "jobTitle"),
                            job_code=position,
                            department=self._org("departmentCode", department.get("departmentCode"), "deptName")
                            if department
                            else None,
                            division=self._org("divisionCode", division.get("divisionCode"), "divisionName")
                            if division
                            else None,
                            location=self._org("locationCode", location.get("locationCode"), "locationName")
                            if location
                            else None,
                            source_field=row.path,
                        )
                    )
            kept.update(body.leftovers())
        return changes, jobs

    def _status_by_code(self, code: Any, field: str, notes: Notes) -> Coded[C.EmploymentStatus] | None:
        """A client status code, mapped through its status class in the client's code table (A-76)."""
        code = text(code)
        if code is None:
            return None
        row = self.codes.get("statusCode", {}).get(code) or {}
        status_class = text(row.get("statusClass"))
        value = P.STATUS_CLASS.get(status_class or "")
        if value is None:
            notes.warn("UNMAPPED_CODE", field, "status code has no documented status class in getClientCodes", code)
        return Coded[C.EmploymentStatus](
            value=value or C.EmploymentStatus.UNMAPPED, raw=code, label=text(row.get("description")), source_field=field
        )

    def _type_by_code(self, code: Any, field: str, notes: Notes) -> Coded[C.EmploymentType] | None:
        """A client employment type code, mapped through its type class in the client's code table (A-76)."""
        code = text(code)
        if code is None:
            return None
        row = self.codes.get("typeCode", {}).get(code) or {}
        type_class = text(row.get("typeClass"))
        value = P.TYPE_CLASS.get(type_class or "")
        if value is None:
            notes.warn("UNMAPPED_CODE", field, "type code has no documented type class in getClientCodes", code)
        return Coded[C.EmploymentType](
            value=value or C.EmploymentType.UNMAPPED, raw=code, label=text(row.get("description")), source_field=field
        )

    def _garnishment_check(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> None:
        """getGarnishmentDetails is refused live (A-09); checkForGarnishments says whether any are missed (A-83)."""
        for capture in self.bundle.ok(
            "employee/v1/checkForGarnishments", clientId=self.client_id, employeeId=employee_id
        ):
            s = Src(capture.body, "checkForGarnishments")
            s.mark("errorCode", "errorMessage", "extension")
            # Peeked, so the answers stay in provider_extensions as sent.
            has = [f for f in ("enrolled", "active") if flag(s.data.get(f))]
            read = any(
                True
                for _ in self.bundle.ok(
                    "deductions/v1/getGarnishmentDetails", clientId=self.client_id, employeeId=employee_id
                )
            )
            if has and not read:
                notes.warn(
                    "GARNISHMENTS_NOT_READ",
                    "employee/v1/checkForGarnishments",
                    f"the employee has garnishments ({' and '.join(has)}), but getGarnishmentDetails returned none "
                    "of them: garnishment elections are missing, not absent (A-83)",
                )
            kept.update(s.leftovers())

    def _compensation(self, comp: Src, employee_id: str, notes: Notes, kept: dict[str, Any]) -> Compensation:
        pay_method = text(comp.get("payMethod"))
        # A rate of 0 is no rate: only a nonzero one is read and mapped, so a 0 stays as sent in
        # provider_extensions (A-73), as for isolved.
        rates: list[Rate] = []
        salary = nonzero(comp, "salary")
        if salary is not None:
            rates.append(Rate(amount=salary, per=C.RatePeriod.PAY_PERIOD, source_field="compensation.salary"))
        hourly = nonzero(comp, "hourlyPay")
        if hourly is not None:
            rates.append(Rate(amount=hourly, per=C.RatePeriod.HOUR, source_field="compensation.hourlyPay"))
        basis_raw = text(comp.data.get("hourlyPayPeriod"))
        basis_rate = decimal(comp.data.get("hourlyPayRate"))
        if basis_rate is not None and basis_rate != ZERO and basis_raw:
            comp.get("hourlyPayRate")
            comp.get("hourlyPayPeriod")
            per = P.HOURLY_PAY_PERIOD.get(basis_raw)
            if per is None:
                notes.warn("UNMAPPED_CODE", "compensation.hourlyPayPeriod", "unknown pay-rate basis", basis_raw)
            elif basis_raw in P.UNDOCUMENTED_HOURLY_PAY_PERIOD:
                notes.info(
                    "UNDOCUMENTED_CODE_EVIDENCED",
                    "compensation.hourlyPayPeriod",
                    "'A' is not in this field's documented list; treated as YEAR (documented 'annually' in "
                    "PayRate.payPeriod; equals annualPay live, A-19)",
                    basis_raw,
                )
            rates.append(
                Rate(amount=basis_rate, per=per or C.RatePeriod.UNMAPPED, source_field="compensation.hourlyPayRate")
            )
        if not rates:
            notes.info("NO_PAY_RATE", "compensation", "no nonzero salary, hourly pay or pay rate; a 0 stays as sent")
        annual = nonzero(comp, "annualPay")  # 0 with no rate is no annual pay, like the rates (A-73)
        if annual is not None and pay_method == "H" and hourly and annual == hourly * 2080:
            notes.info(
                "PROVIDER_ANNUALIZED",
                "compensation.annualPay",
                "annualPay equals hourlyPay x 2080 for this hourly employee (A-20)",
            )
        standard = decimal(comp.get("standardHours"))
        return Compensation(
            pay_type=coded(P.PAY_METHOD, pay_method, "compensation.payMethod", notes, C.PayType.UNMAPPED),
            pay_frequency=self._frequency(comp.get("payPeriod"), "compensation.payPeriod", notes),
            rates=rates,
            annual_pay=Money(amount=annual, source_field="compensation.annualPay") if annual is not None else None,
            standard_hours=Quantity(
                value=standard, unit=C.QuantityUnit.HOURS, source_field="compensation.standardHours"
            )
            if standard is not None
            else None,
            standard_hours_per="PAY_PERIOD" if standard is not None else None,
            effective_date=iso_date(comp.get("effectiveDate"), "compensation.effectiveDate", notes),
            history=self._pay_history(employee_id, notes, kept),
        )

    def _pay_history(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[CompensationChange]:
        """Each pay rate change; whatever a row has that isn't mapped is added to `kept` (A-62)."""
        changes = []
        for capture in self.bundle.ok("employee/v1/getPayRateHistory", clientId=self.client_id, employeeId=employee_id):
            for i, row in enumerate(((capture.body.get("payRateHistory") or {}).get("payRate")) or []):
                h = Src(row, f"payRateHistory.payRate[{i}]")
                effective = iso_date(h.get("effectiveDate"), h.path + ".effectiveDate", notes)
                if effective and effective.year >= 9999:
                    notes.info(
                        "UNDOCUMENTED_SENTINEL_DATE",
                        h.path + ".effectiveDate",
                        "kept as a date; no documented meaning (A-25)",
                        str(effective),
                    )
                period = text(h.data.get("payPeriod"))
                rates = []
                # As for the current rates, a 0 is no rate and stays as sent (A-73).
                rate = nonzero(h, "payRate")
                if rate is not None:
                    per = P.PAY_RATE_PERIOD.get(period or "")
                    if per is not None:
                        h.get("payPeriod")
                        if period in P.UNDOCUMENTED_PAY_RATE_PERIOD:
                            notes.info(
                                "UNDOCUMENTED_CODE_EVIDENCED",
                                h.path + ".payPeriod",
                                "'Y' isn't in this field's documented list; treated as YEAR ('(Y)early' in "
                                "Compensation.hourlyPayPeriod; payRate equals annualPay live, A-19)",
                                period,
                            )
                    elif period:  # an unknown period is not read, so it stays as sent next to an UNMAPPED rate
                        notes.warn("UNMAPPED_CODE", h.path + ".payPeriod", "unknown pay-rate period", period)
                    rates.append(Rate(amount=rate, per=per or C.RatePeriod.UNMAPPED, source_field=h.path + ".payRate"))
                hourly = nonzero(h, "hourlyRate")
                if hourly is not None:
                    rates.append(Rate(amount=hourly, per=C.RatePeriod.HOUR, source_field=h.path + ".hourlyRate"))
                standard = decimal(h.get("standardHours"))
                changes.append(
                    CompensationChange(
                        source_id=f"{text(row.get('effectiveDate'))}#{i}",
                        effective_date=effective,
                        pay_type=coded(
                            P.PAY_METHOD, h.get("payMethod"), h.path + ".payMethod", notes, C.PayType.UNMAPPED
                        ),
                        rates=rates,
                        annual_pay=money(h.get("annualPay"), h.path + ".annualPay"),
                        standard_hours=Quantity(
                            value=standard, unit=C.QuantityUnit.HOURS, source_field=h.path + ".standardHours"
                        )
                        if standard is not None
                        else None,
                        reason=text(h.get("reason")),
                    )
                )
                kept.update(h.leftovers())
        return changes

    # -------------------------------------------------------------- direct deposits

    @staticmethod
    def _deposit_settings(employee: Src) -> dict[str, tuple[dict[str, Any], list[Any], str | None]]:
        """For directDeposit and hsa: the settings that apply to all their accounts (as sent), the account
        rows, and the voucherType that scopes every direct deposit account."""
        found = {}
        for block, rows_key in (("directDeposit", "achVoucher"), ("hsa", "hsaDepositSettings")):
            data = employee.data.get(block)
            if not isinstance(data, dict):
                continue
            settings = Src(data, block)
            settings.mark(rows_key)
            rows = data.get(rows_key) or []
            # Read only when there are accounts for it to scope; otherwise it stays with the other settings.
            scope = text(settings.get("voucherType")) if rows and block == "directDeposit" else None
            found[block] = (settings.leftovers(), rows, scope)
        return found

    def _deposits(self, employee_id: str, settings: dict[str, tuple[dict[str, Any], list[Any], str | None]]) -> None:
        employee_ref = self._id("employee", self.client_id, employee_id)
        for block, purpose in (("directDeposit", C.DepositPurpose.NET_PAY), ("hsa", C.DepositPurpose.HSA)):
            shared, rows, scope = settings.get(block, ({}, [], None))
            for i, row in enumerate(rows):
                self._deposit(Src(row), employee_ref, employee_id, purpose, i + 1, scope, shared)

    def _deposit(
        self,
        s: Src,
        employee_ref: str,
        employee_id: str,
        purpose: C.DepositPurpose,
        sequence: int,
        scope: str | None,
        shared: dict,
    ) -> None:
        notes = Notes()
        hsa = purpose is C.DepositPurpose.HSA
        prefix = "hsa.hsaDepositSettings[]" if hsa else "directDeposit.achVoucher[]"
        account_raw = text(s.get("accountType"))
        funding = None
        if hsa:
            mapped = P.HSA_ACCOUNT.get(account_raw or "")
            account_type = Coded[C.AccountType](
                value=mapped[0] if mapped else C.AccountType.UNMAPPED,
                raw=account_raw,
                source_field=f"{prefix}.accountType",
            )
            funding = Coded[C.FundingParty](
                value=mapped[1] if mapped else C.FundingParty.UNMAPPED,
                raw=account_raw,
                source_field=f"{prefix}.accountType",
            )
            if not mapped:
                notes.warn("UNMAPPED_CODE", f"{prefix}.accountType", "unknown HSA account type", account_raw)
        else:
            account_type = coded(
                P.DD_ACCOUNT_TYPE,
                account_raw,
                f"{prefix}.accountType",
                notes,
                C.AccountType.UNMAPPED,
                empty_is_none=False,
            )
        method_raw = text(s.get("method"))
        method = coded(
            P.HSA_METHOD if hsa else P.DD_METHOD,
            method_raw,
            f"{prefix}.method",
            notes,
            C.DepositMethod.UNMAPPED,
            empty_is_none=False,
        )
        value = decimal(s.get("amount"))
        is_percent = method.value in (
            C.DepositMethod.PERCENT_BASE_UNSPECIFIED,
            C.DepositMethod.PERCENT_OF_NET_AFTER_FIXED,
            C.DepositMethod.PERCENT_OF_NET_AFTER_TAXES,
        )
        # No fetched paycheck shows a percent deposit being paid, so its scale can't be checked (A-29).
        if is_percent and value is not None:
            notes.info(
                "PERCENT_SCALE_UNVERIFIED",
                f"{prefix}.amount",
                "no fetched paycheck pays a percent deposit, so the scale can't be checked (A-29)",
                str(value),
            )
        account_number = text(s.get("accountNum"))
        digits, was_masked = last4(account_number)
        overrides = text(s.get("voucherTypeOverride")) or scope
        applies = [
            coded(
                P.VOUCHER_SCOPE,
                letter,
                f"{prefix}.voucherTypeOverride"
                if text(s.data.get("voucherTypeOverride"))
                else "directDeposit.voucherType",
                notes,
                C.PayKindScope.UNMAPPED,
            )
            for letter in (overrides or "")
        ]
        self.out.add(
            "direct_deposits",
            DirectDeposit(
                id=self._id("direct_deposit", self.client_id, employee_id, purpose.value.lower(), sequence),
                source=self._source(
                    ["employee/v1/getEmployee"], clientId=self.client_id, employeeId=employee_id, position=sequence
                ),
                employee_id=employee_ref,
                company_id=self.company_id,
                purpose=purpose,
                funding=funding,
                account=BankAccount(
                    type=account_type,
                    routing_number=text(s.get("transitNum")),
                    account_last4=digits,
                    masked_at_source=was_masked if account_number else None,
                    bank_name=text(s.get("bankName")),
                ),
                method=method,
                amount=Money(amount=value, source_field=f"{prefix}.amount")
                if value is not None and not is_percent
                else None,
                percent=Percent(
                    percent=None,
                    scale=C.PercentScale.UNVERIFIED,
                    raw=str(value),
                    source_field=f"{prefix}.amount",
                )
                if value is not None and is_percent
                else None,
                limit=money(s.get("limit"), f"{prefix}.limit"),
                sequence=sequence,
                is_remainder=is_remainder(method.value),
                status=coded(P.DD_STATUS, s.get("status"), f"{prefix}.status", notes, C.DepositStatus.UNMAPPED),
                applies_to_pay_types=[a for a in applies if a],
                # Last, so every field read above is already marked.
                provider_extensions=sanitize_extensions({**shared, **s.leftovers()}),
                diagnostics=notes.items,
            ),
        )

    # -------------------------------------------------------------- deduction setup

    def _deductions(self, employee_id: str) -> None:
        seen: dict[tuple, DeductionElection] = {}
        first: dict[tuple, dict] = {}
        for endpoint, body_key in (
            ("deductions/v1/getDeductions", "employeeDeductions"),
            ("deductions/v1/getVoluntaryRecurringDeductions", "voluntaryDeduction"),
        ):
            for capture in self.bundle.ok(endpoint, clientId=self.client_id, employeeId=employee_id):
                for i, row in enumerate(((capture.body.get(body_key) or {}).get("deduction")) or []):
                    # The election's identity (code and dates), the same parts as its canonical ID.
                    key = (text(row.get("deductionCode")), text(row.get("startDate")), text(row.get("stopDate")))
                    if key in seen:
                        # The same election from a second endpoint: keep only the fields that differ.
                        repeat = Src(row, f"{body_key}.deduction[{i}]")
                        repeat.mark(
                            *(k for k, v in row.items() if first[key].get(k) == v),
                            why="the same value the first endpoint sent for this election",
                        )
                        differing = sanitize_extensions(repeat.leftovers())
                        seen[key].provider_extensions.update(differing)
                        if differing:
                            seen[key].diagnostics.append(
                                Diagnostic(
                                    code="SOURCE_CONFLICT",
                                    severity=C.Severity.WARNING,
                                    field=body_key,
                                    message="a second endpoint disagrees on this election; the first is "
                                    "mapped and the other values are kept: " + ", ".join(sorted(differing)),
                                )
                            )
                        seen[key].source.endpoints = sorted(set(seen[key].source.endpoints) | {endpoint})
                        continue
                    first[key] = row
                    seen[key] = self._election(Src(row, f"{body_key}.deduction[{i}]"), employee_id, endpoint)
        # getDeductions lists a loan's repayment with the loan's ID, and getEmployeeLoans the loan itself: one
        # election, so the two become one record (A-64).
        repaying: dict[tuple[str, str | None], DeductionElection] = {
            (e.code, e.loan_or_garnishment_id): e for e in seen.values() if e.loan_or_garnishment_id
        }
        for capture in self.bundle.ok(
            "deductions/v1/getEmployeeLoans", clientId=self.client_id, employeeId=employee_id
        ):
            for i, row in enumerate(capture.body.get("employeeLoanDetail") or []):
                s = Src(row, f"employeeLoanDetail[{i}]")
                loan = self._loan(s, employee_id)
                election = repaying.get((loan.code, loan.loan_or_garnishment_id))
                if election is None:
                    self.out.add("deduction_elections", loan)
                else:
                    self._merge_loan(election, loan, s.path)
        for election in seen.values():
            self.out.add("deduction_elections", election)
        for capture in self.bundle.ok(
            "employee/v1/getScheduledDeductions", clientId=self.client_id, employeeId=employee_id
        ):
            for i, row in enumerate(capture.body.get("scheduledDeduction") or []):
                self.out.add("deduction_elections", self._scheduled(Src(row, f"scheduledDeduction[{i}]"), employee_id))

    @staticmethod
    def _merge_loan(election: DeductionElection, loan: DeductionElection, path: str) -> None:
        """A loan joins the getDeductions election that repays it. getDeductions is mapped, as the first
        endpoint is for any election (A-64): the loan adds its details, and a value the two disagree on is kept
        and named in a SOURCE_CONFLICT warning."""
        election.loan = loan.loan
        election.source.endpoints = sorted(set(election.source.endpoints) | set(loan.source.endpoints))
        election.source.ids |= {k: v for k, v in loan.source.ids.items() if k not in election.source.ids}
        ours = election.calculation.amount if election.calculation else None
        theirs = loan.calculation.amount if loan.calculation else None
        differing: dict[str, Any] = {}
        if theirs is not None and (ours is None or ours.amount != theirs.amount):
            differing[f"{path}.paymentAmount"] = str(theirs.amount)
        for name, key in (("effective_from", "startDate"), ("effective_to", "stopDate")):
            value = getattr(loan, name)
            if value is not None and value != getattr(election, name):
                differing[f"{path}.{key}"] = value.isoformat()
        election.provider_extensions |= loan.provider_extensions | differing
        election.diagnostics += loan.diagnostics
        if differing:
            election.diagnostics.append(
                Diagnostic(
                    code="SOURCE_CONFLICT",
                    severity=C.Severity.WARNING,
                    field="employeeLoanDetail",
                    message="getEmployeeLoans disagrees on this loan's election; getDeductions is mapped and the "
                    "other values are kept: " + ", ".join(sorted(differing)),
                )
            )

    def _category(self, deduction_type: Any, field: str, notes: Notes):
        raw = text(deduction_type)
        mapped = P.DEDUCTION_TYPE.get(raw or "")
        if raw and not mapped:
            notes.warn("UNMAPPED_CODE", field, "unknown deduction type", raw)
        category = Coded[C.DeductionCategory](
            value=mapped[0] if mapped else C.DeductionCategory.UNMAPPED, raw=raw, source_field=field
        )
        return category, (mapped[1] if mapped else C.TaxTreatment.UNSPECIFIED), (mapped[2] if mapped else None)

    def _calculation(
        self, method_code: Any, field: str, value: Decimal | None, use_percent: bool | None, notes: Notes
    ) -> Calculation:
        raw = text(method_code)
        mapped = P.CALCULATION_METHOD.get(raw or "")
        if raw and not mapped:
            notes.warn("UNMAPPED_CODE", field, "unknown calculation method", raw)
        method = Coded[C.CalculationMethod](
            value=mapped[0] if mapped else C.CalculationMethod.UNMAPPED, raw=raw, source_field=field
        )
        basis = mapped[1] if mapped else C.CalculationBasis.UNSPECIFIED
        calc = Calculation(method=method, basis=basis, rounding=mapped[2] if mapped else None)
        if value is None or use_percent is None:
            return calc
        if use_percent:
            # Live, every percent deduction's paycheck lines equal percent / 100 x its base: points (A-29).
            calc.percent = Percent(percent=value, basis=basis, scale=C.PercentScale.VERIFIED_POINTS, raw=str(value))
        elif method.value is C.CalculationMethod.RATE_PER_HOUR:
            calc.rate = Rate(amount=value, per=C.RatePeriod.HOUR)
        else:
            calc.amount = Money(amount=value)
        return calc

    def _election(self, s: Src, employee_id: str, endpoint: str) -> DeductionElection:
        notes = Notes()
        code = text(s.get("deductionCode")) or ""
        category, treatment, catch_up = self._category(s.get("deductionType"), f"{s.path}.deductionType", notes)
        # Whether the amount is dollars or a percent decides what it means. The flag is documented "The default
        # is False", so a missing flag means dollars, said in a note; one that isn't a yes/no leaves the amount
        # raw in provider_extensions instead of guessed (A-73).
        amount, use_percent = decimal(s.data.get("amount")), None
        if amount is not None:
            if s.data.get("usePercent") in (None, ""):
                use_percent = False
                notes.info(
                    "DOCUMENTED_DEFAULT",
                    f"{s.path}.usePercent",
                    "not sent; documented default False, so the amount is dollars (EmployeeDeductions-Deduction)",
                )
            else:
                use_percent = known_flag(
                    s.get("usePercent"), f"{s.path}.usePercent", notes, "whether the amount is dollars or a percent"
                )
            if use_percent is not None:
                s.get("amount")
        calculation = self._calculation(
            s.get("deductionMethod"), f"{s.path}.deductionMethod", amount, use_percent, notes
        )
        match_method = text(s.get("matchMethod"))
        match = None
        if match_method:
            value = decimal(s.get("matchAmount"))
            m = coded(
                P.MATCH_METHOD,
                match_method,
                f"{s.path}.matchMethod",
                notes,
                C.CalculationMethod.UNMAPPED,
                empty_is_none=False,
            )
            match = EmployerMatch(
                method=m,
                description=text(s.get("matchDescription")),
                amount=Money(amount=value)
                if value is not None and m.value is C.CalculationMethod.FIXED_AMOUNT
                else None,
                percent=Percent(percent=None, scale=C.PercentScale.UNVERIFIED, raw=str(value))
                if value is not None and m.value is C.CalculationMethod.PERCENT
                else None,
            )
        limits = DeductionLimits(
            per_period=money(s.get("limit")),
            maximum=money(s.get("maximum")),
            maximum_basis=coded(P.LIMIT_BASIS, s.get("basis"), f"{s.path}.basis", notes, C.LimitBasis.UNMAPPED),
        )
        start = text(s.get("startDate"))
        return DeductionElection(
            id=self._id(
                "deduction_election",
                self.client_id,
                employee_id,
                code,
                start or "open",
                text(s.data.get("stopDate")) or "open",
            ),
            source=self._source([endpoint], clientId=self.client_id, employeeId=employee_id, deductionCode=code),
            employee_id=self._id("employee", self.client_id, employee_id),
            company_id=self.company_id,
            code=code,
            label=text(s.get("description")) or self._label("deductionCode", code, "description"),
            category=category,
            tax_treatment=treatment,
            catch_up=catch_up,
            calculation=calculation,
            limits=limits if any(v is not None for v in limits.model_dump().values()) else None,
            frequency=Coded[str](value="UNMAPPED", raw=text(s.get("period")), source_field=f"{s.path}.period")
            if text(s.data.get("period"))
            else None,
            effective_from=iso_date(start, f"{s.path}.startDate", notes),
            effective_to=iso_date(s.get("stopDate"), f"{s.path}.stopDate", notes),
            employer_match=match,
            arrears_tracking=flag(s.get("trackArrears")),
            mandatory=flag(s.get("mandatory")),
            benefit_plan_id=text(s.get("benefitPlanId")),
            loan_or_garnishment_id=text(s.get("loanOrGarnishId")),
            provider_extensions=sanitize_extensions(s.leftovers()),
            diagnostics=notes.items,
        )

    def _scheduled(self, s: Src, employee_id: str) -> DeductionElection:
        notes = Notes()
        code = text(s.get("deductionCode")) or ""
        deduction_type = self.codes.get("deductionCode", {}).get(code, {}).get("type")
        category, treatment, catch_up = self._category(deduction_type, "clientCodes.deductionCode[].type", notes)
        amount = decimal(s.get("amount"))
        start = text(s.get("startDate"))
        return DeductionElection(
            id=self._id("deduction_election", self.client_id, employee_id, "scheduled", code, start or "open"),
            source=self._source(
                ["employee/v1/getScheduledDeductions"],
                clientId=self.client_id,
                employeeId=employee_id,
                deductionCode=code,
            ),
            employee_id=self._id("employee", self.client_id, employee_id),
            company_id=self.company_id,
            code=code,
            label=text(s.get("checkStubDescription")) or self._label("deductionCode", code, "description"),
            category=category,
            tax_treatment=treatment,
            catch_up=catch_up,
            calculation=Calculation(
                method=Coded[C.CalculationMethod](
                    value=C.CalculationMethod.FIXED_AMOUNT, source_field=f"{s.path}.amount"
                ),
                amount=Money(amount=amount, source_field=f"{s.path}.amount") if amount is not None else None,
            ),
            status=coded(P.SCHEDULED_STATUS, s.get("status"), f"{s.path}.status", notes, C.ElectionStatus.UNMAPPED),
            effective_from=iso_date(start, f"{s.path}.startDate", notes),
            effective_to=iso_date(s.get("stopDate"), f"{s.path}.stopDate", notes),
            provider_extensions=sanitize_extensions(s.leftovers()),
            diagnostics=notes.items,
        )

    def _loan(self, s: Src, employee_id: str) -> DeductionElection:
        notes = Notes()
        code = text(s.get("deductionCode")) or ""
        loan_id = text(s.get("loanId")) or ""
        deduction_type = self.codes.get("deductionCode", {}).get(code, {}).get("type") or "L"
        category, treatment, catch_up = self._category(deduction_type, "clientCodes.deductionCode[].type", notes)
        frequency_raw = text(s.get("paymentFreq"))
        # Dates are documented as YYYY-DD-MM but arrive as YYYY-MM-DD (A-17); parsed as ISO.
        return DeductionElection(
            id=self._id("deduction_election", self.client_id, employee_id, "loan", loan_id),
            source=self._source(
                ["deductions/v1/getEmployeeLoans"], clientId=self.client_id, employeeId=employee_id, loanId=loan_id
            ),
            employee_id=self._id("employee", self.client_id, employee_id),
            company_id=self.company_id,
            code=code,
            label=self._label("deductionCode", code, "description") or text(s.get("loanReason")),
            category=category,
            tax_treatment=treatment,
            catch_up=catch_up,
            calculation=Calculation(
                method=Coded[C.CalculationMethod](
                    value=C.CalculationMethod.FIXED_AMOUNT, source_field=f"{s.path}.paymentAmount"
                ),
                amount=money(s.get("paymentAmount"), f"{s.path}.paymentAmount"),
            ),
            effective_from=iso_date(s.get("startDate"), f"{s.path}.startDate", notes),
            effective_to=iso_date(s.get("stopDate"), f"{s.path}.stopDate", notes),
            loan_or_garnishment_id=loan_id or None,
            loan=LoanDetails(
                principal=money(s.get("loanAmount"), f"{s.path}.loanAmount"),
                payback_amount=money(s.get("paybackAmount"), f"{s.path}.paybackAmount"),
                paid_to_date=money(s.get("paidAmount"), f"{s.path}.paidAmount"),
                payment_amount=money(s.data.get("paymentAmount")),
                payment_frequency=Coded[str](
                    value=P.LOAN_FREQUENCY.get(frequency_raw, "UNMAPPED"),
                    raw=frequency_raw,
                    source_field=f"{s.path}.paymentFreq",
                )
                if frequency_raw
                else None,
                loan_date=iso_date(s.get("loanDate"), f"{s.path}.loanDate", notes),
                reason=text(s.get("loanReason")),
            ),
            provider_extensions=sanitize_extensions(s.leftovers()),
            diagnostics=notes.items,
        )

    def _retirement_loans(self) -> list[DeductionElection]:
        """Loans against a retirement plan, for the whole client. Each is repaid by a payroll deduction:
        paymentAmount is the "amount employee will pay back per pay period", starting on deductionStarts. The
        response names no deduction code, so `code` is empty and the plan is `benefit_plan_id` (A-87)."""
        elections = []
        for capture in self.bundle.ok("benefits/v1/getRetirementLoans", clientId=self.client_id):
            for i, row in enumerate(capture.body.get("retirementLoan") or []):
                notes = Notes()
                s = Src(row, f"retirementLoan[{i}]")
                employee_id = text(s.get("employeeId")) or ""
                loan_id = text(s.get("loanId")) or ""
                payment = money(s.get("paymentAmount"), f"{s.path}.paymentAmount")
                elections.append(
                    DeductionElection(
                        id=self._id("deduction_election", self.client_id, employee_id, "retirement-loan", loan_id),
                        source=self._source(
                            ["benefits/v1/getRetirementLoans"],
                            clientId=self.client_id,
                            employeeId=employee_id,
                            loanId=loan_id,
                        ),
                        employee_id=self._id("employee", self.client_id, employee_id),
                        company_id=self.company_id,
                        code="",
                        label=text(s.get("loanReason")),
                        category=Coded[C.DeductionCategory](
                            value=C.DeductionCategory.RETIREMENT_LOAN, source_field="retirementLoan[]"
                        ),
                        calculation=Calculation(
                            method=Coded[C.CalculationMethod](
                                value=C.CalculationMethod.FIXED_AMOUNT, source_field=f"{s.path}.paymentAmount"
                            ),
                            amount=payment,
                        )
                        if payment is not None
                        else None,
                        effective_from=iso_date(s.get("deductionStarts"), f"{s.path}.deductionStarts", notes),
                        benefit_plan_id=text(s.get("planId401k")),
                        loan_or_garnishment_id=loan_id or None,
                        loan=LoanDetails(
                            principal=money(s.get("loanAmount"), f"{s.path}.loanAmount"),
                            payback_amount=money(s.get("paybackAmount"), f"{s.path}.paybackAmount"),
                            paid_to_date=money(s.get("amtPaidBackToDate"), f"{s.path}.amtPaidBackToDate"),
                            payment_amount=payment,
                            loan_date=iso_date(s.get("loanDate"), f"{s.path}.loanDate", notes),
                            reason=text(s.data.get("loanReason")),
                        ),
                        provider_extensions=sanitize_extensions(s.leftovers()),
                        diagnostics=notes.items,
                    )
                )
        return elections

    # -------------------------------------------------------------- payroll runs

    def _payroll_runs(self) -> dict[str, str]:
        # batch ID -> (batch list row, batch info, endpoints); each response keeps its own read record.
        batches: dict[str, tuple[dict, dict, list[str]]] = {}
        for capture in self.bundle.ok("payroll/v1/getBatchListByDate", clientId=self.client_id):
            for row in capture.body.get("batchList") or []:
                batch_id = text((row or {}).get("batchId"))
                if batch_id and batch_id not in batches:
                    batches[batch_id] = (row, {}, ["payroll/v1/getBatchListByDate"])
        for capture in self.bundle.ok("payroll/v1/getBatchInfo", clientId=self.client_id):
            control = capture.body.get("batchControl") or {}
            batch_id = text(control.get("batchId"))
            if batch_id:
                row, _, endpoints = batches.get(batch_id, ({}, {}, []))
                batches[batch_id] = (row, control, endpoints + ["payroll/v1/getBatchInfo"])
        runs = {}
        for batch_id, (row, control, endpoints) in sorted(batches.items()):
            notes = Notes()
            s = Src(row)
            info = Src(control, "batchInfo")
            groups = []
            for g in s.children("payGroup"):
                groups.append(
                    RunPayGroup(
                        pay_group=text(g.get("payGroupId")) or "",
                        period=DateRange(
                            start=iso_date(g.get("payPeriodStartDate"), g.path, notes),
                            end=iso_date(g.get("payPeriodEndDate"), g.path, notes),
                        ),
                        weeks_worked=text(g.get("weeksWorked")),
                        deduction_period=text(g.get("deductPeriod")),
                    )
                )
            if not groups:
                for g in info.children("voucher"):
                    groups.append(
                        RunPayGroup(
                            pay_group=text(g.get("payGroupId")) or "",
                            period=DateRange(
                                start=iso_date(g.get("periodStart"), g.path, notes),
                                end=iso_date(g.get("periodEnd"), g.path, notes),
                            ),
                            weeks_worked=text(g.get("weeksWorked")),
                            deduction_period=text(g.get("deductPeriod")),
                        )
                    )
            run_id = self._id("payroll_run", self.client_id, batch_id)
            runs[batch_id] = run_id
            batch_type = s.get("batchType") if "batchType" in row else info.get("batchType")
            self.out.add(
                "payroll_runs",
                PayrollRun(
                    id=run_id,
                    source=self._source(endpoints, clientId=self.client_id, batchId=batch_id),
                    company_id=self.company_id,
                    pay_date=iso_date(s.get("payDate") or info.get("payDate"), "batchList[].payDate", notes),
                    description=text(info.get("batchDescription")),
                    type=coded(
                        P.BATCH_TYPE,
                        batch_type,
                        "batchList[].batchType",
                        notes,
                        C.PayrollRunType.UNMAPPED,
                        empty_is_none=False,
                    ),
                    status=coded(
                        P.BATCH_STATUS,
                        s.get("batchStatus") or info.get("batchStatus"),
                        "batchList[].batchStatus",
                        notes,
                        C.PayrollRunStatus.UNMAPPED,
                    ),
                    pay_groups=groups,
                    # Last, so every field read above is already marked.
                    provider_extensions=sanitize_extensions({**s.leftovers(), **info.leftovers()}),
                    diagnostics=notes.items,
                ),
            )
        return runs

    # -------------------------------------------------------------- pay statements

    def _pay_statements(self, runs: dict[str, str], employees: set[str]) -> None:
        seen: set[str] = set()
        for capture in self.bundle.ok("payroll/v1/getPayrollVoucherForBatch", clientId=self.client_id):
            # Live key is payrollVoucher; the spec documents payrollVouchers (A-16).
            rows = capture.body.get("payrollVoucher") or capture.body.get("payrollVouchers") or []
            for row in rows:
                voucher_id = text((row or {}).get("voucherId"))
                if voucher_id and voucher_id not in seen:
                    seen.add(voucher_id)
                    self._pay_statement(Src(row), voucher_id, runs, employees)

    def _pay_class(self, code: Any, line_class: Any, field: str, notes: Notes) -> Coded[C.EarningKind]:
        raw = text(line_class)
        source_field = field
        if raw is None:
            raw = text((self.codes.get("payCode", {}).get(str(code)) or {}).get("payClass"))
            source_field = "clientCodes.payCode[].payClass"
        return coded(P.PAY_CLASS, raw, source_field, notes, C.EarningKind.UNMAPPED, empty_is_none=False)

    def _earning_category(
        self, code: str | None, kind: Coded[C.EarningKind], notes: Notes
    ) -> Coded[C.EarningCategory] | None:
        """PrismHR's own category of the pay code (talxPayType), or Doubletime from its rate class; a pay
        code with neither is the customer's own, left UNMAPPED for review (A-67)."""
        if not categorized(kind):
            return None
        definition = self.codes.get("payCode", {}).get(str(code)) or {}
        talx, rate_class = text(definition.get("talxPayType")), text(definition.get("rateClass"))
        if rate_class == P.RATE_CLASS_DOUBLETIME and talx in (None, "O"):
            return Coded[C.EarningCategory](
                value=C.EarningCategory.DOUBLE_TIME, raw=rate_class, source_field="clientCodes.payCode[].rateClass"
            )
        if talx is not None:
            return coded(P.TALX_PAY_TYPE, talx, "clientCodes.payCode[].talxPayType", notes, C.EarningCategory.UNMAPPED)
        return customer_category(code, self._label("payCode", code, "payDescription"), "clientCodes.payCode[].id")

    @staticmethod
    def _tax_type(
        code: str | None, label: str | None, field: str, notes: Notes
    ) -> tuple[Coded[C.TaxType] | None, str | None]:
        """Federal codes exactly; state and local codes by their tax number (A-68). A state tax's state is
        the one its description starts with ("WI Income Tax", "ALASKA SUTA EE")."""
        found: tuple[C.TaxType, str | None] | None = None
        if code in P.FEDERAL_TAX:
            found = (P.FEDERAL_TAX[code], None)
        elif (state_code := re.fullmatch(r"(\d{2})-(\d{2})", code or "")) and state_code[1] != "00":
            value = P.STATE_TAX.get(state_code[2])
            found = (value, _leading_state(label)) if value else None
        elif local_code := re.fullmatch(r"\d{5}(?:\d{4})?-(\d{2})", code or ""):
            value = P.LOCAL_TAX.get(local_code[1])
            found = (value, None) if value else None
        return tax_type(found, code, field, notes, label)

    def _quantity_unit(self, code: Any) -> C.QuantityUnit:
        reason = text((self.codes.get("payCode", {}).get(str(code)) or {}).get("payReason"))
        return P.PAY_REASON.get(reason or "", C.QuantityUnit.UNKNOWN)

    def _pay_statement(self, s: Src, voucher_id: str, runs: dict[str, str], employees: set[str]) -> None:
        notes = Notes()
        employee_id = text(s.get("employeeId")) or ""
        batch_id = text(s.get("batchId"))
        run_id = runs.get(batch_id or "")
        if batch_id and not run_id:
            notes.info("RUN_NOT_IN_BUNDLE", "batchId", "the voucher's batch is not in the bundle", batch_id)
        if employee_id not in employees:
            notes.info(
                "EMPLOYEE_NOT_IN_BUNDLE", "employeeId", "employee record was not fetched into this bundle", employee_id
            )

        earnings, unknown_units = [], set()
        for line in s.children("earning"):
            code = text(line.get("payCode"))
            unit = self._quantity_unit(code)
            if unit is C.QuantityUnit.UNKNOWN:
                unknown_units.add(code)
            quantity = decimal(line.get("hoursUnits"))
            rate = decimal(line.get("unitRate"))
            allocation = {
                k: v
                for k in (
                    "division",
                    "jobCode",
                    "shift",
                    "department",
                    "location",
                    "projWork",
                    "projPhase",
                    "workComp",
                    "glCode",
                )
                if (v := text(line.get(k)))
            }
            worked = decimal(line.data.get("hoursWorked"))
            if worked not in (None, ZERO):  # 0 hours worked is reported as none; the 0 stays as sent (A-73)
                line.get("hoursWorked")
            kind = self._pay_class(code, line.get("payClass"), "earning[].payClass", notes)
            earnings.append(
                EarningLine(
                    code=code,
                    label=self._label("payCode", code, "payDescription") or text(line.get("payClassDescription")),
                    in_gross=True,
                    kind=kind,
                    category=self._earning_category(code, kind, notes),
                    quantity=Quantity(value=quantity, unit=unit, source_field="earning[].hoursUnits")
                    if quantity is not None
                    else None,
                    hours_worked=Quantity(value=worked, unit=C.QuantityUnit.HOURS, source_field="earning[].hoursWorked")
                    if worked not in (None, ZERO)
                    else None,
                    rate=Rate(
                        amount=rate,
                        per={C.QuantityUnit.HOURS: C.RatePeriod.HOUR, C.QuantityUnit.UNITS: C.RatePeriod.UNIT}.get(
                            unit, C.RatePeriod.UNMAPPED
                        ),
                        source_field="earning[].unitRate",
                    )
                    if rate is not None
                    else None,
                    amount=line_amount(line.get("payAmount"), "earning[].payAmount", notes),
                    allocation=allocation,
                    source_field="earning[]",
                )
            )
        for line in s.children("otherEarningsDetail"):
            code = text(line.get("otherEarnCode"))
            kind = self._pay_class(code, None, "otherEarningsDetail[].otherEarnCode", notes)
            earnings.append(
                EarningLine(
                    code=code,
                    label=text(line.get("otherEarnsDesc")) or self._label("payCode", code, "payDescription"),
                    in_gross=True,
                    kind=kind,
                    category=self._earning_category(code, kind, notes),
                    amount=line_amount(line.get("otherEarnAmount"), "otherEarningsDetail[].otherEarnAmount", notes),
                    source_field="otherEarningsDetail[]",
                )
            )
        if unknown_units:
            notes.info(
                "QUANTITY_UNIT_UNKNOWN",
                "earning[].hoursUnits",
                "pay code has no payReason in the client code table; hours vs units unknown (A-38)",
                ",".join(sorted(c for c in unknown_units if c)),
            )

        taxes = []
        for side, prefix, paid_by in (
            ("employeeTax", "emp", C.TaxPaidBy.EMPLOYEE),
            ("companyTax", "com", C.TaxPaidBy.EMPLOYER),
        ):
            for t in s.children(side):
                code, label = text(t.get(f"{prefix}TaxDeductCode")), text(t.get(f"{prefix}TaxDeductCodeDesc"))
                tax_kind, state = self._tax_type(code, label, f"{side}[].{prefix}TaxDeductCode", notes)
                taxes.append(
                    TaxLine(
                        code=code,
                        label=label,
                        type=tax_kind,
                        state=state,
                        paid_by=paid_by,
                        amount=line_amount(t.get(f"{prefix}TaxAmount"), f"{side}[].{prefix}TaxAmount", notes),
                        taxable_wages=money(t.get(f"{prefix}TaxableAmount")),
                        source_field=f"{side}[]",
                    )
                )

        deductions = []
        for d in s.children("deduction"):
            category, treatment, _ = self._category(d.get("deductType"), "deduction[].deductType", notes)
            deductions.append(
                DeductionLine(
                    code=text(d.get("deductCode")),
                    label=text(d.get("deductDescription")),
                    category=category,
                    tax_treatment=treatment,
                    employee_amount=line_amount(d.get("deductAmount"), "deduction[].deductAmount", notes),
                    source_field="deduction[]",
                )
            )
        for d in s.children("otherDeduction"):
            code = text(d.get("otherDeductCode"))
            category, treatment, _ = self._category(
                self.codes.get("deductionCode", {}).get(code or "", {}).get("type"),
                "clientCodes.deductionCode[].type",
                notes,
            )
            deductions.append(
                DeductionLine(
                    code=code,
                    label=text(d.get("otherDeductDescription")),
                    category=category,
                    tax_treatment=treatment,
                    employee_amount=line_amount(
                        d.get("otherDeductAmount"), "otherDeduction[].otherDeductAmount", notes
                    ),
                    source_field="otherDeduction[]",
                )
            )

        contributions = [
            ContributionLine(
                code=text(c.get("code")),
                label=text(c.get("description")),
                amount=line_amount(c.get("amount"), "employerContributions[].amount", notes),
                source_field="employerContributions[]",
            )
            for c in s.children("employerContributions")
        ]
        benefits = [
            BenefitDetail(
                plan=text(b.get("planId")),
                coverage_period=text(b.get("coveragePeriod")),
                premium=money(b.get("premiumAmt")),
                premium_cost=money(b.get("premiumCost")),
                employee_contribution=money(b.get("empContrib")),
                employee_deduction=money(b.get("empDeduct")),
                source_field="benefit[]",
            )
            for b in s.children("benefit")
        ]

        retirement = None
        r = s.child("retirement")
        if r is not None:
            amounts = {
                name: Money(amount=amt, source_field=f"retirement.{field}")
                for field, name in RETIREMENT_FIELDS.items()
                if (amt := decimal(r.get(field))) is not None
            }
            plan = text(r.get("planId"))
            if plan or any(m.amount != ZERO for m in amounts.values()):
                retirement = RetirementSummary(
                    plan=plan, base_earnings=money(r.get("baseEarnings"), "retirement.baseEarnings"), amounts=amounts
                )

        payments = []
        for d in s.children("directDeposit"):
            account = text(d.get("accountNum"))
            digits, was_masked = last4(account)
            payments.append(
                PaymentLine(
                    kind=Coded[C.PaymentKind](value=C.PaymentKind.DIRECT_DEPOSIT, source_field="directDeposit[]"),
                    amount=line_amount(d.get("amount"), "directDeposit[].amount", notes),
                    routing_number=text(d.get("transitNum")),
                    account_last4=digits,
                    masked_at_source=was_masked if account else None,
                    status=text(d.get("status")),
                    source_field="directDeposit[]",
                )
            )
        check_amount = decimal(s.data.get("checkAmt"))
        if check_amount is not None and check_amount != ZERO:  # a 0 is no paper check, and stays as sent (A-73)
            s.get("checkAmt")
            payments.append(
                PaymentLine(
                    kind=Coded[C.PaymentKind](value=C.PaymentKind.CHECK, source_field="checkAmt"),
                    amount=Money(amount=check_amount),
                    source_field="checkAmt",
                )
            )

        # totalEarnings includes non-cash pay classes (A-32), so it is gross wages; gross pay is derived (A-54).
        wages = money(s.get("totalEarnings"), "totalEarnings")
        net = decimal(s.get("netPay"))
        totals = PayStatementTotals(
            gross_wages=wages,
            gross_pay=paid_gross(wages, earnings, "totalEarnings", notes),
            net_pay=Money(amount=net, source_field="netPay") if net is not None else None,
            employee_taxes=derived_sum(
                [t.amount for t in taxes if t.paid_by is C.TaxPaidBy.EMPLOYEE], "sum(employeeTax[].empTaxAmount)"
            ),
            employer_taxes=derived_sum(
                [t.amount for t in taxes if t.paid_by is C.TaxPaidBy.EMPLOYER], "sum(companyTax[].comTaxAmount)"
            ),
            deductions=derived_sum(
                [d.employee_amount for d in deductions if d.employee_amount],
                "sum(deduction[].deductAmount) + sum(otherDeduction[].otherDeductAmount)",
            ),
            employer_contributions=derived_sum(
                [c.amount for c in contributions], "sum(employerContributions[].amount)"
            ),
        )
        void_date = iso_date(s.get("voidDate"), "voidDate", notes)
        statement = PayStatement(
            id=self._id("pay_statement", self.client_id, voucher_id),
            source=self._source(
                ["payroll/v1/getPayrollVoucherForBatch"],
                clientId=self.client_id,
                voucherId=voucher_id,
                batchId=batch_id,
            ),
            company_id=self.company_id,
            employee_id=self._id("employee", self.client_id, employee_id),
            payroll_run_id=run_id,
            pay_date=iso_date(s.get("payDate"), "payDate", notes),
            period=DateRange(
                start=iso_date(s.get("payPeriodStart"), "payPeriodStart", notes),
                end=iso_date(s.get("payPeriodEnd"), "payPeriodEnd", notes),
            ),
            check_number=text(s.first("checkNumber", "checkNum")),
            type=coded(P.VOUCHER_TYPE, s.get("type"), "type", notes, C.PayStatementType.UNMAPPED, empty_is_none=False),
            status=unmapped_label(s.get("status"), None, "status"),
            voided=void_date is not None,
            void_date=void_date,
            totals=totals,
            earnings=earnings,
            taxes=taxes,
            deductions=deductions,
            employer_contributions=contributions,
            benefit_details=benefits,
            retirement=retirement,
            payments=payments,
            provider_extensions=sanitize_extensions(s.leftovers()),
            diagnostics=notes.items,
        )
        attach_checks(statement)
        self.out.add("pay_statements", statement)


def _leading_state(label: str | None) -> str | None:
    """The state a tax description starts with, as a USPS code or a full name ("WI Income Tax", "ALASKA SUTA EE")."""
    words = (label or "").replace(",", " ").split()
    for n in range(min(3, len(words)), 0, -1):
        if state := us_state(" ".join(words[:n])):
            return state
    return None
