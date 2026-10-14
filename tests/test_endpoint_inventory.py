"""Every read endpoint the providers document has a decision: fetched, or why not (A-74).

The tool once fetched only the endpoints its plan named, and nothing checked the rest of the specs: a
whole endpoint of employee data could be left out without any test noticing. These tests read the specs
in contracts/ and fail when a documented read endpoint in the five data types has no decision.
"""

from collections import Counter

import pytest

from normalization.live import endpoints as E

# Read (GET) operations each spec documents; the specs are hash-checked, so these don't drift.
DOCUMENTED = {"prismhr": 253, "isolved": 302, "ukg-ready": 300}


@pytest.mark.parametrize("provider", E.PROVIDERS)
def test_every_documented_read_endpoint_has_a_decision(provider):
    entries = E.inventory(provider)
    assert len(entries) == DOCUMENTED[provider]
    undecided = [e.path for e in entries if e.disposition == E.UNDECIDED]
    assert not undecided, f"read endpoints with no decision: {undecided}"


@pytest.mark.parametrize("provider", E.PROVIDERS)
def test_every_fetched_endpoint_is_documented_once(provider):
    shapes = Counter(E._shape(e.path) for e in E.inventory(provider))
    assert {shape: shapes[shape] for shape in E.fetched(provider)} == {shape: 1 for shape in E.fetched(provider)}


def test_every_recorded_decision_is_for_a_documented_endpoint_that_isnt_fetched():
    documented = {(p, e.path): e for p in E.PROVIDERS for e in E.inventory(p)}
    stale = [key for key in E.DECISIONS if key not in documented]
    assert not stale, f"decisions for endpoints the specs don't document: {stale}"
    overruled = [key for key in E.DECISIONS if documented[key].disposition == E.FETCHED]
    assert not overruled, f"decisions for endpoints that are fetched: {overruled}"


def test_decisions_use_the_known_reasons():
    known = {E.SAME, E.WORKFLOW, E.CONFIG, E.UNREACHABLE, E.EMPTY_LIVE, E.REFUSED_LIVE, E.OUT}
    assert {disposition for disposition, _ in E.DECISIONS.values()} <= known
    assert all(reason.strip() for _, reason in E.DECISIONS.values())
