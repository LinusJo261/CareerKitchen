"""PostgreSQL read-only export boundaries; all database fixtures are fictional."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from app.db.models import MatchingObservation, PairCycle
from app.services.common import utcnow
from app.services.matching_learning import export_observations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from scripts.export_matching_outcomes import export_dataset


def test_outcome_export_uses_a_read_only_repeatable_database_snapshot(engine, tmp_path):
    def inspect_transaction(db, **kwargs):
        assert db.scalar(text("SHOW transaction_read_only")) == "on"
        assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        return {
            "rows": [],
            "diagnostics": {"exported_resolutions": 0},
            "consent_source_version": "fictional-read-only-test",
        }

    with patch("app.services.matching_learning.export_observations", side_effect=inspect_transaction):
        summary = export_dataset(engine, tmp_path / "export", environment="test")
    assert summary["row_count"] == 0
    assert summary["source_kind"] == "fictional_fixture"


def test_database_rejects_accidental_export_mutation_and_publishes_no_files(engine, tmp_path):
    def accidental_mutation(db, **kwargs):
        db.execute(text("CREATE TABLE fictional_export_mutation (id integer)"))

    with patch("app.services.matching_learning.export_observations", side_effect=accidental_mutation):
        with pytest.raises(DBAPIError):
            export_dataset(engine, tmp_path / "export", environment="test")
    assert not (tmp_path / "export").exists()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('fictional_export_mutation')")) is None


def test_window_filters_before_row_limit_and_keeps_global_diagnostics(market, tmp_path):
    cutoff = utcnow() - timedelta(days=1)
    with Session(market.engine) as db, db.begin():
        for index, created in enumerate((cutoff - timedelta(days=2), cutoff - timedelta(days=1), cutoff)):
            cycle = PairCycle(
                candidate_id=market.candidate.id,
                vacancy_id=market.vacancy.id,
                role_version=1,
                cycle_number=index + 1,
                first_mover="CANDIDATE",
                state="CLOSED_PASSED",
                closed_at=created,
                created_at=created,
            )
            db.add(cycle)
            db.flush()
            # The candidate has never opted into learning. These explicitly
            # fictional stored rows exercise SQL window/count behavior only.
            db.add(
                MatchingObservation(
                    pair_cycle_id=cycle.id,
                    candidate_id=market.candidate.id,
                    vacancy_id=market.vacancy.id,
                    observation={},
                    created_at=created,
                )
            )
    with Session(market.engine) as db:
        with pytest.raises(ValueError, match="exceeds declared maximum"):
            export_observations(db, max_rows=1)
    summary = export_dataset(
        market.engine,
        tmp_path / "windowed-export",
        environment="test",
        max_rows=1,
        observed_since=cutoff.isoformat(),
    )
    assert summary["row_count"] == 0
    diagnostics = json.loads((tmp_path / "windowed-export" / "diagnostics.json").read_text())["counts"]
    assert diagnostics["stored_immutable_resolutions"] == 3
    assert diagnostics["stored_window_resolutions"] == 1
    assert diagnostics["outside_observation_window"] == 2
    assert diagnostics["excluded_current_consent_or_account"] == 1
    assert diagnostics["all_introductions"] == 3
    assert diagnostics["without_frozen_resolution"] == 0
    declaration = json.loads((tmp_path / "windowed-export" / "export_window.json").read_text())
    assert declaration["observation_created_at_gte"] == cutoff.isoformat()
    with Session(market.engine) as db:
        result = export_observations(db, max_rows=1, observed_since=cutoff + timedelta(seconds=1))
    assert result["diagnostics"]["stored_window_resolutions"] == 0
    assert result["diagnostics"]["stored_immutable_resolutions"] == 3
    assert result["diagnostics"]["without_frozen_resolution"] == 0
