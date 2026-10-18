"""Tomo-only exploratory nested group validation; never evaluates the old test set."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
from sklearn.model_selection import GroupKFold

from scripts.wfhs_comparison_features import (
    BASE_FEATURE_NAMES,
    CONTEXT_FEATURE_NAMES,
    EXPANDED_VARIANTS,
    SATISFACTION_ONLY_VARIANTS,
    VARIANTS,
    feature_names,
)
from scripts.wfhs_comparison_models import fit_candidate, predict_artifact
from scripts.wfhs_model import regression_metrics
from scripts.wfhs_research import (
    ALPHAS,
    DEFAULT_RAW,
    LIMITATIONS,
    _hash,
    _json,
    cluster_partition,
    prepare_dataset,
)

PROTOCOL_VERSION = "tomo-baseline-nested-groups-v1"
FOREST_PROTOCOL_VERSION = "tomo-forest-nested-groups-v2"
EXPANDED_PROTOCOL_VERSION = "tomo-expanded-baseline-nested-groups-v3"
SATISFACTION_ONLY_PROTOCOL_VERSION = "tomo-satisfaction-only-nested-groups-v4"
ORIGINAL_SPLIT_SEED = 42
STRATEGIES = ("ridge_baseline", "ridge_interactions", "boosting_baseline", "boosting_interactions")
EXTRA_LIMITATIONS = [
    "Exploratory development comparison on previously inspected study data, not a fresh prospective validation.",
    "Original seed-42 test groups are excluded before outcome parsing; no new final-test metric is calculated.",
    "Nested out-of-fold metrics describe a training/selection procedure, not independent accuracy of the final refitted artifact.",
    "Conditional cluster bootstrap intervals do not include full refitting/model-selection uncertainty.",
    "The fitted candidate is not promoted over the selected Model B and cannot change live matching.",
]


def candidate_grid(
    include_random_forest: bool = False,
    expanded_features: bool = False,
    include_satisfaction_only: bool = False,
) -> list[dict[str, Any]]:
    """Fixed small grid; candidate order resolves exact score ties."""
    if include_satisfaction_only and not expanded_features:
        raise ValueError("Satisfaction-only comparison requires expanded baseline features")
    result = []
    for variant in VARIANTS:
        for alpha in reversed(ALPHAS):
            result.append(
                {
                    "id": f"ridge_{variant}_l2_{alpha:g}",
                    "family": "ridge",
                    "variant": variant,
                    "parameters": {"l2": alpha},
                }
            )
        for depth in (1, 2):
            result.append(
                {
                    "id": f"boosting_{variant}_depth_{depth}",
                    "family": "boosting",
                    "variant": variant,
                    "parameters": {
                        "max_depth": depth,
                        "n_estimators": 100,
                        "learning_rate": 0.03,
                        "min_samples_leaf": 20,
                    },
                }
            )
    if include_random_forest:
        for variant in VARIANTS:
            for depth in (3, 6):
                for leaf in (5, 20):
                    result.append(
                        {
                            "id": f"random_forest_{variant}_depth_{depth}_leaf_{leaf}",
                            "family": "random_forest",
                            "variant": variant,
                            "parameters": {
                                "max_depth": depth,
                                "n_estimators": 200,
                                "min_samples_leaf": leaf,
                                "max_features": 1.0,
                            },
                        }
                    )
    if expanded_features:
        for variant in EXPANDED_VARIANTS + (SATISFACTION_ONLY_VARIANTS if include_satisfaction_only else ()):
            # Reuse the exact algorithm grids; only the declared inputs change.
            for candidate in candidate_grid(include_random_forest):
                if candidate["variant"] != "baseline":
                    continue
                result.append(
                    {
                        **candidate,
                        "id": candidate["id"].replace("_baseline_", f"_{variant}_", 1),
                        "variant": variant,
                    }
                )
    return result


def protocol_version(
    include_random_forest: bool, expanded_features: bool, include_satisfaction_only: bool = False
) -> str:
    if include_satisfaction_only:
        if not expanded_features:
            raise ValueError("Satisfaction-only comparison requires expanded baseline features")
        return SATISFACTION_ONLY_PROTOCOL_VERSION
    if expanded_features:
        return EXPANDED_PROTOCOL_VERSION
    return FOREST_PROTOCOL_VERSION if include_random_forest else PROTOCOL_VERSION


def _groups_hash(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted({row["baseline_cluster"] for row in rows})).encode()).hexdigest()


def grouped_folds(rows: list[dict], count: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    if type(count) is not int or count < 2:
        raise ValueError("At least two group folds are required")
    groups = np.asarray([row["baseline_cluster"] for row in rows])
    if len(set(groups)) < count:
        raise ValueError("Not enough independent work groups for the declared folds")
    splitter = GroupKFold(n_splits=count, shuffle=True, random_state=seed)
    folds = list(splitter.split(np.zeros(len(rows)), groups=groups))
    for train, validation in folds:
        if set(groups[train]) & set(groups[validation]):
            raise ValueError("Work groups crossed a validation boundary")
    return folds


def _targets(rows: list[dict]) -> np.ndarray:
    return np.asarray([row["followup_satisfaction"] for row in rows], dtype=float)


def _features(rows: list[dict]) -> list[dict]:
    return [
        {**row["features"], "baseline_satisfaction": row["baseline_satisfaction"]}
        if set(row["features"]) == set(CONTEXT_FEATURE_NAMES[:-1])
        else row["features"]
        for row in rows
    ]


def tune_candidates(rows: list[dict], grid: list[dict], folds: int, seed: int, metric: str) -> list[dict]:
    """Every candidate fit gets its own fold-local encoder and training labels."""
    if metric not in {"rmse", "mae"}:
        raise ValueError("Choose rmse or mae before running the comparison")
    plans = grouped_folds(rows, folds, seed)
    targets = _targets(rows)
    results = []
    for spec in grid:
        prediction = np.full(len(rows), np.nan)
        for train_indices, validation_indices in plans:
            training = [rows[index] for index in train_indices]
            validation = [rows[index] for index in validation_indices]
            fitted = fit_candidate(_features(training), _targets(training), spec, seed=seed)
            prediction[validation_indices] = fitted.predict(_features(validation))
        results.append({"spec": spec, "metrics": regression_metrics(targets, prediction)})
    return results


def _choose(tuning: list[dict], metric: str, strategy: str | None = None) -> dict:
    eligible = [
        item
        for item in tuning
        if strategy is None or f"{item['spec']['family']}_{item['spec']['variant']}" == strategy
    ]
    if not eligible:
        raise ValueError("No candidates in the requested strategy")
    return min(eligible, key=lambda item: item["metrics"][metric])["spec"]


def paired_cluster_intervals(
    rows: list[dict],
    predictions: dict[str, np.ndarray],
    samples: int,
    seed: int,
    reference_name: str = "original_ridge_recipe",
) -> dict:
    if type(samples) is not int or samples < 20:
        raise ValueError("At least 20 cluster bootstrap samples are required")
    target = _targets(rows)
    groups = sorted({row["baseline_cluster"] for row in rows})
    indices = [
        np.asarray([i for i, row in enumerate(rows) if row["baseline_cluster"] == group]) for group in groups
    ]
    rng = np.random.default_rng(seed)
    draws = [
        np.concatenate([indices[index] for index in rng.integers(len(groups), size=len(groups))])
        for _ in range(samples)
    ]
    reference = predictions[reference_name]
    intervals = {}
    for name, prediction in predictions.items():
        if name == reference_name:
            continue
        deltas: dict[str, list[float]] = {metric: [] for metric in ("mae", "rmse")}
        for draw in draws:
            actual = regression_metrics(target[draw], prediction[draw])
            baseline = regression_metrics(target[draw], reference[draw])
            for metric in deltas:
                deltas[metric].append(actual[metric] - baseline[metric])
        full, baseline = regression_metrics(target, prediction), regression_metrics(target, reference)
        intervals[name] = {
            metric: {
                "estimate": full[metric] - baseline[metric],
                "lower": float(np.quantile(values, 0.025)),
                "upper": float(np.quantile(values, 0.975)),
            }
            for metric, values in deltas.items()
        }
    return {
        "reference": reference_name,
        "resamples": samples,
        "confidence_level": 0.95,
        "method": "paired_whole_cluster_resampling_with_multiplicity",
        "interpretation": "negative_delta_means_lower_error; descriptive_conditional_on_fixed_oof_predictions",
        "includes_refitting_uncertainty": False,
        "intervals": intervals,
    }


def compare_records(
    rows: list[dict],
    audit: dict,
    *,
    seed: int = 42,
    outer_folds: int = 5,
    inner_folds: int = 3,
    metric: str = "rmse",
    bootstrap_samples: int = 1000,
    include_random_forest: bool = False,
    expanded_features: bool = False,
    include_satisfaction_only: bool = False,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict, dict]:
    if metric not in {"rmse", "mae"}:
        raise ValueError("Choose rmse or mae before running the comparison")
    if include_satisfaction_only and (not expanded_features or metric != "rmse"):
        raise ValueError(
            "Satisfaction-only comparison requires expanded baseline features and RMSE selection"
        )
    if type(bootstrap_samples) is not int or bootstrap_samples < 20:
        raise ValueError("At least 20 cluster bootstrap samples are required")
    if audit.get("dataset") != "tomo" or audit.get("data_partition") != "original_train_validation_only":
        raise ValueError("Use the Tomo development-only importer before comparing models")
    if bool(audit.get("expanded_features", False)) != expanded_features:
        raise ValueError("Comparison feature mode must match the importer audit")
    if not rows or len({row["person_id"] for row in rows}) != len(rows):
        raise ValueError("Use exactly one observation per employee")
    if any(cluster_partition(row["baseline_cluster"], ORIGINAL_SPLIT_SEED) == "test" for row in rows):
        raise ValueError("Original test groups must never enter comparison data")
    target = _targets(rows)
    regression_metrics(target, target)
    persistence = np.asarray([row["baseline_satisfaction"] for row in rows])
    regression_metrics(target, persistence)
    if len(np.unique(target)) < 2:
        raise ValueError("Comparison needs variation in reported satisfaction")
    expected_inputs = set(CONTEXT_FEATURE_NAMES[:-1] if expanded_features else BASE_FEATURE_NAMES)
    if any(set(row["features"]) != expected_inputs for row in rows):
        raise ValueError("Prepared inputs must match the declared baseline feature mode")
    grid = candidate_grid(include_random_forest, expanded_features, include_satisfaction_only)
    strategies = (
        (*STRATEGIES, "random_forest_baseline", "random_forest_interactions")
        if include_random_forest
        else STRATEGIES
    )
    if expanded_features:
        families = ("ridge", "boosting", "random_forest") if include_random_forest else ("ridge", "boosting")
        strategies = (
            *strategies,
            *(
                f"{family}_{variant}"
                for variant in EXPANDED_VARIANTS
                + (SATISFACTION_ONLY_VARIANTS if include_satisfaction_only else ())
                for family in families
            ),
        )
    version = protocol_version(include_random_forest, expanded_features, include_satisfaction_only)
    plans = grouped_folds(rows, outer_folds, seed)
    # Validate all inner plans before the first fit to avoid partial experiments.
    for training, _ in plans:
        grouped_folds([rows[index] for index in training], inner_folds, seed)
    prediction = {
        name: np.full(len(rows), np.nan)
        for name in (
            *strategies,
            "selected_pipeline",
            "original_ridge_recipe",
            "training_mean",
            "training_median",
        )
    }
    prediction["baseline_satisfaction_persistence"] = persistence
    folds: list[dict[str, Any]] = []
    for number, (train_indices, validation_indices) in enumerate(plans, 1):
        training = [rows[index] for index in train_indices]
        validation = [rows[index] for index in validation_indices]
        tuning = tune_candidates(training, grid, inner_folds, seed, metric)
        selected = {strategy: _choose(tuning, metric, strategy) for strategy in strategies}
        selected["selected_pipeline"] = _choose(tuning, metric)
        selected["original_ridge_recipe"] = {
            "id": "original_ridge_recipe",
            "family": "ridge",
            "variant": "baseline",
            "parameters": {"l2": 0.1},
        }
        for strategy, spec in selected.items():
            fitted = fit_candidate(_features(training), _targets(training), spec, seed=seed)
            prediction[strategy][validation_indices] = fitted.predict(_features(validation))
        training_target = _targets(training)
        prediction["training_mean"][validation_indices] = float(np.mean(training_target))
        prediction["training_median"][validation_indices] = float(np.median(training_target))
        folds.append(
            {
                "fold": number,
                "training_people": len(training),
                "validation_people": len(validation),
                "training_clusters": len({row["baseline_cluster"] for row in training}),
                "validation_clusters": len({row["baseline_cluster"] for row in validation}),
                "training_group_hash": _groups_hash(training),
                "validation_group_hash": _groups_hash(validation),
                "selected_candidates": {name: spec["id"] for name, spec in selected.items()},
                "inner_validation": tuning,
                "outer_metrics": {
                    name: regression_metrics(target[validation_indices], values[validation_indices])
                    for name, values in prediction.items()
                },
            }
        )
        if progress:
            progress(f"Completed outer group fold {number}/{outer_folds}")
    metrics = {name: regression_metrics(target, values) for name, values in prediction.items()}
    intervals = paired_cluster_intervals(rows, prediction, bootstrap_samples, seed)
    if progress:
        progress("Selecting an experimental candidate using all development groups")
    final_tuning = tune_candidates(rows, grid, outer_folds, seed, metric)
    final_spec = _choose(final_tuning, metric)
    final = fit_candidate(_features(rows), target, final_spec, seed=seed)
    model = final.to_dict()
    # Verify the stored numerical representation, without touching any test row.
    if not np.allclose(
        final.predict(_features(rows)), predict_artifact(model, _features(rows)), atol=1e-10, rtol=0
    ):
        raise ValueError("Serialized candidate failed prediction replay")
    limitations = [
        *[
            limitation
            for limitation in LIMITATIONS
            if limitation
            != "No survey-weighted population inference or cluster-level uncertainty intervals are implemented."
        ],
        "No survey-weighted population inference; cluster intervals are conditional descriptive estimates only.",
        *EXTRA_LIMITATIONS,
    ]
    if include_random_forest:
        limitations.append(
            "Random forests were added after inspecting the earlier development comparison; this extension is exploratory."
        )
    if expanded_features:
        limitations.extend(
            [
                "Expanded baseline inputs were chosen after viewing prior development results; this is exploratory.",
                "Variants with baseline satisfaction forecast existing employees; this response is unavailable for an unstarted job.",
            ]
        )
    if include_satisfaction_only:
        limitations.append(
            "The fitted satisfaction-only ablation was added after inspecting earlier development results; its comparison is exploratory."
        )
    report = {
        "schema_version": 1,
        "protocol_version": version,
        "dataset": "tomo",
        "target": "employee_reported_satisfaction_scale_at_12_months",
        "live_execution": False,
        "fictional_data": False,
        "active_model_changed": False,
        "test_evaluated": False,
        "original_test_split_seed": ORIGINAL_SPLIT_SEED,
        "development_people": len(rows),
        "development_clusters": len({row["baseline_cluster"] for row in rows}),
        "development_group_hash": _groups_hash(rows),
        "preparation": audit,
        "selection_metric": metric,
        "outer_folds": outer_folds,
        "inner_folds": inner_folds,
        "seed": seed,
        "include_random_forest": include_random_forest,
        "expanded_features": expanded_features,
        "include_satisfaction_only": include_satisfaction_only,
        "feature_variants": {
            variant: feature_names(variant)
            for variant in (*VARIANTS, *EXPANDED_VARIANTS, *SATISFACTION_ONLY_VARIANTS)
            if variant in VARIANTS
            or variant in EXPANDED_VARIANTS
            and expanded_features
            or variant in SATISFACTION_ONLY_VARIANTS
            and include_satisfaction_only
        },
        "baseline_satisfaction_model_usage": (
            ["baseline_with_satisfaction", "expanded_with_satisfaction"]
            + (["satisfaction_only"] if include_satisfaction_only else [])
            if expanded_features
            else []
        ),
        "candidate_grid": grid,
        "tie_break": "first_candidate_in_declared_grid",
        "metrics_aggregation": "pooled_predictions_each_employee_held_out_once_in_outer_folds",
        "preprocessing": "encoder_fitted_only_on_each_training_fold_including_inner_selection",
        "folds": folds,
        "nested_oof_metrics": metrics,
        "paired_cluster_bootstrap": intervals,
        "final_development_cv": final_tuning,
        "experimental_candidate": final_spec,
        "final_candidate_performance": "not_independently_evaluated_requires_fresh_outcomes",
        "nested_selector_counts": dict(
            Counter(fold["selected_candidates"]["selected_pipeline"] for fold in folds)
        ),
        "limitations": limitations,
    }
    if include_satisfaction_only:
        report["baseline_satisfaction_ablation"] = {
            "interpretation": "conditions_added_to_fitted_satisfaction_only; negative_error_delta_means_lower_error",
            "feature_timing": "baseline_for_existing_employees_not_prehire",
            "families": {
                family: {
                    "satisfaction_only_metrics": metrics[f"{family}_satisfaction_only"],
                    "condition_model_metrics": {
                        variant: metrics[f"{family}_{variant}"]
                        for variant in ("baseline_with_satisfaction", "expanded_with_satisfaction")
                    },
                    "paired_cluster_bootstrap": paired_cluster_intervals(
                        rows,
                        {
                            name: prediction[name]
                            for name in (
                                f"{family}_satisfaction_only",
                                f"{family}_baseline_with_satisfaction",
                                f"{family}_expanded_with_satisfaction",
                            )
                        },
                        bootstrap_samples,
                        seed,
                        reference_name=f"{family}_satisfaction_only",
                    ),
                }
                for family in families
            },
        }
    artifact = {
        "schema_version": 1,
        "protocol_version": version,
        "dataset": "tomo",
        "source_sha256": audit["source_sha256"],
        "training_people": len(rows),
        "selection_metric": metric,
        "original_test_evaluated": False,
        "usage": "experimental_offline_candidate_not_promoted",
        "live_execution": False,
        "feature_timing": "baseline_for_existing_employees_not_prehire",
        "fitted_candidate": model,
        "limitations": limitations,
    }
    return artifact, report


def run_comparison(
    raw_dir: Path,
    output: Path,
    *,
    seed: int = 42,
    outer_folds: int = 5,
    inner_folds: int = 3,
    metric: str = "rmse",
    bootstrap_samples: int = 1000,
    include_random_forest: bool = False,
    expanded_features: bool = False,
    include_satisfaction_only: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict:
    if output.exists():
        raise ValueError("Choose a new comparison directory; existing results are preserved")
    if include_satisfaction_only and (not expanded_features or metric != "rmse"):
        raise ValueError(
            "Satisfaction-only comparison requires expanded baseline features and RMSE selection"
        )
    documents = ("36158-Codebook.pdf", "36158-User_guide.pdf", "TermsOfUse.html")
    if any(not (raw_dir / name).is_file() for name in documents):
        raise ValueError("Keep the WFHS documentation and terms beside the data")
    preparation_options = {"expanded_features": True} if expanded_features else {}
    rows, audit = prepare_dataset(raw_dir, "tomo", development_only=True, **preparation_options)
    settings = {
        "schema_version": 1,
        "protocol_version": protocol_version(
            include_random_forest, expanded_features, include_satisfaction_only
        ),
        "dataset": "tomo",
        "source_sha256": audit["source_sha256"],
        "document_sha256": {name: _hash(raw_dir / name) for name in documents},
        "seed": seed,
        "outer_folds": outer_folds,
        "inner_folds": inner_folds,
        "selection_metric": metric,
        "bootstrap_samples": bootstrap_samples,
        "candidate_grid": candidate_grid(include_random_forest, expanded_features, include_satisfaction_only),
        "include_random_forest": include_random_forest,
        "expanded_features": expanded_features,
        "include_satisfaction_only": include_satisfaction_only,
        "feature_variants": {
            variant: feature_names(variant)
            for variant in (*VARIANTS, *EXPANDED_VARIANTS, *SATISFACTION_ONLY_VARIANTS)
            if variant in VARIANTS
            or variant in EXPANDED_VARIANTS
            and expanded_features
            or variant in SATISFACTION_ONLY_VARIANTS
            and include_satisfaction_only
        },
        "original_split_seed": ORIGINAL_SPLIT_SEED,
        "reserved_test_evaluated": False,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "sklearn": sklearn.__version__,
        },
        "live_execution": False,
        "fictional_data": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".tomo-comparison-", dir=output.parent) as temporary:
        staged = Path(temporary) / "results"
        staged.mkdir()
        _json(staged / "protocol.json", settings)
        artifact, report = compare_records(
            rows,
            audit,
            seed=seed,
            outer_folds=outer_folds,
            inner_folds=inner_folds,
            metric=metric,
            bootstrap_samples=bootstrap_samples,
            include_random_forest=include_random_forest,
            expanded_features=expanded_features,
            include_satisfaction_only=include_satisfaction_only,
            progress=progress,
        )
        report["versions"] = settings["versions"]
        _json(staged / "experimental_model.json", artifact)
        _json(staged / "report.json", report)
        if output.exists():
            raise ValueError("Output appeared during comparison; refusing to replace it")
        staged.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--outer-folds", type=int, default=5)
    parser.add_argument("--inner-folds", type=int, default=3)
    parser.add_argument("--metric", choices=("rmse", "mae"), default="rmse")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument(
        "--include-random-forest",
        action="store_true",
        help="Extend the original 14 candidates with eight bounded random forest configurations",
    )
    parser.add_argument(
        "--expand-baseline-features",
        action="store_true",
        help="Compare added workplace scales and explicitly separate variants with baseline satisfaction",
    )
    parser.add_argument(
        "--include-satisfaction-only",
        action="store_true",
        help="Add fitted earlier-satisfaction-only controls; requires --expand-baseline-features and RMSE",
    )
    args = parser.parse_args()
    try:
        report = run_comparison(
            args.raw_dir,
            args.output,
            seed=args.seed,
            outer_folds=args.outer_folds,
            inner_folds=args.inner_folds,
            metric=args.metric,
            bootstrap_samples=args.bootstrap_samples,
            include_random_forest=args.include_random_forest,
            expanded_features=args.expand_baseline_features,
            include_satisfaction_only=args.include_satisfaction_only,
            progress=lambda message: print(message, flush=True),
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Tomo comparison: {exc}\n")
    for name, metrics in report["nested_oof_metrics"].items():
        print(f"{name}: MAE={metrics['mae']:.3f}, RMSE={metrics['rmse']:.3f}")
    print(f"Original test groups were not evaluated. Active Model B is unchanged. Artifacts: {args.output}")


if __name__ == "__main__":
    main()
