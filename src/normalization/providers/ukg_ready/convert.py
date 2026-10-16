"""UKG Ready: raw bundle in, canonical records out.

A UKG company (cid) is the company, and its EINs are its legal employers (A-15, A-60). UKG returns
no gross or net, so both are derived from the lines and flagged (A-54). Times are milliseconds
(A-24), span dates follow UKG's documented convention (A-25), and time-dependent values are
evaluated at the bundle's as_of date (A-33). IDs live in the request path.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from normalization.bundle import Bundle, Capture
from normalization.canonical import codes as C
from normalization.canonical.records import (
    Address,
    BankAccount,
    Calculation,
    Company,
    Compensation,
    CompensationChange,
    Contact,
    ContributionLine,
    DeductionElection,
    DeductionLine,
    DirectDeposit,
    EarningLine,
    Email,
    Employee,
    EmployerRef,
    FrequencyInfo,
    Identifier,
    OrgAssignment,
    PaymentLine,
    PayrollRun,
    PayStatement,
    PayStatementTotals,
    PersonName,
    Phone,
    Prenote,
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
from normalization.source import Notes, Src, coded, decimal, flag, iso_date, text, unmapped_label

from ..common import (
    ZERO,
    address,
    attach_checks,
    categorized,
    customer_category,
    derived_sum,
    is_remainder,
    paid_gross,
    tax_type,
    unmasked_date,
    us_state,
)
from . import codes as U

PROVIDER = "ukg-ready"
ROOT = "rest/v2/companies/{company}"
EMP = ROOT + "/employees/{id}"
# Responses about one employee read into the employee record, besides the employee itself.
POSITION = ROOT + "/position/assignments/{id}"
PER_EMPLOYEE = (
    *(
        EMP + suffix
        for suffix in ("/pay-info", "/compensation/history", "/demographics", "/contacts", "/tax-info", "/benefits")
    ),
    POSITION,
)
RUN = ROOT + "/payrolls/{id}"
_IDS = re.compile(
    r"rest/v2/companies/(?P<company>[^/]+)"
    r"(?:/employees/(?P<employee>[^/]+))?"
    r"(?:/payrolls/(?P<payroll>[^/]+))?"
    r"(?:/pay-statements/(?P<statement>[^/]+))?"
    r"(?:/deductions/(?P<deduction>[^/]+))?"
)
# Position Management names the employee's account at the end of its path, not under /employees.
_POSITION = re.compile(r"rest/v2/companies/[^/]+/position/assignments/(?P<employee>[^/]+)$")
_TYPE_NAME = re.compile(r"^\s*([^()]*?)\s*(?:\(([^)]*)\))?\s*$")
# A state tax code: "<tax>:<state>[:<n>]", e.g. SIT:WI, SUTA:WI:2 (A-68)
_STATE_TAX = re.compile(r"([A-Z_]+):([A-Z]{2})(?::\d+)?")
MS_PER_HOUR = Decimal(3_600_000)
# Foundations.html: "beginning of time" and "end of time" (A-25).
OPEN_START, OPEN_END = date(1900, 1, 1), date(3000, 1, 1)
# Every UKG date field is documented as "within the 1900-12-31 and 2079-06-05 date range".
DOCUMENTED_RANGE = (date(1900, 12, 31), date(2079, 6, 5))
PENNY = Decimal("0.01")


def path_ids(capture: Capture) -> dict[str, str]:
    match = _IDS.match(capture.path)
    ids = {k: v for k, v in (match.groupdict() if match else {}).items() if v}
    if position := _POSITION.match(capture.path):
        ids["employee"] = position.group("employee")
    return ids


def request_scope(capture: Capture) -> list[tuple[str, dict[str, str]]]:
    """The records a request feeds, by the IDs in their Source.ids: its employee, else its company (A-70)."""
    ids = path_ids(capture)
    if not ids.get("company"):
        return []
    company = {"companyId": ids["company"]}
    employee = [("employees", company | {"accountId": ids["employee"]})] if ids.get("employee") else []
    return employee + [("companies", company)]


def without_links(extensions: dict[str, Any]) -> dict[str, Any]:
    """Hypermedia links are API navigation, not data, and are not kept (model §9)."""
    return {k: v for k, v in extensions.items() if not re.search(r"(^|\.)_links\.", k)}


def hours(value: Any, field: str) -> Quantity | None:
    """UKG times are milliseconds (A-24): converted to hours, with the raw value kept."""
    ms = decimal(value)
    if ms is None:
        return None
    return Quantity(
        value=ms / MS_PER_HOUR,
        unit=C.QuantityUnit.HOURS,
        raw=value,
        derived=True,
        formula=f"{field} / 3600000",
        source_field=field,
    )


def span_date(value: Any, field: str, notes: Notes) -> date | None:
    """A UKG span boundary: only the documented beginning and end of time become open (A-25)."""
    parsed = iso_date(value, field, notes)
    if parsed in (OPEN_START, OPEN_END):
        notes.info("OPEN_ENDED", field, "UKG's documented beginning or end of time; kept as open (A-25)", text(value))
        return None
    if parsed is not None and not DOCUMENTED_RANGE[0] < parsed <= DOCUMENTED_RANGE[1]:
        notes.info("UNDOCUMENTED_SENTINEL_DATE", field, "kept as a date; no documented meaning (A-25)", text(value))
    return parsed


def active_at(start: date | None, end: date | None, as_of: date) -> bool:
    """Foundations.html: effective dates are inclusive and expiration dates exclusive (A-25)."""
    return (start is None or start <= as_of) and (end is None or as_of < end)


def amount(value: Any, field: str, notes: Notes, currency: str | None = None) -> Money | None:
    """An amount exactly as sent. UKG documents amounts as floats "rounded to a Penny"; a value that is
    a binary floating-point form of a penny amount is reported, never changed (A-59)."""
    parsed = decimal(value)
    if parsed is None:
        return None
    exponent = parsed.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -6 and abs(parsed - parsed.quantize(PENNY)) < Decimal("1e-9"):
        notes.info("FLOAT_ARTIFACT", field, f"a binary floating-point form of {parsed.quantize(PENNY)}", str(value))
    return Money(amount=parsed, currency=currency or "USD", source_field=field)


def normalize(bundle: Bundle, as_of: date | None = None) -> Output:
    out = Output()
    companies = {str(c["company_id"]) for c in bundle.companies if c.get("company_id")}
    companies |= {ids["company"] for c in bundle.captures if (ids := path_ids(c)).get("company")}
    for company_id in sorted(companies):
        company = _Company(bundle, company_id, as_of or bundle.as_of, out)
        with company_scope(company.company_id):
            company.run()
    return out


class _Company:
    def __init__(self, bundle: Bundle, cid: str, as_of: date | None, out: Output):
        self.bundle, self.cid, self.as_of, self.out = bundle, cid, as_of, out
        self.tenant = bundle.tenant_id
        self.company_id = self._id("company", cid)
        self.lookups = {
            # A row without an ID can't be referenced, so it is not part of the lookup.
            name: {key: row for row in self._rows(f"{ROOT}/lookup/{name}", "items") if (key := text(row.get("id")))}
            for name in ("eins", "pay-types", "employee-types", "jobs")
        }
        # Cost centers by ID, and each tree's name: its root, which "has only id and name" (A-75).
        self.cost_centers: dict[str, tuple[str | None, dict]] = {}
        self.cost_center_trees: dict[str, str | None] = {}
        for capture in self._captures(f"{ROOT}/config/cost-centers"):
            tree = text(capture.params.get("tree_index"))
            for node in self._rows_of(capture, "cost_centers"):
                if (node_id := text(node.get("id"))) is not None:
                    self.cost_centers[node_id] = (tree, node)
                    if text(node.get("parent_id")) is None and tree is not None:
                        self.cost_center_trees[tree] = text(node.get("name"))

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

    def _captures(self, endpoint: str, **want: str):
        for capture in self.bundle.ok(endpoint):
            ids = path_ids(capture)
            if ids.get("company") == self.cid and all(ids.get(k) == v for k, v in want.items()):
                yield capture

    def _rows(self, endpoint: str, key: str, **want: str) -> list[dict]:
        rows: list[dict] = []
        for capture in self._captures(endpoint, **want):
            body = capture.body
            rows += (body.get(key) or []) if isinstance(body, dict) else []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def _rows_of(capture: Capture, key: str) -> list[dict]:
        rows = capture.body.get(key) if isinstance(capture.body, dict) else None
        return [r for r in rows or [] if isinstance(r, dict)]

    def _cost_center_path(self, node_id: str) -> list[str]:
        """Names from below the tree's root down to the cost center."""
        names: list[str] = []
        seen: set[str] = set()
        current: str | None = node_id
        while current is not None and current not in seen and current in self.cost_centers:
            seen.add(current)
            _, node = self.cost_centers[current]
            parent = text(node.get("parent_id"))
            if parent is None:
                break  # the root is the tree itself: its name is the dimension
            names.append(text(node.get("name")) or current)
            current = parent
        return names[::-1]

    def _named(self, lookup: str, ref: Src | None, key: str = "name") -> tuple[str | None, str | None]:
        """(id, name) of a lookup reference such as {"id": 35043008}."""
        ref_id = text(ref.get("id")) if ref else None
        return ref_id, text((self.lookups[lookup].get(ref_id) or {}).get(key)) if ref_id else None

    @staticmethod
    def _percent(value: Decimal | None, field: str) -> Percent | None:
        """UKG percents have no documented scale and no live examples (A-29)."""
        if value is None:
            return None
        return Percent(percent=None, scale=C.PercentScale.UNVERIFIED, raw=str(value), source_field=field)

    def _status_at(self, active: bool | None, start: date | None, end: date | None, notes: Notes, field: str):
        """Active only if the record says so and its span contains as_of (A-25, A-33)."""
        if active is False:
            return False
        if self.as_of is None:
            notes.warn("AS_OF_UNKNOWN", field, "no as_of date to evaluate the span against (A-33)")
            return None
        inside = active_at(start, end, self.as_of)
        notes.info("EVALUATED_AT_AS_OF", field, f"span {start}..{end} evaluated at {self.as_of} (A-33)")
        return inside if active is not None else None

    # -------------------------------------------------------------- run

    def run(self) -> None:
        self._company()
        employees: set[str] = set()
        for capture in self._captures(EMP):
            employee_id = path_ids(capture).get("employee")
            if isinstance(capture.body, dict) and employee_id and employee_id not in employees:
                employees.add(employee_id)
                self._employee(Src(capture.body), employee_id)
                self._deposits(employee_id)
                self._elections(employee_id)
        self._payroll_runs()
        self._pay_statements(employees)

    # -------------------------------------------------------------- company

    def _company(self) -> None:
        notes = Notes()
        notes.info("NO_COMPANY_ENDPOINT", None, "UKG has no company details endpoint; name and address stay null")
        employers: dict[str, EmployerRef] = {}
        extensions: dict[str, Any] = {}
        for ein_id, row in sorted(self.lookups["eins"].items()):
            e = Src(row, f"eins[{ein_id}]")
            tax_id = text(e.get("ein_tax_id"))
            employers[ein_id] = EmployerRef(
                kind=C.EmployerKind.EIN,
                provider_id=text(e.get("id")),
                name=text(e.get("ein_name")),
                tax_id=TaxIdentifier(value=tax_id, source_field="lookup/eins.ein_tax_id") if tax_id else None,
            )
            extensions.update(e.leftovers())
        # Payrolls can name EINs that lookup/eins doesn't list (A-60).
        for row, _ in self._run_rows().values():
            data = row.get("ein") or {}
            payroll_ein = text(data.get("id"))
            if payroll_ein and payroll_ein not in employers:
                ein = Src(data, f"payroll_eins[{payroll_ein}]")
                ein.get("id")
                tax_id = text(ein.get("ein_tax_id"))
                employers[payroll_ein] = EmployerRef(
                    kind=C.EmployerKind.EIN,
                    provider_id=payroll_ein,
                    name=text(ein.get("ein_name")),
                    tax_id=TaxIdentifier(value=tax_id, source_field="payrolls[].ein.ein_tax_id") if tax_id else None,
                )
                extensions.update(ein.leftovers())  # what else payrolls say about it, as for listed EINs
                notes.info(
                    "EIN_FROM_PAYROLL", "payrolls[].ein", "named by payrolls, not listed by lookup/eins", payroll_ein
                )
        self.out.add(
            "companies",
            Company(
                id=self.company_id,
                source=self._source([ROOT + "/lookup/eins", ROOT + "/payrolls"], companyId=self.cid),
                employers=[employers[k] for k in sorted(employers)],
                provider_extensions=sanitize_extensions(extensions),
                diagnostics=notes.items,
            ),
        )

    # -------------------------------------------------------------- employees

    def _employee(self, s: Src, employee_id: str) -> None:
        notes = Notes()
        s.get("id")
        # photo_href is a signed link that works as a credential (model §9); _links is navigation.
        s.mark("photo_href", "_links")

        identifiers = [Identifier(type=C.IdentifierType.PROVIDER_ID, value=employee_id, source_field="id")]
        for kind, field in (
            (C.IdentifierType.EMPLOYEE_NUMBER, "employee_id"),
            (C.IdentifierType.EXTERNAL_ID, "external_id"),
            (C.IdentifierType.USERNAME, "username"),
        ):
            value = text(s.get(field))
            if value:
                identifiers.append(Identifier(type=kind, value=value, source_field=field))

        national_id = None
        ssn = text(s.get("social_security"))
        if ssn:
            digits, was_masked = last4(ssn)
            national_id = NationalId(
                type=C.NationalIdType.SSN, last4=digits, masked_at_source=was_masked, source_field="social_security"
            )
        else:
            primary = next((n for n in s.children("national_id_numbers") if flag(n.get("primary"))), None)
            if primary is not None:
                digits, was_masked = last4(text(primary.get("value")))
                national_id = NationalId(
                    type=U.NATIONAL_ID_TYPE.get(text(primary.get("type")) or "", C.NationalIdType.OTHER),
                    last4=digits,
                    masked_at_source=was_masked,
                    source_field=f"{primary.path}.value",
                )
        # Other national ID numbers stay in provider_extensions, sanitized to their last 4 (A-23).

        dates = s.child("dates") or Src({})
        status_raw = text(s.get("status"))
        status = coded(U.EMPLOYEE_STATUS, status_raw, "status", notes, C.EmploymentStatus.UNMAPPED, label=status_raw)
        ein_id = text((s.child("ein") or Src({})).get("id"))
        s.mark("ein_name", why="the EIN's name, which the company's employers carry")

        addresses = [
            a
            for a in (
                self._address(C.AddressType.HOME, s.child("address")),
                self._address(C.AddressType.MAILING, s.child("mailing_address")),
            )
            if a
        ]
        phones_src = s.child("phones") or Src({})
        phones = [
            Phone(type=t, number=n)
            for t, n in (
                (C.PhoneType.HOME, text(phones_src.get("home_phone"))),
                (C.PhoneType.MOBILE, text(phones_src.get("cell_phone"))),
                (C.PhoneType.WORK, text(phones_src.get("work_phone"))),
            )
            if n
        ]
        email = text(s.get("primary_email"))
        # Ranked after primary_email; neither has a stated purpose (A-82).
        secondary_email = text(s.get("secondary_email"))
        kept: dict[str, Any] = {}
        managers = sorted(s.children("managers"), key=lambda m: decimal(m.get("index")) or ZERO)
        manager = text(((managers[0].child("empl_ref") or Src({})).get("account_id"))) if managers else None

        info = self._pay_info(employee_id)
        employee_type_id, employee_type = self._named("employee-types", info.child("employee_type"))
        pay_type_id, pay_type_name = self._named("pay-types", info.child("pay_type"))
        job_id, job_name = self._named("jobs", info.child("default_job"))

        history_extensions: dict[str, Any] = {}
        compensation = self._compensation(employee_id, pay_type_id, pay_type_name, notes, history_extensions)
        # pay-info standard_work_day is documented as milliseconds, as the organizer's reference audit cites (A-56).
        compensation.standard_work_day = hours(info.get("standard_work_day"), "pay-info.standard_work_day")

        employee = Employee(
            id=self._id("employee", employee_id),
            company_id=self.company_id,
            legal_entity_id=ein_id,
            source=self._source(
                [EMP] + [e for e in PER_EMPLOYEE if any(True for _ in self._captures(e, employee=employee_id))],
                companyId=self.cid,
                accountId=employee_id,
            ),
            identifiers=identifiers,
            national_id=national_id,
            name=dict(
                first=text(s.get("first_name")),
                middle=text(s.get("middle_name")),
                last=text(s.get("last_name")),
                nickname=text(s.get("nickname")),
            ),
            personal=dict(
                birth_date=iso_date(dates.get("birthday"), "dates.birthday", notes),
                **self._demographics(employee_id, notes, kept),
                contacts=self._contacts(employee_id, notes, kept),
            ),
            addresses=addresses,
            phones=phones,
            emails=[
                Email(type=t, address=a)
                for t, a in ((C.EmailType.MAIN, email), (C.EmailType.SECONDARY, secondary_email))
                if a
            ],
            employment=dict(
                status=status,
                employment_type=unmapped_label(employee_type_id, employee_type, "pay-info.employee_type.id"),
                hire_date=iso_date(dates.get("hired"), "dates.hired", notes),
                rehire_date=iso_date(dates.get("re_hired"), "dates.re_hired", notes),
                start_date=iso_date(dates.get("started"), "dates.started", notes),
                seniority_date=iso_date(dates.get("seniority"), "dates.seniority", notes),
                termination_date=iso_date(dates.get("terminated"), "dates.terminated", notes),
                employer_ids=[ein_id] if ein_id else [],
            ),
            job=dict(
                title=job_name,
                job_code=job_id,
                manager_employee_id=self._id("employee", manager) if manager else None,
                org_units=self._org_units(s, notes),
            ),
            compensation=compensation,
            diagnostics=notes.items,
        )
        # Only now has every mapped field been read, so the leftovers are exactly what wasn't mapped.
        extensions = without_links(sanitize_extensions(s.leftovers()))
        extensions.update(without_links(sanitize_extensions(info.leftovers())))
        extensions.update(history_extensions)
        # Kept unchanged: tax setup, as for the other providers (A-34), benefit plans and position assignments
        # (A-80).
        for endpoint, prefix in ((EMP + "/tax-info", "tax-info"), (EMP + "/benefits", ""), (POSITION, "position")):
            for capture in self._captures(endpoint, employee=employee_id):
                extensions.update(without_links(sanitize_extensions(Src(capture.body, prefix).leftovers())))
        extensions.update(kept)
        employee.provider_extensions = extensions
        self.out.add("employees", employee)

    @staticmethod
    def _address(kind: C.AddressType, a: Src | None) -> Address | None:
        return address(
            kind,
            a,
            line1="address_line_1",
            line2="address_line_2",
            city="city",
            state=("state_code", "state"),
            postal_code="zip",
            country="country",
        )

    def _demographics(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> dict[str, Any]:
        """Gender, ethnicity and citizenship. UKG documents them as enums without definitions, so they stay
        UNMAPPED with the value as sent until a mapping file confirms them (A-26, A-79)."""
        found: dict[str, Any] = {}
        for capture in self._captures(EMP + "/demographics", employee=employee_id):
            d = Src(capture.body, "demographics")
            for field, enum in (("gender", C.Gender), ("citizenship", C.Citizenship)):
                raw = text(d.get(field))
                if raw is not None:
                    notes.warn("UNMAPPED_CODE", f"demographics.{field}", "a documented value with no definition", raw)
                    found[field] = coded_type(enum)(value=enum.UNMAPPED, raw=raw, source_field=f"demographics.{field}")
            found["ethnicity"] = unmapped_label(d.get("ethnicity"), None, "demographics.ethnicity")
            kept.update(without_links(sanitize_extensions(d.leftovers())))
        return found

    def _contacts(self, employee_id: str, notes: Notes, kept: dict[str, Any]) -> list[Contact]:
        """Emergency contacts, dependents and beneficiaries (A-77)."""
        contacts = []
        for capture in self._captures(EMP + "/contacts", employee=employee_id):
            body = Src(capture.body)
            for c in body.children("contacts"):
                c.mark("employee", why="the employee's own account ID")
                phones = [
                    Phone(type=t, number=n)
                    for key, t in (
                        ("home_phone", C.PhoneType.HOME),
                        ("cell_phone", C.PhoneType.MOBILE),
                        ("work_phone", C.PhoneType.WORK),
                    )
                    if (n := text((c.child(key) or Src({})).get("number")))
                ]
                contacts.append(
                    Contact(
                        source_id=text(c.get("id")),
                        roles=[role for field, role in U.CONTACT_ROLES if flag(c.get(field))],
                        name=PersonName(
                            prefix=text(c.get("salutation")),
                            first=text(c.get("first_name")),
                            middle=text(c.get("middle_name")),
                            last=text(c.get("last_name")),
                            suffix=text(c.get("name_suffix")),
                        ),
                        relationship=text(c.get("relationship")),
                        primary=flag(c.get("primary")),
                        birth_date=unmasked_date(c, "birthdate", notes),
                        phones=phones,
                        source_field=c.path,
                    )
                )
            kept.update(without_links(sanitize_extensions(body.leftovers())))
        return contacts

    def _org_units(self, s: Src, notes: Notes) -> list[OrgAssignment]:
        """The employee's default cost centers. Each index is a cost-center tree, named by its root (A-75)."""
        units = []
        info = s.child("cost_centers_info")
        for d in info.children("defaults") if info else []:
            index = text(d.get("index"))
            value_id = text((d.child("value") or Src({})).get("id"))
            if value_id is None:
                continue
            tree, node = self.cost_centers.get(value_id, (None, None))
            if node is None:
                notes.warn(
                    "COST_CENTER_UNRESOLVED",
                    f"{d.path}.value.id",
                    f"not among the cost centers of tree {index}; kept by ID, without a name",
                    value_id,
                )
            elif tree != index:
                notes.warn("COST_CENTER_TREE_MISMATCH", f"{d.path}.index", f"the cost center is in tree {tree}", index)
            units.append(
                OrgAssignment(
                    dimension=self.cost_center_trees.get(index or ""),
                    code=value_id,
                    name=text(node.get("name")) if node else None,
                    path=self._cost_center_path(value_id) if node else [],
                    source_field=f"{d.path}.value.id",
                )
            )
        return units

    def _pay_info(self, employee_id: str) -> Src:
        capture = next(self._captures(EMP + "/pay-info", employee=employee_id), None)
        return Src(capture.body if capture else {}, "pay-info")

    def _compensation(
        self,
        employee_id: str,
        pay_type_id: str | None,
        pay_type_name: str | None,
        notes: Notes,
        extensions: dict[str, Any],
    ) -> Compensation:
        """The record in effect at as_of, plus every record as history; unread fields go to extensions."""
        rows = self._rows(EMP + "/compensation/history", "compensations", employee=employee_id)
        history: list[tuple[date | None, Src, CompensationChange]] = []
        for i, row in enumerate(rows):
            h = Src(row, f"compensation.history[{i}]")
            h.mark("_links")
            h.mark("employee", why="the employee's own account ID")
            effective = span_date(h.get("effective_from"), f"{h.path}.effective_from", notes)
            history.append(
                (
                    effective,
                    h,
                    CompensationChange(
                        source_id=text(h.get("id")),
                        effective_date=effective,
                        rates=self._rates(h, notes),
                        annual_pay=self._annual(h),
                        standard_hours=hours(h.get("time"), f"{h.path}.time"),
                    ),
                )
            )
        history.sort(key=lambda item: (item[0] or date.min, item[2].source_id or ""))
        # The current record is the latest one in effect at as_of (A-33); later ones are only history.
        in_effect = [item for item in history if self.as_of is None or item[0] is None or item[0] <= self.as_of]
        current = in_effect[-1] if in_effect else None
        if self.as_of is None and history:
            notes.warn("AS_OF_UNKNOWN", "compensation", "no as_of date; the latest record is used (A-33)")
        frequency, standard_hours, standard_per = None, None, None
        if current:
            _, h, change = current
            frequency = self._frequency(h.get("num_pp_in_year"), f"{h.path}.num_pp_in_year")
            standard_hours = change.standard_hours
            standard_per = text(h.get("time_period")) if standard_hours else None
        for _, h, _ in history:
            extensions.update(without_links(sanitize_extensions(h.leftovers())))
        return Compensation(
            pay_type=Coded[C.PayType](
                value=C.PayType.UNMAPPED, raw=pay_type_id, label=pay_type_name, source_field="pay-info.pay_type.id"
            )
            if pay_type_id
            else None,
            pay_frequency=frequency,
            rates=current[2].rates if current else [],
            annual_pay=current[2].annual_pay if current else None,
            standard_hours=standard_hours,
            standard_hours_per=standard_per,
            effective_date=current[0] if current else None,
            history=[change for _, _, change in history],
        )

    @staticmethod
    def _placeholder(h: Src) -> bool:
        """The 1900-12-31 rows with no amount and 0 pay periods (A-56); a real zero pay is kept."""
        return decimal(h.data.get("amount")) in (None, ZERO) and decimal(h.data.get("num_pp_in_year")) in (None, ZERO)

    def _rates(self, h: Src, notes: Notes) -> list[Rate]:
        """amount per amount_period, plus hourly_pay; live they agree on all 27 records (A-56)."""
        rates: list[Rate] = []
        if self._placeholder(h):
            return rates  # its fields stay raw in provider_extensions
        value, period = decimal(h.get("amount")), text(h.data.get("amount_period"))
        currency = text(h.get("currency")) or "USD"
        if value is not None:
            # An undefined period is not read, so it stays as sent in provider_extensions next to an UNMAPPED rate.
            per = U.RATE_PERIOD.get(period or "")
            if per is not None:
                h.get("amount_period")
            else:
                notes.warn("UNMAPPED_CODE", f"{h.path}.amount_period", "a documented value with no definition", period)
            rates.append(
                Rate(amount=value, currency=currency, per=per or C.RatePeriod.UNMAPPED, source_field=f"{h.path}.amount")
            )
        hourly = decimal(h.get("hourly_pay"))
        if hourly is not None and period != "HOUR":
            rates.append(
                Rate(amount=hourly, currency=currency, per=C.RatePeriod.HOUR, source_field=f"{h.path}.hourly_pay")
            )
        return rates

    def _annual(self, h: Src) -> Money | None:
        value = decimal(h.data.get("amount"))
        if h.data.get("amount_period") == "YEAR" and value is not None and not self._placeholder(h):
            return Money(amount=value, currency=text(h.data.get("currency")) or "USD", source_field=f"{h.path}.amount")
        return None

    def _frequency(self, count: Any, field: str) -> FrequencyInfo | None:
        """num_pp_in_year is a count; 0 means not set (A-56)."""
        n = decimal(count)
        if n is None or n == ZERO:
            return None
        periods = int(n)
        return FrequencyInfo(
            frequency=Coded[C.PayFrequency](
                value=U.FREQUENCY_BY_COUNT.get(periods, C.PayFrequency.OTHER), raw=count, source_field=field
            ),
            periods_per_year=periods,
        )

    # -------------------------------------------------------------- direct deposits

    def _deposits(self, employee_id: str) -> None:
        for i, row in enumerate(self._rows(EMP + "/direct-deposits", "deposits", employee=employee_id)):
            notes = Notes()
            s = Src(row)
            s.mark("_links")
            deposit_id = text(s.get("id")) or str(i)
            method_src = s.child("calc_method") or Src({})
            method_raw, method_label = text(method_src.get("type")), text(method_src.get("display_name"))
            method = coded(U.DD_METHOD, method_raw, "calc_method.type", notes, C.DepositMethod.UNMAPPED, method_label)
            if method is None:
                method = Coded[C.DepositMethod](value=C.DepositMethod.UNMAPPED, source_field="calc_method.type")
                notes.warn("NO_ALLOCATION", "calc_method", "no calculation method")
            # The deposit states its own currency (#/schemas/137); its amount is in that currency.
            value = amount(s.get("amount"), "amount", notes, text(s.data.get("currency")))
            pct = decimal(s.get("percentage"))
            kind = text(s.get("type"))
            if kind == U.RESERVE_LIVE_CHECK:
                account_type = coded(
                    U.DD_ACCOUNT_TYPE, kind, "type", notes, C.AccountType.UNMAPPED, empty_is_none=False
                )
            else:
                account_type = coded(
                    U.DD_ACCOUNT_TYPE,
                    s.get("account_type"),
                    "account_type",
                    notes,
                    C.AccountType.UNMAPPED,
                    empty_is_none=False,
                )
                if kind and kind != "DIRECT_DEPOSIT":
                    notes.warn("UNMAPPED_CODE", "type", "deposit type without a documented meaning", kind)
            account = text(s.get("account_number"))
            digits, was_masked = last4(account)
            start = span_date(s.get("active_from"), "active_from", notes)
            end = span_date(s.get("active_to"), "active_to", notes)
            active = flag(s.get("active"))
            live = self._status_at(active, start, end, notes, "active")
            frequency = text((s.child("payroll_frequency") or Src({})).get("type"))
            prenote_status = text(s.get("pre_note_status"))
            self.out.add(
                "direct_deposits",
                DirectDeposit(
                    id=self._id("direct_deposit", deposit_id),
                    source=self._source(
                        [EMP + "/direct-deposits"], companyId=self.cid, accountId=employee_id, depositId=deposit_id
                    ),
                    employee_id=self._id("employee", employee_id),
                    company_id=self.company_id,
                    purpose=C.DepositPurpose.NET_PAY,
                    account=BankAccount(
                        type=account_type,
                        routing_number=text(s.get("routing_number")),
                        routing_type=text(s.get("routing_type")),
                        account_last4=digits,
                        masked_at_source=was_masked if account else None,
                    ),
                    method=method,
                    amount=value,
                    percent=self._percent(pct, "percentage"),
                    sequence=int(seq) if (seq := decimal(s.get("sequence"))) is not None else None,
                    is_remainder=is_remainder(method.value),
                    status=Coded[C.DepositStatus](
                        value=C.DepositStatus.UNMAPPED
                        if live is None
                        else (C.DepositStatus.ACTIVE if live else C.DepositStatus.INACTIVE),
                        raw=active,
                        source_field="active + active_from/active_to",
                    ),
                    effective_from=start,
                    effective_to=end,
                    frequency=Coded[str](value="UNMAPPED", raw=frequency, source_field="payroll_frequency.type")
                    if frequency
                    else None,
                    prenote=Prenote(
                        status=Coded[str](value="UNMAPPED", raw=prenote_status, source_field="pre_note_status")
                        if prenote_status
                        else None,
                        sent_date=iso_date(s.get("pre_note_sent_date"), "pre_note_sent_date", notes),
                        expiration_date=iso_date(s.get("pre_note_expiration_date"), "pre_note_expiration_date", notes),
                    )
                    if prenote_status or s.data.get("pre_note_sent_date")
                    else None,
                    currency=text(s.get("currency")),
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )

    # -------------------------------------------------------------- deduction setup

    def _elections(self, employee_id: str) -> None:
        """Documented setup endpoints (#/schemas/132, #/schemas/133); the live tenant returns 404 (A-12)."""
        details = {
            path_ids(c).get("deduction"): c.body
            for c in self._captures(EMP + "/deductions/{id}", employee=employee_id)
            if isinstance(c.body, dict)
        }
        for row in self._rows(EMP + "/deductions", "deductions", employee=employee_id):
            notes = Notes()
            deduction_id = text(row.get("id")) or ""
            detailed = deduction_id in details
            s = Src(details[deduction_id] if detailed else row)
            s.mark("_links")
            s.get("id")
            if not detailed:
                notes.info(
                    "DETAIL_NOT_FETCHED", None, "from the deductions list; calculation details weren't requested"
                )
            deduction = s.child("deduction") or Src({})
            code, label = text(deduction.get("code")) or "", text(deduction.get("name"))
            calc = s.child("ee_calc_method") or Src({})
            method = calc.child("method") or Src({})
            method_raw, method_label = text(method.get("type")), text(method.get("display_name"))
            pct = decimal(calc.get("percent"))
            calculation = None
            if method_raw:
                # The method type is an open string with no documented values (model §7).
                calculation = Calculation(
                    method=Coded[C.CalculationMethod](
                        value=C.CalculationMethod.UNMAPPED,
                        raw=method_raw,
                        label=method_label,
                        source_field="ee_calc_method.method.type",
                    ),
                    percent=self._percent(pct, "ee_calc_method.percent"),
                )
            if (
                any(s.data.get(k) is not None for k in ("annual_max_amount", "er_annual_max_amount"))
                or calc.data.get("amount") is not None
            ):
                notes.info(
                    "AMOUNT_UNIT_UNVERIFIED",
                    None,
                    "setup amounts are typed integer, with no documented unit (dollars or cents); kept raw (A-12)",
                )
            start = span_date(s.get("effective_from"), "effective_from", notes)
            end = span_date(s.get("effective_to"), "effective_to", notes)
            live = self._status_at(True, start, end, notes, "effective_from/effective_to")
            frequency = s.child("ee_frequency") or Src({})
            frequency_raw = text(frequency.get("type"))
            self.out.add(
                "deduction_elections",
                DeductionElection(
                    id=self._id("deduction_election", deduction_id),
                    source=self._source(
                        [EMP + "/deductions", EMP + "/deductions/{id}"] if detailed else [EMP + "/deductions"],
                        companyId=self.cid,
                        accountId=employee_id,
                        deductionId=deduction_id,
                    ),
                    employee_id=self._id("employee", employee_id),
                    company_id=self.company_id,
                    code=code,
                    label=label,
                    # Deduction codes are tenant-configured, with no provider classification (A-35).
                    category=Coded[C.DeductionCategory](
                        value=C.DeductionCategory.UNMAPPED, raw=code or None, label=label, source_field="deduction.code"
                    ),
                    calculation=calculation,
                    status=Coded[C.ElectionStatus](
                        value=C.ElectionStatus.UNMAPPED
                        if live is None
                        else (C.ElectionStatus.ACTIVE if live else C.ElectionStatus.INACTIVE),
                        source_field="effective_from/effective_to",
                    ),
                    frequency=Coded[str](
                        value="UNMAPPED",
                        raw=frequency_raw,
                        label=text(frequency.get("display_name")),
                        source_field="ee_frequency.type",
                    )
                    if frequency_raw
                    else None,
                    effective_from=start,
                    effective_to=end,
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )

    # -------------------------------------------------------------- payroll runs

    def _run_rows(self) -> dict[str, tuple[dict, bool]]:
        """Payrolls by ID: the detail when fetched, else the row from the payroll list."""
        rows: dict[str, tuple[dict, bool]] = {}
        for row in self._rows(ROOT + "/payrolls", "payrolls"):
            if payroll_id := text(row.get("id")):
                rows.setdefault(payroll_id, (row, False))
        for capture in self._captures(RUN):
            payroll_id = path_ids(capture).get("payroll")
            if payroll_id and isinstance(capture.body, dict):
                rows[payroll_id] = (capture.body, True)
        return rows

    def _payroll_runs(self) -> None:
        for payroll_id, (body, detailed) in sorted(self._run_rows().items()):
            notes = Notes()
            s = Src(body)
            s.mark("_links")
            s.mark(
                "ein.ein_name",
                "ein.ein_tax_id",
                "ein.ein_country_id",
                why="the EIN's details, on the company's employers",
            )
            s.get("id")
            run_type = s.child("type") or Src({})
            type_name = text(run_type.get("display_name"))
            status_raw = text(s.get("status"))
            if status_raw != "FINALIZED":
                notes.info("NOT_FINALIZED", "status", "not finalized; amounts may still change (A-13)", status_raw)
            self.out.add(
                "payroll_runs",
                PayrollRun(
                    id=self._id("payroll_run", payroll_id),
                    source=self._source(
                        [RUN if detailed else ROOT + "/payrolls"], companyId=self.cid, payrollId=payroll_id
                    ),
                    company_id=self.company_id,
                    pay_date=iso_date(s.get("pay_date"), "pay_date", notes),
                    processed_date=iso_date(s.get("date_finalized"), "date_finalized", notes),
                    description=text(s.get("name")),
                    type=coded(U.RUN_TYPE, type_name, "type.display_name", notes, C.PayrollRunType.UNMAPPED, type_name)
                    or Coded[C.PayrollRunType](value=C.PayrollRunType.UNMAPPED, source_field="type.display_name"),
                    status=coded(U.RUN_STATUS, status_raw, "status", notes, C.PayrollRunStatus.UNMAPPED),
                    period=DateRange(
                        start=iso_date(s.get("start_date"), "start_date", notes),
                        end=iso_date(s.get("end_date"), "end_date", notes),
                    ),
                    legal_entity_id=text((s.child("ein") or Src({})).get("id")),
                    provider_extensions=without_links(sanitize_extensions(s.leftovers())),
                    diagnostics=notes.items,
                ),
            )

    # -------------------------------------------------------------- pay statements

    def _pay_statements(self, employees: set[str]) -> None:
        found: dict[str, tuple[dict, bool, str | None]] = {}
        for capture in self._captures(RUN + "/pay-statements"):
            payroll_id = path_ids(capture).get("payroll")
            rows = capture.body.get("pay_statements") if isinstance(capture.body, dict) else None
            for row in rows or []:
                if isinstance(row, dict) and (statement_id := text(row.get("id"))):
                    found.setdefault(statement_id, (row, False, payroll_id))
        for capture in self._captures(RUN + "/pay-statements/{id}"):
            ids = path_ids(capture)
            if ids.get("statement") and isinstance(capture.body, dict):
                found[ids["statement"]] = (capture.body, True, ids.get("payroll"))
        for statement_id, (body, detailed, payroll_id) in sorted(found.items()):
            self._pay_statement(Src(body), statement_id, detailed, payroll_id, employees)

    def _earning_kind(self, type_name: str | None, notes: Notes) -> Coded[C.EarningKind]:
        """UKG's own line type: "<kind> (<modifiers>)"; an unknown modifier leaves it UNMAPPED (A-58)."""
        match = _TYPE_NAME.match(type_name or "")
        base = match.group(1) if match else None
        modifiers = {m.strip() for m in (match.group(2) or "").split(",") if m.strip()} if match else set()
        if base in U.EARNING_TYPE and modifiers <= U.KNOWN_MODIFIERS:
            value = C.EarningKind.NON_CASH_FRINGE if U.FRINGE in modifiers else U.EARNING_TYPE[base]
        else:
            value = C.EarningKind.UNMAPPED
            notes.warn("UNMAPPED_CODE", "earnings[].type_name", "no evidenced meaning for this line type", type_name)
        return Coded[C.EarningKind](value=value, raw=type_name, source_field="earnings[].type_name")

    @staticmethod
    def _tax_type(code: str | None, label: str | None, notes: Notes) -> tuple[Coded[C.TaxType] | None, str | None]:
        """Documented and evidenced codes exactly; state taxes as "<tax>:<state>[:<n>]" (A-68)."""
        found: tuple[C.TaxType, str | None] | None = None
        if code in U.TAX_CODE:
            found = (U.TAX_CODE[code], None)
        elif (match := _STATE_TAX.fullmatch(code or "")) and (state := us_state(match[2])):
            value = U.STATE_TAX_PREFIX.get(match[1])
            found = (value, state) if value else None
        return tax_type(found, code, "taxes[].company_tax.code", notes, label)

    @staticmethod
    def _line_rate(line: Src, quantity: Quantity | None, value: Money, notes: Notes) -> Rate | None:
        """base_rate is the employee's base hourly rate. It is this line's rate only where hours x base_rate =
        amount; premium lines multiply it (overtime: 1.5 on every live line) and keep it raw (A-24)."""
        base = decimal(line.data.get("base_rate"))
        if quantity is None or base is None:
            return None
        if abs(quantity.value * base - value.amount) <= PENNY:
            line.get("base_rate")
            return Rate(amount=base, per=C.RatePeriod.HOUR, source_field="earnings[].base_rate")
        if quantity.value * base:
            ratio = (value.amount / (quantity.value * base)).quantize(Decimal("0.0001"))
            notes.info(
                "BASE_RATE_NOT_LINE_RATE",
                "earnings[].base_rate",
                f"amount = {ratio} x hours x base_rate; base_rate is kept raw (A-24)",
                str(base),
            )
        return None

    @staticmethod
    def _allocation(line: Src) -> dict[str, str]:
        allocation = {}
        for cc in line.children("cost_centers"):
            value = cc.child("value") or Src({})
            name = text(value.first("display_name", "name")) or text(value.get("id"))
            if name:
                allocation[f"cost_center[{text(cc.get('index'))}]"] = name
        return allocation

    def _pay_statement(
        self, s: Src, statement_id: str, detailed: bool, payroll_id: str | None, employees: set[str]
    ) -> None:
        notes = Notes()
        s.mark("_links")
        s.get("id")
        employee_id = text((s.child("employee") or Src({})).get("account_id")) or ""
        if not detailed:
            notes.info("DETAIL_NOT_FETCHED", None, "from the payroll's statement list; line items were not requested")
        if employee_id not in employees:
            notes.info("EMPLOYEE_NOT_IN_BUNDLE", "employee.account_id", "employee record was not fetched", employee_id)
        if payroll_id and self._id("payroll_run", payroll_id) not in self.out.ids("payroll_runs"):
            notes.info("RUN_NOT_IN_BUNDLE", None, "the statement's payroll was not fetched into the bundle", payroll_id)
        status_raw = text(s.get("status"))
        if status_raw != "FINALIZED":
            notes.info("NOT_FINALIZED", "status", "not finalized; amounts may still change (A-13)", status_raw)

        earnings = []
        for line in s.children("earnings"):
            value = amount(line.get("ee_amount"), "earnings[].ee_amount", notes)
            if value is None:
                continue  # no money on this statement; the line stays in provider_extensions
            item = line.child("earning") or Src({})
            quantity = hours(line.get("hours"), "earnings[].hours")
            rate = self._line_rate(line, quantity, value, notes)
            code, label = text(item.get("code")), text(item.get("name"))
            kind = self._earning_kind(text(line.get("type_name")), notes)
            earnings.append(
                EarningLine(
                    code=code,
                    label=label,
                    kind=kind,
                    # UKG doesn't classify earning codes: the tenant's own, left for review (A-67)
                    category=customer_category(code, label, "earnings[].earning.code") if categorized(kind) else None,
                    in_gross=True,  # gross wages are derived as the sum of every line (A-54)
                    quantity=quantity,
                    rate=rate,
                    amount=value,
                    period=DateRange(
                        start=iso_date(line.get("date_range_from"), "earnings[].date_range_from", notes),
                        end=iso_date(line.get("date_range_to"), "earnings[].date_range_to", notes),
                    )
                    if line.data.get("date_range_from") or line.data.get("date_range_to")
                    else None,
                    allocation=self._allocation(line),
                    source_field="earnings[]",
                )
            )

        taxes = []
        for line in s.children("taxes"):
            tax = line.child("company_tax") or Src({})
            code, label = text(tax.get("code")), text(tax.get("name"))
            tax_kind, state = self._tax_type(code, label, notes)
            for paid_by, prefix in ((C.TaxPaidBy.EMPLOYEE, "ee"), (C.TaxPaidBy.EMPLOYER, "er")):
                value = amount(line.get(f"{prefix}_amount"), f"taxes[].{prefix}_amount", notes)
                if value is not None:
                    taxes.append(
                        TaxLine(
                            code=code,
                            label=label,
                            type=tax_kind,
                            state=state,
                            paid_by=paid_by,
                            amount=value,
                            taxable_wages=amount(
                                line.get(f"{prefix}_subject_wage"), f"taxes[].{prefix}_subject_wage", notes
                            ),
                            source_field="taxes[]",
                        )
                    )

        deductions, contributions = [], []
        for line in s.children("deductions"):
            item = line.child("deduction") or Src({})
            code, label = text(item.get("code")), text(item.get("name"))
            employee_value = amount(line.get("ee_amount"), "deductions[].ee_amount", notes)
            employer_value = amount(line.get("er_amount"), "deductions[].er_amount", notes)
            if employee_value is not None:
                deductions.append(
                    DeductionLine(
                        code=code,
                        external_id=text(item.get("external_id")),
                        label=label,
                        category=Coded[C.DeductionCategory](
                            value=C.DeductionCategory.UNMAPPED,
                            raw=code,
                            label=label,
                            source_field="deductions[].deduction.code",
                        ),
                        employee_amount=employee_value,
                        source_field="deductions[]",
                    )
                )
            if employer_value is not None:
                contributions.append(
                    ContributionLine(
                        code=code, label=label, amount=employer_value, source_field="deductions[].er_amount"
                    )
                )

        payments = []
        for line in s.children("payments"):
            type_name = text(line.data.get("type_name"))
            if type_name == U.FRINGE_PAYMENT:
                continue  # balances the non-cash earnings; nothing is paid (A-58). Kept in extensions.
            value = amount(line.get("ee_amount"), "payments[].ee_amount", notes)
            if value is None:
                continue
            payments.append(
                PaymentLine(
                    kind=coded(
                        U.PAYMENT_TYPE,
                        line.get("type_name"),
                        "payments[].type_name",
                        notes,
                        C.PaymentKind.UNMAPPED,
                        empty_is_none=False,
                    ),
                    amount=value,
                    source_field="payments[]",
                )
            )

        has_lines = bool(earnings or taxes or deductions)
        wages = derived_sum([e.amount for e in earnings], "sum(earnings[].ee_amount)") if earnings else None
        cash = [p.amount for p in payments if p.kind.value is not C.PaymentKind.UNMAPPED]
        if any(p.kind.value is C.PaymentKind.UNMAPPED for p in payments):
            # A payment of unknown kind may or may not be cash, so net pay can't be derived (A-58).
            cash = []
            notes.info("NET_PAY_NOT_DERIVED", "payments", "a payment of unknown kind could be cash or not")
        type_src = s.child("type") or Src({})
        type_name = text(type_src.get("display_name"))
        statement = PayStatement(
            id=self._id("pay_statement", statement_id),
            source=self._source(
                [RUN + "/pay-statements/{id}" if detailed else RUN + "/pay-statements"],
                companyId=self.cid,
                payrollId=payroll_id,
                payStatementId=statement_id,
            ),
            company_id=self.company_id,
            employee_id=self._id("employee", employee_id),
            # Statements are read under their payroll, so the link comes from the request path.
            payroll_run_id=self._id("payroll_run", payroll_id) if payroll_id else None,
            pay_date=iso_date(s.get("pay_date"), "pay_date", notes),
            period=DateRange(
                start=iso_date(s.get("pay_period_start"), "pay_period_start", notes),
                end=iso_date(s.get("pay_period_end"), "pay_period_end", notes),
            ),
            type=coded(U.STATEMENT_TYPE, type_name, "type.display_name", notes, C.PayStatementType.UNMAPPED, type_name)
            or Coded[C.PayStatementType](value=C.PayStatementType.UNMAPPED, source_field="type.display_name"),
            status=unmapped_label(status_raw, None, "status"),
            totals=PayStatementTotals(
                gross_wages=wages,
                gross_pay=paid_gross(wages, earnings, "sum(earnings[].ee_amount)", notes),
                net_pay=derived_sum(cash, "sum(payments[Check, Direct Deposit].ee_amount)") if cash else None,
                employee_taxes=derived_sum(
                    [t.amount for t in taxes if t.paid_by is C.TaxPaidBy.EMPLOYEE], "sum(taxes[].ee_amount)"
                )
                if has_lines
                else None,
                employer_taxes=derived_sum(
                    [t.amount for t in taxes if t.paid_by is C.TaxPaidBy.EMPLOYER], "sum(taxes[].er_amount)"
                )
                if has_lines
                else None,
                deductions=derived_sum(
                    [d.employee_amount for d in deductions if d.employee_amount], "sum(deductions[].ee_amount)"
                )
                if has_lines
                else None,
                employer_contributions=derived_sum([c.amount for c in contributions], "sum(deductions[].er_amount)")
                if has_lines
                else None,
            ),
            earnings=earnings,
            taxes=taxes,
            deductions=deductions,
            employer_contributions=contributions,
            payments=payments,
            provider_extensions=without_links(sanitize_extensions(s.leftovers())),
            diagnostics=notes.items,
        )
        attach_checks(statement)
        self.out.add("pay_statements", statement)
