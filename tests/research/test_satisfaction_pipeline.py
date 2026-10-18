"""Offline importer/training checks using clearly fictional, temporary records."""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.satisfaction_research import (
    EXAMPLE_MAPPING,
    demo,
    initialize,
    load_records,
    month,
    person_group,
    split_records,
    train,
    validate_mapping,
)


def fixture_mapping():
    mapping = json.loads(EXAMPLE_MAPPING.read_text())
    mapping["source"] = {
        "kind": "fictional_fixture", "dataset": "fictional_unit_test",
        "release": "fixture-v1", "codebook_url": "fixture://not-a-survey",
    }
    return mapping


def fixture_row(**changes):
    row = {
        "person_id": "fictional-person", "employer_id": "fictional-employer",
        "job_started_at": "2000-01", "feature_as_of": "2000-01",
        "rating_reference_at": "2000-07", "rating_observed_at": "2000-08",
        "satisfaction": "1", "prior_experience_years": "2",
        "offered_hours_per_week": "40", "employment_type": "FULL_TIME",
    }
    row.update(changes)
    return row


def write_csv(path, rows, mapping=None):
    mapping = mapping or fixture_mapping()
    fields = list(mapping["columns"].values())
    fields.extend(mapping["features"]["numeric"].values())
    fields.extend(mapping["features"]["categorical"].values())
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def person_in(group):
    return next(f"fictional-{index}" for index in range(10000)
                if person_group(f"fictional-{index}", 42) == group)


class SatisfactionImporterTests(unittest.TestCase):
    def load(self, rows, mapping=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fictional.csv"
            write_csv(path, rows, mapping)
            return load_records(path, mapping or fixture_mapping())

    def test_survey_codes_have_correct_worst_to_best_direction(self):
        rows = [fixture_row(person_id=f"fictional-{code}", satisfaction=str(code))
                for code in range(1, 6)]
        records, diagnostics = self.load(rows)
        self.assertEqual([row["label"] for row in records], [4, 3, 2, 1, 0])
        self.assertEqual(diagnostics["usable_spells"], 5)

    def test_negative_missing_codes_are_excluded_not_low_satisfaction(self):
        rows = [fixture_row(person_id=f"fictional-{code}", satisfaction=str(code))
                for code in range(-5, 0)]
        records, diagnostics = self.load([*rows, fixture_row(satisfaction="3")])
        self.assertEqual([row["label"] for row in records], [2])
        self.assertEqual(diagnostics["excluded"], {"missing_satisfaction": 5})

    def test_unknown_satisfaction_codes_fail_instead_of_becoming_negatives(self):
        for value in ["0", "6", "1.0", "unknown"]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unknown satisfaction code"):
                self.load([fixture_row(satisfaction=value)])

    def test_posthire_features_and_invalid_outcome_timelines_fail(self):
        changes = [
            {"feature_as_of": "2000-02"},
            {"rating_reference_at": "2000-01"},
            {"rating_reference_at": "1999-12"},
            {"rating_reference_at": "2000-09", "rating_observed_at": "2000-08"},
            {"rating_observed_at": "2000-13"},
            {"job_started_at": "2000-01-01"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load([fixture_row(**change)])

    def test_all_observations_outside_declared_followup_window_fail(self):
        for reference in ["2000-02", "2002-02"]:
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "No usable"):
                self.load([fixture_row(rating_reference_at=reference, rating_observed_at=reference)])
        records, diagnostics = self.load([
            fixture_row(person_id="outside", rating_reference_at="2000-02"), fixture_row(),
        ])
        self.assertEqual(len(records), 1)
        self.assertEqual(diagnostics["excluded"]["outside_followup_window"], 1)

    def test_first_observed_rating_selected_and_returning_to_employer_is_new_spell(self):
        # Deliberately list the happier later outcome first to catch cherry-picking.
        rows = [
            fixture_row(satisfaction="1", rating_reference_at="2000-10", rating_observed_at="2001-01"),
            fixture_row(satisfaction="5"),
            fixture_row(satisfaction="2", job_started_at="2002-01", feature_as_of="2002-01",
                        rating_reference_at="2002-07", rating_observed_at="2002-08"),
        ]
        records, diagnostics = self.load(rows)
        self.assertEqual([record["label"] for record in records], [0, 3])
        self.assertEqual(len({row["job_started_at"] for row in records}), 2)
        self.assertEqual(diagnostics["excluded"]["later_rating_same_spell"], 1)

    def test_duplicate_observation_and_predictor_label_alias_fail(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.load([fixture_row(), fixture_row()])
        mapping = fixture_mapping()
        mapping["features"]["numeric"]["prior_experience_years"] = "satisfaction"
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate_mapping(mapping)

    def test_posthire_or_protected_feature_declarations_fail(self):
        for name in ["promotion_count", "final_tenure", "age", "person_id"]:
            mapping = fixture_mapping()
            mapping["features"]["numeric"][name] = name
            mapping["feature_timing"][name] = "prehire_or_job_start"
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsupported feature"):
                validate_mapping(mapping)
        mapping = fixture_mapping()
        mapping["feature_timing"]["prior_experience_years"] = "after_hiring"
        with self.assertRaisesRegex(ValueError, "prehire_or_job_start"):
            validate_mapping(mapping)


class SatisfactionSplitTests(unittest.TestCase):
    def test_person_disjoint_forward_time_split_excludes_future_known_training_labels(self):
        people = {name: person_in(name) for name in ("train", "validation", "test")}

        def record(group, started, observed):
            return {"person_id": people[group], "job_started_at": month(started),
                    "rating_observed_at": month(observed)}

        usable = [record("train", "2000-01", "2000-08"),
                  record("validation", "2010-01", "2010-08"),
                  record("test", "2020-01", "2020-08")]
        excluded = [
            record("train", "2004-01", "2005-01"),  # Label not known at training cutoff.
            record("train", "2020-01", "2020-08"),  # Same person cannot enter test.
            record("validation", "2004-01", "2010-08"),  # Job starts before validation cohort.
            record("validation", "2014-01", "2015-01"),  # Label beyond validation cutoff.
            record("test", "2010-01", "2010-08"),
        ]
        groups, diagnostics = split_records([*usable, *excluded], 42, "2005-01", "2015-01")
        self.assertEqual({name: len(rows) for name, rows in groups.items()},
                         {"train": 1, "validation": 1, "test": 1})
        self.assertEqual(diagnostics["outside_group_time_cohort"], len(excluded))
        person_sets = {name: {row["person_id"] for row in rows} for name, rows in groups.items()}
        for left, right in [("train", "validation"), ("train", "test"), ("validation", "test")]:
            self.assertTrue(person_sets[left].isdisjoint(person_sets[right]))
        self.assertLess(max(row["rating_observed_at"] for row in groups["train"]), month("2005-01"))
        self.assertEqual(groups, split_records([*usable, *excluded], 42, "2005-01", "2015-01")[0])

    def test_empty_splits_and_reversed_cutoffs_fail(self):
        for first, second in [("2005-01", "2015-01"), ("2015-01", "2005-01")]:
            with self.subTest(first=first, second=second), self.assertRaises(ValueError):
                split_records([], 42, first, second)


class SatisfactionPipelineTests(unittest.TestCase):
    def test_initialize_refuses_to_overwrite_either_input(self):
        for filename in ("mapping.json", "observations.csv"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                existing = path / filename
                existing.write_text("user input must survive\n")
                with self.assertRaisesRegex(ValueError, "already exists"):
                    initialize(path)
                self.assertEqual(existing.read_text(), "user input must survive\n")
                self.assertEqual(list(path.iterdir()), [existing])
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            path = Path(directory)
            initialize(path)
            mapping_before = (path / "mapping.json").read_bytes()
            csv_before = (path / "observations.csv").read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                initialize(path)
            self.assertEqual((path / "mapping.json").read_bytes(), mapping_before)
            self.assertEqual((path / "observations.csv").read_bytes(), csv_before)

    def test_fictional_demo_exports_replayable_artifacts_with_explicit_limitations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                report = demo(path)
            self.assertIn("FICTIONAL SOFTWARE DEMO ONLY", captured.getvalue())
            report_path = path / "fictional_satisfaction_report.json"
            model_path = path / "fictional_satisfaction_model.json"
            report_bytes, model_bytes = report_path.read_bytes(), model_path.read_bytes()
            artifact = json.loads(model_bytes)
            self.assertEqual(report, json.loads(report_bytes))
            for exported in (report, artifact):
                self.assertTrue(exported["fictional_data"])
                self.assertFalse(exported["live_execution"])
                self.assertEqual(exported["provenance"]["source"]["kind"], "fictional_fixture")
                self.assertTrue(any("FICTIONAL FIXTURE" in item for item in exported["limitations"]))
            self.assertEqual(artifact["model"]["target"], "reported_job_satisfaction")
            self.assertEqual(len(artifact["model"]["class_order_worst_to_best"]), 5)
            self.assertLess(artifact["model"]["final_loss"], artifact["model"]["initial_loss"])
            for split in ("validation", "test"):
                self.assertGreater(report["evaluation"][split]["model"]["count"], 0)
                self.assertIn("training_distribution_baseline", report["evaluation"][split])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(report, demo(path))
            self.assertEqual(report_path.read_bytes(), report_bytes)
            self.assertEqual(model_path.read_bytes(), model_bytes)

    def test_real_export_requires_actual_source_metadata_before_training(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            mapping = json.loads(EXAMPLE_MAPPING.read_text())
            self.assertEqual(mapping["source"]["kind"], "survey_export")
            mapping_path = path / "mapping.json"
            mapping_path.write_text(json.dumps(mapping))
            input_path = path / "observations.csv"
            write_csv(input_path, [fixture_row()], mapping)
            with self.assertRaisesRegex(ValueError, "actual export"):
                train(input_path, mapping_path, path / "output", "2005-01", "2015-01")
            self.assertFalse((path / "output").exists())


if __name__ == "__main__":
    unittest.main()
