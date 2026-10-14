"""Small helpers shared by the provider converters."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from normalization.canonical.codes import (
    CATEGORIZED_EARNING_KINDS,
    NON_CASH_EARNING_KINDS,
    US_STATE_BY_NAME,
    US_STATES,
    CheckResult,
    EarningCategory,
    EarningKind,
    Severity,
    TaxType,
)
from normalization.canonical.records import EarningLine, PayStatement
from normalization.canonical.types import Coded, Diagnostic, Money
from normalization.checks import reconcile
from normalization.sanitize import MASK_CHARS
from normalization.source import Notes, decimal

ZERO = Decimal("0")


def money(value: Any, field: str | None = None) -> Money | None:
    amount = decimal(value)
    return None if amount is None else Money(amount=amount, source_field=field)


def line_amount(value: Any, field: str | None, notes: Notes) -> Money:
    """A paycheck line's amount. A line sent without one keeps a 0 placeholder, so its code and other
    values stay, and an AMOUNT_MISSING warning says the 0 was not sent: missing is never zero (A-72)."""
    amount = decimal(value)
    if amount is None:
        notes.warn("AMOUNT_MISSING", field, "the line has no amount; the 0 here stands in for it and was not sent")
        return Money(amount=ZERO, source_field=field)
    return Money(amount=amount, source_field=field)


def derived_sum(amounts: list[Decimal], formula: str) -> Money:
    return Money(amount=sum(amounts, ZERO), derived=True, formula=formula)


def masked(value: str | None) -> bool:
    if not value:
        return False
    return any(ch in MASK_CHARS for ch in value)


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


def categorized(kind: Coded[EarningKind]) -> bool:
    """Whether an earning line of this kind gets a category: earnings, or a line of unknown kind (A-67)."""
    return EarningKind(kind.value) in CATEGORIZED_EARNING_KINDS


def customer_category(code: str | None, label: str | None, field: str) -> Coded[EarningCategory] | None:
    """An earning code the provider doesn't classify: UNMAPPED with the code as raw, for the review queue.

    No warning per line: like other customer-configured codes (A-35), it is one decision per code for a
    person to make in a mapping file (A-65), not a data problem on each paycheck.
    """
    if code is None:
        return None
    return Coded[EarningCategory](value=EarningCategory.UNMAPPED, raw=code, label=label, source_field=field)


def tax_type(
    found: tuple[TaxType, str | None] | None, raw: str | None, field: str, notes: Notes, label: str | None = None
) -> tuple[Coded[TaxType] | None, str | None]:
    """The tax type and state a provider rule found for a tax code; a code no rule covers stays UNMAPPED (A-68)."""
    if raw is None:
        return None, None
    if found is None:
        notes.warn("UNMAPPED_CODE", field, "no documented or evidenced tax type for this code", raw)
        return Coded[TaxType](value=TaxType.UNMAPPED, raw=raw, label=label, source_field=field), None
    value, state = found
    return Coded[TaxType](value=value, raw=raw, label=label, source_field=field), state


def us_state(name: str | None) -> str | None:
    """The USPS code of a state given by its code or its full name, in any case; None for anything else."""
    key = " ".join((name or "").upper().split())
    return key if key in US_STATES else US_STATE_BY_NAME.get(key)


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
