"""Local entry point. Transformation output schema is chosen by the candidate."""
import argparse
import json
import sys
from pathlib import Path

from .adapters import ADAPTERS, ENTITIES
from .references import all_readiness_issues, load_reference, readiness_issues


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tada AI normalization starter")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-providers")
    commands.add_parser("check-inputs")
    run = commands.add_parser("normalize")
    run.add_argument("--provider", choices=ADAPTERS, required=True)
    run.add_argument("--entity", choices=ENTITIES, required=True)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "list-providers":
        print("\n".join(ADAPTERS))
        return 0
    if args.command == "check-inputs":
        issues = all_readiness_issues()
        print(json.dumps(issues, indent=2))
        return 2 if any(issues.values()) else 0
    issues = readiness_issues(args.provider)
    if issues:
        print(json.dumps({"provider": args.provider, "readiness_issues": issues}, indent=2), file=sys.stderr)
        return 2
    try:
        with args.input.open(encoding="utf-8") as stream:
            response = json.load(stream)
        result = ADAPTERS[args.provider].normalize(args.entity, response, load_reference(args.provider))
        # Serialize first and refuse overwriting an existing file in this scaffold.
        serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    except (OSError, ValueError, TypeError, NotImplementedError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
