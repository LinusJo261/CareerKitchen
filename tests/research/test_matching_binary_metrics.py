"""Fictional qrels check exact ranking math; no dataset accuracy is stipulated."""

import copy
import itertools
import json
import math
import unittest
from unittest import mock

from scripts import matching_binary_metrics as metrics


def direct_metrics(labels, cutoff):
    positives = sum(labels)
    if not positives:
        return None
    relevant_before = 0
    precision_sum = 0.0
    for rank, label in enumerate(labels, 1):
        relevant_before += label
        if label:
            precision_sum += relevant_before / rank
    retrieved = sum(labels[:cutoff])
    dcg = sum(label / math.log2(rank + 1) for rank, label in enumerate(labels[:cutoff], 1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(cutoff, positives) + 1))
    return {
        "map": precision_sum / positives,
        "precision_at_k": retrieved / cutoff,
        "recall_at_k": retrieved / positives,
        "ndcg_at_k": dcg / ideal,
    }


class TieAwareBinaryTests(unittest.TestCase):
    def test_hand_calculated_partially_tied_average_precision(self):
        result = metrics.binary_ranking_metrics([3, 3, 0], [1, 0, 1], cutoff=1)
        self.assertAlmostEqual(result["map"], 17 / 24)
        self.assertEqual(result["precision_at_k"], 0.5)
        self.assertEqual(result["ndcg_at_k"], 0.5)
        self.assertEqual(result["recall_at_k"], 0.25)
        self.assertAlmostEqual(result["score_pair_tie_rate"], 1 / 3)

    def test_exact_tie_expectations_match_exhaustive_permutation_oracle(self):
        cases = 0
        for scores in itertools.product(range(3), repeat=4):
            valid_orders = [
                order
                for order in itertools.permutations(range(4))
                if all(scores[order[index]] >= scores[order[index + 1]] for index in range(3))
            ]
            for labels in itertools.product((0, 1), repeat=4):
                if not any(labels):
                    continue
                for cutoff in (1, 3, 5):
                    expected_rows = [
                        direct_metrics([labels[index] for index in order], cutoff) for order in valid_orders
                    ]
                    observed = metrics.binary_ranking_metrics(list(scores), list(labels), cutoff=cutoff)
                    for metric in ("map", "precision_at_k", "ndcg_at_k", "recall_at_k"):
                        self.assertAlmostEqual(
                            observed[metric],
                            sum(row[metric] for row in expected_rows) / len(expected_rows),
                            places=12,
                        )
                    cases += 1
        self.assertEqual(cases, 3645)

    def test_no_ties_matches_standard_ranking_metrics(self):
        labels = [0, 1, 0, 1, 1]
        result = metrics.binary_ranking_metrics([5, 4, 3, 2, 1], labels, cutoff=3)
        for metric, expected in direct_metrics(labels, 3).items():
            self.assertAlmostEqual(result[metric], expected)
        self.assertEqual(result["score_pair_tie_rate"], 0)

    def test_zero_positive_metrics_are_undefined_and_singleton_valid(self):
        empty = metrics.binary_ranking_metrics([1, 1], [0, 0])
        self.assertEqual(empty["score_pair_tie_rate"], 1)
        for metric in metrics.METRICS[:-1]:
            self.assertIsNone(empty[metric])
        singleton = metrics.binary_ranking_metrics([1], [1], cutoff=10)
        self.assertEqual(singleton["map"], 1)
        self.assertEqual(singleton["precision_at_k"], 0.1)
        self.assertEqual(singleton["ndcg_at_k"], 1)
        self.assertEqual(singleton["recall_at_k"], 1)


class BinaryAggregateTests(unittest.TestCase):
    def setUp(self):
        self.predictions = {
            "reference": {
                "private_job_a": {"private_cv_a": 3, "private_cv_b": 1},
                "private_job_b": {"private_cv_a": 1, "private_cv_b": 3},
            },
            "other": {
                "private_job_a": {"private_cv_a": 1, "private_cv_b": 3},
                "private_job_b": {"private_cv_a": 3, "private_cv_b": 1},
            },
        }
        self.judgments = {
            "private_job_a": {"private_cv_a": 1, "private_cv_b": 0},
            "private_job_b": {"private_cv_a": 1, "private_cv_b": 0},
        }

    def test_condensed_pool_ignores_unjudged_documents_without_calling_them_negative(self):
        first = metrics.evaluate_binary_scores(
            self.predictions, self.judgments, bootstrap_replicates=10, cutoff=1
        )
        changed = copy.deepcopy(self.predictions)
        for queries in changed.values():
            for scores in queries.values():
                scores["unknown_cv"] = 999
        second = metrics.evaluate_binary_scores(changed, self.judgments, bootstrap_replicates=10, cutoff=1)
        for method in first["methods"]:
            self.assertEqual(first["methods"][method]["mean"], second["methods"][method]["mean"])
            self.assertEqual(
                second["methods"][method]["judgment_coverage"]["mean_top_k_judgment_coverage"], 0
            )
            self.assertEqual(
                second["methods"][method]["judgment_coverage"]["unjudged_scored_documents_across_queries"], 2
            )

    def test_identical_methods_have_zero_paired_intervals(self):
        predictions = {"reference": self.predictions["reference"], "duplicate": self.predictions["reference"]}
        report = metrics.evaluate_binary_scores(
            predictions, self.judgments, bootstrap_replicates=30, reference_method="reference"
        )
        comparison = report["paired_comparisons"]["duplicate"]
        for metric in metrics.METRICS:
            self.assertEqual(comparison["delta_method_minus_reference"][metric], 0)
            self.assertEqual(comparison["bootstrap_job_cluster_95"][metric], {"lower": 0, "upper": 0})

    def test_queries_resampled_as_whole_paired_clusters(self):
        with mock.patch.object(metrics.random.Random, "choices", side_effect=[[0, 0], [1, 1]]) as resample:
            report = metrics.evaluate_binary_scores(
                self.predictions,
                self.judgments,
                bootstrap_replicates=2,
                cutoff=1,
                reference_method="reference",
            )
        self.assertEqual(resample.call_count, 2)
        comparison = report["paired_comparisons"]["other"]
        self.assertEqual(comparison["delta_method_minus_reference"]["precision_at_k"], 0)
        self.assertEqual(
            comparison["bootstrap_job_cluster_95"]["precision_at_k"], {"lower": -0.95, "upper": 0.95}
        )

    def test_zero_positive_queries_are_excluded_and_counted(self):
        judgments = copy.deepcopy(self.judgments)
        judgments["private_job_b"] = {"private_cv_a": 0, "private_cv_b": 0}
        report = metrics.evaluate_binary_scores(self.predictions, judgments, bootstrap_replicates=3, cutoff=1)
        self.assertEqual(report["geometry"]["zero_positive_queries_excluded"], 1)
        self.assertEqual(report["methods"]["reference"]["mean"]["map"], 1)
        self.assertEqual(report["methods"]["reference"]["evaluable_queries"], 1)

    def test_all_zero_queries_do_not_invent_accuracy_or_intervals(self):
        judgments = {query: {document: 0 for document in labels} for query, labels in self.judgments.items()}
        report = metrics.evaluate_binary_scores(self.predictions, judgments, bootstrap_replicates=3)
        self.assertEqual(report["status"], "NO_POSITIVE_JUDGMENTS")
        self.assertEqual(report["geometry"]["zero_positive_queries_excluded"], 2)
        for method in report["methods"].values():
            self.assertTrue(all(value is None for value in method["mean"].values()))
            self.assertTrue(all(value is None for value in method["bootstrap_job_cluster_95"].values()))
        json.dumps(report, allow_nan=False)

    def test_all_positive_condensed_pool_is_flagged_non_discriminative(self):
        judgments = {query: {document: 1 for document in labels} for query, labels in self.judgments.items()}
        report = metrics.evaluate_binary_scores(self.predictions, judgments, bootstrap_replicates=3, cutoff=1)
        self.assertEqual(report["status"], "NON_DISCRIMINATIVE_ALL_JUDGMENTS_POSITIVE")
        self.assertEqual(report["geometry"]["all_positive_queries_non_discriminative"], 2)
        self.assertEqual(report["methods"]["reference"]["mean"]["map"], 1)
        self.assertEqual(report["methods"]["other"]["mean"]["map"], 1)

    def test_uniform_random_baseline_is_exact_and_compared_on_same_queries(self):
        report = metrics.evaluate_binary_scores(
            self.predictions, self.judgments, bootstrap_replicates=3, cutoff=1
        )
        random = report["uniform_random_expected"]["mean"]
        self.assertEqual(random["map"], 0.75)
        self.assertEqual(random["precision_at_k"], 0.5)
        self.assertEqual(random["ndcg_at_k"], 0.5)
        self.assertEqual(random["recall_at_k"], 0.5)
        self.assertIn("reference", report["paired_comparisons_vs_uniform_random"])

    def test_reproducible_seed_input_order_no_mutation_and_aggregate_only(self):
        before = copy.deepcopy((self.predictions, self.judgments))
        first = metrics.evaluate_binary_scores(
            self.predictions, self.judgments, bootstrap_replicates=21, seed=123
        )
        second = metrics.evaluate_binary_scores(
            dict(reversed(list(self.predictions.items()))),
            dict(reversed(list(self.judgments.items()))),
            bootstrap_replicates=21,
            seed=123,
        )
        self.assertEqual(first, second)
        self.assertEqual((self.predictions, self.judgments), before)
        encoded = json.dumps(first, allow_nan=False)
        self.assertNotIn("private_job", encoded)
        self.assertNotIn("private_cv", encoded)

    def test_invalid_predictions_and_judgments_rejected(self):
        invalid_cases = [
            ({}, self.judgments),
            ({"": self.predictions["reference"]}, self.judgments),
            ({"method": {"missing_query": {"a": 1}}}, self.judgments),
            ({"method": {"query": {"a": True}}}, {"query": {"a": 1}}),
            ({"method": {"query": {"a": math.nan}}}, {"query": {"a": 1}}),
            ({"method": {"query": {"a": math.inf}}}, {"query": {"a": 1}}),
            ({"method": {"query": {"a": 1}}}, {}),
            ({"method": {"query": {"a": 1}}}, {"query": {"a": True}}),
            ({"method": {"query": {"a": 1}}}, {"query": {"a": 2}}),
            ({"method": {"query": {"a": 1}}}, {"query": {"a": 1, "missing": 0}}),
        ]
        for predictions, judgments in invalid_cases:
            with self.subTest(predictions=predictions, judgments=judgments), self.assertRaises(ValueError):
                metrics.evaluate_binary_scores(predictions, judgments, bootstrap_replicates=1)

    def test_invalid_evaluation_parameters_rejected(self):
        for parameter, invalids in {
            "cutoff": [0, True, 1.5],
            "bootstrap_replicates": [0, True, 1.5],
            "seed": [True, -1, 2**64],
            "reference_method": [True, "missing"],
        }.items():
            for invalid in invalids:
                with self.subTest(parameter=parameter, invalid=invalid), self.assertRaises(ValueError):
                    metrics.evaluate_binary_scores(self.predictions, self.judgments, **{parameter: invalid})


class PublishedRetrievalTests(unittest.TestCase):
    def test_full_pool_retrieval_keeps_unlisted_suitability_unknown(self):
        predictions = {"method": {"job": {"known_positive": 1, "unlisted": 3, "known_unsuitable": 0}}}
        judgments = {"job": {"known_positive": 1, "known_unsuitable": 0}}
        report = metrics.evaluate_retrieval_scores(predictions, judgments, cutoff=1, bootstrap_replicates=3)
        method = report["methods"]["method"]
        self.assertEqual(method["mean"]["map"], 0.5)
        self.assertEqual(method["mean"]["precision_at_k"], 0)
        self.assertEqual(method["judgment_coverage"]["mean_top_k_judgment_coverage"], 0)
        self.assertEqual(
            report["source_judgments"],
            {
                "published_relevant_pairs": 1,
                "explicit_unsuitable_pairs": 1,
                "unjudged_scored_pairs": 1,
                "scored_query_document_pairs": 3,
            },
        )
        self.assertEqual(report["unlisted_candidate_policy"], "uncredited_not_confirmed_negative")
        self.assertFalse(report["classification_accuracy_measured"])
        self.assertNotIn("negative_judgments", report["geometry"])

    def test_positive_only_qrels_are_measured_as_full_pool_retrieval(self):
        predictions = {"method": {"job": {"positive": 1, "unlisted_a": 0, "unlisted_b": -1}}}
        judgments = {"job": {"positive": 1}}
        report = metrics.evaluate_retrieval_scores(predictions, judgments, cutoff=1, bootstrap_replicates=2)
        self.assertEqual(report["status"], "PUBLISHED_QRELS_RETRIEVAL_MEASURED")
        self.assertEqual(report["source_judgments"]["explicit_unsuitable_pairs"], 0)
        self.assertEqual(report["source_judgments"]["unjudged_scored_pairs"], 2)
        self.assertEqual(report["methods"]["method"]["mean"]["map"], 1)
        self.assertAlmostEqual(report["uniform_random_expected"]["mean"]["map"], (1 + 1 / 2 + 1 / 3) / 3)

    def test_unequal_candidate_pools_between_methods_rejected(self):
        predictions = {"first": {"job": {"positive": 1, "unknown": 0}}, "second": {"job": {"positive": 1}}}
        with self.assertRaisesRegex(ValueError, "identical candidate pools"):
            metrics.evaluate_retrieval_scores(predictions, {"job": {"positive": 1}}, bootstrap_replicates=1)

    def test_full_pool_exact_ties_use_random_expectation_and_coverage(self):
        report = metrics.evaluate_retrieval_scores(
            {"tied": {"job": {"positive": 0, "unknown_a": 0, "unknown_b": 0, "unknown_c": 0}}},
            {"job": {"positive": 1}},
            cutoff=1,
            bootstrap_replicates=3,
        )
        self.assertEqual(report["methods"]["tied"]["mean"], report["uniform_random_expected"]["mean"])
        self.assertEqual(report["methods"]["tied"]["judgment_coverage"]["mean_top_k_judgment_coverage"], 0.25)
        for metric in metrics.METRICS:
            self.assertEqual(
                report["paired_comparisons_vs_uniform_random"]["tied"]["bootstrap_job_cluster_95"][metric],
                {"lower": 0, "upper": 0},
            )


if __name__ == "__main__":
    unittest.main()
