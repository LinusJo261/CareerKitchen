"""Fictional fixtures validate offline research behavior, not hiring quality."""

import json
import unittest

import numpy as np

from scripts.matching_research_core import (
    FEATURE_NAMES,
    LogisticModel,
    PreparedCorpus,
    feature_matrix,
    fit_logistic,
    normalize_generator_skill,
    ranking_metrics,
    resume_split,
    sample_training_indices,
    split_jobs,
)


def resume(resume_id, skills, **updates):
    return {
        "resume_id": resume_id,
        "skills": skills,
        "role": "Engineer",
        "seniority": "Mid",
        "summary": "build systems",
        "experience_bullets": ["deliver software"],
        **updates,
    }


def job(**updates):
    return {
        "job_id": "J_demo",
        "job_title": "Engineer",
        "seniority": "Mid",
        "must_have_skills": ["Python", "SQL", "Git"],
        "nice_to_have_skills": ["Docker"],
        "description": "build software",
        "responsibilities": ["deliver systems"],
        **updates,
    }


class FeatureTests(unittest.TestCase):
    def test_generator_normalization_preserves_meaningful_punctuation(self):
        self.assertEqual(normalize_generator_skill("  PYTHON &  SQL \n"), "python sql")
        self.assertEqual(normalize_generator_skill("C++ / C# .NET CI/CD"), "c++ / c# .net ci/cd")
        # The source generator has no semantic alias map.
        self.assertNotEqual(normalize_generator_skill("JS"), normalize_generator_skill("JavaScript"))

    def test_separate_coverage_features_and_stable_resume_order(self):
        corpus = PreparedCorpus([
            resume("R_b", ["Python"]),
            resume("R_a", ["python", "SQL", "Git", "Docker"]),
        ])
        matrix = feature_matrix(job(must_have_skills=["Python", "SQL", "SQL", "Git"]), corpus)
        self.assertEqual(corpus.ids, ["R_a", "R_b"])
        self.assertEqual(matrix.shape, (2, len(FEATURE_NAMES)))
        np.testing.assert_allclose(matrix[:, 0], [1, 1 / 3])
        np.testing.assert_allclose(matrix[:, 1], [1, 0])
        np.testing.assert_allclose(matrix[:, 2:4], 1)
        self.assertEqual(matrix[0, 4], 1)

    def test_absent_preferences_and_empty_required_coverage(self):
        corpus = PreparedCorpus([resume("R_a", [])])
        matrix = feature_matrix(job(must_have_skills=[], nice_to_have_skills=[]), corpus)
        np.testing.assert_allclose(matrix[0, :3], [1, 0, 0])

    def test_identifiers_labels_and_education_are_not_text_features(self):
        corpus = PreparedCorpus([resume("R_a", ["Python"], education="secret_token")])
        changed_corpus = PreparedCorpus([resume("R_changed", ["Python"], education="different")])
        original = feature_matrix(job(), corpus)
        changed = feature_matrix(job(job_id="other", relevant_resume_ids=["secret_token"]), changed_corpus)
        np.testing.assert_array_equal(original, changed)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            PreparedCorpus([resume("R_a", []), resume("R_a", [])])


class SamplingAndSplitTests(unittest.TestCase):
    def setUp(self):
        self.corpus = PreparedCorpus([
            resume("R_positive", ["Python", "SQL", "Git"]),
            resume("R_unlisted_qualified", ["Python", "SQL"]),
            resume("R_negative_a", ["Python"]),
            resume("R_negative_b", ["JavaScript"]),
        ])

    def test_unlisted_qualifying_resumes_are_never_negative_labels(self):
        indices, labels = sample_training_indices(job(), self.corpus, {"R_positive"}, seed=42)
        sampled = {self.corpus.ids[index]: label for index, label in zip(indices, labels)}
        self.assertEqual(sampled["R_positive"], 1)
        self.assertNotIn("R_unlisted_qualified", sampled)
        self.assertEqual(len(sampled), 2)
        again = sample_training_indices(job(), self.corpus, {"R_positive"}, seed=42)
        np.testing.assert_array_equal(indices, again[0])
        np.testing.assert_array_equal(labels, again[1])

    def test_invalid_positive_labels_raise(self):
        for positives in ({"R_missing"}, {"R_negative_a"}):
            with self.subTest(positives=positives), self.assertRaises(ValueError):
                sample_training_indices(job(), self.corpus, positives, seed=42)

    def test_no_balanced_sample_returns_empty_arrays(self):
        indices, labels = sample_training_indices(job(), self.corpus, set(), seed=42)
        self.assertEqual(indices.size, 0)
        self.assertEqual(labels.size, 0)

    def test_duplicate_structured_templates_share_partition(self):
        original = job(job_id="J_a", industry="Travel")
        duplicate = job(
            job_id="J_b", job_title=" ENGINEER ", seniority=" mid ",
            must_have_skills=[" git ", "SQL", "python", "Python"],
            nice_to_have_skills=["DOCKER"], industry="Health", description="other prose",
        )
        unrelated = job(job_id="J_c", job_title="Analyst", must_have_skills=["Excel"])
        partitions = split_jobs([original, unrelated, duplicate], seed=42)
        assigned = {row["job_id"]: name for name, rows in partitions.items() for row in rows}
        self.assertEqual(assigned["J_a"], assigned["J_b"])
        self.assertEqual(partitions, split_jobs([duplicate, original, unrelated], seed=42))
        self.assertEqual(set(assigned), {"J_a", "J_b", "J_c"})
        self.assertEqual(resume_split(resume("R_a", []), 42), resume_split(resume("R_a", ["SQL"]), 42))


class LogisticTests(unittest.TestCase):
    def test_logistic_learns_synthetic_separation_and_serializes(self):
        x = np.zeros((20, 5))
        x[10:, 0] = 1
        y = np.asarray([0] * 10 + [1] * 10)
        model = fit_logistic(x, y)
        self.assertLess(model.final_loss, model.initial_loss)
        scores = model.scores(x)
        self.assertGreater(scores[-1], scores[0])
        self.assertLess(scores[0], 0)
        self.assertGreater(scores[-1], 0)
        self.assertGreater(model.weights[0], 0)
        payload = json.loads(json.dumps(model.to_dict(), allow_nan=False))
        self.assertEqual(payload["target"], "synthetic_relevance")
        self.assertEqual(payload["feature_names"], list(FEATURE_NAMES))
        self.assertIsNone(payload["calibration"])
        np.testing.assert_array_equal(scores, fit_logistic(x, y).scores(x))

    def test_invalid_training_and_model_inputs_raise(self):
        x = np.zeros((2, 5))
        cases = [
            (np.zeros((2, 4)), [0, 1], {}),
            (np.full((2, 5), np.nan), [0, 1], {}),
            (np.full((2, 5), 2), [0, 1], {}),
            (x, [0], {}),
            (x, [1, 1], {}),
            (x, [0, np.nan], {}),
            (x, [0, 1], {"l2": -1}),
            (x, [0, 1], {"epochs": 0}),
        ]
        for features, labels, kwargs in cases:
            with self.subTest(kwargs=kwargs, labels=labels), self.assertRaises(ValueError):
                fit_logistic(features, np.asarray(labels), **kwargs)
        with self.assertRaises(ValueError):
            LogisticModel([1], 0).scores(x)
        with self.assertRaises(ValueError):
            LogisticModel([0] * 5, float("inf")).scores(x)


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.corpus = PreparedCorpus([resume("R_c", []), resume("R_a", []), resume("R_b", [])])

    def test_recall_denominator_precision_and_deterministic_ties(self):
        metrics = ranking_metrics(
            np.asarray([0.5, 0.5, 0.1]), self.corpus,
            {"R_b", "R_c"}, np.asarray([True, False, True]), k=1,
        )
        self.assertEqual(metrics["recommended_ids"], ["R_a"])
        self.assertEqual(metrics["listed_recall_at_k"], 0)
        self.assertEqual(metrics["threshold_precision_at_k"], 1)
        self.assertEqual(metrics["expected_listed_recall_for_qualified_only_ranker"], 0.5)
        metrics = ranking_metrics(
            np.asarray([0.1, 1.0, 0.5]), self.corpus,
            {"R_b", "R_c"}, np.asarray([False, True, True]), k=1,
        )
        self.assertEqual(metrics["listed_recall_at_k"], 0.5)

    def test_empty_labels_and_k_larger_than_corpus(self):
        metrics = ranking_metrics(np.zeros(3), self.corpus, set(), np.zeros(3, dtype=bool), k=30)
        self.assertIsNone(metrics["listed_recall_at_k"])
        self.assertIsNone(metrics["expected_listed_recall_for_qualified_only_ranker"])
        self.assertEqual(metrics["recommended_ids"], ["R_a", "R_b", "R_c"])
        self.assertEqual(metrics["threshold_precision_at_k"], 0)

    def test_holdout_recall_uses_only_labels_inside_its_corpus(self):
        metrics = ranking_metrics(
            np.asarray([0, 1, 0]), self.corpus,
            {"R_b", "R_outside_holdout"}, np.ones(3, dtype=bool), k=1,
        )
        self.assertEqual(metrics["listed_positive_count"], 1)
        self.assertEqual(metrics["listed_recall_at_k"], 1)

    def test_invalid_ranking_inputs_raise(self):
        cases = [
            ([0, np.nan, 0], [True] * 3, 1),
            ([0, 0], [True] * 3, 1),
            ([0] * 3, [True], 1),
            ([0] * 3, [True] * 3, 0),
            ([0] * 3, [2] * 3, 1),
        ]
        for scores, qualified, k in cases:
            with self.subTest(k=k), self.assertRaises(ValueError):
                ranking_metrics(np.asarray(scores), self.corpus, set(), np.asarray(qualified), k)


if __name__ == "__main__":
    unittest.main()
