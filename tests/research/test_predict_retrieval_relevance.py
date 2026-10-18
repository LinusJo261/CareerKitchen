"""Fictional unlabeled submission contracts; no external score is fabricated."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import predict_retrieval_relevance as prediction
from scripts.train_retrieval_relevance import FEATURE_NAMES, PortableRetrievalRanker


def model():
    return PortableRetrievalRanker(
        means=(0.0,) * len(FEATURE_NAMES),
        scales=(1.0,) * len(FEATURE_NAMES),
        coefficients=(0.0,) * len(FEATURE_NAMES),
        regularization=1.0,
        source_sha256="a" * 64,
        training_job_clusters=10,
        training_positive_judgments=20,
        candidate_corpus_size=472,
    )


def write_source(path):
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(40):
            archive.writestr(f"TaskA/test/en/queries/PRIVATE_JOB_{index:03}.txt", "python data")
        for index in range(476):
            archive.writestr(f"TaskA/test/en/corpus/PRIVATE_CV_{index:03}.txt", "python analysis")


class PredictionTests(unittest.TestCase):
    def test_correct_full_pool_trec_format_and_deterministic_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fictional.zip"
            write_source(source)
            first, summary = prediction.test_predictions(source, model(), "LISTWISE_ML")
            second, repeated = prediction.test_predictions(source, model(), "LISTWISE_ML")
            self.assertEqual(first, second)
            self.assertEqual(summary, repeated)
            self.assertEqual(summary["prediction_rows"], 19040)
            self.assertFalse(summary["labels_available"])
            self.assertFalse(summary["external_submission_performed"])
            self.assertIsNone(summary["external_accuracy"])
            self.assertEqual(summary["submission_sha256"], hashlib.sha256(first.encode()).hexdigest())
            rows = [line.split("\t") for line in first.splitlines()]
            self.assertEqual(len(rows), 19040)
            self.assertTrue(
                all(len(row) == 6 and row[1] == "Q0" and row[5] == prediction.RUN_TAG for row in rows)
            )
            self.assertEqual([int(row[3]) for row in rows[:476]], list(range(1, 477)))
            self.assertEqual(rows[0][0], "PRIVATE_JOB_000.txt")
            self.assertEqual(rows[0][2], "PRIVATE_CV_000.txt")
            self.assertNotIn("PRIVATE_", json.dumps(summary))

    def test_selected_fallback_does_not_call_learned_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fictional.zip"
            write_source(source)
            with patch.object(
                PortableRetrievalRanker, "score_features", side_effect=AssertionError("ML not selected")
            ):
                _, summary = prediction.test_predictions(source, model(), "TFIDF_FALLBACK")
            self.assertEqual(summary["selected_policy"], "TFIDF_FALLBACK")
            with self.assertRaises(ValueError):
                prediction.test_predictions(source, model(), "UNKNOWN")

    def test_pinned_source_and_matching_final_policy_before_publication(self):
        local = prediction.ROOT / ".local"
        local.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local) as temporary:
            root = Path(temporary)
            source = root / "fictional.zip"
            write_source(source)
            artifact, policy = root / "model.json", root / "policy.json"
            artifact.write_text(json.dumps(model().to_dict()))
            policy.write_text(
                json.dumps(
                    {"model_sha256": "wrong", "final_model_policy": {"selected_policy": "LISTWISE_ML"}}
                )
            )
            output = root / "predictions"
            with self.assertRaisesRegex(ValueError, "exact model"):
                prediction.prepare(source, artifact, policy, output)
            self.assertFalse(output.exists())
            policy.write_text(
                json.dumps(
                    {
                        "model_sha256": model().to_dict()["model_sha256"],
                        "final_model_policy": {"selected_policy": "LISTWISE_ML"},
                    }
                )
            )
            with patch(
                "scripts.talentclef_source.load_source",
                return_value=({}, {}, {}, {"archive_sha256": "a" * 64}),
            ) as source_loader:
                summary = prediction.prepare(source, artifact, policy, output)
                source_loader.assert_called_once_with(source)
            self.assertTrue((output / "talentclef-test-en.run").is_file())
            self.assertEqual(json.loads((output / "report.json").read_text()), summary)
            with self.assertRaises(FileExistsError):
                prediction.prepare(source, artifact, policy, output)
            with self.assertRaisesRegex(ValueError, "ignored"):
                prediction.prepare(source, artifact, policy, prediction.ROOT / "docs" / "unused-predictions")


if __name__ == "__main__":
    unittest.main()
