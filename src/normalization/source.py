"""Reading provider data: tracked field access, value parsing and per-record diagnostics.

Converters read every source field through Src. Whatever a converter never read is
returned by leftovers() and kept in provider_extensions, so nothing is lost silently.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterator, Literal, Mapping, TypeVar, overload

from .canonical.codes import Severity
from .canonical.types import Coded, Diagnostic, Raw, coded_type

_MISSING = object()
_EMPTY: tuple[Any, ...] = (None, "", [], {})


@dataclass
class Trace:
    """What converters read while trace() is active, for the field coverage report."""

    roots: list[Src] = field(default_factory=list)  # every Src with its own read record
    # (read record, paths returned as leftovers): a path read after that is both mapped and kept
    given: list[tuple[set[str], set[str]]] = field(default_factory=list)

    def read_after_kept(self) -> set[str]:
        return {path for used, paths in self.given for path in paths if _covered(path, used)}


_TRACE: Trace | None = None


class Src:
    """One source object plus the shared record of which paths a converter has read."""

    def __init__(self, data: Any, path: str = "", used: set[str] | None = None):
        self.data = data if isinstance(data, dict) else {}
        self.path = path
        if used is None and _TRACE is not None:
            _TRACE.roots.append(self)
        self.used = used if used is not None else set()

    def _full(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def _walk(self, key: str) -> Any:
        node: Any = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return _MISSING
            node = node[part]
        return node

    def get(self, key: str, default: Any = None) -> Any:
        node = self._walk(key)
        if node is _MISSING:
            return default
        self.used.add(self._full(key))
        return node

    def first(self, *keys: str) -> Any:
        """The first key present with a non-empty value; every key tried is marked as read."""
        found = None
        for key in keys:
            value = self.get(key)
            if found is None and value not in _EMPTY:
                found = value
        return found

    def mark(self, *keys: str) -> None:
        """Mark subtrees as handled elsewhere (for example by a separate deposit record)."""
        for key in keys:
            if self._walk(key) is not _MISSING:
                self.used.add(self._full(key))

    def child(self, key: str) -> Src | None:
        node = self._walk(key)
        return Src(node, self._full(key), self.used) if isinstance(node, dict) else None

    def children(self, key: str) -> list[Src]:
        node = self._walk(key)
        if not isinstance(node, list):
            return []
        base = self._full(key)
        return [Src(item, f"{base}[{i}]", self.used) for i, item in enumerate(node) if isinstance(item, dict)]

    def leftovers(self) -> dict[str, Any]:
        """Every non-empty leaf under this object that no converter read."""
        left = {path: value for path, value in _leaves(self.data, self.path) if not _covered(path, self.used)}
        if _TRACE is not None:
            _TRACE.given.append((self.used, set(left)))
        return left


def covered(src: Src, relative: str) -> bool:
    """Whether the converter read this path (relative to the Src's own data) or a parent of it."""
    return _covered(src._full(relative) if relative else src.path, src.used)


@contextmanager
def trace() -> Iterator[Trace]:
    """Record what converters read inside the block, for the field coverage report."""
    global _TRACE
    previous, _TRACE = _TRACE, Trace()
    try:
        yield _TRACE
    finally:
        _TRACE = previous


def _leaves(node: Any, path: str) -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _leaves(value, f"{path}[{i}]")
    elif node not in (None, ""):
        yield path, node


def _covered(path: str, used: set[str]) -> bool:
    if path in used:
        return True
    return any(path.startswith(prefix) and path[len(prefix)] in ".[" for prefix in used if len(path) > len(prefix))


# ---------------------------------------------------------------- values


def text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def decimal(value: Any) -> Decimal | None:
    if value in _EMPTY or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None
    # "NaN" and "Infinity" parse as decimals but are not amounts; like unparseable text, they are no value.
    return parsed if parsed.is_finite() else None


def flag(value: Any) -> bool | None:
    """Booleans arrive as true/false, T/F, Y/N, Yes/No or empty."""
    if isinstance(value, bool):
        return value
    lookup = {"t": True, "true": True, "y": True, "yes": True, "f": False, "false": False, "n": False, "no": False}
    return lookup.get(str(value).strip().lower()) if value not in _EMPTY else None


def known_flag(value: Any, field: str, notes: Notes, unknown: str) -> bool | None:
    """A yes/no that decides what a line means. Missing, or not a yes/no, stays unknown with a FLAG_MISSING
    warning naming what is therefore unknown; it is never read as "no" (A-73)."""
    result = flag(value)
    if result is None:
        notes.warn("FLAG_MISSING", field, f"missing or not a yes/no, so {unknown} is unknown", raw_scalar(value))
    return result


_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")


def raw_scalar(value: Any) -> Raw:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


class Notes:
    """Diagnostics for one record."""

    def __init__(self) -> None:
        self.items: list[Diagnostic] = []

    def add(self, code: str, severity: Severity, field: str | None, message: str, raw: Any = None) -> None:
        self.items.append(Diagnostic(code=code, severity=severity, field=field, message=message, raw=raw_scalar(raw)))

    def info(self, code: str, field: str | None, message: str, raw: Any = None) -> None:
        self.add(code, Severity.INFO, field, message, raw)

    def warn(self, code: str, field: str | None, message: str, raw: Any = None) -> None:
        self.add(code, Severity.WARNING, field, message, raw)


def iso_date(value: Any, field: str, notes: Notes) -> date | None:
    """YYYY-MM-DD, or a date-time at midnight. Anything else is reported, never guessed."""
    raw = text(value)
    if raw is None:
        return None
    match = _DATE.match(raw)
    if not match:
        notes.warn("UNPARSEABLE_DATE", field, "not an ISO date; kept only in diagnostics", raw)
        return None
    year, month, day, hh, mm, ss = match.group(1, 2, 3, 4, 5, 6)
    try:
        parsed = date(int(year), int(month), int(day))
    except ValueError:
        notes.warn("INVALID_DATE", field, "date components are out of range", raw)
        return None
    if hh is not None and (hh, mm, ss) != ("00", "00", "00"):
        notes.info("TIME_DROPPED", field, "date-time had a time of day; only the date is kept", raw)
    return parsed


E = TypeVar("E", bound=Enum)


@overload
def coded(
    table: Mapping[str, E],
    value: Any,
    field: str,
    notes: Notes,
    unmapped: E,
    label: str | None = ...,
    *,
    empty_is_none: Literal[False],
) -> Coded[E]: ...


@overload
def coded(
    table: Mapping[str, E],
    value: Any,
    field: str,
    notes: Notes,
    unmapped: E,
    label: str | None = ...,
    *,
    empty_is_none: bool = ...,
) -> Coded[E] | None: ...


def coded(
    table: Mapping[str, E],
    value: Any,
    field: str,
    notes: Notes,
    unmapped: E,
    label: str | None = None,
    *,
    empty_is_none: bool = True,
) -> Coded[E] | None:
    """Translate a raw code through a table keyed by this exact source field; unknown codes stay UNMAPPED."""
    raw = text(value) if not isinstance(value, bool) else value
    if raw is None and empty_is_none:
        return None
    key = "" if raw is None else raw
    if isinstance(key, str) and key in table:
        return coded_type(type(unmapped))(value=table[key], raw=raw_scalar(value), label=label, source_field=field)
    notes.warn("UNMAPPED_CODE", field, "no documented or evidenced meaning for this code", value)
    return coded_type(type(unmapped))(value=unmapped, raw=raw_scalar(value), label=label, source_field=field)


def unmapped_label(value: Any, label: str | None, field: str) -> Coded[str] | None:
    """A customer-configured code: kept with its label, deliberately not translated (A-35)."""
    raw = text(value)
    if raw is None:
        return None
    return Coded[str](value="UNMAPPED", raw=raw, label=label, source_field=field)
