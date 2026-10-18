"""Prepare an ignored NLS export for offline research; never changes live matching."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = re.compile(r"^([A-Z]\d+\.\d+)\s+\[([^\]]+)\][^\n]*Survey Year:\s*(\d{4})", re.M)
FIELDS = (
    "person_id",
    "employer_id",
    "job_started_at",
    "feature_as_of",
    "rating_reference_at",
    "rating_observed_at",
    "satisfaction",
    "weekly_hours_at_start",
)
LABELS = {
    1: "Like it very much",
    2: "Like it fairly well",
    3: "Think it is OK",
    4: "Dislike it somewhat",
    5: "Dislike it very much",
}


def parse_codebook(path: Path) -> dict:
    """Map exact wave/question names to reference-number CSV columns."""
    text = path.read_text(encoding="utf-8-sig")
    headers = list(HEADER.finditer(text))
    if not headers:
        raise ValueError("No NLS reference-number headers found in codebook")
    result, seen_columns = {}, set()
    for index, match in enumerate(headers):
        reference, question, year = match[1], match[2], int(match[3])
        column = reference.replace(".", "")
        block = text[match.end() : headers[index + 1].start() if index + 1 < len(headers) else len(text)]
        if (year, question) in result or column in seen_columns:
            raise ValueError("Duplicate year/question or reference in codebook")
        seen_columns.add(column)
        if re.fullmatch(r"YEMP-101200\.\d+", question):
            for code, label in LABELS.items():
                if not re.search(rf"^\s*\d+\s+{code}\s+{re.escape(label)}\s*$", block, re.M | re.I):
                    raise ValueError("Satisfaction codebook must confirm codes 1 best through 5 worst")
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        description = next((line for line in lines if line != "PRIMARY VARIABLE"), "")
        result[year, question] = dict(
            column=column, question=question, year=year, reference=reference, description=description
        )
    return result


def _integer(value: str | None) -> int | None:
    try:
        number = float(value or "nan")
        return int(number) if math.isfinite(number) and number.is_integer() else None
    except ValueError:
        return None


def _month(year: int | None, month: int | None) -> int | None:
    return year * 12 + month - 1 if year and 1900 <= year <= 2200 and month and 1 <= month <= 12 else None


def _format_month(value: int) -> str:
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def prepare(csv_path: Path, codebook_path: Path, output: Path) -> dict:
    destinations = {
        (output / name).resolve()
        for name in (
            "observations.csv",
            "mapping.json",
            "preparation_report.json",
        )
    }
    if {csv_path.resolve(), codebook_path.resolve()} & destinations:
        raise ValueError("Output would overwrite a raw input; choose a separate prepared directory")
    metadata = parse_codebook(codebook_path)
    satisfaction = sorted(
        (year, int(name.rsplit(".", 1)[1]), item)
        for (year, name), item in metadata.items()
        if re.fullmatch(r"YEMP-101200\.\d+", name)
    )
    if not satisfaction:
        raise ValueError("Export has no satisfaction fields")
    if len({(year, slot) for year, slot, _ in satisfaction}) != len(satisfaction):
        raise ValueError("Duplicate survey-year/employer-slot satisfaction fields")
    pubids = [item["column"] for (_, name), item in metadata.items() if name == "PUBID"]
    if len(pubids) != 1:
        raise ValueError("Codebook must contain one PUBID")
    years = sorted({year for year, _ in metadata})
    counts: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    by_year: Counter[str] = Counter()
    missing_columns = []
    prepared, people = [], set()
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("CSV contains duplicate headers")
        if not {item["column"] for item in metadata.values()} <= set(headers):
            raise ValueError("CSV is missing reference columns declared in its codebook")
        specs = []
        for year, slot, label in satisfaction:

            def find(name, survey_year=year):
                item = metadata.get((survey_year, name))
                return item["column"] if item else None

            def dates(base):
                return tuple(
                    next(
                        (
                            find(base + separator + part)
                            for separator in ("~", "_")
                            if find(base + separator + part)
                        ),
                        None,
                    )
                    for part in ("Y", "M")
                )

            suffix = f".{slot:02d}"
            spec = dict(
                year=year,
                slot=slot,
                label=label["column"],
                uid=find("YEMP_UID" + suffix),
                current=find("YEMP_CURFLAG" + suffix),
                start=dates("YEMP_STARTDATE" + suffix),
                stop=dates("YEMP_STOPDATE" + suffix),
                interview=dates("CV_INTERVIEW_DATE"),
                hours=[find(base + suffix) for base in ("YEMP-23901", "YEMP-34402")],
            )
            gaps = [name for name in ("uid", "current") if not spec[name]]
            gaps += [name for name in ("start", "stop", "interview") if not all(spec[name])]
            if not any(spec["hours"]):
                gaps.append("start_hours")
            if gaps:
                missing_columns.append(dict(survey_year=year, employer_slot=slot, fields=gaps))
            specs.append(spec)
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("CSV has malformed field counts")
            person = _integer(row[pubids[0]])
            if person is None or person <= 0 or person in people:
                raise ValueError("PUBID must be positive and unique; inspect the export locally")
            people.add(person)
            for spec in specs:
                label = _integer(row[spec["label"]])
                if label is None or label < 0:
                    counts["missing_or_invalid_satisfaction"] += 1
                    continue
                if label not in LABELS:
                    raise ValueError("Unexpected satisfaction code; inspect the codebook locally")
                counts["valid_labels_considered"] += 1

                def value(column, source_row=row):
                    return _integer(source_row[column]) if column else None

                def date(columns, lookup=value):
                    return _month(*(lookup(column) for column in columns))

                uid, current = value(spec["uid"]), value(spec["current"])
                reason = None
                if not all((spec["uid"], spec["current"], *spec["start"], *spec["interview"])):
                    reason = "missing_required_columns"
                elif not uid or uid < 0 or current not in (0, 1):
                    reason = "missing_identity_or_current_status"
                elif current == 0 and not all(spec["stop"]):
                    reason = "missing_required_columns"
                else:
                    start, interview = date(spec["start"]), date(spec["interview"])
                    reference = interview if current == 1 else date(spec["stop"])
                    if start is None or interview is None or reference is None:
                        reason = "missing_or_invalid_dates"
                    elif not start < reference <= interview:
                        reason = "invalid_timeline"
                    elif not 3 <= reference - start <= 24:
                        reason = "outside_followup_window"
                hours, invalid_hours = [], False
                for column in spec["hours"]:
                    raw = row[column].strip() if column else ""
                    if not raw:
                        continue
                    try:
                        number = float(raw)
                    except ValueError:
                        invalid_hours = True
                        continue
                    if math.isfinite(number) and number < 0:
                        continue
                    if not math.isfinite(number) or number > 168:
                        invalid_hours = True
                    else:
                        hours.append(number)
                if reason is None:
                    if invalid_hours:
                        reason = "hours_out_of_range"
                    elif len(set(hours)) > 1:
                        reason = "conflicting_start_hours"
                    elif not hours:
                        reason = "missing_start_hours"
                if reason:
                    excluded[reason] += 1
                    continue
                prepared.append(
                    dict(
                        zip(
                            FIELDS,
                            (
                                str(person),
                                str(uid),
                                _format_month(start),
                                _format_month(start),
                                _format_month(reference),
                                _format_month(interview),
                                str(label),
                                format(hours[0], ".15g"),
                            ),
                            strict=True,
                        )
                    )
                )
                by_year[str(spec["year"])] += 1
    hashes = {
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "codebook_sha256": hashlib.sha256(codebook_path.read_bytes()).hexdigest(),
    }
    mapping = json.loads((ROOT / "research/satisfaction_mapping.example.json").read_text())
    mapping["source"] = dict(
        kind="survey_export",
        dataset="NLSY97",
        release=f"local-export-survey-years-{years[0]}-{years[-1]}",
        codebook_url="https://www.nlsinfo.org/content/cohorts/nlsy97/topical-guide/employment/employers-jobs",
        **hashes,
    )
    mapping["features"] = dict(numeric={"weekly_hours_at_start": "weekly_hours_at_start"}, categorical={})
    mapping["feature_timing"] = {"weekly_hours_at_start": "prehire_or_job_start"}
    notes = [
        "Only same-wave employer-slot joins; no UID carryforward or nominal-year date inference.",
        "Exact 23901/34402 hours describe reported usual hours at start/resume; not contractual offers.",
        "H suffixes are hours at home and are excluded; missing hours are excluded.",
        "Three-to-24-month follow-up is a declared study choice; trainer keeps first eligible rating per spell.",
        "Satisfaction universe and response selection change across survey rounds.",
    ]
    mapping["preparation"] = dict(feature_semantics=notes, source_questions=["YEMP-23901", "YEMP-34402"])
    report = dict(
        schema_version=1,
        live_execution=False,
        fictional_data=False,
        source=mapping["source"],
        source_rows=len(people),
        **counts,
        retained_observations=len(prepared),
        excluded=dict(excluded),
        retained_by_survey_year=dict(sorted(by_year.items())),
        missing_columns=missing_columns,
        followup_months=mapping["followup_months"],
        limitations=notes,
    )
    report["field_coverage_by_survey_year"] = {
        str(year): {
            "satisfaction_slots": sum(spec["year"] == year for spec in specs),
            **{
                name + "_slots": sum(spec["year"] == year and all(spec[name]) for spec in specs)
                for name in ("start", "stop", "interview")
            },
        }
        for year in sorted({spec["year"] for spec in specs})
    }
    output.mkdir(parents=True, exist_ok=True)
    with (output / "observations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(prepared)
    for name, content in (("mapping.json", mapping), ("preparation_report.json", report)):
        (output / name).write_text(json.dumps(content, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--codebook", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/satisfaction-research/prepared")
    args = parser.parse_args()
    print(json.dumps(prepare(args.input, args.codebook, args.output), indent=2))


if __name__ == "__main__":
    main()
