"""Train immutable reciprocal matching challengers from frozen explicit decisions.

NumPy is an offline dependency only. No database writes, artifact activation,
online weight updates, or guessed nonresponse labels occur in this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from scripts.mutual_matching_research import (
    ESTIMATION_POPULATION,
    LIMITATIONS,
    TARGET,
    binary_metrics,
    load_records,
    split_records,
    timestamp,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.matching.learning import validate_artifact  # noqa: E402

FEATURE_VERSION = "reciprocal-structured-v1"
FEATURE_NAMES = ("employer_skills", "candidate_role", "candidate_work_mode", "candidate_employment_type")
INPUT_FEATURE_NAMES = (
    "preferred_skill_coverage",
    "candidate_role_preference_alignment",
    "candidate_work_mode_preference_alignment",
    "candidate_employment_type_preference_alignment",
)
L2_GRID = (0.001, 0.01, 0.1, 1.0)


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def sigmoid(value: np.ndarray) -> np.ndarray:
    # logaddexp avoids overflow for deliberately extreme but finite logits.
    return np.exp(-np.logaddexp(0, -np.asarray(value, dtype=float)))


def _values(rows: list[dict]) -> np.ndarray:
    return np.array(
        [
            [np.nan if row["features"][key] is None else row["features"][key] for key in INPUT_FEATURE_NAMES]
            for row in rows
        ],
        dtype=float,
    )


def fit_transforms(rows: list[dict]) -> list[dict]:
    """Only training observations determine imputation, center and scale."""
    values = _values(rows)
    if not np.any(np.isfinite(values)):
        raise ValueError("No known training features; frozen pre-exposure snapshots are required")
    transforms = []
    for column in values.T:
        known = column[np.isfinite(column)]
        median = float(np.median(known)) if len(known) else 0.0
        filled = np.where(np.isnan(column), median, column)
        transforms.append(
            {
                "imputation_median": median,
                "center": float(np.mean(filled)),
                "scale": max(float(np.std(filled)), 0.05),
            }
        )
    return transforms


def transform(rows: list[dict], transforms: list[dict]) -> np.ndarray:
    values = _values(rows)
    result = np.empty((len(rows), len(FEATURE_NAMES) * 2))
    for index, statistics in enumerate(transforms):
        column = values[:, index]
        missing = np.isnan(column)
        result[:, index * 2] = (
            np.where(missing, statistics["imputation_median"], column) - statistics["center"]
        ) / statistics["scale"]
        result[:, index * 2 + 1] = missing.astype(float)
    return result


def fit_logistic(matrix: np.ndarray, labels: np.ndarray, l2: float, max_steps: int = 100) -> dict:
    """Deterministic damped Newton logistic regression with an unpenalized intercept."""
    if (
        matrix.ndim != 2
        or labels.shape != (len(matrix),)
        or not np.all(np.isfinite(matrix))
        or not np.all(np.isin(labels, [0, 1]))
        or len(np.unique(labels)) != 2
    ):
        raise ValueError("Logistic fitting requires finite inputs and both explicit outcome classes")
    if not math.isfinite(l2) or l2 <= 0:
        raise ValueError("A positive finite regularization strength is required")
    x = np.column_stack((np.ones(len(matrix)), matrix))
    beta = np.zeros(x.shape[1])
    mean = float(np.mean(labels))
    beta[0] = math.log(mean / (1 - mean))
    penalty = np.diag([0.0, *([l2] * matrix.shape[1])])

    def loss(parameters: np.ndarray) -> float:
        logits = x @ parameters
        return float(
            np.mean(np.logaddexp(0, logits) - labels * logits) + 0.5 * parameters @ penalty @ parameters
        )

    converged = False
    for _ in range(max_steps):
        probability = sigmoid(x @ beta)
        gradient = x.T @ (probability - labels) / len(x) + penalty @ beta
        if np.max(np.abs(gradient)) < 1e-9:
            converged = True
            break
        curvature = np.maximum(probability * (1 - probability), 1e-10)
        hessian = (x.T * curvature) @ x / len(x) + penalty
        direction = np.linalg.solve(hessian + np.eye(len(beta)) * 1e-10, gradient)
        step, current = 1.0, loss(beta)
        while step > 1e-8:
            proposed = beta - step * direction
            if loss(proposed) <= current - 1e-4 * step * float(gradient @ direction):
                beta = proposed
                break
            step /= 2
        else:
            break
    if not np.all(np.isfinite(beta)):
        raise ValueError("Training failed to produce finite coefficients")
    return {"coefficients": beta[1:].tolist(), "intercept": float(beta[0]), "converged": converged}


def _raw(model: dict, matrix: np.ndarray) -> np.ndarray:
    return matrix @ np.array(model["coefficients"]) + model["intercept"]


def probabilities(model: dict, matrix: np.ndarray, calibration: dict) -> np.ndarray:
    return sigmoid(calibration["slope"] * _raw(model, matrix) + calibration["intercept"])


def _loss(labels: np.ndarray, probability: np.ndarray) -> float:
    safe = np.clip(probability, 1e-15, 1 - 1e-15)
    return float(-np.mean(labels * np.log(safe) + (1 - labels) * np.log(1 - safe)))


def compatibility_baseline(rows: list[dict]) -> np.ndarray:
    """The live equal-applicable compatibility score; a ranking score, not probability."""
    result = []
    for row in rows:
        skills, role, work, employment = [row["features"][name] for name in INPUT_FEATURE_NAMES]
        # Live preferences are known for eligible pairs. Unknown fixture inputs use
        # a declared neutral value solely to make this comparison total.
        role, work, employment = [0.5 if value is None else value for value in (role, work, employment)]
        employer = role if skills is None else (role + skills) / 2
        result.append(math.sqrt(employer * (role + work + employment) / 3))
    return np.asarray(result)


def _ranking_metrics(labels: np.ndarray, probability: np.ndarray) -> tuple[float | None, float | None]:
    positives, negatives = int(np.sum(labels)), len(labels) - int(np.sum(labels))
    if not positives or not negatives:
        return None, None
    order = np.argsort(-probability, kind="stable")
    ordered = probability[order]
    ends = np.r_[np.flatnonzero(ordered[:-1] != ordered[1:]), len(order) - 1]
    tp = np.cumsum(labels[order])[ends]
    fp = ends + 1 - tp
    # Entire tied score groups enter together, avoiding order-dependent AUC/AP.
    roc_auc = float(np.trapezoid(np.r_[0, tp / positives], np.r_[0, fp / negatives]))
    average_precision = float(np.sum(np.diff(np.r_[0, tp / positives]) * tp / (tp + fp)))
    return roc_auc, average_precision


def _wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    mean, denominator = successes / total, 1 + z * z / total
    center = (mean + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(mean * (1 - mean) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def metrics(labels: np.ndarray, probability: np.ndarray, threshold: float = 0.5) -> dict:
    result = binary_metrics(labels, probability)
    predicted = probability >= threshold
    actual = labels == 1
    tp, fp = int(np.sum(predicted & actual)), int(np.sum(predicted & ~actual))
    fn, tn = int(np.sum(~predicted & actual)), int(np.sum(~predicted & ~actual))
    auc, ap = _ranking_metrics(labels, probability)
    result.update(
        {
            "threshold": threshold,
            "accuracy": float(np.mean(predicted == actual)),
            "accuracy_wilson_95": _wilson(tp + tn, len(labels)),
            "balanced_accuracy": 0.5 * (tp / (tp + fn) + tn / (tn + fp)) if tp + fn and tn + fp else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "precision_wilson_95": _wilson(tp, tp + fp),
            "recall": tp / (tp + fn) if tp + fn else None,
            "recall_wilson_95": _wilson(tp, tp + fn),
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
            "confusion_matrix": [[tn, fp], [fn, tp]],
            "roc_auc": auc,
            "average_precision": ap,
            "expected_calibration_error": sum(
                item["count"] * abs(item["mean_prediction"] - item["observed_mutual_rate"])
                for item in result["calibration_bins"]
            )
            / len(labels),
        }
    )
    return result


def choose_threshold(labels: np.ndarray, probability: np.ndarray) -> float:
    # Threshold affects evaluation only; it never overrides eligibility or opt-in.
    positives, negatives = int(np.sum(labels)), len(labels) - int(np.sum(labels))
    if not positives or not negatives:
        raise ValueError("Threshold selection requires both validation outcome classes")
    order = np.argsort(probability, kind="stable")
    values, sorted_labels = probability[order], labels[order]
    candidates = np.unique(np.r_[0, values, 1])
    below = np.searchsorted(values, candidates, side="left")
    false_negatives = np.r_[0, np.cumsum(sorted_labels)][below]
    true_negatives = below - false_negatives
    balanced = 0.5 * ((positives - false_negatives) / positives + true_negatives / negatives)
    index = max(range(len(candidates)), key=lambda item: (balanced[item], -abs(candidates[item] - 0.5)))
    return float(candidates[index])


def paired_confidence(
    rows: list[dict],
    labels: np.ndarray,
    probability: np.ndarray,
    baseline: np.ndarray,
    seed: int,
    replicates: int,
) -> dict:
    """Paired cluster sensitivity intervals for repeated people and employers.

    The envelope of separate candidate and organization bootstrap intervals is a
    conservative sensitivity summary, not a proven two-way bootstrap interval.
    """
    if type(replicates) is not int or replicates < 50:
        raise ValueError("Use at least 50 bootstrap replicates")

    def loss(p: np.ndarray) -> np.ndarray:
        return -(
            labels * np.log(np.clip(p, 1e-15, 1 - 1e-15))
            + (1 - labels) * np.log(np.clip(1 - p, 1e-15, 1 - 1e-15))
        )

    log_delta = loss(probability) - loss(baseline)
    brier_delta = (probability - labels) ** 2 - (baseline - labels) ** 2
    rng = np.random.default_rng(seed)
    by_scope = {}
    for scope in ("candidate_id", "organization_id"):
        grouped: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            grouped.setdefault(row[scope], []).append(index)
        # Resample cluster sums/counts, avoiding expansion of every row on each
        # bootstrap draw when organizations contain many repeated introductions.
        counts = np.array([len(indices) for indices in grouped.values()])
        sums = np.array(
            [
                [float(np.sum(log_delta[indices])), float(np.sum(brier_delta[indices]))]
                for indices in grouped.values()
            ]
        )
        draws = []
        for _ in range(replicates):
            selected = rng.integers(len(counts), size=len(counts))
            draws.append(np.sum(sums[selected], axis=0) / np.sum(counts[selected]))
        scope_intervals = np.quantile(np.array(draws), [0.025, 0.975], axis=0)
        by_scope[scope] = {
            "cluster_count": len(counts),
            "log_loss_delta_95": scope_intervals[:, 0].tolist(),
            "brier_delta_95": scope_intervals[:, 1].tolist(),
        }
    intervals = np.array(
        [
            [
                min(item[metric][0] for item in by_scope.values()),
                max(item[metric][1] for item in by_scope.values()),
            ]
            for metric in ("log_loss_delta_95", "brier_delta_95")
        ]
    )
    return {
        "method": "envelope_of_paired_candidate_and_organization_cluster_percentile_bootstraps",
        "cluster_count": by_scope["candidate_id"]["cluster_count"],
        "replicates": replicates,
        "log_loss_delta": float(np.mean(log_delta)),
        "log_loss_delta_95": intervals[0].tolist(),
        "brier_delta": float(np.mean(brier_delta)),
        "brier_delta_95": intervals[1].tolist(),
        "by_scope": by_scope,
        "interpretation": "negative favors challenger; sensitivity envelope, not guaranteed joint 95% coverage",
    }


def _organization_overlap(groups: dict[str, list[dict]]) -> dict[str, int]:
    names = list(groups)
    result = {}
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            overlap = {row["organization_id"] for row in groups[left]} & {
                row["organization_id"] for row in groups[right]
            }
            result[f"{left}_{right}"] = len(overlap)
    return result


def fit_challenger(groups: dict[str, list[dict]]) -> tuple[dict, dict]:
    """Model/regularization/calibration/threshold selection cannot access test rows."""
    training, validation = groups["train"], groups["validation"]
    transforms = fit_transforms(training)
    train_x, valid_x = transform(training, transforms), transform(validation, transforms)
    train_y = np.array([row["label"] for row in training])
    valid_y = np.array([row["label"] for row in validation])
    if len(np.unique(valid_y)) != 2:
        raise ValueError("Validation must contain both explicit outcome classes")
    choices = []
    identity = {"kind": "identity", "slope": 1.0, "intercept": 0.0}
    for l2 in L2_GRID:
        model = fit_logistic(train_x, train_y, l2)
        choices.append((_loss(valid_y, probabilities(model, valid_x, identity)), l2, model))
    _, selected_l2, fitted = min(choices, key=lambda item: (item[0], -item[1]))
    # A separate temporal half of validation fits calibration. Its later half
    # chooses identity versus Platt, avoiding in-sample calibration selection.
    exposure_times = sorted({row["first_exposed_at"] for row in validation})
    cutoff = exposure_times[len(exposure_times) // 2]
    later = [index for index, row in enumerate(validation) if row["first_exposed_at"] >= cutoff]
    later_candidates = {validation[index]["candidate_id"] for index in later}
    later_organizations = {validation[index]["organization_id"] for index in later}
    earlier = [
        index
        for index, row in enumerate(validation)
        if row["first_exposed_at"] < cutoff
        and row["candidate_id"] not in later_candidates
        and row["organization_id"] not in later_organizations
    ]
    calibration_fit, calibration_select = np.array(earlier, dtype=int), np.array(later, dtype=int)
    calibration = identity
    calibration_reason = "insufficient_validation_classes_for_disjoint_calibration"
    if (
        len(calibration_fit) >= 20
        and len(calibration_select) >= 20
        and len(np.unique(valid_y[calibration_fit])) == 2
        and len(np.unique(valid_y[calibration_select])) == 2
    ):
        raw = _raw(fitted, valid_x)
        platt = fit_logistic(raw[calibration_fit, None], valid_y[calibration_fit], 0.01)
        proposed = {"kind": "platt", "slope": platt["coefficients"][0], "intercept": platt["intercept"]}
        if proposed["slope"] > 0 and _loss(
            valid_y[calibration_select], probabilities(fitted, valid_x[calibration_select], proposed)
        ) < _loss(valid_y[calibration_select], probabilities(fitted, valid_x[calibration_select], identity)):
            calibration = proposed
            calibration_reason = "platt_won_on_separate_later_validation_half"
        else:
            calibration_reason = "identity_won_on_separate_later_validation_half"
    threshold = choose_threshold(valid_y, probabilities(fitted, valid_x, calibration))
    return {
        "transforms": transforms,
        "coefficients": fitted["coefficients"],
        "intercept": fitted["intercept"],
        "calibration": calibration,
        "decision_threshold": threshold,
    }, {
        "selected_l2": selected_l2,
        "l2_validation_log_loss": {str(l2): loss for loss, l2, _ in choices},
        "training_converged": fitted["converged"],
        "calibration_selection": calibration_reason,
        "calibration_fit_count": len(calibration_fit),
        "calibration_selection_count": len(calibration_select),
        "calibration_cohort_policy": "strict exposure-time cut; earlier candidates and organizations purged if present later",
        "threshold_selection": "validation_balanced_accuracy",
    }


def fit_compatibility_probability_baseline(groups: dict[str, list[dict]]) -> dict:
    """Give the incumbent compatibility ranking a fair train-fitted probability map."""
    training, validation = groups["train"], groups["validation"]
    train_x, valid_x = compatibility_baseline(training)[:, None], compatibility_baseline(validation)[:, None]
    train_y, valid_y = (np.array([row["label"] for row in rows]) for rows in (training, validation))
    choices = []
    for l2 in L2_GRID:
        model = fit_logistic(train_x, train_y, l2)
        choices.append((_loss(valid_y, sigmoid(_raw(model, valid_x))), -l2, model))
    _, negative_l2, model = min(choices, key=lambda item: (item[0], item[1]))
    return {**model, "l2": -negative_l2, "feature": "current_compatibility_score"}


def load_incumbent(path: Path, manifest: dict) -> dict:
    """Validate immutable observed incumbent parameters before paired evaluation."""
    artifact = json.loads(path.read_text(encoding="utf-8"))
    validate_artifact(artifact)
    if (
        artifact.get("schema_version") != 2
        or artifact.get("artifact_kind") != "reciprocal_logistic_challenger"
        or artifact.get("target") != TARGET
        or artifact.get("estimation_population") != ESTIMATION_POPULATION
        or artifact.get("feature_version") != FEATURE_VERSION
        or artifact.get("feature_names") != list(FEATURE_NAMES)
        or artifact.get("horizon_days") != manifest["horizon_days"]
    ):
        raise ValueError("Incumbent has incompatible feature, population, target or horizon semantics")
    source = artifact.get("source", {})
    if (
        artifact.get("fictional_data") is not False
        or source.get("kind") != "observed_introduction_outcomes"
        or source.get("dataset") != manifest["source"]["dataset"]
    ):
        raise ValueError("Incumbent requires observed provenance from the same declared dataset population")
    if timestamp(source["exported_at"]) > timestamp(manifest["source"]["exported_at"]):
        raise ValueError("Incumbent cannot have a later source export than the challenger")

    return artifact


def train(
    input_path: Path,
    manifest_path: Path,
    output: Path,
    train_before: str,
    validate_before: str,
    seed: int = 42,
    bootstrap_replicates: int = 1000,
    allow_fictional: bool = False,
    incumbent_path: Path | None = None,
) -> dict:
    if output.exists():
        raise FileExistsError("Choose a fresh immutable model output directory")
    input_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fictional = manifest.get("source", {}).get("kind") == "fictional_fixture"
    if fictional and not allow_fictional:
        raise ValueError("Fictional fixtures require --allow-fictional and cannot qualify for activation")
    rows, diagnostics = load_records(input_path, manifest)
    groups, split = split_records(rows, seed, train_before, validate_before)
    split["class_counts"] = {
        name: {
            "positives": sum(row["label"] == 1 for row in current),
            "negatives": sum(row["label"] == 0 for row in current),
        }
        for name, current in groups.items()
    }
    if (
        hashlib.sha256(input_path.read_bytes()).hexdigest() != input_hash
        or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_hash
    ):
        raise ValueError("Input changed while loading; export an immutable dataset before training")
    fitted, selection = fit_challenger(groups)
    compatibility_model = fit_compatibility_probability_baseline(groups)
    incumbent = load_incumbent(incumbent_path, manifest) if incumbent_path is not None else None
    if incumbent is not None and timestamp(incumbent["source"]["exported_at"]) > min(
        row["first_exposed_at"] for row in groups["validation"]
    ):
        raise ValueError(
            "Freeze incumbent before validation exposures; a later-trained incumbent contaminates evaluation"
        )
    prevalence = float(np.mean([row["label"] for row in groups["train"]]))
    evaluations = {}
    for name in ("validation", "test"):
        current = groups[name]
        labels = np.array([row["label"] for row in current])
        predicted = probabilities(fitted, transform(current, fitted["transforms"]), fitted["calibration"])
        baselines = {
            "training_prevalence": np.full(len(current), prevalence),
            "current_compatibility": compatibility_baseline(current),
            "fitted_compatibility": sigmoid(
                _raw(compatibility_model, compatibility_baseline(current)[:, None])
            ),
        }
        if incumbent is not None:
            baselines["incumbent"] = probabilities(
                incumbent, transform(current, incumbent["transforms"]), incumbent["calibration"]
            )
        evaluations[name] = {
            "challenger": metrics(labels, predicted, fitted["decision_threshold"]),
            "baselines": {key: metrics(labels, value) for key, value in baselines.items()},
            "paired_comparisons": {
                key: paired_confidence(current, labels, predicted, value, seed, bootstrap_replicates)
                for key, value in baselines.items()
            },
        }
    overlaps = _organization_overlap(groups)
    reasons = []
    if fictional:
        reasons.append("FICTIONAL_FIXTURE")
    if any(overlaps.values()):
        reasons.append("ORGANIZATIONS_OVERLAP_ACROSS_SPLITS")
    if not selection["training_converged"]:
        reasons.append("TRAINING_DID_NOT_CONVERGE")
    for name, current in groups.items():
        counts = [sum(row["label"] == label for row in current) for label in (0, 1)]
        if len(current) < 100 or min(counts) < 20:
            reasons.append(f"INSUFFICIENT_{name.upper()}_CLASS_COUNTS")
    for name, result in evaluations.items():
        for baseline, comparison in result["paired_comparisons"].items():
            if comparison["cluster_count"] < 20:
                reasons.append(f"INSUFFICIENT_{name.upper()}_CANDIDATE_CLUSTERS")
            if comparison["by_scope"]["organization_id"]["cluster_count"] < 20:
                reasons.append(f"INSUFFICIENT_{name.upper()}_ORGANIZATION_CLUSTERS")
            if comparison["log_loss_delta_95"][1] >= 0 or comparison["brier_delta_95"][1] >= 0:
                reasons.append(f"NO_CONFIDENT_{name.upper()}_GAIN_VS_{baseline.upper()}")
    provenance = {
        "input_sha256": input_hash,
        "manifest_sha256": manifest_hash,
        "split": split,
        "selection": selection,
        "compatibility_probability_baseline": compatibility_model,
        "incumbent_model_id": incumbent["model_id"] if incumbent is not None else None,
        "bootstrap_seed": seed,
        "test_cohort_sha256": canonical_hash({"cycles": sorted(row["cycle_id"] for row in groups["test"])}),
    }
    evidence = {"eligible_for_review": not reasons, "reasons": sorted(set(reasons))}
    artifact = {
        "schema_version": 2,
        "artifact_kind": "reciprocal_logistic_challenger",
        "target": TARGET,
        "estimation_population": ESTIMATION_POPULATION,
        "feature_version": FEATURE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        **fitted,
        "horizon_days": manifest["horizon_days"],
        "fictional_data": fictional,
        "source": manifest["source"],
        "provenance": provenance,
        "evidence": evidence,
    }
    artifact["model_id"] = canonical_hash(artifact)
    validate_artifact(artifact, require_eligible=False)
    report = {
        "schema_version": 2,
        "model_id": artifact["model_id"],
        "target": TARGET,
        "fictional_data": fictional,
        "source": manifest["source"],
        "data_quality": diagnostics,
        "provenance": provenance,
        "evaluation": evaluations,
        "evidence": evidence,
        "organization_overlap": overlaps,
        "limitations": [
            *LIMITATIONS,
            "Current compatibility is not a calibrated probability; probability losses compare its raw score only.",
            "Wilson intervals assume independent observations; paired confidence summaries envelope separate candidate and organization cluster intervals, without guaranteed joint coverage.",
            "Organization overlap blocks review eligibility; no claim of employer-generalization with overlapping organizations.",
            "Review eligibility is an offline evidence screen, not causal proof or automatic authorization for activation.",
            "Repeated tuning against the same test cohort invalidates its untouched-holdout interpretation.",
            "Regularization selection and calibration use validation outcomes; validation uncertainty is optimistic after selection. The untouched test provides the independent evaluation.",
            "Four structured inputs may offer little variation after hard eligibility; outcome data cannot manufacture missing signals.",
        ],
    }
    prefix = "fictional_" if fictional else "observed_"
    serialized = {
        f"{prefix}model.json": json.dumps(artifact, indent=2, allow_nan=False) + "\n",
        f"{prefix}report.json": json.dumps(report, indent=2, allow_nan=False) + "\n",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    parent = output.parent.resolve()
    staging = Path(tempfile.mkdtemp(prefix=".matching-stage-", dir=parent))
    try:
        for filename, content in serialized.items():
            (staging / filename).write_text(content, encoding="utf-8")
        if output.exists():
            raise FileExistsError("Choose a fresh immutable model output directory")
        staging.rename(output)
    finally:
        # Only remove the unique staging directory created above, never output.
        if staging.exists():
            if staging.resolve().parent != parent or not staging.name.startswith(".matching-stage-"):
                raise RuntimeError("Refusing cleanup outside the model staging directory")
            shutil.rmtree(staging)
    print(
        json.dumps({"model_id": artifact["model_id"], "output": str(output), "evidence": evidence}, indent=2)
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-before", required=True)
    parser.add_argument("--validate-before", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bootstrap-replicates", type=int, default=1000)
    parser.add_argument("--allow-fictional", action="store_true")
    parser.add_argument(
        "--incumbent", type=Path, help="Current active immutable observed model for paired comparison"
    )
    args = parser.parse_args()
    train(
        args.input,
        args.manifest,
        args.output,
        args.train_before,
        args.validate_before,
        args.seed,
        args.bootstrap_replicates,
        args.allow_fictional,
        args.incumbent,
    )


if __name__ == "__main__":
    main()
