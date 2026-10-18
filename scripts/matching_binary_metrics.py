"""Tie-aware judged-pool binary ranking metrics with paired job uncertainty.

Unjudged candidates are excluded from relevance calculations, never labelled
negative. This condensed evaluation is not an official full-corpus TREC score.
All within-score-tie permutations are averaged analytically, including AP.
"""

from __future__ import annotations

import math
import random
from itertools import groupby
from typing import Any, cast

from scripts.matching_accuracy_metrics import _interval

METRICS = ("map", "precision_at_k", "ndcg_at_k", "recall_at_k", "score_pair_tie_rate")
PROTOCOL_VERSION = "binary-judged-pool-paired-job-cluster-v1"


def _scores(values: list[float]) -> None:
    if not isinstance(values, list) or not values:
        raise ValueError("A nonempty list of scores is required.")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        for value in values
    ):
        raise ValueError("Scores must be finite numbers, never booleans.")


def _cutoff(cutoff: int) -> None:
    if type(cutoff) is not int or cutoff < 1:
        raise ValueError("cutoff must be a positive integer, never a boolean.")


def _groups(scores: list[float], labels: list[int]) -> list[tuple[int, int]]:
    ranked = sorted(zip(scores, labels, strict=True), key=lambda pair: pair[0], reverse=True)
    result = []
    for _, group in groupby(ranked, key=lambda pair: pair[0]):
        values = list(group)
        result.append((len(values), sum(value[1] for value in values)))
    return result


def binary_ranking_metrics(
    scores: list[float], labels: list[int], *, cutoff: int = 10
) -> dict[str, float | None]:
    """Expected AP and binary top-k metrics under uniform exact-score tie order.

    AP uses the entire supplied, judged ranking and divides by all its positive
    judgments. P@k divides by requested k, including if the judged pool has fewer
    than k candidates. Zero-positive queries have undefined relevance metrics and
    must be counted and excluded from macro means, never silently given zero AP.
    """
    _scores(scores)
    _cutoff(cutoff)
    if (
        not isinstance(labels, list)
        or len(labels) != len(scores)
        or any(type(value) is not int or value not in (0, 1) for value in labels)
    ):
        raise ValueError("One explicit binary integer judgment is required per score.")
    positives = sum(labels)
    groups = _groups(scores, labels)
    total_pairs = len(scores) * (len(scores) - 1) / 2
    tied_pairs = sum(size * (size - 1) / 2 for size, _ in groups)
    tie_rate = tied_pairs / total_pairs if total_pairs else 0.0
    if not positives:
        return {metric: tie_rate if metric == "score_pair_tie_rate" else None for metric in METRICS}

    ap_terms = []
    dcg_terms = []
    expected_top_k_positives = 0.0
    preceding_documents = 0
    preceding_positives = 0
    for size, group_positives in groups:
        prevalence = group_positives / size
        for offset in range(1, size + 1):
            # E[I_t * (# preceding positives including current) / rank].
            # Current/preceding indicators within the tie are dependent, so
            # replacing both by their separate means would give biased AP.
            numerator = prevalence * (preceding_positives + 1)
            if size > 1:
                numerator += (offset - 1) * group_positives * (group_positives - 1) / (size * (size - 1))
            rank = preceding_documents + offset
            ap_terms.append(numerator / rank)
            if rank <= cutoff:
                expected_top_k_positives += prevalence
                dcg_terms.append(prevalence / math.log2(rank + 1))
        preceding_documents += size
        preceding_positives += group_positives
    ideal_dcg = math.fsum(1 / math.log2(rank + 1) for rank in range(1, min(cutoff, positives) + 1))
    return {
        "map": math.fsum(ap_terms) / positives,
        "precision_at_k": expected_top_k_positives / cutoff,
        "ndcg_at_k": math.fsum(dcg_terms) / ideal_dcg,
        "recall_at_k": expected_top_k_positives / positives,
        "score_pair_tie_rate": tie_rate,
    }


def _validate(
    predictions: dict[str, dict[str, dict[str, float]]], judgments: dict[str, dict[str, int]]
) -> list[str]:
    if not isinstance(judgments, dict) or not judgments:
        raise ValueError("At least one query with explicit judgments is required.")
    for query, labels in judgments.items():
        if not isinstance(query, str) or not query.strip() or not isinstance(labels, dict) or not labels:
            raise ValueError("Judgment queries must have nonempty string IDs and nonempty document maps.")
        for document, label in labels.items():
            if not isinstance(document, str) or not document.strip():
                raise ValueError("Judged document IDs must be nonempty strings.")
            if type(label) is not int or label not in (0, 1):
                raise ValueError("Relevance judgments must be explicit binary integers, never booleans.")
    if not isinstance(predictions, dict) or not predictions:
        raise ValueError("At least one named prediction method is required.")
    for method, queries in predictions.items():
        if not isinstance(method, str) or not method.strip() or not isinstance(queries, dict):
            raise ValueError("Prediction methods must have nonempty names and query maps.")
        if set(queries) != set(judgments):
            raise ValueError("Every method must score exactly the same judged queries.")
        for query, documents in queries.items():
            if (
                not isinstance(documents, dict)
                or not documents
                or not set(judgments[query]) <= set(documents)
            ):
                raise ValueError(
                    "Every method must score every judged document; missing labels are not zero."
                )
            if any(not isinstance(document, str) or not document.strip() for document in documents):
                raise ValueError("Scored document IDs must be nonempty strings.")
            _scores(list(documents.values()))
    return sorted(judgments)


def _comparison(
    method: dict[str, Any],
    reference: dict[str, Any],
    samples: dict[str, list[float]],
    reference_samples: dict[str, list[float]],
    reference_name: str,
) -> dict[str, Any]:
    return {
        "reference_method": reference_name,
        "delta_method_minus_reference": {
            metric: method["mean"][metric] - reference["mean"][metric]
            if method["mean"][metric] is not None
            else None
            for metric in METRICS
        },
        "bootstrap_job_cluster_95": {
            metric: _interval(
                [left - right for left, right in zip(samples[metric], reference_samples[metric], strict=True)]
            )
            if samples[metric]
            else None
            for metric in METRICS
        },
    }


def _judgment_coverage(
    predictions: dict[str, dict[str, float]], judgments: dict[str, dict[str, int]], cutoff: int
) -> dict[str, int | float]:
    coverage = []
    for query in sorted(judgments):
        documents = list(predictions[query])
        groups = _groups(
            [predictions[query][document] for document in documents],
            [int(document in judgments[query]) for document in documents],
        )
        preceding = 0
        expected_judged = 0.0
        for size, judged in groups:
            included = min(size, max(0, cutoff - preceding))
            expected_judged += included * judged / size
            preceding += size
        coverage.append(expected_judged / cutoff)
    return {
        "scored_documents_across_queries": sum(len(documents) for documents in predictions.values()),
        "judged_documents_across_queries": sum(len(labels) for labels in judgments.values()),
        "unjudged_scored_documents_across_queries": sum(
            len(predictions[query]) - len(judgments[query]) for query in judgments
        ),
        "mean_top_k_judgment_coverage": math.fsum(coverage) / len(coverage),
        "queries_with_fewer_than_cutoff_scored_documents": sum(
            len(documents) < cutoff for documents in predictions.values()
        ),
    }


def evaluate_binary_scores(
    predictions: dict[str, dict[str, dict[str, float]]],
    judgments: dict[str, dict[str, int]],
    *,
    cutoff: int = 10,
    bootstrap_replicates: int = 10_000,
    seed: int = 20261018,
    reference_method: str | None = None,
) -> dict[str, Any]:
    """Return aggregate judged-pool metrics and paired job-cluster intervals.

    Extra scored documents without judgments may be provided for pool-coverage
    diagnostics, but cannot change relevance results. No raw IDs, scores,
    individual labels, per-query results or resampled records are returned.
    """
    _cutoff(cutoff)
    if type(bootstrap_replicates) is not int or bootstrap_replicates < 1:
        raise ValueError("bootstrap_replicates must be a positive integer, never a boolean.")
    if type(seed) is not int or not 0 <= seed <= 2**64 - 1:
        raise ValueError("seed must be an integer in [0, 2**64 - 1], never a boolean.")
    queries = _validate(predictions, judgments)
    if reference_method is not None and (
        not isinstance(reference_method, str) or reference_method not in predictions
    ):
        raise ValueError("reference_method must name an evaluated method or be None.")

    positive_queries = [query for query in queries if sum(judgments[query].values())]
    rows: dict[str, list[dict[str, float | None]]] = {}
    methods: dict[str, Any] = {}
    random_rows = []
    for query in positive_queries:
        random_rows.append(
            binary_ranking_metrics(
                [0.0] * len(judgments[query]), list(judgments[query].values()), cutoff=cutoff
            )
        )
    for method in sorted(predictions):
        values = []
        for query in positive_queries:
            documents = sorted(judgments[query])
            values.append(
                binary_ranking_metrics(
                    [predictions[method][query][document] for document in documents],
                    [judgments[query][document] for document in documents],
                    cutoff=cutoff,
                )
            )
        rows[method] = values
        methods[method] = {
            "mean": {
                metric: math.fsum(cast(float, row[metric]) for row in values) / len(values)
                if values
                else None
                for metric in METRICS
            },
            "evaluable_queries": len(values),
            "judgment_coverage": _judgment_coverage(predictions[method], judgments, cutoff),
        }
    random_result = {
        "mean": {
            metric: math.fsum(cast(float, row[metric]) for row in random_rows) / len(random_rows)
            if random_rows
            else None
            for metric in METRICS
        },
        "evaluable_queries": len(random_rows),
        "expectation": "uniform_permutation_of_the_same_judged_candidates_per_query",
        "tie_rate_semantics": "one_all_tied_score_group_is_used_to_compute_exact_uniform_permutation_expectations",
    }
    samples: dict[str, dict[str, list[float]]] = {
        method: {metric: [] for metric in METRICS} for method in methods
    }
    random_samples: dict[str, list[float]] = {metric: [] for metric in METRICS}
    generator = random.Random(seed)
    if positive_queries:
        for _ in range(bootstrap_replicates):
            selected = generator.choices(range(len(positive_queries)), k=len(positive_queries))
            for method, values in rows.items():
                for metric in METRICS:
                    samples[method][metric].append(
                        math.fsum(cast(float, values[index][metric]) for index in selected) / len(selected)
                    )
            for metric in METRICS:
                random_samples[metric].append(
                    math.fsum(cast(float, random_rows[index][metric]) for index in selected) / len(selected)
                )
    for method in methods:
        methods[method]["bootstrap_job_cluster_95"] = {
            metric: _interval(samples[method][metric]) if samples[method][metric] else None
            for metric in METRICS
        }
    random_result["bootstrap_job_cluster_95"] = {
        metric: _interval(random_samples[metric]) if random_samples[metric] else None for metric in METRICS
    }
    comparisons = {}
    if reference_method is not None:
        comparisons = {
            method: _comparison(
                methods[method],
                methods[reference_method],
                samples[method],
                samples[reference_method],
                reference_method,
            )
            for method in methods
            if method != reference_method
        }
    random_comparisons = {
        method: _comparison(
            methods[method], random_result, samples[method], random_samples, "uniform_random_expected"
        )
        for method in methods
    }
    negative_judgments = sum(len(labels) - sum(labels.values()) for labels in judgments.values())
    return {
        "protocol_version": PROTOCOL_VERSION,
        "status": (
            "NO_POSITIVE_JUDGMENTS"
            if not positive_queries
            else "NON_DISCRIMINATIVE_ALL_JUDGMENTS_POSITIVE"
            if not negative_judgments
            else "MEASURED"
        ),
        "universe_scope": "condensed_judged_pool_only",
        "official_full_corpus_leaderboard_score": False,
        "cutoff": cutoff,
        "primary_metric": "map",
        "geometry": {
            "queries": len(queries),
            "evaluable_positive_queries": len(positive_queries),
            "zero_positive_queries_excluded": len(queries) - len(positive_queries),
            "judged_query_document_pairs": sum(len(labels) for labels in judgments.values()),
            "positive_judgments": sum(sum(labels.values()) for labels in judgments.values()),
            "negative_judgments": negative_judgments,
            "all_positive_queries_non_discriminative": sum(
                all(labels.values()) for labels in judgments.values()
            ),
            "queries_with_fewer_than_cutoff_judged_documents": sum(
                len(labels) < cutoff for labels in judgments.values()
            ),
        },
        "methods": methods,
        "uniform_random_expected": random_result,
        "reference_method": reference_method,
        "paired_comparisons": comparisons,
        "paired_comparisons_vs_uniform_random": random_comparisons,
        "uncertainty": {
            "unit": "job_query_cluster",
            "confidence_level": 0.95,
            "method": "paired_percentile_bootstrap_linear_interpolation",
            "bootstrap_replicates": bootstrap_replicates,
            "seed": seed,
            "judged_documents_resampled_independently": False,
            "all_methods_use_identical_query_resamples": True,
            "multiple_comparison_adjustment": "none",
        },
        "definitions": {
            "map": "macro mean of full judged-ranking average precision with exact uniform score-tie expectation",
            "precision_at_k": "expected relevant candidates in the first k judged positions divided by requested k",
            "ndcg_at_k": "expected binary-gain discounted cumulative gain at k divided by ideal judged-pool DCG at k",
            "recall_at_k": "expected relevant candidates in the first k judged positions divided by all judged positives",
            "score_pair_tie_rate": "fraction of judged candidate pairs with exactly equal model scores; not an accuracy target",
            "coverage": "expected fraction of original scored-pool top-k positions having a judgment; unjudged positions stay unknown",
        },
        "limitations": [
            "Only explicitly judged candidates enter relevance metrics; unjudged candidates are excluded rather than treated as unsuitable.",
            "An all-positive judged pool cannot discriminate any method; perfect condensed scores in such a pool are not evidence of matching accuracy.",
            "Condensed judged-pool MAP and top-k metrics differ from official full-corpus TREC conventions and leaderboard scores.",
            "Judged pools may be selected by prior retrieval systems and do not establish unbiased relevance for the complete corpus.",
            "All accuracy means and paired intervals exclude zero-positive queries; their count is disclosed separately.",
            "P@k divides by requested k even when fewer than k judged candidates exist; recall concerns judged positives only.",
            "Score ties use exact expected metrics over uniform tie permutations, not IDs or source row ordering.",
            "Intervals resample jobs with all their judged candidates intact and are conditional on the supplied corpus, judgments and fixed methods.",
            "Few jobs, synthetic profiles, expert judgment bias, job selection, annotation uncertainty and adapter choices limit generalization.",
            "Intervals are exploratory and unadjusted for multiple comparisons; benchmark reuse does not establish a statistically reliable winning method.",
            "Relevance scores and these metrics are not calibrated probabilities or observed mutual-interest, employment or hiring accuracy.",
        ],
    }


def evaluate_retrieval_scores(
    predictions: dict[str, dict[str, dict[str, float]]],
    judgments: dict[str, dict[str, int]],
    *,
    cutoff: int = 10,
    bootstrap_replicates: int = 10_000,
    seed: int = 20261018,
    reference_method: str | None = None,
) -> dict[str, Any]:
    """Measure retrieval of published relevant candidates over the full pool.

    Published positives earn relevance credit; unlisted candidates earn no
    credit under this explicit IR convention. Unlisted candidates remain unknown
    suitability, never confirmed negatives or classification error labels.
    This is a separate target from condensed judged-pool suitability evaluation.
    """
    queries = _validate(predictions, judgments)
    first_method = next(iter(predictions))
    for method in predictions:
        if any(set(predictions[method][query]) != set(predictions[first_method][query]) for query in queries):
            raise ValueError("Full-corpus retrieval comparisons require identical candidate pools per query.")
    credit = {
        query: {
            document: int(judgments[query].get(document) == 1)
            for document in predictions[first_method][query]
        }
        for query in queries
    }
    report = evaluate_binary_scores(
        predictions,
        credit,
        cutoff=cutoff,
        bootstrap_replicates=bootstrap_replicates,
        seed=seed,
        reference_method=reference_method,
    )
    report["protocol_version"] = "published-relevant-retrieval-paired-job-cluster-v1"
    report["status"] = (
        "PUBLISHED_QRELS_RETRIEVAL_MEASURED"
        if report["geometry"]["positive_judgments"]
        else "NO_PUBLISHED_POSITIVES"
    )
    report["measurement_target"] = "retrieval_of_published_relevant_candidates"
    report["universe_scope"] = "common_full_scored_candidate_pool"
    report["unlisted_candidate_policy"] = "uncredited_not_confirmed_negative"
    report["classification_accuracy_measured"] = False
    report["source_judgments"] = {
        "published_relevant_pairs": sum(sum(labels.values()) for labels in judgments.values()),
        "explicit_unsuitable_pairs": sum(len(labels) - sum(labels.values()) for labels in judgments.values()),
        "unjudged_scored_pairs": sum(
            len(predictions[first_method][query]) - len(judgments[query]) for query in queries
        ),
        "scored_query_document_pairs": sum(len(predictions[first_method][query]) for query in queries),
    }
    geometry = report["geometry"]
    geometry["scored_query_document_pairs"] = geometry.pop("judged_query_document_pairs")
    geometry["published_relevant_pairs"] = geometry.pop("positive_judgments")
    geometry["uncredited_pairs"] = geometry.pop("negative_judgments")
    geometry["queries_with_fewer_than_cutoff_candidates"] = geometry.pop(
        "queries_with_fewer_than_cutoff_judged_documents"
    )
    geometry.pop("all_positive_queries_non_discriminative")
    geometry["zero_published_positive_queries_excluded"] = geometry.pop("zero_positive_queries_excluded")
    for method in report["methods"]:
        report["methods"][method]["judgment_coverage"] = _judgment_coverage(
            predictions[method], judgments, cutoff
        )
    report["uniform_random_expected"]["expectation"] = (
        "uniform_permutation_of_the_same_full_candidate_pool_per_query"
    )
    report["uncertainty"]["candidates_resampled_independently"] = report["uncertainty"].pop(
        "judged_documents_resampled_independently"
    )
    report["definitions"] = {
        "map": "macro mean full-pool AP for retrieval of published relevant candidates; unlisted candidates earn no relevance credit",
        "precision_at_k": "expected published-relevant candidates in the first k full-pool positions divided by requested k; not verified suitability precision",
        "ndcg_at_k": "expected published-relevance binary DCG at k divided by ideal published-relevance DCG at k",
        "recall_at_k": "expected published-relevant candidates in the first k positions divided by all published positives for that job",
        "score_pair_tie_rate": "fraction of full-pool candidate pairs with exactly equal model scores; not an accuracy target",
        "coverage": "expected fraction of full-pool top-k positions having any published suitability judgment; remaining positions have unknown suitability",
    }
    report["limitations"] = [
        "This measures retrieval of published relevant candidates, not binary suitability classification or hiring accuracy.",
        "Unlisted candidates earn zero relevance credit under an explicit information-retrieval convention; their suitability remains unknown, not confirmed negative.",
        "P@k is published-relevance credit at k, not an estimate of the fraction of genuinely suitable candidates in the top k.",
        "Sparse qrels can omit genuinely suitable candidates; selected or incomplete relevance judgments limit inference about the entire corpus.",
        "All methods rank the identical full candidate pool for each job; every method and random baseline uses the same job resamples.",
        "Jobs with no published positives are excluded from macro relevance metrics and counted explicitly.",
        "Ties use exact uniform-permutation expectations, preventing source IDs or row order from generating artificial gains.",
        "MAP follows a full-ranking published-relevance IR convention, but exact tie expectations and this subset protocol need not match an official leaderboard implementation.",
        "Intervals resample jobs and condition on the fixed corpus, qrels and methods; they omit annotation, adapter, candidate-pool and model-selection uncertainty.",
        "Few jobs and synthetic profiles limit generalization; exploratory intervals are unadjusted for multiple comparisons and benchmark reuse.",
        "No observed mutual-interest, application, offer, employment-start, calibrated probability or live product outcome is measured.",
    ]
    return report
