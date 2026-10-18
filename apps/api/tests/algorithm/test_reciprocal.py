import unittest
from dataclasses import replace

from app.matching.attention import MarketPrices
from app.matching.reciprocal import ReciprocalFeatures, score_reciprocal, skill_coverage


class ReciprocalTests(unittest.TestCase):
    def setUp(self):
        self.features = ReciprocalFeatures("c", "v", 1, 1, "2026-10-17T00:00:00+00:00", 1, 1, 1, 1, True)

    def test_taxonomy_aliases_case_and_duplicate_requirements(self):
        self.assertEqual(skill_coverage((("JavaScript", ("JS",)),), (" js ", "JS", "Python")), 0.5)

    def test_unspecified_preferences_are_not_a_mismatch(self):
        self.assertIsNone(skill_coverage((), ()))
        result = score_reciprocal(replace(self.features, employer_skills=None), MarketPrices())
        self.assertEqual(result["employer_fit"], 1)

    def test_unknown_skill_does_not_disappear(self):
        self.assertEqual(skill_coverage((), ("communication",)), 0)

    def test_both_sides_affect_relevance(self):
        full = score_reciprocal(self.features, MarketPrices())
        lower = score_reciprocal(replace(self.features, candidate_role=0), MarketPrices())
        self.assertLess(lower["relevance"], full["relevance"])

    def test_direction_accounts_for_congestion(self):
        result = score_reciprocal(self.features, MarketPrices(job_congestion=0.4))
        self.assertEqual(result["first_mover"], "EMPLOYER")
        self.assertEqual(result["estimate_kind"], "NONPROBABILISTIC")

    def test_ineligible_pair_cannot_be_scored(self):
        with self.assertRaises(ValueError):
            score_reciprocal(replace(self.features, eligible=False), MarketPrices())

    def test_snapshot_is_versioned_and_replayable(self):
        result = score_reciprocal(self.features, MarketPrices())
        self.assertEqual(result, score_reciprocal(self.features, MarketPrices()))
        changed = score_reciprocal(replace(self.features, candidate_version=2), MarketPrices())
        self.assertNotEqual(result["feature_hash"], changed["feature_hash"])


if __name__ == "__main__":
    unittest.main()
