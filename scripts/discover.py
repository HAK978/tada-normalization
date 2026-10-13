"""Read-only discovery against the demo tenants.

Responses are saved verbatim under .discovery/ (gitignored) and are never
committed. Needs DEMO_SIGNIN_API_KEY in the environment or in .env.

    python scripts/discover.py --provider all --signin-only
    python scripts/discover.py --provider prismhr --max-employees 5
"""

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from normalization.live.client import ReadOnlyClient, Recorder
from normalization.live.crawl import Limits, crawl
from normalization.live.scope import ScopeError
from normalization.live.signin import SignInError, load_api_key

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("prismhr", "isolved", "ukg-ready")


def main(argv=None) -> int:
    today = date.today()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=(*PROVIDERS, "all"), required=True)
    parser.add_argument("--signin-only", action="store_true", help="sign in and save the public session context only")
    parser.add_argument("--since", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--until", type=date.fromisoformat, default=date(today.year + 1, 12, 31))
    parser.add_argument("--max-employees", type=int, default=25)
    parser.add_argument("--max-payrolls", type=int, default=12)
    parser.add_argument("--max-paychecks", type=int, default=40)
    parser.add_argument("--max-companies", type=int, default=None)
    parser.add_argument("--out", type=Path, default=ROOT / ".discovery")
    args = parser.parse_args(argv)

    api_key = load_api_key(ROOT / ".env")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    failures = 0
    for provider in PROVIDERS if args.provider == "all" else (args.provider,):
        run_dir = args.out / provider / stamp
        recorder = Recorder(run_dir)
        try:
            client = ReadOnlyClient(provider, api_key, recorder)
            print(json.dumps(client.session.public_context(), indent=2))
            if not args.signin_only:
                crawl(
                    client,
                    Limits(
                        args.since,
                        args.until,
                        args.max_employees,
                        args.max_payrolls,
                        args.max_paychecks,
                        args.max_companies,
                    ),
                )
        except (SignInError, ScopeError) as exc:
            failures += 1
            print(f"[{provider}] stopped: {exc}", file=sys.stderr)
        print(f"[{provider}] saved {recorder.count} responses to {run_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
