"""Validation-only Model A learning curve; no test scoring or live matching."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from scripts.matching_research import (
    DATASET,
    LIMITATIONS,
    REVISION,
    load_tables,
    resume_partitions,
    validate_tables,
)
from scripts.matching_research_core import (
    FEATURE_NAMES,
    LogisticModel,
    PreparedCorpus,
    feature_matrix,
    fit_logistic,
    normalize_generator_skill,
    ranking_metrics,
    sample_training_indices,
    split_jobs,
)

PROTOCOL_VERSION = "model-a-validation-learning-curve-v1"
FEATURE_VARIANTS = ("required_only", "all_five")
DEFAULT_SIZES: tuple[int | str, ...] = (25, 100, 500, "all")
DEFAULT_PENALTIES = (0.1, 0.01, 0.001)
PRIMARY_POOL = "unseen_validation_resumes"
EXTRA_LIMITATIONS = [
    "Selection uses fixed balanced known-positive/rule-negative validation pairs, not hiring outcomes.",
    "Balanced sampling has artificial prevalence; sigmoid outputs are not calibrated real-world probabilities.",
    "Test jobs and test-resume pools are not scored, fitted, or used for parameter selection.",
    "Earlier test results have already been inspected; fresh confirmation is still needed.",
    "Better sampled-pair log loss can sharpen the known skill threshold without improving recommendation order.",
    "The final training size is the largest declared size; validation selects only features and regularization there.",
]


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def template_signature(job: dict) -> str:
    def skills(field: str) -> list[str]:
        return sorted({normalize_generator_skill(value) for value in job[field]})

    return json.dumps(
        [
            normalize_generator_skill(job["job_title"]),
            normalize_generator_skill(job["seniority"]),
            skills("must_have_skills"),
            skills("nice_to_have_skills"),
        ],
        sort_keys=True,
    )


def nested_training_sets(jobs: list[dict], sizes: Sequence[int | str], seed: int) -> list[dict]:
    """One label-independent, seeded template order; complete groups stay together."""
    if not sizes or not jobs:
        raise ValueError("Declare nonempty training sizes and training jobs")
    targets: list[int] = []
    for size in sizes:
        if size == "all":
            target = len(jobs)
        elif type(size) is int and 0 < size <= len(jobs):
            target = size
        else:
            raise ValueError("Training sizes must be positive job counts or all")
        if targets and target <= targets[-1]:
            raise ValueError("Training sizes must increase strictly, with all last")
        targets.append(target)
    groups: dict[str, list[dict]] = defaultdict(list)
    for job in jobs:
        groups[template_signature(job)].append(job)
    order = sorted(groups, key=lambda signature: (_digest([seed, signature]), signature))
    result = []
    for declared, target in zip(sizes, targets, strict=True):
        selected = []
        templates = []
        for signature in order:
            selected.extend(sorted(groups[signature], key=lambda job: job["job_id"]))
            templates.append(signature)
            if len(selected) >= target:
                break
        result.append({"declared_size": declared, "jobs": selected, "templates": templates})
    return result


def mask_features(features: np.ndarray, variant: str) -> np.ndarray:
    if variant not in FEATURE_VARIANTS:
        raise ValueError("Choose required_only or all_five")
    if variant == "all_five":
        return features
    masked = np.zeros_like(features)
    masked[:, 0] = features[:, 0]
    return masked


def pair_log_loss(model: LogisticModel, features: np.ndarray, target: np.ndarray) -> float:
    scores = model.scores(features)
    if target.shape != scores.shape or not len(target) or set(np.unique(target)) != {0, 1}:
        raise ValueError("Validation pairs must contain both known classes")
    return float(np.mean(np.logaddexp(0, scores) - target * scores))


@dataclass
class ValidationPool:
    corpus: PreparedCorpus
    matrices: list[tuple[dict, np.ndarray, set[str]]]
    pair_features: np.ndarray
    pair_targets: np.ndarray
    pair_fingerprint: str
    jobs_with_pairs: int


def validation_pool(
    jobs: list[dict], corpus: PreparedCorpus, labels: dict, seed: int, per_class: int
) -> ValidationPool:
    matrices = []
    xs, ys, fingerprints = [], [], []
    available = set(corpus.ids)
    for job in jobs:
        features = feature_matrix(job, corpus)
        positives = labels[job["job_id"]] & available
        indices, target = sample_training_indices(job, corpus, positives, seed, per_class)
        matrices.append((job, features, positives))
        if len(target):
            xs.append(features[indices])
            ys.append(target)
            fingerprints.append([job["job_id"], [corpus.ids[index] for index in indices], target.tolist()])
    if not xs:
        raise ValueError("Each validation pool needs balanced known-label pairs")
    return ValidationPool(corpus, matrices, np.vstack(xs), np.concatenate(ys), _digest(fingerprints), len(xs))


def ranking_summary(pool: ValidationPool, method: str | LogisticModel, k: int) -> dict:
    rows = []
    for _, features, positives in pool.matrices:
        if isinstance(method, LogisticModel):
            scores = method.scores(features)
        elif method == "required_skill_overlap":
            scores = features[:, 0]
        elif method == "equal_required_preferred_overlap":
            scores = (features[:, 0] + features[:, 1]) / 2 if features[0, 2] else features[:, 0]
        else:
            raise ValueError("Unknown ranking method")
        metric = ranking_metrics(scores, pool.corpus, positives, features[:, 0] >= 0.6, k)
        metric.pop("recommended_ids")
        rows.append(metric)
    return {
        "jobs": len(rows),
        "jobs_with_listed_positives": sum(row["listed_positive_count"] > 0 for row in rows),
        "candidate_pool": len(pool.corpus.ids),
        "macro_mean": {
            key: float(np.mean(values))
            if (values := [row[key] for row in rows if row[key] is not None])
            else None
            for key in rows[0]
        },
    }


def restore_model(artifact: dict) -> LogisticModel:
    if (
        not isinstance(artifact, dict)
        or type(artifact.get("schema_version")) is not int
        or artifact.get("schema_version") != 1
        or artifact.get("protocol_version") != PROTOCOL_VERSION
        or artifact.get("target") != "synthetic_relevance"
        or artifact.get("live_execution") is not False
        or artifact.get("test_scored") is not False
        or artifact.get("feature_variant") not in FEATURE_VARIANTS
        or artifact.get("usage") != "experimental_offline_not_promoted"
    ):
        raise ValueError("Unsupported offline learning-curve artifact contract")
    value = artifact.get("fitted_model", {})
    if (
        not isinstance(value, dict)
        or value.get("model_type") != "numpy_logistic_regression"
        or value.get("feature_names") != list(FEATURE_NAMES)
        or value.get("target") != "synthetic_relevance"
        or value.get("output") != "uncalibrated_logit"
        or value.get("calibration") is not None
        or "calibration" not in value
    ):
        raise ValueError("Artifact must preserve the uncalibrated synthetic feature/target contract")
    try:
        model = LogisticModel(value["weights"], value["bias"])
        model.scores(np.zeros((1, len(FEATURE_NAMES))))
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Malformed learning-curve model coefficients") from exc
    if artifact["feature_variant"] == "required_only" and any(weight != 0 for weight in model.weights[1:]):
        raise ValueError("Required-only artifact contains unexpected feature weights")
    return model


def compare_tables(
    tables: dict,
    *,
    sizes: Sequence[int | str] = DEFAULT_SIZES,
    penalties: Sequence[float] = DEFAULT_PENALTIES,
    seed: int = 42,
    epochs: int = 500,
    k: int = 30,
    per_class: int = 30,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict, dict]:
    if (
        type(seed) is not int
        or not 0 <= seed <= 2**32 - 1
        or type(epochs) is not int
        or epochs < 1
        or type(k) is not int
        or k < 1
        or type(per_class) is not int
        or per_class < 1
        or not penalties
        or any(isinstance(value, bool) or not np.isfinite(value) or value < 0 for value in penalties)
        or len(set(penalties)) != len(penalties)
    ):
        raise ValueError("Declare valid fixed seeds, counts, and distinct finite nonnegative penalties")
    validate_tables(tables)
    partitions = split_jobs(tables["jobs"], seed)
    if any(not group for group in partitions.values()):
        raise ValueError("The original job template split needs all three partitions")
    corpora, diagnostics = resume_partitions(tables["resumes"], seed)
    plan = nested_training_sets(partitions["train"], sizes, seed)
    labels = {row["job_id"]: set(row["relevant_resume_ids"]) for row in tables["matches"]}
    if progress:
        progress("Caching fixed validation features; test jobs and test resumes are not scored")
    pools = {
        "training_resumes": validation_pool(
            partitions["validation"], corpora["train"], labels, seed, per_class
        ),
        PRIMARY_POOL: validation_pool(
            partitions["validation"], corpora["validation"], labels, seed, per_class
        ),
    }
    # Compute selected training-pair features once, then reuse identical prefixes.
    pairs = {}
    train_ids = set(corpora["train"].ids)
    for index, job in enumerate(plan[-1]["jobs"], 1):
        indices, target = sample_training_indices(
            job, corpora["train"], labels[job["job_id"]] & train_ids, seed, per_class
        )
        pairs[job["job_id"]] = (feature_matrix(job, corpora["train"], indices), target)
        if progress and index % 250 == 0:
            progress(f"Prepared training pairs for {index}/{len(plan[-1]['jobs'])} jobs")
    curve: list[dict[str, Any]] = []
    final_model = None
    final_choice = None
    primary = pools[PRIMARY_POOL]
    for step in plan:
        usable = [pairs[job["job_id"]] for job in step["jobs"] if len(pairs[job["job_id"]][1])]
        if not usable:
            raise ValueError("Every training size needs balanced pairs")
        x, y = np.vstack([pair[0] for pair in usable]), np.concatenate([pair[1] for pair in usable])
        candidates: list[dict[str, Any]] = []
        fitted = {}
        for variant in FEATURE_VARIANTS:
            for penalty in penalties:
                model = fit_logistic(mask_features(x, variant), y, l2=penalty, epochs=epochs)
                candidate_id = f"{variant}_l2_{penalty:g}"
                fitted[candidate_id] = model
                candidates.append(
                    {
                        "id": candidate_id,
                        "feature_variant": variant,
                        "l2": float(penalty),
                        "primary_validation_pair_log_loss": pair_log_loss(
                            model, primary.pair_features, primary.pair_targets
                        ),
                    }
                )
        selected = {
            variant: min(
                (item for item in candidates if item["feature_variant"] == variant),
                key=lambda item: item["primary_validation_pair_log_loss"],
            )
            for variant in FEATURE_VARIANTS
        }
        step_results = {}
        for name, pool in pools.items():
            step_results[name] = {
                variant: {
                    "pair_log_loss": pair_log_loss(
                        fitted[choice["id"]], pool.pair_features, pool.pair_targets
                    ),
                    "ranking": ranking_summary(pool, fitted[choice["id"]], k),
                }
                for variant, choice in selected.items()
            }
        choice = min(candidates, key=lambda item: item["primary_validation_pair_log_loss"])
        final_choice, final_model = choice, fitted[choice["id"]]
        curve.append(
            {
                "declared_size": step["declared_size"],
                "training_jobs": len(step["jobs"]),
                "training_templates": len(step["templates"]),
                "jobs_with_pairs": len(usable),
                "training_job_ids_sha256": _digest([job["job_id"] for job in step["jobs"]]),
                "training_pairs": len(y),
                "positive_pairs": int(y.sum()),
                "negative_pairs": int(len(y) - y.sum()),
                "candidates": candidates,
                "selected_by_feature_variant": selected,
                "validation": step_results,
            }
        )
        if progress:
            progress(
                f"Completed {len(step['jobs'])} training jobs / {len(y)} pairs; selected validation loss={choice['primary_validation_pair_log_loss']:.4f}"
            )
    assert final_model is not None and final_choice is not None
    artifact = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "target": "synthetic_relevance",
        "live_execution": False,
        "test_scored": False,
        "usage": "experimental_offline_not_promoted",
        "feature_variant": final_choice["feature_variant"],
        "selected_l2": final_choice["l2"],
        "training_jobs": curve[-1]["training_jobs"],
        "training_pairs": curve[-1]["training_pairs"],
        "fitted_model": final_model.to_dict(),
        "limitations": [*LIMITATIONS, *EXTRA_LIMITATIONS],
    }
    if not np.allclose(
        restore_model(json.loads(json.dumps(artifact))).scores(primary.pair_features),
        final_model.scores(primary.pair_features),
        atol=1e-12,
        rtol=0,
    ):
        raise ValueError("Serialized learning-curve candidate failed prediction replay")
    report = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "target": "synthetic_relevance_only",
        "live_execution": False,
        "test_scored": False,
        "active_model_changed": False,
        "seed": seed,
        "epochs": epochs,
        "k": k,
        "pairs_per_class": per_class,
        "penalties": list(penalties),
        "feature_variants": list(FEATURE_VARIANTS),
        "training_order": "seeded_hash_of_structured_template_then_job_id_complete_template_groups",
        "selection_metric": "pooled_balanced_known_pair_log_loss",
        "selection_pool": PRIMARY_POOL,
        "selection_size_policy": "largest_declared_training_size",
        "tie_break": "first_in_declared_grid",
        "split_counts": {name: len(rows) for name, rows in partitions.items()},
        "resume_diagnostics": diagnostics,
        "validation_pools": {
            name: {
                "jobs": len(pool.matrices),
                "candidate_pool": len(pool.corpus.ids),
                "sampled_pairs": len(pool.pair_targets),
                "jobs_with_pairs": pool.jobs_with_pairs,
                "pair_fingerprint": pool.pair_fingerprint,
                "baselines": {
                    method: ranking_summary(pool, method, k)
                    for method in ("required_skill_overlap", "equal_required_preferred_overlap")
                },
            }
            for name, pool in pools.items()
        },
        "learning_curve": curve,
        "selected_candidate": final_choice,
        "independent_final_performance": "not_evaluated_selection_uses_development_validation",
        "limitations": [*LIMITATIONS, *EXTRA_LIMITATIONS],
    }
    return artifact, report


def run_experiment(
    output: Path,
    *,
    data_dir: Path | None = None,
    download: bool = False,
    sizes: Sequence[int | str] = DEFAULT_SIZES,
    penalties: Sequence[float] = DEFAULT_PENALTIES,
    seed: int = 42,
    epochs: int = 500,
    k: int = 30,
    per_class: int = 30,
    progress: Callable[[str], None] | None = None,
) -> dict:
    if output.exists():
        raise ValueError("Choose a new directory; existing models and reports are preserved")
    tables, checksums = load_tables(data_dir, download)
    protocol = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "dataset": DATASET,
        "revision": REVISION if data_dir is None else None,
        "file_sha256": checksums,
        "seed": seed,
        "training_sizes": list(sizes),
        "penalties": list(penalties),
        "epochs": epochs,
        "k": k,
        "pairs_per_class": per_class,
        "feature_variants": list(FEATURE_VARIANTS),
        "selection_pool": PRIMARY_POOL,
        "selection_metric": "pooled_balanced_known_pair_log_loss",
        "test_scored": False,
        "versions": {"python": platform.python_version(), "numpy": np.__version__},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".model-a-curve-", dir=output.parent) as directory:
        staged = Path(directory) / "results"
        staged.mkdir()
        _json(staged / "protocol.json", protocol)
        artifact, report = compare_tables(
            tables,
            sizes=sizes,
            penalties=penalties,
            seed=seed,
            epochs=epochs,
            k=k,
            per_class=per_class,
            progress=progress,
        )
        provenance = {name: protocol[name] for name in ("dataset", "revision", "file_sha256", "versions")}
        artifact.update(provenance)
        report.update(provenance)
        _json(staged / "experimental_model.json", artifact)
        _json(staged / "report.json", report)
        if output.exists():
            raise ValueError("Output appeared during training; refusing to replace it")
        staged.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    try:
        report = run_experiment(
            args.output,
            data_dir=args.data_dir,
            download=args.download,
            progress=lambda message: print(message, flush=True),
        )
    except (ValueError, OSError, ImportError) as exc:
        parser.exit(2, f"Model A learning curve: {exc}\n")
    print("Selected candidate:", report["selected_candidate"])
    print(f"Validation-only synthetic experiment; test pools not scored. Artifacts: {args.output}")


if __name__ == "__main__":
    main()
