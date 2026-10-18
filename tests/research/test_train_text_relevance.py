"""Fictional preferences verify fitting and leakage controls, not real accuracy."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.train_text_relevance import (
    FEATURE_NAMES,
    PortableTextRanker,
    fit_pairwise,
    grouped_folds,
    nested_cross_validate,
    publish_json,
    select_regularization,
)


def fixture():
    features = []
    for index in range(10):
        best = [0.0] * len(FEATURE_NAMES)
        other = [0.0] * len(FEATURE_NAMES)
        best[0], other[0] = 0.7 + index / 100, 0.2 + index / 100
        features.append([best, other])
    annotations = {"rater_a": [[1, 2] for _ in features], "rater_b": [[1, 2] for _ in features]}
    annotations["rater_b"][0] = None
    return features, annotations


class TrainingTests(unittest.TestCase):
    def test_actual_fitting_learns_preferences_and_inverts_when_labels_invert(self):
        features, annotations = fixture()
        indices = list(range(10))
        learned = fit_pairwise(features, annotations, indices, regularization=0.1, source_sha256="a" * 64)
        reversed_labels = {
            name: [list(reversed(row)) if row else None for row in rows] for name, rows in annotations.items()
        }
        reversed_model = fit_pairwise(
            features, reversed_labels, indices, regularization=0.1, source_sha256="a" * 64
        )
        self.assertGreater(learned.coefficients[0], 0)
        self.assertLess(reversed_model.coefficients[0], 0)
        self.assertAlmostEqual(learned.coefficients[0], -reversed_model.coefficients[0])
        self.assertEqual(learned.training_query_clusters, 10)
        self.assertEqual(learned.training_judgments, 19)
        self.assertEqual(learned.training_preference_pairs, 19)
        self.assertEqual(learned.scales[1:], (1.0,) * (len(FEATURE_NAMES) - 1))
        self.assertEqual(PortableTextRanker.from_dict(learned.to_dict()), learned)

    def test_heldout_features_and_labels_cannot_change_training_or_scaling(self):
        features, annotations = fixture()
        first = fit_pairwise(
            features, annotations, list(range(8)), regularization=1.0, source_sha256="a" * 64
        )
        changed_features, changed_labels = copy.deepcopy(features), copy.deepcopy(annotations)
        for index in (8, 9):
            changed_features[index] = [[1.0] * len(FEATURE_NAMES), [0.0] * len(FEATURE_NAMES)]
            for rows in changed_labels.values():
                rows[index] = [2, 1]
        second = fit_pairwise(
            changed_features, changed_labels, list(range(8)), regularization=1.0, source_sha256="a" * 64
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        expected_mean = sum(row[0] for query in features[:8] for row in query) / 16
        self.assertAlmostEqual(first.means[0], expected_mean)

    def test_rater_duplication_does_not_duplicate_cluster_training_weight(self):
        features, annotations = fixture()
        one = {"first": [[1, 2] for _ in features]}
        two = {**one, "second": [[1, 2] for _ in features]}
        first = fit_pairwise(features, one, list(range(10)), regularization=1.0, source_sha256="a" * 64)
        second = fit_pairwise(features, two, list(range(10)), regularization=1.0, source_sha256="a" * 64)
        self.assertAlmostEqual(first.coefficients[0], second.coefficients[0])

    def test_group_folds_are_deterministic_disjoint_and_complete(self):
        folds = grouped_folds(list(range(30)), 5)
        self.assertEqual(folds, grouped_folds(list(reversed(range(30))), 5))
        self.assertEqual(sorted(value for fold in folds for value in fold), list(range(30)))
        self.assertEqual([len(fold) for fold in folds], [6] * 5)
        self.assertNotEqual(folds, grouped_folds(list(range(30)), 5, 43))

    def test_nested_oof_and_selection_use_real_fitted_models(self):
        features, annotations = fixture()
        scores, report = nested_cross_validate(features, annotations, source_sha256="a" * 64)
        self.assertEqual(len(scores), 10)
        self.assertTrue(all(row[0] > row[1] for row in scores))
        self.assertTrue(report["every_cv_scored_out_of_fold"])
        self.assertEqual(sum(report["selected_regularization_counts"].values()), 5)
        regularization, results = select_regularization(
            features, annotations, list(range(10)), source_sha256="a" * 64
        )
        self.assertTrue(all(value == 1.0 for value in results.values()))
        self.assertEqual(regularization, 100.0)

    def test_invalid_labels_features_or_groups_fail_before_training(self):
        features, annotations = fixture()
        for indices in ([], [0, 0], [True], [-1], [10]):
            with self.assertRaises(ValueError):
                fit_pairwise(features, annotations, indices, regularization=1.0, source_sha256="a" * 64)
        annotations["rater_a"][0] = [1, 1]
        with self.assertRaises(ValueError):
            fit_pairwise(features, annotations, list(range(10)), regularization=1.0, source_sha256="a" * 64)

    def test_artifact_publication_is_json_only_and_refuses_overwrite(self):
        features, annotations = fixture()
        model = fit_pairwise(
            features, annotations, list(range(10)), regularization=1.0, source_sha256="a" * 64
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.json"
            publish_json(model.to_dict(), path)
            self.assertEqual(PortableTextRanker.from_dict(json.loads(path.read_text())), model)
            with self.assertRaises(FileExistsError):
                publish_json(model.to_dict(), path)


if __name__ == "__main__":
    unittest.main()
