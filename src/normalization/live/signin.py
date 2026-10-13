"""Sign in through the organizer's demo service; provider auth stays in memory only.

POST /signin to the organizer's service is the only non-GET request this
project makes. Its response carries provider credentials, so the Session
keeps them out of repr() and public_context() never includes them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .scope import Companies

SIGNIN_URL = "https://tada-demo-provider-signin.onrender.com/signin"
TENANT_SELECTORS = {"prismhr": "prism", "isolved": "isol", "ukg-ready": "ukg"}
API_KEY_VARIABLE = "DEMO_SIGNIN_API_KEY"


class SignInError(Exception):
    """The sign-in service refused the request or answered unexpectedly."""


@dataclass
class Session:
    provider: str
    tenant_id: str
    base_url: str
    companies: Companies
    company_entries: list[dict]
    auth_headers: dict[str, str] = field(repr=False)
    auth_fields: list[str] = field(default_factory=list)
    secrets: tuple[str, ...] = field(default=(), repr=False)

    def public_context(self) -> dict:
        """Everything about the session that is safe to print or save."""
        return {
            "provider": self.provider,
            "tenant_id": self.tenant_id,
            "base_url": self.base_url,
            "companies": self.company_entries,
            "auth_fields_returned": self.auth_fields,
            "auth_header_names": sorted(self.auth_headers),
        }


def load_api_key(env_file: Path = Path(".env")) -> str:
    """Read the key from the environment, falling back to a KEY=VALUE .env file."""
    key = os.environ.get(API_KEY_VARIABLE, "").strip()
    if not key and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == API_KEY_VARIABLE:
                key = value.strip().strip("'\"")
    if not key:
        raise SignInError(f"{API_KEY_VARIABLE} is not set; add it to .env")
    return key


def sign_in(provider: str, api_key: str, http: httpx.Client) -> Session:
    response = http.post(
        SIGNIN_URL,
        headers={"X-API-Key": api_key},
        json={"tenant": TENANT_SELECTORS[provider]},
        timeout=httpx.Timeout(120.0, connect=60.0),
        follow_redirects=False,
    )
    if response.is_redirect:
        # Following it would resend the API key to wherever the redirect points.
        raise SignInError(f"/signin for {provider} answered with a redirect; refusing to follow it")
    if response.status_code != 200:
        detail = response.text[:200].replace(api_key, "[REDACTED]")
        raise SignInError(f"/signin for {provider} returned HTTP {response.status_code}: {detail}")
    data = response.json()
    auth = data.get("auth") or {}
    usage = data.get("usage") or {}
    token = auth.get("sessionId") if provider == "prismhr" else auth.get("access_token")
    if not token or not data.get("base_url"):
        raise SignInError(f"/signin for {provider} returned no token or base_url (fields: {sorted(data)})")
    header_name = usage.get("header_name") or ("sessionId" if provider == "prismhr" else "Authorization")
    prefix = usage.get("header_prefix")
    if prefix is None:
        prefix = "" if provider == "prismhr" else "Bearer"
    value = f"{prefix.strip()} {token}" if prefix.strip() else token
    entries = (data.get("context") or {}).get("companies") or []
    return Session(
        provider=provider,
        tenant_id=str(data.get("tenant_id", "")),
        base_url=data["base_url"],
        companies=Companies.from_signin(provider, entries),
        company_entries=entries,
        auth_headers={header_name: value},
        auth_fields=sorted(auth),
        secrets=tuple(str(v) for k, v in auth.items() if k in ("sessionId", "access_token", "refresh_token") and v),
    )
