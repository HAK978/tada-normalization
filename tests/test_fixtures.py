"""Synthetic fixtures are deterministic and match the provider's published schema."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from normalization.bundle import Bundle
from normalization.fixtures.validate import errors

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = sorted(p for p in (ROOT / "fixtures").glob("*/*") if (p / "session.json").is_file())


def test_committed_fixtures_and_golden_files_match_a_fresh_generation():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_fixtures.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("bundle_dir", BUNDLES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_fixture_response_matches_the_provider_schema(bundle_dir):
    bundle = Bundle.load(bundle_dir)
    problems = [
        (c.file, e) for c in bundle.captures if c.status == 200 for e in errors(bundle.provider, c.endpoint, c.body)
    ]
    assert problems == []


def test_the_manifest_lists_every_fixture_file_with_its_hash():
    manifest = json.loads((ROOT / "fixtures/MANIFEST.json").read_text(encoding="utf-8"))
    listed = {entry["file"]: entry["sha256"] for s in manifest["scenarios"] for entry in [*s["files"], s["golden"]]}
    on_disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / "fixtures").rglob("*.json")} - {"fixtures/MANIFEST.json"}
    assert on_disk <= set(listed), sorted(on_disk - set(listed))
    assert not [f for f, sha in listed.items() if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != sha]


def test_fixtures_are_synthetic():
    for bundle_dir in BUNDLES:
        assert Bundle.load(bundle_dir).tenant_id == "synthetic"
