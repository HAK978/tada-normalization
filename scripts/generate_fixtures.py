"""Generate the seeded synthetic fixtures and their expected (golden) canonical output.

    python scripts/generate_fixtures.py            # rewrite fixtures/ and tests/golden/
    python scripts/generate_fixtures.py --check    # exit 1 if anything would change

Fixtures are provider-shaped raw bundles built from known facts (src/normalization/fixtures/).
Every generated response is validated against the provider's published schema before writing.
"""

import argparse
import sys
import tempfile
from pathlib import Path

from normalization.bundle import Bundle
from normalization.fixtures import (
    isolved as isolved_fixtures,
    prismhr as prismhr_fixtures,
    ukg_ready as ukg_fixtures,
)
from normalization.fixtures.validate import errors
from normalization.providers import isolved, prismhr, ukg_ready

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = {
    ("prismhr", "brightside"): (prismhr_fixtures.build, prismhr.normalize),
    ("isolved", "brightside"): (isolved_fixtures.build, isolved.normalize),
    ("ukg-ready", "brightside"): (ukg_fixtures.build, ukg_ready.normalize),
}


def generate(root: Path) -> list[Path]:
    written: list[Path] = []
    for (provider, scenario), (build, normalize) in SCENARIOS.items():
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
        written += bundle.write(target)
        golden = root / "tests" / "golden" / provider / f"{scenario}.json"
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(normalize(Bundle.load(target)).to_json(), encoding="utf-8")
        written.append(golden)
    return written


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
