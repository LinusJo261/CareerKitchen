from uuid import uuid4

from app.db.models import DecisionCard, IdempotencyRecord, OrgMember
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_offline_synthetic_replay_persisted_no_live_cards(market):
    body = {
        "fictional_only": True,
        "state_version": "synthetic-test-v1",
        "vacancies": [
            {
                "vacancy_id": "synthetic-role",
                "role_version": 1,
                "shortlist_limit": 3,
                "models": [
                    {
                        "version": "stipulated-fixture-v1",
                        "conditional_independence_asserted": True,
                        "scenarios": [
                            {
                                "scenario_id": "common-cancellation",
                                "weight": 1,
                                "job_wide_failure": 0.005,
                                "assumption_version": "hypothetical-v1",
                                "candidates": [{"candidate_id": "synthetic-person", "success": 0.99}],
                            }
                        ],
                    }
                ],
            }
        ],
        "edges": [{"candidate_id": "synthetic-person", "vacancy_id": "synthetic-role", "routing_value": 1}],
    }
    assert market.call(0, "POST", "/internal/shadow/replay", body).status_code == 403
    result = market.call(2, "POST", "/internal/shadow/replay", body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["certification_state"] == "CANNOT_CERTIFY"
    details = market.call(2, "GET", "/internal/shadow/runs/" + result.json()["data"]["run_id"])
    assert details.status_code == 200, details.text
    assert details.json()["data"]["side_effect_count"] == 0
    plan = details.json()["data"]["diagnostics"]["plan"]
    assert plan["vacancies"][0]["modeled_threshold_pass"] is False
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0
    body["vacancies"][0]["models"][0]["scenarios"][0]["weight"] = 0.5
    assert market.call(2, "POST", "/internal/shadow/replay", body).status_code == 422


def test_multipart_retries_ignore_boundary_and_response_is_encrypted(market):
    from app.core.auth import mint_dev_token

    user = market.users[0]
    headers = {
        "Authorization": "Bearer " + mint_dev_token(user.id, email=user.verified_email),
        "Idempotency-Key": str(uuid4()),
    }
    for _ in range(2):
        response = market.client.post(
            "/v1/candidates/me/resume",
            files={"file": ("resume.txt", b"Fictional candidate resume. Engineering work.", "text/plain")},
            headers=headers,
        )
        assert response.status_code == 200, response.text
    assert response.headers["Idempotency-Replayed"] == "true"
    with Session(market.engine) as db:
        record = db.scalar(select(IdempotencyRecord))
        assert "Fictional" not in record.response_json
        assert not record.response_json.startswith("{")


def test_upload_limits_and_private_proxy(market):
    from app.core.auth import mint_dev_token

    headers = {
        "Authorization": "Bearer " + mint_dev_token(market.users[0].id, email=market.users[0].verified_email),
        "Idempotency-Key": str(uuid4()),
    }
    result = market.client.post(
        "/v1/candidates/me/resume",
        files={"file": ("malicious.txt", b"binary\x00bytes", "text/plain")},
        headers=headers,
    )
    assert result.status_code == 422
    result = market.call(0, "POST", "/candidates/me/pause", {"expected_version": 1, "unused": "x" * 100000})
    assert result.status_code == 413


def test_cached_write_response_rechecks_revoked_tenant_authority(market):
    path = f"/vacancies/{market.vacancy.id}/close"
    payload = {"expected_version": market.vacancy.version}
    first = market.call(1, "POST", path, payload, key="revoke-access-replay")
    assert first.status_code == 200, first.text
    with Session(market.engine) as db:
        for member in db.scalars(select(OrgMember).where(OrgMember.user_id == market.users[1].id)):
            member.status = "REVOKED"
        db.commit()
    result = market.call(1, "POST", path, payload, key="revoke-access-replay")
    assert result.status_code == 403, result.text


def test_deletion_request_immediately_revokes_employer_document_access(market, monkeypatch, tmp_path):
    from datetime import timedelta

    from app.core.auth import mint_dev_token
    from app.core.settings import get_settings
    from app.services.common import utcnow

    monkeypatch.setattr(get_settings(), "local_storage_dir", tmp_path)
    claim = market.call(
        0,
        "POST",
        "/evidence/claims",
        {
            "expected_version": 1,
            "claim_type": "PROJECT",
            "requirement_keys": ["python"],
            "statement": "Fictional project demonstration evidence",
            "job_related_purpose": "Fictional engineering role project requirement",
        },
    )
    assert claim.status_code == 201, claim.text
    claim_id = claim.json()["data"]["id"]
    headers = {
        "Authorization": "Bearer " + mint_dev_token(market.users[0].id, email=market.users[0].verified_email),
        "Idempotency-Key": str(uuid4()),
    }
    attached = market.client.post(
        f"/v1/evidence/claims/{claim_id}/document",
        data={"expected_version": "1"},
        files={"file": ("project.txt", b"Fictional project evidence, no real credential.", "text/plain")},
        headers=headers,
    )
    assert attached.status_code == 201, attached.text
    verified = market.call(
        2,
        "POST",
        f"/evidence/claims/{claim_id}/verify",
        {
            "expected_version": 2,
            "decision": "VERIFIED",
            "method": "INDEPENDENT_DOCUMENT_REVIEW",
            "issuer": "Fictional fixture issuer",
            "source_reference": "Independent fictional test review source",
            "expires_at": (utcnow() + timedelta(days=7)).isoformat(),
            "affirm_independent_check": True,
        },
    )
    assert verified.status_code == 200, verified.text
    granted = market.call(
        0,
        "POST",
        "/consents/evidence",
        {
            "expected_version": market.vacancy.version,
            "vacancy_id": market.vacancy.id,
            "terms_hash": market.vacancy.terms_hash,
            "claim_id": claim_id,
            "claim_expected_version": 3,
            "org_id": market.org.id,
            "kind": "DISCLOSE_DOCUMENT",
            "consent_text": "Explicit fictional employer document disclosure consent",
            "expires_at": (utcnow() + timedelta(days=1)).isoformat(),
            "checkbox_confirmed": True,
        },
    )
    assert granted.status_code == 201, granted.text
    path = f"/evidence/claims/{claim_id}/document"
    assert market.call(1, "GET", path, params={"vacancy_id": market.vacancy.id}).status_code == 200
    deletion = market.call(0, "POST", "/privacy/delete")
    assert deletion.status_code == 202, deletion.text
    assert market.call(1, "GET", path, params={"vacancy_id": market.vacancy.id}).status_code == 403
    assert market.call(0, "GET", "/sessions/me").status_code == 403


def test_candidate_cannot_supply_employer_opt_in_for_the_same_pair(market):
    with Session(market.engine) as db:
        db.add(OrgMember(org_id=market.org.id, user_id=market.users[0].id, role="RECRUITER"))
        db.commit()
    result = market.call(
        2,
        "POST",
        "/internal/decisions/issue",
        {
            "candidate_id": market.candidate.id,
            "vacancy_id": market.vacancy.id,
            "role_version": market.vacancy.version,
            "first_mover": "CANDIDATE",
            "human_review_reason": "Fictional test of party separation",
        },
    )
    assert result.status_code == 409, result.text
    assert "PARTICIPANT_ROLE_CONFLICT" in result.json()["error"]["message"]
    with Session(market.engine) as db:
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0


def test_replan_api_operation_is_consumed_as_shadow_only(market, monkeypatch):
    from app.core.settings import get_settings
    from app.db.models import InboxConsumption, OutboxEvent, ShadowRun
    from app.workers import runner
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(get_settings(), "feature_mode", "BASELINE")
    path = f"/vacancies/{market.vacancy.id}/shortlist/replan"
    assert market.call(1, "POST", path, {"expected_version": 1}).status_code == 409
    monkeypatch.setattr(get_settings(), "feature_mode", "SHADOW")
    queued = market.call(1, "POST", path, {"expected_version": 1})
    assert queued.status_code == 202, queued.text
    operation_id = queued.json()["data"]["operation_id"]
    with Session(market.engine) as db:
        assert db.get(OutboxEvent, operation_id).kind == "shortlist.replan_requested"
    factory = sessionmaker(bind=market.engine, expire_on_commit=False, autoflush=False)
    assert runner.process_one(factory, shadow=True) == (True, True)
    with Session(market.engine) as db:
        assert db.get(OutboxEvent, operation_id).dispatched_at is not None
        assert db.get(InboxConsumption, (runner.CONSUMER, operation_id))
        assert db.scalar(select(ShadowRun).where(ShadowRun.event_id == operation_id)).side_effect_count == 0
        assert db.scalar(select(func.count()).select_from(DecisionCard)) == 0
