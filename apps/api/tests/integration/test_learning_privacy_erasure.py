"""Privacy deletion revokes learning immediately; every seeded outcome is fictional."""

from app.db.models import (
    AuditEvent,
    Candidate,
    MatchingModel,
    MatchingObservation,
    Organization,
    OutboxEvent,
    PairCycle,
    User,
)
from app.services import clearing, matching_learning
from app.services.common import Actor, utcnow
from app.workers.privacy import erase_local_owner_data, owner_export
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def seed_learning_resolution_and_active_fixture(market):
    """Capture one fictional explicit pass, then install a retirement-only fixture.

    The deliberately incomplete model bypasses promotion exclusively to verify
    privacy retirement. It supplies no real performance or activation evidence.
    """
    with Session(market.engine) as db, db.begin():
        candidate = db.get(Candidate, market.candidate.id)
        org = db.get(Organization, market.org.id)
        matching_learning.set_learning_consent(db, market.actor(0), candidate, True, candidate.version)
        matching_learning.set_learning_consent(db, market.actor(1), org, True, org.version)
        issued = clearing.reconcile(db, market.actor(2), [market.vacancy.id])
        assert len(issued) == 1
        cycle = db.scalar(select(PairCycle))
        cycle_id = cycle.id
    # Use the actual decision API so capture occurs in the answer transaction.
    listed = market.call(0, "GET", "/candidates/me/decisions")
    assert listed.status_code == 200, listed.text
    card = listed.json()["data"][0]
    answered = market.call(
        0,
        "POST",
        f"/decisions/{card['id']}/pass",
        {"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
    )
    assert answered.status_code == 200, answered.text
    with Session(market.engine) as db, db.begin():
        assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 1
        model = MatchingModel(
            model_key="f" * 64,
            status="ACTIVE",
            activated_by=market.users[2].id,
            artifact={"fictional_data": True, "fixture_purpose": "privacy retirement only"},
            evaluation={"fictional_fixture": True},
        )
        db.add(model)
        db.flush()
        return model.id, cycle_id


def assert_learning_erasure_barrier(db, market, model_id):
    candidate = db.get(Candidate, market.candidate.id)
    assert candidate.matching_learning_opt_in is False
    assert candidate.matching_learning_consent_version == 3
    assert db.get(MatchingModel, model_id).status == "RETIRED"
    assert matching_learning.active_model_info(db)["active"] is False
    exported = matching_learning.export_observations(db)
    assert exported["rows"] == []
    assert exported["diagnostics"]["excluded_current_consent_or_account"] == 1
    assert db.scalar(select(func.count()).select_from(MatchingObservation)) == 1
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "matching.model_retired")) is not None
    assert db.scalar(select(OutboxEvent).where(OutboxEvent.kind == "matching.model_retired")) is not None


def test_privacy_delete_immediately_retires_model_and_excludes_frozen_contribution(market):
    model_id, _ = seed_learning_resolution_and_active_fixture(market)
    response = market.call(0, "POST", "/privacy/delete", key="fictional-learning-privacy-delete")
    assert response.status_code == 202, response.text
    replay = market.call(0, "POST", "/privacy/delete", key="fictional-learning-privacy-delete")
    # Deactivated accounts cannot use historical mutation replays to restore access.
    assert replay.status_code == 403
    with Session(market.engine) as db:
        assert_learning_erasure_barrier(db, market, model_id)
        candidate = db.get(Candidate, market.candidate.id)
        assert candidate.state == "DEACTIVATED"
        assert candidate.version == 4  # Enable, revoke and account deactivation each advance version.
        assert db.get(User, market.users[0].id).status == "DEACTIVATED"


def test_worker_direct_erasure_revokes_learning_even_without_prior_delete_api(market):
    model_id, _ = seed_learning_resolution_and_active_fixture(market)
    worker = Actor(market.users[2].id, utcnow(), ("SYSTEM_WORKER",))
    with Session(market.engine) as db, db.begin():
        erase_local_owner_data(db, worker, db.get(User, market.users[0].id))
    with Session(market.engine) as db:
        assert_learning_erasure_barrier(db, market, model_id)
        assert db.get(Candidate, market.candidate.id).headline == "Deleted account"


def test_owner_export_includes_only_own_learning_consent_state(market):
    with Session(market.engine) as db:
        result = owner_export(db, db.get(User, market.users[0].id))
    assert result["candidate"]["matching_learning_opt_in"] is False
    assert result["candidate"]["matching_learning_consent_version"] == 1
    assert "matching_models" not in result
