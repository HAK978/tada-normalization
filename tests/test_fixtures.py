"""Synthetic fixtures are deterministic and match the provider's published schema."""

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


def test_fixtures_are_synthetic():
    for bundle_dir in BUNDLES:
        assert Bundle.load(bundle_dir).tenant_id == "synthetic"
