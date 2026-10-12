"""Offline crawl against a fake provider: only GETs, no secrets on disk, re-sign-in on expiry."""
import json
from datetime import date

import httpx
import pytest

from normalization.live.client import ReadOnlyClient, Recorder
from normalization.live.crawl import Limits, crawl
from normalization.live.scope import ScopeError
from normalization.live.signin import SIGNIN_URL

TOKEN = "secret-token-that-must-never-be-saved"
BASE = "https://ukg.example.test/ta"


class FakeUkg:
    def __init__(self, expire_first_call=False):
        self.requests: list[httpx.Request] = []
        self.signins = 0
        self.expire_first_call = expire_first_call

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == SIGNIN_URL:
            self.signins += 1
            return httpx.Response(200, json={
                "provider": "ukg", "tenant_id": "833341", "base_url": BASE,
                "auth": {"access_token": TOKEN, "token_type": "Bearer"},
                "context": {"companies": [{"company_id": "33"}]},
                "usage": {"header_name": "Authorization", "header_prefix": "Bearer"},
            })
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if self.expire_first_call:
            self.expire_first_call = False
            return httpx.Response(401, json={"error": "expired"})
        path = request.url.path
        if path.endswith("/employees"):
            return httpx.Response(200, json={"employees": [{"id": 1}, {"id": 2}]})
        if path.endswith("/deductions"):
            return httpx.Response(200, json={"deductions": [{"id": 9}]})
        if path.endswith("/payrolls"):
            return httpx.Response(200, json={"payrolls": [{"id": 5}]})
        if path.endswith("/pay-statements"):
            return httpx.Response(200, json={"pay_statements": [{"id": 6}]})
        if path.endswith("/direct-deposits"):
            return httpx.Response(410, json={"message": "deprecated"})
        return httpx.Response(200, json={"ok": True})


def make_client(tmp_path, fake):
    http = httpx.Client(transport=httpx.MockTransport(fake))
    return ReadOnlyClient("ukg-ready", "api-key", Recorder(tmp_path / "run"), http=http,
                          delay=0, sleep=lambda _: None, log=lambda _: None)


def test_crawl_sends_only_gets_and_never_saves_the_token(tmp_path):
    fake = FakeUkg()
    client = make_client(tmp_path, fake)
    crawl(client, Limits(date(2024, 1, 1), date(2024, 12, 31)))

    methods = {(r.method, str(r.url) == SIGNIN_URL) for r in fake.requests}
    assert methods == {("POST", True), ("GET", False)}
    dd = [r for r in fake.requests if r.url.path.endswith("/direct-deposits")]
    assert dd and all(r.headers["X-End-of-Support-Timeline"] == "2026-01-29" for r in dd)

    saved = list((tmp_path / "run").rglob("*.json")) + list((tmp_path / "run").rglob("*.jsonl"))
    assert saved and not any(TOKEN in path.read_text() for path in saved)
    context = json.loads((tmp_path / "run" / "session.json").read_text())
    assert context["companies"] == [{"company_id": "33"}]


def test_expired_session_signs_in_again_once(tmp_path):
    fake = FakeUkg(expire_first_call=True)
    client = make_client(tmp_path, fake)
    record = client.get("rest/v2/companies/33/lookup/eins")
    assert record["status"] == 200 and fake.signins == 2


def test_out_of_scope_request_is_never_sent(tmp_path):
    fake = FakeUkg()
    client = make_client(tmp_path, fake)
    before = len(fake.requests)
    with pytest.raises(ScopeError):
        client.get("rest/v2/companies/34/employees")
    assert len(fake.requests) == before


PRISM_BASE = "https://prism.example.test/api/services/rest"


def prism_transport(requests):
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == SIGNIN_URL:
            return httpx.Response(200, json={
                "base_url": PRISM_BASE, "tenant_id": "970592", "auth": {"sessionId": TOKEN},
                "context": {"companies": [{"client_id": "102"}]}})
        if request.url.path.endswith("/getClientMaster"):
            return httpx.Response(200, json={"clientMaster": {
                "id": "102", "employerId": "5", "altEmployer": [{"altEmployerId": "20"}]}})
        return httpx.Response(200, json={"employerInfo": []})
    return handle


def test_employer_lookups_are_learned_only_from_demo_client_masters(tmp_path):
    requests: list[httpx.Request] = []
    http = httpx.Client(transport=httpx.MockTransport(prism_transport(requests)))
    client = ReadOnlyClient("prismhr", "api-key", Recorder(tmp_path / "run"), http=http,
                            delay=0, sleep=lambda _: None, log=lambda _: None)
    with pytest.raises(ScopeError):
        client.get("system/v1/getEmployerDetails", {"employerId": "5"})
    client.get("clientMaster/v1/getClientMaster", {"clientId": "102"})
    assert client.employers == {"5", "20"}
    assert client.get("system/v1/getEmployerDetails", {"employerId": "20"})["status"] == 200
    before = len(requests)
    for params in ({"employerId": "7"}, {}):
        with pytest.raises(ScopeError):
            client.get("system/v1/getEmployerDetails", params)
    assert len(requests) == before
