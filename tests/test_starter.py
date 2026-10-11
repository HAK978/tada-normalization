"""Starter plumbing checks only. These do not assess transformation correctness."""
import contextlib
import io
import unittest

from normalization.__main__ import main
from normalization.adapters import ADAPTERS, ENTITIES
from normalization.references import all_readiness_issues, load_reference


class StarterChecks(unittest.TestCase):
    def test_expected_providers_and_entities_are_exposed(self):
        self.assertEqual(set(ADAPTERS), {"prismhr", "isolved", "ukg-ready"})
        self.assertEqual(set(ENTITIES), {"company", "employee", "payroll"})

    def test_reference_readiness_matches_distributed_materials(self):
        issues = all_readiness_issues()
        self.assertEqual(load_reference("prismhr")["lookup_status"], "verified")
        self.assertEqual(issues["prismhr"], [])
        for provider in ("isolved", "ukg-ready"):
            with self.subTest(provider=provider):
                ref = load_reference(provider)
                self.assertEqual(ref["lookup_status"], "verified")
                self.assertTrue(ref["lookups"])
                self.assertEqual(ref["distribution"]["status"], "user_approved_private_upload")
                self.assertFalse(ref["distribution"]["provider_redistribution_permission_verified"])
                self.assertTrue(issues[provider])

    def test_all_nine_transformations_are_explicitly_unimplemented(self):
        for provider, adapter in ADAPTERS.items():
            for entity in ENTITIES:
                with self.subTest(provider=provider, entity=entity):
                    with self.assertRaises(NotImplementedError):
                        adapter.normalize(entity, None, load_reference(provider))

    def test_readiness_command_exits_nonzero_for_missing_pack(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["check-inputs"]), 2)


if __name__ == "__main__":
    unittest.main()
