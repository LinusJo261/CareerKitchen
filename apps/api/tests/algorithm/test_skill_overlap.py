"""Confirmed-concept overlap features, never inferred resume qualifications."""

import unittest
from dataclasses import replace

from app.matching.reciprocal import ReciprocalFeatures, skill_overlap


class SkillOverlapTests(unittest.TestCase):
    def test_precision_retains_extra_confirmed_skills_and_unmatched_preferences(self):
        self.assertEqual(skill_overlap((("Python", ()), ("SQL", ())), ("Python", "Rust")), (0.5, 1 / 3))

    def test_synonyms_and_duplicate_concepts_count_once(self):
        skills = (("JavaScript", ("JS",)), (" javascript ", ("ECMAScript",)))
        self.assertEqual(skill_overlap(skills, ("JS", "JavaScript", "ecmascript")), (1, 1))

    def test_ambiguous_alias_never_asserts_multiple_skills(self):
        skills = (("first", ("shared",)), ("second", ("shared",)))
        self.assertEqual(skill_overlap(skills, ("shared",)), (0, 0))

    def test_canonical_preference_takes_precedence_over_another_concepts_alias(self):
        skills = (("Python", ()), ("Other", ("Python",)))
        self.assertEqual(skill_overlap(skills, ("Python",)), (0.5, 0.5))

    def test_missing_preferences_are_not_applicable_and_missing_skills_do_not_match(self):
        self.assertEqual(skill_overlap((("Python", ()),), ()), (None, None))
        self.assertEqual(skill_overlap((), ("Python",)), (0, 0))

    def test_feature_extension_is_optional_and_bounded(self):
        features = ReciprocalFeatures("c", "v", 1, 1, "2026-10-18T00:00:00Z", 0.5, 1, 1, 1, True)
        self.assertIsNone(features.text_relevance)
        for name in ("skill_precision", "skill_jaccard", "text_relevance"):
            for bad in (True, float("nan"), -0.1, 1.1, "0.5"):
                with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                    replace(features, **{name: bad})
            extra = {"text_relevance_model_id": "a" * 64} if name == "text_relevance" else {}
            self.assertEqual(getattr(replace(features, **{name: 0.25}, **extra), name), 0.25)

    def test_text_relevance_requires_immutable_extractor_identity(self):
        features = ReciprocalFeatures("c", "v", 1, 1, "2026-10-18T00:00:00Z", 0.5, 1, 1, 1, True)
        for changes in (
            {"text_relevance": 0.5},
            {"text_relevance_model_id": "a" * 64},
            {"text_relevance": 0.5, "text_relevance_model_id": "invalid"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(features, **changes)
