"""Mapping files and the review queue for unmapped values (A-65).

The code tables in providers/*/codes.py hold what the provider documents. A tenant's own codes,
or a value no table knows yet, come out UNMAPPED. A mapping file resolves such values without
code changes:

    {"provider": "prismhr",
     "mappings": [{"field": "compensation.citizenshipStatus", "raw": "Y", "value": "US_CITIZEN",
                   "evidence": "Tenant admin confirmed on 2026-10-14 that Y means citizen"}]}

Rules: a mapping only fills a value that would otherwise be UNMAPPED, it never overrides a code
table; every entry needs written evidence; the value must be valid for that field's canonical enum
(checked when applied). Each record a mapping touched gets a MAPPED_BY_FILE info diagnostic quoting
the evidence, and the UNMAPPED_CODE warning it resolved is removed.

`review()` lists what is still unmapped across outputs, grouped into distinct decisions, and
`template()` turns that list into a mapping file to fill in.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .canonical.codes import Severity
from .canonical.types import MAPPING_OVERRIDE, Coded, Diagnostic, Raw
from .output import Output


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


@dataclass
class Mappings:
    """Mapping entries for one provider, keyed by (source field, raw value)."""

    provider: str
    entries: dict[tuple[str, str], Mapping] = dataclasses.field(default_factory=dict)
    used: set[tuple[str, str]] = dataclasses.field(default_factory=set)

    @classmethod
    def load(cls, paths: list[Path], provider: str) -> Mappings:
        result = cls(provider)
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("provider") != provider:
                continue
            for i, row in enumerate(data.get("mappings") or []):
                where = f"{path}: mappings[{i}]"
                if row.get("value") is None:
                    continue  # a template row not decided yet
                missing = [k for k in ("field", "raw", "value", "evidence") if not row.get(k) and row.get(k) != 0]
                if missing:
                    raise ValueError(f"{where}: missing {', '.join(missing)}; every mapping needs evidence")
                key = (_field(row["field"]), _key(row["raw"]))
                if key in result.entries and result.entries[key].value != row["value"]:
                    raise ValueError(f"{where}: {key} is already mapped to {result.entries[key].value}")
                result.entries[key] = Mapping(key[0], key[1], str(row["value"]), row["evidence"])
        return result

    def lookup(self, field_: str, raw: Raw) -> str | None:
        key = (_field(field_), _key(raw))
        entry = self.entries.get(key)
        if entry is None:
            return None
        self.used.add(key)
        return entry.value


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
    for records in output.records.values():
        for record in records:
            hits = {(_field(c.source_field), _key(c.raw)) for c in coded_values(record)} & mappings.used
            if not hits:
                continue
            record.diagnostics = [
                d
                for d in record.diagnostics
                if not (d.code == "UNMAPPED_CODE" and (_field(d.field), _key(d.raw)) in hits)
            ]
            for key in sorted(hits):
                entry = mappings.entries[key]
                record.diagnostics.append(
                    Diagnostic(
                        code="MAPPED_BY_FILE",
                        severity=Severity.INFO,
                        field=entry.field,
                        message=f"mapped to {entry.value} by a mapping file: {entry.evidence}",
                        raw=entry.raw,
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
    field: str
    raw: str
    labels: Counter = dataclasses.field(default_factory=Counter)
    records: int = 0
    examples: list[str] = dataclasses.field(default_factory=list)
    kind: Any = str  # the canonical type: an enum, or str for an open code
    suggestions: list = dataclasses.field(default_factory=list)  # filled by normalization.suggest

    @property
    def allowed(self) -> list[str] | None:
        if isinstance(self.kind, type) and issubclass(self.kind, Enum):
            return [m.value for m in self.kind if m.value != "UNMAPPED"]
        return None


def review(outputs: list[tuple[str, Output]]) -> list[Unmapped]:
    """Every distinct still-unmapped (provider, field, raw value), most frequent first."""
    found: dict[tuple[str, str, str], Unmapped] = {}
    for provider, output in outputs:
        for records in output.records.values():
            for record in records:
                seen = set()
                for c in coded_values(record):
                    if value_of(c) != "UNMAPPED" or c.raw is None:
                        continue
                    key = (provider, _field(c.source_field), _key(c.raw))
                    item = found.setdefault(key, Unmapped(*key, kind=kind_of(c)))
                    if c.label:
                        item.labels[c.label] += 1
                    if key not in seen:
                        seen.add(key)
                        item.records += 1
                        if len(item.examples) < 3:
                            item.examples.append(record.id)
    return sorted(found.values(), key=lambda u: (-u.records, u.provider, u.field, u.raw))


def template(items: list[Unmapped]) -> dict[str, dict]:
    """One mapping file per provider, with every unmapped value listed and value/evidence left empty."""
    files: dict[str, dict] = defaultdict(lambda: {"mappings": []})
    for u in items:
        files[u.provider]["provider"] = u.provider
        files[u.provider]["mappings"].append(
            {
                "field": u.field,
                "raw": u.raw,
                "label": u.labels.most_common(1)[0][0] if u.labels else None,
                "records": u.records,
                "allowed": u.allowed,
                "suggestions": [s.__dict__ for s in u.suggestions],
                "value": None,
                "evidence": None,
            }
        )
    return dict(files)


def render(items: list[Unmapped]) -> str:
    lines = [
        "# Unmapped values to review",
        "",
        "Each row is one decision: a provider value no code table or mapping file resolves yet. Fill in",
        "`value` and `evidence` in the matching mapping-file template, then normalize with `--mappings`.",
        "",
        "Suggestions are proposals only: arithmetic on the provider's own totals is evidence of cash vs",
        "non-cash; similar names are a hint for you, not evidence. Nothing is applied until a mapping file",
        "says so.",
        "",
        "| Provider | Field | Raw value | Label | Records | Suggestions | Examples |",
        "|---|---|---|---|---:|---|---|",
    ]
    for u in items:
        label = u.labels.most_common(1)[0][0] if u.labels else ""
        hints = "<br>".join(f"**{s.method}**: {' / '.join(s.values) or 'none'}. {s.reasoning}" for s in u.suggestions)
        lines.append(
            f"| {u.provider} | `{u.field}` | `{u.raw}` | {label} | {u.records} | {hints} | "
            + ", ".join(f"`{e}`" for e in u.examples)
            + " |"
        )
    return "\n".join(lines) + "\n"
