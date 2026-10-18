"""Fictional rankings verify metrics and dependence handling, never accuracy claims."""

import copy
import itertools
import json
import math
import unittest
from unittest import mock

from scripts import matching_accuracy_metrics as metrics


class AccuracyMetricsTests(unittest.TestCase):
    def test_hand_calculated_exact_ties(self):
        report = metrics.evaluate_scores(
            {"tied": [[3, 3, 0]]}, {"rater": [[2, 1, 3]]}, bootstrap_replicates=10
        )
        observed = report["methods"]["tied"]["pooled_query_rater"]
        self.assertAlmostEqual(observed["pairwise_agreement"], 5 / 6)
        self.assertEqual(observed["top1_agreement"], 0.5)
        self.assertEqual(observed["mrr_human_first_choice"], 0.75)
        self.assertAlmostEqual(observed["score_pair_tie_rate"], 1 / 3)

    def test_expected_all_tied_scores_equal_uniform_random_rank_metrics(self):
        report = metrics.evaluate_scores(
            {"tied": [[1, 1, 1, 1, 1]]}, {"rater": [[1, 2, 3, 4, 5]]}, bootstrap_replicates=5
        )
        observed = report["methods"]["tied"]["pooled_query_rater"]
        for metric in metrics.METRICS[:3]:
            self.assertEqual(observed[metric], report["uniform_random_expected"][metric])
        self.assertEqual(observed["score_pair_tie_rate"], 1)

    def test_unequal_rater_coverage_uses_rating_count_denominator(self):
        predictions = {"method": [[1, 0], [1, 0]]}
        annotations = {"one": [[1, 2], [2, 1]], "two": [[1, 2], None]}
        # Cluster 0 contributes 2 correct ratings, cluster 1 contributes 1
        # incorrect rating. Draws (0,1), (0,0), (1,1) give 2/3, 1, 0.
        draws = [[0, 1], [0, 0], [1, 1]]
        with mock.patch.object(metrics.random.Random, "choices", side_effect=draws) as resample:
            report = metrics.evaluate_scores(predictions, annotations, bootstrap_replicates=3)
        method = report["methods"]["method"]
        self.assertAlmostEqual(method["pooled_query_rater"]["top1_agreement"], 2 / 3)
        self.assertEqual(method["per_rater"]["one"]["top1_agreement"], 0.5)
        self.assertEqual(method["per_rater"]["two"]["top1_agreement"], 1)
        interval = method["bootstrap_cv_cluster_95"]["top1_agreement"]
        self.assertAlmostEqual(interval["lower"], (2 / 3) * 0.05)
        self.assertAlmostEqual(interval["upper"], 1 - (1 / 3) * 0.05)
        self.assertEqual(resample.call_count, 3)
        self.assertEqual(method["query_clusters"], 2)
        self.assertEqual(method["pooled_query_rater_count"], 3)

    def test_identical_methods_have_exactly_zero_paired_interval(self):
        rows = [[3, 2, 1], [1, 2, 3], [2, 3, 1]]
        report = metrics.evaluate_scores(
            {"reference": rows, "duplicate": copy.deepcopy(rows)},
            {"one": [[1, 2, 3], [1, 3, 2], [3, 1, 2]]},
            reference_method="reference",
            bootstrap_replicates=40,
        )
        comparison = report["paired_comparisons"]["duplicate"]
        for metric in metrics.METRICS:
            self.assertEqual(comparison["delta_method_minus_reference"][metric], 0)
            self.assertEqual(comparison["bootstrap_cv_cluster_95"][metric], {"lower": 0, "upper": 0})

    def test_paired_difference_uses_same_cluster_draws_for_both_methods(self):
        with mock.patch.object(metrics.random.Random, "choices", side_effect=[[0, 0], [1, 1]]):
            report = metrics.evaluate_scores(
                {"reference": [[2, 1], [2, 1]], "opposite": [[1, 2], [1, 2]]},
                {"rater": [[1, 2], [2, 1]]},
                reference_method="reference",
                bootstrap_replicates=2,
            )
        comparison = report["paired_comparisons"]["opposite"]
        self.assertEqual(comparison["delta_method_minus_reference"]["top1_agreement"], 0)
        self.assertEqual(
            comparison["bootstrap_cv_cluster_95"]["top1_agreement"], {"lower": -0.95, "upper": 0.95}
        )

    def test_reproducible_seed_and_input_dict_order_and_no_mutation(self):
        predictions = {"reference": [[3, 1, 2], [2, 3, 1]], "other": [[1, 2, 3], [3, 2, 1]]}
        annotations = {"one": [[1, 2, 3], None], "two": [[3, 2, 1], [2, 1, 3]]}
        original = copy.deepcopy((predictions, annotations))
        first = metrics.evaluate_scores(predictions, annotations, seed=42, bootstrap_replicates=51)
        second = metrics.evaluate_scores(
            dict(reversed(list(predictions.items()))),
            dict(reversed(list(annotations.items()))),
            seed=42,
            bootstrap_replicates=51,
        )
        self.assertEqual(first, second)
        self.assertEqual((predictions, annotations), original)

    def test_unlabelled_queries_excluded_without_converting_to_negative(self):
        report = metrics.evaluate_scores(
            {"method": [[3, 2, 1], [1, 2, 3]]},
            {"rater": [[1, 2, 3], None]},
            bootstrap_replicates=5,
        )
        self.assertEqual(report["query_clusters"], 1)
        self.assertEqual(report["geometry"]["unlabelled_queries_excluded"], 1)
        self.assertEqual(report["methods"]["method"]["pooled_query_rater"]["top1_agreement"], 1)

    def test_output_is_aggregate_only_json_serializable(self):
        report = metrics.evaluate_scores(
            {"method": [[913.177, 42.333], [12.345, 913.177]]},
            {"rater": [[1, 2], [2, 1]]},
            bootstrap_replicates=5,
        )
        encoded = json.dumps(report, allow_nan=False)
        self.assertNotIn("913.177", encoded)
        self.assertNotIn("42.333", encoded)
        self.assertNotIn("predictions", report)
        self.assertNotIn("annotations", report)
        self.assertNotIn("per_query", report)
        self.assertNotIn("per_query", report["methods"]["method"])

    def test_all_human_orders_match_explicit_uniform_tie_permutation_reference(self):
        for scores in itertools.product(range(2), repeat=3):
            predictions = [
                order
                for order in itertools.permutations(range(1, 4))
                if all(scores[order[index] - 1] >= scores[order[index + 1] - 1] for index in range(2))
            ]
            for human in itertools.permutations(range(1, 4)):
                result = metrics.evaluate_scores(
                    {"method": [list(scores)]}, {"rater": [list(human)]}, bootstrap_replicates=1
                )["methods"]["method"]["pooled_query_rater"]
                expected_top1 = sum(predicted[0] == human[0] for predicted in predictions) / len(predictions)
                expected_mrr = sum(1 / (predicted.index(human[0]) + 1) for predicted in predictions) / len(
                    predictions
                )
                self.assertAlmostEqual(result["top1_agreement"], expected_top1)
                self.assertAlmostEqual(result["mrr_human_first_choice"], expected_mrr)

    def test_malformed_scores_and_inconsistent_geometry_rejected(self):
        invalid_predictions = [
            {},
            {"": [[1, 0]]},
            {"method": []},
            {"method": [[1]]},
            {"method": [[True, 0]]},
            {"method": [[math.nan, 0]]},
            {"method": [[math.inf, 0]]},
            {"method": [["1", 0]]},
            {"method": [(1, 0)]},
            {"method": [[1, 0], [1, 0, 2]]},
            {"first": [[1, 0]], "second": [[1, 0], [2, 1]]},
            {"first": [[1, 0]], "second": [[1, 0, 2]]},
        ]
        for predictions in invalid_predictions:
            with self.subTest(predictions=predictions), self.assertRaises(ValueError):
                metrics.evaluate_scores(predictions, {"rater": [[1, 2]]}, bootstrap_replicates=1)

    def test_malformed_or_unlabelled_annotations_rejected(self):
        invalid_annotations = [
            {},
            {"": [[1, 2]]},
            {"rater": []},
            {"rater": [[True, 2]]},
            {"rater": [[1, 1]]},
            {"rater": [[1, 3]]},
            {"rater": [[1]]},
            {"rater": [(1, 2)]},
            {"rater": [None]},
            {"rater": [[1, 2]], "empty": [None]},
        ]
        for annotations in invalid_annotations:
            with self.subTest(annotations=annotations), self.assertRaises(ValueError):
                metrics.evaluate_scores({"method": [[1, 0]]}, annotations, bootstrap_replicates=1)

    def test_invalid_parameters_rejected(self):
        for parameter, invalid_values in {
            "bootstrap_replicates": [0, -1, True, 1.5, "100"],
            "seed": [True, -1, 2**64, 1.5, "42"],
            "reference_method": [True, "missing", 1],
        }.items():
            for invalid in invalid_values:
                with self.subTest(parameter=parameter, value=invalid), self.assertRaises(ValueError):
                    metrics.evaluate_scores({"method": [[1, 0]]}, {"rater": [[1, 2]]}, **{parameter: invalid})


if __name__ == "__main__":
    unittest.main()
