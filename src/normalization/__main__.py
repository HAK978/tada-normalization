"""Command line for the normalization platform.

    python -m normalization demo                  normalize every provider's synthetic scenario (offline)
    python -m normalization normalize BUNDLE      normalize one raw bundle: a fixture or a live fetch
    python -m normalization fetch --provider P    read-only fetch from the live demo tenants
    python -m normalization schema                write the canonical model's JSON Schemas
    python -m normalization coverage [BUNDLE ...]  report what happens to every source field

Normalized output goes under out/ (gitignored): one JSON file per record type, summary.json,
and canonical.sqlite. Only `fetch` uses the network; it needs DEMO_SIGNIN_API_KEY (A-04).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .bundle import Bundle
from .canonical.schema import write_schemas
from .coverage import measure, render
from .export import write_json, write_sqlite
from .output import Output
from .providers import PROVIDERS, normalize

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = "brightside"
# Report columns: heading -> record type.
COLUMNS = {
    "companies": "companies",
    "employees": "employees",
    "deposits": "direct_deposits",
    "elections": "deduction_elections",
    "runs": "payroll_runs",
    "paychecks": "pay_statements",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m normalization", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    demo = commands.add_parser("demo", help="normalize every provider's synthetic scenario (offline)")
    demo.add_argument("--out", type=Path, default=ROOT / "out" / "demo")

    run = commands.add_parser("normalize", help="normalize one raw bundle: a fixture or a live fetch")
    run.add_argument("bundle", type=Path, help="a bundle folder: session.json and captures/")
    run.add_argument("--out", type=Path, help="output folder (default: out/<provider>/<bundle folder>)")
    run.add_argument("--as-of", type=date.fromisoformat, help="evaluate time-dependent values at this date (A-33)")
    run.add_argument("--no-sqlite", action="store_true", help="write JSON only")

    today = date.today()
    fetch = commands.add_parser("fetch", help="read-only fetch from the live demo tenants (needs the API key)")
    fetch.add_argument("--provider", choices=(*PROVIDERS, "all"), required=True)
    fetch.add_argument("--signin-only", action="store_true", help="sign in and save the public session context only")
    fetch.add_argument("--since", type=date.fromisoformat, default=date(2015, 1, 1))
    fetch.add_argument("--until", type=date.fromisoformat, default=date(today.year + 1, 12, 31))
    fetch.add_argument("--max-employees", type=int, default=25)
    fetch.add_argument("--max-payrolls", type=int, default=12)
    fetch.add_argument("--max-paychecks", type=int, default=40)
    fetch.add_argument("--max-companies", type=int, default=None)
    fetch.add_argument("--out", type=Path, default=ROOT / ".discovery", help="where raw bundles go (gitignored)")
    fetch.add_argument("--env-file", type=Path, default=ROOT / ".env", help="read DEMO_SIGNIN_API_KEY from here")
    fetch.add_argument("--normalize", action="store_true", help="also normalize each fetched bundle into out/")

    schema = commands.add_parser("schema", help="write the JSON Schema of every canonical record type")
    schema.add_argument("--out", type=Path, default=ROOT / "schemas")

    coverage = commands.add_parser("coverage", help="report what the converters do with every source field")
    coverage.add_argument("bundles", type=Path, nargs="*", help="raw bundles (default: every synthetic scenario)")
    coverage.add_argument("--out", type=Path, default=ROOT / "docs" / "FIELD_COVERAGE.md")

    args = parser.parse_args(argv)
    handlers = {"demo": _demo, "normalize": _normalize, "fetch": _fetch, "schema": _schema, "coverage": _coverage}
    return handlers[args.command](args)


def _demo(args: argparse.Namespace) -> int:
    results = []
    for provider in PROVIDERS:
        output = normalize(Bundle.load(ROOT / "fixtures" / provider / SCENARIO))
        write_json(output, args.out / provider)
        results.append((provider, output))
    database = write_sqlite([output for _, output in results], args.out / "canonical.sqlite")
    _report(results)
    print(f"\nJSON, one file per record type: {args.out}/<provider>/")
    print(f"SQLite, all three providers:    {database}")
    return 0


def _normalize(args: argparse.Namespace) -> int:
    try:
        bundle = Bundle.load(args.bundle)
        output = normalize(bundle, args.as_of)
    except (OSError, KeyError, ValueError) as exc:
        print(f"cannot normalize {args.bundle}: {exc}", file=sys.stderr)
        return 1
    out = args.out or ROOT / "out" / bundle.provider / args.bundle.resolve().name
    _write(output, out, sqlite=not args.no_sqlite)
    _report([(bundle.provider, output)])
    print(f"\nwritten to {out}")
    return 0


def _fetch(args: argparse.Namespace) -> int:
    # Imported here so the offline commands never load the network client.
    from .live.crawl import Limits
    from .live.fetch import fetch
    from .live.signin import SignInError

    providers = list(PROVIDERS) if args.provider == "all" else [args.provider]
    limits = Limits(
        args.since, args.until, args.max_employees, args.max_payrolls, args.max_paychecks, args.max_companies
    )
    try:
        bundles, failures = fetch(providers, limits, args.out, args.env_file, signin_only=args.signin_only)
    except SignInError as exc:
        print(f"fetch stopped: {exc}", file=sys.stderr)
        return 1
    if args.normalize and not args.signin_only:
        results = []
        for folder in bundles:
            bundle = Bundle.load(folder)
            output = normalize(bundle)
            _write(output, ROOT / "out" / bundle.provider / folder.name, sqlite=True)
            results.append((bundle.provider, output))
        _report(results)
    return 1 if failures else 0


def _schema(args: argparse.Namespace) -> int:
    for path in write_schemas(args.out):
        print(path)
    return 0


def _coverage(args: argparse.Namespace) -> int:
    folders = args.bundles or [ROOT / "fixtures" / provider / SCENARIO for provider in PROVIDERS]
    results = []
    for folder in folders:
        bundle = Bundle.load(folder)
        synthetic = folder.resolve().is_relative_to(ROOT / "fixtures")
        source = f"`{folder.resolve().relative_to(ROOT)}`" if synthetic else f"a live fetch (`{folder.name}`)"
        results.append(measure(bundle, source))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(results), encoding="utf-8")
    twice = [(r.provider, path) for r in results for path in r.read_after_kept]
    for provider, path in twice:
        print(f"[{provider}] {path} is both mapped and kept in provider_extensions", file=sys.stderr)
    print(f"written to {args.out}")
    return 1 if twice else 0


def _write(output: Output, out: Path, *, sqlite: bool) -> None:
    write_json(output, out)
    if sqlite:
        write_sqlite([output], out / "canonical.sqlite")


def _report(results: list[tuple[str, Output]]) -> None:
    """One line per provider: record counts, reconciliation checks and warnings."""
    header = ["provider", *COLUMNS, "checks pass/fail", "warnings"]
    rows = [header]
    for provider, output in results:
        summary = output.summary()
        checks = summary["checks"]
        rows.append(
            [
                provider,
                *(str(summary["counts"][kind]) for kind in COLUMNS.values()),
                f"{checks.get('pass', 0)}/{checks.get('fail', 0)}",
                str(summary["diagnostics"].get("warning", 0)),
            ]
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    for row in rows:
        print(
            "  ".join(
                cell.ljust(w) if i == 0 else cell.rjust(w) for i, (cell, w) in enumerate(zip(row, widths, strict=True))
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
