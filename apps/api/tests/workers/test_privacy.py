import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.core.auth import VerifiedIdentity
from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.core.settings import get_settings
from app.db.models import (
    Candidate,
    CandidateSkill,
    Message,
    MutualMatch,
    Offer,
    OutboxEvent,
    PairCycle,
    PrivacyRequest,
    Skill,
    User,
    Vacancy,
)
from app.db.pact_models import EvidenceClaim, EvidenceGrant, ExclusiveReservation, TermConsent
from app.integrations.storage import store_resume
from app.services.common import Actor, digest, emit, utcnow
from app.workers import runner
from sqlalchemy import func, select
from starlette.requests import Request

from app.api import deps


def request_operation(m, kind):
    with m.factory.begin() as db:
        request = PrivacyRequest(user_id=m.candidate_user_id, kind=kind)
        db.add(request)
        emit(db, Actor(m.candidate_user_id, utcnow()), f"privacy.{kind.lower()}_requested", request)
        return request.id


def seed_private_records(m):
    with m.factory.begin() as db:
        user = db.get(User, m.candidate_user_id)
        user.issuer, user.subject = get_settings().jwt_issuer, user.id
        candidate = db.get(Candidate, m.candidate_id)
        candidate.display_name = "Owner private display name"
        candidate.professional_links = {
            "linkedin": "https://www.linkedin.com/in/fictional-private-owner",
            "portfolio": "https://fictional-private-owner.example.invalid/portfolio",
        }
        candidate.summary = "Owner private summary"
        candidate.experiences = [{"title": "Owner private work history"}]
        candidate.education = [{"institution": "Owner private education"}]
        candidate.compensation_floor_cipher = encrypt("75000")
        skill = Skill(name="Fictional private skill")
        db.add(skill)
        db.flush()
        db.add(CandidateSkill(candidate_id=candidate.id, skill_id=skill.id))
        pair = PairCycle(
            candidate_id=candidate.id,
            vacancy_id=m.vacancy_id,
            role_version=1,
            first_mover="CANDIDATE",
            state="MUTUAL_MATCH",
            candidate_interested_at=utcnow(),
            employer_interested_at=utcnow(),
        )
        db.add(pair)
        db.flush()
        match = MutualMatch(pair_cycle_id=pair.id)
        db.add(match)
        db.flush()
        db.add_all(
            [
                Message(
                    match_id=match.id,
                    sender_user_id=m.candidate_user_id,
                    body="Owner authored private message",
                ),
                Message(
                    match_id=match.id, sender_user_id=m.owner_id, body="Counterpart confidential message"
                ),
            ]
        )
        db.add(
            Offer(
                pair_cycle_id=pair.id,
                issued_by=m.owner_id,
                terms_cipher=encrypt("Counterpart confidential offer terms"),
                expires_at=utcnow() + timedelta(days=1),
                start_at=utcnow() + timedelta(days=10),
            )
        )
        claim = EvidenceClaim(
            candidate_id=candidate.id,
            claim_type="LICENSE",
            requirement_keys=["license"],
            statement_hash=digest("Owner evidence statement"),
            status="VERIFIED",
            issuer="Fictional issuer",
            verified_at=utcnow(),
            verifier_user_id=m.outsider_id,
            verification_method="ISSUER_CONTACT",
            source_reference_hash=digest("Fictional source"),
            expires_at=utcnow() + timedelta(days=1),
        )
        db.add(claim)
        db.flush()
        db.add_all(
            [
                EvidenceGrant(
                    candidate_id=candidate.id,
                    claim_id=claim.id,
                    org_id=db.get(Vacancy, m.vacancy_id).org_id,
                    vacancy_id=m.vacancy_id,
                    role_version=1,
                    terms_hash="terms",
                    kind="DISCLOSE_SUMMARY",
                    consent_text_hash="consent",
                    expires_at=utcnow() + timedelta(days=1),
                ),
                TermConsent(
                    candidate_id=candidate.id,
                    vacancy_id=m.vacancy_id,
                    role_version=1,
                    terms_hash="terms",
                    scope="PRELIMINARY_INTEREST",
                    expires_at=utcnow() + timedelta(days=1),
                ),
                ExclusiveReservation(
                    candidate_id=candidate.id,
                    vacancy_id=m.vacancy_id,
                    role_version=1,
                    terms_hash="terms",
                    consent_text_hash="consent",
                    expires_at=utcnow() + timedelta(hours=1),
                ),
            ]
        )
        return match.id


def test_export_is_encrypted_owner_scoped_and_contains_no_counterpart_content(worker_market):
    m = worker_market
    seed_private_records(m)
    request_id = request_operation(m, "EXPORT")
    assert runner.process_one(m.factory, shadow=False) == (True, True)
    with m.factory() as db:
        request = db.get(PrivacyRequest, request_id)
        assert request.status == "COMPLETE"
        assert "Owner private summary" not in request.result_cipher
        result = json.loads(decrypt(request.result_cipher))
        assert result["candidate"]["display_name"] == "Owner private display name"
        assert result["candidate"]["professional_links"] == {
            "linkedin": "https://www.linkedin.com/in/fictional-private-owner",
            "portfolio": "https://fictional-private-owner.example.invalid/portfolio",
        }
        assert result["candidate"]["private_compensation_floor"] == "75000"
        assert result["candidate"]["experiences"][0]["title"] == "Owner private work history"
        assert len(result["skills"]) == len(result["evidence_claims"]) == len(result["evidence_grants"]) == 1
        assert result["authored_messages"][0]["body"] == "Owner authored private message"
        serialized = json.dumps(result)
        assert "Counterpart confidential" not in serialized
        assert "token_cipher" not in serialized and "source_reference_hash" not in serialized
        assert all(
            "Owner private summary" not in json.dumps(event.payload)
            for event in db.scalars(select(OutboxEvent))
        )


def test_erasure_scrubs_owner_data_revokes_scopes_preserves_counterpart_and_blocks_fresh_login(
    worker_market, monkeypatch, tmp_path
):
    m = worker_market
    seed_private_records(m)
    settings = get_settings()
    monkeypatch.setattr(settings, "local_storage_dir", tmp_path)
    monkeypatch.setattr(settings, "storage_backend", "local")
    stored = store_resume(b"Owner resume to delete", "text/plain", m.candidate_user_id)
    with m.factory.begin() as db:
        db.get(Candidate, m.candidate_id).resume_object_ref = stored.object_key
    request_id = request_operation(m, "DELETE")
    assert runner.process_one(m.factory, shadow=False) == (True, True)
    with m.factory() as db:
        request = db.get(PrivacyRequest, request_id)
        assert request.status == "NEEDS_PROVIDER_REVIEW"
        candidate = db.get(Candidate, m.candidate_id)
        assert candidate.headline == "Deleted account" and candidate.summary == ""
        assert candidate.display_name == "" and candidate.professional_links == {}
        assert candidate.experiences == candidate.education == []
        assert candidate.compensation_floor_cipher is candidate.resume_object_ref is None
        assert db.scalar(select(func.count()).select_from(CandidateSkill)) == 0
        assert db.scalar(select(EvidenceClaim)).status == "REVOKED"
        assert db.scalar(select(EvidenceGrant)).revoked_at is not None
        assert db.scalar(select(TermConsent)).revoked_at is not None
        assert db.scalar(select(ExclusiveReservation)).status == "RELEASED"
        own = db.scalar(select(Message).where(Message.sender_user_id == m.candidate_user_id))
        counterpart = db.scalar(select(Message).where(Message.sender_user_id == m.owner_id))
        assert own.body == "[Deleted by author]"
        assert counterpart.body == "Counterpart confidential message"
        user = db.get(User, m.candidate_user_id)
        assert user.status == "DEACTIVATED" and user.verified_email == ""
        identity = VerifiedIdentity(
            UUID(user.subject),
            user.issuer,
            UUID("4c4421a5-f6b0-4cf8-a6d7-3fc567d3c803"),
            "fictional@example.test",
            True,
            utcnow(),
        )
        monkeypatch.setattr(deps, "verify_access_token", lambda *args, **kwargs: identity)
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", b"Bearer test")],
                "client": ("testclient", 1234),
                "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
            }
        )
        request.state.db, request.state.request_id = db, "test"
        with pytest.raises(AppError) as raised:
            deps.actor_dep(request)
        assert raised.value.code == "ACCOUNT_INACTIVE"
    assert not (tmp_path / stored.object_key).exists()


def test_blob_ownership_failure_retries_and_does_not_claim_erased(worker_market, monkeypatch):
    m = worker_market
    with m.factory.begin() as db:
        db.get(
            Candidate, m.candidate_id
        ).resume_object_ref = f"{m.outsider_id}/4c4421a5-f6b0-4cf8-a6d7-3fc567d3c803.enc"
    request_id = request_operation(m, "DELETE")
    assert runner.process_one(m.factory, shadow=False) == (True, False)
    with m.factory() as db:
        assert db.get(PrivacyRequest, request_id).status == "QUEUED"
        assert db.get(User, m.candidate_user_id).status == "ACTIVE"


def test_expired_dependencies_emit_once_without_fabricating_revocation(worker_market):
    m = worker_market
    seed_private_records(m)
    with m.factory.begin() as db:
        for model in (EvidenceClaim, EvidenceGrant, TermConsent, ExclusiveReservation):
            db.scalar(select(model)).expires_at = utcnow() - timedelta(seconds=1)
    runner.maintenance(m.factory)
    runner.maintenance(m.factory)
    with m.factory() as db:
        assert db.scalar(select(EvidenceGrant)).revoked_at is None
        assert db.scalar(select(TermConsent)).revoked_at is None
        assert db.scalar(select(ExclusiveReservation)).status == "EXPIRED"
        assert (
            len(list(db.scalars(select(OutboxEvent).where(OutboxEvent.kind == "candidate.consent_expired"))))
            == 2
        )
        assert (
            len(list(db.scalars(select(OutboxEvent).where(OutboxEvent.kind == "candidate.evidence_expired"))))
            == 1
        )


@pytest.mark.parametrize("model", [EvidenceClaim, EvidenceGrant, TermConsent])
def test_expiration_rechecks_concurrent_revocation_after_acquiring_scope_lock(
    worker_market, monkeypatch, model
):
    m = worker_market
    seed_private_records(m)
    with m.factory.begin() as db:
        row = db.scalar(select(model))
        row.expires_at = utcnow() - timedelta(seconds=1)
        row_id = row.id
    original_lock = runner.lock_scopes
    revoked = False

    def revoke_before_lock(db, *keys):
        nonlocal revoked
        if not revoked and f"candidate:{m.candidate_id}" in keys:
            with m.factory.begin() as concurrent:
                row = concurrent.get(model, row_id)
                row.revoked_at = utcnow()
                row.version += 1
            revoked = True
        original_lock(db, *keys)

    monkeypatch.setattr(runner, "lock_scopes", revoke_before_lock)
    with m.factory.begin() as db:
        actor = runner.worker_actor(db)
        assert runner.expire_pact_dependencies(db, actor) == 0
    assert revoked
    with m.factory() as db:
        assert db.get(model, row_id).revoked_at is not None
        assert not db.scalar(
            select(OutboxEvent.id).where(
                OutboxEvent.aggregate_id == row_id,
                OutboxEvent.kind.in_({"candidate.consent_expired", "candidate.evidence_expired"}),
            )
        )


def test_orphan_cleanup_preserves_referenced_and_recent_blobs_and_requires_retention(
    worker_market, monkeypatch, tmp_path
):
    import os

    from app.workers.storage_cleanup import cleanup_local_orphans

    m = worker_market
    settings = get_settings()
    monkeypatch.setattr(settings, "local_storage_dir", tmp_path)
    monkeypatch.setattr(settings, "storage_backend", "local")
    referenced = store_resume(b"Referenced private resume", "text/plain", m.candidate_user_id)
    orphan = store_resume(b"Old unreferenced upload", "text/plain", m.candidate_user_id)
    recent = store_resume(b"New in-flight upload", "text/plain", m.candidate_user_id)
    old = (utcnow() - timedelta(days=10)).timestamp()
    for stored in (referenced, orphan):
        os.utime(tmp_path / stored.object_key, (old, old))
    with m.factory.begin() as db:
        db.get(Candidate, m.candidate_id).resume_object_ref = referenced.object_key
        db.flush()
        dry = cleanup_local_orphans(db)
        assert dry["eligible"] == 1 and dry["deleted"] == 0
        deleted = cleanup_local_orphans(db, dry_run=False)
        assert deleted["deleted"] == 1
        with pytest.raises(ValueError):
            cleanup_local_orphans(db, retention_days=0)
    assert (tmp_path / referenced.object_key).exists()
    assert (tmp_path / recent.object_key).exists()
    assert not (tmp_path / orphan.object_key).exists()
