"""The result of normalizing one bundle: canonical records grouped by type."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from . import exactjson
from .canonical.records import RECORD_TYPES, PayStatement, dump
from .canonical.types import Record


@dataclass
class Output:
    records: dict[str, list[Record]] = field(default_factory=lambda: {kind: [] for kind in RECORD_TYPES})

    def add(self, kind: str, record: Record) -> None:
        if not isinstance(record, RECORD_TYPES[kind]):
            raise TypeError(f"{kind} expects {RECORD_TYPES[kind].__name__}, got {type(record).__name__}")
        self.records[kind].append(record)

    def ids(self, kind: str) -> set[str]:
        return {record.id for record in self.records[kind]}

    def summary(self) -> dict:
        severities = Counter(
            d.severity.value for records in self.records.values() for r in records for d in r.diagnostics
        )
        statements = cast("list[PayStatement]", self.records["pay_statements"])
        checks = Counter(c.result.value for r in statements for c in r.checks)
        return {
            "counts": {kind: len(records) for kind, records in self.records.items()},
            "diagnostics": dict(severities),
            "checks": dict(checks),
        }

    def to_json(self) -> str:
        """Deterministic JSON of everything: records sorted by id within each type, plus the summary."""
        records = {kind: [dump(r) for r in sorted(items, key=lambda r: r.id)] for kind, items in self.records.items()}
        return exactjson.dumps({"summary": self.summary(), "records": records}, indent=1) + "\n"
