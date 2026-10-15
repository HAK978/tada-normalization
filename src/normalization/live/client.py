"""GET-only client for the live demo tenants; every response is saved with credentials scrubbed."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import httpx

from .. import exactjson
from . import scope
from .signin import Session, sign_in

# Response headers are saved for discovery, minus anything that could carry a credential.
_DROPPED_HEADERS = {
    "set-cookie",
    "cookie",
    "authorization",
    "www-authenticate",
    "proxy-authenticate",
    "sessionid",
    "x-api-key",
}
# Signed tokens embedded in responses (UKG photo_href links carry one per employee).
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+)?")
_RETRYABLE = {429, 502, 504}
_MAX_REDIRECTS = 3


class Recorder:
    """Writes one JSON file per response plus an index, in request order."""

    def __init__(self, root: Path):
        self.root = root
        self.captures = root / "captures"
        self.captures.mkdir(parents=True, exist_ok=False)
        self.count = 0

    def save_context(self, session: Session) -> None:
        context = {**session.public_context(), "saved_at": _now()}
        (self.root / "session.json").write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")

    def save(
        self,
        endpoint: str,
        path: str,
        params: dict,
        response: httpx.Response,
        elapsed: float,
        redact: Callable[[str], str] = lambda text: text,
    ) -> dict:
        self.count += 1
        try:
            body = exactjson.loads(response.text)
        except ValueError:
            body = {"_non_json_body": response.text[:20000]}
        record = {
            "seq": self.count,
            "endpoint": endpoint,
            "path": path,
            "params": params,
            "status": response.status_code,
            "fetched_at": _now(),
            "elapsed_s": round(elapsed, 3),
            "headers": {k: v for k, v in response.headers.items() if k.lower() not in _DROPPED_HEADERS},
            "body": body,
        }
        name = f"{self.count:04d}_{re.sub(r'[^A-Za-z0-9]+', '_', endpoint).strip('_')[:80]}.json"
        (self.captures / name).write_text(redact(exactjson.dumps(record, indent=2)) + "\n", encoding="utf-8")
        index_line = {k: record[k] for k in ("seq", "endpoint", "path", "params", "status")} | {"file": name}
        with (self.root / "index.jsonl").open("a", encoding="utf-8") as index:
            index.write(redact(exactjson.dumps(index_line)) + "\n")
        return record


class ReadOnlyClient:
    """Sends only scope-checked GET requests; there is deliberately no other verb."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        recorder: Recorder,
        *,
        http: httpx.Client | None = None,
        delay: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ):
        self.provider = provider
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=httpx.Timeout(90.0, connect=30.0), follow_redirects=False)
        self.recorder = recorder
        self.delay = delay
        self.sleep = sleep
        self.log = log
        self.session = sign_in(provider, api_key, self._http)
        self.denied: set[str] = set()
        self.employers: set[str] = set()
        recorder.save_context(self.session)

    def get(self, path: str, params: dict | None = None, headers: dict | None = None) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.session.base_url.rstrip('/')}/{path.lstrip('/')}"
        endpoint = scope.check(
            self.provider,
            self.session.base_url,
            self.session.companies,
            url,
            params,
            frozenset(self.employers),
            method="GET",
        )
        started = time.monotonic()
        response = self._send(endpoint, url, params, headers or {})
        record = self.recorder.save(endpoint, path, params, response, time.monotonic() - started, self.redact)
        if endpoint == "clientMaster/v1/getClientMaster" and response.status_code == 200:
            self._learn_employers(record["body"])
        self.log(self.redact(f"[{self.provider}] {response.status_code} {path} {_brief(params)}"))
        self.sleep(self.delay)
        return record

    def redact(self, text: str) -> str:
        """Remove the API key, the current session's tokens and embedded signed tokens."""
        for secret in (self._api_key, *self.session.secrets):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return _JWT.sub("[REDACTED_TOKEN]", text)

    def _send(self, endpoint: str, url: str, params: dict, headers: dict) -> httpx.Response:
        reauthenticated = False
        for attempt in range(1, 5):
            response = self._follow(url, params, headers)
            if self._session_expired(response):
                if reauthenticated:
                    # Still refused with a brand-new session: a permission gap, not an expired token.
                    self.denied.add(endpoint)
                    return response
                if endpoint not in self.denied:
                    self.log(f"[{self.provider}] session may have expired; signing in again")
                    self._reauthenticate()
                    reauthenticated = True
                    continue
            wait = self._retry_wait(response, attempt)
            if wait is None or attempt == 4:
                return response
            self.log(f"[{self.provider}] HTTP {response.status_code}; waiting {wait:.1f}s before retrying")
            self.sleep(wait)
        return response

    def _follow(self, url: str, params: dict, headers: dict) -> httpx.Response:
        """Follow redirects manually so each hop is scope-checked too."""
        for _ in range(_MAX_REDIRECTS + 1):
            # Per request, so an injected client that follows redirects can't skip the checks below.
            response = self._http.get(
                url,
                params=params,
                follow_redirects=False,
                headers={"Accept": "application/json", **headers, **self.session.auth_headers},
            )
            if not response.is_redirect:
                return response
            target = httpx.URL(urljoin(str(response.url), response.headers["location"]))
            params = {}
            for key, value in target.params.multi_items():
                params[key] = (
                    [*params[key], value]
                    if isinstance(params.get(key), list)
                    else ([params[key], value] if key in params else value)
                )
            url = str(target.copy_with(query=None))
            scope.check(
                self.provider,
                self.session.base_url,
                self.session.companies,
                url,
                params,
                frozenset(self.employers),
                method="GET",
            )
        return response

    def _learn_employers(self, body: object) -> None:
        """Allow employer lookups only for employers a demo client's own master record points at."""
        master = body.get("clientMaster") if isinstance(body, dict) else None
        if not isinstance(master, dict):
            return
        candidates = [master.get("employerId")]
        candidates += [alt.get("altEmployerId") for alt in master.get("altEmployer") or [] if isinstance(alt, dict)]
        self.employers.update(str(c) for c in candidates if isinstance(c, (str, int)) and str(c).strip())

    def _reauthenticate(self) -> None:
        previous = self.session
        session = sign_in(self.provider, self._api_key, self._http)
        if (session.base_url, session.companies) != (previous.base_url, previous.companies):
            raise scope.ScopeError("re-sign-in returned a different base URL or company list; stopping")
        self.session = session

    def _session_expired(self, response: httpx.Response) -> bool:
        if response.status_code == 401:
            return True
        if self.provider == "prismhr" and response.status_code == 200:
            try:
                message = str(response.json().get("errorMessage") or "")
            except (ValueError, AttributeError):
                return False
            return "session has expired" in message.lower()
        return False

    @staticmethod
    def _retry_wait(response: httpx.Response, attempt: int) -> float | None:
        if response.status_code == 503:
            # UKG documents X-CallLimit-TimeToWait in milliseconds; without it, wait 60s.
            wait_ms = response.headers.get("X-CallLimit-TimeToWait")
            return int(wait_ms) / 1000 if wait_ms and wait_ms.isdigit() else 60.0
        if response.status_code in _RETRYABLE:
            return 2.0**attempt
        return None


def _brief(params: dict) -> str:
    parts = []
    for key, value in params.items():
        shown = f"[{len(value)} ids]" if isinstance(value, list) else str(value)
        parts.append(f"{key}={shown}")
    return " ".join(parts)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
