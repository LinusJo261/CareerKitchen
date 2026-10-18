"""Freeze official ESCO English labels for an offline, label-blind skill adapter.

This taxonomy is external vocabulary, not a hiring-outcome dataset. Nothing here
trains or changes the production matching system. Raw API pages and derived data
belong in ignored .local storage; the manifest retains provenance and checksums.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / ".local" / "matching-accuracy" / "esco"
VERSION = "v1.2.0"
API = "https://ec.europa.eu/esco/api/search"
LICENSE_URL = "https://esco.ec.europa.eu/en/node/456"
DOCUMENTATION_URL = "https://esco.ec.europa.eu/en/use-esco/use-esco-services-api/esco-web-service-api"
SKILL_PREFIX = "http://data.europa.eu/esco/skill/"
SOURCE_NAME = "European Commission ESCO English skill labels"
NORMALIZATION = "NFKC-casefold-whitespace-v1"


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _label(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError("ESCO labels must be nonempty strings of at most 2000 characters")
    return value.strip()


def validate_concept(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"id", "preferred_label", "aliases"}:
        raise ValueError("Expected exactly id, preferred_label, aliases")
    concept_id = value["id"]
    if not isinstance(concept_id, str) or not concept_id.startswith(SKILL_PREFIX):
        raise ValueError("Expected an official ESCO skill URI")
    try:
        parsed = UUID(concept_id.removeprefix(SKILL_PREFIX))
    except ValueError as exc:
        raise ValueError("Expected an official ESCO skill UUID") from exc
    if str(parsed) != concept_id.removeprefix(SKILL_PREFIX):
        raise ValueError("ESCO skill UUID must be canonical")
    preferred = _label(value["preferred_label"])
    aliases = value["aliases"]
    if not isinstance(aliases, list) or len(aliases) > 1000:
        raise ValueError("ESCO aliases must be a bounded list")
    checked = [_label(alias) for alias in aliases]
    if len(set(checked)) != len(checked):
        raise ValueError("Duplicate exact aliases within a concept")
    return {"id": concept_id, "preferred_label": preferred, "aliases": checked}


def concept_from_api(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("className") != "Skill":
        raise ValueError("API result must be an ESCO Skill")
    if value.get("status") != "released":
        raise ValueError("Obsolete or unreleased skills must not enter the vocabulary")
    preferred = value.get("preferredLabel")
    alternate = value.get("alternativeLabel", {})
    if not isinstance(preferred, dict) or not isinstance(alternate, dict):
        raise ValueError("Missing English ESCO label maps")
    aliases = alternate.get("en", [])
    if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
        raise ValueError("ESCO English source aliases must be strings in a list")
    # Some released official records contain a literal empty alternative label.
    # Retain every concept and nonblank alias, documenting discarded empty terms.
    aliases = list(dict.fromkeys(alias.strip() for alias in aliases if alias.strip()))
    return validate_concept(
        {"id": value.get("uri"), "preferred_label": preferred.get("en"), "aliases": aliases}
    )


def source_anomalies(raw: bytes) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in json.loads(raw)["_embedded"]["results"]:
        aliases = row.get("alternativeLabel", {}).get("en", [])
        nonblank = [alias.strip() for alias in aliases if alias.strip()]
        counts["discarded_blank_source_aliases"] += len(aliases) - len(nonblank)
        counts["discarded_duplicate_source_aliases"] += len(nonblank) - len(set(nonblank))
    return counts


def vocabulary_statistics(concepts: list[dict[str, Any]]) -> dict[str, int | str]:
    by_label: dict[str, set[str]] = defaultdict(set)
    duplicate_within = 0
    counts: Counter[str] = Counter()
    for concept in concepts:
        own = [normalize_label(value) for value in [concept["preferred_label"], *concept["aliases"]]]
        duplicate_within += len(own) - len(set(own))
        for label in own:
            by_label[label].add(concept["id"])
        counts["aliases"] += len(concept["aliases"])
    ambiguous = {label: ids for label, ids in by_label.items() if len(ids) > 1}
    return {
        "concepts": len(concepts),
        "preferred_labels": len(concepts),
        "alternative_labels": counts["aliases"],
        "unique_normalized_labels": len(by_label),
        "ambiguous_normalized_labels": len(ambiguous),
        "concepts_with_ambiguous_labels": len(set().union(*ambiguous.values())) if ambiguous else 0,
        "duplicate_normalized_labels_within_concept": duplicate_within,
        "normalization": NORMALIZATION,
    }


def page_url(offset: int, limit: int = 100) -> str:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid ESCO API page bounds")
    # Returned next/self links omit selectedVersion. Build every page with the
    # explicit release instead of accidentally switching to the API default.
    return (
        API
        + "?"
        + urllib.parse.urlencode(
            {
                "type": "skill",
                "language": "en",
                "limit": limit,
                "offset": offset,
                "full": "true",
                "viewObsolete": "false",
                "selectedVersion": VERSION,
            }
        )
    )


def parse_page(raw: bytes, *, offset: int, limit: int, total: int | None = None) -> tuple[list[dict], int]:
    value = json.loads(raw)
    if (
        not isinstance(value, dict)
        or type(value.get("total")) is not int
        or not 1 <= value["total"] <= 100000
        or value.get("offset") != offset
        or value.get("limit") != limit
        or value.get("language") != "en"
        or value.get("type") != ["skill"]
        or (total is not None and value["total"] != total)
    ):
        raise ValueError("ESCO API page metadata changed or did not match the requested page")
    records = value.get("_embedded", {}).get("results")
    expected = min(limit, max(0, value["total"] - offset * limit))
    if not isinstance(records, list) or len(records) != expected:
        raise ValueError("ESCO API page is incomplete")
    return [concept_from_api(record) for record in records], value["total"]


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "CareerKitchen-research/1",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        parsed = urllib.parse.urlsplit(response.geturl())
        if parsed.scheme != "https" or parsed.netloc != "ec.europa.eu":
            raise ValueError("ESCO API redirected outside its official HTTPS origin")
        raw = response.read(20_000_001)
        if len(raw) > 20_000_000:
            raise ValueError("ESCO page exceeds the bounded download size")
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        if len(raw) > 20_000_000:
            raise ValueError("ESCO decompressed page exceeds the bounded download size")
        return raw


def _write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)


def download_source(output: Path = DEFAULT_SOURCE, *, limit: int = 100, workers: int = 4) -> dict:
    output = Path(output)
    if (output / "manifest.json").exists():
        return load_source(output)[1]
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("Use between one and four public API download workers")
    output.mkdir(parents=True, exist_ok=True)
    raw_directory = output / "raw"
    raw_directory.mkdir(exist_ok=True)

    def acquire(offset: int) -> tuple[bytes, dict]:
        url = page_url(offset, limit)
        path = raw_directory / f"page-{offset:05d}.json.gz"
        meta_path = raw_directory / f"page-{offset:05d}.metadata.json"
        if path.exists() and meta_path.exists():
            raw = gzip.decompress(path.read_bytes())
            metadata = json.loads(meta_path.read_bytes())
            if metadata.get("source_url") != url or metadata.get("sha256") != sha256(raw):
                raise ValueError("Cached official ESCO page failed source or checksum validation")
            return raw, metadata
        if path.exists() or meta_path.exists():
            raise ValueError("Incomplete cached page; use a fresh output directory")
        raw = _fetch(url)
        parse_page(raw, offset=offset, limit=limit)
        metadata = {
            "source_url": url,
            "sha256": sha256(raw),
            "bytes": len(raw),
            "downloaded_at": datetime.now(UTC).isoformat(),
        }
        _write_new(path, gzip.compress(raw, mtime=0))
        _write_new(meta_path, canonical_bytes(metadata))
        return raw, metadata

    first, first_metadata = acquire(0)
    concepts, total = parse_page(first, offset=0, limit=limit)
    pages = [first_metadata]
    anomalies = source_anomalies(first)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for offset, (raw, metadata) in enumerate(pool.map(acquire, range(1, math.ceil(total / limit))), 1):
            rows, _ = parse_page(raw, offset=offset, limit=limit, total=total)
            concepts.extend(rows)
            pages.append(metadata)
            anomalies.update(source_anomalies(raw))
    if len(concepts) != total or len({item["id"] for item in concepts}) != total:
        raise ValueError("Official API pagination produced missing or duplicate concept IDs")
    concepts.sort(key=lambda item: item["id"])
    derived = b"".join(canonical_bytes(concept) for concept in concepts)
    manifest = {
        "schema_version": 1,
        "source_name": SOURCE_NAME,
        "version": VERSION,
        "language": "en",
        "source_url": page_url(0, limit),
        "documentation_url": DOCUMENTATION_URL,
        "license": "CC-BY-4.0 (EU-owned content; see source copyright notice for third-party attribution)",
        "license_url": LICENSE_URL,
        "attribution": "European Commission, ESCO v1.2.0 English skill preferred and alternative labels; extracted via official public API.",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "data_file": "english-skills.jsonl",
        "data_sha256": sha256(derived),
        "api_total": total,
        "pages": pages,
        "statistics": vocabulary_statistics(concepts),
        "source_anomalies": dict(anomalies),
        "source_cleaning": "Discard blank alternative labels and exact duplicates after whitespace trimming; retain every released concept and all other English labels.",
        "selection": "All released Skill concepts; no benchmark texts, labels, or outcomes used for vocabulary selection.",
    }
    _write_new(output / "english-skills.jsonl", derived)
    _write_new(output / "manifest.json", canonical_bytes(manifest))
    return load_source(output)[1]


def load_source(path: Path = DEFAULT_SOURCE) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    directory = Path(path)
    if directory.is_file():
        directory = directory.parent
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("source_name") != SOURCE_NAME
        or manifest.get("version") != VERSION
        or manifest.get("language") != "en"
        or manifest.get("data_file") != "english-skills.jsonl"
        or not isinstance(manifest.get("data_sha256"), str)
        or re.fullmatch("[0-9a-f]{64}", manifest["data_sha256"]) is None
    ):
        raise ValueError("Invalid frozen ESCO manifest")
    raw = (directory / "english-skills.jsonl").read_bytes()
    if sha256(raw) != manifest["data_sha256"]:
        raise ValueError("Frozen ESCO English labels failed checksum validation")
    rows = [validate_concept(json.loads(line)) for line in raw.splitlines()]
    if len(rows) != manifest.get("api_total") or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Frozen ESCO labels have missing or duplicate concepts")
    if vocabulary_statistics(rows) != manifest.get("statistics"):
        raise ValueError("Frozen ESCO ambiguity statistics do not match its labels")
    provenance = {**manifest, "manifest_sha256": sha256(manifest_raw)}
    return rows, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = download_source(args.output, workers=args.workers)
    print(
        json.dumps({key: result[key] for key in ("version", "data_sha256", "manifest_sha256", "statistics")})
    )


if __name__ == "__main__":
    main()
