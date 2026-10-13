"""A raw bundle: saved provider responses, from a live fetch or the synthetic generator.

Layout (same for both sources):
    <bundle>/session.json            provider, tenant_id, companies (no credentials)
    <bundle>/captures/NNNN_*.json    {"endpoint", "path", "params", "status", "body", ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

    @classmethod
    def load(cls, root: Path) -> Bundle:
        session = exactjson.loads((root / "session.json").read_text(encoding="utf-8"))
        captures = []
        for file in sorted((root / "captures").glob("*.json")):
            data = exactjson.loads(file.read_text(encoding="utf-8"))
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
        return cls(session["provider"], str(session.get("tenant_id", "")), session.get("companies") or [], captures)

    def find(self, endpoint: str, **params: Any) -> Iterator[Capture]:
        """Captures of one endpoint whose params include all of the given ones."""
        for capture in self.captures:
            if capture.endpoint == endpoint and all(str(capture.params.get(k)) == str(v) for k, v in params.items()):
                yield capture

    def ok(self, endpoint: str, **params: Any) -> Iterator[Capture]:
        for capture in self.find(endpoint, **params):
            if capture.status == 200 and isinstance(capture.body, (dict, list)):
                yield capture
