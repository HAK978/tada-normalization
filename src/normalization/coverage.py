"""Field coverage: what the converters do with every field a provider returns (model §9).

The converter runs with tracing on, then every saved 200 response is walked leaf by leaf:

- mapped: the converter read it into a canonical record (possibly another record, such as a
  deposit built from the employee response);
- kept: not mapped, so it is kept, sanitized, in the record's provider_extensions;
- dropped: deliberately not kept, for the reason given;
- reference: a lookup table the converter reads by code rather than field by field;
- unused: the converter doesn't read that response (crawl indexes, refused endpoints).

Only field paths are reported, never values. Array positions are folded into [].
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .bundle import Bundle
from .providers import normalize
from .source import Src, covered, trace

# Fields left out on purpose: (pattern over the folded field path, reason) (model §9).
DROPPED = {
    "prismhr": [
        (r"(^|\.)health(\.|\[|$)", "medical data, outside the model"),
        (r"^(errorCode|errorMessage|extension|checksum)$", "response envelope"),
        (r"^(clientId|employeeId)$|^payRateHistory\.(clientId|employeeId)$", "echo of the request parameters"),
        (r"^(count|startpage|total)$", "paging envelope"),
    ],
    "isolved": [
        (r"(^|\.)links(\.|\[|$)", "API navigation"),
        (r"(^|\.)(logoData|profilePicture)$", "an image"),
        (r"(^|\.)i9Documents(\.|\[|$)", "identity documents are never kept"),
        (r"(^|\.)attachments(\.|\[|$)", "documents are never kept"),
        (r"^(nextPageUrl|previousPageUrl|totalItems|totalPages)$", "paging envelope"),
    ],
    "ukg-ready": [
        (r"(^|\.)_links(\.|$)", "API navigation"),
        (r"(^|\.)photo_href$", "a signed link that works as a credential"),
        (r"^_routing_type$", "a default for new deposits; each deposit carries its own routing type"),
    ],
}
# Responses the converters read as code tables, by key, rather than field by field.
REFERENCE = {
    "prismhr": {"clientMaster/v1/getClientCodes"},
    "isolved": {
        "api/lookup/Frequencies",
        "api/lookup/genders",
        "api/lookup/maritalStatuses",
        "api/lookup/citizenships",
        "api/clients/{client}/payItems",
    },
    "ukg-ready": {
        "rest/v2/companies/{company}/lookup/eins",
        "rest/v2/companies/{company}/lookup/pay-types",
        "rest/v2/companies/{company}/lookup/employee-types",
        "rest/v2/companies/{company}/lookup/jobs",
    },
}
STATUSES = ("mapped", "kept", "dropped", "reference", "unused")


@dataclass
class Coverage:
    provider: str
    source: str
    captures: int
    # (endpoint, field path) -> status counts across every occurrence
    fields: dict[tuple[str, str], Counter] = field(default_factory=dict)
    reasons: dict[tuple[str, str], str] = field(default_factory=dict)
    # Source paths a converter returned as leftovers and then read: mapped and kept twice. Should be empty.
    read_after_kept: list[str] = field(default_factory=list)

    def label(self, key: tuple[str, str]) -> str:
        counts = self.fields[key]
        if len(counts) == 1:
            status = next(iter(counts))
            return f"dropped: {self.reasons[key]}" if status == "dropped" else status
        return " / ".join(f"{status} ({counts[status]})" for status in STATUSES if counts[status])


def measure(bundle: Bundle, source: str) -> Coverage:
    with trace() as traced:
        normalize(bundle)
    # Every object inside a tracked record, so a response nested into a merged record is still found.
    by_data: dict[int, list[tuple[Src, str]]] = {}
    for root in traced.roots:
        for node, rel in _objects(root.data, ""):
            by_data.setdefault(id(node), []).append((root, rel))
    result = Coverage(bundle.provider, source, sum(1 for c in bundle.captures if c.status == 200))
    result.read_after_kept = sorted(traced.read_after_kept())
    dropped = DROPPED.get(bundle.provider, [])
    for capture in bundle.captures:
        if capture.status != 200:
            continue
        reference = capture.endpoint in REFERENCE.get(bundle.provider, set())
        for path, status in _walk(capture.body, "", by_data, []):
            folded = re.sub(r"\[\d+\]", "[]", path)
            reason = next((why for pattern, why in dropped if re.search(pattern, folded)), None)
            if reason:
                status = "dropped"
            elif reference and status == "unused":
                status = "reference"
            key = (capture.endpoint, folded)
            result.fields.setdefault(key, Counter())[status] += 1
            if reason:
                result.reasons[key] = reason
    return result


def _objects(node: Any, rel: str):
    """Every dict under node, with its path relative to node."""
    if isinstance(node, dict):
        yield node, rel
        for key, value in node.items():
            yield from _objects(value, f"{rel}.{key}" if rel else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _objects(value, f"{rel}[{i}]")


def _walk(node: Any, path: str, by_data: dict[int, list[tuple[Src, str]]], active: list[tuple[Src, str]]):
    """Yield (path, mapped|kept|unused) for every leaf; the innermost tracked object decides."""
    if isinstance(node, dict) and id(node) in by_data:
        active = list(by_data[id(node)])
    if isinstance(node, dict):
        for key, value in node.items():
            inner = [(root, f"{rel}.{key}" if rel else key) for root, rel in active]
            yield from _walk(value, f"{path}.{key}" if path else key, by_data, inner)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, f"{path}[{i}]", by_data, [(r, f"{rel}[{i}]") for r, rel in active])
    elif node not in (None, ""):
        if not active:
            yield path, "unused"
        else:
            yield path, "mapped" if any(covered(root, rel) for root, rel in active) else "kept"


def render(results: list[Coverage]) -> str:
    lines = [
        "# Field coverage",
        "",
        "Generated by `python -m normalization coverage`. For every field a provider returned, this lists what",
        "the converter does with it. It shows field paths only, never values; array positions are folded into `[]`.",
        "",
        "- **mapped**: read into a canonical record. Some are read into another record, such as a deposit built",
        "  from the employee response.",
        "- **kept**: not mapped, so it is kept, sanitized, in the record's `provider_extensions`.",
        "- **dropped**: deliberately not kept, for the reason given.",
        "- **reference**: a lookup table the converter reads by code, not field by field.",
        "- **unused**: a response the converter doesn't read, such as a crawl index.",
        "",
        "A field that is mapped in some records and kept in others shows both, with counts.",
        "",
        "Sources:",
        "",
    ]
    lines += [f"- {r.provider}: {r.source} ({r.captures} responses)" for r in results]
    lines += [
        "",
        "## Summary",
        "",
        "| Provider | Endpoint | Fields | Mapped | Kept | Dropped | Reference | Unused |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        for endpoint in sorted({e for e, _ in r.fields}):
            keys = [k for k in r.fields if k[0] == endpoint]
            totals = Counter(_main_status(r.fields[k]) for k in keys)
            counts = " | ".join(str(totals[s]) for s in STATUSES)
            lines.append(f"| {r.provider} | `{endpoint}` | {len(keys)} | {counts} |")
    for r in results:
        lines += ["", f"## {r.provider}", ""]
        for endpoint in sorted({e for e, _ in r.fields}):
            lines += [f"### `{endpoint}`", "", "| Field | Disposition |", "|---|---|"]
            for key in sorted(k for k in r.fields if k[0] == endpoint):
                lines.append(f"| `{key[1]}` | {r.label(key)} |")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _main_status(counts: Counter) -> str:
    return max(STATUSES, key=lambda s: (counts[s], -STATUSES.index(s)))
