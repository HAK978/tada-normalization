"""Mapping files and the review queue for unmapped values (A-65, A-69).

The code tables in providers/*/codes.py hold what the provider documents. A tenant's own codes,
or a value no table knows yet, come out UNMAPPED. A mapping file resolves such values for one
tenant, without code changes:

    {"provider": "prismhr", "tenant": "970592",
     "mappings": [{"field": "compensation.citizenshipStatus", "raw": "Y", "value": "US_CITIZEN",
                   "companies": ["prismhr:970592:company:102"],
                   "evidence": "Tenant admin confirmed on 2026-10-14 that Y means citizen"}]}

Rules:
- a mapping only fills a value that would otherwise be UNMAPPED; it never overrides a code table;
- every entry needs written evidence; the value must be valid for that field's canonical enum
  (checked when applied);
- a file applies only to the tenant it names, and a rule with `companies` only to those companies
  (canonical company IDs), because a customer's code can mean different things in two of its
  companies. Without `companies`, a rule covers the whole tenant. Rules for one value whose
  companies overlap must agree.

Each record a mapping touched gets a MAPPED_BY_FILE info diagnostic quoting the evidence, and the
UNMAPPED_CODE warning it resolved is removed.

`review()` lists what is still unmapped across outputs, grouped into distinct decisions, and
`template()` turns that list into one mapping file per tenant to fill in.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .canonical.codes import Severity
from .canonical.types import MAPPING_COMPANY, MAPPING_OVERRIDE, Coded, Diagnostic, Raw
from .output import Output

# Reviewed mapping files shipped with the project (A-86). Each applies only to the tenant it names (A-69).
REVIEWED = Path(__file__).resolve().parents[2] / "mappings"


def reviewed() -> list[Path]:
    """The reviewed mapping files, in a fixed order."""
    return sorted(REVIEWED.glob("*.json"))


def _key(raw: Raw) -> str:
    return raw if isinstance(raw, str) else json.dumps(raw)


def _field(source_field: str | None) -> str:
    """Array positions don't change what a field means: deduction[3].period is deduction[].period."""
    return re.sub(r"\[\d+\]", "[]", source_field or "")


@dataclass
class Mapping:
    field: str
    raw: str
    value: str
    evidence: str
    companies: frozenset[str] | None = None  # canonical company IDs; None covers the whole tenant
    source: str = ""  # the file the rule came from
    applied: bool = False

    def covers(self, company: str | None) -> bool:
        return self.companies is None or company in self.companies


@dataclass
class Mappings:
    """Mapping rules for one provider tenant, keyed by (source field, raw value)."""

    provider: str
    tenant: str
    entries: dict[tuple[str, str], list[Mapping]] = dataclasses.field(default_factory=dict)
    used: set[tuple[str, str, str | None]] = dataclasses.field(default_factory=set)  # (field, raw, company)
    files: list[dict[str, Any]] = dataclasses.field(default_factory=list)  # the files loaded, for provenance
    skipped: list[str] = dataclasses.field(default_factory=list)  # files for another provider or tenant

    @classmethod
    def load(cls, paths: list[Path], provider: str, tenant: str) -> Mappings:
        result = cls(provider, tenant)
        for path in paths:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            if data.get("provider") != provider:
                result.skipped.append(f"{path}: for provider {data.get('provider')!r}")
                continue
            if not data.get("tenant"):
                raise ValueError(f"{path}: a mapping file must name its tenant (A-69)")
            if str(data["tenant"]) != tenant:
                result.skipped.append(f"{path}: for tenant {data['tenant']!r}")
                continue
            rules = 0
            for i, row in enumerate(data.get("mappings") or []):
                where = f"{path}: mappings[{i}]"
                if row.get("value") is None:
                    continue  # a template row not decided yet
                missing = [k for k in ("field", "raw", "value", "evidence") if not row.get(k) and row.get(k) != 0]
                if missing:
                    raise ValueError(f"{where}: missing {', '.join(missing)}; every mapping needs evidence")
                rule = Mapping(
                    _field(row["field"]),
                    _key(row["raw"]),
                    str(row["value"]),
                    row["evidence"],
                    _companies(row.get("companies"), where),
                    str(path),
                )
                result._add(rule, where)
                rules += 1
            result.files.append(
                {"path": str(path), "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "rules": rules}
            )
        return result

    def _add(self, rule: Mapping, where: str) -> None:
        rules = self.entries.setdefault((rule.field, rule.raw), [])
        for other in rules:
            if other.value != rule.value and _overlap(other.companies, rule.companies):
                scope = _scope(other.companies)
                raise ValueError(f"{where}: {(rule.field, rule.raw)} is already mapped to {other.value} for {scope}")
        rules.append(rule)
        rules.sort(key=lambda m: m.companies is None)  # rules for named companies before tenant-wide ones

    def rule(self, field_: str, raw: Raw, company: str | None) -> Mapping | None:
        return next((m for m in self.entries.get((_field(field_), _key(raw)), []) if m.covers(company)), None)

    def lookup(self, field_: str, raw: Raw) -> str | None:
        company = MAPPING_COMPANY.get()
        rule = self.rule(field_, raw, company)
        if rule is None:
            return None
        rule.applied = True
        self.used.add((rule.field, rule.raw, company))
        return rule.value

    def report(self) -> list[dict[str, Any]]:
        """Each file loaded, with its hash and which rules matched nothing: a value no longer seen, or a
        mistyped field, raw value or company ID."""
        rules = [rule for entries in self.entries.values() for rule in entries]
        return [
            {
                **file,
                "applied": sum(1 for r in rules if r.source == file["path"] and r.applied),
                "unapplied": [
                    {"field": r.field, "raw": r.raw, "companies": sorted(r.companies) if r.companies else None}
                    for r in rules
                    if r.source == file["path"] and not r.applied
                ],
            }
            for file in self.files
        ]


def _companies(value: Any, where: str) -> frozenset[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or not all(isinstance(c, str) and c for c in value):
        raise ValueError(f"{where}: companies must be a list of company IDs; leave it out to cover the whole tenant")
    return frozenset(value)


def _overlap(a: frozenset[str] | None, b: frozenset[str] | None) -> bool:
    return a is None or b is None or bool(a & b)


def _scope(companies: frozenset[str] | None) -> str:
    return "the whole tenant" if companies is None else ", ".join(sorted(companies))


def company_of(kind: str, record: Any) -> str | None:
    """The canonical ID of the company a record belongs to."""
    return record.id if kind == "companies" else getattr(record, "company_id", None)


@contextmanager
def active(mappings: Mappings | None) -> Iterator[None]:
    if mappings is None or not mappings.entries:
        yield
        return
    token = MAPPING_OVERRIDE.set(mappings.lookup)
    try:
        yield
    finally:
        MAPPING_OVERRIDE.reset(token)


def annotate(output: Output, mappings: Mappings | None) -> None:
    """Replace each resolved UNMAPPED_CODE warning with a MAPPED_BY_FILE note quoting the evidence."""
    if mappings is None or not mappings.used:
        return
    for kind, records in output.records.items():
        for record in records:
            company = company_of(kind, record)
            hits = {
                key
                for c in coded_values(record)
                if (*(key := (_field(c.source_field), _key(c.raw))), company) in mappings.used
            }
            if not hits:
                continue
            record.diagnostics = [
                d
                for d in record.diagnostics
                if not (d.code == "UNMAPPED_CODE" and (_field(d.field), _key(d.raw)) in hits)
            ]
            for key in sorted(hits):
                rule = mappings.rule(*key, company)
                if rule is None:
                    continue
                record.diagnostics.append(
                    Diagnostic(
                        code="MAPPED_BY_FILE",
                        severity=Severity.INFO,
                        field=rule.field,
                        message=f"mapped to {rule.value} by a mapping file: {rule.evidence}",
                        raw=rule.raw,
                    )
                )


def value_of(coded: Coded) -> str:
    return str(getattr(coded.value, "value", coded.value))


def kind_of(coded: Coded) -> type:
    """The canonical type of a coded value: an enum, or str for an open code."""
    args = type(coded).__pydantic_generic_metadata__["args"]
    return args[0] if args else str


def coded_values(node: Any) -> Iterator[Coded]:
    """Every Coded value anywhere inside a record."""
    if isinstance(node, Coded):
        yield node
    elif isinstance(node, BaseModel):
        for name in type(node).model_fields:
            yield from coded_values(getattr(node, name))
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from coded_values(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from coded_values(item)


@dataclass
class Unmapped:
    provider: str
    tenant: str
    field: str
    raw: str
    labels: Counter = dataclasses.field(default_factory=Counter)
    records: int = 0
    examples: list[str] = dataclasses.field(default_factory=list)
    companies: set[str] = dataclasses.field(default_factory=set)  # canonical IDs of the companies it was seen in
    kind: Any = str  # the canonical type: an enum, or str for an open code
    suggestions: list = dataclasses.field(default_factory=list)  # filled by normalization.suggest

    @property
    def allowed(self) -> list[str] | None:
        if isinstance(self.kind, type) and issubclass(self.kind, Enum):
            return [m.value for m in self.kind if m.value != "UNMAPPED"]
        return None


def review(outputs: list[tuple[str, Output]]) -> list[Unmapped]:
    """Every distinct still-unmapped (provider, tenant, field, raw value), most frequent first."""
    found: dict[tuple[str, str, str, str], Unmapped] = {}
    for provider, output in outputs:
        for kind, records in output.records.items():
            for record in records:
                company = company_of(kind, record)
                seen = set()
                for c in coded_values(record):
                    if value_of(c) != "UNMAPPED" or c.raw is None:
                        continue
                    key = (provider, record.source.tenant_id, _field(c.source_field), _key(c.raw))
                    item = found.setdefault(key, Unmapped(*key, kind=kind_of(c)))
                    if c.label:
                        item.labels[c.label] += 1
                    if company:
                        item.companies.add(company)
                    if key not in seen:
                        seen.add(key)
                        item.records += 1
                        if len(item.examples) < 3:
                            item.examples.append(record.id)
    return sorted(found.values(), key=lambda u: (-u.records, u.provider, u.tenant, u.field, u.raw))


def template(items: list[Unmapped]) -> dict[tuple[str, str], dict]:
    """One mapping file per (provider, tenant), every unmapped value listed with value/evidence left empty.

    Each row is limited to the companies the value was seen in. Removing `companies` widens a rule to
    the whole tenant, which is a decision of its own.
    """
    files: dict[tuple[str, str], dict] = {}
    for u in items:
        file = files.setdefault((u.provider, u.tenant), {"provider": u.provider, "tenant": u.tenant, "mappings": []})
        file["mappings"].append(
            {
                "field": u.field,
                "raw": u.raw,
                "label": u.labels.most_common(1)[0][0] if u.labels else None,
                "records": u.records,
                "companies": sorted(u.companies) or None,
                "allowed": u.allowed,
                "suggestions": [s.__dict__ for s in u.suggestions],
                "value": None,
                "evidence": None,
            }
        )
    return files


def render(items: list[Unmapped]) -> str:
    lines = [
        "# Unmapped values to review",
        "",
        "Each row is one decision: a provider value no code table or mapping file resolves yet. Fill in",
        "`value` and `evidence` in the matching mapping-file template, then normalize with `--mappings`.",
        "A template row covers only the companies the value was seen in; remove `companies` to cover the",
        "whole tenant.",
        "",
        "Suggestions are proposals only: arithmetic on the provider's own totals is evidence of cash vs",
        "non-cash; similar names are a hint for you, not evidence. Nothing is applied until a mapping file",
        "says so.",
        "",
        "| Provider | Tenant | Field | Raw value | Label | Companies | Records | Suggestions | Examples |",
        "|---|---|---|---|---|---:|---:|---|---|",
    ]
    for u in items:
        label = u.labels.most_common(1)[0][0] if u.labels else ""
        hints = "<br>".join(f"**{s.method}**: {' / '.join(s.values) or 'none'}. {s.reasoning}" for s in u.suggestions)
        lines.append(
            f"| {u.provider} | {u.tenant} | `{u.field}` | `{u.raw}` | {label} | {len(u.companies)} | {u.records} | "
            f"{hints} | " + ", ".join(f"`{e}`" for e in u.examples) + " |"
        )
    return "\n".join(lines) + "\n"
