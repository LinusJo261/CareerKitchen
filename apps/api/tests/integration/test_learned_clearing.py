"""Isolated PostgreSQL parameter fixtures exercise live inference, not real accuracy.

The registry rows below deliberately bypass promotion. Their qualification
metadata is a software fixture and supplies no observed outcome evidence.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from app.core.errors import AppError
from app.db.models import (
    Candidate,
    CandidateSkill,
    DecisionCard,
    MatchingModel,
    PairCycle,
    Requirement,
    Skill,
    User,
)
from app.matching.learning import FEATURE_NAMES, POPULATION, TARGET, artifact_hash
from app.services import clearing, matching_learning
from app.services.common import utcnow
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


def parameter_only_artifact():
    """Simulated registry metadata only; never promote this fixture or call it trained."""
    artifact = {
        "schema_version": 2,
        "artifact_kind": "reciprocal_logistic_challenger",
        "target": TARGET,
        "estimation_population": POPULATION,
        "feature_version": "reciprocal-structured-v1",
        "feature_names": list(FEATURE_NAMES),
        "transforms": [{"imputation_median": 0.5, "center": 0.5, "scale": 0.5} for _ in range(4)],
        # Deliberately invert preferred-skill utility to prove the actual scorer
        # affects selection. This coefficient is a test input, not a recommendation.
        "coefficients": [-3, 0, 0, 0, 0, 0, 0, 0],
        "intercept": 0,
        "calibration": {"kind": "identity", "slope": 1, "intercept": 0},
        "decision_threshold": 0.5,
        "horizon_days": 14,
        "fictional_data": False,
        "source": {
            "kind": "observed_introduction_outcomes",
            "dataset": "fictional_parameter_fixture_no_outcomes",
            "source_version": "fixture-only-bypass-promotion",
            "exported_at": (utcnow() - timedelta(hours=1)).isoformat(),
        },
        "provenance": {"input_sha256": "a" * 64, "manifest_sha256": "b" * 64, "test_cohort_sha256": "c" * 64},
        "evidence": {"eligible_for_review": True, "reasons": []},
    }
    artifact["model_id"] = artifact_hash(artifact)
    return artifact


def seed_registry_fixture(db, market, artifact):
    db.add(
        MatchingModel(
            model_key=artifact["model_id"],
            artifact=artifact,
            evaluation={"fixture_only": "no_observed_metrics_or_real_promotion"},
            status="ACTIVE",
            activated_by=market.users[2].id,
        )
    )
    db.flush()


def build_two_candidate_skill_market(db, market):
    first = db.get(Candidate, market.candidate.id)
    first.cap = 1
    user = User(issuer="fictional-learned-scoring", subject=str(uuid4()))
    db.add(user)
    db.flush()
    second = Candidate(
        user_id=user.id,
        headline="Fictional inference candidate",
        state="ACTIVE",
        cap=1,
        role_families=["ENGINEERING"],
        employment_types=["FULL_TIME"],
        work_modes=["REMOTE"],
        terms_accepted=True,
        privacy_accepted=True,
        confirmed_at=utcnow(),
    )
    db.add(second)
    skill = Skill(name="Fictional fixture skill", aliases=[])
    db.add(skill)
    db.flush()
    db.add(CandidateSkill(candidate_id=first.id, skill_id=skill.id, confirmed=True))
    db.add(
        Requirement(
            vacancy_id=market.vacancy.id,
            kind="PREFERENCE",
            key=skill.name,
            description="Fictional software-only preference",
        )
    )
    # Reserve nine receiving slots so exactly one first card fits the attention
    # ceiling. The candidates remain eligible, and their own capacities are one.
    from app.db.models import WaitingItem

    for _ in range(9):
        inactive_user = User(issuer="fictional-reserved-queue", subject=str(uuid4()))
        db.add(inactive_user)
        db.flush()
        inactive = Candidate(user_id=inactive_user.id, state="DRAFT", headline="Fictional queue fixture")
        db.add(inactive)
        db.flush()
        cycle = PairCycle(
            candidate_id=inactive.id,
            vacancy_id=market.vacancy.id,
            role_version=1,
            first_mover="CANDIDATE",
            state="WAITING_EMPLOYER_SLOT",
            candidate_interested_at=utcnow(),
        )
        db.add(cycle)
        db.flush()
        db.add(WaitingItem(pair_cycle_id=cycle.id, side="EMPLOYER", expires_at=utcnow() + timedelta(days=1)))
    db.flush()
    return first, second


def test_seeded_model_parameters_change_actual_selection_and_keep_frozen_native_inputs(market):
    with Session(market.engine) as db, db.begin():
        first, second = build_two_candidate_skill_market(db, market)
        artifact = parameter_only_artifact()
        seed_registry_fixture(db, market, artifact)
        issued = clearing.reconcile(db, market.actor(2), [market.vacancy.id])
        assert len(issued) == 1
        assert issued[0]["candidate_id"] == second.id
        assert issued[0]["candidate_id"] != first.id
        card = db.get(DecisionCard, issued[0]["decision_id"])
        cycle = db.get(PairCycle, card.pair_cycle_id)
        assert cycle.model_version == "ml-v2:" + artifact["model_id"]
        assert cycle.score_trace["learning"]["active"] is True
        assert cycle.score_trace["learning"]["estimation_population"] == POPULATION
        assert cycle.score_trace["learning_snapshot"]["employer_skills"] == 0
        assert cycle.score_trace["deterministic_relevance"] < cycle.score_trace["relevance"]
        assert clearing.receiving_count(db, "EMPLOYER", vacancy_id=market.vacancy.id) == 10
        assert clearing.reconcile(db, market.actor(2), [market.vacancy.id]) == []


@pytest.mark.parametrize("failure", ["fictional", "tampered", "stale"])
def test_unqualified_registry_parameters_fall_back_to_actual_deterministic_selection(market, failure):
    with Session(market.engine) as db, db.begin():
        first, second = build_two_candidate_skill_market(db, market)
        artifact = parameter_only_artifact()
        if failure == "fictional":
            artifact["fictional_data"] = True
            artifact["source"]["kind"] = "fictional_fixture"
            artifact["model_id"] = artifact_hash(artifact)
        elif failure == "stale":
            artifact["source"]["exported_at"] = "2000-01-01T00:00:00Z"
            artifact["model_id"] = artifact_hash(artifact)
        else:
            artifact["coefficients"][0] += 1
        seed_registry_fixture(db, market, artifact)
        issued = clearing.reconcile(db, market.actor(2), [market.vacancy.id])
        assert len(issued) == 1
        assert issued[0]["candidate_id"] == first.id
        assert issued[0]["candidate_id"] != second.id
        card = db.get(DecisionCard, issued[0]["decision_id"])
        cycle = db.get(PairCycle, card.pair_cycle_id)
        assert cycle.model_version == "reciprocal-compatibility-v1"
        assert cycle.score_trace["learning"]["active"] is False


def test_changed_model_between_planning_and_issuance_aborts_before_any_card(market, monkeypatch):
    with Session(market.engine) as db, db.begin():
        build_two_candidate_skill_market(db, market)
        artifact = parameter_only_artifact()
        seed_registry_fixture(db, market, artifact)
        original = matching_learning.current_scoring_model
        first_model, _ = original(db)
        assert first_model is not None
        outcomes = iter([(first_model, "OBSERVED_MODEL_ACTIVE"), (None, "NO_QUALIFIED_OBSERVED_MODEL")])
        monkeypatch.setattr(matching_learning, "current_scoring_model", lambda session: next(outcomes))
        with pytest.raises(AppError) as error, db.begin_nested():
            clearing.reconcile(db, market.actor(2), [market.vacancy.id])
        assert error.value.code == "MODEL_VERSION_CONFLICT"
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0


def test_real_loopback_export_refresh_with_no_outcomes_preserves_empty_registry(engine, tmp_path):
    from scripts.refresh_matching_learning import refresh

    result = refresh(
        engine,
        tmp_path / "empty-refresh",
        environment="development",
        train_before="2025-01-01T00:00:00Z",
        validate_before="2026-01-01T00:00:00Z",
    )
    assert result["status"] == "NOT_TRAINED"
    assert result["source_kind"] == "fictional_fixture"
    assert result["exported_rows"] == 0
    assert result["promoted"] is False
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(MatchingModel)) == 0
