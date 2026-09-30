"""Unit tests for SkillsReconciliationAdapter."""

import os
import unittest
from adapter.skills_adapter import SkillsReconciliationAdapter


class TestSkillsReconciliationAdapter(unittest.TestCase):

    def setUp(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tax_path = os.path.join(base_dir, "skills_taxonomy.json")
        rules_path = os.path.join(base_dir, "skills_mapping_rules.json")
        self.adapter = SkillsReconciliationAdapter(tax_path, rules_path)

    def test_exact_canonical_match(self):
        res = self.adapter.reconcile_skill("PostgreSQL")
        self.assertEqual(res["status"], "RESOLVED")
        self.assertEqual(res["match_type"], "EXACT")
        self.assertEqual(res["canonical_code"], "SKILL_POSTGRESQL")
        self.assertEqual(res["confidence"], 1.0)

    def test_alias_match(self):
        cases = [
            ("postgres", "SKILL_POSTGRESQL"),
            ("psql", "SKILL_POSTGRESQL"),
            ("постгрес", "SKILL_POSTGRESQL"),
            ("k8s", "SKILL_KUBERNETES"),
            ("кубернетес", "SKILL_KUBERNETES"),
            ("golang", "SKILL_GOLANG"),
            ("джава", "SKILL_JAVA"),
            ("ts", "SKILL_TYPESCRIPT"),
            ("js", "SKILL_JAVASCRIPT"),
            ("ci/cd", "SKILL_CICD"),
        ]
        for raw, expected_code in cases:
            with self.subTest(raw=raw):
                res = self.adapter.reconcile_skill(raw)
                self.assertEqual(res["status"], "RESOLVED")
                self.assertEqual(res["canonical_code"], expected_code)

    def test_protected_tokens_preservation(self):
        # Protected tokens like C++, C#, .NET should not lose their punctuation or be split
        protected = ["C++", "c++", "C#", ".NET", "Node.js", "Vue.js", "CI/CD"]
        for p in protected:
            tokens = self.adapter.split_composite_skills(p)
            self.assertEqual(len(tokens), 1, f"Expected 1 token for {p}, got {tokens}")
            self.assertEqual(tokens[0].lower(), p.lower())

    def test_composite_skill_splitting(self):
        composite = "React / Redux / TypeScript"
        tokens = self.adapter.split_composite_skills(composite)
        self.assertEqual(tokens, ["React", "Redux", "TypeScript"])

        reconciled = self.adapter.reconcile_all([composite])
        self.assertEqual(len(reconciled), 3)
        self.assertEqual(reconciled[0]["canonical_code"], "SKILL_REACT")
        self.assertEqual(reconciled[1]["canonical_code"], "SKILL_REDUX")
        self.assertEqual(reconciled[2]["canonical_code"], "SKILL_TYPESCRIPT")

    def test_composite_with_protected_tokens(self):
        composite = "Docker, Kubernetes, C++, CI/CD, Helm"
        tokens = self.adapter.split_composite_skills(composite)
        self.assertIn("c++", [t.lower() for t in tokens])
        self.assertIn("ci/cd", [t.lower() for t in tokens])

    def test_version_stripping(self):
        cases = [
            ("Java 17", "SKILL_JAVA"),
            ("Python 3.11", "SKILL_PYTHON"),
            ("Vue 3", "SKILL_VUEJS"),
        ]
        for raw, expected_code in cases:
            with self.subTest(raw=raw):
                res = self.adapter.reconcile_skill(raw)
                self.assertEqual(res["canonical_code"], expected_code)

    def test_unmapped_enqueue_and_resolve(self):
        unknown_skill = "QuantumHaskellCloud"
        res = self.adapter.reconcile_skill(unknown_skill, source="HH_RU", sample_context="Lead Scientist")
        self.assertEqual(res["status"], "UNMAPPED")
        self.assertIsNotNone(res["unmapped_id"])

        unmapped_list = self.adapter.get_unmapped_queue()
        self.assertEqual(len(unmapped_list), 1)
        self.assertEqual(unmapped_list[0]["raw_value"], unknown_skill)
        self.assertEqual(unmapped_list[0]["occurrence_count"], 1)

        # Re-encountering increments occurrence count
        res2 = self.adapter.reconcile_skill(unknown_skill, source="HH_RU")
        unmapped_list2 = self.adapter.get_unmapped_queue()
        self.assertEqual(unmapped_list2[0]["occurrence_count"], 2)

        # 1-Click resolve via Generic MDM Hub
        unmapped_id = unmapped_list[0]["id"]
        resolve_res = self.adapter.resolve_unmapped(unmapped_id, "SKILL_RUST", create_alias=True)
        self.assertEqual(resolve_res["status"], "SUCCESS")

        # Now subsequent reconcile should resolve immediately via the newly registered alias
        res3 = self.adapter.reconcile_skill(unknown_skill)
        self.assertEqual(res3["status"], "RESOLVED")
        self.assertEqual(res3["canonical_code"], "SKILL_RUST")

    def test_canonical_dictionary_filtering(self):
        all_dbs = self.adapter.get_canonical_dictionary(category="DATABASE")
        self.assertTrue(len(all_dbs) >= 5)
        codes = [d["code"] for d in all_dbs]
        self.assertIn("SKILL_POSTGRESQL", codes)
        self.assertIn("SKILL_REDIS", codes)

        search_res = self.adapter.get_canonical_dictionary(search="spark")
        self.assertTrue(len(search_res) >= 1)
        self.assertEqual(search_res[0]["code"], "SKILL_APACHE_SPARK")


if __name__ == "__main__":
    unittest.main()
