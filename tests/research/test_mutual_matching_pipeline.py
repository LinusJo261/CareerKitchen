"""Fictional introduction fixtures verify software, not actual matching quality."""

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.mutual_matching_features import FEATURE_NAMES
from scripts.mutual_matching_research import (
    FEATURE_VERSION,
    TARGET,
    binary_metrics,
    demo,
    identity_group,
    initialize,
    label_record,
    load_records,
    predict,
    split_records,
    timestamp,
    train,
    validate_manifest,
)


def fixture_manifest():
    return {
        "schema_version": 1, "target": TARGET, "feature_version": FEATURE_VERSION, "horizon_days": 14,
        "source": {"kind": "fictional_fixture", "dataset": "fictional_unit_test",
                   "source_version": "fixture-v1", "exported_at": "2025-01-01T00:00:00Z"},
    }


def fixture_row():
    return {
        "cycle_id": "fictional-cycle", "candidate_id": "fictional-candidate",
        "vacancy_id": "fictional-vacancy", "organization_id": "fictional-org",
        "candidate_version": 1, "vacancy_version": 1, "policy_version": "fictional-policy-v1",
        "feature_as_of": "2020-01-01T00:00:00Z", "first_exposed_at": "2020-01-02T00:00:00Z",
        "first_mover": "candidate", "observed_at": "2020-02-01T00:00:00Z",
        "eligibility": "ELIGIBLE", "observation_status": "OBSERVABLE",
        "features": dict.fromkeys(FEATURE_NAMES, .5),
        "decisions": {
            "candidate": {"status": "INTERESTED", "issued_at": "2020-01-02T00:00:00Z",
                          "answered_at": "2020-01-03T00:00:00Z"},
            "employer": {"status": "INTERESTED", "issued_at": "2020-01-04T00:00:00Z",
                         "answered_at": "2020-01-05T00:00:00Z"},
        },
    }


def unissued():
    return {"status": "NOT_ISSUED", "issued_at": None, "answered_at": None}


def fixture_identity(kind, group):
    return next(f"fictional-{kind}-{index}" for index in range(10000)
                if identity_group(kind, f"fictional-{kind}-{index}", 42) == group)


class MutualOutcomeTests(unittest.TestCase):
    def test_only_two_explicit_opt_ins_are_positive_for_either_first_mover(self):
        row = fixture_row()
        for first in ("candidate", "employer"):
            with self.subTest(first=first):
                row["first_mover"] = first
                if first == "employer":
                    row["decisions"]["candidate"], row["decisions"]["employer"] = (
                        row["decisions"]["employer"], row["decisions"]["candidate"],
                    )
                record, reason = label_record(row, 14)
                self.assertIsNone(reason)
                self.assertEqual(record["label"], 1)
                self.assertEqual(record["label_observed_at"], timestamp("2020-01-05T00:00:00Z"))

    def test_explicit_pass_by_either_side_is_negative(self):
        for side in ("candidate", "employer"):
            row = fixture_row()
            row["decisions"][side]["status"] = "PASSED"
            if side == "candidate":
                row["decisions"]["employer"] = unissued()
            record, reason = label_record(row, 14)
            self.assertIsNone(reason)
            self.assertEqual(record["label"], 0)

    def test_one_opt_in_unanswered_expired_or_cancelled_is_not_negative(self):
        for status in ("NOT_ISSUED", "PENDING", "EXPIRED", "CANCELLED"):
            row = fixture_row()
            row["decisions"]["employer"] = unissued() if status == "NOT_ISSUED" else {
                "status": status, "issued_at": "2020-01-04T00:00:00Z", "answered_at": None,
            }
            record, reason = label_record(row, 14)
            self.assertIsNotNone(reason)
            self.assertNotIn("label", record)

    def test_changed_terms_withdrawal_and_ineligibility_are_excluded(self):
        for name, value in (("observation_status", "TERMS_CHANGED"), ("observation_status", "CANCELLED"),
                            ("observation_status", "WITHDRAWN"), ("eligibility", "INELIGIBLE"),
                            ("eligibility", "NEEDS_CLARIFICATION")):
            row = fixture_row()
            row[name] = value
            record, reason = label_record(row, 14)
            self.assertIsNotNone(reason)
            self.assertNotIn("label", record)

    def test_outcome_horizon_is_explicit_and_late_outcomes_are_excluded(self):
        for status in ("INTERESTED", "PASSED"):
            row = fixture_row()
            row["decisions"]["employer"].update(status=status, answered_at="2020-01-17T00:00:00Z")
            _, reason = label_record(row, 14)
            self.assertEqual(reason, "outside_horizon")
            record, reason = label_record(row, 30)
            self.assertIsNone(reason)
            self.assertEqual(record["label"], int(status == "INTERESTED"))

    def test_future_features_invalid_issuance_and_impossible_decisions_fail(self):
        invalid = []
        row = fixture_row()
        row["feature_as_of"] = "2020-01-03T00:00:00Z"
        invalid.append(row)
        row = fixture_row()
        row["decisions"]["employer"]["issued_at"] = "2020-01-02T00:00:00Z"
        invalid.append(row)
        row = fixture_row()
        row["decisions"]["candidate"]["status"] = "PASSED"
        invalid.append(row)
        row = fixture_row()
        row["decisions"]["candidate"]["answered_at"] = None
        invalid.append(row)
        row = fixture_row()
        row["observed_at"] = "2020-01-03T00:00:00Z"
        invalid.append(row)
        row = fixture_row()
        row["decisions"]["employer"]["status"] = "PENDING"
        invalid.append(row)
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                label_record(row, 14)

    def test_current_pair_interest_and_extra_predictors_are_forbidden(self):
        for feature in ("candidate_interested", "employer_interested", "candidate_id", "satisfaction"):
            row = fixture_row()
            row["features"][feature] = 1
            with self.subTest(feature=feature), self.assertRaisesRegex(ValueError, "ten declared"):
                label_record(row, 14)

    def test_duplicate_cycles_and_post_export_observations_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fictional.jsonl"
            row = fixture_row()
            path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "Duplicate introduction"):
                load_records(path, fixture_manifest())
            row["observed_at"] = "2026-01-01T00:00:00Z"
            path.write_text(json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "export timestamp"):
                load_records(path, fixture_manifest())

    def test_satisfaction_and_synthetic_relevance_are_not_mutual_interest_sources(self):
        for kind in ("survey_export", "synthetic_relevance"):
            manifest = fixture_manifest()
            manifest["source"]["kind"] = kind
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "introduction outcomes"):
                validate_manifest(manifest)
        manifest = fixture_manifest()
        manifest["target"] = "reported_job_satisfaction"
        with self.assertRaisesRegex(ValueError, "mutual opt-in"):
            validate_manifest(manifest)


class MutualSplitAndMetricsTests(unittest.TestCase):
    def test_both_identities_are_disjoint_and_future_training_outcomes_excluded(self):
        rows = []
        for group, year in (("train", 2000), ("validation", 2010), ("test", 2020)):
            row = {
                "candidate_id": fixture_identity("candidate", group),
                "vacancy_id": fixture_identity("vacancy", group),
                "first_exposed_at": timestamp(f"{year}-01-01T00:00:00Z"),
                "label_observed_at": timestamp(f"{year}-01-02T00:00:00Z"),
                "observed_at": timestamp(f"{year}-01-03T00:00:00Z"),
            }
            rows.append(row)
        # An earlier answer does not make later status/exclusion information known.
        future = {**rows[0], "observed_at": timestamp("2005-01-01T00:00:00Z")}
        cross_group = {**rows[1], "vacancy_id": rows[0]["vacancy_id"]}
        groups, diagnostic = split_records([*rows, future, cross_group], 42,
                                          "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
        self.assertEqual(diagnostic["counts"], {"train": 1, "validation": 1, "test": 1})
        self.assertEqual(diagnostic["outside_group_time_cohort"], 2)
        for key in ("candidate_id", "vacancy_id"):
            identities = [{row[key] for row in group} for group in groups.values()]
            self.assertTrue(identities[0].isdisjoint(identities[1] | identities[2]))
            self.assertTrue(identities[1].isdisjoint(identities[2]))

    def test_metrics_reveal_majority_only_prediction_and_probability_quality(self):
        labels = np.array([0, 0, 0, 1])
        result = binary_metrics(labels, np.array([.1, .1, .1, .1]))
        self.assertEqual(result["accuracy"], .75)
        self.assertEqual(result["balanced_accuracy"], .5)
        self.assertEqual(result["recall"], 0)
        self.assertIsNone(result["precision"])
        better = binary_metrics(labels, np.array([.1, .1, .1, .9]))
        self.assertLess(better["log_loss"], result["log_loss"])
        self.assertLess(better["brier_score"], result["brier_score"])
        self.assertEqual(sum(item["count"] for item in better["calibration_bins"]), 4)
        self.assertIsNone(binary_metrics(np.ones(2), np.ones(2))["balanced_accuracy"])
        for probabilities in (np.array([float("nan")]), np.array([1.1])):
            with self.assertRaises(ValueError):
                binary_metrics(np.array([1]), probabilities)


class MutualPipelineTests(unittest.TestCase):
    def test_no_model_returns_no_invented_probability_and_eligibility_abstains(self):
        snapshot = {"schema_version": 1, "eligibility": "ELIGIBLE", "features": fixture_row()["features"]}
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "missing_model.json"
            self.assertEqual(predict(model, snapshot)["status"], "NOT_TRAINED")
            self.assertIsNone(predict(model, snapshot)["match_probability"])
            for state in ("INELIGIBLE", "NEEDS_CLARIFICATION"):
                snapshot["eligibility"] = state
                self.assertEqual(predict(model, snapshot)["status"], "ABSTAIN")
                self.assertIsNone(predict(model, snapshot)["match_probability"])

    def test_init_creates_empty_inputs_and_preserves_existing_work(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / "input"
            initialize(path)
            self.assertEqual((path / "introductions.jsonl").read_text(), "")
            before = {item.name: item.read_bytes() for item in path.iterdir()}
            with self.assertRaisesRegex(ValueError, "empty input"):
                initialize(path)
            self.assertEqual(before, {item.name: item.read_bytes() for item in path.iterdir()})
            with self.assertRaisesRegex(ValueError, "actual export"):
                validate_manifest(json.loads((path / "manifest.json").read_text()))

    def test_training_replay_and_prediction_are_target_specific_and_fictional(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / "fictional"
            report = demo(path)
            model_path = path / "evaluation/fictional_match_model.json"
            artifact = json.loads(model_path.read_text())
            self.assertTrue(report["fictional_data"])
            self.assertTrue(artifact["fictional_data"])
            self.assertFalse(artifact["live_execution"])
            self.assertEqual(artifact["target"], TARGET)
            self.assertNotIn("reported_job_satisfaction", model_path.read_text())
            self.assertNotIn("fictional-candidate", model_path.read_text())
            self.assertEqual(artifact["model"]["class_order"], ["explicit_pass", "mutual_opt_in"])
            again = train(path / "fictional_introductions.jsonl", path / "fictional_manifest.json", path / "replay",
                          "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
            self.assertEqual(report, again)
            self.assertEqual(model_path.read_bytes(), (path / "replay/fictional_match_model.json").read_bytes())
            snapshot = {"schema_version": 1, "eligibility": "ELIGIBLE", "features": fixture_row()["features"]}
            result = predict(model_path, snapshot)
            self.assertTrue(result["fictional_data"])
            self.assertEqual(result["status"], "EXPERIMENTAL_UNCALIBRATED")
            self.assertTrue(0 <= result["match_probability"] <= 1)
            snapshot["features"] = dict.fromkeys(FEATURE_NAMES)
            self.assertEqual(predict(model_path, snapshot)["status"], "ABSTAIN")
            with self.assertRaises(FileExistsError):
                train(path / "fictional_introductions.jsonl", path / "fictional_manifest.json", path / "evaluation",
                      "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")

    def test_prediction_rejects_outcomes_foreign_targets_and_corrupt_encoders(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / "fictional"
            demo(path)
            model = path / "evaluation/fictional_match_model.json"
            original = json.loads(model.read_text())
            snapshot = {"schema_version": 1, "eligibility": "ELIGIBLE", "features": fixture_row()["features"]}
            with self.assertRaisesRegex(ValueError, "outcomes are forbidden"):
                predict(model, {**snapshot, "candidate_interested": True})
            mutations = [lambda a: a.update(target="reported_job_satisfaction"),
                         lambda a: a["encoder"]["numeric_stats"]["required_skill_coverage"].update(median=float("nan")),
                         lambda a: a["model"]["class_order"].reverse(),
                         lambda a: a["model"]["feature_names"].reverse()]
            for mutation in mutations:
                altered = deepcopy(original)
                mutation(altered)
                model.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    predict(model, snapshot)

    def test_wholly_unobserved_features_do_not_use_validation_data_for_imputation(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory) / "fictional"
            demo(path)
            input_path = path / "fictional_introductions.jsonl"
            rows = [json.loads(line) for line in input_path.read_text().splitlines()]
            for row in rows:
                if "fictional-train-" in row["cycle_id"]:
                    row["features"]["candidate_schedule_preference_alignment"] = None
            input_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            report = train(input_path, path / "fictional_manifest.json", path / "sparse",
                           "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z")
            self.assertEqual(report["unobserved_training_features"], ["candidate_schedule_preference_alignment"])
            self.assertNotIn("candidate_schedule_preference_alignment", report["active_features"])


if __name__ == "__main__":
    unittest.main()
