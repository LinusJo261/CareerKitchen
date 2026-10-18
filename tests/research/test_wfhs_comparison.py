"""Fictional fixtures check development-only comparison boundaries and publication."""

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts import wfhs_comparison as comparison
from scripts import wfhs_research as wfhs
from scripts.wfhs_comparison_models import fit_candidate, predict_artifact
from scripts.wfhs_model import regression_metrics


def development_records():
    clusters = [
        f"tomo:{index}" for index in range(1, 100) if wfhs.cluster_partition(f"tomo:{index}", 42) != "test"
    ][:12]
    rows = []
    for group, cluster in enumerate(clusters):
        for colleague in range(2):
            index = 2 * group + colleague
            rows.append(
                {
                    "person_id": f"fictional-comparison-{index}",
                    "baseline_cluster": cluster,
                    "condition": "1" if index % 2 else "2",
                    "baseline_wave": 1,
                    "outcome_wave": 3,
                    "baseline_satisfaction": 3.0,
                    "followup_satisfaction": 2 + index / 20,
                    "features": {
                        "control_over_work_hours": 1 + index % 5,
                        "family_supportive_supervisor": 1 + (index + 1) % 5,
                        "decision_authority": 1 + (index + 2) % 5,
                        "psychological_job_demands": 1 + (index + 3) % 5,
                        "hours_worked_last_week": 20 + index,
                        "hours_expected_by_manager": 30.0,
                    },
                }
            )
    return rows


def audit(expanded_features=False):
    return {
        "dataset": "tomo",
        "data_partition": "original_train_validation_only",
        "source_sha256": hashlib.sha256(b"fictional comparison fixture").hexdigest(),
        "expanded_features": expanded_features,
    }


def tiny_grid(include_random_forest=False, expanded_features=False, include_satisfaction_only=False):
    result = [
        {
            "id": f"fixture_{family}_{variant}",
            "family": family,
            "variant": variant,
            "parameters": {"l2": 0.1}
            if family == "ridge"
            else {
                "max_depth": 1,
                "n_estimators": 3,
                "learning_rate": 0.1,
                "min_samples_leaf": 1,
            },
        }
        for variant in ("baseline", "interactions")
        for family in ("ridge", "boosting")
    ]
    if include_random_forest:
        result.extend(
            {
                "id": f"fixture_random_forest_{variant}",
                "family": "random_forest",
                "variant": variant,
                "parameters": {
                    "max_depth": 3,
                    "n_estimators": 3,
                    "min_samples_leaf": 1,
                    "max_features": 1.0,
                },
            }
            for variant in ("baseline", "interactions")
        )
    if expanded_features:
        for variant in comparison.EXPANDED_VARIANTS + (
            comparison.SATISFACTION_ONLY_VARIANTS if include_satisfaction_only else ()
        ):
            for candidate in tiny_grid(include_random_forest):
                if candidate["variant"] == "baseline":
                    result.append({**candidate, "id": candidate["id"] + "_" + variant, "variant": variant})
    return result


def expanded_records():
    rows = development_records()
    for index, record in enumerate(rows):
        record["features"].update(
            work_to_family_conflict=1 + index % 5,
            emotional_burnout=None if index % 4 == 0 else 1 + index % 7,
            work_family_climate=1 + (index + 2) % 5,
        )
    return rows


def survey_row(person, wave, cluster):
    return {
        "ADMINLINK": person,
        "WAVE": str(wave),
        "EMPLOYEE": "1",
        "MANAGER": "0",
        "CONDITION": "1",
        "STUDYGROUP": str(cluster),
        "EXCLUDE": "",
        wfhs.LABEL: "3",
        **dict.fromkeys(wfhs.LABEL_ITEMS, "3"),
        **{column: "40" if name.startswith("hours_") else "3" for name, column in wfhs.FEATURES.items()},
    }


def write_survey(raw, rows):
    source = raw / wfhs.DATASETS["tomo"][0]
    source.parent.mkdir(parents=True, exist_ok=True)
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return source


class WFHSComparisonTests(unittest.TestCase):
    def test_satisfaction_only_grid_is_opt_in_and_preserves_all_existing_candidates(self):
        for forests, count in ((False, 42), (True, 66)):
            previous = comparison.candidate_grid(forests, True)
            extended = comparison.candidate_grid(forests, True, True)
            self.assertEqual(extended[: len(previous)], previous)
            self.assertEqual(len(extended), count)
            self.assertEqual(len({item["id"] for item in extended}), count)
            self.assertEqual(
                [
                    (item["family"], item["parameters"])
                    for item in extended
                    if item["variant"] == "satisfaction_only"
                ],
                [(item["family"], item["parameters"]) for item in previous if item["variant"] == "baseline"],
            )
            self.assertEqual(
                comparison.protocol_version(forests, True, True),
                comparison.SATISFACTION_ONLY_PROTOCOL_VERSION,
            )
        self.assertEqual(comparison.protocol_version(False, False), comparison.PROTOCOL_VERSION)
        self.assertEqual(comparison.protocol_version(True, False), comparison.FOREST_PROTOCOL_VERSION)
        self.assertEqual(comparison.protocol_version(True, True), comparison.EXPANDED_PROTOCOL_VERSION)
        with self.assertRaises(ValueError):
            comparison.candidate_grid(include_satisfaction_only=True)

    def test_satisfaction_only_requires_expanded_context_and_fixed_rmse_before_fitting(self):
        with patch.object(comparison, "fit_candidate") as fit:
            for expanded, metric in ((False, "rmse"), (True, "mae")):
                with self.subTest(expanded=expanded, metric=metric), self.assertRaises(ValueError):
                    comparison.compare_records(
                        expanded_records(),
                        audit(True),
                        expanded_features=expanded,
                        include_satisfaction_only=True,
                        metric=metric,
                    )
            fit.assert_not_called()
        with patch.object(comparison, "prepare_dataset") as prepare:
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                comparison.run_comparison(
                    Path(temporary), Path(temporary) / "invalid", include_satisfaction_only=True
                )
            prepare.assert_not_called()

    def test_satisfaction_only_comparison_reuses_folds_and_pairs_each_family_against_conditions(self):
        rows = expanded_records()
        for index, record in enumerate(rows):
            record["baseline_satisfaction"] = 2 + index / 20
        with patch.object(comparison, "candidate_grid", side_effect=tiny_grid):
            _, previous = comparison.compare_records(
                rows,
                audit(True),
                outer_folds=2,
                inner_folds=2,
                bootstrap_samples=20,
                include_random_forest=True,
                expanded_features=True,
            )
            artifact, report = comparison.compare_records(
                rows,
                audit(True),
                outer_folds=2,
                inner_folds=2,
                bootstrap_samples=20,
                include_random_forest=True,
                expanded_features=True,
                include_satisfaction_only=True,
            )
        self.assertEqual(report["protocol_version"], comparison.SATISFACTION_ONLY_PROTOCOL_VERSION)
        self.assertEqual(artifact["protocol_version"], comparison.SATISFACTION_ONLY_PROTOCOL_VERSION)
        self.assertEqual(report["feature_variants"]["satisfaction_only"], ["baseline_satisfaction"])
        self.assertIn("satisfaction_only", report["baseline_satisfaction_model_usage"])
        self.assertFalse(report["test_evaluated"])
        self.assertFalse(report["active_model_changed"])
        for strategy, metrics in previous["nested_oof_metrics"].items():
            if strategy != "selected_pipeline":
                self.assertEqual(metrics, report["nested_oof_metrics"][strategy])
        for before, after in zip(previous["folds"], report["folds"], strict=True):
            self.assertEqual(before["training_group_hash"], after["training_group_hash"])
            self.assertEqual(before["validation_group_hash"], after["validation_group_hash"])
        for family in ("ridge", "boosting", "random_forest"):
            comparison_row = report["baseline_satisfaction_ablation"]["families"][family]
            self.assertEqual(
                comparison_row["satisfaction_only_metrics"],
                report["nested_oof_metrics"][f"{family}_satisfaction_only"],
            )
            intervals = comparison_row["paired_cluster_bootstrap"]
            self.assertEqual(intervals["reference"], f"{family}_satisfaction_only")
            for variant in ("baseline_with_satisfaction", "expanded_with_satisfaction"):
                observed = report["nested_oof_metrics"][f"{family}_{variant}"]
                self.assertEqual(comparison_row["condition_model_metrics"][variant], observed)
                self.assertAlmostEqual(
                    intervals["intervals"][f"{family}_{variant}"]["rmse"]["estimate"],
                    observed["rmse"] - comparison_row["satisfaction_only_metrics"]["rmse"],
                )

    def test_expanded_grid_changes_inputs_without_changing_algorithm_options(self):
        for forests, count in ((False, 35), (True, 55)):
            original = comparison.candidate_grid(forests)
            expanded = comparison.candidate_grid(forests, True)
            self.assertEqual(len(expanded), count)
            self.assertEqual(expanded[: len(original)], original)
            self.assertEqual(len({item["id"] for item in expanded}), count)
            for variant in comparison.EXPANDED_VARIANTS:
                candidates = [item for item in expanded if item["variant"] == variant]
                baseline = [item for item in original if item["variant"] == "baseline"]
                self.assertEqual(
                    [(item["family"], item["parameters"]) for item in candidates],
                    [(item["family"], item["parameters"]) for item in baseline],
                )

    def test_expanded_run_keeps_original_metrics_and_declares_satisfaction_ablation(self):
        rows = expanded_records()
        with patch.object(comparison, "candidate_grid", side_effect=tiny_grid):
            _, original = comparison.compare_records(
                development_records(),
                audit(),
                outer_folds=2,
                inner_folds=2,
                bootstrap_samples=20,
                include_random_forest=True,
            )
            artifact, extended = comparison.compare_records(
                rows,
                audit(True),
                outer_folds=2,
                inner_folds=2,
                bootstrap_samples=20,
                include_random_forest=True,
                expanded_features=True,
            )
        self.assertEqual(extended["protocol_version"], comparison.EXPANDED_PROTOCOL_VERSION)
        self.assertEqual(artifact["protocol_version"], comparison.EXPANDED_PROTOCOL_VERSION)
        self.assertTrue(extended["expanded_features"])
        self.assertEqual(
            extended["baseline_satisfaction_model_usage"],
            ["baseline_with_satisfaction", "expanded_with_satisfaction"],
        )
        for variant, count in (
            ("baseline", 6),
            ("expanded", 9),
            ("baseline_with_satisfaction", 7),
            ("expanded_with_satisfaction", 10),
        ):
            self.assertEqual(len(extended["feature_variants"][variant]), count)
        for name in (
            *comparison.STRATEGIES,
            "random_forest_baseline",
            "random_forest_interactions",
            "original_ridge_recipe",
        ):
            self.assertEqual(original["nested_oof_metrics"][name], extended["nested_oof_metrics"][name])
        features = comparison._features(rows)
        self.assertEqual(features[0]["baseline_satisfaction"], rows[0]["baseline_satisfaction"])
        self.assertNotIn("baseline_satisfaction", rows[0]["features"])
        self.assertNotIn("followup_satisfaction", features[0])
        self.assertEqual(len(features[0]), 10)
        self.assertFalse(extended["test_evaluated"])
        for family in ("ridge", "boosting", "random_forest"):
            for variant in comparison.EXPANDED_VARIANTS:
                self.assertEqual(extended["nested_oof_metrics"][f"{family}_{variant}"]["count"], len(rows))

    def test_expanded_feature_audit_and_input_mode_must_agree_before_fitting(self):
        with patch.object(comparison, "fit_candidate") as fit:
            for rows, declaration, enabled in (
                (expanded_records(), audit(True), False),
                (development_records(), audit(), True),
                (development_records(), audit(True), True),
                (expanded_records(), audit(), False),
            ):
                with self.subTest(enabled=enabled, audit=declaration), self.assertRaises(ValueError):
                    comparison.compare_records(
                        rows,
                        declaration,
                        expanded_features=enabled,
                        outer_folds=2,
                        inner_folds=2,
                        bootstrap_samples=20,
                    )
            fit.assert_not_called()

    def test_forest_grid_preserves_original_candidates_and_adds_eight_fixed_configurations(self):
        original = comparison.candidate_grid()
        extended = comparison.candidate_grid(True)
        self.assertEqual(len(original), 14)
        self.assertEqual(len(extended), 22)
        self.assertEqual(extended[:14], original)
        self.assertEqual(len({item["id"] for item in extended}), len(extended))
        for item in extended[14:]:
            self.assertEqual(item["family"], "random_forest")
            self.assertIn(item["variant"], ("baseline", "interactions"))
            self.assertIn(item["parameters"]["max_depth"], (3, 6))
            self.assertIn(item["parameters"]["min_samples_leaf"], (5, 20))
            self.assertEqual(item["parameters"]["n_estimators"], 200)
            self.assertEqual(item["parameters"]["max_features"], 1.0)

    def test_forest_extension_keeps_same_folds_and_existing_strategy_metrics(self):
        rows = development_records()
        with patch.object(comparison, "candidate_grid", side_effect=tiny_grid):
            _, original = comparison.compare_records(
                rows, audit(), outer_folds=2, inner_folds=2, bootstrap_samples=20
            )
            artifact, extended = comparison.compare_records(
                rows,
                audit(),
                outer_folds=2,
                inner_folds=2,
                bootstrap_samples=20,
                include_random_forest=True,
            )
        self.assertEqual(extended["protocol_version"], comparison.FOREST_PROTOCOL_VERSION)
        self.assertTrue(extended["include_random_forest"])
        self.assertFalse(extended["test_evaluated"])
        self.assertFalse(extended["active_model_changed"])
        self.assertEqual(artifact["protocol_version"], comparison.FOREST_PROTOCOL_VERSION)
        for name in (*comparison.STRATEGIES, "original_ridge_recipe", "training_mean", "training_median"):
            self.assertEqual(original["nested_oof_metrics"][name], extended["nested_oof_metrics"][name])
        for before, after in zip(original["folds"], extended["folds"], strict=True):
            self.assertEqual(before["training_group_hash"], after["training_group_hash"])
            self.assertEqual(before["validation_group_hash"], after["validation_group_hash"])
            for strategy in ("random_forest_baseline", "random_forest_interactions"):
                self.assertTrue(after["selected_candidates"][strategy].startswith("fixture_random_forest"))
        for name in ("random_forest_baseline", "random_forest_interactions"):
            self.assertEqual(extended["nested_oof_metrics"][name]["count"], len(rows))

    def test_grouped_folds_are_deterministic_disjoint_and_cover_each_employee_once(self):
        rows = development_records()
        folds = comparison.grouped_folds(rows, 3, 42)
        repeated = comparison.grouped_folds(rows, 3, 42)
        validation_people = []
        for (train, validation), (again_train, again_validation) in zip(folds, repeated, strict=True):
            np.testing.assert_array_equal(train, again_train)
            np.testing.assert_array_equal(validation, again_validation)
            training_groups = {rows[index]["baseline_cluster"] for index in train}
            validation_groups = {rows[index]["baseline_cluster"] for index in validation}
            self.assertFalse(training_groups & validation_groups)
            self.assertEqual(set(train) | set(validation), set(range(len(rows))))
            validation_people.extend(validation.tolist())
        self.assertEqual(sorted(validation_people), list(range(len(rows))))
        for count in (1, 13, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                comparison.grouped_folds(rows, count, 42)

    def test_reserved_test_rows_and_non_development_inputs_fail_before_fitting(self):
        rows = development_records()
        reserved = next(
            f"tomo:{index}"
            for index in range(1, 100)
            if wfhs.cluster_partition(f"tomo:{index}", 42) == "test"
        )
        rows[0]["baseline_cluster"] = reserved
        with patch.object(comparison, "fit_candidate") as fit:
            with self.assertRaisesRegex(ValueError, "Original test groups"):
                comparison.compare_records(rows, audit(), outer_folds=2, inner_folds=2, bootstrap_samples=20)
            for declaration in (
                {**audit(), "dataset": "leef"},
                {**audit(), "data_partition": "all_eligible_pairs"},
            ):
                with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                    comparison.compare_records(development_records(), declaration)
            fit.assert_not_called()

    def test_development_import_skips_reserved_outcomes_before_numeric_parsing(self):
        development = next(
            str(index) for index in range(1, 100) if wfhs.cluster_partition(f"tomo:{index}", 42) != "test"
        )
        reserved = next(
            str(index) for index in range(1, 100) if wfhs.cluster_partition(f"tomo:{index}", 42) == "test"
        )
        source_rows = [survey_row("fictional-development", wave, development) for wave in (1, 3)]
        for wave in (1, 3):
            hidden = survey_row("fictional-reserved", wave, reserved)
            hidden[wfhs.LABEL] = "must-not-parse-this-outcome"
            hidden[wfhs.LABEL_ITEMS[0]] = "must-not-parse-this-item"
            source_rows.append(hidden)
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            source = write_survey(raw, source_rows)
            original = source.read_bytes()
            rows, preparation = wfhs.prepare_dataset(raw, "tomo", development_only=True)
            self.assertEqual([row["person_id"] for row in rows], ["tomo:fictional-development"])
            self.assertEqual(preparation["data_partition"], "original_train_validation_only")
            self.assertEqual(preparation["exclusions"]["reserved_original_test_baseline_employee"], 1)
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(ValueError):
                wfhs.prepare_dataset(raw, "tomo")
            with self.assertRaises(ValueError):
                wfhs.prepare_dataset(raw, "leef", development_only=True)

    def test_inner_fits_and_preprocessing_receive_only_their_training_fold(self):
        rows = development_records()
        by_hours = {row["features"]["hours_worked_last_week"]: row for row in rows}
        allowed = []
        for training, validation in comparison.grouped_folds(rows, 2, 42):
            allowed.append(
                (
                    {rows[index]["features"]["hours_worked_last_week"] for index in training},
                    {rows[index]["features"]["hours_worked_last_week"] for index in validation},
                )
            )
        calls = []

        def checked_fit(features, target, spec, seed=42):
            training_hours = {row["hours_worked_last_week"] for row in features}
            matching = [validation for training, validation in allowed if training == training_hours]
            self.assertEqual(len(matching), 1)
            np.testing.assert_array_equal(
                target, [by_hours[row["hours_worked_last_week"]]["followup_satisfaction"] for row in features]
            )
            fitted = fit_candidate(features, target, spec, seed=seed)
            stats = fitted.encoder.numeric_stats["hours_worked_last_week"]
            self.assertEqual(stats["minimum"], min(training_hours))
            self.assertEqual(stats["maximum"], max(training_hours))

            class CheckedPrediction:
                def predict(inner_self, held_out):
                    held_out_hours = {row["hours_worked_last_week"] for row in held_out}
                    self.assertEqual(held_out_hours, matching[0])
                    self.assertFalse(held_out_hours & training_hours)
                    return fitted.predict(held_out)

            calls.append(training_hours)
            return CheckedPrediction()

        with patch.object(comparison, "fit_candidate", side_effect=checked_fit):
            tuning = comparison.tune_candidates(rows, tiny_grid(), 2, 42, "rmse")
        self.assertEqual(len(calls), 2 * len(tiny_grid()))
        self.assertEqual(len(tuning), len(tiny_grid()))

    def test_nested_selection_sees_outer_training_only_then_refits_development_data(self):
        rows = development_records()
        expected = [
            {rows[index]["person_id"] for index in training}
            for training, _ in comparison.grouped_folds(rows, 2, 42)
        ]
        expected.append({row["person_id"] for row in rows})
        calls = []
        real_tune = comparison.tune_candidates

        def checked_tune(training, grid, folds, seed, metric):
            identities = {row["person_id"] for row in training}
            self.assertEqual(identities, expected[len(calls)])
            calls.append(identities)
            return real_tune(training, grid, folds, seed, metric)

        with (
            patch.object(comparison, "candidate_grid", side_effect=tiny_grid),
            patch.object(comparison, "tune_candidates", side_effect=checked_tune),
        ):
            artifact, report = comparison.compare_records(
                rows, audit(), outer_folds=2, inner_folds=2, bootstrap_samples=20
            )
        self.assertEqual(len(calls), 3)
        self.assertFalse(report["test_evaluated"])
        self.assertFalse(report["active_model_changed"])
        self.assertFalse(artifact["original_test_evaluated"])
        self.assertEqual(artifact["usage"], "experimental_offline_candidate_not_promoted")

    def test_pooled_metrics_use_every_employee_once_and_fold_training_baselines(self):
        rows = development_records()
        original = copy.deepcopy(rows)
        target = np.asarray([row["followup_satisfaction"] for row in rows])
        expected_mean = np.empty(len(rows))
        expected_median = np.empty(len(rows))
        for training, validation in comparison.grouped_folds(rows, 2, 42):
            expected_mean[validation] = np.mean(target[training])
            expected_median[validation] = np.median(target[training])
        with patch.object(comparison, "candidate_grid", side_effect=tiny_grid):
            _, report = comparison.compare_records(
                rows, audit(), outer_folds=2, inner_folds=2, bootstrap_samples=20
            )
        for name, expected in (("training_mean", expected_mean), ("training_median", expected_median)):
            self.assertEqual(report["nested_oof_metrics"][name], regression_metrics(target, expected))
        self.assertTrue(
            all(metrics["count"] == len(rows) for metrics in report["nested_oof_metrics"].values())
        )
        self.assertEqual(sum(fold["validation_people"] for fold in report["folds"]), len(rows))
        self.assertEqual(sum(report["nested_selector_counts"].values()), 2)
        self.assertEqual(report["development_people"], len(rows))
        self.assertEqual(rows, original)

    def test_identical_paired_predictions_have_zero_cluster_bootstrap_deltas(self):
        rows = development_records()
        predictions = np.full(len(rows), 3.0)
        interval = comparison.paired_cluster_intervals(
            rows,
            {"original_ridge_recipe": predictions, "same_predictions": predictions.copy()},
            20,
            42,
        )
        self.assertEqual(interval["resamples"], 20)
        self.assertFalse(interval["includes_refitting_uncertainty"])
        self.assertEqual(interval["method"], "paired_whole_cluster_resampling_with_multiplicity")
        for metric in ("mae", "rmse"):
            self.assertEqual(
                interval["intervals"]["same_predictions"][metric], {"estimate": 0, "lower": 0, "upper": 0}
            )
        with self.assertRaises(ValueError):
            comparison.paired_cluster_intervals(rows, {"original_ridge_recipe": predictions}, 19, 42)

    def test_published_protocol_and_json_candidate_replay_preserve_selected_model(self):
        rows = development_records()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "fictional-raw"
            raw.mkdir()
            for name in ("36158-Codebook.pdf", "36158-User_guide.pdf", "TermsOfUse.html"):
                (raw / name).write_text("Fictional comparison documentation only.\n")
            active = root / "selected-model-b" / "model.json"
            active.parent.mkdir()
            active.write_text("Existing selected Model B fixture; preserve unchanged.\n")
            saved = active.read_bytes()
            output = root / "comparison"
            with (
                patch.object(comparison, "prepare_dataset", return_value=(rows, audit())) as prepare,
                patch.object(comparison, "candidate_grid", side_effect=tiny_grid),
            ):
                report = comparison.run_comparison(
                    raw, output, outer_folds=2, inner_folds=2, bootstrap_samples=20
                )
            prepare.assert_called_once_with(raw, "tomo", development_only=True)
            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {"protocol.json", "experimental_model.json", "report.json"},
            )
            protocol = json.loads((output / "protocol.json").read_text())
            artifact = json.loads((output / "experimental_model.json").read_text())
            self.assertEqual(protocol["candidate_grid"], report["candidate_grid"])
            self.assertEqual(protocol["original_split_seed"], 42)
            self.assertFalse(protocol["reserved_test_evaluated"])
            self.assertFalse(report["active_model_changed"])
            self.assertEqual(protocol["versions"], report["versions"])
            self.assertEqual(active.read_bytes(), saved)
            features = [row["features"] for row in rows]
            replay = predict_artifact(artifact["fitted_candidate"], features)
            spec = report["experimental_candidate"]
            refit = fit_candidate(features, np.asarray([row["followup_satisfaction"] for row in rows]), spec)
            np.testing.assert_allclose(replay, refit.predict(features), atol=1e-10, rtol=0)

    def test_satisfaction_only_publication_freezes_the_same_protocol_and_import_mode(self):
        rows = expanded_records()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "fictional-raw"
            raw.mkdir()
            for name in ("36158-Codebook.pdf", "36158-User_guide.pdf", "TermsOfUse.html"):
                (raw / name).write_text("Fictional comparison documentation only.\n")
            output = root / "comparison-v4"
            with (
                patch.object(comparison, "prepare_dataset", return_value=(rows, audit(True))) as prepare,
                patch.object(comparison, "candidate_grid", side_effect=tiny_grid),
            ):
                report = comparison.run_comparison(
                    raw,
                    output,
                    outer_folds=2,
                    inner_folds=2,
                    bootstrap_samples=20,
                    include_random_forest=True,
                    expanded_features=True,
                    include_satisfaction_only=True,
                )
            prepare.assert_called_once_with(raw, "tomo", development_only=True, expanded_features=True)
            protocol = json.loads((output / "protocol.json").read_text())
            artifact = json.loads((output / "experimental_model.json").read_text())
            self.assertEqual(protocol["protocol_version"], comparison.SATISFACTION_ONLY_PROTOCOL_VERSION)
            self.assertTrue(protocol["include_satisfaction_only"])
            self.assertEqual(protocol["feature_variants"]["satisfaction_only"], ["baseline_satisfaction"])
            self.assertEqual(protocol["candidate_grid"], report["candidate_grid"])
            self.assertFalse(protocol["reserved_test_evaluated"])
            self.assertFalse(artifact["original_test_evaluated"])
            restored = predict_artifact(artifact["fitted_candidate"], comparison._features(rows))
            self.assertEqual(restored.shape, (len(rows),))

    def test_failed_comparison_publishes_nothing_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "fictional-raw"
            raw.mkdir()
            for name in ("36158-Codebook.pdf", "36158-User_guide.pdf", "TermsOfUse.html"):
                (raw / name).write_text("Fictional comparison documentation only.\n")
            output = root / "failed-run"
            with (
                patch.object(comparison, "prepare_dataset", return_value=(development_records(), audit())),
                patch.object(comparison, "compare_records", side_effect=ValueError("invalid fixture fit")),
            ):
                with self.assertRaisesRegex(ValueError, "invalid fixture fit"):
                    comparison.run_comparison(raw, output, outer_folds=2, inner_folds=2, bootstrap_samples=20)
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".tomo-comparison-*")))
            output.mkdir()
            sentinel = output / "preserve.txt"
            sentinel.write_text("Existing experiment.\n")
            with patch.object(comparison, "prepare_dataset") as prepare:
                with self.assertRaisesRegex(ValueError, "new comparison directory"):
                    comparison.run_comparison(raw, output)
                prepare.assert_not_called()
            self.assertEqual(sentinel.read_text(), "Existing experiment.\n")


if __name__ == "__main__":
    unittest.main()
