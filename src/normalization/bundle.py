"""A raw bundle: saved provider responses, from a live fetch or the synthetic generator.

Layout (same for both sources):
    <bundle>/session.json            provider, tenant_id, companies (no credentials)
    <bundle>/captures/NNNN_*.json    {"endpoint", "path", "params", "status", "body", ...}
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from . import exactjson


@dataclass
class Capture:
    endpoint: str
    path: str
    params: dict[str, Any]
    status: int
    body: Any
    file: str


@dataclass
class Bundle:
    provider: str
    tenant_id: str
    companies: list[dict[str, Any]]
    captures: list[Capture] = field(default_factory=list)
    # The date time-dependent values are evaluated at (A-33): a fixture's fixed date, else the fetch date.
    as_of: date | None = None
    # Which snapshot this is (A-71): the folder name, when it was saved, and a SHA-256 of every file.
    name: str | None = None
    saved_at: str | None = None
    sha256: str | None = None

    @classmethod
    def load(cls, root: Path) -> Bundle:
        text = (root / "session.json").read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8"))
        session = exactjson.loads(text)
        captures = []
        for file in sorted((root / "captures").glob("*.json")):
            text = file.read_text(encoding="utf-8")
            digest.update(file.name.encode("utf-8") + b"\0" + text.encode("utf-8"))
            data = exactjson.loads(text)
            captures.append(
                Capture(
                    data["endpoint"],
                    data.get("path", ""),
                    data.get("params") or {},
                    int(data.get("status", 0)),
                    data.get("body"),
                    file.name,
                )
            )
        as_of = session.get("as_of") or str(session.get("saved_at") or "")[:10]
        return cls(
            session["provider"],
            str(session.get("tenant_id", "")),
            session.get("companies") or [],
            captures,
            date.fromisoformat(as_of) if as_of else None,
            root.name,
            str(session["saved_at"]) if session.get("saved_at") else None,
            digest.hexdigest(),
        )

    def find(self, endpoint: str, **params: Any) -> Iterator[Capture]:
        """Captures of one endpoint whose params include all of the given ones."""
        for capture in self.captures:
            if capture.endpoint == endpoint and all(str(capture.params.get(k)) == str(v) for k, v in params.items()):
                yield capture

    def ok(self, endpoint: str, **params: Any) -> Iterator[Capture]:
        for capture in self.find(endpoint, **params):
            if capture.status == 200 and isinstance(capture.body, (dict, list)):
                yield capture
