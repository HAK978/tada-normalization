"""Sensitive values keep at most their last 4 digits, everywhere in the output (A-23).

Known sensitive fields are listed by source path. A second sweep catches SSN-shaped strings
anywhere else. A value that arrived masked yields no last 4: digits are never invented.
"""

from __future__ import annotations

import re
from typing import Any

MASK_CHARS = set("*Xx#")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Matched against the end of a source path, e.g. "employee[0].compensation.ssn".
SENSITIVE_FIELDS = re.compile(
    r"(?:^|[.\]])(?:ssn|cobraSSN|employeeSSN|social_security|social_insurance|national_insurance|bsn"
    r"|accountNum|accountNumber|account_number|bank_account_number|account"
    r"|national_id_numbers\[\d+\]\.value)$"
)


def last4(value: Any) -> tuple[str | None, bool | None]:
    """(last 4 digits or None, whether the provider had masked it)."""
    if value in (None, ""):
        return None, None
    raw = str(value).strip()
    masked = any(ch in MASK_CHARS for ch in raw)
    tail = raw[-4:]
    if len(tail) == 4 and tail.isdigit():
        return tail, masked
    return None, masked


def redacted(value: Any) -> str:
    digits, masked = last4(value)
    return f"***{digits}" if digits else "***"


def sweep(value: Any, path: str = "") -> Any:
    """Sanitize a nested structure: sensitive fields by name, SSN-shaped strings anywhere."""
    if isinstance(value, dict):
        return {k: sweep(v, f"{path}.{k}" if path else k) for k, v in value.items()}
    if isinstance(value, list):
        return [sweep(v, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, str):
        if SENSITIVE_FIELDS.search(path):
            return redacted(value)
        return _SSN.sub(lambda m: "***-**-" + m.group(0)[-4:], value)
    return value


def sanitize_extensions(leftovers: dict[str, Any]) -> dict[str, Any]:
    """provider_extensions are flat {source path: value}; each path is checked on its own."""
    return {
        path: (redacted(v) if isinstance(v, str) and SENSITIVE_FIELDS.search(path) else sweep(v, path))
        for path, v in leftovers.items()
    }
