"""isolved: raw bundle in, canonical records out.

An isolved legal company is the company, with its client kept as the parent (A-30). isolved
sends descriptions instead of codes; codes.py maps the exact texts of provider-level lookups.
IDs live in the request path, so they are read from each capture's path.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from normalization.bundle import Bundle, Capture
from normalization.canonical import codes as C
from normalization.canonical.records import (
    Address,
    BankAccount,
    BenefitDetail,
    Calculation,
    Company,
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
    EmployerRef,
    EmploymentChange,
    FrequencyInfo,
    GarnishmentDetails,
    Identifier,
    JobChange,
    OrgAssignment,
    OrgUnit,
    PayGroup,
    PaymentLine,
    PayrollRun,
    PayStatement,
    PayStatementTotals,
    PersonName,
    Phone,
    RunPayGroup,
    TaxLine,
)
from normalization.canonical.types import (
    Coded,
    DateRange,
    Money,
    NationalId,
    Percent,
    Quantity,
    Rate,
    Source,
    TaxIdentifier,
    coded_type,
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
    line_amount,
    money,
    tax_type,
    unmasked_date,
    us_state,
)
from . import codes as I

PROVIDER = "isolved"
_IDS = re.compile(
    r"api/(?:corestream/)?clients/(?P<client>[^/]+)"
    r"(?:/legals/(?P<legal>[^/]+))?"
    r"(?:/(?:employees)/(?P<employee>[^/]+))?"
    r"(?:/checks/(?P<check>[^/]+))?"
    r"(?:/paygroupId/(?P<group>[^/]+))?"
    r"(?:/payrollRunHistory/(?P<run>[^/]+))?"
)
_PERIODS_PER_YEAR = re.compile(r"^(\d+) Pay Periods Per Year$")
E = "api/clients/{client}/legals/{legal}/employees/{id}"
# Responses about one employee read into the employee record, besides the employee itself (A-76, A-77, A-81).
PER_EMPLOYEE = (E + "/salaries", E + "/statuses", E + "/jobs", E + "/categories", E + "/contacts", E + "/veteranStatus")


def path_ids(capture: Capture) -> dict[str, str]:
    match = _IDS.match(capture.path)
    return {k: v for k, v in (match.groupdict() if match else {}).items() if v}


def request_scope(capture: Capture) -> list[tuple[str, dict[str, str]]]:
    """The records a request feeds, by the IDs in their Source.ids: its employee, else its company (A-70)."""
    ids = path_ids(capture)
    if not ids.get("client"):
        return []  # system lookups
    company = {"clientId": ids["client"]} | ({"legalId": ids["legal"]} if ids.get("legal") else {})
    employee = [("employees", company | {"employeeId": ids["employee"]})] if ids.get("employee") else []
    return employee + [("companies", company)]


def without_links(extensions: dict[str, Any]) -> dict[str, Any]:
    """Hypermedia links are API navigation, not data, and are not kept (model §9)."""
    return {k: v for k, v in extensions.items() if not re.search(r"(^|\.)links\[", k)}


def normalize(bundle: Bundle, as_of: date | None = None) -> Output:
    out = Output()
    legals = {(str(c["client_id"]), str(c["legal_id"])) for c in bundle.companies if c.get("legal_id")}
    for capture in bundle.captures:
        ids = path_ids(capture)
        if ids.get("client") and ids.get("legal"):
            legals.add((ids["client"], ids["legal"]))
    for client_id, legal_id in sorted(legals):
        legal = _Legal(bundle, client_id, legal_id, out)
        with company_scope(legal.company_id):
            legal.run()
    return out


class _Legal:
    def __init__(self, bundle: Bundle, client_id: str, legal_id: str, out: Output):
        self.bundle, self.client_id, self.legal_id, self.out = bundle, client_id, legal_id, out
        self.tenant = bundle.tenant_id
        self.company_id = self._id("company", client_id, legal_id)
        self.frequencies = {
            str(row.get("id")): text(row.get("description"))
            for capture in bundle.ok("api/lookup/Frequencies")
            for row in (capture.body if isinstance(capture.body, list) else [])
        }
        self.pay_items = {
            text(row.get("title")): row
            for capture in self._captures("api/clients/{client}/payItems", legal=False)
            for row in (capture.body if isinstance(capture.body, list) else [])
            if text(row.get("title"))
        }
        self.runs_by_key: dict[tuple, list[str]] = {}
        # Lookup code -> description, for fields the spec types as codes but live sends as text (A-52).
        self.lookups = {
            name: {
                str(row.get("id")): text(row.get("description"))
                for capture in bundle.ok(f"api/lookup/{name}")
                for row in (capture.body if isinstance(capture.body, list) else [])
            }
            for name in ("genders", "maritalStatuses", "citizenships", "ContactRelationshipCodes")
        }

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

    def _captures(self, endpoint: str, *, legal: bool = True, **want: str):
        for capture in self.bundle.ok(endpoint):
            ids = path_ids(capture)
            if ids.get("client") != self.client_id or (legal and ids.get("legal") != self.legal_id):
                continue
            if all(ids.get(k) == v for k, v in want.items()):
                yield capture

    def _body_list(self, endpoint: str, **want: str) -> list[dict]:
        rows: list[dict] = []
        for capture in self._captures(endpoint, legal=True, **want):
            body = capture.body
            rows += body if isinstance(body, list) else (body.get("results") or [])
        return [r for r in rows if isinstance(r, dict)]

    def _frequency(self, frequency_id: Any, field: str, notes: Notes, description: Any = None) -> FrequencyInfo | None:
        raw = text(frequency_id)
        if raw is None:
            return None
        label = text(description) or self.frequencies.get(raw)
        known = I.FREQUENCY.get(label or "")
        periods = _PERIODS_PER_YEAR.match(label or "")
        if known:
            value, per_year = known
        elif periods:
            value, per_year = C.PayFrequency.OTHER, int(periods.group(1))
        else:
            value, per_year = C.PayFrequency.UNMAPPED, None
            notes.warn("UNMAPPED_CODE", field, "frequency description not in the Frequencies lookup table", raw)
        return FrequencyInfo(
            frequency=Coded[C.PayFrequency](value=value, raw=raw, label=label, source_field=field),
            periods_per_year=per_year,
        )

    def _described(self, lookup: str, value: Any) -> str | None:
        """The lookup description: live sends it directly; the spec's code form is translated."""
        raw = text(value)
        return self.lookups.get(lookup, {}).get(raw, raw) if raw else None

    def _lookup_coded(self, lookup: str, table: dict, value: Any, field: str, notes: Notes, unmapped):
        """Map by the lookup description, keeping exactly what was sent as the raw value (A-52)."""
        raw = text(value)
        if raw is None:
            return None
        description = self._described(lookup, raw)
        if description not in table:
            notes.warn("UNMAPPED_CODE", field, "not in the provider lookup table", raw)
        return coded_type(type(unmapped))(
            value=table.get(description, unmapped), raw=raw, label=description, source_field=field
        )

    def _classify(self, pay_item_name: Any) -> tuple[Coded[C.DeductionCategory] | None, C.TaxTreatment]:
        """Category from the client pay item's system classification, linked by title (A-49)."""
        item = self.pay_items.get(text(pay_item_name))
        if not item:
            return None, C.TaxTreatment.UNSPECIFIED
        benefit, kind = text(item.get("systemBenefitType")), text(item.get("systemPayItemType"))
        mapped = I.DEDUCTION_CLASS.get((benefit, kind)) or I.DEDUCTION_CLASS.get((benefit, None))
        if mapped is None and benefit is None:
            mapped = I.DEDUCTION_CLASS.get((None, kind))
        category, treatment = mapped if mapped else (C.DeductionCategory.UNMAPPED, C.TaxTreatment.UNSPECIFIED)
        if treatment is C.TaxTreatment.UNSPECIFIED and kind and any(m in kind.lower() for m in I.POST_TAX_MARKERS):
            treatment = C.TaxTreatment.POST_TAX
        raw = " / ".join(v for v in (benefit, kind) if v)
        return (
            Coded[C.DeductionCategory](
                value=category,
                raw=raw or None,
                label=kind,
                source_field="clientPayItems[].systemBenefitType+systemPayItemType",
            ),
            treatment,
        )

    def _earning_kind(self, title: str | None, memo: bool, notes: Notes) -> Coded[C.EarningKind]:
        """Memo lines by their flag; the rest from the client pay item's system classification (A-53)."""
        if memo:
            return Coded[C.EarningKind](value=C.EarningKind.MEMO, raw=True, source_field="earnings[].isMemoEarning")
        item = self.pay_items.get(title or "") or {}
        benefit, kind = text(item.get("systemBenefitType")), text(item.get("systemPayItemType"))
        value = I.EARNING_BENEFIT_CLASS.get(benefit or "") or I.EARNING_CLASS.get(kind or "")
        raw = " / ".join(v for v in (benefit, kind) if v) or None
        if value is None:
            notes.warn(
                "UNMAPPED_CODE",
                "clientPayItems[].systemBenefitType+systemPayItemType",
                f"no system earning classification for pay item {title!r}",
                raw,
            )
        return Coded[C.EarningKind](
            value=value or C.EarningKind.UNMAPPED,
            raw=raw,
            label=kind,
            source_field="clientPayItems[].systemBenefitType+systemPayItemType",
        )

    def _earning_category(
        self, title: str | None, kind: Coded[C.EarningKind], notes: Notes
    ) -> Coded[C.EarningCategory] | None:
        """From the system earning the client pay item is built on, else its system benefit type (A-67)."""
        if not categorized(kind):
            return None
        item = self.pay_items.get(title or "") or {}
        benefit, system = text(item.get("systemBenefitType")), text(item.get("systemPayItemType"))
        if system is None and benefit is None:  # no client pay item to classify it; the kind already warns
            return customer_category(title, None, "earnings[].itemDescription")
        value = I.EARNING_CATEGORY.get(system or "") or I.EARNING_BENEFIT_CATEGORY.get(benefit or "")
        if value is None:
            notes.warn(
                "UNMAPPED_CODE", "clientPayItems[].systemPayItemType", "no category for this system earning", system
            )
        return Coded[C.EarningCategory](
            value=value or C.EarningCategory.UNMAPPED,
            raw=system or benefit,
            label=title,
            source_field="clientPayItems[].systemPayItemType",
        )

    @staticmethod
    def _tax_type(description: str | None, notes: Notes) -> tuple[Coded[C.TaxType] | None, str | None]:
        """Federal taxes by exact description, state taxes as "<state> <tax>" (A-68)."""
        found: tuple[C.TaxType, str | None] | None = None
        words = (description or "").split()
        if description in I.FEDERAL_TAX:
            found = (I.FEDERAL_TAX[description], None)
        else:
            for n in (2, 1):  # "SUI ER" before "WH"
                tax, state = " ".join(words[-n:]), us_state(" ".join(words[:-n]))
                if len(words) > n and tax in I.STATE_TAX and state:
                    found = (I.STATE_TAX[tax], state)
                    break
        return tax_type(found, description, "taxes[].itemDescription", notes)

    # -------------------------------------------------------------- run

    def run(self) -> None:
        self._company()
        checks_by_employee = self._check_bodies()
        employees = set()
        for capture in self._captures(E):
            employee_id = path_ids(capture).get("employee")
            if isinstance(capture.body, dict) and employee_id and employee_id not in employees:
                employees.add(employee_id)
                self._employee(Src(capture.body), employee_id, checks_by_employee.get(employee_id, []))
                self._deposits(employee_id)
                self._elections(employee_id)
        self._payroll_runs()
        self._pay_statements(checks_by_employee, employees)

    # -------------------------------------------------------------- company

    def _company(self) -> None:
        notes = Notes()
        capture = next(self._captures("api/clients/{client}/legals/{legal}"), None)
        s = Src(capture.body if capture else {})
        if capture is None:
            notes.warn("SOURCE_MISSING", None, "legal company details are not in the bundle")
        client = next(self._captures("api/clients/{client}", legal=False), None)
        client_src = Src(client.body if client else {}, "client")
        client_src.get("id")
        client_name = text(client_src.get("clientName"))
        s.mark("client", "links", "logoData")  # client: the parent below; logoData: an image (model §9)
        fein = text(s.get("federalEIN"))
        pay_groups = []
        for g in s.children("payGroups"):
            pay_groups.append(
                PayGroup(
                    code=text(g.get("id")) or "",
                    name=text(g.get("payGroupName")),
                    frequency=self._frequency(g.get("payFrequency"), "payGroups[].payFrequency", notes),
                )
            )
        address = s.child("legalAddress") or Src({})
        addr = Address(
            type=C.AddressType.COMPANY,
            line1=text(address.get("streetAddress1")),
            line2=text(address.get("streetAddress2")),
            city=text(address.get("city")),
            state=text(address.get("state")),
            postal_code=text(address.get("zipCode")),
        )
        phone = text(address.get("phoneNumber"))
        legal_name = text(s.get("legalName"))
        status_raw = text(s.get("status"))
        self.out.add(
            "companies",
            Company(
                id=self.company_id,
                source=self._source(
                    ["api/clients/{client}/legals/{legal}", "api/clients/{client}"],
                    clientId=self.client_id,
                    legalId=self.legal_id,
                ),
                name=text(s.get("dbaName")) or legal_name,
                legal_name=legal_name,
                parent=OrgUnit(code=self.client_id, name=client_name),
                status=coded(
                    {"Active": C.CompanyStatus.ACTIVE},
                    status_raw,
                    "status",
                    notes,
                    C.CompanyStatus.UNMAPPED,
                    label=status_raw,
                ),
                own_tax_id=TaxIdentifier(value=fein, source_field="federalEIN") if fein else None,
                employers=[
                    EmployerRef(
                        kind=C.EmployerKind.LEGAL_COMPANY,
                        provider_id=self.legal_id,
                        name=legal_name,
                        tax_id=TaxIdentifier(value=fein, source_field="federalEIN") if fein else None,
                    )
                ],
                pay_groups=pay_groups,
                addresses=[addr] if any([addr.line1, addr.city, addr.postal_code]) else [],
                phones=[Phone(type=C.PhoneType.MAIN, number=phone)] if phone else [],
                provider_extensions=without_links(sanitize_extensions({**s.leftovers(), **client_src.leftovers()})),
                diagnostics=notes.items,
            ),
        )

    # -------------------------------------------------------------- employees

    def _check_bodies(self) -> dict[str, list[tuple[dict, bool]]]:
        """Checks per employee: detail responses first, then the legal-level list for the rest."""
        found: dict[str, tuple[dict, bool, str]] = {}
        for capture in self._captures(E + "/checks/{id}"):
            ids = path_ids(capture)
            if isinstance(capture.body, dict) and ids.get("check"):
                found[ids["check"]] = (capture.body, True, ids.get("employee", ""))
        for row in self._body_list("api/clients/{client}/legals/{legal}/checks"):
            check_id = text(row.get("id"))
            if check_id and check_id not in found:
                found[check_id] = (row, False, text(row.get("employeeId")) or "")
        by_employee: dict[str, list[tuple[dict, bool]]] = {}
        for body, detailed, employee_id in found.values():
            by_employee.setdefault(employee_id, []).append((body, detailed))
        return by_employee

    def _employee(self, s: Src, employee_id: str, checks: list[tuple[dict, bool]]) -> None:
        notes = Notes()
        history_kept: dict[str, Any] = {}  # salary history fields that aren't mapped (A-62)
        s.get("id")
        # Identity documents and images are never kept (model §9); links are navigation.
        s.mark("i9Documents", "profilePicture", "attachments", "links", "directDeposits")
        name = s.child("nameAddress") or Src({})
        personal = s.child("personal") or Src({})

        identifiers = [Identifier(type=C.IdentifierType.PROVIDER_ID, value=employee_id, source_field="id")]
        for kind, field in (
            (C.IdentifierType.EMPLOYEE_NUMBER, "employeeNumber"),
            (C.IdentifierType.CLOCK_NUMBER, "timeclockId"),
            (C.IdentifierType.UNIQUE_ID, "uniqueId"),
        ):
            value = text(s.get(field))
            if value:
                identifiers.append(Identifier(type=kind, value=value, source_field=field))

        ssn = text(s.get("ssn"))
        national_id = None
        if ssn:
            digits, was_masked = last4(ssn)
            national_id = NationalId(
                type=C.NationalIdType.SSN, last4=digits, masked_at_source=was_masked, source_field="ssn"
            )
        else:
            # The employee endpoint returns no SSN; check details carry a masked one with the last 4 (A-50).
            from_check = next((text(b.get("employeeSSN")) for b, _ in checks if text(b.get("employeeSSN"))), None)
            if from_check:
                digits, was_masked = last4(from_check)
                national_id = NationalId(
                    type=C.NationalIdType.SSN,
                    last4=digits,
                    masked_at_source=was_masked,
                    source_field="checks[].employeeSSN",
                )

        status_text = text(s.get("employmentStatus"))
        status_date = iso_date(s.get("statusDate"), "statusDate", notes)
        # "If terminated, indicates the effective date of the employee termination"; the status date stands in.
        termination_date = iso_date(s.get("terminationDate"), "terminationDate", notes)
        # "The employee's current employment work location code", and "'location id' - 'location description'".
        location_code = text(s.get("workLocation"))
        location_text = text(s.get("workLocationDashDescription"))
        prefix = f"{location_code} - " if location_code else None
        location_name = (
            location_text[len(prefix) :]
            if prefix and location_text and location_text.startswith(prefix)
            else location_text
        )
        statuses = [
            Src(row, f"statuses[{i}]") for i, row in enumerate(self._body_list(E + "/statuses", employee=employee_id))
        ]
        implied = any(
            flag(row.get("isImpliedStatus")) and text(row.get("clientEmploymentStatusDescription")) == status_text
            for row in statuses
        )
        if status_text and implied and status_text in I.IMPLIED_STATUS:
            status = Coded[C.EmploymentStatus](
                value=I.IMPLIED_STATUS[status_text], raw=status_text, label=status_text, source_field="employmentStatus"
            )
        elif status_text:
            status = Coded[C.EmploymentStatus](
                value=C.EmploymentStatus.UNMAPPED, raw=status_text, label=status_text, source_field="employmentStatus"
            )
            notes.info(
                "CUSTOMER_STATUS",
                "employmentStatus",
                "not shown as an implied system status in /statuses; kept as a label (A-48)",
                status_text,
            )
        else:
            status = None

        pay_type_text = text(s.get("payType"))
        worker = None
        if pay_type_text == I.CONTRACTOR_PAY_TYPE:
            worker = Coded[C.WorkerClassification](
                value=C.WorkerClassification.CONTRACTOR_1099, raw=pay_type_text, source_field="payType"
            )
        pay_type = None
        if pay_type_text:
            value = I.PAY_TYPE.get(pay_type_text, C.PayType.UNMAPPED)
            if value is C.PayType.UNMAPPED and pay_type_text != I.CONTRACTOR_PAY_TYPE:
                notes.warn(
                    "UNMAPPED_CODE", "payType", "pay type description not in the system pay types table", pay_type_text
                )
            pay_type = Coded[C.PayType](value=value, raw=pay_type_text, label=pay_type_text, source_field="payType")

        # isolved sends 0 for a rate that doesn't apply (A-73): only a nonzero rate is read and mapped, so a
        # 0 stays as sent in provider_extensions.
        rates = []
        for field, per in (("hourlyRate", C.RatePeriod.HOUR), ("perPaySalary", C.RatePeriod.PAY_PERIOD)):
            amount = decimal(s.data.get(field))
            if amount is not None and amount != ZERO:
                s.get(field)
                rates.append(Rate(amount=amount, per=per, source_field=field))
        if not rates:
            notes.info("NO_PAY_RATE", "hourlyRate", "no nonzero hourly rate or per-pay salary; isolved's 0 means none")
        normal_hours = decimal(s.get("normalHours"))
        override = s.child("overrideAddress") or Src({})
        addresses = [
            a
            for a in (
                Address(
                    type=C.AddressType.HOME,
                    line1=text(name.get("address1")),
                    line2=text(name.get("address2")),
                    city=text(name.get("city")),
                    state=text(name.get("state")),
                    postal_code=text(name.get("zipCode")),
                ),
                Address(
                    type=C.AddressType.MAILING,
                    line1=text(override.get("address1")),
                    line2=text(override.get("address2")),
                    city=text(override.get("city")),
                    state=text(override.get("state")),
                    postal_code=text(override.get("zipCode")),
                    country=text(override.get("country")),
                ),
            )
            if any([a.line1, a.city, a.postal_code])
        ]
        phones = [
            Phone(type=t, number=n)
            for t, n in (
                (C.PhoneType.HOME, text(personal.get("homePhone"))),
                (C.PhoneType.MOBILE, text(personal.get("mobilePhone"))),
                (C.PhoneType.WORK, text(personal.get("officePhone"))),
                (C.PhoneType.FAX, text(personal.get("faxNumber"))),
            )
            if n
        ]
        emails = [
            Email(type=t, address=a)
            for t, a in (
                (C.EmailType.MAIN, text(s.get("emailAddress"))),
                (C.EmailType.PERSONAL, text(personal.get("personalEmailAddress"))),
            )
            if a
        ]
        disabled = self._disabled(s, notes)
        veteran = self._veteran(s, employee_id, notes, history_kept)
        # Organization fields are customer-defined; each keeps the customer's own title (A-75).
        org_units = [
            OrgAssignment(
                dimension=text(o.get("title")),
                code=text(o.get("value")),
                name=text(o.get("valueDescription")),
                source_field=o.path,
            )
            for o in s.children("organizations")
            if text(o.data.get("value")) or text(o.data.get("valueDescription"))
        ]
        manager = text((s.child("assignedManager") or Src({})).get("id"))
        supervisor = text((s.child("assignedSupervisor") or Src({})).get("id"))

        employee = Employee(
            id=self._id("employee", employee_id),
            company_id=self.company_id,
            source=self._source(
                [E] + [e for e in PER_EMPLOYEE if any(True for _ in self._captures(e, employee=employee_id))],
                clientId=self.client_id,
                legalId=self.legal_id,
                employeeId=employee_id,
            ),
            identifiers=identifiers,
            national_id=national_id,
            name=dict(
                first=text(name.get("firstName")),
                middle=text(name.get("middleName")),
                last=text(name.get("lastName")),
                preferred=text(name.get("preferredName")),
                prefix=text(name.get("prefix")),
                suffix=text(name.get("suffix")),
            ),
            personal=dict(
                birth_date=iso_date(s.get("birthDate"), "birthDate", notes),
                gender=self._lookup_coded("genders", I.GENDER, s.get("gender"), "gender", notes, C.Gender.UNMAPPED),
                marital_status=self._lookup_coded(
                    "maritalStatuses",
                    I.MARITAL,
                    s.get("maritalStatus"),
                    "maritalStatus",
                    notes,
                    C.MaritalStatus.UNMAPPED,
                ),
                ethnicity=unmapped_label(s.get("ethnicOrigin"), text(s.data.get("ethnicOrigin")), "ethnicOrigin"),
                disabled=disabled,
                veteran=veteran,
                citizenship=self._lookup_coded(
                    "citizenships",
                    I.CITIZENSHIP,
                    s.get("citizenship"),
                    "citizenship",
                    notes,
                    C.Citizenship.UNMAPPED,
                ),
                contacts=self._contacts(employee_id, notes, history_kept),
            ),
            addresses=addresses,
            phones=phones,
            emails=emails,
            employment=dict(
                status=status,
                status_date=status_date,
                employment_type=unmapped_label(s.get("employmentCategoryCode"), None, "employmentCategoryCode"),
                worker_classification=worker,
                original_hire_date=iso_date(s.get("originalHireDate"), "originalHireDate", notes),
                hire_date=iso_date(s.get("hireDate"), "hireDate", notes),
                rehire_date=iso_date(s.get("rehireDate"), "rehireDate", notes),
                termination_date=termination_date
                or (status_date if status and status.value is C.EmploymentStatus.TERMINATED else None),
                # Reasons are text the customer can configure: kept with their label, not translated (A-35).
                termination_reason=unmapped_label(
                    s.get("terminationReason"), text(s.data.get("terminationReason")), "terminationReason"
                ),
                flsa_exempt=flag(s.get("jobFLSAExempt")),
                history=self._status_history(statuses, notes)
                + self._category_history(employee_id, notes, history_kept),
            ),
            job=dict(
                title=text(s.get("jobTitle")),
                job_code=text(s.get("jobCode")),
                manager_employee_id=self._id("employee", manager) if manager else None,
                supervisor_employee_id=self._id("employee", supervisor) if supervisor else None,
                location=OrgUnit(code=location_code or "", name=location_name)
                if location_code or location_name
                else None,
                pay_group=text(s.get("payGroup")),
                org_units=org_units,
                history=self._job_history(employee_id, notes, history_kept),
            ),
            compensation=Compensation(
                pay_type=pay_type,
                pay_frequency=self._frequency(s.get("payFrequency"), "payFrequency", notes),
                rates=rates,
                annual_pay=money(s.get("annualSalary"), "annualSalary"),
                standard_hours=Quantity(value=normal_hours, unit=C.QuantityUnit.HOURS, source_field="normalHours")
                if normal_hours is not None
                else None,
                standard_hours_per="PAY_PERIOD" if normal_hours is not None else None,
                effective_date=iso_date(s.get("salaryEffectiveDate"), "salaryEffectiveDate", notes),
                history=self._salary_history(employee_id, notes, history_kept),
            ),
            diagnostics=notes.items,
        )
        # Only now has every mapped field been read, so the leftovers are exactly what wasn't mapped.
        extensions = without_links(sanitize_extensions(s.leftovers()))
        # Earning and employer-side pay items have no record of their own; they are kept here (model §9),
        # minus the employee's own name and IDs that each item repeats.
        for i, row in enumerate(self._body_list(E + "/payItems", employee=employee_id)):
            if text(row.get("payItemType")) != "Deduction":
                item = Src(row, f"payItems[{i}]")
                item.mark("firstName", "lastName", "employeeId", "employeeNumber")
                extensions.update(without_links(sanitize_extensions(item.leftovers())))
        # Status history, salary history fields not mapped and alternate pay rates are kept too.
        extensions.update(history_kept)
        for history_row in statuses:
            extensions.update(without_links(sanitize_extensions(history_row.leftovers())))
        for i, row in enumerate(self._body_list(E + "/payRates", employee=employee_id)):
            extensions.update(without_links(sanitize_extensions(Src(row, f"payRates[{i}]").leftovers())))
        employee.provider_extensions = extensions
        self.out.add("employees", employee)

    def _disabled(self, s: Src, notes: Notes) -> Coded[C.YesNoDeclined] | None:
        """`disabled` is documented True = Disabled, False = Not Disabled; when it is null, the read-only
        `disabilityDescription` may still say the employee declined to answer (A-81)."""
        disabled = flag(s.get("disabled"))
        if disabled is not None:
            return Coded[C.YesNoDeclined](
                value=C.YesNoDeclined.YES if disabled else C.YesNoDeclined.NO, raw=disabled, source_field="disabled"
            )
        description = text(s.get("disabilityDescription"))
        if description is None:
            return None
        value = I.DISABILITY_DESCRIPTION.get(description)
        if value is None:
            notes.warn("UNMAPPED_CODE", "disabilityDescription", "not a known disability description", description)
        return Coded[C.YesNoDeclined](
            value=value or C.YesNoDeclined.UNMAPPED,
            raw=description,
            label=description,
            source_field="disabilityDescription",
        )

    def _veteran(self, s: Src, employee_id: str, notes: Notes, kept: dict[str, Any]) -> Coded[C.YesNoDeclined] | None:
        """YES when a documented veteran flag is true; otherwise /veteranStatus's text, which has no documented
        values, stays UNMAPPED. A false flag says nothing, and veteranStatusNotSpecified is kept raw (A-81)."""
        flagged = next((f for f in I.VETERAN_FLAGS if flag(s.data.get(f))), None)
        status: Coded[C.YesNoDeclined] | None = None
        if flagged:
            s.get(flagged)
            status = Coded[C.YesNoDeclined](value=C.YesNoDeclined.YES, raw=True, source_field=flagged)
        for capture in self._captures(E + "/veteranStatus", employee=employee_id):
            v = Src(capture.body, "veteranStatus")
            flag_field = next((f for f in I.VETERAN_STATUS_FLAGS if flag(v.data.get(f))), None)
            if status is None and flag_field:
                v.get(flag_field)
                status = Coded[C.YesNoDeclined](
                    value=C.YesNoDeclined.YES, raw=True, source_field=f"{v.path}.{flag_field}"
                )
            said = text(v.data.get("veteranStatus"))
            if status is None and said:
                v.get("veteranStatus")
                notes.warn("UNMAPPED_CODE", "veteranStatus.veteranStatus", "no documented values", said)
                status = Coded[C.YesNoDeclined](
                    value=C.YesNoDeclined.UNMAPPED, raw=said, label=said, source_field="veteranStatus.veteranStatus"
                )
            kept.update(without_links(sanitize_extensions(v.leftovers())))
        return status

    def _status_history(self, statuses: list[Src], notes: Notes) -> list[EmploymentChange]:
        """Each /statuses row as a status change; implied system statuses map as the current one does (A-48, A-76)."""
        changes = []
        for row in statuses:
            description = text(row.get("clientEmploymentStatusDescription"))
            implied = flag(row.get("isImpliedStatus"))
            value = I.IMPLIED_STATUS.get(description or "") if implied else None
            changes.append(
                EmploymentChange(
                    kind=C.EmploymentChangeKind.STATUS,
                    effective_date=iso_date(row.get("effectiveDate"), f"{row.path}.effectiveDate", notes),
                    end_date=iso_date(row.get("endDate"), f"{row.path}.endDate", notes),
                    status=Coded[C.EmploymentStatus](
                        value=value or C.EmploymentStatus.UNMAPPED,
                        raw=description,
                        label=description,
                        source_field=f"{row.path}.clientEmploymentStatusDescription",
                    )
                    if description
                    else None,
                    # Change reasons are customer text: kept with their label, not translated (A-35).
                    reason=unmapped_label(
                        row.get("changeReason"), text(row.data.get("changeReason")), f"{row.path}.changeReason"
                    ),
                    source_field=row.path,
                )
            )
        return changes

    @staticmethod
    def _reason(row: Src) -> Coded[str] | None:
        """A client change reason ({code, description}): customer configuration, kept with its label (A-35)."""
        reason = row.child("changeReason")
        if reason is None:
            return None
        return unmapped_label(reason.get("code"), text(reason.get("description")), f"{reason.path}.code")

    def _category_history(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[EmploymentChange]:
        """Effective-dated employment categories. Categories are customer codes, like the current one (A-76)."""
        changes = []
        for i, row in enumerate(self._body_list(E + "/categories", employee=employee_id)):
            c = Src(row, f"categories[{i}]")
            category = c.child("employmentCategory") or Src({})
            changes.append(
                EmploymentChange(
                    kind=C.EmploymentChangeKind.CATEGORY,
                    source_id=text(c.get("id")),
                    effective_date=iso_date(c.get("effectiveDate"), f"{c.path}.effectiveDate", notes),
                    employment_type=unmapped_label(
                        category.get("code"), text(category.get("description")), f"{c.path}.employmentCategory.code"
                    ),
                    reason=self._reason(c),
                    source_field=c.path,
                )
            )
            kept.update(without_links(sanitize_extensions(c.leftovers())))
        return changes

    def _job_history(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[JobChange]:
        """Effective-dated jobs, with their manager, supervisor and organization fields (A-75, A-76)."""
        jobs = []
        for i, row in enumerate(self._body_list(E + "/jobs", employee=employee_id)):
            j = Src(row, f"jobs[{i}]")
            client_job = j.child("clientJob") or Src({})
            manager = text((j.child("manager") or Src({})).get("id"))
            supervisor = text((j.child("supervisor") or Src({})).get("id"))
            jobs.append(
                JobChange(
                    source_id=text(j.get("id")),
                    effective_date=iso_date(j.get("effectiveDate"), f"{j.path}.effectiveDate", notes),
                    title=text(client_job.get("jobTitle")),
                    job_code=text(client_job.get("jobCode")),
                    org_units=[
                        OrgAssignment(
                            dimension=text((o.child("clientOrganizationField") or Src({})).get("title")),
                            code=text(o.get("organizationValue")),
                            source_field=o.path,
                        )
                        for o in j.children("organizations")
                        if text(o.data.get("organizationValue"))
                    ],
                    manager_employee_id=self._id("employee", manager) if manager else None,
                    supervisor_employee_id=self._id("employee", supervisor) if supervisor else None,
                    reason=self._reason(j),
                    source_field=j.path,
                )
            )
            kept.update(without_links(sanitize_extensions(j.leftovers())))
        return jobs

    def _contacts(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[Contact]:
        """Emergency contacts, dependents and beneficiaries (A-77). The unmasked birth date is read; both SSNs
        stay sanitized to their last 4 (A-23)."""
        contacts = []
        for i, row in enumerate(self._body_list(E + "/contacts", employee=employee_id)):
            c = Src(row, f"contacts[{i}]")
            # A missing role flag leaves that role unknown, with a warning; it is never read as "no" (A-73).
            roles = [
                role
                for field, role in I.CONTACT_ROLES
                if known_flag(c.get(field), f"{c.path}.{field}", notes, f"whether the contact is {role.value.lower()}")
            ]
            unmasked = text(c.get("birthDateUnmasked"))
            if unmasked:
                c.mark("birthDate")  # the masked copy of the same date
                birth_date = iso_date(unmasked, f"{c.path}.birthDateUnmasked", notes)
            else:
                birth_date = unmasked_date(c, "birthDate", notes)
            relationship = text(c.get("relationshipCode"))
            email = text(c.get("emailAddress"))
            address = Address(
                type=C.AddressType.MAILING,  # "the contact mailing address" (useEmployeeAddress)
                line1=text(c.get("address1")),
                line2=text(c.get("address2")),
                city=text(c.get("city")),
                state=text(c.get("state")),
                postal_code=text(c.get("zipCode")),
            )
            order = c.get("emergencyCallOrder")
            contacts.append(
                Contact(
                    source_id=text(c.get("id")),
                    roles=roles,
                    name=PersonName(
                        first=text(c.get("firstName")),
                        middle=text(c.get("middleName")),
                        last=text(c.get("lastName")),
                        prefix=text(c.get("prefix")),
                        suffix=text(c.get("suffix")),
                    ),
                    relationship=self._described("ContactRelationshipCodes", relationship),
                    relationship_code=relationship,
                    priority=int(order) if isinstance(order, int) and not isinstance(order, bool) else None,
                    birth_date=birth_date,
                    phones=[
                        Phone(type=t, number=n)
                        for t, n in (
                            (C.PhoneType.HOME, text(c.get("homePhone"))),
                            (C.PhoneType.MOBILE, text(c.get("mobilePhone"))),
                            (C.PhoneType.WORK, text(c.get("workPhone"))),
                        )
                        if n
                    ],
                    emails=[Email(type=C.EmailType.MAIN, address=email)] if email else [],
                    address=address if any([address.line1, address.city, address.postal_code]) else None,
                    source_field=c.path,
                )
            )
            kept.update(without_links(sanitize_extensions(c.leftovers())))
        return contacts

    def _salary_history(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[CompensationChange]:
        """Each salary row as a change; whatever a row has that isn't mapped is added to `kept` (A-62)."""
        changes = []
        for i, row in enumerate(self._body_list(E + "/salaries", employee=employee_id)):
            h = Src(row, f"salaries[{i}]")
            pay_type = text((h.child("payType") or Src({})).get("description"))
            rates = []
            for f, per in (("hourlyRate", C.RatePeriod.HOUR), ("perPaySalary", C.RatePeriod.PAY_PERIOD)):
                if (a := decimal(h.data.get(f))) is not None and a != ZERO:  # a 0 means none (A-73) and stays raw
                    h.get(f)
                    rates.append(Rate(amount=a, per=per, source_field=f"{h.path}.{f}"))
            hours = decimal(h.get("normalHours"))
            changes.append(
                CompensationChange(
                    source_id=text(h.get("id")),
                    effective_date=iso_date(h.get("effectiveDate"), f"{h.path}.effectiveDate", notes),
                    pay_type=Coded[C.PayType](
                        value=I.PAY_TYPE.get(pay_type or "", C.PayType.UNMAPPED),
                        raw=pay_type,
                        label=pay_type,
                        source_field=f"{h.path}.payType.description",
                    )
                    if pay_type
                    else None,
                    rates=rates,
                    standard_hours=Quantity(
                        value=hours, unit=C.QuantityUnit.HOURS, source_field=f"{h.path}.normalHours"
                    )
                    if hours is not None
                    else None,
                    reason=text((h.child("changeReason") or Src({})).get("description")),
                )
            )
            kept.update(without_links(sanitize_extensions(h.leftovers())))
        return changes

    # -------------------------------------------------------------- direct deposits

    def _deposits(self, employee_id: str) -> None:
        for row in self._body_list(E + "/directdeposits", employee=employee_id):
            notes = Notes()
            s = Src(row)
            deposit_id = text(s.get("id")) or ""
            sequence = s.get("sequenceNumber")
            amount, percent = decimal(s.get("amount")), decimal(s.get("percent"))
            if sequence == 0:
                method = C.DepositMethod.REMAINDER  # "Direct Deposit sequence. (0 = Net Pay)"
            elif amount is not None:
                method = C.DepositMethod.FIXED_AMOUNT
            elif percent is not None:
                method = C.DepositMethod.PERCENT_BASE_UNSPECIFIED
                notes.info(
                    "PERCENT_SCALE_UNVERIFIED",
                    "percent",
                    "no live percent deposits to verify the scale (A-29)",
                    str(percent),
                )
            else:
                method = C.DepositMethod.UNMAPPED
                notes.warn("NO_ALLOCATION", None, "neither amount, percent nor the net-pay sequence (0) is set")
            account = text(s.get("accountNumber"))
            digits, was_masked = last4(account)
            frequency = text(s.get("frequency"))
            self.out.add(
                "direct_deposits",
                DirectDeposit(
                    id=self._id("direct_deposit", deposit_id),
                    source=self._source(
                        [E + "/directdeposits"],
                        clientId=self.client_id,
                        legalId=self.legal_id,
                        employeeId=employee_id,
                        depositId=deposit_id,
                    ),
                    employee_id=self._id("employee", employee_id),
                    company_id=self.company_id,
                    purpose=C.DepositPurpose.NET_PAY,
                    account=BankAccount(
                        type=coded(
                            I.DD_ACCOUNT_TYPE,
                            s.get("accountType"),
                            "accountType",
                            notes,
                            C.AccountType.UNMAPPED,
                            label=text(s.data.get("accountType")),
                            empty_is_none=False,
                        ),
                        routing_number=text(s.get("routingNumber")),
                        account_last4=digits,
                        masked_at_source=was_masked if account else None,
                        bank_name=text(s.get("bankName")),
                    ),
                    method=Coded[C.DepositMethod](
                        value=method,
                        raw=sequence if sequence == 0 else None,
                        source_field="sequenceNumber/amount/percent",
                    ),
                    amount=Money(amount=amount, source_field="amount") if amount is not None else None,
                    percent=Percent(
                        percent=None, scale=C.PercentScale.UNVERIFIED, raw=str(percent), source_field="percent"
                    )
                    if percent is not None
                    else None,
                    sequence=sequence if isinstance(sequence, int) else None,
                    is_remainder=method is C.DepositMethod.REMAINDER,
                    status=coded(
                        I.DD_STATUS,
                        s.get("status"),
                        "status",
                        notes,
                        C.DepositStatus.UNMAPPED,
                        label=text(s.data.get("status")),
                    ),
                    frequency=Coded[str](value="UNMAPPED", raw=frequency, label=frequency, source_field="frequency")
                    if frequency
                    else None,
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )

    # -------------------------------------------------------------- deduction setup

    def _calculation(self, params: list[Src], notes: Notes) -> Calculation | None:
        # One parameter drives the calculation; only it is read, so any others stay in provider_extensions.
        rows = [(p, text(p.data.get("paramType")), decimal(p.data.get("paramValue"))) for p in params]
        chosen = next((r for r in rows if r[2] not in (None, ZERO)), rows[0] if rows else None)
        if chosen is None:
            return None
        param, kind, value = chosen
        param.get("paramType")
        param.get("paramValue")
        if kind == "Amount":
            return Calculation(
                method=Coded[C.CalculationMethod](
                    value=C.CalculationMethod.FIXED_AMOUNT, raw=kind, source_field="calcParams[].paramType"
                ),
                amount=Money(amount=value) if value is not None else None,
            )
        if kind == "Percent":
            return Calculation(
                method=Coded[C.CalculationMethod](
                    value=C.CalculationMethod.PERCENT, raw=kind, source_field="calcParams[].paramType"
                ),
                percent=Percent(
                    percent=None, scale=C.PercentScale.UNVERIFIED, raw=str(value) if value is not None else None
                ),
            )
        if kind:
            notes.info(
                "UNMAPPED_CODE", "calcParams[].paramType", "calculation parameter without a documented basis", kind
            )
            return Calculation(
                method=Coded[C.CalculationMethod](
                    value=C.CalculationMethod.UNMAPPED, raw=kind, source_field="calcParams[].paramType"
                )
            )
        return None

    def _elections(self, employee_id: str) -> None:
        for i, row in enumerate(self._body_list(E + "/payItems", employee=employee_id)):
            if text(row.get("payItemType")) != "Deduction":
                continue
            notes = Notes()
            s = Src(row)
            item_id, name = text(s.get("id")) or str(i), text(s.get("payItemName"))
            s.mark("payItemType", "payItemId", "firstName", "lastName", "employeeId", "employeeNumber", "links")
            category, treatment = self._classify(name)
            if category is None:
                notes.warn("UNCLASSIFIED", "payItemName", "no client pay item with this title to classify it", name)
                category = Coded[C.DeductionCategory](
                    value=C.DeductionCategory.UNMAPPED, raw=name, source_field="payItemName"
                )
            schedule = text(s.get("scheduleOverride")) or text((self.pay_items.get(name) or {}).get("scheduleDefault"))
            self.out.add(
                "deduction_elections",
                DeductionElection(
                    id=self._id("deduction_election", employee_id, "payitem", item_id),
                    source=self._source(
                        [E + "/payItems", "api/clients/{client}/payItems"],
                        clientId=self.client_id,
                        legalId=self.legal_id,
                        employeeId=employee_id,
                        payItemId=item_id,
                    ),
                    employee_id=self._id("employee", employee_id),
                    company_id=self.company_id,
                    code=text(s.get("payItemCode")) or name or item_id,
                    label=name,
                    category=category,
                    tax_treatment=treatment,
                    calculation=self._calculation(s.children("calcParams"), notes),
                    frequency=Coded[str](
                        value="UNMAPPED", raw=schedule, label=schedule, source_field="scheduleOverride"
                    )
                    if schedule
                    else None,
                    effective_from=iso_date(s.get("startDate"), "startDate", notes),
                    effective_to=iso_date(s.get("stopDate"), "stopDate", notes),
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )
        for row in self._body_list(E + "/garnishments", employee=employee_id):
            notes = Notes()
            s = Src(row)
            garnishment_id = text(s.get("id")) or ""
            kind = s.child("garnishmentType") or Src({})
            # A garnishment is an amount or a percent; a 0 is "not this one" and stays as sent (A-73). With
            # neither, how it is calculated is unknown, not a fixed amount.
            amount, percent = (
                v if (v := decimal(s.data.get(k))) not in (None, ZERO) else None for k in ("amount", "percent")
            )
            for key, value in (("amount", amount), ("percent", percent)):
                if value is not None:
                    s.get(key)
            if amount is None and percent is None:
                notes.warn("AMOUNT_MISSING", "amount/percent", "neither an amount nor a percent was sent")
            basis_raw = text(s.get("percentageOf"))
            basis = {
                "Gross Pay": C.CalculationBasis.GROSS_PAY,
                "Gross Wages": C.CalculationBasis.GROSS_WAGES,
                "Net Pay": C.CalculationBasis.NET_PAY,
                "Disposable Income": C.CalculationBasis.DISPOSABLE_INCOME,
            }.get(basis_raw or "", C.CalculationBasis.UNSPECIFIED)
            calculation = Calculation(
                method=Coded[C.CalculationMethod](
                    value=C.CalculationMethod.PERCENT
                    if percent is not None
                    else C.CalculationMethod.FIXED_AMOUNT
                    if amount is not None
                    else C.CalculationMethod.UNMAPPED,
                    source_field="amount/percent",
                ),
                basis=basis,
                amount=Money(amount=amount) if amount is not None else None,
                percent=Percent(percent=None, basis=basis, scale=C.PercentScale.UNVERIFIED, raw=str(percent))
                if percent is not None
                else None,
            )
            type_label = text(kind.get("typeDescription"))
            payee = s.child("garnishmentPayee") or Src({})
            status_raw = text(s.get("status"))
            self.out.add(
                "deduction_elections",
                DeductionElection(
                    id=self._id("deduction_election", employee_id, "garnishment", garnishment_id),
                    source=self._source(
                        [E + "/garnishments"],
                        clientId=self.client_id,
                        legalId=self.legal_id,
                        employeeId=employee_id,
                        garnishmentId=garnishment_id,
                    ),
                    employee_id=self._id("employee", employee_id),
                    company_id=self.company_id,
                    code=text(kind.get("id")) or garnishment_id,
                    label=text(s.get("garnishmentDescription")) or type_label,
                    category=Coded[C.DeductionCategory](
                        value=C.DeductionCategory.GARNISHMENT, source_field="garnishments[]"
                    ),
                    calculation=calculation,
                    limits=DeductionLimits(per_period=money(s.get("limit")), maximum=money(s.get("maximumAmount"))),
                    status=coded(
                        {"Active": C.ElectionStatus.ACTIVE, "Inactive": C.ElectionStatus.INACTIVE},
                        status_raw,
                        "status",
                        notes,
                        C.ElectionStatus.UNMAPPED,
                        label=status_raw,
                    ),
                    effective_from=iso_date(s.get("startDate"), "startDate", notes),
                    effective_to=iso_date(s.get("stopDate"), "stopDate", notes),
                    loan_or_garnishment_id=garnishment_id or None,
                    garnishment=GarnishmentDetails(
                        case_number=text(s.get("caseNumber")),
                        garnishment_type=unmapped_label(kind.data.get("id"), type_label, "garnishmentType.id"),
                        payee=text(payee.get("payeeName")),
                        issuing_state=text((s.child("state") or Src({})).get("id")),
                        arrears_balance=money(s.get("arrearsBalance")),
                        remaining_balance=money(s.get("remainingBalance")),
                        fee=money(s.get("feeAmount")),
                    ),
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )

    # -------------------------------------------------------------- payroll runs

    def _payroll_runs(self) -> None:
        runs: dict[tuple[str, str], tuple[dict, list[str]]] = {}
        history = "api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory"
        # The run history list first, then the detail, which replaces its list row when fetched.
        for endpoint in (history, history + "/{id}"):
            for capture in self._captures(endpoint):
                group = path_ids(capture).get("group", "")
                body = capture.body
                for row in body if isinstance(body, list) else [body]:
                    run_id = text((row or {}).get("id"))
                    if run_id:
                        _, endpoints = runs.get((group, run_id), ({}, []))
                        runs[(group, run_id)] = (row, endpoints + [endpoint])
        for (group, run_id), (row, endpoints) in sorted(runs.items()):
            notes = Notes()
            s = Src(row)
            canonical_id = self._id("payroll_run", self.client_id, self.legal_id, group, run_id)
            pay_date = iso_date(s.get("payDate"), "payDate", notes)
            run_number = text(s.get("runNumber"))
            self.runs_by_key.setdefault((pay_date, run_number), []).append(canonical_id)
            type_raw, status_raw = text(s.get("payrollRunType")), text(s.get("status"))
            self.out.add(
                "payroll_runs",
                PayrollRun(
                    id=canonical_id,
                    source=self._source(
                        endpoints, clientId=self.client_id, legalId=self.legal_id, payGroupId=group, payrollRunId=run_id
                    ),
                    company_id=self.company_id,
                    pay_date=pay_date,
                    processed_date=iso_date(s.get("runDate"), "runDate", notes),
                    description=text(s.get("payOfTheMonth")),
                    type=coded(
                        I.RUN_TYPE,
                        type_raw,
                        "payrollRunType",
                        notes,
                        C.PayrollRunType.UNMAPPED,
                        label=type_raw,
                        empty_is_none=False,
                    ),
                    status=coded(
                        I.RUN_STATUS, status_raw, "status", notes, C.PayrollRunStatus.UNMAPPED, label=status_raw
                    ),
                    pay_groups=[
                        RunPayGroup(
                            pay_group=group,
                            period=DateRange(
                                start=iso_date(s.get("periodBeginDate"), "periodBeginDate", notes),
                                end=iso_date(s.get("periodEndDate"), "periodEndDate", notes),
                            ),
                        )
                    ],
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )

    # -------------------------------------------------------------- pay statements

    def _pay_statements(self, checks_by_employee: dict[str, list[tuple[dict, bool]]], employees: set[str]) -> None:
        for employee_id, checks in sorted(checks_by_employee.items()):
            for body, detailed in checks:
                self._pay_statement(Src(body), employee_id, detailed, employee_id in employees)

    def _lines(self, s: Src, key: str) -> list[Src]:
        """Lines that belong to this check: check* values set. YTD-only carryover lines stay in extensions."""
        return [
            line
            for line in s.children(key)
            if line.data.get("checkDollars") is not None or line.data.get("checkHours") not in (None, 0)
        ]

    def _pay_statement(self, s: Src, employee_id: str, detailed: bool, employee_known: bool) -> None:
        notes = Notes()
        check_id = text(s.get("id")) or ""
        s.mark("links")
        if not detailed:
            notes.info("DETAIL_NOT_FETCHED", None, "from the legal-level check list; line items were not requested")
        if not employee_known:
            notes.info(
                "EMPLOYEE_NOT_IN_BUNDLE", "employeeId", "employee record was not fetched into this bundle", employee_id
            )
        pay_date = iso_date(s.get("checkDate"), "checkDate", notes)
        run_number = text(s.get("payrollRunNumber"))
        candidates = self.runs_by_key.get((pay_date, run_number), [])
        run_id = candidates[0] if len(candidates) == 1 else None
        if run_number and len(candidates) != 1:
            notes.info(
                "RUN_NOT_MATCHED",
                "payrollRunNumber",
                f"{len(candidates)} payroll runs match pay date + run number; left unlinked (A-40)",
                run_number,
            )

        earnings = []
        for line in self._lines(s, "earnings"):
            memo = known_flag(
                line.get("isMemoEarning"), "earnings[].isMemoEarning", notes, "whether the line counts in gross wages"
            )
            # One quantity per line: hours if set, else units. Only the one used is read, so the other
            # (when both are set) stays in provider_extensions.
            hours, units = decimal(line.data.get("checkHours")), decimal(line.data.get("checkUnits"))
            quantity = None
            if hours not in (None, ZERO):
                line.get("checkHours")
                quantity = Quantity(value=hours, unit=C.QuantityUnit.HOURS, source_field="earnings[].checkHours")
            elif units not in (None, ZERO):
                line.get("checkUnits")
                quantity = Quantity(value=units, unit=C.QuantityUnit.UNITS, source_field="earnings[].checkUnits")
            title = text(line.get("itemDescription"))
            kind = self._earning_kind(title, bool(memo), notes)
            earnings.append(
                EarningLine(
                    code=text(line.get("itemCode")),
                    label=title,
                    kind=kind,
                    category=self._earning_category(title, kind, notes),
                    # grossWages is the sum of the non-memo lines (A-28); unknown when the flag is (A-73)
                    in_gross=None if memo is None else not memo,
                    quantity=quantity,
                    amount=line_amount(line.get("checkDollars"), "earnings[].checkDollars", notes),
                    source_field="earnings[]",
                )
            )
        taxes = []
        for t in self._lines(s, "taxes"):
            description = text(t.get("itemDescription"))
            tax, state = self._tax_type(description, notes)
            employee_tax = known_flag(t.get("isEmployeeTax"), "taxes[].isEmployeeTax", notes, "who paid the tax")
            taxes.append(
                TaxLine(
                    code=text(t.get("itemCode")),
                    label=description,
                    type=tax,
                    state=state,
                    paid_by=C.TaxPaidBy.UNMAPPED
                    if employee_tax is None
                    else C.TaxPaidBy.EMPLOYEE
                    if employee_tax
                    else C.TaxPaidBy.EMPLOYER,
                    amount=line_amount(t.get("checkDollars"), "taxes[].checkDollars", notes),
                    taxable_wages=money(t.get("checkTaxableWages")),
                    source_field="taxes[]",
                )
            )
        deductions = []
        for d in self._lines(s, "deductions"):
            label = text(d.get("itemDescription"))
            category, treatment = self._classify(label)
            deductions.append(
                DeductionLine(
                    code=text(d.get("itemCode")),
                    label=label,
                    category=category,
                    tax_treatment=treatment,
                    employee_amount=line_amount(d.get("checkDollars"), "deductions[].checkDollars", notes),
                    source_field="deductions[]",
                )
            )
        for g in self._lines(s, "garnishments"):
            deductions.append(
                DeductionLine(
                    code=text(g.get("itemCode")),
                    label=text(g.get("itemDescription")),
                    category=Coded[C.DeductionCategory](
                        value=C.DeductionCategory.GARNISHMENT, source_field="garnishments[]"
                    ),
                    employee_amount=line_amount(g.get("checkDollars"), "garnishments[].checkDollars", notes),
                    source_field="garnishments[]",
                )
            )
        contributions, benefits = [], []
        for b in s.children("benefits"):
            employer, employee, catch_up = (
                decimal(b.data.get(k))
                for k in ("checkEmployerContribution", "checkEmployeeDeduction", "checkEmployeeCatchUp")
            )
            if all(v in (None, ZERO) for v in (employer, employee, catch_up)):
                continue  # nothing on this check: the line stays as sent in provider_extensions (A-73)
            title = text(b.get("benefitTitle"))
            for key, value in (("checkEmployerContribution", employer), ("checkEmployeeDeduction", employee)):
                if value is not None:
                    b.get(key)
            if employer not in (None, ZERO):
                contributions.append(
                    ContributionLine(
                        code=title,
                        label=text(b.get("benefitDescription")),
                        amount=Money(amount=employer),
                        source_field="benefits[]",
                    )
                )
            if catch_up not in (None, ZERO):  # a 0 catch-up is none, and stays as sent (A-73)
                b.get("checkEmployeeCatchUp")
            benefits.append(
                BenefitDetail(
                    plan=title,
                    employee_deduction=Money(amount=employee) if employee is not None else None,
                    employee_contribution=Money(amount=catch_up) if catch_up not in (None, ZERO) else None,
                    employer_contribution=Money(amount=employer) if employer is not None else None,
                    source_field="benefits[]",
                )
            )
        payments = []
        for d in s.children("directDeposits"):
            account = text(d.get("account"))
            digits, was_masked = last4(account)
            payments.append(
                PaymentLine(
                    kind=Coded[C.PaymentKind](value=C.PaymentKind.DIRECT_DEPOSIT, source_field="directDeposits[]"),
                    amount=line_amount(d.get("depositAmount"), "directDeposits[].depositAmount", notes),
                    account_last4=digits,
                    masked_at_source=was_masked if account else None,
                    source_field="directDeposits[]",
                )
            )
        # The check list has no deposit lines (A-51); its deposit total stands in for them.
        deposited = decimal(s.get("directDepositAmount")) if s.get("directDeposits") is None else None
        if deposited not in (None, ZERO):
            payments.append(
                PaymentLine(
                    kind=Coded[C.PaymentKind](value=C.PaymentKind.DIRECT_DEPOSIT, source_field="directDepositAmount"),
                    amount=Money(amount=deposited),
                    source_field="directDepositAmount",
                )
            )
        check_amount = decimal(s.data.get("checkAmount"))
        if check_amount not in (None, ZERO):  # a 0 is no paper check, and stays as sent (A-73)
            s.get("checkAmount")
            payments.append(
                PaymentLine(
                    kind=Coded[C.PaymentKind](value=C.PaymentKind.CHECK, source_field="checkAmount"),
                    amount=Money(amount=check_amount),
                    source_field="checkAmount",
                )
            )
        # grossWages - non-cash earnings = grossPay (A-28); the checks verify it per paycheck.
        gross, wages, net = decimal(s.get("grossPay")), decimal(s.get("grossWages")), decimal(s.get("netPay"))
        has_lines = bool(earnings or taxes or deductions)
        type_raw = text(s.get("checkTypeDescription"))
        statement = PayStatement(
            id=self._id("pay_statement", check_id),
            source=self._source(
                [E + "/checks/{id}" if detailed else "api/clients/{client}/legals/{legal}/checks"],
                clientId=self.client_id,
                legalId=self.legal_id,
                employeeId=employee_id,
                checkId=check_id,
            ),
            company_id=self.company_id,
            employee_id=self._id("employee", employee_id),
            payroll_run_id=run_id,
            pay_date=pay_date,
            period=DateRange(
                start=iso_date(s.get("periodBeginDate"), "periodBeginDate", notes),
                end=iso_date(s.get("periodEndDate"), "periodEndDate", notes),
            ),
            check_number=text(s.get("checkNumber")),
            # List-only checks have no type at all; that is missing detail (DETAIL_NOT_FETCHED), not an unknown code.
            type=coded(
                I.CHECK_TYPE, type_raw, "checkTypeDescription", notes, C.PayStatementType.UNMAPPED, label=type_raw
            )
            or Coded[C.PayStatementType](value=C.PayStatementType.UNMAPPED, source_field="checkTypeDescription"),
            totals=PayStatementTotals(
                gross_pay=Money(amount=gross, source_field="grossPay") if gross is not None else None,
                gross_wages=Money(amount=wages, source_field="grossWages") if wages is not None else None,
                net_pay=Money(amount=net, source_field="netPay") if net is not None else None,
                employee_taxes=derived_sum(
                    [t.amount.amount for t in taxes if t.paid_by is C.TaxPaidBy.EMPLOYEE],
                    "sum(taxes[isEmployeeTax].checkDollars)",
                )
                if has_lines
                else None,
                employer_taxes=derived_sum(
                    [t.amount.amount for t in taxes if t.paid_by is C.TaxPaidBy.EMPLOYER],
                    "sum(taxes[not isEmployeeTax].checkDollars)",
                )
                if has_lines
                else None,
                deductions=derived_sum(
                    [d.employee_amount.amount for d in deductions if d.employee_amount],
                    "sum(deductions[].checkDollars) + sum(garnishments[].checkDollars)",
                )
                if has_lines
                else None,
                employer_contributions=derived_sum(
                    [c.amount.amount for c in contributions], "sum(benefits[].checkEmployerContribution)"
                )
                if has_lines
                else None,
            ),
            earnings=earnings,
            taxes=taxes,
            deductions=deductions,
            employer_contributions=contributions,
            benefit_details=benefits,
            payments=payments,
            provider_extensions=without_links(sanitize_extensions(s.leftovers())),
            diagnostics=notes.items,
        )
        attach_checks(statement)
        self.out.add("pay_statements", statement)
