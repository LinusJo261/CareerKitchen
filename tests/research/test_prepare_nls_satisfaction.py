"""Explicitly fictional mini exports verify preparation, not survey performance."""

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.prepare_nls_satisfaction import LABELS, parse_codebook, prepare
from scripts.satisfaction_research import load_records


class PrepareNlsSatisfactionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def basic(self, year=1998, slot=1, separator="~"):
        suffix = f".{slot:02d}"
        return {(1997, "PUBID"): 101, (year, "YEMP-101200" + suffix): 1,
                (year, "YEMP_UID" + suffix): 9801, (year, "YEMP_CURFLAG" + suffix): 1,
                (year, "YEMP_STARTDATE" + suffix + separator + "Y"): 1998,
                (year, "YEMP_STARTDATE" + suffix + separator + "M"): 1,
                (year, "YEMP_STOPDATE" + suffix + separator + "Y"): 1998,
                (year, "YEMP_STOPDATE" + suffix + separator + "M"): 5,
                (year, "CV_INTERVIEW_DATE" + separator + "Y"): 1998,
                (year, "CV_INTERVIEW_DATE" + separator + "M"): 7,
                (year, "YEMP-23901" + suffix): 40, (year, "YEMP-34402" + suffix): -4}

    def export(self, rows):
        names = sorted(set().union(*(row.keys() for row in rows)))
        columns, blocks = {}, []
        for index, (year, name) in enumerate(names, 1):
            ref = f"R{index:05d}.00"
            columns[year, name] = ref.replace(".", "")
            labels = "\n".join(f"   10   {code} {label}" for code, label in LABELS.items()) if name.startswith("YEMP-101200.") else ""
            blocks.append(f"{ref}    [{name}]          Survey Year: {year}\n  PRIMARY VARIABLE\n\n  FICTIONAL {name}\n{labels}\n" + "-" * 80 + "\n")
        codebook = self.root / "fictional.cdb"
        codebook.write_text("".join(blocks))
        path = self.root / "fictional.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns.values())
            writer.writeheader()
            writer.writerows({columns[name]: row.get(name, -4) for name in names} for row in rows)
        return path, codebook

    def run_prepare(self, rows):
        csv_path, cdb = self.export(rows)
        report = prepare(csv_path, cdb, self.root / "prepared")
        with (self.root / "prepared/observations.csv").open(newline="") as handle:
            observations = list(csv.DictReader(handle))
        return report, observations

    def test_reference_mapping_and_label_semantics(self):
        _, codebook = self.export([self.basic()])
        metadata = parse_codebook(codebook)
        item = metadata[1998, "YEMP-101200.01"]
        self.assertEqual(item["column"], item["reference"].replace(".", ""))
        codebook.write_text(codebook.read_text().replace("1 Like it very much", "1 Dislike it very much"))
        with self.assertRaisesRegex(ValueError, "confirm codes"):
            parse_codebook(codebook)

    def test_tilde_and_underscore_dates(self):
        for separator in ("~", "_"):
            report, observations = self.run_prepare([self.basic(separator=separator)])
            self.assertEqual(report["retained_observations"], 1)
            self.assertEqual(observations[0]["job_started_at"], "1998-01")
            self.assertEqual(observations[0]["weekly_hours_at_start"], "40")

    def test_crosswave_slot_permutations_do_not_join_on_uid_or_slot_alone(self):
        row = self.basic()
        row.update(self.basic(year=1999, slot=2))
        row[1999, "YEMP_UID.02"] = 9801
        row[1999, "YEMP-23901.02"] = 25
        row[1999, "YEMP_STARTDATE.02~Y"] = 1999
        row[1999, "CV_INTERVIEW_DATE~Y"] = 1999
        report, observations = self.run_prepare([row])
        self.assertEqual(report["retained_observations"], 2)
        self.assertEqual([r["weekly_hours_at_start"] for r in observations], ["40", "25"])
        self.assertEqual([r["job_started_at"] for r in observations], ["1998-01", "1999-01"])

    def test_ongoing_and_ended_reference_months(self):
        ongoing, ended = self.basic(), self.basic()
        ended[1997, "PUBID"] = 102
        ended[1998, "YEMP_CURFLAG.01"] = 0
        ended[1998, "YEMP-101200.01"] = 5
        _, observations = self.run_prepare([ongoing, ended])
        self.assertEqual([r["rating_reference_at"] for r in observations], ["1998-07", "1998-05"])
        self.assertEqual([r["satisfaction"] for r in observations], ["1", "5"])

    def test_later_wave_missing_own_dates_not_backfilled(self):
        row = self.basic()
        row.update({(2023, "YEMP-101200.01"): 1, (2023, "YEMP_UID.01"): 9801,
                    (2023, "YEMP_CURFLAG.01"): 1, (2023, "YEMP-23901.01"): 30,
                    (2023, "CV_INTERVIEW_DATE~Y"): 2024, (2023, "CV_INTERVIEW_DATE~M"): 1})
        report, observations = self.run_prepare([row])
        self.assertEqual(len(observations), 1)
        self.assertEqual(report["excluded"], {"missing_required_columns": 1})
        self.assertEqual(report["field_coverage_by_survey_year"]["2023"]["start_slots"], 0)
        self.assertIn("start", report["missing_columns"][0]["fields"])

    def test_home_hours_never_substitute_total_hours(self):
        row = self.basic()
        row[1998, "YEMP-23901.01"] = -4
        row[1998, "YEMP-23901H.01"] = 35
        row[1998, "YEMP-34402H.01"] = 35
        report, observations = self.run_prepare([row])
        self.assertFalse(observations)
        self.assertEqual(report["excluded"], {"missing_start_hours": 1})

    def test_conflicting_and_out_of_range_hours_excluded(self):
        conflict, extreme = self.basic(), self.basic()
        conflict[1998, "YEMP-34402.01"] = 30
        extreme[1997, "PUBID"] = 102
        extreme[1998, "YEMP-23901.01"] = 169
        report, observations = self.run_prepare([conflict, extreme])
        self.assertFalse(observations)
        self.assertEqual(report["excluded"], {"conflicting_start_hours": 1, "hours_out_of_range": 1})

    def test_equal_branches_and_nonhourly_branch(self):
        equal, nonhourly = self.basic(), self.basic()
        equal[1998, "YEMP-34402.01"] = 40
        nonhourly[1997, "PUBID"] = 102
        nonhourly[1998, "YEMP-23901.01"] = -4
        nonhourly[1998, "YEMP-34402.01"] = 20
        _, observations = self.run_prepare([equal, nonhourly])
        self.assertEqual([r["weekly_hours_at_start"] for r in observations], ["40", "20"])

    def test_fractional_hours_valid_and_nonfinite_hours_rejected(self):
        fractional, invalid = self.basic(), self.basic()
        fractional[1998, "YEMP-23901.01"] = 37.5
        invalid[1997, "PUBID"] = 102
        invalid[1998, "YEMP-23901.01"] = "NaN"
        invalid[1998, "YEMP-34402.01"] = 40
        report, observations = self.run_prepare([fractional, invalid])
        self.assertEqual([r["weekly_hours_at_start"] for r in observations], ["37.5"])
        self.assertEqual(report["excluded"], {"hours_out_of_range": 1})

    def test_missing_invalid_dates_and_followup_are_separate_exclusions(self):
        rows = [self.basic() for _ in range(3)]
        for index, row in enumerate(rows):
            row[1997, "PUBID"] = 101 + index
        rows[0][1998, "YEMP_STARTDATE.01~M"] = -2
        rows[1][1998, "YEMP_STARTDATE.01~M"] = 8
        rows[2][1998, "YEMP_STARTDATE.01~M"] = 6
        report, observations = self.run_prepare(rows)
        self.assertFalse(observations)
        self.assertEqual(sum(report["excluded"].values()), report["valid_labels_considered"])
        self.assertEqual(set(report["excluded"]), {"missing_or_invalid_dates", "invalid_timeline", "outside_followup_window"})

    def test_provenance_hashes_and_no_respondent_data_in_report(self):
        path, codebook = self.export([self.basic()])
        report = prepare(path, codebook, self.root / "prepared")
        mapping = json.loads((self.root / "prepared/mapping.json").read_text())
        self.assertEqual(mapping["source"]["csv_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(mapping["source"]["codebook_sha256"], hashlib.sha256(codebook.read_bytes()).hexdigest())
        self.assertEqual(mapping["source"]["release"], "local-export-survey-years-1997-1998")
        self.assertEqual(mapping["features"]["numeric"], {"weekly_hours_at_start": "weekly_hours_at_start"})
        self.assertNotIn("person_id", report)
        self.assertEqual(report, prepare(path, codebook, self.root / "prepared"))

    def test_prepared_hours_feature_is_accepted_by_training_pipeline(self):
        path, codebook = self.export([self.basic()])
        output = self.root / "prepared"
        prepare(path, codebook, output)
        mapping = json.loads((output / "mapping.json").read_text())
        records, diagnostics = load_records(output / "observations.csv", mapping)
        self.assertEqual(records[0]["features"], {"weekly_hours_at_start": 40.0})
        self.assertEqual(diagnostics["usable_spells"], 1)

    def test_duplicate_respondents_and_headers_rejected(self):
        path, codebook = self.export([self.basic(), self.basic()])
        with self.assertRaisesRegex(ValueError, "unique"):
            prepare(path, codebook, self.root / "prepared")
        path.write_text("duplicate,duplicate\n1,1\n")
        with self.assertRaisesRegex(ValueError, "duplicate headers"):
            prepare(path, codebook, self.root / "prepared")

    def test_preparation_cannot_overwrite_raw_csv(self):
        path, codebook = self.export([self.basic()])
        raw = self.root / "observations.csv"
        path.rename(raw)
        original = raw.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite a raw"):
            prepare(raw, codebook, self.root)
        self.assertEqual(raw.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
