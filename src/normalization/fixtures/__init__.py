"""Seeded synthetic fixtures: provider-shaped raw bundles generated from known facts.

Fixtures use the same bundle layout as live discovery (see normalization.bundle), so the
converters can't tell them apart. Real provider records are never used (A-06).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from .. import exactjson

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class FixtureBundle:
    provider: str
    tenant_id: str
    companies: list[dict[str, Any]]
    captures: list[dict[str, Any]] = field(default_factory=list)
    as_of: str | None = None  # fixed evaluation date for time-dependent values (A-33)

    def add(self, endpoint: str, path: str, params: dict, body: Any, status: int = 200) -> None:
        self.captures.append({"endpoint": endpoint, "path": path, "params": params, "status": status, "body": body})

    def write(self, root: Path) -> list[Path]:
        """Write session.json and one capture file per response; returns every file written."""
        captures = root / "captures"
        captures.mkdir(parents=True, exist_ok=True)
        for old in captures.glob("*.json"):
            old.unlink()
        session = {
            "provider": self.provider,
            "tenant_id": self.tenant_id,
            "companies": self.companies,
            "synthetic": True,
        }
        if self.as_of:
            session["as_of"] = self.as_of
        written = [root / "session.json"]
        written[0].write_text(exactjson.dumps(session, indent=2) + "\n", encoding="utf-8")
        for seq, capture in enumerate(self.captures, start=1):
            name = f"{seq:04d}_{re.sub(r'[^A-Za-z0-9]+', '_', capture['endpoint']).strip('_')[:80]}.json"
            path = captures / name
            path.write_text(exactjson.dumps({"seq": seq, **capture}, indent=2) + "\n", encoding="utf-8")
            written.append(path)
        return written
