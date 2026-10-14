"""Mapping files and the review queue (A-65, A-69): unknown values resolved by data with evidence, not
code, for one tenant and, where a rule says so, only some of its companies."""

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
PRISM = ROOT / "fixtures/prismhr/brightside"
TENANT = "synthetic"  # the fixtures' tenant


def mapping_file(tmp_path, provider, *rows, name="mappings.json", tenant=TENANT):
    path = tmp_path / name
    path.write_text(json.dumps({"provider": provider, "tenant": tenant, "mappings": list(rows)}), encoding="utf-8")
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
    mappings = Mappings.load([mapping_file(tmp_path, "ukg-ready", row)], "ukg-ready", TENANT)
    assert mappings.lookup("earnings[0].type_name", "Earning (Memo)") == "MEMO"


def test_every_mapping_needs_evidence_and_a_valid_value(tmp_path):
    with pytest.raises(ValueError, match="evidence"):
        Mappings.load([mapping_file(tmp_path, "ukg-ready", {**MEMO, "evidence": ""})], "ukg-ready", TENANT)
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
    path.write_text(json.dumps(files[("ukg-ready", TENANT)]), encoding="utf-8")
    assert Mappings.load([path], "ukg-ready", TENANT).entries == {}
    row = next(r for r in files[("ukg-ready", TENANT)]["mappings"] if r["raw"] == "Earning (Memo)")
    row.update(value="MEMO", evidence="confirmed with the tenant")
    path.write_text(json.dumps(files[("ukg-ready", TENANT)]), encoding="utf-8")
    remaining = review([("ukg-ready", normalize(Bundle.load(UKG), mapping_files=[path]))])
    assert ("earnings[].type_name", "Earning (Memo)") not in {(u.field, u.raw) for u in remaining}


def test_review_command_writes_the_report_and_templates(tmp_path, capsys):
    assert main(["review", str(UKG), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "UNMAPPED_REVIEW.md").read_text(encoding="utf-8").startswith("# Unmapped values to review")
    template_file = json.loads((tmp_path / "mappings-ukg-ready-synthetic.json").read_text(encoding="utf-8"))
    assert (template_file["provider"], template_file["tenant"]) == ("ukg-ready", TENANT)
    assert "distinct unmapped values" in capsys.readouterr().out


# ---------------------------------------------------------------- scope (A-69)

PRNT = {"field": "status", "raw": "PRNT", "value": "PRINTED", "evidence": "PEO payroll team, 2026-10-14"}
CLIENT_201, CLIENT_202 = "prismhr:synthetic:company:201", "prismhr:synthetic:company:202"


def statuses(out):
    return {r.id: r.status.value for r in out.records["pay_statements"]}


def test_a_mapping_file_names_its_tenant_and_applies_to_no_other(tmp_path):
    unnamed = tmp_path / "unnamed.json"
    unnamed.write_text(json.dumps({"provider": "ukg-ready", "mappings": [MEMO]}), encoding="utf-8")
    with pytest.raises(ValueError, match="must name its tenant"):
        normalize(Bundle.load(UKG), mapping_files=[unnamed])
    other = mapping_file(tmp_path, "ukg-ready", MEMO, tenant="another-tenant")
    loaded = Mappings.load([other], "ukg-ready", TENANT)
    assert loaded.entries == {} and "another-tenant" in loaded.skipped[0]
    memo = one(normalize(Bundle.load(UKG), mapping_files=[other]), "pay_statements", ":7103")
    assert next(e for e in memo.earnings if e.code == "Tips Memo").kind.value.value == "UNMAPPED"


def test_a_rule_for_some_companies_applies_only_to_them(tmp_path):
    # PRNT is a voucher status in both fixture clients; the evidence covers client 201 only.
    path = mapping_file(tmp_path, "prismhr", {**PRNT, "companies": [CLIENT_201]})
    out = normalize(Bundle.load(PRISM), mapping_files=[path])
    by_client = {sid.split(":")[3]: status for sid, status in statuses(out).items()}
    assert {by_client[k] for k in by_client if k == "201"} == {"PRINTED"}
    assert by_client["202"] == "UNMAPPED"
    mapped = {r.company_id for r in out.records["pay_statements"] if "MAPPED_BY_FILE" in codes(r)}
    assert mapped == {CLIENT_201}


def test_the_same_code_can_mean_different_things_in_two_companies(tmp_path):
    path = mapping_file(
        tmp_path,
        "prismhr",
        {**PRNT, "companies": [CLIENT_201]},
        {**PRNT, "value": "PRINTED_ELSEWHERE", "companies": [CLIENT_202]},
    )
    out = normalize(Bundle.load(PRISM), mapping_files=[path])
    assert {s for sid, s in statuses(out).items() if ":202:" in sid} == {"PRINTED_ELSEWHERE"}
    assert {s for sid, s in statuses(out).items() if ":201:" in sid} == {"PRINTED"}


def test_rules_whose_companies_overlap_must_agree(tmp_path):
    clash = mapping_file(tmp_path, "prismhr", {**PRNT, "companies": [CLIENT_201]}, {**PRNT, "value": "OTHER"})
    with pytest.raises(ValueError, match="already mapped to PRINTED for prismhr:synthetic:company:201"):
        Mappings.load([clash], "prismhr", TENANT)
    with pytest.raises(ValueError, match="list of company IDs"):
        Mappings.load([mapping_file(tmp_path, "prismhr", {**PRNT, "companies": []})], "prismhr", TENANT)


def test_the_template_limits_each_rule_to_the_companies_it_was_seen_in():
    items = review([("prismhr", normalize(Bundle.load(PRISM)))])
    rows = {r["raw"]: r for r in template(items)[("prismhr", TENANT)]["mappings"]}
    assert rows["PRNT"]["companies"] == [CLIENT_201, CLIENT_202]
    assert rows["OT"]["companies"] == [CLIENT_201]


def test_the_output_says_which_mapping_files_and_rules_applied(tmp_path):
    typo = {**PRNT, "companies": ["prismhr:synthetic:company:2O1"]}  # letter O for zero: matches nothing
    path = mapping_file(tmp_path, "prismhr", PRNT, {**typo, "raw": "VOID"})
    elsewhere = mapping_file(tmp_path, "prismhr", PRNT, name="other.json", tenant="another-tenant")
    out = normalize(Bundle.load(PRISM), mapping_files=[path, elsewhere])
    [report] = out.provenance["mapping_files"]
    assert (report["path"], report["rules"], report["applied"]) == (str(path), 2, 1)
    assert len(report["sha256"]) == 64
    assert report["unapplied"] == [{"field": "status", "raw": "VOID", "companies": typo["companies"]}]
    assert out.provenance["mapping_files_skipped"] == [f"{elsewhere}: for tenant 'another-tenant'"]
