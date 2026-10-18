"""Offline end-to-end fixtures, never downloads or production database writes."""

import contextlib
import copy
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.matching_research import FILES, resume_partitions, run, validate_tables


def fixture_tables():
    resumes = [{
        "resume_id": f"R_{index:03}", "role": "Engineer", "seniority": "Mid",
        "summary": f"Fictional profile {index}", "experience_bullets": ["Build tools"],
        "skills": ["Python", "SQL"] if index % 2 else ["Java"],
    } for index in range(100)]
    jobs = [{
        "job_id": f"J_{index:03}", "job_title": f"Fictional engineer {index}",
        "seniority": "Mid", "description": "Fictional engineering role",
        "responsibilities": ["Build tools"], "must_have_skills": ["Python"],
        "nice_to_have_skills": ["SQL"],
    } for index in range(60)]
    matches = [{"job_id": job["job_id"], "relevant_resume_ids": [
        resume["resume_id"] for resume in resumes if "Python" in resume["skills"]
    ][:30]} for job in jobs]
    return {"resumes": resumes, "jobs": jobs, "matches": matches}


class PipelineTests(unittest.TestCase):
    def test_equivalent_resume_content_cannot_cross_holdouts(self):
        rows = fixture_tables()["resumes"]
        twin = copy.deepcopy(rows[0])
        twin.update({"resume_id": "R_TWIN", "role": " ENGINEER ",
                     "summary": "  FICTIONAL   profile 0 ", "experience_bullets": ["tools Build"]})
        corpora, diagnostics = resume_partitions([*rows, twin], 42)
        membership = {rid: split for split, corpus in corpora.items() for rid in corpus.ids}
        self.assertEqual(membership["R_000"], membership["R_TWIN"])
        self.assertEqual(diagnostics["duplicate_model_visible_resume_rows"], 1)

    def test_invalid_references_and_inconsistent_labels_fail_closed(self):
        tables = fixture_tables()
        validate_tables(tables)
        bad = copy.deepcopy(tables)
        bad["matches"][0]["relevant_resume_ids"] = ["absent"]
        with self.assertRaisesRegex(ValueError, "dangling"):
            validate_tables(bad)
        bad = copy.deepcopy(tables)
        bad["matches"][0]["relevant_resume_ids"] = ["R_000"]
        with self.assertRaisesRegex(ValueError, "contradict"):
            validate_tables(bad)

    def test_local_parquet_training_exports_replayable_offline_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tables = fixture_tables()
            for name, filename in FILES.items():
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(pa.Table.from_pylist(tables[name]), path)
            args = Namespace(
                command="train", data_dir=root, download=False, output=root / "output",
                seed=42, k=5, max_jobs=3, pairs_per_class=5, l2=.01, epochs=100,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                report = run(args)
            self.assertIsNone(report["revision"])
            self.assertEqual(report["source"], "local_override")
            self.assertFalse(report["live_execution"])
            self.assertEqual(len(report["file_sha256"]), 3)
            self.assertLess(report["model"]["final_loss"], report["model"]["initial_loss"])
            exported = json.loads((args.output / "synthetic_relevance_model.json").read_text())
            self.assertEqual(exported["output"], "uncalibrated_logit")
            self.assertEqual(len(exported["weights"]), 5)
            self.assertEqual(exported["positive_pairs"], exported["negative_pairs"])
            for scenario in report["results"].values():
                self.assertIn("learned_synthetic_relevance", scenario["metrics"])
                sample = scenario["first_job_examples"]["learned_synthetic_relevance"]["first_five"]
                if sample:
                    self.assertEqual(len(sample[0]["features"]), 5)
            with contextlib.redirect_stdout(io.StringIO()):
                replay = run(args)
            self.assertEqual(report, replay)


if __name__ == "__main__":
    unittest.main()
