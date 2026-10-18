"""Fictional numerical fixtures verify estimators, not real outcome quality."""

import copy
import json
import unittest
from unittest.mock import patch

import numpy as np

from scripts.wfhs_comparison_features import EXPANDED_VARIANTS, feature_names
from scripts.wfhs_comparison_models import fit_candidate, predict_artifact


def row(value=3, hours=40):
    return {
        "control_over_work_hours": value,
        "family_supportive_supervisor": value,
        "decision_authority": value,
        "psychological_job_demands": value,
        "hours_worked_last_week": hours,
        "hours_expected_by_manager": 40,
    }


def context(source, **changes):
    return {
        **source,
        "work_to_family_conflict": 2,
        "emotional_burnout": 6,
        "work_family_climate": 3,
        "baseline_satisfaction": 3,
        **changes,
    }


def spec(family="ridge", variant="baseline"):
    return {
        "id": f"fictional-{family}-{variant}",
        "family": family,
        "variant": variant,
        "parameters": {
            "ridge": {"l2": 0},
            "boosting": {
                "max_depth": 2,
                "n_estimators": 100,
                "learning_rate": 0.03,
                "min_samples_leaf": 20,
            },
            "random_forest": {
                "max_depth": 3,
                "n_estimators": 30,
                "min_samples_leaf": 5,
                "max_features": 1.0,
            },
        }[family],
    }


class WFHSComparisonModelTests(unittest.TestCase):
    def setUp(self):
        self.features = [row(value, hours=20 + value * 5) for value in np.linspace(1, 5, 120)]
        self.target = np.asarray(
            [1.25 + 0.75 * (feature["control_over_work_hours"] - 1) for feature in self.features]
        )

    def test_ridge_preserves_fractional_targets_and_matches_exact_linear_relation(self):
        model = fit_candidate(self.features, self.target, spec())
        np.testing.assert_allclose(model.predict(self.features), self.target, atol=1e-12)
        self.assertAlmostEqual(model.predict([row(2.5, 32.5)])[0], 2.375)
        self.assertEqual(len(model.encoder.numeric), 6)

    def test_satisfaction_only_models_and_json_replay_cannot_use_the_other_nine_fields(self):
        features = [
            context(item, baseline_satisfaction=float(self.target[index]))
            for index, item in enumerate(self.features)
        ]
        altered = [
            {**dict.fromkeys(feature), "baseline_satisfaction": feature["baseline_satisfaction"]}
            for feature in features
        ]
        original = copy.deepcopy(features)
        for family in ("ridge", "boosting", "random_forest"):
            with self.subTest(family=family):
                fitted = fit_candidate(features, self.target, spec(family, "satisfaction_only"))
                repeated = fit_candidate(altered, self.target, spec(family, "satisfaction_only"))
                self.assertEqual(fitted.encoder.numeric, ["baseline_satisfaction"])
                self.assertEqual(set(fitted.encoder.numeric_stats), {"baseline_satisfaction"})
                artifact = json.loads(json.dumps(fitted.to_dict(), allow_nan=False))
                self.assertEqual(artifact, repeated.to_dict())
                np.testing.assert_array_equal(fitted.predict(features), fitted.predict(altered))
                np.testing.assert_allclose(
                    fitted.predict(features), predict_artifact(artifact, altered), rtol=0, atol=1e-12
                )
                for invalid in (row(), dict(features[0], followup_satisfaction=4)):
                    with self.assertRaises(ValueError):
                        predict_artifact(artifact, [invalid])
                corrupted = copy.deepcopy(artifact)
                corrupted["encoder"]["numeric"].append("hours_worked_last_week")
                with self.assertRaises(ValueError):
                    predict_artifact(corrupted, features)
        self.assertEqual(features, original)

    def test_shallow_boosting_learns_nonlinearity_and_keeps_group_controls_explicit(self):
        target = np.asarray(
            [1.5 if feature["control_over_work_hours"] < 3 else 4.5 for feature in self.features]
        )
        model = fit_candidate(self.features, target, spec("boosting"))
        self.assertLess(np.mean((model.predict(self.features) - target) ** 2), 0.02)
        self.assertIsNone(model.estimator.n_iter_no_change)
        self.assertEqual(model.estimator.subsample, 1)
        self.assertEqual(model.estimator.max_depth, 2)
        self.assertEqual(model.estimator.random_state, 42)

    def test_random_forest_learns_nonlinearity_with_reproducible_bounded_trees(self):
        target = np.asarray([1.5 if item["control_over_work_hours"] < 3 else 4.5 for item in self.features])
        model = fit_candidate(self.features, target, spec("random_forest"))
        repeated = fit_candidate(self.features, target, spec("random_forest"))
        self.assertLess(np.mean((model.predict(self.features) - target) ** 2), 0.1)
        np.testing.assert_array_equal(model.predict(self.features), repeated.predict(self.features))
        self.assertEqual(model.estimator.max_depth, 3)
        self.assertEqual(model.estimator.min_samples_leaf, 5)
        self.assertTrue(model.estimator.bootstrap)
        self.assertFalse(model.estimator.oob_score)
        self.assertEqual(model.estimator.n_jobs, 1)
        self.assertTrue(all(tree.tree_.max_depth <= 3 for tree in model.estimator.estimators_))

    def test_fold_only_statistics_and_missing_indicators_are_replayed(self):
        features = [row(1, 10), row(3, 30), row(5, 50), row(2, None)]
        features[-1]["control_over_work_hours"] = None
        model = fit_candidate(features, np.asarray([1.5, 3.25, 4.5, 2]), spec(variant="interactions"))
        artifact = model.to_dict()
        stats = artifact["encoder"]["numeric_stats"]
        self.assertEqual(stats["hours_worked_last_week"], {"minimum": 10, "maximum": 50, "median": 30})
        self.assertEqual(stats["hours_gap"]["median"], -10)
        self.assertEqual(len(model.encoder.numeric), 10)
        before = copy.deepcopy(artifact)
        model.predict([row(5, 168), row(1, 0), row(None, None)])
        self.assertEqual(before, model.to_dict())
        np.testing.assert_array_equal(
            model.predict([row(None, None)]), predict_artifact(artifact, [row(None, None)])
        )

    def test_all_families_json_replay_without_fit_and_allow_empty_predictions(self):
        query = [row(1, 0), row(5, 168), row(2.5, 32.5), row(None, None)]
        for family in ("ridge", "boosting", "random_forest"):
            for variant in ("baseline", "interactions"):
                with self.subTest(family=family, variant=variant):
                    model = fit_candidate(self.features, self.target, spec(family, variant))
                    artifact = json.loads(json.dumps(model.to_dict(), allow_nan=False))
                    with patch(
                        "scripts.wfhs_comparison_models.fit_candidate",
                        side_effect=AssertionError("Must not fit"),
                    ):
                        restored = predict_artifact(artifact, query)
                    np.testing.assert_allclose(model.predict(query), restored, rtol=0, atol=1e-12)
                    # A legacy six-input artifact may receive a complete context;
                    # the extra conditions/satisfaction must remain excluded.
                    np.testing.assert_allclose(
                        predict_artifact(artifact, [context(item) for item in query]),
                        restored,
                        rtol=0,
                        atol=1e-12,
                    )
                    self.assertTrue(np.all((restored >= 1) & (restored <= 5)))
                    self.assertEqual(model.predict([]).shape, (0,))
                    self.assertEqual(predict_artifact(artifact, []).shape, (0,))
                    self.assertEqual(artifact["usage"], "offline_only")
                    self.assertEqual(artifact["output"], "predicted_scale_value_not_probability")

    def test_expanded_variants_roundtrip_all_families_with_correct_survey_domains(self):
        features = [
            context(item, emotional_burnout=6 + index % 2, baseline_satisfaction=float(self.target[index]))
            for index, item in enumerate(self.features)
        ]
        query = [
            context(row(2.5, 30), emotional_burnout=7, baseline_satisfaction=4.25),
            context(row(None, None), emotional_burnout=None, baseline_satisfaction=None),
        ]
        for family in ("ridge", "boosting", "random_forest"):
            for variant in EXPANDED_VARIANTS:
                with self.subTest(family=family, variant=variant):
                    model = fit_candidate(features, self.target, spec(family, variant))
                    artifact = json.loads(json.dumps(model.to_dict(), allow_nan=False))
                    self.assertEqual(artifact["encoder"]["numeric"], feature_names(variant))
                    np.testing.assert_allclose(
                        model.predict(query),
                        predict_artifact(artifact, query),
                        rtol=0,
                        atol=1e-12,
                    )
                    with self.assertRaises(ValueError):
                        predict_artifact(artifact, [row()])
                    if "emotional_burnout" in feature_names(variant):
                        self.assertEqual(
                            artifact["encoder"]["numeric_stats"]["emotional_burnout"]["maximum"], 7
                        )
                        artifact["encoder"]["numeric_stats"]["emotional_burnout"]["median"] = 8
                        with self.assertRaises(ValueError):
                            predict_artifact(artifact, query)

    def test_baseline_satisfaction_enters_only_explicit_satisfaction_variants(self):
        target = np.linspace(1, 5, 30)
        features = [context(row(), baseline_satisfaction=float(value)) for value in target]
        for without, with_satisfaction in (
            ("baseline", "baseline_with_satisfaction"),
            ("expanded", "expanded_with_satisfaction"),
        ):
            plain = fit_candidate(features, target, spec(variant=without))
            augmented = fit_candidate(features, target, spec(variant=with_satisfaction))
            np.testing.assert_allclose(plain.predict(features), np.full(30, 3), atol=1e-12)
            np.testing.assert_allclose(augmented.predict(features), target, atol=1e-12)
            self.assertNotIn("baseline_satisfaction", plain.encoder.numeric)
            self.assertIn("baseline_satisfaction", augmented.encoder.numeric)
            self.assertEqual(
                augmented.to_dict()["feature_timing"], "baseline_for_existing_employees_not_prehire"
            )

    def test_boosting_replay_matches_float32_threshold_behavior(self):
        model = fit_candidate(self.features, self.target, spec("boosting"))
        artifact = model.to_dict()
        tree = artifact["model"]["trees"][0]
        index = tree["feature"][0]
        feature = model.encoder.feature_names[index].removesuffix("__scaled")
        self.assertFalse(feature.endswith("__missing"))
        threshold = tree["threshold"][0]
        stats = model.encoder.numeric_stats[feature]
        query = row()
        query[feature] = stats["minimum"] + (threshold + 1e-10) * (stats["maximum"] - stats["minimum"])
        np.testing.assert_allclose(
            model.predict([query]), predict_artifact(artifact, [query]), atol=1e-12, rtol=0
        )

    def test_ridge_replay_clips_extreme_valid_coefficients(self):
        artifact = fit_candidate(self.features, self.target, spec()).to_dict()
        artifact["model"]["weights"] = [0] * len(artifact["model"]["weights"])
        artifact["model"]["bias"] = 20
        np.testing.assert_array_equal(predict_artifact(artifact, [row()]), [5])
        artifact["model"]["bias"] = -20
        np.testing.assert_array_equal(predict_artifact(artifact, [row()]), [1])

    def test_bad_training_data_and_candidate_parameters_fail(self):
        cases = [
            {"features": []},
            {"features": [row()], "y": [2]},
            {"y": [2]},
            {"y": np.full(120, np.nan)},
            {"y": np.full(120, 6)},
            {"y": np.full(120, True)},
            {"seed": True},
            {"seed": -1},
            {"seed": 2**32},
            {"spec": {**spec(), "variant": "future"}},
            {"spec": {**spec(), "parameters": {"l2": True}}},
            {"spec": {**spec(), "parameters": {"l2": -1}}},
            {"spec": {**spec("boosting"), "parameters": {**spec("boosting")["parameters"], "max_depth": 3}}},
            {
                "spec": {
                    **spec("random_forest"),
                    "parameters": {**spec("random_forest")["parameters"], "max_depth": 99},
                }
            },
            {
                "spec": {
                    **spec("random_forest"),
                    "parameters": {**spec("random_forest")["parameters"], "max_features": 0},
                }
            },
            {
                "spec": {
                    **spec("random_forest"),
                    "parameters": {**spec("random_forest")["parameters"], "min_samples_leaf": True},
                }
            },
            {
                "spec": {
                    **spec("random_forest"),
                    "parameters": {**spec("random_forest")["parameters"], "bootstrap": False},
                }
            },
            {
                "spec": {
                    **spec("boosting"),
                    "parameters": {**spec("boosting")["parameters"], "learning_rate": 0},
                }
            },
            {"features": [dict(feature, followup_satisfaction=2) for feature in self.features]},
        ]
        for case in cases:
            arguments = {"features": self.features, "y": self.target, "spec": spec()}
            arguments.update(case)
            with self.subTest(case=case), self.assertRaises(ValueError):
                fit_candidate(**arguments)

    def test_missing_entire_training_feature_cannot_use_held_out_statistics(self):
        features = [dict(feature, hours_worked_last_week=None) for feature in self.features]
        with self.assertRaisesRegex(ValueError, "no observed training values"):
            fit_candidate(features, self.target, spec())

    def test_invalid_encoder_state_fails_before_prediction(self):
        artifact = fit_candidate(self.features, self.target, spec()).to_dict()
        for mutate in (
            lambda value: value["encoder"]["numeric_stats"]["hours_worked_last_week"].update(median=200),
            lambda value: value["encoder"]["numeric_stats"]["hours_worked_last_week"].update(
                minimum=float("nan")
            ),
            lambda value: value["encoder"].update(feature_names=["wrong"]),
            lambda value: value["model"].update(feature_names=["wrong"]),
            lambda value: value["model"].update(weights=[1]),
        ):
            bad = copy.deepcopy(artifact)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                predict_artifact(bad, [row()])

    def test_replay_requires_every_semantic_metadata_field_for_all_families(self):
        names = (
            "schema_version",
            "target",
            "output",
            "usage",
            "scale_bounds",
            "scale_interpretation",
            "feature_timing",
        )
        for family in ("ridge", "boosting", "random_forest"):
            artifact = fit_candidate(self.features, self.target, spec(family)).to_dict()
            for name in names:
                bad = copy.deepcopy(artifact)
                del bad[name]
                with self.subTest(family=family, missing=name), self.assertRaisesRegex(ValueError, name):
                    predict_artifact(bad, [])

    def test_replay_rejects_relabeling_or_changing_scale_and_feature_timing(self):
        replacements = (
            ("schema_version", 2),
            ("schema_version", True),
            ("schema_version", 1.0),
            ("target", "joint_employee_manager_satisfaction"),
            ("output", "calibrated_match_probability"),
            ("usage", "live_matching"),
            ("scale_bounds", [0, 100]),
            ("scale_bounds", [True, 5]),
            ("scale_bounds", [1.0, 5.0]),
            ("scale_bounds", [1]),
            ("scale_interpretation", "cardinal_satisfaction_utility"),
            ("feature_timing", "prehire"),
            ("feature_timing", None),
        )
        for family in ("ridge", "boosting", "random_forest"):
            artifact = fit_candidate(self.features, self.target, spec(family)).to_dict()
            for name, replacement in replacements:
                bad = copy.deepcopy(artifact)
                bad[name] = replacement
                with (
                    self.subTest(family=family, name=name, replacement=replacement),
                    self.assertRaisesRegex(ValueError, name),
                ):
                    predict_artifact(bad, [row()])

    def test_corrupt_tree_cycles_bounds_and_nonfinite_values_fail_safely(self):
        artifact = fit_candidate(self.features, self.target, spec("boosting")).to_dict()
        for mutate in (
            lambda value: value["model"]["trees"][0]["children_left"].__setitem__(0, 0),
            lambda value: value["model"]["trees"][0]["children_left"].__setitem__(0, 999),
            lambda value: value["model"]["trees"][0]["feature"].__setitem__(0, 999),
            lambda value: value["model"]["trees"][0]["value"].__setitem__(0, float("inf")),
            lambda value: value["model"]["trees"][0]["threshold"].__setitem__(0, -1),
            lambda value: value["model"].update(learning_rate=0),
            lambda value: value["model"].update(init_constant=float("nan")),
            lambda value: value["model"]["trees"].pop(),
        ):
            bad = copy.deepcopy(artifact)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                predict_artifact(bad, [row()])

    def test_random_forest_replay_requires_mean_of_valid_scale_trees(self):
        model = fit_candidate(self.features, self.target, spec("random_forest"))
        artifact = model.to_dict()
        query = [row(1), row(2.5), row(5)]
        matrix = model.encoder.transform(query)
        expected = np.mean([tree.predict(matrix) for tree in model.estimator.estimators_], axis=0)
        np.testing.assert_allclose(predict_artifact(artifact, query), expected, atol=1e-12, rtol=0)
        for mutate in (
            lambda value: value["model"].update(aggregation="sum"),
            lambda value: value["model"].update(model_type="gradient_boosting_regression_trees_json"),
            lambda value: value["model"]["trees"].pop(),
            lambda value: value["model"]["trees"][0]["children_left"].__setitem__(0, 0),
            lambda value: value["model"]["trees"][0]["value"].__setitem__(0, 6),
            lambda value: value["model"]["trees"][0]["threshold"].__setitem__(0, float("nan")),
        ):
            bad = copy.deepcopy(artifact)
            mutate(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                predict_artifact(bad, query)


if __name__ == "__main__":
    unittest.main()
