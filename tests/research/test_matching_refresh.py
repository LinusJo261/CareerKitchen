"""Mocked orchestration checks; no observed outcomes or live database are invented."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import refresh_matching_learning as refresh_module


class MatchingRefreshTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / ".local"
        root.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "refresh"
        self.options = {
            "environment": "production",
            "train_before": "2025-01-01T00:00:00Z",
            "validate_before": "2026-01-01T00:00:00Z",
        }
        self.active = {
            "id": "fictional-registry-record",
            "model_key": "a" * 64,
            "artifact": {"model_id": "a" * 64, "test_fixture": "parameters_only_no_outcomes"},
        }

    def exported(self, *, rows=10, kind="observed_introduction_outcomes"):
        return {
            "row_count": rows,
            "source_kind": kind,
            "output": str(self.output / "input"),
            "input_path": str(self.output / "input" / "introductions.jsonl"),
            "manifest_path": str(self.output / "input" / "manifest.json"),
            "diagnostics_path": str(self.output / "input" / "diagnostics.json"),
        }

    def fake_train(self, *args, **kwargs):
        # This mock supplies control-flow metadata, never training rows or metrics.
        result = {"fictional_data": False, "evidence": {"eligible_for_review": True, "reasons": []}}
        output = args[2]
        output.mkdir()
        (output / "observed_model.json").write_text(json.dumps({"model_id": "b" * 64}))
        (output / "observed_report.json").write_text(json.dumps(result))
        return result

    def test_empty_observed_export_preserves_active_and_produces_no_model(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=self.active),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported(rows=0)),
            patch.object(refresh_module, "train") as fit,
            patch.object(refresh_module, "_promote") as promote,
        ):
            result = refresh_module.refresh(object(), self.output, **self.options, promote=True)
        assert result["status"] == "NOT_TRAINED"
        assert result["reason_codes"] == ["NO_EXPORTED_OBSERVATIONS"]
        assert not result["promoted"]
        assert not (self.output / "challenger").exists()
        assert json.loads((self.output / "incumbent_model.json").read_text()) == self.active["artifact"]
        fit.assert_not_called()
        promote.assert_not_called()

    def test_optional_observation_window_is_normalized_and_forwarded_before_export_limit(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=None),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported(rows=0)) as export,
        ):
            result = refresh_module.refresh(
                object(), self.output, **self.options, observed_since="2024-06-01T05:00:00+05:00"
            )
        assert export.call_args.kwargs["observed_since"] == "2024-06-01T00:00:00+00:00"
        assert result["observed_since"] == "2024-06-01T00:00:00+00:00"
        assert (
            json.loads((self.output / "refresh_status.json").read_text())["observed_since"]
            == result["observed_since"]
        )

    def test_no_window_keeps_full_export_contract_and_does_not_pass_new_keyword(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=None),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported(rows=0)) as export,
        ):
            result = refresh_module.refresh(object(), self.output, **self.options)
        assert "observed_since" not in export.call_args.kwargs
        assert result["observed_since"] is None

    def test_invalid_or_naive_observation_window_fails_before_database_access(self):
        for value in ("not-a-time", "2024-01-01", "2024-01-01T12:00:00"):
            with self.subTest(value=value), patch.object(refresh_module, "_read_active") as read:
                with self.assertRaises(ValueError):
                    refresh_module.refresh(object(), self.output, **self.options, observed_since=value)
                assert not self.output.exists()
                read.assert_not_called()

    def test_insufficient_forward_time_data_is_a_normal_nonpromotion(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=self.active),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported()),
            patch.object(
                refresh_module,
                "train",
                side_effect=ValueError("Empty evaluation split; obtain more observed pairs"),
            ),
            patch.object(refresh_module, "_promote") as promote,
        ):
            result = refresh_module.refresh(object(), self.output, **self.options, promote=True)
        assert result["status"] == "INSUFFICIENT_DATA"
        assert result["reason_codes"] == ["EMPTY_FORWARD_TIME_EVALUATION_SPLIT"]
        promote.assert_not_called()

    def test_training_does_not_promote_without_explicit_flag(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=None),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported()),
            patch.object(refresh_module, "train", side_effect=self.fake_train),
            patch.object(refresh_module, "_promote") as promote,
        ):
            result = refresh_module.refresh(object(), self.output, **self.options)
        assert result["status"] == "TRAINED_REVIEW_REQUIRED"
        assert not result["promoted"]
        promote.assert_not_called()

    def test_production_promote_passes_frozen_incumbent_for_atomic_compare_and_swap(self):
        events = []

        def read_active(engine):
            events.append("read")
            return self.active

        def export(engine, output, **options):
            events.append("export")
            return self.exported()

        with (
            patch.object(refresh_module, "_read_active", side_effect=read_active),
            patch.object(refresh_module, "_export_dataset", side_effect=export),
            patch.object(refresh_module, "train", side_effect=self.fake_train) as fit,
            patch.object(
                refresh_module, "_promote", return_value={"active": True, "model_id": "b" * 64, "version": 1}
            ) as promote,
        ):
            engine = object()
            result = refresh_module.refresh(engine, self.output, **self.options, promote=True)
        assert events == ["read", "export"]
        assert result["status"] == "PROMOTED"
        assert result["promoted"]
        assert fit.call_args.kwargs["incumbent_path"] == self.output / "incumbent_model.json"
        assert promote.call_args.args[3] == self.active["model_key"]

    def test_rejected_evidence_never_reaches_registry(self):
        def rejected_train(*args, **kwargs):
            result = self.fake_train(*args, **kwargs)
            result["evidence"] = {
                "eligible_for_review": False,
                "reasons": ["NO_CONFIDENT_TEST_GAIN_VS_INCUMBENT"],
            }
            return result

        with (
            patch.object(refresh_module, "_read_active", return_value=None),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported()),
            patch.object(refresh_module, "train", side_effect=rejected_train),
            patch.object(refresh_module, "_promote") as promote,
        ):
            result = refresh_module.refresh(object(), self.output, **self.options, promote=True)
        assert result["status"] == "PROMOTION_DECLINED"
        promote.assert_not_called()

    def test_nonproduction_promotion_is_rejected_before_reading_or_writing(self):
        for environment in ("development", "test", "staging"):
            with self.subTest(environment=environment), patch.object(refresh_module, "_read_active") as read:
                with self.assertRaisesRegex(ValueError, "production outcomes"):
                    refresh_module.refresh(
                        object(), self.output, **{**self.options, "environment": environment}, promote=True
                    )
                assert not self.output.exists()
                read.assert_not_called()

    def test_unexpected_promotion_error_reports_unknown_commit_without_logging_secrets(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=self.active),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported()),
            patch.object(refresh_module, "train", side_effect=self.fake_train),
            patch.object(
                refresh_module, "_promote", side_effect=ValueError("fictional-dsn-password-must-never-appear")
            ),
        ):
            result = refresh_module.refresh(object(), self.output, **self.options, promote=True)
        assert result["status"] == "PROMOTION_STATE_UNKNOWN"
        assert result["promoted"] is None
        assert (self.output / "challenger" / "observed_model.json").exists()
        assert "password" not in (self.output / "refresh_status.json").read_text()
        assert result["reason_codes"] == ["STEP_FAILED"]

    def test_definitive_registry_gate_rejection_stays_rejected_after_transaction_rollback(self):
        from app.core.errors import AppError

        with (
            patch.object(refresh_module, "_read_active", return_value=self.active),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported()),
            patch.object(refresh_module, "train", side_effect=self.fake_train),
            patch.object(
                refresh_module,
                "_promote",
                side_effect=AppError(409, "MODEL_VERSION_CONFLICT", "Sensitive detail is not exported"),
            ),
        ):
            result = refresh_module.refresh(object(), self.output, **self.options, promote=True)
        assert result["status"] == "PROMOTION_REJECTED"
        assert result["promoted"] is False
        assert result["reason_codes"] == ["MODEL_VERSION_CONFLICT"]
        assert "Sensitive detail" not in json.dumps(result)

    def test_status_write_failure_after_commit_is_not_reported_as_rollback(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=None),
            patch.object(refresh_module, "_export_dataset", return_value=self.exported()),
            patch.object(refresh_module, "train", side_effect=self.fake_train),
            patch.object(refresh_module, "_promote", return_value={"active": True, "model_id": "b" * 64}),
            patch.object(refresh_module, "_write_status", side_effect=OSError("fictional local disk error")),
        ):
            with self.assertRaisesRegex(RuntimeError, "promotion completed"):
                refresh_module.refresh(object(), self.output, **self.options, promote=True)

    def test_existing_refresh_directory_is_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "previous.txt"
        marker.write_text("fictional previous run")
        with patch.object(refresh_module, "_read_active") as read:
            with self.assertRaises(FileExistsError):
                refresh_module.refresh(object(), self.output, **self.options)
            read.assert_not_called()
        assert marker.read_text() == "fictional previous run"

    def test_export_errors_are_sanitized_and_reported_without_training(self):
        with (
            patch.object(refresh_module, "_read_active", return_value=None),
            patch.object(
                refresh_module,
                "_export_dataset",
                side_effect=RuntimeError("fictional private connection string"),
            ),
            patch.object(refresh_module, "train") as fit,
        ):
            result = refresh_module.refresh(object(), self.output, **self.options)
        assert result["status"] == "FAILED"
        assert result["failed_stage"] == "export"
        assert "private connection" not in json.dumps(result)
        fit.assert_not_called()
