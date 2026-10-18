"""Pinned TalentCLEF 2026 English development data, for offline research only.

Documents are synthetic, human-reviewed profiles and vacancies. The public
development qrels contain positive relevance judgments only; unlisted pairs
remain unjudged, never inferred rejected introductions or hiring outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

RECORD_ID = 19652670
VERSION = "0.3.0"
LICENSE = "CC-BY-4.0"
METADATA_URL = f"https://zenodo.org/api/records/{RECORD_ID}"
ARCHIVE_URL = f"https://zenodo.org/records/{RECORD_ID}/files/TaskA.zip?download=1"
ARCHIVE_MD5 = "431ec3b693ae1ba24fe04793f9c1f750"
ARCHIVE_SHA256 = "3437ef0437b0f603a15c5e3f8e62e3450ba24cb2bbbdbc5ad328829bbce0e179"
ARCHIVE_SIZE = 3_753_484
DEFAULT_SOURCE = Path(".local/matching-accuracy/talentclef/source/TaskA.zip")
METADATA_FILENAME = f"zenodo-record-{RECORD_ID}.json"
PREFIX = "TaskA/development/en/"
CORPUS_DESCRIPTION = "https://talentclef.github.io/talentclef/docs/talentclef-2026/data/description_corpus/"
INVENTORY_COUNTS = {
    "TaskA/development/en/queries/": 10,
    "TaskA/development/en/corpus/": 472,
    "TaskA/development/es/queries/": 10,
    "TaskA/development/es/corpus/": 472,
    "TaskA/test/en/queries/": 40,
    "TaskA/test/en/corpus/": 476,
    "TaskA/test/es/queries/": 40,
    "TaskA/test/es/corpus/": 476,
    "TaskA/development/en/qrels.tsv": 1,
    "TaskA/development/es/qrels.tsv": 1,
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_metadata(record: Any) -> None:
    """Verify the provider's public license, fixed record, and published checksum."""
    if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] != RECORD_ID:
        raise ValueError("Expected the pinned Zenodo dataset record.")
    metadata = record.get("metadata")
    if not isinstance(metadata, dict) or (
        metadata.get("version") != VERSION
        or metadata.get("license") != {"id": "cc-by-4.0"}
        or metadata.get("access_right") != "open"
    ):
        raise ValueError("Expected version 0.3.0 with an explicit open CC-BY-4.0 license.")
    files = record.get("files")
    if not isinstance(files, list):
        raise ValueError("The published source file metadata is missing.")
    selected = [entry for entry in files if isinstance(entry, dict) and entry.get("key") == "TaskA.zip"]
    if len(selected) != 1 or (
        selected[0].get("checksum") != f"md5:{ARCHIVE_MD5}"
        or type(selected[0].get("size")) is not int
        or selected[0]["size"] != ARCHIVE_SIZE
    ):
        raise ValueError("The provider's archive checksum or size changed.")


def _validate_archive(data: bytes) -> None:
    if len(data) != ARCHIVE_SIZE:
        raise ValueError("Source archive size differs from the pinned version.")
    if hashlib.md5(data, usedforsecurity=False).hexdigest() != ARCHIVE_MD5:
        raise ValueError("Source archive differs from the provider's pinned MD5.")
    if _sha256(data) != ARCHIVE_SHA256:
        raise ValueError("Source archive differs from the pinned SHA256.")


def _curl(url: str, destination: Path, maximum: int) -> None:
    subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--tlsv1.2",
            "--max-time",
            "120",
            "--max-filesize",
            str(maximum),
            url,
            "--output",
            str(destination),
        ],
        check=True,
    )


def _publish_without_replacement(staged: Path, destination: Path) -> None:
    if os.name == "nt":
        # Windows rename fails if the destination already exists; it avoids
        # hard-link privileges while retaining atomic no-replacement publication.
        os.rename(staged, destination)
    else:
        os.link(staged, destination)


def download_source(archive: Path = DEFAULT_SOURCE) -> None:
    """Acquire only the exact licensed Task A archive and its provider metadata.

    Neither destination is overwritten. Metadata publishes first; the archive
    becomes visible only after checksum, license, inventory, and label checks.
    """
    metadata_path = archive.parent / METADATA_FILENAME
    if archive.exists() or metadata_path.exists():
        raise FileExistsError("Source archive or provider metadata already exists.")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".talentclef-download-", dir=archive.parent) as temporary:
        stage = Path(temporary)
        staged_archive, staged_metadata = stage / "TaskA.zip", stage / METADATA_FILENAME
        _curl(METADATA_URL, staged_metadata, 1_000_000)
        record = json.loads(staged_metadata.read_text(encoding="utf-8"))
        validate_metadata(record)
        _curl(ARCHIVE_URL, staged_archive, 8_000_000)
        load_source(staged_archive)
        _publish_without_replacement(staged_metadata, metadata_path)
        _publish_without_replacement(staged_archive, archive)


def parse_qrels(text: str, jobs: dict[str, str], resumes: dict[str, str]) -> dict[str, dict[str, int]]:
    """Parse explicit judgments only; preserve sparse, one-class judgment sets."""
    result: dict[str, dict[str, int]] = {query_id: {} for query_id in jobs}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        row = line.split()
        if len(row) != 4 or row[1] != "0" or row[3] not in {"0", "1"}:
            raise ValueError(f"Malformed binary qrels row {line_number}.")
        query_id, _, resume_id, label = row
        if query_id not in jobs or resume_id not in resumes:
            raise ValueError(f"Unknown query or corpus ID in qrels row {line_number}.")
        if resume_id in result[query_id]:
            raise ValueError(f"Duplicate query/corpus judgment in qrels row {line_number}.")
        result[query_id][resume_id] = int(label)
    if not jobs or not resumes or any(not judgments for judgments in result.values()):
        raise ValueError("Every source query requires at least one explicit judgment.")
    return result


def _inventory(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate source archive entries are forbidden.")
    files: list[zipfile.ZipInfo] = []
    counts: Counter[str] = Counter()
    for info in infos:
        path = PurePosixPath(info.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in info.filename
            or ":" in info.filename
            or not info.filename.startswith("TaskA/")
            or stat.S_ISLNK(info.external_attr >> 16)
        ):
            raise ValueError("Unsafe source archive entry.")
        if info.is_dir():
            if not any(key.startswith(info.filename) for key in INVENTORY_COUNTS):
                raise ValueError("Unexpected source archive directory.")
            continue
        if info.file_size > 1_000_000 or info.flag_bits & 1:
            raise ValueError("Oversized or encrypted source entry.")
        group = next((key for key in INVENTORY_COUNTS if info.filename == key), None)
        if group is None:
            group = next(
                (key for key in INVENTORY_COUNTS if key.endswith("/") and info.filename.startswith(key)),
                None,
            )
            if group is None or not re.fullmatch(r"[0-9]+", info.filename.removeprefix(group)):
                raise ValueError("Unexpected source archive file inventory.")
        counts[group] += 1
        files.append(info)
    if dict(counts) != INVENTORY_COUNTS or sum(info.file_size for info in files) > 40_000_000:
        raise ValueError("Source inventory does not match the pinned development/test partitions.")
    return files


def load_source(
    archive_path: Path = DEFAULT_SOURCE,
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, int]], dict[str, Any]]:
    """Return English development documents and explicit human qrels only.

    No extraction to disk, guessed native features, test evaluation, or automatic
    promotion occurs. Returned text and individual judgments must stay local.
    """
    metadata_path = archive_path.parent / METADATA_FILENAME
    metadata_bytes = metadata_path.read_bytes()
    if len(metadata_bytes) > 1_000_000:
        raise ValueError("Provider metadata exceeds the size limit.")
    validate_metadata(json.loads(metadata_bytes.decode("utf-8")))
    data = archive_path.read_bytes()
    _validate_archive(data)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = _inventory(archive)
        file_hashes = {info.filename: _sha256(archive.read(info)) for info in infos}
        documents: dict[str, dict[str, str]] = {"queries": {}, "corpus": {}}
        for category, target in documents.items():
            prefix = PREFIX + category + "/"
            for info in infos:
                if not info.filename.startswith(prefix):
                    continue
                text = archive.read(info).decode("utf-8-sig").strip()
                if not text or "\x00" in text:
                    raise ValueError("Source documents must contain nonempty UTF-8 text.")
                target[info.filename.removeprefix(prefix)] = text
        jobs, resumes = documents["queries"], documents["corpus"]
        qrels = parse_qrels(archive.read(PREFIX + "qrels.tsv").decode("utf-8-sig"), jobs, resumes)
    labels = Counter(label for judgments in qrels.values() for label in judgments.values())
    universe = len(jobs) * len(resumes)
    judgments = sum(labels.values())
    provenance = {
        "dataset": "TalentCLEF 2026 Task A",
        "record_id": RECORD_ID,
        "version": VERSION,
        "source_url": f"https://zenodo.org/records/{RECORD_ID}",
        "archive_url": ARCHIVE_URL,
        "archive_size": ARCHIVE_SIZE,
        "archive_md5": ARCHIVE_MD5,
        "archive_sha256": ARCHIVE_SHA256,
        "metadata_url": METADATA_URL,
        "metadata_sha256": _sha256(metadata_bytes),
        "license": LICENSE,
        "corpus_description": CORPUS_DESCRIPTION,
        "partition": "development",
        "language": "en",
        "document_kind": "SYNTHETIC_HUMAN_REVIEWED_TEXT",
        "label_kind": "HUMAN_EXPERT_RELEVANCE",
        "native_confirmed_structured_skills_available": False,
        "native_candidate_preferences_available": False,
        "source_archive_file_count": len(infos),
        "evaluated_query_count": len(jobs),
        "evaluated_corpus_count": len(resumes),
        "possible_pairs": universe,
        "explicit_judgments": judgments,
        "explicit_positive_judgments": labels[1],
        "explicit_negative_judgments": labels[0],
        "unjudged_pairs": universe - judgments,
        "judgment_coverage": judgments / universe,
        "judgments_per_query": {key: len(value) for key, value in sorted(qrels.items())},
        "fully_judged_query_count": sum(len(value) == len(resumes) for value in qrels.values()),
        "all_file_sha256": dict(sorted(file_hashes.items())),
        "limitations": [
            "Synthetic privacy-preserving documents and expert relevance labels are not observed hiring or mutual-interest outcomes.",
            "Only English development judgments are evaluated; public test labels are not supplied.",
            "Unlisted pairs remain unjudged, never confirmed negatives. Positive-only qrels do not support binary accuracy, precision, recall, or ROC-AUC against genuine negative labels.",
            "Official information-retrieval MAP treats absence from the relevance list according to the competition convention; that is not evidence of an observed rejection.",
            "Ten job queries provide limited query-level uncertainty and no broad population certification.",
            "Native confirmed taxonomy skills and candidate preferences are unavailable; any extraction adapter is a separately declared proxy.",
        ],
    }
    return jobs, resumes, qrels, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        download_source(args.source)
    _, _, _, provenance = load_source(args.source)
    print(json.dumps({key: value for key, value in provenance.items() if key != "all_file_sha256"}, indent=2))


if __name__ == "__main__":
    main()
