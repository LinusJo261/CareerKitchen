"""Offline regression for a reported questionnaire-mean satisfaction scale.

The numerical scale is useful for comparing prediction errors, but its steps do
not establish equal changes in wellbeing or satisfaction utility. This module
does not predict employer satisfaction, mutual interest, or a match probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any

import numpy as np


def _feature_names(values: list[str]) -> list[str]:
    if (
        not isinstance(values, (list, tuple))
        or not values
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("feature_names must contain unique nonempty strings.")
    return list(values)


def _number(value: Any, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number.")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result


def _penalty(value: Any) -> float:
    result = _number(value, "l2")
    if result < 0:
        raise ValueError("l2 must be nonnegative.")
    return result


def _numeric_array(value: Any, name: str) -> np.ndarray:
    try:
        array = np.asarray(value)
        # Numeric strings, booleans, and complex values are not measurements.
        if array.dtype.kind not in "iuf":
            raise ValueError
        array = array.astype(float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must contain real numeric values.") from exc
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain finite values.")
    return array


def _matrix(value: Any, columns: int) -> np.ndarray:
    matrix = _numeric_array(value, "Features")
    if matrix.ndim != 2 or matrix.shape[1] != columns:
        raise ValueError(f"Features must be a two-dimensional matrix with {columns} columns.")
    if np.any((matrix < 0) | (matrix > 1)):
        raise ValueError("Features must be normalized to [0, 1].")
    return matrix


def _scale_vector(value: Any, name: str, count: int | None = None) -> np.ndarray:
    vector = _numeric_array(value, name)
    if vector.ndim != 1 or not len(vector) or (count is not None and len(vector) != count):
        raise ValueError(f"{name} must be a nonempty vector matching the observation count.")
    if np.any((vector < 1) | (vector > 5)):
        raise ValueError(f"{name} must be within the reported scale [1, 5].")
    return vector


@dataclass
class ScaleRidgeModel:
    feature_names: list[str]
    weights: list[float]
    bias: float
    l2: float = 1.0

    def __post_init__(self) -> None:
        self.feature_names = _feature_names(self.feature_names)
        weights = _numeric_array(self.weights, "Model weights")
        if weights.shape != (len(self.feature_names),):
            raise ValueError("Model weights must have one entry per feature.")
        self.weights = weights.tolist()
        self.bias = _number(self.bias, "Model bias")
        self.l2 = _penalty(self.l2)

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return clipped questionnaire-scale predictions, never probabilities."""
        matrix = _matrix(x, len(self.feature_names))
        with np.errstate(over="ignore", invalid="ignore"):
            predictions = matrix @ np.asarray(self.weights) + self.bias
        if not np.all(np.isfinite(predictions)):
            raise ValueError("Model predictions overflowed; coefficients cannot be used safely.")
        return np.clip(predictions, 1, 5)

    def to_dict(self) -> dict:
        return {
            "model_type": "numpy_ridge_regression",
            "target": "employee_reported_satisfaction_scale",
            "output": "predicted_scale_value_not_probability",
            "usage": "offline_only",
            "scale_bounds": [1, 5],
            "scale_interpretation": "reported_questionnaire_mean_not_cardinal_satisfaction_utility",
            "feature_names": list(self.feature_names),
            "weights": list(self.weights),
            "bias": self.bias,
            "l2": self.l2,
            "objective": "mean_squared_error_plus_l2_squared_weight_norm",
            "intercept_penalized": False,
            "prediction_clipping": [1, 5],
        }


def fit_ridge(
    x: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    l2: float = 1.0,
) -> ScaleRidgeModel:
    """Minimize average squared error plus ``l2 * sum(weights**2)``.

    Centering leaves the intercept unpenalized. Augmented least squares avoids
    a matrix inverse and also supports collinear features and zero penalty.
    """
    names = _feature_names(feature_names)
    matrix = _matrix(x, len(names))
    target = _scale_vector(y, "Targets", len(matrix))
    if len(matrix) < 2:
        raise ValueError("Training requires at least two observations.")
    penalty = _penalty(l2)
    x_mean = matrix.mean(axis=0)
    y_mean = float(target.mean())
    centered = matrix - x_mean
    # A decimal constant can acquire a tiny residual when its mean is rounded.
    # With l2=0, least squares could mistake that residual for a usable column.
    centered[:, np.ptp(matrix, axis=0) == 0] = 0
    root_count = np.sqrt(len(matrix))
    design = np.vstack(
        (
            centered / root_count,
            np.sqrt(penalty) * np.eye(len(names)),
        )
    )
    response = np.concatenate(((target - y_mean) / root_count, np.zeros(len(names))))
    weights, _, _, _ = np.linalg.lstsq(design, response, rcond=None)
    bias = float(y_mean - x_mean @ weights)
    return ScaleRidgeModel(names, weights.tolist(), bias, penalty)


def regression_metrics(y: np.ndarray, prediction: np.ndarray) -> dict:
    """Errors measure numerical questionnaire-scale values, not match accuracy."""
    target = _scale_vector(y, "Targets")
    predictions = _scale_vector(prediction, "Predictions", len(target))
    residual = predictions - target
    squared_error = float(np.sum(residual * residual))
    variation = float(np.sum((target - target.mean()) ** 2))
    return {
        "count": len(target),
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(squared_error / len(target))),
        "r2": 1 - squared_error / variation if variation > 0 else None,
    }
