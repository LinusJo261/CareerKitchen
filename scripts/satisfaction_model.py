"""Small offline reported-satisfaction baseline; never imported by the API.

Categories have an order, but the distance between adjacent survey responses is
not an equal interval of satisfaction. The classifier does not model employer
interest, mutual interest, or an employment outcome other than the supplied label.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np


def _names(values: list[str], name: str, minimum: int = 1) -> list[str]:
    if (
        not isinstance(values, (list, tuple))
        or len(values) < minimum
        or any(not isinstance(value, str) or not value for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{name} must contain {minimum} or more unique nonempty strings.")
    return list(values)


def _matrix(value: Any, columns: int) -> np.ndarray:
    try:
        matrix = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Features must be a numeric matrix.") from exc
    if matrix.ndim != 2 or matrix.shape[1] != columns:
        raise ValueError(f"Features must be a two-dimensional matrix with {columns} columns.")
    if not np.all(np.isfinite(matrix)) or np.any((matrix < 0) | (matrix > 1)):
        raise ValueError("Features must be finite and normalized to [0, 1].")
    return matrix


def _labels(value: Any, classes: int, count: int | None = None) -> np.ndarray:
    try:
        labels = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Labels must be integer class indices.") from exc
    if labels.ndim != 1 or not len(labels) or (count is not None and len(labels) != count):
        raise ValueError("Labels must be a nonempty vector matching the feature rows.")
    if (
        not np.all(np.isfinite(labels))
        or np.any(labels != np.floor(labels))
        or np.any((labels < 0) | (labels >= classes))
    ):
        raise ValueError(f"Labels must be integer class indices from 0 to {classes - 1}.")
    return labels.astype(int)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


@dataclass
class SatisfactionModel:
    feature_names: list[str]
    labels: list[str]
    weights: list[list[float]]
    bias: list[float]
    initial_loss: float | None = None
    final_loss: float | None = None

    def __post_init__(self) -> None:
        self.feature_names = _names(self.feature_names, "feature_names")
        self.labels = _names(self.labels, "labels", minimum=2)
        try:
            weights = np.asarray(self.weights, dtype=float)
            bias = np.asarray(self.bias, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("Model coefficients must be numeric.") from exc
        if weights.shape != (len(self.feature_names), len(self.labels)):
            raise ValueError("Model weights must have shape features by classes.")
        if bias.shape != (len(self.labels),):
            raise ValueError("Model bias must have one entry per class.")
        if not np.all(np.isfinite(weights)) or not np.all(np.isfinite(bias)):
            raise ValueError("Model coefficients must be finite.")
        for loss in (self.initial_loss, self.final_loss):
            if loss is not None and (not np.isfinite(loss) or loss < 0):
                raise ValueError("Recorded losses must be finite nonnegative numbers.")
        self.weights = weights.tolist()
        self.bias = bias.tolist()

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        matrix = _matrix(x, len(self.feature_names))
        if not len(matrix):
            return np.empty((0, len(self.labels)), dtype=float)
        logits = matrix @ np.asarray(self.weights) + np.asarray(self.bias)
        if not np.all(np.isfinite(logits)):
            raise ValueError("Model logits overflowed; coefficients cannot be used safely.")
        return _softmax(logits)

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return the most likely category index, breaking ties by class order."""
        return np.argmax(self.predict_proba(x), axis=1)

    def to_dict(self) -> dict:
        return {
            "model_type": "numpy_multinomial_logistic_regression",
            "target": "reported_job_satisfaction",
            "class_order_worst_to_best": list(self.labels),
            "feature_names": list(self.feature_names),
            "weights": [list(row) for row in self.weights],
            "bias": list(self.bias),
            "initial_loss": self.initial_loss,
            "final_loss": self.final_loss,
            "output": "uncalibrated_class_probabilities",
            "ordinal_distance": "category_steps_only_not_equal_satisfaction_intervals",
        }


def fit_model(
    x: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    labels: list[str],
    l2: float = 0.01,
    epochs: int = 500,
) -> SatisfactionModel:
    """Fit deterministic full-batch softmax with a fixed complete class order.

    At least two classes must be observed. Requested classes absent from training
    remain in the output; callers should report the resulting lack of evidence.
    """
    feature_names = _names(feature_names, "feature_names")
    labels = _names(labels, "labels", minimum=2)
    matrix = _matrix(x, len(feature_names))
    indices = _labels(y, len(labels), len(matrix))
    if len(np.unique(indices)) < 2:
        raise ValueError("Training must observe at least two classes.")
    if not isinstance(epochs, int) or isinstance(epochs, bool) or epochs < 1:
        raise ValueError("epochs must be a positive integer.")
    if isinstance(l2, bool) or not isinstance(l2, (int, float)) or not np.isfinite(l2) or l2 < 0:
        raise ValueError("l2 must be a finite nonnegative number.")

    weights = np.zeros((len(feature_names), len(labels)), dtype=float)
    bias = np.zeros(len(labels), dtype=float)
    targets = np.eye(len(labels))[indices]

    def loss() -> float:
        logits = matrix @ weights + bias
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        log_probabilities = shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))
        return float(
            -np.mean(log_probabilities[np.arange(len(indices)), indices])
            + 0.5 * l2 * np.sum(weights * weights)
        )

    initial_loss = loss()
    # Softmax curvature is <= 1/2; include the intercept in the row norm.
    curvature_bound = 0.5 * (1 + np.mean(np.sum(matrix * matrix, axis=1))) + l2
    learning_rate = 1 / curvature_bound
    for _ in range(epochs):
        residual = _softmax(matrix @ weights + bias) - targets
        weights -= learning_rate * (matrix.T @ residual / len(indices) + l2 * weights)
        bias -= learning_rate * residual.mean(axis=0)
    return SatisfactionModel(feature_names, labels, weights.tolist(), bias.tolist(), initial_loss, loss())


def fit_majority_baseline(y: np.ndarray, classes: int) -> np.ndarray:
    """Return empirical training-class frequencies, including absent categories."""
    if not isinstance(classes, int) or isinstance(classes, bool) or classes < 2:
        raise ValueError("classes must be an integer of at least two.")
    indices = _labels(y, classes)
    return np.bincount(indices, minlength=classes) / len(indices)


def classification_metrics(y: np.ndarray, proba: np.ndarray) -> dict:
    """Category distances describe steps in the order, not satisfaction units."""
    try:
        probabilities = np.asarray(proba, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Probabilities must be a numeric matrix.") from exc
    if probabilities.ndim != 2 or probabilities.shape[1] < 2:
        raise ValueError("Probabilities must be a matrix with at least two classes.")
    if (
        not np.all(np.isfinite(probabilities))
        or np.any((probabilities < 0) | (probabilities > 1))
        or not np.allclose(probabilities.sum(axis=1), 1, rtol=0, atol=1e-7)
    ):
        raise ValueError("Probabilities must be finite, in [0, 1], and sum to one per row.")
    indices = _labels(y, probabilities.shape[1], len(probabilities))
    predictions = probabilities.argmax(axis=1)
    distance = np.abs(predictions - indices)
    confusion = np.zeros((probabilities.shape[1], probabilities.shape[1]), dtype=int)
    np.add.at(confusion, (indices, predictions), 1)
    observed = probabilities[np.arange(len(indices)), indices]
    targets = np.eye(probabilities.shape[1])[indices]
    return {
        "count": len(indices),
        "accuracy": float(np.mean(distance == 0)),
        "ordinal_mae": float(np.mean(distance)),
        "within_one_category": float(np.mean(distance <= 1)),
        "log_loss": float(-np.mean(np.log(np.clip(observed, np.finfo(float).eps, 1)))),
        "multiclass_brier": float(np.mean(np.sum((probabilities - targets) ** 2, axis=1))),
        "confusion_matrix": confusion.tolist(),
    }


def _numeric(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(f"Numeric feature {name!r} must be a number or None.")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError(f"Numeric feature {name!r} must be finite or None.")
    return number


def _category(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Categorical feature {name!r} must be a string or None.")
    return value


@dataclass
class TabularEncoder:
    """Min-max numeric and one-hot categorical features fitted only on training.

    Every numeric feature gets a missing indicator, even if training is complete.
    Every category gets distinct missing/unknown indicators, so test-only values
    never alter the training vocabulary or become conflated with missing answers.
    """

    numeric: list[str]
    categorical: list[str]
    numeric_stats: dict[str, dict[str, float]]
    categories: dict[str, list[str]]

    @classmethod
    def fit(cls, rows: list[dict], numeric: list[str], categorical: list[str]) -> TabularEncoder:
        numeric = _names(numeric, "numeric", minimum=0)
        categorical = _names(categorical, "categorical", minimum=0)
        if not numeric and not categorical:
            raise ValueError("At least one numeric or categorical feature is required.")
        if set(numeric) & set(categorical):
            raise ValueError("Numeric and categorical features must be disjoint.")
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Training rows must be nonempty dictionaries.")
        stats: dict[str, dict[str, float]] = {}
        categories: dict[str, list[str]] = {}
        for name in numeric:
            values = [_numeric(row.get(name), name) for row in rows]
            observed = [value for value in values if value is not None]
            if not observed:
                raise ValueError(f"Numeric feature {name!r} has no observed training values.")
            stats[name] = {
                "minimum": min(observed),
                "maximum": max(observed),
                "median": float(np.median(observed)),
            }
        for name in categorical:
            category_values = [_category(row.get(name), name) for row in rows]
            categories[name] = sorted({value for value in category_values if value is not None})
        return cls(numeric, categorical, stats, categories)

    @property
    def feature_names(self) -> list[str]:
        names: list[str] = []
        for name in self.numeric:
            names.extend((f"{name}__scaled", f"{name}__missing"))
        for name in self.categorical:
            names.extend(f"{name}__category={json.dumps(value)}" for value in self.categories[name])
            names.extend((f"{name}__missing", f"{name}__unknown"))
        return names

    def transform(self, rows: list[dict]) -> np.ndarray:
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("Rows must be dictionaries.")
        matrix = np.zeros((len(rows), len(self.feature_names)), dtype=float)
        offset = 0
        for name in self.numeric:
            stats = self.numeric_stats[name]
            minimum, maximum = stats["minimum"], stats["maximum"]
            for index, row in enumerate(rows):
                value = _numeric(row.get(name), name)
                matrix[index, offset + 1] = value is None
                if value is None:
                    value = stats["median"]
                matrix[index, offset] = (
                    np.clip((value - minimum) / (maximum - minimum), 0, 1) if maximum > minimum else 0
                )
            offset += 2
        for name in self.categorical:
            vocabulary = {value: index for index, value in enumerate(self.categories[name])}
            for index, row in enumerate(rows):
                category = _category(row.get(name), name)
                column = (
                    len(vocabulary) if category is None else vocabulary.get(category, len(vocabulary) + 1)
                )
                matrix[index, offset + column] = 1
            offset += len(vocabulary) + 2
        return matrix

    def to_dict(self) -> dict:
        return {
            "numeric": list(self.numeric),
            "categorical": list(self.categorical),
            "numeric_stats": {name: dict(stats) for name, stats in self.numeric_stats.items()},
            "categories": {name: list(values) for name, values in self.categories.items()},
            "feature_names": self.feature_names,
            "numeric_scaling": "training_min_max_clipped_to_unit_interval",
            "numeric_imputation": "training_median_with_missing_indicator",
            "categorical_encoding": "training_one_hot_with_missing_and_unknown_indicators",
        }
