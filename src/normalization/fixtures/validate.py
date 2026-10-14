"""Validate generated responses against the provider's own published schema.

Known live key aliases are translated back to their documented names before validation, so
the contents are checked too, not just accepted as extra properties (A-43). contracts/ is
read, never modified.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft4Validator
from jsonschema.validators import validator_for
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4

ROOT = Path(__file__).resolve().parents[3]
SPECS = {
    "prismhr": ROOT / "contracts/prismhr/openapi/prismhr-2025.09.openapi.json",
    # The primary isolved snapshot only; the alternate is never mixed in.
    "isolved": ROOT / "contracts/isolved/openapi/isolved-v6.swagger.json",
    # Not OpenAPI: a list of {source_page, method, schema} blocks, one per documented operation.
    "ukg-ready": ROOT / "contracts/ukg-ready/reference-schemas.json",
}
# Documented live deviations that fixtures reproduce on purpose: (validator, field) pairs that are
# not reported (A-52, A-61). The field is the failing property's name, or for additionalProperties
# the unexpected property's name. Everything else is reported.
DEVIATIONS = {
    "isolved": {("maxLength", "maritalStatus")},
    "ukg-ready": {("additionalProperties", "ein_name"), ("minimum", "num_pp_in_year")},
}
# Live response keys that differ from the spec, per endpoint, translated back at any depth of the body for
# validation only (A-16, A-43, A-78).
ALIASES = {
    "prismhr": {
        "payroll/v1/getPayrollVoucherForBatch": {"payrollVoucher": "payrollVouchers"},
        "clientMaster/v1/getPayrollSchedule": {"clientPayrollSchedule": "clientPayrollSchedules"},
        "employee/v1/getEmployee": {"employerId": "employerIds"},
        "employee/v1/getHistory": {"historyRecord": "historyRecords"},
        "clientMaster/v1/getAllPrismClientContacts": {"prismClientContact": "prismClientContacts"},
    },
}


def aliases(provider: str, endpoint: str) -> dict[str, str]:
    return ALIASES.get(provider, {}).get(endpoint, {})


def _documented(value: Any, names: dict[str, str]) -> Any:
    """The body with every live alias renamed to its documented key, wherever it sits."""
    if isinstance(value, dict):
        return {
            (names[k] if k in names and names[k] not in value else k): _documented(v, names) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_documented(v, names) for v in value]
    return value


@lru_cache(maxsize=None)
def _registry(provider: str) -> tuple[dict, Registry]:
    document = json.loads(SPECS[provider].read_text(encoding="utf-8"))
    resource = Resource.from_contents(document, default_specification=DRAFT4)
    return document, Registry().with_resource(f"urn:{provider}", resource)


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.strip("/").lower())


@lru_cache(maxsize=None)
def _swagger_path(provider: str, endpoint: str) -> str:
    """Our endpoint templates name placeholders {client}/{legal}/{id}; the spec names them its own way."""
    document, _ = _registry(provider)
    matches = [path for path in document["paths"] if _shape(path) == _shape(endpoint)]
    if len(matches) != 1:
        raise KeyError(f"{endpoint}: {len(matches)} matching spec paths")
    return matches[0]


def _page_shape(page: str) -> str:
    """reference-docs/res/__v2__companies__(cid)__employees__(aid).html -> v2/companies/{}/employees/{}"""
    name = page.rsplit("/", 1)[-1].removesuffix(".html")
    return re.sub(r"\([^)]*\)", "{}", name.replace("__", "/")).strip("/").lower()


@lru_cache(maxsize=None)
def _ukg_schema(endpoint: str) -> int:
    """The index of the documented GET schema whose source page names the same path."""
    document, _ = _registry("ukg-ready")
    target = _shape(endpoint.removeprefix("rest/"))
    matches = [
        i
        for i, block in enumerate(document["schemas"])
        if block.get("method") == "GET" and _page_shape(block.get("source_page", "")) == target
    ]
    if len(matches) != 1:
        raise KeyError(f"{endpoint}: {len(matches)} matching documented schemas")
    return matches[0]


def response_pointer(provider: str, endpoint: str) -> str:
    if provider == "prismhr":
        return f"/paths/{_escape('/' + endpoint)}/get/responses/200/content/{_escape('application/json')}/schema"
    if provider == "isolved":
        return f"/paths/{_escape(_swagger_path(provider, endpoint))}/get/responses/200/schema"
    if provider == "ukg-ready":
        return f"/schemas/{_ukg_schema(endpoint)}/schema"
    raise ValueError(provider)


def _deviation(provider: str, error: Any) -> bool:
    allowed = DEVIATIONS.get(provider, set())
    if error.validator == "additionalProperties":
        names = re.findall(r"'([^']+)'", error.message.split("(", 1)[-1])
        return bool(names) and all(("additionalProperties", name) in allowed for name in names)
    field = str(error.absolute_path[-1]) if error.absolute_path else ""
    return (error.validator, field) in allowed


def _root(provider: str, endpoint: str) -> tuple[dict, dict]:
    """(the document $refs resolve against, the response schema). Each UKG block is its own JSON
    Schema document, with its own definitions and $schema version."""
    document, _ = _registry(provider)
    if provider == "ukg-ready":
        block = document["schemas"][_ukg_schema(endpoint)]["schema"]
        return block, block
    return document, _deref(document, {"$ref": "#" + response_pointer(provider, endpoint)})


def errors(provider: str, endpoint: str, body: Any, allow_null: bool = True) -> list[str]:
    """Schema violations for one 200 response body (empty list = valid).

    Live PrismHR sends null for many typed fields (422 of 428 live responses are valid once
    nulls are allowed, A-47), so null is accepted by default; nothing else is relaxed.
    """
    body = _documented(deepcopy(body), aliases(provider, endpoint))
    if provider == "ukg-ready":
        _, schema = _root(provider, endpoint)
        validator = validator_for(schema, default=Draft4Validator)(schema)
    else:
        _, registry = _registry(provider)
        validator = Draft4Validator(
            {"$ref": f"urn:{provider}#{response_pointer(provider, endpoint)}"}, registry=registry
        )
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in validator.iter_errors(body)
        if not (allow_null and e.validator == "type" and e.instance is None) and not _deviation(provider, e)
    ]


def _deref(document: dict, schema: dict) -> dict:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 50:
        node: Any = document
        for token in schema["$ref"].lstrip("#/").split("/"):
            node = node[token.replace("~1", "/").replace("~0", "~")]
        schema, seen = node, seen + 1
    return schema


def _complete(document: dict, schema: dict, value: Any, aliases: dict[str, str]) -> Any:
    schema = _deref(document, schema)
    for part in schema.get("allOf", []):
        value = _complete(document, part, value, aliases)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        present = {aliases.get(k, k) for k in value}
        for name in schema.get("required", []):
            if name not in present:
                value[name] = None
        for key, item in value.items():
            documented = aliases.get(key, key)
            if documented in properties and item is not None:
                value[key] = _complete(document, properties[documented], item, aliases)
    elif isinstance(value, list) and "items" in schema:
        value = [_complete(document, schema["items"], item, aliases) if item is not None else item for item in value]
    return value


def complete(provider: str, endpoint: str, body: Any) -> Any:
    """Add every required property the body doesn't set, as null: live PrismHR returns all fields,
    mostly empty or null (A-47). Live key aliases are completed against their documented schema."""
    document, schema = _root(provider, endpoint)
    return _complete(document, schema, deepcopy(body), aliases(provider, endpoint))
