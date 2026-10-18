"""Fictional text fixtures check benchmark semantics; never hiring outcomes."""

import hashlib
import io
import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import matching_text_benchmark as benchmark


def docx(text):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return result.getvalue()


def annotations():
    return {
        name: [[1, 2, 3, 4, 5] for _ in range(30)]
        for name in ("ANNOTATOR_1_RANKINGS", "ANNOTATOR_2_RANKINGS")
    }


def annotation_text(rows=None):
    rows = annotations() if rows is None else rows
    return "Source explanatory text\n" + "\n".join(f"{name}={value!r}" for name, value in rows.items())


def source_fixture(path):
    with zipfile.ZipFile(path, "w") as archive:
        files = {
            "README.md": b"Fictional fixture only",
            "LICENSE": b"GNU GENERAL PUBLIC LICENSE Version 3",
            "annotation_instructions.docx": docx("Fictional annotation guidance"),
            benchmark.ANNOTATIONS: annotation_text().encode(),
            "5_vacancies.csv": (
                "id,job_description,job_title,uid\n"
                + "\n".join(
                    f"{document_id},fixture description {index},fixture title {index},U{index}"
                    for index, document_id in enumerate([8, 37, 90, 207, 499])
                )
            ).encode(),
        }
        files.update({f"CV/{index}.docx": docx(f"PRIVATE_FIXTURE_TEXT {index}") for index in range(1, 66)})
        for name, data in files.items():
            archive.writestr(benchmark.ROOT + name, data)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AnnotationTests(unittest.TestCase):
    def test_malformed_rater_row_preserves_cv_position_and_other_rater(self):
        rows = annotations()
        rows["ANNOTATOR_1_RANKINGS"][8] = [1, 5, 2, 1, 4]
        parsed, excluded = benchmark.parse_annotations(annotation_text(rows))
        self.assertIsNone(parsed["ANNOTATOR_1_RANKINGS"][8])
        self.assertEqual(parsed["ANNOTATOR_1_RANKINGS"][9], [1, 2, 3, 4, 5])
        self.assertEqual(parsed["ANNOTATOR_2_RANKINGS"][8], [1, 2, 3, 4, 5])
        self.assertEqual(excluded, {"ANNOTATOR_1_RANKINGS": 1, "ANNOTATOR_2_RANKINGS": 0})

    def test_never_executes_annotation_code(self):
        with self.assertRaises((ValueError, SyntaxError)):
            benchmark.parse_annotations(annotation_text() + "\n__import__('os').system('false')")

    def test_incomplete_annotation_join_is_rejected(self):
        rows = annotations()
        rows["ANNOTATOR_2_RANKINGS"].pop()
        with self.assertRaisesRegex(ValueError, "exactly 30"):
            benchmark.parse_annotations(annotation_text(rows))

    def test_duplicate_annotator_assignment_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "two known"):
            benchmark.parse_annotations(annotation_text() + "\nANNOTATOR_1_RANKINGS=[]")


class RankingTests(unittest.TestCase):
    def test_human_order_is_vacancy_ids_in_best_first_order(self):
        metrics = benchmark.ranking_metrics([4, 2, 5, 3, 1], [3, 1, 4, 2, 5])
        self.assertEqual(metrics["pairwise_agreement"], 1)
        self.assertEqual(metrics["top1_agreement"], 1)
        self.assertEqual(metrics["mrr_human_first_choice"], 1)
        reversed_metrics = benchmark.ranking_metrics([4, 2, 5, 3, 1], [5, 2, 4, 1, 3])
        self.assertEqual(reversed_metrics["pairwise_agreement"], 0)

    def test_predicted_ties_receive_expected_random_tie_order_credit(self):
        metrics = benchmark.ranking_metrics([1, 1, 1, 1, 1], [1, 2, 3, 4, 5])
        self.assertEqual(metrics["pairwise_agreement"], 0.5)
        self.assertEqual(metrics["top1_agreement"], 0.2)
        self.assertAlmostEqual(metrics["mrr_human_first_choice"], sum(1 / rank for rank in range(1, 6)) / 5)
        partial = benchmark.ranking_metrics([3, 2, 2, 0, 0], [2, 1, 3, 4, 5])
        self.assertEqual(partial["top1_agreement"], 0)
        self.assertAlmostEqual(partial["mrr_human_first_choice"], (1 / 2 + 1 / 3) / 2)

    def test_nonfinite_scores_and_malformed_human_order_rejected(self):
        with self.assertRaises(ValueError):
            benchmark.ranking_metrics([math.nan, 0], [1, 2])
        with self.assertRaises(ValueError):
            benchmark.ranking_metrics([1, 0], [1, 1])

    def test_tokenizer_preserves_language_suffixes_and_unicode_normalization(self):
        self.assertEqual(
            benchmark.tokens("Ｃ＋＋ C# Python REST.API naïve"), ["c++", "c#", "python", "rest.api", "naïve"]
        )

    def test_fixed_lexical_methods_match_relevant_words_without_labels(self):
        scores = benchmark.score_documents("python python c++", ["python c++", "pastry baking", "python"])
        for method in benchmark.METHODS:
            self.assertGreater(scores[method][0], scores[method][1])
            self.assertGreater(scores[method][2], scores[method][1])
            self.assertEqual(scores[method][1], 0)
        self.assertAlmostEqual(scores["lexical_jaccard"][0], 1)

    def test_oov_queries_tie_without_fabricated_similarity(self):
        scores = benchmark.score_documents("unknown", ["python", "java"])
        self.assertEqual(scores, {method: [0.0, 0.0] for method in benchmark.METHODS})


class SourceAndReportTests(unittest.TestCase):
    def test_pinned_source_hash_inventory_and_exact_csv_join(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.zip"
            checksum = source_fixture(source)
            with mock.patch.object(benchmark, "ARCHIVE_SHA256", checksum):
                jobs, resumes, raters, provenance = benchmark.load_source(source)
                self.assertEqual((len(jobs), len(resumes), len(raters)), (5, 30, 2))
                self.assertEqual(len(provenance["all_file_sha256"]), 70)
            with self.assertRaisesRegex(ValueError, "SHA256"):
                benchmark.load_source(source)

    def test_inventory_cannot_silently_add_or_remove_cv_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.zip"
            source_fixture(source)
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr(benchmark.ROOT + "unexpected.txt", "Fictional extra")
            checksum = hashlib.sha256(source.read_bytes()).hexdigest()
            with (
                mock.patch.object(benchmark, "ARCHIVE_SHA256", checksum),
                self.assertRaisesRegex(ValueError, "inventory"),
            ):
                benchmark.load_source(source)

    def test_aggregate_report_replay_no_raw_text_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary) / "source.zip", Path(temporary) / "run-1"
            checksum = source_fixture(source)
            with mock.patch.object(benchmark, "ARCHIVE_SHA256", checksum):
                report = benchmark.run_benchmark(source, output)
                self.assertTrue(report["deterministic_replay_verified"])
                self.assertFalse(report["label_training_or_tuning"])
                self.assertNotIn("PRIVATE_FIXTURE_TEXT", (output / "report.json").read_text())
                self.assertNotIn("fixture description", (output / "report.json").read_text())
                self.assertEqual(json.loads((output / "report.json").read_text()), report)
                with self.assertRaises(FileExistsError):
                    benchmark.run_benchmark(source, output)

    def test_raters_remain_separate_and_invalid_rows_do_not_inflate_denominators(self):
        rows = annotations()
        rows["ANNOTATOR_1_RANKINGS"][0] = None
        rows["ANNOTATOR_2_RANKINGS"] = [[5, 4, 3, 2, 1] for _ in range(30)]
        report = benchmark.evaluate(["python", "java", "sql", "c++", "baking"], ["python"] * 30, rows)
        result = report["methods"]["lexical_jaccard"]
        self.assertEqual(result["pooled_query_rater_count"], 59)
        self.assertEqual(result["per_rater"]["ANNOTATOR_1_RANKINGS"]["queries"], 29)
        self.assertEqual(result["per_rater"]["ANNOTATOR_1_RANKINGS"]["top1_agreement"], 1)
        self.assertEqual(result["per_rater"]["ANNOTATOR_2_RANKINGS"]["top1_agreement"], 0)
        self.assertEqual(report["human_inter_rater_agreement"]["pairwise_agreement"], 0)

    def test_source_failure_does_not_publish_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result"
            with self.assertRaises(FileNotFoundError):
                benchmark.run_benchmark(Path(temporary) / "missing.zip", output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
