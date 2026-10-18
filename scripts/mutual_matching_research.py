"""Offline prediction of two explicit opt-ins; never imported by live clearing."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from scripts.mutual_matching_features import FEATURE_NAMES, validate_features
from scripts.satisfaction_model import SatisfactionModel, TabularEncoder, fit_model

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".local" / "mutual-matching"
TARGET = "mutual_opt_in_within_horizon"
FEATURE_VERSION = "mutual-pair-features-v1"
ESTIMATION_POPULATION = "eligible_issued_introductions_with_explicit_resolution_within_horizon"
LABELS = ["explicit_pass", "mutual_opt_in"]
SIDES = ("candidate", "employer")
ROW_KEYS = {
    "cycle_id",
    "candidate_id",
    "vacancy_id",
    "organization_id",
    "candidate_version",
    "vacancy_version",
    "feature_as_of",
    "first_exposed_at",
    "first_mover",
    "policy_version",
    "eligibility",
    "observation_status",
    "observed_at",
    "features",
    "decisions",
}
LIMITATIONS = [
    "Offline, uncalibrated estimate of explicit mutual opt-in, not hiring, job satisfaction or employment start.",
    "Only eligible issued introductions with two explicit opt-ins or an explicit pass inside the horizon are labeled.",
    "Pending, expired, cancelled, withdrawn, changed-term and late outcomes are excluded, not inferred negatives.",
    "Selective exposure and response censoring remain; observed-decision performance is not performance on all possible pairs.",
    "Preferences are pre-exposure inputs; this cycle's interest responses are outcomes, never predictive features.",
    "Sanitized, consented, versioned point-in-time exports must be supplied; timestamps alone do not verify provenance.",
    "No calibration certification, live activation, introductions, consent changes or attention allocation.",
]


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Timestamps must be timezone-aware ISO 8601 strings")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Timestamps must be timezone-aware ISO 8601 strings") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone")
    return result.astimezone(UTC)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "REPLACE" in value:
        raise ValueError(f"Set a nonempty {name} from the actual export")
    return value


def validate_manifest(manifest: dict) -> None:
    if set(manifest) != {"schema_version", "target", "feature_version", "horizon_days", "source"}:
        raise ValueError("Unexpected manifest fields")
    if manifest["schema_version"] != 1 or manifest["target"] != TARGET:
        raise ValueError("Expected explicit mutual opt-in target, not satisfaction or synthetic relevance")
    if manifest["feature_version"] != FEATURE_VERSION:
        raise ValueError("Unsupported feature version")
    if type(manifest["horizon_days"]) is not int or not 1 <= manifest["horizon_days"] <= 365:
        raise ValueError("Declare a horizon_days between 1 and 365 before training")
    source = manifest["source"]
    if set(source) != {"kind", "dataset", "source_version", "exported_at"} or source["kind"] not in {
        "observed_introduction_outcomes",
        "fictional_fixture",
    }:
        raise ValueError("Training requires explicit introduction outcomes or a labeled fictional fixture")
    _text(source["dataset"], "source dataset")
    _text(source["source_version"], "source version")
    timestamp(source["exported_at"])


def _decision(value: dict, first_exposed: datetime, observed: datetime) -> dict:
    if not isinstance(value, dict) or set(value) != {"status", "issued_at", "answered_at"}:
        raise ValueError("Each decision requires status, issued_at and answered_at")
    status = value["status"]
    if status not in {"NOT_ISSUED", "PENDING", "INTERESTED", "PASSED", "EXPIRED", "CANCELLED"}:
        raise ValueError("Unsupported decision status")
    issued = timestamp(value["issued_at"]) if value["issued_at"] is not None else None
    answered = timestamp(value["answered_at"]) if value["answered_at"] is not None else None
    if status == "NOT_ISSUED":
        if issued is not None or answered is not None:
            raise ValueError("Unissued decisions cannot have issuance or answer timestamps")
    elif issued is None or not first_exposed <= issued <= observed:
        raise ValueError("Decision issuance must follow first exposure and precede observation")
    if status in {"INTERESTED", "PASSED"}:
        if issued is None or answered is None or not issued <= answered <= observed:
            raise ValueError("Explicit responses require an answer timestamp after issuance")
    elif answered is not None:
        raise ValueError("Unanswered decisions cannot carry an explicit answer timestamp")
    return {"status": status, "issued_at": issued, "answered_at": answered}


def label_record(raw: dict, horizon_days: int) -> tuple[dict, str | None]:
    """Validate a frozen snapshot and derive a label from observed decisions only."""
    if not isinstance(raw, dict) or set(raw) != ROW_KEYS:
        raise ValueError("Introduction records must use exactly the documented snapshot/outcome fields")
    for name in ("cycle_id", "candidate_id", "vacancy_id", "organization_id", "policy_version"):
        _text(raw[name], name)
    for name in ("candidate_version", "vacancy_version"):
        if type(raw[name]) is not int or raw[name] < 1:
            raise ValueError("Snapshot profile and vacancy versions must be positive integers")
    features = validate_features(raw["features"])
    as_of, exposed, observed = (
        timestamp(raw[name])
        for name in (
            "feature_as_of",
            "first_exposed_at",
            "observed_at",
        )
    )
    if not as_of <= exposed <= observed:
        raise ValueError("Features must be frozen before first exposure; observation follows exposure")
    if raw["first_mover"] not in SIDES or set(raw["decisions"]) != set(SIDES):
        raise ValueError("Declare both decisions and a candidate/employer first mover")
    decisions = {side: _decision(raw["decisions"][side], exposed, observed) for side in SIDES}
    first = decisions[raw["first_mover"]]
    second = decisions[next(side for side in SIDES if side != raw["first_mover"])]
    if first["issued_at"] != exposed:
        raise ValueError("The first-mover card must be issued at first_exposed_at")
    if second["status"] != "NOT_ISSUED" and (
        first["status"] != "INTERESTED" or second["issued_at"] < first["answered_at"]
    ):
        raise ValueError("The second card requires the first side's prior explicit opt-in")
    if raw["eligibility"] not in {"ELIGIBLE", "INELIGIBLE", "NEEDS_CLARIFICATION"}:
        raise ValueError("Unknown eligibility state")
    if raw["observation_status"] not in {"OBSERVABLE", "CANCELLED", "TERMS_CHANGED", "WITHDRAWN"}:
        raise ValueError("Unknown observation status")
    record = {
        **{
            name: raw[name]
            for name in (
                "cycle_id",
                "candidate_id",
                "vacancy_id",
                "organization_id",
                "policy_version",
            )
        },
        "features": features,
        "first_exposed_at": exposed,
        "observed_at": observed,
    }
    if raw["eligibility"] != "ELIGIBLE":
        return record, "ineligible_or_unclear"
    if raw["observation_status"] != "OBSERVABLE":
        return record, raw["observation_status"].lower()
    if any(item["status"] in {"EXPIRED", "CANCELLED"} for item in decisions.values()):
        return record, "expired_or_cancelled"
    deadline = exposed + timedelta(days=horizon_days)
    passes = [item["answered_at"] for item in decisions.values() if item["status"] == "PASSED"]
    if passes and min(passes) <= deadline:
        return {**record, "label": 0, "label_observed_at": min(passes)}, None
    if all(item["status"] == "INTERESTED" for item in decisions.values()):
        resolved = max(item["answered_at"] for item in decisions.values())
        if resolved <= deadline:
            return {**record, "label": 1, "label_observed_at": resolved}, None
        return record, "outside_horizon"
    if passes:
        return record, "outside_horizon"
    return record, "unresolved"


def load_records(path: Path, manifest: dict) -> tuple[list[dict], dict]:
    validate_manifest(manifest)
    records, seen = [], set()
    exclusions: Counter[str] = Counter()
    exported = timestamp(manifest["source"]["exported_at"])
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            record, reason = label_record(raw, manifest["horizon_days"])
            if record["cycle_id"] in seen:
                raise ValueError("Duplicate introduction cycle; export one frozen row per cycle")
            seen.add(record["cycle_id"])
            if timestamp(raw["observed_at"]) > exported:
                raise ValueError("An observation cannot occur after the export timestamp")
            if reason:
                exclusions[reason] += 1
            else:
                records.append(record)
    if not records:
        raise ValueError(
            "No observed mutual opt-ins or explicit passes; survey satisfaction cannot supply these labels"
        )
    return records, {"source_cycles": len(seen), "labeled_cycles": len(records), "excluded": dict(exclusions)}


def identity_group(kind: str, identity: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{kind}:{identity}".encode()).hexdigest(), 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def split_records(
    records: list[dict], seed: int, train_before: str, validate_before: str
) -> tuple[dict, dict]:
    first, second = timestamp(train_before), timestamp(validate_before)
    if first >= second:
        raise ValueError("train-before must precede validate-before")
    groups: dict[str, list[dict]] = {name: [] for name in ("train", "validation", "test")}
    excluded = 0
    for row in records:
        candidate_group = identity_group("candidate", row["candidate_id"], seed)
        vacancy_group = identity_group("vacancy", row["vacancy_id"], seed)
        group = candidate_group if candidate_group == vacancy_group else None
        included = (
            group == "train"
            and row["observed_at"] < first
            or group == "validation"
            and first <= row["first_exposed_at"]
            and row["observed_at"] < second
            or group == "test"
            and row["first_exposed_at"] >= second
        )
        if included and group is not None:
            groups[group].append(row)
        else:
            excluded += 1
    if any(not rows for rows in groups.values()):
        raise ValueError("Empty evaluation split; obtain more observed pairs or review declared date cutoffs")
    return groups, {
        "policy": "candidate-disjoint and vacancy-disjoint hash groups intersected with forward-time cohorts",
        "seed": seed,
        "train_before": train_before,
        "validate_before": validate_before,
        "outside_group_time_cohort": excluded,
        "counts": {name: len(rows) for name, rows in groups.items()},
    }


def binary_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict:
    labels, probabilities = np.asarray(labels), np.asarray(probabilities, dtype=float)
    if (
        labels.ndim != 1
        or not len(labels)
        or probabilities.shape != labels.shape
        or not np.all(np.isin(labels, [0, 1]))
        or not np.all(np.isfinite(probabilities))
        or np.any((probabilities < 0) | (probabilities > 1))
    ):
        raise ValueError("Binary metrics require observed 0/1 labels and finite matching probabilities")
    predictions = probabilities >= 0.5
    positives, negatives = labels == 1, labels == 0
    tp, fp = int(np.sum(predictions & positives)), int(np.sum(predictions & negatives))
    fn, tn = int(np.sum(~predictions & positives)), int(np.sum(~predictions & negatives))
    safe = np.clip(probabilities, np.finfo(float).eps, 1 - np.finfo(float).eps)
    bins = []
    for index in range(10):
        mask = (probabilities >= index / 10) & (
            probabilities <= 1 if index == 9 else probabilities < (index + 1) / 10
        )
        if np.any(mask):
            bins.append(
                {
                    "lower": index / 10,
                    "upper": (index + 1) / 10,
                    "count": int(np.sum(mask)),
                    "mean_prediction": float(np.mean(probabilities[mask])),
                    "observed_mutual_rate": float(np.mean(labels[mask])),
                }
            )
    return {
        "count": len(labels),
        "positives": int(np.sum(positives)),
        "accuracy": float(np.mean(predictions == labels)),
        "balanced_accuracy": 0.5 * (tp / (tp + fn) + tn / (tn + fp))
        if np.any(positives) and np.any(negatives)
        else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "log_loss": float(-np.mean(labels * np.log(safe) + (1 - labels) * np.log(1 - safe))),
        "brier_score": float(np.mean((probabilities - labels) ** 2)),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "calibration_bins": bins,
    }


def train(
    input_path: Path,
    manifest_path: Path,
    output: Path,
    train_before: str,
    validate_before: str,
    seed: int = 42,
    epochs: int = 500,
    l2: float = 0.01,
) -> dict:
    manifest = json.loads(manifest_path.read_text())
    rows, diagnostics = load_records(input_path, manifest)
    groups, split = split_records(rows, seed, train_before, validate_before)
    active = [
        name for name in FEATURE_NAMES if any(row["features"][name] is not None for row in groups["train"])
    ]
    if not active:
        raise ValueError(
            "No observed training features; collect structured experience and preference snapshots"
        )
    encoder = TabularEncoder.fit([row["features"] for row in groups["train"]], active, [])
    xs = {name: encoder.transform([row["features"] for row in records]) for name, records in groups.items()}
    ys = {name: np.array([row["label"] for row in records]) for name, records in groups.items()}
    # Reuse the numeric classifier/encoder only, never satisfaction labels or weights.
    fitted = fit_model(xs["train"], ys["train"], encoder.feature_names, LABELS, l2=l2, epochs=epochs)
    prevalence = float(np.mean(ys["train"]))
    evaluation = {
        name: {
            "model": binary_metrics(ys[name], fitted.predict_proba(xs[name])[:, 1]),
            "training_prevalence_baseline": binary_metrics(ys[name], np.full(len(ys[name]), prevalence)),
        }
        for name in ("validation", "test")
    }
    fictional = manifest["source"]["kind"] == "fictional_fixture"
    limitations = LIMITATIONS + (
        ["FICTIONAL SOFTWARE FIXTURE: metrics are not real matching performance."] if fictional else []
    )
    provenance = {
        "source": manifest["source"],
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "split": split,
        "epochs": epochs,
        "l2": l2,
    }
    common = {
        "schema_version": 1,
        "target": TARGET,
        "feature_version": FEATURE_VERSION,
        "estimation_population": ESTIMATION_POPULATION,
        "horizon_days": manifest["horizon_days"],
        "live_execution": False,
        "fictional_data": fictional,
        "estimate_kind": "EXPERIMENTAL_UNCALIBRATED",
        "provenance": provenance,
        "limitations": limitations,
    }
    report = {
        **common,
        "data_quality": diagnostics,
        "features": list(FEATURE_NAMES),
        "active_features": active,
        "unobserved_training_features": [name for name in FEATURE_NAMES if name not in active],
        "evaluation": evaluation,
    }
    model = {
        "model_type": "numpy_binary_logistic_regression",
        "class_order": LABELS,
        "feature_names": fitted.feature_names,
        "weights": fitted.weights,
        "bias": fitted.bias,
    }
    artifact = {**common, "model": model, "encoder": encoder.to_dict()}
    # A fresh destination preserves earlier experiments and protects input files.
    output.mkdir(parents=True, exist_ok=False)
    prefix = "fictional_" if fictional else "observed_"
    for name, data in (("match_report.json", report), ("match_model.json", artifact)):
        (output / (prefix + name)).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    print(
        "FICTIONAL SOFTWARE FIXTURE ONLY" if fictional else "OBSERVED INTRODUCTION EXPERIMENT — OFFLINE ONLY"
    )
    for name, result in evaluation.items():
        print(
            f"{name}: {result['model']['count']} pairs; log loss={result['model']['log_loss']:.4f}; "
            f"baseline log loss={result['training_prevalence_baseline']['log_loss']:.4f}"
        )
    print(f"Artifacts: {output}")
    return report


def _load_encoder(data: dict) -> TabularEncoder:
    names, stats = data["numeric"], data["numeric_stats"]
    if (
        not isinstance(names, list)
        or not names
        or names != [name for name in FEATURE_NAMES if name in names]
        or data["categorical"]
        or data["categories"]
        or set(stats) != set(names)
    ):
        raise ValueError("Artifact feature contract differs from the fixed pair feature set")
    for name in names:
        item = stats[name]
        if set(item) != {"minimum", "maximum", "median"}:
            raise ValueError("Invalid training encoder statistics")
        if any(type(value) not in (int, float) or not np.isfinite(value) for value in item.values()):
            raise ValueError("Invalid training encoder statistics")
        if not 0 <= item["minimum"] <= item["median"] <= item["maximum"]:
            raise ValueError("Invalid training encoder statistics")
        if name != "relevant_experience_years" and item["maximum"] > 1:
            raise ValueError("Invalid training alignment statistics")
    encoder = TabularEncoder(names, [], stats, {})
    if data["feature_names"] != encoder.feature_names:
        raise ValueError("Artifact encoder feature order differs")
    return encoder


def predict(artifact_path: Path, snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or set(snapshot) != {"schema_version", "eligibility", "features"}:
        raise ValueError(
            "Prediction accepts only schema_version, eligibility and frozen features; outcomes are forbidden"
        )
    if snapshot["schema_version"] != 1:
        raise ValueError("Unsupported snapshot schema")
    features = validate_features(snapshot["features"])
    if snapshot["eligibility"] not in {"ELIGIBLE", "INELIGIBLE", "NEEDS_CLARIFICATION"}:
        raise ValueError("Unknown eligibility state")
    base = {
        "target": TARGET,
        "estimation_population": ESTIMATION_POPULATION,
        "live_execution": False,
        "match_probability": None,
    }
    if snapshot["eligibility"] != "ELIGIBLE":
        return {**base, "status": "ABSTAIN", "reason": snapshot["eligibility"]}
    if not artifact_path.exists():
        return {**base, "status": "NOT_TRAINED", "reason": "Observed mutual opt-in training data required"}
    artifact = json.loads(artifact_path.read_text())
    if (
        artifact["schema_version"] != 1
        or artifact["target"] != TARGET
        or artifact["feature_version"] != FEATURE_VERSION
    ):
        raise ValueError("Artifact is not a compatible mutual opt-in model")
    if artifact["live_execution"] is not False or artifact["estimate_kind"] != "EXPERIMENTAL_UNCALIBRATED":
        raise ValueError("Only explicitly offline experimental artifacts are supported")
    if artifact.get("estimation_population") != ESTIMATION_POPULATION:
        raise ValueError("Artifact has incompatible outcome-selection semantics")
    encoder = _load_encoder(artifact["encoder"])
    if all(features[name] is None for name in encoder.numeric):
        return {**base, "status": "ABSTAIN", "reason": "NO_KNOWN_INPUT_FEATURES"}
    model = artifact["model"]
    if model["model_type"] != "numpy_binary_logistic_regression" or model["class_order"] != LABELS:
        raise ValueError("Artifact has an incompatible model or target class order")
    if model["feature_names"] != encoder.feature_names:
        raise ValueError("Artifact model and encoder feature order differ")
    fitted = SatisfactionModel(model["feature_names"], LABELS, model["weights"], model["bias"])
    probability = float(fitted.predict_proba(encoder.transform([features]))[0, 1])
    return {
        **base,
        "status": "EXPERIMENTAL_UNCALIBRATED",
        "match_probability": probability,
        "horizon_days": artifact["horizon_days"],
        "fictional_data": artifact["fictional_data"],
        "feature_version": FEATURE_VERSION,
        "unused_training_features": [name for name in FEATURE_NAMES if name not in encoder.numeric],
    }


def initialize(directory: Path) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Choose an empty input directory; existing data will not be overwritten")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "target": TARGET,
        "feature_version": FEATURE_VERSION,
        "horizon_days": 14,
        "source": {
            "kind": "observed_introduction_outcomes",
            "dataset": "REPLACE_WITH_ACTUAL_EXPORT",
            "source_version": "REPLACE_WITH_ACTUAL_EXPORT_VERSION",
            "exported_at": datetime.now(UTC).isoformat(),
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (directory / "introductions.jsonl").touch(exist_ok=False)
    snapshot = {
        "schema_version": 1,
        "eligibility": "NEEDS_CLARIFICATION",
        "features": dict.fromkeys(FEATURE_NAMES),
    }
    (directory / "prediction_input.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Created empty training inputs in {directory}; real opt-in outcomes are still required")


def _fixture_identity(kind: str, group: str, index: int) -> str:
    attempt = 0
    while True:
        identity = f"fictional-{kind}-{group}-{index}-{attempt}"
        if identity_group(kind, identity, 42) == group:
            return identity
        attempt += 1


def demo(directory: Path) -> dict:
    """Generate clearly fictional software fixtures; never use NLS satisfaction as matches."""
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": 1,
        "target": TARGET,
        "feature_version": FEATURE_VERSION,
        "horizon_days": 14,
        "source": {
            "kind": "fictional_fixture",
            "dataset": "fictional_mutual_opt_in_software_fixture",
            "source_version": "fixture-v1",
            "exported_at": "2025-01-01T00:00:00Z",
        },
    }
    input_path, manifest_path = (
        directory / "fictional_introductions.jsonl",
        directory / "fictional_manifest.json",
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with input_path.open("w") as handle:
        for group, year in (("train", 2000), ("validation", 2010), ("test", 2020)):
            for index in range(60):
                signal = (index % 10) / 9
                features = dict.fromkeys(FEATURE_NAMES, signal)
                features["required_skill_coverage"] = 1.0
                features["relevant_experience_years"] = signal * 8
                positive = index % 10 >= 5
                exposed = f"{year}-01-01T00:00:00Z"
                response = f"{year}-01-02T00:00:00Z"
                second_issued = f"{year}-01-03T00:00:00Z"
                row = {
                    "cycle_id": f"fictional-{group}-{index}",
                    "candidate_id": _fixture_identity("candidate", group, index),
                    "vacancy_id": _fixture_identity("vacancy", group, index),
                    "organization_id": f"fictional-org-{group}-{index}",
                    "candidate_version": 1,
                    "vacancy_version": 1,
                    "feature_as_of": exposed,
                    "first_exposed_at": exposed,
                    "first_mover": "candidate",
                    "policy_version": "fictional-v1",
                    "eligibility": "ELIGIBLE",
                    "observation_status": "OBSERVABLE",
                    "observed_at": f"{year}-01-10T00:00:00Z",
                    "features": features,
                    "decisions": {
                        "candidate": {
                            "status": "INTERESTED" if positive else "PASSED",
                            "issued_at": exposed,
                            "answered_at": response,
                        },
                        "employer": {
                            "status": "INTERESTED" if positive else "NOT_ISSUED",
                            "issued_at": second_issued if positive else None,
                            "answered_at": f"{year}-01-04T00:00:00Z" if positive else None,
                        },
                    },
                }
                handle.write(json.dumps(row) + "\n")
    return train(
        input_path, manifest_path, directory / "evaluation", "2005-01-01T00:00:00Z", "2015-01-01T00:00:00Z"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "input")
    fixture = commands.add_parser("demo")
    fixture.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "fictional-demo")
    for name in ("validate", "train"):
        command = commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
        if name == "train":
            command.add_argument("--train-before", required=True)
            command.add_argument("--validate-before", required=True)
            command.add_argument("--output", type=Path, required=True)
    forecast = commands.add_parser("predict")
    forecast.add_argument("--model", type=Path, required=True)
    forecast.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.output)
    elif args.command == "demo":
        demo(args.output)
    elif args.command == "validate":
        _, diagnostics = load_records(args.input, json.loads(args.manifest.read_text()))
        print(json.dumps(diagnostics, indent=2))
    elif args.command == "train":
        train(args.input, args.manifest, args.output, args.train_before, args.validate_before)
    else:
        print(json.dumps(predict(args.model, json.loads(args.input.read_text())), indent=2))


if __name__ == "__main__":
    main()
