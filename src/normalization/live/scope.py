"""Scope guard for live provider calls.

The demo tokens are write-capable and are not limited to the demo companies,
so every live request is checked before it is sent: it must stay on the base
URL returned by /signin, match an allowlisted read endpoint, and reference
only the demo company IDs returned by /signin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


class ScopeError(Exception):
    """Raised for a request outside the demo scope; nothing is sent."""


@dataclass(frozen=True)
class Companies:
    """Demo company identifiers from /signin, compared as strings."""

    clients: frozenset[str] = frozenset()
    legals: frozenset[tuple[str, str]] = frozenset()
    companies: frozenset[str] = frozenset()

    @classmethod
    def from_signin(cls, provider: str, entries: list[dict]) -> Companies:
        def ids(key: str) -> list[str]:
            return [str(entry[key]) for entry in entries if entry.get(key) not in (None, "")]

        if provider == "prismhr":
            return cls(clients=frozenset(ids("client_id")))
        if provider == "isolved":
            pairs = frozenset(
                (str(entry["client_id"]), str(entry["legal_id"]))
                for entry in entries
                if entry.get("client_id") not in (None, "") and entry.get("legal_id") not in (None, "")
            )
            return cls(clients=frozenset(client for client, _ in pairs), legals=pairs)
        if provider == "ukg-ready":
            return cls(companies=frozenset(ids("company_id")))
        raise ValueError(f"unknown provider {provider!r}")


# PrismHR addresses operations as {service}/v1/{operation}; every one listed
# here is a documented GET that takes a clientId query parameter.
PRISM_OPERATIONS = frozenset(
    {
        "clientMaster/v1/getClientMaster",
        "clientMaster/v1/getClientCodes",
        "clientMaster/v1/getPayrollSchedule",
        "clientMaster/v1/getAllPrismClientContacts",
        "employee/v1/getEmployeeList",
        "employee/v1/getEmployee",
        "employee/v1/getPayRateHistory",
        "employee/v1/getScheduledDeductions",
        "employee/v1/getHistory",
        "employee/v1/checkForGarnishments",
        "deductions/v1/getDeductions",
        "deductions/v1/getVoluntaryRecurringDeductions",
        "deductions/v1/getEmployeeLoans",
        "deductions/v1/getGarnishmentDetails",
        "benefits/v1/getActiveBenefitPlans",
        "benefits/v1/getDependents",
        "payroll/v1/getBatchListByDate",
        "payroll/v1/getBatchInfo",
        "payroll/v1/getPayrollVoucherForBatch",
        "payroll/v1/getScheduledPayments",
    }
)

# The one operation not keyed by clientId. Without an employerId it lists every employer
# in the tenant, so it is only allowed for employer IDs that demo clients reference.
PRISM_EMPLOYER_OPERATION = "system/v1/getEmployerDetails"

ISOLVED_TEMPLATES = (
    "api/clients/{client}",
    "api/clients/{client}/payItems",
    "api/clients/{client}/legals/{legal}",
    "api/clients/{client}/legals/{legal}/checks",
    "api/clients/{client}/legals/{legal}/employees",
    "api/clients/{client}/legals/{legal}/employees/{id}",
    "api/clients/{client}/legals/{legal}/employees/{id}/directdeposits",
    "api/clients/{client}/legals/{legal}/employees/{id}/salaries",
    "api/clients/{client}/legals/{legal}/employees/{id}/statuses",
    "api/clients/{client}/legals/{legal}/employees/{id}/payRates",
    "api/clients/{client}/legals/{legal}/employees/{id}/payItems",
    "api/clients/{client}/legals/{legal}/employees/{id}/garnishments",
    "api/clients/{client}/legals/{legal}/employees/{id}/payroll",
    "api/clients/{client}/legals/{legal}/employees/{id}/checks",
    "api/clients/{client}/legals/{legal}/employees/{id}/checks/{id}",
    "api/clients/{client}/legals/{legal}/employees/{id}/contacts",
    "api/clients/{client}/legals/{legal}/employees/{id}/veteranStatus",
    "api/clients/{client}/legals/{legal}/employees/{id}/jobs",
    "api/clients/{client}/legals/{legal}/employees/{id}/categories",
    "api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory",
    "api/clients/{client}/legals/{legal}/paygroupId/{id}/payrollRunHistory/{id}",
    "api/corestream/clients/{client}/legals/{legal}/employees/{id}/deductions",
    "api/corestream/clients/{client}/legals/{legal}/paygroups/{id}/payrolls/{id}",
    "api/lookup/Frequencies",
    "api/lookup/genders",
    "api/lookup/maritalStatuses",
    "api/lookup/ethnicorigins",
    "api/lookup/citizenships",
    "api/lookup/ContactRelationshipCodes",
    "api/system/payTypes",
    "api/system/earnings",
)

UKG_TEMPLATES = (
    "rest/v2/companies/{company}/lookup/eins",
    "rest/v2/companies/{company}/lookup/earning-codes",
    "rest/v2/companies/{company}/lookup/deduction-codes",
    "rest/v2/companies/{company}/lookup/pay-types",
    "rest/v2/companies/{company}/lookup/payroll-types",
    "rest/v2/companies/{company}/lookup/pay-statement-types",
    "rest/v2/companies/{company}/lookup/employee-types",
    "rest/v2/companies/{company}/lookup/jobs",
    "rest/v2/companies/{company}/config/cost-centers",
    "rest/v2/companies/{company}/employees",
    "rest/v2/companies/{company}/employees/{id}",
    "rest/v2/companies/{company}/employees/{id}/pay-info",
    "rest/v2/companies/{company}/employees/{id}/compensation/history",
    "rest/v2/companies/{company}/employees/{id}/demographics",
    "rest/v2/companies/{company}/employees/{id}/contacts",
    "rest/v2/companies/{company}/employees/{id}/tax-info",
    "rest/v2/companies/{company}/employees/{id}/benefits",
    "rest/v2/companies/{company}/employees/{id}/direct-deposits",
    "rest/v2/companies/{company}/employees/{id}/deductions",
    "rest/v2/companies/{company}/employees/{id}/deductions/{id}",
    "rest/v2/companies/{company}/position/assignments/{id}",
    "rest/v2/companies/{company}/payrolls",
    "rest/v2/companies/{company}/payrolls/{id}",
    "rest/v2/companies/{company}/payrolls/{id}/pay-statements",
    "rest/v2/companies/{company}/payrolls/{id}/pay-statements/{id}",
)

# A path segment may not start with "." so "." and ".." can never match.
_SEGMENT = r"([A-Za-z0-9_~-][A-Za-z0-9_.~-]*)"


def _compile(template: str) -> tuple[re.Pattern[str], tuple[str, ...]]:
    names, parts = [], []
    for segment in template.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            names.append(segment[1:-1])
            parts.append(_SEGMENT)
        else:
            parts.append(re.escape(segment))
    return re.compile("/".join(parts)), tuple(names)


_TEMPLATES = {
    "isolved": [(template, *_compile(template)) for template in ISOLVED_TEMPLATES],
    "ukg-ready": [(template, *_compile(template)) for template in UKG_TEMPLATES],
}


def check(
    provider: str,
    base_url: str,
    companies: Companies,
    url: str,
    params: dict | None = None,
    employers: frozenset[str] = frozenset(),
) -> str:
    """Return the matched endpoint id, or raise ScopeError without sending anything.

    employers: PrismHR employer IDs referenced by the demo clients' own getClientMaster responses.
    """
    base, target = urlsplit(base_url), urlsplit(url)
    if (target.scheme, target.netloc.lower()) != (base.scheme, base.netloc.lower()):
        raise ScopeError(f"{url} is not on the /signin base URL host")
    if target.query or target.fragment:
        raise ScopeError("pass query parameters separately so they can be checked")
    prefix = base.path.rstrip("/") + "/"
    if not target.path.startswith(prefix):
        raise ScopeError(f"{target.path} is outside the /signin base URL path")
    relative = target.path[len(prefix) :].rstrip("/")
    params = params or {}
    if provider == "prismhr":
        return _check_prism(relative, params, companies, employers)
    if provider in _TEMPLATES:
        return _check_template(provider, relative, companies)
    raise ScopeError(f"unknown provider {provider!r}")


def _check_prism(operation: str, params: dict, companies: Companies, employers: frozenset[str]) -> str:
    if operation == PRISM_EMPLOYER_OPERATION:
        employer = params.get("employerId")
        if not isinstance(employer, (str, int)) or str(employer) not in employers:
            raise ScopeError(f"employerId {employer!r} is not referenced by a demo client")
        return operation
    if operation not in PRISM_OPERATIONS:
        raise ScopeError(f"PrismHR operation {operation!r} is not allowlisted")
    client = params.get("clientId")
    if not isinstance(client, (str, int)) or str(client) not in companies.clients:
        raise ScopeError(f"clientId {client!r} is not a demo client from /signin")
    return operation


def _check_template(provider: str, relative: str, companies: Companies) -> str:
    for template, pattern, names in _TEMPLATES[provider]:
        match = pattern.fullmatch(relative)
        if not match:
            continue
        values = dict(zip(names, match.groups(), strict=True))
        if "company" in values and values["company"] not in companies.companies:
            raise ScopeError(f"company {values['company']!r} is not the demo company from /signin")
        if "legal" in values and (values["client"], values["legal"]) not in companies.legals:
            raise ScopeError(f"client/legal {values['client']}/{values['legal']} is not a demo pair from /signin")
        if "client" in values and values["client"] not in companies.clients:
            raise ScopeError(f"client {values['client']!r} is not a demo client from /signin")
        return template
    raise ScopeError(f"{provider} path {relative!r} is not allowlisted")
