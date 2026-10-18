"""Fictional fixtures verify offline feature calculations, not match quality."""

import unittest
from datetime import date, datetime

from scripts.mutual_matching_features import FEATURE_NAMES, build_features, validate_features


class MutualMatchingFeatureTests(unittest.TestCase):
    def build(self, **changes):
        arguments = {
            "confirmed_skills": ("python", "sql"),
            "required_skills": ("python", "sql", "java"),
            "preferred_skills": ("sql", "rust"),
            "relevant_experience_periods": ((date(2020, 1, 1), date(2022, 1, 1)),),
            "minimum_experience_years": 4,
            "as_of": date(2024, 1, 1),
            "preference_alignments": dict.fromkeys(FEATURE_NAMES[4:], 0.5),
        }
        arguments.update(changes)
        return build_features(**arguments)

    def test_builds_declared_features_with_separate_skill_coverages(self):
        features = self.build()
        self.assertEqual(tuple(features), FEATURE_NAMES)
        self.assertAlmostEqual(features["required_skill_coverage"], 2 / 3)
        self.assertEqual(features["preferred_skill_coverage"], 0.5)
        years = (date(2022, 1, 1) - date(2020, 1, 1)).days / 365.25
        self.assertAlmostEqual(features["relevant_experience_years"], years)
        self.assertAlmostEqual(features["experience_requirement_coverage"], years / 4)
        for name in FEATURE_NAMES[4:]:
            self.assertEqual(features[name], 0.5)

    def test_skills_normalize_case_whitespace_and_duplicate_requirements(self):
        result = self.build(
            confirmed_skills=("  PYTHON ", "machine   learning"),
            required_skills=("python", " Python ", "machine learning"),
            preferred_skills=(" ML ",),
        )
        self.assertEqual(result["required_skill_coverage"], 1)
        # Aliases are resolved by the caller's curated taxonomy, not guessed here.
        self.assertEqual(result["preferred_skill_coverage"], 0)

    def test_empty_or_unknown_requirements_are_not_penalized(self):
        for requirements in ((), None):
            result = self.build(required_skills=requirements, preferred_skills=requirements)
            self.assertIsNone(result["required_skill_coverage"])
            self.assertIsNone(result["preferred_skill_coverage"])

    def test_unknown_and_confirmed_empty_skills_are_distinct(self):
        for name in ("required_skill_coverage", "preferred_skill_coverage"):
            self.assertIsNone(self.build(confirmed_skills=None)[name])
            self.assertEqual(self.build(confirmed_skills=())[name], 0)

    def test_overlapping_duplicate_and_adjacent_jobs_do_not_double_count(self):
        periods = (
            (date(2021, 1, 1), date(2023, 1, 1)),
            (date(2020, 1, 1), date(2022, 1, 1)),
            (date(2021, 1, 1), date(2023, 1, 1)),
            (date(2023, 1, 1), date(2024, 1, 1)),
        )
        expected = (date(2024, 1, 1) - date(2020, 1, 1)).days / 365.25
        self.assertAlmostEqual(self.build(relevant_experience_periods=periods)[
            "relevant_experience_years"], expected)

    def test_disjoint_jobs_count_only_elapsed_work_periods(self):
        periods = (
            (date(2020, 1, 1), date(2021, 1, 1)),
            (date(2022, 1, 1), date(2023, 1, 1)),
        )
        expected = (366 + 365) / 365.25
        self.assertAlmostEqual(self.build(relevant_experience_periods=periods)[
            "relevant_experience_years"], expected)

    def test_ongoing_and_future_end_dates_clip_at_cutoff(self):
        for end in (None, date(2030, 1, 1)):
            result = self.build(relevant_experience_periods=((date(2022, 1, 1), end),))
            self.assertAlmostEqual(result["relevant_experience_years"], 730 / 365.25)

    def test_unknown_experience_is_not_zero_and_no_minimum_is_not_a_penalty(self):
        unknown = self.build(relevant_experience_periods=None)
        self.assertIsNone(unknown["relevant_experience_years"])
        self.assertIsNone(unknown["experience_requirement_coverage"])
        empty = self.build(relevant_experience_periods=())
        self.assertEqual(empty["relevant_experience_years"], 0)
        self.assertEqual(empty["experience_requirement_coverage"], 0)
        for minimum in (0, None):
            self.assertIsNone(self.build(minimum_experience_years=minimum)[
                "experience_requirement_coverage"])

    def test_experience_coverage_caps_at_one_without_clipping_years(self):
        result = self.build(minimum_experience_years=1)
        self.assertGreater(result["relevant_experience_years"], 1)
        self.assertEqual(result["experience_requirement_coverage"], 1)

    def test_invalid_experience_and_cutoffs_are_rejected(self):
        invalid_periods = [
            ((date(2025, 1, 1), None),),
            ((date(2021, 1, 1), date(2020, 1, 1)),),
            (("2020-01-01", None),),
            ((date(2020, 1, 1), datetime(2021, 1, 1)),),
            ((date(2020, 1, 1),),),
            [(date(2020, 1, 1), None)],
        ]
        for periods in invalid_periods:
            with self.subTest(periods=periods), self.assertRaises(ValueError):
                self.build(relevant_experience_periods=periods)
        for cutoff in ("2024-01-01", datetime(2024, 1, 1), None):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                self.build(as_of=cutoff)

    def test_invalid_minimum_experience_and_skills_are_rejected(self):
        for minimum in (-1, True, float("nan"), float("inf"), "2"):
            with self.subTest(minimum=minimum), self.assertRaises(ValueError):
                self.build(minimum_experience_years=minimum)
        for name in ("confirmed_skills", "required_skills", "preferred_skills"):
            for value in ("python", ["python"], ("  ",), (42,)):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.build(**{name: value})

    def test_missing_unknown_and_outcome_feature_names_are_rejected(self):
        values = dict.fromkeys(FEATURE_NAMES, None)
        missing = dict(values)
        del missing[FEATURE_NAMES[0]]
        for invalid in (missing, {**values, "candidate_interested": 1}, {}, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_features(invalid)
        for alignments in ({}, {**dict.fromkeys(FEATURE_NAMES[4:], None), "employer_interested": 1}):
            with self.subTest(alignments=alignments), self.assertRaises(ValueError):
                self.build(preference_alignments=alignments)

    def test_all_numeric_features_reject_nonfinite_negative_or_boolean_values(self):
        for name in FEATURE_NAMES:
            for value in (-0.1, True, False, float("nan"), float("inf"), "0.5"):
                values = dict.fromkeys(FEATURE_NAMES, None)
                values[name] = value
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    validate_features(values)
            if name != "relevant_experience_years":
                values = dict.fromkeys(FEATURE_NAMES, None)
                values[name] = 1.01
                with self.subTest(name=name), self.assertRaises(ValueError):
                    validate_features(values)

    def test_validated_features_normalize_numeric_values_without_mutating_inputs(self):
        original = dict.fromkeys(FEATURE_NAMES, 1)
        original["relevant_experience_years"] = 30
        original["candidate_schedule_preference_alignment"] = None
        copy = dict(original)
        normalized = validate_features(original)
        self.assertEqual(original, copy)
        self.assertEqual(normalized["relevant_experience_years"], 30.0)
        self.assertIsInstance(normalized["required_skill_coverage"], float)
        self.assertIsNone(normalized["candidate_schedule_preference_alignment"])


if __name__ == "__main__":
    unittest.main()
