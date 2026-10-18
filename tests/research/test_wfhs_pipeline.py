"""Fictional fixtures verify the pipeline, not observational prediction quality."""

import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts import wfhs_research as wfhs
from scripts.satisfaction_model import TabularEncoder


class WFHSPipelineTests(unittest.TestCase):
    """All people, responses, and documents below are synthetic software fixtures."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / "fictional-wfhs"
        self.raw.mkdir()
        for name in ("36158-Codebook.pdf", "36158-User_guide.pdf", "TermsOfUse.html"):
            (self.raw / name).write_text("Fictional documentation fixture only.\n")

    @staticmethod
    def row(person, wave, cluster="1", employee=True, items=(3, 4, 4)):
        row = {
            "ADMINLINK": str(person), "WAVE": str(wave),
            "EMPLOYEE": "1" if employee else "0", "MANAGER": "0" if employee else "1",
            "CONDITION": "1", "STUDYGROUP": str(cluster), "LF_CENTERID": str(cluster),
            "EXCLUDE": "", wfhs.LABEL: repr(sum(items) / 3),
            **{name: str(value) for name, value in zip(wfhs.LABEL_ITEMS, items)},
            **{column: "3" for column in wfhs.FEATURES.values()},
        }
        row["WM_HPQ1"] = "40"
        row[wfhs.FEATURES["hours_expected_by_manager"]] = "40"
        return row

    def write_rows(self, rows, dataset="tomo"):
        source = self.raw / wfhs.DATASETS[dataset][0]
        source.parent.mkdir(parents=True, exist_ok=True)
        headers = list(self.row("header", 1))
        with source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        return source

    def training_records(self):
        records = []
        for index in range(120):
            records.append({
                "person_id": f"fictional:{index}", "baseline_cluster": f"fictional:group-{index}",
                "condition": "1" if index % 2 else "2", "baseline_wave": 1, "outcome_wave": 3,
                "baseline_satisfaction": 3.0, "followup_satisfaction": 2.0 + index % 3,
                "features": {
                    name: (10.0 + 10 * (index % 3) if name.startswith("hours_") else 2.0 + index % 3)
                    for name in wfhs.FEATURES
                },
            })
        return records

    @staticmethod
    def audit():
        return {"dataset": "tomo", "source_sha256": hashlib.sha256(b"fictional fixture").hexdigest()}

    def test_exact_person_and_wave_join_uses_baseline_and_twelve_months(self):
        rows = [
            self.row("a", 3, items=(4, 4, 5)), self.row("b", 1, items=(1, 2, 3)),
            self.row("a", 2, items=(1, 1, 1)), self.row("a", 1, items=(2, 2, 2)),
            self.row("b", 3, items=(3, 3, 3)), self.row("a", 4, items=(5, 5, 5)),
            self.row("baseline-only", 1), self.row("followup-only", 3),
        ]
        self.write_rows(rows)
        records, audit = wfhs.prepare_dataset(self.raw, "tomo")
        by_person = {row["person_id"]: row for row in records}
        self.assertEqual(set(by_person), {"tomo:a", "tomo:b"})
        self.assertEqual(by_person["tomo:a"]["baseline_satisfaction"], 2)
        self.assertAlmostEqual(by_person["tomo:a"]["followup_satisfaction"], 13 / 3)
        self.assertEqual(by_person["tomo:b"]["followup_satisfaction"], 3)
        self.assertEqual(audit["source_rows"], 8)
        self.assertEqual(audit["exclusions"]["missing_12_month_observation"], 1)

    def test_future_features_and_cluster_changes_cannot_change_baseline_inputs(self):
        baseline, future = self.row("a", 1, "11"), self.row("a", 3, "22")
        self.write_rows([baseline, future])
        original, _ = wfhs.prepare_dataset(self.raw, "tomo")
        # Deliberately invalid future measurements must never become model inputs.
        future.update({column: "not-a-baseline-value" for column in wfhs.FEATURES.values()})
        self.write_rows([future, baseline])
        changed, audit = wfhs.prepare_dataset(self.raw, "tomo")
        self.assertEqual(changed, original)
        self.assertEqual(changed[0]["baseline_cluster"], "tomo:11")
        self.assertEqual(audit["changed_cluster_at_followup"], 1)

    def test_documented_missing_codes_and_fractional_questionnaire_mean_are_preserved(self):
        baseline, future = self.row("a", 1), self.row("a", 3, items=(4, 4, 5))
        baseline["SCWM_CWH"], baseline["WM_HPQ1"] = "-8", "-7"
        missing_future = self.row("missing", 3)
        missing_future.update({wfhs.LABEL: "-8", **{field: "-4" for field in wfhs.LABEL_ITEMS}})
        self.write_rows([baseline, future, self.row("missing", 1), missing_future])
        records, audit = wfhs.prepare_dataset(self.raw, "tomo")
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["features"]["control_over_work_hours"])
        self.assertIsNone(records[0]["features"]["hours_worked_last_week"])
        self.assertAlmostEqual(records[0]["followup_satisfaction"], 13 / 3)
        self.assertNotEqual(records[0]["followup_satisfaction"], 4)
        self.assertEqual(audit["exclusions"]["missing_12_month_satisfaction"], 1)

    def test_scale_item_disagreement_rounding_and_undocumented_values_fail(self):
        alterations = [
            ({wfhs.LABEL: "4"}, "future"),
            ({wfhs.LABEL: repr(4.2)}, "future"),
            ({wfhs.LABEL_ITEMS[0]: "4.5"}, "future"),
            ({wfhs.LABEL_ITEMS[0]: "-4"}, "future"),
            ({"SCWM_CWH": "-99"}, "baseline"),
            ({"WM_HPQ1": "169"}, "baseline"),
            ({wfhs.LABEL: "nan"}, "future"),
        ]
        for alteration, timing in alterations:
            with self.subTest(alteration=alteration, timing=timing):
                baseline, future = self.row("a", 1), self.row("a", 3, items=(4, 4, 5))
                (baseline if timing == "baseline" else future).update(alteration)
                self.write_rows([baseline, future])
                with self.assertRaises(ValueError):
                    wfhs.prepare_dataset(self.raw, "tomo")

    def test_manager_own_satisfaction_and_role_changes_do_not_become_employee_targets(self):
        self.write_rows([
            self.row("employee", 1), self.row("employee", 3),
            self.row("manager", 1, employee=False), self.row("manager", 3, employee=False),
            self.row("promoted", 1), self.row("promoted", 3, employee=False),
        ], dataset="leef")
        records, audit = wfhs.prepare_dataset(self.raw, "leef")
        self.assertEqual([row["person_id"] for row in records], ["leef:employee"])
        self.assertEqual(audit["exclusions"]["not_baseline_employee"], 1)
        self.assertEqual(audit["exclusions"]["not_employee_at_followup"], 1)

    def test_duplicate_person_wave_stops_exact_longitudinal_join(self):
        self.write_rows([self.row("a", 1), self.row("a", 3), self.row("a", 3)])
        with self.assertRaisesRegex(ValueError, "Duplicate participant/wave"):
            wfhs.prepare_dataset(self.raw, "tomo")

    def test_tomo_main_study_exclusions_are_applied_before_followup_pairing(self):
        not_invited = dict(self.row("not-invited", 1), EXCLUDE="1")
        not_randomized = dict(self.row("not-randomized", 1), EXCLUDE="2")
        self.write_rows([self.row("eligible", 1), self.row("eligible", 3), not_invited, not_randomized])
        records, audit = wfhs.prepare_dataset(self.raw, "tomo")
        self.assertEqual([row["person_id"] for row in records], ["tomo:eligible"])
        self.assertEqual(audit["exclusions"]["tomo_not_invited"], 1)
        self.assertEqual(audit["exclusions"]["tomo_not_randomized"], 1)
        self.assertNotIn("missing_12_month_observation", audit["exclusions"])

    def test_splits_are_deterministic_and_keep_people_and_baseline_clusters_disjoint(self):
        records = self.training_records()
        for index in range(12):
            extra = dict(records[index], person_id=f"fictional:colleague-{index}")
            records.append(extra)
        groups, summary = wfhs.split_records(records)
        repeated, _ = wfhs.split_records(list(reversed(records)))
        for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
            self.assertTrue({row["person_id"] for row in groups[left]}.isdisjoint(
                row["person_id"] for row in groups[right]
            ))
            self.assertTrue({row["baseline_cluster"] for row in groups[left]}.isdisjoint(
                row["baseline_cluster"] for row in groups[right]
            ))
        for name, rows in groups.items():
            self.assertEqual({row["person_id"] for row in rows}, {row["person_id"] for row in repeated[name]})
        self.assertFalse(summary["calendar_time_holdout"])
        with self.assertRaises(ValueError):
            wfhs.split_records(records + [records[0]])

    def test_encoder_median_and_range_come_only_from_training(self):
        records = self.training_records()
        groups, _ = wfhs.split_records(records)
        feature = "hours_worked_last_week"
        for index, row in enumerate(groups["train"]):
            row["features"][feature] = (10.0, 20.0, None)[index % 3]
        for row in groups["validation"] + groups["test"]:
            row["features"][feature] = 168.0
        artifact, _ = wfhs.train_dataset(records, self.audit())
        stats = artifact["encoder"]["numeric_stats"][feature]
        observed = [row["features"][feature] for row in groups["train"] if row["features"][feature] is not None]
        self.assertEqual(stats["minimum"], 10)
        self.assertEqual(stats["maximum"], 20)
        self.assertEqual(stats["median"], float(np.median(observed)))
        encoded = artifact["encoder"]
        encoder = TabularEncoder(encoded["numeric"], encoded["categorical"], encoded["numeric_stats"], encoded["categories"])
        unknown = dict(groups["train"][0]["features"], **{feature: None})
        offset = encoder.feature_names.index(f"{feature}__scaled")
        vector = encoder.transform([unknown])[0]
        self.assertAlmostEqual(vector[offset], (stats["median"] - 10) / 10)
        self.assertEqual(vector[offset + 1], 1)
        # Changing test measurements and labels cannot alter fitted state or selection.
        for row in groups["test"]:
            row["features"][feature] = 0
            row["followup_satisfaction"] = 5
        changed, _ = wfhs.train_dataset(records, self.audit())
        for key in ("encoder", "model", "selected_l2"):
            self.assertEqual(changed[key], artifact[key])

    def test_l2_selection_uses_validation_even_when_test_favors_another_candidate(self):
        records = self.training_records()
        groups, _ = wfhs.split_records(records)
        for row in groups["validation"]:
            row["followup_satisfaction"] = 3
        for row in groups["test"]:
            row["followup_satisfaction"] = 5

        class FictionalModel:
            def __init__(self, penalty):
                self.penalty = penalty

            def predict(self, x):
                value = 3 if self.penalty == .1 else 5 if self.penalty == 1 else 1
                return np.full(len(x), value, dtype=float)

            def to_dict(self):
                return {"fictional_test_model": True, "l2": self.penalty}

        with patch.object(wfhs, "fit_ridge", side_effect=lambda x, y, feature_names, l2: FictionalModel(l2)):
            artifact, report = wfhs.train_dataset(records, self.audit())
        self.assertEqual(artifact["selected_l2"], .1)
        self.assertEqual(report["evaluation"]["validation"]["model"]["rmse"], 0)
        self.assertEqual(report["evaluation"]["test"]["model"]["rmse"], 2)
        self.assertFalse(report["hyperparameter_selection"]["test_used_for_selection"])

    def test_all_dataset_validation_and_training_failure_publish_no_partial_results(self):
        valid = [self.row("a", 1), self.row("a", 3)]
        self.write_rows(valid, "tomo")
        self.write_rows(valid + [self.row("a", 3)], "leef")
        output = self.root / "results"
        with self.assertRaises(ValueError):
            wfhs.run(self.raw, output, ["tomo", "leef"])
        self.assertFalse(output.exists())
        self.write_rows(valid, "leef")
        with patch.object(wfhs, "train_dataset", side_effect=[({}, {}), ValueError("Fictional second dataset training failure")]):
            with self.assertRaisesRegex(ValueError, "second dataset"):
                wfhs.run(self.raw, output, ["tomo", "leef"], train=True)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".wfhs-staging-*")), [])

    def test_successful_publication_preserves_sources_and_refuses_overwrite(self):
        source = self.write_rows([self.row("a", 1), self.row("a", 3)])
        original = source.read_bytes()
        output = self.root / "results"
        result = wfhs.run(self.raw, output, ["tomo"])
        self.assertEqual(result["tomo"]["usable_employee_pairs"], 1)
        self.assertTrue((output / "tomo/observations.csv").is_file())
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["datasets"], ["tomo"])
        self.assertFalse(manifest["live_execution"])
        before = {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()}
        with self.assertRaisesRegex(ValueError, "already exists"):
            wfhs.run(self.raw, output, ["tomo"])
        self.assertEqual(before, {path.relative_to(output): path.read_bytes() for path in output.rglob("*") if path.is_file()})
        self.assertEqual(source.read_bytes(), original)

    def test_cli_defaults_to_tomo_without_requiring_leef_source(self):
        self.write_rows([self.row("a", 1), self.row("a", 3)], "tomo")
        output = self.root / "default-model-b"
        self.assertFalse((self.raw / wfhs.DATASETS["leef"][0]).exists())
        with patch("sys.argv", [
            "wfhs_research", "prepare", "--raw-dir", str(self.raw), "--output", str(output),
        ]), redirect_stdout(io.StringIO()):
            wfhs.main()
        manifest = json.loads((output / "manifest.json").read_text())
        self.assertEqual(manifest["datasets"], ["tomo"])
        self.assertTrue((output / "tomo/observations.csv").is_file())
        self.assertFalse((output / "leef").exists())


if __name__ == "__main__":
    unittest.main()
