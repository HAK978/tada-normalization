"""Paycheck reconciliation. Results are reported on the record; amounts are never adjusted."""

from __future__ import annotations

from decimal import Decimal

from .canonical.codes import NON_CASH_EARNING_KINDS, CheckResult, EarningKind
from .canonical.records import PayStatement
from .canonical.types import CheckOutcome

TOLERANCE = Decimal("0.01")


def _sum(amounts) -> Decimal:
    return sum((a for a in amounts if a is not None), Decimal("0"))


def reconcile(statement: PayStatement) -> list[CheckOutcome]:
    totals, out = statement.totals, []
    gross = totals.gross_pay.amount if totals.gross_pay else None
    net = totals.net_pay.amount if totals.net_pay else None
    counted = [line for line in statement.earnings if line.in_gross is not False]
    has_lines = bool(statement.earnings or statement.taxes or statement.deductions)

    # The provider's own gross-of-lines figure: gross wages when it reports one (isolved), else gross pay.
    lines_total = totals.gross_wages or totals.gross_pay
    if lines_total is not None and counted and not lines_total.derived:
        earnings = _sum(line.amount.amount for line in counted)
        ok = abs(lines_total.amount - earnings) <= TOLERANCE
        out.append(
            CheckOutcome(
                rule=f"{'gross wages' if totals.gross_wages else 'gross'} = sum of earning lines counted in gross",
                result=CheckResult.PASS if ok else CheckResult.FAIL,
                detail=f"{lines_total.amount} vs {earnings}",
            )
        )

    if gross is not None and net is not None and has_lines:
        non_cash = _sum(
            line.amount.amount for line in counted if EarningKind(line.kind.value) in NON_CASH_EARNING_KINDS
        )
        ee_taxes = _sum(line.amount.amount for line in statement.taxes if line.paid_by == "EMPLOYEE")
        deductions = _sum(line.employee_amount.amount for line in statement.deductions if line.employee_amount)
        expected = gross - non_cash - ee_taxes - deductions
        ok = abs(expected - net) <= TOLERANCE
        out.append(
            CheckOutcome(
                rule="gross - non-cash earnings - employee taxes - deductions = net",
                result=CheckResult.PASS if ok else CheckResult.FAIL,
                detail=f"{gross} - {non_cash} - {ee_taxes} - {deductions} = {expected}; net {net}",
            )
        )

    if net is not None and statement.payments and not totals.net_pay.derived:
        paid = _sum(p.amount.amount for p in statement.payments)
        ok = abs(paid - net) <= TOLERANCE
        out.append(
            CheckOutcome(
                rule="payments = net",
                result=CheckResult.PASS if ok else CheckResult.FAIL,
                detail=f"{paid} vs {net}",
            )
        )
    return out
