"""The organizer's lookup references agree with the code tables (A-85).

contracts/<provider>/lookup-reference.json lists code domains with their cited meanings. Where a domain names
a field a converter maps, every documented code must have a canonical mapping, and nothing else may be
mapped. A change on either side fails here.
"""

import json
from pathlib import Path

import pytest

from normalization.providers.prismhr import codes as P
from normalization.providers.ukg_ready import codes as U

ROOT = Path(__file__).resolve().parents[1]


def domains(provider: str) -> dict[str, list[dict]]:
    reference = json.loads((ROOT / "contracts" / provider / "lookup-reference.json").read_text(encoding="utf-8"))
    return {lookup["domain"]: lookup["entries"] for lookup in reference["lookups"]}


@pytest.mark.parametrize(
    ("domain", "table"),
    [
        ("client_status_class", P.COMPANY_STATUS),
        ("client_service_type", P.SERVICE_TYPE),
        ("user_employee_status_class", P.STATUS_CLASS),
        ("deduction_type", P.DEDUCTION_TYPE),
    ],
)
def test_prismhr_tables_map_exactly_the_documented_codes(domain, table):
    assert set(table) == {entry["code"] for entry in domains("prismhr")[domain]}


def test_ukg_documents_no_meaning_for_its_codes():
    # The premise of A-26 and A-79: UKG names its enum values without defining them.
    meanings = {str(entry.get("meaning")) for entries in domains("ukg-ready").values() for entry in entries}
    assert meanings == {"None"}


def test_ukg_tables_map_only_documented_codes():
    ukg = domains("ukg-ready")

    def documented(suffix: str) -> set[str]:
        return {entry["code"] for name, entries in ukg.items() if name.endswith(suffix) for entry in entries}

    assert set(U.NATIONAL_ID_TYPE) <= documented("/properties/national_id_numbers/items/properties/type")
    assert set(U.RUN_STATUS) <= documented("__payrolls__(id).html:/properties/status")
