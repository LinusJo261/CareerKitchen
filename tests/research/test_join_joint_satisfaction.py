"""Fictional CSV collections verify exact joins, never observed match quality."""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.join_joint_satisfaction import initialize, join
from scripts.mutual_matching_features import FEATURE_NAMES
from scripts.prepare_joint_satisfaction import EXAMPLE_MAPPING
from scripts.satisfaction_research import person_group, train


FEATURE_HEADERS = ("person_id", "employer_id", "job_started_at", "feature_as_of", *FEATURE_NAMES)
EMPLOYEE_HEADERS = (
    "person_id", "employer_id", "job_started_at", "reference_at", "observed_at", "response_id", "value", "kind",
)
MANAGER_HEADERS = (*EMPLOYEE_HEADERS, "rater_id")
SPECS = {
    "feature_snapshots.csv": FEATURE_HEADERS,
    "employee_ratings.csv": EMPLOYEE_HEADERS,
    "manager_ratings.csv": MANAGER_HEADERS,
}


def feature(person="fictional-person-A", employer="fictional-employer-A", started="2000-01"):
    return {
        "person_id": person, "employer_id": employer, "job_started_at": started, "feature_as_of": started,
        **dict.fromkeys(FEATURE_NAMES, "0.5"), "relevant_experience_years": "3",
    }


def rating(side, snapshot=None, reference="2000-07", value="5"):
    snapshot = snapshot or feature()
    row = {name: snapshot[name] for name in ("person_id", "employer_id", "job_started_at")}
    row.update(reference_at=reference, observed_at=reference,
               response_id=f"{snapshot['person_id']}-{snapshot['employer_id']}-{reference}-{side}",
               value=value, kind=f"direct_{side}_report")
    if side == "manager":
        row["rater_id"] = f"{snapshot['employer_id']}-fictional-manager"
    return row


def write_csv(path, headers, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_collection(directory, features, employees, managers):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for (name, headers), rows in zip(SPECS.items(), (features, employees, managers)):
        write_csv(directory / name, headers, rows)
    mapping = json.loads(EXAMPLE_MAPPING.read_text())
    mapping["source"] = {
        "kind": "fictional_fixture", "dataset": "fictional_csv_join_tests", "release": "fixture-v1",
        "codebook_url": "fixture://paired-direct-rating-instruments",
    }
    (directory / "mapping.json").write_text(json.dumps(mapping))


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


class JointCSVJoinTests(unittest.TestCase):
    def run_join(self, features=None, employees=None, managers=None, mutate=None):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input", Path(directory) / "joined"
            write_collection(source, [feature()] if features is None else features,
                             [rating("employee")] if employees is None else employees,
                             [rating("manager")] if managers is None else managers)
            if mutate:
                mutate(source)
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            with contextlib.redirect_stdout(io.StringIO()):
                report = join(source, output)
            self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, before)
            joined = [json.loads(line) for line in (output / "ratings.jsonl").read_text().splitlines() if line]
            prepared = read_csv(output / "prepared" / "observations.csv")
            self.assertTrue((output / "mapping.json").is_file())
            self.assertTrue((output / "join_report.json").is_file())
            self.assertTrue((output / "prepared" / "mapping.json").is_file())
            self.assertTrue((output / "prepared" / "preparation_report.json").is_file())
            return joined, prepared, report

    def test_initialize_creates_exact_headers_empty_files_and_will_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input"
            with contextlib.redirect_stdout(io.StringIO()):
                initialize(source)
            for name, expected in SPECS.items():
                with (source / name).open(newline="") as handle:
                    reader = csv.reader(handle)
                    self.assertEqual(next(reader), list(expected))
                    self.assertEqual(list(reader), [])
            self.assertTrue((source / "collection_instructions.md").is_file())
            self.assertTrue((source / "mapping.json").is_file())
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            with self.assertRaises((ValueError, FileExistsError)):
                initialize(source)
            self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, before)
            # Empty templates are intentionally not a usable observed dataset.
            with self.assertRaises(ValueError):
                join(source, Path(directory) / "output")

    def test_exact_join_preserves_independent_ratings_for_people_at_same_employer(self):
        first, second = feature(), feature(person="fictional-person-B")
        joined, prepared, report = self.run_join(
            [first, second], [rating("employee", first, value="5"), rating("employee", second, value="2")],
            [rating("manager", second, value="5"), rating("manager", first, value="1")],
        )
        by_person = {row["person_id"]: row for row in joined}
        self.assertEqual(by_person[first["person_id"]]["manager_rating"]["value"], "1")
        self.assertEqual(by_person[second["person_id"]]["manager_rating"]["value"], "5")
        scores = {row["person_id"]: float(row["joint_score"]) for row in prepared}
        self.assertEqual(scores, {first["person_id"]: 0, second["person_id"]: 25})
        for identity in (first["person_id"], second["person_id"], first["employer_id"]):
            self.assertNotIn(identity, json.dumps(report))

    def test_same_person_different_employers_or_returning_job_spells_stay_separate(self):
        snapshots = [feature(), feature(employer="fictional-employer-B"), feature(started="2002-01")]
        references = ["2000-07", "2000-07", "2002-07"]
        joined, prepared, _ = self.run_join(
            snapshots,
            [rating("employee", snap, reference, str(index + 1))
             for index, (snap, reference) in enumerate(zip(snapshots, references))],
            [rating("manager", snap, reference, "5") for snap, reference in zip(snapshots, references)],
        )
        self.assertEqual(len(joined), 3)
        self.assertEqual(len(prepared), 3)
        self.assertEqual(sorted(int(row["joint_rating"]) for row in prepared), [0, 1, 2])

    def test_mismatched_reference_periods_remain_two_unlabeled_partial_pairs(self):
        joined, prepared, _ = self.run_join(
            employees=[rating("employee", reference="2000-07")],
            managers=[rating("manager", reference="2000-08")],
        )
        self.assertEqual(len(joined), 2)
        self.assertEqual(sorted(row["label_status"] for row in prepared), ["MISSING_EMPLOYEE", "MISSING_MANAGER"])
        self.assertTrue(all(row["joint_rating"] == "" for row in prepared))
        self.assertEqual(sum(row["employee_rating"] is not None for row in joined), 1)
        self.assertEqual(sum(row["manager_rating"] is not None for row in joined), 1)

    def test_employee_and_manager_for_different_people_do_not_create_a_joint_label(self):
        first, second = feature(), feature(person="fictional-person-B")
        joined, prepared, _ = self.run_join([first, second], [rating("employee", first)], [rating("manager", second)])
        self.assertEqual(len(joined), 2)
        self.assertEqual(sorted(row["label_status"] for row in prepared), ["MISSING_EMPLOYEE", "MISSING_MANAGER"])
        self.assertTrue(all(row["joint_score"] == "" for row in prepared))

    def test_unknown_features_and_feature_only_spell_are_preserved_without_labels(self):
        snapshot = feature()
        snapshot["preferred_skill_coverage"] = ""
        joined, prepared, _ = self.run_join([snapshot], [], [])
        self.assertEqual(len(joined), 1)
        self.assertIsNone(joined[0]["features"]["preferred_skill_coverage"])
        self.assertIsNone(joined[0]["employee_rating"])
        self.assertIsNone(joined[0]["manager_rating"])
        self.assertEqual(prepared[0]["preferred_skill_coverage"], "")
        self.assertEqual(prepared[0]["label_status"], "MISSING_BOTH")
        self.assertEqual(prepared[0]["joint_rating"], "")

    def test_two_periods_of_reported_missing_codes_stay_distinct_and_unlabeled(self):
        references = ("2000-07", "2000-08")
        joined, prepared, _ = self.run_join(
            employees=[rating("employee", reference=reference, value="-4") for reference in references],
            managers=[rating("manager", reference=reference, value="-5") for reference in references],
        )
        self.assertEqual(len(joined), 2)
        self.assertEqual(len(prepared), 2)
        self.assertEqual({row["employee_reference_at"] for row in prepared}, set(references))
        self.assertTrue(all(row["label_status"] == "MISSING_BOTH" for row in prepared))
        self.assertTrue(all(row["joint_rating"] == "" for row in prepared))

    def test_duplicate_snapshots_responses_and_side_period_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            self.run_join(features=[feature(), feature()])
        first, second = rating("employee"), rating("employee", reference="2000-08")
        second["response_id"] = first["response_id"]
        with self.assertRaises(ValueError):
            self.run_join(employees=[first, second])
        duplicate = deepcopy(first)
        duplicate["response_id"] += "-second-response"
        with self.assertRaises(ValueError):
            self.run_join(employees=[first, duplicate])

    def test_orphan_ratings_require_exact_frozen_spell_and_do_not_use_fuzzy_identity(self):
        for field, value in (("person_id", "fictional-other"), ("employer_id", "fictional-other"),
                             ("job_started_at", "1999-01")):
            employee = rating("employee")
            employee[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_join(employees=[employee])

    def test_wrong_rating_sources_and_invalid_timelines_are_rejected(self):
        for side in ("employee", "manager"):
            source = rating(side)
            source["kind"] = "predicted_satisfaction"
            with self.subTest(side=side), self.assertRaises(ValueError):
                self.run_join(**{f"{side}s" if side == "manager" else "employees": [source]})
        employee = rating("employee")
        employee["observed_at"] = "2000-06"
        with self.assertRaises(ValueError):
            self.run_join(employees=[employee])
        snapshot = feature()
        snapshot["feature_as_of"] = "2000-02"
        with self.assertRaises(ValueError):
            self.run_join(features=[snapshot])

    def test_invalid_numeric_features_and_rating_codes_are_not_imputed_silently(self):
        for value in ("NaN", "inf", "-0.2", "1.1", "True", "unknown"):
            snapshot = feature()
            snapshot["required_skill_coverage"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_join(features=[snapshot])
        employee = rating("employee", value="6")
        with self.assertRaises(ValueError):
            self.run_join(employees=[employee])

    def test_extra_headers_duplicate_headers_and_malformed_csv_rows_are_rejected(self):
        for filename, headers in SPECS.items():
            def extra(source, filename=filename, headers=headers):
                rows = read_csv(source / filename)
                for row in rows:
                    row["satisfaction_prediction"] = "0.9"
                write_csv(source / filename, (*headers, "satisfaction_prediction"), rows)

            with self.subTest(filename=filename, problem="extra"), self.assertRaises(ValueError):
                self.run_join(mutate=extra)

            def malformed(source, filename=filename):
                path = source / filename
                path.write_text(path.read_text().rstrip("\n") + ",undeclared-cell\n")

            with self.subTest(filename=filename, problem="extra-cell"), self.assertRaises(ValueError):
                self.run_join(mutate=malformed)

        def duplicate_header(source):
            path = source / "feature_snapshots.csv"
            text = path.read_text().splitlines()
            text[0] += ",person_id"
            path.write_text("\n".join(text) + "\n")

        with self.assertRaises(ValueError):
            self.run_join(mutate=duplicate_header)

    def test_existing_output_directory_and_raw_inputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input", Path(directory) / "output"
            write_collection(source, [feature()], [rating("employee")], [rating("manager")])
            output.mkdir()
            (output / "preserve.txt").write_text("original")
            before = {path.name: path.read_bytes() for path in source.iterdir()}
            with self.assertRaises((ValueError, FileExistsError)):
                join(source, output)
            self.assertEqual((output / "preserve.txt").read_text(), "original")
            self.assertEqual({path.name: path.read_bytes() for path in source.iterdir()}, before)

    def test_joined_preparation_can_train_existing_joint_model_without_manual_edits(self):
        snapshots, employees, managers = [], [], []
        for group, year in (("train", 2000), ("validation", 2010), ("test", 2020)):
            people = [f"fictional-join-{group}-{index}" for index in range(1000)
                      if person_group(f"fictional-join-{group}-{index}", 42) == group][:10]
            for index, person in enumerate(people):
                category = index % 5
                snapshot = feature(person=person, started=f"{year}-01")
                for name in FEATURE_NAMES:
                    snapshot[name] = str(category / 4)
                snapshot["relevant_experience_years"] = str(category * 2)
                snapshots.append(snapshot)
                employees.append(rating("employee", snapshot, f"{year}-07", str(category + 1)))
                managers.append(rating("manager", snapshot, f"{year}-07", "5"))
        with tempfile.TemporaryDirectory() as directory:
            source, output, evaluation = (Path(directory) / name for name in ("input", "joined", "evaluation"))
            write_collection(source, snapshots, employees, managers)
            with contextlib.redirect_stdout(io.StringIO()):
                join(source, output)
                report = train(output / "prepared" / "observations.csv", output / "prepared" / "mapping.json",
                               evaluation, "2005-01", "2015-01", epochs=20)
            self.assertEqual(report["target"], "joint_reported_satisfaction")
            self.assertTrue(report["fictional_data"])
            self.assertFalse(report["live_execution"])
            self.assertEqual(report["provenance"]["split"]["split_counts"], {
                "train": 10, "validation": 10, "test": 10,
            })
            self.assertTrue((evaluation / "fictional_joint_satisfaction_model.json").is_file())


if __name__ == "__main__":
    unittest.main()
