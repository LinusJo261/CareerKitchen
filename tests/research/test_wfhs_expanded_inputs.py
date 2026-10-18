"""Fictional fixtures check temporal boundaries, scale domains, and cohort stability."""

import csv
import tempfile
import unittest
from pathlib import Path

from scripts import wfhs_research as wfhs


class WFHSExpandedInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.raw = Path(self.temporary.name)
        self.development_group = self.group_for("train")
        self.reserved_group = self.group_for("test")

    @staticmethod
    def group_for(partition):
        return str(
            next(
                number
                for number in range(1, 1000)
                if wfhs.cluster_partition(f"tomo:{number}", 42) == partition
            )
        )

    def row(self, person, wave, *, group=None, extras=True):
        row = {
            "ADMINLINK": person,
            "WAVE": str(wave),
            "EMPLOYEE": "1",
            "MANAGER": "0",
            "CONDITION": "1",
            "STUDYGROUP": group or self.development_group,
            "EXCLUDE": "",
            wfhs.LABEL: repr(11 / 3),
            **{column: str(value) for column, value in zip(wfhs.LABEL_ITEMS, (3, 4, 4), strict=True)},
            **{column: "3" for column in wfhs.FEATURES.values()},
        }
        row["WM_HPQ1"] = "40"
        row["WM_HPQ2R"] = "40"
        if extras:
            row.update({column: "3" for column in wfhs.EXPANDED_FEATURES.values()})
        return row

    def write_rows(self, rows):
        source = self.raw / wfhs.DATASETS["tomo"][0]
        source.parent.mkdir(parents=True, exist_ok=True)
        with source.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        return source

    def prepare(self, *, expanded=True):
        return wfhs.prepare_dataset(self.raw, "tomo", development_only=True, expanded_features=expanded)

    def test_default_remains_six_features_without_requiring_extra_columns(self):
        self.write_rows([self.row("a", 1, extras=False), self.row("a", 3, extras=False)])
        default, audit = wfhs.prepare_dataset(self.raw, "tomo")
        development, _ = self.prepare(expanded=False)
        self.assertEqual(default, development)
        self.assertEqual(set(default[0]["features"]), set(wfhs.FEATURES))
        self.assertEqual(audit["feature_sources"], wfhs.FEATURES)
        self.assertFalse(audit["expanded_features"])
        self.assertEqual(audit["expanded_feature_directions"], {})
        self.assertEqual(
            audit["baseline_satisfaction_usage"], "persistence_baseline_only_not_a_model_feature"
        )

    def test_default_ignores_extra_numeric_values_and_expansion_requires_columns(self):
        baseline, followup = self.row("a", 1), self.row("a", 3)
        baseline.update({column: "not-selected" for column in wfhs.EXPANDED_FEATURES.values()})
        self.write_rows([baseline, followup])
        records, _ = self.prepare(expanded=False)
        self.assertEqual(set(records[0]["features"]), set(wfhs.FEATURES))
        self.write_rows([self.row("a", 1, extras=False), self.row("a", 3, extras=False)])
        with self.assertRaisesRegex(ValueError, "documented source columns"):
            self.prepare()

    def test_expansion_is_restricted_to_development_only_tomo(self):
        for dataset, development_only in (("tomo", False), ("leef", False), ("leef", True)):
            with self.subTest(dataset=dataset, development_only=development_only):
                with self.assertRaisesRegex(ValueError, "Tomo"):
                    wfhs.prepare_dataset(
                        self.raw,
                        dataset,
                        development_only=development_only,
                        expanded_features=True,
                    )

    def test_documented_scale_bounds_directions_and_missingness_are_audited(self):
        baseline, followup = self.row("a", 1), self.row("a", 3)
        baseline.update(SCWM_WTFC="1", SCWM_BURN="7", SCWM_OCLI="5")
        self.write_rows([baseline, followup])
        records, audit = self.prepare()
        self.assertEqual(len(records[0]["features"]), 9)
        self.assertEqual(records[0]["features"]["emotional_burnout"], 7)
        self.assertEqual(audit["feature_domains"]["emotional_burnout"], [1, 7])
        self.assertEqual(audit["feature_domains"]["work_to_family_conflict"], [1, 5])
        self.assertEqual(audit["feature_domains"]["work_family_climate"], [1, 5])
        self.assertEqual(audit["feature_missing_codes"]["emotional_burnout"], ["", -8])
        self.assertEqual(audit["feature_sources"], wfhs.FEATURES | wfhs.EXPANDED_FEATURES)
        self.assertIn("less_pressure", audit["expanded_feature_directions"]["work_family_climate"])
        self.assertNotIn("baseline_satisfaction", records[0]["features"])
        self.assertEqual(records[0]["baseline_satisfaction"], 11 / 3)
        self.assertEqual(
            audit["baseline_satisfaction_usage"],
            "separate_baseline_field_for_persistence_and_explicitly_named_forecast_variants",
        )

    def test_missing_extra_scales_retain_the_employee_without_using_followup_values(self):
        baseline, followup = self.row("a", 1), self.row("a", 3)
        baseline.update(SCWM_WTFC="-8", SCWM_BURN="", SCWM_OCLI=" -8 ")
        self.write_rows([baseline, followup])
        records, audit = self.prepare()
        self.assertEqual(len(records), 1)
        for name in wfhs.EXPANDED_FEATURES:
            self.assertIsNone(records[0]["features"][name])
            self.assertEqual(audit["baseline_feature_missing_counts"][name], 1)
        self.assertEqual(audit["usable_employee_pairs"], 1)

    def test_fractional_scale_means_are_preserved(self):
        baseline, followup = self.row("a", 1), self.row("a", 3)
        baseline.update(SCWM_WTFC="2.4", SCWM_BURN=repr(17 / 3), SCWM_OCLI=repr(10 / 3))
        self.write_rows([baseline, followup])
        records, _ = self.prepare()
        self.assertEqual(records[0]["features"]["work_to_family_conflict"], 2.4)
        self.assertEqual(records[0]["features"]["emotional_burnout"], 17 / 3)
        self.assertEqual(records[0]["features"]["work_family_climate"], 10 / 3)

    def test_out_of_range_nonfinite_and_undocumented_missing_codes_fail(self):
        cases = {
            "SCWM_WTFC": ("0", "5.1", "-4", "nan"),
            "SCWM_BURN": ("0", "7.1", "-7", "inf"),
            "SCWM_OCLI": ("0", "6", "-4", "not-numeric"),
        }
        for column, values in cases.items():
            for value in values:
                with self.subTest(column=column, value=value):
                    baseline, followup = self.row("a", 1), self.row("a", 3)
                    baseline[column] = value
                    self.write_rows([baseline, followup])
                    with self.assertRaisesRegex(ValueError, column):
                        self.prepare()

    def test_only_baseline_extra_features_are_ever_parsed(self):
        baseline = self.row("a", 1)
        baseline.update(SCWM_WTFC="2", SCWM_BURN="6", SCWM_OCLI="4")
        later = [self.row("a", wave) for wave in (2, 3, 4)]
        for row in later:
            row.update(
                {
                    column: "invalid-future-input"
                    for column in (*wfhs.FEATURES.values(), *wfhs.EXPANDED_FEATURES.values())
                }
            )
        self.write_rows([later[2], later[1], baseline, later[0]])
        records, _ = self.prepare()
        self.assertEqual(records[0]["features"]["work_to_family_conflict"], 2)
        self.assertEqual(records[0]["features"]["emotional_burnout"], 6)
        self.assertEqual(records[0]["features"]["work_family_climate"], 4)
        self.assertEqual(records[0]["features"]["hours_worked_last_week"], 40)

    def test_reserved_test_group_skips_numeric_inputs_and_outcomes_before_parsing(self):
        reserved = [self.row("reserved", wave, group=self.reserved_group) for wave in (1, 3)]
        for row in reserved:
            row.update(
                {
                    column: "deliberately-unread-reserved-value"
                    for column in (
                        wfhs.LABEL,
                        *wfhs.LABEL_ITEMS,
                        *wfhs.FEATURES.values(),
                        *wfhs.EXPANDED_FEATURES.values(),
                    )
                }
            )
        self.write_rows([self.row("eligible", 1), self.row("eligible", 3), *reserved])
        records, audit = self.prepare()
        self.assertEqual([row["person_id"] for row in records], ["tomo:eligible"])
        self.assertEqual(audit["exclusions"]["reserved_original_test_baseline_employee"], 1)

    def test_original_cohort_is_unchanged_even_if_extra_features_are_missing_or_available(self):
        missing_extra = self.row("missing-extra", 1)
        missing_extra.update({column: "-8" for column in wfhs.EXPANDED_FEATURES.values()})
        missing_base = self.row("missing-base", 1)
        missing_base.update(
            {column: "-7" if column in {"WM_HPQ1", "WM_HPQ2R"} else "-8" for column in wfhs.FEATURES.values()}
        )
        self.write_rows(
            [
                self.row("complete", 1),
                self.row("complete", 3),
                missing_extra,
                self.row("missing-extra", 3),
                missing_base,
                self.row("missing-base", 3),
                self.row("no-followup", 1),
            ]
        )
        original, original_audit = self.prepare(expanded=False)
        expanded, expanded_audit = self.prepare()
        self.assertEqual([row["person_id"] for row in expanded], [row["person_id"] for row in original])
        self.assertEqual(expanded_audit["exclusions"], original_audit["exclusions"])
        self.assertEqual(len(expanded), 2)
        for old, new in zip(original, expanded, strict=True):
            self.assertEqual(
                {key: new[key] for key in old if key != "features"},
                {key: old[key] for key in old if key != "features"},
            )
            self.assertEqual({key: new["features"][key] for key in wfhs.FEATURES}, old["features"])


if __name__ == "__main__":
    unittest.main()
