"""Requests that returned no data: nothing to return, or unavailable (A-70).

An empty list in the output must mean the provider said there was nothing. A request that was refused,
failed, or reached an endpoint the tenant doesn't have leaves its data unknown instead. Each such
request is reported as SOURCE_UNAVAILABLE on the records it would have fed: an employee whose
deductions couldn't be fetched has unknown deductions, not none.

A failed request counts as an empty answer only where the provider documents that response as "nothing
found" (`EMPTY_RESPONSES` in its codes module) or says so in its message (`EMPTY_MESSAGES`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from importlib import import_module
from typing import Any

from .bundle import Bundle, Capture
from .canonical.codes import Severity
from .canonical.types import Diagnostic, Record
from .output import Output

OK, EMPTY, UNAVAILABLE = "ok", "empty", "unavailable"


def assess(bundle: Bundle, output: Output, package: str) -> dict[str, Any]:
    """Report each unavailable request on the records it would have fed; return the request counts."""
    codes = import_module(f"normalization.providers.{package}.codes")
    convert = import_module(f"normalization.providers.{package}.convert")
    in_body = getattr(convert, "error_in_body", None)
    outcomes: Counter[str] = Counter()
    failed: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    reports: dict[tuple[str, str, str], tuple[Record, list[str]]] = {}
    for capture in bundle.captures:
        error = in_body(capture) if in_body else None
        outcome = _outcome(capture, error, codes)
        outcomes[outcome] += 1
        if outcome != UNAVAILABLE:
            continue
        status = f"errorCode {error}" if error else f"HTTP {capture.status}"
        failed[(capture.endpoint, status)]["requests"] += 1
        owners = _owners(output, convert.request_scope(capture))
        if not owners:
            failed[(capture.endpoint, status)]["unattributed"] += 1
        for record in owners:
            reports.setdefault((record.id, capture.endpoint, status), (record, []))[1].append(_message(capture.body))
    for (_, endpoint, status), (record, messages) in sorted(reports.items(), key=lambda kv: kv[0]):
        said = next((m for m in messages if m), "")
        count = f" ({len(messages)} requests)" if len(messages) > 1 else ""
        record.diagnostics.append(
            Diagnostic(
                code="SOURCE_UNAVAILABLE",
                severity=Severity.WARNING,
                field=endpoint,
                message=f"{status}{': ' + said if said else ''}{count}; what this request returns is unknown "
                "for this record, not empty (A-70)",
                raw=error_code(status),
            )
        )
    return {
        "total": len(bundle.captures),
        **{outcome: outcomes[outcome] for outcome in (OK, EMPTY, UNAVAILABLE)},
        "unavailable_by_endpoint": [
            {"endpoint": e, "status": s, "requests": c["requests"], "unattributed": c["unattributed"]}
            for (e, s), c in sorted(failed.items())
        ],
    }


def error_code(status: str) -> str:
    """The bare code of a failure: 404 for "HTTP 404", 403 for "errorCode 403"."""
    return status.split()[-1]


def _outcome(capture: Capture, error: str | None, codes: Any) -> str:
    if capture.status == 200 and not error:
        return OK
    if capture.status in getattr(codes, "EMPTY_RESPONSES", {}).get(capture.endpoint, {}):
        return EMPTY
    prefixes = getattr(codes, "EMPTY_MESSAGES", {}).get(capture.endpoint, ())
    if prefixes and _message(capture.body).startswith(prefixes):
        return EMPTY
    return UNAVAILABLE


def _owners(output: Output, scopes: list[tuple[str, dict[str, str]]]) -> list[Record]:
    """The records whose source IDs match a request's: employees first, else companies."""
    for kind in ("employees", "companies"):
        wanted = [ids for k, ids in scopes if k == kind]
        found = [
            r
            for r in output.records[kind]
            if any(all(r.source.ids.get(k) == v for k, v in ids.items()) for ids in wanted)
        ]
        if found:
            return found
    return []


def _message(body: Any) -> str:
    """What the provider said about a failure, from the places the three providers put it."""
    if not isinstance(body, dict):
        return ""
    errors = body.get("errors")
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    said = next((v for v in (body.get("errorMessage"), body.get("message"), first.get("message")) if v), "")
    return " ".join(str(said).split())[:200]
