"""Account lifecycle changes must invalidate cached candidate versions."""

from app.db.models import AuditEvent, Candidate, OutboxEvent, User
from sqlalchemy import select
from sqlalchemy.orm import Session


def assert_event(db, action, entity_id, version):
    assert (
        db.scalar(select(AuditEvent).where(AuditEvent.action == action, AuditEvent.entity_id == entity_id))
        is not None
    )
    event = db.scalar(
        select(OutboxEvent).where(OutboxEvent.kind == action, OutboxEvent.aggregate_id == entity_id)
    )
    assert event is not None and event.payload["version"] == version


def test_suspension_versions_candidate_and_rejects_stale_activation(market):
    path = f"/admin/users/{market.users[0].id}/status"
    response = market.call(
        2,
        "POST",
        path,
        {"expected_version": 1, "status": "SUSPENDED", "reason": "Fictional moderation test decision."},
    )
    assert response.status_code == 200, response.text
    with Session(market.engine) as db:
        candidate = db.get(Candidate, market.candidate.id)
        assert candidate.state == "PAUSED" and candidate.version == 2
        assert_event(db, "candidate.paused", candidate.id, 2)

    restored = market.call(
        2,
        "POST",
        path,
        {"expected_version": 2, "status": "ACTIVE", "reason": "Fictional moderation review completed."},
    )
    assert restored.status_code == 200, restored.text
    stale = market.call(0, "POST", "/candidates/me/activate", {"expected_version": 1})
    assert stale.status_code == 412, stale.text
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_deletion_immediately_versions_and_audits_account_and_candidate(market):
    response = market.call(0, "POST", "/privacy/delete")
    assert response.status_code == 202, response.text
    with Session(market.engine) as db:
        candidate = db.get(Candidate, market.candidate.id)
        user = db.get(User, market.users[0].id)
        assert candidate.state == "DEACTIVATED" and candidate.version == 2
        assert user.status == "DEACTIVATED" and user.version == 2
        assert_event(db, "candidate.deactivated", candidate.id, 2)
        assert_event(db, "account.deactivated", user.id, 2)
