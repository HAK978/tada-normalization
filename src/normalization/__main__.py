"""Command line for the normalization platform.

    python -m normalization demo                  normalize every provider's synthetic scenario (offline)
    python -m normalization normalize BUNDLE      normalize one raw bundle: a fixture or a live fetch
    python -m normalization fetch --provider P    read-only fetch from the live demo tenants
    python -m normalization schema                write the canonical model's JSON Schemas
    python -m normalization coverage [BUNDLE ...]  report what happens to every source field
    python -m normalization write EMPLOYEES_JSON   dry run: the UKG Ready requests that would create them
    python -m normalization review BUNDLE ...     list unmapped values to decide, with mapping-file templates

Normalized output goes under out/ (gitignored): one JSON file per record type, summary.json,
and canonical.sqlite. Only `fetch` uses the network; it needs DEMO_SIGNIN_API_KEY (A-04).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import exactjson, mappings
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
    _mapping_options(demo)

    run = commands.add_parser("normalize", help="normalize one raw bundle: a fixture or a live fetch")
    run.add_argument("bundle", type=Path, help="a bundle folder: session.json and captures/")
    run.add_argument("--out", type=Path, help="output folder (default: out/<provider>/<bundle folder>)")
    run.add_argument("--as-of", type=date.fromisoformat, help="evaluate time-dependent values at this date (A-33)")
    run.add_argument("--no-sqlite", action="store_true", help="write JSON only")
    _mapping_options(run)

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
    _mapping_options(fetch)

    schema = commands.add_parser("schema", help="write the JSON Schema of every canonical record type")
    schema.add_argument("--out", type=Path, default=ROOT / "schemas")

    coverage = commands.add_parser("coverage", help="report what the converters do with every source field")
    coverage.add_argument("bundles", type=Path, nargs="*", help="raw bundles (default: every synthetic scenario)")
    coverage.add_argument(
        "--out",
        type=Path,
        help="default: docs/FIELD_COVERAGE.md for live bundles; out/FIELD_COVERAGE.md for the synthetic scenarios",
    )

    write = commands.add_parser("write", help="dry run: the UKG Ready requests that would create these employees")
    write.add_argument("employees", type=Path, help="an employees.json written by `demo` or `normalize`")
    write.add_argument("--to", choices=("ukg-ready",), default="ukg-ready", help="destination provider")
    write.add_argument("--employee", help="only this canonical employee ID (or a unique ending of it)")
    write.add_argument("--company", default="{cid}", help="destination UKG company ID")
    write.add_argument("--ein-id", type=int, help="destination EIN ID, for multi-EIN companies")
    write.add_argument("--out", type=Path, default=ROOT / "out" / "write")

    review = commands.add_parser("review", help="list unmapped values to decide, with mapping-file templates")
    review.add_argument("bundles", type=Path, nargs="+", help="raw bundles to normalize and review")
    _mapping_options(review)
    review.add_argument("--out", type=Path, default=ROOT / "out" / "review")

    args = parser.parse_args(argv)
    handlers = {
        "review": _review,
        "demo": _demo,
        "normalize": _normalize,
        "fetch": _fetch,
        "schema": _schema,
        "coverage": _coverage,
        "write": _write_dry_run,
    }
    return handlers[args.command](args)


def _mapping_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--mappings", type=Path, action="append", default=[], help="mapping file (A-65); repeatable")
    command.add_argument(
        "--no-reviewed-mappings",
        action="store_true",
        help="leave out the reviewed mapping files in mappings/, which otherwise apply to their own tenants (A-86)",
    )


def mapping_files(args: argparse.Namespace) -> list[Path]:
    """The reviewed mapping files in mappings/ unless left out, then any given with --mappings."""
    reviewed = [] if args.no_reviewed_mappings else mappings.reviewed()
    return reviewed + [p for p in args.mappings if p.resolve() not in {r.resolve() for r in reviewed}]


def _demo(args: argparse.Namespace) -> int:
    results = []
    for provider in PROVIDERS:
        output = normalize(Bundle.load(ROOT / "fixtures" / provider / SCENARIO), mapping_files=mapping_files(args))
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
        output = normalize(bundle, args.as_of, mapping_files(args))
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
            output = normalize(bundle, mapping_files=mapping_files(args))
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
    # The committed report describes the live fetch, so a run on the synthetic scenarios never replaces it.
    out = args.out or ROOT / ("docs" if args.bundles else "out") / "FIELD_COVERAGE.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(results), encoding="utf-8")
    twice = [(r.provider, path) for r in results for path in r.read_after_kept]
    for provider, path in twice:
        print(f"[{provider}] {path} is both mapped and kept in provider_extensions", file=sys.stderr)
    lost = [(r.provider, endpoint, path) for r in results for endpoint, path in r.lost]
    for provider, endpoint, path in lost:
        print(f"[{provider}] {endpoint} {path} is neither mapped nor kept: lost", file=sys.stderr)
    unread = [(r.provider, endpoint) for r in results for endpoint in r.unread]
    for provider, endpoint in unread:
        print(f"[{provider}] {endpoint}: no converter reads this response at all", file=sys.stderr)
    print(f"written to {out}")
    return 1 if twice or lost or unread else 0


def _write_dry_run(args: argparse.Namespace) -> int:
    """Nothing is sent: there is deliberately no way to execute a plan from here (A-63)."""
    from .write.ukg_ready import plan

    employees = json.loads(args.employees.read_text(encoding="utf-8"))
    if args.employee:
        employees = [e for e in employees if e["id"] == args.employee or e["id"].endswith(f":{args.employee}")]
        if len(employees) != 1:
            print(f"{args.employee}: {len(employees)} matching employees", file=sys.stderr)
            return 1
    out = args.out / args.to
    out.mkdir(parents=True, exist_ok=True)
    for employee in employees:
        result = plan(employee, company=args.company, ein_id=args.ein_id)
        path = out / (re.sub(r"[^A-Za-z0-9_.-]+", "_", employee["id"]) + ".json")
        path.write_text(exactjson.dumps(result.to_dict(), indent=1) + "\n", encoding="utf-8")
        verdict = "valid" if result.valid else "rejected by the schema"
        gaps = ", ".join(g["field"] for g in result.gaps) or "none"
        print(f"{employee['id']}: {len(result.requests)} requests, {verdict}; gaps: {gaps}")
    print(f"\ndry run only, nothing sent. Plans: {out}")
    return 0


def _review(args: argparse.Namespace) -> int:
    from .mappings import render, review, template
    from .suggest import suggest

    try:
        outputs = []
        for folder in args.bundles:
            bundle = Bundle.load(folder)
            outputs.append((bundle.provider, normalize(bundle, mapping_files=mapping_files(args))))
    except (OSError, KeyError, ValueError) as exc:
        print(f"cannot review: {exc}", file=sys.stderr)
        return 1
    items = review(outputs)
    suggest(items, outputs)  # proposals only; nothing is applied without a mapping file (A-66)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "UNMAPPED_REVIEW.md").write_text(render(items), encoding="utf-8")
    for (provider, tenant), data in template(items).items():
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"mappings-{provider}-{tenant}") + ".json"
        (args.out / name).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    records = sum(u.records for u in items)
    print(f"{len(items)} distinct unmapped values across {records} record mentions")
    for u in items[:15]:
        label = f" ({u.labels.most_common(1)[0][0]})" if u.labels else ""
        print(f"  {u.provider:9} {u.field} = {u.raw!r}{label}: {u.records} records")
        for s in u.suggestions:
            print(f"      {s.method}: {' / '.join(s.values) or 'no candidate'} ({s.confidence:.2f})")
    print(f"\nreport and mapping-file templates: {args.out}")
    return 0


def _write(output: Output, out: Path, *, sqlite: bool) -> None:
    write_json(output, out)
    if sqlite:
        write_sqlite([output], out / "canonical.sqlite")


def _report(results: list[tuple[str, Output]]) -> None:
    """One line per provider: record counts, reconciliation checks, warnings and requests that came back
    without data although data may exist (A-70)."""
    header = ["provider", *COLUMNS, "checks pass/fail", "warnings", "unavailable"]
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
                str(summary["requests"].get("unavailable", 0)),
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
