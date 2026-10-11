"""Basic input readiness checks, not licensing or OpenAPI validation."""
import json
from pathlib import Path

from .adapters import ADAPTERS

ROOT = Path(__file__).resolve().parents[2]


def load_reference(provider, root=ROOT):
    path = root / "contracts" / provider / "lookup-reference.json"
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def readiness_issues(provider, root=ROOT):
    try:
        ref = load_reference(provider, root)
        if not isinstance(ref, dict):
            return ["Lookup reference must be a JSON object."]
        issues = []
        if ref.get("provider") != provider:
            issues.append("Reference provider identifier does not match the folder.")
        if ref.get("lookup_status") != "verified":
            issues.append("Lookup contents are a template or remain unverified.")
        if not isinstance(ref.get("lookups"), list):
            issues.append("Lookup domains must be an array.")
        if not ref.get("reference_version"):
            issues.append("Reference version is missing.")
        distribution = ref.get("distribution") or {}
        if distribution.get("status") != "verified" or not distribution.get("evidence_reference"):
            issues.append("Candidate-distribution permission has not been verified.")
        spec = ref.get("openapi") or {}
        if spec.get("status") != "verified":
            issues.append("OpenAPI artifact is absent or unverified.")
        relative = spec.get("relative_path")
        base = (root / "contracts" / provider / "openapi").resolve()
        if not isinstance(relative, str) or not relative:
            issues.append("Approved OpenAPI filename is missing.")
        else:
            path = (base / relative).resolve()
            if base not in path.parents or path.suffix.lower() not in (".json", ".yaml", ".yml") or not path.is_file():
                issues.append("Approved OpenAPI file must exist inside the provider openapi directory.")
        if not all(spec.get(key) for key in ("version", "source", "sha256")):
            issues.append("OpenAPI provenance/version/checksum metadata is incomplete.")
        return issues
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return ["Cannot read reference metadata: " + str(exc)]


def all_readiness_issues(root=ROOT):
    return {provider: readiness_issues(provider, root) for provider in ADAPTERS}
