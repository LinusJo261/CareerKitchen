"""Fictional paired reports validate software, never real satisfaction quality."""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

from scripts.mutual_matching_features import FEATURE_NAMES
from scripts.prepare_joint_satisfaction import EXAMPLE_MAPPING, initialize, prepare
from scripts.satisfaction_model import SatisfactionModel, TabularEncoder
from scripts.satisfaction_research import load_records, month, person_group, split_records, train, validate_mapping


def fixture_mapping():
    mapping = json.loads(EXAMPLE_MAPPING.read_text())
    mapping["source"] = {
        "kind": "fictional_fixture", "dataset": "fictional_direct_paired_unit_test",
        "release": "fixture-v1", "codebook_url": "fixture://direct-paired-rating-definitions",
    }
    return mapping


def fixture_row(person="fictional-person", employer="fictional-employer", started="2000-01",
                reference="2000-07", employee_value="5", manager_value="3"):
    def rating(side, value):
        result = {
            "response_id": f"{person}-{side}-{reference}", "person_id": person,
            "employer_id": employer, "job_started_at": started, "reference_at": reference,
            "observed_at": reference, "value": value,
            "kind": f"direct_{side}_report",
        }
        if side == "manager":
            result["rater_id"] = f"{employer}-fictional-manager"
        return result

    row = {
        "person_id": person, "employer_id": employer, "job_started_at": started,
        "feature_as_of": started, "features": dict.fromkeys(FEATURE_NAMES, .5),
        "employee_rating": rating("employee", employee_value),
        "manager_rating": rating("manager", manager_value),
    }
    row["features"]["relevant_experience_years"] = 3
    return row


def write_inputs(directory, rows, mapping):
    directory = Path(directory)
    inputs, manifest = directory / "fictional_ratings.jsonl", directory / "fixture_mapping.json"
    inputs.write_text("".join(json.dumps(row) + "\n" for row in rows))
    manifest.write_text(json.dumps(mapping))
    return inputs, manifest


def read_prepared(directory):
    with (Path(directory) / "observations.csv").open(newline="") as handle:
        return list(csv.DictReader(handle))


class JointPreparationTests(unittest.TestCase):
    def convert(self, rows, mapping=None):
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, rows, mapping or fixture_mapping())
            before = inputs.read_bytes(), manifest.read_bytes()
            output = Path(directory) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                report = prepare(inputs, manifest, output)
            self.assertEqual((inputs.read_bytes(), manifest.read_bytes()), before)
            return read_prepared(output), json.loads((output / "mapping.json").read_text()), report

    def test_initialization_creates_empty_inputs_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "input"
            with contextlib.redirect_stdout(io.StringIO()):
                initialize(output)
            self.assertEqual((output / "ratings.jsonl").read_text(), "")
            mapping = json.loads((output / "mapping.json").read_text())
            self.assertEqual(mapping["target"], "joint_reported_satisfaction")
            with self.assertRaises(ValueError):
                validate_mapping(mapping)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaises((ValueError, FileExistsError)):
                initialize(output)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)

    def test_normalization_preserves_both_ratings_and_uses_the_lower_category(self):
        pairs = [(1, 1, 0), (5, 5, 4), (5, 2, 1), (2, 5, 1), (3, 4, 2)]
        rows = [fixture_row(person=f"fictional-{index}", employee_value=employee,
                            manager_value=str(manager))
                for index, (employee, manager, _) in enumerate(pairs)]
        prepared, mapping, report = self.convert(rows)
        self.assertEqual(mapping["target"], "joint_reported_satisfaction")
        self.assertEqual(mapping["joint_label"]["aggregation"], "minimum")
        self.assertEqual(report["source_rows"], 5)
        self.assertEqual(report["paired_rows"], 5)
        self.assertFalse(report["live_execution"])
        self.assertTrue(report["fictional_data"])
        for actual, (employee, manager, joint) in zip(prepared, pairs):
            self.assertEqual(int(actual["employee_rating"]), employee - 1)
            self.assertEqual(int(actual["manager_rating"]), manager - 1)
            self.assertEqual(int(actual["joint_rating"]), joint)
            self.assertEqual(float(actual["joint_score"]), 25 * joint)
            self.assertEqual(actual["label_status"], "OBSERVED_PAIRED")
        self.assertEqual(set(mapping["features"]["numeric"]), set(FEATURE_NAMES))
        self.assertEqual(mapping["features"]["categorical"], {})

    def test_each_direct_rating_scale_can_have_a_different_declared_direction(self):
        mapping = fixture_mapping()
        mapping["rating_collection"]["manager_codes_worst_to_best"] = ["5", "4", "3", "2", "1"]
        rows, _, _ = self.convert([fixture_row(employee_value="5", manager_value="2")], mapping)
        self.assertEqual(int(rows[0]["employee_rating"]), 4)
        self.assertEqual(int(rows[0]["manager_rating"]), 3)
        self.assertEqual(int(rows[0]["joint_rating"]), 3)
        self.assertEqual(float(rows[0]["joint_score"]), 75)

    def test_missing_direct_reports_preserve_known_rating_without_inventing_target(self):
        rows = []
        for index, missing in enumerate(("employee_rating", "manager_rating", "both")):
            row = fixture_row(person=f"fictional-missing-{index}")
            if missing == "both":
                row["employee_rating"] = row["manager_rating"] = None
            else:
                row[missing] = None
            rows.append(row)
        prepared, _, report = self.convert(rows)
        self.assertEqual(report["paired_rows"], 0)
        self.assertEqual([row["label_status"] for row in prepared], [
            "MISSING_EMPLOYEE", "MISSING_MANAGER", "MISSING_BOTH",
        ])
        for row in prepared:
            self.assertEqual(row["joint_rating"], "")
            self.assertEqual(row["joint_score"], "")
        self.assertEqual(int(prepared[0]["manager_rating"]), 2)
        self.assertEqual(int(prepared[1]["employee_rating"]), 4)

    def test_reference_month_is_shared_but_latest_observation_controls_availability(self):
        row = fixture_row()
        row["employee_rating"]["observed_at"] = "2000-08"
        row["manager_rating"]["observed_at"] = "2000-10"
        prepared, _, _ = self.convert([row])
        self.assertEqual(prepared[0]["rating_reference_at"], "2000-07")
        self.assertEqual(prepared[0]["rating_observed_at"], "2000-10")

    def test_mismatched_person_employer_spell_and_reference_are_rejected(self):
        for side in ("employee_rating", "manager_rating"):
            for field, value in (("person_id", "fictional-other"), ("employer_id", "fictional-other"),
                                 ("job_started_at", "1999-01"), ("reference_at", "2000-08")):
                row = fixture_row()
                row[side][field] = value
                if field == "reference_at":
                    row[side]["observed_at"] = value
                with self.subTest(side=side, field=field), self.assertRaises(ValueError):
                    self.convert([row])

    def test_predictions_indirect_manager_proxies_and_illegal_codes_are_rejected(self):
        for side in ("employee_rating", "manager_rating"):
            for kind in ("predicted_manager_report", "promotion_proxy", "tenure_proxy", "synthetic_rating"):
                row = fixture_row()
                row[side]["kind"] = kind
                with self.subTest(side=side, kind=kind), self.assertRaises(ValueError):
                    self.convert([row])
            for value in (True, False, "0", "6", "3.0", 2.5):
                row = fixture_row()
                row[side]["value"] = value
                with self.subTest(side=side, value=value), self.assertRaises(ValueError):
                    self.convert([row])

    def test_declared_missing_response_values_are_preserved_as_unknown(self):
        for side, expected in (("employee_rating", "MISSING_EMPLOYEE"), ("manager_rating", "MISSING_MANAGER")):
            for value in (None, "", -1, "-2", "-3", "-4", "-5"):
                row = fixture_row()
                row[side]["value"] = value
                with self.subTest(side=side, value=value):
                    prepared, _, report = self.convert([row])
                    self.assertEqual(prepared[0]["label_status"], expected)
                    self.assertEqual(prepared[0][side], "")
                    self.assertEqual(prepared[0]["joint_rating"], "")
                    self.assertEqual(prepared[0]["joint_score"], "")
                    self.assertEqual(report["paired_rows"], 0)

    def test_future_features_invalid_response_dates_and_rater_ids_are_rejected(self):
        invalid = []
        row = fixture_row()
        row["feature_as_of"] = "2000-02"
        invalid.append(row)
        for side in ("employee_rating", "manager_rating"):
            row = fixture_row()
            row[side]["observed_at"] = "2000-06"
            invalid.append(row)
        row = fixture_row()
        row["manager_rating"]["rater_id"] = ""
        invalid.append(row)
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.convert([row])

    def test_duplicate_response_ids_and_same_spell_reference_are_rejected(self):
        first, second = fixture_row(), fixture_row(person="fictional-other")
        second["employee_rating"]["response_id"] = first["employee_rating"]["response_id"]
        with self.assertRaises(ValueError):
            self.convert([first, second])
        duplicate = deepcopy(first)
        for side in ("employee_rating", "manager_rating"):
            duplicate[side]["response_id"] += "-different-response"
        with self.assertRaises(ValueError):
            self.convert([first, duplicate])

    def test_outcome_features_and_incompatible_data_sources_are_rejected(self):
        for name in ("joint_rating", "employee_rating", "manager_rating", "promotion_count", "satisfaction"):
            row = fixture_row()
            row["features"][name] = 1
            with self.subTest(feature=name), self.assertRaises(ValueError):
                self.convert([row])
        for kind in ("survey_export", "synthetic_relevance", "observed_introduction_outcomes"):
            mapping = fixture_mapping()
            mapping["source"]["kind"] = kind
            with self.subTest(source=kind), self.assertRaises(ValueError):
                self.convert([fixture_row()], mapping)

    def test_outside_followup_is_counted_without_becoming_a_low_rating(self):
        prepared, _, report = self.convert([
            fixture_row(person="fictional-early", reference="2000-02"),
            fixture_row(person="fictional-late", reference="2002-02"),
            fixture_row(person="fictional-eligible"),
        ])
        self.assertEqual(report["source_rows"], 3)
        self.assertEqual(report["retained_rows"], 1)
        self.assertEqual(sum(report["excluded"].values()), 2)
        self.assertEqual(prepared[0]["person_id"], "fictional-eligible")

    def test_output_directory_is_fresh_and_raw_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, [fixture_row()], fixture_mapping())
            output = Path(directory) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(inputs, manifest, output)
            before = {path.name: path.read_bytes() for path in output.iterdir()}
            with self.assertRaises((ValueError, FileExistsError)):
                prepare(inputs, manifest, output)
            self.assertEqual({path.name: path.read_bytes() for path in output.iterdir()}, before)


class JointTrainingTests(unittest.TestCase):
    def test_late_manager_report_cannot_enter_earlier_training_cohort(self):
        rows = []
        for group, year in (("train", 2000), ("validation", 2010), ("test", 2020)):
            person = next(f"fictional-{group}-{index}" for index in range(1000)
                          if person_group(f"fictional-{group}-{index}", 42) == group)
            rows.append(fixture_row(person=person, started=f"{year}-01", reference=f"{year}-07"))
        late_person = next(f"fictional-late-{index}" for index in range(1000)
                           if person_group(f"fictional-late-{index}", 42) == "train")
        late = fixture_row(person=late_person)
        late["manager_rating"]["observed_at"] = "2006-01"
        rows.append(late)
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, rows, fixture_mapping())
            output = Path(directory) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(inputs, manifest, output)
            mapping = json.loads((output / "mapping.json").read_text())
            records, _ = load_records(output / "observations.csv", mapping)
            groups, diagnostics = split_records(records, 42, "2005-01", "2015-01")
            self.assertEqual(diagnostics["split_counts"], {"train": 1, "validation": 1, "test": 1})
            self.assertEqual(diagnostics["outside_group_time_cohort"], 1)
            self.assertNotIn(late_person, {row["person_id"] for row in groups["train"]})

    def test_preparation_training_and_replay_use_joint_target_with_both_direct_ratings(self):
        rows = []
        for group, year in (("train", 2000), ("validation", 2010), ("test", 2020)):
            people = [f"fictional-{group}-{index}" for index in range(1000)
                      if person_group(f"fictional-{group}-{index}", 42) == group][:10]
            for index, person in enumerate(people):
                category = index % 5
                row = fixture_row(person=person, started=f"{year}-01", reference=f"{year}-07",
                                  employee_value=str(category + 1), manager_value="5")
                row["features"] = dict.fromkeys(FEATURE_NAMES, category / 4)
                row["features"]["relevant_experience_years"] = category * 2
                row["features"]["candidate_schedule_preference_alignment"] = None
                rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, rows, fixture_mapping())
            prepared, output = Path(directory) / "prepared", Path(directory) / "evaluation"
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(inputs, manifest, prepared)
                report = train(prepared / "observations.csv", prepared / "mapping.json", output,
                               "2005-01", "2015-01", epochs=30)
            self.assertEqual(report["target"], "joint_reported_satisfaction")
            self.assertFalse(report["live_execution"])
            self.assertTrue(report["fictional_data"])
            self.assertEqual(report["joint_score_by_class"], [0, 25, 50, 75, 100])
            self.assertEqual(report["provenance"]["split"]["split_counts"], {
                "train": 10, "validation": 10, "test": 10,
            })
            artifact_path = output / "fictional_joint_satisfaction_model.json"
            self.assertTrue((output / "fictional_joint_satisfaction_report.json").is_file())
            artifact = json.loads(artifact_path.read_text())
            model_data = artifact["model"]
            self.assertEqual(model_data["target"], "joint_reported_satisfaction")
            self.assertEqual(model_data["class_order_worst_to_best"], [f"joint_{index}" for index in range(5)])
            self.assertEqual(model_data["joint_label"]["aggregation"], "minimum")
            self.assertEqual(model_data["joint_score_by_class"], [0, 25, 50, 75, 100])
            self.assertFalse((output / "fictional_satisfaction_model.json").exists())
            self.assertNotIn("candidate_schedule_preference_alignment", artifact["encoder"]["numeric"])
            mapping = json.loads((prepared / "mapping.json").read_text())
            records, _ = load_records(prepared / "observations.csv", mapping)
            for record in records:
                self.assertEqual(record["label"], min(record["employee_rating"], record["manager_rating"]))
                self.assertEqual(record["joint_score"], 25 * record["label"])
                self.assertEqual(record["rating_observed_at"], month(f"{record['job_started_at'] // 12}-07"))
            encoded = artifact["encoder"]
            encoder = TabularEncoder(encoded["numeric"], encoded["categorical"],
                                     encoded["numeric_stats"], encoded["categories"])
            restored = SatisfactionModel(model_data["feature_names"], model_data["class_order_worst_to_best"],
                                         model_data["weights"], model_data["bias"])
            probabilities = restored.predict_proba(encoder.transform([record["features"] for record in records]))
            self.assertEqual(probabilities.shape, (30, 5))
            self.assertTrue(np.all(np.isfinite(probabilities)))
            np.testing.assert_allclose(probabilities.sum(axis=1), 1)

    def test_tampered_joint_label_cannot_disagree_with_direct_ratings(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, [fixture_row()], fixture_mapping())
            prepared = Path(directory) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(inputs, manifest, prepared)
            mapping = json.loads((prepared / "mapping.json").read_text())
            rows = read_prepared(prepared)
            rows[0]["joint_rating"] = "4"
            with (prepared / "observations.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaises(ValueError):
                load_records(prepared / "observations.csv", mapping)

    def test_csv_training_cannot_bypass_bounded_pair_feature_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, [fixture_row()], fixture_mapping())
            prepared = Path(directory) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(inputs, manifest, prepared)
            mapping = json.loads((prepared / "mapping.json").read_text())
            rows = read_prepared(prepared)
            rows[0]["candidate_work_mode_preference_alignment"] = "1.5"
            with (prepared / "observations.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaises(ValueError):
                load_records(prepared / "observations.csv", mapping)

    def test_csv_training_requires_both_reference_periods_and_latest_observation(self):
        row = fixture_row()
        row["employee_rating"]["observed_at"] = "2000-08"
        row["manager_rating"]["observed_at"] = "2000-10"
        with tempfile.TemporaryDirectory() as directory:
            inputs, manifest = write_inputs(directory, [row], fixture_mapping())
            prepared = Path(directory) / "prepared"
            with contextlib.redirect_stdout(io.StringIO()):
                prepare(inputs, manifest, prepared)
            mapping = json.loads((prepared / "mapping.json").read_text())
            original = read_prepared(prepared)
            for field, value in (("rating_observed_at", "2000-09"), ("manager_reference_at", "2000-08")):
                rows = deepcopy(original)
                rows[0][field] = value
                with (prepared / "observations.csv").open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
                with self.subTest(field=field), self.assertRaises(ValueError):
                    load_records(prepared / "observations.csv", mapping)


if __name__ == "__main__":
    unittest.main()
