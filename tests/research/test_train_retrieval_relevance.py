"""Fictional published positives verify ML, PU semantics and whole-job isolation."""

import copy
import math
import unittest

import numpy as np

from scripts.train_retrieval_relevance import (
    FEATURE_NAMES,
    PortableRetrievalRanker,
    fit_listwise,
    listwise_objective,
    nested_cross_validate,
    published_positive_ap,
    select_policy,
)


def fixture():
    features = []
    for index in range(5):
        rows = [[0.0] * len(FEATURE_NAMES) for _ in range(4)]
        for position in range(4):
            rows[position][0] = 0.9 - position / 5 - index / 100
        features.append(rows)
    return features, [[0] for _ in features], [[4.0, 3.0, 2.0, 1.0] for _ in features]


class ListwiseTests(unittest.TestCase):
    def test_fitting_learns_published_positives_without_binary_negative_targets(self):
        features, positives, _ = fixture()
        model = fit_listwise(features, positives, list(range(5)), regularization=0.1, source_sha256="a" * 64)
        self.assertGreater(model.coefficients[0], 0)
        self.assertEqual(model.training_positive_judgments, 5)
        self.assertEqual(model.candidate_corpus_size, 4)
        self.assertEqual(model.scales[1:], (1.0,) * (len(FEATURE_NAMES) - 1))
        self.assertEqual(PortableRetrievalRanker.from_dict(model.to_dict()), model)
        reversed_model = fit_listwise(
            features, [[3]] * 5, list(range(5)), regularization=0.1, source_sha256="a" * 64
        )
        self.assertLess(reversed_model.coefficients[0], 0)

    def test_excluded_job_features_and_labels_are_not_read(self):
        features, positives, baseline = fixture()
        model = fit_listwise(features, positives, [0, 1, 2, 3], regularization=1.0, source_sha256="a" * 64)
        expected_policy = select_policy(features, positives, baseline, [0, 1, 2, 3], source_sha256="a" * 64)
        features[4], positives[4], baseline[4] = None, None, None
        actual = fit_listwise(features, positives, [0, 1, 2, 3], regularization=1.0, source_sha256="a" * 64)
        self.assertEqual(actual.to_dict(), model.to_dict())
        self.assertEqual(
            select_policy(features, positives, baseline, [0, 1, 2, 3], source_sha256="a" * 64),
            expected_policy,
        )

    def test_inner_only_policy_falls_back_on_tie_and_learns_when_baseline_loses(self):
        features, positives, baseline = fixture()
        selected, use_ml, report = select_policy(
            features, positives, baseline, list(range(5)), source_sha256="a" * 64
        )
        self.assertEqual(selected, 100.0)
        self.assertFalse(use_ml)
        self.assertEqual(report["selected_policy"], "TFIDF_FALLBACK")
        wrong = [list(reversed(row)) for row in baseline]
        _, use_ml, _ = select_policy(features, positives, wrong, list(range(5)), source_sha256="a" * 64)
        self.assertTrue(use_ml)
        raw, gated, summary = nested_cross_validate(features, positives, wrong, source_sha256="a" * 64)
        self.assertEqual(raw, gated)
        self.assertEqual(summary["ml_selected_outer_jobs"], 5)
        self.assertEqual(summary["inner_whole_job_folds_per_outer"], 4)
        self.assertTrue(all(row[0] > row[-1] for row in raw))

    def test_all_published_positive_candidates_produce_zero_coefficients(self):
        features, _, _ = fixture()
        model = fit_listwise(
            features, [list(range(4))] * 5, list(range(5)), regularization=0.1, source_sha256="a" * 64
        )
        self.assertEqual(model.coefficients, (0.0,) * len(FEATURE_NAMES))

    def test_stable_derivatives_match_independent_finite_differences(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=(3, 4, len(FEATURE_NAMES)))
        positive_means = np.array([row[:2].mean(axis=0) for row in x])
        w = rng.normal(size=len(FEATURE_NAMES)) / 4
        loss, gradient, hessian = listwise_objective(w, x, positive_means, 0.2)
        self.assertTrue(math.isfinite(loss))
        epsilon = 1e-5
        numeric = []
        numeric_hessian = []
        for column in range(len(w)):
            direction = np.zeros_like(w)
            direction[column] = epsilon
            left = listwise_objective(w - direction, x, positive_means, 0.2)
            right = listwise_objective(w + direction, x, positive_means, 0.2)
            numeric.append((right[0] - left[0]) / (2 * epsilon))
            numeric_hessian.append((right[1] - left[1]) / (2 * epsilon))
        np.testing.assert_allclose(gradient, numeric, atol=1e-8, rtol=0)
        np.testing.assert_allclose(hessian, np.array(numeric_hessian).T, atol=1e-8, rtol=0)
        self.assertGreaterEqual(np.linalg.eigvalsh(hessian).min(), 0.2 - 1e-12)

    def test_bad_geometry_labels_bools_and_parameters_fail(self):
        features, positives, _ = fixture()
        for indices in ([], [True], [0, 0], [5]):
            with self.assertRaises(ValueError):
                fit_listwise(features, positives, indices, regularization=1.0, source_sha256="a" * 64)
        for invalid in (True, float("nan"), -1, 0):
            with self.assertRaises(ValueError):
                fit_listwise(features, positives, [0, 1], regularization=invalid, source_sha256="a" * 64)
        changed = copy.deepcopy(features)
        changed[0][0][0] = True
        with self.assertRaises(ValueError):
            fit_listwise(changed, positives, [0, 1], regularization=1.0, source_sha256="a" * 64)
        for invalid in ([], [0, 0], [True], [4]):
            changed_labels = copy.deepcopy(positives)
            changed_labels[0] = invalid
            with self.assertRaises(ValueError):
                fit_listwise(features, changed_labels, [0, 1], regularization=1.0, source_sha256="a" * 64)

    def test_published_positive_ap_counts_unknown_as_no_credit_not_classification(self):
        self.assertEqual(published_positive_ap([3.0, 2.0, 1.0], [0, 2]), (1 + 2 / 3) / 2)
        self.assertAlmostEqual(published_positive_ap([0.0] * 3, [0]), (1 + 0.5 + 1 / 3) / 3)


if __name__ == "__main__":
    unittest.main()
