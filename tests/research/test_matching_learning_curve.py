"""Fictional fixtures verify validation boundaries, not actual hiring quality."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts import matching_learning_curve as curve
from scripts.matching_research import resume_partitions
from scripts.matching_research_core import LogisticModel, split_jobs
from tests.research.test_research_pipeline import fixture_tables


class LearningCurveTests(unittest.TestCase):
    def run_fixture(self):
        return curve.compare_tables(
            fixture_tables(),
            sizes=(3, 8, "all"),
            penalties=(0.1, 0.01),
            epochs=30,
            k=5,
            per_class=3,
        )

    def test_training_sizes_are_nested_and_complete_template_groups_stay_together(self):
        jobs = fixture_tables()["jobs"][:10]
        duplicate = copy.deepcopy(jobs[0])
        duplicate["job_id"] = "duplicate-template"
        jobs.append(duplicate)
        plan = curve.nested_training_sets(jobs, (3, 6, "all"), 42)
        repeated = curve.nested_training_sets(list(reversed(jobs)), (3, 6, "all"), 42)
        self.assertEqual(plan, repeated)
        previous = set()
        for step in plan:
            ids = {job["job_id"] for job in step["jobs"]}
            self.assertLessEqual(previous, ids)
            self.assertEqual(jobs[0]["job_id"] in ids, duplicate["job_id"] in ids)
            previous = ids
        self.assertEqual(len(plan[-1]["jobs"]), len(jobs))
        for sizes in ((), (0,), (True,), (99,), (3, 2), ("all", 3), (3, 3)):
            with self.subTest(sizes=sizes), self.assertRaises(ValueError):
                curve.nested_training_sets(jobs, sizes, 42)

    def test_required_only_mask_removes_other_inputs_without_mutating_source(self):
        x = np.asarray([[0.1, 1, 1, 1, 0.5], [0.9, 0, 0, 0, 0.2]])
        original = x.copy()
        masked = curve.mask_features(x, "required_only")
        np.testing.assert_array_equal(masked[:, 0], x[:, 0])
        np.testing.assert_array_equal(masked[:, 1:], 0)
        np.testing.assert_array_equal(original, x)
        with self.assertRaises(ValueError):
            curve.mask_features(x, "invented")

    def test_no_test_jobs_or_resumes_enter_feature_scoring_sampling_or_fitting(self):
        tables = fixture_tables()
        partitions = split_jobs(tables["jobs"], 42)
        corpora, _ = resume_partitions(tables["resumes"], 42)
        forbidden_jobs = {job["job_id"] for job in partitions["test"]}
        forbidden_resumes = set(corpora["test"].ids)
        real_features, real_sample = curve.feature_matrix, curve.sample_training_indices
        calls = []

        def checked_features(job, corpus, indices=None):
            self.assertNotIn(job["job_id"], forbidden_jobs)
            self.assertFalse(set(corpus.ids) & forbidden_resumes)
            calls.append(job["job_id"])
            return real_features(job, corpus, indices)

        def checked_sample(job, corpus, *args):
            self.assertNotIn(job["job_id"], forbidden_jobs)
            self.assertFalse(set(corpus.ids) & forbidden_resumes)
            return real_sample(job, corpus, *args)

        with (
            patch.object(curve, "feature_matrix", side_effect=checked_features),
            patch.object(curve, "sample_training_indices", side_effect=checked_sample),
        ):
            artifact, report = self.run_fixture()
        self.assertTrue(calls)
        self.assertFalse(report["test_scored"])
        self.assertFalse(artifact["test_scored"])
        self.assertEqual(report["selection_pool"], "unseen_validation_resumes")
        self.assertEqual(report["learning_curve"][-1]["training_jobs"], len(partitions["train"]))
        self.assertEqual(
            report["validation_pools"][curve.PRIMARY_POOL]["candidate_pool"], len(corpora["validation"].ids)
        )

    def test_parameter_selection_uses_pair_loss_even_when_recall_favors_other_features(self):
        def misleading_recall(pool, method, k):
            required_only = isinstance(method, LogisticModel) and not any(method.weights[1:])
            return {"macro_mean": {"listed_recall_at_k": 1.0 if required_only else 0.0}}

        with patch.object(curve, "ranking_summary", side_effect=misleading_recall):
            _, report = self.run_fixture()
        self.assertEqual(report["selected_candidate"]["feature_variant"], "all_five")
        for point in report["learning_curve"]:
            expected = min(point["candidates"], key=lambda item: item["primary_validation_pair_log_loss"])
            for variant in curve.FEATURE_VARIANTS:
                candidates = [item for item in point["candidates"] if item["feature_variant"] == variant]
                self.assertEqual(
                    point["selected_by_feature_variant"][variant],
                    min(candidates, key=lambda item: item["primary_validation_pair_log_loss"]),
                )
            self.assertEqual(
                point["validation"][curve.PRIMARY_POOL]["required_only"]["ranking"]["macro_mean"][
                    "listed_recall_at_k"
                ],
                1,
            )
        self.assertEqual(report["selected_candidate"], expected)

    def test_fixed_validation_samples_reproducibility_and_json_model_replay(self):
        artifact, report = self.run_fixture()
        repeated_artifact, repeated_report = self.run_fixture()
        self.assertEqual(artifact, repeated_artifact)
        self.assertEqual(report, repeated_report)
        self.assertEqual(report["selection_size_policy"], "largest_declared_training_size")
        for pool in report["validation_pools"].values():
            self.assertEqual(len(pool["pair_fingerprint"]), 64)
            self.assertGreater(pool["sampled_pairs"], 0)
        model = curve.restore_model(json.loads(json.dumps(artifact, allow_nan=False)))
        query = np.asarray([[0, 0.5, 1, 0, 0], [1, 1, 1, 1, 0.5]])
        np.testing.assert_array_equal(
            model.scores(query),
            LogisticModel(artifact["fitted_model"]["weights"], artifact["fitted_model"]["bias"]).scores(
                query
            ),
        )
        self.assertEqual(artifact["fitted_model"]["output"], "uncalibrated_logit")
        self.assertIsNone(artifact["fitted_model"]["calibration"])
        for name, changed in (("target", "mutual_match"), ("test_scored", True), ("live_execution", True)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                curve.restore_model({**artifact, name: changed})

    def test_extreme_scores_use_finite_stable_loss(self):
        model = LogisticModel([600, 0, 0, 0, 0], -300)
        x = np.zeros((2, 5))
        x[1, 0] = 1
        self.assertTrue(np.isfinite(curve.pair_log_loss(model, x, np.asarray([0, 1]))))
        with self.assertRaises(ValueError):
            curve.pair_log_loss(model, x, np.asarray([1, 1]))

    def test_artifact_contract_rejects_malformed_or_relabelled_coefficients(self):
        artifact, _ = self.run_fixture()
        for mutation in (
            lambda value: value.update(schema_version=True),
            lambda value: value.update(usage="live_matching"),
            lambda value: value.update(fitted_model=None),
            lambda value: value["fitted_model"].pop("weights"),
            lambda value: value["fitted_model"].update(bias=None),
            lambda value: value["fitted_model"].update(output="match_probability"),
            lambda value: value["fitted_model"].pop("calibration"),
            lambda value: value["fitted_model"].update(weights=[float("nan")] * 5),
        ):
            changed = copy.deepcopy(artifact)
            mutation(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                curve.restore_model(changed)

    def test_invalid_counts_and_penalties_fail_before_fitting(self):
        for settings in (
            {"seed": True},
            {"epochs": 0},
            {"per_class": 0},
            {"k": 0},
            {"penalties": ()},
            {"penalties": (0.1, 0.1)},
            {"penalties": (float("nan"),)},
        ):
            with self.subTest(settings=settings), patch.object(curve, "fit_logistic") as fit:
                with self.assertRaises(ValueError):
                    curve.compare_tables(fixture_tables(), sizes=(3, "all"), **settings)
                fit.assert_not_called()

    def test_atomic_publication_preserves_prior_results_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "new-run"
            sentinel = root / "prior-model.json"
            sentinel.write_text("preserve existing experiment\n")
            options = {"sizes": (3, "all"), "penalties": (0.1,), "epochs": 20, "k": 5, "per_class": 3}
            with patch.object(curve, "load_tables", return_value=(fixture_tables(), {"fixture": "abc"})):
                report = curve.run_experiment(output, **options)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"protocol.json", "experimental_model.json", "report.json"},
            )
            protocol = json.loads((output / "protocol.json").read_text())
            self.assertEqual(protocol["file_sha256"], report["file_sha256"])
            self.assertEqual(protocol["selection_pool"], report["selection_pool"])
            self.assertEqual(sentinel.read_text(), "preserve existing experiment\n")
            with (
                patch.object(curve, "load_tables") as load,
                self.assertRaisesRegex(ValueError, "new directory"),
            ):
                curve.run_experiment(output, **options)
            load.assert_not_called()
            failed = root / "failed"
            with (
                patch.object(curve, "load_tables", return_value=(fixture_tables(), {})),
                patch.object(curve, "compare_tables", side_effect=ValueError("fixture failure")),
                self.assertRaisesRegex(ValueError, "fixture failure"),
            ):
                curve.run_experiment(failed, **options)
            self.assertFalse(failed.exists())
            self.assertFalse(list(root.glob(".model-a-curve-*")))


if __name__ == "__main__":
    unittest.main()
