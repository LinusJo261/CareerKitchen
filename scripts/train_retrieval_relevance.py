"""Fit a public-positive retrieval surrogate, never a production outcome model.

Unlisted candidates are competing background in a listwise softmax surrogate.
They are not assigned confirmed-negative suitability or outcome labels. Selection
uses whole-job validation; the shared candidate corpus is explicitly transductive.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.matching.retrieval_relevance import MODEL_TARGET, PortableRetrievalRanker  # noqa: E402
from app.matching.text_relevance import (  # noqa: E402
    FEATURE_NAMES,
    FEATURE_VERSION,
    TextFeatureIndex,
)

from scripts.matching_binary_metrics import binary_ranking_metrics  # noqa: E402
from scripts.train_text_relevance import publish_json  # noqa: E402

REGULARIZATION_GRID = (0.01, 0.1, 1.0, 10.0, 100.0)
TRAINING_PROTOCOL = {
    "learner": "L2 listwise softmax cross entropy; full-batch damped Newton; no intercept",
    "objective": "equal-job mean(logsumexp(all candidate scores) - mean(published positive scores)) + lambda*||w||^2/2",
    "labels": "published positives only; unlisted candidates are competing unlabeled background, not confirmed negatives",
    "surrogate_bias": "Encourages published positives above background; incomplete or selectively observed positives can bias the learned relevance order.",
    "scaling": "means and population standard deviations fitted only to training-job feature rows; constant features use scale 1",
    "features": FEATURE_VERSION,
    "regularization_grid": list(REGULARIZATION_GRID),
    "selection_metric": "inner leave-one-job-out published-positive MAP; largest regularization wins ties rounded to 12 decimals",
    "fallback": "TF-IDF when best inner learner MAP is not strictly greater than inner TF-IDF MAP by 1e-12",
    "outer_folds": "leave one whole job out; ten folds for the pinned English development corpus",
    "inner_folds": "leave one whole training job out; nine folds inside each outer fold",
    "candidate_corpus": "all 472 candidates are shared seen background; transductive indexing; no independent candidate holdout",
    "indexing": "label-free document IDF uses shared candidate corpus only; query/document direction retained",
    "validation_labels": "held-out job labels are inaccessible to fitting and policy selection",
    "maximum_newton_iterations": 100,
    "gradient_tolerance": 1e-8,
    "scope": "exploratory nested cross-validation of previously examined public development data",
    "post_outer_result_tuning": False,
}


def _training_arrays(
    features: Sequence[Sequence[Sequence[float]]],
    positives: Sequence[Sequence[int]],
    indices: Sequence[int],
) -> tuple[Any, list[Any]]:
    if (
        not indices
        or len(set(indices)) != len(indices)
        or len(features) != len(positives)
        or any(type(index) is not int or not 0 <= index < len(features) for index in indices)
    ):
        raise ValueError("Distinct in-range training-job indices are required.")
    # Deliberately validate/read only selected job labels and feature rows.
    selected_rows = [features[index] for index in indices]
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for query in selected_rows
        for row in query
        for value in row
    ):
        raise ValueError("Feature values must be numbers, never booleans.")
    rows = np.asarray(selected_rows)
    if (
        rows.dtype.kind not in "fiu"
        or rows.ndim != 3
        or rows.shape[1] < 2
        or rows.shape[2] != len(FEATURE_NAMES)
        or not np.isfinite(rows).all()
        or np.any(rows < 0)
        or np.any(rows > 1)
    ):
        raise ValueError("Finite bounded training-job feature rows are required.")
    selected = []
    for index in indices:
        values = positives[index]
        if (
            not values
            or len(set(values)) != len(values)
            or any(type(value) is not int or not 0 <= value < rows.shape[1] for value in values)
        ):
            raise ValueError("Unique published-positive candidate positions are required per training job.")
        selected.append(np.asarray(values, dtype=int))
    return rows.astype(float), selected


def listwise_objective(
    coefficients: Any,
    scaled_features: Any,
    positive_means: Any,
    regularization: float,
) -> tuple[float, Any, Any]:
    """Stable equal-job loss, gradient and Hessian for a numerical optimizer.

    positive_means contains training-job mean feature vectors for published
    positives. No binary negative labels are constructed by this objective.
    """
    scores = scaled_features @ coefficients
    maxima = scores.max(axis=1, keepdims=True)
    exponentials = np.exp(scores - maxima)
    probabilities = exponentials / exponentials.sum(axis=1, keepdims=True)
    weighted_means = np.einsum("qn,qnd->qd", probabilities, scaled_features)
    loss = float(
        np.mean(maxima[:, 0] + np.log(exponentials.sum(axis=1)) - positive_means @ coefficients)
        + regularization * np.dot(coefficients, coefficients) / 2
    )
    gradient = (weighted_means - positive_means).mean(axis=0) + regularization * coefficients
    centered = scaled_features - weighted_means[:, None, :]
    hessian = np.einsum("qnd,qn,qne->de", centered, probabilities, centered) / len(scaled_features)
    hessian += regularization * np.eye(len(FEATURE_NAMES))
    return loss, gradient, hessian


def fit_listwise(
    features: Sequence[Sequence[Sequence[float]]],
    positives: Sequence[Sequence[int]],
    training_indices: Sequence[int],
    *,
    regularization: float,
    source_sha256: str,
) -> PortableRetrievalRanker:
    rows, selected = _training_arrays(features, positives, training_indices)
    if (
        isinstance(regularization, bool)
        or not isinstance(regularization, (float, int))
        or not math.isfinite(regularization)
        or not 0 < regularization <= 1e6
    ):
        raise ValueError("Finite bounded positive regularization is required.")
    means = rows.reshape(-1, len(FEATURE_NAMES)).mean(axis=0)
    scales = rows.reshape(-1, len(FEATURE_NAMES)).std(axis=0)
    scales = np.where(scales < 1e-8, 1.0, scales)
    scaled = (rows - means) / scales
    positive_means = np.asarray([scaled[index, values].mean(axis=0) for index, values in enumerate(selected)])
    coefficients = np.zeros(len(FEATURE_NAMES))
    for _ in range(100):
        previous, gradient, hessian = listwise_objective(coefficients, scaled, positive_means, regularization)
        if float(np.max(np.abs(gradient))) < 1e-8:
            break
        step = np.linalg.solve(hessian, gradient)
        factor = 1.0
        while factor > 2**-30:
            candidate = coefficients - factor * step
            loss = listwise_objective(candidate, scaled, positive_means, regularization)[0]
            if loss <= previous - 1e-4 * factor * float(np.dot(gradient, step)):
                coefficients = candidate
                break
            factor /= 2
        else:
            raise RuntimeError("Listwise learner line search failed; no model published.")
    else:
        raise RuntimeError("Listwise learner failed to converge; no model published.")
    return PortableRetrievalRanker(
        means=tuple(float(x) for x in means),
        scales=tuple(float(x) for x in scales),
        coefficients=tuple(float(x) for x in coefficients),
        regularization=float(regularization),
        source_sha256=source_sha256,
        training_job_clusters=len(training_indices),
        training_positive_judgments=sum(map(len, selected)),
        candidate_corpus_size=rows.shape[1],
    )


def published_positive_ap(scores: Sequence[float], positives: Sequence[int]) -> float:
    # Zeros below mean no published retrieval credit; they are not inferred
    # confirmed-negative suitability labels. The metric uses all candidates.
    credit = set(positives)
    result = binary_ranking_metrics(list(scores), [int(i in credit) for i in range(len(scores))])["map"]
    if result is None:
        raise ValueError("Published-positive AP requires at least one positive.")
    return float(result)


def select_policy(
    features: Sequence[Sequence[Sequence[float]]],
    positives: Sequence[Sequence[int]],
    baseline_scores: Sequence[Sequence[float]],
    training_indices: Sequence[int],
    *,
    source_sha256: str,
) -> tuple[float, bool, dict[str, Any]]:
    _training_arrays(features, positives, training_indices)
    if len(training_indices) < 2 or len(baseline_scores) != len(features):
        raise ValueError("Policy selection needs at least two training jobs and matching baseline rows.")
    baseline = math.fsum(
        published_positive_ap(baseline_scores[index], positives[index]) for index in training_indices
    ) / len(training_indices)
    results = {}
    for regularization in REGULARIZATION_GRID:
        values = []
        for validation in training_indices:
            training = [index for index in training_indices if index != validation]
            model = fit_listwise(
                features, positives, training, regularization=regularization, source_sha256=source_sha256
            )
            values.append(
                published_positive_ap(model.score_features(features[validation]), positives[validation])
            )
        results[str(regularization)] = math.fsum(values) / len(values)
    selected = max(REGULARIZATION_GRID, key=lambda value: (round(results[str(value)], 12), value))
    use_ml = results[str(selected)] > baseline + 1e-12
    return (
        selected,
        use_ml,
        {
            "selected_regularization": selected,
            "inner_learner_map": results,
            "inner_tfidf_map": baseline,
            "selected_policy": "LISTWISE_ML" if use_ml else "TFIDF_FALLBACK",
            "inner_whole_job_folds": len(training_indices),
        },
    )


def nested_cross_validate(
    features: Sequence[Sequence[Sequence[float]]],
    positives: Sequence[Sequence[int]],
    baseline_scores: Sequence[Sequence[float]],
    *,
    source_sha256: str,
) -> tuple[list[list[float]], list[list[float]], dict[str, Any]]:
    indices = tuple(range(len(features)))
    if len(indices) < 3:
        raise ValueError("Nested job validation requires at least three whole jobs.")
    learned, gated = [], []
    choices: Counter[str] = Counter()
    regularizations: Counter[str] = Counter()
    for validation in indices:
        training = [index for index in indices if index != validation]
        regularization, use_ml, _ = select_policy(
            features,
            positives,
            baseline_scores,
            training,
            source_sha256=source_sha256,
        )
        model = fit_listwise(
            features, positives, training, regularization=regularization, source_sha256=source_sha256
        )
        scores = list(model.score_features(features[validation]))
        learned.append(scores)
        gated.append(scores if use_ml else list(baseline_scores[validation]))
        choices["LISTWISE_ML" if use_ml else "TFIDF_FALLBACK"] += 1
        regularizations[str(regularization)] += 1
    return (
        learned,
        gated,
        {
            "outer_whole_job_folds": len(indices),
            "inner_whole_job_folds_per_outer": len(indices) - 1,
            "every_job_scored_without_its_training_or_selection_labels": True,
            "ml_selected_outer_jobs": choices["LISTWISE_ML"],
            "tfidf_selected_outer_jobs": choices["TFIDF_FALLBACK"],
            "selected_regularization_counts": dict(sorted(regularizations.items())),
            "candidate_holdout": False,
            "shared_candidate_background": True,
        },
    )


def train_final(
    features: Sequence[Sequence[Sequence[float]]],
    positives: Sequence[Sequence[int]],
    baseline_scores: Sequence[Sequence[float]],
    *,
    source_sha256: str,
) -> tuple[PortableRetrievalRanker, dict[str, Any]]:
    indices = tuple(range(len(features)))
    regularization, _, summary = select_policy(
        features, positives, baseline_scores, indices, source_sha256=source_sha256
    )
    return fit_listwise(
        features, positives, indices, regularization=regularization, source_sha256=source_sha256
    ), summary


def main() -> None:
    from scripts.matching_text_benchmark import score_documents
    from scripts.talentclef_source import DEFAULT_SOURCE, load_source

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--talent-source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    jobs, resumes, judgments, provenance = load_source(args.talent_source)
    candidate_ids = sorted(resumes)
    texts = [resumes[key] for key in candidate_ids]
    index = TextFeatureIndex(texts)
    features, positives, baseline = [], [], []
    for job, text in sorted(jobs.items()):
        if any(value != 1 for value in judgments[job].values()):
            raise ValueError("This protocol accepts published-positive judgments only.")
        features.append(index.features(text))
        positives.append([i for i, key in enumerate(candidate_ids) if key in judgments[job]])
        baseline.append(score_documents(text, texts)["tfidf_cosine"])
    model, policy = train_final(features, positives, baseline, source_sha256=provenance["archive_sha256"])
    publish_json(model.to_dict(), args.output)
    print(
        json.dumps(
            {
                "artifact": str(args.output),
                "target": MODEL_TARGET,
                "production_eligible": False,
                "policy": policy,
            }
        )
    )


if __name__ == "__main__":
    main()
