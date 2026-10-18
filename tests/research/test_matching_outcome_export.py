"""Fictional observations test export plumbing, never real matching accuracy."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.export_matching_outcomes import export_dataset
from scripts.mutual_matching_features import EXPANDED_FEATURE_NAMES, FEATURE_NAMES


def fictional_result():
    features = dict.fromkeys(FEATURE_NAMES)
    features.update(
        {
            "preferred_skill_coverage": 0.5,
            "candidate_role_preference_alignment": 1,
            "candidate_work_mode_preference_alignment": 1,
            "candidate_employment_type_preference_alignment": 1,
        }
    )
    row = {
        "cycle_id": "1" * 64,
        "candidate_id": "2" * 64,
        "vacancy_id": "3" * 64,
        "organization_id": "4" * 64,
        "candidate_version": 1,
        "vacancy_version": 2,
        "feature_as_of": "2000-01-01T00:00:00Z",
        "first_exposed_at": "2000-01-01T00:00:01Z",
        "first_mover": "candidate",
        "policy_version": "fictional-fixed-policy-v1",
        "eligibility": "ELIGIBLE",
        "observation_status": "OBSERVABLE",
        "observed_at": "2000-01-02T00:00:01Z",
        "features": features,
        "decisions": {
            "candidate": {
                "status": "PASSED",
                "issued_at": "2000-01-01T00:00:01Z",
                "answered_at": "2000-01-02T00:00:00Z",
            },
            "employer": {"status": "NOT_ISSUED", "issued_at": None, "answered_at": None},
        },
    }
    return {
        "rows": [row],
        "consent_source_version": "fictional-consent-epoch-v1",
        "diagnostics": {
            "stored_immutable_resolutions": 1,
            "exported_resolutions": 1,
            "excluded": {"current_consent": 0},
            "without_frozen_resolution": 3,
        },
    }


class MatchingOutcomeExportTests(unittest.TestCase):
    def setUp(self):
        workspace = Path(__file__).resolve().parents[2] / ".local"
        workspace.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="outcome-export-test-", dir=workspace)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def export(self, result=None, *, environment="test", **kwargs):
        result = fictional_result() if result is None else result
        with patch("scripts.export_matching_outcomes._read_observations", return_value=result) as read:
            summary = export_dataset(
                self.engine, self.directory / "export", environment=environment, **kwargs
            )
        return summary, read

    def test_export_preserves_frozen_values_and_writes_native_manifest(self):
        result = fictional_result()
        before = deepcopy(result)
        summary, read = self.export(result, horizon_days=21, max_rows=125)
        read.assert_called_once_with(self.engine, 21, 125)
        self.assertEqual(result, before)
        self.assertEqual(summary["row_count"], 1)
        rows = [json.loads(line) for line in Path(summary["input_path"]).read_text().splitlines()]
        expected = deepcopy(before["rows"])
        expected[0]["features"].update(
            {name: None for name in EXPANDED_FEATURE_NAMES if name not in FEATURE_NAMES}
        )
        expected[0]["feature_provenance"] = {"text_relevance_model_id": None}
        self.assertEqual(rows, expected)
        manifest = json.loads(Path(summary["manifest_path"]).read_text())
        self.assertEqual(
            set(manifest), {"schema_version", "target", "feature_version", "horizon_days", "source"}
        )
        self.assertEqual(manifest["horizon_days"], 21)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["feature_version"], "mutual-pair-features-v2")
        self.assertEqual(manifest["source"]["kind"], "fictional_fixture")
        self.assertEqual(manifest["source"]["source_version"], result["consent_source_version"])
        self.assertEqual(manifest["source"]["dataset"], "career-kitchen-consented-introductions")
        diagnostics = json.loads(Path(summary["diagnostics_path"]).read_text())
        self.assertEqual(diagnostics, {"exported_rows": 1, "counts": result["diagnostics"]})

    def test_only_explicit_production_environment_is_marked_observed(self):
        for environment in ("development", "test", "staging", "production"):
            with self.subTest(environment=environment):
                output = self.directory / environment
                with patch(
                    "scripts.export_matching_outcomes._read_observations", return_value=fictional_result()
                ):
                    summary = export_dataset(self.engine, output, environment=environment)
                expected = (
                    "observed_introduction_outcomes" if environment == "production" else "fictional_fixture"
                )
                self.assertEqual(summary["source_kind"], expected)

    def test_existing_output_is_immutable_and_prevents_database_read(self):
        output = self.directory / "export"
        output.mkdir()
        marker = output / "preserve.txt"
        marker.write_text("fictional marker")
        with patch("scripts.export_matching_outcomes._read_observations") as read:
            with self.assertRaises(FileExistsError):
                export_dataset(self.engine, output, environment="test")
            read.assert_not_called()
        self.assertEqual(marker.read_text(), "fictional marker")

    def test_empty_export_publishes_zero_rows_and_diagnostics_without_training_claim(self):
        result = fictional_result()
        result["rows"] = []
        result["diagnostics"] = {"stored_immutable_resolutions": 0, "exported_resolutions": 0}
        summary, _ = self.export(result)
        self.assertEqual(summary["row_count"], 0)
        self.assertEqual(Path(summary["input_path"]).read_text(), "")
        self.assertNotIn("accuracy", Path(summary["diagnostics_path"]).read_text())
        self.assertIsNone(summary["observed_since"])
        self.assertIsNone(json.loads(Path(summary["window_path"]).read_text())["observation_created_at_gte"])

    def test_optional_window_is_normalized_declared_and_does_not_change_native_manifest(self):
        summary, read = self.export(observed_since="2000-01-01T03:00:00+03:00")
        since = datetime(2000, 1, 1, tzinfo=UTC)
        read.assert_called_once_with(self.engine, 14, 10000, observed_since=since)
        self.assertEqual(summary["observed_since"], since.isoformat())
        declaration = json.loads(Path(summary["window_path"]).read_text())
        self.assertEqual(declaration["observation_created_at_gte"], since.isoformat())
        manifest = json.loads(Path(summary["manifest_path"]).read_text())
        self.assertEqual(
            set(manifest), {"schema_version", "target", "feature_version", "horizon_days", "source"}
        )
        self.assertEqual(manifest["source"]["source_version"], "fictional-consent-epoch-v1")
        self.assertEqual(manifest["source"]["dataset"], "career-kitchen-consented-introductions")

    def test_aware_datetime_window_is_supported(self):
        since = datetime(2000, 1, 1, tzinfo=UTC)
        summary, read = self.export(observed_since=since)
        read.assert_called_once_with(self.engine, 14, 10000, observed_since=since)
        self.assertEqual(summary["observed_since"], since.isoformat())

    def test_available_text_relevance_requires_matching_immutable_lineage(self):
        for model_id in (None, "not-a-model-hash", "A" * 64):
            with self.subTest(model_id=model_id):
                result = fictional_result()
                result["rows"][0]["features"].update(
                    skill_precision=0.5, skill_jaccard=0.25, text_relevance=0.8
                )
                result["rows"][0]["feature_provenance"] = {"text_relevance_model_id": model_id}
                with self.assertRaises(ValueError):
                    self.export(result)
                assert not (self.directory / "export").exists()
        result["rows"][0]["feature_provenance"] = {"text_relevance_model_id": "a" * 64}
        summary, _ = self.export(result)
        row = json.loads(Path(summary["input_path"]).read_text())
        assert row["features"]["text_relevance"] == 0.8
        assert row["feature_provenance"] == {"text_relevance_model_id": "a" * 64}

    def test_ambiguous_or_malformed_windows_fail_before_read(self):
        for invalid in ("2000-01-01", "not-a-time", datetime(2000, 1, 1), True, {}):
            with (
                self.subTest(invalid=invalid),
                patch("scripts.export_matching_outcomes._read_observations") as read,
            ):
                with self.assertRaises(ValueError):
                    export_dataset(
                        self.engine, self.directory / "export", environment="test", observed_since=invalid
                    )
                read.assert_not_called()

    def test_bad_arguments_and_non_postgres_fail_before_read(self):
        with patch("scripts.export_matching_outcomes._read_observations") as read:
            for arguments in (
                {"environment": "unknown"},
                {"environment": "test", "horizon_days": True},
                {"environment": "test", "horizon_days": 0},
                {"environment": "test", "max_rows": 0},
                {"environment": "test", "max_rows": 100001},
            ):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    export_dataset(self.engine, self.directory / "export", **arguments)
            self.engine.dialect.name = "sqlite"
            with self.assertRaises(ValueError):
                export_dataset(self.engine, self.directory / "export", environment="test")
            read.assert_not_called()

    def test_raw_identities_extra_fields_and_future_snapshots_are_rejected(self):
        mutations = [
            lambda result: result["rows"][0].update(candidate_id="fictional-raw-database-id"),
            lambda result: result["rows"][0].update(private_resume="fictional private document"),
            lambda result: result["rows"][0].update(observed_at="2100-01-01T00:00:00Z"),
            lambda result: result["rows"][0]["features"].update(private_salary_floor=1),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                result = fictional_result()
                mutate(result)
                with self.assertRaises(ValueError):
                    self.export(result)
                self.assertFalse((self.directory / "export").exists())

    def test_duplicate_and_oversized_exports_fail_closed(self):
        result = fictional_result()
        result["rows"] *= 2
        with self.assertRaises(ValueError):
            self.export(result)
        result["rows"][1] = {**result["rows"][1], "cycle_id": "5" * 64}
        with self.assertRaises(ValueError):
            self.export(result, max_rows=1)
        self.assertFalse((self.directory / "export").exists())

    def test_diagnostics_cannot_export_raw_payloads_or_private_strings(self):
        result = fictional_result()
        result["diagnostics"]["raw_email"] = "fictional@example.invalid"
        with self.assertRaises(ValueError):
            self.export(result)
        self.assertFalse((self.directory / "export").exists())

    def test_partial_write_failure_does_not_publish_dataset_or_leave_staging(self):
        original_write = Path.write_text

        def fail_manifest(path, *args, **kwargs):
            if path.name == "manifest.json":
                raise OSError("fictional write failure")
            return original_write(path, *args, **kwargs)

        with patch.object(Path, "write_text", fail_manifest), self.assertRaises(OSError):
            self.export()
        self.assertFalse((self.directory / "export").exists())
        self.assertEqual(list(self.directory.glob(".matching-export-*")), [])

    def test_failed_read_does_not_publish_partial_artifacts(self):
        with patch(
            "scripts.export_matching_outcomes._read_observations", side_effect=RuntimeError("fictional error")
        ):
            with self.assertRaises(RuntimeError):
                export_dataset(self.engine, self.directory / "export", environment="test")
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
