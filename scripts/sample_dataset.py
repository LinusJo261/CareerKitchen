"""Freeze synthetic applicants and jobs for an isolated development sample database.

Only the pinned dataset card, resumes, and jobs are downloaded. Match labels,
embeddings, hiring outcomes, and the other suggested datasets are never read.
Downloaded data stays under ignored .local storage. Offline loading needs no
optional dependencies; the explicit download step requires httpx and pyarrow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / ".local" / "sample-dataset"
DATASET = "michaelozon/candidate-matching-synthetic"
REVISION = "178ab864dcad9910c5670d43e4bdbbb901a11f18"
SOURCE_URL = f"https://huggingface.co/datasets/{DATASET}"
BASE_URL = f"{SOURCE_URL}/resolve/{REVISION}/"
SCHEMA_VERSION = 1
COUNTS = {"resumes": 10_000, "jobs": 2_500}


# Independently downloaded and SHA256-checked on 2026-10-18. A revision update
# requires reviewing the license, schema, and these exact byte-level pins.
class SourceFile(TypedDict):
    source_path: str
    bytes: int
    sha256: str


class TableFile(TypedDict):
    file: str
    count: int
    bytes: int
    sha256: str


SOURCE_FILES: dict[str, SourceFile] = {
    "README.md": {
        "source_path": "README.md",
        "bytes": 13_204,
        "sha256": "7a8c23a8a8721e2f977431a4d05e20dbe8a52d19f4f9fd33aceac5334ec7b4cc",
    },
    "resumes.parquet": {
        "source_path": "data/resumes-00000-of-00001.parquet",
        "bytes": 277_342,
        "sha256": "4a25add9c3a620c4c396e867063e390fc8084f9b53ed8135def049303a29d7a4",
    },
    "jobs.parquet": {
        "source_path": "jobs/train-00000-of-00001.parquet",
        "bytes": 56_026,
        "sha256": "c13d7c7e0ab510e81117974027de1364f973a27b3cacc8fabfbd8851c352c871",
    },
}
TABLE_FILES: dict[str, TableFile] = {
    "resumes": {
        "file": "resumes.jsonl",
        "count": 10_000,
        "bytes": 5_384_007,
        "sha256": "0800cf6703dd7df2de3576454b0cdda08a5a1e9a9fb010aef0b320dc5d04ac6f",
    },
    "jobs": {
        "file": "jobs.jsonl",
        "count": 2_500,
        "bytes": 1_685_436,
        "sha256": "11a758ef72a3dc533bd12e069f12bcaed9ddb7defbdaa7b2739ad66dff08d153",
    },
}
RESUME_FIELDS = {
    "resume_id",
    "role",
    "seniority",
    "years_experience",
    "industry",
    "education",
    "skills",
    "summary",
    "experience_bullets",
}
JOB_FIELDS = {
    "job_id",
    "job_title",
    "seniority",
    "industry",
    "must_have_skills",
    "nice_to_have_skills",
    "description",
    "responsibilities",
    "requirements",
}
MAX_JSONL_BYTES = 25_000_000
MAX_MANIFEST_BYTES = 20_000


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _text(value: object, field: str, *, maximum: int = 300) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 and char not in "\n\t\r" for char in value)
    ):
        raise ValueError(f"{field} must be nonblank bounded text without control characters")
    return value.strip()


def _texts(value: object, field: str, *, minimum: int = 0, maximum: int = 30) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} must be a bounded list of text")
    values = [_text(item, field, maximum=2_000) for item in value]
    if len({item.casefold() for item in values}) != len(values):
        raise ValueError(f"{field} contains duplicate text")
    return values


def _base(value: object, fields: set[str], key: str, prefix: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"Unexpected {key} source schema; review a new source version explicitly")
    record = dict(value)
    if not isinstance(record[key], str) or re.fullmatch(prefix + r"_[0-9]{6}", record[key]) is None:
        raise ValueError(f"Invalid synthetic {key}")
    if not isinstance(record["seniority"], str) or record["seniority"] not in {"Junior", "Mid", "Senior"}:
        raise ValueError("Unexpected synthetic seniority")
    record["industry"] = _text(record["industry"], "industry")
    return record


def validate_resume(value: object) -> dict[str, Any]:
    row = _base(value, RESUME_FIELDS, "resume_id", "R")
    years = row["years_experience"]
    if type(years) is not int or not 0 <= years <= 60:
        raise ValueError("years_experience must be an integer between zero and sixty")
    for field in ("role", "education"):
        row[field] = _text(row[field], field)
    row["summary"] = _text(row["summary"], "summary", maximum=20_000)
    row["skills"] = _texts(row["skills"], "skills", minimum=1)
    row["experience_bullets"] = _texts(row["experience_bullets"], "experience_bullets")
    return row


def validate_job(value: object) -> dict[str, Any]:
    row = _base(value, JOB_FIELDS, "job_id", "J")
    row["job_title"] = _text(row["job_title"], "job_title")
    row["description"] = _text(row["description"], "description", maximum=20_000)
    for field in ("must_have_skills", "nice_to_have_skills", "responsibilities", "requirements"):
        row[field] = _texts(row[field], field, minimum=int(field == "must_have_skills"))
    return row


def validate_tables(tables: object) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(tables, dict) or set(tables) != set(COUNTS):
        raise ValueError("Only synthetic resumes and jobs may enter the sample source")
    checked = {}
    for name, validator, key in (("resumes", validate_resume, "resume_id"), ("jobs", validate_job, "job_id")):
        rows = tables[name]
        if not isinstance(rows, list) or len(rows) != COUNTS[name]:
            raise ValueError(f"Expected exactly {COUNTS[name]} pinned synthetic {name}")
        values = [validator(row) for row in rows]
        if len({row[key] for row in values}) != len(values):
            raise ValueError(f"Duplicate synthetic {key}")
        checked[name] = sorted(values, key=lambda row: row[key])
    return checked


def _read_bounded(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("Missing, linked, or oversized frozen sample source file")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Frozen sample source file exceeds its size limit")
    return raw


def _verified_file(raw: bytes, metadata: Mapping[str, Any]) -> None:
    if len(raw) != metadata["bytes"] or sha256(raw) != metadata["sha256"]:
        raise ValueError("Pinned synthetic source failed byte length or SHA256 validation")


def _public_origin(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
        and (host == "huggingface.co" or host.endswith(".hf.co"))
    )


def _fetch(url: str, maximum: int) -> bytes:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "The explicit download step requires httpx in the selected Python environment"
        ) from exc
    # Check each redirect before issuing its request. Never persist signed CDN
    # redirects, cookies, credentials, or tokens in the provenance manifest.
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            for _ in range(6):
                if not _public_origin(url):
                    raise ValueError(
                        "Synthetic source redirected outside official HTTPS Hugging Face origins"
                    )
                with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Synthetic source redirect is missing a destination")
                        url = urljoin(url, location)
                        continue
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"Pinned public synthetic source returned HTTP {response.status_code}"
                        )
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65_536):
                        raw.extend(chunk)
                        if len(raw) > maximum:
                            raise ValueError("Synthetic source exceeds the pinned download size")
                    return bytes(raw)
            raise ValueError("Synthetic source exceeded the bounded redirect count")
    except httpx.HTTPError:
        raise RuntimeError("Pinned public synthetic source download failed") from None


def _parquet_rows(raw: bytes, name: str) -> list[dict[str, Any]]:
    try:
        import pyarrow as arrow
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise RuntimeError(
            "The explicit download step requires optional pyarrow; use the isolated research environment"
        ) from exc
    source = parquet.ParquetFile(arrow.BufferReader(raw))
    if source.metadata.num_rows != COUNTS[name]:
        raise ValueError("Pinned synthetic Parquet row count changed")
    expected = RESUME_FIELDS if name == "resumes" else JOB_FIELDS
    if set(source.schema_arrow.names) != expected or len(source.schema_arrow.names) != len(expected):
        raise ValueError("Pinned synthetic Parquet schema changed")
    return source.read().to_pylist()


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)


def download_source(output: Path = DEFAULT_SOURCE) -> dict[str, Any]:
    """Fetch and pin only explicitly synthetic records; never modifies a database."""
    directory = Path(output)
    if (directory / "manifest.json").exists():
        return load_source(directory)[1]
    directory.mkdir(parents=True, exist_ok=True)
    # Do not overwrite partial downloads or unrelated data. All input is verified
    # in memory before creating source files; manifest is written last.
    if any(directory.iterdir()):
        raise ValueError("Use an empty sample source directory or a complete validated source")
    files = {}
    for filename, metadata in SOURCE_FILES.items():
        raw = _fetch(BASE_URL + metadata["source_path"], metadata["bytes"])
        _verified_file(raw, metadata)
        files[filename] = raw
    tables = validate_tables({name: _parquet_rows(files[name + ".parquet"], name) for name in COUNTS})
    derived = {name: b"".join(canonical_bytes(row) for row in rows) for name, rows in tables.items()}
    if any(len(raw) > MAX_JSONL_BYTES for raw in derived.values()):
        raise ValueError("Derived synthetic records exceed the frozen source size limit")
    for name, raw in derived.items():
        _verified_file(raw, TABLE_FILES[name])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset": DATASET,
        "revision": REVISION,
        "source_url": SOURCE_URL,
        "license": "MIT",
        "license_evidence": f"{BASE_URL}README.md",
        "attribution": "Michael Ozon, Candidate-Job Matching Synthetic Dataset (2026), Hugging Face.",
        "fictional": True,
        "purpose": "Isolated development samples; no real people, vacancies, preferences, consent, or hiring outcomes.",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "source_files": SOURCE_FILES,
        "tables": TABLE_FILES,
    }
    for filename, raw in files.items():
        _write_new(directory / filename, raw)
    for name, raw in derived.items():
        _write_new(directory / (name + ".jsonl"), raw)
    _write_new(directory / "manifest.json", canonical_bytes(manifest))
    return load_source(directory)[1]


def load_source(path: Path = DEFAULT_SOURCE) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Verify immutable originals and canonical JSONL without network or pyarrow."""
    directory = Path(path)
    if directory.is_file():
        directory = directory.parent
    manifest_raw = _read_bounded(directory / "manifest.json", MAX_MANIFEST_BYTES)
    manifest = json.loads(manifest_raw)
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("dataset") != DATASET
        or manifest.get("revision") != REVISION
        or manifest.get("source_url") != SOURCE_URL
        or manifest.get("license") != "MIT"
        or manifest.get("license_evidence") != BASE_URL + "README.md"
        or manifest.get("fictional") is not True
        or manifest.get("source_files") != SOURCE_FILES
        or not isinstance(manifest.get("tables"), dict)
        or set(manifest["tables"]) != set(COUNTS)
        or manifest["tables"] != TABLE_FILES
    ):
        raise ValueError("Invalid pinned synthetic dataset manifest")
    for filename, source_metadata in SOURCE_FILES.items():
        _verified_file(_read_bounded(directory / filename, source_metadata["bytes"]), source_metadata)
    tables = {}
    for name, count in COUNTS.items():
        metadata = manifest["tables"][name]
        if (
            not isinstance(metadata, dict)
            or metadata.get("file") != name + ".jsonl"
            or type(metadata.get("count")) is not int
            or metadata["count"] != count
            or type(metadata.get("bytes")) is not int
            or not 1 <= metadata["bytes"] <= MAX_JSONL_BYTES
            or not isinstance(metadata.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is None
        ):
            raise ValueError("Invalid bounded synthetic table manifest")
        raw = _read_bounded(directory / (name + ".jsonl"), metadata["bytes"])
        _verified_file(raw, metadata)
        tables[name] = [json.loads(line) for line in raw.splitlines()]
    checked = validate_tables(tables)
    # Canonical serialization ensures row sorting and validated normalization are
    # themselves covered by the checksum, not silently changed during import.
    for name, rows in checked.items():
        if sha256(b"".join(canonical_bytes(row) for row in rows)) != manifest["tables"][name]["sha256"]:
            raise ValueError("Frozen sample records are not in canonical validated order")
    return checked, {**manifest, "manifest_sha256": sha256(manifest_raw)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--download", action="store_true", help="Explicitly fetch pinned public synthetic source"
    )
    args = parser.parse_args()
    try:
        provenance = download_source(args.output) if args.download else load_source(args.output)[1]
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"Sample source: {exc}\n")
    print(
        json.dumps(
            {
                "dataset": DATASET,
                "revision": REVISION,
                "manifest_sha256": provenance["manifest_sha256"],
                "counts": {name: meta["count"] for name, meta in provenance["tables"].items()},
                "manifest": str(args.output.resolve() / "manifest.json"),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
