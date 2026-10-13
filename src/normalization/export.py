"""Writing normalized output: one JSON file per record type, and one SQLite database (A-36).

SQLite holds every record twice: as typed columns for querying and joining (canonical IDs link
company -> employee -> deposits, elections and pay statements), and as the full canonical JSON in
the `record` column, so nothing is lost. Money and other decimals are TEXT, exactly as in the JSON:
SQLite has no decimal type and REAL would round them, so CAST to REAL only for rough arithmetic.
Foreign keys are declared for tooling but not enforced, because a paycheck may name an employee
whose record wasn't fetched (EMPLOYEE_NOT_IN_BUNDLE); `PRAGMA foreign_key_check` lists those.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

from . import exactjson
from .canonical.records import dump
from .output import Output

SCHEMA = """
CREATE TABLE companies (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    name TEXT,
    legal_name TEXT,
    parent_code TEXT,
    parent_name TEXT,
    status TEXT,
    status_raw TEXT,
    own_tax_id TEXT,
    service_arrangement TEXT,
    record TEXT NOT NULL
);
CREATE TABLE company_employers (
    company_id TEXT NOT NULL REFERENCES companies(id),
    line INTEGER NOT NULL,
    kind TEXT NOT NULL,
    provider_id TEXT,
    name TEXT,
    tax_id TEXT,
    PRIMARY KEY (company_id, line)
);
CREATE TABLE employees (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    legal_entity_id TEXT,
    first_name TEXT,
    middle_name TEXT,
    last_name TEXT,
    birth_date TEXT,
    ssn_last4 TEXT,
    status TEXT,
    status_raw TEXT,
    employment_type TEXT,
    employment_type_label TEXT,
    worker_classification TEXT,
    hire_date TEXT,
    rehire_date TEXT,
    termination_date TEXT,
    job_title TEXT,
    pay_type TEXT,
    pay_type_label TEXT,
    pay_frequency TEXT,
    periods_per_year INTEGER,
    annual_pay TEXT,
    record TEXT NOT NULL
);
CREATE TABLE employee_rates (
    employee_id TEXT NOT NULL REFERENCES employees(id),
    line INTEGER NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT,
    per TEXT NOT NULL,
    derived INTEGER NOT NULL,
    source_field TEXT,
    PRIMARY KEY (employee_id, line)
);
CREATE TABLE direct_deposits (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    company_id TEXT NOT NULL REFERENCES companies(id),
    purpose TEXT NOT NULL,
    sequence INTEGER,
    method TEXT NOT NULL,
    method_raw TEXT,
    method_label TEXT,
    amount TEXT,
    percent TEXT,
    percent_scale TEXT,
    percent_raw TEXT,
    is_remainder INTEGER NOT NULL,
    account_type TEXT,
    account_last4 TEXT,
    routing_number TEXT,
    status TEXT,
    effective_from TEXT,
    effective_to TEXT,
    record TEXT NOT NULL
);
CREATE TABLE deduction_elections (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    company_id TEXT NOT NULL REFERENCES companies(id),
    code TEXT NOT NULL,
    label TEXT,
    category TEXT NOT NULL,
    category_raw TEXT,
    tax_treatment TEXT,
    calculation_method TEXT,
    calculation_method_label TEXT,
    calculation_basis TEXT,
    amount TEXT,
    percent TEXT,
    percent_raw TEXT,
    status TEXT,
    effective_from TEXT,
    effective_to TEXT,
    record TEXT NOT NULL
);
CREATE TABLE payroll_runs (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL REFERENCES companies(id),
    pay_date TEXT,
    description TEXT,
    type TEXT NOT NULL,
    type_raw TEXT,
    status TEXT,
    status_raw TEXT,
    legal_entity_id TEXT,
    record TEXT NOT NULL
);
CREATE TABLE pay_statements (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    company_id TEXT NOT NULL REFERENCES companies(id),
    payroll_run_id TEXT REFERENCES payroll_runs(id),
    pay_date TEXT,
    period_start TEXT,
    period_end TEXT,
    check_number TEXT,
    type TEXT NOT NULL,
    type_raw TEXT,
    voided INTEGER NOT NULL,
    gross_wages TEXT,
    gross_wages_derived INTEGER,
    gross_pay TEXT,
    gross_pay_derived INTEGER,
    net_pay TEXT,
    net_pay_derived INTEGER,
    employee_taxes TEXT,
    employer_taxes TEXT,
    deductions TEXT,
    employer_contributions TEXT,
    record TEXT NOT NULL
);
CREATE TABLE earning_lines (
    pay_statement_id TEXT NOT NULL REFERENCES pay_statements(id),
    line INTEGER NOT NULL,
    code TEXT,
    label TEXT,
    kind TEXT NOT NULL,
    kind_raw TEXT,
    in_gross INTEGER,
    quantity TEXT,
    quantity_unit TEXT,
    rate TEXT,
    rate_per TEXT,
    amount TEXT NOT NULL,
    PRIMARY KEY (pay_statement_id, line)
);
CREATE TABLE tax_lines (
    pay_statement_id TEXT NOT NULL REFERENCES pay_statements(id),
    line INTEGER NOT NULL,
    code TEXT,
    label TEXT,
    paid_by TEXT NOT NULL,
    amount TEXT NOT NULL,
    taxable_wages TEXT,
    PRIMARY KEY (pay_statement_id, line)
);
CREATE TABLE deduction_lines (
    pay_statement_id TEXT NOT NULL REFERENCES pay_statements(id),
    line INTEGER NOT NULL,
    code TEXT,
    external_id TEXT,
    label TEXT,
    category TEXT,
    category_raw TEXT,
    tax_treatment TEXT,
    employee_amount TEXT,
    employer_amount TEXT,
    PRIMARY KEY (pay_statement_id, line)
);
CREATE TABLE contribution_lines (
    pay_statement_id TEXT NOT NULL REFERENCES pay_statements(id),
    line INTEGER NOT NULL,
    code TEXT,
    label TEXT,
    amount TEXT NOT NULL,
    PRIMARY KEY (pay_statement_id, line)
);
CREATE TABLE payment_lines (
    pay_statement_id TEXT NOT NULL REFERENCES pay_statements(id),
    line INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount TEXT NOT NULL,
    account_last4 TEXT,
    PRIMARY KEY (pay_statement_id, line)
);
CREATE TABLE checks (
    pay_statement_id TEXT NOT NULL REFERENCES pay_statements(id),
    line INTEGER NOT NULL,
    rule TEXT NOT NULL,
    result TEXT NOT NULL,
    detail TEXT,
    PRIMARY KEY (pay_statement_id, line)
);
CREATE TABLE diagnostics (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    line INTEGER NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    field TEXT,
    message TEXT,
    raw TEXT,
    PRIMARY KEY (record_id, line)
);
CREATE INDEX employees_company ON employees(company_id);
CREATE INDEX direct_deposits_employee ON direct_deposits(employee_id);
CREATE INDEX deduction_elections_employee ON deduction_elections(employee_id);
CREATE INDEX payroll_runs_company ON payroll_runs(company_id);
CREATE INDEX pay_statements_employee ON pay_statements(employee_id);
CREATE INDEX pay_statements_run ON pay_statements(payroll_run_id);
CREATE INDEX diagnostics_code ON diagnostics(code);
CREATE VIEW pay_statement_overview AS
SELECT s.id, c.provider, s.employee_id, e.first_name, e.last_name, s.pay_date,
       s.gross_wages, s.gross_pay, s.net_pay,
       (SELECT COUNT(*) FROM checks k WHERE k.pay_statement_id = s.id AND k.result = 'pass') AS checks_passed,
       (SELECT COUNT(*) FROM checks k WHERE k.pay_statement_id = s.id AND k.result = 'fail') AS checks_failed
FROM pay_statements s
JOIN companies c ON c.id = s.company_id
LEFT JOIN employees e ON e.id = s.employee_id;
"""


def write_json(output: Output, directory: Path) -> list[Path]:
    """<directory>/<record type>.json (records sorted by id) and summary.json."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, records in output.records.items():
        path = directory / f"{kind}.json"
        rows = [dump(r) for r in sorted(records, key=lambda r: r.id)]
        path.write_text(exactjson.dumps(rows, indent=1) + "\n", encoding="utf-8")
        written.append(path)
    summary = directory / "summary.json"
    summary.write_text(json.dumps(output.summary(), indent=1) + "\n", encoding="utf-8")
    return [*written, summary]


def write_sqlite(outputs: Iterable[Output], path: Path) -> Path:
    """A fresh database holding every given output; canonical IDs are unique across providers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as db:
        db.executescript(SCHEMA)
        for output in outputs:
            for kind, records in output.records.items():
                for record in sorted(records, key=lambda r: r.id):
                    data = dump(record)
                    _ROWS[kind](db, data)
                    for i, d in enumerate(data.get("diagnostics", [])):
                        _insert(
                            db,
                            "diagnostics",
                            record_type=kind,
                            record_id=data["id"],
                            line=i,
                            severity=d["severity"],
                            code=d["code"],
                            field=d.get("field"),
                            message=d.get("message"),
                            raw=_raw(d.get("raw")),
                        )
        db.commit()
    return path


# ---------------------------------------------------------------- rows


def _at(data: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def _raw(value: Any) -> str | None:
    """A provider's raw value as text; non-strings keep their JSON form (true, 26)."""
    return value if value is None or isinstance(value, str) else json.dumps(value)


def _flag(value: Any) -> int | None:
    return None if value is None else int(bool(value))


def _record(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))


def _insert(db: sqlite3.Connection, table: str, **row: Any) -> None:
    columns = ", ".join(row)
    db.execute(f"INSERT INTO {table} ({columns}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


def _company(db: sqlite3.Connection, c: dict) -> None:
    _insert(
        db,
        "companies",
        id=c["id"],
        provider=c["source"]["provider"],
        tenant_id=c["source"]["tenant_id"],
        name=c.get("name"),
        legal_name=c.get("legal_name"),
        parent_code=_at(c, "parent.code"),
        parent_name=_at(c, "parent.name"),
        status=_at(c, "status.value"),
        status_raw=_raw(_at(c, "status.raw")),
        own_tax_id=_at(c, "own_tax_id.value"),
        service_arrangement=_at(c, "service_arrangement.value"),
        record=_record(c),
    )
    for i, e in enumerate(c.get("employers", [])):
        _insert(
            db,
            "company_employers",
            company_id=c["id"],
            line=i,
            kind=e["kind"],
            provider_id=e.get("provider_id"),
            name=e.get("name"),
            tax_id=_at(e, "tax_id.value"),
        )


def _employee(db: sqlite3.Connection, e: dict) -> None:
    comp = e.get("compensation", {})
    _insert(
        db,
        "employees",
        id=e["id"],
        company_id=e["company_id"],
        legal_entity_id=e.get("legal_entity_id"),
        first_name=_at(e, "name.first"),
        middle_name=_at(e, "name.middle"),
        last_name=_at(e, "name.last"),
        birth_date=_at(e, "personal.birth_date"),
        ssn_last4=_at(e, "national_id.last4"),
        status=_at(e, "employment.status.value"),
        status_raw=_raw(_at(e, "employment.status.raw")),
        employment_type=_at(e, "employment.employment_type.value"),
        employment_type_label=_at(e, "employment.employment_type.label"),
        worker_classification=_at(e, "employment.worker_classification.value"),
        hire_date=_at(e, "employment.hire_date"),
        rehire_date=_at(e, "employment.rehire_date"),
        termination_date=_at(e, "employment.termination_date"),
        job_title=_at(e, "job.title"),
        pay_type=_at(comp, "pay_type.value"),
        pay_type_label=_at(comp, "pay_type.label"),
        pay_frequency=_at(comp, "pay_frequency.frequency.value"),
        periods_per_year=_at(comp, "pay_frequency.periods_per_year"),
        annual_pay=_at(comp, "annual_pay.amount"),
        record=_record(e),
    )
    for i, r in enumerate(comp.get("rates", [])):
        _insert(
            db,
            "employee_rates",
            employee_id=e["id"],
            line=i,
            amount=r["amount"],
            currency=r.get("currency"),
            per=r["per"],
            derived=_flag(r.get("derived")),
            source_field=r.get("source_field"),
        )


def _deposit(db: sqlite3.Connection, d: dict) -> None:
    _insert(
        db,
        "direct_deposits",
        id=d["id"],
        employee_id=d["employee_id"],
        company_id=d["company_id"],
        purpose=d["purpose"],
        sequence=d.get("sequence"),
        method=_at(d, "method.value"),
        method_raw=_raw(_at(d, "method.raw")),
        method_label=_at(d, "method.label"),
        amount=_at(d, "amount.amount"),
        percent=_at(d, "percent.percent"),
        percent_scale=_at(d, "percent.scale"),
        percent_raw=_at(d, "percent.raw"),
        is_remainder=_flag(d["is_remainder"]),
        account_type=_at(d, "account.type.value"),
        account_last4=_at(d, "account.account_last4"),
        routing_number=_at(d, "account.routing_number"),
        status=_at(d, "status.value"),
        effective_from=d.get("effective_from"),
        effective_to=d.get("effective_to"),
        record=_record(d),
    )


def _election(db: sqlite3.Connection, d: dict) -> None:
    _insert(
        db,
        "deduction_elections",
        id=d["id"],
        employee_id=d["employee_id"],
        company_id=d["company_id"],
        code=d["code"],
        label=d.get("label"),
        category=_at(d, "category.value"),
        category_raw=_raw(_at(d, "category.raw")),
        tax_treatment=d.get("tax_treatment"),
        calculation_method=_at(d, "calculation.method.value"),
        calculation_method_label=_at(d, "calculation.method.label"),
        calculation_basis=_at(d, "calculation.basis"),
        amount=_at(d, "calculation.amount.amount"),
        percent=_at(d, "calculation.percent.percent"),
        percent_raw=_at(d, "calculation.percent.raw"),
        status=_at(d, "status.value"),
        effective_from=d.get("effective_from"),
        effective_to=d.get("effective_to"),
        record=_record(d),
    )


def _run(db: sqlite3.Connection, r: dict) -> None:
    _insert(
        db,
        "payroll_runs",
        id=r["id"],
        company_id=r["company_id"],
        pay_date=r.get("pay_date"),
        description=r.get("description"),
        type=_at(r, "type.value"),
        type_raw=_raw(_at(r, "type.raw")),
        status=_at(r, "status.value"),
        status_raw=_raw(_at(r, "status.raw")),
        legal_entity_id=r.get("legal_entity_id"),
        record=_record(r),
    )


def _statement(db: sqlite3.Connection, s: dict) -> None:
    totals = s.get("totals", {})
    _insert(
        db,
        "pay_statements",
        id=s["id"],
        employee_id=s["employee_id"],
        company_id=s["company_id"],
        payroll_run_id=s.get("payroll_run_id"),
        pay_date=s.get("pay_date"),
        period_start=_at(s, "period.start"),
        period_end=_at(s, "period.end"),
        check_number=s.get("check_number"),
        type=_at(s, "type.value"),
        type_raw=_raw(_at(s, "type.raw")),
        voided=_flag(s.get("voided")),
        gross_wages=_at(totals, "gross_wages.amount"),
        gross_wages_derived=_flag(_at(totals, "gross_wages.derived")),
        gross_pay=_at(totals, "gross_pay.amount"),
        gross_pay_derived=_flag(_at(totals, "gross_pay.derived")),
        net_pay=_at(totals, "net_pay.amount"),
        net_pay_derived=_flag(_at(totals, "net_pay.derived")),
        employee_taxes=_at(totals, "employee_taxes.amount"),
        employer_taxes=_at(totals, "employer_taxes.amount"),
        deductions=_at(totals, "deductions.amount"),
        employer_contributions=_at(totals, "employer_contributions.amount"),
        record=_record(s),
    )
    sid = s["id"]
    for i, e in enumerate(s.get("earnings", [])):
        _insert(
            db,
            "earning_lines",
            pay_statement_id=sid,
            line=i,
            code=e.get("code"),
            label=e.get("label"),
            kind=_at(e, "kind.value"),
            kind_raw=_raw(_at(e, "kind.raw")),
            in_gross=_flag(e.get("in_gross")),
            quantity=_at(e, "quantity.value"),
            quantity_unit=_at(e, "quantity.unit"),
            rate=_at(e, "rate.amount"),
            rate_per=_at(e, "rate.per"),
            amount=_at(e, "amount.amount"),
        )
    for i, t in enumerate(s.get("taxes", [])):
        _insert(
            db,
            "tax_lines",
            pay_statement_id=sid,
            line=i,
            code=t.get("code"),
            label=t.get("label"),
            paid_by=t["paid_by"],
            amount=_at(t, "amount.amount"),
            taxable_wages=_at(t, "taxable_wages.amount"),
        )
    for i, d in enumerate(s.get("deductions", [])):
        _insert(
            db,
            "deduction_lines",
            pay_statement_id=sid,
            line=i,
            code=d.get("code"),
            external_id=d.get("external_id"),
            label=d.get("label"),
            category=_at(d, "category.value"),
            category_raw=_raw(_at(d, "category.raw")),
            tax_treatment=d.get("tax_treatment"),
            employee_amount=_at(d, "employee_amount.amount"),
            employer_amount=_at(d, "employer_amount.amount"),
        )
    for i, c in enumerate(s.get("employer_contributions", [])):
        _insert(
            db,
            "contribution_lines",
            pay_statement_id=sid,
            line=i,
            code=c.get("code"),
            label=c.get("label"),
            amount=_at(c, "amount.amount"),
        )
    for i, p in enumerate(s.get("payments", [])):
        _insert(
            db,
            "payment_lines",
            pay_statement_id=sid,
            line=i,
            kind=_at(p, "kind.value"),
            amount=_at(p, "amount.amount"),
            account_last4=p.get("account_last4"),
        )
    for i, k in enumerate(s.get("checks", [])):
        _insert(db, "checks", pay_statement_id=sid, line=i, rule=k["rule"], result=k["result"], detail=k.get("detail"))


_ROWS: dict[str, Callable[[sqlite3.Connection, dict], None]] = {
    "companies": _company,
    "employees": _employee,
    "direct_deposits": _deposit,
    "deduction_elections": _election,
    "payroll_runs": _run,
    "pay_statements": _statement,
}
