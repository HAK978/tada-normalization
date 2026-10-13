"""JSON Schema export of the canonical model: one file per record type (model §1).

The schemas describe the serialized form, exactly what the JSON output and the SQLite `record`
column hold: decimals as strings, dates as ISO strings, unset optional fields left out.
"""

from __future__ import annotations

import json
from pathlib import Path

from .records import RECORD_TYPES

DIALECT = "https://json-schema.org/draft/2020-12/schema"


def schemas() -> dict[str, dict]:
    return {
        kind: {"$schema": DIALECT, **model.model_json_schema(mode="serialization")}
        for kind, model in RECORD_TYPES.items()
    }


def write_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, schema in schemas().items():
        path = directory / f"{kind}.schema.json"
        path.write_text(json.dumps(schema, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written
