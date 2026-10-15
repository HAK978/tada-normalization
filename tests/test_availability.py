"""Unavailable is not empty (A-70): a request that returned no data is either an answer ("nothing
found", documented or stated by the provider) or a gap, reported on the records it would have fed."""

from pathlib import Path

from normalization.bundle import Bundle, Capture
from normalization.providers import normalize

ROOT = Path(__file__).resolve().parents[1]


def bundle(provider: str) -> Bundle:
    return Bundle.load(ROOT / f"fixtures/{provider}/brightside")


def unavailable(record):
    return {(d.field, d.raw) for d in record.diagnostics if d.code == "SOURCE_UNAVAILABLE"}


def one(out, kind, suffix):
    return next(r for r in out.records[kind] if r.id.endswith(suffix))


def test_an_endpoint_the_tenant_lacks_is_reported_on_each_employee_it_would_have_fed():
    out = normalize(bundle("ukg-ready"))
    deductions = "rest/v2/companies/{company}/employees/{id}/deductions"
    for aid in ("5002", "5003", "5004", "5005"):  # their deduction setup answers 404 "Unresolvable URL"
        employee = one(out, "employees", f":{aid}")
        assert unavailable(employee) == {(deductions, "404")}
        assert not [e for e in out.records["deduction_elections"] if e.employee_id == employee.id]
    assert not unavailable(one(out, "employees", ":5001"))  # fetched: its elections are real
    assert {"endpoint": deductions, "status": "HTTP 404", "requests": 4, "unattributed": 0} in out.summary()[
        "unavailable"
    ]


def test_a_cost_center_tree_said_to_be_unused_is_unavailable_not_empty():
    # Live, tree 1 answers 400 "Cost Center not used." while 8 employees are assigned cost centers in it, so
    # the answer can't be taken as an empty tree (A-75).
    out = normalize(bundle("ukg-ready"))
    cost_centers = "rest/v2/companies/{company}/config/cost-centers"
    assert (cost_centers, "400") in unavailable(one(out, "companies", ":7001"))
    assert out.summary()["requests"]["empty"] == 0


def test_a_404_the_provider_documents_as_nothing_found_is_an_empty_answer():
    out = normalize(bundle("isolved"))
    requests = out.summary()["requests"]
    # e.g. "No employee direct deposits found.", "No contacts found", "No Employee jobs found."
    assert (requests["empty"], requests["unavailable"]) == (12, 0)
    assert not any(unavailable(r) for records in out.records.values() for r in records)


def test_prism_saying_no_batches_is_an_answer_and_a_server_error_is_not():
    b = bundle("prismhr")
    batches = "payroll/v1/getBatchListByDate"
    params = {"clientId": "201", "dateType": "PAY", "startDate": "2027-01-01", "endDate": "2027-12-31"}
    b.captures += [
        Capture(batches, batches, params, 404, {"errorCode": "404", "errorMessage": "No batches could be found"}, "x1"),
        Capture(batches, batches, params, 500, {"errorCode": "500", "errorMessage": "internal server error"}, "x2"),
    ]
    out = normalize(b)
    assert unavailable(one(out, "companies", ":201")) >= {(batches, "500")}
    assert (batches, "404") not in unavailable(one(out, "companies", ":201"))
    assert {"endpoint": batches, "status": "HTTP 500", "requests": 1, "unattributed": 0} in out.summary()["unavailable"]


def test_a_prism_error_inside_http_200_counts_as_unavailable():
    b = bundle("prismhr")
    loans = next(c for c in b.captures if c.endpoint == "deductions/v1/getEmployeeLoans")
    loans.body = {"errorCode": "5", "errorMessage": "this user session has expired"}
    out = normalize(b)
    employee = loans.params["employeeId"]
    assert ("deductions/v1/getEmployeeLoans", "5") in unavailable(one(out, "employees", f":201:{employee}"))


def test_a_failure_for_an_employee_not_in_the_output_falls_back_to_the_company():
    b = bundle("ukg-ready")
    path = "rest/v2/companies/7001/employees/9999/pay-info"
    b.captures.append(Capture("rest/v2/companies/{company}/employees/{id}/pay-info", path, {}, 503, None, "x"))
    out = normalize(b)
    assert ("rest/v2/companies/{company}/employees/{id}/pay-info", "503") in unavailable(one(out, "companies", ":7001"))


def test_a_failure_that_belongs_to_no_record_is_still_counted():
    b = bundle("isolved")
    b.captures.append(Capture("api/lookup/genders", "api/lookup/genders", {}, 500, {"message": "boom"}, "x"))
    out = normalize(b)
    assert {"endpoint": "api/lookup/genders", "status": "HTTP 500", "requests": 1, "unattributed": 1} in out.summary()[
        "unavailable"
    ]
