"""Dry-run write: a canonical employee as the UKG Ready requests that would create it (A-63).

Nothing is sent. UKG documents that creating an employee "covers the core fields of the
employee" and that related data needs further calls, so the plan is two requests:

1. POST /v2/companies/{cid}/employees (core fields, #/schemas/105);
2. POST /v2/companies/{cid}/compensation/history (pay, #/schemas/32), for the account that
   step 1 creates.

Each body is validated against UKG's documented request schema. A value the canonical record
can't supply is a gap with its reason, never invented; a destination default is listed as one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from jsonschema import Draft4Validator
from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "contracts/ukg-ready/reference-schemas.json"
EMPLOYEE_SCHEMA, COMPENSATION_SCHEMA = 105, 32
MS_PER_HOUR = 3_600_000
# canonical rate period -> UKG compensation amount_period (#/schemas/32 enum)
AMOUNT_PERIOD = {"HOUR": "HOUR", "WEEK": "WEEK", "MONTH": "MONTH", "YEAR": "YEAR", "PAY_PERIOD": "PAY_PERIOD"}
TIME_PERIOD = {"WEEK": "WEEK", "MONTH": "MONTH", "YEAR": "YEAR", "PAY_PERIOD": "PAY_PERIOD"}
PHONES = {"HOME": "home_phone", "MOBILE": "cell_phone", "WORK": "work_phone"}
# Placeholder for the account ID that step 1 returns; replaced before step 2 is sent.
NEW_ACCOUNT = 0


@dataclass
class Request:
    step: int
    method: str
    path: str
    schema: str
    body: dict
    errors: list[str] = field(default_factory=list)


@dataclass
class Plan:
    employee_id: str
    company: str
    requests: list[Request] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    defaults: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(r.errors for r in self.requests)

    def to_dict(self) -> dict:
        return {
            "destination": "ukg-ready",
            "dry_run": True,
            "employee_id": self.employee_id,
            "company": self.company,
            "valid": self.valid,
            "requests": [r.__dict__ for r in self.requests],
            "gaps": self.gaps,
            "defaults": self.defaults,
            "notes": self.notes,
        }


def _schema(index: int) -> dict:
    return json.loads(SCHEMAS.read_text(encoding="utf-8"))["schemas"][index]["schema"]


def _errors(index: int, body: dict) -> list[str]:
    schema = _schema(index)
    validator = validator_for(schema, default=Draft4Validator)(schema)
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in validator.iter_errors(body)]


def _first(items: list[dict], kind: str, *types: str) -> Any:
    for wanted in types:
        for item in items:
            if item.get("type") == wanted:
                return item.get(kind)
    return None


def plan(employee: dict, company: str = "{cid}", ein_id: int | None = None) -> Plan:
    """The requests that would create this canonical employee (as dumped JSON) in UKG Ready."""
    result = Plan(employee_id=employee["id"], company=company)

    def gap(name: str, reason: str) -> None:
        result.gaps.append({"field": name, "reason": reason})

    identifiers = employee.get("identifiers", [])
    name = employee.get("name", {})
    employment = employee.get("employment", {})
    body: dict[str, Any] = {
        "username": _first(identifiers, "value", "USERNAME"),
        "first_name": name.get("first"),
        "middle_name": name.get("middle"),
        "last_name": name.get("last"),
        "nickname": name.get("preferred"),
        "suffix": name.get("suffix"),
        "employee_id": _first(identifiers, "value", "EMPLOYEE_NUMBER"),
        # Where the record came from, so the destination can be traced back to the source.
        "external_id": employee["id"],
        "primary_email": _first(employee.get("emails", []), "address", "MAIN", "WORK"),
        "secondary_email": _first(employee.get("emails", []), "address", "PERSONAL"),
    }
    if body["username"] is None:
        gap("username", "UKG requires a username and the source has none; one is never made up")
    if body["employee_id"] and len(body["employee_id"]) > 20:
        gap("employee_id", "longer than UKG's 20 characters")
        body["employee_id"] = None

    dates = {
        "hired": employment.get("hire_date"),
        "re_hired": employment.get("rehire_date"),
        "started": employment.get("start_date"),
        "seniority": employment.get("seniority_date"),
        "birthday": employee.get("personal", {}).get("birth_date"),
    }
    body["dates"] = {k: v for k, v in dates.items() if v}

    addresses = {a.get("type"): a for a in employee.get("addresses", [])}
    for kind, key in (("HOME", "address"), ("MAILING", "mailing_address")):
        if kind in addresses:
            body[key] = _address(addresses[kind], key, gap, result)
    if "mailing_address" in body:
        body["use_separate_mailing_address"] = True
    phones = {PHONES[p["type"]]: p["number"] for p in reversed(employee.get("phones", [])) if p.get("type") in PHONES}
    if phones:
        body["phones"] = phones

    national = employee.get("national_id") or {}
    if national:
        gap(
            "social_security",
            "the canonical model keeps only the last 4 digits (A-23); a real write needs the full number "
            "from a secure source",
        )
    if ein_id is not None:
        body["ein"] = {"id": ein_id}
    else:
        result.notes.append("No --ein-id: UKG uses `ein` only for multi-EIN companies.")
    status = (employment.get("status") or {}).get("value")
    if status and status != "ACTIVE":
        result.notes.append(
            f"The source status is {status}. UKG's `status` is read-only on create; a termination needs a "
            "later update (`termination_details`)."
        )
    if employee.get("job", {}).get("manager_employee_id"):
        gap("managers", "the manager's account ID in the destination is unknown until that manager exists there")

    body = _clean(body)
    result.requests.append(
        Request(1, "POST", f"/v2/companies/{company}/employees", "#/schemas/105", body, _errors(EMPLOYEE_SCHEMA, body))
    )
    compensation = _compensation(employee.get("compensation", {}), gap, result)
    if compensation is not None:
        result.requests.append(
            Request(
                2,
                "POST",
                f"/v2/companies/{company}/compensation/history",
                "#/schemas/32",
                compensation,
                _errors(COMPENSATION_SCHEMA, compensation),
            )
        )
    return result


def _address(address: dict, key: str, gap, result: Plan) -> dict:
    country = address.get("country")
    if country is None:
        country = "USA"
        result.defaults.append(
            {
                "field": f"{key}.country",
                "value": "USA",
                "reason": "UKG requires an ISO alpha-3 country; the source sent none, and all three source "
                "providers are US payroll systems",
            }
        )
    if address.get("county"):
        gap(f"{key}.county", "UKG addresses have no county field")
    return {
        "address_line_1": address.get("line1"),
        "address_line_2": address.get("line2"),
        "address_line_3": address.get("line3"),
        "city": address.get("city"),
        "state_code": address.get("state"),
        "zip": address.get("postal_code"),
        "country": country,
    }


def _compensation(comp: dict, gap, result: Plan) -> dict | None:
    """One UKG compensation record: the amount on the employee's own pay basis (A-63)."""
    rates = comp.get("rates", [])
    pay_type = (comp.get("pay_type") or {}).get("value")
    chosen = None
    if pay_type == "SALARY" and comp.get("annual_pay"):
        chosen = {**comp["annual_pay"], "per": "YEAR"}
    elif pay_type == "HOURLY":
        chosen = next((r for r in rates if r.get("per") == "HOUR"), None)
    if chosen is None:
        chosen = next((r for r in rates if r.get("per") in AMOUNT_PERIOD), None)
    if chosen is None:
        gap("compensation", "no rate with a period UKG supports (year, month, week, hour, pay period)")
        return None
    result.notes.append(f"Pay amount taken from {chosen.get('source_field') or 'the canonical rate'}.")

    body: dict[str, Any] = {
        "employee": {"account_id": NEW_ACCOUNT},
        "effective_from": comp.get("effective_date"),
        "amount": Decimal(chosen["amount"]),
        "amount_period": AMOUNT_PERIOD[chosen["per"]],
        "currency": chosen.get("currency"),
        "num_pp_in_year": (comp.get("pay_frequency") or {}).get("periods_per_year"),
    }
    result.notes.append("`employee.account_id` 0 stands for the account ID that step 1 returns.")
    standard = comp.get("standard_hours")
    per = TIME_PERIOD.get(comp.get("standard_hours_per") or "")
    if standard and per:
        body["time"] = int(Decimal(standard["value"]) * MS_PER_HOUR)
        body["time_period"] = per
    else:
        gap("time", "UKG requires standard hours with their period; the source has none UKG can express")
    if body["effective_from"] is None:
        gap("effective_from", "UKG requires the date the pay takes effect; the source has none")
    if body["num_pp_in_year"] is None:
        gap("num_pp_in_year", "UKG requires pay periods per year; the source pay frequency doesn't give them")
    return _clean(body)


def _clean(value: Any) -> Any:
    """Drop empty values: UKG's request schemas don't accept nulls."""
    if isinstance(value, dict):
        cleaned = {k: _clean(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, "", {}, [])}
    return value
