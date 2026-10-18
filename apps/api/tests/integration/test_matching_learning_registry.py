"""Fabricated qualification metadata tests software gates, never real accuracy.

The declared observed sources and confidence intervals below are deliberately
invented local contract fixtures. No artifact from this file may be deployed or
reported as an empirical hiring/model result.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

import pytest
from app.core.errors import AppError
from app.db.models import (
    Candidate,
    DecisionCard,
    Exposure,
    MatchingModel,
    MatchingObservation,
    PairCycle,
)
from app.matching.learning import FEATURE_NAMES, POPULATION, TARGET, artifact_hash
from app.services import matching_learning as learning
from app.services.common import lock_scopes, utcnow
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


def qualification_fixture(source_version="career-kitchen-learning-consent-v0", tag="first", incumbent=None):
    """A fabricated report for registry mechanics, with no real observed data."""
    now = utcnow().replace(microsecond=0)
    exported = now - timedelta(days=1) if incumbent is None else now - timedelta(hours=1)
    before_train = exported - timedelta(days=10) if incumbent is None else now - timedelta(hours=23)
    before_validation = exported - timedelta(days=5) if incumbent is None else now - timedelta(hours=12)
    artifact = {
        "schema_version": 2,
        "artifact_kind": "reciprocal_logistic_challenger",
        "target": TARGET,
        "estimation_population": POPULATION,
        "feature_version": "reciprocal-structured-v1",
        "feature_names": list(FEATURE_NAMES),
        "transforms": [{"imputation_median": 0.5, "center": 0.5, "scale": 0.5} for _ in range(4)],
        "coefficients": [1, 0] * 4,
        "intercept": 0,
        "calibration": {"kind": "identity", "slope": 1, "intercept": 0},
        "decision_threshold": 0.5,
        "horizon_days": 14,
        "fictional_data": False,
        "source": {
            "kind": "observed_introduction_outcomes",
            "dataset": "FICTIONAL-REGISTRY-CONTRACT-FIXTURE",
            "source_version": source_version,
            "exported_at": exported.isoformat(),
        },
        "provenance": {
            **{
                name: sha256(f"fictional-{tag}-{name}".encode()).hexdigest()
                for name in ("input_sha256", "manifest_sha256", "test_cohort_sha256")
            },
            "incumbent_model_id": incumbent,
            "selection": {"training_converged": True},
            "split": {
                "train_before": before_train.isoformat(),
                "validate_before": before_validation.isoformat(),
                "counts": {"train": 100, "validation": 100, "test": 100},
                "class_counts": {
                    name: {"positives": 50, "negatives": 50} for name in ("train", "validation", "test")
                },
            },
        },
        "evidence": {"eligible_for_review": True, "reasons": []},
    }
    comparison = {
        "cluster_count": 30,
        "by_scope": {"organization_id": {"cluster_count": 30}},
        "log_loss_delta_95": [-0.04, -0.01],
        "brier_delta_95": [-0.03, -0.001],
    }
    baselines = ["training_prevalence", "current_compatibility", "fitted_compatibility"]
    if incumbent:
        baselines.append("incumbent")
    report = {
        "schema_version": 2,
        "target": TARGET,
        "fictional_data": False,
        "organization_overlap": {name: 0 for name in ("train_validation", "train_test", "validation_test")},
        "evaluation": {
            name: {
                "challenger": {"count": 100, "positives": 50},
                "paired_comparisons": {baseline: deepcopy(comparison) for baseline in baselines},
            }
            for name in ("validation", "test")
        },
        "evidence": {"eligible_for_review": True, "reasons": []},
    }
    return synchronize(artifact, report)


def synchronize(artifact, report):
    artifact["model_id"] = artifact_hash(artifact)
    report.update(
        {
            "model_id": artifact["model_id"],
            "source": deepcopy(artifact["source"]),
            "provenance": deepcopy(artifact["provenance"]),
        }
    )
    return artifact, report


def activate(market, artifact, report, incumbent=None, key=None):
    return market.call(
        2,
        "POST",
        "/internal/matching/model",
        {"artifact": artifact, "evaluation": report, "expected_active_model_id": incumbent},
        key=key,
    )


def enable_learning(market):
    for actor, path in (
        (0, "/candidates/me/learning-consent"),
        (1, f"/organizations/{market.org.id}/learning-consent"),
    ):
        current = market.call(actor, "GET", path).json()["data"]
        response = market.call(actor, "PUT", path, {"enabled": True, "expected_version": current["version"]})
        assert response.status_code == 200, response.text


def resolve(market, *, interested=False):
    issued = market.call(2, "POST", "/internal/reconcile")
    assert issued.status_code == 200, issued.text
    first_id = issued.json()["data"]["issued"][0]["decision_id"]
    first = market.call(0, "GET", f"/decisions/{first_id}").json()["data"]
    answer = market.call(
        0,
        "POST",
        f"/decisions/{first_id}/{'interested' if interested else 'pass'}",
        {"expected_cycle_version": first["cycle_version"], "decision_token": first["decision_token"]},
    )
    assert answer.status_code == 200, answer.text
    if interested:
        with Session(market.engine) as db:
            assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 0
            second_id = db.scalar(
                select(DecisionCard.id).where(
                    DecisionCard.status == "ACTIVE", DecisionCard.side == "EMPLOYER"
                )
            )
        second = market.call(1, "GET", f"/decisions/{second_id}").json()["data"]
        response = market.call(
            1,
            "POST",
            f"/decisions/{second_id}/interested",
            {"expected_cycle_version": second["cycle_version"], "decision_token": second["decision_token"]},
        )
        assert response.status_code == 200, response.text


def test_registry_activation_replacement_retirement_and_no_retired_reactivation(market):
    artifact, report = qualification_fixture()
    first = activate(market, artifact, report, key="fabricated-registry-activation")
    assert first.status_code == 200, first.text
    assert first.json()["data"] == {"active": True, "model_id": artifact["model_id"], "version": 1}
    replay = activate(market, artifact, report, key="fabricated-registry-activation")
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    challenger, challenger_report = qualification_fixture(tag="replacement", incumbent=artifact["model_id"])
    assert activate(market, challenger, challenger_report).status_code == 409
    replacement = activate(market, challenger, challenger_report, incumbent=artifact["model_id"])
    assert replacement.status_code == 200, replacement.text
    retired = market.call(
        2,
        "POST",
        "/internal/matching/model/retire",
        {
            "expected_active_model_id": challenger["model_id"],
            "reason": "Fabricated rollback integration fixture",
        },
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["data"]["active"] is False
    assert activate(market, challenger, challenger_report).status_code == 409
    with Session(market.engine) as db:
        models = list(db.scalars(select(MatchingModel)))
        assert len(models) == 2
        assert {row.status for row in models} == {"RETIRED"}
        assert {row.version for row in models} == {2}


def test_revocation_retires_active_model_and_stale_export_epoch_cannot_promote(market):
    stale_artifact, stale_report = qualification_fixture()
    enable_learning(market)
    assert activate(market, stale_artifact, stale_report).status_code == 422
    with Session(market.engine) as db:
        epoch = learning.consent_source_version(db)
    artifact, report = qualification_fixture(epoch)
    assert activate(market, artifact, report).status_code == 200
    response = market.call(
        0, "PUT", "/candidates/me/learning-consent", {"enabled": False, "expected_version": 2}
    )
    assert response.status_code == 200, response.text
    assert market.call(2, "GET", "/internal/matching/model").json()["data"]["active"] is False
    assert activate(market, artifact, report).status_code == 409


def test_retirement_cannot_reset_the_forward_holdout_boundary(market):
    artifact, report = qualification_fixture()
    assert activate(market, artifact, report).status_code == 200
    response = market.call(
        2,
        "POST",
        "/internal/matching/model/retire",
        {
            "expected_active_model_id": artifact["model_id"],
            "reason": "Fabricated holdout boundary regression fixture",
        },
    )
    assert response.status_code == 200
    # A new digest can describe substantially overlapping old observations. It
    # cannot erase the chronology of the retired model's already used holdout.
    challenger, challenger_report = qualification_fixture(tag="changed-old-cohort-hash")
    rejected = activate(market, challenger, challenger_report)
    assert rejected.status_code == 422, rejected.text
    assert "previously registered" in rejected.json()["error"]["message"]


@pytest.mark.parametrize(
    "malformation",
    [
        "nested_selection",
        "nested_evaluation",
        "nested_clusters",
        "missing_overlap",
        "overlap",
        "class_count",
        "candidate_clusters",
        "organization_clusters",
        "non_improving_loss",
        "training_count",
        "naive_cutoff",
        "future_export",
        "missing_class_counts",
        "class_count_sum",
        "class_count_boolean",
        "training_class_shortage",
    ],
)
def test_model_qualification_rejects_malformed_or_insufficient_evidence(market, malformation):
    artifact, report = qualification_fixture()
    comparison = report["evaluation"]["test"]["paired_comparisons"]["fitted_compatibility"]
    if malformation == "nested_selection":
        artifact["provenance"]["selection"] = []
    elif malformation == "nested_evaluation":
        report["evaluation"] = []
    elif malformation == "nested_clusters":
        comparison["by_scope"] = []
    elif malformation == "missing_overlap":
        report["organization_overlap"] = {"train_test": 0}
    elif malformation == "overlap":
        report["organization_overlap"]["train_test"] = 1
    elif malformation == "class_count":
        report["evaluation"]["test"]["challenger"]["positives"] = 19
    elif malformation == "candidate_clusters":
        comparison["cluster_count"] = 19
    elif malformation == "organization_clusters":
        comparison["by_scope"]["organization_id"]["cluster_count"] = 19
    elif malformation == "non_improving_loss":
        comparison["log_loss_delta_95"][1] = 0
    elif malformation == "training_count":
        artifact["provenance"]["split"]["counts"]["train"] = 99
    elif malformation == "naive_cutoff":
        artifact["provenance"]["split"]["train_before"] = "2026-01-01T00:00:00"
    elif malformation == "future_export":
        artifact["source"]["exported_at"] = (utcnow() + timedelta(days=1)).isoformat()
    elif malformation == "missing_class_counts":
        artifact["provenance"]["split"].pop("class_counts")
    elif malformation == "class_count_sum":
        artifact["provenance"]["split"]["class_counts"]["train"]["negatives"] = 49
    elif malformation == "class_count_boolean":
        artifact["provenance"]["split"]["class_counts"]["train"]["positives"] = True
    elif malformation == "training_class_shortage":
        artifact["provenance"]["split"]["class_counts"]["train"] = {"positives": 19, "negatives": 81}
    synchronize(artifact, report)
    response = activate(market, artifact, report)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "MODEL_NOT_QUALIFIED"


def test_racing_qualified_model_activations_choose_one_incumbent(market):
    fixtures = [qualification_fixture(tag=f"concurrent-{index}") for index in range(2)]

    def promote(fixture):
        with Session(market.engine) as db:
            try:
                with db.begin():
                    learning.promote_model(db, market.actor(2), *fixture, None)
                return "OK"
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(promote, fixtures))
    assert outcomes.count("OK") == 1
    assert outcomes.count("MODEL_VERSION_CONFLICT") == 1
    with Session(market.engine) as db:
        assert (
            db.scalar(select(func.count()).select_from(MatchingModel).where(MatchingModel.status == "ACTIVE"))
            == 1
        )


@pytest.mark.parametrize("state", ["future", "stale", "corrupt"])
def test_runtime_models_fail_closed_to_deterministic_scoring(market, state):
    artifact, report = qualification_fixture()
    if state == "future":
        artifact["source"]["exported_at"] = (utcnow() + timedelta(days=1)).isoformat()
    elif state == "stale":
        artifact["source"]["exported_at"] = (utcnow() - timedelta(days=400)).isoformat()
    else:
        artifact["coefficients"] = []
    synchronize(artifact, report)
    with Session(market.engine) as db, db.begin():
        db.add(
            MatchingModel(
                model_key=artifact["model_id"],
                artifact=artifact,
                evaluation=report,
                activated_by=market.users[2].id,
            )
        )
        db.flush()
        model, reason = learning.current_scoring_model(db)
        assert model is None
        assert state.upper() in reason if state != "corrupt" else "INVALID" in reason


@pytest.mark.parametrize("interested", [False, True])
def test_consented_explicit_outcome_is_immutable_frozen_and_pseudonymized(market, interested):
    enable_learning(market)
    resolve(market, interested=interested)
    with Session(market.engine) as db, db.begin():
        observation = db.scalar(select(MatchingObservation))
        assert observation is not None
        frozen = deepcopy(observation.observation)
        assert frozen["policy_version"] == "directional-attention-flow-v1"
        assert frozen["features"]["preferred_skill_coverage"] is None
        db.get(Candidate, market.candidate.id).role_families = ["DESIGN"]
        cycle = db.get(PairCycle, observation.pair_cycle_id)
        learning.record_observation(db, market.actor(2), cycle)
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 1
        exported = learning.export_observations(db)
        assert len(exported["rows"]) == 1
        row = exported["rows"][0]
        assert row["features"] == frozen["features"]
        for name in ("cycle_id", "candidate_id", "vacancy_id", "organization_id"):
            assert len(row[name]) == 64
            assert row[name] != frozen[name]
        with pytest.raises(ValueError, match="Append-only"), db.begin_nested():
            observation.observation = {**frozen, "observed_at": utcnow().isoformat()}
            db.flush()


def test_opt_in_after_exposure_never_retroactively_authorizes_training(market):
    issued = market.call(2, "POST", "/internal/reconcile").json()["data"]["issued"][0]
    enable_learning(market)
    card = market.call(0, "GET", f"/decisions/{issued['decision_id']}").json()["data"]
    response = market.call(
        0,
        "POST",
        f"/decisions/{card['id']}/pass",
        {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
    )
    assert response.status_code == 200, response.text
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 0
        assert learning.export_observations(db)["rows"] == []


def test_revocation_and_new_opt_in_exclude_prior_resolutions(market):
    enable_learning(market)
    resolve(market)
    response = market.call(
        0, "PUT", "/candidates/me/learning-consent", {"enabled": False, "expected_version": 2}
    )
    assert response.status_code == 200
    with Session(market.engine) as db:
        assert learning.export_observations(db)["rows"] == []
    response = market.call(
        0, "PUT", "/candidates/me/learning-consent", {"enabled": True, "expected_version": 3}
    )
    assert response.status_code == 200
    with Session(market.engine) as db:
        assert learning.export_observations(db)["rows"] == []
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 1


@pytest.mark.parametrize(
    "malformation",
    ["missing_features", "list_features", "invalid_as_of", "invalid_native", "list_consent", "list_snapshot"],
)
def test_corrupt_frozen_learning_metadata_cannot_break_a_participant_decision(market, malformation):
    enable_learning(market)
    issued = market.call(2, "POST", "/internal/reconcile").json()["data"]["issued"][0]
    with Session(market.engine) as db, db.begin():
        exposure = db.scalar(select(Exposure))
        trace = deepcopy(exposure.score_trace)
        if malformation == "missing_features":
            trace.pop("features")
        elif malformation == "list_features":
            trace["features"] = []
        elif malformation == "invalid_as_of":
            trace["features"]["as_of"] = "invalid"
        elif malformation == "invalid_native":
            trace["learning_snapshot"]["employer_skills"] = True
        elif malformation == "list_consent":
            trace["learning_consent"] = []
        else:
            trace["learning_snapshot"] = []
        # Deliberately simulate a corrupt legacy database row. Normal ORM event
        # updates are prohibited and participant/API payloads cannot do this.
        db.execute(update(Exposure).where(Exposure.id == exposure.id).values(score_trace=trace))
    card = market.call(0, "GET", f"/decisions/{issued['decision_id']}").json()["data"]
    response = market.call(
        0,
        "POST",
        f"/decisions/{card['id']}/pass",
        {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
    )
    assert response.status_code == 200, response.text
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 0


def test_pending_and_expired_introductions_are_never_negative_training_examples(market):
    enable_learning(market)
    market.call(2, "POST", "/internal/reconcile")
    with Session(market.engine) as db, db.begin():
        assert learning.export_observations(db)["rows"] == []
        card = db.scalar(select(DecisionCard))
        card.expires_at = utcnow() - timedelta(hours=1)
        db.flush()
        from app.services import clearing

        clearing.expire_due(db, market.actor(2))
        cycle = db.get(PairCycle, card.pair_cycle_id)
        learning.record_observation(db, market.actor(2), cycle)
        assert learning.export_observations(db)["rows"] == []
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 0


def test_nonconsenting_participant_decision_does_not_wait_for_model_registry(market):
    issued = market.call(2, "POST", "/internal/reconcile").json()["data"]["issued"][0]
    card = market.call(0, "GET", f"/decisions/{issued['decision_id']}").json()["data"]
    with ThreadPoolExecutor(max_workers=1) as workers:
        with Session(market.engine) as registry_lock, registry_lock.begin():
            lock_scopes(registry_lock, learning.COORDINATION_SCOPE)
            future = workers.submit(
                market.call,
                0,
                "POST",
                f"/decisions/{card['id']}/pass",
                {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
            )
            try:
                response = future.result(timeout=5)
            finally:
                # Release before joining the worker even when the regression
                # assertion times out, so this test can fail without hanging.
                registry_lock.rollback()
    assert response.status_code == 200, response.text
