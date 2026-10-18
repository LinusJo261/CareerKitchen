"""Fictional end-to-end listwise validation; these scores are not real evidence."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import benchmark_retrieval_relevance as benchmark
from scripts.train_retrieval_relevance import PortableRetrievalRanker

JOBS = {
    "PRIVATE_JOB_A": "python analysis",
    "PRIVATE_JOB_B": "welding safety",
    "PRIVATE_JOB_C": "accounting finance",
}
CANDIDATES = {
    "PRIVATE_CV_A": "python data analysis",
    "PRIVATE_CV_B": "industrial welding safety",
    "PRIVATE_CV_C": "accounting finance report",
    "PRIVATE_CV_D": "retail store sales",
}
JUDGMENTS = {
    "PRIVATE_JOB_A": {"PRIVATE_CV_A": 1},
    "PRIVATE_JOB_B": {"PRIVATE_CV_B": 1},
    "PRIVATE_JOB_C": {"PRIVATE_CV_C": 1},
}
CONCEPTS = [{"id": "python", "preferred_label": "python", "aliases": []}]
PROVENANCE = {"archive_sha256": "a" * 64, "fictional_source": True}


class BenchmarkTests(unittest.TestCase):
    def test_actual_nested_model_replay_report_unknown_policy_and_immutable_output(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(benchmark, "_fingerprints", return_value={"fixed": "b" * 64}),
            patch("scripts.esco_source.load_source", return_value=(CONCEPTS, {"fictional": True})),
            patch(
                "scripts.talentclef_source.load_source",
                return_value=(JOBS, CANDIDATES, JUDGMENTS, PROVENANCE),
            ),
        ):
            output = Path(temporary) / "one"
            first = benchmark.run_benchmark(Path("talent"), Path("esco"), output, bootstrap_replicates=1000)
            second = benchmark.run_benchmark(
                Path("talent"), Path("esco"), Path(temporary) / "two", bootstrap_replicates=1000
            )
            self.assertEqual(first["protocol_sha256"], second["protocol_sha256"])
            self.assertEqual(first["results"], second["results"])
            self.assertEqual(first["model_sha256"], second["model_sha256"])
            self.assertFalse(first["production_model_promoted"])
            self.assertFalse(first["binary_accuracy_measured"])
            self.assertIsNone(first["production_matching_accuracy"])
            self.assertTrue(first["portable_artifact_replay_verified"])
            self.assertEqual(first["results"]["source_judgments"]["explicit_unsuitable_pairs"], 0)
            self.assertEqual(first["results"]["source_judgments"]["unjudged_scored_pairs"], 9)
            self.assertEqual(
                first["results"]["unlisted_candidate_policy"], "uncredited_not_confirmed_negative"
            )
            self.assertEqual(first["validation"]["outer_whole_job_folds"], 3)
            self.assertEqual(
                first["validation"]["ml_selected_outer_jobs"]
                + first["validation"]["tfidf_selected_outer_jobs"],
                3,
            )
            artifact = json.loads((output / "public-retrieval-model.json").read_text())
            self.assertEqual(
                PortableRetrievalRanker.from_dict(artifact).to_dict()["model_sha256"], first["model_sha256"]
            )
            serialized = (output / "report.json").read_text() + (
                output / "public-retrieval-model.json"
            ).read_text()
            for private in ("PRIVATE_JOB_", "PRIVATE_CV_", '"individual_scores"', '"qrels"', '"predictions"'):
                self.assertNotIn(private, serialized)
            protocol = json.loads((output / "protocol.json").read_text())
            self.assertEqual(
                hashlib.sha256(json.dumps(protocol, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                first["protocol_sha256"],
            )
            with self.assertRaises(FileExistsError):
                benchmark.run_benchmark(Path("talent"), Path("esco"), output, bootstrap_replicates=1000)
            changed = Path(temporary) / "changed"
            with patch.object(benchmark, "_fingerprints", side_effect=[{}, {"new": "hash"}]):
                with self.assertRaisesRegex(ValueError, "sources changed"):
                    benchmark.run_benchmark(Path("talent"), Path("esco"), changed, bootstrap_replicates=1000)
            self.assertFalse(changed.exists())

    def test_protocol_serialized_before_labels_and_negative_or_unknown_joins_rejected(self):
        original = json.dumps
        frozen = []

        def dumps(value, *args, **kwargs):
            result = original(value, *args, **kwargs)
            if (
                isinstance(value, dict)
                and value.get("protocol_version") == benchmark.PROTOCOL_VERSION
                and "training" in value
            ):
                frozen.append(result)
            return result

        def loader(_):
            self.assertTrue(frozen)
            self.assertFalse(json.loads(frozen[0])["candidate_corpus_holdout"])
            return JOBS, CANDIDATES, {**JUDGMENTS, "PRIVATE_JOB_A": {"PRIVATE_CV_A": 0}}, PROVENANCE

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(benchmark, "_fingerprints", return_value={}),
            patch("scripts.esco_source.load_source", return_value=(CONCEPTS, {})),
            patch("scripts.talentclef_source.load_source", side_effect=loader),
            patch.object(benchmark.json, "dumps", side_effect=dumps),
        ):
            output = Path(temporary) / "invalid"
            with self.assertRaisesRegex(ValueError, "positive-only"):
                benchmark.run_benchmark(Path("talent"), Path("esco"), output, bootstrap_replicates=1000)
            self.assertFalse(output.exists())

    def test_bad_bootstrap_rejected_before_source_access(self):
        for invalid in (True, 999, 1000.0):
            with self.assertRaises(ValueError):
                benchmark.run_benchmark(
                    Path("talent"), Path("esco"), Path("unused-new-evaluation"), bootstrap_replicates=invalid
                )


if __name__ == "__main__":
    unittest.main()
