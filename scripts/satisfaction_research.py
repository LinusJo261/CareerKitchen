"""Offline reported-job-satisfaction experiment. Never used by the live matcher."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from scripts.joint_satisfaction_label import joint_satisfaction
from scripts.mutual_matching_features import FEATURE_NAMES as PAIR_FEATURE_NAMES
from scripts.mutual_matching_features import validate_features as validate_pair_features
from scripts.satisfaction_model import (
    TabularEncoder,
    classification_metrics,
    fit_majority_baseline,
    fit_model,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MAPPING = ROOT / "research" / "satisfaction_mapping.example.json"
DEFAULT_OUTPUT = ROOT / ".local" / "satisfaction-research"
NUMERIC_FEATURES = {
    "prior_experience_years",
    "offered_hourly_pay",
    "offered_hours_per_week",
    "weekly_hours_at_start",
} | set(PAIR_FEATURE_NAMES)
CATEGORICAL_FEATURES = {
    "job_role_family",
    "employment_type",
    "work_mode",
    "industry_at_start",
    "schedule_at_start",
}
COLUMNS = (
    "person_id",
    "employer_id",
    "job_started_at",
    "feature_as_of",
    "rating_reference_at",
    "rating_observed_at",
    "satisfaction",
)
LIMITATIONS = [
    "Employee-reported satisfaction in observed employment; not employer satisfaction or mutual interest.",
    "No causal claim about recommending jobs the respondent never held.",
    "Ordinal category steps do not establish equal satisfaction intervals.",
    "Date checks cannot verify that exported features truly describe prehire/start conditions; codebook review is required.",
    "Survey start-of-job conditions may be reported retrospectively alongside satisfaction; reference timing does not prove prospective availability.",
    "Month-resolution timelines and a declared follow-up window, not exact-day or universal 12-month outcomes.",
    "Missing satisfaction is excluded, never inferred from tenure or promotion; selection and survey nonresponse remain.",
    "No survey-weighted population estimates or complex-survey uncertainty corrections are implemented.",
    "Historical survey performance does not establish transport to Career Kitchen users or live recommendation quality.",
]
JOINT_TARGET = "joint_reported_satisfaction"
JOINT_LABEL_VERSION = "direct-paired-minimum-v1"
JOINT_PROVENANCE_COLUMNS = {
    "employee_reference_at",
    "manager_reference_at",
    "employee_observed_at",
    "manager_observed_at",
    "employee_response_id",
    "manager_response_id",
    "manager_rater_id",
}
JOINT_LIMITATIONS = [
    "Joint label is the lower of direct employee and direct manager ratings for the same employment spell and reference month.",
    "Minimum is a declared product policy, not a learned weighting or validated measure of overall match quality.",
    "The 0-100 score indexes five ordered categories; it is not a probability or a measured equal-interval satisfaction quantity.",
    "Missing ratings are excluded, never inferred from employee-only surveys, promotions, retention or model predictions.",
    "Only prehire/start features may be used; both ratings are outcomes, never predictors.",
    "Timestamps and source declarations cannot independently authenticate direct reports or consent.",
    "Complete paired responses may be selective; missing manager or employee responses can bias evaluation.",
    "Historical observed jobs do not establish causal satisfaction on unchosen jobs or mutual opt-in probabilities.",
    "Offline only; essential eligibility, consent and double opt-in remain separate backend responsibilities.",
]


def month(value: str) -> int:
    """Use true month resolution; do not invent interview days."""
    parts = value.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError("Dates must be YYYY-MM, using the actual survey month/year")
    year, number = map(int, parts)
    if not 1900 <= year <= 2200 or not 1 <= number <= 12:
        raise ValueError("Invalid survey month/year")
    return year * 12 + number - 1


def person_group(person_id: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{person_id}".encode()).hexdigest(), 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def validate_mapping(mapping: dict) -> None:
    if mapping.get("schema_version") != 1:
        raise ValueError("Unsupported mapping schema_version")
    source = mapping["source"]
    target = mapping.get("target", "reported_job_satisfaction")
    if target not in {"reported_job_satisfaction", JOINT_TARGET}:
        raise ValueError("Unsupported satisfaction target")
    if source["kind"] not in {"survey_export", "fictional_fixture", "paired_direct_ratings"}:
        raise ValueError("Declare survey_export, paired_direct_ratings or fictional_fixture source kind")
    if (source["kind"] == "paired_direct_ratings") != (target == JOINT_TARGET) and source[
        "kind"
    ] != "fictional_fixture":
        raise ValueError(
            "Joint targets require paired direct ratings; employee-only surveys cannot supply manager ratings"
        )
    if not all(
        isinstance(source.get(key), str) and source[key].strip() and "REPLACE" not in source[key]
        for key in ("dataset", "release", "codebook_url")
    ):
        raise ValueError("Set source dataset, release and codebook_url from the actual export")
    if set(mapping["columns"]) != set(COLUMNS):
        raise ValueError("Mapping must include every required identity, timing and label column")
    labels = mapping["label_order_worst_to_best"]
    if not isinstance(labels, list) or len(labels) < 2 or len(set(labels)) != len(labels):
        raise ValueError("Declare unique satisfaction labels ordered worst to best")
    if not all(isinstance(label, str) and label.strip() for label in labels):
        raise ValueError("Satisfaction labels must be nonempty strings")
    codes = mapping["label_codes"]
    if not codes or set(codes.values()) != set(labels):
        raise ValueError("label_codes must cover the declared satisfaction categories")
    if set(codes) & set(mapping["missing_codes"]):
        raise ValueError("Missing-response codes cannot also be satisfaction labels")
    numeric, categorical = mapping["features"]["numeric"], mapping["features"]["categorical"]
    if not set(numeric) <= NUMERIC_FEATURES or not set(categorical) <= CATEGORICAL_FEATURES:
        raise ValueError("Unsupported feature; IDs, demographics and posthire outcomes cannot be predictors")
    if not numeric and not categorical:
        raise ValueError("At least one prehire feature must be selected")
    selected = list(numeric.values()) + list(categorical.values())
    names = list(mapping["columns"].values()) + selected
    if target == JOINT_TARGET:
        joint = mapping.get("joint_label", {})
        if (
            set(joint) != {"version", "aggregation", "employee_rating_column", "manager_rating_column"}
            or joint["version"] != JOINT_LABEL_VERSION
            or joint["aggregation"] != "minimum"
        ):
            raise ValueError("Joint labels require the versioned direct-paired minimum policy")
        if labels != [f"joint_{index}" for index in range(5)] or codes != {
            str(index): f"joint_{index}" for index in range(5)
        }:
            raise ValueError("Joint labels must use normalized ordinal categories 0 through 4")
        names += [joint["employee_rating_column"], joint["manager_rating_column"]]
        if set(numeric) != set(PAIR_FEATURE_NAMES) or categorical:
            raise ValueError("Joint targets require the fixed ten structured pair features")
        names += list(JOINT_PROVENANCE_COLUMNS)
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(names) != len(set(names)):
        raise ValueError(
            "Source columns must be distinct nonempty names; label/identity/timing cannot be features"
        )
    declarations = mapping["feature_timing"]
    if set(declarations) != set(numeric) | set(categorical) or any(
        item != "prehire_or_job_start" for item in declarations.values()
    ):
        raise ValueError("Explicitly document prehire_or_job_start timing for every selected feature")
    minimum, maximum = mapping["followup_months"]["min"], mapping["followup_months"]["max"]
    if type(minimum) is not int or type(maximum) is not int or not 1 <= minimum <= maximum:
        raise ValueError("Choose a positive, ordered follow-up month window before training")


def load_records(input_path: Path, mapping: dict) -> tuple[list[dict], dict]:
    validate_mapping(mapping)
    missing = set(mapping["missing_codes"])
    columns = mapping["columns"]
    numeric, categorical = mapping["features"]["numeric"], mapping["features"]["categorical"]
    is_joint = mapping.get("target") == JOINT_TARGET
    excluded: Counter = Counter()
    records, seen = [], set()
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = set(columns.values()) | set(numeric.values()) | set(categorical.values())
        if is_joint:
            required.update(
                mapping["joint_label"][key] for key in ("employee_rating_column", "manager_rating_column")
            )
            required.update(JOINT_PROVENANCE_COLUMNS)
        if reader.fieldnames and len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("CSV has duplicate headers; export reference-number headers and review the join")
        if not required <= set(reader.fieldnames or []):
            raise ValueError(
                "CSV is missing mapped columns; use the export codebook to prepare a long-format CSV"
            )
        for number, raw in enumerate(reader, 2):
            if None in raw or any(raw.get(field) is None for field in required):
                raise ValueError(f"CSV row {number}: malformed field count")
            row = {key: (raw[value] or "").strip() for key, value in columns.items()}
            if row["satisfaction"] in missing:
                excluded["missing_satisfaction"] += 1
                continue
            if row["satisfaction"] not in mapping["label_codes"]:
                raise ValueError(f"CSV row {number}: unknown satisfaction code; review the codebook")
            paired = None
            if is_joint:
                ratings = [
                    (raw[mapping["joint_label"][key]] or "").strip()
                    for key in ("employee_rating_column", "manager_rating_column")
                ]
                if any(rating not in {str(index) for index in range(5)} for rating in ratings):
                    raise ValueError(
                        "A joint target requires both normalized direct ratings, never an inferred manager rating"
                    )
                paired = joint_satisfaction(*(int(rating) for rating in ratings))
                if row["satisfaction"] != str(int(paired["joint_rating"])):
                    raise ValueError("Joint target disagrees with the lower direct rating")
            if any(row[field] in missing for field in COLUMNS if field != "satisfaction"):
                excluded["missing_identity_or_timing"] += 1
                continue
            dates = {
                field: month(row[field])
                for field in (
                    "job_started_at",
                    "feature_as_of",
                    "rating_reference_at",
                    "rating_observed_at",
                )
            }
            if is_joint:
                source_dates = {
                    key: month((raw[key] or "").strip())
                    for key in (
                        "employee_reference_at",
                        "manager_reference_at",
                        "employee_observed_at",
                        "manager_observed_at",
                    )
                }
                if (
                    source_dates["employee_reference_at"] != dates["rating_reference_at"]
                    or source_dates["manager_reference_at"] != dates["rating_reference_at"]
                    or any(
                        source_dates[f"{side}_observed_at"] < dates["rating_reference_at"]
                        for side in ("employee", "manager")
                    )
                    or max(source_dates["employee_observed_at"], source_dates["manager_observed_at"])
                    != dates["rating_observed_at"]
                ):
                    raise ValueError(
                        "Joint timing must preserve both reference periods and the later response observation"
                    )
                if any(
                    not (raw[key] or "").strip()
                    for key in (
                        "employee_response_id",
                        "manager_response_id",
                        "manager_rater_id",
                    )
                ):
                    raise ValueError("Joint labels require both response IDs and direct manager provenance")
            if dates["feature_as_of"] > dates["job_started_at"]:
                raise ValueError(f"CSV row {number}: posthire feature leakage; use prehire/start variables")
            if not dates["job_started_at"] < dates["rating_reference_at"] <= dates["rating_observed_at"]:
                raise ValueError(f"CSV row {number}: invalid outcome reference/observation timeline")
            followup = dates["rating_reference_at"] - dates["job_started_at"]
            if not mapping["followup_months"]["min"] <= followup <= mapping["followup_months"]["max"]:
                excluded["outside_followup_window"] += 1
                continue
            identity = (
                row["person_id"],
                row["employer_id"],
                dates["job_started_at"],
                dates["rating_observed_at"],
            )
            if identity in seen:
                raise ValueError(
                    "Duplicate respondent/employer/start/observation record; check the wide-to-long join"
                )
            seen.add(identity)
            values: dict[str, float | str | None] = {}
            for name, source in numeric.items():
                value = (raw[source] or "").strip()
                numeric_value = None if value in missing else float(value)
                values[name] = numeric_value
                if numeric_value is not None and (not np.isfinite(numeric_value) or numeric_value < 0):
                    raise ValueError(f"CSV row {number}: invalid nonnegative start-of-job numeric feature")
            for name, source in categorical.items():
                value = (raw[source] or "").strip()
                values[name] = None if value in missing else value
            if is_joint:
                values = dict(validate_pair_features(values))
            records.append(
                {
                    "person_id": row["person_id"],
                    "employer_id": row["employer_id"],
                    **dates,
                    "features": values,
                    "followup_months": followup,
                    "label": mapping["label_order_worst_to_best"].index(
                        mapping["label_codes"][row["satisfaction"]]
                    ),
                    **(
                        {
                            "employee_rating": paired["employee_rating"],
                            "manager_rating": paired["manager_rating"],
                            "joint_score": paired["joint_score"],
                        }
                        if paired
                        else {}
                    ),
                }
            )
    # One outcome per employment spell: first observed eligible rating, never
    # cherry-pick the happiest rating. Returning to the same employer is a new spell.
    spells = {}
    for row in sorted(records, key=lambda item: (item["rating_observed_at"], item["rating_reference_at"])):
        key = (row["person_id"], row["employer_id"], row["job_started_at"])
        if key in spells:
            excluded["later_rating_same_spell"] += 1
        else:
            spells[key] = row
    records = list(spells.values())
    if not records:
        raise ValueError("No usable satisfaction observations after missingness and follow-up checks")
    return records, {
        "usable_spells": len(records),
        "excluded": dict(excluded),
        "people": len({row["person_id"] for row in records}),
        "label_counts": dict(Counter(mapping["label_order_worst_to_best"][row["label"]] for row in records)),
        "mean_followup_months": float(np.mean([row["followup_months"] for row in records])),
    }


def split_records(
    records: list[dict],
    seed: int,
    train_before: str | None = None,
    validate_before: str | None = None,
    policy: str = "grouped-temporal",
) -> tuple[dict, dict]:
    if policy not in {"grouped-temporal", "grouped-pilot"}:
        raise ValueError("Unknown evaluation split policy")
    if policy == "grouped-pilot":
        if train_before is not None or validate_before is not None:
            raise ValueError("Grouped pilot evaluation does not use temporal cutoffs")
        first = second = None
    else:
        if not train_before or not validate_before:
            raise ValueError("Temporal evaluation requires train-before and validate-before cutoffs")
        first, second = month(train_before), month(validate_before)
        if first >= second:
            raise ValueError("train-before must precede validate-before")
    groups: dict[str, list] = {"train": [], "validation": [], "test": []}
    excluded = 0
    for row in records:
        group = person_group(row["person_id"], seed)
        if policy == "grouped-pilot":
            groups[group].append(row)
        elif group == "train" and row["rating_observed_at"] < first:
            groups[group].append(row)
        elif group == "validation" and row["job_started_at"] >= first and row["rating_observed_at"] < second:
            groups[group].append(row)
        elif group == "test" and row["job_started_at"] >= second:
            groups[group].append(row)
        else:
            excluded += 1
    if any(not value for value in groups.values()):
        raise ValueError(
            "An evaluation split is empty; select more people/rounds or review the declared date cutoffs"
        )
    diagnostics = {
        "policy": (
            "person-disjoint hash groups intersected with forward-time cohorts; unused rows are excluded"
            if policy == "grouped-temporal"
            else "person-disjoint pilot holdout; no forward-time evaluation"
        ),
        "split_policy": policy,
        "seed": seed,
        "train_before": train_before,
        "validate_before": validate_before,
        "outside_group_time_cohort": excluded,
        "split_counts": {name: len(rows) for name, rows in groups.items()},
        "person_counts": {name: len({row["person_id"] for row in rows}) for name, rows in groups.items()},
    }
    return groups, diagnostics


def train(
    input_path: Path,
    mapping_path: Path,
    output: Path,
    train_before: str | None = None,
    validate_before: str | None = None,
    seed: int = 42,
    epochs: int = 500,
    l2: float = 0.01,
    split_policy: str = "grouped-temporal",
) -> dict:
    mapping = json.loads(mapping_path.read_text())
    target = mapping.get("target", "reported_job_satisfaction")
    is_joint = target == JOINT_TARGET
    if split_policy == "grouped-pilot" and not is_joint:
        raise ValueError("Grouped pilot mode is available only for direct joint satisfaction labels")
    records, diagnostics = load_records(input_path, mapping)
    groups, split_diagnostics = split_records(
        records, seed, train_before, validate_before, policy=split_policy
    )
    numeric, categorical = mapping["features"]["numeric"], mapping["features"]["categorical"]
    unused = []
    if is_joint:
        unused = [name for name in numeric if all(row["features"][name] is None for row in groups["train"])]
        numeric = {name: source for name, source in numeric.items() if name not in unused}
    encoder = TabularEncoder.fit(
        [row["features"] for row in groups["train"]], list(numeric), list(categorical)
    )
    xs = {name: encoder.transform([row["features"] for row in rows]) for name, rows in groups.items()}
    ys = {name: np.array([row["label"] for row in rows]) for name, rows in groups.items()}
    labels = mapping["label_order_worst_to_best"]
    diagnostics["label_counts_by_split"] = {
        name: {label: int(np.count_nonzero(ys[name] == index)) for index, label in enumerate(labels)}
        for name in groups
    }
    diagnostics["classes_missing_from_training"] = [
        label for index, label in enumerate(labels) if not np.any(ys["train"] == index)
    ]
    model = fit_model(xs["train"], ys["train"], encoder.feature_names, labels, l2=l2, epochs=epochs)
    baseline = fit_majority_baseline(ys["train"], len(labels))
    evaluation = {}
    for name in ("validation", "test"):
        evaluation[name] = {
            "model": classification_metrics(ys[name], model.predict_proba(xs[name])),
            "training_distribution_baseline": classification_metrics(
                ys[name], np.tile(baseline, (len(ys[name]), 1))
            ),
        }
    provenance = {
        "source": mapping["source"],
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
        "followup_months": mapping["followup_months"],
        "split": split_diagnostics,
        "epochs": epochs,
        "l2": l2,
        **({"joint_label": mapping["joint_label"]} if is_joint else {}),
    }
    fictional = mapping["source"]["kind"] == "fictional_fixture"
    report = {
        "schema_version": 1,
        "target": target,
        "live_execution": False,
        "class_order_worst_to_best": labels,
        "fictional_data": fictional,
        "provenance": provenance,
        "data_quality": diagnostics,
        "evaluation": evaluation,
        "limitations": (JOINT_LIMITATIONS if is_joint else LIMITATIONS)
        + (
            [
                "Grouped pilot holdouts do not establish forward-time performance; employers may overlap between folds."
            ]
            if split_policy == "grouped-pilot"
            else []
        )
        + (
            ["FICTIONAL FIXTURE: scores validate software only, not survey or hiring performance."]
            if fictional
            else []
        ),
        **(
            {
                "joint_label": mapping["joint_label"],
                "joint_score_by_class": [0, 25, 50, 75, 100],
                "unobserved_training_features": unused,
            }
            if is_joint
            else {}
        ),
    }
    output.mkdir(parents=True, exist_ok=not is_joint)
    prefix = "fictional_" if fictional else "paired_" if is_joint else "survey_"
    artifact_name = "joint_satisfaction" if is_joint else "satisfaction"
    model_data = model.to_dict()
    if is_joint:
        model_data.update(
            target=target, joint_label=mapping["joint_label"], joint_score_by_class=[0, 25, 50, 75, 100]
        )
    (output / f"{prefix}{artifact_name}_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    artifact = {
        "schema_version": 1,
        "live_execution": False,
        "fictional_data": fictional,
        "model": model_data,
        "encoder": encoder.to_dict(),
        "provenance": provenance,
        "limitations": report["limitations"],
    }
    (output / f"{prefix}{artifact_name}_model.json").write_text(
        json.dumps(artifact, indent=2, allow_nan=False) + "\n"
    )
    print(
        "FICTIONAL SOFTWARE DEMO ONLY"
        if fictional
        else (
            "OBSERVED DIRECT PAIRED SATISFACTION — OFFLINE ONLY"
            if is_joint
            else "OBSERVATIONAL SURVEY EXPERIMENT — OFFLINE ONLY"
        )
    )
    for name, metrics in evaluation.items():
        actual, simple = metrics["model"], metrics["training_distribution_baseline"]
        print(
            f"{name}: {actual['count']} observations; model accuracy={actual['accuracy']:.1%}, "
            f"majority baseline={simple['accuracy']:.1%}; ordinal MAE={actual['ordinal_mae']:.3f}"
        )
    print(f"Artifacts: {output / (prefix + artifact_name + '_report.json')}")
    return report


def initialize(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(EXAMPLE_MAPPING.read_text())
    fields = (
        list(mapping["columns"].values())
        + list(mapping["features"]["numeric"].values())
        + list(mapping["features"]["categorical"].values())
    )
    # Exclusive creation protects a user's existing mapping/export.
    for path in (directory / "mapping.json", directory / "observations.csv"):
        if path.exists():
            raise ValueError("Input template already exists; choose a new directory")
    with (directory / "mapping.json").open("x") as handle:
        handle.write(json.dumps(mapping, indent=2) + "\n")
    with (directory / "observations.csv").open("x", newline="") as handle:
        csv.writer(handle).writerow(fields)
    print(
        f"Created empty CSV and mapping template in {directory}. Read docs/satisfaction-research.md before populating."
    )


def demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(EXAMPLE_MAPPING.read_text())
    mapping["source"] = {
        "kind": "fictional_fixture",
        "dataset": "fictional_software_fixture",
        "release": "fixture-v1",
        "codebook_url": "fixture://not-a-survey",
    }
    path = directory / "fictional_observations.csv"
    fields = (
        list(mapping["columns"].values())
        + list(mapping["features"]["numeric"].values())
        + list(mapping["features"]["categorical"].values())
    )
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(300):
            person = f"fictional-person-{index}"
            group = person_group(person, 42)
            year = {"train": 2000, "validation": 2010, "test": 2020}[group]
            category = index % 5
            writer.writerow(
                {
                    "person_id": person,
                    "employer_id": f"fictional-employer-{index % 8}",
                    "job_started_at": f"{year}-01",
                    "feature_as_of": f"{year}-01",
                    "rating_reference_at": f"{year}-07",
                    "rating_observed_at": f"{year}-07",
                    "satisfaction": str(5 - category),
                    "prior_experience_years": category * 3,
                    "offered_hours_per_week": 20 + category * 5,
                    "employment_type": "FULL_TIME",
                }
            )
    config = directory / "fictional_mapping.json"
    config.write_text(json.dumps(mapping, indent=2) + "\n")
    return train(path, config, directory, "2005-01", "2015-01")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "validate", "train", "demo"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-before", help="YYYY-MM: training labels must be observed before this month")
    parser.add_argument(
        "--validate-before", help="YYYY-MM: validation labels known before this month; test jobs start after"
    )
    parser.add_argument(
        "--split-policy",
        choices=("grouped-temporal", "grouped-pilot"),
        default="grouped-temporal",
        help="Joint pilot mode separates people without asserting a forward-time evaluation",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.output / "input")
        elif args.command == "demo":
            demo(args.output / "fictional-demo")
        else:
            if not args.input or not args.mapping:
                parser.error("--input and --mapping are required")
            if args.command == "validate":
                records, diagnostics = load_records(args.input, json.loads(args.mapping.read_text()))
                print(json.dumps(diagnostics, indent=2))
            else:
                if args.split_policy == "grouped-temporal" and (
                    not args.train_before or not args.validate_before
                ):
                    parser.error("Declare --train-before and --validate-before month cutoffs")
                train(
                    args.input,
                    args.mapping,
                    args.output,
                    args.train_before,
                    args.validate_before,
                    args.seed,
                    args.epochs,
                    args.l2,
                    split_policy=args.split_policy,
                )
    except (ValueError, KeyError, FileNotFoundError) as exc:
        parser.exit(1, f"Satisfaction research stopped: {exc}\n")


if __name__ == "__main__":
    main()
