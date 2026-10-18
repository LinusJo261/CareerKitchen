"""Fictional taxonomy fixtures test acquisition and validation, never matching accuracy."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from scripts.esco_source import (
    SKILL_PREFIX,
    VERSION,
    canonical_bytes,
    concept_from_api,
    download_source,
    load_source,
    normalize_label,
    page_url,
    parse_page,
    sha256,
    validate_concept,
    vocabulary_statistics,
)


def concept(index: int = 1, label: str = "fictional taxonomy label", aliases: list | None = None) -> dict:
    return {
        "id": SKILL_PREFIX + f"00000000-0000-4000-8000-{index:012d}",
        "preferred_label": label,
        "aliases": ["fictional alias"] if aliases is None else aliases,
    }


def api_row(row: dict) -> dict:
    return {
        "uri": row["id"],
        "className": "Skill",
        "status": "released",
        "preferredLabel": {"en": row["preferred_label"], "de": "fictional foreign label"},
        "alternativeLabel": {"en": row["aliases"]},
    }


def page(rows: list[dict], *, offset: int = 0, limit: int = 2, total: int | None = None) -> bytes:
    return canonical_bytes(
        {
            "total": len(rows) if total is None else total,
            "offset": offset,
            "limit": limit,
            "language": "en",
            "type": ["skill"],
            "_embedded": {"results": [api_row(row) for row in rows]},
        }
    )


class EscoSourceTests(unittest.TestCase):
    def test_url_always_freezes_version_and_excludes_obsolete(self) -> None:
        for offset in (0, 1, 139):
            url = page_url(offset)
            self.assertIn(f"selectedVersion={VERSION}", url)
            self.assertIn("viewObsolete=false", url)
            self.assertIn(f"offset={offset}", url)

    def test_bad_page_bounds_rejected(self) -> None:
        for offset, limit in ((-1, 10), (True, 10), (0, 0), (0, 101), (0, True)):
            with self.subTest(offset=offset, limit=limit), self.assertRaises(ValueError):
                page_url(offset, limit)

    def test_only_english_preferred_and_alternative_labels_used(self) -> None:
        original = concept()
        self.assertEqual(concept_from_api(api_row(original)), original)
        no_aliases = api_row(original)
        del no_aliases["alternativeLabel"]
        self.assertEqual(concept_from_api(no_aliases)["aliases"], [])

    def test_empty_source_alias_anomaly_does_not_remove_concept(self) -> None:
        row = api_row(concept())
        row["alternativeLabel"]["en"] = ["", " ", " valid alias ", "valid alias"]
        self.assertEqual(concept_from_api(row), concept(aliases=["valid alias"]))

    def test_obsolete_wrong_class_or_missing_english_rejected(self) -> None:
        variants = []
        original = api_row(concept())
        for key, value in (
            ("status", "obsolete"),
            ("className", "Occupation"),
            ("preferredLabel", {"de": "x"}),
        ):
            row = deepcopy(original)
            row[key] = value
            variants.append(row)
        for row in variants:
            with self.subTest(row=row), self.assertRaises(ValueError):
                concept_from_api(row)

    def test_concept_strict_schema_and_types(self) -> None:
        original = concept()
        bad = []
        for key, value in (
            ("id", "https://unrelated.example/skill/1"),
            ("id", SKILL_PREFIX + "not-a-uuid"),
            ("preferred_label", " "),
            ("aliases", "not a list"),
            ("aliases", [None]),
            ("aliases", ["duplicate", "duplicate"]),
        ):
            row = deepcopy(original)
            row[key] = value
            bad.append(row)
        bad.append({**original, "unexpected": "value"})
        for row in bad:
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate_concept(row)

    def test_normalization_and_ambiguity_counts_preserve_all_concepts(self) -> None:
        rows = [concept(1, "Ｆｏｏ", ["Foo", " shared alias "]), concept(2, "bar", ["SHARED   ALIAS"])]
        stats = vocabulary_statistics(rows)
        self.assertEqual(normalize_label(" ＦＯＯ  \n bar "), "foo bar")
        self.assertEqual(stats["concepts"], 2)
        self.assertEqual(stats["ambiguous_normalized_labels"], 1)
        self.assertEqual(stats["concepts_with_ambiguous_labels"], 2)
        self.assertEqual(stats["duplicate_normalized_labels_within_concept"], 1)

    def test_page_complete_and_consistent(self) -> None:
        rows = [concept(1), concept(2)]
        parsed, total = parse_page(page(rows), offset=0, limit=2)
        self.assertEqual((parsed, total), (rows, 2))
        tail, total = parse_page(page([concept(3)], offset=1, total=3), offset=1, limit=2, total=3)
        self.assertEqual((tail, total), ([concept(3)], 3))
        for raw, offset, limit, expected_total in (
            (page(rows), 1, 2, None),
            (page(rows), 0, 1, None),
            (page(rows), 0, 2, 3),
            (page(rows, total=3), 0, 2, 2),
            (page([concept(1)], total=2), 0, 2, 2),
        ):
            with self.subTest(offset=offset, limit=limit), self.assertRaises(ValueError):
                parse_page(raw, offset=offset, limit=limit, total=expected_total)

    def test_download_freeze_loader_cache_and_checksum(self) -> None:
        rows = [concept(1), concept(2), concept(3)]
        pages = [page(rows[:2], total=3), page(rows[2:], offset=1, total=3)]
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("scripts.esco_source._fetch", side_effect=pages) as fetch,
        ):
            output = Path(temp)
            metadata = download_source(output, limit=2, workers=1)
            loaded, provenance = load_source(output)
            self.assertEqual(loaded, rows)
            self.assertEqual(metadata, provenance)
            self.assertEqual(len(metadata["pages"]), 2)
            self.assertEqual(metadata["pages"][0]["sha256"], sha256(pages[0]))
            self.assertIn("selectedVersion=v1.2.0", fetch.call_args_list[1].args[0])
            self.assertEqual(download_source(output, limit=2, workers=1), metadata)
            self.assertEqual(fetch.call_count, 2)
            (output / "english-skills.jsonl").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_source(output)

    def test_duplicate_concept_across_pages_rejected(self) -> None:
        pages = [page([concept(1), concept(2)], total=3), page([concept(1)], offset=1, total=3)]
        with tempfile.TemporaryDirectory() as temp, patch("scripts.esco_source._fetch", side_effect=pages):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                download_source(Path(temp), limit=2, workers=1)
            self.assertFalse((Path(temp) / "manifest.json").exists())

    def test_loader_rejects_manifest_tampering_and_traversal(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            patch("scripts.esco_source._fetch", return_value=page([concept()])),
        ):
            directory = Path(temp)
            download_source(directory, limit=2, workers=1)
            original = json.loads((directory / "manifest.json").read_bytes())
            for field, value in (("version", "latest"), ("data_file", "../outside.jsonl"), ("api_total", 2)):
                bad = {**original, field: value}
                (directory / "manifest.json").write_bytes(canonical_bytes(bad))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    load_source(directory)


if __name__ == "__main__":
    unittest.main()
