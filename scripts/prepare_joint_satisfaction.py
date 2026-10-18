"""Prepare direct, paired satisfaction outcomes for offline training only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from scripts.joint_satisfaction_label import joint_satisfaction
from scripts.mutual_matching_features import FEATURE_NAMES, validate_features
from scripts.satisfaction_research import JOINT_TARGET, month, validate_mapping

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MAPPING = ROOT / "research" / "joint_satisfaction_mapping.example.json"
DEFAULT_OUTPUT = ROOT / ".local" / "joint-satisfaction"
ROW_KEYS = {
    "person_id",
    "employer_id",
    "job_started_at",
    "feature_as_of",
    "features",
    "employee_rating",
    "manager_rating",
}
RATING_KEYS = {
    "response_id",
    "person_id",
    "employer_id",
    "job_started_at",
    "reference_at",
    "observed_at",
    "value",
    "kind",
}
FIELDS = (
    "person_id",
    "employer_id",
    "job_started_at",
    "feature_as_of",
    "rating_reference_at",
    "rating_observed_at",
    "joint_rating",
    *FEATURE_NAMES,
    "employee_rating",
    "manager_rating",
    "joint_score",
    "label_status",
    "employee_raw_value",
    "manager_raw_value",
    "employee_reference_at",
    "manager_reference_at",
    "employee_observed_at",
    "manager_observed_at",
    "employee_response_id",
    "manager_response_id",
    "manager_rater_id",
)


def validate_preparation_mapping(mapping: dict) -> None:
    validate_mapping(mapping)
    if mapping.get("target") != JOINT_TARGET:
        raise ValueError("Preparation requires the joint direct-satisfaction target")
    collection = mapping.get("rating_collection", {})
    if set(collection) != {"employee_codes_worst_to_best", "manager_codes_worst_to_best", "reference_period"}:
        raise ValueError("Declare both rating scales and the reference period")
    if collection["reference_period"] != "same_month":
        raise ValueError("Both direct ratings must concern the same reference month")
    for side in ("employee", "manager"):
        codes = collection[f"{side}_codes_worst_to_best"]
        if (
            not isinstance(codes, list)
            or len(codes) != 5
            or any(not isinstance(code, str) or not code.strip() for code in codes)
            or len(set(codes)) != 5
            or set(codes) & set(mapping["missing_codes"])
        ):
            raise ValueError("Declare five distinct raw rating codes ordered worst to best")
    # The prepared output has a fixed schema. Custom raw-code scales are supported;
    # renaming outcomes into predictors or selecting arbitrary columns is not.
    example = json.loads(EXAMPLE_MAPPING.read_text())
    for key in ("columns", "features", "feature_timing", "joint_label"):
        if mapping[key] != example[key]:
            raise ValueError("Joint preparation uses the fixed outcome and pair-feature column contract")


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty pseudonymous identifier")
    return value


def _rating(raw: dict | None, side: str, row: dict, mapping: dict) -> dict:
    if raw is None:
        return {"value": None}
    required = RATING_KEYS | ({"rater_id"} if side == "manager" else set())
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError(f"{side} rating must include exactly its direct-response identity and timing fields")
    if raw["kind"] != f"direct_{side}_report":
        raise ValueError("Only direct employee and direct manager reports can define this joint target")
    _identity(raw["response_id"], "response_id")
    if side == "manager":
        _identity(raw["rater_id"], "manager rater_id")
    for key in ("person_id", "employer_id", "job_started_at"):
        if raw[key] != row[key]:
            raise ValueError(
                "Employee and manager ratings must identify the same person, employer and job start"
            )
    reference, observed = month(raw["reference_at"]), month(raw["observed_at"])
    if not month(row["job_started_at"]) < reference <= observed:
        raise ValueError("Direct rating reference must follow job start and precede observation")
    value = raw["value"]
    if isinstance(value, bool) or value is not None and type(value) not in (int, str):
        raise ValueError("Raw direct ratings must use an explicitly mapped integer or string code")
    code = "" if value is None else str(value)
    if code in mapping["missing_codes"]:
        normalized = None
    else:
        codes = mapping["rating_collection"][f"{side}_codes_worst_to_best"]
        if code not in codes:
            raise ValueError("Unknown direct rating code; review its declared instrument scale")
        normalized = codes.index(code)
    return {**raw, "raw_value": code, "value": normalized, "reference": reference, "observed": observed}


def prepare(input_path: Path, mapping_path: Path, output: Path) -> dict:
    mapping = json.loads(mapping_path.read_text())
    validate_preparation_mapping(mapping)
    if output.exists():
        raise FileExistsError(
            "Choose a new prepared directory; existing raw data and experiments are preserved"
        )
    rows, seen_responses, seen_periods = [], set(), set()
    statuses: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    source_rows = 0
    with input_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            source_rows += 1
            raw = json.loads(line)
            if not isinstance(raw, dict) or set(raw) != ROW_KEYS:
                raise ValueError(
                    "Use exactly the documented employment-spell, feature and paired-rating fields"
                )
            for key in ("person_id", "employer_id"):
                _identity(raw[key], key)
            started, cutoff = month(raw["job_started_at"]), month(raw["feature_as_of"])
            if cutoff > started:
                raise ValueError("Posthire feature leakage: inputs must be frozen before or at job start")
            features = validate_features(raw["features"])
            ratings = {
                side: _rating(raw[f"{side}_rating"], side, raw, mapping) for side in ("employee", "manager")
            }
            for side, rating in ratings.items():
                if "response_id" not in rating:
                    continue
                response_identity = side, rating["response_id"]
                if response_identity in seen_responses:
                    raise ValueError(
                        "Duplicate direct response ID; do not reuse one rating for multiple examples"
                    )
                seen_responses.add(response_identity)
            available = [rating for rating in ratings.values() if "reference" in rating]
            if len(available) == 2 and available[0]["reference"] != available[1]["reference"]:
                raise ValueError("Paired direct ratings must describe the same reference month")
            # A collected refusal still identifies a reference period. Preserve
            # it without inventing a rating or collapsing different follow-ups.
            reference = available[0]["reference"] if available else None
            identity = raw["person_id"], raw["employer_id"], started, reference
            if identity in seen_periods:
                raise ValueError(
                    "Duplicate employment-spell/reference-period ratings; resolve conflicts before preparation"
                )
            seen_periods.add(identity)
            if available and any(
                not mapping["followup_months"]["min"]
                <= rating["reference"] - started
                <= mapping["followup_months"]["max"]
                for rating in available
            ):
                excluded["outside_followup_window"] += 1
                continue
            label = joint_satisfaction(ratings["employee"]["value"], ratings["manager"]["value"])
            statuses[label["status"]] += 1
            row = {key: raw[key] for key in ("person_id", "employer_id", "job_started_at", "feature_as_of")}
            row.update(features)
            row.update(
                employee_rating=label["employee_rating"],
                manager_rating=label["manager_rating"],
                joint_rating=int(label["joint_rating"]) if label["joint_rating"] is not None else None,
                joint_score=label["joint_score"],
                label_status=label["status"],
            )
            row["rating_reference_at"] = available[0]["reference_at"] if available else ""
            row["rating_observed_at"] = max((rating["observed_at"] for rating in available), default="")
            for side, rating in ratings.items():
                for destination, source in (
                    ("raw_value", "raw_value"),
                    ("reference_at", "reference_at"),
                    ("observed_at", "observed_at"),
                    ("response_id", "response_id"),
                ):
                    row[f"{side}_{destination}"] = rating.get(source, "")
            row["manager_rater_id"] = ratings["manager"].get("rater_id", "")
            rows.append(row)
    mapping["source"] = {
        **mapping["source"],
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "raw_mapping_sha256": hashlib.sha256(mapping_path.read_bytes()).hexdigest(),
    }
    report = {
        "schema_version": 1,
        "target": JOINT_TARGET,
        "live_execution": False,
        "fictional_data": mapping["source"]["kind"] == "fictional_fixture",
        "source": mapping["source"],
        "source_rows": source_rows,
        "retained_rows": len(rows),
        "paired_rows": statuses["OBSERVED_PAIRED"],
        "label_status_counts": dict(statuses),
        "excluded": dict(excluded),
        "joint_label": mapping["joint_label"],
        "rating_collection": mapping["rating_collection"],
        "joint_score_counts": dict(
            Counter(str(row["joint_score"]) for row in rows if row["joint_score"] is not None)
        ),
        "limitations": [
            "Only paired direct reports create a label; missing manager feedback stays unknown.",
            "Both reports concern the same person/employer/job start and reference month; sources must authenticate those declarations.",
            "Normalized categories are ordinal0..4; score25*minimum is a policy index, not a probability.",
            "Manager rater and response IDs are provenance fields only; they never enter predictors or aggregate model reports.",
            "This preparation cannot independently establish consent, authority or source authenticity.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / "observations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (output / "mapping.json").write_text(json.dumps(mapping, indent=2) + "\n")
    (output / "preparation_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"Prepared {len(rows)} rows; {report['paired_rows']} paired joint labels; missing sides remain unknown"
    )
    return report


def initialize(directory: Path) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Choose an empty input directory; existing work will not be overwritten")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "mapping.json").write_bytes(EXAMPLE_MAPPING.read_bytes())
    (directory / "ratings.jsonl").touch(exist_ok=False)
    print(f"Created empty paired-rating inputs in {directory}; actual direct manager responses are required")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "input")
    command = commands.add_parser("prepare")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--mapping", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.output)
    else:
        prepare(args.input, args.mapping, args.output)


if __name__ == "__main__":
    main()
