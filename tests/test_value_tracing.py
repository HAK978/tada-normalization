"""Every value a converter reads reaches the output (A-62).

The coverage report calls a field mapped once a converter reads it, which doesn't prove its value reaches a
record: an audit found addresses whose fields were read and then thrown away. This test checks the outcome.
For each field the report calls mapped or kept, it puts a unique marker value into that field of the synthetic
scenario, normalizes, and requires the marker in the output: in a canonical field, a raw value,
provider_extensions or a diagnostic. A field where it may not appear needs a reviewed reason below.
"""

import copy
import re
from decimal import Decimal
from pathlib import Path

import pytest

from normalization.bundle import Bundle
from normalization.coverage import _main_status, measure
from normalization.providers import PROVIDERS, normalize
from normalization.sanitize import SENSITIVE_FIELDS

ROOT = Path(__file__).resolve().parents[1]
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

PATH_ID = "the record's own ID, also in the request path, which is the copy the record uses"
DETAIL = "a list row whose fetched detail replaces it; list-only rows are mapped from the list"
LETTERS = "a string of one-letter pay kinds: each letter is kept as the raw value of its own coded entry"

# (endpoint, field) where a marker may rightly not reach the output, with why.
EXEMPT: dict[str, dict[tuple[str, str], str]] = {
    "prismhr": {
        ("employee/v1/getEmployee", "employee[].directDeposit.voucherType"): LETTERS,
        ("employee/v1/getEmployee", "employee[].directDeposit.achVoucher[].voucherTypeOverride"): LETTERS,
    },
    "isolved": {
        ("api/clients/{client}", "id"): PATH_ID,
        ("api/clients/{client}/legals/{legal}/employees/{id}", "id"): PATH_ID,
        ("api/clients/{client}/legals/{legal}/employees/{id}/contacts", "[].birthDate"): (
            "a masked copy of birthDateUnmasked, dropped when that is sent (A-77)"
        ),
    },
    "ukg-ready": {
        ("rest/v2/companies/{company}/employees/{id}", "id"): PATH_ID,
        ("rest/v2/companies/{company}/employees/{id}/deductions/{id}", "id"): PATH_ID,
        ("rest/v2/companies/{company}/payrolls/{id}", "id"): PATH_ID,
        ("rest/v2/companies/{company}/payrolls/{id}/pay-statements/{id}", "id"): PATH_ID,
        ("rest/v2/companies/{company}/employees/{id}", "managers[].index"): "only orders the managers",
        ("rest/v2/companies/{company}/employees/{id}/deductions", "deductions[].deduction.code"): DETAIL,
        ("rest/v2/companies/{company}/employees/{id}/deductions", "deductions[].deduction.name"): DETAIL,
        ("rest/v2/companies/{company}/employees/{id}/deductions", "deductions[].effective_from"): DETAIL,
        ("rest/v2/companies/{company}/employees/{id}/deductions", "deductions[].effective_to"): DETAIL,
        ("rest/v2/companies/{company}/employees/{id}/deductions", "deductions[].sequence"): DETAIL,
    },
}


def _leaves(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _leaves(value, (*path, i))
    else:
        yield path, node


def _fold(path) -> str:
    return "".join("[]" if isinstance(p, int) else (f".{p}" if i else str(p)) for i, p in enumerate(path))


def _exact(path) -> str:
    return "".join(f"[{p}]" if isinstance(p, int) else (f".{p}" if i else str(p)) for i, p in enumerate(path))


def _marker(value, n: int):
    """A value of the same kind as the original, unlike anything in the scenarios: (value to plant, text to find)."""
    if isinstance(value, int):
        return 7193500 + n, str(7193500 + n)
    if isinstance(value, (float, Decimal)) or (isinstance(value, str) and NUMBER.fullmatch(value)):
        text = f"719{n:03d}.4381"
        return (text if isinstance(value, str) else float(text)), text
    if isinstance(value, str) and DATE.match(value):
        text = f"20{31 + n % 60}-0{1 + n % 9}-1{n % 9}"
        return text + value[10:], text
    return f"Kqv{n:04d}", f"Kqv{n:04d}"  # no mask characters (* X x #)


def traced_fields(provider: str):
    """Each mapped or kept field of the scenario, first occurrence only: (capture index, path, folded key)."""
    base = Bundle.load(ROOT / f"fixtures/{provider}/brightside")
    report = measure(base, "fixture")
    wanted = {key for key, counts in report.fields.items() if _main_status(counts) in ("mapped", "kept")}
    seen = set()
    for i, capture in enumerate(base.captures):
        if capture.status != 200:
            continue
        for path, value in _leaves(capture.body):
            key = (capture.endpoint, _fold(path))
            if key in seen or key not in wanted or value in (None, "") or isinstance(value, bool):
                continue
            if SENSITIVE_FIELDS.search(_exact(path)):
                continue  # masked to the last 4 by design (A-23)
            seen.add(key)
            yield i, path, key
    return base


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_value_a_converter_reads_reaches_the_output(provider):
    base = Bundle.load(ROOT / f"fixtures/{provider}/brightside")
    lost = []
    for n, (i, path, key) in enumerate(traced_fields(provider)):
        b = copy.deepcopy(base)
        node = b.captures[i].body
        for part in path[:-1]:
            node = node[part]
        planted, find = _marker(node[path[-1]], n)
        node[path[-1]] = planted
        if find not in normalize(b).to_json() and key not in EXEMPT[provider]:
            lost.append(key)
    assert not lost, f"read, but the value never reaches the output: {lost}"
    stale = [key for key in EXEMPT[provider] if key not in {k for _, _, k in traced_fields(provider)}]
    assert not stale, f"exemptions for fields no longer traced: {stale}"
