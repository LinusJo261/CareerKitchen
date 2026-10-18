"""Fit an offline public-human ordinal ranker; never promote an outcome model.

Only explicit relative preferences supply labels. Each CV cluster has equal
training weight; its available raters and their document pairs share that weight.
The deployment inference artifact contains aggregate numeric parameters only.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.matching.text_relevance import FEATURE_NAMES, PortableTextRanker, TextFeatureIndex  # noqa: E402

from scripts.matching_text_benchmark import load_source, ranking_metrics  # noqa: E402

SEED = 42
OUTER_FOLDS = 5
INNER_FOLDS = 4
REGULARIZATION_GRID = (0.01, 0.1, 1.0, 10.0, 100.0)
TRAINING_PROTOCOL = {
    "learner": "L2 pairwise logistic regression; no intercept; full-batch damped Newton",
    "training_target": "explicit human best-to-worst document preferences only",
    "training_weights": "equal mass per CV cluster, then equal per available rater and unordered pair",
    "scaling": "means and population standard deviations fitted on training CV document rows only; constant features use scale 1",
    "regularization_grid": list(REGULARIZATION_GRID),
    "selection_metric": "inner held-out query/rater pairwise agreement; largest regularization wins ties",
    "outer_folds": OUTER_FOLDS,
    "inner_folds": INNER_FOLDS,
    "seed": SEED,
    "group": "entire CV with both raters and all five jobs; never split pairs or raters",
    "outer_prediction": "each CV scored only by a model selected and fitted without its labels or features in scaling",
    "fixed_candidate_pool": "five public jobs; label-free IDF indexes only those five jobs",
    "scope": "exploratory nested cross-validation of an already examined public source; fixed jobs and raters",
    "maximum_newton_iterations": 100,
    "gradient_tolerance": 1e-8,
}


def _validate(
    features: Sequence[Sequence[Sequence[float]]],
    annotations: dict[str, list[list[int] | None]],
) -> tuple[int, int]:
    if not features or not features[0] or len(features[0]) < 2:
        raise ValueError("At least two documents per query are required.")
    documents = len(features[0])
    for query in features:
        if len(query) != documents:
            raise ValueError("Queries must share document geometry.")
        for row in query:
            if len(row) != len(FEATURE_NAMES) or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in row
            ):
                raise ValueError("Training features must satisfy the bounded inference contract.")
    if not annotations or any(len(rows) != len(features) for rows in annotations.values()):
        raise ValueError("Rater arrays must retain all CV positions.")
    expected = set(range(1, documents + 1))
    for query_index in range(len(features)):
        orders = [rows[query_index] for rows in annotations.values() if rows[query_index] is not None]
        if not orders or any(
            not isinstance(order, list)
            or len(order) != documents
            or any(type(value) is not int for value in order)
            or set(order) != expected
            for order in orders
        ):
            raise ValueError("Every query needs at least one valid complete preference order.")
    return len(features), documents


def grouped_folds(indices: Sequence[int], folds: int, seed: int = SEED) -> tuple[tuple[int, ...], ...]:
    if type(folds) is not int or folds < 2 or len(indices) < folds or len(set(indices)) != len(indices):
        raise ValueError("Distinct query clusters and at least two nonempty folds are required.")
    if type(seed) is not int or seed < 0 or any(type(value) is not int or value < 0 for value in indices):
        raise ValueError("Nonnegative integer query indices and seed are required.")
    shuffled = sorted(indices)
    random.Random(seed).shuffle(shuffled)
    return tuple(tuple(sorted(shuffled[offset::folds])) for offset in range(folds))


def fit_pairwise(
    features: Sequence[Sequence[Sequence[float]]],
    annotations: dict[str, list[list[int] | None]],
    training_indices: Sequence[int],
    *,
    regularization: float,
    source_sha256: str,
) -> PortableTextRanker:
    query_count, documents = _validate(features, annotations)
    if (
        not training_indices
        or len(set(training_indices)) != len(training_indices)
        or any(type(index) is not int or not 0 <= index < query_count for index in training_indices)
    ):
        raise ValueError("Training requires distinct in-range whole-query indices.")
    if isinstance(regularization, bool) or not math.isfinite(regularization) or regularization <= 0:
        raise ValueError("Regularization must be finite and positive.")
    training_rows = np.asarray([features[index] for index in training_indices], dtype=float)
    means = training_rows.reshape(-1, len(FEATURE_NAMES)).mean(axis=0)
    scales = training_rows.reshape(-1, len(FEATURE_NAMES)).std(axis=0)
    scales = np.where(scales < 1e-8, 1.0, scales)
    differences, weights = [], []
    judgments = 0
    for index in training_indices:
        orders = [rows[index] for rows in annotations.values() if rows[index] is not None]
        judgments += len(orders)
        weight = 1.0 / (len(training_indices) * len(orders) * math.comb(documents, 2))
        for order in orders:
            assert order is not None
            for winner, loser in itertools.combinations(order, 2):
                differences.append(
                    (np.asarray(features[index][winner - 1]) - features[index][loser - 1]) / scales
                )
                weights.append(weight)
    matrix = np.asarray(differences, dtype=float)
    mass = np.asarray(weights, dtype=float)
    coefficients = np.zeros(len(FEATURE_NAMES), dtype=float)

    def objective(candidate: Any) -> float:
        return float(
            np.dot(mass, np.logaddexp(0.0, -(matrix @ candidate)))
            + 0.5 * regularization * np.dot(candidate, candidate)
        )

    for _ in range(100):
        margins = matrix @ coefficients
        failure = np.exp(-np.logaddexp(0.0, margins))
        gradient = -(matrix.T @ (mass * failure)) + regularization * coefficients
        if float(np.max(np.abs(gradient))) < 1e-8:
            break
        hessian = matrix.T @ ((mass * failure * (1.0 - failure))[:, None] * matrix)
        hessian += regularization * np.eye(len(FEATURE_NAMES))
        step = np.linalg.solve(hessian, gradient)
        previous = objective(coefficients)
        factor = 1.0
        while factor > 2**-30:
            candidate = coefficients - factor * step
            if objective(candidate) <= previous - 1e-4 * factor * float(np.dot(gradient, step)):
                coefficients = candidate
                break
            factor /= 2.0
        else:
            raise RuntimeError("Pairwise learner line search failed; no artifact published.")
    else:
        raise RuntimeError("Pairwise learner did not converge; no artifact published.")
    return PortableTextRanker(
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        regularization=float(regularization),
        source_sha256=source_sha256,
        training_query_clusters=len(training_indices),
        training_judgments=judgments,
        training_preference_pairs=len(differences),
    )


def _agreement(
    model: PortableTextRanker,
    features: Sequence[Sequence[Sequence[float]]],
    annotations: dict[str, list[list[int] | None]],
    indices: Sequence[int],
) -> tuple[float, int]:
    total, count = 0.0, 0
    for index in indices:
        scores = list(model.score_features(features[index]))
        for rows in annotations.values():
            order = rows[index]
            if order is not None:
                total += ranking_metrics(scores, order)["pairwise_agreement"]
                count += 1
    return total, count


def select_regularization(
    features: Sequence[Sequence[Sequence[float]]],
    annotations: dict[str, list[list[int] | None]],
    training_indices: Sequence[int],
    *,
    source_sha256: str,
) -> tuple[float, dict[str, float]]:
    folds = grouped_folds(training_indices, INNER_FOLDS, SEED)
    results = {}
    for regularization in REGULARIZATION_GRID:
        total, count = 0.0, 0
        for validation in folds:
            training = sorted(set(training_indices) - set(validation))
            model = fit_pairwise(
                features, annotations, training, regularization=regularization, source_sha256=source_sha256
            )
            value, observations = _agreement(model, features, annotations, validation)
            total += value
            count += observations
        results[str(regularization)] = total / count
    selected = max(REGULARIZATION_GRID, key=lambda value: (round(results[str(value)], 12), value))
    return selected, results


def nested_cross_validate(
    features: Sequence[Sequence[Sequence[float]]],
    annotations: dict[str, list[list[int] | None]],
    *,
    source_sha256: str,
) -> tuple[list[list[float]], dict[str, Any]]:
    queries, _ = _validate(features, annotations)
    all_indices = tuple(range(queries))
    folds = grouped_folds(all_indices, OUTER_FOLDS, SEED)
    predictions: list[list[float] | None] = [None] * queries
    selections: Counter[str] = Counter()
    fold_counts = []
    for validation in folds:
        training = sorted(set(all_indices) - set(validation))
        regularization, _ = select_regularization(
            features, annotations, training, source_sha256=source_sha256
        )
        model = fit_pairwise(
            features, annotations, training, regularization=regularization, source_sha256=source_sha256
        )
        selections[str(regularization)] += 1
        for index in validation:
            predictions[index] = list(model.score_features(features[index]))
        fold_counts.append({"training_cv_clusters": len(training), "held_out_cv_clusters": len(validation)})
    assert all(row is not None for row in predictions)
    return [row for row in predictions if row is not None], {
        "protocol": TRAINING_PROTOCOL,
        "outer_fold_counts": fold_counts,
        "selected_regularization_counts": dict(sorted(selections.items())),
        "every_cv_scored_out_of_fold": True,
        "outer_partition_sha256": hashlib.sha256(json.dumps(folds).encode()).hexdigest(),
    }


def train_final(
    features: Sequence[Sequence[Sequence[float]]],
    annotations: dict[str, list[list[int] | None]],
    *,
    source_sha256: str,
) -> tuple[PortableTextRanker, dict[str, Any]]:
    indices = tuple(range(len(features)))
    regularization, inner = select_regularization(features, annotations, indices, source_sha256=source_sha256)
    model = fit_pairwise(
        features, annotations, indices, regularization=regularization, source_sha256=source_sha256
    )
    return model, {"selected_regularization": regularization, "inner_cv_pairwise_agreement": inner}


def publish_json(value: dict[str, Any], output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise FileExistsError("Choose a fresh immutable artifact path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".text-ranker-", dir=output.parent) as temporary:
        staged = Path(temporary) / "artifact.json"
        staged.write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        if os.name == "nt":
            os.rename(staged, output)
        else:
            os.link(staged, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--human-source", type=Path, default=Path(".local/matching-human-benchmark/source/repository.zip")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError("Choose a fresh immutable artifact path.")
    jobs, resumes, annotations, provenance = load_source(args.human_source)
    index = TextFeatureIndex(jobs)
    features = [index.features(text) for text in resumes]
    model, _ = train_final(features, annotations, source_sha256=provenance["archive_sha256"])
    publish_json(model.to_dict(), args.output)
    print(
        json.dumps(
            {"artifact": str(args.output), "target": model.to_dict()["target"], "production_eligible": False}
        )
    )


if __name__ == "__main__":
    main()
