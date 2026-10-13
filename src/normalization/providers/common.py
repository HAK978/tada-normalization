"""Small helpers shared by the provider converters."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from normalization.canonical.codes import NON_CASH_EARNING_KINDS, CheckResult, EarningKind, Severity
from normalization.canonical.records import EarningLine, PayStatement
from normalization.canonical.types import Diagnostic, Money
from normalization.checks import reconcile
from normalization.sanitize import MASK_CHARS
from normalization.source import Notes, decimal

ZERO = Decimal("0")


def money(value: Any, field: str | None = None) -> Money | None:
    amount = decimal(value)
    return None if amount is None else Money(amount=amount, source_field=field)


def derived_sum(amounts: list[Decimal], formula: str) -> Money:
    return Money(amount=sum(amounts, ZERO), derived=True, formula=formula)


def masked(value: str | None) -> bool:
    return bool(value) and any(ch in MASK_CHARS for ch in value)


def paid_gross(wages: Money | None, earnings: list[EarningLine], source: str, notes: Notes) -> Money | None:
    """Gross pay derived from gross wages: wages minus the non-cash earnings counted in them (A-54).

    Not derived when a counted line's kind is unknown, since that line could be either.
    """
    counted = [line for line in earnings if line.in_gross is not False]
    if wages is None or not counted:
        return None
    if any(EarningKind(line.kind.value) is EarningKind.UNMAPPED for line in counted):
        notes.info("GROSS_PAY_NOT_DERIVED", "earnings", "an earning line counted in gross has an unmapped kind")
        return None
    non_cash = [line.amount.amount for line in counted if EarningKind(line.kind.value) in NON_CASH_EARNING_KINDS]
    return Money(
        amount=wages.amount - sum(non_cash, ZERO), derived=True, formula=f"{source} - sum(non-cash earning lines)"
    )


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
