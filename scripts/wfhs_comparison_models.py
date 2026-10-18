"""Fold-local offline WFHS estimators and validated JSON-only prediction replay."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral, Real
from typing import Any

import numpy as np

from scripts.satisfaction_model import TabularEncoder
from scripts.wfhs_comparison_features import (
    EXPANDED_VARIANTS,
    SATISFACTION_ONLY_VARIANTS,
    VARIANTS,
    feature_bounds,
    feature_names,
    feature_variant,
)
from scripts.wfhs_model import ScaleRidgeModel, fit_ridge


def _artifact_metadata() -> dict:
    return {
        "schema_version": 1,
        "target": "employee_reported_satisfaction_scale_at_12_months",
        "output": "predicted_scale_value_not_probability",
        "usage": "offline_only",
        "scale_bounds": [1, 5],
        "scale_interpretation": "reported_questionnaire_mean_not_cardinal_satisfaction_utility",
        "feature_timing": "baseline_for_existing_employees_not_prehire",
    }


def _validate_metadata(artifact: Any) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("WFHS comparison artifact must be a dictionary")
    for name, expected in _artifact_metadata().items():
        observed = artifact.get(name)
        if type(observed) is not type(expected):
            raise ValueError(f"Unsupported WFHS comparison artifact {name}")
        if name == "scale_bounds" and (
            not isinstance(observed, list)
            or len(observed) != 2
            or any(type(bound) is not int for bound in observed)
        ):
            raise ValueError("Unsupported WFHS comparison artifact scale_bounds")
        if observed != expected:
            raise ValueError(f"Unsupported WFHS comparison artifact {name}")


def _real(value: Any, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite real number") from exc
    if not np.isfinite(number):
        raise ValueError(f"{name} must be a finite real number")
    return number


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _spec(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"id", "family", "variant", "parameters"}:
        raise ValueError("Candidate specification needs id, family, variant, and parameters")
    if not isinstance(value["id"], str) or not value["id"].strip():
        raise ValueError("Candidate id must be a nonempty string")
    if (
        value["family"] not in ("ridge", "boosting", "random_forest")
        or value["variant"] not in VARIANTS + EXPANDED_VARIANTS + SATISFACTION_ONLY_VARIANTS
    ):
        raise ValueError("Choose a documented candidate family and feature variant")
    parameters = value["parameters"]
    if not isinstance(parameters, dict):
        raise ValueError("Candidate parameters must be a dictionary")
    if value["family"] == "ridge":
        if set(parameters) != {"l2"}:
            raise ValueError("Ridge requires exactly the l2 parameter")
        l2 = _real(parameters["l2"], "l2")
        if l2 < 0:
            raise ValueError("l2 must be nonnegative")
        parameters = {"l2": l2}
    elif value["family"] == "boosting":
        if set(parameters) != {"max_depth", "n_estimators", "learning_rate", "min_samples_leaf"}:
            raise ValueError("Boosting requires depth, estimator count, learning rate, and leaf size")
        depth = _integer(parameters["max_depth"], "max_depth", 1)
        if depth not in (1, 2):
            raise ValueError("Comparison boosting trees must have depth one or two")
        learning_rate = _real(parameters["learning_rate"], "learning_rate")
        if not 0 < learning_rate <= 1:
            raise ValueError("learning_rate must be in (0, 1]")
        parameters = {
            "max_depth": depth,
            "n_estimators": _integer(parameters["n_estimators"], "n_estimators", 1),
            "learning_rate": learning_rate,
            "min_samples_leaf": _integer(parameters["min_samples_leaf"], "min_samples_leaf", 1),
        }
    else:
        if set(parameters) != {"max_depth", "n_estimators", "min_samples_leaf", "max_features"}:
            raise ValueError("Random forest requires depth, estimator count, leaf size, and feature fraction")
        depth = _integer(parameters["max_depth"], "max_depth", 1)
        if depth not in (3, 6):
            raise ValueError("Comparison random forests must have depth three or six")
        max_features = _real(parameters["max_features"], "max_features")
        if not 0 < max_features <= 1:
            raise ValueError("max_features must be in (0, 1]")
        parameters = {
            "max_depth": depth,
            "n_estimators": _integer(parameters["n_estimators"], "n_estimators", 1),
            "min_samples_leaf": _integer(parameters["min_samples_leaf"], "min_samples_leaf", 1),
            "max_features": max_features,
        }
    return {
        "id": value["id"],
        "family": value["family"],
        "variant": value["variant"],
        "parameters": parameters,
    }


def _rows(features: Any, variant: str) -> list[dict]:
    if not isinstance(features, list):
        raise ValueError("Features must be a list of baseline feature mappings")
    return [feature_variant(row, variant) for row in features]


def _targets(y: Any, count: int) -> np.ndarray:
    try:
        raw = np.asarray(y)
        if raw.dtype.kind not in "iuf":
            raise ValueError
        target = raw.astype(float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Targets must be a finite numeric vector") from exc
    if (
        target.shape != (count,)
        or count < 2
        or not np.all(np.isfinite(target))
        or np.any((target < 1) | (target > 5))
    ):
        raise ValueError("At least two scale targets in [1, 5] must match the feature rows")
    return target


def _predictions(value: np.ndarray) -> np.ndarray:
    if not np.all(np.isfinite(value)):
        raise ValueError("Model predictions must remain finite")
    return np.clip(value, 1, 5)


@dataclass
class FittedCandidate:
    spec: dict
    encoder: TabularEncoder
    estimator: Any

    def predict(self, features: list[dict]) -> np.ndarray:
        rows = _rows(features, self.spec["variant"])
        if not rows:
            return np.empty(0, dtype=float)
        return _predictions(np.asarray(self.estimator.predict(self.encoder.transform(rows)), dtype=float))

    def to_dict(self) -> dict:
        if self.spec["family"] == "ridge":
            model = self.estimator.to_dict()
        else:
            import sklearn

            trees = []
            estimators = (
                self.estimator.estimators_.ravel()
                if self.spec["family"] == "boosting"
                else self.estimator.estimators_
            )
            for estimator in estimators:
                tree = estimator.tree_
                trees.append(
                    {
                        "children_left": tree.children_left.tolist(),
                        "children_right": tree.children_right.tolist(),
                        "feature": tree.feature.tolist(),
                        "threshold": tree.threshold.tolist(),
                        "value": tree.value[:, 0, 0].tolist(),
                    }
                )
            model = {
                "sklearn_version": sklearn.__version__,
                "prediction_input_dtype": "float32",
                "trees": trees,
            }
            if self.spec["family"] == "boosting":
                model.update(
                    model_type="gradient_boosting_regression_trees_json",
                    init_constant=float(self.estimator.init_.constant_[0, 0]),
                    learning_rate=float(self.estimator.learning_rate),
                )
            else:
                model.update(model_type="random_forest_regression_trees_json", aggregation="mean")
        return {
            **_artifact_metadata(),
            "spec": _spec(self.spec),
            "encoder": self.encoder.to_dict(),
            "model": model,
        }


def fit_candidate(features: list[dict], y: np.ndarray, spec: dict, seed: int = 42) -> FittedCandidate:
    """Fit all preprocessing on only the rows supplied by the caller's fold."""
    specification = _spec(spec)
    random_state = _integer(seed, "seed")
    if random_state > 2**32 - 1:
        raise ValueError("seed must fit the estimator's unsigned 32-bit random state")
    rows = _rows(features, specification["variant"])
    target = _targets(y, len(rows))
    encoder = TabularEncoder.fit(rows, feature_names(specification["variant"]), [])
    matrix = encoder.transform(rows)
    if specification["family"] == "ridge":
        estimator = fit_ridge(matrix, target, encoder.feature_names, **specification["parameters"])
    elif specification["family"] == "boosting":
        from sklearn.ensemble import GradientBoostingRegressor

        estimator = GradientBoostingRegressor(
            **specification["parameters"],
            loss="squared_error",
            subsample=1.0,
            n_iter_no_change=None,
            random_state=random_state,
        ).fit(matrix, target)
    else:
        from sklearn.ensemble import RandomForestRegressor

        estimator = RandomForestRegressor(
            **specification["parameters"],
            criterion="squared_error",
            bootstrap=True,
            oob_score=False,
            n_jobs=1,
            random_state=random_state,
        ).fit(matrix, target)
    return FittedCandidate(specification, encoder, estimator)


def _encoder(value: Any, variant: str) -> TabularEncoder:
    names = feature_names(variant)
    if (
        not isinstance(value, dict)
        or value.get("numeric") != names
        or value.get("categorical") != []
        or value.get("categories") != {}
        or not isinstance(value.get("numeric_stats"), dict)
        or set(value["numeric_stats"]) != set(names)
    ):
        raise ValueError("Artifact encoder must retain the exact numerical feature contract")
    stats = {}
    for name in names:
        current = value["numeric_stats"][name]
        if not isinstance(current, dict) or set(current) != {"minimum", "maximum", "median"}:
            raise ValueError("Artifact numerical statistics need minimum, maximum, and median")
        current = {key: _real(number, key) for key, number in current.items()}
        low, high = feature_bounds(name)
        if not low <= current["minimum"] <= current["median"] <= current["maximum"] <= high:
            raise ValueError("Artifact numerical statistics violate feature domains or ordering")
        stats[name] = current
    encoder = TabularEncoder(names, [], stats, {})
    if value.get("feature_names") != encoder.feature_names:
        raise ValueError("Artifact encoded feature order is inconsistent")
    return encoder


def _tree(value: Any, columns: int, max_depth: int) -> dict[str, np.ndarray]:
    keys = {"children_left", "children_right", "feature", "threshold", "value"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Each JSON regression tree needs its documented node arrays")
    arrays = {}
    for name in keys:
        if not isinstance(value[name], list) or not value[name]:
            raise ValueError("Regression tree node arrays must be nonempty lists")
        if name in {"children_left", "children_right", "feature"}:
            if any(
                isinstance(item, (bool, np.bool_)) or not isinstance(item, Integral) for item in value[name]
            ):
                raise ValueError("Tree indices must be integer values")
            try:
                arrays[name] = np.asarray(value[name], dtype=np.int64)
            except (ValueError, OverflowError) as exc:
                raise ValueError("Tree indices exceed supported bounds") from exc
        else:
            arrays[name] = np.asarray([_real(item, f"Tree {name}") for item in value[name]])
    count = len(arrays["value"])
    if any(array.shape != (count,) for array in arrays.values()) or count > 2 ** (max_depth + 1) - 1:
        raise ValueError("Tree arrays must align and respect the configured shallow depth")
    visited = set()
    pending = [(0, 0)]
    while pending:
        node, depth = pending.pop()
        if node in visited or not 0 <= node < count or depth > max_depth:
            raise ValueError("Tree must be acyclic, rooted, and within its documented depth")
        visited.add(node)
        left, right = int(arrays["children_left"][node]), int(arrays["children_right"][node])
        feature = int(arrays["feature"][node])
        if left == right == -1:
            if feature != -2:
                raise ValueError("Leaf feature indices must use the documented -2 sentinel")
        else:
            if not (0 <= left < count and 0 <= right < count and 0 <= feature < columns):
                raise ValueError("Tree child and feature indices are outside their bounds")
            if not 0 <= arrays["threshold"][node] <= 1:
                raise ValueError("Tree thresholds must lie within normalized feature bounds")
            pending.extend(((left, depth + 1), (right, depth + 1)))
    if len(visited) != count:
        raise ValueError("Tree node arrays contain unreachable nodes")
    return arrays


def predict_artifact(artifact: dict, features: list[dict]) -> np.ndarray:
    """Replay primitive JSON coefficients/trees without deserialization or fitting."""
    _validate_metadata(artifact)
    try:
        specification = _spec(artifact["spec"])
        encoder = _encoder(artifact["encoder"], specification["variant"])
        rows = _rows(features, specification["variant"])
        matrix = encoder.transform(rows)
        model = artifact["model"]
        if not isinstance(model, dict):
            raise ValueError("Artifact model must be a dictionary")
        if specification["family"] == "ridge":
            if (
                model.get("feature_names") != encoder.feature_names
                or model.get("l2") != specification["parameters"]["l2"]
            ):
                raise ValueError("Artifact ridge coefficient order or penalty is inconsistent")
            restored = ScaleRidgeModel(model["feature_names"], model["weights"], model["bias"], model["l2"])
            return restored.predict(matrix)
        parameters = specification["parameters"]
        family = specification["family"]
        expected_type = (
            "gradient_boosting_regression_trees_json"
            if family == "boosting"
            else "random_forest_regression_trees_json"
        )
        if model.get("model_type") != expected_type or model.get("prediction_input_dtype") != "float32":
            raise ValueError("Unsupported tree ensemble artifact representation")
        if family == "boosting":
            rate = _real(model["learning_rate"], "Boosting learning_rate")
            initial = _real(model["init_constant"], "Boosting initial scale")
            if rate != parameters["learning_rate"] or not 1 <= initial <= 5:
                raise ValueError("Boosting initial scale or learning rate is inconsistent")
        else:
            if model.get("aggregation") != "mean":
                raise ValueError("Random forest predictions must average all trees")
            initial = 0.0
            rate = 1.0 / parameters["n_estimators"]
        raw_trees = model["trees"]
        if not isinstance(raw_trees, list) or len(raw_trees) != parameters["n_estimators"]:
            raise ValueError("Tree count differs from the candidate specification")
        trees = [_tree(tree, matrix.shape[1], parameters["max_depth"]) for tree in raw_trees]
        if family == "random_forest" and any(
            np.any((tree["value"] < 1) | (tree["value"] > 5)) for tree in trees
        ):
            raise ValueError("Random forest node predictions must remain within the target scale")
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError("Malformed WFHS comparison artifact") from exc
    # sklearn decision trees compare float32 inputs against double thresholds.
    matrix = matrix.astype(np.float32)
    prediction = np.full(len(rows), initial)
    with np.errstate(over="ignore", invalid="ignore"):
        for tree in trees:
            for row_index, row in enumerate(matrix):
                node = 0
                while tree["children_left"][node] != -1:
                    feature = tree["feature"][node]
                    node = (
                        tree["children_left"][node]
                        if row[feature] <= tree["threshold"][node]
                        else tree["children_right"][node]
                    )
                prediction[row_index] += rate * tree["value"][node]
    return _predictions(prediction)
