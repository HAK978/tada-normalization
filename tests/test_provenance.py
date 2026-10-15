"""Provenance (A-71): every output says which snapshot, evaluation date, mapping files and code made it."""

import json
import shutil
import sqlite3
from pathlib import Path

from normalization.bundle import Bundle
from normalization.export import write_json, write_sqlite
from normalization.providers import normalize

ROOT = Path(__file__).resolve().parents[1]
UKG = ROOT / "fixtures/ukg-ready/brightside"


def test_provenance_names_the_snapshot_date_mapping_files_and_code(tmp_path):
    mapping = tmp_path / "mappings.json"
    mapping.write_text(
        json.dumps(
            {
                "provider": "ukg-ready",
                "tenant": "synthetic",
                "mappings": [
                    {"field": "earnings[].type_name", "raw": "Earning (Memo)", "value": "MEMO", "evidence": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )
    bundle = Bundle.load(UKG)
    write_json(normalize(bundle, mapping_files=[mapping]), tmp_path / "out")
    about = json.loads((tmp_path / "out/provenance.json").read_text(encoding="utf-8"))
    assert about["bundle"] == {
        "provider": "ukg-ready",
        "tenant": "synthetic",
        "name": "brightside",
        "saved_at": bundle.saved_at,
        "captures": len(bundle.captures),
        "sha256": bundle.sha256,
    }
    assert about["as_of"] == bundle.as_of.isoformat()
    assert about["requests"]["unavailable"] == 5  # 4 deduction setups and the cost-center tree (A-70, A-75)
    assert (about["mapping_files"][0]["path"], about["mapping_files"][0]["applied"]) == (str(mapping), 1)
    assert about["tool"]["name"] == "tada-normalization" and about["tool"]["version"]
    assert about["tool"]["commit"] is None or len(about["tool"]["commit"]) == 40
    assert about["written_at"]


def test_the_bundle_hash_is_stable_and_changes_with_any_file(tmp_path):
    copy = tmp_path / "brightside"
    shutil.copytree(UKG, copy)
    first = Bundle.load(copy).sha256
    assert first == Bundle.load(copy).sha256 == Bundle.load(UKG).sha256 and len(first) == 64
    capture = sorted((copy / "captures").glob("*.json"))[-1]
    capture.write_text(capture.read_text(encoding="utf-8").replace("Regular", "Regulars", 1), encoding="utf-8")
    assert Bundle.load(copy).sha256 != first


def test_sqlite_has_a_source_row_per_output(tmp_path):
    outputs = [normalize(Bundle.load(ROOT / f"fixtures/{p}/brightside")) for p in ("prismhr", "ukg-ready")]
    database = write_sqlite(outputs, tmp_path / "canonical.sqlite")
    with sqlite3.connect(database) as db:
        rows = db.execute("SELECT provider, bundle_sha256, requests_unavailable FROM sources ORDER BY 1").fetchall()
    assert rows == [
        ("prismhr", Bundle.load(ROOT / "fixtures/prismhr/brightside").sha256, 7),
        ("ukg-ready", Bundle.load(UKG).sha256, 5),
    ]
