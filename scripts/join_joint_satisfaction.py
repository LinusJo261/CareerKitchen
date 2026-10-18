"""Join separately collected direct ratings to frozen features, offline only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from scripts.mutual_matching_features import FEATURE_NAMES, validate_features
from scripts.prepare_joint_satisfaction import EXAMPLE_MAPPING, prepare, validate_preparation_mapping
from scripts.satisfaction_research import month

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / ".local" / "joint-satisfaction" / "collection"
SPELL_COLUMNS = ("person_id", "employer_id", "job_started_at")
FEATURE_COLUMNS = (*SPELL_COLUMNS, "feature_as_of", *FEATURE_NAMES)
RATING_COLUMNS = (*SPELL_COLUMNS, "reference_at", "observed_at", "response_id", "value", "kind")
MANAGER_COLUMNS = (*RATING_COLUMNS, "rater_id")
TABLES = {
    "feature_snapshots.csv": FEATURE_COLUMNS,
    "employee_ratings.csv": RATING_COLUMNS,
    "manager_ratings.csv": MANAGER_COLUMNS,
}

COLLECTION_INSTRUCTIONS = """# Collect paired satisfaction reports

These CSV files are empty templates, not training data. Actual, consented reports
from employees and their direct managers about the same jobs are required.

1. Give each employee and employer a pseudonymous ID. Include the actual job's
   start month (YYYY-MM) so a return to the same employer is a different spell.
   Keep identity/contact lookup files separate; do not put names or emails here.
2. Put one feature snapshot in feature_snapshots.csv for each employment spell.
   feature_as_of must be at or before job start. Use only information known then.
   Leave unknown numeric inputs blank; do not substitute current preferences or
   later promotions. Relevant experience is years; other alignments are 0..1.
3. Ask both parties about the same chosen reference month, for example six months
   after job start. The default preparation window accepts 3..24 months. Record
   each response in its side's CSV using the same person/employer/start/reference
   key. observed_at is when that side's answer was collected, in YYYY-MM.
4. Employee question: Overall, how satisfied were you with this job during the
   specified reference month? Manager question: Overall, how satisfied were you
   with this hire during that same reference month? Use five explicitly anchored
   categories: 1 very dissatisfied, 2 dissatisfied, 3 neither, 4 satisfied,
   5 very satisfied.
   Document actual wording/anchors in the instrument reference in mapping.json.
5. employee kind is direct_employee_report; manager kind is direct_manager_report.
   Give each response a unique response_id. Manager rows also need rater_id for
   the actual direct manager. Do not substitute predicted or secondhand ratings.
   An unanswered request is not a rating: omit that response row. For a collected
   refusal/missing response, use a declared missing code; never enter zero.
6. Set the actual dataset name, collection release and instrument reference in
   mapping.json. Default raw ratings run from 1 worst to 5 best. If the instrument differs,
   declare each side's five codes in worst-to-best order before preparing data.
7. Run the documented join command. It matches exact job identities and reference
   months; mismatches stay unpaired or fail, and no missing side is invented.

The collector is responsible for verifying manager relationships, consent and
historical source authenticity. A pseudonymous ID or source declaration is not
proof. NLSY97 respondents and synthetic Hugging Face profiles are unrelated;
do not assign them common IDs to manufacture a join. A joint score is the lower
rating on a normalized scale, not a probability of hiring or mutual interest.
"""


def _read_table(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or set(headers) != set(columns):
            raise ValueError(f"{path.name} must contain exactly the documented unique CSV headers")
        result = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path.name} has a malformed field count")
            result.append({key: value.strip() for key, value in row.items()})
        return result


def _spell(row: dict) -> tuple[str, str, str]:
    if not row["person_id"] or not row["employer_id"]:
        raise ValueError("Person and employer IDs must be nonempty pseudonymous identifiers")
    month(row["job_started_at"])
    return tuple(row[name] for name in SPELL_COLUMNS)


def _features(rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        key = _spell(row)
        if key in result:
            raise ValueError(
                "Duplicate feature snapshot for one employment spell; do not create a many-to-many join"
            )
        if month(row["feature_as_of"]) > month(row["job_started_at"]):
            raise ValueError("Posthire feature leakage: freeze features before or at job start")
        try:
            values = {name: None if row[name] == "" else float(row[name]) for name in FEATURE_NAMES}
        except ValueError as exc:
            raise ValueError("Features must be numbers or blank for unknown") from exc
        result[key] = {
            **{name: row[name] for name in (*SPELL_COLUMNS, "feature_as_of")},
            "features": validate_features(values),
        }
    return result


def _ratings(rows: list[dict], side: str, snapshots: dict, mapping: dict) -> dict:
    result, response_ids = {}, set()
    valid_codes = set(mapping["rating_collection"][f"{side}_codes_worst_to_best"]) | set(
        mapping["missing_codes"]
    )
    for row in rows:
        spell = _spell(row)
        if spell not in snapshots:
            raise ValueError("Rating has no exact frozen feature snapshot for its person/employer/job start")
        if not month(row["job_started_at"]) < month(row["reference_at"]) <= month(row["observed_at"]):
            raise ValueError("Rating reference must follow job start and precede observation")
        key = (*spell, row["reference_at"])
        if key in result:
            raise ValueError(
                f"Duplicate {side} rating for one spell/reference month; resolve conflicting reports"
            )
        if not row["response_id"] or row["response_id"] in response_ids:
            raise ValueError(f"Missing or duplicate {side} response ID")
        if row["kind"] != f"direct_{side}_report":
            raise ValueError("Only direct employee and direct manager reports can supply satisfaction labels")
        if side == "manager" and not row["rater_id"]:
            raise ValueError("A direct manager rating requires its pseudonymous rater ID")
        if row["value"] not in valid_codes:
            raise ValueError("Unknown raw rating code; use the instrument's declared scale")
        response_ids.add(row["response_id"])
        result[key] = row
    return result


def join(input_directory: Path, output: Path) -> dict:
    """Exact, outer join; never impute a response or match by similar profiles."""
    if output.exists():
        raise FileExistsError("Choose a new joined output directory; existing work is preserved")
    mapping_path = input_directory / "mapping.json"
    mapping = json.loads(mapping_path.read_text())
    validate_preparation_mapping(mapping)
    tables = {name: _read_table(input_directory / name, columns) for name, columns in TABLES.items()}
    snapshots = _features(tables["feature_snapshots.csv"])
    if not snapshots:
        raise ValueError("No feature snapshots; templates alone are not observed training data")
    employee = _ratings(tables["employee_ratings.csv"], "employee", snapshots, mapping)
    manager = _ratings(tables["manager_ratings.csv"], "manager", snapshots, mapping)
    periods = defaultdict(set)
    for key in employee.keys() | manager.keys():
        periods[key[:3]].add(key[3])
    records = []
    for spell, snapshot in sorted(snapshots.items()):
        if not periods[spell]:
            records.append({**snapshot, "employee_rating": None, "manager_rating": None})
        else:
            for period in sorted(periods[spell]):
                key = (*spell, period)
                records.append(
                    {**snapshot, "employee_rating": employee.get(key), "manager_rating": manager.get(key)}
                )
    hashes = {
        name: hashlib.sha256((input_directory / name).read_bytes()).hexdigest()
        for name in (*TABLES, "mapping.json")
    }
    mapping["source"] = {**mapping["source"], "collection_sha256": hashes}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Validate and prepare in a temporary sibling directory. Publish the complete
    # bundle only on success; no user inputs are written or partially replaced.
    with tempfile.TemporaryDirectory(prefix=".joint-join-", dir=output.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        (staging / "ratings.jsonl").write_text(
            "".join(json.dumps(row, allow_nan=False) + "\n" for row in records)
        )
        (staging / "mapping.json").write_text(json.dumps(mapping, indent=2) + "\n")
        prepared = prepare(staging / "ratings.jsonl", staging / "mapping.json", staging / "prepared")
        report = {
            "schema_version": 1,
            "target": mapping["target"],
            "live_execution": False,
            "fictional_data": prepared["fictional_data"],
            "source": mapping["source"],
            "feature_snapshots": len(snapshots),
            "employee_responses": len(employee),
            "manager_responses": len(manager),
            "joined_rows": len(records),
            "paired_rows": prepared["paired_rows"],
            "label_status_counts": prepared["label_status_counts"],
            "excluded": prepared["excluded"],
            "join_policy": "exact person_id + employer_id + job_started_at; ratings also share reference_at",
            "limitations": [
                "No fuzzy joins, synthetic identities or inferred manager feedback.",
                "Different reference months produce separate incomplete records, never a paired label.",
                "Collected direct response declarations and prehire feature provenance require source review.",
                "Complete paired responses may be selective; score is not a match probability.",
            ],
        }
        (staging / "join_report.json").write_text(json.dumps(report, indent=2) + "\n")
        if output.exists():
            raise FileExistsError("Output appeared during preparation; choose a new destination")
        staging.rename(output)
    print(
        f"Joined {len(records)} records; {report['paired_rows']} paired labels. Prepared training files: {output / 'prepared'}"
    )
    return report


def initialize(directory: Path) -> None:
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Choose an empty collection directory; existing work will not be overwritten")
    directory.mkdir(parents=True, exist_ok=True)
    for name, columns in TABLES.items():
        with (directory / name).open("x", newline="") as handle:
            csv.writer(handle).writerow(columns)
    (directory / "mapping.json").write_bytes(EXAMPLE_MAPPING.read_bytes())
    (directory / "collection_instructions.md").write_text(COLLECTION_INSTRUCTIONS)
    print(f"Created three empty CSV templates in {directory}; collect real paired responses before training")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--output", type=Path, default=DEFAULT_INPUT)
    command = commands.add_parser("join")
    command.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.output)
    else:
        join(args.input, args.output)


if __name__ == "__main__":
    main()
