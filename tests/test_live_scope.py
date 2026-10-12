"""The live scope guard must refuse anything outside the demo companies, offline."""
import pytest

from normalization.live import client as live_client
from normalization.live.scope import Companies, ScopeError, check

PRISM_BASE = "https://prism.example.test/api/services/rest"
ISOLVED_BASE = "https://isolved.example.test"
UKG_BASE = "https://ukg.example.test/ta"

PRISM = Companies.from_signin("prismhr", [{"client_id": "100"}, {"client_id": "200"}])
ISOLVED = Companies.from_signin("isolved", [{"client_id": 7, "legal_id": 70}])
UKG = Companies.from_signin("ukg-ready", [{"company_id": "33"}])


def test_prism_allows_allowlisted_operation_for_demo_client():
    url = PRISM_BASE + "/employee/v1/getEmployee"
    assert check("prismhr", PRISM_BASE, PRISM, url, {"clientId": "100"}) == "employee/v1/getEmployee"


@pytest.mark.parametrize("url, params", [
    (PRISM_BASE + "/employee/v1/getEmployee", {"clientId": "999"}),
    (PRISM_BASE + "/employee/v1/getEmployee", {}),
    (PRISM_BASE + "/employee/v1/updateEmployeeFields", {"clientId": "100"}),
    (PRISM_BASE + "/clientMaster/v1/getClientList", {"clientId": "100"}),
    ("https://evil.example.test/api/services/rest/employee/v1/getEmployee", {"clientId": "100"}),
    (PRISM_BASE + "/employee/v1/getEmployee?clientId=100", {"clientId": "100"}),
])
def test_prism_refuses_out_of_scope_requests(url, params):
    with pytest.raises(ScopeError):
        check("prismhr", PRISM_BASE, PRISM, url, params)


def test_isolved_allows_demo_pair_and_global_lookups():
    url = ISOLVED_BASE + "/api/clients/7/legals/70/employees/5/directdeposits"
    assert check("isolved", ISOLVED_BASE, ISOLVED, url).endswith("/directdeposits")
    assert check("isolved", ISOLVED_BASE, ISOLVED, ISOLVED_BASE + "/api/lookup/Frequencies") == "api/lookup/Frequencies"
    assert check("isolved", ISOLVED_BASE, ISOLVED, ISOLVED_BASE + "/api/clients/7") == "api/clients/{client}"


@pytest.mark.parametrize("path", [
    "/api/clients/7/legals/71/employees",
    "/api/clients/8/legals/70/employees",
    "/api/clients/8",
    "/api/clients",
    "/api/legals",
    "/api/clients/7/legals/70/employees/../../71/employees",
    "/api/clients/7/legals/70/employees/5/directdeposits/9",
])
def test_isolved_refuses_other_companies_and_unlisted_paths(path):
    with pytest.raises(ScopeError):
        check("isolved", ISOLVED_BASE, ISOLVED, ISOLVED_BASE + path)


def test_ukg_allows_demo_company_only():
    url = UKG_BASE + "/rest/v2/companies/33/employees/1/pay-info"
    assert check("ukg-ready", UKG_BASE, UKG, url).endswith("/pay-info")
    with pytest.raises(ScopeError):
        check("ukg-ready", UKG_BASE, UKG, UKG_BASE + "/rest/v2/companies/34/employees")
    with pytest.raises(ScopeError):
        check("ukg-ready", UKG_BASE, UKG, "https://ukg.example.test/other/rest/v2/companies/33/employees")


def test_client_exposes_no_write_methods():
    for name in ("post", "put", "patch", "delete", "request"):
        assert not hasattr(live_client.ReadOnlyClient, name)


def test_prism_employer_details_only_for_referenced_employers():
    url = PRISM_BASE + "/system/v1/getEmployerDetails"
    referenced = frozenset({"5", "20"})
    assert check("prismhr", PRISM_BASE, PRISM, url, {"employerId": "5"}, referenced) == "system/v1/getEmployerDetails"
    for params, employers in (({"employerId": "7"}, referenced), ({}, referenced), ({"employerId": "5"}, frozenset())):
        with pytest.raises(ScopeError):
            check("prismhr", PRISM_BASE, PRISM, url, params, employers)
