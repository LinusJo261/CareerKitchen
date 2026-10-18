"""Software contracts for an explicitly offline, unconfirmed text adapter."""

import math
import unittest

from scripts.matching_skill_proxy import SkillProxy, extraction_summary, score_skill_sets


class ProxyTests(unittest.TestCase):
    def test_official_aliases_resolve_concepts_without_substrings_or_skill_inference(self):
        proxy = SkillProxy(
            [
                {"id": "python", "preferred_label": "Python programming", "aliases": ["Python"]},
                {"id": "cpp", "preferred_label": "C++", "aliases": []},
                {"id": "csharp", "preferred_label": "C#", "aliases": []},
            ]
        )
        self.assertEqual(proxy.extract("PYTHON; C++; C#. Not pythonic or C."), {"python", "cpp", "csharp"})
        self.assertEqual(proxy.extract("Java experience"), set())

    def test_colliding_alias_is_excluded_instead_of_picking_an_arbitrary_concept(self):
        proxy = SkillProxy(
            [
                {"id": "one", "preferred_label": "first skill", "aliases": ["shared"]},
                {"id": "two", "preferred_label": "second skill", "aliases": ["shared"]},
            ]
        )
        self.assertEqual(proxy.extract("shared"), set())
        self.assertEqual(proxy.extract("first skill"), {"one"})
        self.assertEqual(proxy.provenance["ambiguous_alias_sequences_excluded"], 1)

    def test_native_core_matches_analytic_eligible_pair_formula(self):
        self.assertAlmostEqual(score_skill_sets(["a"], ["a", "b"]), math.sqrt(0.75))
        self.assertAlmostEqual(score_skill_sets([], ["a"]), math.sqrt(0.5))
        self.assertEqual(score_skill_sets([], []), 1.0)
        self.assertEqual(score_skill_sets(["a", "a"], ["a"]), 1.0)

    def test_vocabulary_order_does_not_change_extraction_or_fingerprint(self):
        concepts = [
            {"id": "x", "preferred_label": "skill one", "aliases": ["alias"]},
            {"id": "y", "preferred_label": "other", "aliases": []},
        ]
        left, right = SkillProxy(concepts), SkillProxy(reversed(concepts))
        self.assertEqual(left.provenance, right.provenance)
        self.assertEqual(left.extract("skill one and other"), right.extract("skill one and other"))

    def test_missing_inputs_are_counted_without_invented_preferences(self):
        self.assertEqual(
            extraction_summary([frozenset(), frozenset({"a", "b"})]),
            {"documents": 2, "documents_with_no_detected_concepts": 1, "mean_detected_concepts": 1.0},
        )


if __name__ == "__main__":
    unittest.main()
