"""Real isolated PostgreSQL controller checks; no observed matching accuracy."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.db.models import MatchingModel
from sqlalchemy.orm import Session

from scripts.continual_matching_learning import _lease, run_once


def test_database_lease_excludes_another_connection_and_releases(engine):
    with _lease(engine) as first:
        assert first
        with _lease(engine) as second:
            assert not second
    with _lease(engine) as later:
        assert later


def test_empty_outcome_store_waits_without_training_or_promotion(engine, tmp_path):
    status = run_once(engine, tmp_path / "controller", environment="test")
    assert status["status"] == "WAITING_FOR_NEW_OUTCOMES"
    assert status["source"]["stored_resolutions"] == 0
    assert status["production_accuracy"] is None
    assert status["promoted"] is False
    assert not (tmp_path / "controller" / "runs").exists()


def test_retired_registry_history_blocks_old_cohort_in_a_fresh_controller_directory(market, tmp_path):
    """Fabricated metadata tests the history query, never training or promotion."""
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    exported_at = (now - timedelta(days=20)).isoformat()
    with Session(market.engine) as db, db.begin():
        db.add(
            MatchingModel(
                model_key="a" * 64,
                # Deliberately minimal non-deployable fixture. The controller
                # reads export chronology, including retired registry history.
                artifact={"source": {"exported_at": exported_at}, "fictional_data": True},
                evaluation={"fixture_only": "no_observed_outcomes_or_qualified_model"},
                status="RETIRED",
                activated_by=market.users[2].id,
            )
        )
    output = tmp_path / "fresh-controller-volume"
    assert not output.exists()
    with patch("scripts.continual_matching_learning._refresh") as refresh:
        status = run_once(market.engine, output, environment="test", now=now)
    assert status["status"] == "WAITING_FOR_FRESH_COHORTS"
    assert status["source"]["latest_registered_export_at"] == exported_at
    assert status["production_accuracy"] is None
    assert status["promoted"] is False
    assert not (output / "controller_state.json").exists()
    assert not (output / "runs").exists()
    refresh.assert_not_called()
