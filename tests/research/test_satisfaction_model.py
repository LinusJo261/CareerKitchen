"""Fictional category fixtures validate software, never real outcome quality."""

import json
import unittest

import numpy as np

from scripts.satisfaction_model import (
    SatisfactionModel,
    TabularEncoder,
    classification_metrics,
    fit_majority_baseline,
    fit_model,
)


LABELS = ["dislike", "neutral", "like"]


class SatisfactionModelTests(unittest.TestCase):
    def test_fits_three_distinguishable_categories_and_reduces_loss(self):
        x = np.tile(np.eye(3), (8, 1))
        y = np.tile(np.arange(3), 8)
        model = fit_model(x, y, ["a", "b", "c"], LABELS, epochs=150)
        self.assertLess(model.final_loss, model.initial_loss / 3)
        np.testing.assert_array_equal(model.predict(x), y)
        probabilities = model.predict_proba(x)
        self.assertTrue(np.all(np.isfinite(probabilities)))
        np.testing.assert_allclose(probabilities.sum(axis=1), 1)
        replay = fit_model(x, y, ["a", "b", "c"], LABELS, epochs=150)
        self.assertEqual(model.to_dict(), replay.to_dict())

    def test_full_class_order_is_preserved_when_training_lacks_a_category(self):
        model = fit_model([[0], [1]], [0, 2], ["x"], LABELS, epochs=50)
        self.assertEqual(model.predict_proba([[0.5]]).shape, (1, 3))
        self.assertEqual(model.labels, LABELS)
        self.assertEqual(model.to_dict()["class_order_worst_to_best"], LABELS)

    def test_export_can_replay_predictions_without_refitting(self):
        model = fit_model([[0], [1]], [0, 2], ["x"], LABELS, epochs=25)
        artifact = json.loads(json.dumps(model.to_dict(), allow_nan=False))
        restored = SatisfactionModel(
            artifact["feature_names"], artifact["class_order_worst_to_best"],
            artifact["weights"], artifact["bias"],
            artifact["initial_loss"], artifact["final_loss"],
        )
        np.testing.assert_array_equal(
            model.predict_proba([[0.1], [0.9]]),
            restored.predict_proba([[0.1], [0.9]]),
        )
        self.assertEqual(artifact["target"], "reported_job_satisfaction")
        self.assertEqual(artifact["output"], "uncalibrated_class_probabilities")
        self.assertIn("not_equal_satisfaction_intervals", artifact["ordinal_distance"])

    def test_extreme_finite_logits_have_finite_normalized_probabilities(self):
        model = SatisfactionModel(["x"], LABELS, [[1000, -1000, 0]], [0, 0, 0])
        proba = model.predict_proba([[0], [1]])
        np.testing.assert_allclose(proba.sum(axis=1), 1)
        self.assertTrue(np.all(np.isfinite(proba)))
        self.assertEqual(model.predict([[1]]).tolist(), [0])
        self.assertEqual(model.predict_proba(np.empty((0, 1))).shape, (0, 3))

    def test_metrics_known_multiclass_fixture(self):
        proba = np.array([
            [.8, .1, .1], [.1, .2, .7], [.6, .3, .1], [.1, .1, .8],
        ])
        result = classification_metrics([0, 1, 2, 2], proba)
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["accuracy"], .5)
        self.assertEqual(result["ordinal_mae"], .75)
        self.assertEqual(result["within_one_category"], .75)
        self.assertEqual(result["confusion_matrix"], [[1, 0, 0], [0, 0, 1], [1, 0, 1]])
        self.assertAlmostEqual(result["log_loss"], -np.log([.8, .2, .1, .8]).mean())
        self.assertAlmostEqual(result["multiclass_brier"], (.06 + 1.14 + 1.26 + .06) / 4)

    def test_majority_baseline_uses_only_passed_labels_and_keeps_absent_classes(self):
        baseline = fit_majority_baseline([2, 2, 0, 0], 3)
        np.testing.assert_array_equal(baseline, [.5, 0, .5])
        self.assertEqual(baseline.argmax(), 0)
        np.testing.assert_array_equal(fit_majority_baseline([1, 1], 3), [0, 1, 0])
        metrics = classification_metrics([0, 1, 2], np.tile(baseline, (3, 1)))
        self.assertTrue(np.isfinite(metrics["log_loss"]))

    def test_fit_rejects_invalid_features_labels_and_training_settings(self):
        bad_cases = [
            {"x": [[np.nan], [1]]}, {"x": [[0], [np.inf]]},
            {"x": [[-0.1], [1]]}, {"x": [[0], [1.1]]}, {"x": [0, 1]},
            {"y": [0]}, {"y": [0, 0]}, {"y": [0, 3]}, {"y": [0, .5]},
            {"y": [0, np.nan]}, {"feature_names": []}, {"labels": ["same", "same"]},
            {"l2": -1}, {"l2": float("inf")}, {"epochs": 0}, {"epochs": True},
        ]
        for bad in bad_cases:
            args = {"x": [[0], [1]], "y": [0, 2], "feature_names": ["x"], "labels": LABELS}
            args.update(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                fit_model(**args)

    def test_metrics_reject_invalid_probabilities_or_labels(self):
        for y, probabilities in [
            ([0], [[.4, .4]]), ([0], [[np.nan, .5]]), ([0], [[-.1, 1.1]]),
            ([0], [[1]]), ([0, 1], [[.5, .5]]), ([2], [[.5, .5]]),
            ([], np.empty((0, 2))),
        ]:
            with self.subTest(y=y, proba=probabilities), self.assertRaises(ValueError):
                classification_metrics(y, probabilities)

    def test_invalid_coefficients_cannot_be_loaded(self):
        for weights, bias in [([[0, 0]], [0, 0, 0]), ([[0, np.nan, 0]], [0, 0, 0]),
                              ([[0, 0, 0]], [0, np.inf, 0])]:
            with self.subTest(weights=weights, bias=bias), self.assertRaises(ValueError):
                SatisfactionModel(["x"], LABELS, weights, bias)


class TabularEncoderTests(unittest.TestCase):
    def test_train_only_statistics_clipping_and_unknown_categories(self):
        encoder = TabularEncoder.fit(
            [{"hours": 10, "mode": "onsite"}, {"hours": 20, "mode": "remote"}],
            ["hours"], ["mode"],
        )
        before = encoder.to_dict()
        transformed = encoder.transform([
            {"hours": -10, "mode": "hybrid"},
            {"hours": 100, "mode": "remote"},
            {"hours": None, "mode": None},
        ])
        np.testing.assert_array_equal(transformed, [
            [0, 0, 0, 0, 0, 1], [1, 0, 0, 1, 0, 0], [.5, 1, 0, 0, 1, 0],
        ])
        self.assertEqual(encoder.to_dict(), before)
        self.assertNotIn("hybrid", encoder.categories["mode"])
        self.assertEqual(len(encoder.feature_names), transformed.shape[1])

    def test_training_median_and_indicators_are_retained_with_missing_inputs(self):
        encoder = TabularEncoder.fit(
            [{"x": 0, "cat": "__unknown"}, {"x": 2}, {"x": 10}, {"x": None}],
            ["x"], ["cat"],
        )
        transformed = encoder.transform([{}, {"x": 10, "cat": "__unknown"}])
        np.testing.assert_array_equal(transformed, [[.2, 1, 0, 1, 0], [1, 0, 1, 0, 0]])
        artifact = json.loads(json.dumps(encoder.to_dict(), allow_nan=False))
        restored = TabularEncoder(
            artifact["numeric"], artifact["categorical"],
            artifact["numeric_stats"], artifact["categories"],
        )
        np.testing.assert_array_equal(restored.transform([{}]), encoder.transform([{}]))

    def test_constant_numeric_and_empty_categorical_training_are_valid(self):
        encoder = TabularEncoder.fit([{"x": 4}, {"x": 4}], ["x"], ["cat"])
        matrix = encoder.transform([{"x": 100, "cat": "test-only"}, {}])
        np.testing.assert_array_equal(matrix, [[0, 0, 0, 1], [0, 1, 1, 0]])
        self.assertEqual(encoder.transform([]).shape, (0, 4))

    def test_invalid_or_useless_training_features_fail(self):
        cases = [
            ([], ["x"], []), ([{}], [], []), ([{}], ["x"], []),
            ([{"x": 1}], ["x"], ["x"]), ([{"x": 1}], ["x", "x"], []),
            ([{"x": "1"}], ["x"], []), ([{"x": True}], ["x"], []),
            ([{"x": float("inf")}], ["x"], []), ([{"cat": 3}], [], ["cat"]),
        ]
        for rows, numeric, categorical in cases:
            with self.subTest(rows=rows, numeric=numeric), self.assertRaises(ValueError):
                TabularEncoder.fit(rows, numeric, categorical)
        encoder = TabularEncoder.fit([{"x": 1}], ["x"], ["cat"])
        for row in [{"x": np.nan}, {"cat": 5}, "invalid"]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                encoder.transform([row])


if __name__ == "__main__":
    unittest.main()
