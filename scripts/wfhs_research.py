"""Offline WFHS baseline-to-12-month employee satisfaction research.

This deliberately does not use the prehire satisfaction importer: WFHS baseline
means study entry for already-employed people, not the start of their job.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from scripts.satisfaction_model import TabularEncoder
from scripts.wfhs_model import fit_ridge, regression_metrics

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / ".local/satisfaction-research/raw/WFHS_Data"
DEFAULT_DATASET = "tomo"
DATASETS = {
    "tomo": ("DS0001/36158-0001-Data.tsv", "STUDYGROUP"),
    "leef": ("DS0002/36158-0002-Data.tsv", "LF_CENTERID"),
}
FEATURES = {
    "control_over_work_hours": "SCWM_CWH",
    "family_supportive_supervisor": "SCWM_FSSB",
    "decision_authority": "SCWM_JSTRDA",
    "psychological_job_demands": "SCWM_JSTRPJD",
    "hours_worked_last_week": "WM_HPQ1",
    "hours_expected_by_manager": "WM_HPQ2R",
}
LABEL = "SCWM_JSAT"
LABEL_ITEMS = ("WM_JSAT1R", "WM_JSAT2R", "WM_JSAT3R")
ALPHAS = (0.0, 0.001, 0.01, 0.1, 1.0)
LIMITATIONS = [
    "Research only; never loaded by the API, worker, or live matcher.",
    "Baseline is study entry for existing employees, not job start or prehire information.",
    "Target is the employee's 12-month reported satisfaction scale, not employer satisfaction, mutual interest, or hiring success.",
    "The three-item questionnaire mean is modeled in reported scale units; equal increments of human satisfaction are not established.",
    "Only paired baseline/follow-up respondents are observed; attrition and survey nonresponse may bias results.",
    "Both intervention and usual-practice conditions are included; this is prediction, not a causal intervention analysis.",
    "Held-out baseline work groups/facilities remain within one employer; this is not evidence about unseen employers or future hiring cohorts.",
    "No survey-weighted population inference or cluster-level uncertainty intervals are implemented.",
    "The outputs are scale predictions, not calibrated match probabilities or a joint employee/manager satisfaction target.",
    "No matching of WFHS people to synthetic resumes, no Model A combination, and no invented preferences or manager ratings.",
]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(raw: str, field: str) -> float | None:
    """Validate selected columns using their documented scale/hour domains."""
    value = raw.strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid numeric value in {field}") from exc
    if not np.isfinite(number):
        raise ValueError(f"Nonfinite value in {field}")
    hours = field in {"WM_HPQ1", "WM_HPQ2", "WM_HPQ2R"}
    missing = {-4.0, -7.0} if hours or field in LABEL_ITEMS else {-8.0}
    if number in missing:
        return None
    low, high = (0, 168) if hours else (1, 5)
    if not low <= number <= high:
        raise ValueError(f"Out-of-range value in {field}; review the source codebook")
    if field in LABEL_ITEMS and number != int(number):
        raise ValueError("Satisfaction item responses must be integer categories")
    if field == LABEL and not np.isclose(number * 3, round(number * 3), atol=1e-8, rtol=0):
        raise ValueError("SCWM_JSAT must retain its three-item mean, without rounding")
    return number


def _satisfaction(row: dict) -> float | None:
    scale = _number(row[LABEL], LABEL)
    items = [_number(row[field], field) for field in LABEL_ITEMS]
    if scale is not None and (
        any(value is None for value in items) or not np.isclose(scale, np.mean(items), atol=1e-8, rtol=0)
    ):
        raise ValueError("SCWM_JSAT disagrees with its three reverse-coded items")
    return scale


def prepare_dataset(raw_dir: Path, dataset: str) -> tuple[list[dict], dict]:
    if dataset not in DATASETS:
        raise ValueError("Choose tomo or leef")
    relative, cluster_column = DATASETS[dataset]
    source = raw_dir / relative
    required = {
        "ADMINLINK",
        "WAVE",
        "EMPLOYEE",
        "MANAGER",
        "CONDITION",
        cluster_column,
        LABEL,
        *LABEL_ITEMS,
        *FEATURES.values(),
    }
    if dataset == "tomo":
        required.add("EXCLUDE")
    by_person: dict[str, dict[int, dict]] = {}
    wave_counts: Counter = Counter()
    employee_counts: Counter = Counter()
    rows = 0
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not required <= set(headers):
            raise ValueError("WFHS TSV needs distinct headers and the documented source columns")
        for raw in reader:
            rows += 1
            if None in raw or any(raw.get(field) is None for field in required):
                raise ValueError("Malformed WFHS TSV field count")
            row = {key: value.strip() for key, value in raw.items()}
            person, wave = row["ADMINLINK"], row["WAVE"]
            if not person or wave not in {"1", "2", "3", "4"}:
                raise ValueError("WFHS needs a participant ID and a documented wave from 1 through 4")
            if row["EMPLOYEE"] not in {"0", "1"} or row["MANAGER"] not in {"0", "1"}:
                raise ValueError("Employee/manager flags must be zero or one")
            if row["EMPLOYEE"] == row["MANAGER"]:
                raise ValueError("Ambiguous employee/manager respondent status")
            observations = by_person.setdefault(person, {})
            if int(wave) in observations:
                raise ValueError("Duplicate participant/wave; exact longitudinal joins are required")
            observations[int(wave)] = row
            wave_counts[wave] += 1
            if row["EMPLOYEE"] == "1":
                employee_counts[wave] += 1

    exclusions: Counter = Counter()
    missing_features: Counter = Counter()
    records = []
    group_changes = 0
    flags: Counter = Counter()
    for person, waves in sorted(by_person.items()):
        baseline = waves.get(1)
        followup = waves.get(3)
        if baseline is None or baseline["EMPLOYEE"] != "1":
            exclusions["not_baseline_employee"] += 1
            continue
        if dataset == "tomo":
            excluded = baseline["EXCLUDE"]
            if excluded not in {"", "1", "2"}:
                raise ValueError("Unknown Tomo main-study exclusion flag")
            if excluded:
                exclusions["tomo_not_invited" if excluded == "1" else "tomo_not_randomized"] += 1
                continue
        if followup is None:
            exclusions["missing_12_month_observation"] += 1
            continue
        if followup["EMPLOYEE"] != "1":
            exclusions["not_employee_at_followup"] += 1
            continue
        baseline_satisfaction, outcome = _satisfaction(baseline), _satisfaction(followup)
        if outcome is None:
            exclusions["missing_12_month_satisfaction"] += 1
            continue
        if baseline_satisfaction is None:
            exclusions["missing_baseline_satisfaction_for_persistence_comparison"] += 1
            continue
        cluster = baseline[cluster_column]
        if not cluster or not cluster.isdigit() or int(cluster) <= 0:
            raise ValueError("A positive documented baseline work group/facility is required")
        if baseline["CONDITION"] not in {"1", "2"}:
            raise ValueError("Unknown study condition")
        group_changes += followup[cluster_column] != cluster
        flags[baseline.get("EXCLUDE", "") or "unflagged"] += 1
        values = {name: _number(baseline[column], column) for name, column in FEATURES.items()}
        if all(value is None for value in values.values()):
            exclusions["all_baseline_features_missing"] += 1
            continue
        missing_features.update(name for name, value in values.items() if value is None)
        records.append(
            {
                "person_id": f"{dataset}:{person}",
                "baseline_cluster": f"{dataset}:{cluster}",
                "condition": baseline["CONDITION"],
                "baseline_wave": 1,
                "outcome_wave": 3,
                "baseline_satisfaction": baseline_satisfaction,
                "followup_satisfaction": outcome,
                "features": values,
            }
        )
    if not records:
        raise ValueError("No usable baseline-to-12-month employee observations")
    return records, {
        "schema_version": 1,
        "dataset": dataset,
        "source_relative_path": relative,
        "source_sha256": _hash(source),
        "source_rows": rows,
        "source_columns": len(headers),
        "source_people": len(by_person),
        "wave_row_counts": dict(wave_counts),
        "employee_wave_counts": dict(employee_counts),
        "usable_employee_pairs": len(records),
        "baseline_clusters": len({row["baseline_cluster"] for row in records}),
        "exclusions": dict(exclusions),
        "baseline_feature_missing_counts": dict(missing_features),
        "changed_cluster_at_followup": group_changes,
        "baseline_exclude_flag_counts": dict(flags),
        "feature_sources": FEATURES,
        "target_column": LABEL,
        "target_definition": "12-month employee-reported mean of WM_JSAT1R, WM_JSAT2R, WM_JSAT3R",
        "target_bounds": [1, 5],
        "target_higher_is_better": True,
        "target_scale": "fractional_three_item_questionnaire_mean_not_five_integer_classes",
        "baseline_satisfaction_usage": "persistence_baseline_only_not_a_model_feature",
        "baseline_wave": 1,
        "outcome_wave": 3,
        "nominal_followup_months": 12,
        "cluster_column": cluster_column,
        "live_execution": False,
        "fictional_data": False,
        "tomo_exclusion_policy": "omit EXCLUDE=1 (not invited) or 2 (not randomized) at baseline",
        "expected_hours_source": "baseline WM_HPQ2R incorporates the documented data-entry correction",
        "limitations": LIMITATIONS,
    }


def cluster_partition(cluster: str, seed: int = 42) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{cluster}".encode()).hexdigest(), 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def split_records(records: list[dict], seed: int = 42) -> tuple[dict, dict]:
    groups: dict[str, list] = {name: [] for name in ("train", "validation", "test")}
    seen = set()
    for row in records:
        if row["person_id"] in seen:
            raise ValueError("Each employee must have exactly one baseline/follow-up pair")
        seen.add(row["person_id"])
        groups[cluster_partition(row["baseline_cluster"], seed)].append(row)
    if any(not rows for rows in groups.values()):
        raise ValueError(
            "All cluster-held-out splits need observations; do not tune the seed to improve results"
        )
    summary = {
        "policy": "baseline_cluster_hash_70_15_15",
        "seed": seed,
        "split_counts": {name: len(rows) for name, rows in groups.items()},
        "cluster_counts": {
            name: len({row["baseline_cluster"] for row in rows}) for name, rows in groups.items()
        },
        "participant_overlap": False,
        "baseline_cluster_overlap": False,
        "calendar_time_holdout": False,
        "unseen_employer_holdout": False,
    }
    return groups, summary


def train_dataset(records: list[dict], audit: dict, seed: int = 42) -> tuple[dict, dict]:
    groups, split = split_records(records, seed)
    feature_rows = {name: [row["features"] for row in rows] for name, rows in groups.items()}
    encoder = TabularEncoder.fit(feature_rows["train"], list(FEATURES), [])
    x = {name: encoder.transform(rows) for name, rows in feature_rows.items()}
    y = {name: np.asarray([row["followup_satisfaction"] for row in rows]) for name, rows in groups.items()}
    if len(np.unique(y["train"])) < 2:
        raise ValueError("Training needs at least two observed satisfaction values")
    candidates: list[dict[str, Any]] = []
    models = {}
    for alpha in ALPHAS:
        model = fit_ridge(x["train"], y["train"], encoder.feature_names, l2=alpha)
        models[alpha] = model
        candidates.append(
            {"l2": alpha, "validation": regression_metrics(y["validation"], model.predict(x["validation"]))}
        )
    chosen = min(candidates, key=lambda item: (item["validation"]["rmse"], -item["l2"]))
    model = models[chosen["l2"]]
    train_mean, train_median = float(np.mean(y["train"])), float(np.median(y["train"]))
    evaluation = {}
    for name in ("validation", "test"):
        predictions = model.predict(x[name])
        persistence = np.asarray([row["baseline_satisfaction"] for row in groups[name]])
        evaluation[name] = {
            "model": regression_metrics(y[name], predictions),
            "training_mean_baseline": regression_metrics(y[name], np.full(len(y[name]), train_mean)),
            "training_median_baseline": regression_metrics(y[name], np.full(len(y[name]), train_median)),
            "baseline_satisfaction_persistence": regression_metrics(y[name], persistence),
            "by_study_condition": {
                condition: regression_metrics(y[name][mask], predictions[mask])
                for condition in ("1", "2")
                if np.any(mask := np.asarray([row["condition"] == condition for row in groups[name]]))
            },
        }
    metadata = {
        "schema_version": 1,
        "dataset": audit["dataset"],
        "live_execution": False,
        "fictional_data": False,
        "target": "employee_reported_satisfaction_scale_at_12_months",
        "feature_timing": "baseline_for_existing_employees_not_prehire",
        "source_sha256": audit["source_sha256"],
        "nominal_followup_months": 12,
        "limitations": LIMITATIONS,
    }
    artifact = {
        **metadata,
        "encoder": encoder.to_dict(),
        "model": model.to_dict(),
        "selected_l2": chosen["l2"],
        "split": split,
    }
    report = {
        **metadata,
        "preparation": audit,
        "split": split,
        "training_count": len(y["train"]),
        "training_target_mean": train_mean,
        "training_target_median": train_median,
        "hyperparameter_selection": {
            "criterion": "validation_rmse",
            "candidates": candidates,
            "selected_l2": chosen["l2"],
            "test_used_for_selection": False,
        },
        "evaluation": evaluation,
        "output": "predicted_questionnaire_scale_value_1_to_5_not_match_probability",
    }
    return artifact, report


def _json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(raw_dir: Path, output: Path, datasets: list[str], *, train: bool = False, seed: int = 42) -> dict:
    if output.exists():
        raise ValueError("Output already exists; choose a new directory to preserve previous research runs")
    if not datasets or len(set(datasets)) != len(datasets) or not set(datasets) <= set(DATASETS):
        raise ValueError("Choose distinct documented WFHS datasets")
    documents = ("36158-Codebook.pdf", "36158-User_guide.pdf", "TermsOfUse.html")
    for name in documents:
        if not (raw_dir / name).is_file():
            raise ValueError("Keep the supplied WFHS codebook, user guide and terms beside the data")
    manifest = {
        "schema_version": 1,
        "study": "ICPSR 36158 v2",
        "doi": "10.3886/ICPSR36158.v2",
        "datasets": datasets,
        "command": "train" if train else "prepare",
        "seed": seed,
        "document_sha256": {name: _hash(raw_dir / name) for name in documents},
        "live_execution": False,
        "fictional_data": False,
        "data_usage": "local research/statistical analysis; source data are not redistributed",
    }
    results = {}
    # Prepare and validate every dataset before publishing any outputs.
    prepared = {name: prepare_dataset(raw_dir, name) for name in datasets}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".wfhs-staging-", dir=output.parent) as temporary:
        staged = Path(temporary) / "results"
        staged.mkdir()
        for name, (records, audit) in prepared.items():
            destination = staged / name
            destination.mkdir()
            columns = [
                "person_id",
                "baseline_cluster",
                "condition",
                "baseline_wave",
                "outcome_wave",
                "baseline_satisfaction",
                "followup_satisfaction",
                *FEATURES,
            ]
            with (destination / "observations.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                writer.writerows(
                    {**{key: row[key] for key in columns if key not in FEATURES}, **row["features"]}
                    for row in records
                )
            _json(destination / "preparation_report.json", audit)
            if train:
                artifact, report = train_dataset(records, audit, seed)
                _json(destination / "model.json", artifact)
                _json(destination / "report.json", report)
                results[name] = report
            else:
                results[name] = audit
        _json(staged / "manifest.json", manifest)
        if output.exists():
            raise ValueError("Output appeared during preparation; refusing to replace it")
        staged.rename(output)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "train"))
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument(
        "--dataset",
        choices=("tomo", "leef", "both"),
        default=DEFAULT_DATASET,
        help="Dataset for this research run (default: tomo, the selected Model B population)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    names = list(DATASETS) if args.dataset == "both" else [args.dataset]
    try:
        results = run(args.raw_dir, args.output, names, train=args.command == "train", seed=args.seed)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"WFHS research: {exc}\n")
    for name, report in results.items():
        audit = report.get("preparation", report)
        print(f"{name}: {audit['usable_employee_pairs']} baseline-to-12-month employee pairs")
        if args.command == "train":
            metrics = report["evaluation"]["test"]
            print(
                f"  Test MAE: {metrics['model']['mae']:.3f}; training-mean baseline: "
                f"{metrics['training_mean_baseline']['mae']:.3f}; persistence: "
                f"{metrics['baseline_satisfaction_persistence']['mae']:.3f}"
            )
    print(f"Artifacts: {args.output}")


if __name__ == "__main__":
    main()
