"""Same-period fictional pilots test software, not future outcome prediction."""

import contextlib
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.mutual_matching_features import FEATURE_NAMES
from scripts.prepare_joint_satisfaction import EXAMPLE_MAPPING as JOINT_MAPPING
from scripts.prepare_joint_satisfaction import prepare
from scripts.satisfaction_research import EXAMPLE_MAPPING as SURVEY_MAPPING
from scripts.satisfaction_research import month, person_group, split_records, train


ROOT = Path(__file__).resolve().parents[2]


def people_in(group):
    return [f"fictional-pilot-{group}-{index}" for index in range(1000)
            if person_group(f"fictional-pilot-{group}-{index}", 42) == group][:5]


def fixture_source():
    return {
        "kind": "fictional_fixture", "dataset": "fictional_same_period_pilot",
        "release": "fixture-v1", "codebook_url": "fixture://not-observed-ratings",
    }


def split_fixture():
    return [{"person_id": person, "employer_id": f"fictional-employer-{spell}",
             "job_started_at": month("2020-01"), "rating_observed_at": month("2020-07")}
            for group in ("train", "validation", "test") for person in people_in(group) for spell in range(2)]


def prepare_fixture(directory):
    directory = Path(directory)
    mapping = json.loads(JOINT_MAPPING.read_text())
    mapping["source"] = fixture_source()
    manifest, raw = directory / "fictional_mapping.json", directory / "fictional_ratings.jsonl"
    manifest.write_text(json.dumps(mapping))
    rows = []
    for group in ("train", "validation", "test"):
        for category, person in enumerate(people_in(group)):
            employer = "fictional-pilot-employer"
            row = {
                "person_id": person, "employer_id": employer,
                "job_started_at": "2020-01", "feature_as_of": "2020-01",
                "features": dict.fromkeys(FEATURE_NAMES, category / 4),
            }
            row["features"]["relevant_experience_years"] = category * 2 + {
                "train": 0, "validation": 100, "test": 200,
            }[group]
            row["features"]["candidate_schedule_preference_alignment"] = None
            for side in ("employee", "manager"):
                response = {
                    "response_id": f"{person}-{side}", "person_id": person, "employer_id": employer,
                    "job_started_at": "2020-01", "reference_at": "2020-07", "observed_at": "2020-07",
                    "value": str(category + 1) if side == "employee" else "5", "kind": f"direct_{side}_report",
                }
                if side == "manager":
                    response["rater_id"] = "fictional-pilot-manager"
                row[f"{side}_rating"] = response
            rows.append(row)
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
    prepared = directory / "prepared"
    with contextlib.redirect_stdout(io.StringIO()):
        prepare(raw, manifest, prepared)
    return prepared


class JointPilotSplitTests(unittest.TestCase):
    def test_same_period_pilot_keeps_people_disjoint_without_changing_dates(self):
        records = split_fixture()
        before = deepcopy(records)
        groups, diagnostics = split_records(records, 42, policy="grouped-pilot")
        self.assertEqual(records, before)
        self.assertEqual(diagnostics["split_counts"], {"train": 10, "validation": 10, "test": 10})
        self.assertIn("pilot", diagnostics["policy"].lower())
        self.assertIn("no forward-time", diagnostics["policy"].lower())
        self.assertIsNone(diagnostics["train_before"])
        self.assertIsNone(diagnostics["validate_before"])
        identities = {name: {row["person_id"] for row in rows} for name, rows in groups.items()}
        for name, rows in groups.items():
            self.assertEqual(identities[name], set(people_in(name)))
            self.assertTrue(all(row["job_started_at"] == month("2020-01") for row in rows))
            self.assertTrue(all(row["rating_observed_at"] == month("2020-07") for row in rows))
        self.assertFalse(identities["train"] & identities["validation"])
        self.assertFalse(identities["train"] & identities["test"])
        self.assertFalse(identities["validation"] & identities["test"])

    def test_pilot_rejects_any_temporal_cutoff_instead_of_ignoring_it(self):
        for first, second in (("2005-01", None), (None, "2015-01"), ("2005-01", "2015-01")):
            with self.subTest(first=first, second=second), self.assertRaises(ValueError):
                split_records(split_fixture(), 42, first, second, policy="grouped-pilot")

    def test_pilot_still_rejects_empty_folds_and_unknown_policies(self):
        records = [row for row in split_fixture() if person_group(row["person_id"], 42) == "train"]
        with self.assertRaises(ValueError):
            split_records(records, 42, policy="grouped-pilot")
        for policy in ("random-pairs", "grouped", None):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                split_records(split_fixture(), 42, policy=policy)

    def test_default_temporal_split_requires_both_cutoffs(self):
        with self.assertRaises(ValueError):
            split_records(split_fixture(), 42)
        for first, second in (("2005-01", None), (None, "2015-01")):
            with self.subTest(first=first, second=second), self.assertRaises(ValueError):
                split_records(split_fixture(), 42, first, second)


class JointPilotTrainingTests(unittest.TestCase):
    def test_joint_model_can_train_on_same_period_pilot_with_explicit_limitations(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared, output = prepare_fixture(directory), Path(directory) / "evaluation"
            with contextlib.redirect_stdout(io.StringIO()):
                report = train(prepared / "observations.csv", prepared / "mapping.json", output,
                               epochs=20, split_policy="grouped-pilot")
            self.assertEqual(report["target"], "joint_reported_satisfaction")
            self.assertTrue(report["fictional_data"])
            self.assertFalse(report["live_execution"])
            self.assertEqual(report["provenance"]["split"]["split_counts"], {
                "train": 5, "validation": 5, "test": 5,
            })
            self.assertIn("no forward-time", report["provenance"]["split"]["policy"].lower())
            limitations = " ".join(report["limitations"]).lower()
            self.assertIn("pilot", limitations)
            self.assertTrue("future" in limitations or "forward-time" in limitations)
            self.assertEqual(report["evaluation"]["test"]["model"]["count"], 5)
            artifact = json.loads((output / "fictional_joint_satisfaction_model.json").read_text())
            self.assertEqual(artifact["model"]["target"], "joint_reported_satisfaction")
            self.assertEqual(artifact["provenance"]["split"], report["provenance"]["split"])
            self.assertEqual(artifact["encoder"]["numeric_stats"]["relevant_experience_years"]["maximum"], 8)
            self.assertNotIn("candidate_schedule_preference_alignment", artifact["encoder"]["numeric"])

    def test_pilot_is_not_available_for_employee_only_satisfaction_target(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            mapping = json.loads(SURVEY_MAPPING.read_text())
            mapping["source"] = fixture_source()
            manifest, observations = directory / "mapping.json", directory / "observations.csv"
            manifest.write_text(json.dumps(mapping))
            headers = [*mapping["columns"].values(), *mapping["features"]["numeric"].values(),
                       *mapping["features"]["categorical"].values()]
            with observations.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                for group in ("train", "validation", "test"):
                    for index, person in enumerate(people_in(group)):
                        writer.writerow({
                            "person_id": person, "employer_id": "fictional-employer",
                            "job_started_at": "2020-01", "feature_as_of": "2020-01",
                            "rating_reference_at": "2020-07", "rating_observed_at": "2020-07",
                            "satisfaction": str(index + 1), "prior_experience_years": "2",
                            "offered_hours_per_week": "40", "employment_type": "FULL_TIME",
                        })
            output = directory / "not_created"
            with self.assertRaises(ValueError):
                train(observations, manifest, output, epochs=5, split_policy="grouped-pilot")
            self.assertFalse(output.exists())

    def test_cli_supports_explicit_pilot_but_keeps_temporal_cutoffs_required(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = prepare_fixture(directory)
            output = Path(directory) / "cli-evaluation"
            command = [
                sys.executable, "-m", "scripts.satisfaction_research", "train",
                "--input", str(prepared / "observations.csv"), "--mapping", str(prepared / "mapping.json"),
                "--output", str(output), "--epochs", "10",
            ]
            missing = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertNotEqual(missing.returncode, 0)
            self.assertFalse(output.exists())
            success = subprocess.run([*command, "--split-policy", "grouped-pilot"],
                                     cwd=ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            report = json.loads((output / "fictional_joint_satisfaction_report.json").read_text())
            self.assertIn("pilot", report["provenance"]["split"]["policy"].lower())
            self.assertTrue(report["fictional_data"])


if __name__ == "__main__":
    unittest.main()
