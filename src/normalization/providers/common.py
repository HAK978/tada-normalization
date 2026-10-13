"""Small helpers shared by the provider converters."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from normalization.canonical.codes import CheckResult, Severity
from normalization.canonical.records import PayStatement
from normalization.canonical.types import Diagnostic, Money
from normalization.checks import reconcile
from normalization.sanitize import MASK_CHARS
from normalization.source import decimal

ZERO = Decimal("0")


def money(value: Any, field: str | None = None) -> Money | None:
    amount = decimal(value)
    return None if amount is None else Money(amount=amount, source_field=field)


def derived_sum(amounts: list[Decimal], formula: str) -> Money:
    return Money(amount=sum(amounts, ZERO), derived=True, formula=formula)


def masked(value: str | None) -> bool:
    return bool(value) and any(ch in MASK_CHARS for ch in value)


def attach_checks(statement: PayStatement) -> None:
    """Run the reconciliation checks and report every failure as a diagnostic."""
    statement.checks = reconcile(statement)
    statement.diagnostics += [
        Diagnostic(
            code="RECONCILIATION_MISMATCH",
            severity=Severity.WARNING,
            field="totals",
            message=f"{check.rule}: {check.detail}",
        )
        for check in statement.checks
        if check.result is CheckResult.FAIL
    ]
