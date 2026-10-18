"""Fictional orchestration checks; their scores are not real matching evidence."""

import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

from scripts import benchmark_matching_accuracy as benchmark

CONCEPTS = [
    {
        "id": "http://data.europa.eu/esco/skill/00000000-0000-0000-0000-000000000001",
        "preferred_label": "Python",
        "aliases": ["python programming"],
    },
    {
        "id": "http://data.europa.eu/esco/skill/00000000-0000-0000-0000-000000000002",
        "preferred_label": "Java",
        "aliases": ["java programming"],
    },
]
HUMAN_SOURCE = Path("FICTIONAL_HUMAN_ARCHIVE.zip")
TALENT_SOURCE = Path("FICTIONAL_TALENT_ARCHIVE.zip")
ESCO_SOURCE = Path("FICTIONAL_ESCO_DIRECTORY")
HUMAN = (
    ["PRIVATE_JOB_ALPHA Python", "PRIVATE_JOB_BETA Java"],
    ["PRIVATE_CV_ALPHA Python", "PRIVATE_CV_BETA Java"],
    {"rater_a": [[1, 2], [2, 1]], "rater_b": [[2, 1], [2, 1]]},
    {"fictional_data": True, "source_kind": "FICTIONAL_TEST_FIXTURE", "queries": 2},
)
TALENT = (
    {"private_job_alpha": "PRIVATE_JOB_ALPHA Python", "private_job_beta": "PRIVATE_JOB_BETA Java"},
    {"private_cv_alpha": "PRIVATE_CV_ALPHA Python", "private_cv_beta": "PRIVATE_CV_BETA Java"},
    {"private_job_alpha": {"private_cv_alpha": 1}, "private_job_beta": {"private_cv_beta": 1}},
    {
        "fictional_data": True,
        "source_kind": "FICTIONAL_TEST_FIXTURE",
        "possible_pairs": 4,
        "explicit_judgments": 2,
        "explicit_positive_judgments": 2,
        "explicit_negative_judgments": 0,
        "unjudged_pairs": 2,
        "judgment_coverage": 0.5,
    },
)
FINGERPRINTS = {
    filename: hashlib.sha256(filename.encode()).hexdigest() for filename in benchmark.SOURCE_FILES
}


@contextmanager
def fixture_sources(*, human_loader=None, talent_loader=None, fingerprints=None):
    """Only source acquisition is faked; extraction, scoring and metrics run."""
    with ExitStack() as stack:
        stack.enter_context(
            mock.patch.object(
                benchmark,
                "load_human_source",
                **({"side_effect": human_loader} if human_loader else {"return_value": HUMAN}),
            )
        )
        stack.enter_context(
            mock.patch(
                "scripts.talentclef_source.load_source",
                **({"side_effect": talent_loader} if talent_loader else {"return_value": TALENT}),
            )
        )
        stack.enter_context(
            mock.patch(
                "scripts.esco_source.load_source",
                return_value=(CONCEPTS, {"fictional_data": True, "license": "FICTIONAL_TEST_VOCABULARY"}),
            )
        )
        fingerprint_mock = stack.enter_context(
            mock.patch.object(
                benchmark,
                "_fingerprints",
                **({"side_effect": fingerprints} if fingerprints else {"return_value": FINGERPRINTS}),
            )
        )
        yield fingerprint_mock


def run(output, **kwargs):
    return benchmark.run_benchmark(
        HUMAN_SOURCE,
        TALENT_SOURCE,
        ESCO_SOURCE,
        output,
        seed=99,
        bootstrap_replicates=1000,
        **kwargs,
    )


class AccuracyBenchmarkTests(unittest.TestCase):
    def test_actual_component_math_and_metrics_keep_scope_and_sparse_labels(self):
        with tempfile.TemporaryDirectory() as temporary, fixture_sources():
            output = Path(temporary) / "complete"
            report = run(output)
            self.assertTrue(report["evaluation_completed"])
            self.assertTrue(report["compatibility_core_experiment"])
            self.assertIsNone(report["production_matching_accuracy"])
            self.assertEqual(report["full_native_input_coverage"], 0)
            self.assertFalse(report["active_ml_model_evaluated"])
            human = report["datasets"]["vanetik_human_rankings"]["results"]
            measured = human["methods"][benchmark.REFERENCE]["pooled_query_rater"]
            self.assertAlmostEqual(measured["top1_agreement"], 0.75)
            self.assertAlmostEqual(measured["pairwise_agreement"], 0.75)
            self.assertAlmostEqual(measured["mrr_human_first_choice"], 0.875)
            self.assertEqual(human["query_clusters"], 2)
            self.assertEqual(human["geometry"]["query_rater_observations"], 4)
            talent = report["datasets"]["talentclef_2026_english_development"]["results"]
            self.assertFalse(talent["classification_accuracy_measured"])
            self.assertEqual(talent["unlisted_candidate_policy"], "uncredited_not_confirmed_negative")
            self.assertEqual(talent["source_judgments"]["explicit_unsuitable_pairs"], 0)
            self.assertEqual(talent["source_judgments"]["unjudged_scored_pairs"], 2)
            self.assertEqual(talent["methods"][benchmark.REFERENCE]["mean"]["map"], 1.0)
            self.assertEqual(talent["methods"][benchmark.REFERENCE]["mean"]["precision_at_k"], 0.1)
            self.assertTrue(report["datasets"]["vanetik_human_rankings"]["source"]["fictional_data"])

    def test_published_artifacts_have_valid_protocol_digest_and_no_source_text_or_individual_records(self):
        with tempfile.TemporaryDirectory() as temporary, fixture_sources():
            output = Path(temporary) / "complete"
            report = run(output)
            self.assertEqual({path.name for path in output.iterdir()}, {"protocol.json", "report.json"})
            protocol = json.loads((output / "protocol.json").read_text())
            restored_report = json.loads((output / "report.json").read_text())
            canonical = json.dumps(protocol, sort_keys=True, allow_nan=False).encode()
            self.assertEqual(report["protocol_sha256"], hashlib.sha256(canonical).hexdigest())
            self.assertEqual(restored_report, report)
            self.assertEqual(protocol["source_sha256"], FINGERPRINTS)
            self.assertNotIn("index", protocol["lexical_parameters"])
            self.assertIn("472", protocol["lexical_index_by_dataset"]["talentclef_2026_english_development"])
            self.assertFalse(protocol["fitting_or_parameter_selection"])
            self.assertIsNone(protocol["production_matching_accuracy"])
            serialized = (output / "report.json").read_text() + (output / "protocol.json").read_text()
            for private in (
                "PRIVATE_JOB_",
                "PRIVATE_CV_",
                "private_cv_alpha",
                "private_cv_beta",
                "private_job_alpha",
                "private_job_beta",
                '"predictions"',
                '"annotations"',
                '"qrels"',
                '"per_query"',
                '"individual_scores"',
                '"individual_rankings"',
            ):
                self.assertNotIn(private, serialized)

    def test_protocol_is_serialized_before_either_label_source_is_loaded(self):
        original_dumps = json.dumps
        frozen = []

        def observe_protocol(value, *args, **kwargs):
            serialized = original_dumps(value, *args, **kwargs)
            if isinstance(value, dict) and value.get("protocol_version") == benchmark.PROTOCOL_VERSION:
                if "scope" in value:
                    frozen.append(serialized)
            return serialized

        def load_human(path):
            self.assertEqual(path, HUMAN_SOURCE)
            self.assertTrue(frozen, "Human labels were read before serializing the frozen protocol")
            protocol = json.loads(frozen[0])
            self.assertEqual(protocol["bootstrap_replicates"], 1000)
            self.assertEqual(protocol["seed"], 99)
            self.assertEqual(protocol["methods"], [benchmark.REFERENCE, *benchmark.COMPARATORS])
            self.assertEqual(protocol["skill_adapter"]["concept_count"], 2)
            return HUMAN

        def load_talent(path):
            self.assertEqual(path, TALENT_SOURCE)
            self.assertTrue(frozen, "Retrieval labels were read before serializing the frozen protocol")
            return TALENT

        with (
            tempfile.TemporaryDirectory() as temporary,
            fixture_sources(human_loader=load_human, talent_loader=load_talent),
            mock.patch.object(benchmark.json, "dumps", side_effect=observe_protocol),
        ):
            run(Path(temporary) / "complete")

    def test_replaying_same_fixture_and_seed_preserves_metrics_and_protocol_hash(self):
        with tempfile.TemporaryDirectory() as temporary, fixture_sources() as fingerprint_mock:
            first = run(Path(temporary) / "first")
            second = run(Path(temporary) / "second")
            self.assertEqual(first["protocol_sha256"], second["protocol_sha256"])
            self.assertEqual(first["datasets"], second["datasets"])
            self.assertEqual(first["limitations"], second["limitations"])
            self.assertEqual(fingerprint_mock.call_count, 4)

    def test_code_change_mid_evaluation_aborts_without_output(self):
        changed = dict(FINGERPRINTS)
        changed[next(iter(changed))] = "0" * 64
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            output = parent / "complete"
            with (
                fixture_sources(fingerprints=[FINGERPRINTS, changed]),
                self.assertRaisesRegex(ValueError, "changed"),
            ):
                run(output)
            self.assertFalse(output.exists())
            self.assertEqual(list(parent.iterdir()), [])

    def test_existing_output_is_never_read_overwritten_or_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "complete"
            output.mkdir()
            sentinel = output / "existing-result.json"
            sentinel.write_text("immutable existing result")
            with fixture_sources() as fingerprint_mock, self.assertRaises(FileExistsError):
                run(output)
            fingerprint_mock.assert_not_called()
            self.assertEqual(sentinel.read_text(), "immutable existing result")
            self.assertEqual([path.name for path in output.iterdir()], ["existing-result.json"])

    def test_label_source_failure_does_not_publish_partial_protocol(self):
        def unavailable(path):
            raise ValueError("FICTIONAL malformed source")

        for which in ("human_loader", "talent_loader"):
            with self.subTest(source=which), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                with fixture_sources(**{which: unavailable}), self.assertRaisesRegex(ValueError, "malformed"):
                    run(parent / "complete")
                self.assertEqual(list(parent.iterdir()), [])

    def test_requires_at_least_one_thousand_integer_replicates_before_loading_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            for replicates in (0, 999, True, 1000.0):
                with self.subTest(replicates=replicates), fixture_sources() as fingerprint_mock:
                    with self.assertRaisesRegex(ValueError, "1000"):
                        benchmark.run_benchmark(
                            HUMAN_SOURCE,
                            TALENT_SOURCE,
                            ESCO_SOURCE,
                            Path(temporary) / "complete",
                            bootstrap_replicates=replicates,
                        )
                    fingerprint_mock.assert_not_called()
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_source_fingerprints_ignore_checkout_line_endings_but_detect_code_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.py"
            with (
                mock.patch.object(benchmark, "ROOT", root),
                mock.patch.object(benchmark, "SOURCE_FILES", ("source.py",)),
            ):
                source.write_bytes(b"first\nsecond\n")
                original = benchmark._fingerprints()
                source.write_bytes(b"first\r\nsecond\r\n")
                self.assertEqual(original, benchmark._fingerprints())
                source.write_bytes(b"changed\r\nsecond\r\n")
                self.assertNotEqual(original, benchmark._fingerprints())


if __name__ == "__main__":
    unittest.main()
