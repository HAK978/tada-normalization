"""Reconciliation rules and derived gross pay, on hand-built statements (A-54)."""

from decimal import Decimal

from normalization.canonical import codes as C
from normalization.canonical.records import EarningLine, PaymentLine, PayStatement, PayStatementTotals, TaxLine
from normalization.canonical.types import Coded, Money, Source
from normalization.checks import reconcile
from normalization.providers.common import paid_gross
from normalization.source import Notes


def line(kind: C.EarningKind, amount: str, in_gross: bool = True) -> EarningLine:
    return EarningLine(
        kind=Coded[C.EarningKind](value=kind, source_field="test"),
        in_gross=in_gross,
        amount=Money(amount=Decimal(amount)),
        source_field="test",
    )


def statement(totals: PayStatementTotals, earnings: list[EarningLine], tax: str = "0", paid: str | None = None):
    return PayStatement(
        id="test:1",
        source=Source(provider="test", tenant_id="t"),
        company_id="c",
        employee_id="e",
        type=Coded[C.PayStatementType](value=C.PayStatementType.REGULAR, source_field="test"),
        totals=totals,
        earnings=earnings,
        taxes=[TaxLine(paid_by=C.TaxPaidBy.EMPLOYEE, amount=Money(amount=Decimal(tax)), source_field="test")],
        payments=[
            PaymentLine(
                kind=Coded[C.PaymentKind](value=C.PaymentKind.CHECK, source_field="test"),
                amount=Money(amount=Decimal(paid)),
                source_field="test",
            )
        ]
        if paid
        else [],
    )


def results(s: PayStatement) -> dict[str, str]:
    return {c.rule: c.result.value for c in reconcile(s)}


EARN, FRINGE, MEMO, UNKNOWN = (
    C.EarningKind.EARNINGS,
    C.EarningKind.NON_CASH_FRINGE,
    C.EarningKind.MEMO,
    C.EarningKind.UNMAPPED,
)


def test_gross_pay_is_derived_as_wages_minus_non_cash_earnings():
    notes = Notes()
    pay = paid_gross(Money(amount=Decimal("103.10")), [line(EARN, "100"), line(FRINGE, "3.10")], "totalEarnings", notes)
    assert (pay.amount, pay.derived, pay.formula) == (
        Decimal("100.00"),
        True,
        "totalEarnings - sum(non-cash earning lines)",
    )
    assert not notes.items


def test_gross_pay_is_not_derived_when_a_counted_line_could_be_either():
    notes = Notes()
    lines = [line(EARN, "100"), line(UNKNOWN, "3.10")]
    assert paid_gross(Money(amount=Decimal("103.10")), lines, "totalEarnings", notes) is None
    assert [d.code for d in notes.items] == ["GROSS_PAY_NOT_DERIVED"]
    # A line outside gross wages doesn't matter, whatever its kind.
    assert paid_gross(Money(amount=Decimal("100")), [line(EARN, "100"), line(UNKNOWN, "5", False)], "x", Notes())


def test_provided_wages_and_pay_must_differ_by_exactly_the_non_cash_lines():
    lines = [line(EARN, "100"), line(FRINGE, "3.10"), line(MEMO, "60", in_gross=False)]
    totals = PayStatementTotals(gross_wages=Money(amount=Decimal("103.10")), gross_pay=Money(amount=Decimal("100")))
    assert results(statement(totals, lines)) == {
        "gross wages = sum of earning lines counted in gross": "pass",
        "gross wages - non-cash earnings = gross pay": "pass",
    }
    totals.gross_pay = Money(amount=Decimal("103.10"))  # a provider that left the fringe in "gross pay"
    assert results(statement(totals, lines))["gross wages - non-cash earnings = gross pay"] == "fail"


def test_net_is_checked_from_gross_pay_and_payments_from_net():
    totals = PayStatementTotals(
        gross_wages=Money(amount=Decimal("103.10")),
        gross_pay=Money(amount=Decimal("100"), derived=True, formula="test"),
        net_pay=Money(amount=Decimal("90")),
    )
    outcome = results(statement(totals, [line(EARN, "100"), line(FRINGE, "3.10")], tax="10", paid="90"))
    # The derived gross pay is not checked against the wages it came from.
    assert outcome == {
        "gross wages = sum of earning lines counted in gross": "pass",
        "gross pay - employee taxes - deductions = net": "pass",
        "payments = net": "pass",
    }


def test_a_derived_total_is_never_checked_against_its_own_lines():
    totals = PayStatementTotals(gross_wages=Money(amount=Decimal("1"), derived=True, formula="sum(lines)"))
    assert results(statement(totals, [line(EARN, "100")])) == {}
