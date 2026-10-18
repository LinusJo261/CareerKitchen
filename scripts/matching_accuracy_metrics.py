"""Aggregate ordinal relevance metrics with paired query-cluster uncertainty.

Queries are independent resampling units. All available rater judgments for a
query travel together, including their missingness. These descriptive intervals
are conditional on the supplied jobs, raters and frozen methods; they do not
estimate hiring success, mutual interest or deployed matching accuracy.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

from scripts.matching_text_benchmark import ranking_metrics

METRICS = (
    "pairwise_agreement",
    "top1_agreement",
    "mrr_human_first_choice",
    "score_pair_tie_rate",
)
PROTOCOL_VERSION = "ordinal-relevance-paired-query-cluster-v1"


def _percentile(values: Sequence[float], probability: float) -> float:
    """Linear interpolation between adjacent ordered bootstrap replicates."""
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _interval(values: Sequence[float]) -> dict[str, float]:
    return {"lower": _percentile(values, 0.025), "upper": _percentile(values, 0.975)}


def _validate(
    predictions: dict[str, list[list[float]]],
    annotations: dict[str, list[list[int] | None]],
) -> tuple[int, int, list[int]]:
    if not isinstance(predictions, dict) or not predictions:
        raise ValueError("At least one named prediction method is required.")
    query_count = 0
    document_count = 0
    for method, rows in predictions.items():
        if not isinstance(method, str) or not method.strip():
            raise ValueError("Prediction method names must be nonempty strings.")
        if not isinstance(rows, list) or not rows:
            raise ValueError("Every prediction method requires a nonempty list of queries.")
        if not query_count:
            query_count = len(rows)
        if len(rows) != query_count:
            raise ValueError("Prediction methods must cover the same queries in the same order.")
        for scores in rows:
            if not isinstance(scores, list) or len(scores) < 2:
                raise ValueError("Every query requires a list with at least two document scores.")
            if not document_count:
                document_count = len(scores)
            if len(scores) != document_count:
                raise ValueError("All queries and methods must share the same document geometry.")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                for value in scores
            ):
                raise ValueError("Prediction scores must be finite numbers, never booleans.")
    if not isinstance(annotations, dict) or not annotations:
        raise ValueError("At least one named rater with annotation rows is required.")
    rating_counts = [0] * query_count
    expected_ids = set(range(1, document_count + 1))
    for rater, rater_rows in annotations.items():
        if not isinstance(rater, str) or not rater.strip():
            raise ValueError("Rater names must be nonempty strings.")
        if not isinstance(rater_rows, list) or len(rater_rows) != query_count:
            raise ValueError("Every rater must retain all query positions, using None for missing rows.")
        valid_rows = 0
        for index, order in enumerate(rater_rows):
            if order is None:
                continue
            if (
                not isinstance(order, list)
                or len(order) != document_count
                or any(type(value) is not int for value in order)
                or set(order) != expected_ids
            ):
                raise ValueError("Human orders must be document-ID permutations or explicit None rows.")
            rating_counts[index] += 1
            valid_rows += 1
        if not valid_rows:
            raise ValueError("Every supplied rater requires at least one valid query.")
    if not any(rating_counts):
        raise ValueError("At least one labelled query cluster is required.")
    return query_count, document_count, rating_counts


def evaluate_scores(
    predictions: dict[str, list[list[float]]],
    annotations: dict[str, list[list[int] | None]],
    *,
    bootstrap_replicates: int = 10_000,
    seed: int = 20261018,
    reference_method: str | None = None,
) -> dict[str, Any]:
    """Evaluate frozen rankings without fitting or exposing individual records.

    Document IDs are one-based positions in every score row. Each human order
    lists those IDs best first. A None annotation is missing, never a negative.
    The pooled estimand weights available query/rater judgments equally; the
    bootstrap keeps that denominator when a query has fewer available raters.
    Every method uses exactly the same query-cluster resamples, so differences
    against the optional reference are paired, rather than independent intervals.
    """
    if type(bootstrap_replicates) is not int or bootstrap_replicates < 1:
        raise ValueError("bootstrap_replicates must be a positive integer, never a boolean.")
    if type(seed) is not int or not 0 <= seed <= 2**64 - 1:
        raise ValueError("seed must be an integer in [0, 2**64 - 1], never a boolean.")
    query_count, document_count, rating_counts = _validate(predictions, annotations)
    if reference_method is not None and (
        not isinstance(reference_method, str) or reference_method not in predictions
    ):
        raise ValueError("reference_method must name an evaluated method or be None.")

    labelled_queries = [index for index, count in enumerate(rating_counts) if count]
    rating_count = sum(rating_counts)
    cluster_count = len(labelled_queries)
    # Store metric sums per query, never independently resample rater rows or
    # the dependent document-pair comparisons inside a query.
    contributions: dict[str, list[list[float]]] = {}
    methods: dict[str, Any] = {}
    for method in sorted(predictions):
        per_rater: dict[str, Any] = {}
        query_sums = [[0.0] * len(METRICS) for _ in range(query_count)]
        for rater in sorted(annotations):
            observations = []
            for index, order in enumerate(annotations[rater]):
                if order is None:
                    continue
                observed = ranking_metrics(predictions[method][index], order)
                observations.append(observed)
                for metric_index, metric in enumerate(METRICS):
                    query_sums[index][metric_index] += observed[metric]
            per_rater[rater] = {
                "queries": len(observations),
                **{
                    metric: math.fsum(row[metric] for row in observations) / len(observations)
                    for metric in METRICS
                },
            }
        contributions[method] = [query_sums[index] for index in labelled_queries]
        methods[method] = {
            "per_rater": per_rater,
            "pooled_query_rater": {
                metric: math.fsum(row[metric_index] for row in query_sums) / rating_count
                for metric_index, metric in enumerate(METRICS)
            },
            "pooled_query_rater_count": rating_count,
            "query_clusters": cluster_count,
        }

    samples: dict[str, dict[str, list[float]]] = {
        method: {metric: [] for metric in METRICS} for method in methods
    }
    counts = [rating_counts[index] for index in labelled_queries]
    generator = random.Random(seed)
    for _ in range(bootstrap_replicates):
        selected = generator.choices(range(cluster_count), k=cluster_count)
        denominator = sum(counts[index] for index in selected)
        for method, clusters in contributions.items():
            for metric_index, metric in enumerate(METRICS):
                samples[method][metric].append(
                    math.fsum(clusters[index][metric_index] for index in selected) / denominator
                )
    for method in methods:
        methods[method]["bootstrap_cv_cluster_95"] = {
            metric: _interval(samples[method][metric]) for metric in METRICS
        }

    comparisons = {}
    if reference_method is not None:
        for method in methods:
            if method == reference_method:
                continue
            comparisons[method] = {
                "reference_method": reference_method,
                "delta_method_minus_reference": {
                    metric: methods[method]["pooled_query_rater"][metric]
                    - methods[reference_method]["pooled_query_rater"][metric]
                    for metric in METRICS
                },
                "bootstrap_cv_cluster_95": {
                    metric: _interval(
                        [
                            left - right
                            for left, right in zip(
                                samples[method][metric], samples[reference_method][metric], strict=True
                            )
                        ]
                    )
                    for metric in METRICS
                },
            }

    return {
        "protocol_version": PROTOCOL_VERSION,
        "geometry": {
            "query_count": query_count,
            "documents_per_query": document_count,
            "raters": len(annotations),
            "query_rater_observations": rating_count,
            "unlabelled_queries_excluded": query_count - cluster_count,
        },
        "query_clusters": cluster_count,
        "methods": methods,
        "reference_method": reference_method,
        "paired_comparisons": comparisons,
        "uniform_random_expected": {
            "pairwise_agreement": 0.5,
            "top1_agreement": 1 / document_count,
            "mrr_human_first_choice": math.fsum(1 / rank for rank in range(1, document_count + 1))
            / document_count,
            "score_pair_tie_rate": 0.0,
        },
        "uncertainty": {
            "unit": "labelled_query_cluster",
            "confidence_level": 0.95,
            "method": "paired_percentile_bootstrap_linear_interpolation",
            "bootstrap_replicates": bootstrap_replicates,
            "seed": seed,
            "rater_rows_resampled_independently": False,
            "document_pairs_resampled_independently": False,
            "raters_and_missingness_preserved_within_sampled_query": True,
            "estimand": "mean_over_available_query_rater_judgments",
            "multiple_comparison_adjustment": "none",
        },
        "limitations": [
            "These are ordinal relevance judgments, not observed mutual interest, hiring outcomes or calibrated match probabilities.",
            "Exploratory intervals assume query clusters are representative independent resampling units and condition on the fixed jobs, raters and methods.",
            "Rater/query rows and document-pair comparisons within a query are dependent; their count is not the independent sample size.",
            "The percentile bootstrap does not include job or rater sampling uncertainty, annotation bias, model selection or text-adapter uncertainty.",
            "Methods and paired differences use the same resampled query clusters, preserving incomplete rater coverage and the pooled-rating denominator.",
            "Intervals are unadjusted for multiple comparisons and cannot establish superiority on an adaptively reused benchmark.",
            "A single labelled query produces a degenerate resampling interval, not evidence of zero population uncertainty.",
            "Predicted ties average uniformly over tied positions; score-pair tie rate describes resolution and is not an accuracy target.",
        ],
    }
