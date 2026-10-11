"""Distributed reference integrity only; no candidate transformations are assessed."""
import hashlib
import json
import unittest
from urllib.parse import unquote

from normalization.references import ROOT, load_reference


def resolve_pointer(document, pointer):
    """Resolve a local JSON Pointer, including escaped keys and array indices."""
    pointer = unquote(pointer[1:] if pointer.startswith("#") else pointer)
    if not pointer:
        return document
    if not pointer.startswith("/"):
        raise ValueError("Expected a local JSON Pointer")
    node = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def walk(node):
    yield node
    if isinstance(node, dict):
        for child in node.values():
            yield from walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


class ReferenceIntegrityChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = load_reference("prismhr")
        cls.base = ROOT / "contracts" / "prismhr"
        cls.path = cls.base / "openapi" / cls.reference["openapi"]["relative_path"]
        cls.payload = cls.path.read_bytes()
        cls.document = json.loads(cls.payload)

    def test_distributed_contract_matches_recorded_checksum_and_license(self):
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(),
                         self.reference["openapi"]["sha256"])
        self.assertEqual(self.document["info"]["version"],
                         self.reference["openapi"]["version"])
        self.assertEqual(self.document["info"]["license"]["name"], "Apache 2.0 License")
        license_text = (self.base / self.reference["distribution"]["license_file"]).read_text()
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertTrue((self.base / "NOTICE.md").is_file())

    def test_internal_schema_references_resolve_and_documented_examples_are_included(self):
        example_count = 0
        for node in walk(self.document):
            if isinstance(node, dict):
                example_count += sum(key in node for key in ("example", "examples"))
                if "$ref" in node:
                    with self.subTest(reference=node["$ref"]):
                        self.assertTrue(node["$ref"].startswith("#/"))
                        resolve_pointer(self.document, node["$ref"])
        self.assertEqual(example_count, 340)
        self.assertTrue(self.document["x-tada-hiring-derivative"]["documented_examples_included"])

    def test_lookup_citations_match_the_distributed_source_descriptions(self):
        for domain in self.reference["lookups"]:
            self.assertTrue(domain["completeness"])
            for pointer in domain["source_field_pointers"]:
                resolve_pointer(self.document, pointer)
            for entry in domain["entries"]:
                with self.subTest(domain=domain["domain"], code=entry["code"]):
                    relative, pointer = entry["evidence_reference"].split("#", 1)
                    self.assertEqual((self.base / relative).resolve(), self.path.resolve())
                    description = resolve_pointer(self.document, pointer)
                    self.assertEqual(description, domain["source_description"])
                    self.assertIsInstance(entry["code"], str)
                    self.assertTrue(entry["meaning"])


class PrivateUploadIntegrityChecks(unittest.TestCase):
    def test_private_uploaded_files_match_manifests(self):
        for provider in ("isolved", "ukg-ready"):
            base = ROOT / "contracts" / provider
            manifest = json.loads((base / "SOURCE_MANIFEST.json").read_text())
            self.assertFalse(manifest["distribution"]["candidate_sharing_approved"])
            for artifact in manifest["artifacts"]:
                with self.subTest(provider=provider, file=artifact["file"]):
                    path = (base / artifact["file"]).resolve()
                    self.assertIn(base.resolve(), path.parents)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                     artifact["sha256"])
            if provider == "ukg-ready":
                self.assertEqual(hashlib.sha256((base / "reference-schemas.json").read_bytes()).hexdigest(),
                                 manifest["reference_schemas_sha256"])

    def test_private_lookup_entries_are_exact_cited_values(self):
        for provider in ("isolved", "ukg-ready"):
            base = ROOT / "contracts" / provider
            cache = {}
            for domain in load_reference(provider)["lookups"]:
                for entry in domain["entries"]:
                    relative, pointer = entry["evidence_reference"].split("#", 1)
                    if relative not in cache:
                        cache[relative] = json.loads((base / relative).read_text())
                    with self.subTest(provider=provider, domain=domain["domain"], code=entry["code"]):
                        self.assertEqual(entry["code"], resolve_pointer(cache[relative], pointer))
                        self.assertIsNone(entry["meaning"])
                        self.assertTrue(entry["meaning_status"])

    def test_private_schema_contracts_preserve_format_boundaries(self):
        base = ROOT / "contracts" / "isolved"
        manifest = json.loads((base / "SOURCE_MANIFEST.json").read_text())
        for artifact in manifest["artifacts"]:
            document = json.loads((base / artifact["file"]).read_text())
            self.assertEqual(document["swagger"], "2.0")
            self.assertTrue(document["x-tada-hiring-derivative"]["documented_examples_included"])
            for node in walk(document):
                if isinstance(node, dict):
                    if "$ref" in node:
                        self.assertTrue(node["$ref"].startswith("#/"))
                        resolve_pointer(document, node["$ref"])
        base = ROOT / "contracts" / "ukg-ready"
        document = json.loads((base / "reference-schemas.json").read_text())
        self.assertNotIn("openapi", document)
        self.assertNotIn("swagger", document)
        self.assertIn("NOT Swagger/OpenAPI", document["artifact_kind"])
        self.assertTrue(document["schemas"])
        self.assertTrue(document["documented_examples_included"])
        example_count = 0
        for record in document["schemas"]:
            page = base / record["source_page"]
            self.assertTrue(page.is_file())
            self.assertIn('id="' + record["source_schema_anchor"] + '"', page.read_text())
            for node in walk(record["schema"]):
                if isinstance(node, dict):
                    example_count += sum(key in node for key in ("example", "examples", "x-example"))
        self.assertEqual(example_count, 101)


if __name__ == "__main__":
    unittest.main()
