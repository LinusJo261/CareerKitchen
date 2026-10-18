"""Fictional fixtures verify the public-data boundary, never real match outcomes."""

import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from scripts import talentclef_source as source


def fixture(directory, *, qrels="101 0 1 1\n102 0 2 1\n", extra=None):
    archive = directory / "TaskA.zip"
    files = {
        source.PREFIX + "queries/101": "PRIVATE_FICTIONAL_JOB_ONE",
        source.PREFIX + "queries/102": "PRIVATE_FICTIONAL_JOB_TWO",
        source.PREFIX + "corpus/1": "PRIVATE_FICTIONAL_RESUME_ONE",
        source.PREFIX + "corpus/2": "PRIVATE_FICTIONAL_RESUME_TWO",
        source.PREFIX + "corpus/3": "PRIVATE_FICTIONAL_RESUME_THREE",
        source.PREFIX + "qrels.tsv": qrels,
    }
    files.update(extra or {})
    with zipfile.ZipFile(archive, "w") as output:
        for name, text in files.items():
            output.writestr(name, text)
    data = archive.read_bytes()
    checksum = hashlib.md5(data, usedforsecurity=False).hexdigest()
    record = {
        "id": source.RECORD_ID,
        "metadata": {"version": source.VERSION, "license": {"id": "cc-by-4.0"}, "access_right": "open"},
        "files": [{"key": "TaskA.zip", "checksum": f"md5:{checksum}", "size": len(data)}],
    }
    (directory / source.METADATA_FILENAME).write_text(json.dumps(record), encoding="utf-8")
    stack = ExitStack()
    stack.enter_context(mock.patch.object(source, "ARCHIVE_SIZE", len(data)))
    stack.enter_context(mock.patch.object(source, "ARCHIVE_MD5", checksum))
    stack.enter_context(mock.patch.object(source, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()))
    stack.enter_context(
        mock.patch.object(
            source,
            "INVENTORY_COUNTS",
            {
                source.PREFIX + "queries/": 2,
                source.PREFIX + "corpus/": 3,
                source.PREFIX + "qrels.tsv": 1,
            },
        )
    )
    return archive, stack


class QrelsTests(unittest.TestCase):
    jobs = {"10": "fictional vacancy", "20": "fictional second vacancy"}
    resumes = {"1": "fictional resume", "2": "fictional second resume", "3": "fictional third resume"}

    def test_positive_only_sparse_judgments_never_fill_unknowns(self):
        result = source.parse_qrels("10\t0\t1\t1\n20 0 2 1\n", self.jobs, self.resumes)
        self.assertEqual(result, {"10": {"1": 1}, "20": {"2": 1}})
        self.assertNotIn("3", result["10"])
        self.assertEqual(sum(len(value) for value in result.values()), 2)

    def test_explicit_negative_is_preserved(self):
        result = source.parse_qrels("10 0 1 0\n20 0 2 1", self.jobs, self.resumes)
        self.assertEqual(result["10"]["1"], 0)

    def test_duplicate_and_contradictory_judgments_are_rejected(self):
        for label in ("0", "1"):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "Duplicate"):
                source.parse_qrels(f"10 0 1 1\n10 0 1 {label}\n20 0 2 1", self.jobs, self.resumes)

    def test_unknown_query_or_resume_is_rejected(self):
        for row in ("30 0 1 1", "10 0 99 1"):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "Unknown"):
                source.parse_qrels(row, self.jobs, self.resumes)

    def test_malformed_labels_columns_and_iteration_are_rejected(self):
        for row in ("10 0 1 2", "10 0 1 True", "10 1 1 1", "10 0 1", "10 0 1 1 extra"):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "Malformed"):
                source.parse_qrels(row, self.jobs, self.resumes)

    def test_source_query_with_no_judgments_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "Every source query"):
            source.parse_qrels("10 0 1 1", self.jobs, self.resumes)


class SourceTests(unittest.TestCase):
    def test_load_preserves_text_locally_and_reports_no_genuine_negative_accuracy(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, patches = fixture(Path(temporary))
            with patches:
                jobs, resumes, qrels, provenance = source.load_source(path)
            self.assertEqual((len(jobs), len(resumes), len(qrels)), (2, 3, 2))
            self.assertEqual(provenance["explicit_positive_judgments"], 2)
            self.assertEqual(provenance["explicit_negative_judgments"], 0)
            self.assertEqual(provenance["unjudged_pairs"], 4)
            self.assertEqual(provenance["judgment_coverage"], 1 / 3)
            self.assertEqual(provenance["fully_judged_query_count"], 0)
            self.assertFalse(provenance["native_confirmed_structured_skills_available"])
            self.assertNotIn("PRIVATE_FICTIONAL", json.dumps(provenance))
            self.assertEqual(len(provenance["all_file_sha256"]), 6)

    def test_metadata_license_version_and_provider_checksum_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path, patches = fixture(directory)
            metadata = directory / source.METADATA_FILENAME
            original = json.loads(metadata.read_text())
            with patches:
                source.load_source(path)
                for change in ("license", "version", "checksum", "size", "record", "access"):
                    record = json.loads(json.dumps(original))
                    if change == "license":
                        record["metadata"]["license"] = {"id": "unknown"}
                    elif change == "version":
                        record["metadata"]["version"] = "latest"
                    elif change == "checksum":
                        record["files"][0]["checksum"] = "md5:changed"
                    elif change == "size":
                        record["files"][0]["size"] = True
                    elif change == "record":
                        record["id"] = True
                    else:
                        record["metadata"]["access_right"] = "closed"
                    metadata.write_text(json.dumps(record))
                    with self.subTest(change=change), self.assertRaises(ValueError):
                        source.load_source(path)

    def test_archive_size_md5_and_sha256_all_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, patches = fixture(Path(temporary))
            with patches:
                data = path.read_bytes()
                for field, value, message in (
                    ("ARCHIVE_SIZE", len(data) + 1, "size"),
                    ("ARCHIVE_MD5", "0" * 32, "MD5"),
                    ("ARCHIVE_SHA256", "0" * 64, "SHA256"),
                ):
                    with (
                        self.subTest(field=field),
                        mock.patch.object(source, field, value),
                        self.assertRaisesRegex(ValueError, message),
                    ):
                        source._validate_archive(data)

    def test_unexpected_entries_and_traversal_rejected_without_extraction(self):
        for name in (
            "TaskA/development/en/corpus/../../escape",
            "TaskA/development/en/corpus/not-a-numeric-id",
            "TaskA/unexpected.py",
            "C:\\escape",
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path, patches = fixture(Path(temporary), extra={name: "fictional"})
                with patches, self.assertRaises(ValueError):
                    source.load_source(path)
                self.assertFalse((Path(temporary) / "escape").exists())

    def test_duplicate_zip_and_symlink_entries_rejected(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                path, patches = fixture(directory)
                with patches:
                    with zipfile.ZipFile(path, "a") as archive:
                        info = zipfile.ZipInfo(source.PREFIX + "corpus/4")
                        if symlink:
                            info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        else:
                            info.filename = source.PREFIX + "corpus/1"
                        with self.assertWarns(UserWarning) if not symlink else ExitStack():
                            archive.writestr(info, "fictional")
                    with zipfile.ZipFile(path) as archive, self.assertRaises(ValueError):
                        source._inventory(archive)

    def test_download_does_not_overwrite_source_or_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, patches = fixture(Path(temporary))
            with patches, mock.patch.object(source, "_curl") as fetch, self.assertRaises(FileExistsError):
                source.download_source(path)
            fetch.assert_not_called()

    def test_failed_download_does_not_publish_either_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with (
                mock.patch.object(source, "_curl", side_effect=RuntimeError("offline")),
                self.assertRaises(RuntimeError),
            ):
                source.download_source(directory / "TaskA.zip")
            self.assertEqual(list(directory.iterdir()), [])

    def test_download_validates_then_publishes_both_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, patches = fixture(directory)
            data = archive.read_bytes()
            metadata = (directory / source.METADATA_FILENAME).read_bytes()
            target = directory / "published" / "TaskA.zip"

            def fetch(url, destination, maximum):
                destination.write_bytes(metadata if url == source.METADATA_URL else data)

            with patches, mock.patch.object(source, "_curl", side_effect=fetch):
                source.download_source(target)
                self.assertEqual(target.read_bytes(), data)
                self.assertEqual((target.parent / source.METADATA_FILENAME).read_bytes(), metadata)
                source.load_source(target)


if __name__ == "__main__":
    unittest.main()
