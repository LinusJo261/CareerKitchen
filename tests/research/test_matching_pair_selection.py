"""Fictional examples check efficient pair construction, not hiring outcomes."""

import hashlib
import json
import unittest
from unittest.mock import patch

import numpy as np

from scripts.matching_research_core import (
    FEATURE_NAMES,
    PreparedCorpus,
    feature_matrix,
    required_coverage,
    sample_training_indices,
)


def _resume(resume_id, skills, **updates):
    return {
        "resume_id": resume_id,
        "skills": skills,
        "role": "Engineer",
        "seniority": "Mid",
        "summary": "build systems",
        "experience_bullets": ["deliver software"],
        **updates,
    }


def _job(**updates):
    return {
        "job_id": "J_pair_fixture",
        "job_title": "Engineer",
        "seniority": "Mid",
        "must_have_skills": ["Python", "SQL", "Git"],
        "nice_to_have_skills": ["Docker"],
        "description": "build software",
        "responsibilities": ["deliver systems"],
        **updates,
    }


class PairConstructionTests(unittest.TestCase):
    def setUp(self):
        self.corpus = PreparedCorpus(
            [
                _resume("A_positive", ["Python", "SQL", "Git", "Docker"]),
                _resume("B_positive", ["Python", "SQL"], seniority="Senior"),
                _resume("C_unlisted_qualified", ["Python", "SQL"]),
                _resume("D_negative", ["Python"]),
                _resume("E_negative", ["JavaScript"]),
                _resume("F_positive", ["Python", "SQL", "Git"]),
            ]
        )
        self.positives = {"A_positive", "B_positive", "F_positive"}

    def test_required_coverage_equals_full_column_with_normalization_and_duplicates(self):
        for job in (
            _job(),
            _job(must_have_skills=["  PYTHON ", "sql", "GIT", "python"]),
            _job(must_have_skills=[]),
        ):
            with self.subTest(required=job["must_have_skills"]):
                np.testing.assert_array_equal(
                    required_coverage(job, self.corpus), feature_matrix(job, self.corpus)[:, 0]
                )

    def test_required_coverage_ignores_preferred_skills_and_prose(self):
        job = _job(nice_to_have_skills=object(), description=object(), responsibilities=object())
        np.testing.assert_array_equal(required_coverage(job, self.corpus), [1, 2 / 3, 2 / 3, 1 / 3, 0, 1])

    def test_required_coverage_handles_empty_corpus_and_rejects_invalid_skills(self):
        empty = PreparedCorpus([])
        for job in (_job(), _job(must_have_skills=[])):
            self.assertEqual(required_coverage(job, empty).shape, (0,))
        with self.assertRaises(ValueError):
            required_coverage(_job(must_have_skills=[None]), self.corpus)

    def test_selected_features_equal_full_matrix_including_repeated_order(self):
        indices = np.asarray([5, 0, 3, 0, 1], dtype=np.int64)
        for job in (_job(), _job(must_have_skills=[], nice_to_have_skills=[])):
            with self.subTest(required=job["must_have_skills"]):
                np.testing.assert_array_equal(
                    feature_matrix(job, self.corpus, indices), feature_matrix(job, self.corpus)[indices]
                )
        np.testing.assert_array_equal(indices, [5, 0, 3, 0, 1])

    def test_subset_does_not_read_unsampled_text(self):
        expected = feature_matrix(_job(), self.corpus, np.asarray([0, 5], dtype=int))
        self.corpus._text_sets[1] = object()
        np.testing.assert_array_equal(
            feature_matrix(_job(), self.corpus, np.asarray([0, 5], dtype=int)), expected
        )

    def test_empty_and_unsigned_subsets(self):
        empty = feature_matrix(_job(), self.corpus, np.asarray([], dtype=int))
        self.assertEqual(empty.shape, (0, len(FEATURE_NAMES)))
        self.assertEqual(feature_matrix(_job(), PreparedCorpus([])).shape, empty.shape)
        indices = np.asarray([2, 0], dtype=np.uint64)
        np.testing.assert_array_equal(
            feature_matrix(_job(), self.corpus, indices), feature_matrix(_job(), self.corpus)[[2, 0]]
        )

    def test_invalid_subset_indices_are_rejected(self):
        invalid = (
            np.asarray([True, False]),
            np.asarray([0.0, 1.0]),
            np.asarray([np.nan]),
            np.asarray([np.inf]),
            np.asarray([0, True], dtype=object),
            np.asarray([[0, 1]]),
            np.asarray(0),
            np.asarray([-1]),
            np.asarray([len(self.corpus.ids)]),
            np.asarray([2**64 - 1], dtype=np.uint64),
            [0, 1],
        )
        for indices in invalid:
            with self.subTest(indices=repr(indices)), self.assertRaises(ValueError):
                feature_matrix(_job(), self.corpus, indices)

    def test_sampling_preserves_original_rng_and_label_alignment(self):
        # Reproduce the original helper's sampling after extracting column zero
        # from all five features; the optimized path must select identical pairs.
        job = _job()
        coverage = feature_matrix(job, self.corpus)[:, 0]
        positives = np.asarray(
            [index for index, resume_id in enumerate(self.corpus.ids) if resume_id in self.positives]
        )
        negatives = np.flatnonzero(coverage < 0.6)
        digest = hashlib.sha256(
            json.dumps([42, job["job_id"]], sort_keys=True, separators=(",", ":")).encode()
        ).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        expected_indices = np.concatenate(
            (rng.choice(positives, size=2, replace=False), rng.choice(negatives, size=2, replace=False))
        )
        expected_labels = np.asarray([1.0, 1.0, 0.0, 0.0])
        permutation = rng.permutation(4)
        indices, labels = sample_training_indices(job, self.corpus, self.positives, 42, per_class=2)
        np.testing.assert_array_equal(indices, expected_indices[permutation])
        np.testing.assert_array_equal(labels, expected_labels[permutation])
        np.testing.assert_array_equal(indices, [3, 5, 4, 0])
        np.testing.assert_array_equal(labels, [0, 1, 0, 1])
        for index, label in zip(indices, labels, strict=True):
            self.assertEqual(label, float(self.corpus.ids[index] in self.positives))
        self.assertNotIn(self.corpus.ids.index("C_unlisted_qualified"), indices)

    def test_sampling_uses_no_full_feature_matrix(self):
        with patch("scripts.matching_research_core.feature_matrix", side_effect=AssertionError):
            indices, labels = sample_training_indices(_job(), self.corpus, self.positives, 42)
        self.assertEqual(len(indices), 4)
        self.assertEqual(int(labels.sum()), 2)


if __name__ == "__main__":
    unittest.main()
