"""Mapping files and the review queue (A-65): unknown values resolved by data with evidence, not code."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.__main__ import main
from normalization.bundle import Bundle
from normalization.mappings import Mappings, review, template
from normalization.providers import normalize

ROOT = Path(__file__).resolve().parents[1]
UKG = ROOT / "fixtures/ukg-ready/brightside"


def mapping_file(tmp_path, provider, *rows, name="mappings.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"provider": provider, "mappings": list(rows)}), encoding="utf-8")
    return path


def one(out, kind, suffix):
    return next(r for r in out.records[kind] if r.id.endswith(suffix))


def codes(record):
    return {d.code for d in record.diagnostics}


MEMO = {
    "field": "earnings[].type_name",
    "raw": "Earning (Memo)",
    "value": "MEMO",
    "evidence": "Tenant payroll admin: memo lines are informational and never paid (ticket 123)",
}


def test_a_mapping_file_resolves_an_unmapped_value_and_everything_downstream(tmp_path):
    before = one(normalize(Bundle.load(UKG)), "pay_statements", ":7103")
    assert before.totals.gross_pay is None  # the unknown line could be cash or not

    after = one(
        normalize(Bundle.load(UKG), mapping_files=[mapping_file(tmp_path, "ukg-ready", MEMO)]),
        "pay_statements",
        ":7103",
    )
    memo = next(e for e in after.earnings if e.code == "Tips Memo")
    assert (memo.kind.value.value, memo.kind.raw) == ("MEMO", "Earning (Memo)")
    # Now classified, gross pay can be derived: the memo line is non-cash.
    assert after.totals.gross_pay.amount == Decimal("1200.00")
    notes = {d.code: d for d in after.diagnostics}
    assert "ticket 123" in notes["MAPPED_BY_FILE"].message
    assert not any(d.code == "UNMAPPED_CODE" and d.raw == "Earning (Memo)" for d in after.diagnostics)


def test_a_mapping_never_overrides_a_code_table(tmp_path):
    rows = {**MEMO, "raw": "Earning", "value": "MEMO"}  # "Earning" is already mapped to EARNINGS
    out = normalize(Bundle.load(UKG), mapping_files=[mapping_file(tmp_path, "ukg-ready", rows)])
    regular = next(e for e in one(out, "pay_statements", ":7102").earnings if e.code == "Regular")
    assert regular.kind.value.value == "EARNINGS"


def test_array_positions_do_not_matter(tmp_path):
    row = {**MEMO, "field": "earnings[3].type_name"}
    mappings = Mappings.load([mapping_file(tmp_path, "ukg-ready", row)], "ukg-ready")
    assert mappings.lookup("earnings[0].type_name", "Earning (Memo)") == "MEMO"


def test_every_mapping_needs_evidence_and_a_valid_value(tmp_path):
    with pytest.raises(ValueError, match="evidence"):
        Mappings.load([mapping_file(tmp_path, "ukg-ready", {**MEMO, "evidence": ""})], "ukg-ready")
    bad = mapping_file(tmp_path, "ukg-ready", {**MEMO, "value": "TIPS_OR_SOMETHING"})
    with pytest.raises(ValueError, match="not a valid EarningKind"):
        normalize(Bundle.load(UKG), mapping_files=[bad])


def test_review_groups_unknowns_into_decisions_and_its_template_round_trips(tmp_path):
    out = normalize(Bundle.load(UKG))
    items = review([("ukg-ready", out)])
    decisions = {(u.field, u.raw) for u in items}
    assert ("earnings[].type_name", "Earning (Memo)") in decisions
    assert ("calc_method.type", "NET_PAY") in decisions
    files = template(items)
    # An unfilled template loads (undecided rows are skipped); filling one row resolves it.
    path = tmp_path / "template.json"
    path.write_text(json.dumps(files["ukg-ready"]), encoding="utf-8")
    assert Mappings.load([path], "ukg-ready").entries == {}
    row = next(r for r in files["ukg-ready"]["mappings"] if r["raw"] == "Earning (Memo)")
    row.update(value="MEMO", evidence="confirmed with the tenant")
    path.write_text(json.dumps(files["ukg-ready"]), encoding="utf-8")
    remaining = review([("ukg-ready", normalize(Bundle.load(UKG), mapping_files=[path]))])
    assert ("earnings[].type_name", "Earning (Memo)") not in {(u.field, u.raw) for u in remaining}


def test_review_command_writes_the_report_and_templates(tmp_path, capsys):
    assert main(["review", str(UKG), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "UNMAPPED_REVIEW.md").read_text(encoding="utf-8").startswith("# Unmapped values to review")
    assert json.loads((tmp_path / "mappings-ukg-ready.json").read_text(encoding="utf-8"))["provider"] == "ukg-ready"
    assert "distinct unmapped values" in capsys.readouterr().out
