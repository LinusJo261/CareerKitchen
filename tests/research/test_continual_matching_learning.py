"""Fictional controller inputs verify scheduling and gates, never accuracy."""

import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts import continual_matching_learning as controller

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


@contextmanager
def lease(acquired=True):
    yield acquired


class ControllerTests(unittest.TestCase):
    def run_fixture(self, path, *, count=1000, registered=None, **options):
        source = {"stored_resolutions": count, "consent_epoch": 3, "latest_registered_export_at": registered}
        with (
            patch.object(controller, "_lease", side_effect=lambda engine: lease()),
            patch.object(controller, "_source_state", return_value=source),
        ):
            return controller.run_once(object(), path, environment="test", now=NOW, **options)

    def test_empty_database_waits_without_export_or_invented_accuracy(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(controller, "_refresh") as refresh:
            result = self.run_fixture(Path(temporary), count=0)
            self.assertEqual(result["status"], "WAITING_FOR_NEW_OUTCOMES")
            self.assertIsNone(result["production_accuracy"])
            self.assertFalse(result["promoted"])
            refresh.assert_not_called()

    def test_counts_only_trigger_existing_refresh_not_model_qualification(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(
                controller, "_refresh", return_value={"status": "CHALLENGER_REJECTED", "promoted": False}
            ) as refresh,
        ):
            result = self.run_fixture(Path(temporary))
            self.assertEqual(result["status"], "REFRESH_COMPLETED")
            self.assertEqual(result["refresh"]["status"], "CHALLENGER_REJECTED")
            self.assertFalse(result["promoted"])
            options = refresh.call_args.kwargs
            self.assertFalse(options["promote"])
            self.assertEqual(options["train_before"], "2026-08-05T00:00:00+00:00")
            self.assertEqual(options["validate_before"], "2026-09-04T00:00:00+00:00")
            self.assertEqual(options["observed_since"], "2025-10-18T00:00:00+00:00")

    def test_lease_contention_does_not_read_labels_or_replace_other_status(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(controller, "_lease", side_effect=lambda engine: lease(False)),
            patch.object(controller, "_source_state") as source,
        ):
            root = Path(temporary)
            result = controller.run_once(object(), root, environment="test", now=NOW)
            self.assertEqual(result["status"], "ANOTHER_REFRESH_RUNNING")
            source.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_even_failed_attempt_reserves_cohort_before_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def failure(*args, **kwargs):
                state = json.loads((root / "controller_state.json").read_text())
                self.assertEqual(state["last_evaluation_at"], NOW.isoformat())
                raise RuntimeError("SENSITIVE_DATABASE_URL_OR_RAW_RECORD")

            with patch.object(controller, "_refresh", side_effect=failure) as refresh:
                result = self.run_fixture(root)
                self.assertEqual(result["status"], "REFRESH_STATE_UNKNOWN")
                self.assertIsNone(result["promoted"])
                self.assertNotIn("SENSITIVE", json.dumps(result))
                result = self.run_fixture(root, count=2000)
                self.assertEqual(result["status"], "WAITING_FOR_FRESH_COHORTS")
                self.assertEqual(refresh.call_count, 1)

    def test_insufficient_data_keeps_prior_holdout_boundary_and_waits_for_new_batch(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(
                controller, "_refresh", return_value={"status": "INSUFFICIENT_DATA", "promoted": False}
            ) as refresh,
        ):
            root = Path(temporary)
            self.run_fixture(root)
            state = json.loads((root / "controller_state.json").read_text())
            self.assertIsNone(state["last_evaluation_at"])
            self.assertEqual(state["resolution_count_at_evaluation"], 1000)
            result = self.run_fixture(root, count=1050)
            self.assertEqual(result["status"], "WAITING_FOR_NEW_OUTCOMES")
            self.run_fixture(root, count=1100)
            self.assertEqual(refresh.call_count, 2)

    def test_structured_uncertain_commit_never_claims_no_promotion(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(
                controller, "_refresh", return_value={"status": "PROMOTION_STATE_UNKNOWN", "promoted": None}
            ),
        ):
            root = Path(temporary)
            result = self.run_fixture(root)
            self.assertEqual(result["status"], "REFRESH_STATE_UNKNOWN")
            self.assertIsNone(result["promoted"])
            self.assertEqual(
                json.loads((root / "controller_state.json").read_text())["last_evaluation_at"],
                NOW.isoformat(),
            )

    def test_retired_registered_history_blocks_old_holdout_after_local_state_loss(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(controller, "_refresh") as refresh:
            result = self.run_fixture(Path(temporary), registered=(NOW - timedelta(days=20)).isoformat())
            self.assertEqual(result["status"], "WAITING_FOR_FRESH_COHORTS")
            refresh.assert_not_called()

    def test_waits_for_new_resolutions_after_an_earlier_window(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(controller, "_refresh") as refresh:
            root = Path(temporary)
            controller._atomic_json(
                root / "controller_state.json",
                {
                    "schema_version": 1,
                    "last_evaluation_at": (NOW - timedelta(days=100)).isoformat(),
                    "resolution_count_at_evaluation": 1000,
                },
            )
            result = self.run_fixture(root, count=1050)
            self.assertEqual(result["status"], "WAITING_FOR_NEW_OUTCOMES")
            self.assertEqual(result["new_resolution_count"], 50)
            refresh.assert_not_called()

    def test_corrupt_or_future_local_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(controller, "_refresh") as refresh:
            root = Path(temporary)
            (root / "controller_state.json").write_text('{"schema_version":true}')
            with self.assertRaises(ValueError):
                self.run_fixture(root)
            refresh.assert_not_called()

    def test_promotion_requires_explicit_production_request_before_reading_source(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(controller, "_source_state") as source:
            with self.assertRaises(ValueError):
                controller.run_once(object(), Path(temporary), environment="test", now=NOW, promote=True)
            source.assert_not_called()

    def test_production_option_is_forwarded_to_qualified_refresh_only(self):
        source = {"stored_resolutions": 1000, "consent_epoch": 3, "latest_registered_export_at": None}
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(controller, "_lease", side_effect=lambda engine: lease()),
            patch.object(controller, "_source_state", return_value=source),
            patch.object(
                controller, "_refresh", return_value={"promoted": True, "status": "PROMOTED"}
            ) as refresh,
        ):
            result = controller.run_once(
                object(), Path(temporary), environment="production", now=NOW, promote=True
            )
            self.assertTrue(refresh.call_args.kwargs["promote"])
            self.assertTrue(result["promoted"])

    def test_invalid_windows_types_and_limits_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for options in (
                {"min_new_resolutions": True},
                {"min_new_resolutions": 99},
                {"validation_days": 0},
                {"horizon_days": 366},
                {"training_window_days": 74},
                {"max_rows": 100001},
            ):
                with self.subTest(options=options), self.assertRaises(ValueError):
                    self.run_fixture(Path(temporary), **options)
