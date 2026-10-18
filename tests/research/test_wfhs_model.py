"""Numerical fixtures test software behavior, not real satisfaction quality."""

import json
import unittest

import numpy as np

from scripts.wfhs_model import ScaleRidgeModel, fit_ridge, regression_metrics


class ScaleRidgeModelTests(unittest.TestCase):
    def test_unregularized_fit_recovers_fractional_scale_without_rounding(self):
        x = np.array([[0], [.25], [.5], [.75], [1]])
        y = 1.25 + 3.5 * x[:, 0]
        model = fit_ridge(x, y, ["schedule"], l2=0)
        np.testing.assert_allclose(model.weights, [3.5], atol=1e-12)
        self.assertAlmostEqual(model.bias, 1.25)
        np.testing.assert_allclose(model.predict(x), y, atol=1e-12)
        self.assertAlmostEqual(model.predict([[.5]])[0], 3)
        self.assertAlmostEqual(model.predict([[.1]])[0], 1.6)

    def test_ridge_matches_analytic_average_loss_solution(self):
        x = np.array([[0], [0], [1], [1]])
        y = np.array([1, 2, 4, 5])
        # Var(x)=.25, Cov(x,y)=.75. The mean-loss ridge slope is .75/(.25+1).
        model = fit_ridge(x, y, ["support"], l2=1)
        self.assertAlmostEqual(model.weights[0], .6)
        self.assertAlmostEqual(model.bias, 2.7)
        # Duplicating observations must not change the penalty's strength.
        duplicated = fit_ridge(np.tile(x, (3, 1)), np.tile(y, 3), ["support"], l2=1)
        np.testing.assert_allclose(model.weights, duplicated.weights, atol=1e-12)
        self.assertAlmostEqual(model.bias, duplicated.bias)

    def test_intercept_is_unpenalized_and_constant_features_are_safe(self):
        x = np.array([[.2, 1], [.2, 1], [.2, 1]])
        y = [2, 3.5, 5]
        for penalty in (0, 1, 1e12):
            with self.subTest(penalty=penalty):
                model = fit_ridge(x, y, ["constant", "intercept_like"], l2=penalty)
                np.testing.assert_allclose(model.weights, [0, 0], atol=1e-12)
                self.assertAlmostEqual(model.bias, 3.5)
                np.testing.assert_allclose(model.predict(x), [3.5] * 3)

    def test_collinear_features_can_fit_without_matrix_inverse(self):
        x = np.array([[0, 0], [.5, .5], [1, 1]])
        model = fit_ridge(x, [1, 3, 5], ["a", "b"], l2=0)
        np.testing.assert_allclose(model.weights, [2, 2], atol=1e-12)
        np.testing.assert_allclose(model.predict(x), [1, 3, 5], atol=1e-12)

    def test_constant_target_remains_a_valid_baseline(self):
        model = fit_ridge([[0], [1]], [3.25, 3.25], ["x"])
        np.testing.assert_allclose(model.weights, [0])
        np.testing.assert_allclose(model.predict([[0], [.5], [1]]), [3.25] * 3)

    def test_predictions_are_clipped_and_empty_prediction_rows_are_allowed(self):
        model = ScaleRidgeModel(["x"], [10], -2, l2=0)
        np.testing.assert_array_equal(model.predict([[0], [.5], [1]]), [1, 3, 5])
        self.assertEqual(model.predict(np.empty((0, 1))).shape, (0,))

    def test_serialized_coefficients_replay_and_declare_interpretation(self):
        model = fit_ridge([[0], [.5], [1]], [1.25, 3, 4.5], ["hours"], l2=.1)
        artifact = json.loads(json.dumps(model.to_dict(), allow_nan=False))
        restored = ScaleRidgeModel(
            artifact["feature_names"], artifact["weights"], artifact["bias"], artifact["l2"]
        )
        np.testing.assert_array_equal(model.predict([[.2], [.8]]), restored.predict([[.2], [.8]]))
        self.assertEqual(artifact["target"], "employee_reported_satisfaction_scale")
        self.assertEqual(artifact["output"], "predicted_scale_value_not_probability")
        self.assertEqual(artifact["usage"], "offline_only")
        self.assertIn("not_cardinal_satisfaction_utility", artifact["scale_interpretation"])
        self.assertIs(artifact["intercept_penalized"], False)
        self.assertEqual(model.to_dict(), fit_ridge(
            [[0], [.5], [1]], [1.25, 3, 4.5], ["hours"], l2=.1
        ).to_dict())

    def test_regression_metrics_known_fractional_fixture(self):
        result = regression_metrics([1, 2.5, 5], [1.5, 2, 4])
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["mae"], 2 / 3)
        self.assertAlmostEqual(result["rmse"], np.sqrt(.5))
        self.assertAlmostEqual(result["r2"], 1 - 1.5 / np.sum((np.array([1, 2.5, 5]) - 8.5 / 3) ** 2))
        self.assertNotIn("accuracy", result)

    def test_constant_target_r2_is_undefined_and_poor_model_can_have_negative_r2(self):
        self.assertIsNone(regression_metrics([3, 3], [2, 4])["r2"])
        self.assertLess(regression_metrics([2, 3], [5, 1])["r2"], 0)

    def test_fit_rejects_invalid_shapes_ranges_names_and_parameters(self):
        bad_cases = [
            {"x": [0, 1]}, {"x": [[0, 1], [1, 0]]}, {"x": [[0], [np.nan]]},
            {"x": [[0], [np.inf]]}, {"x": [[-.1], [1]]}, {"x": [[0], [1.1]]},
            {"x": [[False], [True]]}, {"x": [["0"], ["1"]]},
            {"x": np.empty((0, 1)), "y": []}, {"x": [[0]], "y": [2]},
            {"y": [[1], [5]]}, {"y": [1]}, {"y": [0, 5]}, {"y": [1, 5.1]},
            {"y": [1, np.nan]}, {"y": [1, np.inf]}, {"y": [False, True]},
            {"feature_names": []}, {"feature_names": [""]}, {"feature_names": [" "]},
            {"feature_names": ["x", "x"]}, {"feature_names": "x"},
            {"l2": -1}, {"l2": np.inf}, {"l2": np.nan}, {"l2": True},
            {"l2": np.bool_(False)}, {"l2": "1"}, {"l2": None},
        ]
        for bad in bad_cases:
            args = {"x": [[0], [1]], "y": [1, 5], "feature_names": ["x"]}
            args.update(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                fit_ridge(**args)

    def test_loaded_coefficients_are_validated_and_cannot_overflow_silently(self):
        for weights, bias, penalty in [
            ([], 1, 1), ([[1]], 1, 1), ([np.nan], 1, 1), ([np.inf], 1, 1),
            ([1], np.nan, 1), ([1], True, 1), ([True], 1, 1), ([1], 1, -1),
        ]:
            with self.subTest(weights=weights, bias=bias, penalty=penalty), self.assertRaises(ValueError):
                ScaleRidgeModel(["x"], weights, bias, penalty)
        model = ScaleRidgeModel(["a", "b"], [1e308, 1e308], 1)
        with self.assertRaises(ValueError):
            model.predict([[1, 1]])

    def test_prediction_rejects_unscaled_or_wrong_features(self):
        model = ScaleRidgeModel(["x"], [1], 2)
        for x in ([0], [[0, 1]], [[-1]], [[2]], [[np.inf]], [[np.nan]]):
            with self.subTest(x=x), self.assertRaises(ValueError):
                model.predict(x)

    def test_metrics_reject_empty_misaligned_or_invalid_scale_values(self):
        for y, prediction in [
            ([], []), ([1, 2], [1]), ([[1]], [1]), ([1], [[1]]),
            ([0], [1]), ([1], [0]), ([1], [5.1]), ([np.nan], [1]),
            ([1], [np.inf]), ([True], [1]), ([1], [True]),
        ]:
            with self.subTest(y=y, prediction=prediction), self.assertRaises(ValueError):
                regression_metrics(y, prediction)


if __name__ == "__main__":
    unittest.main()
