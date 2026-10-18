"""Independent contract examples for public relevance evaluation reports."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import benchmark_text_relevance as benchmark
from scripts.train_text_relevance import PortableTextRanker


class BenchmarkTests(unittest.TestCase):
    def test_disagreeing_reviewers_bound_attainable_top_one(self):
        report = benchmark.human_agreement({"one": [[1, 2], [1, 2], None], "two": [[2, 1], [1, 2], [2, 1]]})
        self.assertEqual(report["two_rater_first_choice_agreement"], 0.5)
        self.assertEqual(report["oracle_maximum_pooled_top1_agreement"], 4 / 5)
        self.assertFalse(report["oracle_is_used_for_training_or_normalizing_accuracy"])

    def test_actual_nested_fit_transfer_replay_and_nonproduction_artifact(self):
        jobs = ["python data science", "welding industrial safety"]
        resumes = [f"python data science engineer {index}" for index in range(10)]
        annotations = {"first": [[1, 2] for _ in resumes], "second": [[1, 2] for _ in resumes]}
        provenance = {"archive_sha256": "a" * 64}
        concepts = [{"id": "python", "preferred_label": "python", "aliases": []}]
        talent_jobs = {"job1": "python data", "job2": "industrial welding"}
        candidates = {
            "cv1": "python data science",
            "cv2": "welding industrial safety",
            "cv3": "accounting finance",
        }
        qrels = {"job1": {"cv1": 1}, "job2": {"cv2": 1}}
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(benchmark, "_fingerprints", return_value={"fixed": "b" * 64}),
            patch.object(
                benchmark, "load_human_source", return_value=(jobs, resumes, annotations, provenance)
            ),
            patch(
                "scripts.esco_source.load_source", return_value=(concepts, {"source": "fictional fixture"})
            ),
            patch(
                "scripts.talentclef_source.load_source",
                return_value=(talent_jobs, candidates, qrels, {"source": "fictional fixture"}),
            ),
        ):
            first_path = Path(temporary) / "first"
            first = benchmark.run_benchmark(
                Path("human"), Path("talent"), Path("esco"), first_path, bootstrap_replicates=1000
            )
            second = benchmark.run_benchmark(
                Path("human"),
                Path("talent"),
                Path("esco"),
                Path(temporary) / "second",
                bootstrap_replicates=1000,
            )
            self.assertEqual(first["protocol_sha256"], second["protocol_sha256"])
            self.assertEqual(first["datasets"], second["datasets"])
            self.assertFalse(first["production_model_promoted"])
            self.assertIsNone(first["production_matching_accuracy"])
            artifact = json.loads((first_path / "public-ordinal-model.json").read_text())
            self.assertEqual(
                PortableTextRanker.from_dict(artifact).to_dict()["model_sha256"], first["fitted_model_sha256"]
            )
            self.assertNotIn("cv1", (first_path / "report.json").read_text())
            self.assertNotIn("python data science", (first_path / "public-ordinal-model.json").read_text())
            self.assertEqual(
                first["datasets"]["vanetik_nested_cv"]["results"]["methods"][benchmark.LEARNED][
                    "pooled_query_rater"
                ]["top1_agreement"],
                1.0,
            )
            with self.assertRaises(FileExistsError):
                benchmark.run_benchmark(
                    Path("human"), Path("talent"), Path("esco"), first_path, bootstrap_replicates=1000
                )
            changed_output = Path(temporary) / "changed-code"
            with patch.object(benchmark, "_fingerprints", side_effect=[{}, {"changed": "c"}]):
                with self.assertRaisesRegex(ValueError, "source changed"):
                    benchmark.run_benchmark(
                        Path("human"),
                        Path("talent"),
                        Path("esco"),
                        changed_output,
                        bootstrap_replicates=1000,
                    )
            self.assertFalse(changed_output.exists())

    def test_source_failure_does_not_publish_partial_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "failed"
            with (
                patch.object(benchmark, "_fingerprints", side_effect=[{}, {"changed": "c"}]),
                patch("scripts.esco_source.load_source", return_value=([], {})),
                patch.object(
                    benchmark, "load_human_source", side_effect=ValueError("fixture loader stopped")
                ),
            ):
                with self.assertRaises(ValueError):
                    benchmark.run_benchmark(
                        Path("human"), Path("talent"), Path("esco"), output, bootstrap_replicates=1000
                    )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
