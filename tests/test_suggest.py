"""Suggestions for unmapped values (A-66): arithmetic first, similar names as a hint, never applied."""

import json
from decimal import Decimal
from pathlib import Path

from normalization.bundle import Bundle
from normalization.mappings import Mappings, review, template
from normalization.providers import normalize
from normalization.suggest import suggest

ROOT = Path(__file__).resolve().parents[1]


def reviewed(provider: str, bundle: Bundle | None = None):
    output = normalize(bundle or Bundle.load(ROOT / f"fixtures/{provider}/brightside"))
    items = review([(provider, output)])
    suggest(items, [(provider, output)])
    return {(u.field, u.raw): u for u in items}


def by_method(item):
    return {s.method: s for s in item.suggestions}


def test_arithmetic_says_an_unknown_earning_is_not_paid_and_similarity_ranks_within_that():
    memo = by_method(reviewed("ukg-ready")[("earnings[].type_name", "Earning (Memo)")])
    arithmetic, similarity = memo["arithmetic"], memo["similarity"]
    assert set(arithmetic.values) == {"MEMO", "NON_CASH_FRINGE", "REPORTED_TIPS"}
    assert arithmetic.confidence == 1.0 and "1 of 1 paychecks" in arithmetic.reasoning
    assert similarity.values[0] == "MEMO" and set(similarity.values) <= set(arithmetic.values)
    assert "not evidence" in similarity.reasoning


def test_arithmetic_says_an_unknown_earning_is_paid_in_cash():
    item = reviewed("isolved")[("clientPayItems[].systemBenefitType+systemPayItemType", "1099M Non EE Comp")]
    arithmetic = by_method(item)["arithmetic"]
    assert set(arithmetic.values) == {"EARNINGS", "REIMBURSEMENT"} and arithmetic.confidence == 1.0


def test_contradicting_paychecks_give_no_candidate():
    bundle = Bundle.load(ROOT / "fixtures/ukg-ready/brightside")
    maria = next(c for c in bundle.captures if c.path.endswith("/pay-statements/7101"))
    # The same unknown line, but here the payments include it: on this paycheck it reads as cash.
    maria.body["earnings"].append(
        {
            "type_name": "Earning (Memo)",
            "earning": {"code": "Tips Memo", "name": "Tips Memo"},
            "ee_amount": Decimal("10"),
        }
    )
    maria.body["payments"][0]["ee_amount"] += Decimal("10")
    arithmetic = by_method(reviewed("ukg-ready", bundle)[("earnings[].type_name", "Earning (Memo)")])["arithmetic"]
    assert arithmetic.values == [] and arithmetic.reasoning.startswith("contradictory")


def test_no_hint_without_a_canonical_list_or_a_resemblance():
    items = reviewed("ukg-ready")
    open_code = items[("payroll_frequency.type", "EVERY_PAY")]  # an open code: no canonical list
    assert open_code.allowed is None and not open_code.suggestions
    assert items[("pay-info.pay_type.id", "901")].allowed == ["SALARY", "HOURLY", "COMMISSION", "DRIVER"]


def test_suggestions_are_never_applied(tmp_path):
    items = reviewed("ukg-ready")
    files = template(list(items.values()))
    row = next(r for r in files["ukg-ready"]["mappings"] if r["raw"] == "Earning (Memo)")
    assert row["suggestions"] and row["value"] is None and row["evidence"] is None
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps(files["ukg-ready"]), encoding="utf-8")
    assert Mappings.load([path], "ukg-ready").entries == {}
    statement = next(
        r
        for r in normalize(Bundle.load(ROOT / "fixtures/ukg-ready/brightside"), mapping_files=[path]).records[
            "pay_statements"
        ]
        if r.id.endswith(":7103")
    )
    memo = next(e for e in statement.earnings if e.code == "Tips Memo")
    assert memo.kind.value.value == "UNMAPPED"


def test_suggestions_are_deterministic():
    first, second = reviewed("ukg-ready"), reviewed("ukg-ready")
    assert {k: [s.__dict__ for s in v.suggestions] for k, v in first.items()} == {
        k: [s.__dict__ for s in v.suggestions] for k, v in second.items()
    }
