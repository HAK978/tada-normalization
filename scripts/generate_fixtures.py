"""Generate the seeded synthetic fixtures and their expected (golden) canonical output.

    python scripts/generate_fixtures.py            # rewrite fixtures/ and tests/golden/
    python scripts/generate_fixtures.py --check    # exit 1 if anything would change

Fixtures are provider-shaped raw bundles built from known facts (src/normalization/fixtures/).
Every generated response is validated against the provider's published schema before writing, and
fixtures/MANIFEST.json records how each scenario was made: its builder and seed, the spec it was
validated against, the schema each response matches, and the SHA-256 of every file written.
"""

import argparse
import hashlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

from normalization.bundle import Bundle
from normalization.fixtures import (
    isolved as isolved_fixtures,
    prismhr as prismhr_fixtures,
    ukg_ready as ukg_fixtures,
)
from normalization.fixtures.validate import DEVIATIONS, SPECS, errors, response_pointer
from normalization.mappings import reviewed
from normalization.providers import normalize

ROOT = Path(__file__).resolve().parents[1]
# The golden output is the whole pipeline's, the one the CLI runs (providers.normalize), with the reviewed
# mapping files applied as the CLI applies them (A-86).
SCENARIOS = {
    ("prismhr", "brightside"): prismhr_fixtures.build,
    ("isolved", "brightside"): isolved_fixtures.build,
    ("ukg-ready", "brightside"): ukg_fixtures.build,
}
ABOUT = (
    "How each synthetic scenario was generated, written by scripts/generate_fixtures.py. "
    "Its --check fails when anything here no longer matches a fresh generation."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_entry(root: Path, provider: str, scenario: str, build, bundle, files: list[Path], golden: Path) -> dict:
    """What made one scenario, and every file it wrote: session.json first, then one file per response."""
    seed = inspect.signature(build).parameters.get("seed")
    session, *captures = files
    return {
        "provider": provider,
        "scenario": scenario,
        "builder": f"{build.__module__}.{build.__name__}",
        "seed": None if seed is None else seed.default,
        "as_of": bundle.as_of,
        "spec": {"file": SPECS[provider].relative_to(ROOT).as_posix(), "sha256": _sha256(SPECS[provider])},
        "validated_responses": sum(capture["status"] == 200 for capture in bundle.captures),
        "allowed_deviations": [
            {"validator": validator, "field": field} for validator, field in sorted(DEVIATIONS.get(provider, ()))
        ],
        "files": [
            {"file": session.relative_to(root).as_posix(), "sha256": _sha256(session)},
            *(
                {
                    "file": path.relative_to(root).as_posix(),
                    "endpoint": capture["endpoint"],
                    "status": capture["status"],
                    **(
                        {"schema": "#" + response_pointer(provider, capture["endpoint"])}
                        if capture["status"] == 200
                        else {}
                    ),
                    "sha256": _sha256(path),
                }
                for path, capture in zip(captures, bundle.captures, strict=True)
            ),
        ],
        "golden": {"file": golden.relative_to(root).as_posix(), "sha256": _sha256(golden)},
    }


def generate(root: Path) -> list[Path]:
    written: list[Path] = []
    scenarios = []
    for (provider, scenario), build in SCENARIOS.items():
        bundle = build()
        problems = [
            (c["endpoint"], e)
            for c in bundle.captures
            if c["status"] == 200
            for e in errors(provider, c["endpoint"], c["body"])
        ]
        if problems:
            raise SystemExit(f"{provider}/{scenario} breaks the provider schema: {problems[:5]}")
        target = root / "fixtures" / provider / scenario
        files = bundle.write(target)
        golden = root / "tests" / "golden" / provider / f"{scenario}.json"
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(normalize(Bundle.load(target), mapping_files=reviewed()).to_json(), encoding="utf-8")
        written += [*files, golden]
        scenarios.append(_manifest_entry(root, provider, scenario, build, bundle, files, golden))
    manifest = root / "fixtures" / "MANIFEST.json"
    manifest.write_text(json.dumps({"about": ABOUT, "scenarios": scenarios}, indent=2) + "\n", encoding="utf-8")
    return [*written, manifest]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed files differ from a fresh run")
    args = parser.parse_args(argv)
    if not args.check:
        for path in generate(ROOT):
            print(path.relative_to(ROOT))
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        fresh = generate(Path(tmp))
        stale = [
            p.relative_to(tmp)
            for p in fresh
            if not (ROOT / p.relative_to(tmp)).is_file() or (ROOT / p.relative_to(tmp)).read_bytes() != p.read_bytes()
        ]
        extra = {p.relative_to(ROOT) for p in (ROOT / "fixtures").rglob("*.json")} - {p.relative_to(tmp) for p in fresh}
    for path in stale:
        print(f"out of date: {path}", file=sys.stderr)
    for path in sorted(extra):
        print(f"not generated: {path}", file=sys.stderr)
    return 1 if stale or extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
