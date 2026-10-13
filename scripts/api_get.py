"""Make one read-only, scope-checked GET against a demo tenant and print the JSON.

Signs in through the organizer's service with DEMO_SIGNIN_API_KEY (.env), sends
the request through the same guard as discovery (GET only, allowlisted
endpoints, demo company IDs only), prints the response and saves a copy under
.discovery/<provider>/<timestamp>_manual/.

    python scripts/api_get.py ukg-ready rest/v2/companies/33704016/lookup/eins
    python scripts/api_get.py isolved api/clients/4046/legals/5797/employees pageSize=5
    python scripts/api_get.py prismhr employee/v1/getEmployeeList clientId=102

Query parameters are key=value; repeat a key to send a list (employeeId=A employeeId=B).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from normalization.live.client import ReadOnlyClient, Recorder
from normalization.live.scope import ScopeError
from normalization.live.signin import SignInError, load_api_key

ROOT = Path(__file__).resolve().parents[1]


def parse_params(pairs: list[str]) -> dict:
    params: dict = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"query parameters must be key=value, got {pair!r}")
        if key in params:
            previous = params[key]
            params[key] = [*previous, value] if isinstance(previous, list) else [previous, value]
        else:
            params[key] = value
    return params


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("provider", choices=("prismhr", "isolved", "ukg-ready"))
    parser.add_argument("path", help="path after the base URL, e.g. rest/v2/companies/33704016/employees")
    parser.add_argument("params", nargs="*", help="query parameters as key=value")
    args = parser.parse_args(argv)

    run = ROOT / ".discovery" / args.provider / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_manual")
    try:
        client = ReadOnlyClient(args.provider, load_api_key(ROOT / ".env"), Recorder(run),
                                log=lambda line: print(line, file=sys.stderr))
        if args.provider == "prismhr" and args.path == "system/v1/getEmployerDetails":
            print("employer lookups need a demo client's master record first; use discover.py", file=sys.stderr)
        record = client.get(args.path, parse_params(args.params))
    except (SignInError, ScopeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record["body"], indent=2))
    return 0 if record["status"] < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
