"""Paycheck reconciliation. Results are reported on the record; amounts are never adjusted.

Gross wages are every earning counted in gross, non-cash ones included; gross pay is the part
actually paid, gross wages minus non-cash earnings (A-54). A derived total is never checked
against the lines it was derived from.
"""

from __future__ import annotations

from decimal import Decimal

from .canonical.codes import NON_CASH_EARNING_KINDS, CheckResult, EarningKind
from .canonical.records import PayStatement
from .canonical.types import CheckOutcome

TOLERANCE = Decimal("0.01")


def _sum(amounts) -> Decimal:
    return sum((a for a in amounts if a is not None), Decimal("0"))


def _outcome(rule: str, expected: Decimal, actual: Decimal, detail: str) -> CheckOutcome:
    ok = abs(expected - actual) <= TOLERANCE
    return CheckOutcome(rule=rule, result=CheckResult.PASS if ok else CheckResult.FAIL, detail=detail)


def reconcile(statement: PayStatement) -> list[CheckOutcome]:
    totals, out = statement.totals, []
    wages, gross, net = totals.gross_wages, totals.gross_pay, totals.net_pay
    counted = [line for line in statement.earnings if line.in_gross is not False]
    non_cash = _sum(line.amount.amount for line in counted if EarningKind(line.kind.value) in NON_CASH_EARNING_KINDS)
    has_lines = bool(statement.earnings or statement.taxes or statement.deductions)

    if wages is not None and counted and not wages.derived:
        earnings = _sum(line.amount.amount for line in counted)
        out.append(
            _outcome(
                "gross wages = sum of earning lines counted in gross",
                wages.amount,
                earnings,
                f"{wages.amount} vs {earnings}",
            )
        )

    # An unknown kind could be cash or not, so this comparison has nothing to stand on (as in paid_gross).
    unknown = any(EarningKind(line.kind.value) is EarningKind.UNMAPPED for line in counted)
    if wages is not None and gross is not None and counted and not unknown and not (wages.derived or gross.derived):
        expected = wages.amount - non_cash
        out.append(
            _outcome(
                "gross wages - non-cash earnings = gross pay",
                expected,
                gross.amount,
                f"{wages.amount} - {non_cash} = {expected}; gross pay {gross.amount}",
            )
        )

    if gross is not None and net is not None and has_lines:
        ee_taxes = _sum(line.amount.amount for line in statement.taxes if line.paid_by == "EMPLOYEE")
        deductions = _sum(line.employee_amount.amount for line in statement.deductions if line.employee_amount)
        expected = gross.amount - ee_taxes - deductions
        out.append(
            _outcome(
                "gross pay - employee taxes - deductions = net",
                expected,
                net.amount,
                f"{gross.amount} - {ee_taxes} - {deductions} = {expected}; net {net.amount}",
            )
        )

    if net is not None and statement.payments and not net.derived:
        paid = _sum(p.amount.amount for p in statement.payments)
        out.append(_outcome("payments = net", paid, net.amount, f"{paid} vs {net.amount}"))
    return out
