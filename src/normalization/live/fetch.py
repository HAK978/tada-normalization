"""Read-only fetch from the live demo tenants into raw bundles (A-04).

Every request goes through the scope guard, and responses are saved under the output folder
(.discovery/ by default, gitignored). Needs DEMO_SIGNIN_API_KEY in the environment or in .env.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .client import ReadOnlyClient, Recorder
from .crawl import Limits, crawl
from .scope import ScopeError
from .signin import SignInError, load_api_key


def fetch(
    providers: list[str],
    limits: Limits,
    out: Path,
    env_file: Path,
    *,
    signin_only: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[list[Path], int]:
    """Fetch each provider into <out>/<provider>/<UTC stamp>/. Returns (bundle folders, failure count)."""
    api_key = load_api_key(env_file)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundles, failures = [], 0
    for provider in providers:
        run_dir = out / provider / stamp
        recorder = Recorder(run_dir)
        try:
            client = ReadOnlyClient(provider, api_key, recorder, log=log)
            log(json.dumps(client.session.public_context(), indent=2))
            if not signin_only:
                crawl(client, limits)
            bundles.append(run_dir)
        except (SignInError, ScopeError) as exc:
            failures += 1
            log(f"[{provider}] stopped: {exc}")
        log(f"[{provider}] saved {recorder.count} responses to {run_dir}")
    return bundles, failures
